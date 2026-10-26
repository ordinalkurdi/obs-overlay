"""Backends: ObsBackend (real OBS via obs-websocket v5) and DemoBackend (in-memory simulation).

Both expose the same blocking interface; ObsService runs them on a worker thread.
Snapshot dict keys are identical for both so the UI never cares which one is active.
"""
from __future__ import annotations
import base64, time, threading
from pathlib import Path

from .audio import peak_from_levels

AUDIO_KIND_HINTS = ("wasapi", "pulse", "alsa", "coreaudio", "audio")


class BackendError(Exception):
    """Carries a status hint: 'auth_required' | 'unavailable' | 'error'."""
    def __init__(self, msg, status="error"):
        super().__init__(msg)
        self.status = status


def _empty_snapshot() -> dict:
    return dict(recording=False, paused=False, rec_dur=0.0, rec_bytes=0, rec_path="",
                streaming=False, stream_dur=0.0, stream_server="", stream_service="",
                bitrate_kbps=None, dropped_pct=None, replay_available=True, replay_active=False,
                scenes=[], scene="", items=[], vcam=None, inputs=[], mic=None, desktop=None, fps=None,
                obs_cpu=None, base_res=None, out_res=None, version="", caps={})


class ObsBackend:
    name = "obs"

    def __init__(self, host, port, password, timeout, emit, meters=False):
        self.host, self.port, self.password, self.timeout = host, port, password, timeout
        self.meters, self.meter_note = meters, ""
        self.subs_mask = 0; self.registered: list[str] = []; self.handler = None
        self.emit = emit                    # emit(event_name, payload_dict)
        self.req = None
        self.ev = None
        self._last_bytes = None
        self._last_t = None

    # ---- connection --------------------------------------------------------
    def connect(self):
        import obsws_python as obs
        try:
            self.req = obs.ReqClient(host=self.host, port=self.port, password=self.password, timeout=self.timeout)
            kw = {}
            if self.meters:
                # obs-websocket eventSubscriptions bitmask: all low-volume events (bits 0-10 = 2047) + InputVolumeMeters (1 << 16).
                # Plain integers: the enum member names differ between obsws-python versions.
                kw["subs"] = 2047 | (1 << 16)
            self.subs_mask = kw.get("subs", 2047)
            self.ev = obs.EventClient(host=self.host, port=self.port, password=self.password, **kw)
            self.handler = _Events(self.emit)
            fns = self.handler.callbacks()                 # explicit functions with proper __name__ (what obsws-python dispatches on)
            self.registered = [f.__name__ for f in fns]
            self.ev.callback.register(fns)
        except Exception as e:                       # classify without ever echoing the password
            msg = str(e).lower()
            self.disconnect()
            if "auth" in msg or "4009" in msg or "password" in msg:
                raise BackendError("Authentication failed - check the WebSocket password in OBS "
                                   "(Tools > WebSocket Server Settings).", "auth_required")
            if isinstance(e, (ConnectionRefusedError, TimeoutError, OSError)) or "refused" in msg or "timed out" in msg:
                raise BackendError("OBS is not reachable. Is OBS running with the WebSocket server enabled "
                                   f"on {self.host}:{self.port}?", "unavailable")
            raise BackendError(f"Connection failed: {type(e).__name__}", "error")

    def disconnect(self):
        for c in (self.ev, self.req):
            try:
                if c:
                    c.disconnect()
            except Exception:
                pass
        self.ev = self.req = None

    def ping(self):
        self.req.get_version()

    def diagnostics(self) -> str:
        h = self.handler
        return (f"event subscriptions mask: {self.subs_mask} (meters {'on' if self.meters else 'off'})\n"
                f"registered event handlers: {len(self.registered)}\n"
                f"volume-meter events received: {h.meter_events if h else 0}\n"
                f"last handler error: {(h.last_error if h else '') or 'none'}")

    # ---- state -------------------------------------------------------------
    def snapshot(self) -> dict:
        r, d = self.req, _empty_snapshot()
        v = r.get_version()
        d["version"] = f"OBS {v.obs_version} / WebSocket {v.obs_web_socket_version}"
        d["caps"] = {"requests": len(getattr(v, "available_requests", []) or []),
                     "rpc_version": getattr(v, "rpc_version", None)}
        rs = r.get_record_status()
        d.update(recording=rs.output_active, paused=getattr(rs, "output_paused", False),
                 rec_dur=rs.output_duration / 1000.0, rec_bytes=rs.output_bytes)
        ss = r.get_stream_status()
        d.update(streaming=ss.output_active, stream_dur=ss.output_duration / 1000.0)
        d["dropped_pct"] = (100.0 * ss.output_skipped_frames / ss.output_total_frames) if ss.output_total_frames else (0.0 if ss.output_active else None)
        now = time.monotonic()
        if ss.output_active and self._last_bytes is not None and ss.output_bytes >= self._last_bytes and now > self._last_t:
            d["bitrate_kbps"] = (ss.output_bytes - self._last_bytes) * 8 / 1000 / (now - self._last_t)
        self._last_bytes, self._last_t = (ss.output_bytes, now) if ss.output_active else (None, None)
        if ss.output_active:
            try:
                svc = r.get_stream_service_settings()           # key is deliberately never read out
                s = svc.stream_service_settings or {}
                d["stream_service"] = s.get("service") or svc.stream_service_type
                d["stream_server"] = s.get("server", "")
            except Exception:
                pass
        try:
            d["replay_active"] = r.get_replay_buffer_status().output_active
        except Exception:
            d["replay_available"] = False                         # replay buffer not available/enabled in OBS
        sl = r.get_scene_list()
        d["scenes"] = [s["sceneName"] for s in reversed(sl.scenes)]
        d["scene"] = sl.current_program_scene_name
        try:     # sources (scene items) of the current scene, top-most first
            its = r.get_scene_item_list(d["scene"]).scene_items
            d["items"] = [dict(id=i["sceneItemId"], name=i["sourceName"], enabled=i["sceneItemEnabled"],
                               locked=i.get("sceneItemLocked", False), group=bool(i.get("isGroup"))) for i in reversed(its)]
        except Exception:
            pass
        try:
            d["vcam"] = r.get_virtual_cam_status().output_active
        except Exception:
            d["vcam"] = None                                      # virtual camera not available in this OBS
        try:
            vs = r.get_video_settings()
            d["base_res"], d["out_res"], d["fps"] = (vs.base_width, vs.base_height), (vs.output_width, vs.output_height), \
                round(vs.fps_numerator / max(vs.fps_denominator, 1), 2)
        except Exception:
            pass
        try:
            st = r.get_stats()
            d["obs_cpu"] = round(st.cpu_usage, 1)
        except Exception:
            pass
        try:
            special = r.get_special_inputs()
        except Exception:
            special = None
        for i in r.get_input_list().inputs:
            kind = i.get("inputKind", "")
            if not any(h in kind for h in AUDIO_KIND_HINTS):
                continue
            n = i["inputName"]
            try:
                muted = r.get_input_mute(n).input_muted
                db = r.get_input_volume(n).input_volume_db
            except Exception:
                continue
            d["inputs"].append(dict(name=n, kind=kind, muted=muted, db=db))
        names = [x["name"] for x in d["inputs"]]
        mic = getattr(special, "mic1", None) if special else None
        desk = getattr(special, "desktop1", None) if special else None
        d["mic"] = mic if mic in names else next((x["name"] for x in d["inputs"] if "input" in x["kind"]), None)
        d["desktop"] = desk if desk in names else next((x["name"] for x in d["inputs"] if "output" in x["kind"]), None)
        return d

    # ---- commands ----------------------------------------------------------
    def start_record(self): self.req.start_record()
    def stop_record(self): return self.req.stop_record().output_path
    def toggle_pause(self): self.req.toggle_record_pause()
    def start_stream(self): self.req.start_stream()
    def stop_stream(self): self.req.stop_stream()
    def start_replay(self): self.req.start_replay_buffer()
    def stop_replay(self): self.req.stop_replay_buffer()
    def save_replay(self): self.req.save_replay_buffer()
    def set_scene(self, name): self.req.set_current_program_scene(name)
    def set_item_enabled(self, scene, item_id, enabled): self.req.set_scene_item_enabled(scene, item_id, enabled)
    def set_item_locked(self, scene, item_id, locked): self.req.set_scene_item_locked(scene, item_id, locked)
    def start_vcam(self): self.req.start_virtual_cam()
    def stop_vcam(self): self.req.stop_virtual_cam()
    def set_mute(self, name, muted): self.req.set_input_mute(name, muted)
    def set_volume_db(self, name, db): self.req.set_input_volume(name, vol_db=db)

    def set_replay_seconds(self, sec: int):
        """Writes the profile parameter used by Simple output mode. Takes effect after the buffer restarts."""
        self.req.set_profile_parameter("SimpleOutput", "RecRBTime", str(int(sec)))

    def screenshot(self, scene, path, fmt, quality):
        """Screenshot of the OBS *scene output* (not the desktop/game directly)."""
        vs = self.req.get_video_settings()
        r = self.req.get_source_screenshot(scene, fmt, vs.output_width, vs.output_height, int(quality))
        b64 = r.image_data.split(",", 1)[1]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(base64.b64decode(b64))

    def preview_png(self, scene, width) -> bytes:
        vs = self.req.get_video_settings()
        h = int(width * vs.base_height / max(vs.base_width, 1))
        r = self.req.get_source_screenshot(scene, "jpg", width, h, 60)
        return base64.b64decode(r.image_data.split(",", 1)[1])


class _Events:
    """obs-websocket event handlers (called on the client's thread). Names map to OBS events."""
    def __init__(self, emit):
        self._emit = emit; self._last_meter = 0.0
        self.meter_events = 0; self.last_error = ""

    def callbacks(self):
        """Every on_<event> method wrapped so an exception can never kill obsws-python's event thread."""
        def wrap(name, fn):
            def handler(d):
                try:
                    fn(d)
                except Exception as e:
                    self.last_error = f"{name}: {type(e).__name__}: {e}"
            handler.__name__ = name
            return handler
        return [wrap(n, getattr(self, n)) for n in dir(self) if n.startswith("on_")]

    def on_input_volume_meters(self, d):
        self.meter_events += 1
        now = time.monotonic()
        if now - self._last_meter < 0.05:       # OBS sends ~50/s; forward at most 20/s (the UI interpolates between them)
            return
        self._last_meter = now
        self._emit("meters", dict(levels={i["inputName"]: peak_from_levels(i.get("inputLevelsMul")) for i in d.inputs}))
    def on_record_state_changed(self, d): self._emit("record", dict(active=d.output_active, state=d.output_state, path=getattr(d, "output_path", None)))
    def on_stream_state_changed(self, d): self._emit("stream", dict(active=d.output_active, state=d.output_state))
    def on_replay_buffer_state_changed(self, d): self._emit("replay_state", dict(active=d.output_active))
    def on_replay_buffer_saved(self, d): self._emit("replay_saved", dict(path=d.saved_replay_path))
    def on_current_program_scene_changed(self, d): self._emit("scene", dict(name=d.scene_name))
    def on_scene_list_changed(self, d): self._emit("scenes", {})
    def on_input_mute_state_changed(self, d): self._emit("mute", dict(name=d.input_name, muted=d.input_muted))
    def on_input_volume_changed(self, d): self._emit("volume", {})
    def on_input_created(self, d): self._emit("inputs", {})
    def on_input_removed(self, d): self._emit("inputs", {})
    def on_scene_item_enable_state_changed(self, d): self._emit("items", {})
    def on_scene_item_lock_state_changed(self, d): self._emit("items", {})
    def on_scene_item_created(self, d): self._emit("items", {})
    def on_scene_item_removed(self, d): self._emit("items", {})
    def on_scene_item_list_reindexed(self, d): self._emit("items", {})
    def on_virtual_cam_state_changed(self, d): self._emit("vcam", dict(active=d.output_active))
    def on_exit_started(self, d): self._emit("exit", {})


class DemoBackend:
    """Self-contained simulation so every control can be exercised without OBS.
    No audio levels and no video are fabricated; stats it cannot know are None ('Unavailable')."""
    name = "demo"

    def __init__(self, emit, record_dir: Path):
        self.emit, self.dir = emit, record_dir
        self.s = _empty_snapshot()
        self.s.update(version="Demo mode (no OBS)", scenes=["Gameplay", "Just Chatting", "BRB"], scene="Gameplay",
                      mic="Mic/Aux", desktop="Desktop Audio", base_res=(1920, 1080), out_res=(1920, 1080), fps=60.0,
                      inputs=[dict(name="Desktop Audio", kind="demo_output", muted=False, db=0.0),
                              dict(name="Mic/Aux", kind="demo_input", muted=False, db=-6.0)])
        self.s["vcam"] = False
        self.items = {"Gameplay": [dict(id=1, name="Alerts", enabled=True, locked=False, group=False),
                                   dict(id=2, name="Webcam", enabled=True, locked=False, group=False),
                                   dict(id=3, name="Game Capture", enabled=True, locked=True, group=False)],
                      "Just Chatting": [dict(id=1, name="Chat", enabled=True, locked=False, group=False),
                                        dict(id=2, name="Webcam", enabled=True, locked=False, group=False)],
                      "BRB": [dict(id=1, name="BRB Image", enabled=True, locked=False, group=False)]}
        self._t0 = {}
        self._lock = threading.Lock()

    def connect(self): pass
    def disconnect(self): pass
    def ping(self): pass

    def snapshot(self):
        with self._lock:
            d = dict(self.s)
            now = time.monotonic()
            if self._t0.get("rec"):
                d["rec_dur"] = now - self._t0["rec"]
                d["rec_bytes"] = int(d["rec_dur"] * 650_000)       # nominal 5.2 Mbps, labelled simulated by Demo mode
            if self._t0.get("stream"):
                d["stream_dur"] = now - self._t0["stream"]
                d["bitrate_kbps"], d["dropped_pct"] = 6000.0, 0.0
            d["inputs"] = [dict(i) for i in self.s["inputs"]]
            d["items"] = [dict(i) for i in self.items.get(self.s["scene"], [])]
            return d

    def start_record(self):
        self._t0["rec"] = time.monotonic(); self.s.update(recording=True, paused=False)
        self.emit("record", dict(active=True, state="OBS_WEBSOCKET_OUTPUT_STARTED", path=None))

    def stop_record(self):
        self.s["recording"] = False; self._t0.pop("rec", None)
        p = str(self.dir / time.strftime("Demo_%Y-%m-%d_%H-%M-%S.txt"))
        self.dir.mkdir(parents=True, exist_ok=True)
        Path(p).write_text("Demo mode placeholder - no video was recorded.\n")
        self.emit("record", dict(active=False, state="OBS_WEBSOCKET_OUTPUT_STOPPED", path=p))
        return p

    def toggle_pause(self): self.s["paused"] = not self.s["paused"]; self.emit("record", dict(active=True, state="paused", path=None))
    def start_stream(self): self._t0["stream"] = time.monotonic(); self.s.update(streaming=True, stream_service="Demo", stream_server="demo://localhost"); self.emit("stream", dict(active=True, state="started"))
    def stop_stream(self): self.s["streaming"] = False; self._t0.pop("stream", None); self.emit("stream", dict(active=False, state="stopped"))
    def start_replay(self): self.s["replay_active"] = True; self.emit("replay_state", dict(active=True))
    def stop_replay(self): self.s["replay_active"] = False; self.emit("replay_state", dict(active=False))

    def save_replay(self):
        if not self.s["replay_active"]:
            raise BackendError("Replay buffer is not active.")
        p = self.dir / "Replays" / time.strftime("Replay_%Y-%m-%d_%H-%M-%S.txt")
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text("Demo replay placeholder.\n")
        self.emit("replay_saved", dict(path=str(p)))

    def set_scene(self, name): self.s["scene"] = name; self.emit("scene", dict(name=name))

    def _item(self, scene, item_id):
        return next(i for i in self.items.get(scene, []) if i["id"] == item_id)

    def set_item_enabled(self, scene, item_id, enabled): self._item(scene, item_id)["enabled"] = enabled; self.emit("items", {})
    def set_item_locked(self, scene, item_id, locked): self._item(scene, item_id)["locked"] = locked; self.emit("items", {})
    def start_vcam(self): self.s["vcam"] = True; self.emit("vcam", dict(active=True))
    def stop_vcam(self): self.s["vcam"] = False; self.emit("vcam", dict(active=False))

    def set_mute(self, name, muted):
        for i in self.s["inputs"]:
            if i["name"] == name: i["muted"] = muted
        self.emit("mute", dict(name=name, muted=muted))

    def set_volume_db(self, name, db):
        for i in self.s["inputs"]:
            if i["name"] == name: i["db"] = db

    def set_replay_seconds(self, sec): pass

    def screenshot(self, scene, path, fmt, quality):
        import cv2, numpy as np
        img = np.full((360, 640, 3), 24, np.uint8)
        cv2.putText(img, f"DEMO - scene: {scene}", (30, 190), cv2.FONT_HERSHEY_SIMPLEX, 1, (200, 200, 200), 2)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        ok, buf = cv2.imencode("." + ("jpg" if fmt in ("jpg", "jpeg") else "png"), img)
        Path(path).write_bytes(buf.tobytes())

    def preview_png(self, scene, width) -> bytes:
        import cv2, numpy as np
        img = np.full((int(width * 9 / 16), width, 3), 30, np.uint8)
        cv2.putText(img, "DEMO MODE - NOT LIVE", (10, img.shape[0] // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)
        return cv2.imencode(".png", img)[1].tobytes()
