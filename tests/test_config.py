# tests/test_config.py
from pathlib import Path

import yaml

from backend.config import DEFAULTS, load_config

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

def test_yaml_file_load_path():
    cfg = load_config("backend/config.yaml", None, None)
    assert cfg.dsp.alpha_hz == (8, 12) and cfg.dsp.notch_hz == (50, 60)
    assert cfg.thresholds.intervene_score == 80
    assert len(cfg.operators) == 5

def test_yaml_file_matches_defaults_per_section():
    parsed = yaml.safe_load(Path("backend/config.yaml").read_text())
    assert parsed.keys() == DEFAULTS.keys()
    for section in DEFAULTS:
        assert parsed[section] == DEFAULTS[section], f"drift in section: {section}"
