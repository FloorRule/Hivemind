from __future__ import annotations
import argparse, asyncio, logging, pathlib
import uvicorn
from backend.app import build_app
from backend.config import load_config
from backend.hub import Hub
from backend.logging_db import LoggingDB
from backend.router import FeedRouter
from backend.scenarios.loader import load_scenario
from backend.sources.sim_source import SimSource

def parse_args():
    p = argparse.ArgumentParser(description="IronMind Guardian hub")
    p.add_argument("--source", choices=["sim", "muse"], default="muse",
                   help="driver for the live slot operator_alpha_01")
    p.add_argument("--config", default="backend/config.yaml")
    p.add_argument("--scenario", default=None,
                   help="scenario yaml override (else per-operator from config)")
    return p.parse_args()

async def orchestrate(args):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler("data/hub.log"),
                  logging.StreamHandler()])
    cfg = load_config(args.config, None, args.source)
    scenario_path = args.scenario or str(
        pathlib.Path(cfg.scenario_dir) / cfg.operators[0].scenario)
    timelines = load_scenario(scenario_path)
    db = LoggingDB(cfg.db.path)
    hub = Hub(cfg, db)
    app = build_app(cfg, hub)
    sim = SimSource(cfg, timelines)      # standby feeds: ALWAYS running
    await sim.start()
    router = FeedRouter(cfg, hub, timelines)
    router_task = asyncio.create_task(router.run())
    server = uvicorn.Server(uvicorn.Config(
        app, host=cfg.hub.host, port=cfg.hub.port, log_level="info"))
    try:
        await server.serve()
    finally:
        await router.stop()
        await sim.stop()
        db.close()

def main():
    pathlib.Path("data").mkdir(exist_ok=True)
    asyncio.run(orchestrate(parse_args()))

if __name__ == "__main__":
    main()
