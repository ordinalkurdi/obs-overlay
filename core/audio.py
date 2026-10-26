"""Qt-free audio helpers: level conversion, activity detection and mic/desktop role resolution."""
from __future__ import annotations
import math

ACTIVE_DB = -50.0          # a source counts as "active" above this peak level
FLOOR_DB = -60.0


def mul_to_db(mul: float) -> float:
    return FLOOR_DB if mul <= 0 else max(FLOOR_DB, 20.0 * math.log10(mul))


def level_percent(mul: float) -> int:
    """0..100 bar value for a linear OBS peak value."""
    return int(round((mul_to_db(mul) - FLOOR_DB) / -FLOOR_DB * 100))


def is_active(mul: float | None) -> bool:
    return mul is not None and mul_to_db(mul) > ACTIVE_DB


def peak_from_levels(levels) -> float:
    """OBS InputVolumeMeters: inputLevelsMul = [[magnitude, peak, inputPeak], ...] per channel -> max peak."""
    best = 0.0
    for ch in levels or []:
        try:
            best = max(best, float(ch[1] if len(ch) > 1 else ch[0]))
        except (TypeError, ValueError, IndexError):
            continue
    return best


def apply_roles(snap: dict, mic_override: str = "", desktop_override: str = "") -> dict:
    """Applies user-chosen microphone/desktop sources on top of the auto-detected ones.
    An override that no longer exists in OBS is ignored (falls back to auto). One source is never both roles."""
    names = {i["name"] for i in snap.get("inputs", [])}
    mic_ok, desk_ok = mic_override in names, desktop_override in names
    if mic_ok:
        snap["mic"] = mic_override
    if desk_ok:
        snap["desktop"] = desktop_override
    if snap.get("mic") and snap.get("mic") == snap.get("desktop"):
        if mic_ok and not desk_ok:
            snap["desktop"] = None
        else:
            snap["mic"] = None
    return snap


class Ballistics:
    """Meter ballistics (Qt-free): fast attack, smooth release, peak-hold marker that falls slowly.
    step(dt) advances the animation and returns True while anything is still moving."""
    ATTACK, RELEASE, HOLD, PEAK_FALL = 40.0, 5.0, 0.6, 30.0     # rates per second / seconds / percent per second

    def __init__(self):
        self.value = self.peak = self.target = 0.0
        self._hold = 0.0

    def step(self, dt: float) -> bool:
        k = self.ATTACK if self.target > self.value else self.RELEASE
        self.value += (self.target - self.value) * min(1.0, max(0.0, dt) * k)
        if self.target <= 0.0 and self.value < 0.4:
            self.value = 0.0
        if self.value >= self.peak:
            self.peak, self._hold = self.value, self.HOLD
        elif self._hold > 0:
            self._hold -= dt
        else:
            self.peak = max(self.value, self.peak - dt * self.PEAK_FALL)
        return self.value > 0.2 or self.peak > 0.2 or abs(self.target - self.value) > 0.2
