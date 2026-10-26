"""Settings screen: a main page (search, quick sliders, categories) that opens one clear page per category.

Every option has a plain-language title and a one-line explanation. Numeric options use sliders with a live value label,
yes/no options use switches. There is no Save button: every change is written to the settings and applied right away
(slightly debounced, sliders apply when released). Pages fade / slide in, switches glide, disabled options fade."""
from __future__ import annotations
import json

from PySide6.QtCore import (Property, QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QPainter
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout,
                               QWidget, QKeySequenceEdit, QColorDialog)

from core import config
from core.config import HOTKEY_LABELS, Settings
from core.hotkeys import find_conflicts
from core.service import ObsService
from . import dialogs
from .common import Row, SeekSlider, icon, separator

METRICS = {"recording": "Recording status/time", "streaming": "Streaming status/time", "bitrate": "Bitrate",
           "dropped": "Dropped frames", "resolution": "Output resolution", "fps": "FPS", "cpu": "System CPU",
           "memory": "System RAM", "replay": "Replay buffer", "connection": "OBS connection"}


# ---------------------------------------------------------------------------------------------------------------------
# small building blocks
# ---------------------------------------------------------------------------------------------------------------------
class Toggle(QCheckBox):
    """On/off switch (same API as a QCheckBox: isChecked / setChecked / toggled) with a gliding knob."""

    def __init__(self, checked=False, accent="#4cc38a"):
        super().__init__(); self._accent = QColor(accent); self._x = 1.0 if checked else 0.0
        self.setChecked(bool(checked)); self.setCursor(Qt.PointingHandCursor); self.setFixedSize(40, 22)
        self._anim = QPropertyAnimation(self, b"knob", self); self._anim.setDuration(150); self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._slide)

    def _slide(self, on):
        self._anim.stop(); self._anim.setStartValue(self._x); self._anim.setEndValue(1.0 if on else 0.0); self._anim.start()

    def _get_knob(self): return self._x
    def _set_knob(self, v): self._x = v; self.update()
    knob = Property(float, _get_knob, _set_knob)

    def set_accent(self, color: str): self._accent = QColor(color); self.update()
    def sizeHint(self): return QSize(40, 22)
    def hitButton(self, pos): return self.rect().contains(pos)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        off, on, t = QColor("#4a4a4a"), self._accent, max(0.0, min(1.0, self._x))
        track = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                       int(off.blue() + (on.blue() - off.blue()) * t))
        p.setPen(Qt.NoPen); p.setBrush(track); p.drawRoundedRect(QRectF(0, 1, 40, 20), 10, 10)
        p.setBrush(QColor("#ffffff") if self.isEnabled() else QColor("#a0a0a0")); p.drawEllipse(QRectF(2 + 20 * t, 3, 16, 16))
        if self.hasFocus():
            p.setPen(self._accent); p.setBrush(Qt.NoBrush); p.drawRoundedRect(QRectF(0.5, 1.5, 39, 19), 10, 10)


class Combo(QComboBox):
    """Combo box that does not steal the mouse wheel while the page is being scrolled."""

    def __init__(self):
        super().__init__(); self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, e):
        if self.hasFocus(): super().wheelEvent(e)
        else: e.ignore()


class SettingsSlider(SeekSlider):
    """Click-to-jump slider; the wheel only works after the slider was clicked (so scrolling the page is safe)."""

    def __init__(self):
        super().__init__(Qt.Horizontal); self.setFocusPolicy(Qt.StrongFocus); self.setMinimumHeight(24)

    def mousePressEvent(self, e):
        self.setFocus(Qt.MouseFocusReason); super().mousePressEvent(e)

    def wheelEvent(self, e):
        if self.hasFocus(): super().wheelEvent(e)
        else: e.ignore()


class SliderField(QWidget):
    """Slider + live value label. Supports steps, scaled values (0.3..1.0 shown as 30..100), a list of fixed choices
    and special texts (0 -> 'Off'). The stored value is only changed once the user actually moves the slider, so
    opening and saving settings never rewrites values such as a width that was set by dragging the panel edge."""
    changed = Signal(object)        # every movement (live label, keeps a mirrored slider in sync)
    committed = Signal()            # the user let go (or used keys / wheel): time to apply

    def __init__(self, value, lo=0, hi=100, step=1, scale=1, fmt=None, choices=None, special=None, label_w=80):
        super().__init__()
        self.choices, self.scale, self.fmt, self.special = choices, scale, fmt, special or {}
        self.sl = SettingsSlider()
        if choices:
            self._lo, self._st = 0, 1
            self.sl.setRange(0, len(choices) - 1); self.sl.setSingleStep(1); self.sl.setPageStep(1)
        else:
            self._lo, self._st = int(round(lo * scale)), max(1, int(round(step * scale)))
            self.sl.setRange(self._lo, int(round(hi * scale))); self.sl.setSingleStep(self._st); self.sl.setPageStep(self._st * 5)
        self.lab = QLabel(); self.lab.setObjectName("valueLabel"); self.lab.setMinimumWidth(label_w)
        self.lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h = QHBoxLayout(self); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(12); h.addWidget(self.sl, 1); h.addWidget(self.lab)
        self.set(value); self.sl.valueChanged.connect(self._moved); self.sl.sliderReleased.connect(self.committed.emit)

    def _index_of(self, v) -> int:
        if self.choices: return min(range(len(self.choices)), key=lambda k: abs(self.choices[k] - float(v)))
        return int(round(float(v) * self.scale))

    def _value_of(self, i):
        if self.choices: return self.choices[i]
        v = i / self.scale
        return int(round(v)) if self.scale == 1 else round(v, 4)

    def _snap(self, i: int) -> int:
        i = self._lo + int(round((i - self._lo) / self._st)) * self._st
        return max(self.sl.minimum(), min(self.sl.maximum(), i))

    def _moved(self, i):
        s = self._snap(i)
        if s != i:
            self.sl.blockSignals(True); self.sl.setValue(s); self.sl.blockSignals(False)
        self._value = self._value_of(s); self._show(); self.changed.emit(self._value)
        if not self.sl.isSliderDown(): self.committed.emit()

    def _show(self):
        v = self._value
        self.lab.setText(self.special[v] if v in self.special else (self.fmt(v) if self.fmt else f"{v:g}"))

    def set(self, v):
        self._value = v
        self.sl.blockSignals(True); self.sl.setValue(self._index_of(v)); self.sl.blockSignals(False); self._show()

    def value(self): return self._value


class Setting(QFrame):
    """One option: bold title, dim one-line explanation, control on the right (inline) or below (wide controls)."""

    def __init__(self, title, desc="", control=None, inline=True):
        super().__init__(); self.setObjectName("setting"); self.hay = f"{title} {desc}".lower(); self._sep = None
        v = QVBoxLayout(self); v.setContentsMargins(14, 10, 14, 10); v.setSpacing(8)
        text = QVBoxLayout(); text.setSpacing(2)
        t = QLabel(title); t.setObjectName("settingTitle"); t.setWordWrap(True); text.addWidget(t)
        if desc:
            d = QLabel(desc); d.setObjectName("dim"); d.setWordWrap(True); text.addWidget(d)
        if control is not None and inline:
            h = QHBoxLayout(); h.setSpacing(14); h.addLayout(text, 1); h.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter); v.addLayout(h)
        else:
            v.addLayout(text)
            if control is not None: v.addWidget(control)

    def set_active(self, active: bool):
        """Fade options that have no effect in the current configuration (instant the first time, animated afterwards)."""
        if getattr(self, "_act", None) == active: return
        first = getattr(self, "_act", None) is None; self._act = active; self.setEnabled(active)
        old = getattr(self, "_fa", None)
        if old is not None: old.stop()
        if first:
            if active: self.setGraphicsEffect(None)
            else: fx = QGraphicsOpacityEffect(self); fx.setOpacity(0.4); self.setGraphicsEffect(fx)
            return
        fx = QGraphicsOpacityEffect(self); fx.setOpacity(0.4 if active else 1.0); self.setGraphicsEffect(fx)
        a = QPropertyAnimation(fx, b"opacity", self); a.setDuration(180); a.setStartValue(fx.opacity()); a.setEndValue(1.0 if active else 0.4)
        if active: a.finished.connect(lambda: QTimer.singleShot(0, lambda: self.setGraphicsEffect(None) if self._act else None))
        self._fa = a; a.start()


class Section(QWidget):
    """A titled card holding several settings (or category rows) separated by hairlines."""

    def __init__(self, title=""):
        super().__init__(); v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(6)
        if title:
            lab = QLabel(title.upper()); lab.setObjectName("sectionTitle"); lab.setContentsMargins(4, 0, 0, 0); v.addWidget(lab)
        self.card = QFrame(); self.card.setObjectName("card"); self.cl = QVBoxLayout(self.card)
        self.cl.setContentsMargins(0, 0, 0, 0); self.cl.setSpacing(0); v.addWidget(self.card); self.items: list[QWidget] = []

    def add(self, w: QWidget):
        w._sep = None
        if self.items: w._sep = separator(); self.cl.addWidget(w._sep)
        self.cl.addWidget(w); self.items.append(w); return w

    def refresh(self):
        first = True
        for w in self.items:
            vis = not w.isHidden()
            if w._sep is not None: w._sep.setVisible(vis and not first)
            if vis: first = False
        self.setVisible(not first)


def _scroll(widget: QWidget) -> QScrollArea:
    sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); sc.setWidget(widget); return sc


def _unit(suffix):
    return lambda v: f"{v:g}{suffix}"


# ---------------------------------------------------------------------------------------------------------------------
# the settings screen
# ---------------------------------------------------------------------------------------------------------------------
class SettingsDialog(QDialog):
    applied = Signal()
    clear_history = Signal()
    closed = Signal()

    def __init__(self, svc: ObsService, hotkey_failures: callable, parent=None):
        super().__init__(parent); self.setWindowFlags(Qt.Widget); self.hide()     # embedded as a page of the overlay; must never appear as its own window
        self.svc, self.cfg, self.failures = svc, svc.cfg, hotkey_failures
        self.getters: dict[str, callable] = {}; self.fields: dict[str, list[SliderField]] = {}
        self.entries: list[tuple[Setting, int]] = []; self.sections: list[Section] = []
        self.cat_rows: dict[int, Row] = {}; self.cat_sub: dict[int, str] = {}; self.page_title: dict[int, str] = {0: "Settings"}
        self._lay = None; self._cur_page = 0; self._cur_title = "quick settings"; self.hk_idx = 0; self.keys: dict = {}
        self.accent = self.cfg["accent"]; self.toggles: list[Toggle] = []; self._hk_conflict = False
        self._dirty = False; self._anim = None; self._fx_widgets: list[QWidget] = []
        self._apply_t = QTimer(self); self._apply_t.setSingleShot(True); self._apply_t.setInterval(280); self._apply_t.timeout.connect(self._apply_now)
        self._idle_t = QTimer(self); self._idle_t.setSingleShot(True); self._idle_t.setInterval(1800); self._idle_t.timeout.connect(self._status_idle)

        # navigation bar (only visible on a category page) + page stack + footer
        self.back = QPushButton(" All settings"); self.back.setObjectName("link"); self.back.setIcon(icon("chevron-left"))
        self.back.setCursor(Qt.PointingHandCursor); self.crumb = QLabel(); self.crumb.setObjectName("dim")
        self.nav = QWidget(); nl = QHBoxLayout(self.nav); nl.setContentsMargins(6, 4, 10, 0); nl.addWidget(self.back); nl.addStretch(); nl.addWidget(self.crumb)
        self.nav.setFixedHeight(36); self.back.setVisible(False)           # fixed height: the page below never jumps when the button appears
        self.stack = QStackedWidget()
        self.hint = QLabel(); self.hint.setObjectName("dim")
        done = QPushButton("Done"); done.setObjectName("primary")
        foot = QHBoxLayout(); foot.setContentsMargins(12, 6, 12, 4); foot.addWidget(self.hint, 1); foot.addWidget(done)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        root.addWidget(self.nav); root.addWidget(self.stack, 1); root.addWidget(separator()); root.addLayout(foot)
        self._status_idle()

        self._build_home(); self._build_categories()
        self.back.clicked.connect(lambda: self._go(0)); done.clicked.connect(self.accept)

    # ---- structure ----------------------------------------------------------
    def _page(self, title: str, desc: str):
        w = QWidget(); w.setObjectName("plain"); lay = QVBoxLayout(w); lay.setContentsMargins(14, 10, 14, 16); lay.setSpacing(16)
        t = QLabel(title); t.setObjectName("pageTitle"); lay.addWidget(t)
        if desc:
            d = QLabel(desc); d.setObjectName("dim"); d.setWordWrap(True); lay.addWidget(d)
        return w, lay

    def _build_home(self):
        home, lay = self._page("Settings", "Search for an option, drag a quick slider, or open a category below.")
        self.stack.addWidget(_scroll(home)); self._lay = lay
        self.search = QLineEdit(); self.search.setPlaceholderText("Search settings (for example: hotkey, opacity, replay)...")
        self.search.setClearButtonEnabled(True); lay.addWidget(self.search)
        self.none = QLabel("No setting matches your search."); self.none.setObjectName("dim"); self.none.setAlignment(Qt.AlignCenter); self.none.hide()
        lay.addWidget(self.none)
        # quick settings: the options people change most, as sliders (kept in sync with the full pages)
        self._cur_page, self._cur_title = 0, "quick settings"
        quick = self._section("Quick settings")
        self._slider(quick, "Overlay opacity", "How see-through the panel is. Lower lets more of the game show through.",
                     "opacity", 0.3, 1.0, 0.02, scale=100, fmt=lambda v: f"{round(v * 100)} %")
        self._slider(quick, "Panel width", "How wide the overlay panel is. You can also drag its edges.", "width", 320, 1600, 10, fmt=_unit(" px"))
        self._slider(quick, "Preview speed", "Time between live preview snapshots. Lower is smoother but heavier on your PC.",
                     "preview_delay_ms", 100, 5000, 50, fmt=self._delay_text, label_w=120)
        self.cats = Section("Categories"); lay.addWidget(self.cats); self.sections.append(self.cats)
        lay.addStretch(1)
        self.search.textChanged.connect(self._filter); self.search.returnPressed.connect(self._open_first)

    def _build_categories(self):
        obs_sub = f"Status: {self.svc.status_text}"
        cats = [("Window & position", "dock-right", "Docked or floating, size, position and auto-hide", self._window,
                 "Where the overlay lives on screen and when it slides in and out."),
                ("Appearance", "palette-outline", "Opacity, text size, corners, accent color, notifications", self._appearance,
                 "How the overlay looks."),
                ("OBS connection", "lan-connect", obs_sub, self._obs, "How this app talks to OBS Studio."),
                ("Recording & replay", "record-circle-outline", "Replay length and confirmations", self._capture,
                 "Behavior of recording, streaming and Instant Replay."),
                ("Gallery & screenshots", "image-multiple-outline", "Folders, thumbnails and screenshot format", self._gallery,
                 "Where your captures are found and saved."),
                ("Preview & audio", "video-outline", "Live preview speed and audio activity", self._preview,
                 "The small live picture of your OBS scene and the audio meters."),
                ("Widgets", "widgets-outline", "Floating statistic widgets and warning levels", self._stats,
                 "Floating widgets that show stats on top of your game."),
                ("Hotkeys", "keyboard-outline", "Global keyboard shortcuts", self._hotkeys,
                 "Shortcuts that work even while a game is in focus."),
                ("Privacy", "shield-lock-outline", "Filenames, history and data", self._privacy, "What this app stores and shows."),
                ("Advanced", "tune", "Diagnostics, backup, import / export and reset", self._advanced,
                 "Troubleshooting tools and settings backup.")]
        for title, ico, sub, fn, desc in cats:
            w, lay = self._page(title, desc); idx = self.stack.addWidget(_scroll(w))
            self._lay, self._cur_page, self._cur_title = lay, idx, title.lower(); self.page_title[idx] = title
            fn(); lay.addStretch(1)
            row = Row(ico, title, sub); self.cats.add(row); row.clicked.connect(lambda i=idx: self._go(i))
            self.cat_rows[idx] = row; self.cat_sub[idx] = sub

    def _section(self, title="") -> Section:
        s = Section(title); self._lay.addWidget(s); self.sections.append(s); return s

    def _note(self, text):
        l = QLabel(text); l.setWordWrap(True); l.setObjectName("dim"); l.setContentsMargins(4, 0, 4, 0); self._lay.addWidget(l)

    # ---- page transitions ------------------------------------------------------
    def _go(self, idx: int):
        """Open page `idx`: the current page fades out, the new one fades and slides in (off when 'Slide animation' is Off)."""
        self._abort_anim(); old = self.stack.currentIndex()
        t = self.search.text().strip()
        self.back.setVisible(idx != 0)
        self.crumb.setText((self.page_title.get(idx, "") + (f"  -  filtered by \"{t}\"" if t else "")) if idx else "")
        if idx == old: return
        ms = int(self.cfg["anim_ms"])
        if ms <= 0 or not self.isVisible(): self.stack.setCurrentIndex(idx); return
        cur = self.stack.currentWidget(); fx = QGraphicsOpacityEffect(cur); fx.setOpacity(1.0); cur.setGraphicsEffect(fx); self._fx_widgets.append(cur)
        out = QPropertyAnimation(fx, b"opacity", self); out.setDuration(max(60, ms // 2)); out.setStartValue(1.0); out.setEndValue(0.0)
        out.setEasingCurve(QEasingCurve.InQuad); out.finished.connect(lambda: self._enter(idx, 1 if idx > old else -1, ms)); self._anim = out; out.start()

    def _enter(self, idx: int, direction: int, ms: int):
        prev, self._anim = self._anim, None
        if prev is not None: prev.deleteLater()
        self._clear_fx(); self.stack.setCurrentIndex(idx); new = self.stack.currentWidget()
        fx = QGraphicsOpacityEffect(new); fx.setOpacity(0.0); new.setGraphicsEffect(fx); self._fx_widgets.append(new)
        end = self.stack.rect(); new.setGeometry(end.translated(40 * direction, 0))
        fade = QPropertyAnimation(fx, b"opacity"); fade.setStartValue(0.0); fade.setEndValue(1.0)
        slide = QPropertyAnimation(new, b"geometry"); slide.setStartValue(end.translated(40 * direction, 0)); slide.setEndValue(end)
        grp = QParallelAnimationGroup(self)
        for a in (fade, slide): a.setDuration(int(ms * 1.2)); a.setEasingCurve(QEasingCurve.OutCubic); grp.addAnimation(a)
        grp.finished.connect(self._anim_finished); self._anim = grp; grp.start()

    def _clear_fx(self):
        for w in self._fx_widgets:
            w.setGraphicsEffect(None)
            if self.stack.indexOf(w) >= 0: w.setGeometry(self.stack.rect())      # never leave a page offset after an interrupted slide
        self._fx_widgets = []

    def _anim_finished(self):
        a, self._anim = self._anim, None
        if a is not None: a.deleteLater()
        QTimer.singleShot(0, self._clear_fx)                    # remove the fade effects once the animation has fully ended

    def _abort_anim(self):
        """Stop a running transition immediately and leave every page clean (a new click during a transition is safe)."""
        a, self._anim = self._anim, None
        if a is not None: a.stop(); a.deleteLater()
        self._clear_fx()

    # ---- live apply ----------------------------------------------------------------
    def _commit(self, key: str):
        """Write ONE changed option to the settings and schedule the (debounced) apply."""
        g = self.getters.get(key)
        if g: self.cfg[key] = g()
        self._schedule()

    def _schedule(self):
        self._dirty = True; self.hint.setText("Saving..."); self.hint.setStyleSheet(""); self._apply_t.start()

    def _apply_now(self):
        if not self._dirty: return
        self._dirty = False; self.cfg.save(); self.applied.emit()
        if hasattr(self, "hk_msg") and not self._hk_conflict:
            bad = self.failures(); self.hk_msg.setStyleSheet("")
            self.hk_msg.setText("Could not register: " + "; ".join(f"{HOTKEY_LABELS[a]} ({m})" for a, m in bad.items()) if bad else "")
        self.hint.setText("\u2713  Saved"); self.hint.setStyleSheet(f"color:{self.cfg['accent']};"); self._idle_t.start()

    def _status_idle(self):
        self.hint.setStyleSheet(""); self.hint.setText("Changes apply instantly and are saved automatically.")

    def _flush(self):
        if self._apply_t.isActive(): self._apply_t.stop(); self._apply_now()

    # ---- option helpers -------------------------------------------------------
    def _add(self, sec: Section, s: Setting, key=None, getter=None) -> Setting:
        sec.add(s); s.hay += " " + self._cur_title; self.entries.append((s, self._cur_page))
        if key and getter and key not in self.getters: self.getters[key] = getter
        return s

    def _toggle(self, sec, title, desc, key) -> tuple[Setting, Toggle]:
        w = Toggle(self.cfg[key], self.accent); self.toggles.append(w)
        w.toggled.connect(lambda _=False, k=key: self._commit(k))
        return self._add(sec, Setting(title, desc, w), key, w.isChecked), w

    def _slider(self, sec, title, desc, key, lo=0, hi=100, step=1, scale=1, fmt=None, choices=None, special=None, label_w=80):
        f = SliderField(self.cfg[key], lo, hi, step, scale, fmt, choices, special, label_w)
        peers = self.fields.setdefault(key, []); peers.append(f)
        f.changed.connect(lambda v, me=f, k=key: [p.set(v) for p in self.fields[k] if p is not me])     # same option on 2 pages: keep in sync
        f.committed.connect(lambda k=key: self._commit(k))                                                # apply when the slider is released
        return self._add(sec, Setting(title, desc, f, inline=False), key, lambda k=key: self.fields[k][0].value())

    def _choice(self, sec, title, desc, key, options) -> tuple[Setting, Combo]:
        w = Combo(); w.setMinimumWidth(170)
        for val, lab in options: w.addItem(lab, val)
        idx = w.findData(self.cfg[key])
        if idx < 0: w.addItem(str(self.cfg[key]), self.cfg[key]); idx = w.count() - 1
        w.setCurrentIndex(idx); w.currentIndexChanged.connect(lambda _=0, k=key: self._commit(k))
        return self._add(sec, Setting(title, desc, w), key, w.currentData), w

    def _text(self, sec, title, desc, key, browse=False) -> Setting:
        w = QLineEdit(self.cfg[key] or ""); box = w
        if browse:
            box = QWidget(); h = QHBoxLayout(box); h.setContentsMargins(0, 0, 0, 0); b = QPushButton("Browse...")
            def choose():
                d = QFileDialog.getExistingDirectory(self, title, w.text())
                if d: w.setText(d); self._commit(key)
            b.clicked.connect(choose); h.addWidget(w, 1); h.addWidget(b)
        w.editingFinished.connect(lambda k=key: self._commit(k))        # typing: apply when the field is left / Enter, not per letter
        return self._add(sec, Setting(title, desc, box, inline=False), key, w.text)

    def _number(self, sec, title, desc, key, lo, hi) -> Setting:
        w = QSpinBox(); w.setRange(lo, hi); w.setValue(int(self.cfg[key])); w.setFixedWidth(100)
        w.setKeyboardTracking(False); w.valueChanged.connect(lambda _=0, k=key: self._commit(k))   # no apply for every typed digit
        return self._add(sec, Setting(title, desc, w), key, w.value)

    def _button(self, sec, title, desc, label, fn, danger=False) -> Setting:
        b = QPushButton(label); b.clicked.connect(fn)
        if danger: b.setObjectName("danger")
        return self._add(sec, Setting(title, desc, b)), b

    @staticmethod
    def _delay_text(v): return f"{v} ms  ({1000 / v:.1f}/s)"

    def _when(self, trigger: QComboBox, settings: list, pred):
        def upd(*_):
            on = pred(trigger.currentData())
            for s in settings: s.set_active(on)
        trigger.currentIndexChanged.connect(upd); upd()

    # ---- search ---------------------------------------------------------------
    def _filter(self, text):
        words = text.lower().split(); counts: dict[int, int] = {}
        for s, pg in self.entries:
            vis = all(w in s.hay for w in words); s.setVisible(vis)
            if vis: counts[pg] = counts.get(pg, 0) + 1
        for sec in self.sections: sec.refresh()
        for pg, row in self.cat_rows.items():
            n = counts.get(pg, 0); row.setVisible(not words or n > 0)
            row.set_texts(sub=(f"{n} matching option{'s' if n != 1 else ''}" if words else self.cat_sub[pg]))
        self.cats.refresh(); self.none.setVisible(bool(words) and not counts)

    def _open_first(self):
        for pg, row in self.cat_rows.items():
            if not row.isHidden(): self._go(pg); return

    # ---- pages ----------------------------------------------------------------
    def _window(self):
        screens = QGuiApplication.screens()
        primary = QGuiApplication.primaryScreen()
        mon = [(i, f"Monitor {i + 1}" + (" (primary)" if i < len(screens) and screens[i] == primary else "")) for i in range(max(1, len(screens)))]
        sec = self._section("Mode")
        _, mode = self._choice(sec, "Window mode", "Docked: the panel slides out from the edge of a monitor. Floating: a normal window you can place anywhere.",
                               "dock_mode", [("docked", "Docked to screen edge"), ("floating", "Floating window")])
        self._choice(sec, "Monitor", "Which screen the overlay appears on.", "monitor", mon)
        side, _ = self._choice(sec, "Dock side", "Which edge of the screen the panel slides out from.", "dock_side", [("right", "Right"), ("left", "Left")])
        self._toggle(sec, "Always on top", "Keep the overlay above other windows (works with borderless-windowed games).", "always_on_top")
        self._toggle(sec, "Start hidden", "Start in the system tray instead of showing the panel.", "start_hidden")
        sec = self._section("Size")
        self._slider(sec, "Panel width", "How wide the overlay panel is. You can also drag its edges.", "width", 320, 1600, 10, fmt=_unit(" px"))
        self._slider(sec, "Panel height", "How tall the panel is. Also resizable by dragging its edges.", "dock_height", 0, 4000, 10,
                     fmt=_unit(" px"), special={0: "Full height"})
        sec = self._section("Position (docked mode)")
        va, valign = self._choice(sec, "Vertical position", "Where along the screen edge the panel sits. Dragging the header up or down sets 'Custom'.",
                                  "dock_valign", [("center", "Centered"), ("top", "Top"), ("bottom", "Bottom"), ("custom", "Custom")])
        dy = self._slider(sec, "Custom vertical offset", "Distance from the top of the screen (used when position is 'Custom').", "dock_y", 0, 4000, 10, fmt=_unit(" px"))
        gap = self._slider(sec, "Gap to screen edge", "Space between the panel and the screen edge. Flush removes the gap and the rounded corners.",
                           "dock_gap", 0, 300, 2, fmt=_unit(" px"), special={0: "Flush"})
        sec = self._section("Show and hide")
        edge, _ = self._toggle(sec, "Slide out at the screen edge", "Move the mouse to the screen edge to open the panel. Turn off if it gets in the way in games.", "edge_reveal")
        auto, _ = self._toggle(sec, "Slide away when the mouse leaves", "Hide the panel again when the mouse leaves it (unless pinned).", "dock_autohide")
        anim = self._slider(sec, "Slide animation", "How long the slide in / out takes.", "anim_ms", 0, 1000, 20, fmt=_unit(" ms"), special={0: "Off"})
        self._slider(sec, "Auto-hide after", "Hide the overlay after this long without use.", "auto_hide_seconds", 0, 600, 5, fmt=_unit(" s"), special={0: "Never"})
        docked = [side, va, gap, edge, auto, anim]
        self._when(mode, docked, lambda v: v == "docked")
        def custom_dep(*_): dy.set_active(mode.currentData() == "docked" and valign.currentData() == "custom")
        mode.currentIndexChanged.connect(custom_dep); valign.currentIndexChanged.connect(custom_dep); custom_dep()
        self._note("True exclusive-fullscreen games cannot show a normal desktop window on top. Use borderless / windowed-fullscreen mode in the game.")

    def _appearance(self):
        sec = self._section("Look")
        self._slider(sec, "Overlay opacity", "How see-through the panel is. Lower lets more of the game show through.", "opacity", 0.3, 1.0, 0.02, scale=100,
                     fmt=lambda v: f"{round(v * 100)} %")
        self._slider(sec, "Text size", "Size of the text in the overlay.", "font_size", 10, 20, 1, fmt=_unit(" px"))
        self._slider(sec, "Corner roundness", "How round the panel corners are.", "radius", 0, 24, 1, fmt=_unit(" px"), special={0: "Square"})
        self._slider(sec, "Row spacing", "Space around each row. Lower is more compact, higher is easier to click.", "row_pad", 2, 20, 1, fmt=_unit(" px"))
        btn = QPushButton(); btn.setCursor(Qt.PointingHandCursor); btn.setToolTip("Click to choose a color")
        def paint(c):
            btn.setText(c); btn.setStyleSheet(f"QPushButton{{background:{c};color:{'#000' if QColor(c).lightness() > 140 else '#fff'};"
                                              f"border:none;font-weight:600;min-width:96px;}}")
        paint(self.cfg["accent"])
        def pick():
            c = QColorDialog.getColor(QColor(btn.text()), self)
            if c.isValid():
                paint(c.name()); self.accent = c.name(); self._commit("accent")
                for t in self.toggles: t.set_accent(self.accent)
        btn.clicked.connect(pick)
        self._add(sec, Setting("Accent color", "Highlight color for sliders, switches and the main button.", btn), "accent", btn.text)
        sec = self._section("Notifications")
        self._toggle(sec, "Show notifications", "Pop-up messages such as 'Recording started' or 'Screenshot saved'.", "notifications")
        self._slider(sec, "Notification duration", "How long a notification stays on screen.", "notification_seconds", 1, 15, 1, fmt=_unit(" s"))

    def _obs(self):
        sec = self._section("Connection")
        self._choice(sec, "Mode", "OBS connects to the real OBS Studio. Demo runs a simulation so you can try the app without OBS.", "mode",
                     [("obs", "OBS Studio"), ("demo", "Demo (simulated)")])
        self._text(sec, "Host", "Address of the computer running OBS. Use 'localhost' for this PC.", "host")
        self._number(sec, "Port", "OBS WebSocket port (OBS default: 4455).", "port", 1, 65535)
        self.pw = QLineEdit(); self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("saved - leave empty to keep" if self.cfg.has_password() else "WebSocket password (optional)")
        self.pw.editingFinished.connect(self._save_password)
        self._add(sec, Setting("Password", "Only needed if you set one in OBS. " + ("Stored in the OS credential store." if Settings.keyring_available() else
                  "No OS credential store found: the password is kept in memory for this session only, never on disk."), self.pw, inline=False))
        self._slider(sec, "Connection timeout", "How long to wait for OBS to answer before giving up.", "timeout", 1, 30, 1, fmt=_unit(" s"))
        sec = self._section("Behavior")
        self._toggle(sec, "Reconnect automatically", "Try again by itself when the connection to OBS is lost.", "auto_reconnect")
        self._toggle(sec, "Connect on startup", "Connect to OBS as soon as the app starts.", "connect_on_start")
        self._toggle(sec, "Allow remote OBS hosts", "Allow connecting to OBS on another computer. Off by default for privacy.", "remote_allowed")
        sec = self._section("Tools")
        self.res = QLabel(""); self.res.setWordWrap(True)
        box = QWidget(); bl = QVBoxLayout(box); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(6)
        test = QPushButton("Test connection"); test.clicked.connect(self._test); bl.addWidget(test); bl.addWidget(self.res)
        self._add(sec, Setting("Test connection", "Check host, port and password with the values above (nothing is saved).", box, inline=False))
        self._button(sec, "Saved password", "Remove the password stored for OBS.", "Forget password", self._forget)
        self._note("Enable the server in OBS: Tools > WebSocket Server Settings (default port 4455).")

    def _test(self):
        pw = self.pw.text() or self.cfg.get_password(); self.res.setText("Testing...")
        host = self.getters["host"](); port = self.getters["port"]()
        self.svc.test_connection(host, port, pw, lambda r, e: self.res.setText(f"OK - OBS {r}" if not e else f"Failed: {e}"))

    def _save_password(self):
        if self.pw.text():
            self.cfg.set_password(self.pw.text()); self.pw.clear(); self.pw.setPlaceholderText("saved - leave empty to keep"); self._schedule()

    def _forget(self):
        self.cfg.set_password(""); self.pw.clear(); self.pw.setPlaceholderText("WebSocket password (optional)"); self._schedule()

    def _capture(self):
        sec = self._section("Instant Replay")
        self._slider(sec, "Replay length", "How much of the past gets saved when you save a replay. Applied through OBS when Instant Replay starts.",
                     "replay_seconds", choices=[15, 30, 60, 120, 180, 300], fmt=lambda s: f"{s} s" if s < 60 else f"{s // 60} min")
        sec = self._section("Safety")
        self._toggle(sec, "Confirm before stopping a recording", "Ask first so you do not end a recording by accident.", "confirm_stop_record")
        self._toggle(sec, "Confirm before stopping a stream", "Ask first so you do not end a live stream by accident.", "confirm_stop_stream")
        self._note("Recording format, encoder, quality, filename format and replay save path are configured in OBS (Settings > Output). "
                   "This app does not duplicate them.")

    def _gallery(self):
        sec = self._section("Folders")
        self._text(sec, "Gallery folder", "Videos and replays are found here, including all sub-folders (per game and replay folders are discovered automatically).", "gallery_root", True)
        self._text(sec, "Screenshot folder", "Where screenshots are saved.", "screenshot_dir", True)
        sec = self._section("Screenshots")
        _, fmt = self._choice(sec, "Format", "PNG keeps full quality. JPEG makes smaller files.", "screenshot_format", [("png", "PNG (lossless)"), ("jpg", "JPEG (smaller)")])
        q = self._slider(sec, "JPEG quality", "Higher looks better but makes bigger files. Only used for JPEG.", "screenshot_quality", 1, 100, 1, fmt=_unit(" %"))
        self._text(sec, "File name pattern", "Date / time codes, for example Screenshot_%Y-%m-%d_%H-%M-%S", "screenshot_pattern")
        self._when(fmt, [q], lambda v: v == "jpg")
        sec = self._section("Thumbnails")
        self._slider(sec, "Thumbnail size", "Size of the pictures in the gallery.", "thumb_size", 100, 260, 10, fmt=_unit(" px"))
        self._note("Screenshots capture the OBS scene output only.")

    def _preview(self):
        sec = self._section("Live preview")
        self._slider(sec, "Preview speed", "Time between preview snapshots. Lower is smoother but heavier on OBS and your CPU (100-5000 ms).",
                     "preview_delay_ms", 100, 5000, 50, fmt=self._delay_text, label_w=120)
        self._slider(sec, "Preview width", "Size of the preview picture inside the overlay.", "preview_width", 160, 640, 20, fmt=_unit(" px"))
        sec = self._section("Audio")
        self._toggle(sec, "Show audio activity", "Live levels and an activity dot for each audio source. Needs OBS.", "audio_detect")
        self._note("A new preview speed applies immediately; nothing is restarted and the video player is not reloaded. "
                   "Right-click an audio source in the overlay to use it as microphone or desktop audio. No audio inputs are created in OBS, "
                   "so there are no duplicate streams or feedback loops.")

    def _stats(self):
        sec = self._section("Widgets")
        self._toggle(sec, "Show floating widgets", "Main switch for all statistic widgets.", "stats_visible")
        self._slider(sec, "Update interval", "How often the numbers refresh.", "stats_interval_ms", 500, 10000, 100, fmt=lambda v: f"{v / 1000:.1f} s")
        sec = self._section("Warning levels")
        self._slider(sec, "Dropped frames warning", "Turn the value red above this share of dropped frames.", "stats_warn_dropped_pct", 0, 100, 0.5, scale=2, fmt=_unit(" %"))
        self._slider(sec, "System CPU warning", "Turn the value red above this CPU load.", "stats_warn_cpu_pct", 10, 100, 5, fmt=_unit(" %"))
        self._note("Add, resize, pin and make widgets click-through from the overlay (Widgets row), or right-click a widget. "
                   "OBS-process CPU and GPU usage / temperature are not exposed by this build and are shown as Unavailable.")

    def _hotkeys(self):
        sec = self._section("Shortcuts")
        for a, lab in HOTKEY_LABELS.items():
            e = QKeySequenceEdit(QKeySequence(self.cfg["hotkeys"][a])); e.setMaximumSequenceLength(1); e.setMinimumWidth(130)
            reset = QPushButton("Reset"); box = QWidget(); h = QHBoxLayout(box); h.setContentsMargins(0, 0, 0, 0); h.addWidget(e, 1); h.addWidget(reset)
            def reset_one(_=False, ed=e, act=a): ed.setKeySequence(QKeySequence(config.DEFAULTS["hotkeys"][act])); self._hk_changed()
            reset.clicked.connect(reset_one); e.editingFinished.connect(self._hk_changed)
            self.keys[a] = e; self._add(sec, Setting(lab, "", box))
        def reset_all():
            for a, e in self.keys.items(): e.setKeySequence(QKeySequence(config.DEFAULTS["hotkeys"][a]))
            self._hk_changed()
        self._button(sec, "Restore defaults", "Set every shortcut back to its original key.", "Restore all", reset_all)
        self.hk_msg = QLabel(); self.hk_msg.setWordWrap(True); self._lay.addWidget(self.hk_msg); self.hk_idx = self._cur_page
        bad = self.failures()
        if bad: self.hk_msg.setText("Could not register: " + "; ".join(f"{HOTKEY_LABELS[a]} ({m})" for a, m in bad.items()))
        self._note("Click a box and press the new key combination. Shortcuts are global and passive: they are not blocked from the game.")

    def _privacy(self):
        sec = self._section("Privacy")
        self._toggle(sec, "Hide file names in the gallery", "Show only thumbnails, useful when streaming or sharing your screen.", "hide_filenames")
        self._button(sec, "Clear thumbnails and favorites", "Delete cached thumbnails and the favorites list.", "Clear", self.clear_history.emit)
        self._note("No analytics or telemetry exist in this app. Media stays local; nothing is uploaded. "
                   "Remote OBS hosts are blocked unless enabled under OBS connection.")

    def _advanced(self):
        sec = self._section("Diagnostics")
        v = self.svc.snap.get("version") or "not connected"
        info = QPlainTextEdit(); info.setReadOnly(True); info.setMinimumHeight(170)
        info.setPlainText(f"Status: {self.svc.status_text}\nOBS: {v}\nCapabilities: {json.dumps(self.svc.snap.get('caps', {}))}\n"
                          f"Replay buffer available: {self.svc.snap.get('replay_available', 'unknown')}\nSettings file: {self.cfg.path}\n"
                          f"Error log: {config.data_dir() / 'error.log'}\n--- Connection diagnostics ---\n{self.svc.diagnostics()}")
        self._add(sec, Setting("Status and connection details", "Select and copy this when asking for help.", info, inline=False))
        log = QPlainTextEdit(); log.setReadOnly(True); log.setMinimumHeight(110)
        log.setPlainText("\n".join(f"{t}  [{l}]  {m}" for t, l, m in reversed(self.svc.notifications)) or "No notifications yet.")
        self._add(sec, Setting("Notification history", "The latest messages shown by the overlay.", log, inline=False))
        sec = self._section("Backup and reset")
        self._button(sec, "Export settings", "Save your settings to a file. The OBS password is never included.", "Export...",
                     lambda: (p := QFileDialog.getSaveFileName(self, "Export", "obs-overlay-settings.json", "JSON (*.json)")[0]) and self.cfg.export_to(p))
        def imp():
            p = QFileDialog.getOpenFileName(self, "Import", "", "JSON (*.json)")[0]
            if p:
                try: self.cfg.import_from(p); self.applied.emit(); self.accept()
                except Exception as e: dialogs.message(self, "Import failed", str(e))
        def reset():
            if dialogs.confirm(self, "Reset", "Reset all settings (hotkeys included)?", danger=True):
                self.cfg.reset(); self.applied.emit(); self.accept()
        self._button(sec, "Import settings", "Load settings from a file saved earlier.", "Import...", imp)
        self._button(sec, "Reset to defaults", "Put every setting, including hotkeys, back to the original values.", "Reset all...", reset, danger=True)

    # ---- hotkeys / closing -------------------------------------------------
    def _hk_changed(self):
        binds = {a: e.keySequence().toString() for a, e in self.keys.items()}
        dup = find_conflicts(binds)
        if dup:                                                  # never apply a conflicting set: tell the user what to change
            names = "; ".join(" & ".join(HOTKEY_LABELS[a] for a in v) + f" -> {k}" for k, v in dup.items())
            self._hk_conflict = True; self.hk_msg.setText("Conflict: " + names + ". Change one of them (not applied yet)."); self.hk_msg.setStyleSheet("color:#ff7b7b")
            return
        self._hk_conflict = False; self.hk_msg.setText(""); self.hk_msg.setStyleSheet("")
        self.cfg["hotkeys"] = binds; self._schedule()

    def accept(self): self._flush(); self.closed.emit()          # "Done": nothing to save, just make sure the last change is applied
    def reject(self): self._flush(); self.closed.emit()
