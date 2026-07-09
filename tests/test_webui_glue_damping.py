"""Regression tests for the webui pyodide glue's damping op (round-7 rebuild).

The browser engine loads ``webui/src/lib/worker/glue.py`` inside pyodide and
drives it with plain dicts / flat float64 arrays. These tests import that same
module directly under CPython and exercise ``calc_damping`` the way the JS
``actions.calcDamping`` does — so a glue-level regression is caught fast (no
pyodide, no browser).

Round-7 rebuild: the glue used to DISCARD the full per-fit plotting dict and
return only fn/Qn, which is why the web UI could not draw the decay-fit plot
the Qt ``DampingFitWindow`` had. It now returns the fit lines plus the
peak-picking context (start_time / threshold / slice spectrum / candidate
peaks) that the interactive panel draws, and accepts the ``peak_threshold``
and ``start_time`` knobs.
"""

import os
import sys

import numpy as np
import pytest

# Import the webui glue module directly (it lives outside the pydvma package).
_WORKER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'webui', 'src', 'lib', 'worker'
)
if _WORKER_DIR not in sys.path:
    sys.path.insert(0, _WORKER_DIR)

glue = pytest.importorskip('glue', reason='webui glue.py requires pydvma importable')

FS = 2000
N = 8000


def _decay(fn, Q, amp=1.0):
    t = np.arange(N) / FS
    zeta = 1.0 / (2.0 * Q)
    wn = 2 * np.pi * fn
    return amp * np.exp(-zeta * wn * t) * np.sin(wn * np.sqrt(1 - zeta ** 2) * t)


def _payload():
    """One-channel time payload exactly as JS timePayload marshals it."""
    y = (_decay(90.0, 40.0) + 0.4 * _decay(400.0, 60.0)).reshape(-1, 1)
    t = np.arange(N) / FS
    return {
        'time_axis': t.astype(np.float64),
        'time_data': y.astype(np.float64).ravel(),
        'n_channels': 1,
        'fs': FS,
    }


def _vals(arr_dict):
    """Values of a glue ``_arr`` marshal ({shape, data, complex})."""
    return np.asarray(arr_dict['data'])


class TestCalcDampingContext:
    def test_returns_fits_and_picking_context(self):
        p = _payload()
        out = glue.calc_damping(p['time_axis'], p['time_data'], p['n_channels'],
                                p['fs'], ch=0, nperseg=256)
        assert len(_vals(out['fn'])) >= 1
        # The context the interactive panel draws.
        for key in ('start_time', 'threshold', 'slice_freq', 'slice_mag',
                    'peaks_freq', 'peaks_mag', 'fits'):
            assert key in out, f'calc_damping missing {key}'
        assert _vals(out['slice_freq']).shape == _vals(out['slice_mag']).shape
        assert len(out['fits']) == len(_vals(out['fn']))
        m = out['fits'][0]
        for key in ('t_fit', 'real_fit', 'real_data'):
            assert len(_vals(m[key])) > 4
        assert _vals(m['t_fit']).shape == _vals(m['real_fit']).shape
        assert np.isfinite(m['f_peak']) and np.isfinite(m['Qn'])

    def test_explicit_threshold_and_start_time_are_honoured(self):
        p = _payload()
        out = glue.calc_damping(p['time_axis'], p['time_data'], p['n_channels'],
                                p['fs'], ch=0, nperseg=256,
                                start_time=0.5, peak_threshold=0.1)
        assert out['threshold'] == 0.1
        # start_time snaps to the nearest STFT frame of 0.5 s.
        assert abs(out['start_time'] - 0.5) < 256 / FS
        # A maximal threshold suppresses every candidate.
        top = glue.calc_damping(p['time_axis'], p['time_data'], p['n_channels'],
                                p['fs'], ch=0, nperseg=256, peak_threshold=1.0)
        assert len(_vals(top['fn'])) == 0 and len(top['fits']) == 0

    def test_cwt_path_carries_context_too(self):
        p = _payload()
        out = glue.calc_damping(p['time_axis'], p['time_data'], p['n_channels'],
                                p['fs'], ch=0, nperseg=256, method='cwt',
                                peak_threshold=0.1)
        assert out['threshold'] == 0.1
        assert len(_vals(out['fn'])) >= 1
        assert np.any(np.abs(_vals(out['peaks_freq']) - 90.0) / 90.0 < 0.1)


class TestCalcDampingBands:
    """The round-7 'by band' damping op: Schroeder decay metrics per band."""

    def _noise_payload(self, t60=0.5):
        rng = np.random.default_rng(5)
        t = np.arange(N) / FS
        y = (rng.standard_normal(N) * 10.0 ** (-3.0 * t / t60)).reshape(-1, 1)
        return {
            'time_axis': t.astype(np.float64),
            'time_data': y.astype(np.float64).ravel(),
            'n_channels': 1,
            'fs': FS,
        }

    def test_octave_ladder_metrics_marshal(self):
        p = self._noise_payload()
        out = glue.calc_damping_bands(p['time_axis'], p['time_data'],
                                      p['n_channels'], p['fs'], ch=0,
                                      bands='octave', f_min=80.0, f_max=800.0)
        assert out['bands'] == 'octave'
        fc = _vals(out['fc'])
        assert len(fc) >= 2
        for key in ('f_lo', 'f_hi', 'EDT', 'T20', 'T30', 'T60', 'Qn'):
            assert _vals(out[key]).shape == fc.shape
        t60 = _vals(out['T60'])
        ok = np.isfinite(t60)
        assert ok.any()
        assert np.allclose(t60[ok], 0.5, rtol=0.2)
        band = out['band_data'][int(np.flatnonzero(ok)[0])]
        assert _vals(band['edc_t']).shape == _vals(band['edc_db']).shape
        assert 'fit_t' in band

    def test_all_band_and_start_time(self):
        p = self._noise_payload(t60=0.4)
        out = glue.calc_damping_bands(p['time_axis'], p['time_data'],
                                      p['n_channels'], p['fs'], ch=0,
                                      bands='all', f_min=100.0, f_max=900.0,
                                      start_time=0.25)
        assert len(_vals(out['fc'])) == 1
        assert abs(out['start_time'] - 0.25) < 2.0 / FS
