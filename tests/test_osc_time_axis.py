"""The oscilloscope time axis has exactly as many samples as its buffer.

The axis used to be ``np.arange(0, N/fs, 1/fs)``, whose length is the
floating-point ``ceil((N/fs) / (1/fs))``, so for some rates it came out
N+1 long against an N-sample ``osc_time_data``. Exact round rates with
the default ``chunk_size`` of 100 happen to land on N, which hid it; the
rates NI coerces a request to do not (3 kHz on a 20 MHz timebase runs at
20e6/6667 = 2999.85 Hz), and neither do some round ones at other chunk
sizes (48 kHz, 10240 samples). `stream_snapshot` copies the axis, so
`calculate_fft` on the snapshot raised "boolean index did not match"
(3C6 lab, 2026-10-28). Mac-runnable, no hardware.
"""

import numpy as np
import pytest

import pydvma as dvma
from pydvma import analysis, streams


@pytest.fixture(autouse=True)
def _clean_streams_state():
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


#: (fs, chunk_size, num_chunks) where ``arange(0, N/fs, 1/fs)`` gives
#: N+1 samples. The first two are NI-coerced rates for a 3 kHz request
#: (20 MHz / 6667 and 80 MHz / 26666); the last is a round rate.
AWKWARD_GEOMETRY = [
    (20e6 / 6667, 100, 30),
    (80e6 / 26666, 100, 30),
    (48000.0, 1024, 10),
]


def _settings(driver, fs, chunk_size, num_chunks):
    s = dvma.MySettings(device_driver=driver, channels=2, fs=3000,
                        chunk_size=chunk_size, num_chunks=num_chunks,
                        viewed_time=None, stored_time=0.5)
    # Assigned after construction, as `_build_and_start_ai_task` does
    # when it adopts the rate DAQmx coerced the request to.
    s.fs = fs
    return s


@pytest.mark.parametrize('fs,chunk_size,num_chunks', AWKWARD_GEOMETRY)
def test_geometry_is_awkward_for_a_float_step(fs, chunk_size, num_chunks):
    # Guards the fixture: if numpy ever stops overshooting here, the
    # tests below would pass without exercising anything.
    n = chunk_size * num_chunks
    assert len(np.arange(0, n / fs, 1 / fs)) == n + 1


def _soundcard_recorder(s):
    return streams.Recorder(s)


def _ni_recorder(s):
    # `_alloc_buffers` is where the NI recorder builds the axes, and the
    # path it re-runs after a rate coercion; no DAQmx task is needed.
    rec = object.__new__(streams.Recorder_NI_nidaqmx)
    rec.settings = s
    rec._alloc_buffers()
    return rec


def _mock_recorder(s):
    return streams.MockRecorder(s)


RECORDERS = [
    pytest.param('soundcard', _soundcard_recorder, id='Recorder'),
    pytest.param('nidaq', _ni_recorder, id='Recorder_NI_nidaqmx'),
    pytest.param('mock', _mock_recorder, id='MockRecorder'),
]


@pytest.mark.parametrize('driver,make', RECORDERS)
@pytest.mark.parametrize('fs,chunk_size,num_chunks', AWKWARD_GEOMETRY)
def test_osc_axes_match_the_buffer(driver, make, fs, chunk_size, num_chunks):
    s = _settings(driver, fs, chunk_size, num_chunks)
    rec = make(s)
    n = chunk_size * num_chunks
    assert rec.osc_time_data.shape[0] == n
    assert len(rec.osc_time_axis) == n
    np.testing.assert_allclose(rec.osc_time_axis, np.arange(n) / fs)
    assert len(rec.osc_freq_axis) == n // 2 + 1
    assert rec.osc_freq_axis.shape == rec.osc_freq_data.shape[:1]


def test_fft_of_a_snapshot_at_a_coerced_rate():
    # The lab symptom end to end, through the mock driver.
    s = dvma.MySettings(channels=2, fs=3000, viewed_time=1,
                        device_driver='mock')
    s.fs = 20e6 / 6667
    streams.start_stream(s)
    assert len(streams.REC.osc_time_axis) == streams.REC.osc_time_data.shape[0]
    td = dvma.stream_snapshot(streams.REC)
    fd = analysis.calculate_fft(td, window='hann')
    assert fd.freq_data.shape == (len(td.time_axis) // 2 + 1, 2)
