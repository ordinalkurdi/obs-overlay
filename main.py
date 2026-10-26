"""OBS OVERLAY - entry point.   python main.py [--demo]"""
from __future__ import annotations
import sys
import time
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from core.config import HOTKEY_LABELS, Settings, data_dir
from core.hotkeys import HotkeyManager
from core.service import ObsService
from ui import dialogs
from ui.common import stylesheet
from ui.gallery_view import GalleryWindow, ImageViewer, MediaStore, PlayerWindow
from ui.overlay import Overlay
from ui.widgets_dock import WidgetManager, WidgetsPage
from ui.settings import SettingsDialog


def app_icon() -> QIcon:
    pm = QPixmap(64, 64); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setBrush(QColor("#303030")); p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14); p.setBrush(QColor("#e5534b")); p.drawEllipse(18, 18, 28, 28); p.end()
    return QIcon(pm)


class App:
    def __init__(self, demo: bool):
        self.qt = QApplication(sys.argv); self.qt.setQuitOnLastWindowClosed(False); self.qt.setApplicationName("OBS Overlay")
        self.cfg = Settings()
        if demo: self.cfg["mode"] = "demo"
        self._css = stylesheet(self.cfg); self.qt.setStyleSheet(self._css); self.qt.setWindowIcon(app_icon())
        self.svc = ObsService(self.cfg); self.store = MediaStore(self.cfg)
        self.hk = HotkeyManager()
        self.overlay = Overlay(self.svc, self.store, self.hint)
        dialogs.set_screen_provider(self.overlay._screen)       # popups/notifications appear centered on the overlay's monitor
        self.widgets = WidgetManager(self.svc); self.widgets_page = WidgetsPage(self.widgets)
        self.overlay.set_widgets_page(self.widgets_page)
        self.player = PlayerWindow(); self.gallery = GalleryWindow(self.store); self.overlay.set_gallery(self.gallery)
        self._wire(); self._tray()
        self.hk.apply(self.cfg["hotkeys"]); self._conn_sig = self._conn_signature()
        self._gal_sig = self._gallery_signature(); self._hk_sig = self._hotkey_signature()
        self.store.rescan(); self.widgets.apply()
        if not self.cfg["start_hidden"]: self.overlay.show_panel()
        if self.cfg["connect_on_start"] or self.cfg["mode"] == "demo": self.svc.connect_backend()
        self.qt.aboutToQuit.connect(self.cleanup)
        sys.excepthook = self._excepthook

    def _excepthook(self, etype, value, tb):
        """A windowed exe has no console: log unexpected errors to error.log and tell the user instead of failing silently."""
        text = "".join(traceback.format_exception(etype, value, tb))
        try:
            with open(data_dir() / "error.log", "a", encoding="utf-8") as f:
                f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n") + text + "\n")
        except OSError:
            pass
        sys.__excepthook__(etype, value, tb)
        try:
            self.svc.say("error", f"Unexpected error: {etype.__name__}: {value}  (details: error.log)")
        except Exception:
            pass

    def hint(self, action: str) -> str:
        return self.cfg["hotkeys"].get(action) or "no shortcut"

    def _wire(self):
        o, s = self.overlay, self.svc
        o.open_settings.connect(self.show_settings); o.gal_row.clicked.connect(self.show_gallery)
        o.strip.activated.connect(self.open_media); self.gallery.open_media.connect(self.open_media)
        o.stat_row.clicked.connect(self.show_widgets); s.state_changed.connect(self.widgets.refresh)
        s.media_created.connect(lambda _p: self.store.rescan())
        self.hk.triggered.connect(self.on_hotkey)

    def _tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self.qt); self.tray.setToolTip("OBS Overlay")
        m = QMenu(); m.addAction("Show / hide overlay", self.overlay.toggle_visible); m.addAction("Gallery", self.show_gallery)
        m.addAction("Settings", self.show_settings)
        m.addAction("Widgets: turn off click-through", lambda: self.widgets.set_click_through_all(False)); m.addSeparator(); m.addAction("Quit", self.qt.quit)
        self.tray.setContextMenu(m); self.tray.activated.connect(lambda r: self.overlay.toggle_visible() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def on_hotkey(self, a: str):
        s, o = self.svc, self.overlay
        {"toggle_overlay": o.toggle_visible, "record": o._rec_clicked, "replay_toggle": s.toggle_replay, "replay_save": s.save_replay,
         "screenshot": s.screenshot, "mic_mute": lambda: s.toggle_mute_role("mic"), "desktop_mute": lambda: s.toggle_mute_role("desktop"),
         "stats": self.toggle_stats, "widgets_click": self.widgets.toggle_click_through_all}[a]()

    def toggle_stats(self):
        self.cfg["stats_visible"] = not self.cfg["stats_visible"]; self.cfg.save(); self.widgets.apply(); self.svc.refresh(); self.overlay.sync()

    def open_media(self, path: str):
        import os
        if not os.path.exists(path):
            self.svc.say("error", "File no longer exists"); self.store.rescan(); return
        if path.lower().endswith((".png", ".jpg", ".jpeg")): ImageViewer(path, self.overlay).exec()
        else: self.player.open(path)

    def show_widgets(self):
        self.overlay.show_panel(); self.overlay.show_page("widgets")

    def show_gallery(self):
        self.overlay.show_panel(); self.overlay.show_page("gallery")

    def show_settings(self):
        d = SettingsDialog(self.svc, lambda: self.hk.failed, parent=self.overlay.stack)   # child of the panel from the start: never a top-level window
        d.applied.connect(self.on_applied); d.clear_history.connect(self.store.clear_history); d.closed.connect(self.overlay.drop_settings)
        self.overlay.show_panel(); self.overlay.set_settings_page(d)

    def _conn_signature(self):
        c = self.cfg
        return (c["mode"], c["host"], c["port"], c["timeout"], c["remote_allowed"], c["audio_detect"], c.get_password())

    def _gallery_signature(self):
        c = self.cfg
        return (c["gallery_root"], c["screenshot_dir"], c["hide_filenames"], c["thumb_size"])

    def _hotkey_signature(self):
        return repr(sorted(self.cfg["hotkeys"].items()))

    def on_applied(self):
        """Called after every settings change (settings apply live), so only redo expensive work when its inputs changed."""
        css = stylesheet(self.cfg)
        if css != self._css: self._css = css; self.qt.setStyleSheet(css)        # re-styling every widget is costly: only when it changed
        self.overlay.apply_settings(); self.widgets.apply()
        gs = self._gallery_signature()
        if gs != self._gal_sig: self._gal_sig = gs; self.store.rescan()
        hs = self._hotkey_signature()
        if hs != self._hk_sig:
            self._hk_sig = hs; self.hk.apply(self.cfg["hotkeys"])
            if self.hk.failed: self.svc.say("warn", "Some shortcuts could not be registered - see Settings > Hotkeys")
        self.overlay.apply_preview()                    # new preview processing time: timer only, nothing restarts
        sig = self._conn_signature()
        if sig != self._conn_sig:                       # re-connect to OBS only when connection-related settings changed
            self._conn_sig = sig; self.svc.connect_backend()

    def cleanup(self):
        self.hk.stop(); self.svc.shutdown(); self.cfg.save()

    def run(self) -> int:
        return self.qt.exec()


if __name__ == "__main__":
    sys.exit(App(demo="--demo" in sys.argv).run())
