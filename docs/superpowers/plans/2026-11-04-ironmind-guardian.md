# IronMind Guardian Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the IronMind Guardian multi-user EEG neurofeedback command center end-to-end on the simulator, per the approved spec (`docs/superpowers/specs/2026-11-04-ironmind-guardian-design.md`).

**Architecture:** One asyncio Python process (FastAPI hub) consumes EEG from an LSL boundary — fed either by the in-process synthetic generator (`SimSource`, always running as standby) or a real Muse via `muselsl`. Per-operator DSP (notch → bandpass → artifact rejection → Welch → baseline z-score) feeds a per-operator escalation state machine whose transitions drive WebSocket fan-out to a plain-JS Command Center and an operator PWA running a p5.js bio-game.

**Tech Stack:** Python 3.12, FastAPI + uvicorn, numpy 2.x, scipy, pylsl 1.16.x, muselsl 2.3 (real headset only), PyYAML, pytest; frontends: vanilla JS ES-modules + p5.js 2D canvas + Tailwind (vendored locally, no CDN at runtime).

## Global Constraints

- Python 3.12, all deps pinned in `requirements.txt`, win_amd64 wheels required (demo laptop = Windows x64, Lenovo i7-8550U / 8GB / UHD 620).
- **No hardcoded thresholds** — every number from spec §6 lives in `backend/config.yaml`.
- Wire protocol: all frames carry `"proto_v": 1`; field names match blueprint v2 (`stress_score`, `alpha_power`, `beta_power`, `status`, `state_override`).
- Bands: α = 8–12 Hz, high-β = 18–30 Hz. Score mapping: `score = int(clip(20 + 25*z, 0, 100))`, z = baseline z-score of β/α ratio.
- Default roster: 5 operators, `operator_alpha_01` is the live slot (`--source sim|muse` overrides its source); other 4 sim.
- Bio-game: p5.js **2D canvas mode only**, ≤300 particles (UHD 620 budget). No audio anywhere.
- Frontend libs are **vendored** into `static/vendor/` by the bootstrap script (venue may be offline); pages must degrade gracefully to `static/shared/theme.css` if a vendor file is missing.
- Repo hygiene: minimal (no LICENSE, no CI), conventional commits (`feat:`, `test:`, `docs:`, `chore:`), `main` always demo-capable — merge only with full pytest suite green.
- **LSL note:** liblsl discovery uses multicast; run `selftest.sh` outside sandboxed environments if the e2e test times out on stream resolution (works normally on real Win/macOS/Linux).
- Scenario timelines are pure time-based (spec's `until: intervention` was deliberately decoupled — the engine owns intervention timing; scenarios only create the physiological conditions).

## File Structure (locked)

```
ironmind-guardian/
├── main.py                       # root entrypoint (argparse + asyncio orchestration)
├── requirements.txt
├── pytest.ini
├── .gitignore
├── backend/
│   ├── __init__.py
│   ├── config.py                 # dataclasses + load_config(path, overrides, source_flag)
│   ├── config.yaml               # ALL tunables + roster
│   ├── dsp.py                    # RingBuffer, preprocess, band powers, StressScorer, OperatorDSP
│   ├── engine.py                 # EscalationEngine state machine
│   ├── protocol.py               # frame builders + validate_incoming
│   ├── logging_db.py             # SQLite events/scores + CSV export
│   ├── hub.py                    # Hub: op state, engines, ws fan-out, overrides, ack contract
│   ├── app.py                    # build_app: FastAPI routes + static mounts
│   ├── router.py                 # FeedRouter: LSL readers, DSP ticks, signal-lost failover
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── generator.py          # EEGGenerator (alpha/beta/pink/blink/jaw)
│   │   ├── sim_source.py         # SimSource: LSL outlets per operator, standby always-on
│   │   └── muse_source.py        # MuseSource: muselsl subprocess + inlet resolution (P3)
│   └── scenarios/
│       ├── __init__.py
│       ├── loader.py             # Timeline, ScenarioSet, load_scenario
│       └── demo_pitch.yaml       # the stage script as data (P2)
├── static/
│   ├── shared/ws.js              # reconnecting WS client helper
│   ├── shared/theme.css          # fallback styles (no Tailwind dependency)
│   ├── vendor/                   # p5.min.js, tailwind.js — fetched by bootstrap (gitignored)
│   ├── command/index.html
│   ├── command/app.js
│   ├── operator/index.html
│   ├── operator/app.js
│   └── operator/game.js
├── scripts/
│   ├── bootstrap.ps1 / bootstrap.sh
│   ├── selftest.ps1  / selftest.sh
│   ├── doctor.ps1    / doctor.sh
│   └── packet_replay.py          # Sim #2: WS-level replay (P2)
├── tests/
│   ├── test_config.py  test_scenario.py  test_generator.py  test_dsp.py
│   ├── test_engine.py  test_protocol.py  test_db.py  test_hub_ws.py
│   ├── test_static.py  test_replay.py  test_muse_swap.py
│   ├── test_e2e.py               # slow: boots hub subprocess, full ladder over WS
│   ├── e2e_config.yaml  e2e_scenario.yaml
├── docs/
│   ├── RUNBOOK.md  MUSE_GUIDE.md  HANDOFF.md   (spec/plans already under docs/superpowers/)
├── README.md
└── data/                         # gitignored: ironmind.db, demo_capture.jsonl, hub.log
```

**Runtime data flow (one lap, for orientation):** `SimSource`/Muse → LSL → `FeedRouter` readers → `OperatorDSP` ring buffer → tick @2Hz → `StressScorer` → `EscalationEngine.update` → `Hub.on_dsp_result` → broadcast @10Hz to `/ws/command` + targeted @5Hz to `/ws/operator/{id}` → engine transitions push `warning_notice` / `state_override` → p5 game changes physiology → loop closes.

---

# PHASE P0 — Vertical Slice

### Task 1: Project skeleton, pinned deps, config loader

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `.gitignore`, `backend/__init__.py`, `backend/config.py`, `backend/config.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `load_config(path: str|None, overrides: dict|None, source_flag: str|None) -> AppConfig`; dataclasses `AppConfig(hub, dsp, thresholds, sources, db, scenario_dir, operators)`, `Operator(id, callsign, source, scenario, seed)`, `HubCfg`, `DSPCfg`, `Thresholds`, `SourcesCfg`, `DBCfg`. Every later task imports these exact names from `backend.config`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from backend.config import load_config

def test_defaults_load():
    cfg = load_config(None, None, None)
    assert cfg.hub.port == 8000
    assert cfg.dsp.fs == 256 and cfg.dsp.alpha_hz == (8, 12)
    assert cfg.thresholds.warn_score == 65 and cfg.thresholds.intervene_score == 80
    assert len(cfg.operators) == 5
    assert cfg.operators[0].id == "operator_alpha_01"
    assert cfg.operators[0].source == "muse"

def test_overrides_deep_merge():
    cfg = load_config(None, {"thresholds": {"warn_sustain_s": 1.0}, "dsp": {"baseline_s": 4.0}}, None)
    assert cfg.thresholds.warn_sustain_s == 1.0
    assert cfg.thresholds.intervene_sustain_s == 10.0   # untouched sibling survives
    assert cfg.dsp.baseline_s == 4.0

def test_source_flag_swaps_live_slot_only():
    cfg = load_config(None, None, "sim")
    assert cfg.operators[0].source == "sim"
    assert cfg.operators[1].source == "sim"  # squad is always sim
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.config`)

- [ ] **Step 3: Write implementation + pinned deps + skeleton files**

`requirements.txt` (exact pins; if `muselsl` proves numpy-2-incompatible during P3, fallback is documented there — do not preemptively downgrade):

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
numpy==2.1.3
scipy==1.14.1
pyyaml==6.0.2
pylsl==1.16.2
websockets>=13.0
httpx==0.27.2
pytest==8.3.4
muselsl==2.3.0
pandas==2.2.3
```

`pytest.ini`:

```ini
[pytest]
markers =
    slow: end-to-end smoke (boots hub subprocess, ~60s)
testpaths = tests
```

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
data/
static/vendor/
.pytest_cache/
```

`backend/__init__.py` and `backend/sources/__init__.py`, `backend/scenarios/__init__.py`: empty files.

`backend/config.yaml`:

```yaml
hub: {host: "0.0.0.0", port: 8000, broadcast_hz: 10.0, operator_push_hz: 5.0, record: false}
dsp:
  fs: 256
  window_s: 4.0
  tick_hz: 2.0
  notch_hz: [50, 60]
  bandpass_hz: [1, 40]
  artifact_uv: 150.0
  alpha_hz: [8, 12]
  hbeta_hz: [18, 30]
  baseline_s: 60.0
  score_offset: 20.0
  score_scale: 25.0
thresholds:
  warn_score: 65
  warn_sustain_s: 8.0
  intervene_score: 80
  intervene_sustain_s: 10.0
  recover_score: 45
  recover_sustain_s: 6.0
  release_score: 55
  release_sustain_s: 15.0
  recovery_grace_s: 15.0
  signal_lost_s: 5.0
  failover_delay_s: 2.0
sources: {sim_stream_prefix: "SimMuse", muse_address: null, standby_all: true}
db: {path: "data/ironmind.db"}
scenario_dir: "backend/scenarios"
operators:
  - {id: operator_alpha_01, callsign: "ALPHA-01", source: muse, scenario: demo_pitch.yaml, seed: 101}
  - {id: operator_bravo_02, callsign: "BRAVO-02", source: sim, scenario: demo_pitch.yaml, seed: 102}
  - {id: operator_charlie_03, callsign: "CHARLIE-03", source: sim, scenario: demo_pitch.yaml, seed: 103}
  - {id: operator_delta_04, callsign: "DELTA-04", source: sim, scenario: demo_pitch.yaml, seed: 104}
  - {id: operator_echo_05, callsign: "ECHO-05", source: sim, scenario: demo_pitch.yaml, seed: 105}
```

`backend/config.py`:

```python
from __future__ import annotations
import copy
from dataclasses import dataclass, field
import yaml

@dataclass
class Operator:
    id: str
    callsign: str
    source: str      # "sim" | "muse"
    scenario: str
    seed: int

@dataclass
class HubCfg:
    host: str = "0.0.0.0"
    port: int = 8000
    broadcast_hz: float = 10.0
    operator_push_hz: float = 5.0
    record: bool = False

@dataclass
class DSPCfg:
    fs: int = 256
    window_s: float = 4.0
    tick_hz: float = 2.0
    notch_hz: tuple = (50, 60)
    bandpass_hz: tuple = (1, 40)
    artifact_uv: float = 150.0
    alpha_hz: tuple = (8, 12)
    hbeta_hz: tuple = (18, 30)
    baseline_s: float = 60.0
    score_offset: float = 20.0
    score_scale: float = 25.0

@dataclass
class Thresholds:
    warn_score: int = 65
    warn_sustain_s: float = 8.0
    intervene_score: int = 80
    intervene_sustain_s: float = 10.0
    recover_score: int = 45
    recover_sustain_s: float = 6.0
    release_score: int = 55
    release_sustain_s: float = 15.0
    recovery_grace_s: float = 15.0
    signal_lost_s: float = 5.0
    failover_delay_s: float = 2.0

@dataclass
class SourcesCfg:
    sim_stream_prefix: str = "SimMuse"
    muse_address: str | None = None
    standby_all: bool = True

@dataclass
class DBCfg:
    path: str = "data/ironmind.db"

@dataclass
class AppConfig:
    hub: HubCfg
    dsp: DSPCfg
    thresholds: Thresholds
    sources: SourcesCfg
    db: DBCfg
    scenario_dir: str
    operators: list[Operator]

DEFAULTS = {
    "hub": {"host": "0.0.0.0", "port": 8000, "broadcast_hz": 10.0,
            "operator_push_hz": 5.0, "record": False},
    "dsp": {"fs": 256, "window_s": 4.0, "tick_hz": 2.0, "notch_hz": [50, 60],
            "bandpass_hz": [1, 40], "artifact_uv": 150.0, "alpha_hz": [8, 12],
            "hbeta_hz": [18, 30], "baseline_s": 60.0, "score_offset": 20.0,
            "score_scale": 25.0},
    "thresholds": {"warn_score": 65, "warn_sustain_s": 8.0, "intervene_score": 80,
                   "intervene_sustain_s": 10.0, "recover_score": 45,
                   "recover_sustain_s": 6.0, "release_score": 55,
                   "release_sustain_s": 15.0, "recovery_grace_s": 15.0,
                   "signal_lost_s": 5.0, "failover_delay_s": 2.0},
    "sources": {"sim_stream_prefix": "SimMuse", "muse_address": None,
                "standby_all": True},
    "db": {"path": "data/ironmind.db"},
    "scenario_dir": "backend/scenarios",
    "operators": [
        {"id": "operator_alpha_01", "callsign": "ALPHA-01", "source": "muse",
         "scenario": "demo_pitch.yaml", "seed": 101},
        {"id": "operator_bravo_02", "callsign": "BRAVO-02", "source": "sim",
         "scenario": "demo_pitch.yaml", "seed": 102},
        {"id": "operator_charlie_03", "callsign": "CHARLIE-03", "source": "sim",
         "scenario": "demo_pitch.yaml", "seed": 103},
        {"id": "operator_delta_04", "callsign": "DELTA-04", "source": "sim",
         "scenario": "demo_pitch.yaml", "seed": 104},
        {"id": "operator_echo_05", "callsign": "ECHO-05", "source": "sim",
         "scenario": "demo_pitch.yaml", "seed": 105},
    ],
}

def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out

def _build(d: dict) -> AppConfig:
    return AppConfig(
        hub=HubCfg(**d["hub"]),
        dsp=DSPCfg(**d["dsp"]),
        thresholds=Thresholds(**d["thresholds"]),
        sources=SourcesCfg(**d["sources"]),
        db=DBCfg(**d["db"]),
        scenario_dir=d["scenario_dir"],
        operators=[Operator(**o) for o in d["operators"]],
    )

def load_config(path: str | None, overrides: dict | None,
                source_flag: str | None) -> AppConfig:
    data = copy.deepcopy(DEFAULTS)
    if path:
        import pathlib
        data = _merge(data, yaml.safe_load(pathlib.Path(path).read_text()))
    data = _merge(data, overrides)
    if source_flag:
        data["operators"][0]["source"] = source_flag  # alpha_01 = live slot
    return _build(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt pytest.ini .gitignore backend/ tests/test_config.py
git commit -m "feat: project skeleton, pinned deps, config loader with deep-merge overrides"
```

---

### Task 2: Scenario loader (timelines → stress_at)

**Files:**
- Create: `backend/scenarios/loader.py`, `backend/scenarios/demo_pitch.yaml` (first draft)
- Test: `tests/test_scenario.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `load_scenario(path: str|None) -> ScenarioSet`; `ScenarioSet.for_op(op_id: str) -> Timeline`; `Timeline.stress_at(t: float) -> float` (0..1). `DEFAULT_TIMELINE` module constant used when an operator has no entry. Later tasks (SimSource, FeedRouter, e2e) call exactly these.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scenario.py
from backend.scenarios.loader import load_scenario, DEFAULT_TIMELINE

YAML_BODY = """
operator_alpha_01:
  baseline: {duration: 60, stress: 0.10}
  events:
    - {t: 70,  action: ramp, to: 0.85, over: 30}
    - {t: 100, action: hold, value: 0.85}
    - {t: 200, action: ramp, to: 0.12, over: 25}
operator_bravo_02:
  baseline: {duration: 30, stress: 0.12}
  loop:
    - {action: hold, value: 0.15, duration: 40}
    - {action: ramp, to: 0.55, over: 30}
    - {action: hold, value: 0.55, duration: 15}
    - {action: ramp, to: 0.12, over: 20}
"""

def write(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(YAML_BODY)
    return str(p)

def test_events_absolute_timeline(tmp_path):
    ts = load_scenario(write(tmp_path))
    tl = ts.for_op("operator_alpha_01")
    assert tl.stress_at(5) == 0.10            # baseline phase
    assert tl.stress_at(70) == 0.10           # ramp not started
    assert abs(tl.stress_at(85) - 0.475) < 1e-6   # halfway up the ramp
    assert tl.stress_at(100) == 0.85          # hold
    assert tl.stress_at(150) == 0.85          # hold persists until next event
    assert abs(tl.stress_at(225) - 0.12) < 1e-6   # down-ramp done

def test_loop_cycles(tmp_path):
    ts = load_scenario(write(tmp_path))
    tl = ts.for_op("operator_bravo_02")
    assert tl.stress_at(10) == 0.12           # baseline
    cycle = 40 + 30 + 15 + 20                 # 105s
    assert abs(tl.stress_at(30 + 20) - 0.15) < 1e-6        # hold segment
    assert abs(tl.stress_at(30 + 55) - 0.35) < 1e-6        # mid-ramp up
    assert abs(tl.stress_at(30 + cycle + 20) - 0.15) < 1e-6  # second cycle

def test_missing_op_gets_default():
    ts = load_scenario(write(tmp_path))
    tl = ts.for_op("operator_echo_05")
    assert tl.stress_at(61) == DEFAULT_TIMELINE["loop"][0]["value"]

def test_default_timeline_is_calm():
    assert DEFAULT_TIMELINE["baseline"]["stress"] <= 0.15
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scenario.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.scenarios.loader`)

- [ ] **Step 3: Write implementation + demo_pitch.yaml draft**

`backend/scenarios/loader.py`:

```python
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
```

`backend/scenarios/demo_pitch.yaml` (draft — choreographed final version lands in Task 14):

```yaml
operator_alpha_01:
  baseline: {duration: 45, stress: 0.10}
  events:
    - {t: 50,  action: ramp, to: 0.85, over: 25}
    - {t: 75,  action: hold, value: 0.85}
    - {t: 130, action: ramp, to: 0.12, over: 25}
operator_bravo_02:
  baseline: {duration: 45, stress: 0.12}
  loop:
    - {action: hold, value: 0.20, duration: 30}
    - {action: ramp, to: 0.60, over: 25}
    - {action: hold, value: 0.60, duration: 12}
    - {action: ramp, to: 0.15, over: 18}
operator_charlie_03:
  baseline: {duration: 45, stress: 0.10}
  loop:
    - {action: hold, value: 0.30, duration: 45}
    - {action: ramp, to: 0.45, over: 30}
operator_delta_04:
  baseline: {duration: 30, stress: 0.15}
  loop:
    - {action: ramp, to: 0.75, over: 20}
    - {action: hold, value: 0.75, duration: 10}
    - {action: ramp, to: 0.15, over: 25}
    - {action: hold, value: 0.15, duration: 30}
operator_echo_05:
  baseline: {duration: 45, stress: 0.10}
  loop:
    - {action: hold, value: 0.12, duration: 80}
    - {action: ramp, to: 0.30, over: 20}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scenario.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/scenarios/ tests/test_scenario.py
git commit -m "feat: scenario loader with absolute-event and looping timelines"
```


---

### Task 3: Synthetic EEG generator

**Files:**
- Create: `backend/sources/generator.py`
- Test: `tests/test_generator.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CHANNELS = ["TP9","AF7","AF8","TP10","AUX"]` (module constant), `FRONTAL_IDX = (1, 2)`, `EEGGenerator(fs: int, seed: int)` with `chunk(n: int, stress: np.ndarray) -> np.ndarray` shaped `(n, 5)` — stress is per-sample 0..1. Stateful (pink filter, artifact schedule); deterministic given seed. Task 4 wraps this in LSL outlets; Task 14 e2e depends on determinism.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_generator.py
import numpy as np
from scipy.signal import welch
from backend.sources.generator import EEGGenerator, CHANNELS

FS = 256

def band_power(sig, lo, hi):
    f, p = welch(sig, fs=FS, nperseg=256)
    m = (f >= lo) & (f <= hi)
    return float(np.trapezoid(p[m], f[m]))

def test_calm_chunk_alpha_dominant():
    g = EEGGenerator(FS, seed=7)
    stress = np.full(1024, 0.10)
    data = g.chunk(1024, stress)           # (1024, 5)
    assert data.shape == (1024, 5)
    tp9 = data[:, 0]
    a = band_power(tp9, 8, 12)
    b = band_power(tp9, 18, 30)
    assert a > 3 * b                        # calm: alpha clearly dominant

def test_stressed_chunk_beta_dominant():
    g = EEGGenerator(FS, seed=7)
    g.chunk(1024, np.full(1024, 0.10))      # settle filters at calm
    data = g.chunk(1024, np.full(1024, 0.90))
    tp9 = data[:, 0]
    assert band_power(tp9, 18, 30) > band_power(tp9, 8, 12)

def test_blink_hits_frontal_only_and_exceeds_artifact_threshold():
    g = EEGGenerator(FS, seed=7)
    data = g.chunk(256 * 12, np.full(256 * 12, 0.10))
    frontal_peak = np.abs(data[:, [1, 2]]).max()
    temporal_peak = np.abs(data[:, [0, 3]]).max()
    assert frontal_peak > 150.0             # crosses artifact_uv threshold
    assert temporal_peak < 80.0             # temporals stay clean-ish

def test_determinism_same_seed():
    d1 = EEGGenerator(FS, 11).chunk(256, np.full(256, 0.2))
    d2 = EEGGenerator(FS, 11).chunk(256, np.full(256, 0.2))
    assert np.array_equal(d1, d2)

def test_channel_count_matches_muse():
    assert CHANNELS == ["TP9", "AF7", "AF8", "TP10", "AUX"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generator.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.sources.generator`)

- [ ] **Step 3: Write implementation**

`backend/sources/generator.py`:

```python
from __future__ import annotations
import numpy as np

CHANNELS = ["TP9", "AF7", "AF8", "TP10", "AUX"]
FRONTAL_IDX = (1, 2)          # AF7, AF8 — where blinks live
ALPHA_HZ = 10.0
BETA_HZ = 22.0
PINK_SCALE_UV = 6.0           # broadband noise floor in microvolts
BLINK_UV = 350.0
BLINK_S = 0.30
JAW_UV = 90.0
JAW_S = 0.40

def amplitudes(s: float) -> tuple[float, float]:
    """Map scenario stress 0..1 -> (alpha_amp_uv, beta_amp_uv)."""
    alpha = 12.0 * (1.15 - 1.05 * s)
    beta = 6.0 * (0.35 + 1.95 * s)
    return alpha, beta

class _Pink:
    """Paul Kellet pink-noise filter, stateful per channel."""
    __slots__ = ("b0", "b1", "b2")

    def __init__(self):
        self.b0 = self.b1 = self.b2 = 0.0

    def __call__(self, w: float) -> float:
        self.b0 = 0.99765 * self.b0 + w * 0.0990460
        self.b1 = 0.96300 * self.b1 + w * 0.2965164
        self.b2 = 0.57000 * self.b2 + w * 1.0526913
        return (self.b0 + self.b1 + self.b2 + w * 0.1848) * 0.20

class EEGGenerator:
    def __init__(self, fs: int, seed: int):
        self.fs = fs
        self.rng = np.random.default_rng(seed)
        self.pinks = [_Pink() for _ in CHANNELS]
        self.t = 0.0
        self.phase = self.rng.uniform(0, 2 * np.pi)
        self._next_blink = self.rng.uniform(3.0, 8.0)
        self._next_jaw = self.rng.uniform(18.0, 40.0)

    def chunk(self, n: int, stress: np.ndarray) -> np.ndarray:
        out = np.zeros((n, len(CHANNELS)))
        blink_on = self._next_blink <= self.t + n / self.fs
        jaw_on = self._next_jaw <= self.t + n / self.fs
        for i in range(n):
            tt = self.t + i / self.fs
            a, b = amplitudes(float(stress[i]))
            row = np.empty(len(CHANNELS))
            for c, pink in enumerate(self.pinks):
                w = self.rng.standard_normal()
                row[c] = (a * np.sin(2 * np.pi * ALPHA_HZ * tt + self.phase)
                          + b * np.sin(2 * np.pi * BETA_HZ * tt)
                          + PINK_SCALE_UV * pink(w))
            if blink_on and self._in_window(tt, self._next_blink, BLINK_S):
                frac = (tt - self._next_blink) / BLINK_S
                amp = BLINK_UV * np.sin(np.pi * frac) ** 2
                for c in FRONTAL_IDX:
                    row[c] += amp
            if jaw_on and self._in_window(tt, self._next_jaw, JAW_S):
                w = self.rng.standard_normal()
                row += JAW_UV * w + JAW_UV * np.sin(2 * np.pi * 45.0 * tt)
            out[i] = row
        self.t += n / self.fs
        if blink_on and self.t > self._next_blink + BLINK_S:
            self._next_blink = self.t + self.rng.uniform(3.0, 8.0)
        if jaw_on and self.t > self._next_jaw + JAW_S:
            self._next_jaw = self.t + self.rng.uniform(18.0, 40.0)
        return out

    @staticmethod
    def _in_window(t: float, start: float, dur: float) -> bool:
        return start <= t <= start + dur
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generator.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/sources/generator.py tests/test_generator.py
git commit -m "feat: deterministic synthetic EEG generator (alpha/beta/pink/blink/jaw)"
```

---

### Task 4: SimSource — LSL outlets per operator

**Files:**
- Create: `backend/sources/sim_source.py`
- Test: `tests/test_sim_source.py`

**Interfaces:**
- Consumes: `AppConfig`, `ScenarioSet.for_op`, `EEGGenerator`, `CHANNELS`.
- Produces: `SimSource(cfg: AppConfig, timelines: ScenarioSet)` with `async start()`, `async stop()`. Always streams **all** operators (including alpha_01 — it is the standby/failover feed, spec §6). Stream metadata: `name="EEG"`, `type="EEG"`, 5ch, 256 Hz float32, `source_id = f"{cfg.sources.sim_stream_prefix}-{op.id}"` (default prefix `SimMuse`). Task 9's FeedRouter resolves inlets by that prefix.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sim_source.py
import asyncio
import numpy as np
from backend.config import load_config
from backend.scenarios.loader import load_scenario
from backend.sources.sim_source import SimSource

def test_sim_streams_lsl_with_muse_metadata():
    async def body():
        cfg = load_config(None, None, "sim")
        tl = load_scenario(None)
        src = SimSource(cfg, tl)
        await src.start()
        from pylsl import resolve_byprop, StreamInlet
        infos = resolve_byprop("name", "EEG", timeout=5.0)
        assert infos, "no EEG stream resolved"
        inlet = StreamInlet(infos[0], max_buflen=4)
        inlet.open_stream(timeout=5.0)
        chunk, ts = inlet.pull_chunk(timeout=5.0)
        assert chunk and len(chunk[0]) == 5
        assert infos[0].nominal_srate() == 256
        assert infos[0].source_id().startswith("SimMuse-")
        await src.stop()
    asyncio.run(asyncio.wait_for(body(), timeout=30.0))

def test_all_five_outlets_running():
    async def body():
        cfg = load_config(None, None, "sim")
        src = SimSource(cfg, load_scenario(None))
        await src.start()
        assert len(src.outlets) == 5
        await src.stop()
    asyncio.run(asyncio.wait_for(body(), timeout=30.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sim_source.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.sources.sim_source`)

- [ ] **Step 3: Write implementation**

`backend/sources/sim_source.py`:

```python
from __future__ import annotations
import asyncio
import time
import numpy as np
from pylsl import StreamInfo, StreamOutlet, IRREGULAR_RATE
from backend.config import AppConfig
from backend.scenarios.loader import ScenarioSet
from backend.sources.generator import EEGGenerator, CHANNELS

CHUNK = 8  # samples per push: 8/256s = 31.25ms pacing

class SimSource:
    """Streams synthetic EEG for every operator over LSL (standby for all,
    live for sim-mode operators). Muse metadata indistinguishable to DSP."""

    def __init__(self, cfg: AppConfig, timelines: ScenarioSet):
        self.outlets: dict[str, StreamOutlet] = {}
        self._tasks: list[asyncio.Task] = []
        self._cfg = cfg
        self._timelines = timelines
        self._t0: float | None = None
        for op in cfg.operators:
            info = StreamInfo(
                name="EEG", type="EEG", channel_count=len(CHANNELS),
                nominal_srate=cfg.dsp.fs, channel_format="float32",
                source_id=f"{cfg.sources.sim_stream_prefix}-{op.id}",
            )
            desc = info.desc()
            chans = desc.append_child("channels")
            for label in CHANNELS:
                chans.append_child("channel").append_child_value("label", label)
            desc.append_child_value("manufacturer", "IronMind Sim")
            self.outlets[op.id] = StreamOutlet(info, chunk_size=CHUNK, max_buffered=256)

    async def start(self):
        self._t0 = time.monotonic()
        for op in self._cfg.operators:
            self._tasks.append(asyncio.create_task(self._run(op.id)))

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run(self, op_id: str):
        seed = next(o.seed for o in self._cfg.operators if o.id == op_id)
        gen = EEGGenerator(self._cfg.dsp.fs, seed)
        tl = self._timelines.for_op(op_id)
        outlet = self.outlets[op_id]
        dt = CHUNK / self._cfg.dsp.fs
        while True:
            t_now = time.monotonic() - self._t0
            stress = np.full(CHUNK, tl.stress_at(t_now))
            outlet.push_chunk(gen.chunk(CHUNK, stress))
            await asyncio.sleep(dt)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sim_source.py -v`
Expected: 2 PASS (if stream resolution times out in a sandbox, rerun unsandboxed — Global Constraints note)

- [ ] **Step 5: Commit**

```bash
git add backend/sources/sim_source.py tests/test_sim_source.py
git commit -m "feat: SimSource streams Muse-identical LSL EEG for all operators"
```


---

### Task 5: DSP — ring buffer, filters, artifact rejection, Welch, baseline scorer

**Files:**
- Create: `backend/dsp.py`
- Test: `tests/test_dsp.py`

**Interfaces:**
- Consumes: `DSPCfg`.
- Produces:
  - `RingBuffer(n_ch: int, capacity: int)` with `append(chunk: np.ndarray)`, `latest(k: int) -> np.ndarray`
  - `preprocess(data: np.ndarray, fs: int, notch_hz: tuple, band_hz: tuple) -> np.ndarray`
  - `channel_valid(data: np.ndarray, artifact_uv: float) -> np.ndarray[bool]`
  - `compute_band_powers(data, fs, alpha_hz, hbeta_hz, artifact_uv) -> tuple[float,float]|None` — median across valid channels; `None` if <2 valid channels
  - `DSPResult(t, alpha, hbeta, ratio, score, valid)` dataclass (score `None` during baseline)
  - `OperatorDSP(op_id: str, cfg: DSPCfg)` with `add_samples(chunk: np.ndarray)`, `tick(t: float) -> DSPResult|None`
  - `StressScorer(baseline_s, tick_hz, offset, scale)` with `update(ratio: float, t: float) -> int|None`, property `ready`, `last_score`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dsp.py
import numpy as np
from backend.dsp import (RingBuffer, preprocess, channel_valid,
                         compute_band_powers, StressScorer, OperatorDSP)
from backend.config import DSPCfg

FS = 256
N = FS * 4          # 4s window

def sine(freq, uv, n=N):
    t = np.arange(n) / FS
    return uv * np.sin(2 * np.pi * freq * t)

def test_ring_buffer_keeps_last_k():
    rb = RingBuffer(5, 512)
    rb.append(np.ones((300, 5)))
    rb.append(np.full((512, 5), 2.0))     # overflow wipes the ones entirely
    latest = rb.latest(512)
    assert latest.shape == (512, 5)
    assert latest[0, 0] == 2.0 and latest[-1, 0] == 2.0

def test_preprocess_removes_line_noise():
    data = (sine(10, 50) + sine(50, 200)).reshape(-1, 1) * np.ones((1, 5))
    cleaned = preprocess(data, FS, (50, 60), (1, 40))
    assert np.abs(cleaned).max() < 100    # 200uV 50Hz component gone

def test_alpha_sine_dominates_beta_band():
    data = (sine(10, 50) + sine(50, 200)).reshape(-1, 1) * np.ones((1, 5))
    x = preprocess(data, FS, (50, 60), (1, 40))
    a, b = compute_band_powers(x, FS, (8, 12), (18, 30), 150.0)
    assert a > 10 * b

def test_artifact_rejection_median_survives_two_corrupted_channels():
    clean = (sine(10, 50)).reshape(-1, 1) * np.ones((1, 5))
    clean = preprocess(clean, FS, (50, 60), (1, 40))
    corrupted = clean.copy()
    corrupted[:, 1] += sine(60, 400)      # blow out AF7
    corrupted[:, 2] += sine(45, 400)      # blow out AF8
    a_clean, b_clean = compute_band_powers(clean, FS, (8, 12), (18, 30), 150.0)
    a_corr, b_corr = compute_band_powers(corrupted, FS, (8, 12), (18, 30), 150.0)
    assert np.abs(a_corr - a_clean) / a_clean < 0.5   # median of TP9/TP10 holds

def test_fewer_than_two_valid_channels_returns_none():
    clean = (sine(10, 50)).reshape(-1, 1) * np.ones((1, 5))
    corrupted = clean.copy()
    for c in range(5):
        corrupted[:, c] += sine(60, 400)  # kill all channels
    x = preprocess(corrupted, FS, (50, 60), (1, 40))
    assert compute_band_powers(x, FS, (8, 12), (18, 30), 150.0) is None

def test_scorer_baseline_then_scores():
    sc = StressScorer(baseline_s=2.0, tick_hz=10.0, offset=20.0, scale=25.0)
    assert not sc.ready
    for i in range(20):
        assert sc.update(0.25, i / 10.0) is None
    assert sc.ready
    s_calm = sc.update(0.25, 2.1)
    assert 10 <= s_calm <= 25              # ~baseline level -> low score
    assert sc.update(0.30, 2.2) == 100     # way above baseline -> saturates
    assert sc.last_score == 100

def test_operator_dsp_tick_flow():
    cfg = DSPCfg(fs=FS, window_s=4.0, tick_hz=2.0, baseline_s=2.0)
    od = OperatorDSP("op1", cfg)
    assert od.tick(0.0) is None            # not enough data yet
    for i in range(FS * 5):                # 5s of calm-ish signal
        od.add_samples(sine(10, 40).reshape(-1, 1) * np.ones((1, 5)))
    r = od.tick(5.0)
    assert r is not None and r.valid
    assert r.score is None                 # still in baseline (need 4 ticks)
    for i in range(FS * 3):
        od.add_samples((sine(10, 40) + sine(22, 60)).reshape(-1, 1) * np.ones((1, 5)))
    r = None
    for i in range(6):                     # tick past baseline (>=4 ticks)
        r = od.tick(8.0 + i * 0.5)
    assert r is not None and r.score is not None and r.score > 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dsp.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.dsp` — note `from backend.dsp import`)

- [ ] **Step 3: Write implementation**

`backend/dsp.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.signal import butter, filtfilt, iirnotch, sosfiltfilt, welch
from backend.config import DSPCfg

@dataclass
class DSPResult:
    t: float
    alpha: float
    hbeta: float
    ratio: float
    score: int | None
    valid: bool

class RingBuffer:
    def __init__(self, n_ch: int, capacity: int):
        self.capacity = capacity
        self.buf = np.zeros((0, n_ch))

    def append(self, chunk: np.ndarray):
        self.buf = np.vstack((self.buf, chunk))[-self.capacity:]

    def latest(self, k: int) -> np.ndarray:
        return self.buf[-k:]

def preprocess(data: np.ndarray, fs: int, notch_hz: tuple,
               band_hz: tuple) -> np.ndarray:
    x = data.astype(float)
    nyq = fs / 2.0
    for f in notch_hz:
        b, a = iirnotch(f / nyq, 30.0)
        x = filtfilt(b, a, x, axis=0)
    sos = butter(4, [band_hz[0] / nyq, band_hz[1] / nyq],
                 btype="band", output="sos")
    return sosfiltfilt(sos, x, axis=0)

def channel_valid(data: np.ndarray, artifact_uv: float) -> np.ndarray:
    return np.abs(data).max(axis=0) < artifact_uv

def compute_band_powers(data: np.ndarray, fs: int, alpha_hz: tuple,
                        hbeta_hz: tuple,
                        artifact_uv: float) -> tuple[float, float] | None:
    valid = channel_valid(data, artifact_uv)
    if valid.sum() < 2:
        return None
    nper = min(256, data.shape[0])
    freqs, psd = welch(data[:, valid], fs=fs, nperseg=nper,
                       noverlap=nper // 2, axis=0)
    def band(lo, hi):
        m = (freqs >= lo) & (freqs <= hi)
        per_ch = np.trapezoid(psd[m, :], freqs[m], axis=0)
        return float(np.median(per_ch))
    return band(*alpha_hz), band(*hbeta_hz)

class StressScorer:
    """Score = offset + scale * z(ratio vs personal baseline), clipped 0..100."""

    def __init__(self, baseline_s: float, tick_hz: float,
                 offset: float = 20.0, scale: float = 25.0):
        self._need = max(int(baseline_s * tick_hz), 2)
        self._buf: list[float] = []
        self._mu = None
        self._sd = None
        self._offset = offset
        self._scale = scale
        self.last_score: int | None = None

    @property
    def ready(self) -> bool:
        return self._mu is not None

    def update(self, ratio: float, t: float) -> int | None:
        if not self.ready:
            self._buf.append(ratio)
            if len(self._buf) >= self._need:
                arr = np.array(self._buf)
                self._mu = float(arr.mean())
                self._sd = max(float(arr.std()), 1e-6)
            return None
        z = (ratio - self._mu) / self._sd
        self.last_score = int(np.clip(self._offset + self._scale * z, 0, 100))
        return self.last_score

class OperatorDSP:
    def __init__(self, op_id: str, cfg: DSPCfg):
        self.op_id = op_id
        self.cfg = cfg
        n_ch = 5
        self.ring = RingBuffer(n_ch, int(cfg.fs * cfg.window_s))
        self.scorer = StressScorer(cfg.baseline_s, cfg.tick_hz,
                                   cfg.score_offset, cfg.score_scale)

    def add_samples(self, chunk: np.ndarray):
        self.ring.append(chunk)

    def tick(self, t: float) -> DSPResult | None:
        need = int(self.cfg.fs * self.cfg.window_s)
        if self.ring.buf.shape[0] < self.cfg.fs * 2:
            return None
        data = self.ring.latest(min(need, self.ring.buf.shape[0]))
        x = preprocess(data, self.cfg.fs, self.cfg.notch_hz,
                       self.cfg.bandpass_hz)
        bp = compute_band_powers(x, self.cfg.fs, self.cfg.alpha_hz,
                                 self.cfg.hbeta_hz, self.cfg.artifact_uv)
        if bp is None:
            return DSPResult(t=t, alpha=0.0, hbeta=0.0, ratio=0.0,
                             score=self.scorer.last_score, valid=False)
        alpha, hbeta = bp
        ratio = hbeta / max(alpha, 1e-9)
        score = self.scorer.update(ratio, t)
        return DSPResult(t=t, alpha=alpha, hbeta=hbeta, ratio=ratio,
                         score=score, valid=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dsp.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/dsp.py tests/test_dsp.py
git commit -m "feat: DSP pipeline (ring buffer, filters, artifact rejection, Welch, baseline z-score)"
```

---

### Task 6: Escalation engine (ladder state machine)

**Files:**
- Create: `backend/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `Thresholds`.
- Produces: `State` (str enum: `BASELINE, NOMINAL, WARNING, INTERVENTION, RECOVERY, SIGNAL_LOST`), `EngineEvent(op_id, from_state, to_state, reason, t)`, `EscalationEngine(op_id: str, th: Thresholds)` with:
  - `update(score: int|None, t: float) -> EngineEvent|None`
  - `force(command: str, t: float) -> EngineEvent|None` — accepts `"TRIGGER_INTERVENTION"`, `"END_INTERVENTION"`, `"RESET"` (same strings as wire protocol)
  - `signal_lost(t: float) -> EngineEvent`
  - property `state`, `_entered` timestamp (Hub reads for telemetry)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine.py
from backend.engine import EscalationEngine, State
from backend.config import Thresholds

def th(**over):
    base = dict(warn_score=65, warn_sustain_s=8.0, intervene_score=80,
                intervene_sustain_s=10.0, recover_score=45, recover_sustain_s=6.0,
                release_score=55, release_sustain_s=15.0, recovery_grace_s=15.0,
                signal_lost_s=5.0, failover_delay_s=2.0)
    base.update(over)
    return Thresholds(**base)

def test_baseline_to_nominal_on_first_score():
    e = EscalationEngine("op", th())
    assert e.state == State.BASELINE
    assert e.update(20, 1.0) is not None      # BASELINE -> NOMINAL event

def test_nominal_to_warning_needs_sustained_score():
    e = EscalationEngine("op", th())
    e.update(20, 0.0)
    for t in range(0, 7):
        assert e.update(70, float(t)) is None  # 7s < 8s sustain
    ev = e.update(70, 8.0)
    assert ev.to_state == State.WARNING

def test_warning_does_not_flap_at_threshold_boundary():
    e = EscalationEngine("op", th())
    e.update(20, 0.0)
    for t in range(0, 20):                     # oscillate around 65, each <8s
        e.update(64.9 if t % 2 else 70, float(t))
    assert e.state == State.NOMINAL

def test_warning_to_intervention():
    e = EscalationEngine("op", th())
    e.update(20, 0.0)                          # BASELINE -> NOMINAL
    for t in range(1, 9):
        assert e.update(70, float(t)) is None  # arming warn-sustain (8s)
    assert e.update(70, 9.0).to_state == State.WARNING
    for t in range(10, 20):
        assert e.update(85, float(t)) is None  # arming intervene-sustain (10s)
    assert e.update(85, 20.0).to_state == State.INTERVENTION

def test_warning_releases_when_score_drops():
    e = EscalationEngine("op", th())
    e.update(20, 0.0)
    for t in range(1, 9):
        e.update(70, float(t))
    assert e.update(70, 9.0).to_state == State.WARNING
    for t in range(10, 25):                    # release arming (15s)
        assert e.update(50, float(t)) is None
    assert e.update(50, 25.0).to_state == State.NOMINAL

def test_intervention_to_recovery_then_nominal():
    e = EscalationEngine("op", th())
    e.update(20, 0.0)
    e.force("TRIGGER_INTERVENTION", 0.0)
    assert e.state == State.INTERVENTION
    for t in range(1, 7):
        assert e.update(40, float(t)) is None  # recovery arming (6s)
    assert e.update(40, 7.0).to_state == State.RECOVERY
    assert e.update(30, 21.0) is None          # 14s into 15s grace
    assert e.update(30, 22.0).to_state == State.NOMINAL  # grace elapsed

def test_manual_force_commands():
    e = EscalationEngine("op", th())
    e.update(20, 0.0)
    e.force("TRIGGER_INTERVENTION", 1.0)
    assert e.state == State.INTERVENTION
    e.force("END_INTERVENTION", 2.0)
    assert e.state == State.RECOVERY
    e.force("RESET", 3.0)
    assert e.state == State.NOMINAL

def test_signal_lost_and_auto_reset_on_resume():
    e = EscalationEngine("op", th())
    e.update(20, 0.0)
    e.signal_lost(10.0)
    assert e.state == State.SIGNAL_LOST
    e.update(None, 11.0)
    ev = e.update(25, 12.0)                    # feed resumed -> auto RESET
    assert ev.to_state == State.NOMINAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engine.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.engine`)

- [ ] **Step 3: Write implementation**

`backend/engine.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_engine.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/engine.py tests/test_engine.py
git commit -m "feat: escalation ladder engine with sustain hysteresis and manual force"
```

---

### Task 7: Protocol frames + SQLite logging

**Files:**
- Create: `backend/protocol.py`, `backend/logging_db.py`
- Test: `tests/test_protocol.py`, `tests/test_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `validate_incoming(msg: dict, context: str) -> bool` — True only for known types: `manual_override` (commands TRIGGER_INTERVENTION/END_INTERVENTION/RESET), `sim_mode` (bool enabled), `client_ready`, `game_state` (playing/recovered bools), `heartbeat`
  - Frame builders, all returning dicts with `proto_v: 1`: `telemetry_batch(ops: list[dict])`, `telemetry_update(op: dict)` (v2 field names), `state_override(user_id, command, target_score)`, `warning_notice(user_id, stress_score)`, `error_frame(detail)`
  - `LoggingDB(path: str)` with `log_event(ts, user_id, event, detail="")`, `log_score(ts, user_id, score, state)`, `export_csv(out_path: str)`, `close()`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_protocol.py
import pytest
from backend.protocol import (validate_incoming, telemetry_batch,
                              telemetry_update, state_override,
                              warning_notice, error_frame)

def test_known_types_pass():
    assert validate_incoming({"type": "manual_override",
                              "user_id": "op1",
                              "command": "TRIGGER_INTERVENTION"}, "cmd")
    assert validate_incoming({"type": "sim_mode", "enabled": True}, "cmd")
    assert validate_incoming({"type": "client_ready"}, "op")
    assert validate_incoming({"type": "game_state", "playing": True,
                              "recovered": False}, "op")
    assert validate_incoming({"type": "heartbeat"}, "op")

def test_unknown_and_bad_payloads_rejected():
    assert not validate_incoming({"type": "drop_table"}, "cmd")
    assert not validate_incoming({"type": "manual_override", "user_id": "op1",
                                  "command": "NUKE"}, "cmd")
    assert not validate_incoming({"type": "manual_override"}, "cmd")  # no user_id
    assert not validate_incoming({"type": "sim_mode"}, "cmd")         # no enabled
    assert not validate_incoming({}, "cmd")

def test_frame_builders_carry_proto_v_and_v2_names():
    f = telemetry_update({"user_id": "op1", "stress_score": 68,
                          "alpha_power": 0.31, "beta_power": 0.47,
                          "status": "warning", "state": "warning"})
    assert f["proto_v"] == 1 and f["type"] == "telemetry_update"
    assert f["stress_score"] == 68            # v2 wire names preserved
    batch = telemetry_batch([{"user_id": "op1"}])
    assert batch["type"] == "telemetry_batch" and batch["proto_v"] == 1
    ov = state_override("op1", "TRIGGER_INTERVENTION", 78)
    assert ov["command"] == "TRIGGER_INTERVENTION" and ov["target_score"] == 78
    wn = warning_notice("op1", 66)
    assert wn["type"] == "warning_notice" and wn["stress_score"] == 66
    assert error_frame("bad")["type"] == "error"
```

```python
# tests/test_db.py
from backend.logging_db import LoggingDB

def test_roundtrip_and_export(tmp_path):
    db = LoggingDB(str(tmp_path / "t.db"))
    db.log_event(1.0, "op1", "STATE_CHANGE", "nominal->warning")
    db.log_score(1.0, "op1", 68, "warning")
    db.log_score(2.0, "op1", 71, "warning")
    rows = db.events_between(0.0, 10.0)
    assert len(rows) == 1 and rows[0][2] == "STATE_CHANGE"
    scores = db.scores_between(0.0, 10.0, "op1")
    assert len(scores) == 2 and scores[1][2] == 71
    out = tmp_path / "out.csv"
    db.export_csv(str(out))
    assert "STATE_CHANGE" in out.read_text()
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_protocol.py tests/test_db.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write implementations**

`backend/protocol.py`:

```python
from __future__ import annotations

PROTO_V = 1

COMMANDS = {"TRIGGER_INTERVENTION", "END_INTERVENTION", "RESET"}

def validate_incoming(msg: dict, context: str) -> bool:
    t = msg.get("type")
    if t == "manual_override" and context == "command":
        return bool(msg.get("user_id")) and msg.get("command") in COMMANDS
    if t == "sim_mode" and context == "command":
        return isinstance(msg.get("enabled"), bool)
    if t == "client_ready" and context == "operator":
        return True
    if t == "game_state" and context == "operator":
        return isinstance(msg.get("playing"), bool) \
            and isinstance(msg.get("recovered"), bool)
    if t == "heartbeat":
        return True
    return False

def telemetry_batch(ops: list[dict]) -> dict:
    return {"type": "telemetry_batch", "proto_v": PROTO_V, "operators": ops}

def telemetry_update(op: dict) -> dict:
    return {"type": "telemetry_update", "proto_v": PROTO_V, **op}

def state_override(user_id: str, command: str, target_score) -> dict:
    return {"type": "state_override", "proto_v": PROTO_V, "user_id": user_id,
            "command": command, "target_score": target_score}

def warning_notice(user_id: str, stress_score) -> dict:
    return {"type": "warning_notice", "proto_v": PROTO_V, "user_id": user_id,
            "stress_score": stress_score}

def error_frame(detail: str) -> dict:
    return {"type": "error", "proto_v": PROTO_V, "detail": detail}
```

`backend/logging_db.py`:

```python
from __future__ import annotations
import csv, pathlib, sqlite3

class LoggingDB:
    def __init__(self, path: str):
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(p))
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                ts REAL, user_id TEXT, event TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS scores (
                ts REAL, user_id TEXT, score INTEGER, state TEXT);
            CREATE INDEX IF NOT EXISTS ix_scores_op ON scores(user_id, ts);
        """)
        self.conn.commit()

    def log_event(self, ts: float, user_id: str, event: str, detail: str = ""):
        self.conn.execute("INSERT INTO events VALUES (?,?,?,?)",
                          (ts, user_id, event, detail))
        self.conn.commit()

    def log_score(self, ts: float, user_id: str, score: int, state: str):
        self.conn.execute("INSERT INTO scores VALUES (?,?,?,?)",
                          (ts, user_id, score, state))
        self.conn.commit()

    def events_between(self, t0: float, t1: float) -> list:
        return self.conn.execute(
            "SELECT * FROM events WHERE ts BETWEEN ? AND ? ORDER BY ts",
            (t0, t1)).fetchall()

    def scores_between(self, t0: float, t1: float, user_id: str) -> list:
        return self.conn.execute(
            "SELECT ts, score, state FROM scores "
            "WHERE ts BETWEEN ? AND ? AND user_id=? ORDER BY ts",
            (t0, t1, user_id)).fetchall()

    def export_csv(self, out_path: str):
        p = pathlib.Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ts", "user_id", "event", "detail"])
            for row in self.conn.execute("SELECT * FROM events ORDER BY ts"):
                w.writerow(row)
            w.writerow([])
            w.writerow(["ts", "user_id", "score", "state"])
            for row in self.conn.execute("SELECT * FROM scores ORDER BY ts"):
                w.writerow(row)

    def close(self):
        self.conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_protocol.py tests/test_db.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/protocol.py backend/logging_db.py tests/test_protocol.py tests/test_db.py
git commit -m "feat: protocol frame builders/validation and SQLite event+score logging"
```


---

### Task 8: Hub, FastAPI app, feed router, main entrypoint — vertical slice

**Files:**
- Create: `backend/hub.py`, `backend/app.py`, `backend/router.py`, `main.py`, `static/shared/ws.js`, `static/shared/theme.css`, `static/command/index.html`, `static/command/app.js`, `static/operator/index.html`, `static/operator/app.js`
- Test: `tests/test_hub_ws.py`, `tests/test_static.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7 (exact names).
- Produces:
  - `Hub(cfg: AppConfig, db: LoggingDB)` — `on_dsp_result(op_id: str, r: DSPResult)`, `manual_override(op_id, command) -> EngineEvent|None`, `set_sim_mode(enabled: bool)`, `on_client_ready(op_id)`, `on_game_state(op_id, playing, recovered)`, `handle_command_ws(ws)`, `handle_operator_ws(ws, op_id)`, `start_loops()`, `stop_loops()`, `snapshot_batch()`, `health()`, `now() -> float`
  - `build_app(cfg: AppConfig, hub: Hub) -> FastAPI` — routes `/ws/command`, `/ws/operator/{op_id}`, `/api/operators`, `/health`, `/` redirect; mounts `/command`, `/operator`, `/static`
  - `FeedRouter(cfg: AppConfig, hub: Hub, timelines: ScenarioSet)` — `run()` (blocking coroutine), `stop()`; resolves per-operator LSL inlets (sim ops → `{prefix}-{op.id}`, muse ops → first EEG stream *not* prefixed), pulls chunks in `asyncio.to_thread`, ticks each `OperatorDSP` at `dsp.tick_hz` calling `hub.on_dsp_result`
  - `main.py` CLI: `python main.py [--source sim|muse] [--config PATH] [--scenario PATH]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_hub_ws.py
import pytest
from fastapi.testclient import TestClient
from backend.config import load_config
from backend.logging_db import LoggingDB
from backend.hub import Hub
from backend.app import build_app
from backend.dsp import DSPResult

def make_hub(tmp_path):
    cfg = load_config(None, {
        "hub": {"broadcast_hz": 2.0, "operator_push_hz": 2.0},
        "db": {"path": str(tmp_path / "t.db")},
        "operators": [
            {"id": "operator_alpha_01", "callsign": "ALPHA-01", "source": "sim",
             "scenario": "x.yaml", "seed": 1},
            {"id": "operator_bravo_02", "callsign": "BRAVO-02", "source": "sim",
             "scenario": "x.yaml", "seed": 2},
        ],
    }, None)
    db = LoggingDB(cfg.db.path)
    hub = Hub(cfg, db)
    app = build_app(cfg, hub)
    return cfg, hub, app

def test_health_and_operators(tmp_path):
    cfg, hub, app = make_hub(tmp_path)
    with TestClient(app) as client:   # 'with' triggers lifespan -> loops start
        r = client.get("/health")
        assert r.status_code == 200 and r.json()["status"] == "ok"
        ops = client.get("/api/operators").json()
    assert ops[0]["user_id"] == "operator_alpha_01"
    assert ops[0]["callsign"] == "ALPHA-01"

def recv_until(ws, typ, limit=40):
    for _ in range(limit):
        m = ws.receive_json()
        if m.get("type") == typ:
            return m
    raise AssertionError(f"never received {typ}")

def test_command_ws_error_frames_and_override_routing(tmp_path):
    cfg, hub, app = make_hub(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/command") as cmd, \
             client.websocket_connect("/ws/operator/operator_alpha_01") as ope:
            cmd.send_text("this is not json{{{")
            assert recv_until(cmd, "error")["detail"]
            cmd.send_json({"type": "drop_table"})
            assert recv_until(cmd, "error")
            cmd.send_json({"type": "manual_override",
                           "user_id": "operator_alpha_01",
                           "command": "TRIGGER_INTERVENTION"})
            ov = recv_until(ope, "state_override")
            assert ov["command"] == "TRIGGER_INTERVENTION"
            assert ov["user_id"] == "operator_alpha_01"
            # client_ready clears ack state; END arrives on operator socket
            ope.send_json({"type": "client_ready"})
            cmd.send_json({"type": "manual_override",
                           "user_id": "operator_alpha_01",
                           "command": "END_INTERVENTION"})
            assert recv_until(ope,
                              "state_override")["command"] == "END_INTERVENTION"

def test_unknown_operator_socket_rejected(tmp_path):
    cfg, hub, app = make_hub(tmp_path)
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/operator/who_dis"):
                pass

def test_dsp_results_drive_batch_and_engine(tmp_path):
    cfg, hub, app = make_hub(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/command") as cmd:
            hub.on_dsp_result("operator_alpha_01",
                              DSPResult(t=0.1, alpha=1.0, hbeta=0.2, ratio=0.2,
                                        score=None, valid=True))
            hub.on_dsp_result("operator_alpha_01",
                              DSPResult(t=0.6, alpha=1.0, hbeta=0.2, ratio=0.2,
                                        score=22, valid=True))
            batch = recv_until(cmd, "telemetry_batch")
            op = next(o for o in batch["operators"]
                      if o["user_id"] == "operator_alpha_01")
            assert op["stress_score"] == 22 and op["state"] == "nominal"
            assert len(op["spark"]) == 1
            cmd.send_json({"type": "sim_mode", "enabled": True})
            batch = recv_until(cmd, "telemetry_batch")
            assert batch["sim"] is True

def test_manual_force_unknown_operator_is_noop(tmp_path):
    cfg, hub, app = make_hub(tmp_path)
    assert hub.manual_override("ghost", "TRIGGER_INTERVENTION") is None
```

```python
# tests/test_static.py
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def test_command_page_exists_with_markers():
    html = (ROOT / "static/command/index.html").read_text()
    assert 'id="grid"' in html and "app.js" in html
    js = (ROOT / "static/command/app.js").read_text()
    assert "manual_override" in js and "sim_mode" in js

def test_operator_page_exists_with_markers():
    html = (ROOT / "static/operator/index.html").read_text()
    assert "app.js" in html and "game.js" in html
    js = (ROOT / "static/operator/app.js").read_text()
    assert "TRIGGER_INTERVENTION" in js and "client_ready" in js
    game = (ROOT / "static/operator/game.js").read_text()
    assert "createCanvas" in game and "END_INTERVENTION" in js

def test_shared_ws_helper_exists():
    ws = (ROOT / "static/shared/ws.js").read_text()
    assert "backoff" in ws and "onmessage" in ws
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hub_ws.py tests/test_static.py -v`
Expected: FAIL (`ModuleNotFoundError: backend.hub` / static files missing)

- [ ] **Step 3: Write hub implementation**

`backend/hub.py`:

```python
from __future__ import annotations
import asyncio, json, logging, time
from collections import deque
from fastapi import WebSocket, WebSocketDisconnect
from backend.config import AppConfig
from backend.engine import EngineEvent, EscalationEngine, State
from backend.logging_db import LoggingDB
from backend.protocol import (validate_incoming, telemetry_batch,
                              telemetry_update, state_override,
                              warning_notice, error_frame)

log = logging.getLogger("hub")

class OpState:
    def __init__(self, op):
        self.op_id = op.id
        self.callsign = op.callsign
        self.source = op.source
        self.score: int | None = None
        self.alpha = 0.0
        self.hbeta = 0.0
        self.valid = True
        self.state = State.BASELINE
        self.spark: deque[int] = deque(maxlen=120)
        self.amber = False
        self.ack_pending = False
        self.ack_retried = False
        self.ready_client = False

class Hub:
    def __init__(self, cfg: AppConfig, db: LoggingDB):
        self.cfg = cfg
        self.db = db
        self.ops = {op.id: OpState(op) for op in cfg.operators}
        self.engines = {op.id: EscalationEngine(op.id, cfg.thresholds)
                        for op in cfg.operators}
        self.cmd_sockets: set[WebSocket] = set()
        self.op_sockets: dict[str, WebSocket | None] = \
            {op.id: None for op in cfg.operators}
        self.sim_mode = False
        self.feed_swap_hook = None      # router registers (Task 9)
        self._t0 = time.monotonic()
        self._tasks: list[asyncio.Task] = []
        self._rec = None
        if cfg.hub.record:
            import pathlib
            p = pathlib.Path("data/demo_capture.jsonl")
            p.parent.mkdir(parents=True, exist_ok=True)
            self._rec = open(p, "a")

    def now(self) -> float:
        return time.monotonic() - self._t0

    # ---- DSP intake ------------------------------------------------------
    def on_dsp_result(self, op_id: str, r):
        st = self.ops[op_id]
        st.score, st.alpha, st.hbeta, st.valid = r.score, r.alpha, r.hbeta, r.valid
        if r.valid and r.score is not None:
            st.spark.append(r.score)
        ev = self.engines[op_id].update(r.score, r.t)
        if ev:
            self._on_engine_event(ev)

    def _on_engine_event(self, ev: EngineEvent):
        st = self.ops[ev.op_id]
        st.state = ev.to_state
        log.info("%s %s -> %s (%s)", ev.op_id, ev.from_state.value,
                 ev.to_state.value, ev.reason)
        self.db.log_event(self.now(), ev.op_id, "STATE_CHANGE",
                          f"{ev.from_state.value}->{ev.to_state.value} "
                          f"({ev.reason})")
        if ev.to_state == State.WARNING:
            self._push_op(ev.op_id, warning_notice(ev.op_id, st.score))
        elif ev.to_state == State.INTERVENTION:
            st.ack_pending, st.ack_retried = True, False
            self._push_op(ev.op_id, state_override(
                ev.op_id, "TRIGGER_INTERVENTION", st.score))
            self._tasks.append(asyncio.create_task(self._ack_watch(ev.op_id)))
        elif ev.to_state == State.RECOVERY:
            st.ack_pending = False
            self._push_op(ev.op_id, state_override(
                ev.op_id, "END_INTERVENTION", st.score))

    async def _ack_watch(self, op_id: str, delay: float = 5.0):
        await asyncio.sleep(delay)
        st = self.ops[op_id]
        if not st.ack_pending:
            return
        if not st.ack_retried:
            st.ack_retried = True
            self._push_op(op_id, state_override(
                op_id, "TRIGGER_INTERVENTION", st.score))
            self._tasks.append(asyncio.create_task(self._ack_watch(op_id)))
        else:
            st.ack_pending = False
            st.amber = True
            log.warning("%s intervention unacknowledged", op_id)

    # ---- client-driven actions -------------------------------------------
    def on_client_ready(self, op_id: str):
        st = self.ops[op_id]
        st.ack_pending = False
        st.amber = False
        st.ready_client = True
        self.db.log_event(self.now(), op_id, "GAME_READY", "")

    def on_game_state(self, op_id: str, playing: bool, recovered: bool):
        self.db.log_event(self.now(), op_id, "GAME_STATE",
                          f"playing={playing} recovered={recovered}")

    def manual_override(self, op_id: str, command: str) -> EngineEvent | None:
        if op_id not in self.engines:
            return None
        ev = self.engines[op_id].force(command, self.now())
        if ev:
            self._on_engine_event(ev)
        return ev

    def set_sim_mode(self, enabled: bool):
        self.sim_mode = enabled
        self.db.log_event(self.now(), "SYSTEM", "SIM_MODE", str(enabled))
        if self.feed_swap_hook:
            self.feed_swap_hook(enabled)

    # ---- snapshots ---------------------------------------------------------
    def op_snapshot(self, op_id: str) -> dict:
        st = self.ops[op_id]
        return {
            "user_id": op_id,
            "callsign": st.callsign,
            "stress_score": st.score,
            "alpha_power": round(st.alpha, 6),
            "beta_power": round(st.hbeta, 6),
            "status": st.state.value,
            "state": st.state.value,
            "valid": st.valid,
            "amber": st.amber,
            "source": st.source,
            "spark": list(st.spark),
        }

    def snapshot_batch(self) -> dict:
        batch = telemetry_batch([self.op_snapshot(k) for k in self.ops])
        batch["t"] = round(self.now(), 3)
        batch["sim"] = self.sim_mode
        return batch

    def health(self) -> dict:
        return {
            "status": "ok",
            "uptime_s": round(self.now(), 1),
            "operators": len(self.ops),
            "sim_mode": self.sim_mode,
            "op_states": {k: st.state.value for k, st in self.ops.items()},
        }

    # ---- loops ---------------------------------------------------------
    async def broadcast_loop(self):
        interval = 1.0 / self.cfg.hub.broadcast_hz
        last_db = 0.0
        while True:
            batch = self.snapshot_batch()
            if self._rec:
                self._rec.write(json.dumps(batch) + "\n")
                self._rec.flush()
            for ws in list(self.cmd_sockets):
                await self._safe_send(ws, batch)
            if self.now() - last_db >= 1.0:
                last_db = self.now()
                for op_id, st in self.ops.items():
                    if st.score is not None:
                        self.db.log_score(self.now(), op_id, st.score,
                                          st.state.value)
            await asyncio.sleep(interval)

    async def operator_push_loop(self):
        interval = 1.0 / self.cfg.hub.operator_push_hz
        while True:
            for op_id, ws in list(self.op_sockets.items()):
                if ws is not None:
                    await self._safe_send(
                        ws, telemetry_update(self.op_snapshot(op_id)))
            await asyncio.sleep(interval)

    def start_loops(self):
        self._tasks.append(asyncio.create_task(self.broadcast_loop()))
        self._tasks.append(asyncio.create_task(self.operator_push_loop()))

    def stop_loops(self):
        for t in self._tasks:
            t.cancel()
        if self._rec:
            self._rec.close()

    # ---- websockets ------------------------------------------------------
    async def handle_command_ws(self, ws: WebSocket):
        await ws.accept()
        self.cmd_sockets.add(ws)
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await self._safe_send(ws, error_frame("malformed JSON"))
                    continue
                if not validate_incoming(msg, "command"):
                    await self._safe_send(ws, error_frame(
                        f"rejected: {msg.get('type')}"))
                    continue
                if msg["type"] == "manual_override":
                    self.manual_override(msg["user_id"], msg["command"])
                elif msg["type"] == "sim_mode":
                    self.set_sim_mode(msg["enabled"])
        except WebSocketDisconnect:
            pass
        finally:
            self.cmd_sockets.discard(ws)

    async def handle_operator_ws(self, ws: WebSocket, op_id: str):
        if op_id not in self.ops:
            await ws.close(code=1008)
            return
        await ws.accept()
        self.op_sockets[op_id] = ws
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await self._safe_send(ws, error_frame("malformed JSON"))
                    continue
                if not validate_incoming(msg, "operator"):
                    await self._safe_send(ws, error_frame(
                        f"rejected: {msg.get('type')}"))
                    continue
                if msg["type"] == "client_ready":
                    self.on_client_ready(op_id)
                elif msg["type"] == "game_state":
                    self.on_game_state(op_id, msg["playing"], msg["recovered"])
        except WebSocketDisconnect:
            pass
        finally:
            if self.op_sockets.get(op_id) is ws:
                self.op_sockets[op_id] = None

    # ---- send helpers ------------------------------------------------------
    def _push_op(self, op_id: str, frame: dict):
        ws = self.op_sockets.get(op_id)
        if ws is not None:
            asyncio.create_task(self._safe_send(ws, frame))

    async def _safe_send(self, ws: WebSocket, frame: dict):
        try:
            await ws.send_json(frame)
        except Exception:
            self.cmd_sockets.discard(ws)
            for k, v in self.op_sockets.items():
                if v is ws:
                    self.op_sockets[k] = None
```


`backend/app.py`:

```python
from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from backend.config import AppConfig
from backend.hub import Hub

ROOT = Path(__file__).resolve().parent.parent

def build_app(cfg: AppConfig, hub: Hub) -> FastAPI:
    app = FastAPI(title="IronMind Guardian")

    @app.websocket("/ws/command")
    async def command_ws(ws):
        await hub.handle_command_ws(ws)

    @app.websocket("/ws/operator/{op_id}")
    async def operator_ws(ws, op_id: str):
        await hub.handle_operator_ws(ws, op_id)

    @app.get("/api/operators")
    async def operators():
        return [{"user_id": k, "callsign": st.callsign, "source": st.source,
                 "state": st.state.value}
                for k, st in hub.ops.items()]

    @app.get("/health")
    async def health():
        return hub.health()

    @app.get("/")
    async def index():
        return RedirectResponse("/command/")

    app.mount("/command", StaticFiles(directory=ROOT / "static/command",
                                      html=True), name="command")
    app.mount("/operator", StaticFiles(directory=ROOT / "static/operator",
                                       html=True), name="operator")
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="assets")

    @app.on_event("startup")
    async def _startup():
        hub.start_loops()

    @app.on_event("shutdown")
    async def _shutdown():
        hub.stop_loops()

    return app
```

`backend/router.py`:

```python
from __future__ import annotations
import asyncio, logging
import numpy as np
from pylsl import StreamInlet, resolve_byprop
from backend.config import AppConfig
from backend.dsp import OperatorDSP
from backend.hub import Hub
from backend.scenarios.loader import ScenarioSet

log = logging.getLogger("router")

class FeedRouter:
    """Resolves one LSL inlet per operator, pulls chunks, ticks DSP."""

    def __init__(self, cfg: AppConfig, hub: Hub, timelines: ScenarioSet):
        self.cfg = cfg
        self.hub = hub
        self.timelines = timelines
        self.dsp = {op.id: OperatorDSP(op.id, cfg.dsp) for op in cfg.operators}
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def run(self):
        self._running = True
        for op in self.cfg.operators:
            prefix = self.cfg.sources.sim_stream_prefix
            if op.source == "muse":
                wanted = None   # first EEG stream NOT carrying the sim prefix
            else:
                wanted = f"{prefix}-{op.id}"
            self._tasks.append(asyncio.create_task(
                self._reader(op.id, wanted)))
            self._tasks.append(asyncio.create_task(
                self._ticker(op.id)))
        await asyncio.gather(*self._tasks)

    def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()

    def _match(self, info, wanted: str | None) -> bool:
        sid = info.source_id()
        if wanted is None:
            return not sid.startswith(self.cfg.sources.sim_stream_prefix)
        return sid == wanted

    async def _reader(self, op_id: str, wanted: str | None):
        inlet = None
        while self._running and inlet is None:
            try:
                infos = await asyncio.to_thread(resolve_byprop, "name", "EEG",
                                                2.0)
                for info in infos:
                    if self._match(info, wanted):
                        inlet = StreamInlet(info, max_buflen=8)
                        break
            except Exception as e:
                log.warning("%s inlet resolve failed: %s", op_id, e)
            if inlet is None:
                await asyncio.sleep(1.0)
        if inlet is None:
            return
        log.info("%s inlet connected: %s", op_id, inlet.info().source_id())
        while self._running:
            chunk, _ts = await asyncio.to_thread(inlet.pull_chunk, 0.25)
            if chunk:
                self.dsp[op_id].add_samples(np.array(chunk, dtype=float))

    async def _ticker(self, op_id: str):
        interval = 1.0 / self.cfg.dsp.tick_hz
        while self._running:
            r = self.dsp[op_id].tick(self.hub.now())
            if r is not None:
                self.hub.on_dsp_result(op_id, r)
            await asyncio.sleep(interval)
```

`main.py`:

```python
from __future__ import annotations
import argparse, asyncio, logging, pathlib
import uvicorn
from backend.app import build_app
from backend.config import load_config
from backend.hub import Hub
from backend.logging_db import LoggingDB
from backend.router import FeedRouter
from backend.scenarios.loader import load_scenario
from backend.sources.sim_source import SimSource

def parse_args():
    p = argparse.ArgumentParser(description="IronMind Guardian hub")
    p.add_argument("--source", choices=["sim", "muse"], default="muse",
                   help="driver for the live slot operator_alpha_01")
    p.add_argument("--config", default="backend/config.yaml")
    p.add_argument("--scenario", default=None,
                   help="scenario yaml override (else per-operator from config)")
    return p.parse_args()

async def orchestrate(args):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler("data/hub.log"),
                  logging.StreamHandler()])
    cfg = load_config(args.config, None, args.source)
    scenario_path = args.scenario or str(
        pathlib.Path(cfg.scenario_dir) / cfg.operators[0].scenario)
    timelines = load_scenario(scenario_path)
    db = LoggingDB(cfg.db.path)
    hub = Hub(cfg, db)
    app = build_app(cfg, hub)
    sim = SimSource(cfg, timelines)      # standby feeds: ALWAYS running
    await sim.start()
    router = FeedRouter(cfg, hub, timelines)
    router_task = asyncio.create_task(router.run())
    server = uvicorn.Server(uvicorn.Config(
        app, host=cfg.hub.host, port=cfg.hub.port, log_level="info"))
    try:
        await server.serve()
    finally:
        router.stop()
        await sim.stop()
        db.close()

def main():
    pathlib.Path("data").mkdir(exist_ok=True)
    asyncio.run(orchestrate(parse_args()))

if __name__ == "__main__":
    main()
```

Minimal frontends for the P0 exit gate (full versions land in Tasks 11–12):

`static/shared/ws.js`:

```javascript
export function connectWS(url, { onMsg, onStatus } = {}) {
  let ws = null, backoff = 500, closed = false, hb = null;
  function connect() {
    ws = new WebSocket(url);
    ws.onopen = () => {
      backoff = 500;
      onStatus && onStatus("online");
      hb = setInterval(() => {
        if (ws.readyState === 1) ws.send(JSON.stringify({ type: "heartbeat" }));
      }, 5000);
    };
    ws.onmessage = (e) => {
      try { onMsg(JSON.parse(e.data)); } catch {}
    };
    ws.onclose = () => {
      clearInterval(hb);
      onStatus && onStatus("offline");
      if (closed) return;
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 8000);
    };
  }
  connect();
  return {
    send: (o) => { if (ws.readyState === 1) ws.send(JSON.stringify(o)); },
    close() { closed = true; ws.close(); },
  };
}
```

`static/shared/theme.css`:

```css
:root { --bg:#0b1220; --panel:#121a2e; --ink:#e6edf7; --dim:#8aa0c2; }
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--ink);
  font-family: ui-sans-serif, system-ui, sans-serif; margin: 0; }
.panel { background: var(--panel); border: 1px solid #223052;
  border-radius: 10px; padding: 12px; }
.dim { color: var(--dim); }
.grid { display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
.badge { padding: 2px 10px; border-radius: 999px; font-size: 12px; }
.badge.baseline { background:#334155; } .badge.nominal { background:#14532d; }
.badge.warning { background:#713f12; } .badge.intervention { background:#7f1d1d; }
.badge.recovery { background:#164e63; } .badge.signal_lost { background:#3f3f46; }
button { background:#1d4ed8; color:white; border:0; border-radius:6px;
  padding:6px 10px; cursor:pointer; }
button:hover { filter: brightness(1.15); }
.amber { outline: 2px solid #f59e0b; }
```

`static/command/index.html`:

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>IronMind Command</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="/static/vendor/tailwind.js" onerror="this.remove()"></script>
<link rel="stylesheet" href="/static/shared/theme.css">
</head><body>
<div class="panel" style="margin:12px">
  <h1 style="margin:0;font-size:18px">IronMind Guardian — Command Center</h1>
  <span id="conn" class="dim">connecting…</span>
  <span id="simbadge" class="badge warning" style="display:none">SIM</span>
</div>
<div id="grid" class="grid" style="margin:12px"></div>
<script type="module" src="app.js"></script>
</body></html>
```

`static/command/app.js`:

```javascript
import { connectWS } from "/static/shared/ws.js";

const grid = document.getElementById("grid");
const conn = document.getElementById("conn");
const simbadge = document.getElementById("simbadge");
const cards = {};

function card(op) {
  const d = document.createElement("div");
  d.className = "panel"; d.dataset.op = op.user_id;
  d.innerHTML = `<b>${op.callsign}</b> <span class="badge baseline" data-b>baseline</span>
    <div style="font-size:42px;font-weight:700" data-score>—</div>
    <canvas width="200" height="40" data-spark></canvas>
    <div class="dim" data-alpha>α — | β —</div>
    <button data-cmd="TRIGGER_INTERVENTION">Trigger</button>
    <button data-cmd="END_INTERVENTION">End</button>
    <button data-cmd="RESET">Reset</button>`;
  d.querySelectorAll("button").forEach(b =>
    b.onclick = () => sock.send({ type: "manual_override",
      user_id: op.user_id, command: b.dataset.cmd }));
  grid.appendChild(d);
  return d;
}

function drawSpark(canvas, points) {
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "#60a5fa"; ctx.beginPath();
  points.forEach((v, i) => {
    const x = i * canvas.width / 120, y = canvas.height - (v / 100) * canvas.height;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

fetch("/api/operators").then(r => r.json()).then(ops =>
  ops.forEach(op => { cards[op.user_id] = card(op); }));

const sock = connectWS(
  `ws://${location.host}/ws/command`,
  { onStatus: s => { conn.textContent = s; },
    onMsg: m => {
      if (m.type === "telemetry_batch") {
        simbadge.style.display = m.sim ? "inline-block" : "none";
        for (const op of m.operators) {
          const d = cards[op.user_id]; if (!d) continue;
          d.querySelector("[data-score]").textContent =
            op.stress_score ?? "CAL";
          const b = d.querySelector("[data-b]");
          b.textContent = op.state; b.className = `badge ${op.state}`;
          d.classList.toggle("amber", !!op.amber);
          d.querySelector("[data-alpha]").textContent =
            `α ${op.alpha_power.toPrecision(3)} | β ${op.beta_power.toPrecision(3)}`;
          drawSpark(d.querySelector("[data-spark]"), op.spark);
        }
      }
    } });

addEventListener("keydown", e => {
  if (e.key.toLowerCase() === "s") {
    sock.send({ type: "sim_mode", enabled: simbadge.style.display === "none" });
  }
});
```

`static/operator/index.html`:

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>IronMind Operator</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/static/shared/theme.css">
<style>
  #toast { position:fixed; top:0; left:0; right:0; background:#b45309;
    padding:16px; text-align:center; display:none; font-weight:700; }
  #game { display:none; }
</style></head><body>
<div class="panel" style="margin:12px">
  <h1 id="callsign" style="margin:0;font-size:20px">OPERATOR</h1>
  <p id="state" class="dim">connecting…</p>
  <p style="font-size:48px;font-weight:700" id="score">—</p>
  <p class="dim" id="hint">Wear the headset. Breathe. The system calibrates
    for 60 seconds.</p>
</div>
<div id="toast">Elevated stress detected — prepare for focus exercise</div>
<div id="game"><div id="gamehud" class="dim"
  style="position:fixed;top:8px;left:12px;z-index:10">Follow the orb.
  Breathe in as it grows, out as it shrinks.</div></div>
<script src="/static/vendor/p5.min.js" onerror="this.remove()"></script>
<script type="module" src="app.js"></script>
</body></html>
```

`static/operator/app.js`:

```javascript
import { connectWS } from "/static/shared/ws.js";
import { startGame, finishGame, setScore } from "./game.js";

const opId = new URLSearchParams(location.search).get("id")
  || "operator_alpha_01";
document.getElementById("callsign").textContent = opId.toUpperCase();
let gameRunning = false;

const sock = connectWS(`ws://${location.host}/ws/operator/${opId}`, {
  onMsg: m => {
    if (m.type === "telemetry_update") {
      document.getElementById("state").textContent = m.state;
      document.getElementById("score").textContent = m.stress_score ?? "CAL";
      setScore(m.stress_score);
    } else if (m.type === "warning_notice") {
      document.getElementById("toast").style.display = "block";
    } else if (m.type === "state_override") {
      if (m.command === "TRIGGER_INTERVENTION" && !gameRunning) {
        gameRunning = true;
        document.documentElement.requestFullscreen?.().catch(() => {});
        document.getElementById("game").style.display = "block";
        startGame("game", () => sock.send({ type: "client_ready" }));
      } else if (m.command === "END_INTERVENTION" && gameRunning) {
        gameRunning = false;
        finishGame(() => {   // overlay done -> restore UI
          document.exitFullscreen?.().catch(() => {});
          document.getElementById("game").style.display = "none";
          document.getElementById("toast").style.display = "none";
        });
      }
    }
  } });
```

`static/operator/game.js` (functional placeholder this task — the tuned bio-game lands in Task 12):

```javascript
let score = 30;
let onReadyCb = null, onDoneCb = null, p = null, finished = false;

export function setScore(s) { if (typeof s === "number") score = s; }

export function startGame(hostId, readyCb) {
  onReadyCb = readyCb;
  finished = false;
  new p5((sketch) => {
    p = sketch;
    let particles = [];
    sketch.setup = () => {
      const c = sketch.createCanvas(sketch.windowWidth, sketch.windowHeight);
      c.parent(hostId);
      sketch.colorMode(sketch.RGB, 255);
      for (let i = 0; i < 300; i++) particles.push(newParticle());
      onReadyCb && onReadyCb();
      onReadyCb = null;
    };
    sketch.draw = () => {
      const calm = 1 - sketch.constrain(score / 100, 0, 1);
      sketch.background(10 + 40 * calm, 10 + 20 * calm, 30 + 30 * calm);
      for (const pt of particles) {
        pt.x += sketch.random(-1, 1) * (1 + 6 * (1 - calm));
        pt.y += sketch.random(-1, 1) * (1 + 6 * (1 - calm));
        sketch.noStroke();
        sketch.fill(200, 200, 255, 120);
        sketch.circle(pt.x, pt.y, pt.d);
      }
      drawOrb(sketch);
    };
  }, hostId);
}

function newParticle() {
  return { x: Math.random() * window.innerWidth,
           y: Math.random() * window.innerHeight,
           d: 2 + Math.random() * 4 };
}

function drawOrb(s) {
  const t = s.millis() / 1000;
  const phase = (t % 8) / 8;
  const grow = phase < 0.5 ? phase * 2 : (1 - phase) * 2;   // 4s in / 4s out
  const r = 60 + grow * 60;
  s.noStroke(); s.fill(120, 200, 255, 90);
  s.circle(s.width / 2, s.height / 2, r * 2);
  s.fill(235); s.textAlign(s.CENTER, s.CENTER); s.textSize(18);
  s.text(grow > 0.9 ? "breathe in" : "breathe out",
         s.width / 2, s.height / 2 + r + 24);
}

export function finishGame(doneCb) {
  onDoneCb = doneCb;
  if (!p || finished) { doneCb && doneCb(); return; }
  finished = true;
  p.noLoop();
  p.background(6, 40, 60);
  p.fill(235); p.textAlign(p.CENTER, p.CENTER); p.textSize(32);
  p.text("SYSTEM NOMINAL — RESUME MISSION", p.width / 2, p.height / 2);
  setTimeout(() => { p.remove(); p = null; onDoneCb && onDoneCb(); }, 2500);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_hub_ws.py tests/test_static.py -v`
Expected: 8 PASS

- [ ] **Step 5: Manual smoke — the P0 exit gate**

Run: `python main.py --source sim --scenario backend/scenarios/demo_pitch.yaml`
Then open `http://localhost:8000/command/` in a browser.
Expected: five operator cards; alpha_01 shows `CAL` for ~60s (config `baseline_s`), then a live score; sparkline draws; badges flip through states as scenarios unfold; DELTA-04 (early spike scenario) reaches WARNING/INTERVENTION within ~2 minutes; buttons trigger manual overrides; `S` toggles the SIM badge.

Note: `static/vendor/` is empty until bootstrap runs — pages render on `theme.css` alone (that's the graceful degradation path). For the polished run, fetch vendors:
```bash
mkdir -p static/vendor
curl -L -o static/vendor/p5.min.js https://cdn.jsdelivr.net/npm/p5@1.11.3/lib/p5.min.js
curl -L -o static/vendor/tailwind.js https://cdn.tailwindcss.com/3.4.16
```

- [ ] **Step 6: Commit**

```bash
git add backend/hub.py backend/app.py backend/router.py main.py static/ tests/test_hub_ws.py tests/test_static.py
git commit -m "feat: vertical slice — hub, ws fan-out, feed router, entrypoint, minimal frontends"
```


---

### Task 9: SIGNAL_LOST watchdog + automatic feed failover

**Files:**
- Modify: `backend/hub.py` (add `mark_signal_lost(op_id)`), `backend/router.py` (watchdog + feed swap + sim-mode hook)
- Test: `tests/test_failover.py`

**Interfaces:**
- Consumes: Task 8's `Hub`, `FeedRouter`.
- Produces:
  - `Hub.mark_signal_lost(op_id: str)` — forces the engine to SIGNAL_LOST via `EscalationEngine.signal_lost(t)` and runs the normal event pipeline
  - `FeedRouter` additions: `self._last_sample: dict[str, float]`, `self._feed: dict[str, str]` (`"sim"|"muse"`), watchdog tasks per muse-slot operator, `_swap_feed(op_id, to: str)`; registers `hub.feed_swap_hook = self._on_sim_mode` so the Command Center `S` toggle reroutes the live slot
  - Failover contract (spec §6/§9): silence > `signal_lost_s` → engine SIGNAL_LOST (grey badge) → still silent after `failover_delay_s` → feed swaps to the operator's standby sim stream, engine auto-resets on first resumed score

- [ ] **Step 1: Write the failing test**

```python
# tests/test_failover.py
import asyncio
import pytest
from backend.config import load_config
from backend.logging_db import LoggingDB
from backend.hub import Hub
from backend.engine import State

OVERRIDES = {
    "hub": {"broadcast_hz": 2.0, "operator_push_hz": 2.0},
    "dsp": {"baseline_s": 2.0, "tick_hz": 4.0},
    "thresholds": {"warn_sustain_s": 1.0, "intervene_sustain_s": 1.0,
                   "recover_sustain_s": 0.5, "release_sustain_s": 1.0,
                   "recovery_grace_s": 1.0, "signal_lost_s": 1.0,
                   "failover_delay_s": 0.5},
}

def test_hub_mark_signal_lost(tmp_path):
    cfg = load_config(None, {**OVERRIDES,
        "db": {"path": str(tmp_path / "t.db")}}, None)
    hub = Hub(cfg, LoggingDB(cfg.db.path))
    hub.mark_signal_lost("operator_alpha_01")
    assert hub.ops["operator_alpha_01"].state == State.SIGNAL_LOST

def test_router_failover_on_stream_death(tmp_path):
    """Standby sim stream dies -> watchdog fails over to the OTHER stream."""
    from backend.sources.sim_source import SimSource
    from backend.router import FeedRouter
    from backend.scenarios.loader import load_scenario

    def load_scenario_stub():
        return load_scenario(None)

    # Muse slot reads a stream prefixed "RealMuse-"; we serve it with a
    # second SimSource (prefix override) that we then kill mid-test.
    overrides = {**OVERRIDES, "db": {"path": str(tmp_path / "t.db")},
                 "operators": [
                     {"id": "operator_alpha_01", "callsign": "ALPHA-01",
                      "source": "muse", "scenario": "x.yaml", "seed": 1}],
                 "sources": {"sim_stream_prefix": "SimMuse"}}
    cfg = load_config(None, overrides, None)
    real_cfg = load_config(None, {**OVERRIDES,
        "db": {"path": str(tmp_path / "t.db")},
        "operators": [
            {"id": "operator_alpha_01", "callsign": "ALPHA-01",
             "source": "sim", "scenario": "x.yaml", "seed": 1}],
        "sources": {"sim_stream_prefix": "RealMuse"}}, None)
    hub = Hub(cfg, LoggingDB(cfg.db.path))
    real = SimSource(real_cfg, load_scenario_stub())       # the "Muse"
    standby = SimSource(cfg, load_scenario_stub())         # the failover
    router = FeedRouter(cfg, hub, load_scenario_stub())

    async def body():
        await asyncio.gather(real.start(), standby.start())
        run_task = asyncio.create_task(router.run())
        try:
            await asyncio.sleep(4.0)                # baseline flows from "Muse"
            assert hub.ops["operator_alpha_01"].state != State.SIGNAL_LOST
            await real.stop()                       # BLE "dies"
            await asyncio.sleep(3.5)                # > lost + failover window
            assert hub.ops["operator_alpha_01"].state != State.SIGNAL_LOST, \
                "failover did not resume scores"
            assert router._feed["operator_alpha_01"] == "sim"
        finally:
            await standby.stop()
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
            await router.stop()

    asyncio.run(asyncio.wait_for(body(), timeout=40.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_failover.py -v`
Expected: FAIL (`AttributeError: 'Hub' object has no attribute 'mark_signal_lost'`)

- [ ] **Step 3: Modify hub and router**

Add to `backend/hub.py` (after `manual_override`):

```python
    def mark_signal_lost(self, op_id: str):
        ev = self.engines[op_id].signal_lost(self.now())
        if ev:
            self._on_engine_event(ev)
```

Modify `backend/router.py` — add instance state in `__init__`:

```python
        self._last_sample: dict[str, float] = {op.id: self.hub.now()
                                               for op in cfg.operators}
        self._feed: dict[str, str] = {op.id: op.source for op in cfg.operators}
        self._readers: dict[str, asyncio.Task] = {}
```

Add watchdog + swap + sim-mode hook methods:

```python
    async def _watchdog(self, op_id: str):
        th = self.cfg.thresholds
        while self._running:
            silent_for = self.hub.now() - self._last_sample[op_id]
            if (self._feed[op_id] == "muse"
                    and silent_for > th.signal_lost_s):
                self.hub.mark_signal_lost(op_id)
                await asyncio.sleep(th.failover_delay_s)
                if self.hub.now() - self._last_sample[op_id] \
                        > th.signal_lost_s:
                    log.warning("%s failing over muse -> sim", op_id)
                    self.hub.db.log_event(self.hub.now(), op_id, "FAILOVER",
                                          "muse->sim")
                    await self._swap(op_id, "sim")
            await asyncio.sleep(0.5)

    async def _swap(self, op_id: str, to: str):
        self._feed[op_id] = to
        old = self._readers.get(op_id)
        if old:
            old.cancel()
        prefix = self.cfg.sources.sim_stream_prefix
        wanted = None if to == "muse" else f"{prefix}-{op_id}"
        self._readers[op_id] = asyncio.create_task(
            self._reader(op_id, wanted))

    def _on_sim_mode(self, enabled: bool):
        """Command Center S-key: live slot -> sim feed (and back)."""
        live = self.cfg.operators[0].id
        if self._feed[live] == "muse" and enabled:
            asyncio.create_task(self._swap(live, "sim"))
        elif self._feed[live] == "sim" and not enabled \
                and self.cfg.operators[0].source == "muse":
            asyncio.create_task(self._swap(live, "muse"))
```

In `run()`: register the hook and start watchdogs — replace the loop with:

```python
        self.hub.feed_swap_hook = self._on_sim_mode
        for op in self.cfg.operators:
            prefix = self.cfg.sources.sim_stream_prefix
            wanted = None if op.source == "muse" \
                else f"{prefix}-{op.id}"
            self._readers[op.id] = asyncio.create_task(
                self._reader(op.id, wanted))
            self._tasks.append(asyncio.create_task(self._ticker(op.id)))
            self._tasks.append(asyncio.create_task(self._watchdog(op.id)))
        await asyncio.gather(*self._tasks)
```

In `_reader()`, stamp sample freshness right after pulling:

```python
            if chunk:
                self._last_sample[op_id] = self.hub.now()
                self.dsp[op_id].add_samples(np.array(chunk, dtype=float))
```

In `stop()`, also cancel readers:

```python
        for t in self._readers.values():
            t.cancel()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_failover.py tests/test_hub_ws.py -v`
Expected: 7 PASS (failover test ~10s)

- [ ] **Step 5: Commit**

```bash
git add backend/hub.py backend/router.py tests/test_failover.py
git commit -m "feat: signal-lost watchdog with automatic muse->sim feed failover and S-key reroute"
```

---

### Task 10: End-to-end smoke test + selftest scripts

**Files:**
- Create: `tests/test_e2e.py`, `tests/e2e_config.yaml`, `tests/e2e_scenario.yaml`, `scripts/selftest.sh`, `scripts/selftest.ps1`
- Test: `tests/test_e2e.py` (marked `slow`)

**Interfaces:**
- Consumes: `main.py` CLI from Task 8.
- Produces: `scripts/selftest.{sh,ps1}` — the teammate's go/no-go gate (spec §8: "all-green on venue laptop ⇒ demo cannot fail for software reasons").

- [ ] **Step 1: Write the config + scenario + failing test**

`tests/e2e_config.yaml`:

```yaml
hub: {host: "127.0.0.1", port: 8123, broadcast_hz: 10.0, operator_push_hz: 5.0, record: false}
dsp: {fs: 256, window_s: 2.0, tick_hz: 4.0, baseline_s: 3.0}
thresholds:
  warn_sustain_s: 1.0
  intervene_sustain_s: 1.0
  recover_sustain_s: 0.5
  release_sustain_s: 1.0
  recovery_grace_s: 1.0
  signal_lost_s: 5.0
  failover_delay_s: 2.0
db: {path: "data/e2e.db"}
operators:
  - {id: operator_alpha_01, callsign: "ALPHA-01", source: sim, scenario: e2e_scenario.yaml, seed: 901}
  - {id: operator_bravo_02, callsign: "BRAVO-02", source: sim, scenario: e2e_scenario.yaml, seed: 902}
```

`tests/e2e_scenario.yaml`:

```yaml
operator_alpha_01:
  baseline: {duration: 3, stress: 0.10}
  events:
    - {t: 5,  action: ramp, to: 0.85, over: 2}
    - {t: 7,  action: hold, value: 0.85}
    - {t: 25, action: ramp, to: 0.12, over: 4}
operator_bravo_02:
  baseline: {duration: 3, stress: 0.12}
  loop:
    - {action: hold, value: 0.15, duration: 30}
    - {action: ramp, to: 0.40, over: 10}
```

```python
# tests/test_e2e.py
import json, subprocess, sys, time
import pytest
from websockets.sync.client import connect
import urllib.request

PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"

def recv_until(ws, typ, deadline):
    while time.time() < deadline:
        m = json.loads(ws.recv(timeout=5))
        if m.get("type") == typ:
            return m
    pytest.fail(f"never received {typ}")

@pytest.mark.slow
def test_full_ladder_over_websockets(tmp_path):
    proc = subprocess.Popen(
        [sys.executable, "main.py", "--source", "sim",
         "--config", "tests/e2e_config.yaml",
         "--scenario", "tests/e2e_scenario.yaml"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        ready = False
        for _ in range(60):
            try:
                urllib.request.urlopen(f"{BASE}/health", timeout=1).read()
                ready = True
                break
            except Exception:
                time.sleep(0.5)
        assert ready, "hub did not come up"

        t0 = time.time()
        cmd = connect(f"ws://127.0.0.1:{PORT}/ws/command")
        ope = connect(f"ws://127.0.0.1:{PORT}/ws/operator/operator_alpha_01")

        got_warning = got_trigger = got_end = None
        saw_cal_then_score = False
        cmd.send(json.dumps({"type": "heartbeat"}))
        deadline = t0 + 60
        while time.time() < deadline:
            m = json.loads(cmd.recv(timeout=5))
            if m.get("type") == "telemetry_batch":
                a = next(o for o in m["operators"]
                         if o["user_id"] == "operator_alpha_01")
                if a["stress_score"] is None:
                    saw_cal_then_score = True
                if a["state"] == "warning" and not got_warning:
                    got_warning = time.time() - t0
                if a["state"] == "intervention":
                    ack = json.dumps({"type": "client_ready"})
                    ope.send(ack)
                if a["state"] == "recovery":
                    got_end = time.time() - t0
                if a["state"] == "nominal" and got_end:
                    break
            elif m.get("type") == "warning_notice":
                got_warning = got_warning or (time.time() - t0)

        ov = recv_until(ope, "state_override", time.time() + 5)
        assert ov["command"] in ("TRIGGER_INTERVENTION", "END_INTERVENTION")
        assert saw_cal_then_score, "expected CAL phase then live scores"
        assert got_warning is not None, "no WARNING transition seen"
        assert got_end is not None, "no RECOVERY transition seen"
        assert got_warning < got_end

        # S-key sim mode flips the flag end-to-end
        cmd.send(json.dumps({"type": "sim_mode", "enabled": True}))
        batch = recv_until(cmd, "telemetry_batch", time.time() + 5)
        assert batch["sim"] is True
        cmd.close(); ope.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
```

- [ ] **Step 2: Run test to verify it fails or passes honestly**

Run: `python -m pytest tests/test_e2e.py -v -m slow` (allow ~90s)
Expected: PASS if Tasks 1–9 are correct. A failure here is the plan's own integration net — debug the failing stage, do not weaken asserts.

- [ ] **Step 3: Write selftest scripts**

`scripts/selftest.sh`:

```bash
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi
echo "== IronMind selftest =="
rc=0
"$PY" -m pytest -q "$@" || rc=$?   # trap, don't die: set -e would skip the verdict
if [ $rc -eq 0 ]; then echo "ALL GREEN — demo cannot fail for software reasons."; else echo "SELFTEST FAILED — fix before demo."; fi
exit $rc
```

`scripts/selftest.ps1`:

```powershell
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
Write-Host "== IronMind selftest =="
& $py -m pytest -q @args
if ($LASTEXITCODE -eq 0) { Write-Host "ALL GREEN - demo cannot fail for software reasons." }
else { Write-Host "SELFTEST FAILED - fix before demo."; exit 1 }
```

- [ ] **Step 4: Run the gate**

Run: `bash scripts/selftest.sh` (unsandboxed if LSL multicast is blocked)
Expected: full suite green including `slow`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e.py tests/e2e_config.yaml tests/e2e_scenario.yaml scripts/selftest.sh scripts/selftest.ps1
git commit -m "test: end-to-end ladder smoke over websockets + selftest gate scripts"
```


---

### Task 11: Command Center — full UI

**Files:**
- Modify: `static/command/index.html`, `static/command/app.js`, `tests/test_static.py`

**Interfaces:**
- Consumes: `telemetry_batch` frames (Task 8 shape), `/api/operators`, `manual_override`/`sim_mode` upstream messages.
- Produces: complete operator console — card grid with score/badge/sparkline/alpha-beta readout, amber outlines, `CAL` phase, alert log of state changes, manual Trigger/End/Reset per operator, `S` global-sim toggle, WS status chip, SIM badge. No build step; extends the Task 8 minimal files in place.

- [ ] **Step 1: Extend the static tripwire test (failing first)**

Add to `tests/test_static.py`:

```python
def test_command_page_has_alert_log_and_sim_toggle():
    html = (ROOT / "static/command/index.html").read_text()
    assert 'id="alertlog"' in html and 'id="simbadge"' in html
    js = (ROOT / "static/command/app.js").read_text()
    assert "alertlog" in js and 'key.toLowerCase() === "s"' in js
```

Run: `python -m pytest tests/test_static.py -v` → new test FAILS.

- [ ] **Step 2: Write the full page + app**

`static/command/index.html`:

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>IronMind Command</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="/static/vendor/tailwind.js" onerror="this.remove()"></script>
<link rel="stylesheet" href="/static/shared/theme.css">
<style>
  .score { font-size: 44px; font-weight: 800; line-height: 1; }
  #alertlog { max-height: 180px; overflow-y: auto; }
  #alertlog div { padding: 2px 0; border-bottom: 1px solid #223052;
    font-size: 13px; }
</style></head><body>
<div class="panel flex items-center gap-4" style="margin:12px">
  <h1 style="margin:0;font-size:18px;font-weight:700">
    IronMind Guardian — Command Center</h1>
  <span id="conn" class="dim">connecting…</span>
  <span id="simbadge" class="badge warning" style="display:none">SIM MODE</span>
  <span class="dim" style="margin-left:auto">S = sim toggle ·
    buttons steer operators</span>
</div>
<div id="grid" class="grid" style="margin:12px"></div>
<div class="panel" style="margin:12px">
  <b>Alert Log</b>
  <div id="alertlog"></div>
</div>
<script type="module" src="app.js"></script>
</body></html>
```

`static/command/app.js` (full replacement):

```javascript
import { connectWS } from "/static/shared/ws.js";

const grid = document.getElementById("grid");
const conn = document.getElementById("conn");
const simbadge = document.getElementById("simbadge");
const alertlog = document.getElementById("alertlog");
const cards = {};
const lastState = {};

const STATE_COLOR = {
  baseline: "#94a3b8", nominal: "#22c55e", warning: "#f59e0b",
  intervention: "#ef4444", recovery: "#22d3ee", signal_lost: "#a1a1aa",
};

function logAlert(callsign, from, to) {
  const d = document.createElement("div");
  const color = STATE_COLOR[to] || "#e6edf7";
  d.innerHTML = `<span class="dim">${new Date().toLocaleTimeString()}</span>
    <b>${callsign}</b> <span style="color:${color}">${from} → ${to}</span>`;
  alertlog.prepend(d);
  while (alertlog.children.length > 60) alertlog.lastChild.remove();
}

function card(op) {
  const d = document.createElement("div");
  d.className = "panel"; d.dataset.op = op.user_id;
  d.innerHTML = `
    <div class="flex items-center justify-between">
      <b>${op.callsign}</b>
      <span class="badge baseline" data-b>baseline</span>
    </div>
    <div class="score" data-score style="margin:8px 0">—</div>
    <canvas width="220" height="44" data-spark style="width:100%"></canvas>
    <div class="dim" data-bands style="margin:6px 0">α — · β —</div>
    <div class="flex gap-2">
      <button data-cmd="TRIGGER_INTERVENTION">Trigger</button>
      <button data-cmd="END_INTERVENTION">End</button>
      <button data-cmd="RESET">Reset</button>
    </div>`;
  d.querySelectorAll("button").forEach(b =>
    b.onclick = () => sock.send({ type: "manual_override",
      user_id: op.user_id, command: b.dataset.cmd }));
  grid.appendChild(d);
  return d;
}

function drawSpark(canvas, points, state) {
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "rgba(96,165,250,0.25)";
  [20, 45, 65, 80].forEach(v => {
    const y = canvas.height - (v / 100) * canvas.height;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
  });
  if (!points.length) return;
  ctx.strokeStyle = STATE_COLOR[state] || "#60a5fa";
  ctx.lineWidth = 2; ctx.beginPath();
  points.forEach((v, i) => {
    const x = (i / 119) * canvas.width;
    const y = canvas.height - (v / 100) * canvas.height;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

fetch("/api/operators").then(r => r.json())
  .then(ops => ops.forEach(op => {
    cards[op.user_id] = card(op);
    lastState[op.user_id] = "baseline";
  }));

const sock = connectWS(`ws://${location.host}/ws/command`, {
  onStatus: s => { conn.textContent = s; },
  onMsg: m => {
    if (m.type !== "telemetry_batch") return;
    simbadge.style.display = m.sim ? "inline-block" : "none";
    for (const op of m.operators) {
      const d = cards[op.user_id]; if (!d) continue;
      if (lastState[op.user_id] !== op.state) {
        logAlert(op.callsign, lastState[op.user_id], op.state);
        lastState[op.user_id] = op.state;
      }
      d.querySelector("[data-score]").textContent =
        op.stress_score ?? "CAL";
      d.querySelector("[data-score]").style.color =
        STATE_COLOR[op.state] || "#e6edf7";
      const b = d.querySelector("[data-b]");
      b.textContent = op.state; b.className = `badge ${op.state}`;
      d.classList.toggle("amber", !!op.amber);
      d.querySelector("[data-bands]").textContent =
        `α ${op.alpha_power.toPrecision(3)} · β ${op.beta_power.toPrecision(3)}`
        + (op.valid ? "" : " · ARTIFACT");
      drawSpark(d.querySelector("[data-spark]"), op.spark, op.state);
    }
  } });

addEventListener("keydown", e => {
  if (e.key.toLowerCase() === "s") {
    const enable = simbadge.style.display === "none";
    sock.send({ type: "sim_mode", enabled: enable });
  }
});
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_static.py tests/test_e2e.py -v -m "slow or not slow" --ignore=none` — minimum: `python -m pytest tests/test_static.py -v`
Expected: PASS (e2e unaffected)

- [ ] **Step 4: Visual check + commit**

Run the hub, watch a full scenario pass on `http://localhost:8000/command/`: CAL → scores → DELTA early intervention → alert log lines append; buttons work; `S` flips SIM badge.

```bash
git add static/command/ tests/test_static.py
git commit -m "feat: full command center UI (alert log, sparklines, overrides, sim toggle)"
```

---

### Task 12: Operator client — tuned bio-game ("Calm the Storm")

**Files:**
- Modify: `static/operator/app.js`, `static/operator/game.js`, `tests/test_static.py`

**Interfaces:**
- Consumes: `/ws/operator/{id}` frames (`telemetry_update`, `warning_notice`, `state_override`); p5 instance mode (2D canvas, ≤300 particles — UHD 620 budget, spec §3).
- Produces: fullscreen game; turbulence follows live `stress_score`; breathing orb 4s-in/4s-out; recovery overlay then auto-close; sends `client_ready` on canvas ready and `game_state {playing, recovered}` transitions; screen wake-lock while in game.

- [ ] **Step 1: Extend static tripwire (failing first)**

Add to `tests/test_static.py`:

```python
def test_game_respects_particle_budget_and_wakelock():
    game = (ROOT / "static/operator/game.js").read_text()
    assert "300" in game and "wakeLock" in (
        ROOT / "static/operator/app.js").read_text()
```

Run: `python -m pytest tests/test_static.py -v` → FAILS.

- [ ] **Step 2: Write the full operator app + game**

`static/operator/app.js` (full replacement):

```javascript
import { connectWS } from "/static/shared/ws.js";
import { startGame, finishGame, setScore } from "./game.js";

const opId = new URLSearchParams(location.search).get("id")
  || "operator_alpha_01";
document.getElementById("callsign").textContent = opId.toUpperCase();
let gameRunning = false;
let wakeLock = null;

async function takeWakeLock() {
  try { wakeLock = await navigator.wakeLock?.request("screen"); } catch {}
}
async function dropWakeLock() {
  try { await wakeLock?.release(); wakeLock = null; } catch {}
}

const sock = connectWS(`ws://${location.host}/ws/operator/${opId}`, {
  onMsg: m => {
    if (m.type === "telemetry_update") {
      document.getElementById("state").textContent = m.state;
      document.getElementById("score").textContent = m.stress_score ?? "CAL";
      setScore(m.stress_score);
    } else if (m.type === "warning_notice") {
      document.getElementById("toast").style.display = "block";
    } else if (m.type === "state_override") {
      if (m.command === "TRIGGER_INTERVENTION" && !gameRunning) {
        gameRunning = true;
        takeWakeLock();
        document.getElementById("toast").style.display = "none";
        document.documentElement.requestFullscreen?.().catch(() => {});
        document.getElementById("game").style.display = "block";
        startGame("game", () => sock.send({ type: "client_ready" }),
          () => sock.send({ type: "game_state", playing: true,
                            recovered: false }));
      } else if (m.command === "END_INTERVENTION" && gameRunning) {
        gameRunning = false;
        sock.send({ type: "game_state", playing: false, recovered: true });
        finishGame(() => {
          dropWakeLock();
          document.exitFullscreen?.().catch(() => {});
          document.getElementById("game").style.display = "none";
          document.getElementById("toast").style.display = "none";
        });
      }
    }
  } });
```

`static/operator/game.js` (full replacement):

```javascript
let score = 30;                 // last live score from telemetry_update
let p = null, finished = false;

export function setScore(s) { if (typeof s === "number") score = s; }

export function startGame(hostId, readyCb, startedCb) {
  finished = false;
  new p5((sketch) => {
    p = sketch;
    const N = 300;                       // hard particle budget (UHD 620)
    let particles = [];
    const newParticle = () => ({
      x: sketch.random(sketch.width), y: sketch.random(sketch.height),
      d: sketch.random(2, 6), drift: sketch.random(0.3, 1),
    });

    sketch.setup = () => {
      const c = sketch.createCanvas(sketch.windowWidth, sketch.windowHeight);
      c.parent(hostId);
      for (let i = 0; i < N; i++) particles.push(newParticle());
      readyCb && readyCb();
      startedCb && startedCb();
    };

    sketch.draw = () => {
      const stress = sketch.constrain(score / 100, 0, 1);
      const calm = 1 - stress;
      // sky: storm slate -> clearing blue as score drops
      sketch.background(15 + 20 * calm, 18 + 40 * calm, 38 + 50 * calm);

      // storm particles: turbulence ∝ stress
      const jitter = 1 + 7 * stress;
      const wind = 2.5 * stress;
      sketch.noStroke();
      for (const pt of particles) {
        pt.x += sketch.random(-1, 1) * jitter * pt.drift + wind;
        pt.y += sketch.random(-1, 1) * jitter * pt.drift;
        if (pt.x > sketch.width) pt.x = 0;
        if (pt.x < 0) pt.x = sketch.width;
        if (pt.y > sketch.height) pt.y = 0;
        if (pt.y < 0) pt.y = sketch.height;
        sketch.fill(190 + 40 * calm, 200, 255, 40 + 90 * calm);
        sketch.circle(pt.x, pt.y, pt.d);
      }

      drawOrb(sketch, stress);
      sketch.fill(235); sketch.noStroke();
      sketch.textAlign(sketch.LEFT, sketch.TOP); sketch.textSize(14);
      sketch.text(`stress ${Math.round(score)}`, 16, 34);
    };
  }, hostId);
}

function drawOrb(s, stress) {
  const t = s.millis() / 1000;
  const phase = (t % 8) / 8;
  const grow = phase < 0.5 ? phase * 2 : (1 - phase) * 2;  // 4s in / 4s out
  const r = 60 + grow * 60;
  s.push();
  s.noStroke(); s.fill(120, 200, 255, 70 + 40 * (1 - stress));
  s.circle(s.width / 2, s.height / 2, r * 2);
  s.noFill(); s.stroke(160, 220, 255, 160);
  s.strokeWeight(3); s.circle(s.width / 2, s.height / 2, r * 2);
  s.pop();
  s.fill(235); s.noStroke(); s.textAlign(s.CENTER, s.CENTER); s.textSize(20);
  s.text(grow > 0.9 ? "breathe in" : "breathe out",
         s.width / 2, s.height / 2 + r + 28);
}

export function finishGame(doneCb) {
  if (!p || finished) { doneCb && doneCb(); return; }
  finished = true;
  p.noLoop();
  p.background(4, 34, 50);
  p.fill(240); p.textAlign(p.CENTER, p.CENTER); p.textSize(32);
  p.text("SYSTEM NOMINAL — RESUME MISSION", p.width / 2, p.height / 2);
  p.textSize(16);
  p.text("Great work. Returning you to operations.",
         p.width / 2, p.height / 2 + 44);
  setTimeout(() => { p.remove(); p = null; doneCb && doneCb(); }, 2500);
}
```

- [ ] **Step 3: Run tests + visual check**

Run: `python -m pytest tests/test_static.py tests/test_e2e.py -m slow -v`
Expected: PASS.
Visual: run hub; open `/operator/?id=operator_delta_04` in a phone-sized window; wait for DELTA's spike → toast → fullscreen storm; breathe with the orb while (optionally a second person) watches; recovery closes it.

- [ ] **Step 4: Commit**

```bash
git add static/operator/ tests/test_static.py
git commit -m "feat: tuned bio-game (storm turbulence, breathing orb, wake-lock, recovery overlay)"
```

---

### Task 13: Pitch scenario tuning + deterministic harness + packet replay (Sim #2)

**Files:**
- Modify: `backend/sources/generator.py` (stress jitter), `backend/scenarios/demo_pitch.yaml` (final choreography)
- Create: `tests/test_pitch_scenario.py`, `scripts/packet_replay.py`
- Test: `tests/test_pitch_scenario.py`, `tests/test_replay.py`

**Interfaces:**
- Consumes: generator/DSP/engine (offline harness: no LSL, no server — feed generator chunks straight into `OperatorDSP` with synthetic clocks).
- Produces:
  - Generator gains slow stress jitter (±0.05 pink-modulated) → realistic baseline ratio variance, determinism preserved via seed
  - `demo_pitch.yaml` final values (tuning knobs; thresholds in config stay sacred)
  - `packet_replay.py --file data/demo_capture.jsonl [--port 8200] [--speed 1.0]` — standalone WS server rebroadcasting recorded `telemetry_batch` frames at 10Hz (Sim #2, spec §7; doubles as last-resort demo, spec §9.5)

- [ ] **Step 1: Write the failing harness test**

```python
# tests/test_pitch_scenario.py
"""Offline, deterministic, LSL-free rehearsal of the pitch scenario.
Runs the full math stack (generator -> DSP -> scorer -> engine) on the
demo_pitch timelines and asserts the STORY: who goes yellow/red/when."""
import numpy as np, yaml, pathlib, pytest
from backend.config import DSPCfg, Thresholds
from backend.dsp import OperatorDSP
from backend.engine import EscalationEngine, State
from backend.scenarios.loader import load_scenario
from backend.sources.generator import EEGGenerator

FS = 256
HARNESS_DSP = {"baseline_s": 12.0, "tick_hz": 2.0, "window_s": 4.0}

def run_operator(tl, seed, seconds=140.0):
    dsp_cfg = DSPCfg(fs=FS, baseline_s=HARNESS_DSP["baseline_s"],
                     tick_hz=HARNESS_DSP["tick_hz"],
                     window_s=HARNESS_DSP["window_s"])
    dsp = OperatorDSP("op", dsp_cfg)
    eng = EscalationEngine("op", Thresholds())
    gen = EEGGenerator(FS, seed)
    t = 0.0
    chunk = 32
    states = {}          # first-t index per state reached
    while t < seconds:
        stress = np.full(chunk, tl.stress_at(t))
        dsp.add_samples(gen.chunk(chunk, stress))
        t += chunk / FS
        if (int(t * FS) // chunk) % int(FS / chunk / HARNESS_DSP["tick_hz"]) == 0:
            r = dsp.tick(t)
            if r is not None:
                ev = eng.update(r.score, t)
                if ev and ev.to_state not in states:
                    states[ev.to_state] = t
    return states, eng.state

def load_tl(path, op_id):
    return load_scenario(path).for_op(op_id)

@pytest.fixture(scope="module")
def pitch():
    return pathlib.Path("backend/scenarios/demo_pitch.yaml").resolve()

def test_alpha01_reaches_intervention_then_recovers(pitch):
    states, _ = run_operator(load_tl(pitch, "operator_alpha_01"), seed=101,
                             seconds=185.0)     # cover the t=130-155 down-ramp
    assert State.INTERVENTION in states, f"never intervened: {states}"
    assert states[State.INTERVENTION] < 110     # inside the scripted window
    assert states.get(State.RECOVERY, 999) < 175

def test_delta_spikes_early(pitch):
    states, _ = run_operator(load_tl(pitch, "operator_delta_04"), seed=104)
    assert State.INTERVENTION in states
    assert states[State.INTERVENTION] < 65      # early spike story

def test_bravo_goes_warning_not_straight_red(pitch):
    states, _ = run_operator(load_tl(pitch, "operator_bravo_02"), seed=102)
    assert State.WARNING in states, f"bravo never warned: {states}"

def test_echo_stays_mostly_calm(pitch):
    states, final = run_operator(load_tl(pitch, "operator_echo_05"), seed=105)
    interventions = [t for s, t in states.items() if s == State.INTERVENTION]
    assert not interventions, f"echo intervened at {interventions}"
```

- [ ] **Step 2: Run harness to see current (untuned) behaviour**

Run: `python -m pytest tests/test_pitch_scenario.py -v`
Expected: some asserts FAIL or pass by luck — this is the tuning loop's baseline.

- [ ] **Step 3: Add generator stress jitter + tune demo_pitch.yaml**

Add to `EEGGenerator.__init__`: `self.slow = _Pink()` and a constant `STRESS_JITTER = 0.05` at module top. In `chunk()`, replace the stress lookup with jittered stress:

```python
        for i in range(n):
            tt = self.t + i / self.fs
            w = self.rng.standard_normal()
            s = float(np.clip(stress[i] + STRESS_JITTER * self.slow(w), 0, 1))
```

(use `s` in the `amplitudes(s)` call; keep the second `w` draw for the pink floor — two draws per sample is fine.)

Final `backend/scenarios/demo_pitch.yaml` (starting values — rerun the harness and nudge operator stress values until all four tests are green; **never touch thresholds in config**):

```yaml
operator_alpha_01:
  baseline: {duration: 45, stress: 0.10}
  events:
    - {t: 50,  action: ramp, to: 0.85, over: 25}
    - {t: 75,  action: hold, value: 0.85}
    - {t: 130, action: ramp, to: 0.12, over: 25}
operator_bravo_02:
  baseline: {duration: 45, stress: 0.12}
  loop:
    - {action: hold, value: 0.30, duration: 30}
    - {action: ramp, to: 0.48, over: 25}
    - {action: hold, value: 0.48, duration: 12}
    - {action: ramp, to: 0.15, over: 18}
operator_charlie_03:
  baseline: {duration: 45, stress: 0.10}
  loop:
    - {action: hold, value: 0.25, duration: 45}
    - {action: ramp, to: 0.38, over: 30}
operator_delta_04:
  baseline: {duration: 20, stress: 0.15}
  loop:
    - {action: ramp, to: 0.68, over: 18}
    - {action: hold, value: 0.68, duration: 12}
    - {action: ramp, to: 0.15, over: 25}
    - {action: hold, value: 0.15, duration: 30}
operator_echo_05:
  baseline: {duration: 45, stress: 0.10}
  loop:
    - {action: hold, value: 0.12, duration: 80}
    - {action: ramp, to: 0.14, over: 20}
    - {action: hold, value: 0.14, duration: 15}
```

- [ ] **Step 4: Run harness until green**

Run: `python -m pytest tests/test_pitch_scenario.py -v`
Expected: 4 PASS (adjust stress values only, in 0.05 steps, if a lane misses its story beat)

- [ ] **Step 5: Packet replay (Sim #2) + record flag — failing tests first**

```python
# tests/test_replay.py
import asyncio, json, time, threading
import pytest
from pathlib import Path

def test_packet_replay_serves_recorded_frames(tmp_path):
    f = tmp_path / "cap.jsonl"
    frames = [{"type": "telemetry_batch", "proto_v": 1, "t": i,
               "sim": True, "operators": [{"user_id": f"op{i}"}]}
              for i in range(3)]
    f.write_text("\n".join(json.dumps(x) for x in frames))
    from scripts.packet_replay import ReplayServer
    srv = ReplayServer(str(f), port=8231)
    thread = threading.Thread(target=srv.run_blocking, daemon=True)
    thread.start()
    time.sleep(0.8)
    from websockets.sync.client import connect
    c = connect("ws://127.0.0.1:8231/")
    got = [json.loads(c.recv(timeout=5)) for _ in range(2)]
    assert got[0]["t"] == 0 and got[1]["t"] == 1
    srv.stop(); c.close()

def test_hub_record_flag_writes_capture(tmp_path):
    from fastapi.testclient import TestClient
    from backend.config import load_config
    from backend.logging_db import LoggingDB
    from backend.hub import Hub
    from backend.app import build_app
    cap = tmp_path / "data" / "demo_capture.jsonl"
    cfg = load_config(None, {
        "hub": {"broadcast_hz": 10.0, "operator_push_hz": 1.0,
                "record": True, "capture_path": str(cap)},
        "db": {"path": str(tmp_path / "t.db")},
        "operators": [{"id": "operator_alpha_01", "callsign": "A",
                       "source": "sim", "scenario": "x", "seed": 1}],
    }, None)
    hub = Hub(cfg, LoggingDB(cfg.db.path))
    client = TestClient(build_app(cfg, hub))
    with client.websocket_connect("/ws/command"):
        time.sleep(0.6)
    assert cap.exists() and len(cap.read_text().strip().splitlines()) >= 3
```

`scripts/packet_replay.py`:

```python
"""Sim #2 (spec §7): replay recorded telemetry_batch frames to frontends.
Usage: python scripts/packet_replay.py --file data/demo_capture.jsonl
       [--port 8200] [--speed 1.0]"""
import argparse, asyncio, json
import websockets

class ReplayServer:
    def __init__(self, path: str, port: int = 8200, speed: float = 1.0):
        self.frames = [json.loads(l) for l in open(path) if l.strip()]
        self.port = port
        self.speed = speed
        self.clients: set = set()
        self._stop = False

    async def _handler(self, ws):
        self.clients.add(ws)
        try:
            await ws.wait_closed()
        finally:
            self.clients.discard(ws)

    async def _pump(self):
        i, interval = 0, 0.1 / self.speed
        while not self._stop:
            if self.clients:
                websockets.broadcast(
                    self.clients, json.dumps(self.frames[i % len(self.frames)]))
                i += 1
            await asyncio.sleep(interval)

    async def serve(self):
        async with websockets.serve(self._handler, "127.0.0.1", self.port):
            await self._pump()

    def run_blocking(self):
        asyncio.run(self.serve())

    def stop(self):
        self._stop = True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/demo_capture.jsonl")
    ap.add_argument("--port", type=int, default=8200)
    ap.add_argument("--speed", type=float, default=1.0)
    a = ap.parse_args()
    ReplayServer(a.file, a.port, a.speed).run_blocking()

if __name__ == "__main__":
    main()
```

For the record-flag test, `backend/hub.py` must honour `hub.capture_path` — change the `__init__` record block to:

```python
        if cfg.hub.record:
            import pathlib
            p = pathlib.Path(getattr(cfg.hub, "capture_path",
                                     "data/demo_capture.jsonl"))
            p.parent.mkdir(parents=True, exist_ok=True)
            self._rec = open(p, "a")
```

and add `capture_path: str = "data/demo_capture.jsonl"` to `HubCfg` + DEFAULTS in `backend/config.py` (DEFAULTS hub dict gains `"capture_path": "data/demo_capture.jsonl"`).

- [ ] **Step 6: Run tests until green**

Run: `python -m pytest tests/test_replay.py tests/test_pitch_scenario.py -v`
Expected: 6 PASS

- [ ] **Step 7: Capture the fallback demo + commit**

Run a real pass with `--config` overridden `record: true` (or a `record.yaml`) for one full pitch cycle, producing `data/demo_capture.jsonl` — copy it to `docs/fallback/demo_capture.jsonl` and commit (it is the last-resort demo, spec §9.5).

```bash
git add backend/sources/generator.py backend/scenarios/demo_pitch.yaml backend/config.py backend/config.yaml backend/hub.py scripts/packet_replay.py tests/test_pitch_scenario.py tests/test_replay.py docs/fallback/
git commit -m "feat: pitch scenario tuned via deterministic harness; packet replay + record (Sim #2)"
```


---

### Task 14: Real-Muse source + pairing guide

**Files:**
- Create: `backend/sources/muse_source.py`, `docs/MUSE_GUIDE.md`
- Test: `tests/test_muse_swap.py`

**Interfaces:**
- Consumes: `SourcesCfg` (`sim_stream_prefix` exclusion rule, `muse_address`).
- Produces: `MuseSource(cfg: AppConfig, mac: str|None = None)` with `ensure_stream_process() -> subprocess.Popen` (spawns `muselsl stream [--address MAC]`), `resolve_inlet(timeout: float = 30.0) -> StreamInlet` (first `EEG` stream whose `source_id` does **not** start with the sim prefix), `stop()`. FeedRouter's existing muse-slot path already consumes any non-prefixed stream — Task 9's failover covers it. NOTE: if `muselsl` proves numpy-2 incompatible, `pip install "numpy<2" pandas` and re-pin requirements (documented contingency; rerun full selftest after).

- [ ] **Step 1: Write the failing swap test**

```python
# tests/test_muse_swap.py
import asyncio
import pytest

@pytest.mark.slow
def test_muse_inlet_picks_non_sim_stream_and_pulls():
    """The 'real headset' is impersonated by a SimSource carrying a
    RealMuse prefix — proves inlet selection + pull path end-to-end."""
    from backend.config import load_config
    from backend.scenarios.loader import load_scenario
    from backend.sources.sim_source import SimSource
    from backend.sources.muse_source import MuseSource

    async def body():
        real_cfg = load_config(None, {
            "operators": [{"id": "operator_alpha_01", "callsign": "A",
                           "source": "sim", "scenario": "x.yaml", "seed": 7}],
            "sources": {"sim_stream_prefix": "RealMuse"}}, None)
        hub_cfg = load_config(None, {   # sim standby also running, must be skipped
            "operators": [{"id": "operator_alpha_01", "callsign": "A",
                           "source": "sim", "scenario": "x.yaml", "seed": 8}],
            "sources": {"sim_stream_prefix": "SimMuse"}}, None)
        real = SimSource(real_cfg, load_scenario(None))
        standby = SimSource(hub_cfg, load_scenario(None))
        await asyncio.gather(real.start(), standby.start())
        muse = MuseSource(hub_cfg)
        inlet = await asyncio.to_thread(muse.resolve_inlet, 15.0)
        inlet.open_stream(timeout=10.0)
        chunk, _ = await asyncio.to_thread(inlet.pull_chunk, 5.0)
        assert chunk and len(chunk[0]) == 5
        assert inlet.info().source_id().startswith("RealMuse")
        await asyncio.gather(real.stop(), standby.stop())

    asyncio.run(asyncio.wait_for(body(), timeout=60.0))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_muse_swap.py -v -m slow`
Expected: FAIL (`ModuleNotFoundError: backend.sources.muse_source`)

- [ ] **Step 3: Write implementation**

`backend/sources/muse_source.py`:

```python
from __future__ import annotations
import asyncio, logging, shutil, subprocess, sys
from pylsl import StreamInlet, resolve_byprop
from backend.config import AppConfig

log = logging.getLogger("muse")

class MuseSource:
    """Real headset: spawns `muselsl stream`, resolves its LSL inlet.
    Any EEG stream WITHOUT the sim prefix qualifies (spec §7 swap rule)."""

    def __init__(self, cfg: AppConfig, mac: str | None = None):
        self.cfg = cfg
        self.mac = mac or cfg.sources.muse_address
        self.proc: subprocess.Popen | None = None

    def ensure_stream_process(self) -> subprocess.Popen:
        exe = shutil.which("muselsl")
        if exe:
            cmd = [exe, "stream"]
        else:
            cmd = [sys.executable, "-m", "muselsl", "stream"]
        if self.mac:
            cmd += ["--address", self.mac]
        log.info("spawning %s", cmd)
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        return self.proc

    def resolve_inlet(self, timeout: float = 30.0) -> StreamInlet:
        deadline = asyncio.get_event_loop().time() + timeout \
            if asyncio.get_event_loop().is_running() else timeout * 10
        import time
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            infos = resolve_byprop("name", "EEG", timeout=2.0)
            for info in infos:
                if not info.source_id().startswith(
                        self.cfg.sources.sim_stream_prefix):
                    log.info("muse inlet: %s", info.source_id())
                    return StreamInlet(info, max_buflen=8)
        raise TimeoutError("no non-sim EEG stream found (headset streaming?)")

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc = None
```

`docs/MUSE_GUIDE.md` (full content):

```markdown
# Muse Pairing & Calibration Guide (for the demo laptop)

## Before leaving home
1. Charge the headset fully (LED solid white when done).
2. Pair ONCE at home per "Venue procedure" below; write the MAC into
   config.yaml -> sources.muse_address (e.g. "00:55:DA:B0:12:34").
3. Update Muse firmware via the official Muse app on a phone (one-time).

## Venue procedure (15 minutes before demo)
1. **Close the Muse app on every nearby phone.** Muse pairs ONE host at a
   time; a phone holding the connection is the #1 silent killer.
2. Put the headset on the presenter. Wet the electrode contacts (breath on
   them / a drop of water) — dry contacts = noisy alpha.
3. Fit: ear hooks snug, band mid-forehead, pads above eyebrows, rear pads
   behind ears. Check fit via the Muse app once, then CLOSE the app and
   kill its background process.
4. On the laptop: `python main.py --source muse` — hub log line
   `muse inlet: Muse-<serial>` means streaming. If it times out:
   - bluetooth-toggle on the laptop, retry
   - `scripts/doctor.ps1` and paste output to the remote operator
5. **Calibration = the first 60 seconds.** Presenter sits calm, breathes
   normally, minimal talking. The score baselines to ~15-25 during this.
6. Rehearse the recovery once: trigger manually, breathe with the orb,
   watch the score fall under 45 and the game self-close.

## Speaking while wearing it
Jaw/talk artifacts are real. Talk normally during baseline; the artifact
filter handles most of it. Avoid gum, big smiles and eyebrow raises in the
first minute. If the live signal is too noisy on stage, say nothing, press
nothing — SIGNAL_LOST/auto-failover covers the stream, and the commander
manual override covers the narrative.
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_muse_swap.py -v -m slow && bash scripts/selftest.sh`
Expected: all green

- [ ] **Step 5: Commit**

```bash
git add backend/sources/muse_source.py docs/MUSE_GUIDE.md tests/test_muse_swap.py
git commit -m "feat: real-Muse source (muselsl spawn + non-sim inlet resolution) and pairing guide"
```

---

### Task 15: Handover pack — bootstrap, doctor, runbook, README, pitch, GitHub

**Files:**
- Create: `scripts/bootstrap.ps1`, `scripts/bootstrap.sh`, `scripts/doctor.ps1`, `scripts/doctor.sh`, `docs/RUNBOOK.md`, `docs/HANDOFF.md`, `docs/PITCH.md`, `README.md`
- Needs from user: **GitHub repo URL** (create `ironmind-guardian` under the user's account, minimal repo, no LICENSE)

**Interfaces:**
- Consumes: everything.
- Produces: the teammate's one-command environment (spec §10). Bootstrap assumes network for `pip install` + vendor fetch; afterwards the demo runs fully offline.

- [ ] **Step 1: bootstrap scripts**

`scripts/bootstrap.ps1`:

```powershell
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
Write-Host "== IronMind bootstrap =="
# detect a launcher: `py -3.12` preferred, plain `python` fallback
$pyExe = $null; $pyVer = @()
foreach ($cand in @(@("py", "-3.12"), @("py", "-3.11"), @("python"))) {
  try {
    & $cand[0] $cand[1] --version 2>$null
    if ($LASTEXITCODE -eq 0) { $pyExe = $cand[0]; $pyVer = @($cand[1] | Where-Object { $_.StartsWith("-3") }); break }
  } catch {}
}
if (-not $pyExe) { Write-Error "Python 3.11/3.12 not found. Install from python.org (tick 'Add to PATH')." }
if (-not (Test-Path ".venv")) { & $pyExe @pyVer -m venv .venv }
$vp = ".venv\Scripts\python.exe"
& $vp -m pip install --upgrade pip
& $vp -m pip install -r requirements.txt
New-Item -ItemType Directory -Force -Path "static/vendor" | Out-Null
if (-not (Test-Path "static/vendor/p5.min.js")) {
  Invoke-WebRequest -Uri "https://cdn.jsdelivr.net/npm/p5@1.11.3/lib/p5.min.js" -OutFile "static/vendor/p5.min.js"
}
if (-not (Test-Path "static/vendor/tailwind.js")) {
  Invoke-WebRequest -Uri "https://cdn.tailwindcss.com/3.4.16" -OutFile "static/vendor/tailwind.js"
}
Write-Host "== selftest (this is the go/no-go gate) =="
& $vp -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Error "SELFTEST FAILED - do not demo until green." }
Write-Host ""
Write-Host "READY. Next steps:"
Write-Host "  .venv\Scripts\python main.py --source sim   (squad simulation)"
Write-Host "  .venv\Scripts\python main.py --source muse  (with headset)"
Write-Host "  Command Center:  http://localhost:8000/command/"
Write-Host "  Operator page:   http://localhost:8000/operator/?id=operator_alpha_01"
```

`scripts/bootstrap.sh`:

```bash
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
echo "== IronMind bootstrap =="
PY="${PYTHON:-python3}"
[ -x ".venv/bin/python" ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
mkdir -p static/vendor
[ -f static/vendor/p5.min.js ] || curl -L -o static/vendor/p5.min.js https://cdn.jsdelivr.net/npm/p5@1.11.3/lib/p5.min.js
[ -f static/vendor/tailwind.js ] || curl -L -o static/vendor/tailwind.js https://cdn.tailwindcss.com/3.4.16
echo "== selftest (go/no-go gate) =="
.venv/bin/python -m pytest -q
echo "READY.  python main.py --source sim   |   http://localhost:8000/command/"
```

- [ ] **Step 2: doctor scripts**

`scripts/doctor.ps1`:

```powershell
Set-Location (Join-Path $PSScriptRoot "..")
Write-Host "== IronMind doctor =="
Write-Host "-- /health --"
try { (Invoke-WebRequest -UseBasicParsing http://localhost:8000/health).Content } catch { Write-Host "hub NOT reachable on :8000" }
Write-Host "-- port 8000 --"
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Format-Table -Auto
Write-Host "-- python --"
if (Test-Path ".venv\Scripts\python.exe") { & ".venv\Scripts\python.exe" --version }
Write-Host "-- last 30 log lines --"
if (Test-Path "data\hub.log") { Get-Content "data\hub.log" -Tail 30 } else { Write-Host "no hub.log" }
Write-Host "-- vendor libs --"
Get-ChildItem static\vendor -ErrorAction SilentlyContinue | Format-Table Name,Length
Write-Host "Paste this entire output to the remote operator."
```

`scripts/doctor.sh`:

```bash
#!/usr/bin/env bash
cd "$(dirname "$0")/.."
echo "== IronMind doctor =="
echo "-- /health --"; curl -s --max-time 2 http://localhost:8000/health || echo "hub NOT reachable on :8000"
echo "-- python --"; [ -x .venv/bin/python ] && .venv/bin/python --version
echo "-- last 30 log lines --"; tail -30 data/hub.log 2>/dev/null || echo "no hub.log"
echo "-- vendor libs --"; ls -la static/vendor 2>/dev/null
echo "Paste this entire output to the remote operator."
```

- [ ] **Step 3: RUNBOOK.md (venue checklist, full content)**

```markdown
# Demo Runbook — 24h Hackathon

## Night before
- [ ] `scripts/bootstrap.ps1` green on the demo laptop (go/no-go gate)
- [ ] Full dress rehearsal done solo: `python main.py --source sim`,
      Command Center + operator page on the laptop, one full scenario cycle
- [ ] `docs/fallback/demo_capture.jsonl` present (last-resort replay)
- [ ] Laptop plugged in; Windows Update deferred; notifications OFF
      (Focus assist on); browser fullscreen tested on the projector

## Venue, T-minus 45 min
- [ ] Wi-Fi check: join venue wifi. If phone cannot reach laptop
      (client isolation): enable Windows Mobile Hotspot on the laptop,
      join the phone to it, use http://<laptop-hotspot-ip>:8000/
- [ ] Headset per docs/MUSE_GUIDE.md (battery, contacts, Muse apps CLOSED)
- [ ] `python main.py --source muse` → log shows `muse inlet: Muse-…`
- [ ] Calibration minute: presenter calm+silent for 60s (score → ~15-25)
- [ ] Browser tabs ready: Command Center (projector) + operator page
      on the phone; both showing live scores

## During the demo
- Presenter wears the headset; commander narrates from the grid.
- Squad mates drift/spike per scenario — the story tells itself.
- The intervention fires on real physiology; the "breathing orb" closes
  the loop. Talk DURING the ramp; let the visuals breathe during the drop.
- Safety nets: `S` = sim takeover; per-card Trigger/End buttons steer
  anything; SIGNAL_LOST self-heals to scripted squad behaviour.

## If everything dies
`python scripts/packet_replay.py --file docs/fallback/demo_capture.jsonl`
then open the frontends against `ws://localhost:8200/` — visually identical,
fully prerecorded (spec §9.5). Deliver the pitch; nobody loses the room.

## Remote operator (stays home)
Available on GitHub + video call. If anything looks wrong:
run `scripts/doctor.ps1`, paste output in the call. HANDOFF.md lists
what changed last.
```

- [ ] **Step 4: README.md + HANDOFF.md + PITCH.md**

`README.md`:

```markdown
# IronMind Guardian

Real-time, multi-user EEG telemetry + closed-loop neurofeedback for
emergency teams. Muse 2 headset -> LSL -> Python hub (DSP, escalation
ladder) -> plain-JS Command Center + operator PWA with a brain-controlled
resilience game. Runs end-to-end on synthetic squad data; a real headset
is a one-flag swap.

## Quickstart
    scripts/bootstrap.ps1          # Windows (or bootstrap.sh on mac/linux)
    .venv\Scripts\python main.py --source sim
    # Command Center:  http://localhost:8000/command/
    # Operator page:   http://localhost:8000/operator/?id=operator_alpha_01
    # With a headset:  python main.py --source muse  (docs/MUSE_GUIDE.md)

## Controls
- `S` on the Command Center: global sim takeover (spec safety net #1)
- Per-operator Trigger / End / Reset buttons: manual escalation
- `scripts/selftest.ps1`: go/no-go gate — must be green before any demo

## Docs
- Demo-day checklist: docs/RUNBOOK.md
- Stage notes + science Q&A: docs/PITCH.md
- Headset pairing: docs/MUSE_GUIDE.md
- Design spec: docs/superpowers/specs/2026-11-04-ironmind-guardian-design.md
- Latest handover notes: docs/HANDOFF.md
```

`docs/HANDOFF.md`:

```markdown
# Handoff — what changed and what to do

## 2026-11-04 (initial handover)
- Full system: hub/DSP/engine/sim + both frontends + safety nets.
- Teammate: pull `main`, run `scripts/bootstrap.ps1`, confirm ALL GREEN,
  then one solo dress rehearsal per docs/RUNBOOK.md.
- Known issues: (none at handover — update this line on every change)
- If anything breaks on site: scripts/doctor.ps1 → paste output to the
  remote operator. Do NOT debug beyond 10 minutes; use the fallback
  replay and keep the room.
```

`docs/PITCH.md` — science-questions cheat sheet (spec §2 honest-science framing;
the teammate memorizes the framing, not a script):

```markdown
# PITCH.md — IronMind Guardian stage notes & science cheat sheet

## The one-line claim (say exactly this)
"We measure cortical arousal — the brain's stress signature — in real time,
and we close the loop: the system detects the rise before the operator breaks
and forces a 60-second reset exercise the operator controls with their own
brainwaves."

## What the score IS (and is NOT)
- IS: a **cortical-arousal indicator** — the ratio of alpha power (8–12 Hz,
  relaxed/idle) to high-beta power (18–30 Hz, active load), scored 0–100
  against EACH OPERATOR'S OWN first-minute baseline.
- IS: relative and personal — "this operator is above their own calm
  reference", not an absolute number comparable across people.
- NOT: a diagnosis, a medical device, an emotion detector, or a mind reader.
  If a judge pushes: "It's the same physiological marker the literature uses
  for mental workload; we're transparent that it's an indicator, not a
  diagnosis."

## Anticipated judge questions
1. "How do you know it's stress and not effort/focus?" — "High-beta rises with
   cognitive load of any kind; in our operational framing, sustained load
   without recovery IS the risk we flag. We call it arousal, honestly."
2. "Why alpha/beta and not a trained ML model?" — "A model trained in a day
   on one person's data overfits and fails on stage. Personal baseline +
   z-score is defensible, explainable, and adapts per operator automatically."
3. "Does it work through noise — talking, movement?" — "Yes, that's why the
   pipeline has a line-noise notch, band-limiting, and per-channel artifact
   rejection (150µV) with median-across-channels — a bad channel bends the
   estimate, it doesn't break it."
4. "What happens if the headset disconnects mid-mission?" — "Show it live:
   grey badge within 5 seconds, then automatic failover to the synthetic
   squad stream. The system degrades gracefully, it never deadlocks."
5. "Is 256Hz consumer hardware enough?" — "Consumer EEG (Muse 2) is exactly
   the resilience story: no lab, no gel, deployable to real teams. All our
   claims are scoped to what it can honestly measure."

## Demo beats (scenario = backend/scenarios/demo_pitch.yaml)
- 0:00 Command Center up, five cards nominal, presenter narrates the mission.
- ~1:00 ALPHA (real headset) starts climbing — point at the sparkline crossing
  the yellow guide line; WARNING badge + phone toast fire on stage.
- Hold on the red escalation: INTERVENTION forces the fullscreen breathing
  game on the operator device; commander explains the closed loop.
- The payoff: score falls as the presenter slows their breathing WITH the orb
  — "the operator controls the intervention with their own brainwaves" —
  RECOVERY, self-close, nominal. Then mention SIGNAL_LOST failover as the
  resilience flourish (demo it once if time allows).

## If live EEG is too noisy on stage
Do NOT apologize. Flip `S` (global sim mode): "For reproducibility, here's the
same mission on our recorded squad telemetry" — and keep narrating. The
failover IS a feature; rehearse the sentence.
```

- [ ] **Step 5: Final gate + GitHub push (needs repo URL from user)**

```bash
bash scripts/selftest.sh   # full suite incl. slow, ALL GREEN
git add scripts/ docs/RUNBOOK.md docs/HANDOFF.md docs/PITCH.md README.md
git commit -m "docs: handover pack — bootstrap, doctor, runbook, README, pitch cheat sheet"
git tag demo-v0.1
# user provides: git remote add origin git@github.com:<user>/ironmind-guardian.git
git push -u origin main --tags
```

- [ ] **Step 6: Rehearsal call with teammate (P4 exit gate)**

Video call: teammate runs bootstrap fresh, does a full solo rehearsal
(sim mode, then muse if the headset has arrived), drives the `S` toggle
and manual overrides unprompted. The handover is DONE only when the
rehearsal completes without the remote operator touching anything.

---

## Plan Notes for the Implementer

- **Task order is mandatory** — every task consumes exact interfaces from earlier tasks.
- **Thresholds in `backend/config.yaml` are sacred.** Scenario stress values are the tuning knobs (Task 13).
- **Never make e2e asserts weaker to get green** — fix the stage the failure points to.
- **Sandbox note:** if LSL stream resolution times out inside a sandboxed shell, rerun the test unsandboxed (liblsl discovery uses multicast).
- Spec cross-reference: Tasks 1–4 = spec §7 Sim#1; 5–6 = §6 score+ladder; 7 = §5 protocol, logging; 8 = §3/§4 hub+frontends; 9 = §6 SIGNAL_LOST, §9.3; 10 = §8 pyramid top; 11–12 = §4 command/operator, §9.1/9.2; 13 = §7 Sim#2, §9.5; 14 = §7 swap + P3; 15 = §10 workflow + P4.
