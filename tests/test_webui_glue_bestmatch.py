"""Regression tests for the webui pyodide glue's Best-Match scaling op.

The browser engine loads ``webui/src/lib/worker/glue.py`` inside pyodide and
drives ``calc_best_match`` with plain dicts / flat interleaved-complex float64
arrays (the same marshalling ``actions.calcBestMatch`` uses).  These tests
import that module directly under CPython so a glue-level regression in the
relative TF scaling tool (Qt parity: ``analysis.best_match``) is caught fast
(no pyodide, no browser).
"""

import os
import sys

import numpy as np
import pytest

_WORKER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'webui', 'src', 'lib', 'worker'
)
if _WORKER_DIR not in sys.path:
    sys.path.insert(0, _WORKER_DIR)

glue = pytest.importorskip('glue', reason='webui glue.py requires pydvma importable')


def _sdof_flat(f, fn, zeta, scale=1.0):
    """Interleaved-complex [re,im,...] accelerance FRF of one SDOF resonance."""
    w = 2 * np.pi * f
    wn = 2 * np.pi * fn
    H = scale * ((-w ** 2) / (wn ** 2 - w ** 2 + 2j * zeta * wn * w)).reshape(-1, 1)
    flat = np.empty(H.size * 2)
    flat[0::2] = H.real.ravel()
    flat[1::2] = H.imag.ravel()
    return flat


def _set(f, fn, zeta, scale=1.0):
    return {'freq_axis': f, 'tf_data': _sdof_flat(f, fn, zeta, scale), 'n_tf': 1}


def test_best_match_recovers_scale_factor():
    """A set scaled by k gets factor ~1/k; the reference set gets ~1."""
    f = np.linspace(1, 200, 400)
    sets = [
        _set(f, 50.0, 0.02, scale=1.0),   # reference
        _set(f, 50.0, 0.02, scale=3.0),   # 3x larger — should scale by 1/3
        _set(f, 50.0, 0.02, scale=0.25),  # 4x smaller — should scale by 4
    ]
    out = glue.calc_best_match(sets, freq_range=[1.0, 200.0], set_ref=0, ch_ref=0)
    facs = [np.asarray(a['data']) for a in out['factors']]
    assert facs[0][0] == pytest.approx(1.0, rel=1e-6)
    assert facs[1][0] == pytest.approx(1.0 / 3.0, rel=1e-3)
    assert facs[2][0] == pytest.approx(4.0, rel=1e-3)


def test_best_match_none_range_uses_full_band():
    """freq_range=None falls back to the reference set's full band (no crash)."""
    f = np.linspace(1, 100, 200)
    sets = [_set(f, 30.0, 0.03, 1.0), _set(f, 30.0, 0.03, 2.0)]
    out = glue.calc_best_match(sets, freq_range=None, set_ref=0, ch_ref=0)
    facs = [np.asarray(a['data']) for a in out['factors']]
    assert facs[0][0] == pytest.approx(1.0, rel=1e-6)
    assert facs[1][0] == pytest.approx(0.5, rel=1e-2)


def test_best_match_multichannel_per_column_factors():
    """A 2-output-column set returns one factor per column."""
    f = np.linspace(1, 100, 200)
    # Reference: 1 column. Target: 2 columns scaled by 2 and 5.
    ref = _set(f, 40.0, 0.02, 1.0)
    c0 = _sdof_flat(f, 40.0, 0.02, 2.0)
    c1 = _sdof_flat(f, 40.0, 0.02, 5.0)
    two = np.empty(c0.size + c1.size)
    # Interleave two columns row-major: [re00,im00,re01,im01, re10,im10,...].
    G0 = c0[0::2] + 1j * c0[1::2]
    G1 = c1[0::2] + 1j * c1[1::2]
    G = np.stack([G0, G1], axis=1)          # (Nf, 2)
    two[0::2] = G.real.ravel()
    two[1::2] = G.imag.ravel()
    target = {'freq_axis': f, 'tf_data': two, 'n_tf': 2}
    out = glue.calc_best_match([ref, target], freq_range=[1.0, 100.0], set_ref=0, ch_ref=0)
    facs = [np.asarray(a['data']) for a in out['factors']]
    assert facs[1].shape == (2,)
    assert facs[1][0] == pytest.approx(0.5, rel=1e-3)
    assert facs[1][1] == pytest.approx(0.2, rel=1e-3)
