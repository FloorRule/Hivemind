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
    dsp = dict(d["dsp"])
    for k in ("notch_hz", "bandpass_hz", "alpha_hz", "hbeta_hz"):
        dsp[k] = tuple(dsp[k])
    return AppConfig(
        hub=HubCfg(**d["hub"]),
        dsp=DSPCfg(**dsp),
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
