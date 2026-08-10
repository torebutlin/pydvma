"""Prototype: read/set the CoreAudio hardware nominal sample rate from pure Python.

Proves pydvma can pin a macOS audio device's true hardware clock (rather than
letting CoreAudio silently sample-rate-convert) with no extra dependency.
"""
import ctypes
import ctypes.util
import struct

_ca = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))

kAudioObjectSystemObject = 1
kAudioObjectPropertyElementMain = 0


def _fourcc(s):
    return struct.unpack(">I", s.encode("ascii"))[0]


kAudioHardwarePropertyDevices = _fourcc("dev#")
kAudioObjectPropertyName = _fourcc("lnam")
kAudioDevicePropertyNominalSampleRate = _fourcc("nsrt")
kAudioDevicePropertyAvailableNominalSampleRates = _fourcc("nsr#")
kAudioDevicePropertyStreamConfiguration = _fourcc("slay")
kAudioObjectPropertyScopeGlobal = _fourcc("glob")
kAudioObjectPropertyScopeInput = _fourcc("inpt")


class AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [("mSelector", ctypes.c_uint32),
                ("mScope", ctypes.c_uint32),
                ("mElement", ctypes.c_uint32)]


class AudioValueRange(ctypes.Structure):
    _fields_ = [("mMinimum", ctypes.c_double), ("mMaximum", ctypes.c_double)]


def _addr(sel, scope=kAudioObjectPropertyScopeGlobal):
    return AudioObjectPropertyAddress(sel, scope, kAudioObjectPropertyElementMain)


def _get(obj, addr, ctype, count=None):
    size = ctypes.c_uint32(0)
    st = _ca.AudioObjectGetPropertyDataSize(
        ctypes.c_uint32(obj), ctypes.byref(addr), 0, None, ctypes.byref(size))
    if st != 0:
        raise OSError(f"AudioObjectGetPropertyDataSize failed: {st}")
    n = size.value // ctypes.sizeof(ctype)
    buf = (ctype * n)()
    st = _ca.AudioObjectGetPropertyData(
        ctypes.c_uint32(obj), ctypes.byref(addr), 0, None,
        ctypes.byref(size), ctypes.byref(buf))
    if st != 0:
        raise OSError(f"AudioObjectGetPropertyData failed: {st}")
    return list(buf)


def device_ids():
    return _get(kAudioObjectSystemObject, _addr(kAudioHardwarePropertyDevices),
                ctypes.c_uint32)


def device_name(dev):
    addr = _addr(kAudioObjectPropertyName)
    cf = ctypes.c_void_p()
    size = ctypes.c_uint32(ctypes.sizeof(cf))
    st = _ca.AudioObjectGetPropertyData(
        ctypes.c_uint32(dev), ctypes.byref(addr), 0, None,
        ctypes.byref(size), ctypes.byref(cf))
    if st != 0 or not cf:
        return None
    cf_lib = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
    cf_lib.CFStringGetCStringPtr.restype = ctypes.c_char_p
    ptr = cf_lib.CFStringGetCStringPtr(cf, 0x08000100)  # kCFStringEncodingUTF8
    if ptr:
        return ptr.decode("utf-8")
    buf = ctypes.create_string_buffer(256)
    if cf_lib.CFStringGetCString(cf, buf, 256, 0x08000100):
        return buf.value.decode("utf-8")
    return None


def find_device(substr):
    for d in device_ids():
        nm = device_name(d)
        if nm and substr.lower() in nm.lower():
            return d, nm
    return None, None


def available_rates(dev):
    rs = _get(dev, _addr(kAudioDevicePropertyAvailableNominalSampleRates),
              AudioValueRange)
    out = []
    for r in rs:
        if r.mMinimum == r.mMaximum:
            out.append(r.mMinimum)
        else:
            out.append((r.mMinimum, r.mMaximum))
    return out


def get_rate(dev):
    addr = _addr(kAudioDevicePropertyNominalSampleRate)
    val = ctypes.c_double(0)
    size = ctypes.c_uint32(ctypes.sizeof(val))
    st = _ca.AudioObjectGetPropertyData(
        ctypes.c_uint32(dev), ctypes.byref(addr), 0, None,
        ctypes.byref(size), ctypes.byref(val))
    if st != 0:
        raise OSError(f"get nominal rate failed: {st}")
    return val.value


def set_rate(dev, rate, timeout=3.0):
    import time
    addr = _addr(kAudioDevicePropertyNominalSampleRate)
    val = ctypes.c_double(float(rate))
    st = _ca.AudioObjectSetPropertyData(
        ctypes.c_uint32(dev), ctypes.byref(addr), 0, None,
        ctypes.c_uint32(ctypes.sizeof(val)), ctypes.byref(val))
    if st != 0:
        raise OSError(f"set nominal rate failed: {st}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if abs(get_rate(dev) - float(rate)) < 1e-6:
            return True
        time.sleep(0.05)
    return False


if __name__ == "__main__":
    dev, nm = find_device("Scarlett")
    print("device:", nm, "id", dev)
    print("available rates:", available_rates(dev))
    print("current rate:", get_rate(dev))
    for target in (44100, 48000, 192000):
        ok = set_rate(dev, target)
        print(f"  set {target}: {'OK' if ok else 'TIMED OUT'} -> now {get_rate(dev)}")
