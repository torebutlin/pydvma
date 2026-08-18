# -*- coding: utf-8 -*-
"""Native engine host: frame codec, worker subprocess, /engine endpoint."""
import asyncio
import functools
import json
import logging
import struct
import threading
import time

import numpy as np
import pytest
from websockets.asyncio.client import connect

from pydvma import engine_host
from pydvma import serve as serve_mod
from pydvma.journal import SessionJournal


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


# --- child resource-limit configuration --------------------------------------

def test_configure_child_limits_raises_cwt_ceiling_on_64bit():
    """`_worker_main` calls this first, in the CHILD process only -- the
    parent (and this test, running in the pytest process) never allocates a
    CWT image, so it is safe to call directly here and just restore the
    module constant afterwards.

    This machine's `sys.maxsize` (any CPython running this test suite) is
    64-bit, so the raise must always fire in CI/dev; the `sys.maxsize >
    2**32` guard inside `_configure_child_limits` itself is what would skip
    it on a 32-bit interpreter (not reachable here, not worth mocking --
    the wasm32-only path is exercised for real via the pyodide worker
    instead).
    """
    from pydvma import analysis
    original = analysis.CWT_MAX_IMAGE_BYTES
    try:
        engine_host._configure_child_limits()
        assert analysis.CWT_MAX_IMAGE_BYTES == 8 * 1024 ** 3
    finally:
        analysis.CWT_MAX_IMAGE_BYTES = original


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


# --- /engine websocket endpoint ---------------------------------------------

#: Set by `_isolated_session_dir` for the duration of each test; read by
#: `_start_server` as its `session_dir` default -- see that fixture's
#: docstring for why this matters (this module's own copy of the same
#: isolation `tests/test_serve_protocol.py` uses).
_TEST_SESSION_DIR = None


@pytest.fixture(autouse=True)
def _isolated_session_dir(tmp_path_factory):
    """Give every server ``_start_server`` spawns in this test its own
    throwaway ``session_dir``, so ``BridgeServer.__init__``'s startup
    scan never touches the real system temp dir.

    Without this, every one of this module's ~8 ``_start_server`` call
    sites constructs a real ``BridgeServer`` with the real-tempdir
    default: each run would scan a developer's actual temp dir, fire a
    liveness probe at whatever ports its ``pydvma-session-*.dvma``
    files name, and could PRUNE (delete) real files older than 7 days
    -- see ``pydvma.serve._adopt_previous_session``. One fresh
    directory per test function makes all of that impossible; combined
    with ``recover=False`` below (this module never exercises recovery
    itself), the startup scan does not even run.
    """
    global _TEST_SESSION_DIR
    _TEST_SESSION_DIR = tmp_path_factory.mktemp('sessions')
    yield
    _TEST_SESSION_DIR = None


async def _start_server(**kwargs):
    kwargs.setdefault('default_driver', 'mock')
    kwargs.setdefault('session_dir', _TEST_SESSION_DIR)
    # This module never exercises startup recovery -- skip the scan
    # entirely rather than merely pointing it at an (empty) scratch dir.
    kwargs.setdefault('recover', False)
    server = serve_mod.BridgeServer(host='127.0.0.1', port=0, **kwargs)
    task = asyncio.create_task(server.run())
    for _ in range(500):
        if server.sockets:
            break
        await asyncio.sleep(0.005)
    port = next(iter(server.sockets)).getsockname()[1]
    return server, task, port


async def _stop_server(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def run_async(coro_fn):
    asyncio.run(coro_fn())


async def _start_engine_server(journal=None):
    """Serve ``handle_connection`` directly on an ephemeral port, no
    :class:`~pydvma.serve.BridgeServer` involved.

    Lets the journal-ops tests pass an explicit
    :class:`~pydvma.journal.SessionJournal` (or exercise the no-journal
    default) straight into ``handle_connection`` without standing up a
    full ``BridgeServer`` and its bridge-protocol machinery -- a bare,
    single-purpose harness for exercising the ``/engine`` endpoint in
    isolation. (``BridgeServer`` itself owns and wires through its own
    journal -- see ``tests/test_serve_protocol.py``'s live-server
    journal tests for that path.)
    """
    from websockets.asyncio.server import serve
    handler = functools.partial(engine_host.handle_connection, journal=journal)
    server = await serve(handler, '127.0.0.1', 0)
    port = next(iter(server.sockets)).getsockname()[1]
    return server, port


async def _stop_engine_server(server):
    server.close()
    await server.wait_closed()


async def _recv(ws, timeout=5.0):
    """``ws.recv()`` bounded by a timeout -- a regression in the journal
    ops (e.g. a reply or push frame that never arrives) must fail this
    test promptly, not hang CI forever.
    """
    return await asyncio.wait_for(ws.recv(), timeout)


def test_engine_endpoint_greets_and_answers_calc_fft():
    async def scenario():
        _s, task, port = await _start_server()
        try:
            async with connect('ws://127.0.0.1:%d/engine' % port,
                               max_size=None) as ws:
                greeting = json.loads(await ws.recv())
                assert greeting['type'] == 'engine_ready'
                assert greeting['v'] == engine_host.ENGINE_PROTOCOL_VERSION
                await ws.send(engine_host.encode_frame(
                    {'id': 1, 'op': 'calc_fft', 'payload': _mk_time()}))
                raw = await ws.recv()
                assert isinstance(raw, (bytes, bytearray))
                reply = engine_host.decode_frame(raw)
                assert reply['id'] == 1 and reply['ok'] is True
                fd = reply['result']['freq_data']
                assert fd['complex'] is True
                assert isinstance(fd['data'], np.ndarray) and fd['data'].size > 0
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_engine_endpoint_error_reply_keeps_connection():
    async def scenario():
        _s, task, port = await _start_server()
        try:
            async with connect('ws://127.0.0.1:%d/engine' % port,
                               max_size=None) as ws:
                await ws.recv()  # greeting
                await ws.send(engine_host.encode_frame(
                    {'id': 5, 'op': 'nope', 'payload': {}}))
                reply = engine_host.decode_frame(await ws.recv())
                assert reply['ok'] is False and 'nope' in reply['error']
                await ws.send(engine_host.encode_frame(
                    {'id': 6, 'op': 'calc_fft', 'payload': _mk_time()}))
                assert engine_host.decode_frame(await ws.recv())['ok'] is True
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_engine_endpoint_streams_progress_frames():
    async def scenario():
        _s, task, port = await _start_server()
        try:
            async with connect('ws://127.0.0.1:%d/engine' % port,
                               max_size=None) as ws:
                await ws.recv()  # greeting
                payload = _mk_time(n=4096)
                payload.pop('window')
                payload.update(ch=0, nperseg=256, noverlap=128, method='cwt')
                await ws.send(engine_host.encode_frame(
                    {'id': 2, 'op': 'calc_sono', 'payload': payload}))
                frames = []
                while True:
                    raw = await ws.recv()
                    if isinstance(raw, (bytes, bytearray)):
                        reply = engine_host.decode_frame(raw)
                        break
                    msg = json.loads(raw)
                    if msg.get('type') == 'progress':
                        frames.append((msg['callId'], msg['done'], msg['total']))
                assert reply['ok'] is True
                assert frames and all(c == 2 for c, _d, _t in frames)
                assert frames[-1][1] == frames[-1][2]  # terminal frame passed through
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_engine_endpoint_malformed_frame_gets_error_text_not_disconnect():
    async def scenario():
        _s, task, port = await _start_server()
        try:
            async with connect('ws://127.0.0.1:%d/engine' % port,
                               max_size=None) as ws:
                await ws.recv()  # greeting
                await ws.send(b'\xff\xff\xff\xff garbage')
                msg = json.loads(await ws.recv())
                assert msg['type'] == 'error'
                # Connection survives:
                await ws.send(engine_host.encode_frame(
                    {'id': 3, 'op': 'calc_fft', 'payload': _mk_time()}))
                assert engine_host.decode_frame(await ws.recv())['ok'] is True
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_bridge_ws_still_works_alongside_engine():
    async def scenario():
        _s, task, port = await _start_server()
        try:
            async with connect('ws://127.0.0.1:%d/ws' % port) as ws:
                await ws.send(json.dumps({'type': 'hello'}))
                cap = json.loads(await ws.recv())
                assert cap['type'] == 'capabilities'
                assert cap['engine'] == {
                    'v': engine_host.ENGINE_PROTOCOL_VERSION,
                    'pydvma': serve_mod.datastructure.VERSION,
                    'journal': True,
                }
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_engine_endpoint_client_close_mid_op_is_a_clean_stop(caplog):
    # Reproduces the canonical Stop / tab-close during a long CWT calc:
    # the client drops the socket while an op is still running in the
    # worker. The reply (and any further progress frames) then try to
    # send on an already-closed socket -- that must be treated as the
    # client's Stop, not an unhandled error that websockets logs as
    # "connection handler failed".
    async def scenario():
        _s, task, port = await _start_server()
        try:
            async with connect('ws://127.0.0.1:%d/engine' % port,
                               max_size=None) as ws:
                await ws.recv()  # greeting
                await ws.send(engine_host.encode_frame(
                    {'id': 9, 'op': 'calc_sono', 'payload': _cwt_payload()}))
                raw = await ws.recv()
                assert not isinstance(raw, (bytes, bytearray))  # a progress frame
            # `async with` exit above closes the socket while the op is
            # still running in the worker subprocess.

            # Give the in-flight op time to finish and attempt its reply
            # (and any further progress frames) against the closed socket.
            await asyncio.sleep(0.5)

            # The server process must have survived cleanly and be ready
            # to serve a fresh connection:
            async with connect('ws://127.0.0.1:%d/engine' % port,
                               max_size=None) as ws2:
                await ws2.recv()  # greeting
                await ws2.send(engine_host.encode_frame(
                    {'id': 10, 'op': 'calc_fft', 'payload': _mk_time()}))
                reply = engine_host.decode_frame(await ws2.recv())
                assert reply['ok'] is True
        finally:
            await _stop_server(task)

    with caplog.at_level(logging.ERROR, logger='websockets.server'):
        run_async(scenario)
    assert 'connection handler failed' not in caplog.text


def test_engine_endpoint_close_mid_op_kills_worker_promptly(monkeypatch):
    # handle_connection currently just `await`s the executor call, and
    # websockets does NOT cancel a running handler task when the peer
    # closes -- so a client's Stop (= socket close) mid-op does nothing
    # until the op finishes on its own: the child keeps burning CPU, a
    # fresh connection's re-init would spin up a SECOND worker alongside
    # it, and the abandoned executor thread starves the thread pool.
    # Reproduce it directly: close mid-op and assert the worker's CHILD
    # PROCESS dies promptly, not after the op's full duration.
    #
    # Capture the EngineWorker instance handle_connection constructs (the
    # server runs IN-PROCESS in this harness -- asyncio.create_task -- so
    # a subclass swapped in via monkeypatch reaches the real handler) so
    # the test can poll its child process directly.
    captured = []
    _RealEngineWorker = engine_host.EngineWorker

    class _CapturingWorker(_RealEngineWorker):
        def __init__(self):
            super().__init__()
            captured.append(self)

    monkeypatch.setattr(engine_host, 'EngineWorker', _CapturingWorker)

    async def scenario():
        _s, task, port = await _start_server()
        try:
            async with connect('ws://127.0.0.1:%d/engine' % port,
                               max_size=None) as ws:
                await ws.recv()  # greeting

                # Sized to run solo for several seconds: measured directly
                # via engine.calc_sono(n=262144, voices_per_octave=40,
                # method='cwt') on this machine at ~4.36s (vs. ~0.29s for
                # the default n=65536/voices=16 the other tests use) --
                # comfortably over a 3s floor with margin for slower CI.
                payload = _mk_time(n=262144)
                payload.pop('window')
                payload.update(ch=0, nperseg=256, noverlap=128,
                               method='cwt', voices_per_octave=40)
                await ws.send(engine_host.encode_frame(
                    {'id': 20, 'op': 'calc_sono', 'payload': payload}))
                raw = await ws.recv()
                assert not isinstance(raw, (bytes, bytearray))  # a progress frame

                assert captured, 'EngineWorker was never constructed'
                worker = captured[-1]
                proc = worker._proc
                assert proc is not None and proc.is_alive()
            # `async with` above closes the client socket here, with the
            # op still running server-side.

            t_close = time.monotonic()
            while proc.is_alive() and time.monotonic() - t_close < 1.5:
                await asyncio.sleep(0.02)
            latency = time.monotonic() - t_close
            assert not proc.is_alive(), (
                'worker child still alive %.2fs after socket close '
                '(op was sized to run ~4.3s)' % latency)

            # A fresh connection must still work (one worker per
            # connection, not left double-booked by the abandoned one):
            async with connect('ws://127.0.0.1:%d/engine' % port,
                               max_size=None) as ws2:
                await ws2.recv()  # greeting
                await ws2.send(engine_host.encode_frame(
                    {'id': 21, 'op': 'calc_fft', 'payload': _mk_time()}))
                reply = engine_host.decode_frame(await ws2.recv())
                assert reply['ok'] is True
            return latency
        finally:
            await _stop_server(task)

    latency = asyncio.run(scenario())
    print('close -> child-dead latency: %.3fs' % latency)


def test_engine_endpoint_two_connections_get_independent_workers():
    async def scenario():
        _s, task, port = await _start_server()
        try:
            async with connect('ws://127.0.0.1:%d/engine' % port,
                               max_size=None) as ws1, \
                       connect('ws://127.0.0.1:%d/engine' % port,
                               max_size=None) as ws2:
                await ws1.recv()  # greeting
                await ws2.recv()  # greeting
                await ws1.send(engine_host.encode_frame(
                    {'id': 30, 'op': 'calc_fft', 'payload': _mk_time()}))
                await ws2.send(engine_host.encode_frame(
                    {'id': 31, 'op': 'calc_fft', 'payload': _mk_time()}))
                reply1 = engine_host.decode_frame(await ws1.recv())
                reply2 = engine_host.decode_frame(await ws2.recv())
                assert reply1['id'] == 30 and reply1['ok'] is True
                assert reply2['id'] == 31 and reply2['ok'] is True
        finally:
            await _stop_server(task)
    run_async(scenario)


# --- journal ops --------------------------------------------------------

class TestJournalOps:
    """``journal_set`` / ``journal_get`` / ``journal_discard_recovered``,
    answered INLINE by ``handle_connection`` -- never dispatched to the
    calc worker subprocess, which only knows compute ops -- plus the
    push-notify text frame a ``notify=True`` journal update sends to
    every connected ``/engine`` client.
    """

    def test_journal_set_replaces_doc(self):
        async def scenario():
            journal = SessionJournal()
            server, port = await _start_engine_server(journal)
            try:
                async with connect('ws://127.0.0.1:%d/engine' % port,
                                   max_size=None) as ws:
                    await _recv(ws)  # greeting
                    await ws.send(engine_host.encode_frame(
                        {'id': 1, 'op': 'journal_set',
                         'payload': {'doc': b'DOCBYTES'}}))
                    reply = engine_host.decode_frame(await _recv(ws))
                    assert reply['ok'] is True
                assert journal.state()[0] == b'DOCBYTES'
            finally:
                await _stop_engine_server(server)
        run_async(scenario)

    def test_journal_get_returns_doc_and_captures(self):
        async def scenario():
            journal = SessionJournal()
            journal.set_doc(b'DOC')
            journal.add_capture(b'CAP1')
            server, port = await _start_engine_server(journal)
            try:
                async with connect('ws://127.0.0.1:%d/engine' % port,
                                   max_size=None) as ws:
                    await _recv(ws)  # greeting
                    await ws.send(engine_host.encode_frame(
                        {'id': 2, 'op': 'journal_get', 'payload': {}}))
                    reply = engine_host.decode_frame(await _recv(ws))
                    assert reply['ok'] is True
                    assert reply['result'] == {
                        'doc': b'DOC', 'captures': [b'CAP1'], 'recovered': None}
            finally:
                await _stop_engine_server(server)
        run_async(scenario)

    def test_journal_get_on_empty_journal(self):
        async def scenario():
            journal = SessionJournal()
            server, port = await _start_engine_server(journal)
            try:
                async with connect('ws://127.0.0.1:%d/engine' % port,
                                   max_size=None) as ws:
                    await _recv(ws)  # greeting
                    await ws.send(engine_host.encode_frame(
                        {'id': 3, 'op': 'journal_get', 'payload': {}}))
                    reply = engine_host.decode_frame(await _recv(ws))
                    assert reply['ok'] is True
                    assert reply['result'] == {
                        'doc': None, 'captures': [], 'recovered': None}
            finally:
                await _stop_engine_server(server)
        run_async(scenario)

    def test_journal_get_includes_recovered(self, tmp_path):
        async def scenario():
            journal = SessionJournal()
            spill = tmp_path / 'old.dvma'
            spill.write_bytes(b'OLD')
            journal.adopt_recovered(str(spill))
            server, port = await _start_engine_server(journal)
            try:
                async with connect('ws://127.0.0.1:%d/engine' % port,
                                   max_size=None) as ws:
                    await _recv(ws)  # greeting
                    await ws.send(engine_host.encode_frame(
                        {'id': 4, 'op': 'journal_get', 'payload': {}}))
                    reply = engine_host.decode_frame(await _recv(ws))
                    assert reply['ok'] is True
                    assert reply['result']['recovered'] == b'OLD'
            finally:
                await _stop_engine_server(server)
        run_async(scenario)

    def test_journal_discard_recovered(self, tmp_path):
        async def scenario():
            journal = SessionJournal()
            spill = tmp_path / 'old.dvma'
            spill.write_bytes(b'OLD')
            journal.adopt_recovered(str(spill))
            server, port = await _start_engine_server(journal)
            try:
                async with connect('ws://127.0.0.1:%d/engine' % port,
                                   max_size=None) as ws:
                    await _recv(ws)  # greeting
                    await ws.send(engine_host.encode_frame(
                        {'id': 5, 'op': 'journal_discard_recovered',
                         'payload': {}}))
                    reply = engine_host.decode_frame(await _recv(ws))
                    assert reply['ok'] is True
                assert journal.recovered() is None
                assert not spill.exists()
            finally:
                await _stop_engine_server(server)
        run_async(scenario)

    def test_journal_op_without_a_journal_declines_inline(self):
        # journal=None (a bare harness serving handle_connection directly)
        # must answer the op itself with an error reply, never forward it
        # to the calc worker -- pinned to the EXACT message so this test
        # cannot pass merely because the worker's own unknown-op error
        # happens to also contain the word "journal" (e.g. from
        # "unknown op: journal_get").
        async def scenario():
            server, port = await _start_engine_server(journal=None)
            try:
                async with connect('ws://127.0.0.1:%d/engine' % port,
                                   max_size=None) as ws:
                    await _recv(ws)  # greeting
                    await ws.send(engine_host.encode_frame(
                        {'id': 6, 'op': 'journal_get', 'payload': {}}))
                    reply = engine_host.decode_frame(await _recv(ws))
                    assert reply['ok'] is False
                    assert reply['error'] == 'no session journal on this server'
            finally:
                await _stop_engine_server(server)
        run_async(scenario)

    def test_journal_set_rejects_missing_doc_bytes(self):
        async def scenario():
            journal = SessionJournal()
            server, port = await _start_engine_server(journal)
            try:
                async with connect('ws://127.0.0.1:%d/engine' % port,
                                   max_size=None) as ws:
                    await _recv(ws)  # greeting
                    await ws.send(engine_host.encode_frame(
                        {'id': 7, 'op': 'journal_set', 'payload': {}}))
                    reply = engine_host.decode_frame(await _recv(ws))
                    assert reply['ok'] is False
                    assert 'doc bytes' in reply['error']
            finally:
                await _stop_engine_server(server)
        run_async(scenario)

    def test_journal_notify_pushes_update_frame_to_client(self):
        async def scenario():
            journal = SessionJournal()
            server, port = await _start_engine_server(journal)
            try:
                async with connect('ws://127.0.0.1:%d/engine' % port,
                                   max_size=None) as ws:
                    greeting = json.loads(await _recv(ws))
                    assert greeting['type'] == 'engine_ready'
                    journal.set_doc(b'DOC', notify=True)
                    msg = json.loads(await _recv(ws))
                    assert msg == {'type': 'journal', 'event': 'updated'}
            finally:
                await _stop_engine_server(server)
        run_async(scenario)

    def test_journal_listener_is_unregistered_after_disconnect(self):
        # Pins the outer finally's unsubscribe. "set_doc(notify=True)
        # after disconnect doesn't raise" would be vacuous -- listener
        # exceptions are already swallowed inside set_doc (see its
        # docstring), so that alone gives zero coverage of the unsubscribe
        # actually running. Poll the journal's own listener list instead
        # (private-attr access is fine in a test whose whole point is to
        # pin this internal contract).
        async def scenario():
            journal = SessionJournal()
            server, port = await _start_engine_server(journal)
            try:
                async with connect('ws://127.0.0.1:%d/engine' % port,
                                   max_size=None) as ws:
                    await _recv(ws)  # greeting
                    assert journal._listeners  # registered while connected
                # client disconnected here -- the server notices and runs
                # its finally asynchronously; poll for it with a deadline
                # so a regression fails this test instead of hanging CI.
                deadline = time.monotonic() + 5.0
                while journal._listeners and time.monotonic() < deadline:
                    await asyncio.sleep(0.05)
                assert journal._listeners == []
            finally:
                await _stop_engine_server(server)
        run_async(scenario)

    def test_journal_set_produces_no_notify_frame_to_the_posting_client(self):
        # The silent-autosave contract: journal_set calls set_doc with the
        # default notify=False (see SessionJournal.set_doc's own
        # docstring -- "the app already has what it just posted"), so the
        # client that just posted a doc must not get its own update
        # echoed back as a {"type": "journal"} push frame.
        async def scenario():
            journal = SessionJournal()
            server, port = await _start_engine_server(journal)
            try:
                async with connect('ws://127.0.0.1:%d/engine' % port,
                                   max_size=None) as ws:
                    await _recv(ws)  # greeting
                    await ws.send(engine_host.encode_frame(
                        {'id': 8, 'op': 'journal_set',
                         'payload': {'doc': b'DOC3'}}))
                    reply = engine_host.decode_frame(await _recv(ws))
                    assert reply['ok'] is True
                    # Bounded drain: nothing arriving within the window is
                    # the PASSING outcome; anything that does arrive must
                    # not be a journal push frame.
                    try:
                        extra = await asyncio.wait_for(ws.recv(), 0.3)
                    except asyncio.TimeoutError:
                        extra = None
                    if extra is not None and not isinstance(extra, (bytes, bytearray)):
                        assert json.loads(extra).get('type') != 'journal'
            finally:
                await _stop_engine_server(server)
        run_async(scenario)

    def test_compute_op_still_works_after_a_journal_op_same_connection(self):
        # Proves the journal-ops `continue` leaves the frame loop healthy
        # for an ordinary compute op that follows on the SAME connection
        # -- not a one-shot dead end that only ever answers journal ops.
        async def scenario():
            journal = SessionJournal()
            server, port = await _start_engine_server(journal)
            try:
                async with connect('ws://127.0.0.1:%d/engine' % port,
                                   max_size=None) as ws:
                    await _recv(ws)  # greeting
                    await ws.send(engine_host.encode_frame(
                        {'id': 9, 'op': 'journal_get', 'payload': {}}))
                    reply1 = engine_host.decode_frame(await _recv(ws))
                    assert reply1['ok'] is True
                    await ws.send(engine_host.encode_frame(
                        {'id': 10, 'op': 'calc_fft', 'payload': _mk_time()}))
                    reply2 = engine_host.decode_frame(await _recv(ws))
                    assert reply2['ok'] is True
                    assert reply2['result']['freq_data']['complex'] is True
            finally:
                await _stop_engine_server(server)
        run_async(scenario)
