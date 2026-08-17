# -*- coding: utf-8 -*-
"""Native engine host: frame codec, worker subprocess, /engine endpoint."""
import numpy as np
import pytest

from pydvma import engine_host


def test_frame_roundtrip_scalars_only():
    header = {'id': 1, 'op': 'calc_fft', 'payload': {'fs': 8000, 'window': None}}
    frame = engine_host.encode_frame(header)
    out = engine_host.decode_frame(frame)
    assert out == header


def test_frame_roundtrip_lifts_arrays_recursively():
    a = np.arange(6, dtype='<f8')
    header = {'id': 2, 'op': 'calc_tf_averaged',
              'payload': {'sets': [{'time_data': a, 'fs': 100.0}],
                          'blob': b'\x00\x01\x02'}}
    frame = engine_host.encode_frame(header)
    out = engine_host.decode_frame(frame)
    got = out['payload']['sets'][0]['time_data']
    assert isinstance(got, np.ndarray) and got.dtype == np.dtype('<f8')
    np.testing.assert_array_equal(got, a)
    assert out['payload']['sets'][0]['fs'] == 100.0
    assert out['payload']['blob'] == b'\x00\x01\x02'


def test_frame_rejects_non_f8_ndarray():
    with pytest.raises(TypeError):
        engine_host.encode_frame({'x': np.arange(3, dtype='int32')})
