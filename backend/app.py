from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from backend.config import AppConfig
from backend.hub import Hub

ROOT = Path(__file__).resolve().parent.parent

def build_app(cfg: AppConfig, hub: Hub) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub.start_loops()      # sync API: registers the loop tasks
        yield
        hub.stop_loops()       # cancels them + closes the recorder

    app = FastAPI(title="IronMind Guardian", lifespan=lifespan)

    @app.websocket("/ws/command")
    async def command_ws(ws: WebSocket):
        await hub.handle_command_ws(ws)

    @app.websocket("/ws/operator/{op_id}")
    async def operator_ws(ws: WebSocket, op_id: str):
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

    return app
