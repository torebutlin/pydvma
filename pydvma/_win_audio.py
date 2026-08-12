# -*- coding: utf-8 -*-
"""Windows Core Audio endpoint access, for the things PortAudio hides.

The Windows twin of :mod:`pydvma._coreaudio`, and it exists for the same
reason: a capture's SCALE depends on device state that the recording API
does not expose. On Windows that state is the endpoint volume — a
control the operator can move from the Sound control panel, or that
another application can move on their behalf, with no visible effect on
anything pydvma reads.

On an ESI U24 XL (measured 2026-08-12, ``dev/2026-08-12-u24xl-windows-bench.md``)
that control is a **−40 .. +12 dB digital gain** applied after the
converter. Two consequences, both bad for measurement:

- It rescales captured data while ``VmaxSC`` goes on asserting the
  device's published full-scale voltage, so every reading is wrong by
  the slider position. The slider's 100% is +12 dB, and 0 dB sits at
  63% of travel, so "turned up" is the natural resting state.
- Because it is post-converter, boosting cannot recover headroom — it
  clips data that was already digitised. Worse, ATTENUATING a clipped
  capture hides the clipping from the level meter: at −20 dB an
  over-range signal peaks at 10% of full scale while still being 45%
  flat-topped.

So pydvma pins it to 0 dB (unity) for the duration of a stream and puts
it back afterwards, exactly as the CoreAudio path does.

Implemented with raw ``ctypes`` COM rather than ``pycaw``/``comtypes``
to keep the dependency surface at zero — the same choice
:mod:`pydvma._coreaudio` makes against ``pyobjc``. Every entry point
returns a benign value rather than raising when the platform, the COM
objects or the device are not there, so callers can invoke them
unconditionally.
"""

import ctypes
from ctypes import POINTER, byref, c_float, c_uint32, c_void_p, c_wchar_p

try:
    from ctypes import HRESULT, WinDLL, oledll
    _ole32 = oledll.ole32
except (ImportError, AttributeError, OSError):     # not Windows
    _ole32 = None
    HRESULT = None
    WinDLL = None


# --- COM plumbing ----------------------------------------------------

CLSCTX_ALL = 0x17
COINIT_APARTMENTTHREADED = 0x2
RPC_E_CHANGED_MODE = -2147417850           # 0x80010106
S_OK = 0
STGM_READ = 0
EDATAFLOW_CAPTURE = 1
DEVICE_STATE_ACTIVE = 0x1


class GUID(ctypes.Structure):
    """A COM interface / class identifier."""

    _fields_ = [('Data1', ctypes.c_uint32),
                ('Data2', ctypes.c_uint16),
                ('Data3', ctypes.c_uint16),
                ('Data4', ctypes.c_ubyte * 8)]

    def __init__(self, text=None):
        """Build a GUID from its canonical brace-less string form.

        Args:
            text (str or None): e.g.
                ``'BCDE0395-E52F-467C-8E3D-C4579291692E'``. ``None``
                leaves the GUID zeroed.
        """
        super(GUID, self).__init__()
        if text is None:
            return
        parts = text.split('-')
        self.Data1 = int(parts[0], 16)
        self.Data2 = int(parts[1], 16)
        self.Data3 = int(parts[2], 16)
        tail = bytes.fromhex(parts[3] + parts[4])
        for i, value in enumerate(tail):
            self.Data4[i] = value


CLSID_MMDeviceEnumerator = 'BCDE0395-E52F-467C-8E3D-C4579291692E'
IID_IMMDeviceEnumerator = 'A95664D2-9614-4F35-A746-DE8DB63617E6'
IID_IAudioEndpointVolume = '5CDF2C82-841E-4546-9722-0CF74078229A'
# PKEY_Device_FriendlyName = {a45c254e-df1c-4efd-8020-67d146a850e0}, 14
PKEY_FRIENDLY_NAME_FMTID = 'A45C254E-DF1C-4EFD-8020-67D146A850E0'
PKEY_FRIENDLY_NAME_PID = 14


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [('fmtid', GUID), ('pid', ctypes.c_ulong)]


class PROPVARIANT(ctypes.Structure):
    # Only the pointer arm is read (friendly name is VT_LPWSTR), so the
    # union is modelled as its largest fixed layout rather than in full.
    _fields_ = [('vt', ctypes.c_ushort),
                ('wReserved1', ctypes.c_ushort),
                ('wReserved2', ctypes.c_ushort),
                ('wReserved3', ctypes.c_ushort),
                ('data', ctypes.c_void_p),
                ('data2', ctypes.c_void_p)]


def _vtable_call(ptr, index, restype, *argtypes):
    """Bind method ``index`` of a COM object's vtable as a callable.

    Args:
        ptr (ctypes.c_void_p): The interface pointer.
        index (int): Zero-based vtable slot. Slots 0-2 are always
            ``IUnknown``'s QueryInterface / AddRef / Release, so
            interface methods start at 3.
        restype: ctypes return type for the bound function.
        *argtypes: ctypes argument types, excluding the implicit
            ``this`` pointer, which is prepended here.

    Returns a callable taking the method's arguments without ``this``.
    """
    vtable = ctypes.cast(ptr, POINTER(c_void_p))[0]
    slot = ctypes.cast(vtable, POINTER(c_void_p))[index]
    proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    func = proto(slot)
    return lambda *args: func(ptr, *args)


def _release(ptr):
    """Release a COM interface pointer, tolerating ``None``."""
    if ptr:
        try:
            _vtable_call(ptr, 2, ctypes.c_ulong)()
        except Exception:
            pass


def available():
    """True when Windows Core Audio can be reached from this process.

    False on every non-Windows platform, and on Windows if ``ole32``
    or the MMDevice enumerator cannot be created (a session with no
    audio service, most likely). Mirrors
    :func:`pydvma._coreaudio.available`, so callers can ask both and act
    on whichever answers.
    """
    if _ole32 is None:
        return False
    enumerator = _device_enumerator()
    if enumerator is None:
        return False
    _release(enumerator)
    return True


def _co_initialize():
    """Join a COM apartment for this thread; harmless if already in one."""
    if _ole32 is None:
        return
    try:
        _ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    except OSError as exc:
        # Already initialised with a different model: fine, we only
        # need SOME apartment.
        if getattr(exc, 'winerror', None) != RPC_E_CHANGED_MODE:
            pass


def _device_enumerator():
    """Create an ``IMMDeviceEnumerator``, or ``None``."""
    if _ole32 is None:
        return None
    _co_initialize()
    ptr = c_void_p()
    try:
        _ole32.CoCreateInstance(byref(GUID(CLSID_MMDeviceEnumerator)), None,
                                CLSCTX_ALL,
                                byref(GUID(IID_IMMDeviceEnumerator)),
                                byref(ptr))
    except Exception:
        return None
    return ptr if ptr else None


def _endpoint_friendly_name(device):
    """Friendly name of an ``IMMDevice``, or ``None``."""
    store = c_void_p()
    try:
        if _vtable_call(device, 4, HRESULT, ctypes.c_ulong,
                        POINTER(c_void_p))(STGM_READ, byref(store)) != S_OK:
            return None
    except Exception:
        return None
    try:
        key = PROPERTYKEY()
        key.fmtid = GUID(PKEY_FRIENDLY_NAME_FMTID)
        key.pid = PKEY_FRIENDLY_NAME_PID
        value = PROPVARIANT()
        if _vtable_call(store, 5, HRESULT, POINTER(PROPERTYKEY),
                        POINTER(PROPVARIANT))(byref(key), byref(value)) != S_OK:
            return None
        if not value.data:
            return None
        return ctypes.cast(value.data, c_wchar_p).value
    except Exception:
        return None
    finally:
        _release(store)


def capture_endpoint_names():
    """Friendly names of every ACTIVE capture endpoint, or ``[]``.

    Useful on its own for diagnosing the gap between what PortAudio
    calls a device and what the Windows endpoint is called — MME
    truncates names to 31 characters, and WDM-KS invents its own
    entirely.
    """
    names = []
    for _index, device, name in _iter_capture_endpoints():
        if name:
            names.append(name)
        _release(device)
    return names


def _iter_capture_endpoints():
    """Yield ``(index, IMMDevice, friendly_name)`` for active captures.

    The caller owns each device pointer and must ``_release`` it.
    """
    enumerator = _device_enumerator()
    if enumerator is None:
        return
    collection = c_void_p()
    try:
        if _vtable_call(enumerator, 3, HRESULT, ctypes.c_int, ctypes.c_ulong,
                        POINTER(c_void_p))(
                            EDATAFLOW_CAPTURE, DEVICE_STATE_ACTIVE,
                            byref(collection)) != S_OK:
            return
    except Exception:
        return
    finally:
        _release(enumerator)

    try:
        count = c_uint32()
        if _vtable_call(collection, 3, HRESULT,
                        POINTER(c_uint32))(byref(count)) != S_OK:
            return
        for i in range(count.value):
            device = c_void_p()
            if _vtable_call(collection, 4, HRESULT, ctypes.c_uint32,
                            POINTER(c_void_p))(i, byref(device)) != S_OK:
                continue
            yield i, device, _endpoint_friendly_name(device)
    finally:
        _release(collection)


def _names_match(portaudio_name, endpoint_name):
    """Do a PortAudio device name and an endpoint friendly name agree?

    Not a plain equality test, because PortAudio does not pass the name
    through unchanged: the MME host API truncates to 31 characters (an
    ESI U24 XL's S/PDIF input arrives as
    ``'SPDIF Interface (U24XL with SPD'``), and WDM-KS builds its own
    name from the kernel-streaming filter. Prefix matching in either
    direction covers truncation; anything more aggressive risks pinning
    the volume on the wrong endpoint, which is worse than not pinning.

    Args:
        portaudio_name (str or None): Name as PortAudio reports it.
        endpoint_name (str or None): Name as the MMDevice API reports it.
    """
    if not portaudio_name or not endpoint_name:
        return False
    a = str(portaudio_name).strip().lower()
    b = str(endpoint_name).strip().lower()
    return a == b or a.startswith(b) or b.startswith(a)


def find_device(name):
    """Locate the capture endpoint matching a PortAudio device name.

    Args:
        name (str or None): PortAudio device name, e.g.
            ``'Line (U24XL with SPDIF I/O)'``.

    Returns ``(endpoint_id, friendly_name)``, where ``endpoint_id`` is
    an opaque token to pass to the volume functions in this module, or
    ``(None, None)`` if there is no unambiguous match. Ambiguity is
    treated as no match: pinning the volume on the wrong endpoint would
    silently rescale a different device's captures.
    """
    if not name or not available():
        return None, None
    hits = []
    for index, device, endpoint_name in _iter_capture_endpoints():
        if _names_match(name, endpoint_name):
            hits.append((index, endpoint_name))
        _release(device)
    if len(hits) != 1:
        return None, None
    return hits[0][0], hits[0][1]


def _endpoint_volume(endpoint_id):
    """Activate ``IAudioEndpointVolume`` on an endpoint index, or ``None``."""
    for index, device, _name in _iter_capture_endpoints():
        if index != endpoint_id:
            _release(device)
            continue
        try:
            ptr = c_void_p()
            hr = _vtable_call(device, 3, HRESULT, POINTER(GUID),
                              ctypes.c_ulong, c_void_p, POINTER(c_void_p))(
                                  byref(GUID(IID_IAudioEndpointVolume)),
                                  CLSCTX_ALL, None, byref(ptr))
            return ptr if hr == S_OK and ptr else None
        except Exception:
            return None
        finally:
            _release(device)
    return None


def volume_range_db(endpoint_id):
    """Hardware volume range of an endpoint, or ``None``.

    Returns ``(min_db, max_db, step_db)``, e.g. ``(-40.0, 12.0, 0.5)``
    on an ESI U24 XL, or ``None`` when the endpoint has no volume
    control. Reported for diagnostics — a range whose maximum is above
    0 dB is a warning sign, because it means the slider can BOOST and
    therefore clip.
    """
    vol = _endpoint_volume(endpoint_id)
    if vol is None:
        return None
    try:
        lo, hi, step = c_float(), c_float(), c_float()
        if _vtable_call(vol, 20, HRESULT, POINTER(c_float), POINTER(c_float),
                        POINTER(c_float))(byref(lo), byref(hi),
                                          byref(step)) != S_OK:
            return None
        return float(lo.value), float(hi.value), float(step.value)
    except Exception:
        return None
    finally:
        _release(vol)


def input_volume_db(endpoint_id):
    """Per-channel input volume of an endpoint, in dB.

    Returns ``{channel_index: db}`` — mirroring
    :func:`pydvma._coreaudio.input_volume_db`, whose per-ELEMENT dict
    exists for the same reason: the channels can hold different values
    (seen on a U24 XL mid-bench), so restoring one value across all of
    them would not be a restore. Returns ``{}`` when the endpoint has no
    volume control or cannot be read.
    """
    vol = _endpoint_volume(endpoint_id)
    if vol is None:
        return {}
    try:
        count = c_uint32()
        if _vtable_call(vol, 5, HRESULT,
                        POINTER(c_uint32))(byref(count)) != S_OK:
            return {}
        out = {}
        for ch in range(count.value):
            db = c_float()
            if _vtable_call(vol, 12, HRESULT, ctypes.c_uint32,
                            POINTER(c_float))(ch, byref(db)) == S_OK:
                out[ch] = float(db.value)
        return out
    except Exception:
        return {}
    finally:
        _release(vol)


def set_input_volume_db(endpoint_id, db, tolerance=0.25, channels=None):
    """Set input-volume channels to ``db``; True once readback agrees.

    Used to pin the control at 0 dB (unity) so a capture's scale matches
    the device's published full-scale input level. Unlike the CoreAudio
    path — where the dB property silently refuses writes and the scalar
    has to be bisected — ``SetChannelVolumeLevel`` takes dB directly on
    Windows and was measured to land exactly (0, ±6, ±12, −20, −40 dB
    all set first time on a U24 XL, 2026-08-12). The readback check is
    kept anyway, because a driver that accepts and ignores a write is
    precisely the failure this function exists to catch.

    A channel already within ``tolerance`` is left untouched, so the
    common already-at-0 case makes no writes at all.

    Args:
        endpoint_id: Token from :func:`find_device`.
        db (float): Target level in dB.
        tolerance (float): Accepted readback error in dB (default 0.25).
        channels (dict or None): Restore mapping ``{channel: db}`` to
            write per-channel values instead of one level everywhere;
            ``db`` is ignored when this is given. Default ``None`` sets
            every channel to ``db``.

    Returns False when the endpoint has no volume control, when Core
    Audio is unavailable, or when any channel cannot be brought within
    ``tolerance``.
    """
    vol = _endpoint_volume(endpoint_id)
    if vol is None:
        return False
    try:
        count = c_uint32()
        if _vtable_call(vol, 5, HRESULT,
                        POINTER(c_uint32))(byref(count)) != S_OK:
            return False
        if channels is None:
            targets = {ch: float(db) for ch in range(count.value)}
        else:
            targets = {int(ch): float(v) for ch, v in channels.items()}
        if not targets:
            return False

        read = _vtable_call(vol, 12, HRESULT, ctypes.c_uint32,
                            POINTER(c_float))
        write = _vtable_call(vol, 10, HRESULT, ctypes.c_uint32, c_float,
                             POINTER(GUID))

        for ch, target in targets.items():
            if ch >= count.value:
                return False
            current = c_float()
            if read(ch, byref(current)) != S_OK:
                return False
            if abs(current.value - target) <= tolerance:
                continue
            if write(ch, c_float(target), None) != S_OK:
                return False
            if read(ch, byref(current)) != S_OK:
                return False
            if abs(current.value - target) > tolerance:
                return False
        return True
    except Exception:
        return False
    finally:
        _release(vol)
