"""AI/AO shared-clock verification against live NI hardware.

These tests light up the synchronisation path in
`streams.setup_output_NI_nidaqmx` and verify two things per device:

1. **Correct clock-source policy.** Each device falls into one of three
   categories and we assert the AO task's readback `samp_clk_src`
   matches:

       - M/X-series with HW-timed AO (e.g. USB-6212): AI's sample
         clock is routed as the AO source → readback equals
         ``/<dev>/ai/SampleClock`` (sample-accurate shared clock).
       - cDAQ chassis: no explicit routing (per-module AI clocks
         aren't routable as AO sources); AI and AO share the chassis
         80 MHz timebase implicitly → readback is the module's local
         AO sample clock.
       - Low-cost USB (USB-6003): AO is software-timed; no hardware
         sample clock is configured → readback is empty.

2. **Sync quality.** Drive a known chirp out of AO, read it back on the
   BNC loopback (``ao0 → ai0`` by convention), cross-correlate against
   the commanded waveform. If the clocks are coherent over the AO
   duration, the correlation has a sharp dominant peak. Drift would
   smear it. Tolerances are per-category so the 6003 (software-timed)
   test passes on signal presence alone without failing on jitter.

Auto-skipped on machines without nidaqmx or with no NI devices.
"""
import numpy as np
import pytest

try:
    import nidaqmx  # noqa: F401
    _NIDAQMX_AVAILABLE = True
except ImportError:
    _NIDAQMX_AVAILABLE = False

if not _NIDAQMX_AVAILABLE:
    pytest.skip('nidaqmx not installed', allow_module_level=True)

import pydvma as dvma
from pydvma import _ni_backend, streams


pytestmark = pytest.mark.hardware


def _discover_devices():
    try:
        return _ni_backend.enumerate_devices()
    except Exception:
        return []


_DEVICES = _discover_devices()
if not _DEVICES:
    pytest.skip('No NI devices found via nidaqmx', allow_module_level=True)

_LOOPBACK_DEVICES = [
    e for e in _DEVICES
    if e['ai_channel_count'] >= 1 and e['ao_channel_count'] >= 1
]
if not _LOOPBACK_DEVICES:
    pytest.skip(
        'No NI devices with both AI and AO channels (sync tests need '
        'a loopback)', allow_module_level=True,
    )


def _config_for_device(entry):
    """Conservative per-device acquisition config (same policy as
    test_acquisition_hardware._config_for_device)."""
    if entry['is_chassis']:
        return dict(NI_mode='DAQmx_Val_PseudoDiff', VmaxNI=5, output_VmaxNI=4)
    return dict(NI_mode='DAQmx_Val_RSE', VmaxNI=10, output_VmaxNI=5)


def _id_for(entry):
    return '{}_{}'.format(entry['name'], entry['product_type']).replace(' ', '_')


@pytest.fixture(
    params=_LOOPBACK_DEVICES,
    ids=[_id_for(e) for e in _LOOPBACK_DEVICES],
)
def device_entry(request):
    return request.param


@pytest.fixture
def device_index(device_entry):
    return _DEVICES.index(device_entry)


@pytest.fixture(autouse=True)
def _cleanup_stream():
    yield
    try:
        if streams.REC is not None:
            streams.REC.end_stream()
    except Exception:
        pass


def _settings_for(device_entry, device_index, *, stored_time=0.4, fs=5000):
    """AI+AO settings sized so AO fits comfortably inside the AI window."""
    cfg = _config_for_device(device_entry)
    return dvma.MySettings(
        device_driver='nidaq', device_index=device_index,
        channels=1,
        output_device_driver='nidaq', output_device_index=device_index,
        output_channels=1,
        fs=fs, stored_time=stored_time,
        **cfg,
    )


def _expected_clock_source(entry):
    """Predicted `samp_clk_src` readback for this device category."""
    if entry['is_chassis']:
        # No explicit routing; DAQmx reports the module's own AO clock.
        # Name resolves through whichever AO module the device_entry
        # enumerates, e.g. cDAQ1Mod2 in this lab.
        return 'chassis_module_local'
    if _ni_backend.supports_hw_ao_sync(entry):
        # M/X-series: AI clock routed as AO source for sample-accurate sync.
        return '/{}/ai/SampleClock'.format(entry['name'])
    # Software-timed AO (USB-600x): no hardware clock.
    return ''


def test_ao_clock_source_policy(monkeypatch, device_entry, device_index):
    """After `setup_output_NI_nidaqmx`, the AO task's `samp_clk_src`
    matches the per-device-category policy in `_ni_backend`."""
    captured = {}
    real_setup = streams.setup_output_NI_nidaqmx

    def capturing_setup(settings, output):
        adapter = real_setup(settings, output)
        # `_task` is the underlying nidaqmx.Task; timing.samp_clk_src
        # reads back whatever DAQmx actually set.
        captured['source'] = adapter._task.timing.samp_clk_src
        return adapter

    monkeypatch.setattr(streams, 'setup_output_NI_nidaqmx', capturing_setup)

    s = _settings_for(device_entry, device_index, stored_time=0.3)
    _, y = dvma.signal_generator(
        s, sig='sweep', T=0.15, amplitude=1.5, f=[200, 1000],
    )
    dvma.log_data(s, output=y)

    src = captured['source']
    expected = _expected_clock_source(device_entry)
    if expected == 'chassis_module_local':
        # e.g. '/cDAQ1Mod2/ao/SampleClock'
        assert src.endswith('/ao/SampleClock'), (
            'cDAQ chassis AO task should fall back to the module\'s '
            'local ao/SampleClock, got {!r}'.format(src)
        )
        assert '/cDAQ' in src or '/c' in src, (
            'readback source {!r} does not look like a chassis module '
            'clock'.format(src)
        )
    else:
        assert src == expected, (
            'AO clock source for {} ({}) was {!r}, expected {!r}'
            .format(device_entry['name'], device_entry['product_type'],
                    src, expected)
        )


def test_ao_ai_sync_sharp_correlation(device_entry, device_index):
    """Drive a chirp AO through the loopback and cross-correlate against
    the commanded waveform. Sharp peak ⇒ coherent sample clocks over
    the AO duration. Tolerances vary by device category: stricter for
    devices with hardware-timed AO, loose for software-timed USB-600x.
    """
    s = _settings_for(device_entry, device_index, stored_time=0.4)
    amp_v = 1.5
    T_chirp = 0.2  # well inside the 0.4 s AI window
    _, y = dvma.signal_generator(
        s, sig='sweep', T=T_chirp, amplitude=amp_v,
        f=[200, 1000],  # above the 9234's ~0.5 Hz HPF
    )
    ds = dvma.log_data(s, output=y)

    ai = ds.time_data_list[0].time_data[:, 0].astype(np.float64)
    ao = y[:, 0].astype(np.float64)

    # Full cross-correlation; 'valid' mode gives an output of length
    # (len(ai) - len(ao) + 1), which is where the chirp could sit.
    assert len(ai) > len(ao), 'AI window must be longer than AO for sync test'
    xc = np.correlate(ai, ao, mode='valid')
    abs_xc = np.abs(xc)

    peak_idx = int(np.argmax(abs_xc))
    peak = float(abs_xc[peak_idx])

    # Sharpness: ratio of peak amplitude to median correlation amplitude
    # elsewhere in the search. In practice on the current lab kit this
    # comes out > 50,000 on all three devices (even software-timed
    # USB-6003) because chirp-vs-chirp correlation concentrates energy
    # at one lag. The thresholds below are therefore *regression safety
    # nets*, not drift-sensitivity measurements — they catch "AO didn't
    # come through" or "gross clock failure" rather than tens-of-ppm
    # drift. Drift sensitivity would need a sub-sample phase analysis.
    median = float(np.median(abs_xc))
    assert median > 0, 'correlation floor was zero; AI may be silent'
    ratio = peak / median

    if device_entry['is_chassis'] or _ni_backend.supports_hw_ao_sync(device_entry):
        min_ratio = 20.0
    else:
        # Software-timed AO (USB-6003): leave extra margin for jitter.
        min_ratio = 5.0

    assert ratio > min_ratio, (
        'correlation peak/median on {} was {:.1f} (min {:.1f}); '
        'AO clock may be drifting relative to AI. peak={:.3f}, '
        'median={:.3f}'.format(
            device_entry['product_type'], ratio, min_ratio, peak, median,
        )
    )

    # And the recovered stimulus should have sensible amplitude
    # (same ballpark as test_pretrigger_with_stimulus): look at the
    # AI slice starting at the correlation peak.
    ai_slice = ai[peak_idx : peak_idx + len(ao)]
    ai_peak = float(np.max(np.abs(ai_slice)))
    expected_peak = amp_v   # signal_generator amplitude is now in volts
    assert ai_peak > 0.3 * expected_peak, (
        'AI chirp amplitude {:.3f} V on {} is too low vs expected {:.3f} V — '
        'correlation found a spurious peak rather than the real stimulus'
        .format(ai_peak, device_entry['product_type'], expected_peak)
    )
