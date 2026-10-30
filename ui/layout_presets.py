"""Layout presets in the UI: one controller (all actions + feedback) and one reusable panel (the list), used both inside
the overlay's Widgets page and in the layout editor toolbar, so they always show the same state."""
from __future__ import annotations
import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from core.layouts import MAX_NAME, PresetError, PresetStore
from . import dialogs
from .common import FG_DIM, Row, icon, tool_button


class PresetNameDialog(QDialog):
    """Asks for a preset name with live validation (empty / too long / duplicate) and keyboard support:
    focus starts in the field, Enter saves, Esc cancels, and Save stays disabled while the name is invalid."""

    def __init__(self, store: PresetStore, title: str, text: str = "", exclude_id: str | None = None, ok_label: str = "Save"):
        super().__init__(None)
        self.store, self.exclude_id, self.result_name = store, exclude_id, ""
        self.setWindowTitle(title); self.setModal(True); self.setMinimumWidth(340)
        lay = QVBoxLayout(self); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(8)
        lab = QLabel("Preset name"); lab.setObjectName("settingTitle")
        self.edit = QLineEdit(text, self); self.edit.setMaxLength(MAX_NAME); self.edit.setPlaceholderText("For example: Streaming, Gaming, Minimal")
        self.edit.setAccessibleName("Preset name")
        self.err = QLabel("", self); self.err.setStyleSheet("color:#ff7b7b"); self.err.setWordWrap(True); self.err.setMinimumHeight(18)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.ok = self.buttons.button(QDialogButtonBox.Ok); self.ok.setText(ok_label); self.ok.setObjectName("primary"); self.ok.setDefault(True)
        self.buttons.accepted.connect(self._accept); self.buttons.rejected.connect(self.reject)
        for w in (lab, self.edit, self.err, self.buttons): lay.addWidget(w)
        self.edit.textChanged.connect(self._check); self.edit.returnPressed.connect(self._accept)
        self._check(); self.edit.selectAll(); self.edit.setFocus()
        dialogs.prepare_dialog(self)

    def _check(self, *_):
        try:
            self.store.validate_name(self.edit.text(), self.exclude_id); self.err.setText(""); self.ok.setEnabled(True)
        except PresetError as e:
            self.err.setText(str(e) if self.edit.text().strip() else ""); self.ok.setEnabled(False)

    def _accept(self):
        if not self.ok.isEnabled(): return
        self.result_name = self.edit.text(); self.accept()


class PresetController(QObject):
    """Every preset action lives here (save, load, rename, overwrite, delete), with confirmations and feedback.
    Nothing ever writes to a preset except an explicit Save / Update, so switching presets can never overwrite another."""
    changed = Signal()

    def __init__(self, mgr, svc):
        super().__init__()
        self.mgr, self.svc = mgr, svc
        self.store = PresetStore(svc.cfg)
        mgr.layout_changed.connect(self.changed.emit); mgr.changed.connect(self.changed.emit)

    # ---- state ------------------------------------------------------------------
    def is_modified(self) -> bool:
        return self.store.is_modified(self.mgr.current_layout())

    def status_text(self) -> str:
        a = self.store.active
        if not a: return "No preset active"
        return f"Active: {a['name']}" + ("  (modified)" if self.is_modified() else "")

    def _say(self, level: str, text: str): self.svc.say(level, text)

    # ---- actions ----------------------------------------------------------------
    def save_new(self):
        dlg = PresetNameDialog(self.store, "Save layout as preset")
        if dlg.exec() != QDialog.Accepted: return
        try:
            p = self.store.create(dlg.result_name, self.mgr.current_layout())
        except PresetError as e:
            dialogs.message(None, "Cannot save preset", str(e)); return
        self._say("success", f"Preset \"{p['name']}\" saved"); self.changed.emit()

    def load(self, pid: str):
        p = self.store.get(pid)
        if not p: self._say("error", "That preset no longer exists"); self.changed.emit(); return
        a = self.store.active
        if a and a["id"] != pid and self.is_modified() and not dialogs.confirm(
                None, "Unsaved layout changes", f"You changed the layout since loading \"{a['name']}\".\n"
                f"Load \"{p['name']}\" anyway? The changes are not saved to \"{a['name']}\"."):
            return
        self.mgr.apply_layout(p["layout"]); self.store.set_active(pid)
        self._say("info", f"Preset \"{p['name']}\" loaded"); self.changed.emit()

    def rename(self, pid: str):
        p = self.store.get(pid)
        if not p: return
        dlg = PresetNameDialog(self.store, "Rename preset", p["name"], exclude_id=pid, ok_label="Rename")
        if dlg.exec() != QDialog.Accepted: return
        old = p["name"]
        try:
            self.store.rename(pid, dlg.result_name)
        except PresetError as e:
            dialogs.message(None, "Cannot rename preset", str(e)); return
        self._say("success", f"Preset \"{old}\" renamed to \"{self.store.get(pid)['name']}\""); self.changed.emit()

    def overwrite(self, pid: str):
        p = self.store.get(pid)
        if not p: return
        if not dialogs.confirm(None, "Update preset", f"Replace the saved layout of \"{p['name']}\" with the current layout?"): return
        try:
            self.store.overwrite(pid, self.mgr.current_layout())
        except PresetError as e:
            dialogs.message(None, "Cannot update preset", str(e)); return
        self._say("success", f"Preset \"{p['name']}\" updated"); self.changed.emit()

    def delete(self, pid: str):
        p = self.store.get(pid)
        if not p: return
        if not dialogs.confirm(None, "Delete preset", f"Delete the preset \"{p['name']}\"? This cannot be undone.", danger=True): return
        self.store.delete(pid); self._say("success", f"Preset \"{p['name']}\" deleted"); self.changed.emit()


class PresetPanel(QWidget):
    """The preset list: click (or Enter) a row to load it; rename / update / delete buttons on each row."""

    def __init__(self, ctl: PresetController, max_list_height: int = 230, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        head = QHBoxLayout(); head.setSpacing(8)
        title = QLabel("LAYOUT PRESETS", self); title.setObjectName("sectionTitle")
        self.save_btn = QPushButton("Save current layout...", self); self.save_btn.setObjectName("primary")
        self.save_btn.setToolTip("Save the widgets' current arrangement as a new preset"); self.save_btn.clicked.connect(ctl.save_new)
        head.addWidget(title); head.addStretch(1); head.addWidget(self.save_btn)
        self.status = QLabel("", self); self.status.setObjectName("dim"); self.status.setWordWrap(True)
        self.host = QWidget(); self.hl = QVBoxLayout(self.host); self.hl.setContentsMargins(0, 0, 0, 0); self.hl.setSpacing(2)
        sc = QScrollArea(self); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame); sc.setWidget(self.host)
        sc.setMaximumHeight(max_list_height); sc.setMinimumHeight(70)
        lay.addLayout(head); lay.addWidget(self.status); lay.addWidget(sc)
        ctl.changed.connect(self.rebuild); self.rebuild()

    @staticmethod
    def _when(ts: float) -> str:
        return time.strftime("%d %b %H:%M", time.localtime(ts)) if ts else ""

    def rebuild(self):
        c = self.ctl; store = c.store
        while self.hl.count():
            item = self.hl.takeAt(0); w = item.widget()
            if w: w.setParent(None); w.deleteLater()
        self.status.setText(c.status_text())
        if not store.presets:
            empty = QLabel("No presets yet. Arrange your widgets, then press \"Save current layout...\".", self.host)
            empty.setObjectName("dim"); empty.setWordWrap(True); self.hl.addWidget(empty)
        active, modified = store.active, c.is_modified()
        for p in store.presets:
            is_active = bool(active) and active["id"] == p["id"]
            n = len(p["layout"]["widgets"])
            sub = (("Active - modified" if modified else "Active") + " - " if is_active else "") + f"{n} widget{'s' if n != 1 else ''}"
            if p["updated"]: sub += f" - saved {self._when(p['updated'])}"
            row = Row("radiobox-marked" if is_active else "radiobox-blank", p["name"], sub, chevron=False,
                      tooltip=f"Load \"{p['name']}\" (Enter)", parent=self.host)
            if is_active: row.set_icon("radiobox-marked", c.svc.cfg["accent"])
            else: row.set_icon("radiobox-blank", FG_DIM)
            row.setAccessibleName(f"Preset {p['name']}" + (", active" if is_active else ""))
            row.clicked.connect(lambda pid=p["id"]: c.load(pid))
            for ico, tip, fn in (("pencil-outline", "Rename preset", c.rename),
                                 ("content-save-outline", "Update: overwrite this preset with the current layout", c.overwrite),
                                 ("trash-can-outline", "Delete preset", c.delete)):
                b = tool_button(ico, tip, size=16); b.clicked.connect(lambda _=False, f=fn, pid=p["id"]: f(pid)); row.add_tail(b)
            self.hl.addWidget(row)
        self.hl.addStretch(1)
