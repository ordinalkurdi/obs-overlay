from __future__ import annotations
from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QSize
from PySide6.QtGui import QIcon, QKeyEvent
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QToolButton, QGraphicsOpacityEffect)

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
    QDialog, QTabWidget, #plain {{ background: {BG}; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; }}
    """


def separator() -> QFrame:
    f = QFrame(); f.setObjectName("sep"); f.setFixedHeight(1)
    return f


class Row(QFrame):
    """Compact NVIDIA-style row: icon, title + dim subtitle, optional right-hand widget or chevron."""
    clicked = Signal()

    def __init__(self, icon_name: str, title: str, subtitle: str = "", chevron=True, tooltip: str = ""):
        super().__init__()
        self.setObjectName("row"); self.setFocusPolicy(Qt.StrongFocus); self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self); lay.setContentsMargins(12, 0, 12, 0); lay.setSpacing(12)
        self.ico = QLabel(); self.ico.setFixedSize(22, 22)
        self.set_icon(icon_name)
        col = QVBoxLayout(); col.setSpacing(1)
        self.title = QLabel(title); self.sub = QLabel(subtitle); self.sub.setObjectName("dim")
        self.sub.setVisible(bool(subtitle))
        col.addWidget(self.title); col.addWidget(self.sub)
        lay.addWidget(self.ico); lay.addLayout(col, 1)
        self.right = QLabel(); self.right.setFixedSize(20, 20)
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


class Toast(QLabel):
    """Small non-blocking notification that fades out."""
    COLORS = {"info": "#3a3a3a", "success": "#1f5a3d", "warn": "#6b5410", "error": "#7a2323"}

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWordWrap(True); self.setAlignment(Qt.AlignCenter); self.hide()
        self._fx = QGraphicsOpacityEffect(self); self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self); self._anim.setDuration(350)
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.timeout.connect(self._fade)
        self._anim.finished.connect(lambda: self.hide() if self._fx.opacity() < 0.05 else None)

    def show_msg(self, level: str, text: str, seconds: float, animate=True):
        self.setStyleSheet(f"background:{self.COLORS.get(level, '#3a3a3a')}; border-radius:6px; padding:7px 10px;")
        self.setText(text)
        w = self.parentWidget().width() - 24
        self.setFixedWidth(w); self.adjustSize(); self.setFixedWidth(w)
        self.move(12, self.parentWidget().height() - self.height() - 40)
        self._anim.stop(); self._fx.setOpacity(1.0); self.show(); self.raise_()
        self._timer.start(int(seconds * 1000))
        self._animate = animate

    def _fade(self):
        if getattr(self, "_animate", True):
            self._anim.setStartValue(1.0); self._anim.setEndValue(0.0); self._anim.start()
        else:
            self.hide()
