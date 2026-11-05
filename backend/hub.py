from __future__ import annotations
import asyncio, json, logging, sqlite3, time
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

    # LoggingDB owns a single sqlite connection (check_same_thread default),
    # created on the asyncio-loop thread in production. The in-process
    # TestClient runs the app on a portal thread, so during tests these calls
    # can arrive cross-thread; drop them there instead of killing the handler.
    # On the real single-loop deployment the guard never triggers.
    def _log_event(self, *args):
        try:
            self.db.log_event(*args)
        except sqlite3.ProgrammingError:
            log.warning("dropped %s db log (db closed or cross-thread)",
                        "event")

    def _log_score(self, *args):
        try:
            self.db.log_score(*args)
        except sqlite3.ProgrammingError:
            log.warning("dropped %s db log (db closed or cross-thread)",
                        "score")

    # ---- DSP intake ------------------------------------------------------
    def on_dsp_result(self, op_id: str, r):
        st = self.ops[op_id]
        st.score, st.alpha, st.hbeta, st.valid = r.score, r.alpha, r.hbeta, r.valid
        if r.valid and r.score is not None:
            st.spark.append(r.score)
        # Task 5 contract: an invalid window carries a stale score — hand the
        # engine None so it holds state and resets its arming clocks instead.
        ev = self.engines[op_id].update(r.score if r.valid else None, r.t)
        if ev:
            self._on_engine_event(ev)

    def _on_engine_event(self, ev: EngineEvent):
        st = self.ops[ev.op_id]
        st.state = ev.to_state
        log.info("%s %s -> %s (%s)", ev.op_id, ev.from_state.value,
                 ev.to_state.value, ev.reason)
        self._log_event(self.now(), ev.op_id, "STATE_CHANGE",
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
        self._log_event(self.now(), op_id, "GAME_READY", "")

    def on_game_state(self, op_id: str, playing: bool, recovered: bool):
        self._log_event(self.now(), op_id, "GAME_STATE",
                        f"playing={playing} recovered={recovered}")

    def manual_override(self, op_id: str, command: str) -> EngineEvent | None:
        if op_id not in self.engines:
            return None
        ev = self.engines[op_id].force(command, self.now())
        if ev:
            self._on_engine_event(ev)
        return ev

    def mark_signal_lost(self, op_id: str):
        ev = self.engines[op_id].signal_lost(self.now())
        if ev:
            self._on_engine_event(ev)

    def set_sim_mode(self, enabled: bool):
        self.sim_mode = enabled
        self._log_event(self.now(), "SYSTEM", "SIM_MODE", str(enabled))
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
                        self._log_score(self.now(), op_id, st.score,
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
