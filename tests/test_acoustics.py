"""Acoustics maths: IEC weighting, base-10 bands, tone level, reference tone."""
import numpy as np
import pytest
from scipy import signal

from pydvma import acoustics, verify, datastructure, options
from pydvma.acoustics import ACOUSTICS_VECTORS


def _exact(n):
    return 1000 * 10 ** (round(10 * np.log10(n / 1000)) / 10)


def test_weighting_iec_table():
    A = {10: -70.4, 20: -50.5, 31.5: -39.4, 63: -26.2, 100: -19.1, 125: -16.1,
         250: -8.6, 500: -3.2, 1000: 0, 2000: 1.2, 4000: 1.0, 8000: -1.1,
         10000: -2.5, 16000: -6.6, 20000: -9.3}
    C = {10: -14.3, 20: -6.2, 31.5: -3.0, 63: -0.8, 125: -0.2, 250: 0.0,
         500: 0.0, 1000: 0, 2000: -0.2, 4000: -0.8, 8000: -3.0, 16000: -8.5,
         20000: -11.2}
    for curve, table in (('A', A), ('C', C)):
        for n, want in table.items():
            got = float(acoustics.weighting_db(_exact(n), curve))
            assert abs(got - want) <= 0.1, (curve, n, got, want)


def test_weighting_known_answers():
    for f, a, c in ACOUSTICS_VECTORS:
        assert abs(float(acoustics.weighting_db(f, 'A')) - a) < 1e-6
        assert abs(float(acoustics.weighting_db(f, 'C')) - c) < 1e-6
    assert abs(float(acoustics.weighting_db(1000.0, 'A'))) < 1e-12
    assert abs(float(acoustics.weighting_db(1000.0, 'C'))) < 1e-12
    assert np.all(acoustics.weighting_db([1, 50, 5000], 'Z') == 0)


def test_weighting_at_zero_hz():
    assert acoustics.weighting_db([0.0, 1000.0], 'A')[0] == -np.inf
    f = np.arange(0, 24000, 1.0)
    out = acoustics.band_levels(f, np.ones(f.size), 'octave', 'A')
    assert np.all(np.isfinite(out['power']))


def test_band_table_nominals():
    t = acoustics.band_table('octave', 22, 22400)
    assert t['nominal'] == [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
    t = acoustics.band_table('third-octave', 890, 1125)
    assert t['nominal'] == [1000]
    t = acoustics.band_table('third-octave', 17, 23000)
    assert t['nominal'][:4] == [20, 25, 31.5, 40] and t['nominal'][-1] == 20000


def test_band_levels_white_noise():
    f = np.arange(0, 24000, 1.0)
    D = 3e-6
    out = acoustics.band_levels(f, np.full(f.size, D), 'octave')
    i = out['nominal'].index(1000)
    assert abs(out['power'][i] - D * (out['upper'][i] - out['lower'][i])) <= 1.5 * D


def test_band_levels_tone():
    fs = 48000
    x = np.sin(2 * np.pi * 1000 * np.arange(fs * 4) / fs)
    f, p = signal.welch(x, fs, window='hann', nperseg=8192, scaling='density')
    out = acoustics.band_levels(f, p, 'octave')
    assert out['power'][out['nominal'].index(1000)] == pytest.approx(0.5, rel=0.02)


def test_band_levels_min_bins():
    f = np.arange(0, 2000) * 5.86
    out = acoustics.band_levels(f, np.ones(f.size), 'third-octave')
    assert 25 not in out['nominal'] and 1000 in out['nominal']
    two = acoustics.band_levels(f, np.ones((2, f.size)), 'third-octave')
    assert two['power'].shape == (2, len(two['nominal']))


def _td(x, fs=48000.0, **kw):
    n = x.shape[0]
    st = options.MySettings(channels=1, fs=fs, device_driver='mock', **kw)
    return datastructure.TimeData(np.arange(n) / fs, x[:, None], st)


def _tone(f, rms, noise_db=-60, fs=48000.0, n=48000 * 2, seed=0):
    t = np.arange(n) / fs
    rng = np.random.default_rng(seed)
    return rms * np.sqrt(2) * np.sin(2 * np.pi * f * t) + rng.standard_normal(n) * rms * 10 ** (noise_db / 20)


def test_reference_tone_calibration():
    r = acoustics.reference_tone_calibration(_td(_tone(1000, 0.0335)), 0, 1.0, 1000)
    assert r['sensitivity'] == pytest.approx(0.0335, rel=1e-3)
    assert r['warnings'] == [] and r['clipped'] is False
    assert abs(r['peak_freq'] - 1000) < 2


def test_reference_tone_warnings():
    r = acoustics.reference_tone_calibration(_td(_tone(1300, 0.1)), 0, 1.0, 1000)
    assert any('1300' in w or '1299' in w or '1300.' in w for w in r['warnings'])
    r = acoustics.reference_tone_calibration(_td(_tone(1000, 0.1, noise_db=3)), 0, 1.0, 1000)
    assert any('noise' in w.lower() and 'dB' in w for w in r['warnings'])
    x = _tone(1000, 0.1, noise_db=-80)
    x = x / np.max(np.abs(x)) * 0.99
    r = acoustics.reference_tone_calibration(_td(x, VmaxSC=1.0), 0, 1.0, 1000)
    assert r['clipped'] is True and any('0.99' in w for w in r['warnings'])


def test_verify_alias():
    assert verify._measure_tone_vrms is acoustics.tone_rms
