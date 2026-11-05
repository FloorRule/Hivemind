from __future__ import annotations
import asyncio, logging, time
import numpy as np
from pylsl import ContinuousResolver, StreamInlet, resolve_byprop
from backend.config import AppConfig
from backend.dsp import DSPResult, OperatorDSP
from backend.engine import State
from backend.hub import Hub
from backend.scenarios.loader import ScenarioSet

log = logging.getLogger("router")

class FeedRouter:
    """Resolves one LSL inlet per operator, pulls chunks, ticks DSP."""

    def __init__(self, cfg: AppConfig, hub: Hub, timelines: ScenarioSet):
        self.cfg = cfg
        self.hub = hub
        self.timelines = timelines
        self.dsp = {op.id: OperatorDSP(op.id, cfg.dsp) for op in cfg.operators}
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._last_sample: dict[str, float] = {op.id: self.hub.now()
                                               for op in cfg.operators}
        self._feed: dict[str, str] = {op.id: op.source for op in cfg.operators}
        self._readers: dict[str, asyncio.Task] = {}

    async def run(self):
        self._running = True
        self.hub.feed_swap_hook = self._on_sim_mode
        for op in self.cfg.operators:
            prefix = self.cfg.sources.sim_stream_prefix
            # muse slot: first EEG stream NOT carrying the sim prefix
            wanted = None if op.source == "muse" \
                else f"{prefix}-{op.id}"
            self._readers[op.id] = asyncio.create_task(
                self._reader(op.id, wanted))
            self._tasks.append(asyncio.create_task(self._ticker(op.id)))
            self._tasks.append(asyncio.create_task(self._watchdog(op.id)))
        await asyncio.gather(*self._tasks)

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        for t in self._readers.values():
            t.cancel()

    def _match(self, info, wanted: str | None) -> bool:
        sid = info.source_id()
        if wanted is None:
            return not sid.startswith(self.cfg.sources.sim_stream_prefix)
        return sid == wanted

    def _resolve_muse(self) -> list:
        """EEG infos not carrying the sim prefix, via a continuous resolver.

        A point resolve (resolve_byprop with minimum=1) returns the first
        same-name replier — and the always-running sim standby outlets win
        that race, so the live muse stream would never match. The continuous
        resolver accumulates every discovery instead, making the muse slot
        deterministic."""
        resolver = ContinuousResolver("name", "EEG")
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            infos = [info for info in resolver.results()
                     if self._match(info, None)]
            if infos:
                return infos
            time.sleep(0.1)
        return []

    async def _reader(self, op_id: str, wanted: str | None):
        inlet = None
        while self._running and inlet is None:
            try:
                if wanted is None:
                    infos = await asyncio.to_thread(self._resolve_muse)
                else:
                    # (prop, value, minimum=1, timeout=2.0): pylsl's minimum
                    # arg is a ctypes int — a bare 2.0 there raises TypeError.
                    infos = await asyncio.to_thread(
                        resolve_byprop, "source_id", wanted, 1, 2.0)
                for info in infos:
                    if self._match(info, wanted):
                        inlet = StreamInlet(info, max_buflen=8)
                        break
            except Exception as e:
                log.warning("%s inlet resolve failed: %s", op_id, e)
            if inlet is None:
                await asyncio.sleep(1.0)
        if inlet is None:
            return
        log.info("%s inlet connected: %s", op_id, inlet.info().source_id())
        while self._running:
            chunk, _ts = await asyncio.to_thread(inlet.pull_chunk, 0.25)
            if chunk:
                self._last_sample[op_id] = self.hub.now()
                self.dsp[op_id].add_samples(np.array(chunk, dtype=float))

    async def _watchdog(self, op_id: str):
        th = self.cfg.thresholds
        while self._running:
            silent_for = self.hub.now() - self._last_sample[op_id]
            if silent_for > th.signal_lost_s:
                # Spec ladder: ANY feed silent past the budget -> grey badge.
                # The swap is muse-only (sim has no failover target). Skip
                # when already grey so a never-resuming feed doesn't spam a
                # STATE_CHANGE row every poll.
                if self.hub.ops[op_id].state != State.SIGNAL_LOST:
                    self.hub.mark_signal_lost(op_id)
                if self._feed[op_id] == "muse":
                    await asyncio.sleep(th.failover_delay_s)
                    if self.hub.now() - self._last_sample[op_id] \
                            > th.signal_lost_s:
                        log.warning("%s failing over muse -> sim", op_id)
                        self.hub.db.log_event(self.hub.now(), op_id,
                                              "FAILOVER", "muse->sim")
                        await self._swap(op_id, "sim")
            await asyncio.sleep(0.5)

    async def _swap(self, op_id: str, to: str):
        self._feed[op_id] = to
        old = self._readers.get(op_id)
        if old:
            old.cancel()
        prefix = self.cfg.sources.sim_stream_prefix
        wanted = None if to == "muse" else f"{prefix}-{op_id}"
        self._readers[op_id] = asyncio.create_task(
            self._reader(op_id, wanted))

    def _on_sim_mode(self, enabled: bool):
        """Command Center S-key: live slot -> sim feed (and back)."""
        live = self.cfg.operators[0].id
        if self._feed[live] == "muse" and enabled:
            asyncio.create_task(self._swap(live, "sim"))
        elif self._feed[live] == "sim" and not enabled \
                and self.cfg.operators[0].source == "muse":
            asyncio.create_task(self._swap(live, "muse"))

    async def _ticker(self, op_id: str):
        interval = 1.0 / self.cfg.dsp.tick_hz
        while self._running:
            r = self.dsp[op_id].tick(self.hub.now())
            if r is not None:
                if self.hub.now() - self._last_sample[op_id] \
                        > self.cfg.dsp.window_s:
                    # Frozen window: data older than the DSP window is not
                    # the operator's current state. Mirror tick()'s own
                    # invalid shape so the engine gets None (hold + disarm)
                    # instead of a stale score — no phantom escalation and
                    # the grey badge holds until genuinely fresh data.
                    r = DSPResult(t=r.t, alpha=0.0, hbeta=0.0, ratio=0.0,
                                  score=r.score, valid=False)
                self.hub.on_dsp_result(op_id, r)
            await asyncio.sleep(interval)
