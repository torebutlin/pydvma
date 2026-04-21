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


TERMINAL_CONFIG_MAP = {
    'DAQmx_Val_RSE': 'RSE',
    'DAQmx_Val_PseudoDiff': 'PSEUDODIFFERENTIAL',
    'DAQmx_Val_Diff': 'DIFF',
    'DAQmx_Val_NRSE': 'NRSE',
}


# USB-600x-family low-cost DAQs: AO is on-demand only, cannot share a
# hardware sample clock with AI.
_SW_TIMED_AO_TYPES = frozenset({
    'USB-6001', 'USB-6002', 'USB-6003', 'USB-6008', 'USB-6009',
})


def resolve_terminal_config(ni_mode):
    if TerminalConfiguration is None:
        raise RuntimeError('nidaqmx is not installed')
    enum_name = TERMINAL_CONFIG_MAP.get(ni_mode)
    if enum_name is None:
        raise ValueError(
            'Unknown NI_mode %r; supported: %s'
            % (ni_mode, ', '.join(sorted(TERMINAL_CONFIG_MAP.keys())))
        )
    return getattr(TerminalConfiguration, enum_name)


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
    return _build_channel_string(device_entry, n_channels, explicit_spec, io='ai')


def build_ao_channel_string(device_entry, n_channels, explicit_spec=None):
    return _build_channel_string(device_entry, n_channels, explicit_spec, io='ao')


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
    """Return the terminal name of the AI sample clock to use as the AO timebase.

    For USB/PCIe devices this is `/<dev>/ai/SampleClock`. For cDAQ chassis,
    when both AI and AO tasks run inside the chassis, referencing the AI
    module's sample clock routes through the chassis timebase.
    """
    if device_entry['is_chassis']:
        modules = device_entry['module_names']
        ai_modules = [m for m in modules if device_entry['module_ai_counts'].get(m, 0) > 0]
        if not ai_modules:
            return None
        return '/%s/ai/SampleClock' % ai_modules[0]
    return '/%s/ai/SampleClock' % device_entry['name']
