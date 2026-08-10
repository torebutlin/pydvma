"""Tests for native-rate capability and capture-rate selection.

The rules here exist because ``sd.check_input_settings`` is not a
capability probe on macOS — it accepts rates the hardware cannot run,
and CoreAudio then resamples silently. See
``dev/plans/2026-08-10-focusrite-scarlett-design.md``.
"""

import numpy as np
import pytest

from pydvma import acquisition, options, streams


SCARLETT_LADDER = [44100.0, 48000.0, 88200.0, 96000.0, 176400.0, 192000.0]


def make_settings(**kwargs):
    kwargs.setdefault('device_driver', 'soundcard')
    kwargs.setdefault('channels', 1)
    kwargs.setdefault('device_index', 0)
    return options.MySettings(**kwargs)


@pytest.fixture
def native(monkeypatch):
    """Report a Scarlett-like discrete rate ladder for the configured device."""
    ladder = list(SCARLETT_LADDER)
    monkeypatch.setattr(streams, 'native_input_rates', lambda s: list(ladder))
    return ladder


class TestSelectCaptureFs:
    def test_native_target_captures_exactly(self, native):
        fs, reason = streams.select_capture_fs(make_settings(fs=48000))
        assert (fs, reason) == (48000.0, 'exact')

    def test_unrunnable_target_steps_up_to_the_lowest_native_rate(self, native):
        """3 kHz is what a 1.5 kHz-bandwidth lab wants and no sound card
        can run it; capture at 44.1 kHz and decimate rather than letting
        the OS resample."""
        fs, reason = streams.select_capture_fs(make_settings(fs=3000))
        assert (fs, reason) == (44100.0, 'lowest-native')

    def test_target_between_native_rates_steps_up(self, native):
        fs, reason = streams.select_capture_fs(make_settings(fs=50000))
        assert (fs, reason) == (88200.0, 'lowest-native')

    def test_lpf_on_picks_lowest_rate_with_real_headroom(self, native):
        """A delta-sigma converter is already anti-aliased at its own
        rate, so capturing above the first rate with headroom buys data
        volume and nothing else."""
        fs, reason = streams.select_capture_fs(make_settings(fs=3000, lpf_on=True))
        assert (fs, reason) == (44100.0, 'oversample')

    def test_lpf_on_needs_2_56x_headroom_not_merely_2x(self, native):
        """fs = 22050 has a 2x rate available (44100) but the resampler's
        passband runs to fs/2.56, so 44100 would clip the top of the
        band; 88200 is the first rate that genuinely covers it."""
        fs, reason = streams.select_capture_fs(make_settings(fs=22050, lpf_on=True))
        assert (fs, reason) == (88200.0, 'oversample')

    def test_lpf_on_falls_back_to_the_top_rate_when_headroom_is_impossible(self, native):
        fs, reason = streams.select_capture_fs(make_settings(fs=96000, lpf_on=True))
        assert (fs, reason) == (192000.0, 'oversample')

    def test_explicit_capture_fs_wins_over_the_automatic_rule(self, native):
        """The case for hardware with no anti-alias filter of its own:
        capture as fast as possible, whatever the auto rule would pick."""
        s = make_settings(fs=3000, lpf_on=True, capture_fs=192000)
        assert streams.select_capture_fs(s) == (192000.0, 'explicit')

    def test_explicit_capture_fs_snaps_up_to_a_runnable_rate(self, native):
        s = make_settings(fs=3000, capture_fs=50000)
        assert streams.select_capture_fs(s) == (88200.0, 'explicit')

    def test_unknown_ladder_leaves_the_target_alone(self, monkeypatch):
        """Off macOS, and for NI/mock, nothing is claimed about the
        hardware and the legacy behaviour must be untouched."""
        monkeypatch.setattr(streams, 'native_input_rates', lambda s: [])
        fs, reason = streams.select_capture_fs(make_settings(fs=3000, lpf_on=True))
        assert (fs, reason) == (3000.0, 'unknown')

    def test_mock_driver_reports_no_ladder(self):
        s = make_settings(fs=3000, device_driver='mock')
        assert streams.native_input_rates(s) == []
        assert streams.select_capture_fs(s)[1] == 'unknown'


class TestCaptureFsSetting:
    def test_defaults_to_auto(self):
        assert make_settings(fs=3000).capture_fs is None

    def test_rejects_a_capture_rate_below_fs(self):
        """The capture rate is decimated DOWN to fs; below it the request
        is incoherent and would silently upsample."""
        with pytest.raises(ValueError, match='at least fs'):
            make_settings(fs=44100, capture_fs=8000)

    def test_string_none_is_treated_as_auto(self):
        assert make_settings(fs=3000, capture_fs='None').capture_fs is None


class TestMaxInputFs:
    def test_uses_the_native_ladder_when_published(self, native):
        assert streams.max_input_fs(make_settings(fs=3000)) == 192000.0

    def test_ignores_native_rates_below_the_target(self, native):
        assert streams.max_input_fs(make_settings(fs=96000)) == 192000.0

    def test_falls_back_to_probing_when_no_ladder_is_published(self, monkeypatch):
        """Where the device publishes nothing, keep the old probe — but
        it must not be consulted when a real ladder exists, since on
        macOS it accepts every rate."""
        monkeypatch.setattr(streams, 'native_input_rates', lambda s: [])
        calls = []

        class FakeSd:
            @staticmethod
            def check_input_settings(device=None, samplerate=None, channels=None):
                calls.append(samplerate)
                if samplerate > 48000:
                    raise ValueError('nope')

        monkeypatch.setattr(streams, 'sd', FakeSd)
        assert streams.max_input_fs(make_settings(fs=8000)) == 48000.0
        assert calls == [192000, 96000, 88200, 48000]

    def test_native_ladder_is_preferred_over_the_probe(self, native, monkeypatch):
        class ExplodingSd:
            @staticmethod
            def check_input_settings(**kwargs):
                raise AssertionError('probe must not be used when a ladder exists')

        monkeypatch.setattr(streams, 'sd', ExplodingSd)
        assert streams.max_input_fs(make_settings(fs=3000)) == 192000.0


class TestCaptureSettings:
    def test_scales_chunk_geometry_with_the_rate(self):
        """Callback cadence and pretrigger DURATION must survive the swap
        to a capture rate, or the pretrig_samples <= chunk_size invariant
        breaks at the new rate."""
        target = make_settings(fs=3000, chunk_size=100, pretrig_samples=50)
        capture = acquisition._capture_settings(target, 44100.0)
        assert capture.fs == 44100
        assert capture.chunk_size == 1470          # 100 * 44100/3000
        assert capture.pretrig_samples == 735      # 50 * 44100/3000
        assert capture.chunk_size / capture.fs == pytest.approx(
            target.chunk_size / target.fs)

    def test_leaves_the_callers_settings_untouched(self):
        target = make_settings(fs=3000, chunk_size=100)
        acquisition._capture_settings(target, 44100.0)
        assert (target.fs, target.chunk_size) == (3000, 100)

    def test_tolerates_pretrigger_being_off(self):
        target = make_settings(fs=3000, chunk_size=100, pretrig_samples=None)
        assert acquisition._capture_settings(target, 44100.0).pretrig_samples is None


class TestLogDataCaptureRate:
    """End-to-end through the mock backend, with a ladder faked on top."""

    def _run(self, monkeypatch, ladder, **kwargs):
        monkeypatch.setattr(streams, 'native_input_rates',
                            lambda s: list(ladder))
        opened = {}
        real_start = streams.start_stream

        def spy(settings):
            opened['fs'] = settings.fs
            return real_start(settings)

        monkeypatch.setattr(streams, 'start_stream', spy)
        kwargs.setdefault('device_driver', 'mock')
        kwargs.setdefault('stored_time', 0.2)
        kwargs.setdefault('chunk_size', 100)
        data = acquisition.log_data(make_settings(**kwargs))
        return data, opened

    def test_captures_at_a_runnable_rate_and_delivers_the_target(self, monkeypatch):
        data, opened = self._run(monkeypatch, SCARLETT_LADDER, fs=3000)
        assert opened['fs'] == 44100, 'stream must open at a rate the device runs'
        td = data.time_data_list[0]
        assert td.settings.fs == 3000, 'caller still gets the fs they asked for'
        assert td.settings.lpf_capture_fs == 44100, 'provenance of the real rate'

    def test_native_target_is_captured_directly(self, monkeypatch):
        data, opened = self._run(monkeypatch, SCARLETT_LADDER, fs=48000,
                                 stored_time=0.05)
        assert opened['fs'] == 48000
        assert data.time_data_list[0].settings.fs == 48000

    def test_explicit_capture_fs_is_honoured_end_to_end(self, monkeypatch):
        data, opened = self._run(monkeypatch, SCARLETT_LADDER, fs=3000,
                                 capture_fs=96000)
        assert opened['fs'] == 96000
        assert data.time_data_list[0].settings.fs == 3000

    def test_delivered_signal_lands_at_the_target_rate(self, monkeypatch):
        """The record must be self-consistent: duration implied by the
        sample count at the delivered fs matches the requested duration."""
        data, _ = self._run(monkeypatch, SCARLETT_LADDER, fs=3000,
                            stored_time=0.5)
        td = data.time_data_list[0]
        duration = td.time_data.shape[0] / td.settings.fs
        assert duration == pytest.approx(0.5, rel=0.05)

    def test_unknown_ladder_keeps_the_legacy_path(self, monkeypatch):
        data, opened = self._run(monkeypatch, [], fs=3000)
        assert opened['fs'] == 3000
        assert data.time_data_list[0].settings.fs == 3000
