"""Mac/Linux/Windows-runnable tests for the same-device soundcard
output path (duplex stream), with a mocked ``sounddevice`` module.

Background
----------
Playing a stimulus on the SAME soundcard that is capturing used to open
a second, separate ``sd.OutputStream`` next to the recorder's running
``sd.InputStream``. On macOS (measured 2026-08-18, raw sounddevice —
not a pydvma regression) opening that second stream KILLS the running
input stream's callback permanently: the capture returns silence and
never recovers (PaMacCore err=-50). The same hardware handles one
full-duplex stream perfectly.

The fix has two halves, both covered here:

* ``MySettings`` resolves an UNSET soundcard ``output_device_index`` to
  the resolved input device whenever that device can play (it has
  output channels), instead of always falling back to the system
  default output — a stimulus should excite the rig on the interface
  that is measuring it, not the laptop speakers.
* ``streams.Recorder.init_stream`` opens ONE duplex ``sd.Stream`` when
  settings route output onto the capture device
  (``streams.output_shares_input_clock``), and
  ``streams.setup_output_soundcard`` plays through that stream (via
  ``Recorder.queue_output``) instead of opening a second one.
"""

import threading
from types import SimpleNamespace

import numpy as np
import pytest

from pydvma import options
from pydvma import streams


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _device(name, n_in, n_out, hostapi=0):
    return {'name': name, 'max_input_channels': n_in,
            'max_output_channels': n_out, 'hostapi': hostapi,
            'default_samplerate': 48000.0}


def _fake_sd(devices, default=(0, 1)):
    """Stand-in for the ``sounddevice`` module: device table +
    constructor-recording stream classes.
    """
    def query_devices(index=None, kind=None):
        if index is None:
            return devices
        return devices[int(index)]

    class FakeStreamBase:
        def __init__(self, **kw):
            self.kw = kw
            self.active = False
            fake.opened.append(self)

        def start(self):
            self.active = True

        def stop(self):
            self.active = False

        def close(self):
            self.active = False

        @property
        def samplerate(self):
            return self.kw.get('samplerate')

    class FakeInputStream(FakeStreamBase):
        pass

    class FakeDuplexStream(FakeStreamBase):
        pass

    class FakeOutputStream(FakeStreamBase):
        def write(self, data):
            self.written = np.copy(data)

    fake = SimpleNamespace(
        query_devices=query_devices,
        query_hostapis=lambda: [{'name': 'Fake API'}],
        default=SimpleNamespace(device=list(default)),
        PortAudioError=Exception,
        InputStream=FakeInputStream,
        Stream=FakeDuplexStream,
        OutputStream=FakeOutputStream,
        opened=[],
    )
    return fake


# A bench that looks like this Mac: a mic (input-only), a 2i2-like
# duplex interface, and speakers (output-only). System default is
# mic + speakers.
def _bench_sd():
    return _fake_sd(
        devices=[
            _device('built-in mic', 1, 0),
            _device('duplex interface', 4, 2),
            _device('built-in speakers', 0, 2),
        ],
        default=(0, 2),
    )


def _settings(**overrides):
    """MySettings-like namespace with everything Recorder touches."""
    base = dict(
        device_driver='soundcard',
        device_index=1,
        channels=4,
        fs=48000,
        chunk_size=8,
        num_chunks=4,
        stored_time=0.01,
        pretrig_samples=None,
        VmaxSC=1.0,
        output_device_driver='soundcard',
        output_device_index=1,
        output_channels=2,
        output_fs=48000,
        device_name=None,
        device_hostapi=None,
        device_full_info=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def no_pins(monkeypatch):
    """Silence the per-capture hardware pins (clock / format / volume):
    they talk to real CoreAudio / Windows COM and are irrelevant here.
    """
    monkeypatch.setattr(streams.Recorder, '_pin_hardware_clock',
                        lambda self, s: setattr(self, 'clock_note', None))
    monkeypatch.setattr(streams.Recorder, '_pin_hardware_format',
                        lambda self, s: None)
    monkeypatch.setattr(streams.Recorder, '_pin_input_volume',
                        lambda self, s: None)


# ---------------------------------------------------------------------------
# MySettings: unset output follows a duplex-capable input device
# ---------------------------------------------------------------------------

class TestUnsetOutputResolution:

    def test_follows_input_device_when_it_can_play(self, monkeypatch):
        monkeypatch.setattr(options, 'sd', _bench_sd())
        s = options.MySettings(device_driver='soundcard', device_index=1,
                               channels=2)
        assert s.output_device_index == 1

    def test_falls_back_to_default_output_for_mic_only_input(self, monkeypatch):
        monkeypatch.setattr(options, 'sd', _bench_sd())
        s = options.MySettings(device_driver='soundcard', device_index=0,
                               channels=1)
        assert s.output_device_index == 2

    def test_explicit_output_index_is_respected(self, monkeypatch):
        monkeypatch.setattr(options, 'sd', _bench_sd())
        s = options.MySettings(device_driver='soundcard', device_index=1,
                               channels=2, output_device_index=2)
        assert s.output_device_index == 2


# ---------------------------------------------------------------------------
# Recorder.init_stream: duplex decision
# ---------------------------------------------------------------------------

class TestInitStreamDuplexDecision:

    def test_same_device_opens_one_duplex_stream(self, monkeypatch, no_pins):
        fake = _bench_sd()
        monkeypatch.setattr(streams, 'sd', fake)
        s = _settings()

        rec = streams.Recorder(s)
        rec.init_stream(s)

        assert isinstance(rec.audio_stream, fake.Stream)
        assert rec.audio_stream.kw['channels'] == (4, 2)
        assert rec.audio_stream.kw['device'] == (1, 1)
        assert rec.audio_stream.kw['callback'] == rec.duplex_callback
        assert rec.duplex_output_channels == 2
        assert rec.audio_stream.active

    def test_different_output_device_keeps_plain_input_stream(
            self, monkeypatch, no_pins):
        fake = _bench_sd()
        monkeypatch.setattr(streams, 'sd', fake)
        s = _settings(output_device_index=2)

        rec = streams.Recorder(s)
        rec.init_stream(s)

        assert isinstance(rec.audio_stream, fake.InputStream)
        assert not getattr(rec, 'duplex_output_channels', None)

    def test_unset_output_index_keeps_plain_input_stream(
            self, monkeypatch, no_pins):
        # Defensive: MySettings resolves the index, but namespace-style
        # callers may leave it None — never guess duplex from None.
        fake = _bench_sd()
        monkeypatch.setattr(streams, 'sd', fake)
        s = _settings(output_device_index=None)

        rec = streams.Recorder(s)
        rec.init_stream(s)

        assert isinstance(rec.audio_stream, fake.InputStream)

    def test_duplex_output_channels_clamped_to_device(self, monkeypatch,
                                                      no_pins, capsys):
        fake = _bench_sd()
        monkeypatch.setattr(streams, 'sd', fake)
        s = _settings(output_channels=8)   # device has 2

        rec = streams.Recorder(s)
        rec.init_stream(s)

        assert rec.audio_stream.kw['channels'] == (4, 2)
        assert s.output_channels == 2
        assert 'WARNING' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Duplex playback engine (queue_output / duplex_callback / cancel_output)
# ---------------------------------------------------------------------------

def _duplex_recorder(settings):
    rec = streams.Recorder(settings)
    rec.duplex_output_channels = settings.output_channels
    return rec


def _drive(rec, n_calls, chunk, in_ch, out_ch):
    """Simulate PortAudio: call the duplex callback n_calls times with a
    constant input chunk, collecting what the recorder plays.
    """
    played = []
    in_chunk = np.full((chunk, in_ch), 0.25, dtype='float32')
    for _ in range(n_calls):
        out = np.empty((chunk, out_ch), dtype='float32')
        out.fill(99.0)  # poison: the callback must overwrite every frame
        rec.duplex_callback(in_chunk, out, chunk, None, None)
        played.append(out.copy())
    return np.concatenate(played, axis=0)


class TestDuplexPlayback:

    def test_idle_callback_plays_silence(self):
        s = _settings(chunk_size=8)
        rec = _duplex_recorder(s)
        played = _drive(rec, 3, 8, 4, 2)
        assert np.all(played == 0.0)

    def test_queued_output_is_played_then_padded_with_zeros(self):
        s = _settings(chunk_size=8)
        rec = _duplex_recorder(s)
        data = np.arange(20 * 2, dtype='float32').reshape(20, 2) / 100.0

        done = rec.queue_output(data)
        played = _drive(rec, 4, 8, 4, 2)   # 32 frames > 20 queued

        assert np.allclose(played[:20], data)
        assert np.all(played[20:] == 0.0)
        assert done.is_set()

    def test_input_side_still_fills_buffers(self):
        s = _settings(chunk_size=8)
        rec = _duplex_recorder(s)
        _drive(rec, 2, 8, 4, 2)
        # last 16 rows of the oscilloscope buffer hold the input chunk
        # scaled by VmaxSC (=1.0)
        assert np.allclose(rec.osc_time_data[-16:, :], 0.25)

    def test_cancel_output_stops_playback_and_releases_waiter(self):
        s = _settings(chunk_size=8)
        rec = _duplex_recorder(s)
        data = np.ones((80, 2), dtype='float32')

        done = rec.queue_output(data)
        _drive(rec, 1, 8, 4, 2)
        rec.cancel_output()
        played_after = _drive(rec, 2, 8, 4, 2)

        assert np.all(played_after == 0.0)
        assert done.is_set()

    def test_narrow_data_padded_to_stream_channels(self):
        s = _settings(chunk_size=8)
        rec = _duplex_recorder(s)
        data = np.ones((8, 1), dtype='float32')

        rec.queue_output(data)
        played = _drive(rec, 1, 8, 4, 2)

        assert np.all(played[:, 0] == 1.0)
        assert np.all(played[:, 1] == 0.0)

    def test_wide_data_sliced_with_warning(self, capsys):
        s = _settings(chunk_size=8)
        rec = _duplex_recorder(s)
        data = np.ones((8, 3), dtype='float32')

        rec.queue_output(data)
        played = _drive(rec, 1, 8, 4, 2)

        assert played.shape[1] == 2
        assert np.all(played[:, :2] == 1.0)
        assert 'WARNING' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# setup_output_soundcard: routing
# ---------------------------------------------------------------------------

@pytest.fixture
def preserve_rec():
    prior = streams.REC
    try:
        yield
    finally:
        streams.REC = prior


class TestSetupOutputRouting:

    def _running_duplex_rec(self, fake, settings):
        rec = streams.Recorder(settings)
        rec.duplex_output_channels = settings.output_channels
        rec.audio_stream = fake.Stream(samplerate=settings.fs)
        rec.audio_stream.start()
        return rec

    def test_same_device_routes_through_running_duplex_stream(
            self, monkeypatch, preserve_rec):
        fake = _bench_sd()
        monkeypatch.setattr(streams, 'sd', fake)
        s = _settings()
        streams.REC = self._running_duplex_rec(fake, s)
        n_streams_before = len(fake.opened)

        adapter = streams.setup_output_soundcard(s)

        assert len(fake.opened) == n_streams_before  # no second stream
        assert hasattr(adapter, 'write')
        assert hasattr(adapter, 'stop')
        assert hasattr(adapter, 'close')

    def test_adapter_write_blocks_until_played(self, monkeypatch,
                                               preserve_rec):
        fake = _bench_sd()
        monkeypatch.setattr(streams, 'sd', fake)
        s = _settings(chunk_size=8)
        rec = self._running_duplex_rec(fake, s)
        streams.REC = rec

        adapter = streams.setup_output_soundcard(s)
        data = np.ones((24, 2), dtype='float32')

        t = threading.Thread(target=adapter.write, args=(data,))
        t.start()
        # drive the "audio thread" until the write unblocks
        deadline = 24
        while t.is_alive() and deadline > 0:
            _drive(rec, 1, 8, 4, 2)
            t.join(timeout=0.05)
            deadline -= 1
        assert not t.is_alive(), 'adapter.write never unblocked'

    def test_adapter_write_released_by_cancel_event(self, monkeypatch,
                                                    preserve_rec):
        # A bridge cancel must stop a blocked stimulus wait even when
        # NO callback ever drains the queue (covers the race where the
        # cancel lands before playback starts).
        fake = _bench_sd()
        monkeypatch.setattr(streams, 'sd', fake)
        s = _settings(chunk_size=8)
        rec = self._running_duplex_rec(fake, s)
        streams.REC = rec

        cancel = threading.Event()
        adapter = streams.setup_output_soundcard(s, cancel_event=cancel)
        data = np.ones((10 * 48000, 2), dtype='float32')  # ~10 s worth

        t = threading.Thread(target=adapter.write, args=(data,))
        t.start()
        cancel.set()
        t.join(timeout=5)
        assert not t.is_alive(), 'cancel_event did not release write'
        # pending stimulus was cancelled: next callback plays silence
        played = _drive(rec, 1, 8, 4, 2)
        assert np.all(played == 0.0)

    def test_adapter_stop_cancels_pending_output(self, monkeypatch,
                                                 preserve_rec):
        fake = _bench_sd()
        monkeypatch.setattr(streams, 'sd', fake)
        s = _settings(chunk_size=8)
        rec = self._running_duplex_rec(fake, s)
        streams.REC = rec

        adapter = streams.setup_output_soundcard(s)
        rec.queue_output(np.ones((800, 2), dtype='float32'))
        adapter.stop()
        played = _drive(rec, 1, 8, 4, 2)
        assert np.all(played == 0.0)

    def test_different_device_opens_separate_output_stream(
            self, monkeypatch, preserve_rec):
        fake = _bench_sd()
        monkeypatch.setattr(streams, 'sd', fake)
        s = _settings(output_device_index=2)
        streams.REC = self._running_duplex_rec(fake, _settings())

        out = streams.setup_output_soundcard(s)

        assert isinstance(out, fake.OutputStream)
        assert out.kw['device'] == 2

    def test_no_running_stream_opens_plain_output_stream(
            self, monkeypatch, preserve_rec):
        fake = _bench_sd()
        monkeypatch.setattr(streams, 'sd', fake)
        s = _settings()
        streams.REC = None

        out = streams.setup_output_soundcard(s)

        assert isinstance(out, fake.OutputStream)

    def test_same_device_without_duplex_refuses_actionably(
            self, monkeypatch, preserve_rec):
        # An input-only stream is live on the device and output targets
        # it: a second stream would silence the capture (macOS). Refuse
        # with a remedy rather than corrupt the measurement.
        fake = _bench_sd()
        monkeypatch.setattr(streams, 'sd', fake)
        s = _settings()
        rec = streams.Recorder(s)
        rec.duplex_output_channels = None
        rec.audio_stream = fake.InputStream(samplerate=s.fs)
        rec.audio_stream.start()
        streams.REC = rec

        with pytest.raises(ValueError, match='same device'):
            streams.setup_output_soundcard(s)
