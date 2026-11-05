from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from backend.config import Thresholds

class State(str, Enum):
    BASELINE = "baseline"
    NOMINAL = "nominal"
    WARNING = "warning"
    INTERVENTION = "intervention"
    RECOVERY = "recovery"
    SIGNAL_LOST = "signal_lost"

@dataclass
class EngineEvent:
    op_id: str
    from_state: State
    to_state: State
    reason: str
    t: float

class EscalationEngine:
    def __init__(self, op_id: str, th: Thresholds):
        self.op_id = op_id
        self.th = th
        self.state = State.BASELINE
        self._entered = 0.0
        self._since: float | None = None    # sustain arming timestamp
        self._armed: str | None = None

    def _transition(self, to: State, reason: str, t: float) -> EngineEvent:
        ev = EngineEvent(self.op_id, self.state, to, reason, t)
        self.state = to
        self._entered = t
        self._disarm()
        return ev

    def _disarm(self):
        self._since = None
        self._armed = None

    def _sustained(self, cond: bool, name: str, sustain_s: float,
                   t: float) -> bool:
        if cond:
            if self._armed != name or self._since is None:
                self._armed, self._since = name, t
            return (t - self._since) >= sustain_s
        self._disarm()
        return False

    def update(self, score: int | None, t: float) -> EngineEvent | None:
        if self.state == State.BASELINE:
            if score is not None:
                return self._transition(State.NOMINAL, "baseline complete", t)
            return None
        if self.state == State.SIGNAL_LOST:
            if score is not None:                  # feed resumed -> auto RESET
                return self._transition(State.NOMINAL, "feed resumed", t)
            return None
        if score is None:                          # invalid DSP window: hold
            self._disarm()                         # state, reset arming clocks
            return None
        if self.state == State.NOMINAL:
            # single _sustained call per update: its disarm-on-false must not
            # be clobbered by a second call in the same tick
            if self._sustained(score >= self.th.warn_score, "warn",
                               self.th.warn_sustain_s, t):
                return self._transition(
                    State.WARNING, f"score>={self.th.warn_score} sustained", t)
            return None
        if self.state == State.WARNING:
            if score >= self.th.intervene_score:
                if self._sustained(True, "intv",
                                   self.th.intervene_sustain_s, t):
                    return self._transition(
                        State.INTERVENTION,
                        f"score>={self.th.intervene_score} sustained", t)
            elif score < self.th.release_score:
                if self._sustained(True, "release",
                                   self.th.release_sustain_s, t):
                    return self._transition(
                        State.NOMINAL,
                        f"score<{self.th.release_score} sustained", t)
            else:
                self._disarm()   # 55 <= score < 80: hold, reset clocks
            return None
        if self.state == State.INTERVENTION:
            if self._sustained(score <= self.th.recover_score, "rec",
                               self.th.recover_sustain_s, t):
                return self._transition(
                    State.RECOVERY, f"score<={self.th.recover_score} sustained",
                    t)
            return None
        if self.state == State.RECOVERY:
            if t - self._entered >= self.th.recovery_grace_s:
                nxt = State.WARNING if score >= self.th.warn_score \
                    else State.NOMINAL
                return self._transition(nxt, "recovery grace elapsed", t)
            return None
        return None   # unreachable: all states handled above

    def force(self, command: str, t: float) -> EngineEvent | None:
        if command == "TRIGGER_INTERVENTION":
            if self.state == State.INTERVENTION:
                return None
            return self._transition(State.INTERVENTION, "manual override", t)
        if command == "END_INTERVENTION":
            if self.state != State.INTERVENTION:
                return None
            return self._transition(State.RECOVERY, "manual end", t)
        if command == "RESET":
            return self._transition(State.NOMINAL, "manual reset", t)
        raise ValueError(f"unknown force command: {command}")

    def signal_lost(self, t: float) -> EngineEvent:
        return self._transition(State.SIGNAL_LOST, "no samples", t)
