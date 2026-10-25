"""Settings persistence. The OBS password is stored only in the OS credential store (keyring)."""
from __future__ import annotations
import json, os, sys, copy
from pathlib import Path

APP = "ObsOverlay"


def data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / APP
    d.mkdir(parents=True, exist_ok=True)
    return d


HOTKEY_LABELS = {
    "toggle_overlay": "Show / hide overlay",
    "record": "Start / stop recording",
    "replay_toggle": "Toggle Instant Replay (replay buffer)",
    "replay_save": "Save replay",
    "screenshot": "Screenshot (OBS scene)",
    "mic_mute": "Toggle microphone mute",
    "desktop_mute": "Toggle desktop audio mute",
    "stats": "Show / hide floating widgets",
    "widgets_click": "Toggle click-through for all widgets",
}

DEFAULTS: dict = {
    "mode": "obs",                 # "obs" | "demo"
    "host": "localhost",
    "port": 4455,
    "timeout": 5,
    "auto_reconnect": True,
    "connect_on_start": True,
    "remote_allowed": False,       # privacy: refuse non-local hosts unless enabled
    "opacity": 0.96,
    "width": 420,
    "always_on_top": True,
    "dock_mode": "docked",         # "docked" (slides from a screen edge) | "floating"
    "dock_side": "right",
    "monitor": 0,
    "edge_reveal": True,
    "dock_autohide": True,
    "anim_ms": 220,
    "pinned": False,               # pinned = stays open, size and position locked
    "dock_height": 780,            # px, 0 = full height of the work area
    "dock_valign": "center",       # top | center | bottom | custom (custom uses dock_y)
    "dock_y": 0,                   # px from top of the work area when valign = custom
    "dock_gap": 12,                # px gap to the screen edge (0 = flush, square corners)
    "row_pad": 8,                  # vertical padding of rows (UI density)
    "start_hidden": True,
    "auto_hide_seconds": 0,        # 0 = never
    "pos": None,
    "accent": "#4cc38a",
    "font_size": 13,
    "radius": 10,
    "gallery_root": str(Path.home() / "Videos"),
    "screenshot_dir": str(Path.home() / "Pictures" / "ObsOverlay"),
    "screenshot_format": "png",
    "screenshot_quality": 90,
    "screenshot_pattern": "Screenshot_%Y-%m-%d_%H-%M-%S",
    "replay_seconds": 60,
    "confirm_stop_record": False,
    "confirm_stop_stream": True,
    "notifications": True,
    "notification_seconds": 3,
    "hide_filenames": False,
    "favorites": [],
    "preview_fps": 1,
    "preview_width": 320,
    "stats_visible": False,        # master switch for all floating widgets
    "widgets": [],                 # list of widget dicts (see ui/widgets_dock.py)
    "stats_metrics": ["recording", "streaming", "bitrate", "dropped", "resolution", "fps",
                      "cpu", "memory", "replay", "connection"],
    "stats_interval_ms": 1000,
    "stats_corner": "top-right",
    "stats_opacity": 0.85,
    "stats_warn_dropped_pct": 2.0,
    "stats_warn_cpu_pct": 85.0,
    "thumb_size": 150,
    "hotkeys": {
        "toggle_overlay": "Alt+Z", "record": "Alt+F9", "replay_toggle": "Alt+Shift+F10",
        "replay_save": "Alt+F10", "screenshot": "Alt+F1", "mic_mute": "Ctrl+Alt+M",
        "desktop_mute": "Ctrl+Alt+D", "stats": "Alt+R", "widgets_click": "Alt+Shift+W",
    },
}


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "settings.json")
        self.data = copy.deepcopy(DEFAULTS)
        self._session_pw = ""
        self.load()

    def load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for k, v in raw.items():
                if k == "hotkeys" and isinstance(v, dict):
                    self.data["hotkeys"].update({a: b for a, b in v.items() if a in HOTKEY_LABELS})
                elif k in DEFAULTS:
                    self.data[k] = v
        except FileNotFoundError:
            pass
        except Exception:
            try:
                self.path.rename(self.path.with_suffix(".corrupt.json"))   # keep a backup, use defaults
            except OSError:
                pass

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def __getitem__(self, k): return self.data[k]
    def __setitem__(self, k, v): self.data[k] = v

    def reset(self):
        self.data = copy.deepcopy(DEFAULTS)
        self.save()

    def export_to(self, path: str):
        Path(path).write_text(json.dumps(self.data, indent=2), encoding="utf-8")   # never includes the password

    def import_from(self, path: str):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        for k, v in raw.items():
            if k in DEFAULTS:
                self.data[k] = v
        self.save()

    # ---- credentials -------------------------------------------------------
    @staticmethod
    def keyring_available() -> bool:
        try:
            import keyring
            from keyring.backends.fail import Keyring as Fail
            return not isinstance(keyring.get_keyring(), Fail)
        except Exception:
            return False

    def get_password(self) -> str:
        if self._session_pw:
            return self._session_pw
        if not self.keyring_available():
            return ""
        import keyring
        return keyring.get_password(APP, "obs-websocket") or ""

    def set_password(self, pw: str):
        self._session_pw = pw          # in memory for this session only
        if self.keyring_available():
            import keyring
            if pw:
                keyring.set_password(APP, "obs-websocket", pw)
            else:
                try:
                    keyring.delete_password(APP, "obs-websocket")
                except Exception:
                    pass

    def has_password(self) -> bool:
        return bool(self.get_password())
