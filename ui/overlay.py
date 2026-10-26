from __future__ import annotations
import time

import psutil
from PySide6.QtCore import Qt, QTimer, Signal, QPoint, QRect, QRectF, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPixmap, QGuiApplication, QCursor, QColor, QLinearGradient, QPainter, QRegion
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel, QMenu, QSlider, QVBoxLayout, QWidget,
                               QFrame, QScrollArea, QStackedWidget, QSizePolicy)

from core import audio, gallery
from core.audio import Ballistics
from core.service import ObsService
from . import dialogs
from .common import FG_DIM, Row, icon, separator, tool_button
from .gallery_view import GalleryStrip, MediaStore


def fmt_elapsed(sec: float) -> str:
    sec = int(max(sec, 0)); h, r = divmod(sec, 3600); m, s = divmod(r, 60)
    return f"{h:d}:{m:02d}:{s:02d}"


class StatsPanel(QWidget):
    """Optional always-on-top statistics panel. Unknown metrics show 'Unavailable' (never invented)."""
    def __init__(self, svc: ObsService):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.svc, self.cfg = svc, svc.cfg
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.lab = QLabel(); self.lab.setTextFormat(Qt.RichText); self.lab.setObjectName("panel")
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(self.lab)
        self.lab.setStyleSheet("background:#181818; border-radius:8px; padding:8px 12px;")
        self.timer = QTimer(self); self.timer.timeout.connect(self.update_stats)
        psutil.cpu_percent(None)

    def apply(self):
        self.setWindowOpacity(float(self.cfg["stats_opacity"]))
        self.timer.setInterval(max(500, int(self.cfg["stats_interval_ms"])))
        if self.cfg["stats_visible"]:
            self.update_stats(); self.show(); self.timer.start()
        else:
            self.hide(); self.timer.stop()

    def update_stats(self):
        s, c = self.svc.snap, self.cfg
        m = set(c["stats_metrics"]); rows = []
        U = '<span style="color:#9a9a9a">Unavailable</span>'
        def add(key, label, val, warn=False):
            if key in m:
                col = "#ff7b7b" if warn else "#f2f2f2"
                rows.append(f'<tr><td style="color:#9a9a9a">{label}&nbsp;&nbsp;</td><td style="color:{col}">{val}</td></tr>')
        add("connection", "OBS", self.svc.status_text)
        rec = s.get("recording")
        add("recording", "Recording", (f"{'Paused' if s.get('paused') else 'REC'} {fmt_elapsed(s.get('rec_dur', 0))}" if rec else "Idle"))
        add("streaming", "Streaming", f"LIVE {fmt_elapsed(s.get('stream_dur', 0))}" if s.get("streaming") else "Offline")
        br = s.get("bitrate_kbps"); add("bitrate", "Bitrate", f"{br:.0f} kbps" if br is not None else U)
        dp = s.get("dropped_pct"); add("dropped", "Dropped", f"{dp:.2f}%" if dp is not None else U, dp is not None and dp >= c["stats_warn_dropped_pct"])
        r = s.get("out_res"); add("resolution", "Output", f"{r[0]}x{r[1]}" if r else U)
        add("fps", "FPS", f"{s['fps']:g}" if s.get("fps") else U)
        cpu = psutil.cpu_percent(None); add("cpu", "System CPU", f"{cpu:.0f}%", cpu >= c["stats_warn_cpu_pct"])
        add("memory", "System RAM", f"{psutil.virtual_memory().percent:.0f}%")
        add("replay", "Replay buffer", ("On" if s.get("replay_active") else "Off") if s.get("replay_available", True) else "Not enabled in OBS")
        self.lab.setText("<table>" + "".join(rows) + "</table>" if rows else "No metrics selected")
        self.adjustSize(); self.reposition()

    def reposition(self):
        g = QGuiApplication.primaryScreen().availableGeometry(); mg = 16; cn = self.cfg["stats_corner"]
        x = g.left() + mg if "left" in cn else g.right() - self.width() - mg
        y = g.top() + mg if "top" in cn else g.bottom() - self.height() - mg
        self.move(x, y)


class LevelBar(QWidget):
    """Smooth audio level bar (OBS-style green/yellow/red) with a peak-hold marker. Animated by the overlay's meter timer."""
    def __init__(self):
        super().__init__(); self.setFixedHeight(6); self.motion = Ballistics()

    def set_target(self, pct: float): self.motion.target = max(0.0, min(100.0, pct))
    def step(self, dt: float) -> bool:
        moving = self.motion.step(dt)
        if moving or self.motion.value == 0.0: self.update()
        return moving

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height(); r = h / 2
        p.setPen(Qt.NoPen); p.setBrush(QColor("#2c2c2c")); p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        fill = w * self.motion.value / 100.0
        if fill > 0.5:
            g = QLinearGradient(0, 0, w, 0)                         # fixed across the full width, like a real meter
            for pos, col in ((0.0, "#4cc38a"), (0.68, "#4cc38a"), (0.85, "#e6b800"), (1.0, "#ff5c5c")): g.setColorAt(pos, QColor(col))
            p.setBrush(g); p.setClipRect(QRectF(0, 0, fill, h)); p.drawRoundedRect(QRectF(0, 0, w, h), r, r); p.setClipping(False)
        pk = w * self.motion.peak / 100.0
        if pk > 3:
            p.setBrush(QColor(255, 255, 255, 190)); p.drawRect(QRectF(min(pk, w) - 2, 0, 2, h))
        p.end()


class Grip(QWidget):
    """Invisible resize handle on the panel border; uses the OS resize so it feels native."""
    def __init__(self, parent, edges, cursor):
        super().__init__(parent); self.edges = edges; self.setCursor(cursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            ov = self.window(); h = ov.windowHandle()
            if h and not ov.pinned:                      # pinned = size locked
                ov._user_resize = True; h.startSystemResize(self.edges)


class EdgeTrigger(QWidget):
    """Nearly invisible 3px strip on the monitor edge; hovering it slides the panel out."""
    entered = Signal()

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.enabled = False

    def configure(self, screen, side, enabled, y=None, h=None):
        g = screen.availableGeometry(); self.enabled = enabled; w = 3
        self.setGeometry(g.right() - w + 1 if side == "right" else g.left(), g.top() if y is None else y, w, h or g.height())
        self.refresh(False)

    def refresh(self, panel_open):
        self.setVisible(self.enabled and not panel_open)

    def paintEvent(self, e):
        p = QPainter(self); p.fillRect(self.rect(), QColor(0, 0, 0, 3)); p.end()   # alpha>0 so Windows delivers hover

    def enterEvent(self, e):
        self.entered.emit()


class Overlay(QWidget):
    open_settings = Signal()
    quit_requested = Signal()

    def __init__(self, svc: ObsService, store: MediaStore, hotkey_hints: callable):
        super().__init__()
        self.svc, self.cfg, self.store, self.hints = svc, svc.cfg, store, hotkey_hints
        self.pinned = False; self._drag: QPoint | None = None; self._preview_on = False
        self._open = False; self._gallery = None; self._settings = None; self._widgets = None
        self.setWindowTitle("OBS OVERLAY"); self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._build()
        svc.state_changed.connect(self.sync); svc.notify.connect(self.on_notify); svc.preview_ready.connect(self._set_preview); svc.meters_changed.connect(self._update_meters)
        self.idle = QTimer(self); self.idle.setSingleShot(True); self.idle.timeout.connect(self._auto_hide)
        self.tick = QTimer(self); self.tick.setInterval(500); self.tick.timeout.connect(self._tick)
        self.pv = QTimer(self); self.pv.timeout.connect(self.svc.request_preview)
        self.anim = QPropertyAnimation(self, b"pos", self)
        self.anim.valueChanged.connect(lambda _v: self._clip()); self.anim.finished.connect(self._anim_done)
        self.edge = EdgeTrigger(); self.edge.entered.connect(self.show_panel)
        self._meter_t = 0.0; self._meter_timer = QTimer(self); self._meter_timer.timeout.connect(self._meter_tick)
        self.leave_timer = QTimer(self); self.leave_timer.setSingleShot(True); self.leave_timer.setInterval(450)
        self.leave_timer.timeout.connect(self._maybe_leave)
        self._user_resize = False
        self._persist = QTimer(self); self._persist.setSingleShot(True); self._persist.setInterval(400)
        self._persist.timeout.connect(self._persist_geometry)
        E = Qt.Edge; C = Qt
        spec = [(E.LeftEdge, C.SizeHorCursor, "l"), (E.RightEdge, C.SizeHorCursor, "r"), (E.TopEdge, C.SizeVerCursor, "t"),
                (E.BottomEdge, C.SizeVerCursor, "b"), (E.LeftEdge | E.TopEdge, C.SizeFDiagCursor, "tl"),
                (E.RightEdge | E.BottomEdge, C.SizeFDiagCursor, "br"), (E.RightEdge | E.TopEdge, C.SizeBDiagCursor, "tr"),
                (E.LeftEdge | E.BottomEdge, C.SizeBDiagCursor, "bl")]
        self.grips = {k: Grip(self, ed, cur) for ed, cur, k in spec}
        self.pin.setChecked(bool(self.cfg["pinned"]))
        self.apply_settings(); self.sync(); self.prev_row.set_texts(sub=self._preview_sub())

    # ---- UI ----------------------------------------------------------------
    def _build(self):
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame(); self.panel.setObjectName("panel"); outer.addWidget(self.panel)
        v = QVBoxLayout(self.panel); v.setContentsMargins(0, 0, 0, 8); v.setSpacing(0)
        # header
        self.header = QFrame(); self.header.setObjectName("header"); hl = QHBoxLayout(self.header); hl.setContentsMargins(16, 10, 10, 10)
        self.title = QLabel("OBS OVERLAY"); self.title.setObjectName("title")
        self.dot = QLabel(); self.dot.setFixedSize(10, 10)
        self.pin = tool_button("pin-outline", "Keep open (pin)", True); self.cfgb = tool_button("cog", "Settings")
        mini = tool_button("window-minimize", "Hide to tray"); close = tool_button("close", "Hide overlay (return to game)")
        self.back = tool_button("arrow-left", "Back to overlay"); self.back.setVisible(False)
        self.back.clicked.connect(lambda: self.show_page("home"))
        hl.addWidget(self.back); hl.addWidget(self.title); hl.addWidget(self.dot); hl.addStretch()
        for b in (self.pin, self.cfgb, mini, close): hl.addWidget(b)
        v.addWidget(self.header)
        self.stack = QStackedWidget(); v.addWidget(self.stack, 1)
        home = QWidget(); home.setObjectName("plain"); hv = QVBoxLayout(home); hv.setContentsMargins(0, 0, 0, 0); hv.setSpacing(0)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); sc.setWidget(home); self.stack.addWidget(sc)
        self.pin.toggled.connect(self._pin); self.cfgb.clicked.connect(self.open_settings.emit)
        mini.clicked.connect(self.hide_panel); close.clicked.connect(self.hide_panel)
        # gallery
        self.gal_row = Row("movie-open-outline", "Gallery", "Recent captures from all game folders", tooltip="Open full gallery")
        hv.addWidget(self.gal_row); self.strip = GalleryStrip(self.store); hv.addWidget(self.strip); hv.addWidget(separator())
        # capture
        self.rec = Row("record-circle-outline", "Record", "", chevron=False); self.rec.set_right_icon("play")
        self.rep = Row("replay", "Instant Replay", "", tooltip="OBS Replay Buffer")
        self.save = Row("content-save-outline", "Save replay", "", chevron=False)
        self.shot = Row("camera-outline", "Screenshot", "", chevron=False, tooltip="Captures the OBS scene output, not the desktop/game directly")
        self.live = Row("broadcast", "Stream", "", chevron=False); self.live.set_right_icon("play")
        self.pause = Row("pause-circle-outline", "Pause recording", "", chevron=False); self.pause.setVisible(False)
        self.vcam = Row("webcam", "Virtual camera", "", chevron=False)
        for r in (self.rec, self.pause, self.rep, self.save, self.shot, self.live, self.vcam): hv.addWidget(r)
        hv.addWidget(separator())
        # production
        self.scene_row = Row("theater", "Scene", "", chevron=False)
        self.scene_box = QComboBox(); self.scene_box.setMinimumWidth(150); self.scene_box.setToolTip("Switch OBS scene")
        self.scene_row.add_tail(self.scene_box); hv.addWidget(self.scene_row)
        self.prev_row = Row("monitor-eye", "Preview", "")
        hv.addWidget(self.prev_row)
        self.prev_lab = QLabel(alignment=Qt.AlignCenter); self.prev_lab.setVisible(False); hv.addWidget(self.prev_lab)
        self.src_row = Row("layers-outline", "Sources", "Show / hide / lock sources of the current scene"); hv.addWidget(self.src_row)
        self.srcbox = QWidget(); self.sl = QVBoxLayout(self.srcbox); self.sl.setContentsMargins(40, 0, 12, 4); self.sl.setSpacing(0)
        self.srcbox.setVisible(False); hv.addWidget(self.srcbox)
        hv.addWidget(separator())
        # audio
        self.mix = Row("tune-vertical", "Audio", "Mute, volume and live activity of OBS audio sources")
        self.mix.set_right_icon("chevron-down", FG_DIM)
        hv.addWidget(self.mix)
        self.mixer = QWidget(); self.ml = QVBoxLayout(self.mixer); self.ml.setContentsMargins(46, 0, 16, 4)
        hv.addWidget(self.mixer); hv.addWidget(separator())
        self.stat_row = Row("view-dashboard-outline", "Widgets", "", tooltip="Add and customize floating widgets (stats, web docks)"); hv.addWidget(self.stat_row)
        self.gallery_btn_hint = None
        self.footer = QLabel(); self.footer.setObjectName("dim"); self.footer.setContentsMargins(16, 6, 16, 0); self.footer.setWordWrap(True)
        hv.addWidget(self.footer)
        self.toast = dialogs.NotificationWindow()           # centered on screen, independent of overlay visibility
        # wiring
        self.rec.clicked.connect(self._rec_clicked); self.live.clicked.connect(self._live_clicked)
        self.rep.clicked.connect(self.svc.toggle_replay); self.save.clicked.connect(self.svc.save_replay); self.shot.clicked.connect(self.svc.screenshot)
        self.mix.clicked.connect(self._toggle_mixer)
        self.prev_row.clicked.connect(self._toggle_preview)
        self.pause.clicked.connect(self.svc.toggle_pause); self.vcam.clicked.connect(self.svc.toggle_vcam)
        self.src_row.clicked.connect(self._toggle_sources)
        self.scene_box.activated.connect(lambda _: self.svc.set_scene(self.scene_box.currentText()))

    # ---- behavior ----------------------------------------------------------
    # ---- docking / pages -----------------------------------------------------
    def docked(self): return self.cfg["dock_mode"] == "docked"

    def _screen(self):
        sc = QGuiApplication.screens(); i = int(self.cfg["monitor"])
        return sc[i] if 0 <= i < len(sc) else QGuiApplication.primaryScreen()

    def _rect(self, shown=True) -> QRect:
        g = self._screen().availableGeometry(); gap = int(self.cfg["dock_gap"])
        w = max(320, min(int(self.cfg["width"]), g.width()))
        h = int(self.cfg["dock_height"]); h = g.height() - 2 * gap if h <= 0 else h
        h = max(320, min(h, g.height()))
        if self.docked():
            va = self.cfg["dock_valign"]
            if va == "top": y = g.top() + gap
            elif va == "bottom": y = g.bottom() - gap - h + 1
            elif va == "custom": y = g.top() + int(self.cfg["dock_y"])
            else: y = g.top() + (g.height() - h) // 2
            y = max(g.top(), min(y, g.bottom() - h + 1))
            if self.cfg["dock_side"] == "right": x = g.right() - w + 1 - gap if shown else g.right() + 1
            else: x = g.left() + gap if shown else g.left() - w
            return QRect(x, y, w, h)
        x, y = self.cfg["pos"] if self.cfg["pos"] else (g.right() - w - 20, g.top() + 60)
        return QRect(x, y, w, min(h, g.height() - 40))

    def apply_settings(self):
        flags = Qt.Tool | Qt.FramelessWindowHint
        if self.cfg["always_on_top"] or self.docked(): flags |= Qt.WindowStaysOnTopHint
        was = self.isVisible(); key = bool(self.cfg["always_on_top"] or self.docked())
        relaunch = False
        if key != getattr(self, "_top_key", None):          # changing window flags recreates the window: only when needed
            self._top_key = key; self.setWindowFlags(flags); relaunch = was
        self.setWindowOpacity(float(self.cfg["opacity"]))
        d = self.docked()
        flush = d and int(self.cfg["dock_gap"]) == 0
        self.panel.setStyleSheet("#panel{border-radius:0px;}" if flush else ""); self.header.setStyleSheet("#header{border-radius:0px;}" if flush else "")
        g = self._screen().availableGeometry(); r = self._rect(True)
        self.setMinimumSize(320, 320); self.setMaximumSize(g.width(), g.height()); self.resize(r.size())
        self._edge_cfg(r); self._place_grips()
        self.anim.setDuration(int(self.cfg["anim_ms"]))
        if relaunch: self.setGeometry(r); self.clearMask(); self.show(); self._open = True
        elif was and self._open: self.setGeometry(r)
        elif not was: self.move(r.topLeft())
        self.edge.refresh(self._open)

    def show_panel(self):
        """Slide in from the monitor edge (docked) or just show (floating)."""
        if self._open and self.isVisible():
            self.raise_(); self.activateWindow(); return
        self.leave_timer.stop(); self.anim.stop()
        if self.docked():
            self.setGeometry(self._rect(False)); self._clip(); self.show(); self._open = True
            if int(self.cfg["anim_ms"]) > 0:
                self.anim.setStartValue(self.pos()); self.anim.setEndValue(self._rect(True).topLeft())
                self.anim.setEasingCurve(QEasingCurve.OutCubic); self.anim.start()
            else:
                self.move(self._rect(True).topLeft()); self.clearMask()
        else:
            self.setGeometry(self._rect(True)); self.show(); self._open = True
        self.edge.refresh(True); self.raise_(); self.activateWindow(); self._bump_idle()

    def hide_panel(self):
        """Slide back out to the edge, then hide (focus returns to the game)."""
        if not self.isVisible(): return
        self._open = False; self.edge.refresh(False); self.anim.stop()
        if self.docked() and int(self.cfg["anim_ms"]) > 0:
            self.anim.setStartValue(self.pos()); self.anim.setEndValue(self._rect(False).topLeft())
            self.anim.setEasingCurve(QEasingCurve.InCubic); self.anim.start()
        else:
            self.hide()

    def toggle_visible(self):
        self.hide_panel() if (self._open and self.isVisible()) else self.show_panel()

    def _anim_done(self):
        if self._open: self.clearMask()
        else: self.hide(); self.clearMask()

    def _clip(self):
        """Mask the part of the sliding panel that lies outside this monitor (no bleeding onto neighbours)."""
        if not self.docked(): return
        vis = QRect(self.pos(), self.size()).intersected(self._screen().geometry())
        self.setMask(QRegion(vis.translated(-self.pos())) if not vis.isEmpty() else QRegion(0, 0, 1, 1))

    def _edge_cfg(self, r: QRect | None = None):
        r = r or self._rect(True)
        self.edge.configure(self._screen(), self.cfg["dock_side"], self.docked() and bool(self.cfg["edge_reveal"]), r.y(), r.height())
        self.edge.refresh(self._open)

    def _place_grips(self):
        w, h, t, c = self.width(), self.height(), 6, 14
        geo = {"l": (0, c, t, h - 2 * c), "r": (w - t, c, t, h - 2 * c), "t": (c, 0, w - 2 * c, t), "b": (c, h - t, w - 2 * c, t),
               "tl": (0, 0, c, c), "br": (w - c, h - c, c, c), "tr": (w - c, 0, c, c), "bl": (0, h - c, c, c)}
        if self.pinned:
            on = set()                                   # pinned: no resize handles at all
        elif self.docked():      # no handle on the side that touches the screen edge
            on = {"l", "t", "b", "tl", "bl"} if self.cfg["dock_side"] == "right" else {"r", "t", "b", "tr", "br"}
        else:
            on = set(geo)
        for k, g in self.grips.items():
            g.setGeometry(*geo[k])
            g.setVisible(k in on); g.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e); self._place_grips()
        if self._user_resize: self._persist.start()      # only user drags are saved, not programmatic resizes

    def _persist_geometry(self):
        if not self._user_resize or not self.isVisible(): return
        self._user_resize = False
        g = self._screen().availableGeometry()
        self.cfg["width"] = self.width(); self.cfg["dock_height"] = self.height()
        if self.docked():
            self.cfg["dock_valign"] = "custom"; self.cfg["dock_y"] = self.y() - g.top()
        else:
            self.cfg["pos"] = [self.x(), self.y()]
        self.cfg.save(); self._edge_cfg()

    def set_gallery(self, w):
        self._gallery = w; self.stack.addWidget(w)

    def set_widgets_page(self, w):
        self._widgets = w; self.stack.addWidget(w)

    def set_settings_page(self, w):
        self.drop_settings(go_home=False); self._settings = w; self.stack.addWidget(w); self.show_page("settings")

    def drop_settings(self, go_home=True):
        if self._settings is not None:
            self.stack.removeWidget(self._settings); self._settings.deleteLater(); self._settings = None
        if go_home: self.show_page("home")

    def show_page(self, name):
        if name == "gallery" and self._gallery: self.stack.setCurrentWidget(self._gallery); t = "GALLERY"
        elif name == "settings" and self._settings: self.stack.setCurrentWidget(self._settings); t = "SETTINGS"
        elif name == "widgets" and self._widgets: self.stack.setCurrentWidget(self._widgets); t = "WIDGETS"
        else: self.stack.setCurrentIndex(0); t = "OBS OVERLAY"
        self.title.setText(t); self.back.setVisible(t != "OBS OVERLAY")

    def hideEvent(self, e):
        self._meter_timer.stop(); self.pv.stop(); self._open = False; self.edge.refresh(False)
        if not self.docked():
            self.cfg["pos"] = [self.x(), self.y()]; self.cfg.save()
        super().hideEvent(e)

    def showEvent(self, e):
        super().showEvent(e); self.store.rescan(); self._update_meters()
        if self._preview_on: self.pv.start(self._preview_interval())

    def leaveEvent(self, e):
        if self.docked() and self.cfg["dock_autohide"] and not self.pinned and self.stack.currentIndex() == 0:
            self.leave_timer.start()
        super().leaveEvent(e)

    def enterEvent(self, e):
        self.leave_timer.stop(); super().enterEvent(e)

    def _maybe_leave(self):
        if self.frameGeometry().contains(QCursor.pos()) or QApplication.activePopupWidget() or QApplication.activeModalWidget(): return
        if not self.pinned and self.stack.currentIndex() == 0: self.hide_panel()

    def _pin(self, on):
        self.pinned = on; self._drag = None
        self.pin.setIcon(icon("pin" if on else "pin-outline"))
        self.pin.setToolTip("Pinned: stays open, size and position locked (click to unpin)" if on else "Pin: keep open and lock size/position")
        self.cfg["pinned"] = bool(on); self.cfg.save()
        self._place_grips(); self._bump_idle()

    def _bump_idle(self):
        s = int(self.cfg["auto_hide_seconds"])
        if s > 0 and not self.pinned: self.idle.start(s * 1000)
        else: self.idle.stop()

    def _auto_hide(self):
        if not self.pinned and not self.frameGeometry().contains(QCursor.pos()): self.hide_panel()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            pt = e.globalPosition().toPoint() - self._drag
            if self.docked():       # docked: slide along the edge only
                g = self._screen().availableGeometry(); pt.setX(self.x()); pt.setY(max(g.top(), min(pt.y(), g.bottom() - self.height() + 1)))
            self.move(pt)
        self._bump_idle()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 52 and not self.pinned:   # pinned = position locked
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseReleaseEvent(self, e):
        if self._drag is not None and self.docked() and self.y() != self._rect(True).y():
            self.cfg["dock_valign"] = "custom"; self.cfg["dock_y"] = self.y() - self._screen().availableGeometry().top()
            self.cfg.save(); self._edge_cfg()
        self._drag = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape: self.show_page("home") if self.stack.currentIndex() != 0 else self.hide_panel()   # Esc: back / give focus to the game
        else: super().keyPressEvent(e)

    def _confirm(self, key, text):
        if not self.cfg[key]: return True
        return dialogs.confirm(self, "Confirm", text)

    def _rec_clicked(self):
        if self.svc.snap.get("recording") and not self._confirm("confirm_stop_record", "Stop recording?"): return
        self.svc.toggle_record()

    def _live_clicked(self):
        if self.svc.snap.get("streaming") and not self._confirm("confirm_stop_stream", "Stop the live stream?"): return
        self.svc.toggle_stream()

    def toggle_stream_hotkey(self): self._live_clicked()

    def _toggle_preview(self):
        self._preview_on = not self._preview_on; self.prev_lab.setVisible(self._preview_on)
        if self._preview_on:
            self.prev_row.set_right_icon("chevron-down"); self.svc.request_preview()
            self.pv.start(self._preview_interval())
        else:
            self.prev_row.set_right_icon("chevron-right"); self.pv.stop()

    def _toggle_sources(self):
        self.srcbox.setVisible(not self.srcbox.isVisible())
        self.src_row.set_right_icon("chevron-down" if self.srcbox.isVisible() else "chevron-right", FG_DIM)

    def _sources(self, items):
        sig = tuple((i["id"], i["name"], i["enabled"], i["locked"]) for i in items)
        if getattr(self, "_src_sig", None) == sig: return
        self._src_sig = sig
        while self.sl.count():
            w = self.sl.takeAt(0).widget()
            if w: w.deleteLater()
        if not items:
            l = QLabel("No sources in this scene"); l.setObjectName("dim"); self.sl.addWidget(l); return
        for it in items:
            row = QWidget(); h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
            on, lk = it["enabled"], it["locked"]
            eye = tool_button("eye" if on else "eye-off-outline", "Hide source" if on else "Show source")
            lock = tool_button("lock" if lk else "lock-open-variant-outline", "Unlock source" if lk else "Lock source (stops accidental moves in OBS)")
            name = QLabel(it["name"] + ("  (group)" if it["group"] else "")); name.setToolTip(it["name"])
            name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            if not on: name.setStyleSheet("color:#6f6f6f;")
            eye.clicked.connect(lambda _=False, i=it["id"], e=on: self.svc.set_item_enabled(i, not e))
            lock.clicked.connect(lambda _=False, i=it["id"], l=lk: self.svc.set_item_locked(i, not l))
            h.addWidget(eye); h.addWidget(name, 1); h.addWidget(lock); self.sl.addWidget(row)

    def _preview_interval(self) -> int:
        return self.cfg.preview_delay()                 # validated 100-5000 ms

    def _preview_sub(self) -> str:
        ms = self.svc.preview_ms
        return f"Snapshot every {self._preview_interval()} ms" + (f" - last frame {ms:.0f} ms" if ms else "") + " (not live video)"

    def apply_preview(self):
        """Apply a changed processing time immediately: only the timer interval changes (no restart, no player reload)."""
        if self._preview_on and self.isVisible():
            self.pv.start(self._preview_interval()); self.svc.request_preview()
        self.prev_row.set_texts(sub=self._preview_sub())

    def _set_preview(self, data: bytes):
        pm = QPixmap(); pm.loadFromData(data)
        if not pm.isNull(): self.prev_lab.setPixmap(pm.scaledToWidth(self.width() - 32, Qt.SmoothTransformation))
        self.prev_row.set_texts(sub=self._preview_sub())

    def on_notify(self, level, text):
        if self.cfg["notifications"]: self.toast.show_msg(level, text, float(self.cfg["notification_seconds"]))

    # ---- state sync --------------------------------------------------------
    def sync(self):
        s, svc = self.svc.snap, self.svc
        col = {"connected": "#3ecf8e", "demo": "#4aa3ff", "connecting": "#e6b800"}.get(svc.status, "#e5534b")
        self.dot.setStyleSheet(f"background:{col}; border-radius:5px;"); self.dot.setToolTip(svc.status_text + (f"\n{svc.error}" if svc.error else ""))
        ok = svc.ok
        for r in (self.rec, self.rep, self.save, self.shot, self.live, self.scene_row, self.mix, self.prev_row, self.src_row):
            r.setEnabled(ok)
        rec = s.get("recording")
        self.rec.set_icon("stop-circle-outline" if rec else "record-circle-outline", "#ff5c5c" if rec else "#f2f2f2")
        self.rec.set_right_icon("stop" if rec else "play")
        self.rec.set_texts("Stop recording" if rec else "Record", self._rec_sub())
        replay_ok = s.get("replay_available", True)
        self.rep.set_texts("Instant Replay", ("On - last %ds" % int(self.cfg["replay_seconds"])) if s.get("replay_active") else
                           ("Off" if replay_ok else "Unavailable: enable Replay Buffer in OBS settings"))
        self.rep.set_icon("replay", "#4cc38a" if s.get("replay_active") else "#f2f2f2"); self.rep.setEnabled(ok and replay_ok)
        self.save.setEnabled(ok and bool(s.get("replay_active")))
        self.save.set_texts(sub=self._hint("replay_save") if s.get("replay_active") else "Turn on Instant Replay first")
        self.shot.set_texts(sub=f"{self._hint('screenshot')} - OBS scene output")
        live = s.get("streaming")
        self.live.set_texts("Stop streaming" if live else "Start streaming", self._stream_sub())
        self.live.set_icon("broadcast", "#ff5c5c" if live else "#f2f2f2"); self.live.set_right_icon("stop" if live else "play")
        self.scene_box.blockSignals(True); self.scene_box.clear(); self.scene_box.addItems(s.get("scenes", []))
        if s.get("scene"): self.scene_box.setCurrentText(s["scene"])
        self.scene_box.blockSignals(False)
        self.scene_row.set_texts(sub="" if ok else "Not connected")
        self._mixer(s.get("inputs", []))
        self.stat_row.set_texts(sub=("On" if self.cfg["stats_visible"] else "Off") + " - floating stats and web docks")
        items = s.get("items", []); self._sources(items)
        self.src_row.set_texts(sub=f"{len(items)} in '{s.get('scene', '')}'" if ok else "Not connected")
        self.src_row.set_right_icon("chevron-down" if self.srcbox.isVisible() else "chevron-right", FG_DIM)
        self.pause.setVisible(bool(rec)); self.pause.setEnabled(ok)
        self.pause.set_texts("Resume recording" if s.get("paused") else "Pause recording", "Pauses the OBS recording file")
        vc = s.get("vcam")
        self.vcam.set_texts(sub="On" if vc else ("Off" if vc is not None else "Unavailable in this OBS"))
        self.vcam.set_icon("webcam", "#4cc38a" if vc else "#f2f2f2"); self.vcam.setEnabled(ok and vc is not None)
        err = f" - {svc.error}" if svc.error and not ok else ""
        self.footer.setText(f"{svc.status_text}{err}  |  {s.get('version', '')}".strip(" |"))
        (self.tick.start() if (rec or live) else self.tick.stop())

    def _hint(self, action): return self.hints(action)

    def _rec_sub(self):
        s = self.svc.snap
        if not s.get("recording"): return self._hint("record") + " - start"
        t = fmt_elapsed(s.get("rec_dur", 0)); sz = gallery.fmt_size(s.get("rec_bytes", 0))
        return f"{'Paused' if s.get('paused') else 'REC'} {t} - {sz}"

    def _stream_sub(self):
        s = self.svc.snap
        if not s.get("streaming"): return "Uses the service configured in OBS (stream key never shown)"
        br = s.get("bitrate_kbps"); dp = s.get("dropped_pct")
        return f"LIVE {fmt_elapsed(s.get('stream_dur', 0))} - {f'{br:.0f} kbps' if br else 'bitrate n/a'} - dropped {f'{dp:.1f}%' if dp is not None else 'n/a'}"

    def _tick(self):
        s = self.svc.snap; now = 0.5
        if s.get("recording") and not s.get("paused"): s["rec_dur"] = s.get("rec_dur", 0) + now   # smooth timer between refreshes
        if s.get("streaming"): s["stream_dur"] = s.get("stream_dur", 0) + now
        self.rec.set_texts(sub=self._rec_sub()); self.live.set_texts(sub=self._stream_sub())

    def _toggle_mixer(self):
        self.mixer.setVisible(not self.mixer.isVisible())
        self.mix.set_right_icon("chevron-down" if self.mixer.isVisible() else "chevron-right", FG_DIM)

    def _mute_clicked(self, name):
        # Always toggle from the REAL OBS state (not from a local flag) so the control can never desynchronize.
        cur = next((i["muted"] for i in self.svc.snap.get("inputs", []) if i["name"] == name), False)
        self.svc.set_mute(name, not cur)

    def _source_menu(self, name, pos):
        m = QMenu(self)
        m.addAction("Use as microphone", lambda: self.svc.set_role("mic", name))
        m.addAction("Use as desktop audio", lambda: self.svc.set_role("desktop", name))
        m.addAction("Auto-detect microphone / desktop", lambda: (self.svc.set_role("mic", ""), self.svc.set_role("desktop", "")))
        m.exec(pos)

    def _mixer(self, inputs):
        sig = tuple(i["name"] for i in inputs)
        if getattr(self, "_mix_sig", None) != sig:
            while self.ml.count():
                w = self.ml.takeAt(0).widget()
                if w: w.deleteLater()
            self._rows = {}
            if not inputs:
                l = QLabel("No audio sources found" if self.svc.ok else "Not connected"); l.setObjectName("dim"); self.ml.addWidget(l)
            for i in inputs:
                n = i["name"]
                box = QWidget(); bv = QVBoxLayout(box); bv.setContentsMargins(0, 2, 0, 2); bv.setSpacing(2)
                head = QHBoxLayout(); head.setSpacing(6)
                mute = tool_button("volume-high", "Mute", size=16)
                dot = QLabel(); dot.setFixedSize(8, 8)
                name = QLabel(n); name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                name.setToolTip("Right-click to use this source as microphone or desktop audio"); name.setContextMenuPolicy(Qt.CustomContextMenu)
                name.customContextMenuRequested.connect(lambda p, nm=n, w=name: self._source_menu(nm, w.mapToGlobal(p)))
                head.addWidget(mute); head.addWidget(name, 1); head.addWidget(dot)
                bar = LevelBar(); dot.setStyleSheet("background:#444; border-radius:4px;")
                sl = QSlider(Qt.Horizontal); sl.setRange(-60, 0); sl.setToolTip("Volume (dB)")
                sl.valueChanged.connect(lambda val, nm=n: self.svc.set_volume_db(nm, float(val)))
                mute.clicked.connect(lambda _=False, nm=n: self._mute_clicked(nm))
                bv.addLayout(head); bv.addWidget(bar); bv.addWidget(sl); self.ml.addWidget(box)
                self._rows[n] = dict(mute=mute, dot=dot, name=name, bar=bar, slider=sl, active_until=0.0, lit=False)
            self._mix_sig = sig
        s = self.svc.snap
        for i in inputs:
            r = self._rows.get(i["name"])
            if not r: continue
            muted = i["muted"]
            r["mute"].setIcon(icon("volume-off" if muted else "volume-high", "#ff7b7b" if muted else "#f2f2f2"))
            r["mute"].setToolTip("Unmute" if muted else "Mute"); r["mute"].setAccessibleName(r["mute"].toolTip())
            tags = [t for t in ("mic", "desktop") if s.get(t) == i["name"]]
            r["name"].setText(i["name"] + (f"  ({', '.join(tags)})" if tags else ""))
            r["name"].setStyleSheet("color:#6f6f6f;" if muted else "")
            sl = r["slider"]
            if not sl.isSliderDown():
                sl.blockSignals(True); sl.setValue(int(max(-60, min(0, i["db"])))); sl.blockSignals(False)
        self._update_meters()

    def _update_meters(self):
        """New real OBS meter data (about 20/s): only sets targets; the meter timer animates smoothly towards them."""
        rows = getattr(self, "_rows", None)
        if not rows or not self.isVisible(): return
        on = bool(self.cfg["audio_detect"]) and self.svc.status == "connected"
        levels, now = self.svc.meters, time.monotonic()
        for n, r in rows.items():
            r["bar"].setVisible(on); r["dot"].setVisible(on)
            if not on: continue
            lv = levels.get(n)
            r["bar"].set_target(float(audio.level_percent(lv)) if lv is not None else 0.0)
            if audio.is_active(lv): r["active_until"] = now + 0.35          # short hold: no flicker between peaks
            r["dot"].setToolTip("Audio detected" if audio.is_active(lv) else ("No signal" if lv is not None else "No level data from OBS yet"))
        if on and not self._meter_timer.isActive():
            self._meter_t = now; self._meter_timer.start(20)                # ~50 fps while something is moving

    def _meter_tick(self):
        rows = getattr(self, "_rows", None)
        if not rows or not self.isVisible():
            self._meter_timer.stop(); return
        now = time.monotonic(); dt = min(0.1, now - self._meter_t); self._meter_t = now
        moving = False
        for r in rows.values():
            if r["bar"].isVisible(): moving |= r["bar"].step(dt)
            lit = now < r["active_until"]
            if lit != r["lit"]:
                r["lit"] = lit; r["dot"].setStyleSheet(f"background:{'#4cc38a' if lit else '#444'}; border-radius:4px;")
            moving |= lit
        if not moving: self._meter_timer.stop()                            # fully at rest: no timer, no CPU
