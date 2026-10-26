"""Confirmation dialogs and notifications, always centered on the screen the overlay lives on and kept inside it."""
from __future__ import annotations
from PySide6.QtCore import QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QInputDialog, QLabel, QMessageBox, QVBoxLayout, QWidget

_screen_provider = None


def set_screen_provider(fn):
    """fn() -> QScreen the overlay is on (so popups appear on the same monitor)."""
    global _screen_provider
    _screen_provider = fn


def _screen():
    try:
        s = _screen_provider() if _screen_provider else None
    except Exception:
        s = None
    return s or QGuiApplication.primaryScreen()


def center_widget(w: QWidget):
    """Center `w` on the target screen's usable area, clamped so it can never leave the screen."""
    g = _screen().availableGeometry()
    w.adjustSize()
    width, height = min(w.width(), g.width()), min(w.height(), g.height())
    if (width, height) != (w.width(), w.height()):
        w.resize(width, height)
    x = max(g.left(), min(g.center().x() - width // 2, g.right() - width + 1))
    y = max(g.top(), min(g.center().y() - height // 2, g.bottom() - height + 1))
    w.move(x, y)                      # an explicit move stops Qt from re-positioning the dialog over its parent


def prepare_dialog(dlg: QDialog):
    dlg.setWindowFlag(Qt.WindowStaysOnTopHint, True)      # stay above games / the overlay
    center_widget(dlg)


def confirm(parent, title: str, text: str, danger: bool = False) -> bool:
    box = QMessageBox(QMessageBox.Warning if danger else QMessageBox.Question, title, text,
                      QMessageBox.Yes | QMessageBox.No, None)
    box.setDefaultButton(QMessageBox.No if danger else QMessageBox.Yes)
    prepare_dialog(box)
    return box.exec() == QMessageBox.Yes


def message(parent, title: str, text: str, level: str = "warning"):
    icon = {"warning": QMessageBox.Warning, "error": QMessageBox.Critical}.get(level, QMessageBox.Information)
    box = QMessageBox(icon, title, text, QMessageBox.Ok, None)
    prepare_dialog(box)
    box.exec()


def ask_text(parent, title: str, label: str, text: str = ""):
    dlg = QInputDialog(None)
    dlg.setWindowTitle(title); dlg.setLabelText(label); dlg.setTextValue(text)
    prepare_dialog(dlg)
    ok = dlg.exec() == QDialog.Accepted
    return dlg.textValue(), ok


class NotificationWindow(QWidget):
    """Notification shown in the exact center of the screen. Click-through and non-focusing, so it never blocks a game."""
    COLORS = {"info": "#3a3a3a", "success": "#1f5a3d", "warn": "#6b5410", "error": "#7a2323"}

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                         Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.lab = QLabel(); self.lab.setWordWrap(True); self.lab.setAlignment(Qt.AlignCenter); self.lab.setMaximumWidth(460)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(self.lab)
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.timeout.connect(self._fade)
        self._anim = QPropertyAnimation(self, b"windowOpacity", self); self._anim.setDuration(350)
        self._anim.finished.connect(lambda: self.hide() if self.windowOpacity() < 0.05 else None)
        self._animate = True

    def show_msg(self, level: str, text: str, seconds: float, animate: bool = True):
        self._animate = animate
        self.lab.setStyleSheet(f"background:{self.COLORS.get(level, '#3a3a3a')}; color:#f2f2f2; border-radius:8px; padding:10px 16px; font-size:14px;")
        self.lab.setText(text)
        self._anim.stop(); self.setWindowOpacity(1.0)
        center_widget(self)
        self.show(); self.raise_()
        self._timer.start(int(seconds * 1000))

    def _fade(self):
        if self._animate:
            self._anim.setStartValue(1.0); self._anim.setEndValue(0.0); self._anim.start()
        else:
            self.hide()
