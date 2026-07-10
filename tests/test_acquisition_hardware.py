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


_LOOPBACK_CACHE = {}


def _has_ao_to_ai_loopback(entry, device_index, amp_v=1.5,
                           min_rms_lift_v=0.05):
    """AC-stimulus loopback probe. Plays a brief 200-1000 Hz sweep on
    ao0 (at ``amp_v`` volts) via the same ``log_data`` stack the real
    tests use, and checks whether ai0 RMS rises by at least
    ``min_rms_lift_v`` volts vs a quiet capture.

    AC (not DC) because DSA AI modules (NI 9234-class) are AC-coupled —
    a DC preflight would report "no signal" on them even when the
    loopback is wired. The 200-1000 Hz band is above the 9234's ~0.5 Hz
    HPF and well below Nyquist for all our AI modules at 5 kS/s.

    Cached per device name — runs at most once per device per session.
    """
    name = entry['name']
    if name in _LOOPBACK_CACHE:
        return _LOOPBACK_CACHE[name]

    s = _settings_for(entry, device_index, stored_time=0.1)
    try:
        _t, y = dvma.signal_generator(
            s, sig='sweep', T=0.08, amplitude=amp_v, f=[200, 1000],
        )
        quiet = dvma.log_data(s).time_data_list[0].time_data[:, 0]
        stim = dvma.log_data(s, output=y).time_data_list[0].time_data[:, 0]
    except Exception:
        _LOOPBACK_CACHE[name] = False
        return False

    quiet_rms = float(np.sqrt(np.mean(quiet ** 2)))
    stim_rms = float(np.sqrt(np.mean(stim ** 2)))
    present = (stim_rms - quiet_rms) >= min_rms_lift_v
    _LOOPBACK_CACHE[name] = present
    return present


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


@pytest.mark.parametrize('n_channels', [2, 4])
def test_multichannel_acquisition(device_entry, device_index, n_channels):
    """Multi-channel capture. Shape reflects all channels, every
    channel is finite, and channels are independent (no trivial
    duplication or cross-channel bleed).

    Auto-skipped when the device doesn't have enough AI channels.
    """
    if device_entry['ai_channel_count'] < n_channels:
        pytest.skip(
            '{} has only {} AI channel(s); skipping channels={}'
            .format(device_entry['product_type'],
                    device_entry['ai_channel_count'], n_channels)
        )
    s = _settings_for(device_entry, device_index,
                      channels=n_channels, stored_time=0.2)
    ds = dvma.log_data(s)
    td = ds.time_data_list[0]
    assert td.time_data.shape == (int(0.2 * s.fs), n_channels)
    assert np.isfinite(td.time_data).all()

    # Channel independence: different channels shouldn't be
    # byte-identical (would indicate a buffer-reshape bug where all
    # channels receive the same slice).
    for ci in range(n_channels):
        for cj in range(ci + 1, n_channels):
            if np.array_equal(td.time_data[:, ci], td.time_data[:, cj]):
                raise AssertionError(
                    'channels {} and {} on {} are byte-identical — '
                    'likely a reshape bug'
                    .format(ci, cj, device_entry['product_type'])
                )


def _ai_modules(device_entry):
    """List of ``(module_name, ai_count)`` for the AI-bearing modules of
    a chassis, in slot order. Empty for standalone devices (they have no
    module concept). Used to find tests that genuinely span >1 module."""
    if not device_entry['is_chassis']:
        return []
    return [
        (m, device_entry['module_ai_counts'].get(m, 0))
        for m in device_entry['module_names']
        if device_entry['module_ai_counts'].get(m, 0) > 0
    ]


def test_multimodule_acquisition_spans_ai_modules(device_entry, device_index):
    """On a chassis with two or more AI modules, capturing more channels
    than the first module holds must spill onto the next module and come
    back as one coherent multi-channel array.

    This exercises the cross-module channel string
    (``cDAQ1Mod1/ai0:3,cDAQ1Mod4/ai0:3``) and the buffer reshape for a
    channel count that no single module could supply — the path that a
    single-module rig never hits. Auto-skipped unless ≥2 AI modules are
    present.
    """
    modules = _ai_modules(device_entry)
    if len(modules) < 2:
        pytest.skip('needs a chassis with >= 2 AI modules')
    first_count = modules[0][1]
    # Request one channel past the first module so the task must open the
    # second module too; cap at the chassis total.
    n_channels = min(first_count + 1, device_entry['ai_channel_count'])
    s = _settings_for(device_entry, device_index,
                      channels=n_channels, stored_time=0.2)
    ds = dvma.log_data(s)
    td = ds.time_data_list[0].time_data
    assert td.shape == (int(0.2 * s.fs), n_channels)
    assert np.isfinite(td).all()
    # The channel string the task was actually built from must span
    # both modules (comma-joined fragments from different devices).
    chan_str = _ni_backend.build_ai_channel_string(device_entry, n_channels)
    devices_used = {frag.split('/')[0] for frag in chan_str.split(',')}
    assert len(devices_used) >= 2, (
        'channels={} on {} did not span two modules (string={!r})'
        .format(n_channels, device_entry['product_type'], chan_str)
    )
    # Channels must stay independent across the module boundary.
    for ci in range(n_channels):
        for cj in range(ci + 1, n_channels):
            if np.array_equal(td[:, ci], td[:, cj]):
                raise AssertionError(
                    'channels {} and {} are byte-identical on {} — '
                    'cross-module reshape bug'
                    .format(ci, cj, device_entry['product_type'])
                )


def test_iepe_applies_to_second_module_channel(device_entry, device_index):
    """IEPE programmed on a channel that lives on the *second* AI module
    is applied to that channel — and only that channel.

    Guards the per-channel, module-aware IEPE path: the channel→module
    map must resolve a second-module channel to its own module both for
    validation and for excitation programming. Mirrors the lab rig where
    an ICP accelerometer sits on the second AI module while the first
    carries an AO→AI loopback. Auto-skipped unless there are ≥2 IEPE-
    capable AI modules.
    """
    modules = _ai_modules(device_entry)
    if len(modules) < 2:
        pytest.skip('needs a chassis with >= 2 AI modules')
    iepe_vals = _supports_iepe(device_entry)
    if not iepe_vals:
        pytest.skip('{} AI modules have no IEPE support'
                    .format(device_entry['product_type']))
    target_current = iepe_vals[0]
    first_count = modules[0][1]
    # First channel of the second module is at index == first module size.
    accel_idx = first_count
    n_channels = min(first_count + 2, device_entry['ai_channel_count'])

    s = _settings_for(device_entry, device_index,
                      channels=n_channels, stored_time=0.1)
    s.iepe_excit_current_A[accel_idx] = target_current

    ds = dvma.log_data(s)
    td = ds.time_data_list[0].time_data
    assert td.shape == (int(0.1 * s.fs), n_channels)

    chs = list(streams.REC.audio_stream.ai_channels)
    # The targeted second-module channel got excitation + AC coupling.
    assert abs(chs[accel_idx].ai_excit_val - target_current) < 1e-9, (
        'channel {} (second module) ai_excit_val = {} A, expected {} A'
        .format(accel_idx, chs[accel_idx].ai_excit_val, target_current)
    )
    assert chs[accel_idx].ai_coupling.name == 'AC'
    # A first-module channel left at 0 stays DC / no excitation.
    assert chs[0].ai_excit_val == 0.0
    assert chs[0].ai_coupling.name == 'DC'


def _ai_sampling_mode(device_entry):
    """Return ``'simultaneous'`` or ``'multiplexed'`` (or ``None`` if
    unknown) for this device's AI path.

    Looked up from the `_ni_device_specs.QUIRKS` table via
    `get_device_info`. For a chassis, the first slotted AI module's
    mode is reported.
    """
    if device_entry['is_chassis']:
        for mod in device_entry['module_names']:
            if device_entry['module_ai_counts'].get(mod, 0) > 0:
                return dvma.get_device_info(mod).get('ai_sampling')
        return None
    return dvma.get_device_info(device_entry['name']).get('ai_sampling')


def test_multichannel_stimulus_reaches_ch0_only(device_entry, device_index):
    """With the loopback wired ao0 → ai0, driving a known stimulus on
    AO should land primarily on channel 0 of the capture. Other
    channels stay at the ambient noise floor, confirming per-channel
    isolation in the multi-channel AI task.

    **Only meaningful on simultaneous-sampling AI**: multiplexed
    low-cost DAQs (USB-6212, USB-6003, etc.) charge-inject between
    mux steps and an open ai1 will "ghost" a heavily-attenuated copy
    of ai0 even though the wiring is correct. Catching that cleanly
    would require grounding the unused terminals, which isn't
    possible in the loopback-only lab setup. Skipped rather than
    asserting looser tolerances, so a genuine cross-channel
    mis-wiring still surfaces on DSA hardware.
    """
    if device_entry['ai_channel_count'] < 2:
        pytest.skip('needs at least 2 AI channels')
    if _ai_sampling_mode(device_entry) != 'simultaneous':
        pytest.skip(
            'Multiplexed-AI device ({}) ghosts the previous channel '
            'into open inputs; strict isolation needs grounded '
            'unused terminals, not a loopback-only setup.'
            .format(device_entry['product_type'])
        )
    if not _has_ao_to_ai_loopback(device_entry, device_index):
        pytest.skip(
            'No ao0 → ai0 loopback detected on {} ({}).'
            .format(device_entry['name'], device_entry['product_type'])
        )
    n_channels = min(device_entry['ai_channel_count'], 4)
    s = _settings_for(device_entry, device_index,
                      channels=n_channels, stored_time=0.2)
    _, y = dvma.signal_generator(
        s, sig='sweep', T=0.15, amplitude=1.5, f=[200, 1000],
    )
    ds = dvma.log_data(s, output=y)
    td = ds.time_data_list[0]
    assert td.time_data.shape == (int(0.2 * s.fs), n_channels)

    ch0_peak = float(np.max(np.abs(td.time_data[:, 0])))
    other_peaks = [float(np.max(np.abs(td.time_data[:, i])))
                   for i in range(1, n_channels)]
    # Stimulus is 1.5 V; other channels see only ambient pickup, which
    # on a short open input is typically well under 200 mV (DSA
    # modules especially). Give loose headroom to survive noisy labs.
    assert ch0_peak > 1.0, (
        'ch0 peak {:.3f} V on {} is lower than expected stimulus'
        .format(ch0_peak, device_entry['product_type'])
    )
    for idx, peak in enumerate(other_peaks, start=1):
        assert peak < 0.5 * ch0_peak, (
            'channel {} peak {:.3f} V on {} is within 50 % of ch0 '
            '({:.3f} V) — cross-talk or channel mis-wiring'
            .format(idx, peak, device_entry['product_type'], ch0_peak)
        )


def test_pretrigger_with_stimulus(device_entry, device_index):
    """AO-driven loopback fires the pretrigger; captured peak matches
    the commanded amplitude within tolerance. Requires a physical
    ao0 → ai0 loopback — auto-skipped on devices where none is detected."""
    if not _has_ao_to_ai_loopback(device_entry, device_index):
        pytest.skip(
            'No ao0 → ai0 loopback detected on {} ({}). Check the BNC '
            'cable; see CLAUDE.md for the expected wiring.'
            .format(device_entry['name'], device_entry['product_type'])
        )
    s = _settings_for(device_entry, device_index, channels=1,
                      stored_time=0.2, pretrig=True)
    amp_v = 1.5  # volts; kept consistent with the pre-Vmax era where
                 # amp_norm=0.3 at output_VmaxNI=5 gave 1.5 V peak.
    expected_peak = amp_v
    t, y = dvma.signal_generator(
        s, sig='sweep', T=0.15, amplitude=amp_v,
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


def test_pretrigger_positioning(device_entry, device_index):
    """The first above-threshold sample in the returned buffer sits
    at exactly index ``pretrig_samples``.

    This is the invariant promised by the trigger state machine: the
    trigger is detected when a crossing reaches
    ``stored_time_data[chunk_size:2*chunk_size]`` (see
    `streams.Recorder` docstring), so the slice log_data returns —
    ``[detected_sample - pretrig_samples : ...]`` — places the crossing
    sample at relative index ``pretrig_samples``. Samples before that
    are all sub-threshold pre-trigger context.

    Requires a working ao0 → ai0 loopback (auto-skipped otherwise).
    """
    if not _has_ao_to_ai_loopback(device_entry, device_index):
        pytest.skip(
            'No ao0 → ai0 loopback detected on {} ({}).'
            .format(device_entry['name'], device_entry['product_type'])
        )
    s = _settings_for(device_entry, device_index, channels=1,
                      stored_time=0.3, pretrig=True)
    # pretrig_samples must stay <= chunk_size (default 100); 50 is a
    # comfortable working value that leaves headroom either side.
    amp_v = 1.5
    _, y = dvma.signal_generator(
        s, sig='sweep', T=0.15, amplitude=amp_v, f=[200, 1000],
    )
    ds = dvma.log_data(s, output=y)
    ai = ds.time_data_list[0].time_data[:, 0]

    assert ds.time_data_list[0].time_data.shape == (int(0.3 * s.fs), 1)

    hits = np.where(np.abs(ai) > s.pretrig_threshold)[0]
    assert len(hits) > 0, (
        'no above-threshold samples in returned buffer on {} — '
        'stimulus did not reach AI, positioning test cannot run'
        .format(device_entry['product_type'])
    )
    first_hit = int(hits[0])
    assert first_hit == s.pretrig_samples, (
        'first above-threshold sample landed at index {} on {}; '
        'expected exactly {} (pretrig_samples). State machine '
        'invariant violated.'.format(
            first_hit, device_entry['product_type'], s.pretrig_samples,
        )
    )

    # Samples strictly before the trigger index must all be quiet —
    # `pretrig_samples` of genuine pre-trigger context.
    pre = ai[:s.pretrig_samples]
    assert np.max(np.abs(pre)) <= s.pretrig_threshold, (
        'pre-trigger window on {} contains above-threshold sample '
        '(max {:.3f} vs threshold {:.3f})'
        .format(device_entry['product_type'], np.max(np.abs(pre)),
                s.pretrig_threshold)
    )


def _supports_iepe(device_entry):
    """Look up the device's IEPE capability through `_ni_device_specs`.

    Returns the list of supported excitation currents in amps (e.g.
    ``[0.0, 0.002]`` on the 9234, ``[]`` on USB-600x / 621x).
    """
    if device_entry['is_chassis']:
        for mod in device_entry['module_names']:
            if device_entry['module_ai_counts'].get(mod, 0) > 0:
                vals = dvma.get_device_info(mod).get(
                    'ai_current_int_excit_discrete_vals', []
                )
                return [v for v in vals if v > 0]
        return []
    return [v for v in dvma.get_device_info(device_entry['name'])
            .get('ai_current_int_excit_discrete_vals', []) if v > 0]


def test_iepe_excitation_applies(device_entry, device_index):
    """Configuring `iepe_excit_current_A=2 mA` on an IEPE-capable device
    actually programs the AI task with that current and AC coupling.

    Verified by reading back ``ai_excit_val`` and ``ai_coupling`` on
    each task channel after start. Auto-skipped on devices without
    IEPE support.
    """
    iepe_vals = _supports_iepe(device_entry)
    if not iepe_vals:
        pytest.skip('{} has no IEPE support'.format(device_entry['product_type']))
    target_current = iepe_vals[0]   # the lowest non-zero value the device offers

    s = _settings_for(device_entry, device_index,
                      channels=1, stored_time=0.1)
    s.iepe_excit_current_A[0] = target_current
    s.channel_sensitivities[0] = 0.1     # 100 mV/g placeholder

    # Capture briefly to force the AI task through its full setup path.
    ds = dvma.log_data(s)
    td = ds.time_data_list[0]
    assert td.time_data.shape == (int(0.1 * s.fs), 1)

    # Sensitivity should have flowed through to the cal_factors.
    assert np.isclose(td.channel_cal_factors[0], 10.0), (
        'cal_factors[0] = {}, expected 10.0 (= 1 / 0.1 V/g)'
        .format(td.channel_cal_factors[0])
    )

    # And the AI task that just ran was configured with IEPE on.
    rec = streams.REC
    task = rec.audio_stream
    chs = list(task.ai_channels)
    assert abs(chs[0].ai_excit_val - target_current) < 1e-9, (
        'ai_excit_val = {} A, expected {} A'
        .format(chs[0].ai_excit_val, target_current)
    )
    assert chs[0].ai_coupling.name == 'AC', (
        'IEPE-enabled channel should be AC-coupled, got {}'
        .format(chs[0].ai_coupling.name)
    )


def test_stream_reuses_when_signature_matches(device_entry, device_index):
    """`log_data` calls with matching hardware settings should reuse
    the existing live AI task — same task handle, same recorder
    instance — rather than tearing down and rebuilding. This is what
    preserves IEPE settling between calls.
    """
    s = _settings_for(device_entry, device_index, channels=1, stored_time=0.1)
    dvma.log_data(s)
    rec1 = streams.REC
    task1 = rec1.audio_stream
    dvma.log_data(s)
    rec2 = streams.REC
    task2 = rec2.audio_stream
    assert rec1 is rec2, 'recorder instance should be reused'
    assert task1 is task2, 'AI task should be reused (preserves IEPE settling)'


def test_stream_rebuilds_when_signature_changes(device_entry, device_index):
    """Changing a hardware-impacting setting (here, fs) forces a
    teardown + rebuild. The task handle should change."""
    s1 = _settings_for(device_entry, device_index, channels=1, stored_time=0.1, fs=2000)
    dvma.log_data(s1)
    task1 = streams.REC.audio_stream
    s2 = _settings_for(device_entry, device_index, channels=1, stored_time=0.1, fs=4000)
    dvma.log_data(s2)
    task2 = streams.REC.audio_stream
    assert task1 is not task2, (
        'fs change should have rebuilt the AI task; got the same task '
        'object back'
    )


def test_iepe_rejected_on_unsupported_device(device_entry, device_index):
    """Requesting IEPE on a non-IEPE device fails loudly at stream
    setup with a clear ValueError.
    """
    if _supports_iepe(device_entry):
        pytest.skip('{} supports IEPE; this test covers the unsupported '
                    'devices'.format(device_entry['product_type']))
    s = _settings_for(device_entry, device_index,
                      channels=1, stored_time=0.1)
    s.iepe_excit_current_A[0] = 0.002
    with pytest.raises(ValueError, match='iepe_excit_current_A'):
        dvma.log_data(s)


def test_iepe_warmup_settles_bias_transient(device_entry, device_index):
    """With IEPE freshly enabled, the AC-coupling HPF on the 9234
    produces a multi-second bias-settling transient (mean drifts
    from sensor bias to 0). The recorder is supposed to block for
    `_IEPE_WARMUP_S` after task.start() so the next capture is
    settled. Verify by tearing down any leftover stream, doing a
    single fresh capture, and checking the captured waveform's
    absolute mean is much smaller than the un-warmed transient
    would have been (~3 V on this lab's accel + 100 mV/g cal).

    Auto-skipped on non-IEPE devices.
    """
    iepe_vals = _supports_iepe(device_entry)
    if not iepe_vals:
        pytest.skip('{} has no IEPE support'.format(device_entry['product_type']))

    # Fully tear down any prior task so the next start_stream is a
    # genuine cold start (worst case for the transient).
    if streams.REC is not None:
        streams.REC.end_stream()
    streams.REC = None
    streams.REC_NI = None

    s = _settings_for(device_entry, device_index,
                      channels=1, stored_time=0.5)
    s.iepe_excit_current_A[0] = iepe_vals[0]   # 0.002 A on the 9234

    ds = dvma.log_data(s)
    y = ds.time_data_list[0].time_data[:, 0]

    # Empirical: pre-warmup, fresh-IEPE captures show |mean| ~ 3 V on
    # the lab's connected accel. Post-warmup, |mean| should be at the
    # noise floor (mV-range) regardless of whether the sensor sees
    # any motion. A 0.5 V threshold catches the un-warmed regression
    # cleanly while leaving headroom for genuine accelerometer signal.
    assert abs(y.mean()) < 0.5, (
        '|mean| = {:.3f} V on {} -- IEPE warmup did not settle the '
        'bias transient (expected < 0.5 V post-warmup)'
        .format(abs(y.mean()), device_entry['product_type'])
    )


def test_iepe_off_default(device_entry, device_index):
    """Default settings produce no IEPE excitation. Verifies that the
    log_data path completes cleanly without any per-channel
    excitation programming — important on non-IEPE devices where
    even querying the property raises DAQmx -200452."""
    s = _settings_for(device_entry, device_index,
                      channels=1, stored_time=0.1)
    # No iepe_excit_current_A override -> defaults to all zeros
    assert np.all(s.iepe_excit_current_A == 0.0)
    # Should not raise on any device, IEPE-capable or not.
    dvma.log_data(s)
    # On IEPE-capable devices the property is queryable; verify it
    # really is at zero. On non-IEPE devices the property doesn't
    # exist, so we just confirm the capture succeeded above.
    if _supports_iepe(device_entry):
        chs = list(streams.REC.audio_stream.ai_channels)
        assert chs[0].ai_excit_val == 0.0


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


def test_dsa_fs_coercion_adopts_actual_rate(device_entry, device_index):
    """DSA modules silently coerce off-ladder sample rates (measured on
    the real NI 9234: requesting 8000 Hz actually samples at
    8533.33 Hz). The recorder must adopt the true rate into
    ``settings.fs`` so time/frequency axes and .dvma metadata stay
    correct, and a repeat request at the original rate must still
    REUSE the running task (else every capture would repeat the ~2 s
    IEPE warmup)."""
    from pydvma import _ni_backend
    caps = _ni_backend.entry_capabilities(device_entry)
    if not caps.get('simultaneous'):
        pytest.skip('rate-ladder coercion applies to DSA hardware only')

    s = _settings_for(device_entry, device_index, channels=1,
                      stored_time=0.2, fs=8000)
    ds = dvma.log_data(s)
    rec = dvma.streams.REC
    actual = float(rec.audio_stream.timing.samp_clk_rate)
    assert s.fs == pytest.approx(actual)
    assert s.fs != 8000  # 8000 is off the 9234 ladder — must have moved
    assert ds.time_data_list[0].time_data.shape[0] == int(0.2 * s.fs)

    # Re-request the ORIGINAL rate: same hardware config -> stream reuse
    # (and the caller's settings adopt the coerced rate again).
    s2 = _settings_for(device_entry, device_index, channels=1,
                       stored_time=0.2, fs=8000)
    dvma.streams.start_stream(s2)
    assert dvma.streams.REC is rec
    assert s2.fs == pytest.approx(actual)


def test_lpf_log_respects_per_channel_max_rate(device_entry, device_index):
    """``lpf_on`` log on real hardware: TimeData comes back at the
    target fs with ``lpf_capture_fs`` recorded, and the oversampled
    capture never exceeds what the device can actually sustain for the
    channel count — on a MULTIPLEXED device (one ADC scanning the
    channel list) the advertised ``ai_max_rate`` is an AGGREGATE
    figure, so the per-channel ceiling is that divided by the number
    of channels. Simultaneous (DSA) devices sample per-channel and may
    use the full rate (their ladder may coerce the capture upward a
    step, but never past the per-channel max)."""
    from pydvma import _ni_backend
    caps = _ni_backend.entry_capabilities(device_entry)
    target_fs = 2000
    n_ch = 2
    s = _settings_for(device_entry, device_index, channels=n_ch,
                      stored_time=0.5, fs=target_fs)
    s.lpf_on = True
    ds = dvma.log_data(s)
    td = ds.time_data_list[0]
    fs_out = float(td.settings.fs)
    assert fs_out == pytest.approx(target_fs), (
        'lpf_on TimeData fs {} != target {}'.format(fs_out, target_fs))
    cap_fs = getattr(td.settings, 'lpf_capture_fs', None)
    assert cap_fs is not None and cap_fs >= 2 * target_fs, cap_fs
    assert td.time_data.shape == (int(0.5 * fs_out), n_ch)
    assert np.isfinite(td.time_data).all()

    per_channel_max = float(caps['ai_max_rate'])
    if not caps.get('simultaneous'):
        per_channel_max /= n_ch
    assert cap_fs <= per_channel_max * (1 + 1e-9), (
        'capture ran at {} Hz but the per-channel ceiling for {} at '
        '{} channels is {} Hz — aggregate ai_max_rate not divided?'
        .format(cap_fs, device_entry['product_type'], n_ch,
                per_channel_max)
    )


def test_lpf_antialiases_out_of_band_stimulus(device_entry, device_index):
    """The point of the digital low-pass: on a multiplexed device (no
    analog anti-alias filter) a tone above the target Nyquist folds
    in-band at full amplitude when logging directly at fs; with
    ``lpf_on`` the oversampled capture keeps the tone real and the
    decimation FIR (96 dB stopband at the new Nyquist) removes it,
    while in-band content passes at unity.

    Drives 400 Hz (in-band) + 1300 Hz (above the 1 kHz target Nyquist)
    through the ao0 → ai0 loopback at output_fs=20 kHz and logs at
    fs=2000 with lpf_on off/on. DSA devices are skipped — their
    hardware anti-aliasing means the 'off' capture never aliases, so
    there is nothing to compare. Software-timed-AO devices (USB-600x,
    AO max 5 kS/s) can't play the 20 kHz drive and are skipped too."""
    from pydvma import _ni_backend
    caps = _ni_backend.entry_capabilities(device_entry)
    if caps.get('simultaneous'):
        pytest.skip('DSA hardware anti-aliases in hardware; the '
                    'unfiltered comparison capture cannot alias')
    out_fs = 20000
    if not caps.get('ao_max_rate') or caps['ao_max_rate'] < out_fs:
        pytest.skip('device AO cannot play a {} S/s drive'.format(out_fs))
    if not _has_ao_to_ai_loopback(device_entry, device_index):
        pytest.skip('No ao0 → ai0 loopback detected on {} ({}).'
                    .format(device_entry['name'],
                            device_entry['product_type']))

    target_fs = 2000
    f_in, f_out = 400.0, 1300.0   # 1300 folds to 700 in a 2 kHz capture
    t = np.arange(0, 1.4, 1.0 / out_fs)
    n_ramp = int(0.05 * out_fs)
    win = np.ones_like(t)
    win[:n_ramp] = 0.5 * (1 - np.cos(np.pi * np.arange(n_ramp) / n_ramp))
    win[-n_ramp:] = 0.5 * (1 + np.cos(np.pi * np.arange(n_ramp) / n_ramp))
    drive = (0.5 * np.sin(2 * np.pi * f_in * t)
             + 0.5 * np.sin(2 * np.pi * f_out * t)) * win

    def tone_amp(sig, fs, f):
        n = len(sig)
        w = np.hanning(n)
        spec = np.abs(np.fft.rfft(sig * w)) * 2 / np.sum(w)
        freqs = np.fft.rfftfreq(n, 1.0 / fs)
        k = int(np.argmin(np.abs(freqs - f)))
        return float(np.max(spec[max(0, k - 2):k + 3]))

    amps = {}
    for lpf in (False, True):
        cfg = _config_for_device(device_entry)
        s = dvma.MySettings(
            device_driver='nidaq', device_index=device_index,
            channels=2, fs=target_fs, stored_time=1.6,
            output_device_driver='nidaq', output_device_index=device_index,
            output_channels=1, output_fs=out_fs, lpf_on=lpf, **cfg,
        )
        ds = dvma.log_data(s, output=drive[:, None])
        td = ds.time_data_list[0]
        fs = float(td.settings.fs)
        y = np.asarray(td.time_data)[:, 0]
        seg = y[int(0.3 * fs):int(1.1 * fs)]   # steady mid-tone window
        amps[lpf] = (tone_amp(seg, fs, f_in), tone_amp(seg, fs, 700.0))

    in_off, alias_off = amps[False]
    in_on, alias_on = amps[True]
    # In-band tone preserved either way (passband to fs/2.56 = 781 Hz).
    assert 0.35 < in_off < 0.65, in_off
    assert 0.35 < in_on < 0.65, in_on
    # Without the LPF the out-of-band tone folds in at full strength...
    assert alias_off > 0.3, (
        'expected the unfiltered capture to alias (~0.5 V at 700 Hz), '
        'got {:.3f} V'.format(alias_off))
    # ...and the LPF must crush it (FIR stopband is 96 dB; allow a
    # generous 40 dB margin for loopback noise floor).
    assert alias_on < alias_off / 100, (
        'alias only dropped from {:.4f} to {:.4f} V with lpf_on — '
        'anti-alias filtering not effective'.format(alias_off, alias_on))


