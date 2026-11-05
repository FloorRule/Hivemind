import numpy as np
from scipy.signal import welch
from backend.sources.generator import EEGGenerator, CHANNELS

FS = 256

def band_power(sig, lo, hi):
    f, p = welch(sig, fs=FS, nperseg=256)
    m = (f >= lo) & (f <= hi)
    return float(np.trapezoid(p[m], f[m]))

def test_calm_chunk_alpha_dominant():
    g = EEGGenerator(FS, seed=7)
    stress = np.full(1024, 0.10)
    data = g.chunk(1024, stress)           # (1024, 5)
    assert data.shape == (1024, 5)
    tp9 = data[:, 0]
    a = band_power(tp9, 8, 12)
    b = band_power(tp9, 18, 30)
    assert a > 3 * b                        # calm: alpha clearly dominant

def test_stressed_chunk_beta_dominant():
    g = EEGGenerator(FS, seed=7)
    g.chunk(1024, np.full(1024, 0.10))      # settle filters at calm
    data = g.chunk(1024, np.full(1024, 0.90))
    tp9 = data[:, 0]
    assert band_power(tp9, 18, 30) > band_power(tp9, 8, 12)

def test_blink_hits_frontal_only_and_exceeds_artifact_threshold():
    g = EEGGenerator(FS, seed=7)
    data = g.chunk(256 * 12, np.full(256 * 12, 0.10))
    frontal_peak = np.abs(data[:, [1, 2]]).max()
    temporal_peak = np.abs(data[:, [0, 3]]).max()
    assert frontal_peak > 150.0             # crosses artifact_uv threshold
    assert temporal_peak < 80.0             # temporals stay clean-ish

def test_determinism_same_seed():
    d1 = EEGGenerator(FS, 11).chunk(256, np.full(256, 0.2))
    d2 = EEGGenerator(FS, 11).chunk(256, np.full(256, 0.2))
    assert np.array_equal(d1, d2)

def test_channel_count_matches_muse():
    assert CHANNELS == ["TP9", "AF7", "AF8", "TP10", "AUX"]
