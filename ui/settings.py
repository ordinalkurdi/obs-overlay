from __future__ import annotations
import json
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget,
                               QVBoxLayout, QWidget, QKeySequenceEdit, QColorDialog, QScrollArea, QFrame)

from core import config
from core.config import HOTKEY_LABELS, Settings
from core.hotkeys import find_conflicts
from core.service import ObsService

METRICS = {"recording": "Recording status/time", "streaming": "Streaming status/time", "bitrate": "Bitrate",
           "dropped": "Dropped frames", "resolution": "Output resolution", "fps": "FPS", "cpu": "System CPU",
           "memory": "System RAM", "replay": "Replay buffer", "connection": "OBS connection"}


class SettingsDialog(QDialog):
    applied = Signal()
    clear_history = Signal()
    closed = Signal()

    def __init__(self, svc: ObsService, hotkey_failures: callable, parent=None):
        super().__init__(parent); self.setWindowFlags(Qt.Widget)     # embedded as a page of the overlay
        self.svc, self.cfg, self.failures = svc, svc.cfg, hotkey_failures
        self.getters: dict[str, callable] = {}; self.rows: list[tuple[QFormLayout, int, str]] = []
        self.search = QLineEdit(); self.search.setPlaceholderText("Search settings..."); self.search.setClearButtonEnabled(True)
        self.cats = QComboBox(); self.stack = QStackedWidget(); self.page_of: dict = {}
        lay = QVBoxLayout(); lay.addWidget(self.search); lay.addWidget(self.cats); lay.addWidget(self.stack, 1)
        ok, cancel = QPushButton("Save"), QPushButton("Cancel"); ok.setObjectName("primary")
        bl = QHBoxLayout(); bl.addStretch(); bl.addWidget(cancel); bl.addWidget(ok)
        root = QVBoxLayout(self); root.addLayout(lay, 1); root.addLayout(bl)
        for name, fn in (("General", self._general), ("OBS connection", self._obs), ("Recording & replay", self._capture),
                         ("Gallery & screenshots", self._gallery), ("Statistics", self._stats), ("Hotkeys", self._hotkeys),
                         ("Privacy", self._privacy), ("Advanced", self._advanced)):
            form = QFormLayout(); form.setRowWrapPolicy(QFormLayout.WrapAllRows); w = QWidget(); w.setLayout(form)
            sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame); sc.setWidget(w)
            self.stack.addWidget(sc); self.cats.addItem(name); self.page_of[id(form)] = self.stack.count() - 1; fn(form)
        self.cats.currentIndexChanged.connect(self.stack.setCurrentIndex); self.cats.setCurrentIndex(0)
        self.search.textChanged.connect(self._filter); ok.clicked.connect(self._save); cancel.clicked.connect(self.reject)

    # ---- helpers -----------------------------------------------------------
    def _add(self, form, label, widget, key=None, getter=None, tip=""):
        form.addRow(label, widget); self.rows.append((form, form.rowCount() - 1, label.lower() + " " + tip.lower()))
        if tip: widget.setToolTip(tip)
        if key: self.getters[key] = getter

    def _check(self, form, label, key, tip=""):
        w = QCheckBox(); w.setChecked(bool(self.cfg[key])); self._add(form, label, w, key, w.isChecked, tip); return w

    def _spin(self, form, label, key, lo, hi, step=1, dbl=False, tip=""):
        w = QDoubleSpinBox() if dbl else QSpinBox(); w.setRange(lo, hi); w.setSingleStep(step); w.setValue(self.cfg[key])
        self._add(form, label, w, key, w.value, tip); return w

    def _combo(self, form, label, key, items, tip=""):
        w = QComboBox(); w.addItems([str(i) for i in items]); w.setCurrentText(str(self.cfg[key]))
        conv = type(items[0]); self._add(form, label, w, key, lambda: conv(w.currentText()), tip); return w

    def _text(self, form, label, key, tip="", browse=False):
        w = QLineEdit(self.cfg[key] or ""); box = w
        if browse:
            box = QWidget(); h = QHBoxLayout(box); h.setContentsMargins(0, 0, 0, 0); b = QPushButton("Browse...")
            b.clicked.connect(lambda: w.setText(QFileDialog.getExistingDirectory(self, label, w.text()) or w.text())); h.addWidget(w, 1); h.addWidget(b)
        self._add(form, label, box, key, w.text, tip); return w

    def _note(self, form, text):
        l = QLabel(text); l.setWordWrap(True); l.setObjectName("dim"); form.addRow(l)

    def _filter(self, text):
        t = text.lower().strip(); first = None
        for form, idx, hay in self.rows:
            vis = (not t) or t in hay
            form.setRowVisible(idx, vis)
            if vis and t and first is None: first = self.page_of.get(id(form))
        if first is not None: self.cats.setCurrentIndex(first)       # jump to the first page with a match

    # ---- pages -------------------------------------------------------------
    def _general(self, f):
        self._combo(f, "Window mode", "dock_mode", ["docked", "floating"], "Docked = panel slides out from a monitor edge")
        self._combo(f, "Dock side", "dock_side", ["right", "left"])
        self._combo(f, "Monitor", "monitor", list(range(max(1, len(QGuiApplication.screens())))), "Index in the OS monitor list (0 = first)")
        self._spin(f, "Panel height (px, 0 = full height)", "dock_height", 0, 4000, 10, tip="Also resizable by dragging the panel edges")
        self._combo(f, "Vertical position", "dock_valign", ["center", "top", "bottom", "custom"], "Dragging the header up/down sets 'custom'")
        self._spin(f, "Custom vertical offset (px from top)", "dock_y", 0, 4000, 10)
        self._spin(f, "Gap to screen edge (px, 0 = flush)", "dock_gap", 0, 300, 2)
        self._spin(f, "Row spacing (UI density)", "row_pad", 2, 20, 1)
        self._check(f, "Slide out when mouse hits the screen edge", "edge_reveal", "A 3px invisible strip at the edge; turn off if it interferes with games")
        self._check(f, "Slide away when mouse leaves (unless pinned)", "dock_autohide")
        self._spin(f, "Slide animation (ms, 0 = off)", "anim_ms", 0, 1000, 20)
        self._spin(f, "Overlay opacity", "opacity", 0.3, 1.0, 0.02, True)
        self._spin(f, "Panel width (px)", "width", 320, 1600, 10, tip="You can also drag the panel edges/corners to resize it")
        self._check(f, "Always on top", "always_on_top", "Keeps the overlay above other windows (borderless-windowed games)")
        self._check(f, "Start hidden (tray only)", "start_hidden")
        self._spin(f, "Auto-hide after (s, 0=off)", "auto_hide_seconds", 0, 600)
        self._spin(f, "Font size", "font_size", 10, 20); self._spin(f, "Corner radius", "radius", 0, 24)
        self._check(f, "Show notifications", "notifications"); self._spin(f, "Notification duration (s)", "notification_seconds", 1, 15, 1)
        btn = QPushButton(self.cfg["accent"]); btn.setToolTip("Accent color")
        def pick():
            c = QColorDialog.getColor(parent=self)
            if c.isValid(): btn.setText(c.name())
        btn.clicked.connect(pick); self._add(f, "Accent color", btn, "accent", btn.text)
        self._note(f, "True exclusive-fullscreen games cannot show a normal desktop window on top. Use borderless/windowed-fullscreen mode in the game.")

    def _obs(self, f):
        mode = QComboBox(); mode.addItems(["obs", "demo"]); mode.setCurrentText(self.cfg["mode"])
        self._add(f, "Mode", mode, "mode", mode.currentText, "'demo' runs a simulation without OBS")
        self._text(f, "Host", "host"); self._spin(f, "Port", "port", 1, 65535)
        self.pw = QLineEdit(); self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("saved - leave empty to keep" if self.cfg.has_password() else "WebSocket password (optional)")
        self._add(f, "Password", self.pw)
        self._spin(f, "Timeout (s)", "timeout", 1, 30); self._check(f, "Auto-reconnect", "auto_reconnect")
        self._check(f, "Connect on startup", "connect_on_start")
        self._check(f, "Allow remote (non-local) OBS hosts", "remote_allowed", "Off by default for privacy")
        self.res = QLabel(""); self.res.setWordWrap(True)
        test = QPushButton("Test connection"); test.clicked.connect(self._test); f.addRow(test, self.res)
        clear = QPushButton("Forget saved password"); clear.clicked.connect(self._forget); f.addRow(clear)
        self._note(f, ("Password is kept in the OS credential store." if Settings.keyring_available() else
                       "No OS credential store available: the password is kept in memory for this session only, never on disk."))
        self._note(f, "Enable the server in OBS: Tools > WebSocket Server Settings (default port 4455).")

    def _test(self):
        pw = self.pw.text() or self.cfg.get_password(); self.res.setText("Testing...")
        host = self.getters["host"](); port = self.getters["port"]()
        self.svc.test_connection(host, port, pw, lambda r, e: self.res.setText(f"OK - OBS {r}" if not e else f"Failed: {e}"))

    def _forget(self):
        self.cfg.set_password(""); self.pw.setPlaceholderText("WebSocket password (optional)")

    def _capture(self, f):
        self._combo(f, "Replay length (s)", "replay_seconds", [15, 30, 60, 120, 180, 300], "Applied via OBS profile (Simple output mode) when Instant Replay starts")
        self._check(f, "Confirm before stopping recording", "confirm_stop_record"); self._check(f, "Confirm before stopping stream", "confirm_stop_stream")
        self._note(f, "Recording format, encoder, quality, filename format and replay save path are configured in OBS (Settings > Output). "
                      "This build does not duplicate them, so no decorative switches are shown.")

    def _gallery(self, f):
        self._text(f, "Gallery folder (scanned recursively)", "gallery_root", "Per-game and replay subfolders are discovered automatically", True)
        self._text(f, "Screenshot folder", "screenshot_dir", browse=True)
        self._combo(f, "Screenshot format", "screenshot_format", ["png", "jpg"]); self._spin(f, "JPEG quality", "screenshot_quality", 1, 100)
        self._text(f, "Screenshot filename pattern", "screenshot_pattern", "strftime codes, e.g. Screenshot_%Y-%m-%d_%H-%M-%S")
        self._spin(f, "Thumbnail size", "thumb_size", 100, 260, 10)
        self._spin(f, "Preview refresh (per second)", "preview_fps", 1, 5); self._spin(f, "Preview width (px)", "preview_width", 160, 640, 20)
        self._note(f, "Screenshots capture the OBS scene output only.")

    def _stats(self, f):
        self._check(f, "Show statistics overlay", "stats_visible")
        self._combo(f, "Corner", "stats_corner", ["top-right", "top-left", "bottom-right", "bottom-left"])
        self._spin(f, "Update interval (ms)", "stats_interval_ms", 500, 10000, 100); self._spin(f, "Opacity", "stats_opacity", 0.3, 1.0, 0.05, True)
        self._spin(f, "Warn: dropped frames %", "stats_warn_dropped_pct", 0, 100, 0.5, True); self._spin(f, "Warn: system CPU %", "stats_warn_cpu_pct", 10, 100, 5, True)
        boxes = {}
        for k, lab in METRICS.items():
            c = QCheckBox(); c.setChecked(k in self.cfg["stats_metrics"]); boxes[k] = c; self._add(f, lab, c)
        self.getters["stats_metrics"] = lambda: [k for k, c in boxes.items() if c.isChecked()]
        self._note(f, "OBS-process CPU and GPU usage/temperature are not exposed by this build and are shown as Unavailable (not invented).")

    def _hotkeys(self, f):
        self.keys: dict[str, QKeySequenceEdit] = {}
        for a, lab in HOTKEY_LABELS.items():
            e = QKeySequenceEdit(QKeySequence(self.cfg["hotkeys"][a])); e.setMaximumSequenceLength(1)
            reset = QPushButton("Reset"); box = QWidget(); h = QHBoxLayout(box); h.setContentsMargins(0, 0, 0, 0); h.addWidget(e, 1); h.addWidget(reset)
            reset.clicked.connect(lambda _=False, ed=e, act=a: ed.setKeySequence(QKeySequence(config.DEFAULTS["hotkeys"][act])))
            self.keys[a] = e; self._add(f, lab, box)
        rst = QPushButton("Restore all default shortcuts")
        rst.clicked.connect(lambda: [e.setKeySequence(QKeySequence(config.DEFAULTS["hotkeys"][a])) for a, e in self.keys.items()]); f.addRow(rst)
        self.hk_msg = QLabel(); self.hk_msg.setWordWrap(True); f.addRow(self.hk_msg)
        bad = self.failures()
        if bad: self.hk_msg.setText("Could not register: " + "; ".join(f"{HOTKEY_LABELS[a]} ({m})" for a, m in bad.items()))
        self._note(f, "Shortcuts are global and passive: they are not blocked from the game.")

    def _privacy(self, f):
        self._check(f, "Hide filenames in gallery", "hide_filenames")
        b = QPushButton("Clear thumbnails & favorites"); b.clicked.connect(self.clear_history.emit); f.addRow(b)
        self._note(f, "No analytics or telemetry exist in this app. Media stays local; nothing is uploaded. Remote OBS hosts are blocked unless enabled under OBS connection.")

    def _advanced(self, f):
        v = self.svc.snap.get("version") or "not connected"
        self._note(f, f"Status: {self.svc.status_text}\nOBS: {v}\nCapabilities: {json.dumps(self.svc.snap.get('caps', {}))}\n"
                      f"Replay buffer available: {self.svc.snap.get('replay_available', 'unknown')}\nSettings file: {self.cfg.path}")
        ex, im, rs = QPushButton("Export settings..."), QPushButton("Import settings..."), QPushButton("Reset to defaults")
        ex.clicked.connect(lambda: (p := QFileDialog.getSaveFileName(self, "Export", "obs-overlay-settings.json", "JSON (*.json)")[0]) and self.cfg.export_to(p))
        def imp():
            p = QFileDialog.getOpenFileName(self, "Import", "", "JSON (*.json)")[0]
            if p:
                try: self.cfg.import_from(p); self.applied.emit(); self.accept()
                except Exception as e: QMessageBox.warning(self, "Import failed", str(e))
        def reset():
            if QMessageBox.question(self, "Reset", "Reset all settings (hotkeys included)?") == QMessageBox.Yes:
                self.cfg.reset(); self.applied.emit(); self.accept()
        im.clicked.connect(imp); rs.clicked.connect(reset)
        for b in (ex, im, rs): f.addRow(b)
        self._note(f, "Exported files never contain the OBS password.")
        log = QPlainTextEdit(); log.setReadOnly(True); log.setMaximumHeight(150)
        log.setPlainText("\n".join(f"{t}  [{l}]  {m}" for t, l, m in reversed(self.svc.notifications)) or "No notifications yet.")
        f.addRow(QLabel("Notification history"), log)

    # ---- save --------------------------------------------------------------
    def _save(self):
        binds = {a: e.keySequence().toString() for a, e in self.keys.items()}
        dup = find_conflicts(binds)
        if dup:
            names = "; ".join(" & ".join(HOTKEY_LABELS[a] for a in v) + f" -> {k}" for k, v in dup.items())
            self.hk_msg.setText("Conflict: " + names + ". Change one of them."); self.hk_msg.setStyleSheet("color:#ff7b7b")
            self.cats.setCurrentIndex(5); return
        for k, g in self.getters.items(): self.cfg[k] = g()
        self.cfg["hotkeys"] = binds
        if self.pw.text(): self.cfg.set_password(self.pw.text())
        self.cfg.save(); self.applied.emit(); self.accept()

    def accept(self): self.closed.emit()
    def reject(self): self.closed.emit()
