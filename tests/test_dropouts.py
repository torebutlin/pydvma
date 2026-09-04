"""Exact-digital-silence dropouts inside a capture (round 14, 2026-09-04).

A USB audio driver that loses a packet zero-fills it and PortAudio never
raises ``input_overflow``, so the round-12 integrity counter stays at
zero while the capture carries stretches of exact zeros (measured on a
Scarlett 2i2 4th Gen: 8 frames to 188 ms, both channels at once).
`acquisition.exact_zero_dropouts` finds them, and `log_data` reports
them through `acquisition.LAST_CAPTURE_DROPOUTS` exactly as it reports
overflows.
"""
import numpy as np
import pytest

import pydvma as dvma
from pydvma import acquisition, streams


def _live_noise(n, channels=2, seed=0):
    rng = np.random.default_rng(seed)
    return 0.05 * rng.standard_normal((n, channels))


class TestExactZeroDropouts:
    def test_clean_record_is_clean(self):
        assert acquisition.exact_zero_dropouts(_live_noise(4000), 8000.0) == (0, 0.0)

    def test_counts_runs_and_their_total_duration(self):
        y = _live_noise(8000)
        y[1000:1040, :] = 0.0        # 40 frames
        y[5000:5008, :] = 0.0        # exactly DROPOUT_MIN_RUN frames
        n, seconds = acquisition.exact_zero_dropouts(y, 8000.0)
        assert n == 2
        assert seconds == pytest.approx(48 / 8000.0)

    def test_short_runs_and_single_channel_zeros_are_ignored(self):
        y = _live_noise(8000)
        y[1000:1007, :] = 0.0        # one frame short of the threshold
        y[3000:3100, 0] = 0.0        # one channel only: not a digital event
        assert acquisition.exact_zero_dropouts(y, 8000.0) == (0, 0.0)

    def test_leading_zeros_are_not_a_dropout(self):
        """Startup shortfall is `_wait_for_buffer_fill`'s business."""
        y = _live_noise(8000)
        y[:500, :] = 0.0
        assert acquisition.exact_zero_dropouts(y, 8000.0) == (0, 0.0)
        y[6000:6100, :] = 0.0
        assert acquisition.exact_zero_dropouts(y, 8000.0)[0] == 1

    def test_trailing_run_counts(self):
        y = _live_noise(8000)
        y[7900:, :] = 0.0
        assert acquisition.exact_zero_dropouts(y, 8000.0) == (1, 100 / 8000.0)

    def test_silent_record_is_not_a_fault(self):
        """A 16-bit host with nothing plugged in delivers zeros; there is
        no coherence in a silent record to protect."""
        y = 1e-5 * _live_noise(8000)
        y[1000:2000, :] = 0.0
        assert acquisition.exact_zero_dropouts(y, 8000.0, full_scale=1.0) == (0, 0.0)
        # ...but the same record against a tiny full scale is live.
        assert acquisition.exact_zero_dropouts(y, 8000.0, full_scale=1e-4)[0] == 1

    def test_one_dimensional_input(self):
        y = 0.05 * np.ones(1000)
        y[100:120] = 0.0
        assert acquisition.exact_zero_dropouts(y, 1000.0) == (1, 0.02)

    def test_empty_input(self):
        assert acquisition.exact_zero_dropouts(np.zeros((0, 2)), 8000.0) == (0, 0.0)


def _mock_settings():
    return dvma.MySettings(device_driver='mock', channels=2, fs=8000,
                           stored_time=0.1, chunk_size=100, num_chunks=4)


def test_log_data_reports_dropouts_in_the_returned_window(monkeypatch):
    """A zero-filled stretch inside the mock recorder's buffer surfaces as
    `LAST_CAPTURE_DROPOUTS` after `log_data`, like an overflow would."""
    real_init = streams.MockRecorder.init_stream

    def init_with_gap(self, settings, *args, **kwargs):
        real_init(self, settings, *args, **kwargs)
        # The returned window is the LAST stored_time*fs = 800 frames of a
        # 1000-frame buffer, so frames 300..340 land at window index 100.
        self.stored_time_data[300:340, :] = 0.0

    monkeypatch.setattr(streams.MockRecorder, 'init_stream', init_with_gap)
    try:
        d = acquisition.log_data(_mock_settings())
        assert acquisition.LAST_CAPTURE_DROPOUTS == (1, pytest.approx(40 / 8000.0))
        y = d.time_data_list[0].time_data
        assert np.all(y[100:140, :] == 0.0)        # the gap really is in the data
    finally:
        try:
            streams.REC.end_stream()
        except Exception:
            pass
        acquisition.LAST_CAPTURE_DROPOUTS = (0, 0.0)


def test_log_data_resets_dropouts_on_a_clean_capture(monkeypatch):
    acquisition.LAST_CAPTURE_DROPOUTS = (5, 1.0)     # stale from "a previous capture"
    try:
        acquisition.log_data(_mock_settings())
        assert acquisition.LAST_CAPTURE_DROPOUTS == (0, 0.0)
    finally:
        try:
            streams.REC.end_stream()
        except Exception:
            pass
        acquisition.LAST_CAPTURE_DROPOUTS = (0, 0.0)
