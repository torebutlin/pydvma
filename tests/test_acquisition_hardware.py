"""End-to-end acquisition tests against live NI hardware.

Auto-skipped on machines without nidaqmx or with no NI devices connected
(so Mac dev machines stay green). On Windows with devices plugged in,
the module discovers what's actually present at collection time and
parametrizes tests across every device that has at least one AI and one
AO channel — matching the "BNC loopback ao0 → ai0 on every device"
convention in `CLAUDE.md`.

Each test runs in three flavours per device:
    - basic acquisition (no pretrigger)
    - pretrigger armed + AO stimulus (real trigger fires)
    - pretrigger armed + no stimulus (timeout fallback, must not crash)

Per-device configuration (terminal config, voltage range) is derived
from the enumerated `device_entry`. The heuristic covers the current
lab kit (USB-6003, USB-6212, cDAQ-9174 + 9234 AI + 9260 AO); if you
plug in a different cDAQ AI module whose terminal mode or range
differs, extend `_config_for_device` below.
"""
import pytest

try:
    import nidaqmx  # noqa: F401
    _NIDAQMX_AVAILABLE = True
except ImportError:
    _NIDAQMX_AVAILABLE = False

if not _NIDAQMX_AVAILABLE:
    pytest.skip('nidaqmx not installed', allow_module_level=True)

import numpy as np

import pydvma as dvma
from pydvma import _ni_backend


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
        'No NI devices with both AI and AO channels (needed for '
        'loopback tests)', allow_module_level=True,
    )


def _config_for_device(entry):
    """Per-device acquisition config.

    Returns dict with NI_mode, VmaxNI, output_VmaxNI tuned for the
    device. Conservative defaults for unknown modules; explicit values
    for modules with non-standard constraints (DSA modules like the
    NI 9234 are pseudo-diff only and fixed ±5 V; NI 9260 AO is ±4.24 V
    peak).
    """
    if entry['is_chassis']:
        # cDAQ chassis: assume a DSA AI module (9234-class) and a
        # low-voltage AO module (9260-class). Override here if your
        # chassis has different modules.
        return dict(NI_mode='DAQmx_Val_PseudoDiff', VmaxNI=5, output_VmaxNI=4)
    # Standalone USB / PCIe devices: RSE, ±10 V AI, ±5 V AO is a
    # conservative default that works for USB-6003 (AO ±5) and is
    # within range for USB-6212 (AO ±10).
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
    """Make sure the NI task is torn down between tests, even on failure."""
    yield
    try:
        if dvma.streams.REC is not None:
            dvma.streams.REC.end_stream()
    except Exception:
        pass


def _settings_for(device_entry, device_index, *, channels=1, stored_time=0.2,
                  fs=5000, pretrig=False):
    # fs=5000 is the conservative common rate across the lab kit:
    #   - USB-6003 AO max is 5 kS/s (software-timed DAC); higher values
    #     trigger DAQmx error -200077 on the output task.
    #   - NI 9260 AO requires fs >= 1.613 kS/s.
    #   - All our AI modules comfortably handle 5 kS/s.
    cfg = _config_for_device(device_entry)
    kwargs = dict(
        device_driver='nidaq', device_index=device_index,
        channels=channels,
        output_device_driver='nidaq', output_device_index=device_index,
        output_channels=1,
        ni_backend='nidaqmx',
        fs=fs, stored_time=stored_time,
        **cfg,
    )
    if pretrig:
        kwargs.update(
            pretrig_samples=50,
            pretrig_threshold=0.2,
            pretrig_channel=0,
            pretrig_timeout=3,
        )
    return dvma.MySettings(**kwargs)


def test_basic_acquisition(device_entry, device_index):
    """Plain continuous acquisition, no pretrigger. Shape and dtype."""
    s = _settings_for(device_entry, device_index, channels=1, stored_time=0.2)
    ds = dvma.log_data(s)
    td = ds.time_data_list[0]
    assert td.time_data.shape == (int(0.2 * s.fs), 1)
    assert np.isfinite(td.time_data).all()


def test_pretrigger_with_stimulus(device_entry, device_index):
    """AO-driven loopback fires the pretrigger; captured peak matches
    the commanded amplitude within tolerance."""
    s = _settings_for(device_entry, device_index, channels=1,
                      stored_time=0.2, pretrig=True)
    amp_norm = 0.3  # normalized 0..1; physical = amp_norm * output_VmaxNI
    expected_peak = amp_norm * s.output_VmaxNI
    t, y = dvma.signal_generator(
        s, sig='sweep', T=0.15, amplitude=amp_norm,
        f=[200, 1000],     # well above 9234's 0.5 Hz HPF
    )
    ds = dvma.log_data(s, output=y)
    ai0 = ds.time_data_list[0].time_data[:, 0]
    assert ds.time_data_list[0].time_data.shape == (int(0.2 * s.fs), 1)
    peak = float(np.max(np.abs(ai0)))
    # Loose tolerance: AC coupling on DSA modules attenuates the low
    # end of the sweep; also the capture window may not include the
    # full sweep plateau. 50 % of expected is generous enough to
    # survive both while still catching "nothing came through".
    assert peak > 0.5 * expected_peak, (
        'loopback peak {:.3f} V on {} is too low vs expected {:.3f} V — '
        'check the BNC cable between ao0 and ai0 on {!r}'
        .format(peak, device_entry['product_type'], expected_peak,
                device_entry['name'])
    )


def test_pretrigger_timeout_no_crash(device_entry, device_index):
    """No stimulus, trigger threshold set above any realistic ambient
    noise: pretrigger times out and log_data must return the tail of
    the buffer rather than crash."""
    s = _settings_for(device_entry, device_index, channels=1,
                      stored_time=0.2, pretrig=True)
    # Override threshold so ambient noise can't trigger, and shorten
    # the timeout so the test finishes quickly.
    s.pretrig_threshold = 100.0   # volts; no sane input ever reaches this
    s.pretrig_timeout = 1.0
    ds = dvma.log_data(s)  # no output
    assert ds.time_data_list[0].time_data.shape == (int(0.2 * s.fs), 1)


def test_suggest_ni_settings_end_to_end(device_entry, device_index):
    """`suggest_ni_settings(...)` output must be directly usable:
    feed it to MySettings and run log_data without any driver error."""
    kwargs = dvma.suggest_ni_settings(device_index)
    s = dvma.MySettings(channels=1, stored_time=0.2, **kwargs)
    # Values must be within-device per the helper's promise
    if device_entry['is_chassis']:
        # Chassis heuristic: DSA module → pseudo-diff + fixed ±5
        assert s.NI_mode == 'DAQmx_Val_PseudoDiff'
    ds = dvma.log_data(s)
    assert ds.time_data_list[0].time_data.shape[0] == int(0.2 * s.fs)


def test_backend_roundtrip_pydaqmx(device_entry, device_index):
    """Sanity: legacy pydaqmx backend still works on non-chassis devices.

    Skipped for cDAQ chassis — pydaqmx path builds `Dev/ai0:N-1` and
    can't express module-qualified chassis channels.
    """
    if device_entry['is_chassis']:
        pytest.skip('pydaqmx path not cDAQ-aware')
    # pydaqmx enumerates differently (modules flat in list); recompute
    # its index by matching device name.
    from pydvma.streams import get_devices_NI
    names, _ = get_devices_NI()
    if names is None or device_entry['name'] not in names:
        pytest.skip('pydaqmx cannot see this device')
    pydaqmx_index = names.index(device_entry['name'])
    cfg = _config_for_device(device_entry)
    s = dvma.MySettings(
        device_driver='nidaq', device_index=pydaqmx_index, channels=1,
        output_device_driver='nidaq', output_device_index=pydaqmx_index,
        output_channels=1,
        ni_backend='pydaqmx',
        fs=10000, stored_time=0.2,
        **cfg,
    )
    ds = dvma.log_data(s)
    assert ds.time_data_list[0].time_data.shape == (2000, 1)
