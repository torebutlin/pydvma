"""macOS CoreAudio hardware-clock control, via ``ctypes``.

WHY THIS EXISTS
---------------
On macOS a USB audio interface runs at exactly one of a small set of
NATIVE sample rates, and that rate is a system-wide property of the
device. PortAudio (and therefore ``sounddevice``) never changes it. Ask
``sounddevice`` for any other rate and CoreAudio silently sample-rate-
converts, with no error and no way for the caller to tell.

Worse, ``sd.check_input_settings()`` reports success for rates the
hardware cannot run at all. Measured on a Focusrite Scarlett 2i2 4th Gen
(2026-08-10, ``dev/plans/2026-08-10-focusrite-scarlett-design.md``), it
accepted every rate from 3 kHz to 192 kHz while the device's true
capability is only::

    44100, 48000, 88200, 96000, 176400, 192000

The quality of the OS conversion depends on the ratio between the
device's current clock and the requested rate — a ratio nobody chose
deliberately, since it depends on whatever rate the last application
left the device at. Measured through that device's own loopback, at a
requested 8 kHz:

===========================  ==================  =================
condition                    device clock 192 k  device clock 44.1 k
===========================  ==================  =================
passband droop at 3 kHz      -4.3 dB             -1.0 dB
alias rejection, 5 kHz tone  -11.7 dB            -64.7 dB
===========================  ==================  =================

12 dB of alias rejection is unusable for measurement. When the requested
rate EQUALS the hardware clock the capture is exact (-0.00 dB at 1 k,
5 k and 15 kHz), so the fix is to pin the clock rather than to trust the
converter.

This module provides that pin. It is macOS-only and inert everywhere
else: ``available()`` returns False and the query helpers return None or
empty, so callers need no platform branches of their own.
"""

import ctypes
import ctypes.util
import struct
import sys
import time
from contextlib import contextmanager

__all__ = [
    'available', 'device_ids', 'device_name', 'find_device',
    'native_rates', 'get_nominal_rate', 'set_nominal_rate', 'pinned_rate',
]


kAudioObjectSystemObject = 1
kAudioObjectPropertyElementMain = 0
_UTF8 = 0x08000100  # kCFStringEncodingUTF8


def _fourcc(code):
    """Pack a four-character CoreAudio selector into its integer form."""
    return struct.unpack('>I', code.encode('ascii'))[0]


kAudioHardwarePropertyDevices = _fourcc('dev#')
kAudioObjectPropertyName = _fourcc('lnam')
kAudioDevicePropertyNominalSampleRate = _fourcc('nsrt')
kAudioDevicePropertyAvailableNominalSampleRates = _fourcc('nsr#')
kAudioObjectPropertyScopeGlobal = _fourcc('glob')


class AudioObjectPropertyAddress(ctypes.Structure):
    """CoreAudio ``AudioObjectPropertyAddress`` (selector, scope, element)."""

    _fields_ = [('mSelector', ctypes.c_uint32),
                ('mScope', ctypes.c_uint32),
                ('mElement', ctypes.c_uint32)]


class AudioValueRange(ctypes.Structure):
    """CoreAudio ``AudioValueRange``; discrete rates have min == max."""

    _fields_ = [('mMinimum', ctypes.c_double),
                ('mMaximum', ctypes.c_double)]


def _load(name):
    try:
        path = ctypes.util.find_library(name)
        return ctypes.CDLL(path) if path else None
    except OSError:
        return None


_ca = _load('CoreAudio') if sys.platform == 'darwin' else None
_cf = _load('CoreFoundation') if sys.platform == 'darwin' else None


def available():
    """True when CoreAudio clock control can be used on this machine.

    False on every non-macOS platform, and on macOS if the frameworks
    cannot be loaded. Callers should treat False as "leave the device
    alone and accept whatever rate it is running at".
    """
    return _ca is not None and _cf is not None


def _addr(selector, scope=kAudioObjectPropertyScopeGlobal):
    return AudioObjectPropertyAddress(selector, scope,
                                      kAudioObjectPropertyElementMain)


def _get_array(obj, addr, ctype):
    """Read a variable-length CoreAudio property as a list of ``ctype``."""
    size = ctypes.c_uint32(0)
    if _ca.AudioObjectGetPropertyDataSize(ctypes.c_uint32(obj),
                                          ctypes.byref(addr), 0, None,
                                          ctypes.byref(size)) != 0:
        return []
    count = size.value // ctypes.sizeof(ctype)
    if count <= 0:
        return []
    buf = (ctype * count)()
    if _ca.AudioObjectGetPropertyData(ctypes.c_uint32(obj), ctypes.byref(addr),
                                      0, None, ctypes.byref(size),
                                      ctypes.byref(buf)) != 0:
        return []
    return list(buf)


def device_ids():
    """Every CoreAudio device id on the system, or an empty list off macOS."""
    if not available():
        return []
    return _get_array(kAudioObjectSystemObject,
                      _addr(kAudioHardwarePropertyDevices), ctypes.c_uint32)


def device_name(device_id):
    """Human-readable name of a CoreAudio device, or None if unavailable.

    The name matches what PortAudio reports for the same device, which is
    how :func:`find_device` bridges a ``sounddevice`` device index to a
    CoreAudio device id.
    """
    if not available():
        return None
    addr = _addr(kAudioObjectPropertyName)
    cfstr = ctypes.c_void_p()
    size = ctypes.c_uint32(ctypes.sizeof(cfstr))
    if _ca.AudioObjectGetPropertyData(ctypes.c_uint32(device_id),
                                      ctypes.byref(addr), 0, None,
                                      ctypes.byref(size),
                                      ctypes.byref(cfstr)) != 0 or not cfstr:
        return None
    _cf.CFStringGetCStringPtr.restype = ctypes.c_char_p
    ptr = _cf.CFStringGetCStringPtr(cfstr, _UTF8)
    if ptr:
        return ptr.decode('utf-8', 'replace')
    buf = ctypes.create_string_buffer(512)
    if _cf.CFStringGetCString(cfstr, buf, 512, _UTF8):
        return buf.value.decode('utf-8', 'replace')
    return None


def find_device(name):
    """Locate a CoreAudio device by name; returns ``(device_id, name)``.

    Matching is exact first, then case-insensitive substring, so a
    PortAudio device name passed straight through will resolve. Returns
    ``(None, None)`` when there is no match or CoreAudio is unavailable.
    """
    if not available() or not name:
        return (None, None)
    ids = device_ids()
    names = {}
    for dev in ids:
        nm = device_name(dev)
        if nm is not None:
            names[dev] = nm
    for dev, nm in names.items():
        if nm == name:
            return (dev, nm)
    needle = name.lower()
    for dev, nm in names.items():
        if needle in nm.lower() or nm.lower() in needle:
            return (dev, nm)
    return (None, None)


def native_rates(device_id):
    """Sample rates the device can genuinely run at, ascending, in Hz.

    This is the authoritative capability list — unlike
    ``sd.check_input_settings``, which on macOS approves rates the
    hardware cannot run because CoreAudio would resample to reach them.
    Devices report discrete rates (min == max); the rare device
    advertising a continuous range contributes both endpoints. Returns an
    empty list off macOS or on any query failure, which callers should
    read as "capability unknown, do not pin".
    """
    if not available():
        return []
    ranges = _get_array(device_id,
                        _addr(kAudioDevicePropertyAvailableNominalSampleRates),
                        AudioValueRange)
    rates = set()
    for r in ranges:
        rates.add(float(r.mMinimum))
        rates.add(float(r.mMaximum))
    return sorted(rates)


def get_nominal_rate(device_id):
    """The device's current hardware clock in Hz, or None if unreadable."""
    if not available():
        return None
    addr = _addr(kAudioDevicePropertyNominalSampleRate)
    val = ctypes.c_double(0)
    size = ctypes.c_uint32(ctypes.sizeof(val))
    if _ca.AudioObjectGetPropertyData(ctypes.c_uint32(device_id),
                                      ctypes.byref(addr), 0, None,
                                      ctypes.byref(size),
                                      ctypes.byref(val)) != 0:
        return None
    return float(val.value)


def set_nominal_rate(device_id, fs, timeout=3.0):
    """Pin the device's hardware clock to ``fs`` Hz; True once it takes.

    The change is asynchronous — CoreAudio reconfigures the device and
    notifies listeners — so this polls until the reported rate matches or
    ``timeout`` seconds elapse, and returns False on timeout rather than
    letting the caller assume a rate that never took effect.

    NOTE this is a SYSTEM-WIDE property. Other applications using the
    same interface are switched too. Callers that care should use
    :func:`pinned_rate`, which restores the previous rate afterwards.
    """
    if not available():
        return False
    addr = _addr(kAudioDevicePropertyNominalSampleRate)
    val = ctypes.c_double(float(fs))
    if _ca.AudioObjectSetPropertyData(ctypes.c_uint32(device_id),
                                      ctypes.byref(addr), 0, None,
                                      ctypes.c_uint32(ctypes.sizeof(val)),
                                      ctypes.byref(val)) != 0:
        return False
    deadline = time.time() + float(timeout)
    while True:
        current = get_nominal_rate(device_id)
        if current is not None and abs(current - float(fs)) < 1e-6:
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.05)


@contextmanager
def pinned_rate(device_id, fs, restore=True, timeout=3.0):
    """Run a block with the device clock pinned to ``fs``, then restore it.

    Yields True if the clock is genuinely at ``fs`` for the duration, and
    False if it could not be pinned — in which case the caller is being
    told its capture will be OS-resampled and should warn rather than
    claim a rate it did not get. Never raises for a pin failure; a
    capture at the wrong rate beats no capture at all.

    With ``restore`` False the clock is left where it was set, which
    makes successive runs identical at the cost of having changed a
    system-wide setting without putting it back.
    """
    previous = get_nominal_rate(device_id)
    ok = False
    if previous is not None and abs(previous - float(fs)) < 1e-6:
        ok = True  # already there; nothing to restore
        previous = None
    else:
        ok = set_nominal_rate(device_id, fs, timeout=timeout)
    try:
        yield ok
    finally:
        if restore and ok and previous is not None:
            try:
                set_nominal_rate(device_id, previous, timeout=timeout)
            except Exception:
                pass
