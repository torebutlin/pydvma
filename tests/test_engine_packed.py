"""`engine._call_packed`: the browser worker's payload as JSON text plus raw
array bytes (``webui/src/lib/worker/pack.ts``).

Safari 27.2's JIT corrupts JS numbers that pyodide converts into Python one by
one (a double arrives as the low 32 bits of its bit pattern), so the worker no
longer lets any JS number cross that way. These tests pin the Python half:
the placeholders unpack to the right arrays and values, and an op called
through the packed path returns exactly what a direct call returns.
"""
import json
import math

import numpy as np
import pytest

from pydvma import engine


class _JsBytes:
    """Stands in for a pyodide JsProxy of a Uint8Array: only `to_bytes`."""

    def __init__(self, b):
        self._b = bytes(b)

    def to_bytes(self):
        return self._b


def _pack(payload):
    """A Python twin of `packPayload`: numpy arrays -> placeholders + bytes."""
    bufs = []

    def walk(v):
        if isinstance(v, np.ndarray):
            a = np.ascontiguousarray(v)
            bufs.append(_JsBytes(a.tobytes()))
            return {'__pydvma_buf__': len(bufs) - 1, 'dtype': a.dtype.str, 'length': a.size}
        if isinstance(v, float) and not math.isfinite(v):
            return {'__pydvma_num__': 'nan' if math.isnan(v) else ('inf' if v > 0 else '-inf')}
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [walk(x) for x in v]
        return v

    return json.dumps(walk(payload)), bufs


def test_placeholders_unpack_to_writable_arrays_of_their_dtype():
    data = np.array([246.82, 0.0011, 5.0, -0.25])
    text, bufs = _pack({'x': data, 'n': np.arange(3, dtype=np.int32)})
    out = engine._unpack_payload(json.loads(text), bufs)
    np.testing.assert_array_equal(out['x'], data)
    assert out['x'].dtype == np.float64 and out['n'].dtype == np.int32
    out['x'][0] = 1.0                       # writable, as np.asarray gave
    # A plain bytes-like buffer works too (the CPython tests, a memoryview).
    out2 = engine._unpack_payload(json.loads(text), [memoryview(data.tobytes()), b'\0' * 12])
    np.testing.assert_array_equal(out2['x'], data)


def test_non_finite_numbers_nested_values_and_nulls_survive():
    text, bufs = _pack({'a': float('nan'), 'b': [1, float('-inf')], 'c': None,
                        'd': {'e': 'x', 'f': True}})
    out = engine._unpack_payload(json.loads(text), bufs)
    assert math.isnan(out['a']) and out['b'] == [1, float('-inf')]
    assert out['c'] is None and out['d'] == {'e': 'x', 'f': True}


def test_a_buffer_of_the_wrong_size_is_refused():
    with pytest.raises(ValueError, match='holds 8 bytes'):
        engine._unpack_payload({'__pydvma_buf__': 0, 'dtype': '<f8', 'length': 2},
                               [_JsBytes(b'\0' * 8)])


def test_only_public_engine_functions_can_be_called():
    for name in ('_unpack_payload', 'np', 'json', 'no_such_op'):
        with pytest.raises(AttributeError, match='not an engine op'):
            engine._call_packed(name, '{}', [])


def _two_mode_tf(f):
    w = 2 * np.pi * f
    G = np.zeros(f.size, dtype=complex)
    for fn, zn, an in ((250.0, 0.002, 1e3), (400.0, 0.002, -1e3)):
        wn = 2 * np.pi * fn
        G += an / (wn ** 2 + 2j * zn * wn * w - w ** 2)
    return G * (1j * w) ** 2


def test_a_packed_fit_matches_a_direct_call_exactly():
    f = np.arange(0.0, 1000.0, 0.25)
    G = _two_mode_tf(f)
    flat = np.empty(G.size * 2)
    flat[0::2], flat[1::2] = G.real, G.imag
    payload = {'freq_axis': f, 'tf_data': flat, 'n_tf': 1, 'n_channels': 2, 'fs': 2000.0,
               'freq_range': [230.0, 270.0], 'measurement_type': 'acc', 'action': 'fit',
               'n_modes': 1}
    direct = engine.calc_fit(**payload)
    text, bufs = _pack(payload)
    packed = engine._call_packed('calc_fit', text, bufs)
    np.testing.assert_array_equal(np.asarray(packed['M']['data']), np.asarray(direct['M']['data']))
    np.testing.assert_array_equal(np.asarray(packed['global_tf_data']['data']),
                                  np.asarray(direct['global_tf_data']['data']))
    assert abs(packed['fn']['data'][0] - 250.0) < 0.01


def test_a_packed_reference_tone_calibration_matches_a_direct_call():
    fs = 48000.0
    t = np.arange(int(fs)) / fs
    x = 0.0335 * np.sqrt(2) * np.sin(2 * np.pi * 1000 * t)
    payload = {'time_axis': t, 'time_data': x, 'n_channels': 1, 'fs': fs, 'channel': 0,
               'ref_rms': 1.0, 'freq': 1000.0, 'vmax': 1.0}
    direct = engine.reference_tone_calibration(**payload)
    text, bufs = _pack(payload)
    packed = engine._call_packed('reference_tone_calibration', text, bufs)
    assert packed == direct
    assert abs(direct['sensitivity'] - 0.0335) < 1e-4 and direct['warnings'] == []
    json.dumps(direct)
