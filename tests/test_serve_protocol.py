"""Mac/Linux/Windows-runnable tests for the ``pydvma serve`` bridge.

Exercise the WebSocket protocol (`pydvma.serve`) end-to-end against the
hardware-free ``device_driver='mock'`` backend — no soundcard or NI
device is opened.  Covers:

* header encode/decode round-trip and the incremental monitor cursor
  (pure-unit, no server),
* the live protocol: hello→capabilities, configure→MySettings/REC,
  monitor frames with deterministic Mock sine content, log→loadable
  ``.dvma``, unknown-key + cancel error paths, two-client / reconnect,
* the HTTP surface: ``/config`` and the no-UI 404 page.

Live tests spin the asyncio server up on an ephemeral loopback port in
the running event loop (no threads, no ``pytest-asyncio`` needed —
each test wraps its scenario in ``asyncio.run``).
"""
import asyncio
import io
import json
import urllib.request

import numpy as np
import pytest

import pydvma as dvma
from pydvma import streams, container
from pydvma import serve as serve_mod

from websockets.asyncio.client import connect


@pytest.fixture(autouse=True)
def _clean_streams_state():
    """Reset module-level recorder globals before and after each test
    (mirrors tests/test_acquisition_mock.py)."""
    streams.REC = None
    streams.REC_MOCK = None
    yield
    if streams.REC is not None:
        try:
            streams.REC.end_stream()
        except Exception:
            pass
    streams.REC = None
    streams.REC_MOCK = None


# ---- server harness ------------------------------------------------------

async def _start_server(**kwargs):
    """Start a BridgeServer on an ephemeral loopback port.

    Returns ``(server, task, port)``; caller must ``_stop_server(task)``.
    """
    kwargs.setdefault('default_driver', 'mock')
    server = serve_mod.BridgeServer(host='127.0.0.1', port=0, **kwargs)
    task = asyncio.create_task(server.run())
    for _ in range(500):
        if server.sockets:
            break
        await asyncio.sleep(0.005)
    else:
        task.cancel()
        raise RuntimeError('server did not bind in time')
    port = server.sockets[0].getsockname()[1]
    return server, task, port


async def _stop_server(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _ws_url(port):
    return 'ws://127.0.0.1:%d/ws' % port


async def _send(ws, **msg):
    await ws.send(json.dumps(msg))


async def _recv_json(ws, timeout=5.0):
    """Receive the next TEXT frame as a decoded dict (skips binary)."""
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        if isinstance(raw, (bytes, bytearray)):
            continue
        return json.loads(raw)


async def _recv_binary(ws, timeout=5.0):
    """Receive the next BINARY frame (skips text)."""
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw)


def run_async(coro_fn):
    """Run an async scenario to completion in a fresh event loop."""
    return asyncio.run(coro_fn())


# ---- unit: header encode/decode -----------------------------------------

class TestHeaderCodec:

    def test_chunk_header_roundtrip(self):
        data = np.arange(12, dtype=float).reshape(4, 3)  # 4 samples, 3 ch
        frame = serve_mod.encode_chunk(stream_id=7, seq=42, data=data, fs=8000.0)
        assert len(frame) == serve_mod.HEADER_SIZE + 4 * 3 * 4
        hdr = serve_mod.decode_header(frame)
        assert hdr['magic'] == serve_mod.MAGIC
        assert hdr['ver'] == serve_mod.PROTOCOL_VERSION
        assert hdr['msgType'] == serve_mod.MSG_CHUNK
        assert hdr['dtype'] == serve_mod.DTYPE_F32
        assert hdr['streamId'] == 7
        assert hdr['nChannels'] == 3
        assert hdr['seq'] == 42
        assert hdr['nSamples'] == 4
        assert hdr['fs'] == pytest.approx(8000.0)
        payload = np.frombuffer(frame[serve_mod.HEADER_SIZE:], dtype='<f4')
        payload = payload.reshape(4, 3)
        np.testing.assert_allclose(payload, data, atol=1e-6)

    def test_container_header(self):
        blob = b'PK\x03\x04 fake dvma bytes'
        frame = serve_mod.encode_container(3, 0, blob, n_channels=2,
                                           n_samples=200, fs=44100.0)
        hdr = serve_mod.decode_header(frame)
        assert hdr['msgType'] == serve_mod.MSG_CONTAINER
        assert hdr['dtype'] == serve_mod.DTYPE_BYTES
        assert hdr['nChannels'] == 2
        assert hdr['nSamples'] == 200
        assert frame[serve_mod.HEADER_SIZE:] == blob

    def test_decode_rejects_bad_magic(self):
        bad = bytes([0x00]) + b'\x00' * (serve_mod.HEADER_SIZE - 1)
        with pytest.raises(ValueError, match='magic'):
            serve_mod.decode_header(bad)


# ---- unit: incremental monitor cursor -----------------------------------

class TestMonitorCursor:

    def test_incremental_slices_tile_without_overlap(self):
        """Simulate a scrolling recorder buffer and confirm the tail
        slices the bridge would ship tile the timeline with no overlap
        and no gaps (the core incremental-scheme invariant)."""
        fs = 1000.0
        buffer_len = 100
        cursor = serve_mod._MonitorCursor(fs, buffer_len)
        cursor.start(0.0)

        # Producer: absolute sample indices. Buffer initially holds
        # [0, buffer_len); each 20 ms tick produces round(fs*dt)=20 more.
        total = buffer_len
        collected = []
        for k in range(1, 11):
            now = k * 0.020
            total += 20  # producer advanced by exactly the estimate
            osc = np.arange(total - buffer_len, total)  # newest window
            n_new, overrun = cursor.take(now)
            assert n_new == 20
            assert overrun is False
            tail = osc[buffer_len - n_new:]  # what the bridge ships
            collected.append(tail)

        allsamples = np.concatenate(collected)
        expected = np.arange(buffer_len, buffer_len + 20 * 10)
        np.testing.assert_array_equal(allsamples, expected)
        # strictly increasing ⇒ no duplicate/overlapping samples
        assert np.all(np.diff(allsamples) == 1)

    def test_overrun_caps_at_buffer_len(self):
        cursor = serve_mod._MonitorCursor(1000.0, 100)
        cursor.start(0.0)
        n_new, overrun = cursor.take(1.0)  # 1 s ⇒ 1000 samples, capped
        assert overrun is True
        assert n_new == 100

    def test_take_before_start_raises(self):
        cursor = serve_mod._MonitorCursor(1000.0, 100)
        with pytest.raises(RuntimeError):
            cursor.take(0.1)


# ---- unit: capabilities --------------------------------------------------

def test_build_capabilities_shape():
    cap = serve_mod.build_capabilities()
    assert cap['v'] == serve_mod.PROTOCOL_VERSION
    assert 'mock' in cap['backends']           # mock is always available
    assert set(cap['devices'].keys()) == {'soundcard', 'nidaq'}
    assert cap['pretrigger'] is True
    assert cap['ao'] is True                   # mock backend always outputs
    # Wave-C per-device cap maps (were {} / None placeholders in v1).
    assert isinstance(cap['fs_ladders'], dict)
    assert isinstance(cap['max_channels'], dict)
    assert isinstance(cap['device_caps'], dict)
    # The mock backend has a stable stub entry in device_caps.
    assert cap['device_caps']['mock:0']['ao'] is True


def test_build_capabilities_includes_nidaq_caps_when_present(monkeypatch):
    """The nidaq branch of build_capabilities wires enumerate_devices +
    entry_capabilities into the per-device maps. nidaqmx never imports on
    Mac, so fake the backend to exercise the assembly here."""
    fake_entry = {
        'name': 'cDAQ1', 'product_type': 'cDAQ-9174', 'is_chassis': True,
        'ai_channel_count': 4, 'ao_channel_count': 2,
        'module_names': ['cDAQ1Mod1', 'cDAQ1Mod2'],
        'module_ai_counts': {'cDAQ1Mod1': 4, 'cDAQ1Mod2': 0},
        'module_ao_counts': {'cDAQ1Mod1': 0, 'cDAQ1Mod2': 2},
    }
    fake_caps = {
        'ai_max_rate': 51200.0, 'ai_min_rate': 1613.0,
        'ao_max_rate': 51200.0, 'ao_min_rate': 1613.0,
        'simultaneous': True, 'iepe_supported': True,
        'iepe_currents': [0.002],
        'terminal_configs': ['DAQmx_Val_PseudoDiff'], 'ao_supported': True,
    }
    monkeypatch.setattr(serve_mod.streams, 'ni', object())
    monkeypatch.setattr(serve_mod._ni_backend, 'enumerate_devices',
                        lambda: [dict(fake_entry)])
    monkeypatch.setattr(serve_mod._ni_backend, 'entry_capabilities',
                        lambda e: dict(fake_caps))

    cap = serve_mod.build_capabilities()
    assert 'nidaq' in cap['backends']
    entry = cap['devices']['nidaq'][0]
    assert entry['name'] == 'cDAQ1'
    assert entry['caps']['simultaneous'] is True     # inline caps on entry
    dc = cap['device_caps']['nidaq:0']
    assert dc['simultaneous'] is True and dc['iepe_supported'] is True
    assert dc['ao'] is True
    assert cap['max_channels']['nidaq:0'] == {'input': 4, 'output': 2}
    # fs ladder bounded by [ai_min_rate, ai_max_rate].
    ladder = cap['fs_ladders']['nidaq:0']
    assert ladder and all(1613.0 <= r <= 51200.0 for r in ladder)


def test_build_capabilities_soundcard_per_device_caps():
    """When sounddevice is importable, each soundcard device carries its
    own fs-ladder + channel counts keyed by ``soundcard:<index>``."""
    if streams.sd is None:
        pytest.skip('sounddevice not available')
    cap = serve_mod.build_capabilities()
    assert 'soundcard' in cap['backends']
    names = cap['devices']['soundcard']
    if not names:
        pytest.skip('no soundcard devices enumerated')
    for i in range(len(names)):
        did = 'soundcard:%d' % i
        assert did in cap['device_caps']
        assert did in cap['fs_ladders']
        assert did in cap['max_channels']
        c = cap['device_caps'][did]
        assert set(c) >= {'max_input_channels', 'max_output_channels',
                          'default_samplerate', 'candidate_rates', 'ao'}
        assert cap['max_channels'][did]['input'] == c['max_input_channels']
        assert isinstance(cap['fs_ladders'][did], list)


# ---- unit: output-signal builder ----------------------------------------

class TestBuildOutputSignal:

    def _settings(self, **kw):
        base = dict(device_driver='mock', channels=2, fs=8000, chunk_size=100,
                    num_chunks=4, viewed_time=None, output_channels=1)
        base.update(kw)
        return dvma.MySettings(**base)

    def test_none_spec_returns_no_output(self):
        s = self._settings()
        assert serve_mod._build_output_signal(s, None) == (None, False)

    def test_type_none_returns_no_output(self):
        s = self._settings()
        y, gen = serve_mod._build_output_signal(s, {'type': 'none'})
        assert y is None and gen is False

    def test_sweep_builds_waveform(self):
        s = self._settings()
        y, gen = serve_mod._build_output_signal(
            s, {'type': 'sweep', 'amp': 0.05, 'f1': 100, 'f2': 1000,
                'duration': 0.1})
        assert gen is True
        assert y.shape == (int(0.1 * s.output_fs), s.output_channels)
        assert np.max(np.abs(y)) <= s.output_vmax() + 1e-9

    def test_white_aliases_uniform(self):
        s = self._settings()
        y, gen = serve_mod._build_output_signal(
            s, {'type': 'white', 'amp': 0.05, 'f1': 100, 'f2': 1000,
                'duration': 0.1})
        assert gen is True and y.shape[1] == s.output_channels

    def test_unknown_type_rejected(self):
        s = self._settings()
        with pytest.raises(ValueError, match='unknown output type'):
            serve_mod._build_output_signal(s, {'type': 'square'})

    def test_unknown_key_rejected(self):
        s = self._settings()
        with pytest.raises(ValueError, match='unknown output key'):
            serve_mod._build_output_signal(
                s, {'type': 'sweep', 'bogus': 1})

    def test_nyquist_violation_rejected(self):
        s = self._settings(fs=8000)
        with pytest.raises(ValueError, match='Nyquist'):
            serve_mod._build_output_signal(
                s, {'type': 'sweep', 'f1': 0, 'f2': 5000})  # > 4000 = fs/2


# ---- live: hello / configure --------------------------------------------

def test_hello_returns_capabilities():
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='hello')
                cap = await _recv_json(ws)
                assert cap['type'] == 'capabilities'
                assert cap['v'] == serve_mod.PROTOCOL_VERSION
                assert 'mock' in cap['backends']
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_configure_creates_rec_with_right_settings():
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 3, 'fs': 8000, 'chunk_size': 1000,
                    'num_chunks': 4, 'viewed_time': None,
                })
                status = await _recv_json(ws)
                assert status['type'] == 'status'
                assert status['event'] == 'configured'
                assert status['driver'] == 'mock'
                assert status['fs'] == 8000.0
                assert status['channels'] == 3
                assert status['oscSamples'] == 4000  # num_chunks*chunk_size

                # REC is created in-process with the requested settings.
                assert isinstance(streams.REC, streams.MockRecorder)
                assert streams.REC.settings.channels == 3
                assert streams.REC.settings.fs == 8000
                assert streams.REC.osc_time_data.shape == (4000, 3)
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_configure_rejects_unknown_key():
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure',
                            settings={'channels': 2, 'bogus_key': 5})
                err = await _recv_json(ws)
                assert err['type'] == 'error'
                assert 'bogus_key' in err['message']
                assert streams.REC is None  # nothing configured
        finally:
            await _stop_server(task)
    run_async(scenario)


# ---- live: monitor feed --------------------------------------------------

def test_monitor_frames_carry_mock_sine():
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 3, 'fs': 8000, 'chunk_size': 1000,
                    'num_chunks': 4, 'viewed_time': None,
                })
                status = await _recv_json(ws)
                buffer_len = status['oscSamples']
                fs = status['fs']
                await _send(ws, type='start_monitor')
                # status 'monitoring' then binary frames follow.
                frame = await _recv_binary(ws, timeout=5.0)
                hdr = serve_mod.decode_header(frame)
                assert hdr['magic'] == serve_mod.MAGIC
                assert hdr['msgType'] == serve_mod.MSG_CHUNK
                assert hdr['nChannels'] == 3
                n = hdr['nSamples']
                assert n > 0
                payload = np.frombuffer(frame[serve_mod.HEADER_SIZE:],
                                        dtype='<f4').reshape(n, 3)

                # The frame is the newest `n` samples (tail) of the mock
                # osc buffer: mock fills osc[i, ch] = 0.1*sin(2π·100·(ch+1)·i/fs).
                start = buffer_len - n
                idx = np.arange(start, start + n)
                for ch in range(3):
                    expected = 0.1 * np.sin(2 * np.pi * 100 * (ch + 1) * idx / fs)
                    np.testing.assert_allclose(payload[:, ch], expected, atol=1e-4)

                await _send(ws, type='stop_monitor')
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_monitor_seq_numbers_increase():
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure',
                            settings={'channels': 2, 'fs': 8000,
                                      'chunk_size': 1000, 'num_chunks': 4,
                                      'viewed_time': None})
                await _recv_json(ws)
                await _send(ws, type='start_monitor')
                seqs = []
                for _ in range(3):
                    frame = await _recv_binary(ws, timeout=5.0)
                    seqs.append(serve_mod.decode_header(frame)['seq'])
                assert seqs == sorted(seqs)
                assert len(set(seqs)) == len(seqs)  # no repeats
                await _send(ws, type='stop_monitor')
        finally:
            await _stop_server(task)
    run_async(scenario)


# ---- live: log round-trip ------------------------------------------------

def test_log_returns_loadable_dvma():
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 2, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 0.1, 'num_chunks': 4, 'viewed_time': None,
                })
                await _recv_json(ws)
                await _send(ws, type='log', duration=0.1, pretrigger=None,
                            test_name='bridge-capture')
                meta = await _recv_json(ws, timeout=10.0)
                assert meta['type'] == 'log_result'
                assert meta['nChannels'] == 2
                assert meta['nSamples'] == int(0.1 * 8000)
                assert meta['testName'] == 'bridge-capture'

                frame = await _recv_binary(ws, timeout=10.0)
                hdr = serve_mod.decode_header(frame)
                assert hdr['msgType'] == serve_mod.MSG_CONTAINER
                assert meta['byteLength'] == len(frame) - serve_mod.HEADER_SIZE

                # pydvma's own container reader loads the bytes back.
                dvma_bytes = frame[serve_mod.HEADER_SIZE:]
                ds = container.load(io.BytesIO(dvma_bytes))
                assert isinstance(ds, dvma.DataSet)
                assert len(ds.time_data_list) == 1
                td = ds.time_data_list[0]
                assert td.time_data.shape == (int(0.1 * 8000), 2)
                assert td.test_name == 'bridge-capture'
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_log_before_configure_errors():
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='log', duration=0.1, pretrigger=None)
                err = await _recv_json(ws)
                assert err['type'] == 'error'
                assert 'configure' in err['message']
        finally:
            await _stop_server(task)
    run_async(scenario)


# ---- live: output / stimulus --------------------------------------------

def test_configure_forwards_output_kwargs_to_settings():
    """The MySettings output_* fields flow in through configure.settings
    and land on the recorder's settings unchanged."""
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 2, 'fs': 8000, 'chunk_size': 1000,
                    'num_chunks': 4, 'viewed_time': None,
                    'output_channels': 2, 'output_fs': 16000,
                    'output_VmaxNI': 3.0, 'use_output_as_ch0': True,
                })
                status = await _recv_json(ws)
                assert status['event'] == 'configured'
                s = streams.REC.settings
                assert s.output_channels == 2
                assert s.output_fs == 16000
                assert s.output_VmaxNI == 3.0
                assert s.use_output_as_ch0 is True
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_log_with_output_prepends_stimulus_channel():
    """A `log` carrying an `output` sweep builds the waveform and drives
    log_data(..., output=y); with use_output_as_ch0 the generated signal
    is prepended, so the captured set has channels+output_channels."""
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 2, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 0.1, 'num_chunks': 4, 'viewed_time': None,
                    'output_channels': 1, 'use_output_as_ch0': True,
                })
                await _recv_json(ws)
                await _send(ws, type='log', duration=0.1, pretrigger=None,
                            output={'type': 'sweep', 'amp': 0.05,
                                    'f1': 100, 'f2': 1000, 'duration': 0.1},
                            test_name='with-output')
                meta = await _recv_json(ws, timeout=10.0)
                assert meta['type'] == 'log_result'
                # 2 input channels + 1 prepended output channel.
                assert meta['nChannels'] == 3

                frame = await _recv_binary(ws, timeout=10.0)
                dvma_bytes = frame[serve_mod.HEADER_SIZE:]
                ds = container.load(io.BytesIO(dvma_bytes))
                td = ds.time_data_list[0]
                assert td.time_data.shape == (int(0.1 * 8000), 3)
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_log_rejects_unknown_output_key():
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 1, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 0.1, 'num_chunks': 4, 'viewed_time': None,
                })
                await _recv_json(ws)
                await _send(ws, type='log', duration=0.1, pretrigger=None,
                            output={'type': 'sweep', 'bogus': 1})
                err = await _recv_json(ws)
                assert err['type'] == 'error'
                assert 'unknown output key' in err['message']
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_log_rejects_output_above_nyquist():
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 1, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 0.1, 'num_chunks': 4, 'viewed_time': None,
                })
                await _recv_json(ws)
                await _send(ws, type='log', duration=0.1, pretrigger=None,
                            output={'type': 'sweep', 'f1': 0, 'f2': 5000})
                err = await _recv_json(ws)
                assert err['type'] == 'error'
                assert 'Nyquist' in err['message']
        finally:
            await _stop_server(task)
    run_async(scenario)


# ---- live: pretrigger status events -------------------------------------

def test_pretrigger_armed_then_timeout_then_result():
    """MockRecorder never triggers, so an armed pretriggered log walks the
    timeout fallback: status 'armed' -> status 'timeout' -> log_result ->
    container frame."""
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 1, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 0.1, 'num_chunks': 4, 'viewed_time': None,
                })
                await _recv_json(ws)
                await _send(ws, type='log', duration=0.1,
                            pretrigger={'samples': 50, 'threshold': 0.2,
                                        'timeout': 0.3},
                            test_name='pretrig-timeout')

                events = []
                meta = None
                for _ in range(10):
                    msg = await _recv_json(ws, timeout=10.0)
                    if msg['type'] == 'status':
                        events.append(msg['event'])
                    elif msg['type'] == 'log_result':
                        meta = msg
                        break
                assert events == ['armed', 'timeout']
                assert meta is not None and meta['testName'] == 'pretrig-timeout'

                # the container frame still follows and loads.
                frame = await _recv_binary(ws, timeout=10.0)
                assert serve_mod.decode_header(frame)['msgType'] == \
                    serve_mod.MSG_CONTAINER
        finally:
            await _stop_server(task)
    run_async(scenario)


# ---- live: cancel --------------------------------------------------------

def test_cancel_stops_monitor():
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure',
                            settings={'channels': 1, 'fs': 8000,
                                      'chunk_size': 1000, 'num_chunks': 4,
                                      'viewed_time': None})
                await _recv_json(ws)
                await _send(ws, type='start_monitor')
                await _recv_binary(ws, timeout=5.0)  # at least one frame
                await _send(ws, type='cancel')
                # Drain until we see the cancelled status; frames may be
                # in flight but must stop shortly after.
                saw_cancel = False
                for _ in range(20):
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    if isinstance(raw, str):
                        msg = json.loads(raw)
                        if msg.get('event') == 'cancelled':
                            saw_cancel = True
                            break
                assert saw_cancel
        finally:
            await _stop_server(task)
    run_async(scenario)


# ---- live: two clients + reconnect --------------------------------------

def test_two_clients_get_distinct_stream_ids():
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws_a, \
                       connect(_ws_url(port)) as ws_b:
                await _send(ws_a, type='configure', settings={'channels': 1})
                sa = await _recv_json(ws_a)
                await _send(ws_b, type='configure', settings={'channels': 1})
                sb = await _recv_json(ws_b)
                assert sa['streamId'] != sb['streamId']

            # reconnect a fresh client after both closed — still serves.
            async with connect(_ws_url(port)) as ws_c:
                await _send(ws_c, type='hello')
                cap = await _recv_json(ws_c)
                assert cap['type'] == 'capabilities'
        finally:
            await _stop_server(task)
    run_async(scenario)


# ---- live: HTTP surface (/config + no-UI 404) ---------------------------

def _http_get(port, path):
    """Blocking HTTP GET → (status, content_type, body_bytes)."""
    url = 'http://127.0.0.1:%d%s' % (port, path)
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.headers.get('Content-Type'), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get('Content-Type'), e.read()


def test_config_endpoint_returns_settings_json():
    settings_doc = {'device_driver': 'mock', 'fs': 8000, 'channels': 2}

    async def scenario():
        _server, task, port = await _start_server(settings_json=settings_doc)
        try:
            loop = asyncio.get_running_loop()
            status, ctype, body = await loop.run_in_executor(
                None, _http_get, port, '/config')
            assert status == 200
            assert 'application/json' in ctype
            assert json.loads(body) == settings_doc
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_no_ui_returns_helpful_404():
    async def scenario():
        # ui_dir=None ⇒ no built UI; GET / should give the help page.
        _server, task, port = await _start_server(ui_dir=None)
        try:
            loop = asyncio.get_running_loop()
            status, ctype, body = await loop.run_in_executor(
                None, _http_get, port, '/')
            assert status == 404
            assert b'pydvma serve is running' in body
            assert b'--ui-dir' in body
        finally:
            await _stop_server(task)
    run_async(scenario)
