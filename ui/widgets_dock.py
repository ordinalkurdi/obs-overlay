"""Floating statistic widgets ("docks"): add as many as you like; each can be moved, resized, made
transparent, pinned (locked) and click-through. Managed from the overlay (Statistics row) or by right-click."""
from __future__ import annotations
import copy
import html
import uuid

import psutil
from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPropertyAnimation, QRect, QSize, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QGraphicsOpacityEffect, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
                               QSlider, QVBoxLayout, QWidget, QApplication, QLineEdit, QToolButton)

from core import layouts
from core.config import data_dir
from core.webdocks import PRESETS, host_of, normalize_url, preset_url
from core.widget_rows import KINDS, METRICS, build_rows
from . import dialogs
from .common import icon, tool_button
from .layout_edit import EditFrame, GuideOverlay
from .layout_presets import PresetPanel
from .overlay import Grip

SYS = {"cpu": None, "mem": None}
DEFAULT_WC = dict(x=60, y=60, w=270, h=200, opacity=0.9, pinned=False, click_through=False, visible=True, metrics=[])

# QtWebEngine must be imported before the QApplication exists (main.py imports this module first).
try:
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAVE_WEB = True

    class SafePage(QWebEnginePage):
        """Only http(s) navigation: no file:, javascript: or other schemes."""
        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            return url.scheme() in ("http", "https", "about", "blob", "data")
except ImportError:
    HAVE_WEB = False

_PROFILE = None
TRANSPARENT_JS = ("(function(){var s=document.createElement('style');"
                  "s.textContent='html,body{background:transparent !important;background-color:transparent !important}';"
                  "(document.head||document.documentElement).appendChild(s);})();")


def web_profile():
    """One persistent profile shared by all web docks, so logins (e.g. Twitch) survive restarts. Stored locally."""
    global _PROFILE
    if _PROFILE is None:
        d = data_dir() / "web"; d.mkdir(exist_ok=True)
        p = QWebEngineProfile("ObsOverlayWeb", QApplication.instance())
        p.setPersistentStoragePath(str(d / "storage")); p.setCachePath(str(d / "cache"))
        p.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        _PROFILE = p
    return _PROFILE


def clear_web_data():
    if HAVE_WEB:
        p = web_profile(); p.cookieStore().deleteAllCookies(); p.clearHttpCache()


class MoveButton(QToolButton):
    """Drag handle: press and drag to move the widget (locked while pinned). Snaps like dragging the widget itself."""
    def __init__(self, dock):
        super().__init__(dock); self.dock = dock; self.setCursor(Qt.SizeAllCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self.dock.drag_start(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton: self.dock.drag_move(e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e):
        self.dock.drag_end()


class HoverBar(QFrame):
    """Compact button strip drawn on the widget itself: move, opacity, pin, click-through, menu, remove."""
    def __init__(self, dock):
        super().__init__(dock); self.setObjectName("hoverbar"); self.setStyleSheet("#hoverbar{background:rgba(48,48,48,225); border-radius:6px;}")
        lay = QHBoxLayout(self); lay.setContentsMargins(2, 2, 2, 2); lay.setSpacing(2)
        self.opacity = QSlider(Qt.Horizontal, self); self.opacity.setRange(20, 100); self.opacity.setFixedWidth(64)
        self.opacity.setValue(int(round(float(dock.w["opacity"]) * 100)))
        self.opacity.setToolTip("Opacity of this widget"); self.opacity.setAccessibleName("Widget opacity")
        self.opacity.valueChanged.connect(lambda v: dock.set_opacity(v / 100, commit=not self.opacity.isSliderDown()))
        self.opacity.sliderReleased.connect(lambda: dock.set_opacity(self.opacity.value() / 100))      # one save when released
        self.move_btn = MoveButton(dock); self.move_btn.setIcon(icon("cursor-move")); self.move_btn.setIconSize(QSize(14, 14))
        self.move_btn.setToolTip("Drag to move")
        self.pin = tool_button("pin-outline", "Pin: lock size and position", True, size=14)
        self.ct = tool_button("mouse-off", "Click-through", True, size=14)
        self.menu_btn = tool_button("dots-vertical", "More options", size=14)
        self.close_btn = tool_button("close", "Remove this widget", size=14)
        for b in (self.move_btn, self.opacity, self.pin, self.ct, self.menu_btn, self.close_btn): lay.addWidget(b)
        self.hide()

    def show_opacity(self, op: float):
        if not self.opacity.isSliderDown():
            self.opacity.blockSignals(True); self.opacity.setValue(int(round(op * 100))); self.opacity.blockSignals(False)


class DockWidget(QWidget):
    needs_save = Signal()
    flags_changed = Signal()
    remove_requested = Signal(str)
    geometry_changed = Signal()         # moved or resized (the edit-mode chip follows the widget)

    @staticmethod
    def _flags(kind: str, click_through: bool):
        f = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        if kind != "web": f |= Qt.WindowDoesNotAcceptFocus        # web docks need keyboard focus (typing in chat)
        return f | Qt.WindowTransparentForInput if click_through else f

    def __init__(self, svc, wc: dict):
        super().__init__(None, self._flags(wc["kind"], bool(wc["click_through"])))
        self.svc, self.w = svc, wc
        self.pinned = bool(wc["pinned"]); self._user_resize = False; self._style = ""; self.view = None; self.hover = None
        self._edit = False; self._drag = None; self._anim = None; self.mgr = None; self.edit_frame = None
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMinimumSize(110, 44)
        self.lab = QLabel(); self.lab.setTextFormat(Qt.RichText); self.lab.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(self.lab)
        if wc["kind"] == "web": self._init_web(lay)
        self.setGeometry(int(wc["x"]), int(wc["y"]), int(wc["w"]), int(wc["h"]))
        self._fx = None
        if wc["kind"] != "web": self._fx = QGraphicsOpacityEffect(self.lab); self.lab.setGraphicsEffect(self._fx)
        self._apply_opacity()
        E = Qt.Edge; C = Qt
        spec = [(E.LeftEdge, C.SizeHorCursor, "l"), (E.RightEdge, C.SizeHorCursor, "r"), (E.TopEdge, C.SizeVerCursor, "t"),
                (E.BottomEdge, C.SizeVerCursor, "b"), (E.LeftEdge | E.TopEdge, C.SizeFDiagCursor, "tl"),
                (E.RightEdge | E.BottomEdge, C.SizeFDiagCursor, "br"), (E.RightEdge | E.TopEdge, C.SizeBDiagCursor, "tr"),
                (E.LeftEdge | E.BottomEdge, C.SizeBDiagCursor, "bl")]
        self.grips = {k: Grip(self, ed, cur) for ed, cur, k in spec}
        self._persist = QTimer(self); self._persist.setSingleShot(True); self._persist.setInterval(400)
        self._persist.timeout.connect(self._save_geometry)
        self.edit_frame = EditFrame(self, svc.cfg["accent"])
        self.hover = HoverBar(self)
        self.hover.pin.toggled.connect(self.set_pinned); self.hover.ct.toggled.connect(self._ct_clicked)
        self.hover.close_btn.clicked.connect(lambda: self.remove_requested.emit(self.w["id"]))
        self.hover.menu_btn.clicked.connect(lambda: self._menu(self.hover.menu_btn.mapToGlobal(QPoint(0, self.hover.menu_btn.height()))))
        self._hover_rule()
        self._sync_pin_ui()
        self._place_grips()

    # ---- rendering -----------------------------------------------------------
    def render(self):
        if self.w["kind"] == "web": return
        s = self.svc
        warn = {"dropped": float(s.cfg["stats_warn_dropped_pct"]), "cpu": float(s.cfg["stats_warn_cpu_pct"])}
        rows = build_rows(self.w["kind"], self.w, s.snap, s.status_text, s.ok, warn, SYS)
        body = "".join(f'<tr><td style="color:#9a9a9a">{html.escape(str(l))}&nbsp;&nbsp;</td>'
                       f'<td style="color:{c}">{html.escape(str(v))}</td></tr>' for l, v, c in rows)
        self.lab.setText("<table>" + (body or '<tr><td style="color:#9a9a9a">No metrics selected</td></tr>') + "</table>")
        fs = max(9, min(48, int(self.width() / 17)))          # text scales with the widget width
        pad = max(6, fs // 2)
        style = f"background:#181818; border-radius:{pad}px; padding:{pad}px {pad + 4}px; font-size:{fs}px; color:#f2f2f2;"
        if style != self._style:
            self._style = style; self.lab.setStyleSheet(style)

    # ---- geometry / interaction ---------------------------------------------
    def _ct_now(self) -> bool:
        """Click-through is suspended while the layout is being edited, so every widget can be grabbed."""
        return bool(self.w["click_through"]) and not self._edit

    def _place_grips(self):
        w, h, t, c = self.width(), self.height(), 6, 12
        geo = {"l": (0, c, t, h - 2 * c), "r": (w - t, c, t, h - 2 * c), "t": (c, 0, w - 2 * c, t), "b": (c, h - t, w - 2 * c, t),
               "tl": (0, 0, c, c), "br": (w - c, h - c, c, c), "tr": (w - c, 0, c, c), "bl": (0, h - c, c, c)}
        for k, g in self.grips.items():
            g.setGeometry(*geo[k]); g.setVisible(not self.pinned and not self._ct_now()); g.raise_()
        if self.edit_frame: self.edit_frame.setGeometry(self.rect()); self.edit_frame.raise_()
        if self.hover:
            self.hover.adjustSize(); self.hover.move(self.width() - self.hover.width() - 4, 4); self.hover.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e); self._place_grips(); self.render(); self._persist.start(); self.geometry_changed.emit()

    def moveEvent(self, e):
        super().moveEvent(e); self._persist.start(); self.geometry_changed.emit()

    def _save_geometry(self):
        g = self.geometry()
        self.w.update(x=g.x(), y=g.y(), w=g.width(), h=g.height()); self._user_resize = False
        self.needs_save.emit()

    def _sync_pin_ui(self):
        h = self.hover
        if h is None: return
        ct = bool(self.w["click_through"])
        for b, on, ico, tip_on, tip_off in (
                (h.pin, self.pinned, ("pin", "pin-outline"), "Pinned - click to unlock", "Pin: lock size and position"),
                (h.ct, ct, ("mouse-off", "mouse-off"), "Click-through is ON", "Click-through: mouse passes to what is behind")):
            b.blockSignals(True); b.setChecked(on); b.setIcon(icon(ico[0] if on else ico[1])); b.setToolTip(tip_on if on else tip_off)
            b.blockSignals(False)

    def _hover_rule(self):
        """Web docks always show their buttons (the page swallows hover); stat widgets show them on hover only."""
        if self.hover is None: return
        if self._ct_now(): self.hover.hide()
        elif self.w["kind"] == "web": self.hover.show(); self.hover.raise_()

    def _ct_clicked(self, on: bool):
        self.set_click_through(on)
        if on:
            hk = self.svc.cfg["hotkeys"].get("widgets_click") or "the tray menu"
            self.svc.say("info", f"Widget is click-through. Turn it off with {hk}, the tray menu or the Widgets page")

    def set_name(self, name: str):
        self.w["name"] = name.strip() or KINDS[self.w["kind"]][0]; self.needs_save.emit()

    def enterEvent(self, e):
        if self.hover and self.w["kind"] != "web" and not self._ct_now(): self.hover.show(); self.hover.raise_()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.hover and self.w["kind"] != "web": self.hover.hide()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self.drag_start(e.globalPosition().toPoint())      # locked while pinned

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton: self.drag_move(e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e):
        self.drag_end()

    # ---- dragging with snap guides ------------------------------------------------
    def drag_start(self, gp: QPoint):
        if not self.pinned:
            if self._anim: self._anim.stop()
            self._drag = (gp, self.pos())

    def drag_move(self, gp: QPoint):
        if not self._drag: return
        gp0, p0 = self._drag
        pos = p0 + (gp - gp0)
        self.move(self.mgr.snap_move(self, QRect(pos, self.size())) if self.mgr else pos)

    def drag_end(self):
        if self._drag:
            self._drag = None
            if self.mgr: self.mgr.end_drag(self)

    # ---- state changes (used by right-click menu and the management page) ----
    def set_pinned(self, on: bool):
        self.w["pinned"] = self.pinned = bool(on); self._sync_pin_ui(); self._place_grips(); self.flags_changed.emit(); self.needs_save.emit()

    def _refresh_flags(self):
        vis, geo = self.isVisible(), self.geometry()
        self.setWindowFlags(self._flags(self.w["kind"], self._ct_now())); self.setGeometry(geo); self._apply_opacity()
        self._place_grips(); self._sync_pin_ui(); self._hover_rule()
        if vis: self.show()

    def set_click_through(self, on: bool):
        self.w["click_through"] = bool(on)
        self._refresh_flags()
        self.flags_changed.emit(); self.needs_save.emit()

    def set_edit_mode(self, on: bool):
        """Layout editing: dashed outline, and click-through widgets become grabbable until editing ends."""
        if on == self._edit: return
        self._edit = on
        if self.w["click_through"]: self._refresh_flags()
        self.edit_frame.accent = QColor(self.svc.cfg["accent"]); self.edit_frame.setVisible(on)
        self._hover_rule(); self._place_grips()

    def apply_config(self, new: dict, animate: bool = True):
        """Applies a saved layout entry to this live widget (used when loading a preset): geometry glides to its place."""
        w = self.w; ct_before = bool(w["click_through"]); old = {k: w.get(k) for k in ("url", "zoom", "transparent")}
        for k in layouts.LAYOUT_KEYS:
            if k not in ("id", "kind") and k in new: w[k] = copy.deepcopy(new[k])
        self.pinned = bool(w["pinned"])
        if bool(w["click_through"]) != ct_before: self._refresh_flags()
        self._apply_opacity()
        if w["kind"] == "web":
            if w.get("url") != old["url"]: self.set_url(w["url"])
            if w.get("zoom") != old["zoom"]: self.set_zoom(float(w.get("zoom", 1.0)))
            if w.get("transparent") != old["transparent"] and self.view: self.set_transparent(bool(w.get("transparent", True)))
        self._sync_pin_ui(); self._place_grips(); self._hover_rule(); self.render()
        target = QRect(int(w["x"]), int(w["y"]), int(w["w"]), int(w["h"]))
        if self._anim: self._anim.stop()
        if animate and self.isVisible() and self.geometry() != target:
            a = QPropertyAnimation(self, b"geometry", self); a.setDuration(220); a.setEasingCurve(QEasingCurve.OutCubic)
            a.setStartValue(self.geometry()); a.setEndValue(target); a.start(); self._anim = a
        else:
            self.setGeometry(target)

    def show_menu(self, pos):
        self._menu(pos)

    def _apply_opacity(self):
        """Opacity fades only the widget's content, never the buttons on top of it (hover bar, outline). Web docks can only
        be faded as a whole window, because the embedded browser cannot take a graphics effect."""
        op = float(self.w["opacity"])
        if self.hover: self.hover.show_opacity(op)                  # keep the bar's slider in step (menu, presets, other sliders)
        if self._fx is not None:
            self.setWindowOpacity(1.0); self._fx.setOpacity(op)
        else:
            self.setWindowOpacity(op)

    def set_opacity(self, v: float, commit: bool = True):
        self.w["opacity"] = round(float(v), 2); self._apply_opacity()
        if commit: self.needs_save.emit()

    def set_visible_flag(self, on: bool):
        self.w["visible"] = bool(on); self.setVisible(bool(on) and bool(self.svc.cfg["stats_visible"]))
        self.flags_changed.emit(); self.needs_save.emit()

    def toggle_metric(self, key: str, on: bool):
        self.w["metrics"] = [k for k in METRICS if (k in self.w["metrics"] and k != key) or (k == key and on)]
        self.render(); self.needs_save.emit()

    def center_on_screen(self):
        g = QGuiApplication.primaryScreen().availableGeometry()
        self.move(g.center() - QPoint(self.width() // 2, self.height() // 2))

    # ---- web docks -------------------------------------------------------------
    def _init_web(self, lay):
        self.lab.hide(); self.setMinimumSize(220, 160)
        box = QFrame(); box.setStyleSheet("background:#181818;")
        bl = QVBoxLayout(box); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(0)
        if HAVE_WEB:
            self.view = QWebEngineView(box); self.view.setPage(SafePage(web_profile(), self.view))
            self.box = box; self._apply_transparency()
            self.view.setZoomFactor(float(self.w.get("zoom", 1.0))); self.view.setUrl(QUrl(self.w["url"]))
            bl.addWidget(self.view, 1)
        else:
            msg = QLabel("Web docks need QtWebEngine.\nInstall the full package: pip install PySide6")
            msg.setAlignment(Qt.AlignCenter); msg.setWordWrap(True); bl.addWidget(msg, 1)
        lay.addWidget(box)

    def _apply_transparency(self, reload=False):
        """Transparent web background: removes the page's white (like an OBS browser source)."""
        on = bool(self.w.get("transparent", True))
        self.box.setStyleSheet("background:transparent;" if on else "background:#181818;")
        if not self.view: return
        page = self.view.page()
        page.setBackgroundColor(QColor(0, 0, 0, 0) if on else QColor("#ffffff"))
        self.view.setAttribute(Qt.WA_TranslucentBackground, on); self.view.setStyleSheet("background:transparent;" if on else "")
        col = page.scripts()
        for old in col.find("obs-overlay-transparent"): col.remove(old)
        if on:
            sc = QWebEngineScript(); sc.setName("obs-overlay-transparent"); sc.setSourceCode(TRANSPARENT_JS)
            sc.setInjectionPoint(QWebEngineScript.DocumentCreation); sc.setWorldId(QWebEngineScript.MainWorld)
            sc.setRunsOnSubFrames(False); col.insert(sc)
        if reload: self.view.reload()

    def set_transparent(self, on: bool):
        self.w["transparent"] = bool(on); self._apply_transparency(reload=True); self.needs_save.emit()

    def set_url(self, url: str):
        self.w["url"] = url
        if self.view: self.view.setUrl(QUrl(url))
        self.needs_save.emit()

    def set_zoom(self, z: float):
        self.w["zoom"] = z
        if self.view: self.view.setZoomFactor(z)
        self.needs_save.emit()

    def open_external(self):
        QDesktopServices.openUrl(self.view.url() if self.view else QUrl(self.w["url"]))

    def contextMenuEvent(self, e):
        self._menu(e.globalPos())

    def _menu(self, pos):
        m = QMenu(self)
        a = m.addAction("Pinned (lock size and position)"); a.setCheckable(True); a.setChecked(self.pinned)
        a.toggled.connect(self.set_pinned)
        a = m.addAction("Click-through (mouse passes to the game)"); a.setCheckable(True); a.setChecked(bool(self.w["click_through"]))
        a.toggled.connect(self.set_click_through)
        om = m.addMenu("Opacity")
        for pct in (100, 85, 70, 55, 40, 25):
            act = om.addAction(f"{pct}%"); act.setCheckable(True); act.setChecked(abs(self.w["opacity"] * 100 - pct) < 8)
            act.triggered.connect(lambda _=False, p=pct: self.set_opacity(p / 100))
        if self.w["kind"] == "web":
            if self.view:
                m.addAction("Back", self.view.back); m.addAction("Reload", self.view.reload)
            m.addAction("Open in your browser", self.open_external)
            a = m.addAction("Transparent background (remove white)"); a.setCheckable(True); a.setChecked(bool(self.w.get("transparent", True)))
            a.toggled.connect(self.set_transparent)
            zm = m.addMenu("Zoom")
            for z in (50, 75, 100, 125, 150, 200):
                act = zm.addAction(f"{z}%"); act.setCheckable(True); act.setChecked(abs(float(self.w.get("zoom", 1.0)) * 100 - z) < 6)
                act.triggered.connect(lambda _=False, v=z: self.set_zoom(v / 100))
        if self.w["kind"] == "stats":
            mm = m.addMenu("Metrics")
            for k, label in METRICS.items():
                act = mm.addAction(label); act.setCheckable(True); act.setChecked(k in self.w["metrics"])
                act.toggled.connect(lambda on, key=k: self.toggle_metric(key, on))
        m.addSeparator()
        m.addAction("Center on screen", self.center_on_screen)
        m.addAction("Remove widget", lambda: self.remove_requested.emit(self.w["id"]))
        m.exec(pos)


class WidgetManager(QObject):
    changed = Signal()              # widgets added/removed or their flags changed (page should rebuild)
    layout_changed = Signal()       # anything about the arrangement changed (debounced): drives the preset "modified" state
    edit_mode_changed = Signal(bool)

    def __init__(self, svc):
        super().__init__()
        self.svc, self.cfg = svc, svc.cfg
        self.docks: dict[str, DockWidget] = {}
        self.edit_mode = False; self.guides: GuideOverlay | None = None
        self._dirty = QTimer(self); self._dirty.setSingleShot(True); self._dirty.setInterval(150); self._dirty.timeout.connect(self.layout_changed.emit)
        for wc in self.cfg["widgets"]:
            for k, v in DEFAULT_WC.items(): wc.setdefault(k, list(v) if isinstance(v, list) else v)
            self._keep_on_screen(wc)
            self._make(wc)
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh)

    @staticmethod
    def _keep_on_screen(wc):
        if not any(s.geometry().intersects(QRect(wc["x"], wc["y"], wc["w"], wc["h"])) for s in QGuiApplication.screens()):
            g = QGuiApplication.primaryScreen().availableGeometry(); wc["x"], wc["y"] = g.left() + 40, g.top() + 40   # was off-screen

    def _make(self, wc):
        d = DockWidget(self.svc, wc); d.mgr = self
        d.needs_save.connect(self.cfg.save); d.needs_save.connect(self._dirty.start)
        d.flags_changed.connect(self.changed.emit); d.remove_requested.connect(self.remove)
        d.set_edit_mode(self.edit_mode)
        self.docks[wc["id"]] = d

    # ---- layout state (presets) ---------------------------------------------------
    def current_layout(self) -> dict:
        return layouts.snapshot(self.cfg["widgets"])

    def apply_layout(self, layout: dict, animate: bool = True):
        """Makes the live widgets match a saved layout without a restart: widgets in both are updated in place (and glide
        to their position), missing ones are created, ones not in the layout are removed."""
        lay = layouts.sanitize_layout(layout)
        if lay is None: raise ValueError("invalid layout")
        entries = [w for w in lay["widgets"] if w["kind"] in KINDS]
        wanted = {w["id"]: w for w in entries}
        for wid in list(self.docks):
            d = self.docks[wid]
            if wid not in wanted or wanted[wid]["kind"] != d.w["kind"]:
                self.docks.pop(wid); d.close(); d.deleteLater()
        result = []
        for nw in entries:
            d = self.docks.get(nw["id"])
            if d:
                self._keep_on_screen(nw); d.apply_config(nw, animate); result.append(d.w)
            else:
                wc = dict(DEFAULT_WC, **nw); wc["metrics"] = list(nw.get("metrics", [])); self._keep_on_screen(wc)
                self._make(wc); result.append(wc)
        self.cfg["widgets"] = result
        self.cfg["stats_visible"] = True                      # the user asked to see this layout
        self.cfg.save(); self.apply(auto_add=False); self.svc.refresh(); self.changed.emit(); self._dirty.start()

    def reset_default_layout(self):
        """Stacks every widget along the right edge of the screen and shows it (names, sizes and settings are kept)."""
        g = dialogs._screen().availableGeometry(); top = g.y() + (64 if self.edit_mode else 0)          # leave room for the toolbar
        lay = self.current_layout()
        pos = layouts.default_positions([(w["w"], w["h"]) for w in lay["widgets"]], (g.x(), top, g.width(), g.height() - (top - g.y())))
        for w, (x, y) in zip(lay["widgets"], pos): w["x"], w["y"], w["visible"] = x, y, True
        self.apply_layout(lay)
        self.svc.say("info", "Widgets arranged in the default layout")

    def hide_all(self):
        for d in self.docks.values(): d.set_visible_flag(False)

    def show_all(self):
        for d in self.docks.values(): d.set_visible_flag(True)

    def all_hidden(self) -> bool:
        return bool(self.docks) and not any(d.w["visible"] for d in self.docks.values())

    # ---- edit mode + snapping -----------------------------------------------------
    def set_edit_mode(self, on: bool):
        if on == self.edit_mode: return
        self.edit_mode = on
        if on and not self.cfg["stats_visible"]: self.cfg["stats_visible"] = True; self.cfg.save()      # widgets must be visible to edit
        for d in self.docks.values(): d.set_edit_mode(on)
        self.apply()
        if not on:
            if self.guides: self.guides.hide()
            self.cfg.save()
        self.edit_mode_changed.emit(on)

    def snap_move(self, dock: DockWidget, rect: QRect) -> QPoint:
        """Called while dragging: returns the snapped position and shows the guide lines + drop indicator (Alt = no snap)."""
        scr = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen(); g = scr.availableGeometry()
        guides, dx, dy = [], 0, 0
        if not (QGuiApplication.keyboardModifiers() & Qt.AltModifier):
            others = [(o.x(), o.y(), o.width(), o.height()) for d in self.docks.values() if d is not dock and d.isVisible() for o in [d.geometry()]]
            dx, dy, guides = layouts.snap_rect((rect.x(), rect.y(), rect.width(), rect.height()), others, (g.x(), g.y(), g.width(), g.height()))
        target = rect.translated(dx, dy)
        if self.guides is None: self.guides = GuideOverlay(self.cfg["accent"])
        self.guides.accent = QColor(self.cfg["accent"]); self.guides.show_guides(scr.geometry(), guides, target)
        return target.topLeft()

    def end_drag(self, dock: DockWidget):
        if self.guides: self.guides.hide()
        scr = QGuiApplication.screenAt(dock.geometry().center()) or QGuiApplication.primaryScreen(); g = scr.availableGeometry()
        g_ = dock.geometry()
        x, y = layouts.clamp_to((g_.x(), g_.y(), g_.width(), g_.height()), (g.x(), g.y(), g.width(), g.height()))
        if (x, y) != (g_.x(), g_.y()): dock.move(x, y)           # never leave a widget where it cannot be grabbed again

    def add(self, kind: str, **extra):
        w, h = KINDS[kind][1]; n = len(self.docks) % 8; g = QGuiApplication.primaryScreen().availableGeometry()
        wc = dict(DEFAULT_WC, id=uuid.uuid4().hex[:8], kind=kind, x=g.left() + 40 + 30 * n, y=g.top() + 40 + 30 * n, w=w, h=h,
                  metrics=list(self.cfg["stats_metrics"]), **extra)
        self.cfg["widgets"].append(wc); self._make(wc)
        self.cfg["stats_visible"] = True; self.cfg.save()
        self.apply(); self.svc.refresh(); self.changed.emit()

    def remove(self, wid: str):
        d = self.docks.pop(wid, None)
        if d: d.close(); d.deleteLater()
        self.cfg["widgets"] = [w for w in self.cfg["widgets"] if w["id"] != wid]; self.cfg.save(); self.changed.emit()

    def apply(self, auto_add: bool = True):
        master = bool(self.cfg["stats_visible"])
        if master and not self.docks and auto_add:
            self.add("stats"); return                           # first use: give the user something to see
        for d in self.docks.values():
            vis = master and bool(d.w["visible"]); d.setVisible(vis)
            if vis: d.render(); d.raise_()
        if master: self.timer.start(max(500, int(self.cfg["stats_interval_ms"])))
        else: self.timer.stop()

    def refresh(self):
        if not any(d.isVisible() for d in self.docks.values()): return
        SYS["cpu"], SYS["mem"] = psutil.cpu_percent(None), psutil.virtual_memory().percent
        for d in self.docks.values():
            if d.isVisible(): d.render()

    def set_click_through_all(self, on: bool):
        for d in self.docks.values(): d.set_click_through(on)

    def toggle_click_through_all(self):
        if not self.docks: return
        on = not any(d.w["click_through"] for d in self.docks.values())
        self.set_click_through_all(on)
        self.svc.say("info", "Widgets are click-through" if on else "Widgets are interactive again")


class WidgetsPage(QWidget):
    """Page inside the overlay to add and configure widgets (needed because click-through widgets ignore the mouse)."""
    def __init__(self, mgr: WidgetManager, presets=None, editor=None):
        super().__init__(); self.mgr = mgr; self.setObjectName("plain")
        lay = QVBoxLayout(self); lay.setContentsMargins(12, 10, 12, 10)
        self.master = QCheckBox("Show floating widgets"); self.master.setChecked(bool(mgr.cfg["stats_visible"]))
        self.master.toggled.connect(self._master)
        top = QHBoxLayout(); self.kind = QComboBox()
        for k, (name, _) in KINDS.items():
            if k != "web": self.kind.addItem(name, k)
        add = QPushButton("Add widget"); add.setObjectName("primary"); add.clicked.connect(lambda: mgr.add(self.kind.currentData()))
        top.addWidget(self.kind, 1); top.addWidget(add)
        edit = None
        if editor is not None:
            edit = QPushButton(self)
            hk = mgr.cfg['hotkeys'].get('layout_edit') or 'no shortcut'

            def sync_edit(on=None):
                on = mgr.edit_mode if on is None else on
                edit.setIcon(icon("check" if on else "cursor-move")); edit.setText(" Exit layout editing" if on else " Edit layout...")
                edit.setToolTip(f"Leave edit mode ({hk})" if on else f"Arrange widgets on screen with snapping guides, and use presets ({hk})")
            edit.clicked.connect(editor.toggle)                  # same button starts and ends editing
            mgr.edit_mode_changed.connect(sync_edit); sync_edit()
        preset_card = None
        if presets is not None:
            preset_card = QFrame(); preset_card.setObjectName("card"); pc = QVBoxLayout(preset_card); pc.setContentsMargins(10, 8, 10, 10)
            pc.addWidget(PresetPanel(presets, max_list_height=150, parent=preset_card))
        tip = QLabel("Drag a widget to move it, drag its edges to resize (text scales with width), right-click for quick options. "
                     "Click-through widgets ignore the mouse: turn it off here, from the tray menu, or with the 'click-through' hotkey.")
        tip.setWordWrap(True); tip.setObjectName("dim")
        self.host = QWidget(); self.hl = QVBoxLayout(self.host); self.hl.setContentsMargins(0, 0, 0, 0); self.hl.setSpacing(8)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame); sc.setWidget(self.host)
        webl = QLabel("<b>Web docks</b> - chat, Twitch Stream Manager, or any web page"); webl.setWordWrap(True)
        wrow = QHBoxLayout(); self.preset = QComboBox(); self.preset.addItems(list(PRESETS)); self.web_in = QLineEdit()
        wadd = QPushButton("Add web dock"); wadd.setObjectName("primary")
        self.web_err = QLabel(); self.web_err.setStyleSheet("color:#ff7b7b"); self.web_err.setWordWrap(True)
        wrow.addWidget(self.preset); wrow.addWidget(self.web_in, 1); wrow.addWidget(wadd)
        self.preset.currentIndexChanged.connect(self._preset_changed); wadd.clicked.connect(self._add_web); self.web_in.returnPressed.connect(self._add_web)
        clear = QPushButton("Clear web login data"); clear.setToolTip("Deletes cookies and cache stored locally for web docks"); clear.clicked.connect(clear_web_data)
        self._preset_changed()
        lay.addWidget(self.master)
        if edit is not None: lay.addWidget(edit)
        if preset_card is not None: lay.addWidget(preset_card)
        lay.addLayout(top); lay.addWidget(webl); lay.addLayout(wrow); lay.addWidget(self.web_err)
        lay.addWidget(tip); lay.addWidget(sc, 1); lay.addWidget(clear)
        mgr.changed.connect(self.rebuild); self.rebuild()

    def showEvent(self, e):
        super().showEvent(e); self.master.blockSignals(True); self.master.setChecked(bool(self.mgr.cfg["stats_visible"]))
        self.master.blockSignals(False); self.rebuild()

    def _preset_changed(self):
        p = PRESETS[self.preset.currentText()]
        self.web_in.setVisible(p["input"] is not None); self.web_in.setPlaceholderText(p["input"] or "")

    def _add_web(self):
        name = self.preset.currentText(); url = preset_url(name, self.web_in.text())
        if not url:
            self.web_err.setText(PRESETS[name]["error"]); return
        self.web_err.setText("")
        self.mgr.add("web", name=host_of(url) if name == "Custom URL" else name, url=url, zoom=1.0); self.web_in.clear()

    def _master(self, on):
        self.mgr.cfg["stats_visible"] = bool(on); self.mgr.cfg.save(); self.mgr.apply(); self.mgr.svc.refresh()

    def rebuild(self):
        while self.hl.count():
            w = self.hl.takeAt(0).widget()
            if w: w.deleteLater()
        if not self.mgr.docks:
            l = QLabel("No widgets yet. Pick a type above and press Add widget."); l.setObjectName("dim"); self.hl.addWidget(l)
        for wid, d in self.mgr.docks.items():
            self.hl.addWidget(self._card(wid, d))
        self.hl.addStretch()

    def _card(self, wid, d: DockWidget):
        card = QFrame(); card.setStyleSheet("QFrame#card{background:#222; border-radius:8px;}"); card.setObjectName("card")
        v = QVBoxLayout(card); v.setContentsMargins(10, 8, 10, 8)
        ne = QLineEdit(d.w.get("name") or KINDS[d.w["kind"]][0]); ne.setToolTip("Widget name - click to rename")
        ne.setStyleSheet("font-weight:600; background:transparent;")
        ne.editingFinished.connect(lambda dd=d, e=ne: (dd.set_name(e.text()), e.setText(dd.w["name"]))); v.addWidget(ne)
        if d.w["kind"] == "web":
            ur = QHBoxLayout(); ue = QLineEdit(d.w["url"]); go = QPushButton("Go"); ue.setToolTip("Address of this dock")
            def apply_url(_=None, dd=d, edit=ue):
                u = normalize_url(edit.text())
                if u: edit.setText(u); dd.set_url(u)
                else: edit.setStyleSheet("border:1px solid #ff7b7b;")
            go.clicked.connect(apply_url); ue.returnPressed.connect(apply_url); ur.addWidget(ue, 1); ur.addWidget(go); v.addLayout(ur)
            tc = QCheckBox("Transparent background (remove white)"); tc.setChecked(bool(d.w.get("transparent", True)))
            tc.toggled.connect(d.set_transparent); v.addWidget(tc)
        r1 = QHBoxLayout()
        for text, key, fn in (("Visible", "visible", d.set_visible_flag), ("Pinned", "pinned", d.set_pinned),
                              ("Click-through", "click_through", d.set_click_through)):
            c = QCheckBox(text); c.setChecked(bool(d.w[key])); c.toggled.connect(fn); r1.addWidget(c)
        v.addLayout(r1)
        r2 = QHBoxLayout(); r2.addWidget(QLabel("Opacity"))
        sl = QSlider(Qt.Horizontal); sl.setRange(20, 100); sl.setValue(int(d.w["opacity"] * 100))
        sl.valueChanged.connect(lambda val, dd=d: dd.set_opacity(val / 100)); r2.addWidget(sl, 1); v.addLayout(r2)
        r3 = QHBoxLayout()
        if d.w["kind"] == "stats":
            b = QPushButton("Metrics..."); menu = QMenu(b)
            for k, label in METRICS.items():
                act = menu.addAction(label); act.setCheckable(True); act.setChecked(k in d.w["metrics"])
                act.toggled.connect(lambda on, key=k, dd=d: dd.toggle_metric(key, on))
            b.setMenu(menu); r3.addWidget(b)
        cb = QPushButton("Center"); cb.clicked.connect(d.center_on_screen)
        rm = QPushButton("Remove"); rm.setObjectName("danger"); rm.clicked.connect(lambda _=False, i=wid: self.mgr.remove(i))
        r3.addStretch(); r3.addWidget(cb); r3.addWidget(rm); v.addLayout(r3)
        return card
