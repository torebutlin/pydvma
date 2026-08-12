"""Cooperative cancellation, and the two-phase armed wait, in `log_data`.

Hardware-free. Two things are being pinned down (round 11):

* **Cancel.** `log_data` accepts a ``threading.Event``; every wait in
  the capture polls it, and setting it stops the capture — including
  whatever stimulus was playing — with a `CaptureCancelled` instead of
  a DataSet. Before this, a capture could not be interrupted at all:
  the free-run path was one ``time.sleep(stored_time)``, so the
  ``pydvma serve`` bridge's ``cancel`` could only ever arrive after the
  fact.
* **Two phases.** ``pretrig_timeout`` bounds the wait for the trigger
  EVENT; the post-trigger data then gets ``stored_time + 5`` seconds of
  its own. It used to bound the whole thing, so any capture longer than
  the timeout "timed out" and silently returned the buffer tail —
  free-run data labelled as triggered.

The two-phase tests drive a REAL `streams.Recorder` (buffers only, no
PortAudio) from a feeder thread standing in for the sounddevice
callback, so `log_data`'s own waiting and slicing are what is under
test, not a reimplementation of them.
"""
import threading
import time

import numpy as np
import pytest

import pydvma as dvma
from pydvma import acquisition, streams


@pytest.fixture(autouse=True)
def _clean_streams_state():
    """Reset the module-level recorder globals around each test."""
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


def _mock_settings(**kwargs):
    base = dict(device_driver='mock', output_device_driver='mock',
                channels=1, fs=8000, chunk_size=100, num_chunks=4,
                viewed_time=None, stored_time=0.2, output_channels=1)
    base.update(kwargs)
    return dvma.MySettings(**base)


# ---- cancellation --------------------------------------------------------

class TestCancelEvent:

    def test_exported_from_the_package(self):
        """Callers need to catch it by name."""
        assert dvma.CaptureCancelled is acquisition.CaptureCancelled
        assert issubclass(acquisition.CaptureCancelled, Exception)

    def test_free_run_returns_promptly_when_already_set(self):
        """A pre-set event must not sit through the whole dwell."""
        s = _mock_settings(stored_time=5.0)
        ev = threading.Event()
        ev.set()
        t0 = time.time()
        with pytest.raises(acquisition.CaptureCancelled):
            dvma.log_data(s, cancel_event=ev)
        assert time.time() - t0 < 1.0

    def test_armed_returns_promptly_when_already_set(self):
        """Same for the armed path, whose phase-1 wait is the long one."""
        s = _mock_settings(stored_time=1.0, pretrig_samples=40,
                           pretrig_threshold=99.0, pretrig_timeout=30.0)
        ev = threading.Event()
        ev.set()
        t0 = time.time()
        with pytest.raises(acquisition.CaptureCancelled):
            dvma.log_data(s, cancel_event=ev)
        assert time.time() - t0 < 1.0

    def test_free_run_cancels_part_way_through(self):
        """Set from another thread mid-dwell: the capture stops there,
        rather than running its 5 seconds out."""
        s = _mock_settings(stored_time=5.0)
        ev = threading.Event()
        threading.Timer(0.2, ev.set).start()
        t0 = time.time()
        with pytest.raises(acquisition.CaptureCancelled):
            dvma.log_data(s, cancel_event=ev)
        elapsed = time.time() - t0
        assert 0.15 < elapsed < 2.0, elapsed

    def test_cancel_stops_a_playing_stimulus(self):
        """A cancelled capture must not leave the AO running."""
        s = _mock_settings(stored_time=5.0, output_channels=1)
        _, y = dvma.signal_generator(s, sig='sweep', T=5.0, amplitude=0.05,
                                     f=[100, 500])
        started = []
        real_setup = streams.setup_output_mock

        def spy(settings, output):
            stream = real_setup(settings, output)
            started.append(stream)
            return stream

        acquisition.streams.setup_output_mock = spy
        try:
            ev = threading.Event()
            threading.Timer(0.2, ev.set).start()
            with pytest.raises(acquisition.CaptureCancelled):
                dvma.log_data(s, output=y, cancel_event=ev)
        finally:
            acquisition.streams.setup_output_mock = real_setup
        assert started, 'stimulus never started — test would prove nothing'
        assert started[0].started is False, 'stimulus left running after cancel'

    def test_no_event_is_unchanged_behaviour(self):
        """The Python API default: a plain blocking capture."""
        s = _mock_settings(stored_time=0.1)
        ds = dvma.log_data(s)
        assert ds.time_data_list[0].time_data.shape == (800, 1)

    def test_unset_event_lets_the_capture_finish(self):
        s = _mock_settings(stored_time=0.1)
        ds = dvma.log_data(s, cancel_event=threading.Event())
        assert ds.time_data_list[0].time_data.shape == (800, 1)


class TestWaitHelper:
    """`acquisition._wait` is the one place the poll cadence lives."""

    def test_returns_false_after_sleeping_without_an_event(self):
        t0 = time.time()
        assert acquisition._wait(0.05) is False
        assert time.time() - t0 >= 0.04

    def test_returns_true_immediately_on_a_set_event(self):
        ev = threading.Event()
        ev.set()
        t0 = time.time()
        assert acquisition._wait(10.0, ev) is True
        assert time.time() - t0 < 0.5

    def test_returns_false_when_the_event_stays_clear(self):
        assert acquisition._wait(0.05, threading.Event()) is False


# ---- two-phase armed wait against a real Recorder ------------------------

class _Feeder(threading.Thread):
    """Stand-in for the sounddevice callback thread.

    Waits until `log_data` has armed the recorder (it sets
    ``trigger_first_detected_message`` immediately after re-running
    ``__init__``, which is what makes this safe against the buffer
    reallocation), then pushes chunks at the real-time cadence. The
    ``quiet_chunks``-th chunk onwards carries an over-threshold signal.
    """

    def __init__(self, rec, settings, quiet_chunks=3, max_chunks=400,
                 ever_loud=True):
        super().__init__(daemon=True)
        self.rec = rec
        self.settings = settings
        self.quiet_chunks = quiet_chunks
        self.max_chunks = max_chunks
        self.ever_loud = ever_loud
        self.stop = threading.Event()
        self.crossing_index = None

    def run(self):
        s = self.settings
        while not self.rec.trigger_first_detected_message:
            if self.stop.is_set():
                return
            time.sleep(0.001)
        period = s.chunk_size / float(s.fs)
        for k in range(self.max_chunks):
            if self.stop.is_set():
                return
            loud = self.ever_loud and k >= self.quiet_chunks
            chunk = np.full((s.chunk_size, s.channels), 0.01, dtype='float32')
            if loud:
                chunk[:, 0] = 1.0
                if self.crossing_index is None:
                    self.crossing_index = k * s.chunk_size
            self.rec.callback(chunk, s.chunk_size, None, None)
            time.sleep(period)


def _install_recorder(monkeypatch, settings):
    """Point `streams.start_stream` at a buffers-only real `Recorder`.

    No PortAudio: `Recorder.__init__` allocates arrays and nothing else,
    and the feeder thread supplies what the sounddevice callback would.
    """
    rec = streams.Recorder(settings)
    rec.audio_stream = object()
    monkeypatch.setattr(streams, 'start_stream', lambda _s: rec)
    monkeypatch.setattr(streams, 'REC', rec)
    return rec


class TestTwoPhaseArmedWait:

    def _settings(self, **kwargs):
        base = dict(device_driver='mock', channels=1, fs=8000, chunk_size=100,
                    num_chunks=4, viewed_time=None, stored_time=0.2,
                    pretrig_samples=40, pretrig_threshold=0.5,
                    pretrig_timeout=3.0)
        base.update(kwargs)
        return dvma.MySettings(**base)

    def test_capture_survives_a_timeout_shorter_than_the_capture(self, monkeypatch):
        """The root-cause regression test.

        ``pretrig_timeout`` (0.5 s) is SHORTER than ``stored_time``
        (0.6 s). Under the old single-phase wait the timeout expired
        before the recorder reported anything, and log_data returned the
        untriggered tail; now phase 1 sees the crossing inside the
        timeout and phase 2 is given its own budget, so the window comes
        back correctly aligned."""
        s = self._settings(stored_time=0.6, pretrig_timeout=0.5)
        rec = _install_recorder(monkeypatch, s)
        feeder = _Feeder(rec, s, quiet_chunks=3)
        feeder.start()
        try:
            ds = dvma.log_data(s, test_name='two-phase')
        finally:
            feeder.stop.set()
            feeder.join(timeout=2.0)

        data = ds.time_data_list[0].time_data
        assert data.shape == (int(s.stored_time * s.fs), 1)
        over = np.abs(data[:, 0]) > s.pretrig_threshold
        assert over.any(), 'no trigger in the returned window'
        assert int(np.argmax(over)) == s.pretrig_samples
        # Pre-trigger context is the real quiet signal, not startup zeros.
        np.testing.assert_allclose(data[:s.pretrig_samples, 0], 0.01,
                                   rtol=0, atol=1e-6)

    def test_trigger_state_is_cleared_and_the_buffer_unfrozen_after(self, monkeypatch):
        """Both flags must come back down together — a `capture_complete`
        left set would keep the stored buffer frozen for good."""
        s = self._settings(stored_time=0.2, pretrig_timeout=2.0)
        rec = _install_recorder(monkeypatch, s)
        feeder = _Feeder(rec, s, quiet_chunks=2)
        feeder.start()
        try:
            dvma.log_data(s)
        finally:
            feeder.stop.set()
            feeder.join(timeout=2.0)

        assert rec.trigger_detected is False
        assert rec.capture_complete is False
        assert rec.trigger_overshoot == 0
        assert np.all(rec.stored_time_data == 0.0)

    def test_timeout_with_no_trigger_returns_the_tail_without_raising(self, monkeypatch):
        """Documented fallback, unchanged: no trigger, no exception."""
        s = self._settings(stored_time=0.2, pretrig_timeout=0.4)
        rec = _install_recorder(monkeypatch, s)
        feeder = _Feeder(rec, s, ever_loud=False)
        feeder.start()
        t0 = time.time()
        try:
            ds = dvma.log_data(s)
        finally:
            feeder.stop.set()
            feeder.join(timeout=2.0)
        elapsed = time.time() - t0
        assert ds.time_data_list[0].time_data.shape == (1600, 1)
        assert rec.trigger_detected is False
        # Bounded by the phase-1 timeout, not by timeout + stored_time.
        assert elapsed < 2.0, elapsed

    def test_cancel_during_the_post_trigger_phase(self, monkeypatch):
        """Phase 2 polls the cancel event too — a long capture can be
        stopped after the trigger has fired."""
        s = self._settings(stored_time=5.0, pretrig_timeout=3.0)
        rec = _install_recorder(monkeypatch, s)
        feeder = _Feeder(rec, s, quiet_chunks=2)
        feeder.start()
        ev = threading.Event()
        threading.Timer(0.5, ev.set).start()
        t0 = time.time()
        try:
            with pytest.raises(acquisition.CaptureCancelled):
                dvma.log_data(s, cancel_event=ev)
        finally:
            feeder.stop.set()
            feeder.join(timeout=2.0)
        assert rec.trigger_detected is True, 'trigger should have fired first'
        assert rec.capture_complete is False
        assert time.time() - t0 < 3.0


class TestSinglePhaseRecorderCompatibility:
    """A recorder without `capture_complete` — i.e. the NI one, and the
    mock — must behave exactly as it did before the two-phase change."""

    def test_mock_pretrigger_timeout_path_is_unchanged(self):
        s = _mock_settings(stored_time=0.1, pretrig_samples=40,
                           pretrig_threshold=99.0, pretrig_timeout=0.3)
        ds = dvma.log_data(s)
        assert ds.time_data_list[0].time_data.shape == (800, 1)
        assert streams.REC.trigger_detected is False
        assert not hasattr(streams.REC, 'capture_complete')

    def test_single_phase_trigger_uses_the_old_second_chunk_slicing(self):
        """With `trigger_detected` already True and the crossing sitting
        in the second-oldest chunk, the returned window is positioned
        from that chunk — the NI convention, untouched."""
        s = _mock_settings(stored_time=0.1, pretrig_samples=40,
                           pretrig_threshold=0.5, pretrig_timeout=2.0)

        # `log_data` builds its own recorder and re-inits it, so plant
        # the signal from a thread once the live one has armed (the mock
        # refills its buffers with a sine and never runs a callback of
        # its own). The crossing goes in the second-oldest chunk, which
        # is where the single-phase convention looks for it.
        planted = {'ok': False}

        def plant():
            deadline = time.time() + 5.0
            while time.time() < deadline:
                rec = streams.REC
                if rec is not None and rec.trigger_first_detected_message:
                    break
                time.sleep(0.001)
            else:
                return
            assert not hasattr(rec, 'capture_complete')
            rec.stored_time_data[:] = 0.01
            rec.stored_time_data[s.chunk_size + 17:, 0] = 1.0
            rec.trigger_detected = True
            planted['ok'] = True

        planter = threading.Thread(target=plant, daemon=True)
        planter.start()
        ds = dvma.log_data(s)
        planter.join(timeout=2.0)
        assert planted['ok'], 'never armed — test would prove nothing'

        data = ds.time_data_list[0].time_data
        assert data.shape == (800, 1)
        over = np.abs(data[:, 0]) > s.pretrig_threshold
        assert over.any()
        assert int(np.argmax(over)) == s.pretrig_samples
