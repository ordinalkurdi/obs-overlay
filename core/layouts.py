"""Widget layout presets, snapping and default arrangement. Pure logic (no Qt) so it can be unit-tested.

Data model (stored in settings.json next to everything else):
    cfg["layout_presets"] = [{"id", "name", "created", "updated", "layout": {"widgets": [...]}}]
    cfg["active_preset"]  = id of the preset last loaded / saved ("" = none)

Preset metadata (id, name, timestamps) is kept apart from the layout it holds, so renaming never touches a layout
and overwriting never touches the name. The live layout always lives in cfg["widgets"]; a preset is only ever
written when the user explicitly saves or overwrites it.
"""
from __future__ import annotations
import copy
import time
import uuid

# Everything that makes up the look and arrangement of one widget. Identity (id, kind) is included so that loading a
# preset can tell which docks to keep, which to create and which to remove.
LAYOUT_KEYS = ("id", "kind", "name", "x", "y", "w", "h", "opacity", "pinned", "click_through", "visible",
               "metrics", "url", "zoom", "transparent")
MAX_NAME = 40
MAX_PRESETS = 50


# ---------------------------------------------------------------------------------------------------------------------
# layouts
# ---------------------------------------------------------------------------------------------------------------------
def snapshot(widgets: list[dict]) -> dict:
    """Deep copy of the layout-relevant part of the live widgets. (The global 'show floating widgets' switch is a
    separate on/off setting, not part of a layout.)"""
    return {"widgets": [{k: copy.deepcopy(w[k]) for k in LAYOUT_KEYS if k in w} for w in widgets]}


def sanitize_layout(raw) -> dict | None:
    """Validates a stored layout; returns a clean copy or None when it is unusable (corrupt file, hand edit)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("widgets"), list):
        return None
    out, seen = [], set()
    for w in raw["widgets"]:
        if not isinstance(w, dict) or not isinstance(w.get("id"), str) or not isinstance(w.get("kind"), str) or w["id"] in seen:
            continue
        try:
            clean = {k: copy.deepcopy(w[k]) for k in LAYOUT_KEYS if k in w}
            for k in ("x", "y"): clean[k] = int(clean.get(k, 60))
            for k in ("w", "h"): clean[k] = max(40, int(clean.get(k, 200)))
            clean["opacity"] = max(0.2, min(1.0, float(clean.get("opacity", 0.9))))
            for k in ("pinned", "click_through", "visible"): clean[k] = bool(clean.get(k, k == "visible"))
            clean["metrics"] = [str(m) for m in clean.get("metrics", [])] if isinstance(clean.get("metrics", []), list) else []
            if clean["kind"] == "web" and not (isinstance(clean.get("url"), str) and clean["url"].lower().startswith(("http://", "https://"))):
                continue                                              # a web dock without a usable address cannot be restored
        except (TypeError, ValueError):
            continue
        seen.add(w["id"]); out.append(clean)
    return {"widgets": out}


def layouts_equal(a: dict | None, b: dict | None) -> bool:
    """True when two layouts describe the same arrangement (order of widgets is irrelevant, id decides)."""
    if a is None or b is None:
        return a is b
    key = lambda lay: {w["id"]: {k: w.get(k) for k in LAYOUT_KEYS} for w in lay["widgets"]}
    return key(a) == key(b)


def default_positions(sizes: list[tuple[int, int]], area: tuple[int, int, int, int], gap: int = 12) -> list[tuple[int, int]]:
    """Default arrangement: widgets are stacked down the right edge of `area` (x, y, w, h), starting a new column to the
    left whenever the next one would not fit. Returns one (x, y) per size, in the same order."""
    ax, ay, aw, ah = area
    pos, col_x, y, col_w = [], ax + aw - gap, ay + gap, 0
    for w, h in sizes:
        if y > ay + gap and y + h > ay + ah - gap:           # does not fit below: next column to the left
            col_x -= col_w + gap; y = ay + gap; col_w = 0
        col_w = max(col_w, w)
        pos.append((max(ax, col_x - w), y))                  # right-aligned inside the column
        y += h + gap
    return pos


# ---------------------------------------------------------------------------------------------------------------------
# snapping (drop indicators while dragging)
# ---------------------------------------------------------------------------------------------------------------------
def snap_rect(rect: tuple[int, int, int, int], others: list[tuple[int, int, int, int]],
              bounds: tuple[int, int, int, int], threshold: int = 10, gap: int = 8):
    """Snap a dragged rect (x, y, w, h) to the screen edges / centre and to the edges of other widgets.

    Returns (dx, dy, guides): the correction to apply, and guide lines [('v', x) | ('h', y)] to draw as drop
    indicators. Each axis snaps to the single closest candidate within `threshold`."""
    x, y, w, h = rect
    bx, by, bw, bh = bounds
    xs = [(bx, bx), (bx + bw - w, bx + bw), (bx + (bw - w) // 2, bx + bw // 2)]          # (new x, guide line)
    ys = [(by, by), (by + bh - h, by + bh), (by + (bh - h) // 2, by + bh // 2)]
    for ox, oy, ow, oh in others:
        xs += [(ox, ox), (ox + ow - w, ox + ow), (ox + ow + gap, ox + ow), (ox - w - gap, ox)]      # align / sit beside
        ys += [(oy, oy), (oy + oh - h, oy + oh), (oy + oh + gap, oy + oh), (oy - h - gap, oy)]

    def best(cands, cur):
        c = min(cands, key=lambda t: abs(t[0] - cur))
        return c if abs(c[0] - cur) <= threshold else None

    bxm, bym = best(xs, x), best(ys, y)
    dx = bxm[0] - x if bxm else 0
    dy = bym[0] - y if bym else 0
    guides = ([("v", bxm[1])] if bxm else []) + ([("h", bym[1])] if bym else [])
    return dx, dy, guides


def clamp_to(rect: tuple[int, int, int, int], bounds: tuple[int, int, int, int], keep: int = 60) -> tuple[int, int]:
    """Keeps at least `keep` px of a widget inside `bounds` so it can never be lost off-screen."""
    x, y, w, h = rect
    bx, by, bw, bh = bounds
    return max(bx - w + keep, min(x, bx + bw - keep)), max(by, min(y, by + bh - keep))


# ---------------------------------------------------------------------------------------------------------------------
# presets
# ---------------------------------------------------------------------------------------------------------------------
def normalize_name(name: str) -> str:
    return " ".join((name or "").split())


class PresetError(ValueError):
    """User-facing message (shown inline in the name dialog)."""


class PresetStore:
    """CRUD for presets on top of a settings object (anything with ['layout_presets'], ['active_preset'] and .save()).

    All mutating methods persist immediately, so presets survive a restart without any extra step."""

    def __init__(self, cfg):
        self.cfg = cfg
        self._sanitize()

    # ---- loading / sanitising --------------------------------------------------
    def _sanitize(self):
        clean, ids, names = [], set(), set()
        raw = self.cfg["layout_presets"] if isinstance(self.cfg["layout_presets"], list) else []
        for p in raw:
            if not isinstance(p, dict) or not isinstance(p.get("id"), str) or p["id"] in ids:
                continue
            layout = sanitize_layout(p.get("layout"))
            name = normalize_name(str(p.get("name", "")))[:MAX_NAME]
            if layout is None or not name:
                continue
            base, n = name, 2
            while name.lower() in names:                                  # repair duplicates from hand-edited files
                suffix = f" ({n})"; name = base[:MAX_NAME - len(suffix)] + suffix; n += 1
            ids.add(p["id"]); names.add(name.lower())
            clean.append({"id": p["id"], "name": name, "created": float(p.get("created", 0) or 0),
                          "updated": float(p.get("updated", 0) or 0), "layout": layout})
        self.cfg["layout_presets"] = clean
        if self.cfg["active_preset"] not in ids: self.cfg["active_preset"] = ""

    # ---- queries ---------------------------------------------------------------
    @property
    def presets(self) -> list[dict]:
        return self.cfg["layout_presets"]

    def get(self, pid: str) -> dict | None:
        return next((p for p in self.presets if p["id"] == pid), None)

    @property
    def active(self) -> dict | None:
        return self.get(self.cfg["active_preset"])

    def validate_name(self, name: str, exclude_id: str | None = None) -> str:
        """Returns the cleaned name or raises PresetError. Names are unique ignoring case and surrounding spaces."""
        n = normalize_name(name)
        if not n: raise PresetError("Enter a name for the preset.")
        if len(n) > MAX_NAME: raise PresetError(f"Use at most {MAX_NAME} characters.")
        if any(p["name"].lower() == n.lower() and p["id"] != exclude_id for p in self.presets):
            raise PresetError("A preset with this name already exists.")
        return n

    def is_modified(self, current: dict) -> bool:
        """True when the live layout differs from the active preset (so the UI can show 'Modified')."""
        a = self.active
        return bool(a) and not layouts_equal(a["layout"], current)

    # ---- mutations -------------------------------------------------------------
    def create(self, name: str, layout: dict) -> dict:
        n = self.validate_name(name)
        if len(self.presets) >= MAX_PRESETS: raise PresetError(f"You can keep at most {MAX_PRESETS} presets.")
        now = time.time()
        p = {"id": uuid.uuid4().hex[:10], "name": n, "created": now, "updated": now, "layout": copy.deepcopy(layout)}
        self.presets.append(p); self.cfg["active_preset"] = p["id"]; self.cfg.save()
        return p

    def rename(self, pid: str, name: str) -> dict:
        p = self.get(pid)
        if not p: raise PresetError("This preset no longer exists.")
        p["name"] = self.validate_name(name, exclude_id=pid)          # the layout is not touched
        self.cfg.save()
        return p

    def overwrite(self, pid: str, layout: dict) -> dict:
        p = self.get(pid)
        if not p: raise PresetError("This preset no longer exists.")
        p["layout"] = copy.deepcopy(layout); p["updated"] = time.time(); self.cfg["active_preset"] = pid; self.cfg.save()
        return p

    def delete(self, pid: str):
        self.cfg["layout_presets"] = [p for p in self.presets if p["id"] != pid]
        if self.cfg["active_preset"] == pid: self.cfg["active_preset"] = ""
        self.cfg.save()

    def set_active(self, pid: str):
        if self.get(pid) is None: raise PresetError("This preset no longer exists.")
        self.cfg["active_preset"] = pid; self.cfg.save()

    def clear_active(self):
        if self.cfg["active_preset"]: self.cfg["active_preset"] = ""; self.cfg.save()
