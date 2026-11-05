# tests/test_sim_source.py
import asyncio
import numpy as np
import pytest
from backend.config import load_config
from backend.scenarios.loader import load_scenario
from backend.sources.sim_source import SimSource

def test_sim_streams_lsl_with_muse_metadata():
    async def body():
        cfg = load_config(None, None, "sim")
        tl = load_scenario(None)
        src = SimSource(cfg, tl)
        await src.start()
        from pylsl import resolve_byprop, StreamInlet
        infos = resolve_byprop("name", "EEG", timeout=5.0)
        assert infos, "no EEG stream resolved"
        inlet = StreamInlet(infos[0], max_buflen=4)
        inlet.open_stream(timeout=5.0)
        chunk, ts = inlet.pull_chunk(timeout=5.0)
        assert chunk and len(chunk[0]) == 5
        assert infos[0].nominal_srate() == 256
        assert infos[0].source_id().startswith("SimMuse-")
        await src.stop()
    asyncio.run(asyncio.wait_for(body(), timeout=30.0))

def test_all_five_outlets_running():
    async def body():
        cfg = load_config(None, None, "sim")
        src = SimSource(cfg, load_scenario(None))
        await src.start()
        assert len(src.outlets) == 5
        await src.stop()
    asyncio.run(asyncio.wait_for(body(), timeout=30.0))

def test_stop_reraises_pump_thread_failure():
    async def body():
        cfg = load_config(None, None, "sim")

        class BoomTL:
            def stress_at(self, t):
                raise RuntimeError("pump exploded")

        class BoomSet:
            def for_op(self, op_id):
                return BoomTL()

        src = SimSource(cfg, BoomSet())
        await src.start()
        await asyncio.sleep(0.2)  # pumps hit the failure almost immediately
        with pytest.raises(RuntimeError, match="pump exploded"):
            await src.stop()
    asyncio.run(asyncio.wait_for(body(), timeout=30.0))
