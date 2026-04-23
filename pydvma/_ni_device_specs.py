"""Safe-default derivation for NI hardware.

Most specs (voltage ranges, sample-rate limits) are queried directly
from the live `nidaqmx` device object, so anything NI supports is
covered automatically. Things the DAQmx driver doesn't expose as
properties — AC coupling on DSA modules, the fact that the NI 9234
is pseudo-differential only, etc. — live in the static `QUIRKS` table
below and are merged into the queried info.

Typical usage:

>>> import pydvma as dvma
>>> kwargs = dvma.suggest_ni_settings(device_index=0)
>>> s = dvma.MySettings(**kwargs, channels=2, stored_time=1.0)
>>> ds = dvma.log_data(s)

The returned dict is just MySettings kwargs, so you can override any
field (channels, fs, VmaxNI, ...) before constructing.
"""
from __future__ import annotations


try:
    import nidaqmx
    from nidaqmx import system as _nidaq_system
    from nidaqmx.constants import ProductCategory as _ProductCategory
except ImportError:
    nidaqmx = None
    _nidaq_system = None
    _ProductCategory = None
except NotImplementedError:
    nidaqmx = None
    _nidaq_system = None
    _ProductCategory = None


# Non-queryable device facts. Keyed by `product_type`. Each entry is
# merged on top of the queried info in `get_device_info`. Add to this
# table when you discover something the DAQmx driver doesn't expose.
QUIRKS = {
    'NI 9234': {
        'terminal_configs': ['DAQmx_Val_PseudoDiff'],
        'ac_coupled_hpf_hz': 0.5,
        'rate_ladder': 'DSA: fs_base / (256 * n), n in [1, 31]; base = 13.1072 MHz',
        'ai_sampling': 'simultaneous',
        'notes': (
            'Dynamic Signal Acquisition module; pseudo-differential '
            'only; AC-coupled with ~0.5 Hz high-pass so low-frequency '
            'content is attenuated; discrete sample-rate ladder '
            '(fs_base / 256*n) so requested rates are snapped; '
            'simultaneous-sampling (one ADC per channel, no inter-'
            'channel skew).'
        ),
    },
    'NI 9260 (BNC)': {
        'ao_sampling': 'simultaneous',
        'notes': (
            'DSA AO module; output limit is ±4.24 V peak (= 3 V_rms). '
            'Minimum sample rate ~1.613 kS/s; simultaneous-updating '
            '(one DAC per channel).'
        ),
    },
    'NI 9260': {
        'ao_sampling': 'simultaneous',
        'notes': (
            'DSA AO module; output ±4.24 V peak (3 V_rms); '
            'fs >= ~1.613 kS/s; simultaneous-updating.'
        ),
    },
    'USB-6001': {'ai_sampling': 'multiplexed', 'notes': 'Low-cost DAQ; AO is software-timed; AO fs <= 5 kS/s; multiplexed AI (single ADC scans channel list, so samples are skewed by the convert time).'},
    'USB-6002': {'ai_sampling': 'multiplexed', 'notes': 'Low-cost DAQ; AO is software-timed; AO fs <= 5 kS/s; multiplexed AI (single ADC scans channel list, so samples are skewed by the convert time).'},
    'USB-6003': {'ai_sampling': 'multiplexed', 'notes': 'Low-cost DAQ; AO is software-timed; AO fs <= 5 kS/s; multiplexed AI (single ADC scans channel list, so samples are skewed by the convert time).'},
    'USB-6008': {'ai_sampling': 'multiplexed', 'notes': 'Low-cost DAQ; AO is software-timed; AO fs <= 5 kS/s; multiplexed AI (single ADC scans channel list, so samples are skewed by the convert time).'},
    'USB-6009': {'ai_sampling': 'multiplexed', 'notes': 'Low-cost DAQ; AO is software-timed; AO fs <= 5 kS/s; multiplexed AI (single ADC scans channel list, so samples are skewed by the convert time).'},
    'USB-6212': {'ai_sampling': 'multiplexed', 'notes': 'M-series DAQ; hardware-timed AO; multiplexed AI (single ADC scans channel list, so samples are skewed by the convert time).'},
}


def _pairs(flat):
    '''Turn a flat DAQmx range list ``[min, max, min, max, ...]`` into
    ``[(min, max), ...]``.'''
    flat = list(flat)
    return [(flat[i], flat[i + 1]) for i in range(0, len(flat) - 1, 2)]


def _try(callable_):
    '''Call ``callable_()``; return its result or None on any exception.

    Modules that lack AI (or AO) raise DAQmx error -200197 when their
    ai_* (or ao_*) properties are accessed; we just treat those as
    absent rather than catching-and-handling each case.
    '''
    try:
        return callable_()
    except Exception:
        return None


def get_device_info(device_name):
    '''Query a live NI device's capabilities via nidaqmx.

    Parameters
    ----------
    device_name : str
        DAQmx device name, e.g. ``'Dev1'`` or ``'cDAQ1Mod1'``.

    Returns
    -------
    dict
        Keys include ``name``, ``product_type``, ``product_category``
        (as the ProductCategory enum member), ``ai_voltage_ranges`` and
        ``ao_voltage_ranges`` as ``[(min, max), ...]`` lists,
        ``ai_max_single_chan_rate`` / ``ai_min_rate`` /
        ``ao_max_rate`` / ``ao_min_rate`` as floats (or None if the
        module doesn't support that axis), plus any static notes from
        the `QUIRKS` table.
    '''
    if nidaqmx is None:
        raise RuntimeError('nidaqmx is not installed')
    dev = nidaqmx.system.Device(device_name)
    info = {
        'name': dev.name,
        'product_type': dev.product_type,
        'product_category': _try(lambda: dev.product_category),
        'ai_voltage_ranges': _pairs(_try(lambda: dev.ai_voltage_rngs) or []),
        'ai_max_single_chan_rate': _try(lambda: float(dev.ai_max_single_chan_rate)),
        'ai_min_rate': _try(lambda: float(dev.ai_min_rate)),
        'ao_voltage_ranges': _pairs(_try(lambda: dev.ao_voltage_rngs) or []),
        'ao_max_rate': _try(lambda: float(dev.ao_max_rate)),
        'ao_min_rate': _try(lambda: float(dev.ao_min_rate)),
    }
    info.update(QUIRKS.get(info['product_type'], {}))
    return info


def _safe_fs(ai_info, ao_info, hard_ceiling=50000):
    '''Pick a sample rate that both AI and AO can run at.

    Uses 1/4 of the lower of (AI max, AO max) so the AI buffer has
    headroom, clamped above the higher of (AI min, AO min) and below
    ``hard_ceiling``. Rounded to the nearest 100.

    Note: the USB-600x low-cost series caps AO at 5 kS/s even though
    AI can go to 100 kS/s — taking the joint min is critical there.
    '''
    maxes = []
    if ai_info is not None:
        r = ai_info.get('ai_max_single_chan_rate')
        if r is not None:
            maxes.append(r)
    if ao_info is not None:
        r = ao_info.get('ao_max_rate')
        if r is not None:
            maxes.append(r)
    ceiling = min(maxes + [hard_ceiling]) if maxes else hard_ceiling
    fs = ceiling / 4

    mins = []
    if ai_info is not None:
        m = ai_info.get('ai_min_rate')
        if m is not None and m > 1:   # below 1 Hz is always achievable
            mins.append(m)
    if ao_info is not None:
        m = ao_info.get('ao_min_rate')
        if m is not None and m > 1:
            mins.append(m)
    if mins:
        fs = max(fs, max(mins))

    return int(round(fs / 100) * 100)


def _pick_terminal_config(ai_info):
    '''Honour a QUIRKS-restricted terminal_configs list if present;
    otherwise default to RSE.'''
    if ai_info is None:
        return 'DAQmx_Val_RSE'
    constrained = ai_info.get('terminal_configs')
    if constrained:
        return constrained[0]
    return 'DAQmx_Val_RSE'


def _pick_vmax(ranges, default):
    '''Largest symmetric range's positive endpoint; or ``default``.'''
    if not ranges:
        return default
    # pick ranges whose min == -max (standard NI convention)
    symmetric = [r for r in ranges if abs(r[0] + r[1]) < 1e-9]
    target = symmetric or ranges
    return float(max(r[1] for r in target))


def suggest_ni_settings(device_index, ni_backend='nidaqmx'):
    '''Return MySettings kwargs with safe defaults for an NI device.

    Picks conservative values that will not trigger DAQmx range /
    rate errors out of the box: largest symmetric voltage range the
    device reports, AI terminal config compatible with the module
    (pseudo-diff for DSA, RSE otherwise), and a sample rate at 1/4 of
    the lower of AI / AO max-rates.

    Parameters
    ----------
    device_index : int
        Index into the enumeration — which enumeration depends on
        ``ni_backend``. For ``'nidaqmx'`` (default) this is the
        chassis-collapsed list from `_ni_backend.enumerate_devices`;
        for ``'pydaqmx'`` it's the flat list from
        `streams.get_devices_NI`.
    ni_backend : {'nidaqmx', 'pydaqmx'}

    Returns
    -------
    dict
        Keyword arguments for `MySettings(...)` — ``device_driver``,
        ``device_index``, ``ni_backend``, ``NI_mode``, ``VmaxNI``,
        ``output_VmaxNI``, ``fs``, ``output_fs``, plus matching
        output_device_* fields. You can merge in your own
        ``channels=N, stored_time=..., pretrig_samples=...`` as needed.
    '''
    if ni_backend == 'nidaqmx':
        if nidaqmx is None:
            raise RuntimeError("ni_backend='nidaqmx' selected but nidaqmx is not installed")
        from . import _ni_backend
        entries = _ni_backend.enumerate_devices()
        if not entries:
            raise RuntimeError('No NI devices found via nidaqmx')
        if device_index < 0 or device_index >= len(entries):
            raise ValueError(
                'device_index %r out of range (nidaqmx sees %d devices)'
                % (device_index, len(entries))
            )
        entry = entries[device_index]
        if entry['is_chassis']:
            ai_mod = next((m for m in entry['module_names']
                           if entry['module_ai_counts'].get(m, 0) > 0), None)
            ao_mod = next((m for m in entry['module_names']
                           if entry['module_ao_counts'].get(m, 0) > 0), None)
            ai_info = get_device_info(ai_mod) if ai_mod else None
            ao_info = get_device_info(ao_mod) if ao_mod else None
        else:
            ai_info = ao_info = get_device_info(entry['name'])
    elif ni_backend == 'pydaqmx':
        # pydaqmx enumeration is flat; use nidaqmx to query specs regardless.
        from . import streams
        names, _ = streams.get_devices_NI()
        if names is None or device_index >= len(names):
            raise ValueError('device_index %r out of range on pydaqmx enumeration' % device_index)
        ai_info = ao_info = get_device_info(names[device_index]) if nidaqmx else None
    else:
        raise ValueError('ni_backend must be "nidaqmx" or "pydaqmx"')

    return {
        'device_driver': 'nidaq',
        'device_index': device_index,
        'output_device_driver': 'nidaq',
        'output_device_index': device_index,
        'ni_backend': ni_backend,
        'NI_mode': _pick_terminal_config(ai_info),
        'VmaxNI': _pick_vmax(
            (ai_info or {}).get('ai_voltage_ranges', []), default=10.0,
        ),
        'output_VmaxNI': _pick_vmax(
            (ao_info or {}).get('ao_voltage_ranges', []), default=5.0,
        ),
        'fs': _safe_fs(ai_info, ao_info),
        'output_fs': _safe_fs(ai_info, ao_info),
    }
