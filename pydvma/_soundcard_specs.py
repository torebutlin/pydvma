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
        # PortAudio / CoreAudio.
        'match': ('scarlett 2i2 4th gen',),
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
}


def device_profile(name):
    """The profile for a device name, or ``None`` if it is not characterised.

    Matching is a case-insensitive substring test, so the name PortAudio
    reports can be passed straight through.
    """
    if not name:
        return None
    needle = str(name).lower()
    for profile in PROFILES.values():
        for pattern in profile['match']:
            if pattern in needle:
                return profile
    return None


def channel_roles(name, channels):
    """Physical role of each of the first ``channels`` inputs, or ``None``.

    Returns a list of strings — ``'analogue'`` for a real input,
    ``'loopback'`` for a digital tap of the output mix — for a device in
    :data:`PROFILES`, otherwise ``None`` (meaning "unknown, treat every
    channel as ordinary"). Channels beyond the profile's list are
    reported as ``'analogue'`` rather than dropped, so a mis-specified
    table can never hide a real input.
    """
    profile = device_profile(name)
    if profile is None:
        return None
    roles = profile['channel_roles']
    return [roles[i] if i < len(roles) else 'analogue'
            for i in range(int(channels))]


def loopback_channels(name, channels):
    """Zero-based indices of the digital-loopback inputs; ``[]`` if none.

    These are not wired to the outside world: they carry whatever the
    interface is playing. Useful both as a warning (a student recording
    them gets the output, not the structure) and as a cable-free
    end-to-end self-test — see ``dev/scarlett_hw_check.py``.
    """
    roles = channel_roles(name, channels)
    if roles is None:
        return []
    return [i for i, role in enumerate(roles) if role == 'loopback']


def input_modes(name):
    """Input modes this device supports, e.g. ``['line', 'inst', 'mic']``.

    ``None`` when the device is not characterised.
    """
    profile = device_profile(name)
    if profile is None:
        return None
    return sorted(profile['max_input_dbu'])


def full_scale_volts(name, gain_db, input_mode='line'):
    """Volts (peak) corresponding to a full-scale reading, or ``None``.

    This is the value ``MySettings.VmaxSC`` wants: the jack voltage that
    reads 1.0 on the normalised ±1 scale PortAudio delivers. It follows
    from the interface's maximum input level ``L`` (in dBu, at minimum
    gain) and the preamp gain ``G``::

        V_fullscale_peak = sqrt(2) * 0.7746 * 10 ** ((L - G) / 20)

    **Confirmed on hardware to 0.10 dB** (2026-08-10): a 5.000 Vpp sine
    into a Scarlett 2i2 Line input at a reported 9 dB gain read 0.505072
    of full scale, implying 4.9498 V peak against the 4.8932 V predicted
    here. So both the published table and Focusrite Control's gain
    readout can be trusted; no per-device calibration run is needed.

    ``gain_db`` is the preamp gain the operator has set — pydvma cannot
    read it, which is why it must be stated. Raises ``ValueError`` for an
    unknown input mode or a gain outside the device's range, since a
    silently wrong voltage would propagate into every derived result.
    """
    profile = device_profile(name)
    if profile is None or gain_db is None:
        return None
    mode = str(input_mode).lower()
    if mode not in profile['max_input_dbu']:
        raise ValueError(
            'input_mode {!r} is not available on {}; choose from {}.'
            .format(input_mode, profile['label'],
                    ', '.join(sorted(profile['max_input_dbu']))))
    gain = float(gain_db)
    limit = profile['gain_range_db'][mode]
    if not (0.0 <= gain <= limit):
        raise ValueError(
            'input_gain_db = {:g} dB is outside the {} {} input range '
            '(0 to {:g} dB).'.format(gain, profile['label'], mode, limit))
    max_dbu = profile['max_input_dbu'][mode]
    return math.sqrt(2.0) * _DBU_REF_VRMS * 10.0 ** ((max_dbu - gain) / 20.0)
