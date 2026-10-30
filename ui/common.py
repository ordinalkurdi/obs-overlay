from __future__ import annotations
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon, QKeyEvent
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSlider, QStyle, QStyleOptionSlider, QVBoxLayout, QWidget, QToolButton)

FG, FG_DIM, BG, HEADER, LINE = "#f2f2f2", "#9a9a9a", "#181818", "#303030", "#2c2c2c"


def icon(name: str, color: str = FG) -> QIcon:
    """Material Design Icons through qtawesome (one consistent set). Falls back to no icon if a name is wrong."""
    try:
        import qtawesome as qta
        return qta.icon(f"mdi6.{name}", color=color)
    except Exception:
        return QIcon()


def stylesheet(cfg) -> str:
    a, fs, r, pad = cfg["accent"], int(cfg["font_size"]), int(cfg["radius"]), int(cfg["row_pad"])
    return f"""
    * {{ font-family: 'Segoe UI', 'Inter', 'Helvetica Neue', sans-serif; font-size: {fs}px; color: {FG}; }}
    #panel {{ background: {BG}; border-radius: {r}px; border: 1px solid #000; }}
    #header {{ background: {HEADER}; border-top-left-radius: {r}px; border-top-right-radius: {r}px; }}
    #title {{ font-weight: 600; font-size: {fs + 3}px; letter-spacing: 1px; }}
    #sep {{ background: {LINE}; max-height: 1px; min-height: 1px; }}
    #dim {{ color: {FG_DIM}; font-size: {fs - 2}px; }}
    #row {{ background: transparent; border-radius: 6px; padding: {pad}px 0px; }}
    #row:hover {{ background: #232323; }}
    #row:focus {{ background: #262626; border: 1px solid {a}; }}
    QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 4px; }}
    QToolButton:hover {{ background: #3a3a3a; }}
    QToolButton:focus {{ border: 1px solid {a}; }}
    QToolButton:checked {{ background: #3a3a3a; }}
    QPushButton {{ background: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 6px; padding: 6px 12px; }}
    QPushButton:hover {{ background: #343434; }} QPushButton:focus {{ border: 1px solid {a}; }}
    QPushButton#primary {{ background: {a}; color: #07140d; border: none; font-weight: 600; }}
    QPushButton#danger {{ background: #7a2323; border: none; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit {{
        background: #222; border: 1px solid #3a3a3a; border-radius: 5px; padding: 4px 6px; }}
    QComboBox QAbstractItemView {{ background: #222; selection-background-color: #3a3a3a; }}
    QSlider::groove:horizontal {{ height: 4px; background: #3a3a3a; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {a}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: #fff; width: 12px; margin: -5px 0; border-radius: 6px; }}
    QListWidget {{ background: {BG}; border: none; }}
    QListWidget::item:selected {{ background: #2d2d2d; border-radius: 6px; }}
    QScrollBar:horizontal {{ height: 6px; background: transparent; }}
    QScrollBar::handle:horizontal {{ background: #444; border-radius: 3px; min-width: 20px; }}
    QScrollBar:vertical {{ width: 6px; background: transparent; }}
    QScrollBar::handle:vertical {{ background: #444; border-radius: 3px; min-height: 20px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QToolTip {{ background: #111; color: {FG}; border: 1px solid #444; padding: 3px; }}
    #card {{ background: #1e1e1e; border: 1px solid {LINE}; border-radius: {r}px; }}
    #sectionTitle {{ color: {FG_DIM}; font-size: {fs - 2}px; font-weight: 600; letter-spacing: 1px; }}
    #pageTitle {{ font-size: {fs + 5}px; font-weight: 600; }}
    #settingTitle {{ font-weight: 600; }}
    #valueLabel {{ color: {a}; font-weight: 600; }}
    #setting {{ background: transparent; }}
    QPushButton#link {{ background: transparent; border: none; color: {a}; padding: 4px 8px; font-weight: 600; }}
    QPushButton#link:hover {{ background: #2a2a2a; }}
    QPlainTextEdit {{ background: #1a1a1a; border: 1px solid #333; border-radius: 5px; font-family: Consolas, 'Cascadia Mono', monospace; }}
    QDialog, QTabWidget, #plain {{ background: {BG}; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; }}
    """


def separator() -> QFrame:
    f = QFrame(); f.setObjectName("sep"); f.setFixedHeight(1)
    return f


class Row(QFrame):
    """Compact NVIDIA-style row: icon, title + dim subtitle, optional right-hand widget or chevron."""
    clicked = Signal()

    def __init__(self, icon_name: str, title: str, subtitle: str = "", chevron=True, tooltip: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("row"); self.setFocusPolicy(Qt.StrongFocus); self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self); lay.setContentsMargins(12, 0, 12, 0); lay.setSpacing(12)
        self.ico = QLabel(self); self.ico.setFixedSize(22, 22)
        self.set_icon(icon_name)
        col = QVBoxLayout(); col.setSpacing(1)
        # children get `self` as parent: a parentless QLabel that is made visible pops up as its own little window
        self.title = QLabel(title, self); self.sub = QLabel(subtitle, self); self.sub.setObjectName("dim")
        self.sub.setVisible(bool(subtitle))
        col.addWidget(self.title); col.addWidget(self.sub)
        lay.addWidget(self.ico); lay.addLayout(col, 1)
        self.right = QLabel(self); self.right.setFixedSize(20, 20)
        if chevron:
            self.right.setPixmap(icon("chevron-right", FG_DIM).pixmap(18, 18))
        lay.addWidget(self.right)
        self._tail_layout = lay
        if tooltip:
            self.setToolTip(tooltip)

    def set_icon(self, name, color=FG):
        self.ico.setPixmap(icon(name, color).pixmap(20, 20))

    def set_right_icon(self, name, color=FG):
        self.right.setPixmap(icon(name, color).pixmap(18, 18))

    def set_texts(self, title=None, sub=None):
        if title is not None: self.title.setText(title)
        if sub is not None: self.sub.setText(sub); self.sub.setVisible(bool(sub))

    def add_tail(self, w: QWidget):
        self._tail_layout.insertWidget(self._tail_layout.count() - 1, w)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(e)


def tool_button(icon_name: str, tip: str, checkable=False, size=18) -> QToolButton:
    b = QToolButton(); b.setIcon(icon(icon_name)); b.setToolTip(tip); b.setAccessibleName(tip)
    b.setCheckable(checkable); b.setIconSize(QSize(size, size))
    b.setCursor(Qt.PointingHandCursor)
    return b


class SeekSlider(QSlider):
    """Slider that jumps straight to the clicked position (and keeps following the mouse while dragging)
    instead of the default page-step behaviour, which made the handle snap back to its old position."""

    def _value_at(self, x: int) -> int:
        opt = QStyleOptionSlider(); self.initStyleOption(opt)
        groove = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
        handle = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
        span = max(1, groove.width() - handle.width())
        pos = x - groove.x() - handle.width() // 2
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), max(0, min(span, pos)), span, opt.upsideDown)

    def _seek_to(self, x: int):
        v = self._value_at(x)
        self.setSliderPosition(v)
        self.sliderMoved.emit(v)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.setSliderDown(True); self._seek_to(int(e.position().x())); e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.isSliderDown(): self._seek_to(int(e.position().x())); e.accept()
        else: super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.isSliderDown():
            self.setSliderDown(False); e.accept()
        else:
            super().mouseReleaseEvent(e)
