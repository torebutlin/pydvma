# -*- coding: utf-8 -*-
"""Native engine host: frame codec, worker subprocess, /engine endpoint."""
import json
import struct
import threading

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


def test_encode_frame_sanitises_non_finite_scalars_but_not_array_values():
    # Realistic producers: calc_damping's Qn -> inf when zeta clips to 0;
    # calc_fit's cost_before on a divergent seed. NaN/Infinity are not
    # valid JSON -- JS JSON.parse on the other end would reject a bare
    # token -- so scalar floats must cross as null, while an f8 blob (raw
    # IEEE-754 bytes, never touched by json.dumps) carries NaN/Inf as-is.
    header = {'x': float('nan'), 'y': float('inf'), 'z': float('-inf'),
              'a': np.array([np.nan, 1.0], dtype='<f8'),
              'fits': [{'Qn': float('inf')}], 'w': np.float64('inf')}
    frame = engine_host.encode_frame(header)
    out = engine_host.decode_frame(frame)
    assert out['x'] is None
    assert out['y'] is None
    assert out['z'] is None
    assert isinstance(out['a'], np.ndarray)
    assert np.isnan(out['a'][0])
    assert out['a'][1] == 1.0
    assert out['fits'][0]['Qn'] is None      # nested non-finite
    assert out['w'] is None                  # numpy scalar, not bare Python float


def test_decode_frame_raises_on_truncated_frame():
    header = {'sets': [{'a': np.arange(4, dtype='<f8'),
                         'b': np.arange(4, dtype='<f8')}]}
    frame = engine_host.encode_frame(header)
    # Chop exactly one f8 element's worth of bytes off the tail -- still
    # 8-aligned, so a naive slice-and-frombuffer decode would silently
    # hand back a short array instead of raising.
    truncated = frame[:-8]
    with pytest.raises(ValueError, match='truncated'):
        engine_host.decode_frame(truncated)


def test_decode_frame_raises_on_unknown_blob_kind():
    header = {'x': {'__bin__': 0, 'kind': 'weird', 'len': 3}}
    head = json.dumps(header).encode('utf-8')
    frame = struct.pack('<I', len(head)) + head + b'abc'
    with pytest.raises(ValueError, match='unknown blob kind'):
        engine_host.decode_frame(frame)


def test_decode_frame_raises_when_f8_len_given_in_elements_not_bytes():
    # Canonical mirror bug: a 6-element (48-byte) f8 array whose
    # placeholder declares len=6 (element count) instead of len=48 (byte
    # count). The blob region present (48 bytes) then disagrees with what
    # the header declares (6 bytes) -- caught by the exact-fit check
    # before any per-blob kind handling runs.
    arr = np.arange(6, dtype='<f8')
    blob = arr.tobytes()
    header = {'x': {'__bin__': 0, 'kind': 'f8', 'len': 6}}
    head = json.dumps(header).encode('utf-8')
    frame = struct.pack('<I', len(head)) + head + blob
    with pytest.raises(ValueError):
        engine_host.decode_frame(frame)


def test_decode_frame_raises_when_f8_blob_len_not_multiple_of_8():
    # The blob region itself fits exactly (so the exact-fit check is
    # satisfied), but the declared len isn't a whole number of float64
    # elements -- must be rejected before frombuffer, not truncate silently.
    header = {'x': {'__bin__': 0, 'kind': 'f8', 'len': 7}}
    head = json.dumps(header).encode('utf-8')
    frame = struct.pack('<I', len(head)) + head + b'1234567'
    with pytest.raises(ValueError, match='multiple of 8'):
        engine_host.decode_frame(frame)


def test_encode_frame_exact_bytes_single_array():
    # Pins the byte-for-byte wire format so the JS mirror (Task 6) can be
    # written and checked against this test's expectation directly. A
    # single-key header keeps JSON key order (and therefore the exact
    # bytes) deterministic.
    arr = np.array([1.0, 2.0], dtype='<f8')
    frame = engine_host.encode_frame({'x': arr})
    blob = arr.tobytes()
    expected_head = json.dumps(
        {'x': {'__bin__': 0, 'kind': 'f8', 'len': len(blob)}}).encode('utf-8')
    expected = struct.pack('<I', len(expected_head)) + expected_head + blob
    assert frame == expected


def test_encode_frame_exact_bytes_bytes_kind():
    # Pins the 'bytes' kind literal -- renaming it in the codec breaks
    # this test even though the f8-only test above wouldn't notice.
    frame = engine_host.encode_frame({'b': b'ab'})
    expected_head = json.dumps(
        {'b': {'__bin__': 0, 'kind': 'bytes', 'len': 2}}).encode('utf-8')
    expected = struct.pack('<I', len(expected_head)) + expected_head + b'ab'
    assert frame == expected


def test_encode_frame_lays_blobs_in_ascending_index_order():
    a = np.array([1.0], dtype='<f8')
    b = np.array([2.0, 2.0], dtype='<f8')
    c = np.array([3.0, 3.0, 3.0], dtype='<f8')
    frame = engine_host.encode_frame({'a': a, 'b': b, 'c': c})
    (n,) = struct.unpack_from('<I', frame, 0)
    tail = frame[4 + n:]
    assert tail == a.tobytes() + b.tobytes() + c.tobytes()


def test_frame_roundtrip_empty_blobs_both_kinds():
    header = {'a': np.array([], dtype='<f8'), 'b': b''}
    frame = engine_host.encode_frame(header)
    out = engine_host.decode_frame(frame)
    assert isinstance(out['a'], np.ndarray)
    assert out['a'].size == 0
    assert out['a'].dtype == np.dtype('<f8')
    assert out['b'] == b''


# --- worker subprocess -------------------------------------------------------

def _mk_time(n=256, fs=1000.0, ch=2):
    t = np.arange(n) / fs
    d = np.sin(2 * np.pi * 50 * t)
    return {'time_axis': t, 'time_data': np.column_stack([d] * ch).ravel(),
            'n_channels': ch, 'fs': fs, 'window': None}


def test_worker_answers_calc_fft():
    w = engine_host.EngineWorker()
    try:
        kind, rid, ok, result = w.request(7, 'calc_fft', _mk_time())
        assert (kind, rid, ok) == ('done', 7, True)
        assert result['freq_data']['complex'] is True
        assert isinstance(result['freq_data']['data'], np.ndarray)
    finally:
        w.close()


def test_worker_reports_error_not_crash():
    w = engine_host.EngineWorker()
    try:
        kind, rid, ok, err = w.request(1, 'no_such_op', {})
        assert (kind, ok) == ('done', False)
        assert 'no_such_op' in err
        # Worker survives a bad op:
        kind, rid, ok, _ = w.request(2, 'calc_fft', _mk_time())
        assert ok is True
    finally:
        w.close()


def test_worker_streams_progress_for_cwt_sono():
    w = engine_host.EngineWorker()
    frames = []
    try:
        payload = _mk_time(n=4096)
        payload.pop('window')
        payload.update(ch=0, nperseg=256, noverlap=128, method='cwt')
        kind, rid, ok, _ = w.request(3, 'calc_sono', payload,
                                     on_progress=lambda d, t: frames.append((d, t)))
        assert ok is True
        assert frames and frames[-1][0] == frames[-1][1]  # terminal frame
    finally:
        w.close()


def test_worker_kill_and_respawn():
    w = engine_host.EngineWorker()
    try:
        w.kill()
        kind, rid, ok, _ = w.request(4, 'calc_fft', _mk_time())
        assert ok is True  # respawned transparently
    finally:
        w.close()


def _cwt_payload(n=4096):
    payload = _mk_time(n=n)
    payload.pop('window')
    payload.update(ch=0, nperseg=256, noverlap=128, method='cwt')
    return payload


def test_worker_cancel_is_cooperative_and_worker_stays_usable():
    w = engine_host.EngineWorker()
    started = threading.Event()
    result = {}

    def run():
        result['reply'] = w.request(9, 'calc_sono', _cwt_payload(),
                                    on_progress=lambda d, t: started.set())

    try:
        t = threading.Thread(target=run)
        t.start()
        assert started.wait(timeout=10.0), 'no progress frame arrived before cancel'
        w.cancel()
        t.join(timeout=10.0)
        assert not t.is_alive()
        assert result['reply'] == ('done', 9, False, 'cancelled')
        # cancel_ev.clear() at the top of the next request -- a cancelled op
        # must not poison the worker for the request that follows it.
        kind, rid, ok, _ = w.request(11, 'calc_fft', _mk_time())
        assert ok is True
    finally:
        w.close()


def test_worker_kill_mid_request_returns_clean_reply_and_respawns():
    w = engine_host.EngineWorker()
    started = threading.Event()
    result = {}

    def run():
        result['reply'] = w.request(10, 'calc_sono', _cwt_payload(),
                                    on_progress=lambda d, t: started.set())

    try:
        t = threading.Thread(target=run)
        t.start()
        assert started.wait(timeout=10.0), 'no progress frame arrived before kill'
        w.kill()
        t.join(timeout=10.0)
        assert not t.is_alive()
        kind, rid, ok, msg = result['reply']
        assert (kind, rid, ok) == ('done', 10, False)
        assert 'engine worker died' in msg
        # respawns transparently:
        kind, rid, ok, _ = w.request(12, 'calc_fft', _mk_time())
        assert ok is True
    finally:
        w.close()
