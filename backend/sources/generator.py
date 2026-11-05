from __future__ import annotations
import numpy as np

CHANNELS = ["TP9", "AF7", "AF8", "TP10", "AUX"]
FRONTAL_IDX = (1, 2)          # AF7, AF8 — where blinks live
ALPHA_HZ = 10.0
BETA_HZ = 22.0
PINK_SCALE_UV = 6.0           # broadband noise floor in microvolts
BLINK_UV = 350.0
BLINK_S = 0.30
JAW_UV = 90.0
JAW_S = 0.40

def amplitudes(s: float) -> tuple[float, float]:
    """Map scenario stress 0..1 -> (alpha_amp_uv, beta_amp_uv)."""
    alpha = 12.0 * (1.15 - 1.05 * s)
    beta = 6.0 * (0.35 + 1.95 * s)
    return alpha, beta

class _Pink:
    """Paul Kellet pink-noise filter, stateful per channel."""
    __slots__ = ("b0", "b1", "b2")

    def __init__(self):
        self.b0 = self.b1 = self.b2 = 0.0

    def __call__(self, w: float) -> float:
        self.b0 = 0.99765 * self.b0 + w * 0.0990460
        self.b1 = 0.96300 * self.b1 + w * 0.2965164
        self.b2 = 0.57000 * self.b2 + w * 1.0526913
        return (self.b0 + self.b1 + self.b2 + w * 0.1848) * 0.20

class EEGGenerator:
    def __init__(self, fs: int, seed: int):
        self.fs = fs
        self.rng = np.random.default_rng(seed)
        self.pinks = [_Pink() for _ in CHANNELS]
        self.t = 0.0
        self.phase = self.rng.uniform(0, 2 * np.pi)
        self._next_blink = self.rng.uniform(3.0, 8.0)
        self._next_jaw = self.rng.uniform(18.0, 40.0)

    def chunk(self, n: int, stress: np.ndarray) -> np.ndarray:
        out = np.zeros((n, len(CHANNELS)))
        blink_on = self._next_blink <= self.t + n / self.fs
        jaw_on = self._next_jaw <= self.t + n / self.fs
        for i in range(n):
            tt = self.t + i / self.fs
            a, b = amplitudes(float(stress[i]))
            row = np.empty(len(CHANNELS))
            for c, pink in enumerate(self.pinks):
                w = self.rng.standard_normal()
                row[c] = (a * np.sin(2 * np.pi * ALPHA_HZ * tt + self.phase)
                          + b * np.sin(2 * np.pi * BETA_HZ * tt)
                          + PINK_SCALE_UV * pink(w))
            if blink_on and self._in_window(tt, self._next_blink, BLINK_S):
                frac = (tt - self._next_blink) / BLINK_S
                amp = BLINK_UV * np.sin(np.pi * frac) ** 2
                for c in FRONTAL_IDX:
                    row[c] += amp
            if jaw_on and self._in_window(tt, self._next_jaw, JAW_S):
                w = self.rng.standard_normal()
                row += JAW_UV * w + JAW_UV * np.sin(2 * np.pi * 45.0 * tt)
            out[i] = row
        self.t += n / self.fs
        if blink_on and self.t > self._next_blink + BLINK_S:
            self._next_blink = self.t + self.rng.uniform(3.0, 8.0)
        if jaw_on and self.t > self._next_jaw + JAW_S:
            self._next_jaw = self.t + self.rng.uniform(18.0, 40.0)
        return out

    @staticmethod
    def _in_window(t: float, start: float, dur: float) -> bool:
        return start <= t <= start + dur
