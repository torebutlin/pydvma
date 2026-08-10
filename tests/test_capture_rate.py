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


class TestOversampleStrategy:
    """Which rate to oversample TO is a property of the hardware, not of
    which code branch happens to run."""

    def test_soundcard_is_delta_sigma_so_lowest_suffices(self):
        assert streams.hardware_antialiases(make_settings(fs=3000)) is True
        assert streams.oversample_strategy(make_settings(fs=3000)) == 'lowest'

    def test_multiplexed_nidaq_must_capture_as_fast_as_possible(self, monkeypatch):
        """USB-6003/6212 have no anti-alias filter, so a high capture
        rate is the only protection available."""
        from pydvma import _ni_backend
        monkeypatch.setattr(_ni_backend, 'enumerate_devices', lambda: [{'name': 'Dev1'}])
        monkeypatch.setattr(_ni_backend, 'entry_capabilities',
                            lambda e: {'simultaneous': False})
        s = make_settings(fs=3000, device_driver='nidaq')
        assert streams.oversample_strategy(s) == 'highest'

    def test_dsa_nidaq_follows_the_soundcard_rule(self, monkeypatch):
        """A 9234 is delta-sigma like the 2i2, so the lowest rate with
        headroom is enough -- capturing faster rejects nothing extra."""
        from pydvma import _ni_backend
        monkeypatch.setattr(_ni_backend, 'enumerate_devices', lambda: [{'name': 'cDAQ1Mod1'}])
        monkeypatch.setattr(_ni_backend, 'entry_capabilities',
                            lambda e: {'simultaneous': True})
        s = make_settings(fs=3000, device_driver='nidaq')
        assert streams.oversample_strategy(s) == 'lowest'

    def test_unknown_hardware_takes_the_safe_side(self, monkeypatch):
        """A probe failure must not quietly reduce alias protection."""
        from pydvma import _ni_backend
        monkeypatch.setattr(_ni_backend, 'enumerate_devices',
                            lambda: (_ for _ in ()).throw(RuntimeError('no driver')))
        s = make_settings(fs=3000, device_driver='nidaq')
        assert streams.hardware_antialiases(s) is None
        assert streams.oversample_strategy(s) == 'highest'

    def test_mock_defaults_to_highest(self):
        assert streams.oversample_strategy(
            make_settings(fs=3000, device_driver='mock')) == 'highest'

    def test_explicit_setting_overrides_the_device_default(self):
        s = make_settings(fs=3000, oversample='highest')
        assert streams.oversample_strategy(s) == 'highest'
        s = make_settings(fs=3000, device_driver='nidaq', oversample='lowest')
        assert streams.oversample_strategy(s) == 'lowest'

    def test_rejects_an_unknown_strategy(self):
        with pytest.raises(ValueError, match="oversample must be"):
            make_settings(fs=3000, oversample='fastest')

    def test_multiplexed_ni_is_reported_as_unfiltered(self, monkeypatch):
        """The USB-6003/6212 have no anti-alias filter; a DSA module does."""
        from pydvma import _ni_backend
        monkeypatch.setattr(_ni_backend, 'enumerate_devices', lambda: [{'name': 'Dev1'}])
        monkeypatch.setattr(_ni_backend, 'entry_capabilities',
                            lambda e: {'simultaneous': False})
        assert streams.hardware_antialiases(
            make_settings(fs=3000, device_driver='nidaq')) is False
        monkeypatch.setattr(_ni_backend, 'entry_capabilities',
                            lambda e: {'simultaneous': True})
        assert streams.hardware_antialiases(
            make_settings(fs=3000, device_driver='nidaq')) is True

    def test_highest_strategy_takes_the_top_native_rate(self, native):
        s = make_settings(fs=3000, lpf_on=True, oversample='highest')
        assert streams.select_capture_fs(s) == (192000.0, 'oversample')

    def test_lowest_strategy_takes_the_first_rate_with_headroom(self, native):
        s = make_settings(fs=3000, lpf_on=True, oversample='lowest')
        assert streams.select_capture_fs(s) == (44100.0, 'oversample')


class TestOversampleStrategyWithoutALadder:
    """The no-ladder path (NI, mock) must obey the same property."""

    def _opened_fs(self, monkeypatch, **kwargs):
        monkeypatch.setattr(streams, 'native_input_rates', lambda s: [])
        monkeypatch.setattr(streams, 'max_input_fs', lambda s: 1_000_000.0)
        opened = {}
        real_start = streams.start_stream

        def spy(settings):
            opened['fs'] = settings.fs
            return real_start(settings)

        monkeypatch.setattr(streams, 'start_stream', spy)
        acquisition.log_data(make_settings(
            device_driver='mock', fs=1000, chunk_size=100,
            stored_time=0.05, lpf_on=True, **kwargs))
        return opened['fs']

    def test_highest_uses_the_full_device_headroom(self, monkeypatch):
        assert self._opened_fs(monkeypatch) == 1_000_000

    def test_lowest_stops_at_the_first_sufficient_multiple(self, monkeypatch):
        """x3, not x1000: ceil(2.56) clears the resampler passband."""
        assert self._opened_fs(monkeypatch, oversample='lowest') == 3000


class TestOutputSharesInputClock:
    def test_same_soundcard_device_shares_one_clock(self):
        s = make_settings(fs=44100, device_index=2, output_device_index=2,
                          output_device_driver='soundcard')
        assert streams.output_shares_input_clock(s) is True

    def test_different_soundcard_devices_keep_separate_clocks(self, monkeypatch):
        monkeypatch.setattr(streams._coreaudio, 'available', lambda: False)
        s = make_settings(fs=44100, device_index=2, output_device_index=5,
                          output_device_driver='soundcard')
        assert streams.output_shares_input_clock(s) is False

    def test_nidaq_output_rate_is_independent(self):
        s = make_settings(fs=44100, device_driver='nidaq', device_index=0,
                          output_device_index=0, output_device_driver='nidaq')
        assert streams.output_shares_input_clock(s) is False


class TestStimulusOnSharedClock:
    """A sound card cannot play at a rate different from its capture, so
    the stimulus is moved onto the capture rate rather than left for the
    OS to resample."""

    def _run(self, monkeypatch, ladder, out_fs, target_fs=3000, tone=200.0):
        monkeypatch.setattr(streams, 'native_input_rates', lambda s: list(ladder))
        monkeypatch.setattr(streams, 'output_shares_input_clock', lambda s: True)
        played = {}

        class FakeStream:
            def WaitUntilTaskDone(self, *a): pass
            def StopTask(self): pass
            def ClearTask(self): pass
            def stop(self): pass
            def close(self): pass

        def fake_output(settings, out):
            played.update(fs=settings.output_fs, n=len(out))
            return FakeStream()

        monkeypatch.setattr(acquisition, 'output_signal', fake_output)
        t = np.arange(0, 1.0, 1 / out_fs)
        wave = np.sin(2 * np.pi * tone * t).reshape(-1, 1)
        s = make_settings(device_driver='mock', fs=target_fs, chunk_size=100,
                          stored_time=0.2, output_fs=out_fs)
        acquisition.log_data(s, output=wave)
        return played

    def test_stimulus_is_moved_onto_the_capture_rate(self, monkeypatch):
        played = self._run(monkeypatch, SCARLETT_LADDER, out_fs=3000)
        assert played['fs'] == 44100, 'must play at the rate the device runs'

    def test_stimulus_keeps_its_duration(self, monkeypatch):
        """Resampling must preserve the physical signal: same seconds of
        excitation, so a sweep still sweeps what it was generated for."""
        played = self._run(monkeypatch, SCARLETT_LADDER, out_fs=3000)
        assert played['n'] / 44100 == pytest.approx(1.0, rel=0.02)

    def test_untouched_when_the_rates_already_agree(self, monkeypatch):
        played = self._run(monkeypatch, SCARLETT_LADDER, out_fs=48000,
                           target_fs=48000)
        assert played['fs'] == 48000
        assert played['n'] == 48000
