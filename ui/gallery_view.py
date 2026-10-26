from __future__ import annotations
import os
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QSize, QUrl, Signal, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QPixmap, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QScrollArea, QSlider, QVBoxLayout,
                               QWidget, QToolButton, QListView)

from core import gallery
from core.config import Settings, data_dir
from . import dialogs
from .common import FG_DIM, SeekSlider, icon, tool_button

CACHE = data_dir() / "thumbs"


class _Job(QRunnable):
    def __init__(self, store, m: gallery.Media):
        super().__init__(); self.store, self.m = store, m

    def run(self):
        d = w = h = None
        if self.m.kind == "video":
            d, w, h = gallery.video_info(self.m.path)
        t = gallery.thumbnail(self.m.path, CACHE)
        self.store._thumb.emit(self.m.path, t or "", d if d is not None else -1.0, w or 0, h or 0)


class MediaStore(QObject):
    """Scans the gallery root recursively (per-game and replay subfolders) and lazily builds thumbnails."""
    changed = Signal()
    thumb_ready = Signal(str)
    _scanned = Signal(list)
    _thumb = Signal(str, str, float, int, int)

    def __init__(self, cfg: Settings):
        super().__init__()
        self.cfg, self.items, self.thumbs = cfg, [], {}
        self._pool = QThreadPool(self); self._pool.setMaxThreadCount(2)          # limit background decoding
        self._scan_pool = QThreadPool(self); self._scan_pool.setMaxThreadCount(1)
        self._scanned.connect(self._on_scan); self._thumb.connect(self._on_thumb)
        self._queued: set[str] = set()
        self.scanning = False

    def rescan(self):
        if self.scanning: return
        self.scanning = True
        root = self.cfg["gallery_root"]; extra = self.cfg["screenshot_dir"]

        class S(QRunnable):
            def run(s_):
                items = gallery.scan(root)
                known = {m.path for m in items}
                if Path(extra).is_dir() and not str(Path(extra)).startswith(str(Path(root))):
                    for m in gallery.scan(extra):
                        if m.path not in known: m.game = "Screenshots"; items.append(m)
                self._scanned.emit(items)
        self._scan_pool.start(S())
        self.changed.emit()

    def _on_scan(self, items):
        old = {m.path: m for m in self.items}
        for m in items:
            if m.path in old: m.duration, m.width, m.height = old[m.path].duration, old[m.path].width, old[m.path].height
        self.items = sorted(items, key=lambda m: -m.mtime)
        self.scanning = False
        self.changed.emit()

    def request_thumb(self, m: gallery.Media):
        if m.path in self.thumbs or m.path in self._queued: return
        self._queued.add(m.path); self._pool.start(_Job(self, m))

    def _on_thumb(self, path, thumb, dur, w, h):
        self._queued.discard(path)
        for m in self.items:
            if m.path == path:
                if dur >= 0: m.duration = dur
                if w: m.width, m.height = w, h
        self.thumbs[path] = thumb
        self.thumb_ready.emit(path)

    def forget(self, path):
        self.items = [m for m in self.items if m.path != path]; self.changed.emit()

    def is_fav(self, path): return path in self.cfg["favorites"]

    def toggle_fav(self, path):
        f = self.cfg["favorites"]
        f.remove(path) if path in f else f.append(path)
        self.cfg.save(); self.changed.emit()

    def display_name(self, m: gallery.Media, idx=0):
        return f"Capture {idx + 1}" if self.cfg["hide_filenames"] else m.name

    def clear_history(self):
        self.cfg["favorites"] = []; self.cfg.save(); self.thumbs.clear()
        for f in CACHE.glob("*.png"):
            try: f.unlink()
            except OSError: pass
        self.changed.emit()


def pix_for(store: MediaStore, m: gallery.Media, size: int) -> QPixmap:
    t = store.thumbs.get(m.path)
    if t:
        p = QPixmap(t)
        if not p.isNull(): return p.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return QPixmap()


def do_rename(parent, store: MediaStore, path: str):
    stem, ok = dialogs.ask_text(parent, "Rename", "New name (without extension):", Path(path).stem)
    if not ok or not stem.strip(): return
    try:
        new = gallery.rename(path, stem.strip())
        if store.is_fav(path):
            store.cfg["favorites"].remove(path); store.cfg["favorites"].append(new); store.cfg.save()
        store.rescan()
    except Exception as e:
        dialogs.message(parent, "Rename failed", str(e))


def do_delete(parent, store: MediaStore, path: str):
    if not dialogs.confirm(parent, "Delete", f"Delete '{Path(path).name}'?\nIt will be moved to the recycle bin when possible.", danger=True):
        return
    try:
        gallery.delete(path); store.forget(path)
    except Exception as e:
        dialogs.message(parent, "Delete failed", str(e))


def show_media_menu(parent, store: MediaStore, path: str, global_pos, open_cb):
    """Right-click menu shared by the overlay strip and the full gallery."""
    if not Path(path).exists():
        store.forget(path); return
    m = QMenu(parent)
    m.addAction(icon("play" if path.lower().endswith(tuple(gallery.VIDEO_EXT)) else "image-outline"), "Open", lambda: open_cb(path))
    m.addAction(icon("folder-open"), "Show in folder", lambda: gallery.reveal(path))
    m.addAction(icon("content-copy"), "Copy file path", lambda: QGuiApplication.clipboard().setText(path))
    m.addAction(icon("open-in-new"), "Open in external player", lambda: gallery.open_external(path))
    m.addSeparator()
    fav = store.is_fav(path)
    m.addAction(icon("star-outline" if fav else "star"), "Remove favorite" if fav else "Add to favorites", lambda: store.toggle_fav(path))
    m.addAction(icon("rename-box"), "Rename...", lambda: do_rename(parent, store, path))
    m.addSeparator()
    m.addAction(icon("delete-outline", "#ff7b7b"), "Delete...", lambda: do_delete(parent, store, path))
    m.exec(global_pos)


class ImageViewer(QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent); self.setWindowTitle(Path(path).name); self.resize(900, 560)
        lay = QVBoxLayout(self); lab = QLabel(alignment=Qt.AlignCenter)
        pm = QPixmap(path)
        lab.setPixmap(pm.scaled(880, 520, Qt.KeepAspectRatio, Qt.SmoothTransformation)) if not pm.isNull() else lab.setText("Cannot load image")
        lay.addWidget(lab)
        dialogs.prepare_dialog(self)             # centered on the overlay's screen, clamped inside it


class PlayerWindow(QWidget):
    """Integrated player (Qt Multimedia). Codec support depends on the OS backend.

    Stability rules (root causes of the old "reload / restart" behaviour):
      * one long-lived QMediaPlayer; the source is only set when a DIFFERENT file is opened or while recovering;
      * re-opening the same clip never resets the source or the position;
      * "restart from 0" only happens at a real EndOfMedia, never from a duration/position heuristic;
      * a partially written (still growing) file is re-loaded at the last position instead of restarting;
      * closing the window pauses (keeps source + position) instead of stop();
      * errors show a Retry button that resumes from the last position."""
    MAX_RECOVERIES = 5

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("OBS Overlay - Player"); self.resize(960, 600); self.path = ""
        self._pos = 0; self._resume = None; self._recoveries = 0; self._size_seen = 0
        self.audio = QAudioOutput(); self.player = QMediaPlayer(self); self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget(); self.player.setVideoOutput(self.video)
        self.info = QLabel(); self.info.setObjectName("dim"); self.err = QLabel(); self.err.setStyleSheet("color:#ff7b7b")
        self.err.setWordWrap(True); self.err.hide()
        self.state_lab = QLabel(); self.state_lab.setObjectName("dim"); self.state_lab.hide()
        self.retry = QPushButton("Retry from last position"); self.retry.hide()
        self.play = tool_button("play", "Play / Pause (Space)"); self.seek = SeekSlider(Qt.Horizontal)
        self.time = QLabel("00:00 / 00:00"); self.vol = QSlider(Qt.Horizontal); self.vol.setRange(0, 100); self.vol.setValue(80)
        self.vol.setFixedWidth(90); self.audio.setVolume(0.8)
        self.mute = tool_button("volume-high", "Mute (M)", True)
        self.speed = QComboBox(); [self.speed.addItem(f"{s}x", s) for s in (0.25, 0.5, 1.0, 1.5, 2.0)]; self.speed.setCurrentIndex(2)
        self.loop = QCheckBox("Loop"); self.loop.setToolTip("Loop playback (L)")
        back, fwd = tool_button("skip-previous", "Previous frame (,)"), tool_button("skip-next", "Next frame (.)")
        full = tool_button("fullscreen", "Fullscreen (F)"); ext = QPushButton("Open externally")
        bar = QHBoxLayout()
        for w in (self.play, back, fwd): bar.addWidget(w)
        bar.addWidget(self.seek, 1); bar.addWidget(self.time); bar.addWidget(self.mute); bar.addWidget(self.vol)
        bar.addWidget(self.speed); bar.addWidget(self.loop); bar.addWidget(full); bar.addWidget(ext)
        lay = QVBoxLayout(self); lay.addWidget(self.video, 1); lay.addWidget(self.state_lab); lay.addWidget(self.err)
        lay.addWidget(self.retry); lay.addLayout(bar); lay.addWidget(self.info)
        self.play.clicked.connect(self.toggle)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.vol.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))
        self.mute.toggled.connect(self.audio.setMuted)
        self.speed.currentIndexChanged.connect(lambda: self.player.setPlaybackRate(self.speed.currentData()))
        self.loop.toggled.connect(lambda on: self.player.setLoops(-1 if on else 1))      # Qt loops internally, no manual restart
        back.clicked.connect(lambda: self.step(-1)); fwd.clicked.connect(lambda: self.step(1))
        full.clicked.connect(self.toggle_full); ext.clicked.connect(lambda: self.path and gallery.open_external(self.path))
        self.retry.clicked.connect(lambda: self._recover(self._pos))
        self.player.durationChanged.connect(lambda d: (self.seek.setRange(0, d), self._t()))
        self.player.positionChanged.connect(self._on_position)
        self.player.playbackStateChanged.connect(lambda s: self.play.setIcon(icon("pause" if s == QMediaPlayer.PlayingState else "play")))
        self.player.mediaStatusChanged.connect(self._status)
        self.player.errorOccurred.connect(self._error)
        for key, fn in (("Space", self.toggle), ("Left", lambda: self.jump(-5000)), ("Right", lambda: self.jump(5000)), ("F", self.toggle_full),
                        ("M", self.mute.toggle), ("L", self.loop.toggle), (",", lambda: self.step(-1)), (".", lambda: self.step(1)), ("Esc", self.on_esc)):
            QShortcut(QKeySequence(key), self, activated=fn)

    # ---- opening / recovery ---------------------------------------------------
    def open(self, path):
        M = QMediaPlayer
        same = path == self.path and self.player.mediaStatus() not in (M.NoMedia, M.InvalidMedia)
        self.show(); self.raise_(); self.activateWindow()
        if same:                                   # same clip: keep source and position, just make sure it plays
            if self.player.playbackState() != M.PlayingState: self.player.play()
            return
        try:
            st = os.stat(path)
        except OSError as e:
            self.err.setText(f"Cannot open file: {e.strerror}"); self.err.show(); return
        self.path = path; self.err.hide(); self.retry.hide(); self._pos = 0; self._resume = None
        self._recoveries = 0; self._size_seen = st.st_size
        self.setWindowTitle(Path(path).name)
        self.info.setText(f"{Path(path).name}  -  {gallery.fmt_size(st.st_size)}  -  {path}")
        self.player.setSource(QUrl.fromLocalFile(path)); self.player.play()

    def _recover(self, pos: int):
        """Re-load the same file and continue at `pos` (used for partial / still-growing files and after errors)."""
        if not self.path: return
        self._resume = max(0, int(pos)); self.err.hide(); self.retry.hide()
        self.player.setSource(QUrl()); self.player.setSource(QUrl.fromLocalFile(self.path))   # empty first: forces a real reload

    def _file_grew(self) -> bool:
        try:
            size = os.stat(self.path).st_size
        except OSError:
            return False
        grew = size > self._size_seen + 1024
        self._size_seen = max(self._size_seen, size)
        return grew

    def _status(self, s):
        M = QMediaPlayer
        if s in (M.LoadingMedia, M.StalledMedia, M.BufferingMedia):
            self.state_lab.setText("Loading..." if s == M.LoadingMedia else "Buffering..."); self.state_lab.show()
        else:
            self.state_lab.hide()
        if s in (M.LoadedMedia, M.BufferedMedia) and self._resume is not None:
            pos, self._resume = self._resume, None
            self.player.setPosition(pos); self.player.play()
        elif s == M.EndOfMedia and self._file_grew() and self._recoveries < self.MAX_RECOVERIES:
            self._recoveries += 1                                   # file was still being written: continue, don't restart
            self.state_lab.setText("Waiting for the rest of the file..."); self.state_lab.show()
            QTimer.singleShot(600, lambda: self._recover(self._pos))

    def _error(self, _err, msg):
        self.err.setText(f"Playback error: {msg}. The codec may be unsupported - use 'Open externally'.")
        self.err.show(); self.retry.show()
        if self._file_grew() and self._recoveries < self.MAX_RECOVERIES:
            self._recoveries += 1
            QTimer.singleShot(800, lambda: self._recover(self._pos))

    # ---- controls -------------------------------------------------------------
    def toggle(self):
        M = QMediaPlayer
        if self.player.playbackState() == M.PlayingState:
            self.player.pause(); return
        if self.player.mediaStatus() == M.EndOfMedia:               # only a REAL end restarts the clip
            self.player.setPosition(0)
        self.player.play()

    def jump(self, ms): self.player.setPosition(max(0, self.player.position() + ms))

    def step(self, n):
        self.player.pause(); self.player.setPosition(max(0, self.player.position() + n * 33))   # ~1 frame @30fps (approximate)

    def toggle_full(self): self.showNormal() if self.isFullScreen() else self.showFullScreen()
    def on_esc(self): self.showNormal() if self.isFullScreen() else None

    def _on_position(self, p):
        if self._resume is None: self._pos = p
        if not self.seek.isSliderDown(): self.seek.setValue(p)
        self._t()

    def _t(self):
        f = lambda ms: gallery.fmt_duration(ms / 1000)
        self.time.setText(f"{f(self.player.position())} / {f(self.player.duration())}")

    def closeEvent(self, e):
        self.player.pause()                         # keep source + position; reopening the same clip resumes
        e.accept()


class GalleryWindow(QWidget):
    open_media = Signal(str)

    def __init__(self, store: MediaStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.search = QLineEdit(); self.search.setPlaceholderText("Search by filename"); self.search.setClearButtonEnabled(True)
        self.kind = QComboBox(); self.kind.addItems(["All", "Recordings", "Clips (replays)", "Screenshots", "Favorites"])
        self.game = QComboBox(); self.game.addItem("All games / folders")
        self.sort = QComboBox(); self.sort.addItems(["Newest", "Oldest", "Duration", "File size"])
        refresh = tool_button("refresh", "Rescan folders"); folder = tool_button("folder-open", "Open gallery folder")
        self.status = QLabel(); self.status.setObjectName("dim")
        top = QVBoxLayout(); r1, r2 = QHBoxLayout(), QHBoxLayout()
        r1.addWidget(self.search, 1); r1.addWidget(refresh); r1.addWidget(folder)
        for w in (self.kind, self.game, self.sort): r2.addWidget(w)
        top.addLayout(r1); top.addLayout(r2)
        self.list = QListWidget(); self.list.setViewMode(QListView.IconMode); self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static); self.list.setWordWrap(True); self.list.setSpacing(8)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu); self.list.setUniformItemSizes(True)
        lay = QVBoxLayout(self); lay.addLayout(top); lay.addWidget(self.list, 1); lay.addWidget(self.status)
        self._items: dict[str, QListWidgetItem] = {}
        store.changed.connect(self.rebuild); store.thumb_ready.connect(self._thumb)
        self.search.textChanged.connect(self.rebuild)
        for c in (self.kind, self.game, self.sort): c.currentIndexChanged.connect(self.rebuild)
        refresh.clicked.connect(store.rescan)
        folder.clicked.connect(lambda: gallery.open_external(store.cfg["gallery_root"]) if Path(store.cfg["gallery_root"]).is_dir() else None)
        self.list.itemActivated.connect(lambda it: self.open_media.emit(it.data(Qt.UserRole)))
        self.list.customContextMenuRequested.connect(self.menu)
        self._vis_timer = QTimer(self); self._vis_timer.setInterval(150); self._vis_timer.timeout.connect(self._load_visible)
        self.list.verticalScrollBar().valueChanged.connect(lambda _: self._vis_timer.start())

    def showEvent(self, e):
        super().showEvent(e); self.store.rescan()

    def _filtered(self):
        q, k, g = self.search.text().lower().strip(), self.kind.currentIndex(), self.game.currentText()
        out = []
        for m in self.store.items:
            if q and q not in m.name.lower(): continue
            if k == 1 and m.kind != "video": continue
            if k == 2 and not m.is_clip: continue
            if k == 3 and m.kind != "image": continue
            if k == 4 and not self.store.is_fav(m.path): continue
            if self.game.currentIndex() > 0 and m.game != g: continue
            out.append(m)
        s = self.sort.currentIndex()
        keyf = {0: lambda m: -m.mtime, 1: lambda m: m.mtime, 2: lambda m: -(m.duration or -1), 3: lambda m: -m.size}[s]
        return sorted(out, key=lambda m: (not self.store.is_fav(m.path), keyf(m)))

    def rebuild(self):
        games = sorted({m.game for m in self.store.items})
        cur = self.game.currentText()
        self.game.blockSignals(True); self.game.clear(); self.game.addItem("All games / folders"); self.game.addItems(games)
        i = self.game.findText(cur); self.game.setCurrentIndex(max(i, 0)); self.game.blockSignals(False)
        ts = int(self.store.cfg["thumb_size"]); self.list.setIconSize(QSize(ts, int(ts * 0.6))); self.list.setGridSize(QSize(ts + 16, int(ts * 0.6) + 56))
        self.list.clear(); self._items.clear()
        items = self._filtered()
        for i, m in enumerate(items):
            star = "* " if self.store.is_fav(m.path) else ""
            sub = (gallery.fmt_duration(m.duration) + "  " if m.kind == "video" else "") + gallery.fmt_size(m.size)
            it = QListWidgetItem(f"{star}{self.store.display_name(m, i)}\n{m.game} - {sub}")
            it.setData(Qt.UserRole, m.path); it.setToolTip(m.path if not self.store.cfg["hide_filenames"] else "")
            p = pix_for(self.store, m, ts)
            if not p.isNull(): it.setIcon(QIcon(p))
            self.list.addItem(it); self._items[m.path] = it
        if not items:
            self.status.setText("Scanning..." if self.store.scanning else
                                "No media found. Record something in OBS, or set the gallery folder in Settings > Gallery.")
        else:
            self.status.setText(f"{len(items)} item(s)")
        self._load_visible()

    def _load_visible(self):
        self._vis_timer.stop()
        vp = self.list.viewport().rect(); by_path = {m.path: m for m in self.store.items}
        for path, it in self._items.items():
            if self.list.visualItemRect(it).intersects(vp) and path in by_path:
                self.store.request_thumb(by_path[path])          # lazy: only what is on screen

    def _thumb(self, path):
        it = self._items.get(path); m = next((x for x in self.store.items if x.path == path), None)
        if it and m:
            p = pix_for(self.store, m, int(self.store.cfg["thumb_size"]))
            if not p.isNull(): it.setIcon(QIcon(p))
            if m.kind == "video" and m.duration is not None and self.sort.currentIndex() == 2: self._vis_timer.start(); self.rebuild()

    def menu(self, pos):
        it = self.list.itemAt(pos)
        if it: show_media_menu(self, self.store, it.data(Qt.UserRole), self.list.mapToGlobal(pos), self.open_media.emit)


class GalleryStrip(QScrollArea):
    """Horizontal strip of recent captures for the compact overlay."""
    activated = Signal(str)

    def __init__(self, store: MediaStore):
        super().__init__(); self.store = store
        self.setFixedHeight(96); self.setFrameShape(QScrollArea.NoFrame); self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.host = QWidget(); self.host.setObjectName("plain"); self.hl = QHBoxLayout(self.host)
        self.hl.setContentsMargins(12, 4, 12, 4); self.hl.setSpacing(8); self.setWidget(self.host)
        store.changed.connect(self.rebuild); store.thumb_ready.connect(lambda _: self.rebuild())
        self._pending = QTimer(self); self._pending.setSingleShot(True); self._pending.setInterval(120); self._pending.timeout.connect(self._build)

    def rebuild(self): self._pending.start()

    def _build(self):
        while self.hl.count():
            w = self.hl.takeAt(0).widget()
            if w: w.deleteLater()
        recent = self.store.items[:12]
        if not recent:
            l = QLabel("No captures yet - record, save a replay or take a screenshot."); l.setObjectName("dim"); self.hl.addWidget(l); self.hl.addStretch(); return
        for m in recent:
            self.store.request_thumb(m)
            b = QToolButton(); b.setFixedSize(112, 80); b.setToolTip(f"{self.store.display_name(m)}\n{m.game}\nRight-click for actions")
            p = pix_for(self.store, m, 112)
            b.setIcon(QIcon(p) if not p.isNull() else icon("movie-open-outline" if m.kind == "video" else "image-outline", FG_DIM))
            b.setIconSize(QSize(108, 76)); b.setCursor(Qt.PointingHandCursor)
            lab = QLabel(gallery.fmt_duration(m.duration) if m.kind == "video" else "IMG", b)
            lab.setStyleSheet("background:rgba(0,0,0,170); border-radius:3px; padding:0 3px; font-size:11px;"); lab.move(4, 4)
            b.clicked.connect(lambda _=False, pth=m.path: self.activated.emit(pth))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda pos, btn=b, pth=m.path: show_media_menu(self, self.store, pth, btn.mapToGlobal(pos), self.activated.emit))
            self.hl.addWidget(b)
        self.hl.addStretch()
