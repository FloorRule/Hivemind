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

def test_missing_op_gets_default(tmp_path):
    ts = load_scenario(write(tmp_path))
    tl = ts.for_op("operator_echo_05")
    assert tl.stress_at(61) == DEFAULT_TIMELINE["loop"][0]["value"]

def test_default_timeline_is_calm():
    assert DEFAULT_TIMELINE["baseline"]["stress"] <= 0.15
