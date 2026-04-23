"""Stress tests that interleave device/mode switches in a single process.

Companion to ``test_acquisition_hardware.py``. That file tears down the
NI task between every test (autouse ``_cleanup_stream`` fixture) so
each case runs from a clean slate. The tests here do the opposite on
purpose: within one test function we make several ``log_data`` calls
with changing settings and let state carry over, because *state
carry-over between acquisitions* is the real-world notebook workflow
and the failure mode behind the reported crash:

    AttributeError: 'NoneType' object has no attribute 'trigger_detected'

Root cause was ``acquisition.log_data`` re-reading ``streams.REC`` on
subsequent calls even though a prior ``end_stream()`` had nulled it.
These tests exercise the sequences that expose that class of bug:

* repeat on the same device,
* switch between two different NI devices,
* toggle pretrigger on and off,
* toggle an AO output stimulus on and off,
* a full cartesian sweep across {device × pretrig × output}.

Auto-skipped on machines without nidaqmx or without the required
hardware — same gate pattern as ``test_acquisition_hardware.py``.
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
_LOOPBACK_DEVICES = [
    e for e in _DEVICES
    if e['ai_channel_count'] >= 1 and e['ao_channel_count'] >= 1
]
if not _LOOPBACK_DEVICES:
    pytest.skip(
        'No NI devices with both AI and AO channels (needed for '
        'loopback stress tests)', allow_module_level=True,
    )


def _config_for_device(entry):
    """Per-device acquisition config. Mirrors ``test_acquisition_hardware``."""
    if entry['is_chassis']:
        return dict(NI_mode='DAQmx_Val_PseudoDiff', VmaxNI=5, output_VmaxNI=4)
    return dict(NI_mode='DAQmx_Val_RSE', VmaxNI=10, output_VmaxNI=5)


def _device_index(entry):
    return _DEVICES.index(entry)


def _id_for(entry):
    return '{}_{}'.format(entry['name'], entry['product_type']).replace(' ', '_')


def _settings_for(entry, *, pretrig=False, stored_time=0.2, fs=5000):
    """Build a MySettings for one log_data call on ``entry``.

    fs=5000 is the conservative common rate across the lab kit
    (USB-6003 software-timed AO caps at 5 kS/s; NI 9260 needs
    >= 1.613 kS/s; all AI modules comfortably handle 5 kS/s).
    """
    cfg = _config_for_device(entry)
    idx = _device_index(entry)
    kwargs = dict(
        device_driver='nidaq', device_index=idx,
        channels=1,
        output_device_driver='nidaq', output_device_index=idx,
        output_channels=1,
        fs=fs, stored_time=stored_time,
        **cfg,
    )
    if pretrig:
        kwargs.update(
            pretrig_samples=50,
            pretrig_threshold=0.2,
            pretrig_channel=0,
            pretrig_timeout=1.5,
        )
    return dvma.MySettings(**kwargs)


def _stimulus(settings, amp_v=1.5):
    """AO sweep that will fire a pretrigger cleanly on any device.

    ``amp_v`` is in volts (post-Vmax-refactor convention). 200-1000 Hz
    is above the 9234's ~0.5 Hz HPF, safe on USB-6003's 5 kS/s AO
    ceiling, and within range on every AO module in the lab.
    """
    _t, y = dvma.signal_generator(
        settings, sig='sweep', T=0.15, amplitude=amp_v, f=[200, 1000],
    )
    return y


def _assert_shape(ds, settings):
    td = ds.time_data_list[0]
    assert td.time_data.shape == (int(settings.stored_time * settings.fs), 1), (
        'unexpected shape {} for {}'.format(td.time_data.shape, settings.device_index)
    )
    assert np.isfinite(td.time_data).all()


@pytest.fixture(scope="module", autouse=True)
def _module_teardown():
    """End whatever stream is live when the module finishes, so the
    stress run doesn't leak a task into later hardware tests."""
    yield
    try:
        if dvma.streams.REC is not None:
            dvma.streams.REC.end_stream()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Individual transitions — each isolates one kind of state carry-over so a
# failure points at a specific transition rather than "something in the sweep".
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('entry', _LOOPBACK_DEVICES, ids=[_id_for(e) for e in _LOOPBACK_DEVICES])
def test_repeat_same_device(entry):
    """Two back-to-back log_data calls on the same device with no manual
    teardown between. Baseline: if this fails, everything else will."""
    s = _settings_for(entry)
    ds1 = dvma.log_data(s)
    ds2 = dvma.log_data(s)
    _assert_shape(ds1, s)
    _assert_shape(ds2, s)


@pytest.mark.parametrize('entry', _LOOPBACK_DEVICES, ids=[_id_for(e) for e in _LOOPBACK_DEVICES])
def test_toggle_pretrigger(entry):
    """No-pretrig → pretrig+AO → no-pretrig on one device. Exercises the
    buffer-reinit + callback path toggling on and off."""
    s_plain = _settings_for(entry, pretrig=False)
    s_trig = _settings_for(entry, pretrig=True)
    y = _stimulus(s_trig)

    _assert_shape(dvma.log_data(s_plain), s_plain)
    _assert_shape(dvma.log_data(s_trig, output=y), s_trig)
    _assert_shape(dvma.log_data(s_plain), s_plain)


@pytest.mark.parametrize('entry', _LOOPBACK_DEVICES, ids=[_id_for(e) for e in _LOOPBACK_DEVICES])
def test_toggle_output(entry):
    """With AO → without AO → with AO on one device. Exercises the AO
    task lifecycle (create / teardown / recreate) across calls."""
    s = _settings_for(entry)
    y = _stimulus(s)

    _assert_shape(dvma.log_data(s, output=y), s)
    _assert_shape(dvma.log_data(s), s)
    _assert_shape(dvma.log_data(s, output=y), s)


@pytest.mark.skipif(
    len(_LOOPBACK_DEVICES) < 2,
    reason='Need at least two NI devices with AI+AO to test device switching',
)
def test_switch_between_two_devices():
    """Log on device A → device B → back to A. This is the exact user
    scenario behind the reported AttributeError crash: the first call
    leaves ``streams.REC`` populated, switching device triggers an
    ``end_stream`` on it, and the next ``log_data`` call must still
    initialise cleanly."""
    dev_a, dev_b = _LOOPBACK_DEVICES[0], _LOOPBACK_DEVICES[1]
    s_a = _settings_for(dev_a)
    s_b = _settings_for(dev_b)

    _assert_shape(dvma.log_data(s_a), s_a)
    _assert_shape(dvma.log_data(s_b), s_b)
    _assert_shape(dvma.log_data(s_a), s_a)


@pytest.mark.skipif(
    len(_LOOPBACK_DEVICES) < 2,
    reason='Need at least two NI devices to test pretrigger + device switch',
)
def test_switch_devices_with_pretrigger_and_output():
    """Harder variant of the device-switch test: pretrigger armed and AO
    stimulus active on each call. Catches teardown issues in the AO
    task that only bite when both input and output tasks are live."""
    dev_a, dev_b = _LOOPBACK_DEVICES[0], _LOOPBACK_DEVICES[1]
    s_a = _settings_for(dev_a, pretrig=True)
    s_b = _settings_for(dev_b, pretrig=True)

    _assert_shape(dvma.log_data(s_a, output=_stimulus(s_a)), s_a)
    _assert_shape(dvma.log_data(s_b, output=_stimulus(s_b)), s_b)
    _assert_shape(dvma.log_data(s_a, output=_stimulus(s_a)), s_a)


# ---------------------------------------------------------------------------
# Full sweep — only meaningful once the isolated transitions above pass. Runs
# every {device × pretrig × output} combination back to back in one process.
# ---------------------------------------------------------------------------


def test_full_matrix_sweep():
    """Interleave every combination of {device × pretrig × output} in one
    run. Catches interactions that isolated pairwise transitions miss
    (e.g. "device switch is fine, pretrigger toggle is fine, but device
    switch *while* pretrig was just armed breaks")."""
    combos = []
    for entry in _LOOPBACK_DEVICES:
        for pretrig in (False, True):
            for with_output in (False, True):
                combos.append((entry, pretrig, with_output))

    # Shuffle deterministically: alternate devices so adjacent runs
    # actually switch device, rather than doing all of device A first.
    combos.sort(key=lambda c: (c[1], c[2], _device_index(c[0])))

    for entry, pretrig, with_output in combos:
        s = _settings_for(entry, pretrig=pretrig)
        output = _stimulus(s) if with_output else None
        ds = dvma.log_data(s, output=output)
        _assert_shape(ds, s)
