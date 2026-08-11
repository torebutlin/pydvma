"""Headless hardware check for the ESI U24 XL (macOS).

Run this after any change to the soundcard acquisition path, alongside
``dev/scarlett_hw_check.py``::

    python dev/u24xl_hw_check.py

WIRING (unlike the Scarlett check, this one needs a cable): the Mac's
3.5 mm jack output feeds the U24 XL's L+R line inputs. The Mac jack
auto-detects a line-level load and runs a 1.0 V rms full-scale output
(measured 2026-08-11 against the U24 XL's published +4.7 dBu input spec,
agreement 0.07 dB — see ``dev/2026-08-11-u24xl-bench.md``), which makes
it a usable reference source for an absolute-scale check.

What it proves, beyond the generic capture path:

1. the profile resolves and is FIXED-GAIN, so ``MySettings`` derives
   ``VmaxSC`` (1.88 V peak) with no stated gain;
2. the capture bit depth is pinned: macOS parks this device at 16-bit
   (and resets it on every rate change), the Recorder raises it to
   24-bit for the stream and puts it back after;
3. the input volume control — a purely DIGITAL -40..+12 dB gain — is
   pinned to 0 dB for the stream and restored after, so a stray
   Settings-app slider cannot silently rescale a capture;
4. a capture through the full pydvma path lands at the ABSOLUTE voltage
   the jack drove into it, with the volume deliberately mis-set first
   (the pin must protect the scale);
5. the low end of the native ladder is real: at fs = 8 kHz the
   anti-alias filter tracks the rate (out-of-band tone rejected, not
   folded), which the 2i2 cannot do at all — its ladder stops at
   44.1 kHz.
"""

import sys
import time

import numpy as np

try:
    import sounddevice as sd
except Exception as exc:                      # pragma: no cover - dev harness
    sys.exit('sounddevice unavailable: %s' % exc)

from pydvma import _coreaudio, _soundcard_specs, acquisition, options, streams

if not _coreaudio.available():
    sys.exit('CoreAudio unavailable — this check is macOS-only.')


DEVICE_MATCH = 'U24XL'
OUTPUT_MATCH = 'External Headphones'   # the Mac jack driving the U24 XL
TONE_AMPLITUDE = 0.1                   # digital peak; modest in case the
                                       # jack is feeding headphones, not
                                       # the U24 XL

PASS, FAIL = '  PASS', '  FAIL'
_results = []


def check(name, ok, detail=''):
    _results.append((name, bool(ok)))
    print('%s  %s%s' % (PASS if ok else FAIL, name,
                        ('  [%s]' % detail) if detail else ''))
    return ok


def find_input_device():
    index = None
    for i, dev in enumerate(sd.query_devices()):
        if DEVICE_MATCH.lower() in dev['name'].lower() and dev['max_input_channels']:
            index = i
            break
    if index is None:
        sys.exit('No input device matching %r found.' % DEVICE_MATCH)
    name = sd.query_devices()[index]['name']
    device_id, _ = _coreaudio.find_device(name)
    if device_id is None:
        sys.exit('%r is not visible through CoreAudio.' % name)
    return index, name, device_id


def find_output_device():
    for i, dev in enumerate(sd.query_devices()):
        if OUTPUT_MATCH.lower() in dev['name'].lower() and dev['max_output_channels']:
            return i, dev['name']
    return None, None


class _JackVolume:
    """Pin the Mac jack's output volume at 0 dB (its calibrated maximum).

    Apple's devices accept a direct write of the dB property (unlike the
    U24 XL's input control); the previous value is restored on exit so
    the user's volume setting survives the harness.
    """

    def __init__(self, name):
        import ctypes
        self._ctypes = ctypes
        self.device_id, _ = _coreaudio.find_device(name)
        self._addr = _coreaudio.AudioObjectPropertyAddress(
            _coreaudio.kAudioDevicePropertyVolumeDecibels,
            _coreaudio._fourcc('outp'), 0)
        self.previous = self._read()

    def _read(self):
        return _coreaudio._get_scalar(self.device_id, self._addr,
                                      self._ctypes.c_float)

    def _write(self, db):
        _coreaudio._set_scalar(self.device_id, self._addr,
                               self._ctypes.c_float(float(db)))
        time.sleep(0.1)

    def __enter__(self):
        self._write(0.0)
        return self

    def __exit__(self, *exc):
        if self.previous is not None:
            self._write(self.previous)


class ToneOut:
    """Play a continuous sine on the Mac jack at the jack's own rate."""

    def __init__(self, index, freq, amplitude=TONE_AMPLITUDE):
        fs = float(sd.query_devices()[index]['default_samplerate'] or 48000)
        n = int(fs)
        cycles = max(1, round(freq * n / fs))
        self.freq = cycles * fs / n
        t = np.arange(n) / fs
        tone = (amplitude * np.sin(2 * np.pi * self.freq * t)).astype('float32')
        self._sig = np.stack([tone, tone], axis=1)
        self._pos = 0

        def cb(outdata, frames, _time, _status):
            idx = (np.arange(self._pos, self._pos + frames)) % n
            outdata[:] = self._sig[idx]
            self._pos += frames

        self.stream = sd.OutputStream(samplerate=fs, device=index, channels=2,
                                      dtype='float32', callback=cb)

    def __enter__(self):
        self.stream.start()
        time.sleep(0.4)   # let the level settle before anyone captures
        return self

    def __exit__(self, *exc):
        self.stream.stop()
        self.stream.close()


def amplitude_at(signal, fs, freq):
    """Peak amplitude near ``freq``, in the same units as the signal."""
    x = np.asarray(signal, dtype=float)
    x = x - x.mean()
    window = np.hanning(len(x))
    spectrum = np.abs(np.fft.rfft(x * window)) / (np.sum(window) / 2)
    axis = np.fft.rfftfreq(len(x), 1 / fs)
    i = int(np.argmin(np.abs(axis - freq)))
    lo, hi = max(0, i - 3), min(len(spectrum), i + 4)
    return float(spectrum[lo:hi].max())


def log(index, fs, seconds, **kwargs):
    """Capture through pydvma's own acquisition path."""
    settings = options.MySettings(device_driver='soundcard', device_index=index,
                                  channels=2, fs=fs, chunk_size=1024,
                                  stored_time=seconds, **kwargs)
    dataset = acquisition.log_data(settings)
    return dataset.time_data_list[0], settings


def main():
    index, name, device_id = find_input_device()
    out_index, out_name = find_output_device()
    print('Capture: %s  (portaudio index %d, coreaudio id %d)' %
          (name, index, device_id))
    print('Source : %s\n' % (out_name or 'NONE — jack checks will skip'))

    original_rate = _coreaudio.get_nominal_rate(device_id)
    original_bits = _coreaudio.input_bit_depth(device_id)
    original_vol = _coreaudio.input_volume_db(device_id)

    ladder = _coreaudio.native_rates(device_id)
    print('Native rate ladder: %s' % ', '.join('%g' % r for r in ladder))
    print('Clock on entry: %g Hz, %s-bit, input volume %s\n' %
          (original_rate, original_bits, original_vol))

    try:
        # -- 1: profile and fixed-gain derivation ---------------------
        profile = _soundcard_specs.device_profile(name)
        check('profile resolves', profile is not None
              and profile['label'] == 'ESI U24 XL')
        check('profile is fixed-gain', _soundcard_specs.fixed_gain(name))
        expected_fs_volts = _soundcard_specs.full_scale_volts(name, 0.0)
        settings = options.MySettings(device_driver='soundcard',
                                      device_index=index, channels=2,
                                      fs=48000)
        check('VmaxSC derived with no stated gain',
              abs(settings.VmaxSC - expected_fs_volts) < 1e-9,
              'VmaxSC = %.4f V peak' % settings.VmaxSC)

        # -- 2: the native ladder reaches genuinely low rates ---------
        check('48 kHz is native', any(abs(r - 48000) < 1e-6 for r in ladder))
        check('a low rate (<= 16 kHz) is native',
              bool(ladder) and min(ladder) <= 16000,
              'floor %g Hz' % (min(ladder) if ladder else float('nan')))

        # -- 3 & 4: bit-depth and volume pinning on a live stream -----
        _coreaudio.set_input_bit_depth(device_id, 16)
        _coreaudio.set_input_volume_db(device_id, -6.0)
        rec = streams.Recorder(settings)
        rec.init_stream(settings)
        time.sleep(0.3)
        check('16-bit stream is raised to 24-bit',
              _coreaudio.input_bit_depth(device_id) == 24)
        vol = _coreaudio.input_volume_db(device_id)
        check('digital input volume is pinned to 0 dB',
              vol and all(abs(v) <= 0.25 for v in vol.values()),
              'during: %s' % vol)
        rec.end_stream()
        time.sleep(0.3)
        check('bit depth is restored after the stream',
              _coreaudio.input_bit_depth(device_id) == 16)
        vol = _coreaudio.input_volume_db(device_id)
        check('input volume is restored after the stream',
              vol and all(abs(v + 6.0) <= 0.5 for v in vol.values()),
              'after: %s' % vol)

        if out_index is not None:
            # -- 5: absolute scale through the full path --------------
            # Jack at 0 dB plays TONE_AMPLITUDE digital peak; in its
            # line-level mode that is TONE_AMPLITUDE * sqrt(2) volts
            # peak at the U24 XL's pins. The input volume is left
            # mis-set at -6 dB on purpose: the Recorder's pin must
            # protect the scale without help.
            expected_vpk = TONE_AMPLITUDE * np.sqrt(2.0)
            with _JackVolume(out_name), ToneOut(out_index, 1000.0) as tone:
                data, _ = log(index, 48000, 2.0)
                measured = amplitude_at(data.time_data[:, 0], 48000, tone.freq)
                err_db = 20 * np.log10(measured / expected_vpk)
                check('capture is ABSOLUTE volts through the jack reference',
                      abs(err_db) < 0.5,
                      '%.4f V vs %.4f V expected (%+.2f dB)'
                      % (measured, expected_vpk, err_db))

                # -- 6: fs = 8 kHz is a real hardware rate ------------
                data8, s8 = log(index, 8000, 2.0)
                inband = amplitude_at(data8.time_data[:, 0], 8000, tone.freq)
                check('1 kHz tone survives an 8 kHz native capture',
                      inband > 0.5 * expected_vpk,
                      '%.4f V' % inband)
            with _JackVolume(out_name), ToneOut(out_index, 5000.0) as tone:
                data8, _ = log(index, 8000, 2.0)
                folded = amplitude_at(data8.time_data[:, 0], 8000, 3000.0)
                rejection_db = 20 * np.log10(
                    (TONE_AMPLITUDE * np.sqrt(2)) / max(folded, 1e-12))
                check('5 kHz is rejected at fs 8 kHz, not folded to 3 kHz',
                      rejection_db > 40.0, '%.1f dB down' % rejection_db)
        else:
            print('  SKIP  jack-reference checks (no %r output found)'
                  % OUTPUT_MATCH)

    finally:
        # leave the device exactly as found
        try:
            if original_bits is not None:
                _coreaudio.set_input_bit_depth(device_id, original_bits)
            for element, value in (original_vol or {}).items():
                _coreaudio.set_input_volume_db(device_id, value,
                                               elements=[element])
            if original_rate is not None:
                _coreaudio.set_nominal_rate(device_id, original_rate)
        except Exception:
            pass

    check('clock is back where it started',
          _coreaudio.get_nominal_rate(device_id) == original_rate)

    passed = sum(ok for _, ok in _results)
    print('\n%d/%d checks passed' % (passed, len(_results)))
    return 0 if passed == len(_results) else 1


if __name__ == '__main__':
    sys.exit(main())
