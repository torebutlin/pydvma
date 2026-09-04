"""Regression tests for the NI AO write path (`streams.setup_output_NI_nidaqmx`)
against a fake ``nidaqmx`` — no hardware.

Background (2026-09-04, office bench): the round-13 AO-coercion fix
resamples a stimulus onto the rate the 9260 really runs, which hands
``task.write`` a fresh C-order ``(N, channels)`` array. The transposed
``(channels, N)`` view of such an array is NOT C-contiguous, and
nidaqmx's ctypes layer refuses it outright::

    ctypes.ArgumentError: argument 6: TypeError: array must have flags
    ['C_CONTIGUOUS']

Seen live the first time a two-channel stimulus met a coerced rate. The
write now copies into C order for both the multi-channel and the
single-channel shapes; these tests pin that, and the resample itself
(the waveform handed to DAQmx is at the coerced rate, with the
sample count re-timed).
"""
import types

import numpy as np
import pytest

import pydvma as dvma
from pydvma import _ni_backend, streams


class _FakeTiming:
    def __init__(self, coerce_to):
        self._coerce_to = coerce_to
        self.calls = []

    def cfg_samp_clk_timing(self, rate, source='', sample_mode=None, samps_per_chan=None):
        self.calls.append(dict(rate=rate, source=source, samps_per_chan=samps_per_chan))
        self.samp_clk_rate = float(self._coerce_to(rate))


class _FakeTask:
    instances = []

    def __init__(self, coerce_to):
        self.timing = _FakeTiming(coerce_to)
        self.ao_channels = types.SimpleNamespace(
            add_ao_voltage_chan=lambda *a, **k: None)
        self.written = None
        _FakeTask.instances.append(self)

    def write(self, data, auto_start=False):
        # What nidaqmx's ctypes layer demands (it raises otherwise).
        assert data.flags['C_CONTIGUOUS'], 'DAQmx write needs a C-contiguous array'
        self.written = np.array(data, copy=True)

    def start(self): pass
    def stop(self): pass
    def close(self): pass
    def is_task_done(self): return True


@pytest.fixture
def fake_ni(monkeypatch):
    """A `nidaqmx` stand-in whose AO clock coerces 12500 -> 12800 (the
    9234/9260 ladder), plus the backend helpers the AO setup consults."""
    _FakeTask.instances.clear()

    def coerce(rate):
        return 12800.0 if abs(rate - 12500.0) < 1 else rate

    ni = types.SimpleNamespace(
        Task=lambda: _FakeTask(coerce),
        constants=types.SimpleNamespace(
            AcquisitionType=types.SimpleNamespace(FINITE='finite', CONTINUOUS='continuous')),
        errors=types.SimpleNamespace(DaqError=RuntimeError),
    )
    monkeypatch.setattr(streams, 'ni', ni)
    monkeypatch.setattr(streams, 'REC_NI', None)   # no AI task -> no clock routing
    entry = {'name': 'cDAQ1', 'product_type': 'cDAQ-9174', 'is_chassis': True,
             'ai_channel_count': 4, 'ao_channel_count': 2}
    monkeypatch.setattr(_ni_backend, 'enumerate_devices', lambda: [entry])
    monkeypatch.setattr(_ni_backend, 'build_ao_channel_string',
                        lambda e, n, spec: 'cDAQ1Mod2/ao0:%d' % (n - 1))
    monkeypatch.setattr(_ni_backend, 'supports_hw_ao_sync', lambda e: False)
    monkeypatch.setattr(streams, '_check_output_vmax_within_hardware', lambda e, v: None)
    monkeypatch.setattr(streams, '_check_output_rate_within_hardware', lambda e, r: None)
    return ni


def _settings(output_channels, output_fs):
    return dvma.MySettings(device_driver='nidaq', device_index=0, channels=1, fs=output_fs,
                           stored_time=0.5, output_device_driver='nidaq',
                           output_device_index=0, output_channels=output_channels,
                           output_fs=output_fs, output_VmaxNI=3.0)


def test_two_channel_coerced_output_is_written_c_contiguous(fake_ni):
    """The lab geometry: output_fs 12500 (defaulted from fs), the 9260 runs
    12800. The resampled (N, 2) waveform must reach DAQmx transposed AND
    C-contiguous, at the coerced rate, with the sample count re-timed."""
    s = _settings(output_channels=2, output_fs=12500)
    n = 12500
    y = np.zeros((n, 2))
    y[:, 0] = np.sin(2 * np.pi * 100 * np.arange(n) / 12500.0)
    y[:, 1] = 0.5 * y[:, 0]
    streams.setup_output_NI_nidaqmx(s, y)
    task = _FakeTask.instances[-1]
    assert task.written.shape[0] == 2
    # Re-timed for the coerced rate: 1 s of signal is 12800 samples now.
    assert task.written.shape[1] == pytest.approx(12800, abs=2)
    assert task.timing.calls[-1]['rate'] == pytest.approx(12800.0)
    assert task.timing.calls[-1]['samps_per_chan'] == task.written.shape[1]
    # The physical signal survived the resample: same amplitude ratio.
    assert np.std(task.written[1]) / np.std(task.written[0]) == pytest.approx(0.5, rel=1e-3)


def test_single_channel_coerced_output_is_written_1d_contiguous(fake_ni):
    s = _settings(output_channels=1, output_fs=12500)
    y = np.sin(2 * np.pi * 100 * np.arange(12500) / 12500.0)[:, None]
    streams.setup_output_NI_nidaqmx(s, y)
    task = _FakeTask.instances[-1]
    assert task.written.ndim == 1
    assert task.written.shape[0] == pytest.approx(12800, abs=2)


def test_uncoerced_two_channel_output_is_written_c_contiguous(fake_ni):
    """No coercion (25600 is on the ladder): the generator's own C-order
    (N, 2) array still needs the transpose copied into C order."""
    s = _settings(output_channels=2, output_fs=25600)
    _t, y = dvma.signal_generator(s, sig='sweep', T=0.2, amplitude=0.5, f=[100, 1000])
    assert y.shape == (int(0.2 * 25600), 2)
    assert not np.asarray(y).T.flags['C_CONTIGUOUS']   # the trap
    streams.setup_output_NI_nidaqmx(s, y)
    task = _FakeTask.instances[-1]
    assert task.written.shape == (2, y.shape[0])
    assert task.timing.calls[-1]['rate'] == pytest.approx(25600.0)
    assert len(task.timing.calls) == 1                  # no re-time without coercion
