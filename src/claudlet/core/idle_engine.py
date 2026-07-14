"""Idle liveliness: an activity-based energy level and the pure behavior
selection that rides on it. No Qt/DBus imports — unit-tested by data, like
core/state_engine.py. Time (`now`, monotonic seconds) and randomness (`rng`)
are always injected so the logic is deterministic under test."""

HIGH, MID, LOW = "high", "mid", "low"

# level thresholds on energy in [0,1] (tune on hardware)
_HIGH_AT = 0.66
_LOW_AT = 0.33

# drain/recovery coefficients (energy units). Tuned so a long, busy session
# visibly tires the creature over tens of minutes, and a quiet rest revives it.
_EVENT_DRAIN = 0.004      # per hook event (session "filling up")
_ROAM_DRAIN = 0.0006      # per roam step/jump (moving around tires it)
_PASSIVE_DRAIN = 0.02     # per minute of wall time while not resting
_RECOVER = 0.05           # per minute of resting
_WAKE_REBOUND = 0.15      # startle bump when activity resumes


def _clamp(v):
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


class IdleEnergy:
    def __init__(self, energy=1.0):
        self.value = _clamp(energy)
        self._last = None      # last `now` seen by update() (for dt)

    def note_event(self, now):
        self.value = _clamp(self.value - _EVENT_DRAIN)

    def note_roam(self, now):
        self.value = _clamp(self.value - _ROAM_DRAIN)

    def update(self, now, resting):
        if self._last is None:
            self._last = now
            return
        dt_min = max(0.0, (now - self._last) / 60.0)
        self._last = now
        if resting:
            self.value = _clamp(self.value + _RECOVER * dt_min)
        else:
            self.value = _clamp(self.value - _PASSIVE_DRAIN * dt_min)

    def wake(self, now):
        self.value = _clamp(self.value + _WAKE_REBOUND)
        self._last = now

    def level(self):
        if self.value >= _HIGH_AT:
            return HIGH
        if self.value <= _LOW_AT:
            return LOW
        return MID
