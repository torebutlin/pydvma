"""Regression tests for the webui pyodide glue's modal-fit op.

The browser engine loads ``webui/src/lib/worker/glue.py`` inside pyodide and
drives it with plain dicts / flat float64 arrays.  These tests import that
same module directly under CPython and exercise ``calc_fit`` the way the JS
``actions.calcFit`` does, so a glue-level regression is caught fast (no
pyodide, no browser).

Round-4 bug 2: pressing **Reject** right after a fit raised
``IndexError: index 0 is out of bounds for axis 0 with size 0`` at
``glue.py`` ~line 410.  Root cause is pydvma's ``ModalData.delete_mode``
calling ``modal.unpack_matrix`` on the now-empty matrix when the LAST mode
is removed.  The glue guards this (``_delete_modes`` returns an empty model
instead of invoking the crashing path), so rejecting the last mode empties
the model cleanly rather than raising.
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


def _sdof_tf_flat(f, fn, zeta):
    """Interleaved-complex [re,im,...] accelerance FRF of one SDOF resonance."""
    w = 2 * np.pi * f
    wn = 2 * np.pi * fn
    H = ((-w ** 2) / (wn ** 2 - w ** 2 + 2j * zeta * wn * w)).reshape(-1, 1)
    flat = np.empty(H.size * 2)
    flat[0::2] = H.real.ravel()
    flat[1::2] = H.imag.ravel()
    return flat


def _common(flat, f, fs):
    return dict(freq_axis=f, tf_data=flat, n_tf=1, ch_in=0,
                n_channels=2, fs=fs, measurement_type='acc')


def test_reject_last_mode_empties_without_raising():
    """Fit one mode, then reject it — must not raise, and the model empties."""
    fs = 2000.0
    f = np.linspace(0, 1000, 2001)
    flat = _sdof_tf_flat(f, 200.0, 0.02)
    common = _common(flat, f, fs)

    fit = glue.calc_fit(**common, freq_range=[150.0, 250.0], action='fit', n_modes=1)
    assert np.asarray(fit['fn']['data']).size == 1        # one mode fitted
    assert fit['M']['shape'][0] == 1

    # Reject the only mode over the same window: the crash path.
    rej = glue.calc_fit(**common, M=fit['M'], freq_range=[150.0, 250.0], action='reject')
    assert np.asarray(rej['fn']['data']).size == 0        # model emptied
    assert rej['M']['shape'][0] == 0                      # shape (0, 0) -> store clears chip
    # No overlays remain once the last mode is gone.
    assert np.asarray(rej['global_freq_axis']['data']).size == 0
    assert np.asarray(rej['recon_freq_axis']['data']).size == 0


def test_reject_one_of_two_modes_keeps_the_other():
    """Partial delete still works: rejecting one mode keeps the survivor."""
    fs = 2000.0
    f = np.linspace(0, 1000, 2001)
    w = 2 * np.pi * f
    H = ((-w ** 2) / ((2 * np.pi * 200) ** 2 - w ** 2 + 2j * 0.02 * (2 * np.pi * 200) * w)
         + (-w ** 2) / ((2 * np.pi * 400) ** 2 - w ** 2 + 2j * 0.02 * (2 * np.pi * 400) * w)
         ).reshape(-1, 1)
    flat = np.empty(H.size * 2)
    flat[0::2] = H.real.ravel()
    flat[1::2] = H.imag.ravel()
    common = _common(flat, f, fs)

    a = glue.calc_fit(**common, freq_range=[150.0, 250.0], action='fit', n_modes=1)
    b = glue.calc_fit(**common, M=a['M'], freq_range=[350.0, 450.0], action='fit', n_modes=1)
    assert np.asarray(b['fn']['data']).size == 2

    # Reject only the ~200 Hz mode; the ~400 Hz mode must survive.
    d = glue.calc_fit(**common, M=b['M'], freq_range=[150.0, 250.0], action='reject')
    surviving = np.asarray(d['fn']['data'])
    assert surviving.size == 1
    assert abs(surviving[0] - 400.0) < 5.0
    assert d['M']['shape'][0] == 1


def test_refit_window_covering_all_modes_does_not_crash():
    """A re-fit whose window covers every existing mode replaces them all
    (the fit branch's delete step also emptied the matrix mid-op)."""
    fs = 2000.0
    f = np.linspace(0, 1000, 2001)
    flat = _sdof_tf_flat(f, 200.0, 0.02)
    common = _common(flat, f, fs)

    a = glue.calc_fit(**common, freq_range=[150.0, 250.0], action='fit', n_modes=1)
    # Re-fit the SAME window: the existing mode is deleted (emptying M) then
    # the fresh mode is added — must not raise, ends with exactly one mode.
    b = glue.calc_fit(**common, M=a['M'], freq_range=[150.0, 250.0], action='fit', n_modes=1)
    assert np.asarray(b['fn']['data']).size == 1
    assert b['M']['shape'][0] == 1


def _sdof_tf_multicol(f, fn, zeta, amps):
    """Interleaved-complex [re,im,...] accelerance FRF, one column per amplitude
    in ``amps`` (same resonance, per-column scale) — an orphan-shaped multi-TF."""
    w = 2 * np.pi * f
    wn = 2 * np.pi * fn
    base = (-w ** 2) / (wn ** 2 - w ** 2 + 2j * zeta * wn * w)
    G = np.column_stack([base * a for a in amps])
    flat = np.empty(G.size * 2)
    flat[0::2] = G.ravel().real
    flat[1::2] = G.ravel().imag
    return flat


def test_orphan_tf_fit_without_ch_in_does_not_raise():
    """Round-6 bug 1: fitting an ORPHAN TF (JW `.mat`, no measured input) sends
    NO ``ch_in`` — the JS `chIn=null` display convention. The engine must apply
    its ``ch_in=None`` default instead of raising
    ``TypeError: missing 'ch_in'`` (the crash Tore saw on Fit 1 / Fit 2)."""
    fs = 2000.0
    f = np.linspace(0, 1000, 2001)
    flat = _sdof_tf_multicol(f, 200.0, 0.02, [1.0, 0.8, 1.3])   # 3 orphan columns
    # NOTE: ch_in deliberately OMITTED (mirrors actions.calcFit for chIn===null).
    fit = glue.calc_fit(freq_axis=f, tf_data=flat, n_tf=3, n_channels=3, fs=fs,
                        measurement_type='acc', freq_range=[150.0, 250.0],
                        action='fit', n_modes=1)
    assert np.asarray(fit['fn']['data']).size == 1
    assert abs(np.asarray(fit['fn']['data'])[0] - 200.0) < 2.0
    # M carries all 3 orphan columns: shape[1] == 2 + 4*3.
    assert fit['M']['shape'][1] == 2 + 4 * 3
    # One set → one slice; its recon columns match the orphan's 3 lines 1:1.
    assert len(fit['slices']) == 1
    assert fit['slices'][0]['global_tf_data']['shape'][1] == 3
    assert fit['recon_tf_data']['shape'][1] == 3


def test_shared_pole_multi_set_fit_and_slices():
    """Item 7: a joint fit over a LIST of per-set TF payloads shares ONE fn/zn
    across every set (per-column amplitudes), and returns per-set recon slices.
    Mirrors Qt's `fit_mode` passing the whole `tf_data_list`."""
    fs = 2000.0
    f = np.linspace(0, 1000, 2001)
    fn, zeta = 300.0, 0.015
    # Three sets: one has 2 TF columns, the others 1 — total 4 joint columns.
    sets = [
        dict(freq_axis=f, tf_data=_sdof_tf_multicol(f, fn, zeta, [1.0, 0.6]),
             n_tf=2, ch_in=None, n_channels=2, fs=fs),
        dict(freq_axis=f, tf_data=_sdof_tf_multicol(f, fn, zeta, [1.4]),
             n_tf=1, ch_in=0, n_channels=2, fs=fs),
        dict(freq_axis=f, tf_data=_sdof_tf_multicol(f, fn, zeta, [0.9]),
             n_tf=1, ch_in=None, n_channels=1, fs=fs),
    ]
    fit = glue.calc_fit(sets=sets, measurement_type='acc',
                        freq_range=[250.0, 350.0], action='fit', n_modes=1)
    # ONE shared mode; its column count is the TOTAL across sets (2+1+1 = 4).
    assert np.asarray(fit['fn']['data']).size == 1
    assert abs(np.asarray(fit['fn']['data'])[0] - fn) < 2.0
    assert fit['M']['shape'][1] == 2 + 4 * 4
    # One slice per set, in order, each carrying only ITS columns.
    assert len(fit['slices']) == 3
    assert [s['n_cols'] for s in fit['slices']] == [2, 1, 1]
    assert fit['slices'][0]['global_tf_data']['shape'][1] == 2
    assert fit['slices'][1]['global_tf_data']['shape'][1] == 1
    # Top-level backward-compat = first set's block.
    assert fit['global_tf_data']['shape'][1] == 2

    # Refine the joint model — one least-squares over all 4 columns.
    ref = glue.calc_fit(sets=sets, M=fit['M'], measurement_type='acc', action='refine')
    assert 'converged' in ref
    assert np.asarray(ref['fn']['data']).size == 1
    assert abs(np.asarray(ref['fn']['data'])[0] - fn) < 2.0

    # Reject over the mode's window clears the shared model on every set.
    rej = glue.calc_fit(sets=sets, M=fit['M'], measurement_type='acc',
                        freq_range=[250.0, 350.0], action='reject')
    assert np.asarray(rej['fn']['data']).size == 0
    assert all(s['global_tf_data']['shape'][0] == 0 for s in rej['slices'])


def test_shared_pole_two_modes_across_sets():
    """A two-mode shared-pole fit: both modes land, and every set's recon
    slice reflects the whole (2-mode) model."""
    fs = 2000.0
    f = np.linspace(0, 1000, 2001)
    w = 2 * np.pi * f
    def two_mode(scale):
        G = (scale * (-w ** 2) / ((2 * np.pi * 200) ** 2 - w ** 2 + 2j * 0.02 * (2 * np.pi * 200) * w)
             + scale * (-w ** 2) / ((2 * np.pi * 500) ** 2 - w ** 2 + 2j * 0.02 * (2 * np.pi * 500) * w))
        flat = np.empty(G.size * 2)
        flat[0::2] = G.real
        flat[1::2] = G.imag
        return flat
    sets = [dict(freq_axis=f, tf_data=two_mode(1.0), n_tf=1, ch_in=None, n_channels=1, fs=fs),
            dict(freq_axis=f, tf_data=two_mode(0.7), n_tf=1, ch_in=None, n_channels=1, fs=fs)]
    fit = glue.calc_fit(sets=sets, measurement_type='acc',
                        freq_range=[100.0, 600.0], action='fit', n_modes=2)
    fns = np.sort(np.asarray(fit['fn']['data']))
    assert fns.size == 2
    assert abs(fns[0] - 200.0) < 10.0 and abs(fns[1] - 500.0) < 10.0
    assert len(fit['slices']) == 2
    assert all(s['n_cols'] == 1 for s in fit['slices'])
