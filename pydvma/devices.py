# -*- coding: utf-8 -*-
"""Choosing a device, and knowing what you chose.

``device_index`` is a position in an enumeration, which is a poor way to
name hardware and a worse way to record what a measurement was taken on.
This module is the layer above it: it inventories what is actually
present, says what is KNOWN about each device versus merely assumed,
recommends which backend to drive it through, and resolves a
human-written name to an index.

Three problems it exists to solve, all of them observed on real benches:

1. **One device, many entries.** Windows lists a single interface once
   per host API — an ESI U24 XL appears seven times here, four of them
   inputs — and the entries are NOT equivalent: MME and DirectSound
   deliver a 16-bit word and accept sample rates the hardware cannot
   clock (the audio engine resamples silently), while WDM-KS delivers
   24 bits and refuses. macOS lists each device once, so none of this is
   visible there. See :func:`preferred_backend`.

2. **Indices move.** The WDM-KS block reordered between two enumerations
   minutes apart with no hardware change (2026-08-12), and a Scarlett
   2i2 moved index when another interface was unplugged (2026-08-10).
   :func:`resolve` selects by name so a script says what it means.

3. **"Volts" are not always volts.** For a device in
   :mod:`pydvma._soundcard_specs` the full-scale voltage is known and
   ``VmaxSC`` follows in closed form. For any other interface pydvma can
   read channel counts and sample rates from the driver but has no way
   to learn what one full-scale sample is worth in volts, and the
   ``VmaxSC = 1.0`` default is a PLACEHOLDER, not a measurement.
   Reporting both cases identically would let an assumption pass for a
   fact, so every entry carries an explicit :func:`calibration_status`
   and the remedy for it.
"""

from . import _soundcard_specs

try:
    import sounddevice as sd
except (ImportError, NotImplementedError, OSError):
    sd = None

try:
    from . import _ni_backend
except Exception:                                  # pragma: no cover
    _ni_backend = None


#: Host APIs in descending order of how much they can be trusted, from
#: measurements on this bench (``dev/2026-08-12-u24xl-windows-bench.md``).
#: WDM-KS and WASAPI bypass the Windows shared-mode audio engine, so they
#: refuse a rate the hardware cannot clock instead of resampling to it,
#: and WDM-KS additionally delivered a full 24-bit word where MME and
#: DirectSound truncated to 16. Platforms that list each device once
#: (Core Audio, ALSA, JACK) have no choice to make and rank first
#: trivially. An unlisted host API sorts mid-table rather than last —
#: unknown is not the same as bad.
HOSTAPI_RANK = {
    'Core Audio': 0,
    'ALSA': 0,
    'JACK Audio Connection Kit': 0,
    'Windows WDM-KS': 0,
    'Windows WASAPI': 1,
    'Windows DirectSound': 3,
    'MME': 4,
}
_UNKNOWN_HOSTAPI_RANK = 2

#: Why each rank, in one line, for the listing.
HOSTAPI_NOTE = {
    'Windows WDM-KS': '24-bit, refuses rates it cannot clock',
    'Windows WASAPI': 'honest rates; 24-bit shared, 16-bit exclusive',
    'Windows DirectSound': '16-bit, resamples silently',
    'MME': '16-bit, resamples silently',
}


def _rank(hostapi):
    return HOSTAPI_RANK.get(hostapi, _UNKNOWN_HOSTAPI_RANK)


#: Virtual entries that follow the OS default rather than naming
#: hardware. Selecting one means "whatever Windows currently considers
#: the default", which can change under a running measurement, so they
#: are listed but flagged rather than recommended.
_ALIAS_TOKENS = ('sound mapper', 'primary sound', 'default')


def is_alias(name):
    """Is this a virtual "follow the OS default" entry rather than a device?

    PortAudio's MME and DirectSound host APIs each publish a routing
    alias — ``'Microsoft Sound Mapper - Input'``, ``'Primary Sound
    Capture Driver'`` — that forwards to whatever the OS default happens
    to be. They enumerate exactly like hardware but name none, so a
    measurement recorded through one has no reproducible provenance.
    """
    needle = str(name or '').lower()
    return any(token in needle for token in _ALIAS_TOKENS)


#: Endpoints that are not an analogue input of the outside world: a
#: digital receiver, or an internal tap of what the machine is playing.
#: Both are legitimate things to record, but neither is what a device's
#: name means by default to a measurement tool, and neither has an
#: analogue voltage scale at all.
_AUXILIARY_TOKENS = ('spdif', 's/pdif', 'stereo mix', 'what u hear',
                     'loopback', 'wave out')


def _squash(text):
    """Lowercase and strip everything but letters and digits.

    Model names are written inconsistently by humans and by vendors
    alike — ``'ESI U24 XL'``, ``'U24XL'``, ``'esi-u24-xl'`` all mean the
    same box — so model matching compares the squashed forms.
    """
    return ''.join(ch for ch in str(text or '').lower() if ch.isalnum())


def _loose_match(needle, haystack):
    """Is ``needle`` a substring of ``haystack`` ignoring case and
    punctuation? Used for MODEL matching only; device-name matching stays
    literal, because a raw device name is what the user copied from a
    listing and should match exactly as shown."""
    a, b = _squash(needle), _squash(haystack)
    return bool(a) and a in b


def endpoint_role(name):
    """The ROLE part of a Windows endpoint name, lowercased.

    Windows names a capture endpoint ``'<role> (<device>)'`` — ``'Line
    (U24XL with SPDIF I/O)'``, ``'SPDIF Interface (U24XL with SPDIF
    I/O)'`` — so the role is the text before the first bracket. Reading
    the WHOLE name instead is a trap this module fell into once: the ESI
    U24 XL's model name contains the words "SPDIF I/O", so a substring
    test for 'spdif' flags its ANALOGUE line input as digital. Names
    without brackets (macOS, ALSA) have no role prefix, so the whole
    name is returned.
    """
    flat = ' '.join(str(name or '').split()).lower()
    head = flat.split('(', 1)[0].strip()
    return head or flat


def is_auxiliary(name):
    """Is this endpoint a digital or internal input rather than a jack?

    Used only to separate otherwise-equal matches in :func:`resolve` —
    an ESI U24 XL publishes both a line input and an S/PDIF receiver, so
    the natural spec ``'U24XL'`` hits two endpoints and one of them
    cannot carry volts. Judged on the endpoint ROLE (see
    :func:`endpoint_role`), never the model name. The tie-break is
    always reported in the note rather than applied silently.
    """
    role = endpoint_role(name)
    return any(token in role for token in _AUXILIARY_TOKENS)


def calibration_status(name, neighbours=None, input_gain_db=None,
                       input_mode='line'):
    """How much pydvma really knows about this device's volts.

    The distinction that keeps an assumption from passing for a fact.
    Sample rates and channel counts come from the driver and are equally
    knowable for any interface; the volts-per-full-scale does not, and
    without it a "voltage" reading is a normalised number wearing a unit.

    Args:
        name (str or None): PortAudio device name.
        neighbours (list or None): Every device name currently present,
            for the indirect Windows profile match — see
            ``_soundcard_specs.device_profile``.
        input_gain_db (float or None): Preamp gain the operator has
            stated, if any.
        input_mode (str): Input mode for the full-scale lookup.

    Returns ``(status, full_scale_volts_or_None, advice)`` where status
    is one of:

    - ``'characterised'`` — the device is in
      :mod:`pydvma._soundcard_specs` and its full scale is known, either
      because it is fixed-gain (nothing to mis-set) or because a gain
      was stated. ``VmaxSC`` is a real voltage.
    - ``'needs_gain'`` — the model is recognised and its maximum input
      level is tabulated, but it has an analogue gain control that no
      audio API can read, so the operator must state ``input_gain_db``
      before volts mean anything.
    - ``'uncalibrated'`` — the model is not characterised. Everything
      the driver reports is still trustworthy; the voltage scale is not
      known and ``VmaxSC = 1.0`` is a placeholder, so readings are
      effectively in full-scale units.
    """
    profile = _soundcard_specs.device_profile(name, neighbours=neighbours)
    if profile is None:
        return ('uncalibrated', None,
                'full scale unknown — readings are in FS units. Set VmaxSC '
                'from the maker\'s spec, or measure it with '
                'dvma.verify_input_scaling() against a known source.')

    fixed = _soundcard_specs.fixed_gain(name, neighbours=neighbours)
    gain = 0.0 if (fixed and input_gain_db is None) else input_gain_db
    if gain is None:
        return ('needs_gain', None,
                'set input_gain_db to the gain on the front panel — no audio '
                'API can read it, and VmaxSC cannot be derived without it.')
    try:
        volts = _soundcard_specs.full_scale_volts(
            name, gain, input_mode, neighbours=neighbours)
    except ValueError as exc:
        return ('needs_gain', None, str(exc))
    if volts is None:
        return ('needs_gain', None,
                'set input_gain_db to the gain on the front panel.')
    detail = ('fixed gain - nothing to mis-set' if fixed
              else 'at the stated %+g dB gain' % gain)
    return ('characterised', volts, detail)


def describe(index, driver='soundcard', neighbours=None, rates=True,
             channels=2):
    """Everything worth knowing about one enumerated device.

    Args:
        index (int): Device index for ``driver``.
        driver (str): ``'soundcard'`` or ``'nidaq'``.
        neighbours (list or None): Cached list of all device names.
        rates (bool): Probe the genuine sample-rate ladder. Costs a
            handful of driver round-trips, so a bulk listing can turn it
            off.
        channels (int): Channel count to probe rates with.

    Returns a dict with ``driver``, ``index``, ``name``, ``hostapi``,
    ``max_input_channels``, ``max_output_channels``, ``default_samplerate``,
    ``native_rates``, ``profile`` (label or ``None``), ``status``,
    ``full_scale_volts``, ``advice``, ``channel_roles`` and ``rank``.
    """
    from . import streams
    if driver == 'nidaq':
        entries = _ni_backend.enumerate_devices() if _ni_backend else []
        e = entries[index]
        return {
            'driver': 'nidaq', 'index': index, 'name': e['name'],
            'hostapi': None, 'profile': e.get('product_type'),
            'max_input_channels': e.get('ai_channel_count') or 0,
            'max_output_channels': e.get('ao_channel_count') or 0,
            'default_samplerate': None, 'native_rates': [],
            # An NI AI range is commanded, not guessed: VmaxNI IS the
            # full scale, and the hardware is calibrated to it.
            'status': 'characterised', 'full_scale_volts': None,
            'advice': 'input range is set by VmaxNI (hardware-calibrated)',
            'channel_roles': [], 'rank': 0,
            'is_chassis': e.get('is_chassis'),
        }

    dev = sd.query_devices()[index]
    name = dev['name']
    if neighbours is None:
        neighbours = streams.all_soundcard_device_names()
    try:
        hostapi = sd.query_hostapis(dev['hostapi'])['name']
    except Exception:
        hostapi = None
    max_in = int(dev.get('max_input_channels', 0) or 0)
    status, volts, advice = calibration_status(name, neighbours=neighbours)
    profile = _soundcard_specs.device_profile(name, neighbours=neighbours)

    native, usable = [], []
    if rates and max_in:
        nch = min(channels, max_in) or 1
        try:
            native = streams.native_input_rates(_RateProbe(index, nch))
        except Exception:
            native = []
        try:
            usable = entry_usable_rates(
                index, hostapi, nch, dev.get('default_samplerate'), native)
        except Exception:
            usable = []

    return {
        'driver': 'soundcard', 'index': index, 'name': name,
        'hostapi': hostapi,
        'max_input_channels': max_in,
        'max_output_channels': int(dev.get('max_output_channels', 0) or 0),
        'default_samplerate': float(dev.get('default_samplerate', 0) or 0),
        'native_rates': native,
        'usable_rates': usable,
        'profile': profile['label'] if profile else None,
        'status': status, 'full_scale_volts': volts, 'advice': advice,
        'channel_roles': _soundcard_specs.channel_roles(
            name, max_in, neighbours=neighbours) or [],
        'rank': _rank(hostapi),
    }


def entry_usable_rates(index, hostapi, channels, default_samplerate,
                       native=None):
    """Rates THIS backend will actually clock, as opposed to accept.

    The device-wide ladder from :func:`streams.native_input_rates` says
    what the converter can do; it does not follow that every host API
    will let you have it. The three cases, measured
    (``dev/2026-08-12-u24xl-windows-bench.md``):

    - **WDM-KS**, and **WASAPI in exclusive mode**, bypass the Windows
      audio engine and refuse a format the hardware cannot clock, so
      what they accept is what you get. They do not accept the same set:
      on an ESI U24 XL, WASAPI-exclusive offers the full 8/16/32/44.1/48
      ladder while WDM-KS refuses everything below 44.1 kHz.
    - **WASAPI shared** runs at the endpoint's Default Format and only
      that.
    - **MME and DirectSound** accept ANY rate and let the engine
      resample to reach it. The only rate they deliver without
      conversion is that same Default Format — a "96 kHz" MME capture of
      a 44.1 kHz endpoint measured as a dead-flat dither floor above
      22 kHz with no information in it at all.

    So for the shared-mode APIs this deliberately ignores the probe and
    reports the Default Format alone. Reporting what they *accept* would
    reproduce the exact fiction this module exists to expose.

    Args:
        index (int): PortAudio device index.
        hostapi (str or None): Host-API name for that index.
        channels (int): Channel count to probe with.
        default_samplerate (float): The entry's default rate.
        native (list or None): Device-wide hardware ladder, used to
            bound the probe.

    Returns a list of floats, ascending, or ``[]`` when nothing can be
    determined.
    """
    from . import streams
    if sd is None:
        return []
    if hostapi in ('MME', 'Windows DirectSound'):
        return [float(default_samplerate)] if default_samplerate else []

    extra = None
    if hostapi == 'Windows WASAPI':
        try:
            extra = sd.WasapiSettings(exclusive=True)
        except Exception:
            extra = None

    out = []
    for rate in (native or streams._RATE_LADDER):
        try:
            sd.check_input_settings(device=index, channels=int(channels),
                                    samplerate=float(rate),
                                    extra_settings=extra)
            out.append(float(rate))
        except Exception:
            continue
    if not out and default_samplerate:
        out = [float(default_samplerate)]
    return out


class _RateProbe(object):
    """Minimal settings-like object for :func:`streams.native_input_rates`.

    That function takes a ``MySettings`` but only reads three fields, and
    constructing a real one here would recurse through the very
    device-resolution machinery this module provides.
    """

    device_driver = 'soundcard'

    def __init__(self, device_index, channels):
        self.device_index = device_index
        self.channels = channels


def _group_key(name):
    """Normalised name used to merge one device's per-host-API entries."""
    return ' '.join(str(name or '').lower().split())


def display_name(name, width=58):
    """A device name safe to print on one line.

    Driver-supplied names are not tidy strings: a Bluetooth headset
    enumerates here as a multi-line resource reference containing a
    literal newline, which would otherwise break the report layout.
    Whitespace is collapsed and over-long names are elided in the
    middle, where the distinguishing part of an audio device name is
    least likely to live.
    """
    flat = ' '.join(str(name or '').split())
    if len(flat) <= width:
        return flat
    keep = (width - 3) // 2
    return flat[:keep] + '...' + flat[-(width - 3 - keep):]


def inventory(driver='soundcard', kind='input', rates=True, channels=2):
    """Physical devices present, each with its available backends.

    Groups the per-host-API entries of one piece of hardware into a
    single record, which is the unit an operator actually thinks in.
    Grouping is by normalised name, tolerating the 31-character
    truncation MME applies. It is deliberately conservative: where a host
    API renames a device beyond recognition (PortAudio's WDM-KS builds
    its own name from the kernel-streaming filter, which on a Scarlett
    2i2 embeds the USB product id and looks nothing like the endpoint
    name) the entries stay separate. Two rows for one box is a smaller
    error than merging two different boxes into one row.

    Args:
        driver (str): ``'soundcard'`` or ``'nidaq'``.
        kind (str): ``'input'``, ``'output'`` or ``'all'``.
        rates (bool): Probe genuine rate ladders.
        channels (int): Channel count to probe rates with.

    Returns a list of dicts, each ``{'name', 'profile', 'status',
    'full_scale_volts', 'advice', 'channel_roles', 'entries'}`` where
    ``entries`` is that device's per-backend records (see
    :func:`describe`) sorted best-first.
    """
    from . import streams
    if driver == 'nidaq':
        entries = _ni_backend.enumerate_devices() if _ni_backend else []
        return [{'name': e['name'],
                 'profile': e.get('product_type'),
                 'status': 'characterised', 'full_scale_volts': None,
                 'advice': 'input range is set by VmaxNI (hardware-calibrated)',
                 'channel_roles': [],
                 'entries': [describe(i, 'nidaq')]}
                for i, e in enumerate(entries)]

    if sd is None:
        return []
    try:
        devices = sd.query_devices()
    except Exception:
        return []
    neighbours = streams.all_soundcard_device_names()

    groups = {}
    order = []
    for i, dev in enumerate(devices):
        max_in = int(dev.get('max_input_channels', 0) or 0)
        max_out = int(dev.get('max_output_channels', 0) or 0)
        if kind == 'input' and not max_in:
            continue
        if kind == 'output' and not max_out:
            continue
        try:
            entry = describe(i, 'soundcard', neighbours=neighbours,
                             rates=rates and kind != 'output',
                             channels=channels)
        except Exception:
            continue
        key = _group_key(entry['name'])
        # Fold an MME-truncated name into whichever group already holds
        # this device, in EITHER direction: the short form may arrive
        # first (MME enumerates before WASAPI) or last. Always adopt the
        # existing group's key -- the displayed name is upgraded to the
        # longest seen separately, below.
        for seen in list(groups):
            if key.startswith(seen) or seen.startswith(key):
                key = seen
                break
        if key not in groups:
            groups[key] = {'name': entry['name'], 'profile': entry['profile'],
                           'status': entry['status'],
                           'full_scale_volts': entry['full_scale_volts'],
                           'advice': entry['advice'],
                           'channel_roles': entry['channel_roles'],
                           'entries': []}
            order.append(key)
        group = groups[key]
        group['entries'].append(entry)
        # Prefer the longest name seen: MME truncates, others do not.
        if len(entry['name']) > len(group['name']):
            group['name'] = entry['name']

    out = []
    for key in order:
        group = groups[key]
        group['entries'].sort(key=lambda e: (e['rank'], e['index']))
        out.append(group)
    return out


def backend_map(kind='input'):
    """Which enumerated entries are the same box, and which one to use.

    The cheap half of :func:`inventory`: name grouping and backend
    ranking with NO capability probing, so it is safe to call on every
    bridge handshake. The UI needs exactly this much to stop showing one
    interface seven times.

    Args:
        kind (str): ``'input'``, ``'output'`` or ``'all'``.

    Returns ``{index: {'group', 'hostapi', 'recommended', 'is_alias',
    'is_auxiliary', 'siblings'}}`` for every soundcard entry of that
    kind, where ``group`` is a stable key shared by one device's
    backends and ``recommended`` marks the best-ranked one. Empty if
    PortAudio is unavailable.
    """
    if sd is None:
        return {}
    try:
        devs = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:
        return {}

    members = {}
    order = []
    for i, dev in enumerate(devs):
        max_in = int(dev.get('max_input_channels', 0) or 0)
        max_out = int(dev.get('max_output_channels', 0) or 0)
        if kind == 'input' and not max_in:
            continue
        if kind == 'output' and not max_out:
            continue
        try:
            api = hostapis[dev['hostapi']]['name']
        except Exception:
            api = None
        key = _group_key(dev['name'])
        for seen in list(members):
            if key.startswith(seen) or seen.startswith(key):
                key = seen
                break
        if key not in members:
            members[key] = []
            order.append(key)
        members[key].append((i, api, dev['name']))

    out = {}
    for key in order:
        entries = sorted(members[key], key=lambda t: (_rank(t[1]), t[0]))
        best = entries[0][0]
        for index, api, name in entries:
            out[index] = {
                'group': key,
                'hostapi': api,
                'recommended': index == best and not is_alias(name),
                'is_alias': is_alias(name),
                'is_auxiliary': is_auxiliary(name),
                'siblings': len(entries),
            }
    return out


def preferred_backend(group):
    """The entry of a device group that should be driven, or ``None``.

    Best-ranked host API first (see :data:`HOSTAPI_RANK`). This encodes a
    measurement, not a preference: on Windows the shared-mode APIs both
    truncate the word and accept sample rates the hardware cannot clock,
    so choosing MME — which is what ``sd.default.device`` points at on
    this bench — silently costs 8 bits and can hand back a "96 kHz"
    capture containing nothing above 22 kHz.
    """
    entries = group.get('entries') or []
    return entries[0] if entries else None


def resolve(spec, driver='soundcard', kind='input', fs=None):
    """Find the device index a human-written name refers to.

    Args:
        spec (str or int): A device index (returned unchanged), or a
            case-insensitive substring of the device name, e.g.
            ``'U24XL'``.
        driver (str): ``'soundcard'`` or ``'nidaq'``.
        kind (str): ``'input'`` or ``'output'``.
        fs (float or None): Intended sample rate. When given, a backend
            that cannot genuinely clock it is passed over in favour of
            one that can, rather than being chosen and silently
            resampling.

    Returns ``(index, entry, note)`` — the chosen index, its
    :func:`describe` record, and a human-readable sentence explaining
    the choice (which backend and why), suitable for printing.

    Raises ``ValueError`` naming every candidate when the spec matches
    no device, or more than one PHYSICAL device — guessing between two
    interfaces is exactly the mistake this function exists to prevent.
    """
    if isinstance(spec, int) or (isinstance(spec, str) and spec.isdigit()):
        index = int(spec)
        return index, describe(index, driver), 'device index %d' % index

    needle = str(spec).strip().lower()
    groups = inventory(driver=driver, kind=kind)
    hits = [g for g in groups if needle in g['name'].lower()]

    via_model = False
    if not hits:
        # Fall back to the MODEL name. The name an OS gives a device is
        # not portable: an ESI U24 XL is 'U24XL with SPDIF I/O' to
        # CoreAudio and 'Line (U24XL with SPDIF I/O)' to Windows, and a
        # Scarlett 2i2 is 'Scarlett 2i2 4th Gen' on macOS but generic
        # 'Analogue 1 + 2 (Focusrite USB Audio)' on Windows — nothing in
        # that string says which model it is. So a settings file that
        # names the raw device works only on the machine it was written
        # on. Matching `_soundcard_specs`' profile label instead makes
        # `device='ESI U24 XL'` resolve on every platform.
        hits = [g for g in groups
                if g.get('profile') and _loose_match(needle, g['profile'])]
        via_model = bool(hits)

    if not hits:
        known = sorted({g['profile'] for g in groups if g.get('profile')})
        message = ('%r matches no %s %s device by name or model. Present: %s'
                   % (spec, driver, kind,
                      ', '.join(repr(display_name(g['name'])) for g in groups)
                      or 'none'))
        if known:
            message += '. Recognised models: %s' % ', '.join(
                repr(k) for k in known)
        raise ValueError(message)

    also = ' (matched by model, not device name)' if via_model else ''
    if len(hits) > 1:
        # An exact name always wins over a partial one.
        exact = [g for g in hits if g['name'].strip().lower() == needle]
        if len(exact) == 1:
            hits = exact
    if len(hits) > 1:
        # Principled tie-break, not a guess: an auxiliary endpoint is a
        # digital or internal input, so it has no analogue voltage scale
        # and is never what "the U24 XL" means to a measurement. Applied
        # ONLY to separate otherwise-equal matches, and always reported.
        primary = [g for g in hits if not is_auxiliary(g['name'])]
        if len(primary) == 1:
            also += (' (%r also matched, but it is an auxiliary/digital input)'
                     % display_name(
                         [g for g in hits if g is not primary[0]][0]['name']))
            hits = primary
    if len(hits) > 1:
        raise ValueError(
            '%r matches %d different devices (%s) - be more specific rather '
            'than let pydvma guess which one to record.'
            % (spec, len(hits),
               ', '.join(repr(display_name(g['name'])) for g in hits)))

    group = hits[0]
    entries = group['entries']
    chosen = None
    rate_note = ''
    if fs:
        # Rank order is only a default: a backend that cannot genuinely
        # clock the requested rate is passed over for one that can,
        # because the alternative is a silent resample. On a U24 XL,
        # fs=8000 moves the choice off WDM-KS (which refuses below
        # 44.1 kHz) onto WASAPI, which clocks it for real.
        for entry in entries:
            usable = entry.get('usable_rates') or []
            if not usable or float(fs) in [float(r) for r in usable]:
                chosen = entry
                break
        if chosen is not None and chosen is not preferred_backend(group):
            rate_note = (' [not the default backend: %s cannot clock %g Hz]'
                         % (preferred_backend(group)['hostapi'], float(fs)))
        elif chosen is None:
            best = preferred_backend(group)
            rate_note = (' [WARNING: no backend clocks %g Hz natively; %s '
                         'will resample to reach it]'
                         % (float(fs), best['hostapi'] if best else '?'))
    if chosen is None:
        chosen = preferred_backend(group)
    if chosen is None:
        raise ValueError('%r has no usable %s entry.' % (group['name'], kind))

    note = 'using %r' % display_name(group['name'])
    note += also
    if chosen['hostapi']:
        note += ' via %s' % chosen['hostapi']
        why = HOSTAPI_NOTE.get(chosen['hostapi'])
        if why:
            note += ' (%s)' % why
        if len(entries) > 1:
            note += '; %d backends available' % len(entries)
    note += rate_note
    note += ' - device index %d' % chosen['index']
    return chosen['index'], chosen, note


#: Public alias. ``resolve`` is a natural name inside this module but too
#: generic in the top-level ``dvma`` namespace.
resolve_device_spec = resolve


_STATUS_LABEL = {
    'characterised': 'CHARACTERISED',
    'needs_gain': 'NEEDS GAIN',
    'uncalibrated': 'uncalibrated',
}

_LEGEND = """
  CHARACTERISED  this model is in pydvma's device table: its full-scale
                 voltage is known, so VmaxSC is derived for you and
                 readings are real volts.
  NEEDS GAIN     the model is recognised and its maximum input level is
                 tabulated, but it has an analogue gain knob no audio API
                 can read. Set input_gain_db to the front-panel value.
  uncalibrated   not a characterised model. Channel counts and sample
                 rates still come straight from the driver and are
                 reliable; the VOLTAGE scale is not known, so VmaxSC=1.0
                 is a placeholder and readings are full-scale units.
                 Fix by setting VmaxSC from the maker's spec, or measure
                 it: dvma.verify_input_scaling(settings, source=...).

  >> marks the backend pydvma recommends for that device. On Windows one
     interface is listed once per host API and they are NOT equivalent -
     the shared-mode ones truncate the word to 16 bits and accept sample
     rates the hardware cannot clock, resampling silently to reach them.
"""


def format_inventory(driver=None, kind='input', rates=True, legend=True):
    """Render the device inventory as a printable report.

    One block per physical device: what it is, whether its voltage scale
    is KNOWN or merely assumed, and every backend it can be driven
    through with the recommended one marked. Backs
    :func:`streams.list_available_devices` and ``pydvma-serve
    --list-devices``.

    Output is deliberately ASCII: this prints to a Windows console,
    where the default code page mangles the en/em dashes used elsewhere
    in the codebase.

    Args:
        driver (str or None): Restrict to one driver, or ``None`` for
            every driver available.
        kind (str): ``'input'``, ``'output'`` or ``'all'``.
        rates (bool): Probe genuine rate ladders (a few driver
            round-trips per device).
        legend (bool): Append the explanation of the calibration
            statuses and the ``>>`` marker.
    """
    drivers = [driver] if driver else ['soundcard', 'nidaq']
    lines = []
    seen_status = set()
    for drv in drivers:
        if drv == 'soundcard' and sd is None:
            continue
        if drv == 'nidaq' and _ni_backend is None:
            continue
        groups = inventory(driver=drv, kind=kind, rates=rates)
        lines.append('')
        lines.append('=' * 70)
        lines.append("device_driver='%s'   %s devices" % (drv, kind))
        lines.append('=' * 70)
        if not groups:
            lines.append('  none found')
            continue
        for group in groups:
            alias = is_alias(group['name'])
            title = display_name(group['name'])
            if group['profile']:
                title += '   [%s]' % group['profile']
            lines.append('')
            lines.append('  %s' % title)
            if alias:
                lines.append('    NB this is a routing alias for the current '
                             'OS default, not a named device')
            seen_status.add(group['status'])
            volts = group['full_scale_volts']
            scale = ('full scale %.4f V peak, %s'
                     % (volts, group['advice']) if volts
                     else 'full scale unknown - readings are FS units')
            if group['status'] == 'needs_gain':
                scale = 'full scale not yet known - %s' % group['advice']
            lines.append('    calibration : %-14s %s'
                         % (_STATUS_LABEL.get(group['status'],
                                              group['status']), scale))
            roles = group.get('channel_roles') or []
            if any(r != 'analogue' for r in roles):
                lines.append('    channels    : %s   (a loopback input '
                             'carries the output mix, not the outside world)'
                             % ', '.join('%d=%s' % (i + 1, r)
                                         for i, r in enumerate(roles)))
            native = next((e.get('native_rates') for e in group['entries']
                           if e.get('native_rates')), [])
            if native:
                lines.append('    hardware    : clocks %s Hz'
                             % '/'.join('%g' % r for r in native))
            for n, entry in enumerate(group['entries']):
                mark = '>>' if (n == 0 and not alias) else '  '
                api = entry['hostapi'] or entry['driver']
                usable = entry.get('usable_rates') or []
                ladder = ('/'.join('%g' % r for r in usable) if usable
                          else 'not knowable')
                short = HOSTAPI_NOTE.get(entry['hostapi'], '')
                lines.append('    %s index %-3d %-20s delivers %-30s %s'
                             % (mark, entry['index'], api, ladder,
                                short if n == 0 else ''))
    if legend and seen_status:
        lines.append('')
        lines.append('-' * 70)
        lines.append(_LEGEND.rstrip())
    lines.append('')
    return '\n'.join(line.rstrip() for line in lines)
