# tests/test_dsp.py
import numpy as np
from backend.dsp import (RingBuffer, preprocess, channel_valid,
                         compute_band_powers, StressScorer, OperatorDSP)
from backend.config import DSPCfg

FS = 256
N = FS * 4          # 4s window

def sine(freq, uv, n=N):
    t = np.arange(n) / FS
    return uv * np.sin(2 * np.pi * freq * t)

def test_ring_buffer_keeps_last_k():
    rb = RingBuffer(5, 512)
    rb.append(np.ones((300, 5)))
    rb.append(np.full((512, 5), 2.0))     # overflow wipes the ones entirely
    latest = rb.latest(512)
    assert latest.shape == (512, 5)
    assert latest[0, 0] == 2.0 and latest[-1, 0] == 2.0

def test_preprocess_removes_line_noise():
    data = (sine(10, 50) + sine(50, 200)).reshape(-1, 1) * np.ones((1, 5))
    cleaned = preprocess(data, FS, (50, 60), (1, 40))
    assert np.abs(cleaned).max() < 100    # 200uV 50Hz component gone

def test_alpha_sine_dominates_beta_band():
    data = (sine(10, 50) + sine(50, 200)).reshape(-1, 1) * np.ones((1, 5))
    x = preprocess(data, FS, (50, 60), (1, 40))
    a, b = compute_band_powers(x, FS, (8, 12), (18, 30), 150.0)
    assert a > 10 * b

def test_artifact_rejection_median_survives_two_corrupted_channels():
    clean = (sine(10, 50)).reshape(-1, 1) * np.ones((1, 5))
    clean = preprocess(clean, FS, (50, 60), (1, 40))
    corrupted = clean.copy()
    corrupted[:, 1] += sine(60, 400)      # blow out AF7
    corrupted[:, 2] += sine(45, 400)      # blow out AF8
    a_clean, b_clean = compute_band_powers(clean, FS, (8, 12), (18, 30), 150.0)
    a_corr, b_corr = compute_band_powers(corrupted, FS, (8, 12), (18, 30), 150.0)
    assert np.abs(a_corr - a_clean) / a_clean < 0.5   # median of TP9/TP10 holds

def test_fewer_than_two_valid_channels_returns_none():
    clean = (sine(10, 50)).reshape(-1, 1) * np.ones((1, 5))
    corrupted = clean.copy()
    for c in range(5):
        corrupted[:, c] += sine(60, 400)  # kill all channels
    x = preprocess(corrupted, FS, (50, 60), (1, 40))
    assert compute_band_powers(x, FS, (8, 12), (18, 30), 150.0) is None

def test_scorer_baseline_then_scores():
    sc = StressScorer(baseline_s=2.0, tick_hz=10.0, offset=20.0, scale=25.0)
    assert not sc.ready
    for i in range(20):
        assert sc.update(0.25, i / 10.0) is None
    assert sc.ready
    s_calm = sc.update(0.25, 2.1)
    assert 10 <= s_calm <= 25              # ~baseline level -> low score
    assert sc.update(0.50, 2.2) == 100     # 2x baseline -> saturates
    assert sc.last_score == 100

def test_operator_dsp_tick_flow():
    cfg = DSPCfg(fs=FS, window_s=4.0, tick_hz=2.0, baseline_s=2.0)
    od = OperatorDSP("op1", cfg)
    assert od.tick(0.0) is None            # not enough data yet
    for i in range(FS * 5):                # 5s of calm-ish signal
        od.add_samples(sine(10, 40).reshape(-1, 1) * np.ones((1, 5)))
    for t in (2.0, 2.5, 3.0):              # collect calm baseline ticks
        od.tick(t)
    r = od.tick(5.0)
    assert r is not None and r.valid
    assert r.score is None                 # still in baseline (need 4 ticks)
    for i in range(FS * 3):
        od.add_samples((sine(10, 40) + sine(22, 60)).reshape(-1, 1) * np.ones((1, 5)))
    r = None
    for i in range(6):                     # tick past baseline (>=4 ticks)
        r = od.tick(8.0 + i * 0.5)
    assert r is not None and r.score is not None and r.score > 50
