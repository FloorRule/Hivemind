from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.signal import butter, filtfilt, iirnotch, sosfiltfilt, welch
from backend.config import DSPCfg

@dataclass
class DSPResult:
    t: float
    alpha: float
    hbeta: float
    ratio: float
    score: int | None
    valid: bool

class RingBuffer:
    def __init__(self, n_ch: int, capacity: int):
        self.capacity = capacity
        self.buf = np.zeros((0, n_ch))

    def append(self, chunk: np.ndarray):
        self.buf = np.vstack((self.buf, chunk))[-self.capacity:]

    def latest(self, k: int) -> np.ndarray:
        return self.buf[-k:]

def preprocess(data: np.ndarray, fs: int, notch_hz: tuple,
               band_hz: tuple) -> np.ndarray:
    x = data.astype(float)
    nyq = fs / 2.0
    for f in notch_hz:
        b, a = iirnotch(f / nyq, 30.0)
        x = filtfilt(b, a, x, axis=0)
    sos = butter(4, [band_hz[0] / nyq, band_hz[1] / nyq],
                 btype="band", output="sos")
    return sosfiltfilt(sos, x, axis=0)

def channel_valid(data: np.ndarray, artifact_uv: float) -> np.ndarray:
    return np.abs(data).max(axis=0) < artifact_uv

def compute_band_powers(data: np.ndarray, fs: int, alpha_hz: tuple,
                        hbeta_hz: tuple,
                        artifact_uv: float) -> tuple[float, float] | None:
    valid = channel_valid(data, artifact_uv)
    if valid.sum() < 2:
        return None
    nper = min(256, data.shape[0])
    freqs, psd = welch(data[:, valid], fs=fs, nperseg=nper,
                       noverlap=nper // 2, axis=0)
    def band(lo, hi):
        m = (freqs >= lo) & (freqs <= hi)
        per_ch = np.trapezoid(psd[m, :], freqs[m], axis=0)
        return float(np.median(per_ch))
    return band(*alpha_hz), band(*hbeta_hz)

class StressScorer:
    """Score = offset + scale * z(ratio vs personal calm baseline), clipped 0..100.

    The baseline anchor is the mean ratio observed while collecting the
    baseline window; spread is the population std of baseline ratios. Both
    need guards for real (overlapping-window) data:

    - mean, not min: the minimum sits ~1-1.5 sigma below the baseline mean,
      which biases every post-baseline reading positive and pegs the score
      the instant baseline completes.
    - sd floored at SD_FLOOR_FRAC * anchor: consecutive baseline ticks share
      nearly the whole DSP window (sliding 100%-overlap Welch), so the raw
      std measures micro-fluctuation (a few % of the ratio), not honest
      band-power variation (Welch estimator CV ~15-20%). Without the floor,
      any real fluctuation produces an enormous z and the score saturates at
      100 permanently — recovery becomes unreachable.
    """

    SD_FLOOR_FRAC = 0.15

    def __init__(self, baseline_s: float, tick_hz: float,
                 offset: float = 20.0, scale: float = 25.0):
        self._need = max(int(baseline_s * tick_hz), 2)
        self._buf: list[float] = []
        self._anchor = None
        self._sd = None
        self._offset = offset
        self._scale = scale
        self.last_score: int | None = None

    @property
    def ready(self) -> bool:
        return self._anchor is not None

    def update(self, ratio: float, t: float) -> int | None:
        if not self.ready:
            self._buf.append(ratio)
            if len(self._buf) >= self._need:
                arr = np.array(self._buf)
                self._anchor = float(arr.mean())
                self._sd = max(float(arr.std()),
                               self.SD_FLOOR_FRAC * self._anchor, 1e-6)
            return None
        z = (ratio - self._anchor) / self._sd
        self.last_score = int(np.clip(self._offset + self._scale * z, 0, 100))
        return self.last_score

class OperatorDSP:
    def __init__(self, op_id: str, cfg: DSPCfg):
        self.op_id = op_id
        self.cfg = cfg
        n_ch = 5
        self.ring = RingBuffer(n_ch, int(cfg.fs * cfg.window_s))
        self.scorer = StressScorer(cfg.baseline_s, cfg.tick_hz,
                                   cfg.score_offset, cfg.score_scale)

    def add_samples(self, chunk: np.ndarray):
        self.ring.append(chunk)

    def tick(self, t: float) -> DSPResult | None:
        need = int(self.cfg.fs * self.cfg.window_s)
        if self.ring.buf.shape[0] < self.cfg.fs * 2:
            return None
        data = self.ring.latest(min(need, self.ring.buf.shape[0]))
        x = preprocess(data, self.cfg.fs, self.cfg.notch_hz,
                       self.cfg.bandpass_hz)
        bp = compute_band_powers(x, self.cfg.fs, self.cfg.alpha_hz,
                                 self.cfg.hbeta_hz, self.cfg.artifact_uv)
        if bp is None:
            return DSPResult(t=t, alpha=0.0, hbeta=0.0, ratio=0.0,
                             score=self.scorer.last_score, valid=False)
        alpha, hbeta = bp
        ratio = hbeta / max(alpha, 1e-9)
        score = self.scorer.update(ratio, t)
        return DSPResult(t=t, alpha=alpha, hbeta=hbeta, ratio=ratio,
                         score=score, valid=True)
