"""Layout edit mode, modelled on Discord's overlay layout editor: every widget gets a dashed outline and a small
chip under it (name, options, pin, hide); dragging shows snap guides and a drop indicator; a toolbar at the top of the
screen offers Widgets / Hide All / Reset Default Layout / Presets / Done."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from core.widget_rows import KINDS
from . import dialogs
from .common import icon, tool_button
from .layout_presets import PresetController, PresetPanel

_TOP = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint


def _screen_rect(point: QPoint) -> QRect:
    s = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    return s.availableGeometry()


class GuideOverlay(QWidget):
    """Click-through layer drawn on the screen while a widget is dragged: snap guide lines and the drop target."""

    def __init__(self, accent: str):
        super().__init__(None, _TOP | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.accent = QColor(accent); self.lines: list[tuple[str, int]] = []; self.target = QRect()

    def show_guides(self, screen_geo: QRect, guides, target: QRect):
        if self.geometry() != screen_geo: self.setGeometry(screen_geo)
        self.lines = [(o, p - (screen_geo.x() if o == "v" else screen_geo.y())) for o, p in guides]
        self.target = target.translated(-screen_geo.topLeft())
        if not self.isVisible(): self.show()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        fill = QColor(self.accent); fill.setAlpha(40); edge = QColor(self.accent); edge.setAlpha(230)
        p.setBrush(fill); p.setPen(QPen(edge, 2, Qt.DashLine)); p.drawRoundedRect(self.target.adjusted(1, 1, -1, -1), 10, 10)
        p.setPen(QPen(edge, 1, Qt.DashLine))
        for o, pos in self.lines:
            if o == "v": p.drawLine(pos, 0, pos, self.height())
            else: p.drawLine(0, pos, self.width(), pos)


class EditFrame(QWidget):
    """Dashed outline drawn over a widget while editing (never intercepts the mouse)."""

    def __init__(self, dock, accent: str):
        super().__init__(dock)
        self.setAttribute(Qt.WA_TransparentForMouseEvents); self.accent = QColor(accent); self.hide()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self.accent); c.setAlpha(230)
        p.setPen(QPen(c, 2, Qt.DashLine)); p.setBrush(Qt.NoBrush); p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)


class EditChip(QWidget):
    """Small pill under a widget showing only its name (options live on the widget's own button bar)."""

    def __init__(self, dock):
        super().__init__(None, _TOP | Qt.WindowDoesNotAcceptFocus)
        self.dock = dock
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)
        outer = QHBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame(self); frame.setObjectName("chip")
        frame.setStyleSheet("#chip{background:rgba(30,30,30,240);border:1px solid #3a3a3a;border-radius:12px;}")
        outer.addWidget(frame)
        h = QHBoxLayout(frame); h.setContentsMargins(10, 3, 10, 3); h.setSpacing(0)
        self.name = QLabel("", frame); self.name.setStyleSheet("font-weight:600;"); h.addWidget(self.name)

    def sync(self, editing: bool):
        d = self.dock
        self.name.setText(d.w.get("name") or KINDS[d.w["kind"]][0])
        self.adjustSize()
        show = editing and d.isVisible()
        if show: self.reposition()
        self.setVisible(show)
        if show: self.raise_()

    def reposition(self):
        g = self.dock.geometry(); sg = _screen_rect(g.center())
        x = max(sg.left(), min(g.left(), sg.right() - self.width() + 1)); y = g.bottom() + 6
        if y + self.height() > sg.bottom(): y = g.top() - self.height() - 6          # no room below: put it above
        if y < sg.top(): y = g.bottom() - self.height() - 6                          # no room above either: inside
        self.move(x, y)


class PresetFlyout(QWidget):
    """The preset list as a panel that hangs under the toolbar (stays open while dialogs are used)."""

    def __init__(self, ctl: PresetController):
        super().__init__(None, _TOP)
        self.setAttribute(Qt.WA_TranslucentBackground)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame(self); frame.setObjectName("flyout")
        frame.setStyleSheet("#flyout{background:rgba(24,24,24,244);border:1px solid #3a3a3a;border-radius:12px;}")
        outer.addWidget(frame); v = QVBoxLayout(frame); v.setContentsMargins(12, 10, 12, 12)
        v.addWidget(PresetPanel(ctl, max_list_height=300, parent=frame))
        self.setFixedWidth(400)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.hide)


class LayoutToolbar(QWidget):
    def __init__(self, ed: "LayoutEditor"):
        super().__init__(None, _TOP)
        self.ed = ed; mgr = ed.mgr
        self.setAttribute(Qt.WA_TranslucentBackground); self.setWindowTitle("Edit widget layout")
        outer = QHBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        bar = QFrame(self); bar.setObjectName("editbar")
        bar.setStyleSheet("#editbar{background:rgba(24,24,24,238);border:1px solid #3a3a3a;border-radius:12px;}")
        outer.addWidget(bar)
        h = QHBoxLayout(bar); h.setContentsMargins(8, 6, 8, 6); h.setSpacing(6)
        self.widgets_btn = QPushButton(icon("view-grid-outline"), " Widgets", bar)
        self.widgets_btn.setToolTip("Add a widget, or show / hide the widgets you have")
        self.menu = QMenu(self.widgets_btn); self.menu.aboutToShow.connect(self._fill_menu); self.widgets_btn.setMenu(self.menu)
        self.hide_btn = QPushButton(icon("eye-off-outline"), " Hide All", bar)
        self.hide_btn.setToolTip("Hide every widget (or show them all again)"); self.hide_btn.clicked.connect(self._hide_all)
        self.reset_btn = QPushButton(icon("restore"), " Reset Default Layout", bar)
        self.reset_btn.setToolTip("Arrange all widgets in the default layout (stacked along the right edge)")
        self.reset_btn.clicked.connect(self._reset)
        self.preset_btn = QPushButton(icon("bookmark-multiple-outline"), " Presets", bar)
        self.preset_btn.setCheckable(True); self.preset_btn.setToolTip("Show saved layout presets"); self.preset_btn.toggled.connect(self._flyout)
        self.save_btn = QPushButton(icon("content-save-outline"), " Save", bar)
        self.save_btn.setToolTip("Save the current layout as a new preset"); self.save_btn.clicked.connect(ed.ctl.save_new)
        self.done_btn = tool_button("close", "Done editing (Esc)", size=18); self.done_btn.clicked.connect(ed.stop)
        for b in (self.widgets_btn, self.hide_btn, self.reset_btn, self.preset_btn, self.save_btn, self.done_btn): h.addWidget(b)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=ed.stop)
        ed.ctl.changed.connect(self.refresh); mgr.changed.connect(self.refresh)

    def refresh(self):
        ctl, mgr = self.ed.ctl, self.ed.mgr
        a = ctl.store.active
        label = " Presets" if not a else f" {a['name'][:18]}{'...' if len(a['name']) > 18 else ''}{' *' if ctl.is_modified() else ''}"
        self.preset_btn.setText(label); self.preset_btn.setToolTip(ctl.status_text() + " - click to manage presets")
        hidden = mgr.all_hidden()
        self.hide_btn.setText(" Show All" if hidden else " Hide All"); self.hide_btn.setIcon(icon("eye-outline" if hidden else "eye-off-outline"))

    def place(self):
        self.adjustSize(); g = dialogs._screen().availableGeometry()
        self.move(g.right() - self.width() - 12, g.top() + 12)
        if self.ed.flyout.isVisible(): self._place_flyout()

    def _place_flyout(self):
        f = self.ed.flyout; f.adjustSize()
        f.move(self.x() + self.width() - f.width(), self.y() + self.height() + 6)

    def _flyout(self, on: bool):
        f = self.ed.flyout
        if on: self._place_flyout(); f.show(); f.raise_()
        else: f.hide()

    def _fill_menu(self):
        m, mgr = self.menu, self.ed.mgr
        m.clear()
        add = m.addMenu(icon("plus"), "Add widget")
        for k, (name, _) in KINDS.items():
            if k != "web":
                a = add.addAction(name); a.triggered.connect(lambda _=False, kind=k: mgr.add(kind))
        m.addSeparator()
        if not mgr.docks: m.addAction("No widgets yet").setEnabled(False)
        for wid, d in mgr.docks.items():
            a = m.addAction(d.w.get("name") or KINDS[d.w["kind"]][0]); a.setCheckable(True); a.setChecked(bool(d.w["visible"]))
            a.toggled.connect(d.set_visible_flag)

    def _hide_all(self):
        mgr = self.ed.mgr; mgr.show_all() if mgr.all_hidden() else mgr.hide_all()

    def _reset(self):
        if dialogs.confirm(None, "Reset default layout", "Arrange all widgets in the default layout?\nPresets are not changed."):
            self.ed.mgr.reset_default_layout()

    def hideEvent(self, e):
        self.preset_btn.setChecked(False); super().hideEvent(e)


class LayoutEditor(QObject):
    """Owns the edit-mode UI (toolbar, chips, preset flyout). The mode itself lives on the WidgetManager."""

    def __init__(self, mgr, ctl: PresetController):
        super().__init__()
        self.mgr, self.ctl = mgr, ctl
        self.chips: dict[str, EditChip] = {}
        self.flyout = PresetFlyout(ctl); self.toolbar = LayoutToolbar(self)
        mgr.edit_mode_changed.connect(self._mode); mgr.changed.connect(self.sync); mgr.layout_changed.connect(self.sync)

    @property
    def active(self) -> bool: return self.mgr.edit_mode

    def start(self): self.mgr.set_edit_mode(True)
    def stop(self): self.mgr.set_edit_mode(False)
    def toggle(self): self.mgr.set_edit_mode(not self.mgr.edit_mode)

    def _mode(self, on: bool):
        if on:
            self.toolbar.place(); self.toolbar.show(); self.toolbar.raise_(); self.toolbar.activateWindow(); self.sync()
        else:
            self.flyout.hide(); self.toolbar.hide()
            for c in self.chips.values(): c.hide()

    def sync(self):
        if not self.active: return
        for wid in [w for w in self.chips if w not in self.mgr.docks]:
            c = self.chips.pop(wid); c.hide(); c.deleteLater()
        for wid, d in self.mgr.docks.items():
            c = self.chips.get(wid)
            if c is None:
                c = self.chips[wid] = EditChip(d); d.geometry_changed.connect(c.reposition)
            c.sync(True)
        self.toolbar.refresh()
