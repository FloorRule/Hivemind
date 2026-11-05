from __future__ import annotations
import threading
import time
import numpy as np
from pylsl import StreamInfo, StreamOutlet
from backend.config import AppConfig
from backend.scenarios.loader import ScenarioSet
from backend.sources.generator import EEGGenerator, CHANNELS

CHUNK = 8  # samples per push: 8/256s = 31.25ms pacing

class SimSource:
    """Streams synthetic EEG for every operator over LSL (standby for all,
    live for sim-mode operators). Muse metadata indistinguishable to DSP.

    Pumping runs on dedicated threads so consumers that call pylsl's blocking
    API on their own thread (or event loop) can never starve the feed."""

    def __init__(self, cfg: AppConfig, timelines: ScenarioSet):
        self.outlets: dict[str, StreamOutlet] = {}
        self._cfg = cfg
        self._timelines = timelines
        self._t0: float | None = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._errors: dict[str, BaseException] = {}
        for op in cfg.operators:
            info = StreamInfo(
                name="EEG", type="EEG", channel_count=len(CHANNELS),
                nominal_srate=cfg.dsp.fs, channel_format="float32",
                source_id=f"{cfg.sources.sim_stream_prefix}-{op.id}",
            )
            desc = info.desc()
            chans = desc.append_child("channels")
            for label in CHANNELS:
                chans.append_child("channel").append_child_value("label", label)
            desc.append_child_value("manufacturer", "IronMind Sim")
            self.outlets[op.id] = StreamOutlet(info, chunk_size=CHUNK, max_buffered=256)

    async def start(self):
        self._stop.clear()
        self._errors.clear()
        self._t0 = time.monotonic()
        for op in self._cfg.operators:
            t = threading.Thread(target=self._pump, args=(op.id,),
                                 name=f"sim-source-{op.id}", daemon=True)
            t.start()
            self._threads.append(t)

    async def stop(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads.clear()
        if self._errors:
            raise next(iter(self._errors.values()))

    def _pump(self, op_id: str):
        try:
            seed = next(o.seed for o in self._cfg.operators if o.id == op_id)
            gen = EEGGenerator(self._cfg.dsp.fs, seed)
            tl = self._timelines.for_op(op_id)
            outlet = self.outlets[op_id]
            dt = CHUNK / self._cfg.dsp.fs
            next_push = time.monotonic()
            while not self._stop.is_set():
                stress = np.full(CHUNK, tl.stress_at(time.monotonic() - self._t0))
                # The outlet declares float32; pylsl push_chunk reinterprets
                # the buffer without conversion, so push float32 explicitly
                # (float64 bytes alias into ~1e38/NaN garbage on the wire).
                outlet.push_chunk(gen.chunk(CHUNK, stress).astype(np.float32))
                next_push += dt
                delay = next_push - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_push = time.monotonic()  # fell behind: resync, don't burst
        except Exception as exc:
            self._errors[op_id] = exc  # surfaced by stop(); thread exits, not live
