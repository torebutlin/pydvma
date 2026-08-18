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

#: The lab's ESI U24 XL — its floor IS the bottom of the standard audio
#: ladder, which is what made the round-11 rate defects visible.
U24XL_LADDER = [8000.0, 16000.0, 32000.0, 44100.0, 48000.0]


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


class TestDeliveredRateOnAnEightKilohertzFloorDevice:
    """Whatever rate is asked for, that is the rate the record carries.

    Round 11's lab session ran at fs = 10000 on a U24 XL — a rate the
    device cannot run — and the wrong-by-10x frequency axis that
    followed was blamed on the analysis. It was not: the delivered rate
    and the rate stamped on the record have to agree by construction,
    for every target, filtered or not. Both are asserted here, the
    second one straight off the time axis, so no future capture-rate
    change can put a factor between them again.
    """

    def _log(self, monkeypatch, target, lpf_on, ladder=None, channels=1,
             **kwargs):
        monkeypatch.setattr(streams, 'native_input_rates',
                            lambda s: list(ladder or U24XL_LADDER))
        data = acquisition.log_data(make_settings(
            device_driver='mock', fs=target, chunk_size=100, channels=channels,
            stored_time=0.2, lpf_on=lpf_on, **kwargs))
        return data.time_data_list[0]

    @pytest.mark.parametrize('target', [500, 1000, 3000, 8000, 10000])
    @pytest.mark.parametrize('lpf_on', [False, True])
    def test_record_is_stamped_with_the_requested_rate(self, monkeypatch,
                                                       target, lpf_on):
        td = self._log(monkeypatch, target, lpf_on)
        assert float(td.settings.fs) == pytest.approx(float(target), rel=1e-9)

    @pytest.mark.parametrize('target', [500, 1000, 3000, 8000, 10000])
    @pytest.mark.parametrize('lpf_on', [False, True])
    def test_time_axis_ticks_at_the_requested_rate(self, monkeypatch,
                                                   target, lpf_on):
        """The stamp is only half of it — the SAMPLES have to arrive on
        that grid too, or every spectrum drawn from them is scaled."""
        td = self._log(monkeypatch, target, lpf_on)
        t = td.time_axis
        assert 1.0 / (t[1] - t[0]) == pytest.approx(float(target), rel=1e-6)

    def test_the_3c6_lab_envelope(self, monkeypatch):
        """The real teaching-lab capture: 3 kHz, 2 channels, digital
        low-pass on, logged natively at 48 kHz and decimated 16:1
        (0.2 s here for speed; the lab runs 30 s)."""
        td = self._log(monkeypatch, 3000, True, channels=2,
                       oversample='highest')
        assert float(td.settings.fs) == pytest.approx(3000.0, rel=1e-9)
        assert float(td.settings.lpf_capture_fs) == 48000.0
        assert td.time_data.shape == (600, 2)          # 0.2 s x 3000 Hz
        t = td.time_axis
        assert 1.0 / (t[1] - t[0]) == pytest.approx(3000.0, rel=1e-6)

    def test_the_3c6_envelope_on_a_real_delta_sigma_interface(self, monkeypatch):
        """What the lab actually gets by DEFAULT on a sound card: 8 kHz,
        not 48 kHz. 'auto' resolves to 'lowest' on a delta-sigma
        converter, whose anti-alias filter tracks the converter rate —
        8 kHz already rejects everything above 4 kHz, so 6x the data
        buys nothing. Delivered rate is identical either way."""
        td = self._log(monkeypatch, 3000, True, channels=2,
                       oversample='lowest')
        assert float(td.settings.lpf_capture_fs) == 8000.0
        assert float(td.settings.fs) == pytest.approx(3000.0, rel=1e-9)
        t = td.time_axis
        assert 1.0 / (t[1] - t[0]) == pytest.approx(3000.0, rel=1e-6)

    @pytest.mark.parametrize('target,expected_capture', [
        (500, 8000), (1000, 8000), (3000, 8000), (8000, 8000),
        (10000, 16000)])
    def test_capture_steps_up_to_a_rate_the_device_runs(self, monkeypatch,
                                                        target,
                                                        expected_capture):
        """Below the 8 kHz floor there is nowhere else to go; 10 kHz sits
        between rungs and must step UP, never down."""
        monkeypatch.setattr(streams, 'native_input_rates',
                            lambda s: list(U24XL_LADDER))
        capture_fs, _reason = streams.select_capture_fs(
            make_settings(fs=target))
        assert capture_fs == float(expected_capture)


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

        def fake_output(settings, out, cancel_event=None):
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


class TestMaxInputFsPerDriver:
    """`max_input_fs` had no direct test at all (pre-existing gap); it
    backs the oversample ceiling on every no-ladder device."""

    def test_mock_reports_its_synthetic_ceiling(self):
        s = make_settings(fs=1000, device_driver='mock')
        assert streams.max_input_fs(s) == float(streams.MOCK_MAX_FS)

    def test_falls_back_to_fs_when_nothing_can_be_learned(self, monkeypatch):
        """A missing driver must not invent headroom that isn't there."""
        monkeypatch.setattr(streams, 'sd', None)
        monkeypatch.setattr(streams, 'native_input_rates', lambda s: [])
        assert streams.max_input_fs(make_settings(fs=8000)) == 8000.0

    def test_nidaq_divides_the_aggregate_rate_per_channel(self, monkeypatch):
        """A multiplexed device scans one ADC across the channel list, so
        its advertised max is the AGGREGATE rate."""
        from pydvma import _ni_backend
        monkeypatch.setattr(_ni_backend, 'enumerate_devices', lambda: [{'name': 'Dev1'}])
        monkeypatch.setattr(_ni_backend, 'entry_capabilities',
                            lambda e: {'ai_max_rate': 100000.0, 'simultaneous': False})
        s = make_settings(fs=1000, device_driver='nidaq', channels=4)
        assert streams.max_input_fs(s) == 25000.0

    def test_nidaq_simultaneous_keeps_the_full_rate_per_channel(self, monkeypatch):
        """DSA modules have a converter per channel, so no division."""
        from pydvma import _ni_backend
        monkeypatch.setattr(_ni_backend, 'enumerate_devices', lambda: [{'name': 'cDAQ1Mod1'}])
        monkeypatch.setattr(_ni_backend, 'entry_capabilities',
                            lambda e: {'ai_max_rate': 51200.0, 'simultaneous': True})
        s = make_settings(fs=1000, device_driver='nidaq', channels=4)
        assert streams.max_input_fs(s) == 51200.0

    def test_nidaq_probe_failure_falls_back_to_fs(self, monkeypatch):
        from pydvma import _ni_backend
        monkeypatch.setattr(_ni_backend, 'enumerate_devices',
                            lambda: (_ for _ in ()).throw(RuntimeError('no driver')))
        s = make_settings(fs=1000, device_driver='nidaq')
        assert streams.max_input_fs(s) == 1000.0


class TestClockNote:
    """A mis-parked device clock has to reach the operator.

    ``_pin_hardware_clock`` has always printed its warning; a warning
    printed into a terminal behind the browser window is a warning
    nobody reads, so it is also recorded on the recorder for
    ``pydvma.serve`` to forward into the UI.
    """

    def _pin(self, monkeypatch, target, ladder, set_ok=True, parked=44100.0):
        ca = streams._coreaudio
        monkeypatch.setattr(ca, 'available', lambda: True)
        monkeypatch.setattr(ca, 'find_device', lambda name: (7, name))
        monkeypatch.setattr(ca, 'native_rates', lambda dev: list(ladder))
        monkeypatch.setattr(ca, 'get_nominal_rate', lambda dev: parked)
        monkeypatch.setattr(ca, 'set_nominal_rate', lambda dev, r: set_ok)
        s = make_settings(fs=target, chunk_size=100, stored_time=0.1)
        s.device_name = 'U24XL with SPDIF I/O'
        rec = streams.Recorder(s)
        rec._pin_hardware_clock(s)
        return rec

    def test_silent_when_the_clock_lands_where_it_was_asked(self, monkeypatch):
        rec = self._pin(monkeypatch, 48000, U24XL_LADDER)
        assert rec.clock_note is None

    def test_off_ladder_target_says_only_the_live_stream_suffers(self, monkeypatch):
        """A 10 kHz target on an 8/16/32 kHz device: the monitor is
        OS-resampled, but the LOG steps up to 16 kHz and decimates, so
        the note must not send the operator hunting a data problem they
        do not have."""
        rec = self._pin(monkeypatch, 10000, U24XL_LADDER)
        assert 'cannot run at 10000 Hz' in rec.clock_note
        assert 'LIVE' in rec.clock_note
        assert 'Logged captures are unaffected' in rec.clock_note

    def test_target_above_the_ceiling_admits_every_capture_is_resampled(self, monkeypatch):
        """Nothing to decimate from above 48 kHz, so the honest answer
        is different — and must not claim the log is fine."""
        rec = self._pin(monkeypatch, 96000, U24XL_LADDER)
        assert 'no higher rate to decimate from' in rec.clock_note
        assert 'Logged captures are unaffected' not in rec.clock_note

    def test_refused_clock_change_is_recorded(self, monkeypatch):
        rec = self._pin(monkeypatch, 48000, U24XL_LADDER, set_ok=False)
        assert 'could not set' in rec.clock_note

    def test_note_survives_the_pretrigger_buffer_reset(self, monkeypatch):
        """`log_data` re-runs ``__init__`` on the LIVE recorder to zero
        the buffers before arming. That does not reopen the stream, so
        what the stream is doing must not be forgotten."""
        rec = self._pin(monkeypatch, 10000, U24XL_LADDER)
        rec.stream_fs = 10000.0
        rec.__init__(rec.settings)
        assert rec.clock_note is not None
        assert rec.stream_fs == 10000.0

    def test_note_is_cleared_on_a_later_clean_pin(self, monkeypatch):
        """Stale warnings are worse than none: the attribute is reset at
        the top of every pin, not only written when there is bad news."""
        rec = self._pin(monkeypatch, 10000, U24XL_LADDER)
        assert rec.clock_note is not None
        s = make_settings(fs=48000, chunk_size=100, stored_time=0.1)
        s.device_name = 'U24XL with SPDIF I/O'
        rec._pin_hardware_clock(s)
        assert rec.clock_note is None


class TestLoopbackWarningOnThePythonPath:
    """The web UI warns in Setup; a notebook user needs the same."""

    def _clamp(self, capsys, monkeypatch, name, channels):
        class FakeSd:
            PortAudioError = RuntimeError

            @staticmethod
            def query_devices(index=None):
                return {'name': name, 'max_input_channels': 4}

        monkeypatch.setattr(streams, 'sd', FakeSd)
        s = make_settings(fs=44100, channels=channels, device_index=0)
        streams._clamp_soundcard_input_channels(s)
        return capsys.readouterr().out

    def test_warns_when_a_loopback_channel_is_included(self, capsys, monkeypatch):
        out = self._clamp(capsys, monkeypatch, 'Scarlett 2i2 4th Gen', 4)
        assert 'DIGITAL LOOPBACK' in out
        assert '3, 4' in out

    def test_silent_when_only_analogue_channels_are_requested(self, capsys, monkeypatch):
        assert self._clamp(capsys, monkeypatch, 'Scarlett 2i2 4th Gen', 2) == ''

    def test_silent_for_an_uncharacterised_device(self, capsys, monkeypatch):
        assert self._clamp(capsys, monkeypatch, 'Some Other Interface', 4) == ''
