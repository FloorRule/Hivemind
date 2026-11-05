# tests/test_failover.py
import asyncio
import pytest
from backend.config import load_config
from backend.logging_db import LoggingDB
from backend.hub import Hub
from backend.engine import State

OVERRIDES = {
    "hub": {"broadcast_hz": 2.0, "operator_push_hz": 2.0},
    "dsp": {"baseline_s": 2.0, "tick_hz": 4.0},
    "thresholds": {"warn_sustain_s": 1.0, "intervene_sustain_s": 1.0,
                   "recover_sustain_s": 0.5, "release_sustain_s": 1.0,
                   "recovery_grace_s": 1.0, "signal_lost_s": 1.0,
                   "failover_delay_s": 0.5},
}

def test_hub_mark_signal_lost(tmp_path):
    cfg = load_config(None, {**OVERRIDES,
        "db": {"path": str(tmp_path / "t.db")}}, None)
    hub = Hub(cfg, LoggingDB(cfg.db.path))
    hub.mark_signal_lost("operator_alpha_01")
    assert hub.ops["operator_alpha_01"].state == State.SIGNAL_LOST

def test_router_failover_on_stream_death(tmp_path):
    """Standby sim stream dies -> watchdog fails over to the OTHER stream."""
    from backend.sources.sim_source import SimSource
    from backend.router import FeedRouter
    from backend.scenarios.loader import load_scenario

    def load_scenario_stub():
        return load_scenario(None)

    # Muse slot reads a stream prefixed "RealMuse-"; we serve it with a
    # second SimSource (prefix override) that we then kill mid-test.
    overrides = {**OVERRIDES, "db": {"path": str(tmp_path / "t.db")},
                 "operators": [
                     {"id": "operator_alpha_01", "callsign": "ALPHA-01",
                      "source": "muse", "scenario": "x.yaml", "seed": 1}],
                 "sources": {"sim_stream_prefix": "SimMuse"}}
    cfg = load_config(None, overrides, None)
    real_cfg = load_config(None, {**OVERRIDES,
        "db": {"path": str(tmp_path / "t.db")},
        "operators": [
            {"id": "operator_alpha_01", "callsign": "ALPHA-01",
             "source": "sim", "scenario": "x.yaml", "seed": 1}],
        "sources": {"sim_stream_prefix": "RealMuse"}}, None)
    hub = Hub(cfg, LoggingDB(cfg.db.path))
    real = SimSource(real_cfg, load_scenario_stub())       # the "Muse"
    standby = SimSource(cfg, load_scenario_stub())         # the failover
    router = FeedRouter(cfg, hub, load_scenario_stub())

    async def body():
        await asyncio.gather(real.start(), standby.start())
        run_task = asyncio.create_task(router.run())
        try:
            await asyncio.sleep(4.0)                # baseline flows from "Muse"
            assert hub.ops["operator_alpha_01"].state != State.SIGNAL_LOST
            await real.stop()                       # BLE "dies"
            await asyncio.sleep(3.5)                # > lost + failover window
            assert hub.ops["operator_alpha_01"].state != State.SIGNAL_LOST, \
                "failover did not resume scores"
            assert router._feed["operator_alpha_01"] == "sim"
        finally:
            await standby.stop()
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
            await router.stop()

    asyncio.run(asyncio.wait_for(body(), timeout=40.0))

def test_watchdog_badges_silent_sim_feed_without_swap(tmp_path):
    """Spec ladder: ANY feed silent past signal_lost_s -> grey badge.
    Sim-native feeds have no failover target: badge + STATE_CHANGE log only,
    no swap and no FAILOVER event."""
    from backend.router import FeedRouter
    from backend.scenarios.loader import load_scenario

    overrides = {**OVERRIDES, "db": {"path": str(tmp_path / "t.db")},
                 "operators": [
                     {"id": "operator_alpha_01", "callsign": "ALPHA-01",
                      "source": "sim", "scenario": "x.yaml", "seed": 1}]}
    cfg = load_config(None, overrides, None)
    db = LoggingDB(cfg.db.path)
    hub = Hub(cfg, db)
    router = FeedRouter(cfg, hub, load_scenario(None))
    router._running = True
    router._last_sample["operator_alpha_01"] = hub.now() - 10.0

    async def body():
        wd = asyncio.create_task(router._watchdog("operator_alpha_01"))
        await asyncio.sleep(1.2)            # > one 0.5s poll cycle
        wd.cancel()
        await asyncio.gather(wd, return_exceptions=True)
        await router.stop()

    asyncio.run(asyncio.wait_for(body(), timeout=10.0))
    assert hub.ops["operator_alpha_01"].state == State.SIGNAL_LOST
    assert router._feed["operator_alpha_01"] == "sim"
    events = db.events_between(0.0, 1e9)
    assert not [e for e in events if e[2] == "FAILOVER"]
    assert [e for e in events if e[2] == "STATE_CHANGE"]
