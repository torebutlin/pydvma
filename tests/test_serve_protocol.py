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


# ---- unit: output-signal builder -- multisine (BLA) ----------------------

class TestBuildOutputSignalMultisine:
    """`_build_output_signal` gains a `'multisine'` type for Schoukens BLA
    captures, delegating to `acquisition.multisine_generator`.  See
    dev/plans/2026-08-10-schoukens-bla-design.md and
    tests/test_multisine.py (the generator's own contract, not duplicated
    here)."""

    def _settings(self, **kw):
        base = dict(device_driver='mock', channels=2, fs=8000, chunk_size=100,
                    num_chunks=4, viewed_time=None, output_channels=2,
                    output_fs=8000)
        base.update(kw)
        return dvma.MySettings(**base)

    def _spec(self, **overrides):
        spec = dict(type='multisine', amp=0.05, n_samples=64, k1=4, k2=10,
                    p_periods=3, t_periods=2, seed=42, m=0, e=0, n_exc=2)
        spec.update(overrides)
        return spec

    def test_multisine_builds_waveform(self):
        s = self._settings()
        spec = self._spec()
        y, gen = serve_mod._build_output_signal(s, spec)
        assert gen is True
        n_periods = spec['t_periods'] + spec['p_periods']
        assert y.shape == (n_periods * spec['n_samples'], spec['n_exc'])

    def test_multisine_siso(self):
        s = self._settings(output_channels=1)
        spec = self._spec(n_exc=1, e=0)
        y, gen = serve_mod._build_output_signal(s, spec)
        assert gen is True
        n_periods = spec['t_periods'] + spec['p_periods']
        assert y.shape == (n_periods * spec['n_samples'], 1)

    def test_unknown_key_rejected_lists_multisine_keys(self):
        s = self._settings()
        with pytest.raises(ValueError) as excinfo:
            serve_mod._build_output_signal(
                s, self._spec(bogus=1))
        msg = str(excinfo.value)
        assert 'unknown output key' in msg
        # names the BRANCH: 'f1' rejected by a multisine spec reads like
        # a typo unless the message says which keyset was applied.
        assert 'multisine' in msg
        assert 'bogus' in msg
        # the allowed-keys list quoted back must be the multisine keyset,
        # not the classic sweep/gaussian/uniform one.
        assert 'n_samples' in msg
        assert 'k1' in msg
        assert 'f1' not in msg

    def test_missing_keys_are_all_listed(self):
        """A half-built spec is usually missing several keys; naming one
        at a time costs a round trip per key."""
        s = self._settings()
        spec = self._spec()
        for key in ('k1', 'k2', 'seed'):
            del spec[key]
        with pytest.raises(ValueError) as excinfo:
            serve_mod._build_output_signal(s, spec)
        msg = str(excinfo.value)
        for key in ('k1', 'k2', 'seed'):
            assert repr(key) in msg

    def test_int_keys_derived_from_the_keyset(self):
        """The int-field tuple is derived from the accepted keyset, so
        the two cannot drift apart when a key is added."""
        assert set(serve_mod._MULTISINE_INT_KEYS) == (
            serve_mod._OUTPUT_SPEC_KEYS_MULTISINE - {'type', 'amp'})

    @pytest.mark.parametrize('key', [
        'n_samples', 'k1', 'k2', 'p_periods', 't_periods', 'seed', 'm', 'e',
        'n_exc',
    ])
    def test_whole_float_int_field_accepted(self, key):
        """JSON has no integer type, so a wire value of 64.0 is a
        legitimate spelling of 64 and must be accepted."""
        s = self._settings()
        spec = self._spec(**{key: float(self._spec()[key])})
        y, gen = serve_mod._build_output_signal(s, spec)
        assert gen is True

    def test_non_integral_float_int_field_rejected(self):
        s = self._settings()
        with pytest.raises(ValueError) as excinfo:
            serve_mod._build_output_signal(s, self._spec(k2=10.5))
        msg = str(excinfo.value)
        assert repr('k2') in msg
        assert 'integer' in msg

    def test_bool_int_field_rejected(self):
        """JSON true/false is an int subclass in Python — it must not
        slip into a numeric spec field."""
        s = self._settings()
        with pytest.raises(ValueError) as excinfo:
            serve_mod._build_output_signal(s, self._spec(n_exc=True))
        assert repr('n_exc') in str(excinfo.value)

    def test_bool_amp_rejected(self):
        s = self._settings()
        with pytest.raises(ValueError) as excinfo:
            serve_mod._build_output_signal(s, self._spec(amp=True))
        assert repr('amp') in str(excinfo.value)

    @pytest.mark.parametrize('bad', [float('nan'), float('inf'),
                                      float('-inf')])
    def test_non_finite_amp_rejected(self, bad):
        """Bare JSON has no NaN/Infinity, but a permissive encoder can
        emit them — and the generator's peak guard is a `>` comparison,
        which is False for NaN, so a NaN amplitude would reach the DAC as
        an all-NaN buffer with nothing raising."""
        s = self._settings()
        with pytest.raises(ValueError) as excinfo:
            serve_mod._build_output_signal(s, self._spec(amp=bad))
        msg = str(excinfo.value)
        assert repr('amp') in msg
        assert 'finite' in msg

    @pytest.mark.parametrize('missing', [
        'amp', 'n_samples', 'k1', 'k2', 'p_periods', 't_periods',
        'seed', 'm', 'e', 'n_exc',
    ])
    def test_missing_required_key_names_it(self, missing):
        s = self._settings()
        spec = self._spec()
        del spec[missing]
        with pytest.raises(ValueError) as excinfo:
            serve_mod._build_output_signal(s, spec)
        # quoted form guards against trivial substring hits for short
        # keys like 'm'/'e' (e.g. "missing" itself contains 'm').
        assert repr(missing) in str(excinfo.value)

    @pytest.mark.parametrize('key', [
        'n_samples', 'k1', 'k2', 'p_periods', 't_periods', 'seed', 'm', 'e',
        'n_exc',
    ])
    def test_non_numeric_int_field_rejected(self, key):
        s = self._settings()
        spec = self._spec(**{key: 'not-a-number'})
        with pytest.raises(ValueError) as excinfo:
            serve_mod._build_output_signal(s, spec)
        msg = str(excinfo.value)
        # quoted key name -- guards against 'not-a-number' itself
        # containing letters like 'm'/'e' that would trivially match a
        # bare substring check.
        assert repr(key) in msg

    def test_non_numeric_amp_rejected(self):
        s = self._settings()
        spec = self._spec(amp='loud')
        with pytest.raises(ValueError) as excinfo:
            serve_mod._build_output_signal(s, spec)
        assert repr('amp') in str(excinfo.value)

    def test_duration_key_rejected_with_explanatory_message(self):
        s = self._settings()
        spec = self._spec(duration=0.5)
        with pytest.raises(ValueError) as excinfo:
            serve_mod._build_output_signal(s, spec)
        msg = str(excinfo.value)
        assert 'duration' in msg
        # explains WHY: duration is derived, not an accepted input.
        assert 'derived' in msg
        assert 'n_samples' in msg

    def test_generator_bin_validation_propagates(self):
        """`_build_output_signal` must not duplicate multisine_generator's
        own k1/k2/N bin-sanity checks -- it just has to let the ValueError
        through unmodified."""
        s = self._settings()
        spec = self._spec(k1=10, k2=4)   # k1 > k2: illegal
        with pytest.raises(ValueError, match='k1'):
            serve_mod._build_output_signal(s, spec)

    def test_generator_peak_guard_propagates(self):
        s = self._settings(output_VmaxSC=0.001)
        spec = self._spec(amp=0.5)   # will blow the tiny rail
        with pytest.raises(ValueError, match='rail'):
            serve_mod._build_output_signal(s, spec)

    def test_amp_maps_to_amp_rms(self):
        """`amp` in the wire spec is the generator's `amp_rms` -- confirm
        the RMS of one period matches, the same way test_multisine.py's
        TestRmsLevel pins the generator itself."""
        spec = self._spec(amp=0.2, n_exc=1)
        s = self._settings(output_VmaxSC=10.0, output_channels=1)
        y, gen = serve_mod._build_output_signal(s, spec)
        N = spec['n_samples']
        rms = np.sqrt(np.mean(y[:N] ** 2, axis=0))
        assert np.allclose(rms, 0.2, rtol=1e-9)


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


def test_configure_forwards_output_device_selection():
    """Round-4 item 12: output DEVICE + CHANNEL selection rides the existing
    configure.settings whitelist (output_device_driver / output_device_index /
    output_channels are ordinary MySettings kwargs) — no protocol addition —
    and lands on the recorder's settings unchanged."""
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 2, 'fs': 8000, 'chunk_size': 1000,
                    'num_chunks': 4, 'viewed_time': None,
                    'output_device_driver': 'mock', 'output_device_index': 0,
                    'output_channels': 2,
                })
                status = await _recv_json(ws)
                assert status['event'] == 'configured'
                s = streams.REC.settings
                assert s.output_device_driver == 'mock'
                assert s.output_device_index == 0
                assert s.output_channels == 2
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_log_output_duration_shorter_than_capture():
    """Round-4 item 12: the output-spec `duration` key (already accepted by
    `_build_output_signal`) drives a stimulus SHORTER than the capture; the
    captured set length still follows the CAPTURE duration, and the container
    frame lands as usual."""
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 2, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 0.1, 'num_chunks': 4, 'viewed_time': None,
                    'output_channels': 1,
                })
                await _recv_json(ws)
                await _send(ws, type='log', duration=0.1, pretrigger=None,
                            output={'type': 'sweep', 'amp': 0.05,
                                    'f1': 100, 'f2': 1000, 'duration': 0.05},
                            test_name='out-dur')
                meta = await _recv_json(ws, timeout=10.0)
                assert meta['type'] == 'log_result'
                # Capture length follows the CAPTURE duration, not the output's.
                assert meta['nSamples'] == int(0.1 * 8000)
                assert meta['nChannels'] == 2  # no use_output_as_ch0 prepend

                frame = await _recv_binary(ws, timeout=10.0)
                assert serve_mod.decode_header(frame)['msgType'] == \
                    serve_mod.MSG_CONTAINER
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


def test_log_with_multisine_output_produces_capture():
    """A `log` carrying a `multisine` output spec drives
    acquisition.multisine_generator (via `_build_output_signal`) and the
    resulting waveform reaches `log_data(..., output=y)` the same as any
    other output type -- BLA-capture wiring, no analysis here."""
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 2, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 0.1, 'num_chunks': 4, 'viewed_time': None,
                    'output_channels': 1,
                })
                await _recv_json(ws)
                await _send(ws, type='log', duration=0.1, pretrigger=None,
                            output={'type': 'multisine', 'amp': 0.05,
                                    'n_samples': 64, 'k1': 4, 'k2': 10,
                                    'p_periods': 2, 't_periods': 1,
                                    'seed': 7, 'm': 0, 'e': 0, 'n_exc': 1},
                            test_name='multisine-capture')
                meta = await _recv_json(ws, timeout=10.0)
                assert meta['type'] == 'log_result'
                assert meta['nChannels'] == 2   # no use_output_as_ch0 prepend
                assert meta['nSamples'] == int(0.1 * 8000)

                frame = await _recv_binary(ws, timeout=10.0)
                assert serve_mod.decode_header(frame)['msgType'] == \
                    serve_mod.MSG_CONTAINER
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_log_rejects_multisine_bin_violation():
    """`multisine_generator`'s own bin-sanity ValueError (not duplicated
    in `_build_output_signal`) propagates through the same `error`-frame
    path as the classic-spec validation errors above."""
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 1, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 0.1, 'num_chunks': 4, 'viewed_time': None,
                    'output_channels': 1,
                })
                await _recv_json(ws)
                await _send(ws, type='log', duration=0.1, pretrigger=None,
                            output={'type': 'multisine', 'amp': 0.05,
                                    'n_samples': 64, 'k1': 10, 'k2': 4,
                                    'p_periods': 2, 't_periods': 1,
                                    'seed': 7, 'm': 0, 'e': 0, 'n_exc': 1})
                err = await _recv_json(ws)
                assert err['type'] == 'error'
                assert 'k1' in err['message']
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


class TestSoundcardNativeRates:
    """The advertised ladder must reflect what the hardware can run.

    ``sd.check_input_settings`` accepts every rate on macOS, so trusting
    it put rates in the UI that the device cannot produce.
    """

    def _caps(self, monkeypatch, native, probe_accepts_everything=True):
        class FakeSd:
            @staticmethod
            def query_devices():
                return [{'name': 'Fake Interface', 'max_input_channels': 2,
                         'max_output_channels': 2, 'default_samplerate': 48000.0}]

            @staticmethod
            def check_input_settings(device=None, channels=None, samplerate=None):
                if not probe_accepts_everything and samplerate > 48000:
                    raise ValueError('nope')

        monkeypatch.setattr(serve_mod.streams, 'sd', FakeSd)
        monkeypatch.setattr(serve_mod, '_soundcard_native_rates', lambda i: list(native))
        return serve_mod._soundcard_device_caps()[1][0]

    def test_native_ladder_is_reported_separately(self, monkeypatch):
        caps = self._caps(monkeypatch, [44100.0, 48000.0, 96000.0])
        assert caps['native_rates'] == [44100, 48000, 96000]

    def test_rates_above_the_hardware_ceiling_are_dropped(self, monkeypatch):
        """The probe accepts 192 kHz on a 96 kHz device; the ladder must not."""
        caps = self._caps(monkeypatch, [44100.0, 48000.0, 96000.0])
        assert 192000 not in caps['candidate_rates']
        assert 176400 not in caps['candidate_rates']

    def test_rates_between_hardware_rungs_are_dropped(self, monkeypatch):
        caps = self._caps(monkeypatch, [44100.0, 96000.0])
        assert 48000 not in caps['candidate_rates']

    def test_low_rates_stay_offered_because_pydvma_decimates(self, monkeypatch):
        """A 44.1 kHz-floor card still delivers the 3 kHz a low-bandwidth
        lab wants — by capturing natively and resampling down."""
        caps = self._caps(monkeypatch, [44100.0, 48000.0])
        assert 8000 in caps['candidate_rates']
        assert 22050 in caps['candidate_rates']

    def test_falls_back_to_probing_when_the_ladder_is_unknown(self, monkeypatch):
        caps = self._caps(monkeypatch, [], probe_accepts_everything=False)
        assert caps['native_rates'] == []
        assert caps['candidate_rates'] == [8000, 11025, 16000, 22050, 32000,
                                           44100, 48000]


class TestSoundcardGainModelInCaps:
    """The UI needs the published input levels to preview what a stated
    gain means before a capture commits to it."""

    def _caps(self, monkeypatch, name):
        class FakeSd:
            @staticmethod
            def query_devices():
                return [{'name': name, 'max_input_channels': 4,
                         'max_output_channels': 2, 'default_samplerate': 48000.0}]

            @staticmethod
            def check_input_settings(**kwargs):
                pass

        monkeypatch.setattr(serve_mod.streams, 'sd', FakeSd)
        monkeypatch.setattr(serve_mod, '_soundcard_native_rates', lambda i: [48000.0])
        return serve_mod._soundcard_device_caps()[1][0]

    def test_characterised_device_publishes_modes_and_levels(self, monkeypatch):
        caps = self._caps(monkeypatch, 'Scarlett 2i2 4th Gen')
        assert caps['input_modes'] == ['inst', 'line', 'mic']
        assert caps['max_input_dbu'] == {'line': 22.0, 'inst': 12.0, 'mic': 16.0}
        assert caps['channel_roles'] == ['analogue', 'analogue', 'loopback', 'loopback']
        assert caps['fixed_gain'] is False

    def test_fixed_gain_device_says_so(self, monkeypatch):
        """A gainless interface's full scale is a hardware constant —
        the UI shows it directly instead of asking for a gain."""
        caps = self._caps(monkeypatch, 'U24XL with SPDIF I/O')
        assert caps['fixed_gain'] is True
        assert caps['input_modes'] == ['line']
        assert caps['max_input_dbu'] == {'line': 4.7}

    def test_uncharacterised_device_publishes_empties_not_guesses(self, monkeypatch):
        caps = self._caps(monkeypatch, 'Some Other Interface')
        assert caps['input_modes'] == []
        assert caps['max_input_dbu'] == {}
        assert caps['channel_roles'] == []
        assert caps['fixed_gain'] is False


class TestDeviceIndexReresolution:
    """A device index is a POSITION in an enumeration, not an identity.

    PortAudio renumbers whenever the device list changes — observed live
    on 2026-08-10, a Scarlett 2i2 at index 2 became index 1 once another
    interface left the list. The UI enumerates once on connect, so a
    stale index silently records the wrong device.
    """

    def _conn(self):
        return serve_mod._Connection.__new__(serve_mod._Connection)

    def _names(self, monkeypatch, names):
        class FakeSd:
            @staticmethod
            def query_devices():
                return [{'name': n} for n in names]

        monkeypatch.setattr(serve_mod.streams, 'sd', FakeSd)

    def test_index_unchanged_when_the_name_still_matches(self, monkeypatch):
        self._names(monkeypatch, ['Built-in', 'Scarlett 2i2 4th Gen'])
        idx, note = self._conn()._reresolve_device_index('soundcard', 1,
                                                         'Scarlett 2i2 4th Gen')
        assert (idx, note) == (1, None)

    def test_follows_the_device_when_it_moves(self, monkeypatch):
        """The real failure: the user picked a DEVICE, not a number."""
        self._names(monkeypatch, ['Built-in', 'Scarlett 2i2 4th Gen', 'BlackHole 2ch'])
        idx, note = self._conn()._reresolve_device_index('soundcard', 2,
                                                         'Scarlett 2i2 4th Gen')
        assert idx == 1
        assert 'moved from device index 2 to 1' in note

    def test_raises_when_the_device_is_gone(self, monkeypatch):
        """Recording silence under the right name is the worst outcome."""
        self._names(monkeypatch, ['Built-in', 'BlackHole 2ch'])
        with pytest.raises(ValueError, match='no longer connected'):
            self._conn()._reresolve_device_index('soundcard', 1,
                                                 'Scarlett 2i2 4th Gen')

    def test_error_names_what_the_index_now_points_at(self, monkeypatch):
        self._names(monkeypatch, ['Built-in', 'BlackHole 2ch'])
        with pytest.raises(ValueError, match="now 'BlackHole 2ch'"):
            self._conn()._reresolve_device_index('soundcard', 1,
                                                 'Scarlett 2i2 4th Gen')

    def test_raises_when_the_index_is_off_the_end(self, monkeypatch):
        self._names(monkeypatch, ['Built-in'])
        with pytest.raises(ValueError, match='no longer connected'):
            self._conn()._reresolve_device_index('soundcard', 5, 'Scarlett 2i2 4th Gen')

    def test_duplicate_names_leave_the_index_alone(self, monkeypatch):
        """Two identical interfaces make the index the ONLY thing telling
        them apart, so second-guessing it would be a downgrade."""
        self._names(monkeypatch, ['Scarlett 2i2 4th Gen', 'Scarlett 2i2 4th Gen'])
        idx, note = self._conn()._reresolve_device_index('soundcard', 1,
                                                         'Scarlett 2i2 4th Gen')
        assert (idx, note) == (1, None)

    def test_no_expected_name_is_a_no_op(self, monkeypatch):
        """Older clients send no name; they must keep working."""
        self._names(monkeypatch, ['Built-in'])
        assert self._conn()._reresolve_device_index('soundcard', 3, None) == (3, None)
        assert self._conn()._reresolve_device_index('soundcard', 3, '') == (3, None)

    def test_mock_driver_is_left_alone(self, monkeypatch):
        assert self._conn()._reresolve_device_index('mock', 0, 'anything') == (0, None)

    def test_enumeration_failure_never_blocks_a_capture(self, monkeypatch):
        """Best-effort: a device list we cannot re-read is not a reason to
        refuse to record."""
        class ExplodingSd:
            @staticmethod
            def query_devices():
                raise RuntimeError('PortAudio unavailable')

        monkeypatch.setattr(serve_mod.streams, 'sd', ExplodingSd)
        assert self._conn()._reresolve_device_index(
            'soundcard', 1, 'Scarlett 2i2 4th Gen') == (1, None)

    def test_nidaq_devices_are_checked_too(self, monkeypatch):
        monkeypatch.setattr(serve_mod._ni_backend, 'enumerate_devices',
                            lambda: [{'name': 'Dev1'}, {'name': 'cDAQ1Mod1'}])
        idx, note = self._conn()._reresolve_device_index('nidaq', 0, 'cDAQ1Mod1')
        assert idx == 1
        assert 'moved' in note


# ---- live: cancel during a log (round 11) --------------------------------

def test_cancel_during_log_aborts():
    """A `cancel` sent mid-capture stops it, and `status/cancelled`
    arrives INSTEAD of `log_result` — no container frame either.

    Root cause this covers: the receive loop used to await the log
    inline, so the cancel frame was not even READ until the capture it
    was meant to interrupt had finished; and the capture itself had no
    cancellation point (one `time.sleep(stored_time)`).
    """
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 1, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 5.0, 'num_chunks': 4, 'viewed_time': None,
                })
                await _recv_json(ws)

                t0 = asyncio.get_running_loop().time()
                await _send(ws, type='log', duration=5.0, pretrigger=None,
                            test_name='cancel-me')
                await asyncio.sleep(0.5)
                await _send(ws, type='cancel')

                msg = await _recv_json(ws, timeout=5.0)
                elapsed = asyncio.get_running_loop().time() - t0
                assert msg['type'] == 'status', msg
                assert msg['event'] == 'cancelled', msg
                # Stopped early rather than running the 5 s out.
                assert elapsed < 3.0, elapsed

                # Nothing else follows: no log_result, no binary container.
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(ws.recv(), timeout=1.0)

                # The connection is still healthy: a fresh log completes.
                await _send(ws, type='configure', settings={
                    'channels': 1, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 0.1, 'num_chunks': 4, 'viewed_time': None,
                })
                await _recv_json(ws)
                await _send(ws, type='log', duration=0.1, pretrigger=None,
                            test_name='after-cancel')
                meta = await _recv_json(ws, timeout=10.0)
                assert meta['type'] == 'log_result'
                assert meta['testName'] == 'after-cancel'
                frame = await _recv_binary(ws, timeout=10.0)
                assert serve_mod.decode_header(frame)['msgType'] == \
                    serve_mod.MSG_CONTAINER
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_cancel_during_log_leaves_the_monitor_running():
    """Decision (round 11): cancelling a capture does not stop the
    oscilloscope — the operator cancelled a log, not the scope."""
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 1, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 5.0, 'num_chunks': 4, 'viewed_time': None,
                })
                await _recv_json(ws)
                await _send(ws, type='start_monitor')
                await _recv_json(ws)                      # monitoring
                await _recv_binary(ws, timeout=5.0)       # a live frame

                await _send(ws, type='log', duration=5.0, pretrigger=None)
                await asyncio.sleep(0.3)
                await _send(ws, type='cancel')

                saw_cancelled = False
                for _ in range(200):
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    if isinstance(raw, str):
                        msg = json.loads(raw)
                        assert msg.get('type') != 'log_result', msg
                        if msg.get('event') == 'cancelled':
                            saw_cancelled = True
                            break
                assert saw_cancelled
                # Monitor frames keep coming after the cancel.
                await _recv_binary(ws, timeout=5.0)
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_second_log_while_one_is_in_flight_is_refused():
    """One process-global recorder ⇒ one capture at a time."""
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 1, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 2.0, 'num_chunks': 4, 'viewed_time': None,
                })
                await _recv_json(ws)
                await _send(ws, type='log', duration=2.0, pretrigger=None)
                await asyncio.sleep(0.2)
                await _send(ws, type='log', duration=2.0, pretrigger=None)
                err = await _recv_json(ws, timeout=5.0)
                assert err['type'] == 'error'
                assert 'already in flight' in err['message']
                await _send(ws, type='cancel')
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_control_messages_are_answered_during_a_log():
    """The receive loop keeps reading while a capture runs — the
    property that makes cancel possible at all."""
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 1, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 3.0, 'num_chunks': 4, 'viewed_time': None,
                })
                await _recv_json(ws)
                await _send(ws, type='log', duration=3.0, pretrigger=None)
                await asyncio.sleep(0.2)
                await _send(ws, type='hello')
                cap = await _recv_json(ws, timeout=2.0)   # answered mid-log
                assert cap['type'] == 'capabilities'
                await _send(ws, type='cancel')
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_log_error_still_reported_from_the_background_task():
    """Errors raised inside the spawned log task must still produce the
    `error` frame the inline dispatch used to send."""
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='configure', settings={
                    'channels': 1, 'fs': 8000, 'chunk_size': 1000,
                    'stored_time': 0.1, 'num_chunks': 4, 'viewed_time': None,
                })
                await _recv_json(ws)
                # pretrig_samples > chunk_size is rejected by log_data.
                await _send(ws, type='log', duration=0.1,
                            pretrigger={'samples': 5000})
                msg = await _recv_json(ws, timeout=10.0)
                if msg.get('event') == 'armed':
                    msg = await _recv_json(ws, timeout=10.0)
                assert msg['type'] == 'error'
                assert 'pretrig_samples' in msg['message']
        finally:
            await _stop_server(task)
    run_async(scenario)


# ---- capabilities: OS default devices (round 11) -------------------------

def test_capabilities_report_the_default_devices():
    """`default_input` / `default_output` name the OS default, or are
    null when there is none to report."""
    async def scenario():
        _server, task, port = await _start_server()
        try:
            async with connect(_ws_url(port)) as ws:
                await _send(ws, type='hello')
                cap = await _recv_json(ws)
                assert 'default_input' in cap
                assert 'default_output' in cap
                sc = cap['devices']['soundcard']
                for key in ('default_input', 'default_output'):
                    entry = cap[key]
                    if entry is None:
                        continue      # legitimate: no PortAudio default
                    assert entry['driver'] == 'soundcard'
                    assert 0 <= entry['index'] < len(sc)
                    # Matches the enumeration it indexes into.
                    assert entry['name'] == sc[entry['index']]
                    assert 'hostapi' in entry
        finally:
            await _stop_server(task)
    run_async(scenario)


class TestDefaultDeviceResolution:
    """Unit-level guards for `_default_soundcard_devices`, whose whole
    job is to answer "null" rather than guess when PortAudio is absent,
    reports the -1 sentinel, or names an index off the end of the list."""

    def test_none_when_sounddevice_is_absent(self, monkeypatch):
        monkeypatch.setattr(serve_mod.streams, 'sd', None)
        assert serve_mod._default_soundcard_devices() == (None, None)

    def test_none_for_the_minus_one_sentinel(self, monkeypatch):
        monkeypatch.setattr(serve_mod.streams, 'sd',
                            type('SD', (), {'default': type('D', (), {'device': [-1, -1]})})())
        monkeypatch.setattr(serve_mod.streams, 'enumerated_device_names',
                            lambda driver: ['Built-in', 'BlackHole 2ch'])
        monkeypatch.setattr(serve_mod.streams, 'enumerated_device_hostapis',
                            lambda driver: ['Core Audio', 'Core Audio'])
        assert serve_mod._default_soundcard_devices() == (None, None)

    def test_none_when_the_index_is_off_the_end(self, monkeypatch):
        monkeypatch.setattr(serve_mod.streams, 'sd',
                            type('SD', (), {'default': type('D', (), {'device': [7, 0]})})())
        monkeypatch.setattr(serve_mod.streams, 'enumerated_device_names',
                            lambda driver: ['Built-in'])
        monkeypatch.setattr(serve_mod.streams, 'enumerated_device_hostapis',
                            lambda driver: ['Core Audio'])
        din, dout = serve_mod._default_soundcard_devices()
        assert din is None
        assert dout == {'driver': 'soundcard', 'index': 0,
                        'name': 'Built-in', 'hostapi': 'Core Audio'}

    def test_reports_name_and_hostapi(self, monkeypatch):
        monkeypatch.setattr(serve_mod.streams, 'sd',
                            type('SD', (), {'default': type('D', (), {'device': [1, 0]})})())
        monkeypatch.setattr(serve_mod.streams, 'enumerated_device_names',
                            lambda driver: ['Speakers', 'U24XL with SPDIF I/O'])
        monkeypatch.setattr(serve_mod.streams, 'enumerated_device_hostapis',
                            lambda driver: ['Windows WASAPI', 'Windows WDM-KS'])
        din, _ = serve_mod._default_soundcard_devices()
        assert din == {'driver': 'soundcard', 'index': 1,
                       'name': 'U24XL with SPDIF I/O',
                       'hostapi': 'Windows WDM-KS'}

    def test_enumeration_failure_is_not_fatal(self, monkeypatch):
        def boom(driver):
            raise RuntimeError('PortAudio unavailable')
        monkeypatch.setattr(serve_mod.streams, 'sd',
                            type('SD', (), {'default': type('D', (), {'device': [0, 0]})})())
        monkeypatch.setattr(serve_mod.streams, 'enumerated_device_names', boom)
        assert serve_mod._default_soundcard_devices() == (None, None)
