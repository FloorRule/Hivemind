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
