"""Pure logic: turns the OBS state snapshot into display rows for each floating widget kind.
Unknown values are shown as 'Unavailable' - never invented."""
from __future__ import annotations
from .gallery import fmt_size

WHITE, RED, GREEN, DIM = "#f2f2f2", "#ff7b7b", "#4cc38a", "#9a9a9a"
U = "Unavailable"

METRICS = {"connection": "OBS connection", "recording": "Recording status/time", "streaming": "Streaming status/time",
           "bitrate": "Bitrate", "dropped": "Dropped frames", "resolution": "Output resolution", "fps": "FPS",
           "cpu": "System CPU", "memory": "System RAM", "replay": "Replay buffer"}

KINDS = {"stats": ("Statistics", (270, 200)), "recording": ("Recording timer", (210, 84)),
         "stream": ("Stream status", (240, 118)), "scene": ("Current scene", (230, 62)),
         "audio": ("Mic / desktop status", (210, 92)), "web": ("Web dock", (380, 520))}


def elapsed(sec: float) -> str:
    sec = int(max(sec or 0, 0)); h, r = divmod(sec, 3600); m, s = divmod(r, 60)
    return f"{h:d}:{m:02d}:{s:02d}"


def build_rows(kind: str, wc: dict, snap: dict, status_text: str, ok: bool, warn: dict, sysm: dict):
    """Returns [(label, value, color)]. warn = {'dropped': pct, 'cpu': pct}; sysm = {'cpu': %, 'mem': %}."""
    s = snap or {}
    if kind != "stats" and not ok:
        return [("OBS", status_text, RED)]
    if kind == "recording":
        if not s.get("recording"):
            return [("Recording", "Idle", DIM)]
        paused = s.get("paused")
        return [("Paused" if paused else "REC", elapsed(s.get("rec_dur", 0)), WHITE if paused else RED),
                ("Size", fmt_size(s.get("rec_bytes", 0)), WHITE)]
    if kind == "stream":
        if not s.get("streaming"):
            return [("Stream", "Offline", DIM)]
        br, dp = s.get("bitrate_kbps"), s.get("dropped_pct")
        return [("LIVE", elapsed(s.get("stream_dur", 0)), GREEN),
                ("Bitrate", f"{br:.0f} kbps" if br is not None else U, WHITE),
                ("Dropped", f"{dp:.2f}%" if dp is not None else U, RED if dp is not None and dp >= warn["dropped"] else WHITE)]
    if kind == "scene":
        return [("Scene", s.get("scene") or U, WHITE)]
    if kind == "audio":
        inp = {i["name"]: i for i in s.get("inputs", [])}
        rows = []
        for role, label in (("mic", "Mic"), ("desktop", "Desktop")):
            i = inp.get(s.get(role))
            rows.append((label, U if not i else ("MUTED" if i["muted"] else "LIVE"), DIM if not i else (RED if i["muted"] else GREEN)))
        return rows
    # --- statistics (user-selectable metrics, in a fixed order)
    m = set(wc.get("metrics", [])); rows = []

    def add(key, label, val, col=WHITE):
        if key in m:
            rows.append((label, val, col))
    add("connection", "OBS", status_text, GREEN if ok else RED)
    rec = s.get("recording")
    add("recording", "Recording", f"{'Paused' if s.get('paused') else 'REC'} {elapsed(s.get('rec_dur', 0))}" if rec else "Idle",
        (WHITE if s.get("paused") else RED) if rec else DIM)
    live = s.get("streaming")
    add("streaming", "Streaming", f"LIVE {elapsed(s.get('stream_dur', 0))}" if live else "Offline", GREEN if live else DIM)
    br = s.get("bitrate_kbps"); add("bitrate", "Bitrate", f"{br:.0f} kbps" if br is not None else U, WHITE if br is not None else DIM)
    dp = s.get("dropped_pct")
    add("dropped", "Dropped", f"{dp:.2f}%" if dp is not None else U, RED if dp is not None and dp >= warn["dropped"] else (WHITE if dp is not None else DIM))
    r = s.get("out_res"); add("resolution", "Output", f"{r[0]}x{r[1]}" if r else U, WHITE if r else DIM)
    add("fps", "FPS", f"{s['fps']:g}" if s.get("fps") else U, WHITE if s.get("fps") else DIM)
    cpu = sysm.get("cpu"); add("cpu", "System CPU", f"{cpu:.0f}%" if cpu is not None else U, RED if cpu is not None and cpu >= warn["cpu"] else WHITE)
    mem = sysm.get("mem"); add("memory", "System RAM", f"{mem:.0f}%" if mem is not None else U)
    rep = (("On" if s.get("replay_active") else "Off") if s.get("replay_available", True) else "Not enabled in OBS")
    add("replay", "Replay buffer", rep, GREEN if s.get("replay_active") else DIM)
    return rows
