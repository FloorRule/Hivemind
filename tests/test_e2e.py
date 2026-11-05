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
