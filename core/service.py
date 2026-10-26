"""ObsService: single source of truth for UI state. All blocking OBS calls run on one worker thread;
results come back to the UI thread through Qt signals. OBS events trigger a state refresh, so the UI
reflects real OBS state (scene changes, recording ended externally, ...) rather than local button state."""
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .audio import apply_roles
from .backends import ObsBackend, DemoBackend, BackendError
from .config import Settings, data_dir

STATUS_TEXT = {
    "connected": "Connected to OBS", "connecting": "Connecting...", "disconnected": "Disconnected",
    "auth_required": "Authentication required", "unavailable": "OBS unavailable", "demo": "Demo mode",
}


class ObsService(QObject):
    state_changed = Signal()
    notify = Signal(str, str)            # level (info|success|warn|error), text
    media_created = Signal(str)          # path of a new recording / replay / screenshot
    preview_ready = Signal(bytes)
    meters_changed = Signal()            # fresh real audio levels from OBS
    _call_done = Signal(object, object, object)   # callback, result, error  (worker -> UI thread)
    _event = Signal(str, dict)

    def __init__(self, settings: Settings):
        super().__init__()
        self.cfg = settings
        self.status = "disconnected"
        self.error = ""
        self.snap: dict = {}
        self.meters: dict[str, float] = {}
        self.preview_ms = 0.0
        self.backend = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="obs")
        self._busy: set[str] = set()
        self._call_done.connect(self._finish)
        self._event.connect(self._on_event)
        self._retry = QTimer(self); self._retry.setInterval(5000); self._retry.timeout.connect(self.connect_backend)
        self._live = QTimer(self); self._live.setInterval(5000); self._live.timeout.connect(self._liveness)
        self._poll = QTimer(self); self._poll.setInterval(1000); self._poll.timeout.connect(self.refresh)
        self.notifications: list[tuple[str, str, str]] = []

    # ---- helpers -----------------------------------------------------------
    @property
    def ok(self) -> bool: return self.status in ("connected", "demo")
    @property
    def status_text(self) -> str: return STATUS_TEXT.get(self.status, self.status)

    def say(self, level, text):
        self.notifications.append((datetime.now().strftime("%H:%M:%S"), level, text))
        del self.notifications[:-100]
        self.notify.emit(level, text)

    def _run(self, fn, cb=None, key=None):
        """Run fn on the worker thread. `key` prevents duplicate in-flight commands (e.g. double-click Record)."""
        if key:
            if key in self._busy:
                return
            self._busy.add(key)

        def job():
            try:
                res, err = fn(), None
            except Exception as e:
                res, err = None, e
            self._call_done.emit((cb, key), res, err)
        self._pool.submit(job)

    def _finish(self, meta, res, err):
        cb, key = meta
        if key:
            self._busy.discard(key)
        if cb:
            cb(res, err)

    # ---- connection --------------------------------------------------------
    def connect_backend(self):
        if self.status == "connecting":
            return
        self._retry.stop()
        self.disconnect_backend(quiet=True)
        if self.cfg["mode"] == "demo":
            self.backend = DemoBackend(self._emit_from_thread, Path(self.cfg["gallery_root"]) / "Demo")
        else:
            host = self.cfg["host"].strip() or "localhost"
            if host not in ("localhost", "127.0.0.1", "::1") and not self.cfg["remote_allowed"]:
                self.status, self.error = "unavailable", "Remote OBS connections are disabled (Settings > Privacy)."
                self.state_changed.emit(); return
            self.backend = ObsBackend(host, int(self.cfg["port"]), self.cfg.get_password(),
                                      float(self.cfg["timeout"]), self._emit_from_thread,
                                      meters=bool(self.cfg["audio_detect"]))
        self.status, self.error = "connecting", ""
        self.state_changed.emit()
        b = self.backend

        def work():
            b.connect()
            return b.snapshot()

        def done(res, err):
            if b is not self.backend:
                return                                   # superseded by a newer connect
            if err:
                st = err.status if isinstance(err, BackendError) else "unavailable"
                self.status, self.error = st, str(err)
                self.state_changed.emit()
                if self.cfg["auto_reconnect"] and st != "auth_required" and self.cfg["mode"] == "obs":
                    self._retry.start()
                return
            self.snap = apply_roles(res, self.cfg["mic_source"], self.cfg["desktop_source"])
            self.status = "demo" if b.name == "demo" else "connected"
            if getattr(b, "meter_note", ""): self.say("warn", b.meter_note)
            if b.name == "obs" and self.cfg["audio_detect"]: QTimer.singleShot(4000, self._check_meters)
            self.say("success", "Demo mode active" if b.name == "demo" else "Connected to OBS")
            self._live.start() if b.name == "obs" else None
            self._apply_poll()
            self.state_changed.emit()
        self._run(work, done)

    def disconnect_backend(self, quiet=False):
        self._live.stop(); self._poll.stop(); self._retry.stop()
        b, self.backend = self.backend, None
        if b:
            self._pool.submit(b.disconnect)             # clean up event subscriptions off the UI thread
        was = self.status
        self.status, self.snap, self.meters = "disconnected", {}, {}
        if not quiet and was in ("connected", "demo"):
            self.say("warn", "Disconnected")
        self.state_changed.emit()

    def _liveness(self):
        b = self.backend
        if not b or self.status != "connected":
            return

        def done(res, err):
            if err and b is self.backend:
                self._lost("OBS connection lost")
        self._run(b.ping, done, key="ping")

    def _lost(self, text):
        if self.status not in ("connected",):
            return
        self.say("error", text)
        self.disconnect_backend(quiet=True)
        self.status = "unavailable"; self.error = text
        self.state_changed.emit()
        if self.cfg["auto_reconnect"]:
            self._retry.start()

    # ---- events ------------------------------------------------------------
    def _emit_from_thread(self, name, payload):
        self._event.emit(name, payload)                 # thread-safe hop to UI thread

    def _on_event(self, name, p):
        if name == "exit":
            self._lost("OBS closed"); return
        if name == "meters":                      # high-frequency: update levels only, no full refresh
            self.meters = p["levels"]; self.meters_changed.emit(); return
        if name == "record":
            if not p.get("active") and p.get("path"):
                self.say("success", f"Recording saved: {Path(p['path']).name}")
                self.media_created.emit(p["path"])
            elif p.get("state", "").endswith("STARTED") or p.get("state") == "started":
                self.say("info", "Recording started")
        elif name == "replay_saved":
            self.say("success", f"Replay saved: {Path(p['path']).name}")
            self.media_created.emit(p["path"])
        elif name == "stream":
            self.say("info", "Stream started" if p.get("active") else "Stream stopped")
        elif name == "scene":
            self.say("info", f"Scene: {p['name']}")
        elif name == "mute":
            self.say("info", f"{p['name']} {'muted' if p['muted'] else 'unmuted'}")
        self.refresh()

    # ---- state refresh -----------------------------------------------------
    def refresh(self):
        b = self.backend
        if not b or not self.ok:
            return

        def done(res, err):
            if b is not self.backend:
                return
            if err:
                if b.name == "obs":
                    self._lost("OBS connection lost")
                return
            self.snap = apply_roles(res, self.cfg["mic_source"], self.cfg["desktop_source"])
            self._apply_poll()
            self.state_changed.emit()
        self._run(b.snapshot, done, key="refresh")

    def _check_meters(self):
        b = self.backend
        if b is None or b.name != "obs" or not self.ok or not self.cfg["audio_detect"]: return
        h = getattr(b, "handler", None)
        if h is not None and h.meter_events == 0:
            self.say("warn", "Audio detection: OBS has sent no level data. Check Settings > Advanced > Connection diagnostics")

    def diagnostics(self) -> str:
        b = self.backend
        return b.diagnostics() if b is not None and hasattr(b, "diagnostics") else "not connected to OBS"

    def _apply_poll(self):
        # Poll only while something time-based is active or the stats panel is visible (no idle polling).
        s = self.snap
        active = s.get("recording") or s.get("streaming") or self.cfg["stats_visible"]
        if active:
            self._poll.setInterval(max(500, int(self.cfg["stats_interval_ms"])))
            self._poll.start()
        else:
            self._poll.stop()

    # ---- commands ----------------------------------------------------------
    def _cmd(self, fn, key, ok_text=None):
        if not self.ok or not self.backend:
            self.say("warn", "Not connected to OBS"); return

        def done(res, err):
            if err:
                self.say("error", f"{key.replace('_', ' ').capitalize()} failed: {err}")
            elif ok_text:
                self.say("success", ok_text)
            self.refresh()
        self._run(fn, done, key=key)

    def toggle_record(self):
        b = self.backend
        if not b: return self.say("warn", "Not connected to OBS")
        self._cmd(b.stop_record if self.snap.get("recording") else b.start_record, "record")

    def toggle_pause(self): self.backend and self._cmd(self.backend.toggle_pause, "pause")

    def toggle_stream(self):
        b = self.backend
        if not b: return self.say("warn", "Not connected to OBS")
        if not self.snap.get("streaming") and self.cfg["mode"] == "obs":
            pass  # OBS reports an error if no service is configured; surfaced by _cmd
        self._cmd(b.stop_stream if self.snap.get("streaming") else b.start_stream, "stream")

    def toggle_replay(self):
        b = self.backend
        if not b: return self.say("warn", "Not connected to OBS")
        if not self.snap.get("replay_available", True):
            return self.say("warn", "Replay Buffer is not enabled in OBS (Settings > Output > Replay Buffer)")
        if self.snap.get("replay_active"):
            self._cmd(b.stop_replay, "replay_toggle", "Instant Replay off")
        else:
            secs = int(self.cfg["replay_seconds"])
            def start():
                try: b.set_replay_seconds(secs)
                except Exception: pass                  # not fatal; OBS keeps its own configured length
                b.start_replay()
            self._cmd(start, "replay_toggle", f"Instant Replay on ({secs}s)")

    def save_replay(self):
        b = self.backend
        if not b: return self.say("warn", "Not connected to OBS")
        if not self.snap.get("replay_active"):
            return self.say("warn", "Instant Replay is off - turn it on first")
        self._cmd(b.save_replay, "replay_save")

    def set_scene(self, name):
        if self.backend and name and name != self.snap.get("scene"):
            self._cmd(lambda: self.backend.set_scene(name), "scene")

    def set_mute(self, name, muted):
        if self.backend and name:
            self._cmd(lambda: self.backend.set_mute(name, muted), f"mute_{name}")

    def toggle_mute_role(self, role: str):
        name = self.snap.get(role)
        if not name:
            return self.say("warn", f"No {role} audio source found in OBS")
        cur = next((i["muted"] for i in self.snap["inputs"] if i["name"] == name), False)
        self.set_mute(name, not cur)

    def set_role(self, role: str, name: str):
        """Choose which OBS audio source is the microphone / desktop audio ('' = auto-detect). No new OBS inputs are created."""
        if role not in ("mic", "desktop"):
            return
        if name and name not in {i["name"] for i in self.snap.get("inputs", [])}:
            return self.say("warn", f"Audio source '{name}' is not available in OBS")
        other = "desktop" if role == "mic" else "mic"
        if name and self.cfg[f"{other}_source"] == name:
            self.cfg[f"{other}_source"] = ""            # one source cannot be both
        self.cfg[f"{role}_source"] = name; self.cfg.save()
        self.say("info", f"{'Microphone' if role == 'mic' else 'Desktop audio'}: {name or 'auto-detect'}")
        self.refresh()

    def set_volume_db(self, name, db):
        if self.backend:
            self._run(lambda: self.backend.set_volume_db(name, db), lambda r, e: None)

    def set_item_enabled(self, item_id, enabled):
        b, scene = self.backend, self.snap.get("scene")
        if b and scene:
            self._cmd(lambda: b.set_item_enabled(scene, item_id, enabled), f"item_{item_id}")

    def set_item_locked(self, item_id, locked):
        b, scene = self.backend, self.snap.get("scene")
        if b and scene:
            self._cmd(lambda: b.set_item_locked(scene, item_id, locked), f"itemlock_{item_id}")

    def toggle_vcam(self):
        b = self.backend
        if not b: return self.say("warn", "Not connected to OBS")
        if self.snap.get("vcam") is None: return self.say("warn", "Virtual camera is not available in this OBS")
        self._cmd(b.stop_vcam if self.snap.get("vcam") else b.start_vcam, "vcam",
                  "Virtual camera off" if self.snap.get("vcam") else "Virtual camera on")

    def screenshot(self):
        b = self.backend
        if not b or not self.ok:
            return self.say("warn", "Not connected to OBS")
        fmt = self.cfg["screenshot_format"]
        stem = datetime.now().strftime(self.cfg["screenshot_pattern"]) or datetime.now().strftime("Screenshot_%Y%m%d_%H%M%S")
        stem = "".join(c for c in stem if c not in '\\/:*?"<>|')
        path = Path(self.cfg["screenshot_dir"]) / f"{stem}.{'jpg' if fmt == 'jpg' else 'png'}"
        scene, q = self.snap.get("scene", ""), self.cfg["screenshot_quality"]

        def done(res, err):
            if err:
                self.say("error", f"Screenshot failed: {err}")
            else:
                self.say("success", f"Screenshot of OBS output saved: {path.name}")
                self.media_created.emit(str(path))
        self._run(lambda: b.screenshot(scene, str(path), fmt, q), done, key="shot")

    def request_preview(self):
        b = self.backend
        if not b or not self.ok: return
        scene, w = self.snap.get("scene", ""), int(self.cfg["preview_width"])

        def work():
            t0 = time.perf_counter()
            return b.preview_png(scene, w), (time.perf_counter() - t0) * 1000

        def done(res, err):
            if not err and res and res[0]:
                self.preview_ms = res[1]; self.preview_ready.emit(res[0])
        self._run(work, done, key="preview")        # key: never queue a new frame while one is still processing

    def test_connection(self, host, port, password, cb):
        """Standalone connection test that does not disturb the active session."""
        def work():
            t = ObsBackend(host, int(port), password, 4, lambda *a: None)
            try:
                t.connect()
                return t.req.get_version().obs_version
            finally:
                t.disconnect()
        self._run(work, cb)

    def shutdown(self):
        self.disconnect_backend(quiet=True)
        self._pool.shutdown(wait=False, cancel_futures=True)
