"""Helpers for the nidaqmx-based NI backend.

Kept separate from streams.py so enumeration, channel-string construction,
and sync-capability logic can be unit-tested with a mocked nidaqmx.system
(no hardware required).
"""
from __future__ import annotations


try:
    import nidaqmx
    from nidaqmx import system as _nidaq_system
    from nidaqmx.constants import ProductCategory, TerminalConfiguration
except ImportError:
    nidaqmx = None
    _nidaq_system = None
    ProductCategory = None
    TerminalConfiguration = None
except NotImplementedError:
    nidaqmx = None
    _nidaq_system = None
    ProductCategory = None
    TerminalConfiguration = None


# nidaqmx 2026 Q2's TerminalConfiguration spells the pseudo-differential
# value `PSEUDO_DIFF` (verified against the live enum). Names on the
# right must match nidaqmx.constants.TerminalConfiguration member names.
TERMINAL_CONFIG_MAP = {
    'DAQmx_Val_RSE': 'RSE',
    'DAQmx_Val_PseudoDiff': 'PSEUDO_DIFF',
    'DAQmx_Val_Diff': 'DIFF',
    'DAQmx_Val_NRSE': 'NRSE',
}


# USB-600x-family low-cost DAQs: AO is on-demand only, cannot share a
# hardware sample clock with AI.
_SW_TIMED_AO_TYPES = frozenset({
    'USB-6001', 'USB-6002', 'USB-6003', 'USB-6008', 'USB-6009',
})


def resolve_terminal_config(ni_mode):
    """Map a pydvma ``NI_mode`` string to an `nidaqmx` TerminalConfiguration.

    Accepts the legacy PyDAQmx-style names used elsewhere in pydvma
    (``'DAQmx_Val_RSE'``, ``'DAQmx_Val_PseudoDiff'``,
    ``'DAQmx_Val_Diff'``, ``'DAQmx_Val_NRSE'``) and returns the matching
    nidaqmx enum member. Raises `RuntimeError` if nidaqmx is not
    installed, or `ValueError` for an unknown mode.

    Note that DSA modules (e.g. NI 9234) only accept
    ``'DAQmx_Val_PseudoDiff'``; the driver will reject any other mode
    when the channel is created.
    """
    if TerminalConfiguration is None:
        raise RuntimeError('nidaqmx is not installed')
    enum_name = TERMINAL_CONFIG_MAP.get(ni_mode)
    if enum_name is None:
        raise ValueError(
            'Unknown NI_mode %r; supported: %s'
            % (ni_mode, ', '.join(sorted(TERMINAL_CONFIG_MAP.keys())))
        )
    return getattr(TerminalConfiguration, enum_name)


def resolve_terminal_config_for_entry(entry, ni_mode, resolver=None):
    """Resolve ``NI_mode`` against what the entry's AI hardware supports.

    Returns the requested TerminalConfiguration when the device supports
    it. When the AI module advertises a set of supported configs (via
    `entry_capabilities`) that does **not** include the requested one —
    e.g. DSA modules like the NI 9234 accept only pseudo-differential
    while ``MySettings`` defaults to ``'DAQmx_Val_RSE'`` — falls back to
    the module's first supported config with a printed one-line note,
    instead of letting DAQmx fail channel creation with an opaque
    -200077. Verified against the real cDAQ-9174 + NI 9234 (2026-07-07
    Windows hardware session).

    If the capability probe fails or reports nothing, the requested
    config is returned unchanged and DAQmx has the final say.

    ``resolver`` is forwarded to `entry_capabilities` for the Mac-side
    mocked tests.
    """
    requested = resolve_terminal_config(ni_mode)  # validates the name
    try:
        supported = entry_capabilities(entry, resolver=resolver).get(
            'terminal_configs') or []
    except Exception:
        return requested
    if not supported or ni_mode in supported:
        return requested
    fallback = supported[0]
    print(
        "NI_mode {!r} is not supported by {} (supports: {}); using {!r}."
        .format(ni_mode, entry['name'], ', '.join(supported), fallback)
    )
    return resolve_terminal_config(fallback)


# Accept either name: nidaqmx uses `COMPACT_DAQ_CHASSIS` (observed on
# nidaqmx 2026 Q2); some older / alternate builds exposed `C_DAQ_CHASSIS`.
# Comparing by `.name` avoids a hard dependency on the exact enum layout.
_CHASSIS_CATEGORY_NAMES = frozenset({
    'COMPACT_DAQ_CHASSIS',
    'C_DAQ_CHASSIS',
})


def _is_chassis(dev):
    pc = getattr(dev, 'product_category', None)
    if pc is None:
        return False
    return getattr(pc, 'name', None) in _CHASSIS_CATEGORY_NAMES


def _ai_count(dev):
    try:
        return len(list(dev.ai_physical_chans))
    except Exception:
        return 0


def _ao_count(dev):
    try:
        return len(list(dev.ao_physical_chans))
    except Exception:
        return 0


def _make_entry(dev, *, is_chassis, ai_channel_count, ao_channel_count,
                module_names=None, module_ai_counts=None, module_ao_counts=None):
    return {
        'name': dev.name,
        'product_type': dev.product_type,
        'is_chassis': is_chassis,
        'ai_channel_count': ai_channel_count,
        'ao_channel_count': ao_channel_count,
        'module_names': list(module_names) if module_names else [],
        'module_ai_counts': dict(module_ai_counts) if module_ai_counts else {},
        'module_ao_counts': dict(module_ao_counts) if module_ao_counts else {},
    }


def enumerate_devices(system=None):
    """Enumerate NI devices, collapsing cDAQ chassis into one entry.

    USB/PCIe devices are returned as individual entries. A cDAQ chassis is
    returned as a single entry whose `ai_channel_count` / `ao_channel_count`
    are the sums across slotted modules; individual module devices are not
    returned on their own. `module_names` and `module_ai_counts` /
    `module_ao_counts` preserve slot-ordered data for the channel-string
    builder.
    """
    if nidaqmx is None:
        return []
    if system is None:
        system = _nidaq_system.System.local()

    devices = list(system.devices)
    module_to_chassis = {}
    for d in devices:
        if _is_chassis(d):
            for m in d.chassis_module_devices:
                module_to_chassis[m.name] = d.name

    out = []
    for d in devices:
        if _is_chassis(d):
            modules = list(d.chassis_module_devices)
            mod_ai = {m.name: _ai_count(m) for m in modules}
            mod_ao = {m.name: _ao_count(m) for m in modules}
            out.append(_make_entry(
                d,
                is_chassis=True,
                ai_channel_count=sum(mod_ai.values()),
                ao_channel_count=sum(mod_ao.values()),
                module_names=[m.name for m in modules],
                module_ai_counts=mod_ai,
                module_ao_counts=mod_ao,
            ))
        elif d.name in module_to_chassis:
            continue
        else:
            out.append(_make_entry(
                d,
                is_chassis=False,
                ai_channel_count=_ai_count(d),
                ao_channel_count=_ao_count(d),
            ))
    return out


def _range_fragment(name, io, count):
    if count == 1:
        return '%s/%s0' % (name, io)
    return '%s/%s0:%d' % (name, io, count - 1)


def _build_channel_string(device_entry, n_channels, explicit_spec, *, io):
    if explicit_spec:
        return explicit_spec
    if n_channels is None or n_channels <= 0:
        raise ValueError('n_channels must be >= 1 (got %r)' % (n_channels,))

    counts_key = 'module_%s_counts' % io
    if not device_entry['is_chassis']:
        available = device_entry['%s_channel_count' % io]
        if n_channels > available:
            raise ValueError(
                'Requested %d %s channels but device %r has only %d'
                % (n_channels, io, device_entry['name'], available)
            )
        return _range_fragment(device_entry['name'], io, n_channels)

    remaining = n_channels
    parts = []
    for mod_name in device_entry['module_names']:
        available = device_entry[counts_key].get(mod_name, 0)
        if available == 0:
            continue
        take = min(remaining, available)
        parts.append(_range_fragment(mod_name, io, take))
        remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        total = device_entry['%s_channel_count' % io]
        raise ValueError(
            'Requested %d %s channels but chassis %r has only %d available across its modules'
            % (n_channels, io, device_entry['name'], total)
        )
    return ','.join(parts)


def build_ai_channel_string(device_entry, n_channels, explicit_spec=None):
    """Build a DAQmx physical-channel string for an AI task.

    Takes a `device_entry` from `enumerate_devices()` and a channel
    count and returns a channel string that nidaqmx accepts.

    * For a standalone USB/PCIe device: ``'Dev1/ai0'`` or
      ``'Dev1/ai0:N-1'`` for N>1.
    * For a cDAQ chassis: walks the slotted modules in slot order and
      consumes ``n_channels`` across them, producing e.g.
      ``'cDAQ1Mod1/ai0:3,cDAQ1Mod2/ai0:3'`` for 8 channels across two
      4-ch modules. Modules with zero AI are skipped.
    * If ``explicit_spec`` is truthy, it is returned verbatim —
      provides an escape hatch for gappy / mixed-module layouts that
      the count-based builder cannot express.

    Raises `ValueError` if ``n_channels`` exceeds the device / chassis
    AI capacity.
    """
    return _build_channel_string(device_entry, n_channels, explicit_spec, io='ai')


def build_ao_channel_string(device_entry, n_channels, explicit_spec=None):
    """Build a DAQmx physical-channel string for an AO task.

    See `build_ai_channel_string` — same behaviour, ``ao`` substituted
    for ``ai``.
    """
    return _build_channel_string(device_entry, n_channels, explicit_spec, io='ao')


def ai_channel_module_map(device_entry, n_channels):
    """Return the owning device name for each of the first ``n_channels``
    AI channels, in acquisition order.

    The AI task built by `build_ai_channel_string` consumes channels
    across slotted modules in slot order, so channel *i* of the captured
    array does not necessarily live on the same module as channel *i+1*.
    This returns a list of length ``n_channels`` giving, for each channel
    index, the name of the device (module on a chassis, or the device
    itself for standalone USB/PCIe) that supplies it. That lets callers
    apply per-channel settings (e.g. IEPE excitation) and validate them
    against the *owning* module rather than assuming a single device.

    Examples:
        * Standalone USB, 3 channels -> ``['Dev1', 'Dev1', 'Dev1']``
        * Chassis with two 4-ch AI modules, 6 channels ->
          ``['cDAQ1Mod1']*4 + ['cDAQ1Mod4']*2`` (slot order, AO-only
          modules skipped — matching the channel string).

    Raises `ValueError` if ``n_channels`` exceeds the AI capacity, mirroring
    `build_ai_channel_string`.
    """
    if n_channels is None or n_channels <= 0:
        raise ValueError('n_channels must be >= 1 (got %r)' % (n_channels,))

    if not device_entry['is_chassis']:
        available = device_entry['ai_channel_count']
        if n_channels > available:
            raise ValueError(
                'Requested %d AI channels but device %r has only %d'
                % (n_channels, device_entry['name'], available)
            )
        return [device_entry['name']] * n_channels

    out = []
    remaining = n_channels
    for mod_name in device_entry['module_names']:
        available = device_entry['module_ai_counts'].get(mod_name, 0)
        if available == 0:
            continue
        take = min(remaining, available)
        out.extend([mod_name] * take)
        remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        raise ValueError(
            'Requested %d AI channels but chassis %r has only %d available '
            'across its modules'
            % (n_channels, device_entry['name'], device_entry['ai_channel_count'])
        )
    return out


def supports_hw_ao_sync(device_entry):
    """Whether AI and AO can share a hardware sample clock on this device.

    True for cDAQ chassis (modules share the chassis timebase) and for
    M-series / X-series with hardware-timed AO. False for USB-600x low-cost
    DAQs whose AO is on-demand only.
    """
    if device_entry['is_chassis']:
        return True
    return device_entry['product_type'] not in _SW_TIMED_AO_TYPES


def ai_sample_clock_source(device_entry):
    """Return the terminal to route as the AO sample clock for hardware
    AI/AO sync, or None if no explicit routing is needed/possible.

    USB/PCIe M- and X-series devices expose `/<dev>/ai/SampleClock`, and
    routing that as the AO source makes AO step on exactly the AI tick.

    cDAQ chassis: per-module `/cDAQ1Mod1/ai/SampleClock` is NOT routable
    as an AO source; the DAQmx driver rejects it. AI and AO on a cDAQ
    chassis are already phase-coherent via the chassis 80 MHz timebase,
    so returning None (fall through to the default per-task clock) gives
    a usable approximation. Sample-accurate cross-module sync needs a
    shared start trigger — tracked with TODO item 13.
    """
    if device_entry['is_chassis']:
        return None
    return '/%s/ai/SampleClock' % device_entry['name']


# Inverse of TERMINAL_CONFIG_MAP: an nidaqmx TerminalConfiguration enum
# member name -> the legacy ``DAQmx_Val_*`` string pydvma's ``NI_mode``
# and `resolve_terminal_config` speak, so a queried terminal-config list
# round-trips back to a value you can hand to `resolve_terminal_config`.
_TERMINAL_CONFIG_NAME_TO_LEGACY = {v: k for k, v in TERMINAL_CONFIG_MAP.items()}


def _safe(fn, default=None):
    """Call ``fn()``; return its result, or ``default`` on any exception.

    NI modules that lack an axis (an AO-only module has no AI properties,
    and vice-versa) raise DAQmx -200197 when the missing ``ai_*`` /
    ``ao_*`` property is read; a device that is offline can raise other
    DaqErrors. Capability probing should degrade to "not reported"
    rather than propagate — hence this catch-all guard.
    """
    try:
        return fn()
    except Exception:
        return default


def _terminal_configs(dev):
    """Supported AI terminal configs for a device, as pydvma legacy names.

    Terminal configuration is a *per-physical-channel* property in
    nidaqmx (``PhysicalChannel.ai_term_cfgs`` -> a list of
    ``TerminalConfiguration`` enum members) — there is no device-level
    equivalent — so this reads the FIRST AI physical channel's list and
    maps each enum member back to the ``DAQmx_Val_*`` string pydvma's
    ``NI_mode`` uses (e.g. ``RSE`` -> ``'DAQmx_Val_RSE'``,
    ``PSEUDO_DIFF`` -> ``'DAQmx_Val_PseudoDiff'``). Returns ``[]`` when
    the device exposes no AI channels or the property can't be read.
    """
    chans = _safe(lambda: list(dev.ai_physical_chans), []) or []
    if not chans:
        return []
    cfgs = _safe(lambda: list(chans[0].ai_term_cfgs), []) or []
    out = []
    for c in cfgs:
        legacy = _TERMINAL_CONFIG_NAME_TO_LEGACY.get(getattr(c, 'name', None))
        if legacy is not None and legacy not in out:
            out.append(legacy)
    return out


def device_capabilities(name, device=None):
    """Query a single NI device's acquisition capabilities via nidaqmx.

    Additive companion to `enumerate_devices` for the ``pydvma serve``
    capabilities handshake: enumerate tells you *what* devices exist,
    this tells you what one of them can *do*.

    Parameters
    ----------
    name : str
        DAQmx device/module name, e.g. ``'Dev1'`` or ``'cDAQ1Mod1'``.
    device : optional
        A pre-resolved nidaqmx ``Device`` (or a fake exposing the same
        properties — the Mac-side tests inject one). When ``None`` the
        name is resolved via ``nidaqmx.system.Device(name)``; that path
        needs nidaqmx importable (raises ``RuntimeError`` otherwise).

    Returns
    -------
    dict
        - ``ai_max_rate`` — ``ai_max_multi_chan_rate`` (the realistic
          multi-channel ceiling), falling back to
          ``ai_max_single_chan_rate`` when the multi property is absent.
        - ``ai_max_single_chan_rate`` — single-channel AI max rate.
        - ``ai_min_rate`` — minimum AI rate.
        - ``ao_max_rate`` / ``ao_min_rate`` — AO rate bounds.
          All rate fields are floats, or ``None`` when the axis/property
          is not reported by the device.
        - ``simultaneous`` — ``ai_simultaneous_sampling_supported``:
          ``True`` on delta-sigma (DSA) modules with a per-channel ADC
          (e.g. the NI 9234 — no inter-channel skew), ``False`` on
          multiplexed devices (USB-6003/6212, whose single ADC scans the
          channel list so samples are skewed by the convert time).
        - ``iepe_supported`` / ``iepe_currents`` — from
          ``ai_current_int_excit_discrete_vals``. A non-empty currents
          list (e.g. ``[0.002]`` on the 9234) means those values are
          legal for ``iepe_excit_current_A``; ``0.0`` (off) is always
          implicitly allowed and is not listed.
        - ``terminal_configs`` — legacy ``DAQmx_Val_*`` names supported
          by the first AI channel (see `_terminal_configs`).
        - ``ao_supported`` — the device exposes ≥1 AO physical channel.
        - ``ai_vmax`` / ``ao_vmax`` — largest symmetric voltage range
          (volts) from ``ai_voltage_rngs`` / ``ao_voltage_rngs``, or
          ``None`` when unreported. Lets clients clamp ``VmaxNI`` /
          ``output_VmaxNI`` before the driver rejects them — e.g. the
          NI 9260 rail is ±4.2426 V, *below* the MySettings default
          ``output_VmaxNI = 5.0``.

    Property names are verified against the nidaqmx-python source
    (``nidaqmx/system/device.py`` and ``physical_channel.py``); the same
    ``ai_max_single_chan_rate`` / ``ai_min_rate`` / ``ao_max_rate`` /
    ``ai_current_int_excit_discrete_vals`` are already relied on by
    `pydvma._ni_device_specs.get_device_info`.

    Sample-rate ladder caveat
    -------------------------
    DSA modules (e.g. the NI 9234) accept only a *discrete* set of rates
    derived from the module timebase (``fs_base / (256 · n)``). nidaqmx
    exposes the ``ai_min_rate`` / ``ai_max_*`` *bounds* but NOT the full
    ladder, and silently coerces a requested rate to the nearest legal
    step at task-create time. Treat the rate fields here as bounds, not
    a promise that every rate between them is achievable on a DSA module.
    """
    if device is None:
        if nidaqmx is None:
            raise RuntimeError('nidaqmx is not installed')
        device = _nidaq_system.Device(name)

    ai_multi = _safe(lambda: float(device.ai_max_multi_chan_rate))
    ai_single = _safe(lambda: float(device.ai_max_single_chan_rate))
    iepe_vals = _safe(lambda: list(device.ai_current_int_excit_discrete_vals), []) or []
    # Report only the >0 discrete currents; 0.0 (no excitation) is always
    # implicitly allowed and would otherwise make iepe_supported wrong.
    iepe_currents = [float(v) for v in iepe_vals if float(v) > 0.0]
    ao_chan_count = _safe(lambda: len(list(device.ao_physical_chans)), 0) or 0

    def _max_symmetric(ranges):
        # ranges is a flat [min, max, min, max, ...] list from
        # ai/ao_voltage_rngs; the largest symmetric range is the
        # largest |max| among the pairs.
        vals = [abs(float(v)) for v in (ranges or [])]
        return max(vals) if vals else None

    return {
        'ai_max_rate': ai_multi if ai_multi is not None else ai_single,
        'ai_max_single_chan_rate': ai_single,
        'ai_min_rate': _safe(lambda: float(device.ai_min_rate)),
        'ao_max_rate': _safe(lambda: float(device.ao_max_rate)),
        'ao_min_rate': _safe(lambda: float(device.ao_min_rate)),
        'simultaneous': _safe(
            lambda: bool(device.ai_simultaneous_sampling_supported)),
        'iepe_supported': len(iepe_currents) > 0,
        'iepe_currents': iepe_currents,
        'terminal_configs': _terminal_configs(device),
        'ao_supported': ao_chan_count > 0,
        'ai_vmax': _max_symmetric(_safe(lambda: list(device.ai_voltage_rngs))),
        'ao_vmax': _max_symmetric(_safe(lambda: list(device.ao_voltage_rngs))),
    }


def entry_capabilities(entry, resolver=None):
    """Merged capabilities for one `enumerate_devices` entry.

    A standalone USB/PCIe device reports every axis itself, so this just
    calls `device_capabilities` on it. A cDAQ **chassis** reports nothing
    at the chassis level — its AI/AO capabilities live on the slotted
    modules — so this queries the first AI-providing module for the AI
    fields (rate ladder, simultaneous sampling, IEPE, terminal configs)
    and the first AO-providing module for the AO fields, then merges
    them (mirroring how `_ni_device_specs.suggest_ni_settings` splits AI
    and AO across modules).

    ``resolver`` maps a device/module name to an object exposing the
    nidaqmx Device properties; it defaults to ``nidaqmx.system.Device``
    and is injected by the Mac-side tests.
    """
    if resolver is None:
        if nidaqmx is None:
            raise RuntimeError('nidaqmx is not installed')
        resolver = lambda n: _nidaq_system.Device(n)  # noqa: E731

    if not entry['is_chassis']:
        caps = device_capabilities(entry['name'], device=resolver(entry['name']))
        caps['ao_supported'] = bool(
            caps['ao_supported'] or entry['ao_channel_count'] > 0)
        return caps

    ai_mod = next((m for m in entry['module_names']
                   if entry['module_ai_counts'].get(m, 0) > 0), None)
    ao_mod = next((m for m in entry['module_names']
                   if entry['module_ao_counts'].get(m, 0) > 0), None)
    ai_caps = (device_capabilities(ai_mod, device=resolver(ai_mod))
               if ai_mod else {})
    ao_caps = (device_capabilities(ao_mod, device=resolver(ao_mod))
               if ao_mod else {})
    return {
        'ai_max_rate': ai_caps.get('ai_max_rate'),
        'ai_max_single_chan_rate': ai_caps.get('ai_max_single_chan_rate'),
        'ai_min_rate': ai_caps.get('ai_min_rate'),
        'ao_max_rate': ao_caps.get('ao_max_rate'),
        'ao_min_rate': ao_caps.get('ao_min_rate'),
        'simultaneous': ai_caps.get('simultaneous'),
        'iepe_supported': bool(ai_caps.get('iepe_supported', False)),
        'iepe_currents': ai_caps.get('iepe_currents', []),
        'terminal_configs': ai_caps.get('terminal_configs', []),
        'ao_supported': bool(ao_mod) or bool(ao_caps.get('ao_supported', False)),
        'ai_vmax': ai_caps.get('ai_vmax'),
        'ao_vmax': ao_caps.get('ao_vmax'),
    }
