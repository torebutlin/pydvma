"""Round-13 regression tests: the NI recorder's circular buffers,
overflow accounting and frozen reuse signature.

Background (2026-09-04, cDAQ lab report — 12.8 kHz x 5 ch x 60 s
captures "with 10-30 s silent gaps and drifting channel voltages",
coherence collapsing to a lobed comb; reproduced live on the bench
cDAQ-9174 the same day):

* ``Recorder_NI_nidaqmx._process_chunk`` SHIFTED the whole stored
  buffer by one chunk per callback, per channel — O(buffer) against a
  ``chunk_size/fs`` budget. The lab geometry is a ~30 MB strided
  memmove per 7.8 ms chunk (99 % of budget on a fast desktop, over
  budget on a laptop); once the reader lags by more than the DAQmx
  buffer (~7.8 s) the driver overwrites unread samples, keeps the task
  running and fails roughly every other read with -200279, so the
  capture comes back time-compressed: leading zeros, the pre-/post-
  stimulus quiet spliced into the window, the sweep at twice its rate.
  The buffers are now circular rings with O(chunk) writes — the same
  design as the round-12 soundcard recorder.
* Those -200279 read errors were printed and otherwise ignored: no
  count, no per-capture warning, so the browser toast that round-12
  wired for PortAudio never fired on NI. They are now counted in
  ``input_overflows`` and reported through ``acquisition.log_data``.
* ``start_stream`` compared the running task against a settings object
  that could BE its own after a reuse pass (serve mutates
  ``stored_time`` in place), so a longer capture could be served from
  a ring sized for the previous one. The reuse key is now the
  signature frozen at task build, as on the soundcard side.

All hardware-free: the recorder is driven buffers-only through the same
fake reader/task pattern as tests/test_streams_ni_callback.py, and the
reuse test runs ``start_stream`` against stubbed build/teardown hooks.
"""
import numpy as np
import pytest

import pydvma as dvma
from pydvma import acquisition, streams


CHUNK = 100
CHANNELS = 3


class _FakeInStream:
    def __init__(self, queue):
        self._queue = queue

    @property
    def avail_samp_per_chan(self):
        return len(self._queue) * CHUNK


class _FakeTask:
    def __init__(self, queue):
        self.in_stream = _FakeInStream(queue)


class _DaqReadError(Exception):
    """Shape of ``nidaqmx.errors.DaqReadError``: carries ``error_code``."""
    def __init__(self, code, msg='daq read error'):
        super().__init__(msg)
        self.error_code = code


class _FakeReader:
    """Pops one queued item per read: an ``(channels, chunk)`` block, or an
    exception instance to raise in its place."""

    def __init__(self, queue):
        self._queue = queue
        self.reads = 0

    def read_many_sample(self, buffer, number_of_samples_per_channel,
                         timeout=10.0):
        assert number_of_samples_per_channel == CHUNK
        if not self._queue:
            raise RuntimeError('read past end of queued data')
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        buffer[:] = item
        self.reads += 1


def _chunk(value):
    """A (channels, chunk) block whose channel c reads ``value + c``."""
    return (np.full((CHANNELS, CHUNK), float(value))
            + np.arange(CHANNELS, dtype=float)[:, None])


def _bare_recorder(queue, stored_time=0.3, pretrig=False):
    s = dvma.MySettings(
        device_driver='nidaq', channels=CHANNELS, fs=5000,
        chunk_size=CHUNK, stored_time=stored_time,
        pretrig_samples=50 if pretrig else None,
        pretrig_threshold=0.2, pretrig_channel=0,
    )
    rec = object.__new__(streams.Recorder_NI_nidaqmx)
    rec.settings = s
    rec.trigger_detected = False
    rec.trigger_first_detected_message = False
    rec._closing = False
    rec.input_overflows = 0
    rec._overflow_notes_printed = 0
    rec._alloc_buffers()
    rec._read_buffer = np.zeros((CHANNELS, CHUNK))
    rec._reader = _FakeReader(queue)
    rec.audio_stream = _FakeTask(queue)
    return rec


# ---------------------------------------------------------------------------
# Ring semantics
# ---------------------------------------------------------------------------

class TestRing:
    def test_buffers_are_rings_behind_copy_properties(self):
        rec = _bare_recorder([])
        assert rec.stored_time_data.shape == (rec.stored_num_chunks * CHUNK,
                                              CHANNELS)
        assert rec.osc_time_data.shape == (rec.settings.num_chunks * CHUNK,
                                           CHANNELS)
        # Copies, not views: mutating the returned array never reaches
        # the recorder ...
        view = rec.stored_time_data
        view[:] = 123.0
        assert not np.any(rec.stored_time_data == 123.0)
        # ... and there is no setter — the old ``rec.stored_time_data =
        # zeros`` idiom must fail loudly rather than silently detach.
        with pytest.raises(AttributeError):
            rec.stored_time_data = np.zeros_like(view)

    def test_time_order_is_preserved_across_the_wrap(self):
        """Feed more chunks than the ring holds: the unrolled view is the
        most recent ``stored_num_chunks`` chunks, oldest first, every
        channel intact — i.e. exactly what the shifting buffer returned."""
        rec = _bare_recorder([])
        n_chunks = rec.stored_num_chunks
        total = n_chunks + 7            # wraps the write pointer
        for k in range(total):
            rec._process_chunk(_chunk(k).T)
        out = rec.stored_time_data
        for j in range(n_chunks):
            k = total - n_chunks + j     # chunk index expected in slot j
            blk = out[j * CHUNK:(j + 1) * CHUNK]
            assert np.all(blk == _chunk(k).T)
        assert rec.chunks_seen == total
        # The oscilloscope ring keeps its own (shorter) recent window.
        osc = rec.osc_time_data
        assert np.all(osc[-CHUNK:] == _chunk(total - 1).T)

    def test_process_chunk_copies_the_read_buffer(self):
        """The reader reuses one DAQmx buffer; the ring must hold its own
        copy of each chunk, not a view the next read overwrites."""
        rec = _bare_recorder([])
        buf = np.zeros((CHANNELS, CHUNK))
        buf[:] = 1.0
        rec._process_chunk(buf.T)
        buf[:] = 2.0
        assert np.all(rec.stored_time_data[-CHUNK:] == 1.0)

    def test_zero_stored_clears_the_ring(self):
        rec = _bare_recorder([])
        for k in range(5):
            rec._process_chunk(_chunk(k + 1).T)
        assert np.any(rec.stored_time_data != 0.0)
        rec.zero_stored()
        assert np.all(rec.stored_time_data == 0.0)
        # The write position is untouched: the next chunk still lands
        # at the tail of the unrolled view.
        rec._process_chunk(_chunk(9).T)
        assert np.all(rec.stored_time_data[-CHUNK:] == _chunk(9).T)

    def test_write_cost_does_not_grow_with_stored_time(self):
        """The whole point: a 60 s ring must cost the same per chunk as a
        0.3 s one (O(chunk), not O(buffer)). Measured as work, not wall
        time — the ring write touches ``chunk_size`` rows whatever the
        ring length."""
        short = _bare_recorder([], stored_time=0.3)
        long_ = _bare_recorder([], stored_time=60.0)
        assert long_.stored_num_chunks > 100 * short.stored_num_chunks
        calls = []
        orig = streams.Recorder._ring_write

        def counting(ring, pos, data):
            calls.append(data.shape[0])
            return orig(ring, pos, data)

        streams.Recorder._ring_write = staticmethod(counting)
        try:
            short._process_chunk(_chunk(1).T)
            long_._process_chunk(_chunk(1).T)
        finally:
            streams.Recorder._ring_write = staticmethod(orig)
        # Two writes (osc + stored) of exactly one chunk each, both sizes.
        assert calls == [CHUNK, CHUNK, CHUNK, CHUNK]

    def test_alloc_buffers_resets_the_rings(self):
        """`_build_and_start_ai_task` re-allocates after a DAQmx rate
        coercion and `log_data` re-inits before arming: both must start
        from empty rings and a zero chunk count."""
        rec = _bare_recorder([])
        for k in range(3):
            rec._process_chunk(_chunk(k + 1).T)
        rec.settings.fs = 5120.0
        rec._alloc_buffers()
        assert rec.chunks_seen == 0
        assert np.all(rec.stored_time_data == 0.0)
        assert rec._stored_pos == 0 and rec._osc_pos == 0


# ---------------------------------------------------------------------------
# Pretrigger contract: two-phase since 2026-09-10 (crossing → completion),
# window slicing sample-exact on hardware — unchanged
# ---------------------------------------------------------------------------

class TestPretriggerWindow:
    def test_check_window_is_the_second_oldest_chunk(self):
        """`log_data` slices the crossing from ``stored[chunk:2*chunk]`` of
        the unrolled buffer; the ring must COMPLETE from exactly that
        chunk, including after the write pointer has wrapped — while the
        crossing itself is flagged the moment it arrives, so the serve
        bridge can say "triggered" at once (round 15: an impulse test on
        a PCI-6220 read "waiting for trigger" for its whole length)."""
        rec = _bare_recorder([], pretrig=True)
        n = rec.stored_num_chunks
        # Prime past the wrap with quiet chunks, then one loud chunk.
        for _ in range(n + 3):
            rec._process_chunk(np.zeros((CHUNK, CHANNELS)))
        loud = np.zeros((CHUNK, CHANNELS))
        loud[10, 0] = 1.0
        rec._process_chunk(loud)
        assert rec.trigger_detected          # phase 1: the crossing, in the NEWEST chunk
        assert not rec.capture_complete      # ... but the window is not in yet
        assert acquisition._capture_finished(rec) is False
        # The stored buffer keeps rolling while the post-trigger half
        # arrives: the crossing becomes second-oldest after n-3 more
        # quiet chunks (ring holds n chunks).
        for _ in range(n - 3):
            rec._process_chunk(np.zeros((CHUNK, CHANNELS)))
        assert not rec.capture_complete
        rec._process_chunk(np.zeros((CHUNK, CHANNELS)))
        assert rec.capture_complete          # phase 2: complete, and frozen
        assert acquisition._capture_finished(rec) is True
        window = rec.stored_time_data[CHUNK:2 * CHUNK, 0]
        assert window[10] == 1.0 and np.count_nonzero(window) == 1
        # Frozen: further chunks no longer move the stored buffer ...
        before = rec.stored_time_data.copy()
        rec._process_chunk(np.full((CHUNK, CHANNELS), 5.0))
        assert np.array_equal(rec.stored_time_data, before)
        # ... while the oscilloscope keeps going.
        assert np.all(rec.osc_time_data[-CHUNK:] == 5.0)

    def test_unarmed_recorder_never_flags_a_crossing(self):
        rec = _bare_recorder([], pretrig=False)
        loud = np.zeros((CHUNK, CHANNELS))
        loud[3, 0] = 9.0
        for _ in range(3):
            rec._process_chunk(loud)
        assert not rec.trigger_detected and not rec.capture_complete
        assert np.all(rec.stored_time_data[-CHUNK:, 0] == loud[:, 0])   # still rolling

    def test_reset_lowers_both_phases_without_inventing_overshoot(self):
        """`acquisition._reset_trigger_state` must not create the soundcard
        recorder's `trigger_overshoot` here: `log_data` tells the two
        recorders' window slicing apart by that attribute."""
        rec = _bare_recorder([], pretrig=True)
        rec.trigger_detected = True
        rec.capture_complete = True
        acquisition._reset_trigger_state(rec)
        assert rec.trigger_detected is False and rec.capture_complete is False
        assert not hasattr(rec, 'trigger_overshoot')


# ---------------------------------------------------------------------------
# Overflow accounting
# ---------------------------------------------------------------------------

class TestOverflowAccounting:
    def test_daqmx_overflow_reads_are_counted_not_fatal(self, capsys):
        """A -200279 read: counted, printed ONCE, the event returns
        cleanly and later reads keep filling the ring."""
        queue = [_chunk(1), _DaqReadError(-200279), _DaqReadError(-200279),
                 _chunk(2), _DaqReadError(-200279), _chunk(3)]
        rec = _bare_recorder(queue)
        # An event's drain loop stops at a failed read (the buffer was
        # just reset, so there is nothing left to drain); DAQmx keeps
        # firing events, so drive one per remaining item.
        events = 0
        while queue and events < 20:
            rec.stream_audio_callback()
            events += 1
        assert rec.input_overflows == 3
        assert rec._reader.reads == 3
        assert np.all(rec.stored_time_data[-CHUNK:] == _chunk(3).T)
        out = capsys.readouterr().out
        assert out.count('input overflow') == 1

    def test_other_read_errors_are_printed_not_counted(self, capsys):
        queue = [_DaqReadError(-50405, 'no transfer in progress')]
        rec = _bare_recorder(queue)
        rec.stream_audio_callback()
        assert rec.input_overflows == 0
        assert 'nidaqmx read error' in capsys.readouterr().out

    def test_closing_recorder_swallows_overflow_quietly(self, capsys):
        rec = _bare_recorder([_DaqReadError(-200279)])
        rec._closing = True
        rec.stream_audio_callback()
        assert rec.input_overflows == 0
        assert capsys.readouterr().out == ''

    def test_log_data_reports_ni_overflows(self, monkeypatch, capsys):
        """`log_data` diffs ``input_overflows`` around the dwell for ANY
        recorder exposing it — the NI recorder now does, so overflows
        during a capture reach ``LAST_CAPTURE_OVERFLOWS`` (and the serve
        toast). Simulated on the mock recorder: the counter is bumped
        while the dwell is in progress."""
        s = dvma.MySettings(device_driver='mock', channels=1, fs=1000,
                            chunk_size=100, stored_time=0.2)
        orig_wait = acquisition._wait

        def wait_and_drop(duration, cancel_event=None, poll=0.05):
            if duration >= 0.2:               # the stored_time dwell
                streams.REC.input_overflows = (
                    getattr(streams.REC, 'input_overflows', 0) + 5)
            return orig_wait(duration, cancel_event, poll)

        monkeypatch.setattr(acquisition, '_wait', wait_and_drop)
        acquisition.LAST_CAPTURE_OVERFLOWS = 0
        try:
            dvma.log_data(s)
            assert acquisition.LAST_CAPTURE_OVERFLOWS == 5
            assert 'dropped input 5 time' in capsys.readouterr().out
        finally:
            if streams.REC is not None:
                streams.REC.end_stream()
            acquisition.LAST_CAPTURE_OVERFLOWS = 0


# ---------------------------------------------------------------------------
# Frozen reuse signature
# ---------------------------------------------------------------------------

class TestFrozenReuseSignature:
    """`start_stream` decides reuse-vs-rebuild from ``_open_signature``
    (frozen at task build), never from ``REC_NI.settings`` — which after
    a reuse pass IS the caller's object."""

    @pytest.fixture
    def stubbed_ni(self, monkeypatch):
        calls = []

        def fake_init(self, settings):
            self.settings = settings
            self.trigger_detected = False
            self.trigger_first_detected_message = False
            if not hasattr(self, 'audio_stream'):
                self.audio_stream = None
                self._open_signature = None
                self._requested_fs = None
            self._alloc_buffers()

        def fake_init_stream(self, settings, _input_=True, _output_=False):
            calls.append('build')
            self.audio_stream = object()
            self._requested_fs = float(settings.fs)
            self._open_signature = streams._ni_settings_signature(settings)

        def fake_end_stream(self):
            calls.append('end')
            self.audio_stream = None

        monkeypatch.setattr(streams, 'ni', object())   # "installed"
        monkeypatch.setattr(streams.Recorder_NI_nidaqmx, '__init__', fake_init)
        monkeypatch.setattr(streams.Recorder_NI_nidaqmx, 'init_stream', fake_init_stream)
        monkeypatch.setattr(streams.Recorder_NI_nidaqmx, 'end_stream', fake_end_stream)
        monkeypatch.setattr(streams, 'REC_NI', None)
        monkeypatch.setattr(streams, 'REC', None)
        return calls

    def _settings(self, stored_time):
        return dvma.MySettings(device_driver='nidaq', device_index=0,
                               channels=2, fs=5000, chunk_size=CHUNK,
                               stored_time=stored_time)

    def test_same_settings_reuse(self, stubbed_ni):
        s = self._settings(1.0)
        streams.start_stream(s)
        streams.start_stream(self._settings(1.0))
        assert stubbed_ni == ['build']
        assert streams.REC is streams.REC_NI

    def test_mutated_shared_object_rebuilds(self, stubbed_ni):
        """The lab path: serve hands log_data the recorder's OWN settings
        object with ``stored_time`` changed in place. A live compare saw
        the object against itself and reused a ring sized for the old
        duration; the frozen signature sees the change."""
        s = self._settings(1.0)
        streams.start_stream(s)
        assert streams.REC_NI.settings is s
        s.stored_time = 60.0            # in-place, on the SAME object
        streams.start_stream(s)
        assert stubbed_ni == ['build', 'end', 'build']
        assert streams.REC_NI.stored_num_chunks == 2 + int(np.ceil(60.0 * 5000 / CHUNK))

    def test_requested_rate_after_coercion_still_reuses(self, stubbed_ni):
        """A caller re-asking for the ORIGINAL (pre-coercion) rate
        describes the same hardware config: reuse, adopting the coerced
        rate — the existing contract, now keyed on the frozen signature
        the task was built with (post-coercion)."""
        s = self._settings(1.0)
        streams.start_stream(s)
        # Simulate the DAQmx coercion the real build performs.
        rec = streams.REC_NI
        rec._requested_fs = 5000.0
        rec.settings.fs = 5120.0
        rec._open_signature = streams._ni_settings_signature(rec.settings)
        again = self._settings(1.0)      # asks for 5000 again
        streams.start_stream(again)
        assert stubbed_ni == ['build']
        assert again.fs == 5120.0


# ---------------------------------------------------------------------------
# Buffer-fill wait now applies to NI too
# ---------------------------------------------------------------------------

def test_wait_for_buffer_fill_honours_ni_chunk_count(monkeypatch):
    """With ``chunks_seen`` on the NI recorder, `_wait_for_buffer_fill`
    waits for the ring to hold the window (a fresh task normally has it
    at once; the wait is a bounded safety net)."""
    rec = _bare_recorder([])
    for _ in range(rec.stored_num_chunks - 2):
        rec._process_chunk(_chunk(1).T)
    monkeypatch.setattr(acquisition, 'BUFFER_FILL_GRACE', 0.05)
    number_samples = int(rec.settings.stored_time * rec.settings.fs)
    acquisition._wait_for_buffer_fill(rec, rec.settings, number_samples)
    # Enough chunks: returns without warning.
    assert 'fewer samples' not in acquisition.MESSAGE
    short = _bare_recorder([])
    acquisition.MESSAGE = ''
    acquisition._wait_for_buffer_fill(short, short.settings, number_samples)
    assert 'fewer samples' in acquisition.MESSAGE


def test_osc_samples_seen_counts_delivered_chunks():
    """The NI twin of `Recorder.osc_samples_seen`: advanced by every
    chunk `_process_chunk` writes into the scope ring, kept across a
    buffer re-allocation, read by the serve monitor."""
    rec = _bare_recorder([])
    assert rec.osc_samples_seen == 0
    for k in range(3):
        rec._process_chunk(_chunk(k).T)
    assert rec.osc_samples_seen == 3 * CHUNK
    rec._alloc_buffers()
    assert rec.osc_samples_seen == 3 * CHUNK
    rec._process_chunk(_chunk(4).T)
    assert rec.osc_samples_seen == 4 * CHUNK
