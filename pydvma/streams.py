from . import acquisition
from . import _ni_backend
from . import _coreaudio

import copy
import numpy as np
import pprint as pp
import time

try:
    import sounddevice as sd
except (ImportError, NotImplementedError, OSError):
    # OSError = package present but the PortAudio C library is
    # missing (default on ubuntu CI runners and some student
    # machines); treat it the same as sounddevice being absent.
    sd = None


try:
    import nidaqmx as ni
    from nidaqmx.stream_readers import AnalogMultiChannelReader
except ImportError:
    ni = None
    AnalogMultiChannelReader = None
except NotImplementedError:
    ni = None
    AnalogMultiChannelReader = None


#%% Handles the different cases of starting soundcard/NI streams


REC_SC = None # create global variable for creating only a single NI stream instance. Not needed for pyaudio.
REC_NI = None
REC_MOCK = None  # hardware-free test backend; see MockRecorder
REC = None


def _ni_recorder_class(settings):
    if ni is None:
        raise RuntimeError('nidaqmx is not installed; pip install nidaqmx')
    return Recorder_NI_nidaqmx


# IEPE warmup time in seconds. When excitation is freshly applied
# at task.start(), the sensor's DC bias rises through the AC-coupling
# HPF on the 9234 (~0.32 s RC time constant), creating a settling
# transient that decays exponentially. 2 s is ~6 RC time constants,
# i.e. settled to <0.3 % of the original bias step. Applied
# unconditionally inside `_build_and_start_ai_task` whenever any
# channel has IEPE enabled — keeps the data clean by default
# without exposing yet another setting. The `start_stream` reuse
# path (below) keeps an already-warmed task alive across log_data
# calls, so this 2 s cost is paid only on a genuine hardware-config
# change (different device, channels, fs, IEPE current, ...).
_IEPE_WARMUP_S = 2.0


def _ni_settings_signature(s):
    """Tuple of hardware-impacting AI-task settings.

    If the new settings' signature matches the running stream's, we
    can reuse the existing AI task and preserve its IEPE settling
    state. If anything in this tuple differs, the task must be torn
    down and rebuilt.

    Deliberately absent: ``pretrig_*`` and ``channel_sensitivities``,
    which only affect log_data's read-side processing — they don't
    re-program the hardware. ``output_*`` is also absent: those go to
    the separate AO task built by `setup_output_NI`, not the AI
    task this signature governs.
    """
    return (
        s.device_driver,
        s.device_index,
        int(s.channels),
        s.input_channels_spec,
        int(s.fs),
        int(s.chunk_size),
        int(s.num_chunks),
        s.NI_mode,
        float(s.VmaxNI),
        float(s.stored_time),  # affects stored_time_data buffer size
        tuple(np.asarray(s.iepe_excit_current_A).tolist()),
    )


def _clamp_soundcard_input_channels(settings):
    '''Clamp ``settings.channels`` to the soundcard input device's
    ``max_input_channels``, mutating ``settings`` in place.

    Why this exists: ``sd.InputStream(channels=N)`` raises PortAudio
    error ``-9998`` (paInvalidChannelCount) when ``N`` exceeds the
    device's reported capability. The default ``MySettings()`` asks
    for ``channels=2``, but a Mac built-in microphone is typically
    mono — so the default path failed cryptically on Mac before this
    clamp. The NI backend already validates analogously (raises
    ``ValueError``) — see `Recorder_NI_nidaqmx.__init__`. Soundcard
    clamps rather than raises because the GUI's
    ``setup_frame_tools_settings`` silently auto-builds default
    settings when the user passes none, so raising would surface an
    error against a value the user never picked.

    Called from `start_stream` *before* `Recorder(settings)` is
    constructed, so the clamped value flows into both buffer
    allocation (`Recorder.__init__`) and the actual
    `sd.InputStream` opening (`Recorder.init_stream`). A no-op when
    ``sd`` is unavailable, when the device default can't be resolved,
    or when ``settings.channels`` already fits.
    '''
    if sd is None:
        return
    if settings.device_index is None:
        try:
            settings.device_index = sd.default.device[0]
        except (AttributeError, TypeError, IndexError):
            return
    try:
        in_info = sd.query_devices(settings.device_index)
    except (sd.PortAudioError, ValueError, TypeError):
        return
    max_in = int(in_info['max_input_channels'])
    if settings.channels > max_in:
        print("WARNING: input device %r supports only %d input channel(s); "
              "requested channels=%d. Clamping to %d."
              % (in_info['name'], max_in, settings.channels, max_in))
        settings.channels = max_in
    _warn_about_loopback_channels(settings, in_info['name'])


def _warn_about_loopback_channels(settings, device_name):
    '''Warn when the requested channels include a digital loopback.

    Not every input a device advertises is wired to the outside world:
    a Scarlett 2i2 4th Gen reports four, of which 3-4 are a DIGITAL
    LOOPBACK of its own output mix. Recorded unknowingly they look like
    a pair of silent channels — or, if anything is playing, like
    plausible data that is actually the interface listening to itself.

    The web UI shows this in Setup; this is the equivalent for the
    notebook / script path. Silent for devices with no profile in
    ``_soundcard_specs`` and whenever no loopback channel is included.
    '''
    from . import _soundcard_specs
    loopback = _soundcard_specs.loopback_channels(
        device_name, settings.channels,
        neighbours=all_soundcard_device_names())
    if not loopback:
        return
    print('WARNING: on %r, input channel(s) %s are a DIGITAL LOOPBACK of the '
          'device output, not analogue inputs — they carry whatever the '
          'interface is playing. Reduce channels to %d to record only the '
          'analogue inputs.'
          % (device_name, ', '.join(str(i + 1) for i in loopback), loopback[0]))


def _clamp_soundcard_output_channels(settings):
    '''Clamp ``settings.output_channels`` to the soundcard output
    device's ``max_output_channels``, mutating ``settings`` in place.

    Mirror of `_clamp_soundcard_input_channels` for the output path.
    Called from `setup_output_soundcard` because output streams are
    opened on a separate code path from input (`acquisition.output_signal`
    → `setup_output_soundcard`), not via `start_stream`. A no-op when
    ``sd`` is unavailable, the output device can't be resolved, or
    ``settings.output_channels`` already fits.
    '''
    if sd is None:
        return
    if settings.output_device_index is None:
        try:
            settings.output_device_index = sd.default.device[1]
        except (AttributeError, TypeError, IndexError):
            return
    try:
        out_info = sd.query_devices(settings.output_device_index)
    except (sd.PortAudioError, ValueError, TypeError):
        return
    max_out = int(out_info['max_output_channels'])
    if settings.output_channels > max_out:
        print("WARNING: output device %r supports only %d output channel(s); "
              "requested output_channels=%d. Clamping to %d."
              % (out_info['name'], max_out, settings.output_channels, max_out))
        settings.output_channels = max_out


# Nominal "hardware" ceiling for the synthetic mock backend — it has no real
# limit, this just gives the digital-low-pass oversampler headroom in tests.
MOCK_MAX_FS = 1_000_000


def all_soundcard_device_names():
    """Names of every PortAudio device currently present, or ``[]``.

    Exists for profile resolution on Windows, where an endpoint's own
    name does not identify the hardware model (a Scarlett 2i2 enumerates
    as generic ``'Analogue 1 + 2 (Focusrite USB Audio)'``) but the
    WDM-KS twin of the same hardware embeds the USB product id — see
    ``_soundcard_specs.device_profile``.
    """
    if sd is None:
        return []
    try:
        return [d['name'] for d in sd.query_devices()]
    except Exception:
        return []


def soundcard_device_name(settings):
    """Name of the configured soundcard input device, or None.

    Resolves an unset ``device_index`` through PortAudio's default input
    device the same way :meth:`Recorder.init_stream` does, so capability
    queries and the stream that follows always describe the same device.
    """
    if sd is None or settings.device_driver != 'soundcard':
        return None
    try:
        index = settings.device_index
        if index is None:
            index = sd.default.device[0]
        return sd.query_devices()[int(index)]['name']
    except Exception:
        return None


# Standard audio rate ladder, ascending — probed against a host API that
# refuses rather than resamples, this yields a device's real capability.
_RATE_LADDER = (8000, 11025, 16000, 22050, 32000, 44100, 48000,
                64000, 88200, 96000, 176400, 192000)

# Windows host APIs that report a device's OWN capability. Both bypass
# the shared-mode audio engine, so `check_input_settings` against them
# refuses a rate the hardware cannot clock. WASAPI is tried first
# because its device names come from the same endpoint as the MME /
# DirectSound entries and therefore match exactly; WDM-KS names come
# from the kernel-streaming filter and can differ (on a Scarlett 2i2 the
# WDM-KS twin embeds the USB product id where the endpoint name does
# not — see `_soundcard_specs.device_profile`).
_WINDOWS_HONEST_HOSTAPIS = ('Windows WASAPI', 'Windows WDM-KS')


def _windows_native_rates(name, channels):
    """Rate ladder a Windows device can GENUINELY clock, ascending.

    Windows exposes one piece of hardware once per host API, and only
    some of those entries tell the truth about rate. MME and DirectSound
    run through the shared-mode audio engine, which accepts ANY rate and
    sample-rate-converts to the endpoint's Default Format — measured on
    an ESI U24 XL (2026-08-12): a "192 kHz" MME capture of a 44.1 kHz
    endpoint carries a dead-flat dither floor above 22 kHz and no
    information at all, and even a plain 48 kHz request is converted.
    WASAPI exclusive mode and WDM-KS bypass the engine and refuse, so
    probing one of THOSE twins of the same hardware gives the real
    ladder.

    Args:
        name (str): PortAudio device name to find a twin of, as reported
            for the endpoint the caller actually configured.
        channels (int): Channel count to probe with — a rate can be
            available at one channel count and not another.

    Returns the accepted rates in ascending order, or ``[]`` when the
    platform is not Windows, no twin is found, or every probe fails
    (meaning "capability unknown", exactly as on an unsupported
    platform). Matching is by exact name first, then by prefix, which
    covers MME truncating names to 31 characters.
    """
    if sd is None or not name:
        return []
    try:
        extra = sd.WasapiSettings(exclusive=True)
    except Exception:
        # Not Windows, or a sounddevice too old to offer the setting.
        return []

    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:
        return []

    def twins(api_name):
        out = []
        for i, dev in enumerate(devices):
            if not dev['max_input_channels']:
                continue
            try:
                if hostapis[dev['hostapi']]['name'] != api_name:
                    continue
            except (IndexError, KeyError):
                continue
            other = dev['name']
            if other == name or other.startswith(name) or name.startswith(other):
                out.append(i)
        return out

    for api_name in _WINDOWS_HONEST_HOSTAPIS:
        exclusive = extra if api_name == 'Windows WASAPI' else None
        for index in twins(api_name):
            rates = []
            for rate in _RATE_LADDER:
                try:
                    sd.check_input_settings(device=index,
                                            channels=int(channels),
                                            samplerate=rate,
                                            extra_settings=exclusive)
                    rates.append(float(rate))
                except Exception:
                    continue
            if rates:
                return rates
    return []


def enumerated_device_names(driver):
    """Names of every device a driver can currently see, by index.

    The list is positional: element ``i`` is the name of device index
    ``i`` for that driver, which is what makes it usable for checking a
    stored index still points where it did.

    Args:
        driver (str): ``'soundcard'`` or ``'nidaq'``. Anything else
            (including ``'mock'``) returns ``[]``.

    Returns the names as a list of strings, or ``[]`` when the driver is
    unrecognised or its enumeration raises — enumeration is best-effort
    and must never be the reason a capture cannot start.
    """
    try:
        if driver == 'soundcard':
            if sd is None:
                return []
            return [d['name'] for d in sd.query_devices()]
        if driver == 'nidaq':
            return [e['name'] for e in _ni_backend.enumerate_devices()]
    except Exception:
        return []
    return []


def enumerated_device_hostapis(driver):
    """Host-API name of every device a driver can see, by index.

    Positional, matching :func:`enumerated_device_names`. Only
    meaningful for ``'soundcard'``: PortAudio lists ONE piece of
    hardware once per host API, and on Windows those entries routinely
    share an identical name (an ESI U24 XL's line input appears as
    ``'Line (U24XL with SPDIF I/O)'`` under all four of MME,
    DirectSound, WASAPI and WDM-KS). The host API is then the only thing
    telling them apart, which makes it half of the device's identity —
    see :func:`resolve_device_index`.

    Args:
        driver (str): ``'soundcard'`` or ``'nidaq'``.

    Returns a list of host-API name strings (``None`` for any entry
    whose host API cannot be read), or ``[]`` for a driver with no host
    API concept or when enumeration raises.
    """
    if driver != 'soundcard' or sd is None:
        return []
    try:
        hostapis = sd.query_hostapis()
        out = []
        for dev in sd.query_devices():
            try:
                out.append(hostapis[dev['hostapi']]['name'])
            except (IndexError, KeyError, TypeError):
                out.append(None)
        return out
    except Exception:
        return []


def resolve_device_index(driver, index, expected_name, expected_hostapi=None):
    """Re-point a stale ``device_index`` at the device it was chosen for.

    Device indices are POSITIONS in an enumeration, not identities, and
    the enumeration is not stable. Observed live twice: a Scarlett 2i2
    moved from index 2 to index 1 once another interface left the list
    (2026-08-10), and on Windows the whole WDM-KS block reordered
    between two enumerations minutes apart with no hardware change at
    all and the same device count — an ESI U24 XL's input moved from
    index 36 to 27 (2026-08-12). Either way the next capture records a
    different device: the wrong signal, under the right name, with no
    error. With a profile-derived ``VmaxSC`` it would also carry the
    wrong voltage scale.

    The defence is to remember the NAME the index was chosen for and
    check the two still agree.

    On Windows the name alone is NOT an identity: PortAudio lists one
    piece of hardware once per host API, all four entries sharing a
    name, so a name-only match finds four candidates and has to give up
    exactly where the protection is most needed. Passing
    ``expected_hostapi`` narrows the search to the backend the index was
    chosen on, which is what makes following a reordered WDM-KS block
    possible.

    Args:
        driver (str): ``'soundcard'`` or ``'nidaq'``.
        index (int or None): The stored device index to check.
        expected_name (str or None): Name the caller believes ``index``
            refers to.
        expected_hostapi (str or None): Host-API name the index was
            chosen on, e.g. ``'Windows WDM-KS'`` (default ``None`` =
            match on name alone, the right behaviour on platforms that
            list each device once).

    Returns ``(index, note_or_None)``: the index unchanged when the
    names agree or there is nothing to check; the NEW index plus an
    explanatory note when the name has moved; and raises ``ValueError``
    when the name is gone entirely, because continuing would record
    silence or the wrong instrument. A name still AMBIGUOUS after the
    host API has been applied is left alone — two identical interfaces
    on one backend make the index the only thing telling them apart, so
    second-guessing it would be a downgrade.
    """
    if not expected_name or index is None:
        return index, None
    names = enumerated_device_names(driver)
    if not names:
        return index, None
    hostapis = enumerated_device_hostapis(driver)

    def same_device(i):
        if names[i] != expected_name:
            return False
        if expected_hostapi and i < len(hostapis) and hostapis[i] is not None:
            return hostapis[i] == expected_hostapi
        return True

    idx = int(index)
    if 0 <= idx < len(names) and same_device(idx):
        return index, None

    matches = [i for i in range(len(names)) if same_device(i)]
    if len(matches) == 1:
        return matches[0], (
            '%r moved from device index %d to %d since the device list '
            'was read; using %d.'
            % (expected_name, idx, matches[0], matches[0]))
    if not matches:
        found = names[idx] if 0 <= idx < len(names) else 'nothing'
        where = ' on %s' % expected_hostapi if expected_hostapi else ''
        raise ValueError(
            '%r%s is no longer connected — device index %d is now %r. '
            'Refresh the device list and choose again rather than '
            'recording the wrong input.' % (expected_name, where, idx, found))
    return index, None


def native_input_rates(settings):
    """Sample rates the configured device can GENUINELY run at, ascending.

    Answered on macOS via CoreAudio's published rate list, and on
    Windows by probing a WASAPI-exclusive or WDM-KS twin of the same
    hardware (see :func:`_windows_native_rates`). Anywhere else — and
    whenever the query fails — this returns an empty list, meaning
    "capability unknown", and callers fall back to the older probe-based
    behaviour.

    The distinction matters because ``sd.check_input_settings`` is not a
    capability probe against a resampling host API. On macOS it approves
    any rate CoreAudio is willing to RESAMPLE to, which is all of them:
    a Scarlett 2i2 accepts a 3 kHz request while its hardware ladder
    starts at 44.1 kHz, and the resulting conversion is silent and of
    ratio-dependent quality (see ``pydvma._coreaudio``). Windows MME and
    DirectSound behave the same way through the shared-mode audio
    engine. Asking hardware that refuses is the only way to know what a
    capture will really run at.
    """
    if settings.device_driver != 'soundcard':
        return []
    name = soundcard_device_name(settings)
    if not name:
        return []
    if _coreaudio.available():
        device_id, _ = _coreaudio.find_device(name)
        if device_id is None:
            return []
        return _coreaudio.native_rates(device_id)
    return _windows_native_rates(name, getattr(settings, 'channels', 1) or 1)


def output_shares_input_clock(settings):
    """True when playback and capture must run at the SAME rate.

    A USB audio interface has one clock for the whole device, so an
    output stream cannot run at a rate different from the capture. Ask
    for one and the OS either resamples the stimulus silently or refuses
    both streams outright (PortAudio ``-50`` on CoreAudio) — neither is
    acceptable for a swept-sine excitation.

    Separate devices keep separate clocks and may differ freely, so this
    is False whenever input and output resolve to different hardware, and
    False for NI (whose AO rate is independently configurable, subject to
    its own ``ao_max_rate`` cap).
    """
    if settings.device_driver != 'soundcard':
        return False
    if getattr(settings, 'output_device_driver', None) != 'soundcard':
        return False
    in_index = settings.device_index
    out_index = getattr(settings, 'output_device_index', None)
    if in_index is None or out_index is None:
        return False
    if int(in_index) == int(out_index):
        return True
    # Different PortAudio indices can still be one piece of hardware
    # (CoreAudio exposes a device once, PortAudio may list it per
    # direction), so compare the underlying devices where we can.
    if not _coreaudio.available() or sd is None:
        return False
    try:
        names = sd.query_devices()
        in_dev, _ = _coreaudio.find_device(names[int(in_index)]['name'])
        out_dev, _ = _coreaudio.find_device(names[int(out_index)]['name'])
    except Exception:
        return False
    return in_dev is not None and in_dev == out_dev


def hardware_antialiases(settings):
    """Does the device filter above its own Nyquist before sampling?

    True for converters that anti-alias in silicon at the converter rate
    (delta-sigma: every audio interface, and NI DSA modules such as the
    9234), False for a filterless multiplexed SAR front end
    (USB-6003/6212), and None when it cannot be determined.

    This is the physical fact behind :func:`oversample_strategy`. Where
    it is True, content above the capture Nyquist is already gone before
    the ADC, so capturing faster buys no extra alias rejection for the
    target band. Where it is False, capturing faster is the ONLY alias
    protection the hardware offers, because anything above Nyquist folds
    in at sampling time and no amount of later filtering can separate it.
    """
    driver = settings.device_driver
    if driver == 'soundcard':
        # Audio-class converters are delta-sigma; the anti-alias filter
        # is inherent and locked to the sample rate (this is why the
        # 2i2's rate ladder starts at 44.1 kHz at all).
        return True
    if driver == 'nidaq':
        try:
            entries = _ni_backend.enumerate_devices()
            idx = settings.device_index if settings.device_index is not None else 0
            return bool(_ni_backend.entry_capabilities(entries[idx]).get('simultaneous'))
        except Exception:
            return None
    return None


def oversample_strategy(settings):
    """How far above ``fs`` to capture: ``'lowest'`` or ``'highest'``.

    ``'lowest'`` takes the first available rate with real headroom over
    the target; ``'highest'`` takes the fastest the device offers.
    ``settings.oversample`` selects explicitly; ``'auto'`` (the default)
    follows :func:`hardware_antialiases`, because that is the fact the
    choice actually turns on:

    - **Anti-aliased in silicon → 'lowest'.** Sound cards and NI DSA
      modules (the 9234) are delta-sigma, so content above the capture
      Nyquist is already gone before the ADC. Capturing faster rejects
      nothing extra — for a 3 kHz target on a 2i2, 192 kHz would carry
      4.35x the data for no alias benefit. It does still buy
      ~10·log10(M) dB of broadband-noise process gain, so ``'highest'``
      remains available when noise floor matters more than data volume.
    - **Not anti-aliased → 'highest'.** Mandatory on the multiplexed SAR
      devices (USB-6003/6212): anything above Nyquist folds in at
      sampling time and no later filtering can separate it, so a high
      capture rate is the only protection there is.
    - **Unknown (mock, probe failure) → 'highest'** — the safe side.

    Note the NI ceiling is per-CHANNEL: on a multiplexed device
    :func:`max_input_fs` divides the aggregate ``ai_max_rate`` by the
    channel count, so 'highest' already accounts for channel sharing.
    """
    explicit = getattr(settings, 'oversample', 'auto')
    if explicit in ('lowest', 'highest'):
        return explicit
    return 'lowest' if hardware_antialiases(settings) is True else 'highest'


def select_capture_fs(settings, native=None):
    """Choose the rate the hardware should actually run at, in Hz.

    Returns ``(capture_fs, reason)`` where ``reason`` is a short tag
    naming which rule applied — ``'exact'``, ``'explicit'``,
    ``'oversample'``, ``'lowest-native'`` or ``'unknown'`` — so callers
    can phrase an accurate message rather than guessing.

    The target rate ``settings.fs`` is what the caller wants DELIVERED;
    the capture rate is what the converter runs at, and the two differ
    whenever the hardware cannot produce the target directly. Rules, in
    order:

    - ``settings.capture_fs`` set explicitly wins, snapped to the nearest
      native rate when the ladder is known (``'explicit'``).
    - With the digital low-pass on, capture at the LOWEST native rate at
      or above ``2.56 * fs`` (``'oversample'``). Audio converters are
      delta-sigma with an anti-alias filter locked to the converter rate,
      so everything above the capture Nyquist is already gone in silicon
      — capturing higher buys no extra alias rejection for the target
      band, only data volume. This is the opposite of the filterless
      multiplexed-SAR case (USB-6003/6212), where capturing as fast as
      possible IS the only alias protection; those devices keep the
      ``max_input_fs`` rule in ``acquisition.log_data``.
    - Target rate already native: capture there, no resampling
      (``'exact'``).
    - Otherwise capture at the lowest native rate above the target and
      decimate in software (``'lowest-native'``) — a rate the hardware
      cannot run is otherwise served by CoreAudio's own converter, whose
      alias rejection was measured as poor as 12 dB.

    With no ladder available the target is returned unchanged
    (``'unknown'``) and the device does whatever it was going to do.
    """
    target = float(settings.fs)
    if native is None:
        native = native_input_rates(settings)
    explicit = getattr(settings, 'capture_fs', None)

    if explicit is not None:
        explicit = float(explicit)
        if native:
            at_or_above = [r for r in native if r >= explicit - 1e-6]
            explicit = at_or_above[0] if at_or_above else native[-1]
        return explicit, 'explicit'

    if not native:
        return target, 'unknown'

    if getattr(settings, 'lpf_on', False):
        if oversample_strategy(settings) == 'highest':
            return native[-1], 'oversample'
        wanted = 2.56 * target
        headroom = [r for r in native if r >= wanted - 1e-6]
        if headroom:
            return headroom[0], 'oversample'
        return native[-1], 'oversample'

    if any(abs(target - r) < 1e-6 for r in native):
        return target, 'exact'

    above = [r for r in native if r > target]
    return (above[0] if above else native[-1]), 'lowest-native'


def max_input_fs(settings):
    """Best-known maximum INPUT sample rate for the configured device, in Hz.

    Backs the digital low-pass toggle (round-9): ``acquisition.log_data``
    oversamples at the largest integer multiple of ``settings.fs`` that
    fits under this cap before resampling back down. Per driver:

    - ``'nidaq'``: the resolved device's ``ai_max_rate`` from
      ``_ni_backend.entry_capabilities``. On a MULTIPLEXED device (one
      ADC scanning the channel list — USB-6003/6212, ``simultaneous``
      False) that figure is the AGGREGATE rate, so it is divided by
      ``settings.channels`` to get the per-channel ceiling; simultaneous
      (DSA, per-channel ADC) devices use it directly. DSA modules (NI
      9234) may still coerce the exact oversample request onto their
      discrete divider ladder afterwards — ``log_data`` resamples from
      the rate the stream ACTUALLY ran at, so the target fs is still
      hit.
    - ``'soundcard'``: the highest rate the device can GENUINELY run
      (:func:`native_input_rates`) where the platform reports one, else
      the highest rate ``sd.check_input_settings`` accepts on a probe
      down the standard ladder. The distinction matters on macOS, where
      that probe accepts everything — see :func:`native_input_rates`.
    - ``'mock'``: ``MOCK_MAX_FS`` (no hardware to limit it).

    Falls back to ``settings.fs`` whenever nothing better can be learned
    (missing driver package, no devices, probe failures) — the caller then
    sees no oversampling headroom and logs unfiltered with a note.
    """
    if settings.device_driver == 'mock':
        return float(MOCK_MAX_FS)
    if settings.device_driver == 'nidaq':
        try:
            entries = _ni_backend.enumerate_devices()
            idx = settings.device_index if settings.device_index is not None else 0
            caps = _ni_backend.entry_capabilities(entries[idx])
            rate = caps.get('ai_max_rate')
            if rate:
                if not caps.get('simultaneous'):
                    # Multiplexed: one ADC scans the channel list, so the
                    # advertised max is AGGREGATE — divide by channel count.
                    rate = float(rate) / max(1, int(settings.channels))
                return float(rate)
        except Exception:
            pass
        return float(settings.fs)
    if settings.device_driver == 'soundcard' and sd is not None:
        # Prefer the device's OWN rate list where the platform can give
        # it (macOS/CoreAudio). The check_input_settings ladder below is
        # not a capability probe there: it approves every rate CoreAudio
        # would resample to, so it reports 192 kHz of headroom on a
        # device whose clock is parked at 44.1 kHz — and the oversampled
        # "capture" is then an OS upsample of the very rate we were
        # trying to improve on.
        native = native_input_rates(settings)
        if native:
            usable = [r for r in native if r >= settings.fs]
            return float(usable[-1] if usable else native[-1])
        for rate in (192000, 96000, 88200, 48000, 44100):
            if rate < settings.fs:
                break
            try:
                sd.check_input_settings(device=settings.device_index,
                                        samplerate=rate,
                                        channels=settings.channels)
                return float(rate)
            except Exception:
                continue
    return float(settings.fs)


def start_stream(settings):
    global REC_SC, REC_NI, REC, REC_MOCK
    # Guard the stored index against an enumeration that has reordered
    # since it was chosen (see `resolve_device_index`). The bridge has
    # done this since 2026-08-10 using the name the browser sent; doing
    # it here extends the same protection to the Python API, notebooks
    # and `pydvma-serve --settings`, which had none. `settings.device_name`
    # is the expectation: set it explicitly to opt in from the first
    # capture, or let `Recorder.init_stream` record the resolved name and
    # every capture after the first is checked automatically.
    expected_name = getattr(settings, 'device_name', None)
    if expected_name and settings.device_index is not None:
        settings.device_index, _note = resolve_device_index(
            settings.device_driver, settings.device_index, expected_name,
            getattr(settings, 'device_hostapi', None))
        if _note:
            print(_note)
    if settings.device_driver == 'mock':
        # Hardware-free test backend — no real audio / NI device opened.
        # Used by tests/test_acquisition_mock.py to exercise the
        # log_data / output_signal / stream_snapshot paths on machines
        # without a soundcard or NI-DAQmx driver. See `MockRecorder`.
        REC_MOCK = MockRecorder(settings)
        REC_MOCK.init_stream(settings)
        REC = REC_MOCK
    elif settings.device_driver == 'soundcard':
        # Clamp channels to the device's max_input_channels before
        # constructing the Recorder — buffer shapes in
        # `Recorder.__init__` use `settings.channels`, so any clamping
        # has to happen here, not inside `init_stream`.
        _clamp_soundcard_input_channels(settings)
        # End any previous soundcard stream FIRST. Overwriting REC_SC
        # leaks the old sd.InputStream — its callback keeps firing into
        # the orphaned recorder's buffers, and the PortAudio handle stays
        # open. Invisible on shared-mode hosts (WASAPI/CoreAudio allow a
        # second open), but a single-handle device — MME under a
        # remote-desktop session — refuses the new stream outright
        # (PaErrorCode -9996; the NI branch below has always torn down
        # its old task for the same reason).
        if REC_SC is not None:
            try:
                REC_SC.end_stream()
            except Exception:
                pass
            REC_SC = None
        REC_SC = Recorder(settings)
        REC_SC.init_stream(settings)
        REC = REC_SC
    elif settings.device_driver == 'nidaq':
        cls = _ni_recorder_class(settings)
        # Reuse path: an existing recorder has a live AI task whose
        # hardware configuration matches the requested settings. Keep
        # the task running — preserves IEPE excitation settling — and
        # just refresh the trigger state for the next capture. Any
        # log_data-side fields (pretrig_*, channel_sensitivities,
        # output_*) get picked up via the settings reference update
        # and applied at read time.
        if (REC_NI is not None
                and isinstance(REC_NI, cls)
                and REC_NI.audio_stream is not None):
            sig_running = _ni_settings_signature(REC_NI.settings)
            match = _ni_settings_signature(settings) == sig_running
            if not match:
                # DSA hardware may have coerced the running task's rate
                # (e.g. 5000 -> 5120 on an NI 9234; see the coercion
                # note in `_build_and_start_ai_task`). A caller
                # re-asking for the ORIGINAL rate describes the same
                # hardware config, so reuse the task — and adopt the
                # coerced rate — rather than rebuilding (which would
                # repeat the ~2 s IEPE warmup on every capture).
                requested = getattr(REC_NI, '_requested_fs', None)
                if (requested is not None
                        and float(settings.fs) == float(requested)):
                    probe = copy.copy(settings)
                    probe.fs = REC_NI.settings.fs
                    if _ni_settings_signature(probe) == sig_running:
                        settings.fs = REC_NI.settings.fs
                        match = True
            if match:
                REC_NI.settings = settings
                REC_NI.trigger_detected = False
                REC_NI.trigger_first_detected_message = False
                REC = REC_NI
                return

        # Rebuild path: hardware config changed (different device,
        # channels, fs, IEPE current, ...) or there's no live task.
        # If an existing REC_NI was created by a different backend, drop it.
        if REC_NI is not None and not isinstance(REC_NI, cls):
            try:
                REC_NI.end_stream()
            except Exception:
                pass
            REC_NI = None
        if REC_NI is None:
            REC_NI = cls(settings)
        else:
            try:
                REC_NI.end_stream()
            except Exception:
                pass
        REC_NI.__init__(settings)
        REC_NI.init_stream(settings)
        REC = REC_NI
        print(REC)
    else:
        raise ValueError('Unknown driver: %r' % settings.device_driver)
        
#%% Find information on available devices
def list_available_devices(io=''):
    # soundcard devices list
    message = '__________________________________________________________\n'
    message += '\n'
    message += 'Devices available using device_driver=''soundcard'', by index:\n'
    message += '__________________________________________________________\n'
    message += '\n'

    device_name_list = get_devices_soundcard()
    if device_name_list is not None:
        N = np.size(device_name_list)
        for i in range(N):
            if io.lower() in device_name_list[i].lower(): # option to only look for input devices
                message += '{}: {}\n'.format(i,device_name_list[i])
    
        try:
            default_input_device = sd.default.device[0]
            message += '\nDefault device is: [%i] %s\n' %(default_input_device,device_name_list[default_input_device])
            message += '\n'
            default_output_device = sd.default.device[1]
            message += 'Default device is: [%i] %s\n' %(default_output_device,device_name_list[default_output_device])
            message += '\n\n'
        except (AttributeError, TypeError, IndexError):
            # sd.default is None (no PortAudio host), or
            # sd.default.device is -1 / not indexable on a headless
            # machine — fall back to "unknown" without pretending any
            # specific device is the default.
            message += 'default information not available\n'
    else:
        message += 'no soundcards found\n'
    
    # NI list (nidaqmx view — cDAQ chassis collapsed into a single entry)
    message += '______________________________________________________\n'
    message += '\n'
    message += "Devices available using device_driver='nidaq', by index:\n"
    message += '______________________________________________________\n'
    message += '\n'
    if ni is None:
        message += 'nidaqmx is not installed\n'
    else:
        entries = _ni_backend.enumerate_devices()
        if not entries:
            message += 'no NI devices found via nidaqmx\n'
        else:
            for i, e in enumerate(entries):
                tag = 'chassis' if e['is_chassis'] else 'device'
                message += '{}: {} ({}, {}) AI={} AO={}'.format(
                    i, e['name'], e['product_type'], tag,
                    e['ai_channel_count'], e['ao_channel_count'],
                )
                if e['is_chassis']:
                    message += ' modules={}'.format(e['module_names'])
                message += '\n'

    print(message)
    return message
    
    
        

def get_devices_NI():
    '''Return (names, types) of every NI device/module visible to nidaqmx.

    Flat list — a cDAQ chassis appears alongside each of its slotted
    modules (e.g. ``['cDAQ1', 'cDAQ1Mod1', 'cDAQ1Mod2']``). For the
    chassis-collapsed view used by `Recorder_NI_nidaqmx` itself, call
    `_ni_backend.enumerate_devices` directly.

    Returns ``(None, None)`` if nidaqmx is not installed or no devices
    are visible, keeping the pre-nidaqmx API shape.
    '''
    if ni is None:
        return None, None
    try:
        system = ni.system.System.local()
        names = [d.name for d in system.devices]
        types = [d.product_type for d in system.devices]
    except Exception:
        return None, None
    if not names:
        return None, None
    return names, types


def get_devices_soundcard():
    if sd is None:
        return None
    try:
        devices = sd.query_devices()
        device_name_list = []
        for device in devices:
            device_name_list.append(device['name'])
    except (sd.PortAudioError, AttributeError, TypeError):
        # PortAudio subsystem not available, or sd.query_devices()
        # returned something without the expected dict-of-device shape
        # (unusual driver config). Treat as "no devices visible".
        return None
    
    return device_name_list

# def get_devices_soundcard():
#     try:
#         audio = pyaudio.PyAudio()
#         device_count = audio.get_device_count()
#         device_name_list = []
#         for i in range(device_count):
#             device = audio.get_device_info_by_index(i)
#             device_name_list.append(device['name'])
#     except:
#         return None
    
#     return device_name_list


#%% sounddevice stream
class Recorder(object):
    '''Soundcard acquisition recorder (via `sounddevice`).

    Owns two circular buffers:

    * ``osc_time_data`` — shape ``(num_chunks * chunk_size, channels)``
      — always live; fed the most-recent samples for the oscilloscope.
    * ``stored_time_data`` — shape ``(stored_num_chunks * chunk_size,
      channels)`` where ``stored_num_chunks = 2 + ceil(stored_time * fs
      / chunk_size)`` — the capture buffer used by `log_data`.

    Trigger / pretrigger state machine
    ----------------------------------
    Each incoming chunk (``chunk_size`` samples, ``channels`` wide)
    runs through `callback`:

    1. Shift both buffers left by ``chunk_size`` and append the new
       chunk at the end. When ``pretrig_samples is not None`` and
       ``trigger_detected`` is already True, `stored_time_data` is
       **frozen** — only `osc_time_data` keeps scrolling.
    2. "First-detect" message: if any sample in the just-read chunk
       exceeds ``pretrig_threshold`` on the monitored
       ``pretrig_channel``, print a one-shot notice. Independent of
       whether the trigger has actually been committed yet.
    3. Trigger check: look at ``stored_time_data[chunk_size :
       2*chunk_size, pretrig_channel]`` (the *second-oldest* chunk in
       the buffer — see below). If any sample exceeds
       ``pretrig_threshold``, set ``trigger_detected = True`` and
       freeze the buffer on subsequent callbacks.

    The "check the second-oldest chunk" design means that by the
    time a trigger is detected, the buffer already holds ~``stored_time
    * fs`` samples of *post*-trigger data and up to ``chunk_size``
    samples of *pre*-trigger data. `log_data` uses this to return a
    window straddling the trigger with ``pretrig_samples`` samples of
    context before it — see `pydvma.acquisition.log_data`. The
    ``chunk_size`` ceiling on the pre-trigger context is why
    ``pretrig_samples > chunk_size`` is rejected.

    Data convention
    ---------------
    Both buffers store voltages. sounddevice delivers float32 samples
    in ±1 normalised units; the callback scales by
    ``settings.VmaxSC`` on the way in, so consumers see a calibrated
    reading at the input jack (``VmaxSC`` = the voltage corresponding
    to a normalised 1.0). Default ``VmaxSC=1.0`` means no calibration
    — ±1 normalised is returned as ±1 "V" — which keeps behaviour
    byte-identical to the old convention for anyone who hasn't
    measured their soundcard's sensitivity.

    Channel-count clamping
    ----------------------
    The buffer shapes are derived from ``settings.channels`` at
    construction time. To keep these consistent with what the
    PortAudio device will actually accept, `start_stream` calls
    `_clamp_soundcard_input_channels` *before* constructing this
    Recorder — so by the time ``__init__`` runs, ``settings.channels``
    is already clamped to ``max_input_channels`` (with a printed
    warning when clamping happened). This avoids the cryptic
    ``PortAudioError -9998`` on devices like a Mac built-in mono mic
    when defaults asked for 2 channels.
    '''
    def __init__(self,settings):
        self.settings = settings
        self.trigger_detected = False
        self.trigger_first_detected_message = False
        self.osc_time_axis=np.arange(0,(self.settings.num_chunks*self.settings.chunk_size)/self.settings.fs,1/self.settings.fs)
        self.osc_freq_axis=np.fft.rfftfreq(len(self.osc_time_axis),1/self.settings.fs)
        self.osc_time_data=np.zeros(shape=((self.settings.num_chunks*self.settings.chunk_size),self.settings.channels))  
        self.osc_time_data_windowed=np.zeros_like(self.osc_time_data)
        self.osc_freq_data = np.abs(np.fft.rfft(self.osc_time_data,axis=0))

        
        #rounds up the number of chunks needed in the pretrig array    
        self.stored_num_chunks=2+int(np.ceil((self.settings.stored_time*self.settings.fs)/self.settings.chunk_size))
        #the +2 is to allow for the updating process on either side
        self.stored_time_data=np.zeros(shape=(self.stored_num_chunks*self.settings.chunk_size,self.settings.channels))
        self.stored_time_data_windowed=np.zeros_like(self.stored_time_data)
        #note the +2s to match up the length of stored_num_chunks
        #formula used from the np.fft.rfft documentation
        self.stored_freq_data = np.abs(np.fft.rfft(self.stored_time_data,axis=0))
        # self.list_dt = []
    
    def callback(self, in_data, frame_count, time_info, status):
        '''
        Obtains data from the audio stream.

        The sounddevice callback delivers float32 samples in ±1
        normalised units; we scale by ``settings.VmaxSC`` on the way
        in so both `osc_time_data` and `stored_time_data` are in
        volts (where "volts" means "ŷ × VmaxSC", with ŷ the
        normalised sample). VmaxSC defaults to 1.0 so uncalibrated
        soundcards keep identical numeric behaviour to the old ±1
        convention.
        '''
        t0 = time.time()
        # self.osc_data_chunk = (np.frombuffer(in_data, dtype='int'+str(self.settings.nbits))/2**(self.settings.nbits-1))
        self.osc_data_chunk = np.copy(in_data) * self.settings.VmaxSC
        self.osc_data_chunk=np.reshape(self.osc_data_chunk,[self.settings.chunk_size,self.settings.channels])
        for i in range(self.settings.channels):
            self.osc_time_data[:-(self.settings.chunk_size),i] = self.osc_time_data[self.settings.chunk_size:,i]
            self.osc_time_data[-(self.settings.chunk_size):,i] = self.osc_data_chunk[:,i]
            if (not self.trigger_detected)  or (self.settings.pretrig_samples is None):
                self.stored_time_data[:-(self.settings.chunk_size),i] = self.stored_time_data[self.settings.chunk_size:,i]
                self.stored_time_data[-(self.settings.chunk_size):,i] = self.osc_data_chunk[:,i]
        
        trigger_first_detected = np.any(np.abs(self.osc_data_chunk[:,self.settings.pretrig_channel])>self.settings.pretrig_threshold)
        if trigger_first_detected and self.trigger_first_detected_message:
            acquisition.MESSAGE += 'Trigger detected. Logging data for {} seconds.\n'.format(self.settings.stored_time)
            print('')
            print(acquisition.MESSAGE)
            self.trigger_first_detected_message=False
            
            
        trigger_check = self.stored_time_data[(self.settings.chunk_size):(2*self.settings.chunk_size),self.settings.pretrig_channel]
        if np.any(np.abs(trigger_check)>self.settings.pretrig_threshold):
            # freeze updating stored_time_data
            self.trigger_detected = True

        # self.list_dt += [time.time()-t0]

        # return in_data
    
    
    def init_stream(self,settings,_input_=True,_output_=False):
        '''Open the live `sd.InputStream` against ``settings.device_index``.

        If ``settings.device_index`` is ``None`` it's resolved to
        ``sd.default.device[0]`` and printed to stdout. ``settings.channels``
        is assumed to already fit the device — `start_stream` clamps it
        via `_clamp_soundcard_input_channels` before this method runs,
        so the value passed to ``sd.InputStream`` will not exceed the
        device's ``max_input_channels`` even if the caller asked for more.
        '''
        
        if settings.device_index is None:
    
            devices = sd.query_devices()
            print('No device specified. Using default:\n\n%i %s'
                  %(sd.default.device[0],devices[sd.default.device[0]]['name']))
            print ('')
            settings.device_index=sd.default.device[0]
            
        settings.device_name = sd.query_devices()[settings.device_index]['name']
        settings.device_full_info = sd.query_devices()[settings.device_index]
        # Record the backend too: on Windows the name is shared by every
        # host API exposing this hardware, so name+host API is the
        # identity `start_stream` re-resolves against next time.
        hostapis = enumerated_device_hostapis('soundcard')
        if settings.device_index < len(hostapis):
            settings.device_hostapi = hostapis[settings.device_index]

        self._pin_hardware_clock(settings)
        self._pin_hardware_format(settings)
        self._pin_input_volume(settings)

        dtype = 'float32'
        self.audio_stream = sd.InputStream(samplerate=settings.fs, 
                                      blocksize=settings.chunk_size, 
                                      device=settings.device_index, 
                                      channels=settings.channels, 
                                      dtype=dtype, 
                                      latency='low', 
                                      extra_settings=None, 
                                      callback=self.callback, 
                                      finished_callback=None, 
                                      clip_off=None, 
                                      dither_off=None, 
                                      never_drop_input=None, 
                                      prime_output_buffers_using_stream_callback=None) 
        self.audio_stream.start()
        
        
    
    def _pin_hardware_clock(self, settings):
        '''Pin the device's hardware clock to ``settings.fs`` before opening.

        Without this the requested rate is only a target: PortAudio never
        retunes the device, so CoreAudio resamples from whatever rate the
        device happens to be parked at, silently and at a quality that
        depends on the ratio (measured between 12 dB and 114 dB of alias
        rejection on the same device — see ``pydvma._coreaudio``).

        The previous rate is remembered so ``end_stream`` can put it back,
        because the clock is a system-wide property shared with every
        other application using the interface. A pin that does not take
        is reported and then tolerated — a resampled capture still beats
        no capture — so the operator learns the data is not what it
        claims to be. No-op off macOS, where the rate list is unknown.
        '''
        self._clock_device_id = None
        self._clock_previous_fs = None
        if not _coreaudio.available():
            return
        device_id, _ = _coreaudio.find_device(settings.device_name)
        if device_id is None:
            return
        native = _coreaudio.native_rates(device_id)
        target = float(settings.fs)
        if native and not any(abs(target - r) < 1e-6 for r in native):
            print('WARNING: %r cannot run at %g Hz (it supports %s). The OS '
                  'will resample, which is not measurement-grade — set fs to '
                  'a supported rate, or use lpf_on / capture_fs to capture at '
                  'one and decimate.'
                  % (settings.device_name, target,
                     ', '.join('%g' % r for r in native)))
            return
        previous = _coreaudio.get_nominal_rate(device_id)
        if previous is not None and abs(previous - target) < 1e-6:
            return  # already correct; a needless change interrupts other audio
        if _coreaudio.set_nominal_rate(device_id, target):
            self._clock_device_id = device_id
            self._clock_previous_fs = previous
        else:
            print('WARNING: could not set %r to %g Hz (it is at %s Hz). The '
                  'capture will be resampled by the OS.'
                  % (settings.device_name, target, previous))

    def _restore_hardware_clock(self):
        '''Put the device clock back where the stream found it.'''
        device_id = getattr(self, '_clock_device_id', None)
        previous = getattr(self, '_clock_previous_fs', None)
        self._clock_device_id = None
        self._clock_previous_fs = None
        if device_id is None or previous is None:
            return
        try:
            _coreaudio.set_nominal_rate(device_id, previous)
        except Exception:
            pass

    def _pin_hardware_format(self, settings):
        '''Raise a 16-bit capture stream to 24-bit for the duration.

        macOS keeps a per-device physical format (Audio MIDI Setup's
        Format box) that defaults to 16-bit on some class-compliant
        interfaces even when they advertise 24 — measured on an ESI
        U24 XL (2026-08-11), where a rate change also RESETS the format
        back to 16-bit, which is why this runs after the clock pin on
        every stream open rather than once. 16 bits cost real dynamic
        range at low sample rates (the U24 XL's 8 kHz in-band floor is
        within 4 dB of the 16-bit dither floor). A device that refuses
        stays at its current depth — that is how it was found, so
        nothing is lost. The previous depth is restored on
        ``end_stream``, like the clock.
        '''
        self._format_device_id = None
        self._format_previous_bits = None
        if not _coreaudio.available():
            return
        device_id, _ = _coreaudio.find_device(settings.device_name)
        if device_id is None:
            return
        current = _coreaudio.input_bit_depth(device_id)
        if current is None or current >= 24:
            return
        if _coreaudio.set_input_bit_depth(device_id, 24):
            self._format_device_id = device_id
            self._format_previous_bits = current
            print('note: %r capture format raised from %d-bit to 24-bit '
                  'for this stream.' % (settings.device_name, current))

    def _restore_hardware_format(self):
        '''Put the capture bit depth back where the stream found it.'''
        device_id = getattr(self, '_format_device_id', None)
        previous = getattr(self, '_format_previous_bits', None)
        self._format_device_id = None
        self._format_previous_bits = None
        if device_id is None or previous is None:
            return
        try:
            _coreaudio.set_input_bit_depth(device_id, previous)
        except Exception:
            pass

    def _pin_input_volume(self, settings):
        '''Pin the device's input volume control at 0 dB (unity).

        Many USB interfaces expose a class-compliant input volume that
        macOS applies to every capture; on an ESI U24 XL it is a purely
        DIGITAL -40..+12 dB gain (SNR measured identical at 0 and
        +12 dB), so any non-zero setting silently rescales the data and
        breaks the volts calibration that ``VmaxSC`` states. 0 dB is
        unity on every device measured, which also makes this the right
        setting for uncharacterised interfaces. The previous per-element
        values are restored on ``end_stream``; a control that cannot be
        pinned is loudly warned about, because the capture's scale is
        then not what the settings claim.
        '''
        self._volume_device_id = None
        self._volume_previous = None
        if not _coreaudio.available():
            return
        device_id, _ = _coreaudio.find_device(settings.device_name)
        if device_id is None:
            return
        volumes = _coreaudio.input_volume_db(device_id)
        if not volumes or all(abs(v) <= 0.25 for v in volumes.values()):
            return
        stated = ', '.join('%+.1f' % v for v in volumes.values())
        if _coreaudio.set_input_volume_db(device_id, 0.0):
            self._volume_device_id = device_id
            self._volume_previous = volumes
            print('note: %r input volume was at %s dB; pinned to 0 dB so '
                  'the capture scale matches the device full-scale '
                  '(restored when the stream closes).'
                  % (settings.device_name, stated))
        else:
            print('WARNING: %r input volume is at %s dB and could not be '
                  'set to 0 dB — captured amplitudes are scaled by that '
                  'much relative to the stated full scale.'
                  % (settings.device_name, stated))

    def _restore_input_volume(self):
        '''Put the input volume control back where the stream found it.'''
        device_id = getattr(self, '_volume_device_id', None)
        previous = getattr(self, '_volume_previous', None)
        self._volume_device_id = None
        self._volume_previous = None
        if device_id is None or not previous:
            return
        try:
            for element, value in previous.items():
                _coreaudio.set_input_volume_db(device_id, value,
                                               elements=[element])
        except Exception:
            pass

    def end_stream(self):
        '''
        Stops and closes the audio stream, tolerating a stream that was
        never opened or is already dead (e.g. after a device
        disconnect) — matching the NI recorder's behaviour. Clears the
        module-level ``REC`` reference, and restores anything this
        recorder pinned on the device: input volume, capture bit depth
        and hardware clock rate, in that order.
        '''
        global REC
        REC = None
        self._restore_input_volume()
        self._restore_hardware_format()
        self._restore_hardware_clock()
        stream = getattr(self, 'audio_stream', None)
        if stream is None:
            return
        try:
            if stream.active:
                stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass
        self.audio_stream = None

        
        



#%% NI stream (nidaqmx backend)


def _ni_callback_interval(chunk_size):
    '''Cadence (in samples) for the NI every-N-samples acquisition
    callback.

    Must equal the per-callback read size (``settings.chunk_size``):
    each callback reads exactly one chunk, so a shorter interval makes
    events fire faster than reads consume samples (unbounded event
    backlog, blocking reads) and a longer one would starve the reads.

    Args:
        chunk_size (int): samples read per callback; must be >= 1.

    Returns:
        int: the validated callback interval (== chunk_size).
    '''
    n = int(chunk_size)
    if n < 1:
        raise ValueError(
            'chunk_size must be >= 1 for the NI callback interval, '
            'got {!r}'.format(chunk_size)
        )
    return n


class Recorder_NI_nidaqmx(object):
    '''NI acquisition recorder using the official nidaqmx Python wrapper.

    Exposes the same public attribute shape the soundcard `Recorder`
    does — `audio_stream`, `osc_time_data`, `stored_time_data`,
    `trigger_detected`, etc. — so `acquisition.py` is driver-agnostic.

    Trigger / pretrigger state machine
    ----------------------------------
    Identical to `Recorder` — see that class's docstring for the full
    description. The only differences in this path are (a) the data
    source (the nidaqmx every-N-samples callback calling
    `read_many_sample` rather than a sounddevice input-stream callback)
    and (b) the sample units: **raw volts** from
    `AnalogMultiChannelReader`, not ±1-normalised float. Thresholds
    (`pretrig_threshold`) are applied with identical code but mean
    different things in the two paths — always specify thresholds in
    the units your chosen device delivers.

    Hardware-specific notes picked up while getting this working:

    * **cDAQ chassis** are addressed via a single entry in the
      enumerated device list. A chassis with an N-channel AI module and
      an M-channel AO module appears as one device with
      ``ai_channel_count=N`` and ``ao_channel_count=M``. Requesting
      ``channels=N`` builds the correct cross-module channel string
      (``cDAQ1Mod1/ai0:N-1``). For mixed / gappy layouts, use the
      ``input_channels_spec`` / ``output_channels_spec`` settings to
      pass a raw physical-channel string.
    * **NI 9234** (and DSA modules generally) are pseudo-differential
      only; set ``NI_mode='DAQmx_Val_PseudoDiff'``. Voltage range is
      fixed at ±5 V; any other ``VmaxNI`` will be accepted silently
      by the driver.
    * **NI 9260** AO is ±4.24 V peak (= 3 V_rms). Setting
      ``output_VmaxNI=10`` triggers DAQmx error -200077.
    * **USB-600x low-cost devices** have software-timed AO: AI/AO
      cannot share a hardware sample clock; the output path falls back
      to an independent (unsynchronised) task.
    * **Data is read in volts** directly via `AnalogMultiChannelReader`,
      not as a normalised float — no ±1 scaling is applied. This
      differs from the soundcard path, which returns ±1-normalised
      float32.
    '''

    def __init__(self, settings):
        self.settings = settings
        self.trigger_detected = False
        self.trigger_first_detected_message = False

        self._alloc_buffers()

        entries = _ni_backend.enumerate_devices()
        if not entries:
            raise RuntimeError('No NI devices found via nidaqmx')
        idx = settings.device_index if settings.device_index is not None else 0
        if idx >= len(entries):
            raise ValueError(
                'device_index %r out of range; nidaqmx sees %d device(s)'
                % (settings.device_index, len(entries))
            )
        self.device_entry = entries[idx]
        self.device_name = self.device_entry['name']

        if settings.channels > self.device_entry['ai_channel_count'] and not settings.input_channels_spec:
            raise ValueError(
                'Requested %d AI channels but %r has only %d available'
                % (settings.channels, self.device_name, self.device_entry['ai_channel_count'])
            )

        # Preserve hardware-level state across re-__init__ calls:
        # acquisition.py re-invokes __init__ to zero the numpy buffers
        # before a pretrigger wait, but the NI task is still running and
        # its callback expects the reader to still exist. Only set these
        # on first construction.
        if not hasattr(self, 'audio_stream'):
            self.audio_stream = None
            self._reader = None
            self._read_buffer = None
            self._callback_ref = None  # keep a strong reference for nidaqmx
            self._closing = False  # set by end_stream; callback bails out
            self._requested_fs = None  # pre-coercion fs; see start_stream

    def _alloc_buffers(self):
        '''(Re)allocate the osc/stored rolling buffers and axes from
        ``self.settings``.

        Split out of ``__init__`` because the buffer geometry depends on
        ``settings.fs``, and on DSA hardware the true rate is only known
        after the task's sample clock is configured —
        `_build_and_start_ai_task` re-calls this when DAQmx coerces the
        requested rate (see the coercion note there).
        '''
        settings = self.settings
        self.osc_time_axis = np.arange(
            0,
            (settings.num_chunks * settings.chunk_size) / settings.fs,
            1 / settings.fs,
        )
        self.osc_freq_axis = np.fft.rfftfreq(len(self.osc_time_axis), 1 / settings.fs)
        self.osc_time_data = np.zeros(
            shape=(settings.num_chunks * settings.chunk_size, settings.channels)
        )
        self.osc_time_data_windowed = np.zeros_like(self.osc_time_data)
        self.osc_freq_data = np.abs(np.fft.rfft(self.osc_time_data, axis=0))

        self.stored_num_chunks = 2 + int(
            np.ceil((settings.stored_time * settings.fs) / settings.chunk_size)
        )
        self.stored_time_data = np.zeros(
            shape=(self.stored_num_chunks * settings.chunk_size, settings.channels)
        )
        self.stored_time_data_windowed = np.zeros_like(self.stored_time_data)
        self.stored_freq_data = np.abs(np.fft.rfft(self.stored_time_data, axis=0))

    def available_devices(self):
        entries = _ni_backend.enumerate_devices()
        return ([e['name'] for e in entries], [e['product_type'] for e in entries])

    def current_device_info(self):
        pp.pprint(self.device_entry)

    def set_channels(self):
        return _ni_backend.build_ai_channel_string(
            self.device_entry,
            self.settings.channels,
            self.settings.input_channels_spec,
        )

    def set_output_channels(self):
        return _ni_backend.build_ao_channel_string(
            self.device_entry,
            self.settings.output_channels,
            self.settings.output_channels_spec,
        )

    def stream_audio_callback(self):
        '''Consume acquired samples and advance the rolling buffers.

        Runs on the nidaqmx every-N-samples event thread. Reads and
        processes one chunk, then **drains any backlog**: while the
        DAQmx input buffer already holds at least another whole chunk,
        keeps reading and processing. The rolling buffers advance one
        chunk per *processed* chunk, so without the drain a host stall
        (paging, USB contention, a busy CPU) would leave buffer time
        lagging real time indefinitely — and the pretrigger check,
        which needs the crossing to roll into
        ``stored_time_data[chunk_size:2*chunk_size]``, could miss its
        timeout even though the trigger physically fired. The drain
        bounds that lag to roughly one callback latency.
        '''
        if self._closing:
            return 0
        if not self._read_and_process_chunk():
            return 0
        try:
            while (not self._closing
                   and self.audio_stream is not None
                   and self.audio_stream.in_stream.avail_samp_per_chan
                       >= self.settings.chunk_size):
                if not self._read_and_process_chunk():
                    break
        except Exception:
            # avail_samp_per_chan can raise if the task is being torn
            # down mid-callback; the next event (if any) resumes.
            pass
        return 0

    def _read_and_process_chunk(self):
        '''Read exactly one chunk from the task and process it.

        Returns True on success, False if the read failed (error is
        printed, not raised — this runs on the driver callback thread).
        '''
        try:
            self._reader.read_many_sample(
                self._read_buffer,
                number_of_samples_per_channel=self.settings.chunk_size,
                timeout=10.0,
            )
        except Exception as e:
            # Expected (and harmless) when end_stream closes the task
            # while a read is in flight on the callback thread — stay
            # quiet then; anything else is worth surfacing.
            if not self._closing:
                print('nidaqmx read error:', e)
            return False
        # Reader fills shape (channels, chunk_size); downstream wants
        # (chunk_size, channels) to match the soundcard path.
        self._process_chunk(self._read_buffer.T)
        return True

    def _process_chunk(self, data_array):
        '''Advance osc/stored rolling buffers by one chunk and run the
        pretrigger state machine (see the class docstring).

        ``data_array`` has shape (chunk_size, channels). The stored
        buffer freezes once ``trigger_detected`` is set; the osc
        (monitor) buffer always advances.
        '''
        self.osc_data_chunk = data_array

        for i in range(self.settings.channels):
            self.osc_time_data[:-(self.settings.chunk_size), i] = self.osc_time_data[self.settings.chunk_size:, i]
            self.osc_time_data[-(self.settings.chunk_size):, i] = self.osc_data_chunk[:, i]
            if (not self.trigger_detected) or (self.settings.pretrig_samples is None):
                self.stored_time_data[:-(self.settings.chunk_size), i] = self.stored_time_data[self.settings.chunk_size:, i]
                self.stored_time_data[-(self.settings.chunk_size):, i] = self.osc_data_chunk[:, i]

        trigger_first_detected = np.any(
            np.abs(self.osc_data_chunk[:, self.settings.pretrig_channel])
            > self.settings.pretrig_threshold
        )
        if trigger_first_detected and self.trigger_first_detected_message:
            acquisition.MESSAGE += 'Trigger detected. Logging data for {} seconds.\n'.format(
                self.settings.stored_time
            )
            print('')
            print(acquisition.MESSAGE)
            self.trigger_first_detected_message = False

        trigger_check = self.stored_time_data[
            self.settings.chunk_size:(2 * self.settings.chunk_size),
            self.settings.pretrig_channel,
        ]
        if np.any(np.abs(trigger_check) > self.settings.pretrig_threshold):
            self.trigger_detected = True

    def init_stream(self, settings, _input_=True, _output_=False):
        # Tear down any previous task on this recorder
        if self.audio_stream is not None:
            try:
                self.audio_stream.stop()
            except Exception:
                pass
            try:
                self.audio_stream.close()
            except Exception:
                pass
            self.audio_stream = None

        try:
            self._build_and_start_ai_task(settings)
        except ni.errors.DaqError as e:
            # -50103 "The specified resource is reserved" usually means a
            # prior Python process leaked the task (notebook kernel crash,
            # Ctrl-C, etc.) and Windows is still holding the reservation.
            # Reset the device once to clear it and retry; surface any
            # other DAQmx error unchanged.
            if e.error_code != -50103:
                raise
            if self.audio_stream is not None:
                try:
                    self.audio_stream.close()
                except Exception:
                    pass
                self.audio_stream = None
            try:
                ni.system.Device(self.device_name).reset_device()
            except Exception:
                pass
            self._build_and_start_ai_task(settings)

    def _build_and_start_ai_task(self, settings):
        # A fresh task gets a fresh teardown flag (it stays True after
        # end_stream so straggler callback events from the old task
        # keep bailing out).
        self._closing = False

        # Callback cadence must equal the per-callback read size —
        # see _ni_callback_interval.
        AutoRegN = _ni_callback_interval(settings.chunk_size)

        # Device-aware: falls back (with a printed note) when the
        # requested NI_mode is impossible on this hardware — e.g. the
        # MySettings default RSE on a pseudo-diff-only DSA module.
        term_config = _ni_backend.resolve_terminal_config_for_entry(
            self.device_entry, settings.NI_mode)
        task = ni.Task()
        task.ai_channels.add_ai_voltage_chan(
            self.set_channels(),
            terminal_config=term_config,
            min_val=-float(settings.VmaxNI),
            max_val=+float(settings.VmaxNI),
        )
        task.timing.cfg_samp_clk_timing(
            rate=float(settings.fs),
            sample_mode=ni.constants.AcquisitionType.CONTINUOUS,
            samps_per_chan=int(settings.chunk_size),
        )

        # DSA modules (NI 9234) run only on their fixed rate ladder and
        # DAQmx **silently coerces** any other request — measured on the
        # real 9234: asking for 8000 Hz actually samples at 8533.33 Hz,
        # 5000 -> 5120. Adopt the true rate into settings.fs (and
        # re-size the rolling buffers, which depend on fs) so time and
        # frequency axes, .dvma metadata, and downstream TF/modal fits
        # stay correct; otherwise every frequency would be off by the
        # coercion ratio (up to ~7 %). The original ask is kept in
        # `_requested_fs` so `start_stream` can still recognise a
        # repeat request as the same hardware config (stream reuse).
        self._requested_fs = float(settings.fs)
        try:
            actual_fs = float(task.timing.samp_clk_rate)
        except (ni.errors.DaqError, AttributeError):
            actual_fs = None
        if actual_fs and abs(actual_fs - float(settings.fs)) > 1e-6:
            print(
                'Requested fs = {:g} Hz was coerced to {:g} Hz by {} '
                '(hardware rate ladder); using the actual rate.'
                .format(float(settings.fs), actual_fs, self.device_name)
            )
            settings.fs = actual_fs
            self._alloc_buffers()

        # Give the DAQmx input buffer several seconds of headroom. The
        # driver default (10 kS at these rates = 2 s at fs=5000) means
        # a host stall longer than that overflows the buffer (-200279)
        # and kills the capture; with headroom the samples just queue
        # and the drain loop in `stream_audio_callback` catches the
        # rolling buffers back up when callbacks resume. The size must
        # be an exact multiple of the every-N event interval
        # (chunk_size) — DAQmx rejects other sizes with -200877 on
        # DMA/USB-bulk transfers (seen on the real cDAQ-9174).
        try:
            chunks_5s = int(np.ceil(5 * float(settings.fs)
                                    / settings.chunk_size))
            min_buf = chunks_5s * int(settings.chunk_size)
            if task.in_stream.input_buf_size < min_buf:
                task.in_stream.input_buf_size = min_buf
        except (ni.errors.DaqError, AttributeError):
            pass  # keep the driver default if the property is refused

        # Per-channel IEPE / ICP excitation. Setting any channel's
        # excitation requires the sample clock to be configured first
        # (DSA modules reject the property otherwise — DAQmx -201087).
        self._apply_per_channel_iepe(task, settings)

        self._read_buffer = np.zeros(
            (settings.channels, settings.chunk_size), dtype=np.float64
        )
        self._reader = AnalogMultiChannelReader(task.in_stream)

        def _cb(task_handle, event_type, number_of_samples, callback_data):
            try:
                return self.stream_audio_callback()
            except Exception as e:
                print('stream_audio_callback error:', e)
                return 0

        self._callback_ref = _cb
        task.register_every_n_samples_acquired_into_buffer_event(AutoRegN, _cb)

        # Assign before start so the retry path in ``init_stream`` can
        # find the task to close if ``task.start()`` raises -50103.
        self.audio_stream = task
        task.start()

        # IEPE warmup: when the 2 mA excitation step turns on at
        # task.start(), the sensor's DC bias rises and propagates
        # through the 9234's AC-coupling HPF. Block until that step
        # has decayed below the noise floor before letting callers
        # read the buffer; otherwise the first capture is dominated
        # by the bias transient (mean drifting from ~12 V to 0).
        if np.any(np.asarray(settings.iepe_excit_current_A) > 0):
            print('IEPE excitation settling for {} s...'.format(_IEPE_WARMUP_S))
            time.sleep(_IEPE_WARMUP_S)

    def _apply_per_channel_iepe(self, task, settings):
        """Apply IEPE excitation + AC coupling per channel from settings.

        ``settings.iepe_excit_current_A`` is an array of length
        ``channels`` (validated in ``MySettings.__init__``). Channels
        with ``> 0`` get internal current excitation at that value
        plus AC coupling (the standard for IEPE/ICP sensors); channels
        with ``0`` are left at the device's default (no excitation, DC
        coupling on the 9234).

        Validates against the *owning* module's advertised
        ``ai_current_int_excit_discrete_vals`` so requesting an
        unsupported current (e.g. 2 mA on a USB-6003) fails loudly
        rather than being silently ignored. On a multi-module chassis
        each channel is checked against the module that actually
        supplies it (channels can span modules — e.g. an IEPE accel on
        the second AI module while the first carries a loopback), so a
        legal current on one module is not assumed legal on another.
        """
        currents = np.asarray(settings.iepe_excit_current_A, dtype=float)
        if not np.any(currents > 0):
            return  # all channels off — nothing to do

        channels = list(task.ai_channels)
        if len(channels) != len(currents):
            raise RuntimeError(
                'IEPE configuration mismatch: task has {} channels but '
                'settings.iepe_excit_current_A has {} entries'
                .format(len(channels), len(currents))
            )

        # Map each channel index to the device (chassis module, or the
        # standalone device itself) that supplies it, so each requested
        # current is validated against the right hardware.
        owning = _ni_backend.ai_channel_module_map(
            self.device_entry, len(currents),
        )
        allowed_cache = {}

        def _allowed_for(dev_name):
            if dev_name not in allowed_cache:
                try:
                    vals = list(
                        ni.system.Device(dev_name)
                        .ai_current_int_excit_discrete_vals
                    )
                except (ni.errors.DaqError, AttributeError):
                    vals = []
                # 0.0 is always implicitly allowed (= no excitation).
                allowed_cache[dev_name] = {0.0} | {float(v) for v in vals}
            return allowed_cache[dev_name]

        for idx, current in enumerate(currents):
            if current <= 0:
                continue
            dev_name = owning[idx]
            allowed_set = _allowed_for(dev_name)
            if not any(abs(current - a) < 1e-9 for a in allowed_set):
                raise ValueError(
                    'iepe_excit_current_A={} A on channel {} is not '
                    'supported by {} (allowed: {} A). Set to 0.0 to '
                    'disable IEPE.'
                    .format(current, idx, dev_name, sorted(allowed_set))
                )
        for ch, current in zip(channels, currents):
            if current > 0:
                ch.ai_excit_src = ni.constants.ExcitationSource.INTERNAL
                ch.ai_excit_val = float(current)
                ch.ai_coupling = ni.constants.Coupling.AC

    def setup_output(self, settings, output):
        # Delegate to the module-level helper so both call paths share the
        # same (validated) implementation.
        return setup_output_NI_nidaqmx(settings, output)

    def end_stream(self):
        global REC
        REC = None
        # Tell the callback thread to bail out before the task handle
        # goes away — its drain loop may be mid-read (see
        # `stream_audio_callback`); reads against a closing task raise
        # cleanly and are suppressed while this flag is set.
        self._closing = True
        if self.audio_stream is not None:
            try:
                self.audio_stream.stop()
            except Exception:
                pass
            try:
                self.audio_stream.close()
            except Exception:
                pass
            self.audio_stream = None
        self._reader = None
        self._read_buffer = None
        self._callback_ref = None


# Backwards-compatibility alias: the public API has always exposed
# `Recorder_NI`, and external notebooks/scripts may still import it
# by that name. Kept pointing at the (now sole) nidaqmx recorder.
Recorder_NI = Recorder_NI_nidaqmx


#%% NI output

def setup_output_NI(settings, output):
    '''Build and stage (but not start) an NI AO task.

    Thin wrapper that defers to `setup_output_NI_nidaqmx` — the
    nidaqmx backend is now the only NI path.
    '''
    if ni is None:
        raise RuntimeError('nidaqmx is not installed; pip install nidaqmx')
    return setup_output_NI_nidaqmx(settings, output)


class _NidaqmxTaskAdapter(object):
    '''Expose the PascalCase methods acquisition.py calls on the NI
    output stream (StartTask, StopTask, WaitUntilTaskDone). Any other
    attribute access falls through to the underlying nidaqmx.Task.
    '''
    def __init__(self, task):
        self._task = task

    def StartTask(self):
        self._task.start()

    def StopTask(self):
        try:
            self._task.stop()
        except Exception:
            pass
        try:
            self._task.close()
        except Exception:
            pass

    def WaitUntilTaskDone(self, timeout):
        self._task.wait_until_done(timeout=float(timeout))

    def ClearTask(self):
        try:
            self._task.close()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._task, name)


def _ao_module_name(device_entry):
    """Return the name of the device's AO-providing module (the chassis
    slot for a cDAQ, or the device itself for a standalone USB/PCIe
    DAQ). Used by `_check_output_vmax_within_hardware` to look up the
    actual hardware AO range. Returns None if no AO module is found."""
    if device_entry['is_chassis']:
        for mod in device_entry['module_names']:
            if device_entry['module_ao_counts'].get(mod, 0) > 0:
                return mod
        return None
    return device_entry['name']


def _check_output_vmax_within_hardware(device_entry, requested_vmax):
    """Raise ValueError if ``requested_vmax`` exceeds the AO module's
    largest range, with a clear message that names the actual hardware
    limit and points the caller at `suggest_ni_settings` for safe
    defaults. Best-effort: if the device's `ao_voltage_ranges` can't be
    queried, silently fall through and let DAQmx surface the error
    itself (still a clear -200077 with min/max attached)."""
    from . import _ni_device_specs    # local import to avoid load-order cycles
    ao_mod = _ao_module_name(device_entry)
    if ao_mod is None:
        return
    try:
        info = _ni_device_specs.get_device_info(ao_mod)
    except (RuntimeError, ni.errors.DaqError):
        return
    ranges = info.get('ao_voltage_ranges') or []
    if not ranges:
        return
    hw_max = max(rmax for _, rmax in ranges)
    if requested_vmax > hw_max + 1e-9:
        raise ValueError(
            'output_VmaxNI = {:.4f} V exceeds the maximum output voltage '
            'of {} ({}) on this hardware ({:.4f} V). Lower output_VmaxNI '
            'in MySettings, or call dvma.suggest_ni_settings(device_index='
            '{!r}) to get safe defaults for this device.'.format(
                requested_vmax, ao_mod, info.get('product_type', '?'),
                hw_max, device_entry['name'],
            )
        )


def _check_output_rate_within_hardware(device_entry, requested_fs):
    """Raise ValueError if ``requested_fs`` is outside the AO module's
    hardware sample-rate bounds, with a message naming the real limit.

    E.g. the USB-6003's AO tops out at 5 kS/s (software-timed) and the
    NI 9260 (DSA) cannot go below ~1613 S/s; without this preflight a
    bad ``output_fs`` surfaces as a raw DAQmx -200077 at task creation.
    Best-effort: if the capability probe fails, fall through and let
    DAQmx report the violation itself.
    """
    try:
        caps = _ni_backend.entry_capabilities(device_entry)
    except Exception:
        return
    hw_max = caps.get('ao_max_rate')
    hw_min = caps.get('ao_min_rate')
    if hw_max and requested_fs > float(hw_max) + 1e-6:
        raise ValueError(
            'output_fs = {:g} Hz exceeds the maximum AO sample rate of '
            '{} ({:g} Hz). Lower output_fs, or call '
            'dvma.suggest_ni_settings(device_index=...) for safe '
            'defaults.'.format(requested_fs, device_entry['name'],
                               float(hw_max))
        )
    if hw_min and requested_fs < float(hw_min) - 1e-6:
        raise ValueError(
            'output_fs = {:g} Hz is below the minimum AO sample rate of '
            '{} ({:g} Hz). Raise output_fs, or call '
            'dvma.suggest_ni_settings(device_index=...) for safe '
            'defaults.'.format(requested_fs, device_entry['name'],
                               float(hw_min))
        )


def setup_output_NI_nidaqmx(settings, output):
    '''Build and stage (but not start) a finite-sample AO task on nidaqmx.

    Parameters
    ----------
    settings : MySettings
        Must have ``output_device_driver='nidaq'``. ``output`` is
        expected in **volts**; the AO task is configured with ranges
        ±``output_VmaxNI`` so any sample outside that range will be
        rejected by DAQmx (error -200077).
    output : ndarray, shape (N_samples, output_channels)
        Playback waveform, in volts. Must stay within ±``output_VmaxNI``
        (e.g. NI 9260 is ±4.24 V peak regardless of the requested
        range).

    Returns
    -------
    _NidaqmxTaskAdapter
        Wrapper exposing ``StartTask`` / ``StopTask`` /
        ``WaitUntilTaskDone`` so `acquisition.py` can call the same
        methods regardless of whether the source is an NI or soundcard
        stream.

    Notes on AI/AO hardware sync
    ----------------------------
    When the AI recorder is a `Recorder_NI_nidaqmx` on the **same
    device or chassis**, that hardware supports hardware-timed AO
    (see `_ni_backend.supports_hw_ao_sync`), **and the AI stream's
    actual rate equals ``output_fs``**, the AO task routes the AI
    sample clock as its source — the resulting AO samples step on
    exactly the AI tick. This works on M/X-series USB (e.g.
    USB-6212). When the rates differ — an explicit ``output_fs`` ≠
    ``fs``, or a digital-low-pass capture (``lpf_on``) whose stream
    runs oversampled at ``lpf_capture_fs`` — the AI clock would step
    the drive at the wrong rate, so the AO task keeps its own
    timebase instead (correct rate, no sample-accurate sync). It is
    also **not** used for cDAQ chassis: per-module AI sample clocks
    are not routable as AO sources there; AI and AO instead share
    the chassis 80 MHz timebase implicitly, which is phase-coherent
    but not sample-accurate across tasks. USB-600x low-cost devices
    have software-timed AO and always run unsynchronised.
    '''
    # `output` is already in volts; no pre-scaling needed.
    output = np.asarray(output)
    output_shape = np.shape(output)
    N_output = output_shape[0]
    N_channel_check = output_shape[1]
    if N_channel_check != settings.output_channels:
        print("output matrix doesn't match number of output channels")

    entries = _ni_backend.enumerate_devices()
    if not entries:
        raise RuntimeError('No NI devices found via nidaqmx')
    if settings.output_device_index is None or settings.output_device_index >= len(entries):
        raise ValueError(
            'output_device_index %r out of range; nidaqmx sees %d device(s)'
            % (settings.output_device_index, len(entries))
        )
    device_entry = entries[settings.output_device_index]
    channel_string = _ni_backend.build_ao_channel_string(
        device_entry, settings.output_channels, settings.output_channels_spec,
    )

    # Pre-check output_VmaxNI against the AO module's actual capability.
    # DAQmx will reject e.g. +/-5 V on the NI 9260 (max +/-4.242641 V) with
    # an opaque -200077 at channel creation; raising a clearer error here
    # with the device's real limit + a pointer to suggest_ni_settings is
    # much friendlier, especially when the call comes from the GUI's
    # default-settings path.
    _check_output_vmax_within_hardware(device_entry, settings.output_VmaxNI)
    _check_output_rate_within_hardware(device_entry, float(settings.output_fs))

    task = ni.Task()
    task.ao_channels.add_ao_voltage_chan(
        channel_string,
        min_val=-float(settings.output_VmaxNI),
        max_val=+float(settings.output_VmaxNI),
    )

    # Share the AI sample clock when possible: both input and output are NI,
    # the AI recorder is on the same device/chassis, hardware-timed AO
    # is supported, AND the AI stream actually runs at output_fs. With an
    # external clock source the `rate` argument below is only advisory —
    # the AO steps on every source tick — so sharing a mismatched AI clock
    # plays the drive at the wrong rate (hardware-verified on a USB-6212:
    # output_fs=2*fs halved every tone; an lpf_on oversampled capture
    # played the drive x100 fast, destroying the stimulus). Falls back to
    # the device's own timebase (unsynchronised but correctly rated).
    clock_source = ''
    if (settings.device_driver == 'nidaq'
            and _ni_backend.supports_hw_ao_sync(device_entry)
            and isinstance(REC_NI, Recorder_NI_nidaqmx)
            and REC_NI.device_entry is not None
            and REC_NI.device_entry['name'] == device_entry['name']
            and abs(float(REC_NI.settings.fs) - float(settings.output_fs))
                <= 1e-6 * float(settings.output_fs)):
        clock_source = _ni_backend.ai_sample_clock_source(device_entry) or ''

    task.timing.cfg_samp_clk_timing(
        rate=float(settings.output_fs),
        source=clock_source,
        sample_mode=ni.constants.AcquisitionType.FINITE,
        samps_per_chan=int(N_output),
    )

    # DSA AO modules (NI 9260) coerce off-ladder rates just like DSA AI
    # (see the coercion note in `_build_and_start_ai_task`). The
    # waveform was generated at `output_fs`, so playback at a coerced
    # rate shifts the stimulus frequencies by the coercion ratio — warn
    # so the user knows the drive band moved (with use_output_as_ch0
    # the *recorded* drive is the measured loopback, so TFs stay
    # correct).
    try:
        actual_out_fs = float(task.timing.samp_clk_rate)
    except (ni.errors.DaqError, AttributeError):
        actual_out_fs = None
    if (not clock_source and actual_out_fs
            and abs(actual_out_fs - float(settings.output_fs)) > 1e-6):
        print(
            'WARNING: requested output_fs = {:g} Hz was coerced to {:g} Hz '
            'by {} (hardware rate ladder); the stimulus plays at {:.4g}x '
            'the intended frequencies. Set output_fs to a supported rate '
            'to avoid this.'.format(
                float(settings.output_fs), actual_out_fs,
                device_entry['name'],
                actual_out_fs / float(settings.output_fs))
        )

    # nidaqmx write: shape is (n_channels, n_samples) for multi-channel,
    # or 1D for single channel. `output` here is (N_output, n_channels).
    data = np.asarray(output, dtype=np.float64).T
    if settings.output_channels == 1:
        data = data[0]
    task.write(data, auto_start=False)

    return _NidaqmxTaskAdapter(task)

def setup_output_soundcard(settings):
    '''Open a soundcard `sd.OutputStream` for `acquisition.output_signal`.

    Clamps ``settings.output_channels`` against the output device's
    ``max_output_channels`` first (mutating ``settings`` in place via
    `_clamp_soundcard_output_channels`); without this clamp,
    ``sd.OutputStream`` would raise PortAudio ``-9998`` on a device
    that supports fewer output channels than requested.
    '''
    _clamp_soundcard_output_channels(settings)
    dtype = 'float32'

    output_stream = sd.OutputStream(samplerate=settings.output_fs,
                                  blocksize=settings.chunk_size,
                                  device=settings.output_device_index,
                                  channels=settings.output_channels,
                                  dtype=dtype,
                                  latency=None,
                                  extra_settings=None,
                                  callback=None,
                                  finished_callback=None,
                                  clip_off=None,
                                  dither_off=None,
                                  never_drop_input=None,
                                  prime_output_buffers_using_stream_callback=None)
    output_stream.start()
    return output_stream


#%% Mock backend — hardware-free, for tests
#
# Drop-in replacement for `Recorder` / `Recorder_NI_nidaqmx`. Used by
# `tests/test_acquisition_mock.py` to exercise the acquisition path
# (log_data, output_signal, stream_snapshot) on machines without a
# soundcard or NI-DAQmx driver. Selected via
# ``settings.device_driver='mock'``; see `start_stream`.
#
# No audio device is ever opened — `setup_output_mock` returns a
# no-op adapter, and `MockRecorder` synthesises a deterministic
# signal into its buffers at construction time. Tests can write
# directly to `stored_time_data` / `osc_time_data` after
# `start_stream` to inject a specific signal.


class MockRecorder(object):
    '''Hardware-free recorder. Same public attribute surface as
    `Recorder` / `Recorder_NI_nidaqmx` — `osc_time_data`,
    `stored_time_data`, `trigger_detected`, `audio_stream`,
    `init_stream`, `end_stream`, etc. — but does not touch any device.

    Buffers are filled with a deterministic sine-per-channel signal at
    construction so analysis-flow tests see non-trivial data. Tests
    that want a specific signal can overwrite `stored_time_data`
    directly after ``streams.start_stream`` and before `log_data`'s
    ``stored_time``-second sleep elapses.

    Trigger semantics: `trigger_detected` stays False unless a test
    sets it manually (no callback fires, since no real samples are
    arriving). The pretrigger path in `log_data` therefore always
    times out and takes the no-trigger fallback when driven via the
    mock — which is sufficient to test the timeout path itself.
    Successful-trigger flows belong on real hardware tests.
    '''

    def __init__(self, settings):
        self.settings = settings
        self.trigger_detected = False
        self.trigger_first_detected_message = False

        self.osc_time_axis = np.arange(
            0,
            (settings.num_chunks * settings.chunk_size) / settings.fs,
            1 / settings.fs,
        )
        self.osc_freq_axis = np.fft.rfftfreq(
            len(self.osc_time_axis), 1 / settings.fs,
        )
        self.osc_time_data = np.zeros(
            (settings.num_chunks * settings.chunk_size, settings.channels)
        )
        self.osc_time_data_windowed = np.zeros_like(self.osc_time_data)
        self.osc_freq_data = np.abs(np.fft.rfft(self.osc_time_data, axis=0))

        self.stored_num_chunks = 2 + int(
            np.ceil((settings.stored_time * settings.fs) / settings.chunk_size)
        )
        self.stored_time_data = np.zeros(
            (self.stored_num_chunks * settings.chunk_size, settings.channels)
        )
        self.stored_time_data_windowed = np.zeros_like(self.stored_time_data)
        self.stored_freq_data = np.abs(np.fft.rfft(self.stored_time_data, axis=0))

        # Deterministic signal: channel k gets a 0.1 V sine at
        # 100 * (k+1) Hz so tests can see distinct content per channel.
        t_stored = np.arange(self.stored_time_data.shape[0]) / settings.fs
        for ch in range(settings.channels):
            self.stored_time_data[:, ch] = 0.1 * np.sin(
                2 * np.pi * 100 * (ch + 1) * t_stored
            )
        # Fill osc_time_data with the same deterministic per-channel
        # sine (phase from t=0), synthesised on its own axis so the
        # osc buffer may be longer or shorter than the stored buffer.
        t_osc = np.arange(self.osc_time_data.shape[0]) / settings.fs
        for ch in range(settings.channels):
            self.osc_time_data[:, ch] = 0.1 * np.sin(
                2 * np.pi * 100 * (ch + 1) * t_osc
            )

        # Preserve `audio_stream` across re-__init__ calls the same way
        # `Recorder_NI_nidaqmx` does — log_data's pretrigger path calls
        # __init__(settings) to zero buffers but expects the stream
        # marker to survive.
        if not hasattr(self, 'audio_stream'):
            self.audio_stream = None

    def init_stream(self, settings, _input_=True, _output_=False):
        # Mark live with a sentinel so `streams.REC.audio_stream is
        # not None` (the test that gates the NI-task reuse path)
        # reads truthy.
        self.audio_stream = object()

    def end_stream(self):
        global REC
        REC = None
        self.audio_stream = None


class _MockOutputStream(object):
    '''No-op output stream matching the shape of both the soundcard
    (`sd.OutputStream`: `write` / `stop` / `close` / `start`) and the
    NI (`_NidaqmxTaskAdapter`: `StartTask` / `StopTask` /
    `WaitUntilTaskDone`) sides, so `acquisition.output_signal` and
    `log_data`'s cleanup branches work without touching real audio.'''

    def __init__(self, settings, output):
        self.settings = settings
        self.output = np.asarray(output)
        self.started = False

    # soundcard-side surface
    def write(self, data):
        pass

    def stop(self):
        pass

    def close(self):
        pass

    def start(self):
        pass

    # NI-side surface
    def StartTask(self):
        self.started = True

    def StopTask(self):
        self.started = False

    def WaitUntilTaskDone(self, timeout):
        pass

    def ClearTask(self):
        pass


def setup_output_mock(settings, output):
    '''Hardware-free analog-output stub used by `acquisition.output_signal`
    when ``settings.output_device_driver='mock'``.'''
    return _MockOutputStream(settings, output)