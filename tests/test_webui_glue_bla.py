# -*- coding: utf-8 -*-
"""Regression tests for the webui pyodide glue's BLA op (`calc_bla`, Task 6).

The browser engine loads ``webui/src/lib/worker/glue.py`` inside pyodide and
drives ``calc_bla`` with plain dicts / flat float64 arrays — the same
``{time_axis, time_data, n_channels, fs}`` ensemble contract
``calc_tf_averaged`` uses (see ``calc_bla``'s docstring). These tests import
that module directly under CPython and exercise ``calc_bla`` the way the
future webui ``bla`` store will, so a glue-level regression is caught fast
(no pyodide, no browser).
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

from pydvma import analysis, testdata  # noqa: E402  (after sys.path insert)


def _payload(td):
    """Flat ``{time_axis, time_data, n_channels, fs}`` payload for one
    capture, matching ``calc_tf_averaged``'s ensemble contract (the shape
    ``_time_data`` expects everywhere in glue.py)."""
    return {
        'time_axis': td.time_axis.astype(np.float64),
        'time_data': td.time_data.astype(np.float64).ravel(),
        'n_channels': int(td.time_data.shape[1]),
        'fs': float(td.settings.fs),
    }


def _vals(arr_dict):
    """Real values of a glue ``_arr`` marshal ({shape, data, complex}),
    reshaped back to its marshalled shape (the flat ``data`` buffer is
    row-major, matching ``_arr``'s ravel on the Python side)."""
    return np.asarray(arr_dict['data']).reshape(arr_dict['shape'])


def _complex_vals(arr_dict):
    """De-interleave a glue ``_arr`` complex marshal into a numpy array."""
    assert arr_dict['complex'] is True
    flat = np.asarray(arr_dict['data'], dtype=np.float64)
    z = flat[0::2] + 1j * flat[1::2]
    return z.reshape(arr_dict['shape'])


def _assert_json_plain(v, path='bla'):
    """Recursively assert ``v`` contains only strict-JSON-safe Python types
    (no numpy scalars/arrays) — what ``.dvma`` needs to store it verbatim."""
    if isinstance(v, dict):
        for k, val in v.items():
            assert isinstance(k, str), f'{path}: non-str key {k!r}'
            _assert_json_plain(val, f'{path}.{k}')
    elif isinstance(v, list):
        for i, x in enumerate(v):
            _assert_json_plain(x, f'{path}[{i}]')
    elif v is None or isinstance(v, (str, int, float, bool)):
        pass
    else:
        pytest.fail(f'{path}: non-JSON-plain value {v!r} of type {type(v)}')


# Small BLA run: M=2, n_exc=2, n_resp=1, N=256, P=2 — the minimum legal
# geometry (M>=2, P>=2) kept tiny for test speed. k1/k2 must stay within
# 1 <= k1 <= k2 <= (N-1)//2 = 127 (create_test_bla_captures' own defaults,
# k1=8/k2=200, assume the default N=2048 and would be invalid here).
_M, _N_EXC, _N_RESP, _N, _P = 2, 2, 1, 256, 2
_K1, _K2 = 8, 100


def _build_run():
    """Small synthetic BLA run: (time_data_list, run_spec, G_true, payloads)."""
    time_data_list, run_spec, G_true = testdata.create_test_bla_captures(
        M=_M, n_exc=_N_EXC, n_resp=_N_RESP, N=_N, P=_P, k1=_K1, k2=_K2)
    payloads = [_payload(td) for td in time_data_list]
    return time_data_list, run_spec, G_true, payloads


class TestCalcBla:
    def test_returns_one_entry_per_excitation_with_expected_shapes(self):
        _, run_spec, _, payloads = _build_run()
        out = glue.calc_bla(time_arrays=payloads, run_spec=run_spec)
        assert len(out) == _N_EXC
        n_k = _K2 - _K1 + 1
        for entry in out:
            for key in ('freq_axis', 'tf_data', 'coherence', 'bla_sigma_nl',
                        'bla_sigma_n', 'bla'):
                assert key in entry, f'calc_bla entry missing {key}'
            assert entry['coherence'] is None  # BLA carries no coherence
            freq = _vals(entry['freq_axis'])
            assert freq.shape == (n_k,)
            tf = _complex_vals(entry['tf_data'])
            assert tf.shape == (n_k, _N_RESP)
            sig_nl = _vals(entry['bla_sigma_nl'])
            sig_n = _vals(entry['bla_sigma_n'])
            assert sig_nl.shape == (n_k, _N_RESP)
            assert sig_n.shape == (n_k, _N_RESP)

    def test_sigma_arrays_are_real_and_nonnegative(self):
        _, run_spec, _, payloads = _build_run()
        out = glue.calc_bla(time_arrays=payloads, run_spec=run_spec)
        for entry in out:
            assert entry['bla_sigma_nl']['complex'] is False
            assert entry['bla_sigma_n']['complex'] is False
            assert np.all(_vals(entry['bla_sigma_nl']) >= 0)
            assert np.all(_vals(entry['bla_sigma_n']) >= 0)
            assert np.all(np.isfinite(_vals(entry['bla_sigma_nl'])))
            assert np.all(np.isfinite(_vals(entry['bla_sigma_n'])))

    def test_bla_meta_is_json_plain_and_carries_q(self):
        _, run_spec, _, payloads = _build_run()
        out = glue.calc_bla(time_arrays=payloads, run_spec=run_spec)
        seen_q = sorted(entry['bla']['q'] for entry in out)
        assert seen_q == list(range(_N_EXC))
        for entry in out:
            _assert_json_plain(entry['bla'])
            assert entry['bla']['excited_bins'] == list(range(_K1, _K2 + 1))
            assert entry['bla']['multisine']['M'] == _M
            assert entry['bla']['multisine']['n_exc'] == _N_EXC

    def test_matches_calling_analysis_calculate_bla_directly(self):
        time_data_list, run_spec, _, payloads = _build_run()
        out = glue.calc_bla(time_arrays=payloads, run_spec=run_spec)
        direct = analysis.calculate_bla(time_data_list, run_spec)
        assert len(out) == len(direct)
        for entry, tf in zip(out, direct):
            assert np.allclose(_complex_vals(entry['tf_data']), tf.tf_data,
                                rtol=1e-10, atol=1e-12)
            assert np.allclose(_vals(entry['freq_axis']), tf.freq_axis,
                                rtol=1e-10, atol=1e-12)
            assert np.allclose(_vals(entry['bla_sigma_nl']), tf.bla_sigma_nl,
                                rtol=1e-10, atol=1e-12)
            assert np.allclose(_vals(entry['bla_sigma_n']), tf.bla_sigma_n,
                                rtol=1e-10, atol=1e-12)


class TestCalcBlaErrors:
    def test_wrong_capture_count_raises_with_calculate_bla_message(self):
        _, run_spec, _, payloads = _build_run()
        with pytest.raises(ValueError, match='BLA run needs'):
            glue.calc_bla(time_arrays=payloads[:-1], run_spec=run_spec)

    def test_missing_calculate_bla_raises_clear_stale_wheel_message(self, monkeypatch):
        """A wheel predating `calculate_bla` must fail with an actionable
        message instead of an opaque AttributeError (the calc_sono /
        calc_damping_bands stale-wheel guard pattern)."""
        monkeypatch.delattr(glue.analysis, 'calculate_bla')
        with pytest.raises(ValueError, match='newer engine'):
            glue.calc_bla(time_arrays=[], run_spec={})
