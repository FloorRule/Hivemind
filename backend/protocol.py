from __future__ import annotations

PROTO_V = 1

COMMANDS = {"TRIGGER_INTERVENTION", "END_INTERVENTION", "RESET"}

# Lane spellings accepted by validate_incoming: the command lane carries
# operator-control frames (manual_override, sim_mode), the operator lane
# carries dashboard state frames (client_ready, game_state). Heartbeat is
# accepted on either lane.
_LANES = {"cmd": "command", "command": "command",
          "op": "operator", "operator": "operator"}

def validate_incoming(msg: dict, context: str) -> bool:
    lane = _LANES.get(context, context)
    t = msg.get("type")
    if t == "manual_override" and lane == "command":
        return bool(msg.get("user_id")) and msg.get("command") in COMMANDS
    if t == "sim_mode" and lane == "command":
        return isinstance(msg.get("enabled"), bool)
    if t == "client_ready" and lane == "operator":
        return True
    if t == "game_state" and lane == "operator":
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
