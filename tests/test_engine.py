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
