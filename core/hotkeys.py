"""Global hotkeys via pynput. Passive listeners only: keys are NOT swallowed, so game input is untouched.
Note: some games/anti-cheat or elevated windows may block global listeners; failures are reported, not hidden."""
from __future__ import annotations
from PySide6.QtCore import QObject, Signal

_MOD = {"ctrl": "<ctrl>", "alt": "<alt>", "shift": "<shift>", "meta": "<cmd>", "win": "<cmd>"}


def to_pynput(seq: str) -> str | None:
    """'Ctrl+Alt+M' -> '<ctrl>+<alt>+m'. Returns None for an empty/invalid sequence."""
    parts = [p.strip() for p in seq.split("+") if p.strip()]
    if not parts:
        return None
    out = []
    for p in parts:
        low = p.lower()
        if low in _MOD:
            out.append(_MOD[low])
        elif len(p) == 1:
            out.append(low)
        else:
            out.append(f"<{low}>")
    if all(o in _MOD.values() for o in out):
        return None                                  # modifiers only
    return "+".join(out)


def find_conflicts(bindings: dict[str, str]) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for action, seq in bindings.items():
        if seq:
            seen.setdefault(seq.lower(), []).append(action)
    return {k: v for k, v in seen.items() if len(v) > 1}


class HotkeyManager(QObject):
    triggered = Signal(str)

    def __init__(self):
        super().__init__()
        self._listener = None
        self.failed: dict[str, str] = {}

    def apply(self, bindings: dict[str, str]):
        self.stop()
        self.failed = {}
        mapping = {}
        for action, seq in bindings.items():
            key = to_pynput(seq) if seq else None
            if seq and not key:
                self.failed[action] = f"'{seq}' is not a valid shortcut"
                continue
            if key:
                mapping[key] = (lambda a=action: self.triggered.emit(a))
        if not mapping:
            return
        try:
            from pynput import keyboard
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.daemon = True
            self._listener.start()
        except Exception as e:
            for a in bindings:
                self.failed.setdefault(a, f"Global hotkeys unavailable: {type(e).__name__} "
                                          "(on macOS grant Accessibility/Input Monitoring; on Wayland use X11)")

    def stop(self):
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
