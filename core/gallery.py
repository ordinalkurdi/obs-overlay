"""Qt-free media gallery: recursive scan (per-game / replay subfolders), thumbnails, file ops."""
from __future__ import annotations
import hashlib, os, subprocess, sys
from dataclasses import dataclass
from pathlib import Path

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".flv", ".avi", ".ts"}
IMAGE_EXT = {".png", ".jpg", ".jpeg"}


@dataclass
class Media:
    path: str
    name: str
    kind: str            # "video" | "image"
    game: str            # first sub-folder below the gallery root
    folder: str          # relative sub-folder path
    is_clip: bool        # lives in a replay/clip folder or has "replay"/"clip" in its path
    size: int
    mtime: float
    duration: float | None = None
    width: int | None = None
    height: int | None = None


def scan(root: str, max_depth: int = 8) -> list[Media]:
    rootp = Path(root)
    out: list[Media] = []
    if not rootp.is_dir():
        return out
    base_depth = len(rootp.parts)
    for dirpath, dirnames, filenames in os.walk(rootp):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() != "$recycle.bin"]
        if len(Path(dirpath).parts) - base_depth >= max_depth:
            dirnames[:] = []
        rel = Path(dirpath).relative_to(rootp)
        game = rel.parts[0] if rel.parts else "(root)"
        for fn in filenames:
            ext = Path(fn).suffix.lower()
            kind = "video" if ext in VIDEO_EXT else "image" if ext in IMAGE_EXT else None
            if not kind:
                continue
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            low = (str(rel) + "/" + fn).lower()
            is_clip = kind == "video" and ("replay" in low or "clip" in low)
            out.append(Media(str(p), fn, kind, game, str(rel) if rel.parts else "",
                             is_clip, st.st_size, st.st_mtime))
    return out


def video_info(path: str):
    """(duration_s, width, height) or (None, None, None)."""
    try:
        import cv2
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return None, None, None
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        return (frames / fps if fps > 0 and frames > 0 else None), w, h
    except Exception:
        return None, None, None


def thumbnail(path: str, cache_dir: Path, size: int = 320) -> str | None:
    """Create (or reuse) a cached PNG thumbnail. Decodes a single frame of a video."""
    try:
        import cv2
        import numpy as np
        st = os.stat(path)
        key = hashlib.sha1(f"{path}|{st.st_mtime_ns}|{st.st_size}|{size}".encode()).hexdigest()
        out = cache_dir / f"{key}.png"
        if out.exists():
            return str(out)
        cache_dir.mkdir(parents=True, exist_ok=True)
        frame = None
        if Path(path).suffix.lower() in VIDEO_EXT:
            cap = cv2.VideoCapture(path)
            n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            if n > 10:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * 0.1))
            ok, frame = cap.read()
            cap.release()
            if not ok:
                frame = None
        else:
            data = np.fromfile(path, dtype=np.uint8)      # unicode-safe on Windows
            frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if frame is None:
            return None
        h, w = frame.shape[:2]
        scale = size / max(w, h)
        if scale < 1:
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", frame)
        if not ok:
            return None
        out.write_bytes(buf.tobytes())
        return str(out)
    except Exception:
        return None


def fmt_duration(sec: float | None) -> str:
    if sec is None:
        return "--:--"
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_size(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return ""


def valid_filename(name: str) -> bool:
    return bool(name) and name not in (".", "..") and not any(c in name for c in '\\/:*?"<>|\0') and len(name) < 200


def rename(path: str, new_stem: str) -> str:
    p = Path(path)
    new_name = new_stem + p.suffix
    if not valid_filename(new_name):
        raise ValueError("Invalid file name")
    dest = p.with_name(new_name)
    if dest.exists():
        raise FileExistsError(f"{new_name} already exists")
    p.rename(dest)
    return str(dest)


def delete(path: str):
    try:
        from send2trash import send2trash
        send2trash(path)               # recoverable
    except ImportError:
        os.remove(path)


def reveal(path: str):
    """Open the containing folder (selecting the file where supported). No shell; args passed as a list."""
    p = str(Path(path))
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", p])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", p])
    else:
        subprocess.Popen(["xdg-open", str(Path(p).parent)])


def open_external(path: str):
    if sys.platform.startswith("win"):
        os.startfile(path)             # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
