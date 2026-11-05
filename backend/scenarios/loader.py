from __future__ import annotations
import pathlib, yaml

DEFAULT_TIMELINE = {
    "baseline": {"duration": 60.0, "stress": 0.12},
    "loop": [
        {"action": "hold", "value": 0.15, "duration": 40.0},
        {"action": "ramp", "to": 0.50, "over": 30.0},
        {"action": "hold", "value": 0.50, "duration": 10.0},
        {"action": "ramp", "to": 0.12, "over": 20.0},
    ],
}

class Timeline:
    def __init__(self, spec: dict):
        b = spec.get("baseline", DEFAULT_TIMELINE["baseline"])
        self._base_dur = float(b["duration"])
        self._base_stress = float(b["stress"])
        self._events = sorted(spec.get("events", []), key=lambda e: e["t"])
        self._loop = spec.get("loop", None)
        self._loop_cycle = sum(float(s.get("duration", s.get("over", 0)))
                               for s in (self._loop or []))

    def stress_at(self, t: float) -> float:
        if t < self._base_dur:
            return self._base_stress
        if self._events:
            return self._walk_events(t)      # events use absolute t (spec format)
        if self._loop:
            return self._value_loop((t - self._base_dur) % self._loop_cycle)
        return self._base_stress

    def _walk_events(self, t: float) -> float:
        val = self._base_stress
        for e in self._events:
            if t < e["t"]:
                break
            if e["action"] == "ramp":
                frac = min((t - e["t"]) / float(e["over"]), 1.0)
                val = val + (e["to"] - val) * frac
            elif e["action"] == "hold":
                val = float(e["value"])
        return val

    def _value_loop(self, elapsed: float) -> float:
        val = self._base_stress
        pos = 0.0
        for s in self._loop:
            seg_len = float(s.get("duration", s.get("over", 0.0)))
            if elapsed < pos + seg_len:
                local = elapsed - pos
                if s["action"] == "hold":
                    return float(s["value"])
                frac = min(local / float(s["over"]), 1.0)
                return val + (s["to"] - val) * frac
            pos += seg_len
            if s["action"] == "hold":
                val = float(s["value"])
            elif s["action"] == "ramp":
                val = float(s["to"])
        return val

class ScenarioSet:
    def __init__(self, timelines: dict[str, Timeline]):
        self._tls = timelines
        self._default = Timeline(DEFAULT_TIMELINE)

    def for_op(self, op_id: str) -> Timeline:
        return self._tls.get(op_id, self._default)

def load_scenario(path: str | None) -> ScenarioSet:
    if not path:
        return ScenarioSet({})
    raw = yaml.safe_load(pathlib.Path(path).read_text()) or {}
    return ScenarioSet({k: Timeline(v) for k, v in raw.items()})
