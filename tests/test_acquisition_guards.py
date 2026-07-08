"""Input-validation and unit-convention tests for `pydvma.acquisition`
and `pydvma.options` that don't need hardware.

These don't need hardware — both guards fire before any stream is
opened, so these tests run on Mac too. The guards come in two layers:

* `MySettings.__init__` rejects invalid combinations at construction
  time (primary defence).
* `acquisition.log_data` re-checks at call time in case settings were
  mutated after construction — e.g. ``s.pretrig_samples = N`` is
  idiomatic in some of the hardware tests.
"""
import pytest

import pydvma as dvma
from pydvma import acquisition


class TestConstructionGuard:
    """`MySettings.__init__` should reject pretrig_samples > chunk_size
    at construction time with a ValueError carrying a clear message.
    """

    def test_raises_above_chunk_size(self):
        with pytest.raises(ValueError, match='pretrig_samples'):
            dvma.MySettings(
                device_driver='soundcard',
                fs=10000, channels=1, chunk_size=100, stored_time=0.5,
                pretrig_samples=200,
                pretrig_threshold=0.1,
            )

    def test_accepts_at_boundary(self):
        """pretrig_samples == chunk_size is the largest valid window."""
        s = dvma.MySettings(
            device_driver='soundcard',
            fs=10000, channels=1, chunk_size=100, stored_time=0.5,
            pretrig_samples=100,
            pretrig_threshold=0.1,
        )
        assert s.pretrig_samples == 100

    def test_accepts_below_boundary(self):
        s = dvma.MySettings(
            device_driver='soundcard',
            fs=10000, channels=1, chunk_size=100, stored_time=0.5,
            pretrig_samples=50,
            pretrig_threshold=0.1,
        )
        assert s.pretrig_samples == 50

    def test_none_bypasses_guard(self):
        """pretrig_samples=None disables triggering; the chunk_size
        constraint doesn't apply."""
        s = dvma.MySettings(
            device_driver='soundcard',
            fs=10000, channels=1, chunk_size=50, stored_time=0.3,
            pretrig_samples=None,
        )
        assert s.pretrig_samples is None


class TestCallSiteGuard:
    """`acquisition.log_data` re-checks pretrig_samples vs chunk_size
    at call time. Catches post-construction mutation that sneaks past
    the constructor check.
    """

    def _valid_settings(self):
        return dvma.MySettings(
            device_driver='soundcard',
            fs=10000, channels=1, chunk_size=100, stored_time=0.3,
            pretrig_samples=50, pretrig_threshold=0.1,
        )

    def test_mutated_above_chunk_size_raises(self):
        s = self._valid_settings()
        s.pretrig_samples = 200      # now inconsistent with chunk_size
        with pytest.raises(ValueError, match='pretrig_samples'):
            acquisition.log_data(s)

    def test_mutated_chunk_size_below_pretrig_raises(self):
        """Equivalent inconsistency the other way: shrinking chunk_size
        below pretrig_samples must also raise."""
        s = self._valid_settings()
        s.chunk_size = 10            # now pretrig_samples (50) > chunk_size
        with pytest.raises(ValueError, match='pretrig_samples'):
            acquisition.log_data(s)


class TestViewedTimeNone:
    """``viewed_time`` is documented as "float or None" (None meaning
    the oscilloscope buffer is sized directly from ``num_chunks``
    instead of being derived from a time window); construction must
    not crash when it's passed explicitly."""

    def test_settings_viewed_time_none(self):
        # viewed_time is documented as "float or None"; None means the
        # osc buffer is still allocated, just sized directly from
        # num_chunks instead of derived from a time window (regression:
        # an unguarded float(viewed_time) predated the None-handling
        # block).
        settings = dvma.MySettings(channels=2, fs=1000, viewed_time=None,
                                    device_driver='mock')
        assert settings.viewed_time is None
        # num_chunks keeps its explicit/default value rather than being
        # derived from viewed_time
        assert settings.num_chunks == 6


class TestVmaxHelpers:
    """The `input_vmax` / `output_vmax` accessors on MySettings pick
    the right driver-specific full-scale voltage. Internal code (the
    recorder callbacks, oscilloscope display, clipping warning,
    signal_generator) reads through these helpers.
    """

    def test_input_soundcard_defaults_to_1(self):
        s = dvma.MySettings(device_driver='soundcard')
        assert s.input_vmax() == 1.0

    def test_input_nidaq_uses_VmaxNI(self):
        s = dvma.MySettings(device_driver='nidaq', VmaxNI=7.5)
        assert s.input_vmax() == 7.5

    def test_input_soundcard_uses_VmaxSC_when_set(self):
        s = dvma.MySettings(device_driver='soundcard', VmaxSC=2.3)
        assert s.input_vmax() == 2.3

    def test_output_follows_output_device_driver(self):
        """output_vmax() is gated on output_device_driver, not
        device_driver — cross-driver setups (e.g. NI in, soundcard
        out) resolve independently."""
        s = dvma.MySettings(
            device_driver='nidaq', VmaxNI=5,
            output_device_driver='soundcard', output_VmaxSC=1.7,
        )
        assert s.input_vmax() == 5.0
        assert s.output_vmax() == 1.7

    def test_output_vmax_defaults_to_input(self):
        s = dvma.MySettings(device_driver='soundcard', VmaxSC=2.0)
        # output_VmaxSC not given -> defaults to VmaxSC
        assert s.output_vmax() == 2.0


class TestOutputDeviceFallback:
    """When `sd.default` is unavailable, `MySettings` falls back to a
    name-based scan of enumerated devices for the output index. If no
    device name contains 'output' (typical input-only Mac setups) the
    scan must fall back gracefully, not raise IndexError."""

    def _patch_sd_default_broken(self, monkeypatch):
        from pydvma import options

        class _BrokenDefault:
            @property
            def device(self):
                raise AttributeError('no default device')

        class _FakeSd:
            default = _BrokenDefault()

        monkeypatch.setattr(options, 'sd', _FakeSd())

    def test_no_output_named_device_falls_back(self, monkeypatch):
        from pydvma import streams
        self._patch_sd_default_broken(monkeypatch)
        monkeypatch.setattr(streams, 'get_devices_soundcard',
                            lambda: ['Built-in Microphone'])
        s = dvma.MySettings(device_driver='mock',
                            output_device_driver='soundcard')
        assert s.output_device_index == 1

    def test_output_named_device_is_picked(self, monkeypatch):
        from pydvma import streams
        self._patch_sd_default_broken(monkeypatch)
        monkeypatch.setattr(streams, 'get_devices_soundcard',
                            lambda: ['mic input', 'speakers output'])
        s = dvma.MySettings(device_driver='mock',
                            output_device_driver='soundcard')
        assert s.output_device_index == 1


class TestNiOutputDeviceFollowsInput:
    """An unset NI output_device_index must follow the INPUT device when
    the output driver is unset or matches the input driver ("same device
    as the input") — not silently route the AO task to NI device 0.
    Real-hardware bug (2026-07-08): webui input on Dev3 (nidaq index 2)
    with the output select on "same as input" drove the cDAQ's 9260
    instead, surfacing as a spurious voltage-rail error at log time."""

    def test_unset_output_driver_follows_input_device(self):
        s = dvma.MySettings(device_driver='nidaq', device_index=2)
        assert s.output_device_driver == 'nidaq'
        assert s.output_device_index == 2

    def test_explicit_same_driver_follows_input_device(self):
        s = dvma.MySettings(device_driver='nidaq', device_index=1,
                            output_device_driver='nidaq')
        assert s.output_device_index == 1

    def test_explicit_output_index_wins(self):
        s = dvma.MySettings(device_driver='nidaq', device_index=2,
                            output_device_index=0)
        assert s.output_device_index == 0

    def test_cross_driver_output_falls_back_to_device_0(self):
        s = dvma.MySettings(device_driver='soundcard', device_index=1,
                            output_device_driver='nidaq')
        assert s.output_device_index == 0

    def test_mock_output_follows_input_device_too(self):
        s = dvma.MySettings(device_driver='mock', device_index=1)
        assert s.output_device_index == 1

    def test_soundcard_output_still_uses_default_output(self, monkeypatch):
        """Soundcard semantics must NOT change: an unset soundcard output
        resolves to the default OUTPUT device, never the input's index."""
        from pydvma import options

        class _FakeDefault:
            device = [3, 7]

        class _FakeSd:
            default = _FakeDefault()

        monkeypatch.setattr(options, 'sd', _FakeSd())
        s = dvma.MySettings(device_driver='soundcard')
        assert s.device_index == 3
        assert s.output_device_index == 7


class TestEndStreamRobustness:
    """Soundcard `Recorder.end_stream` must tolerate a stream that was
    never opened or is already dead, matching the NI recorder."""

    def test_end_stream_without_open_stream_does_not_raise(self):
        from pydvma import streams
        s = dvma.MySettings(device_driver='mock', channels=2)
        rec = streams.Recorder(s)  # buffers only; init_stream never called
        rec.end_stream()
        assert streams.REC is None

    def test_end_stream_with_dead_stream_object_does_not_raise(self):
        from pydvma import streams
        s = dvma.MySettings(device_driver='mock', channels=2)
        rec = streams.Recorder(s)

        class _DeadStream:
            @property
            def active(self):
                raise RuntimeError('PortAudio: stream closed')

            def stop(self):
                raise RuntimeError('closed')

            def close(self):
                raise RuntimeError('closed')

        rec.audio_stream = _DeadStream()
        rec.end_stream()  # must swallow, like the NI path
        assert rec.audio_stream is None


class TestNiCallbackInterval:
    """The NI every-N-samples callback interval must equal the
    per-callback read size (chunk_size). The old largest-of-{10,100,
    1000} table made events fire faster than reads consume samples for
    any other chunk_size, and crashed outright below 10."""

    def test_interval_equals_chunk_size(self):
        from pydvma import streams
        assert streams._ni_callback_interval(1000) == 1000
        assert streams._ni_callback_interval(2048) == 2048  # was capped to 1000
        assert streams._ni_callback_interval(7) == 7        # was IndexError

    def test_invalid_chunk_size_raises(self):
        from pydvma import streams
        with pytest.raises(ValueError, match='chunk_size'):
            streams._ni_callback_interval(0)


class TestOutputRatePreflight:
    """`_check_output_rate_within_hardware` turns an out-of-bounds
    ``output_fs`` into a clear ValueError naming the hardware limit,
    instead of the raw DAQmx -200077 seen on the real USB-6003 (AO max
    5 kS/s) during the 2026-07-07 hardware session."""

    _ENTRY = {'name': 'Dev3', 'product_type': 'USB-6003',
              'is_chassis': False, 'ai_channel_count': 8,
              'ao_channel_count': 2, 'module_names': [],
              'module_ai_counts': {}, 'module_ao_counts': {}}

    def _patch_caps(self, monkeypatch, caps):
        from pydvma import streams
        monkeypatch.setattr(streams._ni_backend, 'entry_capabilities',
                            lambda entry, resolver=None: caps)

    def test_rate_above_hw_max_raises_clearly(self, monkeypatch):
        from pydvma import streams
        self._patch_caps(monkeypatch, {'ao_max_rate': 5000.0,
                                       'ao_min_rate': 0.02})
        with pytest.raises(ValueError, match='5000'):
            streams._check_output_rate_within_hardware(self._ENTRY, 8000.0)

    def test_rate_below_hw_min_raises_clearly(self, monkeypatch):
        from pydvma import streams
        self._patch_caps(monkeypatch, {'ao_max_rate': 51200.0,
                                       'ao_min_rate': 1613.0})
        with pytest.raises(ValueError, match='1613'):
            streams._check_output_rate_within_hardware(self._ENTRY, 1000.0)

    def test_rate_within_bounds_passes(self, monkeypatch):
        from pydvma import streams
        self._patch_caps(monkeypatch, {'ao_max_rate': 5000.0,
                                       'ao_min_rate': 0.02})
        streams._check_output_rate_within_hardware(self._ENTRY, 5000.0)

    def test_probe_failure_falls_through(self, monkeypatch):
        from pydvma import streams

        def boom(entry, resolver=None):
            raise RuntimeError('no driver')

        monkeypatch.setattr(streams._ni_backend, 'entry_capabilities', boom)
        streams._check_output_rate_within_hardware(self._ENTRY, 8000.0)
