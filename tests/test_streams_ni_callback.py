"""Unit tests for the NI recorder's callback backlog drain.

Mac-runnable (no hardware, no nidaqmx): builds a bare
``Recorder_NI_nidaqmx`` via ``object.__new__`` and feeds it chunks
through a fake reader + fake ``in_stream``, mimicking the DAQmx
every-N-samples event with a queue of already-acquired samples.

Motivation (2026-07-07 Windows hardware session): the rolling buffers
advance one chunk per processed chunk, so when the host stalls
(paging, USB contention, busy CPU) and callbacks lag the hardware,
buffer time falls behind real time and a pretrigger crossing can miss
its timeout even though it physically fired — observed live on a
USB-6212 and USB-6003 while an npm install saturated the machine. The
drain loop in ``stream_audio_callback`` consumes the whole backlog per
event, bounding the lag to about one callback latency.
"""
import numpy as np
import pytest

import pydvma as dvma
from pydvma import streams


CHUNK = 100
CHANNELS = 1


class FakeInStream:
    def __init__(self, queue):
        self._queue = queue

    @property
    def avail_samp_per_chan(self):
        return len(self._queue) * CHUNK


class FakeTask:
    def __init__(self, queue):
        self.in_stream = FakeInStream(queue)


class FakeReader:
    """Pops one queued (channels, chunk) block per read call."""

    def __init__(self, queue):
        self._queue = queue
        self.reads = 0

    def read_many_sample(self, buffer, number_of_samples_per_channel,
                         timeout=10.0):
        assert number_of_samples_per_channel == CHUNK
        if not self._queue:
            raise RuntimeError('read past end of queued data')
        buffer[:] = self._queue.pop(0)
        self.reads += 1


def _chunk(value):
    """A (channels, chunk) block of constant ``value`` volts."""
    return np.full((CHANNELS, CHUNK), float(value))


def _bare_recorder(queue, pretrig=True):
    """Recorder_NI_nidaqmx with fakes in place of DAQmx objects."""
    s = dvma.MySettings(
        device_driver='nidaq', channels=CHANNELS, fs=5000,
        chunk_size=CHUNK, stored_time=0.3,
        pretrig_samples=50 if pretrig else None,
        pretrig_threshold=0.2, pretrig_channel=0,
    )
    rec = object.__new__(streams.Recorder_NI_nidaqmx)
    rec.settings = s
    rec.trigger_detected = False
    rec.trigger_first_detected_message = False  # skip MESSAGE print path
    rec._closing = False
    rec.osc_time_data = np.zeros((s.num_chunks * CHUNK, CHANNELS))
    stored_num_chunks = 2 + int(np.ceil(s.stored_time * s.fs / CHUNK))
    rec.stored_time_data = np.zeros((stored_num_chunks * CHUNK, CHANNELS))
    rec._read_buffer = np.zeros((CHANNELS, CHUNK))
    rec._reader = FakeReader(queue)
    rec.audio_stream = FakeTask(queue)
    return rec


def test_single_chunk_no_backlog():
    """With nothing queued beyond the event's own chunk, exactly one
    chunk is read and appended."""
    queue = [_chunk(0.05)]
    rec = _bare_recorder(queue)
    rec.stream_audio_callback()
    assert rec._reader.reads == 1
    assert np.all(rec.stored_time_data[-CHUNK:, 0] == 0.05)


def test_backlog_fully_drained_in_one_event():
    """All queued chunks are consumed by a single callback event, so
    buffer time catches up to real time despite missed events."""
    queue = [_chunk(0.01 * (i + 1)) for i in range(10)]
    rec = _bare_recorder(queue)
    rec.stream_audio_callback()
    assert rec._reader.reads == 10
    assert len(queue) == 0
    # Most recent chunk sits at the buffer tail.
    assert np.all(rec.stored_time_data[-CHUNK:, 0] == pytest.approx(0.10))


def test_drain_preserves_pretrigger_freeze():
    """A crossing that rolls into stored[chunk:2*chunk] mid-drain sets
    trigger_detected and freezes the stored buffer for the rest of the
    backlog, exactly as if the chunks had arrived one event each."""
    stored_chunks = 17  # 2 + ceil(0.3*5000/100)
    # One loud chunk followed by enough quiet chunks to roll it into
    # the check window [chunk:2*chunk], then several more that must
    # NOT displace it once frozen.
    queue = ([_chunk(1.0)]
             + [_chunk(0.0)] * (stored_chunks - 2)
             + [_chunk(0.0)] * 5)
    rec = _bare_recorder(queue)
    rec.stream_audio_callback()
    assert rec.trigger_detected
    # Loud chunk frozen in the check window, not rolled out by the
    # 5 post-trigger chunks.
    assert np.all(rec.stored_time_data[CHUNK:2 * CHUNK, 0] == 1.0)
    # The osc (monitor) buffer keeps advancing after the freeze.
    assert np.all(rec.osc_time_data[-CHUNK:, 0] == 0.0)
    # Everything queued was still consumed (reads keep pace with the
    # hardware even after the trigger).
    assert len(queue) == 0


def test_read_error_stops_event_cleanly():
    """A failed read prints and returns without raising into the
    driver thread and without touching the buffers."""
    rec = _bare_recorder([])  # empty queue -> FakeReader raises
    rec.stream_audio_callback()  # must not raise
    assert np.all(rec.stored_time_data == 0.0)


def test_closing_flag_stops_callback_immediately():
    """Once end_stream marks the recorder as closing, a straggler
    callback event must not read at all (the task handle may already
    be gone)."""
    queue = [_chunk(0.05)] * 3
    rec = _bare_recorder(queue)
    rec._closing = True
    rec.stream_audio_callback()
    assert rec._reader.reads == 0
    assert np.all(rec.stored_time_data == 0.0)
