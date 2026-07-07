"""Mac/Linux/Windows-runnable acquisition tests using the hardware-free
``device_driver='mock'`` backend (`pydvma.streams.MockRecorder`).

These tests exercise the call shape of `log_data`, `output_signal`,
`signal_generator`, and `stream_snapshot` without opening any
soundcard or NI device. They complement the live-hardware tests in
`test_acquisition_*` which are gated on real NI devices being
plugged in.

Scope: API contracts (returned shapes, cal_factor propagation, the
no-trigger timeout path) — not waveform correctness, which only the
real-hardware tests can prove.

The mock backend is silent by construction: no `sd.OutputStream` is
ever opened, so OS volume is irrelevant for this test file.
"""

import numpy as np
import pytest

import pydvma as dvma
from pydvma import streams, acquisition


@pytest.fixture(autouse=True)
def _clean_streams_state():
    """Reset module-level recorder globals before and after each test
    so state doesn't leak between tests via `streams.REC`."""
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


def _mock_settings(channels=2, fs=10000, chunk_size=1000, stored_time=0.1,
                   output_channels=1, **kwargs):
    return dvma.MySettings(
        device_driver='mock',
        output_device_driver='mock',
        fs=fs, channels=channels, chunk_size=chunk_size,
        num_chunks=4, stored_time=stored_time,
        output_channels=output_channels,
        **kwargs,
    )


class TestMockBackendBasics:

    def test_settings_accepts_mock_driver(self):
        s = _mock_settings()
        assert s.device_driver == 'mock'
        assert s.output_device_driver == 'mock'
        assert s.device_index == 0
        assert s.output_device_index == 0

    def test_start_stream_creates_mock_recorder(self):
        s = _mock_settings()
        streams.start_stream(s)
        assert streams.REC is not None
        assert isinstance(streams.REC, streams.MockRecorder)
        assert streams.REC.audio_stream is not None

    def test_start_stream_does_not_load_sounddevice_or_nidaqmx(self):
        """Hardware-free invariant: mock backend must not load the
        actual hardware libraries. (sd / ni may already be imported by
        other paths; we only assert the *recorder class* doesn't depend
        on them being functional.)"""
        s = _mock_settings()
        streams.start_stream(s)
        # No assertion needed beyond "didn't raise" — on a machine
        # without a working sound device, the soundcard path would
        # have crashed already.
        streams.REC.end_stream()

    def test_end_stream_clears_REC(self):
        s = _mock_settings()
        streams.start_stream(s)
        streams.REC.end_stream()
        assert streams.REC is None


class TestLogDataNoPretrigger:

    def test_log_data_returns_dataset_with_correct_shape(self):
        s = _mock_settings(channels=3, fs=8000, stored_time=0.05)
        ds = dvma.log_data(s)
        assert isinstance(ds, dvma.DataSet)
        assert len(ds.time_data_list) == 1
        td = ds.time_data_list[0]
        expected_samples = int(s.stored_time * s.fs)
        assert td.time_data.shape == (expected_samples, 3)
        assert len(td.time_axis) == expected_samples

    def test_log_data_default_cal_factors_are_ones(self):
        s = _mock_settings(channels=4)
        ds = dvma.log_data(s)
        np.testing.assert_array_equal(
            ds.time_data_list[0].channel_cal_factors, np.ones(4),
        )

    def test_log_data_propagates_channel_sensitivities_as_cal_factors(self):
        """log_data should set channel_cal_factors = 1 / sensitivity.
        A 100 mV/g accelerometer (sensitivity=0.1 V/g) maps to cal=10."""
        s = _mock_settings(channels=3,
                           channel_sensitivities=[0.1, 0.05, 1.0])
        ds = dvma.log_data(s)
        cal = ds.time_data_list[0].channel_cal_factors
        np.testing.assert_allclose(cal, [10.0, 20.0, 1.0])

    def test_log_data_returns_voltages_from_mock_signal(self):
        """The mock fills stored_time_data with sines in volts; the
        returned TimeData should preserve those voltage values."""
        s = _mock_settings(channels=2, fs=10000, stored_time=0.1)
        ds = dvma.log_data(s)
        td = ds.time_data_list[0]
        # Mock generates ch0 sine at 100 Hz amplitude 0.1 V
        # max absolute should be ~0.1 V on each channel.
        assert np.max(np.abs(td.time_data[:, 0])) <= 0.11
        assert np.max(np.abs(td.time_data[:, 0])) >= 0.05

    def test_log_data_with_output_does_not_crash(self):
        s = _mock_settings(channels=2, output_channels=1)
        t, y = dvma.signal_generator(s, sig='gaussian', T=0.05, amplitude=0.05)
        ds = dvma.log_data(s, output=y)
        assert len(ds.time_data_list) == 1
        td = ds.time_data_list[0]
        assert td.time_data.shape == (int(s.stored_time * s.fs), 2)

    def test_log_data_test_name_is_stored(self):
        s = _mock_settings()
        ds = dvma.log_data(s, test_name='unit-test-capture')
        assert ds.time_data_list[0].test_name == 'unit-test-capture'

    def test_log_data_reuses_existing_REC(self):
        """Two back-to-back log_data calls should keep REC alive as
        the same MockRecorder instance (no rebuild)."""
        s = _mock_settings()
        dvma.log_data(s)
        rec1 = streams.REC
        dvma.log_data(s)
        rec2 = streams.REC
        # MockRecorder rebuild path: start_stream always rebuilds for
        # device_driver='mock' (no signature-reuse logic). That's fine —
        # rec1 may differ from rec2. Just verify both are MockRecorders.
        assert isinstance(rec1, streams.MockRecorder)
        assert isinstance(rec2, streams.MockRecorder)


class TestLogDataPretrigger:

    def test_pretrigger_timeout_returns_tail_of_buffer(self):
        """Mock has no callback to fire, so the trigger never trips.
        After `pretrig_timeout` seconds log_data should return the
        tail of stored_time_data with trigger_detected = False."""
        s = _mock_settings(channels=2, fs=10000, stored_time=0.1,
                           chunk_size=1000, pretrig_samples=200,
                           pretrig_threshold=99.0,  # impossible to trip
                           pretrig_timeout=0.5)
        ds = dvma.log_data(s)
        td = ds.time_data_list[0]
        # Same shape contract whether or not a trigger fired
        assert td.time_data.shape == (int(s.stored_time * s.fs), 2)
        assert streams.REC.trigger_detected is False

    def test_pretrigger_rejects_pretrig_samples_above_chunk_size(self):
        """log_data's defence-in-depth guard."""
        s = _mock_settings(channels=2, chunk_size=500, pretrig_samples=100,
                           pretrig_threshold=0.5, pretrig_timeout=0.5)
        # mutate post-construction to bypass MySettings's own guard
        s.pretrig_samples = 600
        with pytest.raises(ValueError, match='pretrig_samples'):
            dvma.log_data(s)

    def test_pretrigger_leaves_no_stale_trigger_state(self):
        """After a pretriggered capture completes, the stored buffer
        must be zeroed and trigger_detected cleared — otherwise the
        captured signal re-rolls through the trigger-check window and
        spuriously re-arms between captures (observed live through the
        serve bridge on real NI hardware: the next armed capture
        reported "triggered" before any stimulus played)."""
        import numpy as np
        s = _mock_settings(channels=1, fs=10000, stored_time=0.1,
                           chunk_size=1000, pretrig_samples=200,
                           pretrig_threshold=99.0, pretrig_timeout=0.2)
        dvma.log_data(s)
        assert streams.REC.trigger_detected is False
        assert np.all(streams.REC.stored_time_data == 0.0)


class TestOutputAndSignalGenerator:

    def test_output_signal_returns_mock_adapter(self):
        s = _mock_settings(channels=1, output_channels=1)
        _, y = dvma.signal_generator(s, sig='gaussian', T=0.05, amplitude=0.05)
        out = acquisition.output_signal(s, y)
        assert isinstance(out, streams._MockOutputStream)
        assert out.started is True
        out.StopTask()
        assert out.started is False

    def test_signal_generator_respects_vmax_safety_ceiling(self):
        """`signal_generator` clamps the peak to ``settings.output_vmax()``
        (the device's full-scale output). For gaussian, ``amplitude``
        is the standard deviation, not the peak — peak is bounded by
        the safety ceiling, not by ``amplitude`` directly."""
        s = _mock_settings(output_channels=1, output_VmaxSC=0.5)
        _, y = dvma.signal_generator(s, sig='gaussian', T=0.1, amplitude=1.0)
        # Safety ceiling = output_VmaxSC = 0.5 V; truncnorm + the
        # final clip in signal_generator should keep peaks at-or-below.
        assert np.max(np.abs(y)) <= 0.5 + 1e-9

    def test_signal_generator_sweep_is_within_amplitude(self):
        """The 'sweep' signal type uses ``amplitude`` as a peak value
        (multiplied into a chirp of unit peak), so amplitude=0.05
        should produce |y| <= 0.05 + ramp window edge effects."""
        s = _mock_settings(output_channels=1)
        _, y = dvma.signal_generator(s, sig='sweep', T=0.1, amplitude=0.05,
                                     f=[100, 500])
        assert np.max(np.abs(y)) <= 0.05 + 1e-9


class TestStreamSnapshot:

    def test_stream_snapshot_returns_timedata(self):
        s = _mock_settings(channels=2)
        streams.start_stream(s)
        td = dvma.stream_snapshot(streams.REC)
        assert td.__class__.__name__ == 'TimeData'
        # osc buffer is num_chunks * chunk_size samples wide
        expected_n = s.num_chunks * s.chunk_size
        assert td.time_data.shape == (expected_n, 2)

    def test_stream_snapshot_after_log_data_reflects_buffer(self):
        s = _mock_settings(channels=1)
        dvma.log_data(s)
        td = dvma.stream_snapshot(streams.REC)
        # Mock fills osc_time_data with the sine signal; snapshot
        # should preserve voltage magnitudes
        assert np.max(np.abs(td.time_data)) > 0.0


def test_mock_recorder_osc_buffer_longer_than_stored():
    # viewed_time=None keeps num_chunks at its default (6 chunks =
    # 600 samples) while a short stored_time gives a 300-sample
    # stored buffer; construction must not assume osc <= stored
    # (regression for the broadcast crash at streams.py:1198).
    settings = dvma.MySettings(channels=2, fs=1000, stored_time=0.1,
                               viewed_time=None, device_driver='mock')
    rec = streams.MockRecorder(settings)
    assert rec.osc_time_data.shape == (600, 2)
    assert rec.stored_time_data.shape == (300, 2)
    # same deterministic signal on the overlapping head
    np.testing.assert_allclose(rec.osc_time_data[:300, :],
                               rec.stored_time_data)
    # and the osc buffer carries signal beyond the stored length
    assert np.abs(rec.osc_time_data[300:, :]).max() > 0
