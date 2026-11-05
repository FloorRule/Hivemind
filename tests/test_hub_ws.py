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
