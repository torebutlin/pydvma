"""Round-12 regression tests: the soundcard recorder's circular buffers,
startup-priming filter, overflow accounting, buffer-fill wait and stream
reuse.

Background (2026-08-20, Scarlett 2i2 live on a Windows bench + Rigol
DG1022Z as a phase-trackable source):

* The old callback SHIFTED the whole ``stored_time_data`` array by one
  chunk on every callback — O(buffer) work against a ``chunk_size/fs``
  budget. A 30 s x 48 kHz x 2 ch capture at the default chunk of 100 is
  a ~23 MB memmove against a 2 ms budget: PortAudio answered by
  dropping input, which quietly destroyed TF coherence (the round-12
  lab report). The buffers are now circular rings with O(chunk) writes.
* A freshly opened stream begins with the host's startup latency — and
  on some hosts (WDM-KS measured) a burst of EXACT-zero priming chunks
  — which put ~0.05-0.1 s of zeros at the front of every first capture.
  Fixed three ways, each covered here: the priming filter skips leading
  all-zero chunks (bounded), ``log_data`` tops its dwell up until the
  buffer really holds a full window (`_wait_for_buffer_fill`), and
  ``start_stream`` REUSES a running matching stream so back-to-back
  captures inherit real history.
* PortAudio's ``input_overflow`` flag was silently ignored; it is now
  counted and reported (``acquisition.LAST_CAPTURE_OVERFLOWS``).

All hardware-free: the Recorder is driven buffers-only (no PortAudio),
and the reuse tests run against a fake ``sounddevice`` module.
"""
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from pydvma import acquisition, options, streams


# ---------------------------------------------------------------------------
# Fakes (pattern shared with tests/test_soundcard_duplex_output.py)
# ---------------------------------------------------------------------------

def _device(name, n_in, n_out, hostapi=0):
    return {'name': name, 'max_input_channels': n_in,
            'max_output_channels': n_out, 'hostapi': hostapi,
            'default_samplerate': 48000.0}


def _fake_sd(devices, default=(0, 1)):
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

    fake = SimpleNamespace(
        query_devices=query_devices,
        query_hostapis=lambda: [{'name': 'Fake API'}],
        default=SimpleNamespace(device=list(default)),
        PortAudioError=Exception,
        InputStream=type('FakeInputStream', (FakeStreamBase,), {}),
        Stream=type('FakeDuplexStream', (FakeStreamBase,), {}),
        OutputStream=type('FakeOutputStream', (FakeStreamBase,), {}),
        opened=[],
    )
    return fake


def _settings(**overrides):
    """MySettings-like namespace with everything Recorder touches.
    Output routed to a DIFFERENT device so the stream is input-only."""
    base = dict(
        device_driver='soundcard',
        device_index=0,
        channels=2,
        fs=8000,
        chunk_size=8,
        num_chunks=4,
        stored_time=0.004,           # 32 samples -> 4-chunk window, 6-chunk ring
        pretrig_samples=None,
        pretrig_threshold=0.5,
        pretrig_channel=0,
        VmaxSC=1.0,
        output_device_driver='soundcard',
        output_device_index=1,
        output_channels=2,
        output_fs=8000,
        device_name=None,
        device_hostapi=None,
        device_full_info=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def no_pins(monkeypatch):
    monkeypatch.setattr(streams.Recorder, '_pin_hardware_clock',
                        lambda self, s: setattr(self, 'clock_note', None))
    monkeypatch.setattr(streams.Recorder, '_pin_hardware_format',
                        lambda self, s: None)
    monkeypatch.setattr(streams.Recorder, '_pin_input_volume',
                        lambda self, s: None)


@pytest.fixture
def clean_globals():
    saved = (streams.REC, streams.REC_SC)
    streams.REC = None
    streams.REC_SC = None
    yield
    streams.REC, streams.REC_SC = saved


def _chunk(settings, value):
    """A constant-valued float32 chunk shaped like the callback's input."""
    return np.full((settings.chunk_size, settings.channels), value,
                   dtype='float32')


def _ramp_chunk(settings, start):
    """A chunk whose samples count upwards from ``start`` (per channel:
    ch1 = ch0 + 1000) so buffer ordering is checkable sample-exactly."""
    n = settings.chunk_size
    col = np.arange(start, start + n, dtype='float32')
    return np.stack([col, col + 1000.0], axis=1)


# ---------------------------------------------------------------------------
# Circular buffers
# ---------------------------------------------------------------------------

class TestRingBuffers:

    def test_partial_fill_orders_zeros_first(self):
        s = _settings()
        rec = streams.Recorder(s)
        rec.callback(_ramp_chunk(s, 0), s.chunk_size, None, None)
        rec.callback(_ramp_chunk(s, 8), s.chunk_size, None, None)
        stored = rec.stored_time_data
        assert stored.shape == (rec.stored_num_chunks * s.chunk_size, 2)
        # everything before the two real chunks is the initial zeros
        assert np.all(stored[:-16] == 0.0)
        np.testing.assert_array_equal(stored[-16:, 0], np.arange(16))
        np.testing.assert_array_equal(stored[-16:, 1], np.arange(16) + 1000)

    def test_wraparound_keeps_the_newest_window_in_order(self):
        s = _settings()
        rec = streams.Recorder(s)
        n_ring = rec.stored_num_chunks              # 6 chunks
        total = 3 * n_ring + 1                      # wrap nearly three times
        for k in range(total):
            rec.callback(_ramp_chunk(s, k * s.chunk_size), s.chunk_size,
                         None, None)
        stored = rec.stored_time_data
        n = stored.shape[0]
        expect_end = total * s.chunk_size
        np.testing.assert_array_equal(
            stored[:, 0], np.arange(expect_end - n, expect_end))
        # the oscilloscope ring wraps identically
        osc = rec.osc_time_data
        np.testing.assert_array_equal(
            osc[:, 0], np.arange(expect_end - osc.shape[0], expect_end))

    def test_armed_freeze_stops_stored_but_not_osc(self):
        s = _settings(pretrig_samples=8, stored_time=0.002)  # 16-sample window
        rec = streams.Recorder(s)
        # quiet history, then a crossing, then post-trigger data
        for k in range(4):
            rec.callback(_chunk(s, 0.01), s.chunk_size, None, None)
        rec.callback(_chunk(s, 1.0), s.chunk_size, None, None)
        rec.callback(_chunk(s, 0.02), s.chunk_size, None, None)
        assert rec.capture_complete
        frozen = rec.stored_time_data
        rec.callback(_chunk(s, 9.9), s.chunk_size, None, None)
        np.testing.assert_array_equal(rec.stored_time_data, frozen)
        assert np.any(rec.osc_time_data == np.float32(9.9))

    def test_zero_stored_clears_the_ring_itself(self):
        s = _settings()
        rec = streams.Recorder(s)
        rec.callback(_chunk(s, 0.5), s.chunk_size, None, None)
        assert np.any(rec.stored_time_data != 0.0)
        rec.zero_stored()
        assert np.all(rec.stored_time_data == 0.0)

    def test_writing_to_the_property_cannot_corrupt_the_ring(self):
        """The property returns a copy — the documented reason
        acquisition zeroes through `zero_stored`, never by assignment."""
        s = _settings()
        rec = streams.Recorder(s)
        rec.callback(_chunk(s, 0.5), s.chunk_size, None, None)
        view = rec.stored_time_data
        view[:] = 123.0
        assert not np.any(rec.stored_time_data == 123.0)


# ---------------------------------------------------------------------------
# Startup-priming filter
# ---------------------------------------------------------------------------

class TestPrimingFilter:

    def test_leading_zero_chunks_are_skipped_until_real_signal(self):
        s = _settings()
        rec = streams.Recorder(s)
        rec._awaiting_first_signal = True            # as init_stream arms it
        rec._startup_zero_chunks = 0
        for _ in range(3):
            rec.callback(_chunk(s, 0.0), s.chunk_size, None, None)
        assert rec.chunks_seen == 0                  # nothing counted
        assert np.all(rec.stored_time_data == 0.0)
        rec.callback(_chunk(s, 0.25), s.chunk_size, None, None)
        assert rec.chunks_seen == 1
        assert not rec._awaiting_first_signal
        # the real chunk landed at the ring tail
        assert np.all(rec.stored_time_data[-s.chunk_size:] == np.float32(0.25))

    def test_the_oscilloscope_still_shows_the_priming_zeros(self):
        """The scope is unfiltered — it shows what the host delivers."""
        s = _settings()
        rec = streams.Recorder(s)
        rec._awaiting_first_signal = True
        rec.callback(_chunk(s, 0.0), s.chunk_size, None, None)
        # the osc ring advanced (its write position moved) even though the
        # stored ring did not
        assert rec._osc_pos == s.chunk_size
        assert rec._stored_pos == 0

    def test_skip_is_bounded_for_a_genuinely_silent_input(self):
        s = _settings(fs=64)                          # bound = 64/8 = 8 chunks
        rec = streams.Recorder(s)
        rec._awaiting_first_signal = True
        rec._startup_zero_chunks = 0
        for _ in range(12):
            rec.callback(_chunk(s, 0.0), s.chunk_size, None, None)
        # after the ~1 s bound the zeros count as data (silence IS data)
        assert not rec._awaiting_first_signal
        assert rec.chunks_seen == 12 - 8

    def test_reinit_does_not_rearm_the_filter(self):
        """Only a stream OPEN primes; `log_data`'s armed-path re-__init__
        on a running stream must not skip real-but-quiet data."""
        s = _settings()
        rec = streams.Recorder(s)
        rec._awaiting_first_signal = True
        rec.callback(_chunk(s, 0.25), s.chunk_size, None, None)
        assert not rec._awaiting_first_signal
        rec.__init__(s)
        assert not rec._awaiting_first_signal


# ---------------------------------------------------------------------------
# Overflow accounting
# ---------------------------------------------------------------------------

class _Flags(SimpleNamespace):
    def __bool__(self):
        return bool(self.input_overflow or self.output_underflow)


def _flags(input_overflow=False, output_underflow=False):
    return _Flags(input_overflow=input_overflow,
                  output_underflow=output_underflow)


class TestOverflowCounting:

    def test_input_overflow_flags_are_counted(self):
        s = _settings()
        rec = streams.Recorder(s)
        rec.callback(_chunk(s, 0.1), s.chunk_size, None, None)
        rec.callback(_chunk(s, 0.1), s.chunk_size, None, _flags(input_overflow=True))
        rec.callback(_chunk(s, 0.1), s.chunk_size, None, _flags(input_overflow=True))
        rec.callback(_chunk(s, 0.1), s.chunk_size, None, _flags(output_underflow=True))
        assert rec.input_overflows == 2
        assert rec.output_underflows == 1

    def test_counter_is_carried_across_reinit(self):
        """`log_data`'s armed path re-__init__s the buffers mid-capture;
        the overflow baseline taken before that must stay valid."""
        s = _settings()
        rec = streams.Recorder(s)
        rec.callback(_chunk(s, 0.1), s.chunk_size, None, _flags(input_overflow=True))
        rec.__init__(s)
        assert rec.input_overflows == 1

    def test_log_data_reports_overflows_seen_during_the_capture(self, monkeypatch, capsys):
        s = options.MySettings(device_driver='mock', channels=2, fs=800,
                               chunk_size=8, num_chunks=4, stored_time=0.05,
                               viewed_time=None)
        rec = streams.Recorder(s)
        rec.audio_stream = object()
        monkeypatch.setattr(streams, 'start_stream', lambda _s: rec)
        monkeypatch.setattr(streams, 'REC', rec)

        stop = threading.Event()

        def feed():
            while not stop.is_set():
                rec.callback(_chunk(s, 0.1), s.chunk_size, None,
                             _flags(input_overflow=True))
                time.sleep(s.chunk_size / float(s.fs))

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        try:
            acquisition.log_data(s)
        finally:
            stop.set()
            feeder.join(timeout=2.0)
        assert acquisition.LAST_CAPTURE_OVERFLOWS > 0
        assert 'dropped input' in capsys.readouterr().out

    def test_clean_capture_resets_the_module_flag(self, monkeypatch):
        acquisition.LAST_CAPTURE_OVERFLOWS = 7        # stale from "before"
        s = options.MySettings(device_driver='mock', channels=2, fs=800,
                               chunk_size=8, num_chunks=4, stored_time=0.05,
                               viewed_time=None)
        rec = streams.Recorder(s)
        rec.audio_stream = object()
        monkeypatch.setattr(streams, 'start_stream', lambda _s: rec)
        monkeypatch.setattr(streams, 'REC', rec)
        stop = threading.Event()

        def feed():
            while not stop.is_set():
                rec.callback(_chunk(s, 0.1), s.chunk_size, None, None)
                time.sleep(s.chunk_size / float(s.fs))

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        try:
            acquisition.log_data(s)
        finally:
            stop.set()
            feeder.join(timeout=2.0)
        assert acquisition.LAST_CAPTURE_OVERFLOWS == 0


# ---------------------------------------------------------------------------
# _wait_for_buffer_fill
# ---------------------------------------------------------------------------

class TestWaitForBufferFill:

    def test_returns_immediately_without_chunks_seen(self):
        rec = SimpleNamespace(settings=SimpleNamespace(chunk_size=8, fs=8000))
        t0 = time.time()
        acquisition._wait_for_buffer_fill(rec, None, 10_000_000)
        assert time.time() - t0 < 0.5

    def test_satisfied_count_returns_after_one_chunk_of_slack(self):
        s = _settings()
        rec = streams.Recorder(s)
        rec.chunks_seen = 1000
        t0 = time.time()
        acquisition._wait_for_buffer_fill(rec, s, 32)
        assert time.time() - t0 < 0.5

    def test_waits_for_the_shortfall(self):
        s = _settings()
        rec = streams.Recorder(s)
        rec.chunks_seen = 0

        def fill_soon():
            time.sleep(0.15)
            rec.chunks_seen = 100

        threading.Thread(target=fill_soon, daemon=True).start()
        t0 = time.time()
        acquisition._wait_for_buffer_fill(rec, s, 32)
        elapsed = time.time() - t0
        assert 0.1 < elapsed < 2.0

    def test_grace_expiry_warns_and_returns(self, monkeypatch, capsys):
        monkeypatch.setattr(acquisition, 'BUFFER_FILL_GRACE', 0.2)
        s = _settings()
        rec = streams.Recorder(s)
        rec.chunks_seen = 0
        t0 = time.time()
        acquisition._wait_for_buffer_fill(rec, s, 32)
        assert time.time() - t0 < 2.0
        assert 'fewer samples' in capsys.readouterr().out

    def test_cancel_raises(self):
        s = _settings()
        rec = streams.Recorder(s)
        rec.chunks_seen = 0
        ev = threading.Event()
        ev.set()
        with pytest.raises(acquisition.CaptureCancelled):
            acquisition._wait_for_buffer_fill(rec, s, 32, cancel_event=ev)


# ---------------------------------------------------------------------------
# Stream reuse in start_stream
# ---------------------------------------------------------------------------

class TestStreamReuse:

    def _bench(self):
        return _fake_sd(
            devices=[_device('iface A', 2, 0), _device('speakers', 0, 2)],
            default=(0, 1),
        )

    def test_matching_settings_reuse_the_running_stream(self, monkeypatch,
                                                        no_pins, clean_globals):
        fake = self._bench()
        monkeypatch.setattr(streams, 'sd', fake)
        s1 = _settings()
        streams.start_stream(s1)
        first = streams.REC_SC
        assert len(fake.opened) == 1
        streams.start_stream(_settings())
        assert streams.REC_SC is first
        assert streams.REC is first
        assert len(fake.opened) == 1                  # no second stream

    def test_streams_open_with_high_latency(self, monkeypatch, no_pins,
                                            clean_globals):
        fake = self._bench()
        monkeypatch.setattr(streams, 'sd', fake)
        streams.start_stream(_settings())
        assert fake.opened[0].kw['latency'] == 'high'

    def test_changed_stored_time_rebuilds(self, monkeypatch, no_pins,
                                          clean_globals):
        fake = self._bench()
        monkeypatch.setattr(streams, 'sd', fake)
        streams.start_stream(_settings())
        first = streams.REC_SC
        streams.start_stream(_settings(stored_time=0.008))
        assert streams.REC_SC is not first
        assert len(fake.opened) == 2

    def test_changed_vmax_rebuilds(self, monkeypatch, no_pins, clean_globals):
        fake = self._bench()
        monkeypatch.setattr(streams, 'sd', fake)
        streams.start_stream(_settings())
        first = streams.REC_SC
        streams.start_stream(_settings(VmaxSC=13.8))
        assert streams.REC_SC is not first

    def test_inplace_mutation_of_the_held_settings_still_rebuilds(
            self, monkeypatch, no_pins, clean_globals):
        """The serve bridge mutates ONE settings object between logs.
        After a reuse pass that object can be the very one the recorder
        holds, so the signature must be frozen at open time — a live
        compare would be object-vs-itself and always match, keeping a
        ring sized for the old duration."""
        fake = self._bench()
        monkeypatch.setattr(streams, 'sd', fake)
        s = _settings()
        streams.start_stream(s)
        streams.start_stream(s)                       # reuse: recorder holds s
        first = streams.REC_SC
        assert first.settings is s
        s.stored_time = 0.016                         # mutate in place
        streams.start_stream(s)
        assert streams.REC_SC is not first            # rebuilt, not reused

    def test_dead_stream_rebuilds(self, monkeypatch, no_pins, clean_globals):
        fake = self._bench()
        monkeypatch.setattr(streams, 'sd', fake)
        streams.start_stream(_settings())
        first = streams.REC_SC
        first.audio_stream.active = False
        streams.start_stream(_settings())
        assert streams.REC_SC is not first
