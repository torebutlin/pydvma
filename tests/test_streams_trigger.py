"""Soundcard pretrigger semantics — `streams.Recorder`'s two-phase trigger.

Hardware-free: `streams.Recorder(settings)` allocates its buffers in
``__init__`` and never touches PortAudio until ``init_stream``, so the
whole state machine can be driven by handing synthetic float32 chunks
straight to `Recorder.callback` — exactly the shape sounddevice
delivers, at whatever cadence the test likes.

What is being pinned down (round 11):

* ``trigger_detected`` means **a crossing was seen**, and fires within
  one chunk of it. It used to be set from the SECOND-OLDEST chunk of
  the ring, so it only went True ~``stored_time`` seconds after the
  event — "capture complete" wearing the label "triggered", which made
  the bridge's ``status/triggered`` arrive at the end of the capture
  and made ``pretrig_timeout`` a race against the capture length.
* ``capture_complete`` means the window is full, and freezes the buffer.
* The window, sliced the way `acquisition.log_data` slices it, puts the
  first above-threshold sample at exactly index ``pretrig_samples``,
  whatever offset the crossing had within its chunk.
* The threshold is compared to VmaxSC-SCALED data (volts on a
  calibrated interface, full-scale units on an uncalibrated one).
"""
import numpy as np
import pytest

import pydvma as dvma
from pydvma import acquisition, streams


def _settings(**kwargs):
    """Soundcard settings for the recorder under test (no device opened)."""
    base = dict(
        device_driver='soundcard', channels=1, fs=8000, chunk_size=100,
        num_chunks=4, viewed_time=None, stored_time=0.1,
        pretrig_samples=40, pretrig_threshold=0.5, pretrig_channel=0,
    )
    base.update(kwargs)
    return dvma.MySettings(**base)


def _feed(rec, chunk):
    """Hand one (chunk_size, channels) float32 block to the callback."""
    rec.callback(np.asarray(chunk, dtype='float32'), len(chunk), None, None)


def _quiet_chunk(settings, amplitude=0.01):
    """A below-threshold chunk (deterministic, not random)."""
    n = settings.chunk_size
    t = np.arange(n)
    return np.tile((amplitude * np.sin(2 * np.pi * t / n))[:, None],
                   (1, settings.channels))


def _sliced_record(rec):
    """The window `acquisition.log_data` would return, sliced its way."""
    number_samples = int(rec.settings.stored_time * rec.settings.fs)
    buf = np.copy(rec.stored_time_data)
    end = buf.shape[0] - int(rec.trigger_overshoot)
    return buf[end - number_samples:end, :]


class TestTriggerDetection:

    def test_stays_false_below_threshold(self):
        """Noise under the threshold must never arm the trigger."""
        s = _settings(pretrig_threshold=0.5)
        rec = streams.Recorder(s)
        rng = np.random.default_rng(0)
        for _ in range(40):
            _feed(rec, rng.uniform(-0.4, 0.4,
                                   size=(s.chunk_size, s.channels)))
        assert rec.trigger_detected is False
        assert rec.capture_complete is False

    def test_fires_in_the_chunk_that_carries_the_crossing(self):
        """The whole point of the round-11 fix: `trigger_detected` marks
        the EVENT, not the end of the capture. The capture here is 800
        samples (8 chunks) long, so the old second-oldest-chunk check
        would not have reported it for another 8 callbacks."""
        s = _settings()
        rec = streams.Recorder(s)
        for _ in range(5):                      # build real history
            _feed(rec, _quiet_chunk(s))
        assert rec.trigger_detected is False

        crossing = _quiet_chunk(s)
        crossing[60:, 0] = 1.0
        _feed(rec, crossing)
        assert rec.trigger_detected is True     # same callback, not later
        # ...and the capture is NOT yet complete: only 40 post-trigger
        # samples of the 760 wanted have arrived.
        assert rec.capture_complete is False

    def test_ignores_a_crossing_before_there_is_pretrigger_history(self):
        """A crossing in the very first chunk would leave the returned
        window's pre-trigger context made of the buffer's startup zeros,
        so detection waits until `pretrig_samples` of real data exist."""
        s = _settings(pretrig_samples=40)
        rec = streams.Recorder(s)
        loud = np.ones((s.chunk_size, s.channels), dtype='float32')
        _feed(rec, loud)
        assert rec.trigger_detected is False
        # Second chunk: a full chunk (100 >= 40) of real history now sits
        # behind it, so the same signal does trigger.
        _feed(rec, loud)
        assert rec.trigger_detected is True

    def test_free_run_never_triggers_or_freezes(self):
        """With `pretrig_samples=None` there is no trigger to detect and
        the stored buffer must keep scrolling forever."""
        s = _settings(pretrig_samples=None)
        rec = streams.Recorder(s)
        loud = np.ones((s.chunk_size, s.channels), dtype='float32')
        for _ in range(12):
            _feed(rec, loud)
        assert rec.trigger_detected is False
        assert rec.capture_complete is False
        # Still tracking the newest data: the tail is the last chunk fed.
        np.testing.assert_allclose(rec.stored_time_data[-s.chunk_size:, 0], 1.0)


class TestCaptureCompletion:

    def test_completes_once_the_window_is_full_and_then_freezes(self):
        s = _settings()                          # 800 samples wanted
        rec = streams.Recorder(s)
        for _ in range(5):
            _feed(rec, _quiet_chunk(s))
        crossing = _quiet_chunk(s)
        crossing[0, 0] = 1.0                     # crossing at chunk start
        _feed(rec, crossing)

        # 800 - 40 = 760 post-trigger samples wanted; 100 arrived with the
        # crossing chunk, so it takes 7 more (700) to cover the remaining
        # 660 — overshooting the window's end by 40 samples, which is
        # exactly what `trigger_overshoot` is for.
        for k in range(6):
            _feed(rec, _quiet_chunk(s))
            assert rec.capture_complete is False, 'completed early at %d' % k
        _feed(rec, _quiet_chunk(s))
        assert rec.capture_complete is True
        assert rec.trigger_overshoot == 40

        frozen = np.copy(rec.stored_time_data)
        _feed(rec, np.full((s.chunk_size, s.channels), 9.0, dtype='float32'))
        np.testing.assert_array_equal(rec.stored_time_data, frozen)
        # The oscilloscope buffer keeps running while the capture is held.
        np.testing.assert_allclose(rec.osc_time_data[-s.chunk_size:, 0], 9.0)

    @pytest.mark.parametrize('offset', [0, 1, 37, 99])
    @pytest.mark.parametrize('pretrig_samples', [1, 40, 100])
    def test_alignment_is_sample_exact_whatever_the_chunk_offset(
            self, offset, pretrig_samples):
        """`record[pretrig_samples]` is the FIRST sample over threshold,
        and the window is the exact stretch of the input stream around
        it — checked against the samples actually fed, sample for
        sample, not just at the trigger index.

        The crossing generally lands mid-chunk while the buffer can only
        freeze on a chunk boundary; `trigger_overshoot` is what makes
        the two line up. The sweep covers both ends of a chunk (first
        sample, last sample) and the extremes of the pre-trigger window
        (1 sample, a full chunk)."""
        s = _settings(pretrig_samples=pretrig_samples, chunk_size=100,
                      stored_time=0.1)
        rec = streams.Recorder(s)
        number_samples = int(s.stored_time * s.fs)

        # Every sample fed is unique (a slow ramp) so the returned window
        # can be located in the input stream unambiguously.
        fed = []
        counter = {'n': 0}

        def feed(loud=False):
            n = s.chunk_size
            k = np.arange(counter['n'], counter['n'] + n)
            counter['n'] += n
            chunk = np.tile((1e-4 * k)[:, None], (1, s.channels))
            if loud:
                chunk[:, 0] += 5.0
            fed.append(chunk)
            _feed(rec, chunk)

        for _ in range(5):
            feed()
        # The crossing chunk: quiet up to `offset`, over threshold after.
        n = s.chunk_size
        k = np.arange(counter['n'], counter['n'] + n)
        counter['n'] += n
        crossing_chunk = np.tile((1e-4 * k)[:, None], (1, s.channels))
        crossing_chunk[offset:, 0] += 5.0
        crossing_index = len(fed) * s.chunk_size + offset
        fed.append(crossing_chunk)
        _feed(rec, crossing_chunk)

        # Feed until the recorder says it has the whole window (bounded
        # so a regression fails the test instead of hanging).
        for _ in range(3 + number_samples // s.chunk_size):
            if rec.capture_complete:
                break
            feed(loud=True)
        assert rec.capture_complete is True
        assert 0 <= rec.trigger_overshoot < s.chunk_size

        record = _sliced_record(rec)
        assert record.shape == (number_samples, s.channels)
        over = np.abs(record[:, 0]) > s.pretrig_threshold
        assert over.any()
        assert int(np.argmax(over)) == s.pretrig_samples

        # ...and the window is the right stretch of the stream, whole.
        stream = np.concatenate(fed, axis=0)
        start = crossing_index - s.pretrig_samples
        np.testing.assert_allclose(
            record, stream[start:start + number_samples, :], rtol=0, atol=1e-6)


class TestThresholdUnits:
    """`pretrig_threshold` is compared AFTER the VmaxSC scaling, so its
    meaning follows the calibration. Documented on `MySettings` and
    `Recorder.callback`; pinned here because it is the kind of thing
    that silently changes when a device gains a voltage scale."""

    #: ESI U24 XL-ish: 1.0 normalised = 13.79 V at the jack.
    VMAX = 13.79

    def _run(self, vmaxsc, threshold, normalised_amplitude):
        s = _settings(VmaxSC=vmaxsc, pretrig_threshold=threshold)
        rec = streams.Recorder(s)
        for _ in range(3):
            _feed(rec, np.zeros((s.chunk_size, s.channels), dtype='float32'))
        chunk = np.full((s.chunk_size, s.channels), normalised_amplitude,
                        dtype='float32')
        _feed(rec, chunk)
        return rec.trigger_detected

    def test_calibrated_device_reads_the_threshold_as_volts(self):
        """0.05 on a calibrated card is 50 mV — 0.4% of full scale — so
        an input far too small to mean anything still trips it."""
        assert self._run(self.VMAX, 0.05, 0.01) is True     # 138 mV
        assert self._run(1.0, 0.05, 0.01) is False          # 1% of FS

    def test_scaling_the_threshold_restores_the_full_scale_meaning(self):
        """Multiplying the threshold by VmaxSC gets "5% of full scale"
        back — the recipe for anyone porting a threshold across a
        calibration."""
        assert self._run(self.VMAX, 0.05 * self.VMAX, 0.01) is False
        assert self._run(self.VMAX, 0.05 * self.VMAX, 0.10) is True


class TestPretriggerSettingsGuards:

    def test_pretrig_samples_beyond_capture_length_is_rejected(self):
        """No post-trigger data left to record. Caught at construction."""
        with pytest.raises(ValueError, match='post-trigger'):
            dvma.MySettings(device_driver='soundcard', fs=8000,
                            chunk_size=1000, stored_time=0.1,
                            pretrig_samples=800)

    def test_equal_to_capture_length_is_also_rejected(self):
        with pytest.raises(ValueError, match='post-trigger'):
            dvma.MySettings(device_driver='soundcard', fs=8000,
                            chunk_size=1000, stored_time=0.05,
                            pretrig_samples=400)

    def test_one_below_the_capture_length_is_allowed(self):
        s = dvma.MySettings(device_driver='soundcard', fs=8000,
                            chunk_size=1000, stored_time=0.05,
                            pretrig_samples=399)
        assert s.pretrig_samples == 399

    def test_log_data_rechecks_a_mutated_pairing(self):
        """`serve` sets `stored_time` and `pretrig_samples` on a live
        settings object, so the pairing is only final at capture time."""
        s = dvma.MySettings(device_driver='mock', fs=8000, chunk_size=1000,
                            stored_time=1.0, pretrig_samples=500)
        s.stored_time = 0.05          # now 400 samples, under the window
        with pytest.raises(ValueError, match='post-trigger'):
            dvma.log_data(s)


class TestCaptureFinishedDuckTyping:
    """`acquisition._capture_finished` is how the two-phase wait stays
    compatible with the NI recorder, which is hardware-verified and
    deliberately untouched."""

    class _SinglePhase:
        """Stand-in for `Recorder_NI_nidaqmx` / `MockRecorder`: sets
        `trigger_detected` only once the post-trigger data is in."""
        def __init__(self, triggered):
            self.trigger_detected = triggered

    def test_single_phase_recorder_answers_from_trigger_detected(self):
        assert acquisition._capture_finished(self._SinglePhase(True)) is True
        assert acquisition._capture_finished(self._SinglePhase(False)) is False

    def test_ni_recorder_class_has_no_second_phase(self):
        """Guard against the two-phase flags being copied onto the NI
        recorder by a future edit — its callback semantics are verified
        on hardware that cannot be re-tested from a Mac."""
        assert not hasattr(streams.Recorder_NI_nidaqmx, 'capture_complete')

    def test_two_phase_recorder_answers_from_capture_complete(self):
        s = _settings()
        rec = streams.Recorder(s)
        rec.trigger_detected = True
        rec.capture_complete = False
        assert acquisition._capture_finished(rec) is False
        rec.capture_complete = True
        assert acquisition._capture_finished(rec) is True
