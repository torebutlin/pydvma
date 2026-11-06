"""Facts about specific audio interfaces that the audio APIs don't expose.

PortAudio and CoreAudio describe a sound card as a count of input and
output channels at a set of sample rates. Two things a measurement user
needs are missing from that picture:

- **What each channel physically is.** A Focusrite Scarlett 2i2 4th Gen
  reports four inputs, but only 1–2 are the analogue Mic/Line/Inst
  inputs; 3–4 are a DIGITAL LOOPBACK of the output mix (user guide p44,
  verified amplitude-exact). Recorded unknowingly, they look like a
  silent — or worse, plausible — pair of channels wired to nothing.
- **What full scale is in volts.** The preamp gain is a front-panel
  control that no API on macOS can read (see
  ``dev/plans/2026-08-10-focusrite-scarlett-design.md``), so pydvma
  cannot discover it. But given the gain the operator states, the
  full-scale voltage follows in closed form from the interface's
  published maximum input level, which is what
  :func:`full_scale_volts` computes for ``MySettings.VmaxSC``.

Some interfaces (the Audient iD44) have a gain per channel, a switchable
pad and channels that are neither analogue nor loopback (ADAT optical);
the profile keys ``per_channel_gain``, ``pad_db``, ``mode_channels`` and
a ``(min, max)`` gain range describe those. A float ``gain_range_db``
still means ``(0, value)``.

Both are static per model, so they live in the ``PROFILES`` table below,
in the spirit of ``_ni_device_specs.QUIRKS``. Add an entry when you
characterise a new interface; unknown devices simply get ``None`` back
and pydvma keeps its existing generic behaviour.
"""
from __future__ import annotations

import math


# dBu is referenced to 0.7746 V rms (1 mW into 600 ohm).
_DBU_REF_VRMS = 0.7746


PROFILES = {
    'scarlett_2i2_gen4': {
        # Matched case-insensitively against the device name reported by
        # PortAudio / CoreAudio. On macOS the model name appears
        # directly; on Windows it never does — the WDM-KS endpoints
        # ('Analogue 1 + 2 (wc4800_8219)') embed the USB product id
        # 0x8219 instead, which is the per-model stable key there.
        'match': ('scarlett 2i2 4th gen', '4800_8219'),
        # Vendor token for the indirect Windows match — see
        # :func:`device_profile`.
        'vendor_match': ('focusrite',),
        'label': 'Focusrite Scarlett 2i2 4th Gen',
        # Physical role of each input channel, in order. 'analogue' is a
        # real input; 'loopback' is a digital tap of the output mix and
        # is NOT connected to the outside world.
        'channel_roles': ('analogue', 'analogue', 'loopback', 'loopback'),
        # Maximum input level at MINIMUM gain, in dBu, per input mode
        # (user guide p43). Full scale at gain G is this minus G.
        'max_input_dbu': {'line': 22.0, 'inst': 12.0, 'mic': 16.0},
        # Usable preamp gain range in dB (p43).
        'gain_range_db': {'line': 69.0, 'inst': 62.0, 'mic': 69.0},
        # Maximum output level of the balanced line outputs, in dBu.
        # NB the front-panel Output knob is an ANALOGUE control in this
        # path, so output voltage is only repeatable at a marked knob
        # position — this figure is the ceiling, not a calibration.
        'max_output_dbu': 16.0,
    },
    'esi_u24xl': {
        # CoreAudio reports 'U24XL with SPDIF I/O'. The Windows
        # enumeration has not been captured yet — if it turns out to be
        # a generic vendor name, add the WDM-KS product-id token here
        # (see the 2i2 entry above and TODO.md).
        'match': ('u24xl', 'u24 xl'),
        'vendor_match': ('esi',),
        'label': 'ESI U24 XL',
        # Two line-level TS jack/RCA inputs; no other physical inputs.
        'channel_roles': ('analogue', 'analogue'),
        # User's guide §6: "Input Level (0dB): +4.7dBu" — i.e. 1.33 V
        # rms / 1.88 V peak reads full scale. Bench-confirmed to
        # 0.07 dB (2026-08-11, dev/2026-08-11-u24xl-bench.md) against a
        # MacBook Pro jack in its line-level output mode.
        'max_input_dbu': {'line': 4.7},
        # FIXED-GAIN interface: there is no analogue gain anywhere in
        # the input path. (The +12 dB "input gain" its USB descriptor
        # offers is an I2S DIGITAL gain — measured SNR is identical at
        # 0 and +12 dB — so it only rescales data; pydvma pins it to
        # 0 dB at capture time, see streams.Recorder.)
        'gain_range_db': {'line': 0.0},
        # User's guide §6: "Output Level (0dB): Max 6.9dBu". NB the
        # LEFT output jack doubles as a stereo headphone out (right
        # must be unplugged for headphone use) — as line outs both
        # jacks are mono L/R.
        'max_output_dbu': 6.9,
    },
    'audient_id44': {
        # iD44MKII Manual V4: p16 (preamp features: line inputs are
        # padded through the mic preamps, -10 dB pad, 100 Hz HPF), p18
        # (input table: mic max +18 dBu, line +28 dBu, DI +10 dBu;
        # digital reference 0 dBFS = +18 dBu), p19 (insert return drives
        # the ADC directly), p55 (spec table: mic gain 0 to +60 dB, line
        # gain -10 to +50 dB, D.I. gain 0-60 dB, mic EIN -126 dBu,
        # max input +18 dBu (+28 with pad), line outs +18 dBu = 0 dBFS,
        # headphones +14 dBu = 0 dBFS, 20 inputs = 4 analogue + 16
        # digital). Bench 2026-11-06 (Mac): CoreAudio reports 22 inputs
        # (21-22 loopback of DAW 1+2, amplitude exact), native rates
        # 44.1/48/88.2/96 kHz, open-input ADC floor about -117 dBFS rms
        # broadband at 48 kHz, line-path gain at the top stop measured
        # +50.46 dB on channel 2.
        'match': ('audient id44',),
        'vendor_match': ('audient',),
        'label': 'Audient iD44',
        # 4 analogue preamps, 16 ADAT optical inputs (not wired to
        # anything unless an expander is attached) and the two DAW
        # loopback channels.
        'channel_roles': ('analogue',) * 4 + ('optical',) * 16
                         + ('loopback',) * 2,
        # Maximum input at the mode's MINIMUM gain (p18, p55).
        'max_input_dbu': {'mic': 18.0, 'line': 28.0, 'inst': 10.0},
        # (minimum, maximum) gain in dB per mode (p55).
        'gain_range_db': {'mic': (0.0, 60.0), 'line': (-10.0, 50.0),
                          'inst': (0.0, 60.0)},
        # Switchable pad (p16). The 10 dB figure is assumed on line and
        # inst; the manual verifies it on mic only.
        'pad_db': 10.0,
        # Inst (D.I.) exists on the first two channels only (zero-based).
        'mode_channels': {'inst': (0, 1)},
        # Each analogue channel has its own gain control.
        'per_channel_gain': True,
        'preferred_fs': 48000,
        # Microphone equivalent input noise (p55) and the measured
        # open-input ADC floor, used by :func:`analogue_floor_dbfs`.
        'ein_dbu': -126.0,
        'adc_floor_dbfs': -117.0,
        'max_output_dbu': 18.0,
        'headphone_output_dbu': 14.0,
    },
}


def _direct_profile(name):
    """Profile whose ``match`` patterns hit ``name`` directly, or ``None``."""
    if not name:
        return None
    needle = str(name).lower()
    for profile in PROFILES.values():
        for pattern in profile['match']:
            if pattern in needle:
                return profile
    return None


def device_profile(name, neighbours=None):
    """The profile for a device name, or ``None`` if it is not characterised.

    Matching is a case-insensitive substring test against each profile's
    ``match`` patterns, so the name PortAudio reports can be passed
    straight through.

    ``neighbours`` — the names of every audio device currently present
    (see ``streams.all_soundcard_device_names``) — enables a second,
    indirect route that Windows needs. There the model name never
    reaches PortAudio: a Scarlett 2i2 4th Gen enumerates as generic
    ``'Analogue 1 + 2 (Focusrite USB Audio)'`` endpoints (MME truncates
    that further), and the model is only identifiable from the WDM-KS
    twin of the same hardware, whose name embeds the USB product id
    (``'wc4800_8219'``). When ``name`` itself matches nothing but
    exactly ONE characterised profile is matched among the neighbours
    AND ``name`` carries that profile's ``vendor_match`` token
    (``'focusrite'``), the endpoint is attributed to that profile.
    Two different characterised interfaces present at once would make a
    generic vendor name genuinely ambiguous, so anything other than a
    single-candidate resolution returns ``None``.
    """
    direct = _direct_profile(name)
    if direct is not None:
        return direct
    if not name or not neighbours:
        return None
    needle = str(name).lower()
    candidates = []
    for other in neighbours:
        profile = _direct_profile(other)
        if profile is not None and profile not in candidates:
            candidates.append(profile)
    if len(candidates) != 1:
        return None
    profile = candidates[0]
    if any(token in needle for token in profile.get('vendor_match', ())):
        return profile
    return None


def channel_roles(name, channels, neighbours=None):
    """Physical role of each of the first ``channels`` inputs, or ``None``.

    Returns a list of strings — ``'analogue'`` for a real input,
    ``'loopback'`` for a digital tap of the output mix — for a device in
    :data:`PROFILES`, otherwise ``None`` (meaning "unknown, treat every
    channel as ordinary"). Channels beyond the profile's list are
    reported as ``'analogue'`` rather than dropped, so a mis-specified
    table can never hide a real input. ``neighbours`` feeds the indirect
    Windows match — see :func:`device_profile`.
    """
    profile = device_profile(name, neighbours)
    if profile is None:
        return None
    roles = profile['channel_roles']
    return [roles[i] if i < len(roles) else 'analogue'
            for i in range(int(channels))]


def loopback_channels(name, channels, neighbours=None):
    """Zero-based indices of the digital-loopback inputs; ``[]`` if none.

    These are not wired to the outside world: they carry whatever the
    interface is playing. Useful both as a warning (a student recording
    them gets the output, not the structure) and as a cable-free
    end-to-end self-test — see ``dev/scarlett_hw_check.py``.
    """
    roles = channel_roles(name, channels, neighbours)
    if roles is None:
        return []
    return [i for i, role in enumerate(roles) if role == 'loopback']


def fixed_gain(name, neighbours=None):
    """True when the device is characterised and has NO analogue gain.

    On a fixed-gain interface (e.g. the ESI U24 XL) the full-scale
    voltage is a constant of the hardware, so ``MySettings`` can derive
    ``VmaxSC`` without the operator stating a gain — there is no knob
    whose position could invalidate it. False both for variable-gain
    devices and for devices that are not characterised at all.
    """
    profile = device_profile(name, neighbours)
    if profile is None:
        return False
    return all(_range_tuple(limit)[1] == 0.0
               for limit in profile['gain_range_db'].values())


def input_modes(name, neighbours=None):
    """Input modes this device supports, e.g. ``['line', 'inst', 'mic']``.

    ``None`` when the device is not characterised.
    """
    profile = device_profile(name, neighbours)
    if profile is None:
        return None
    return sorted(profile['max_input_dbu'])


def max_input_dbu(name, neighbours=None):
    """Maximum input level at minimum gain, in dBu, keyed by input mode.

    ``None`` when the device is not characterised. Published to the web
    UI so it can preview the full-scale voltage a stated gain implies,
    using the same arithmetic as :func:`full_scale_volts`.
    """
    profile = device_profile(name, neighbours)
    if profile is None:
        return None
    return dict(profile['max_input_dbu'])


def _range_tuple(value):
    """A ``gain_range_db`` entry as ``(min, max)``; a float means ``(0, value)``."""
    if isinstance(value, (tuple, list)):
        return (float(value[0]), float(value[1]))
    return (0.0, float(value))


def gain_range(name, input_mode, neighbours=None):
    """Usable ``(min_db, max_db)`` preamp gain for an input mode, or ``None``.

    ``None`` when the device is not characterised or lacks that mode.
    Profiles that store a single float give ``(0.0, value)``; the Audient
    iD44's line path starts at -10 dB.
    """
    profile = device_profile(name, neighbours)
    if profile is None:
        return None
    entry = profile['gain_range_db'].get(str(input_mode).lower())
    return None if entry is None else _range_tuple(entry)


def per_channel_gain(name, neighbours=None):
    """True when each analogue input has its own gain control (iD44)."""
    profile = device_profile(name, neighbours)
    return bool(profile and profile.get('per_channel_gain', False))


def channel_input_modes(name, channel, neighbours=None):
    """Input modes available on one zero-based channel, sorted, or ``None``.

    ``None`` when the device is not characterised. ``'inst'`` is offered
    only on the channels in the profile's ``mode_channels['inst']``;
    optical and loopback channels have no input mode (``[]``).
    """
    profile = device_profile(name, neighbours)
    if profile is None:
        return None
    channel = int(channel)
    roles = profile['channel_roles']
    role = roles[channel] if channel < len(roles) else 'analogue'
    if role != 'analogue':
        return []
    restricted = profile.get('mode_channels', {})
    return sorted(m for m in profile['max_input_dbu']
                  if m not in restricted or channel in restricted[m])


def optical_channels(name, channels, neighbours=None):
    """Zero-based indices of the digital optical (ADAT) inputs; ``[]`` if none."""
    roles = channel_roles(name, channels, neighbours)
    if roles is None:
        return []
    return [i for i, role in enumerate(roles) if role == 'optical']


def preferred_fs(name, neighbours=None):
    """The profile's preferred sample rate in Hz, or ``None``."""
    profile = device_profile(name, neighbours)
    return None if profile is None else profile.get('preferred_fs')


def _input_fs_dbu(profile, gain_db, input_mode, pad):
    """Input level (dBu) that reads full scale; validates mode, gain, pad."""
    mode = str(input_mode).lower()
    if mode not in profile['max_input_dbu']:
        raise ValueError(
            'input_mode {!r} is not available on {}; choose from {}.'
            .format(input_mode, profile['label'],
                    ', '.join(sorted(profile['max_input_dbu']))))
    gain = float(gain_db)
    gmin, gmax = _range_tuple(profile['gain_range_db'][mode])
    if not (gmin <= gain <= gmax):
        raise ValueError(
            'input_gain_db = {:g} dB is outside the {} {} input range '
            '({:g} to {:g} dB).'.format(gain, profile['label'], mode,
                                        gmin, gmax))
    if pad and not profile.get('pad_db'):
        raise ValueError('{} has no input pad.'.format(profile['label']))
    pad_db = profile['pad_db'] if pad else 0.0
    return profile['max_input_dbu'][mode] - (gain - gmin) + pad_db


def full_scale_volts(name, gain_db, input_mode='line', neighbours=None,
                     pad=False):
    """Volts (peak) corresponding to a full-scale reading, or ``None``.

    This is the value ``MySettings.VmaxSC`` wants: the jack voltage that
    reads 1.0 on the normalised ±1 scale PortAudio delivers. It follows
    from the interface's maximum input level ``L`` (in dBu, at minimum
    gain ``Gmin``), the preamp gain ``G`` and the optional pad::

        V_fullscale_peak = sqrt(2) * 0.7746
                           * 10 ** ((L - (G - Gmin) + pad_db) / 20)

    ``Gmin`` is 0 for the Scarlett and U24 XL, so this reduces to
    ``(L - G)`` there. **Confirmed on hardware to 0.10 dB** (2026-08-10):
    a 5.000 Vpp sine into a Scarlett 2i2 Line input at a reported 9 dB
    gain read 0.505072 of full scale, implying 4.9498 V peak against the
    4.8932 V predicted here. The iD44 pad value is assumed 10 dB on line
    and inst inputs and verified (manual) on mic only.

    Args:
        name (str): Device name as PortAudio reports it.
        gain_db (float or None): Preamp gain the operator has set;
            pydvma cannot read it, which is why it must be stated.
        input_mode (str): ``'line'``, ``'mic'`` or ``'inst'``.
        neighbours (list or None): Every device name present, for the
            indirect Windows match.
        pad (bool): True when the input pad is engaged.

    Returns:
        volts (float or None): Peak volts at digital full scale, or
            ``None`` for an uncharacterised device or no gain.

    Raises:
        ValueError: For an unknown input mode, a gain outside the
            device's range, or ``pad=True`` on a device with no pad, since
            a silently wrong voltage would propagate into every result.
    """
    profile = device_profile(name, neighbours)
    if profile is None or gain_db is None:
        return None
    level = _input_fs_dbu(profile, gain_db, input_mode, pad)
    return math.sqrt(2.0) * _DBU_REF_VRMS * 10.0 ** (level / 20.0)


def analogue_floor_dbfs(name, gain_db, input_mode='mic', neighbours=None,
                        pad=False):
    """Expected broadband noise floor in dBFS rms, or ``None``.

    Adds, in power, the preamp's equivalent input noise referred to full
    scale (``ein_dbu`` minus the full-scale input level at this gain) and
    the converter's own floor (``adc_floor_dbfs``). ``None`` when the
    profile has no ``ein_dbu``. Takes the same arguments as
    :func:`full_scale_volts` and raises the same ``ValueError``.
    """
    profile = device_profile(name, neighbours)
    if profile is None or gain_db is None or 'ein_dbu' not in profile:
        return None
    fs_dbu = _input_fs_dbu(profile, gain_db, input_mode, pad)
    power = (10.0 ** ((profile['ein_dbu'] - fs_dbu) / 10.0)
             + 10.0 ** (profile['adc_floor_dbfs'] / 10.0))
    return 10.0 * math.log10(power)
