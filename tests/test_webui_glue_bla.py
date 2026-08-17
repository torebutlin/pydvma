# -*- coding: utf-8 -*-
"""Regression tests for the webui pyodide glue's BLA op (``calc_bla``).

The browser engine loads ``webui/src/lib/worker/glue.py`` inside pyodide and
drives ``calc_bla`` from ``webui/src/lib/stores/bla.ts`` with the
``{time_axis, time_data, n_channels, fs}`` ensemble contract
``calc_tf_averaged`` uses (see ``calc_bla``'s docstring). These tests import
that module directly under CPython and exercise it the same way, so a
glue-level regression is caught fast (no pyodide, no browser).

Payload SHAPE matters as much as payload content here. Top-level kwargs are
converted by ``callKwargs``, but every value NESTED inside them crosses the
FFI as a ``JsProxy``: a plain-object proxy exposes its keys as ATTRIBUTES
only (no ``[...]``, no ``in``), and a Map-like proxy exposes only ``.get``.
Plain dicts alone would therefore test a shape the browser never sends, so
the run is replayed through attribute-only and Map-like fakes and the
results are required to be identical.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from pydvma import engine as glue

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
    (no numpy scalars/arrays) — what ``.dvma`` needs to store it verbatim.

    The leaf test is ``type(v) in ...``, NOT ``isinstance``: ``np.float64``
    subclasses ``float`` and ``np.bool_`` does not, but several numpy scalar
    types pass an ``isinstance`` check against their Python counterpart and
    would slip through — exactly the class of value ``_json_clean`` exists to
    strip (``json.dumps`` rejects them, so a `.dvma` save would fail long
    after the analysis returned).
    """
    if isinstance(v, dict):
        for k, val in v.items():
            assert type(k) is str, f'{path}: non-str key {k!r} ({type(k)})'
            _assert_json_plain(val, f'{path}.{k}')
    elif isinstance(v, list):
        for i, x in enumerate(v):
            _assert_json_plain(x, f'{path}[{i}]')
    elif v is None or type(v) in (str, bool, int, float):
        pass
    else:
        pytest.fail(f'{path}: non-JSON-plain value {v!r} of type {type(v)}')


def _as_obj(v):
    """Wrap dicts as ATTRIBUTE-ONLY objects, recursively — the CPython twin
    of a pyodide plain-object ``JsProxy``.

    A `SimpleNamespace` has no ``.get`` and no ``__getitem__``, so ``_get``
    must fall through to its ``getattr`` branch exactly as it does in the
    browser. Lists are mapped element-wise (a JS array proxy stays iterable);
    numpy arrays and scalars pass through untouched.
    """
    if isinstance(v, dict):
        return SimpleNamespace(**{k: _as_obj(x) for k, x in v.items()})
    if isinstance(v, list):
        return [_as_obj(x) for x in v]
    return v


class _MapLike:
    """A dict-shaped payload exposing ONLY ``.get`` — the CPython twin of a
    Map-like ``JsProxy`` (``_get``'s second branch). Deliberately offers no
    ``__getitem__``, no ``__contains__`` and no attribute access, so a glue
    path that reached for any of those would fail here."""

    def __init__(self, d):
        self._d = {k: _as_map(v) for k, v in d.items()}

    def get(self, k):
        return self._d.get(k)


def _as_map(v):
    """Recursive `_MapLike` wrapper (dicts → Map-like, lists mapped)."""
    if isinstance(v, dict):
        return _MapLike(v)
    if isinstance(v, list):
        return [_as_map(x) for x in v]
    return v


# Small BLA run: M=2, n_exc=2, n_resp=2, N=256, P=2 — the minimum legal
# geometry (M>=2, P>=2) kept tiny for test speed. k1/k2 must stay within
# 1 <= k1 <= k2 <= (N-1)//2 = 127 (create_test_bla_captures' own defaults,
# k1=8/k2=200, assume the default N=2048 and would be invalid here).
#
# TWO responses on purpose: with n_resp = 1 every marshalled array is
# (n_k, 1), so a row/column transposition in the `_arr` round-trip is
# invisible — the shape assertions pass either way and the values line up.
# The second response makes the (n_k, n_resp) layout load-bearing, and the
# two columns are genuinely different filters (`_bla_reference_filters`), so
# a swapped/broadcast column shows up as a value mismatch.
_M, _N_EXC, _N_RESP, _N, _P = 2, 2, 2, 256, 2
_K1, _K2 = 8, 100


def _build_run():
    """Small synthetic BLA run: (time_data_list, run_spec, G_true, payloads).

    ``G_true`` is the reference system's exact response at the excited bins,
    shape ``(n_k, n_resp, n_exc)`` — excitation ``q``'s glue entry must match
    ``G_true[:, :, q]``.
    """
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
            # The response columns must be DISTINCT curves: each response is a
            # different reference filter, so an accidental broadcast (or a
            # transposed reshape) would collapse them onto each other.
            assert not np.allclose(tf[:, 0], tf[:, 1])

    def test_recovers_the_reference_system_per_excitation(self):
        """The marshalled entry for excitation ``q`` is ``G_true[:, :, q]``.

        This is what pins the (n_k, n_resp) COLUMN ORDER through the flat
        `_arr` round-trip: the two responses are different filters, so a
        swapped pair or a transposed reshape fails here even though the
        shapes still match.
        """
        _, run_spec, G_true, payloads = _build_run()
        out = glue.calc_bla(time_arrays=payloads, run_spec=run_spec)
        for q, entry in enumerate(out):
            tf = _complex_vals(entry['tf_data'])
            # Tolerance ~6x the measured deviation of this fixed-seed run
            # (max |ΔG| ≈ 8e-4 from the synthetic output noise).
            assert np.allclose(tf, G_true[:, :, q], rtol=1e-2, atol=5e-3)

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


def _assert_same_entries(got, expected):
    """Two ``calc_bla`` returns are element-for-element identical."""
    assert len(got) == len(expected)
    for a, b in zip(got, expected):
        assert a['coherence'] is b['coherence'] is None
        for key in ('freq_axis', 'tf_data', 'bla_sigma_nl', 'bla_sigma_n'):
            assert a[key]['shape'] == b[key]['shape'], key
            assert a[key]['complex'] == b[key]['complex'], key
            assert np.array_equal(np.asarray(a[key]['data']),
                                  np.asarray(b[key]['data'])), key
        assert a['bla'] == b['bla']


class TestCalcBlaPayloadShapes:
    """The browser never sends plain dicts for NESTED values — it sends
    ``JsProxy`` objects. Both proxy flavours must reach the same result."""

    def test_attribute_only_payloads_match_plain_dicts(self):
        _, run_spec, _, payloads = _build_run()
        expected = glue.calc_bla(time_arrays=payloads, run_spec=run_spec)
        # `run_spec` AND every capture payload arrive as attribute-only
        # objects (the plain-object JsProxy shape): no `[...]`, no `.get`.
        out = glue.calc_bla(time_arrays=[_as_obj(p) for p in payloads],
                            run_spec=_as_obj(run_spec))
        _assert_same_entries(out, expected)

    def test_map_like_payloads_match_plain_dicts(self):
        _, run_spec, _, payloads = _build_run()
        expected = glue.calc_bla(time_arrays=payloads, run_spec=run_spec)
        out = glue.calc_bla(time_arrays=[_as_map(p) for p in payloads],
                            run_spec=_as_map(run_spec))
        _assert_same_entries(out, expected)

    def test_meta_stays_json_plain_through_a_proxy_shaped_spec(self):
        """`_bla_run_spec` normalises the proxy tree to plain Python BEFORE
        `calculate_bla` sees it, so the `bla` meta it attaches must be just as
        JSON-clean as on the dict path (a leaked proxy or numpy scalar here
        would only surface later, as a `.dvma` save failure)."""
        _, run_spec, _, payloads = _build_run()
        out = glue.calc_bla(time_arrays=[_as_obj(p) for p in payloads],
                            run_spec=_as_obj(run_spec))
        for entry in out:
            _assert_json_plain(entry['bla'])


class TestCalcBlaCommandedX:
    """Commanded-x: the analysis regenerates the excitation from the seed
    instead of reading measured input channels (`x_channels: None`)."""

    def _commanded(self, run_spec):
        spec = dict(run_spec)
        spec['x_mode'] = 'commanded'
        spec['x_channels'] = None
        return spec

    def test_commanded_spec_runs_and_matches_the_direct_call(self):
        time_data_list, run_spec, _, payloads = _build_run()
        spec = self._commanded(run_spec)
        out = glue.calc_bla(time_arrays=payloads, run_spec=spec)
        direct = analysis.calculate_bla(time_data_list, spec)
        assert len(out) == _N_EXC
        for entry, tf in zip(out, direct):
            assert np.allclose(_complex_vals(entry['tf_data']), tf.tf_data,
                                rtol=1e-10, atol=1e-12)
        # The mode is recorded in the meta; the x-channel list is None there.
        for entry in out:
            assert entry['bla']['x_mode'] == 'commanded'
            assert entry['bla']['x_channels'] is None
            _assert_json_plain(entry['bla'])

    def test_commanded_recovers_the_same_system_as_measured_x(self):
        """The synthetic captures record a NOISELESS excitation, so the two
        x sources describe the same input and must land on the same system —
        the check that the regenerated phase/scaling law really is the one
        `multisine_generator` played."""
        _, run_spec, G_true, payloads = _build_run()
        out = glue.calc_bla(time_arrays=payloads,
                            run_spec=self._commanded(run_spec))
        for q, entry in enumerate(out):
            assert np.allclose(_complex_vals(entry['tf_data']), G_true[:, :, q],
                                rtol=1e-2, atol=5e-3)

    def test_commanded_spec_survives_a_proxy_shaped_payload(self):
        """`_bla_run_spec`'s `not x_channels` guard has to read a None that
        arrived through a proxy (where a JS `null` is neither a dict key nor
        an empty list) — a wrong guard here would fall into the measured
        branch and raise about missing x_channels."""
        _, run_spec, _, payloads = _build_run()
        spec = self._commanded(run_spec)
        expected = glue.calc_bla(time_arrays=payloads, run_spec=spec)
        _assert_same_entries(
            glue.calc_bla(time_arrays=[_as_obj(p) for p in payloads],
                          run_spec=_as_obj(spec)),
            expected)
        _assert_same_entries(
            glue.calc_bla(time_arrays=[_as_map(p) for p in payloads],
                          run_spec=_as_map(spec)),
            expected)


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
