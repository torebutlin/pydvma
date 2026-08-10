"""Headless hardware check for a Focusrite Scarlett (or any CoreAudio device).

Run this on macOS after any change to the soundcard acquisition path, the
same way ``dev/bridge_hw_check.py`` is run after an NI change::

    python dev/scarlett_hw_check.py

It needs NO cable. The Scarlett 2i2 4th Gen presents inputs 3/4 as a
DIGITAL LOOPBACK of outputs 1/2 (user guide p44, verified
amplitude-exact), so a tone played to the outputs comes back on the
inputs and the whole capture path can be exercised on a bare desk.

What it proves:

1. the device's native rate ladder is queryable, and its clock is
   pinnable and restorable;
2. a capture at a native rate is bit-exact — no OS resampling;
3. asking for a rate the hardware CANNOT run (3 kHz) captures at a real
   rate and delivers the requested one;
4. the delivered data is genuinely anti-aliased — a tone above the
   target Nyquist is rejected, rather than folded back into the band as
   the OS resampler does.

Test 4 is the one that matters. It is the difference between a
measurement and a plausible-looking picture.
"""

import sys
import time

import numpy as np

try:
    import sounddevice as sd
except Exception as exc:                      # pragma: no cover - dev harness
    sys.exit('sounddevice unavailable: %s' % exc)

from pydvma import _coreaudio, acquisition, options, streams


DEVICE_MATCH = 'Scarlett'
LOOPBACK_CHANNEL = 3          # 1-based input channel carrying Loopback 1
TONE_AMPLITUDE = 0.05         # kept low: the outputs may feed monitors

PASS, FAIL = '  PASS', '  FAIL'
_results = []


def check(name, ok, detail=''):
    _results.append((name, bool(ok)))
    print('%s  %s%s' % (PASS if ok else FAIL, name,
                        ('  [%s]' % detail) if detail else ''))
    return ok


def find_device():
    """Locate the interface in both PortAudio and CoreAudio."""
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


class ToneOut:
    """Play a continuous sine to outputs 1/2 at the device's own clock rate.

    Generating at the hardware rate matters: a tone synthesised inside a
    low-rate stream is already aliased before it reaches the device, which
    would make the anti-aliasing test below silently meaningless.
    """

    def __init__(self, index, fs, freq):
        self.phase = 0.0
        self.fs = float(fs)
        self.freq = float(freq)
        self.stream = sd.OutputStream(device=index, samplerate=self.fs,
                                      channels=2, dtype='float32',
                                      callback=self._cb)

    def _cb(self, outdata, frames, timeinfo, status):
        n = np.arange(frames)
        phase = self.phase + 2 * np.pi * self.freq * n / self.fs
        outdata[:, 0] = (TONE_AMPLITUDE * np.sin(phase)).astype('float32')
        outdata[:, 1] = 0.0
        self.phase = (phase[-1] + 2 * np.pi * self.freq / self.fs) % (2 * np.pi)

    def __enter__(self):
        self.stream.start()
        time.sleep(0.4)
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


def log(index, fs, seconds, channels=4, **kwargs):
    """Capture through pydvma's own acquisition path."""
    settings = options.MySettings(device_driver='soundcard', device_index=index,
                                  channels=channels, fs=fs, chunk_size=1024,
                                  stored_time=seconds, **kwargs)
    dataset = acquisition.log_data(settings)
    return dataset.time_data_list[0]


def main():
    index, name, device_id = find_device()
    print('Device: %s  (portaudio index %d, coreaudio id %d)\n' % (name, index, device_id))

    original = _coreaudio.get_nominal_rate(device_id)
    ladder = _coreaudio.native_rates(device_id)
    print('Native rate ladder: %s' % ', '.join('%g' % r for r in ladder))
    print('Clock on entry: %g Hz\n' % original)

    try:
        # --- 1. capability + clock control -------------------------------
        check('native rate ladder is published', len(ladder) >= 2,
              '%d rates' % len(ladder))

        settings = options.MySettings(device_driver='soundcard',
                                      device_index=index, channels=2, fs=44100)
        check('native_input_rates matches CoreAudio',
              streams.native_input_rates(settings) == ladder)

        lowest = ladder[0]
        with _coreaudio.pinned_rate(device_id, lowest) as ok:
            during = _coreaudio.get_nominal_rate(device_id)
            check('clock pins to %g Hz' % lowest, ok and during == lowest,
                  'clock read back as %g Hz' % during)
        check('clock is restored afterwards',
              _coreaudio.get_nominal_rate(device_id) == original,
              '%g Hz' % _coreaudio.get_nominal_rate(device_id))

        # A note on method: the tone stream below is opened at the rate
        # the CAPTURE will run at, with the clock already pinned there.
        # The device has ONE clock, so an output stream left running at a
        # different rate while that clock moves takes both streams down
        # (PaMacCore -50, then silence) — an interaction worth knowing
        # about in its own right, but not what these checks are measuring.
        _coreaudio.set_nominal_rate(device_id, lowest)

        # --- 2. a capture at a native rate is exact ----------------------
        tone_hz = 1000.0
        with ToneOut(index, lowest, tone_hz):
            td = log(index, int(lowest), 1.5)
        level = amplitude_at(td.time_data[:, LOOPBACK_CHANNEL - 1],
                             td.settings.fs, tone_hz)
        err_db = 20 * np.log10(max(level, 1e-12) / TONE_AMPLITUDE)
        check('capture at a native rate is amplitude-exact',
              abs(err_db) < 0.5, '%.2f dB error' % err_db)
        check('capture ran at the requested native rate',
              td.settings.fs == int(lowest), 'fs = %s' % td.settings.fs)

        # --- 3. an unrunnable rate is captured properly and delivered ----
        target_fs = 3000
        with ToneOut(index, lowest, 500.0):
            td = log(index, target_fs, 1.5)
        check('unrunnable fs is delivered as asked',
              td.settings.fs == target_fs, 'fs = %s' % td.settings.fs)
        check('capture rate recorded for provenance',
              getattr(td.settings, 'lpf_capture_fs', None) in ladder,
              'lpf_capture_fs = %s' % getattr(td.settings, 'lpf_capture_fs', None))
        in_band = amplitude_at(td.time_data[:, LOOPBACK_CHANNEL - 1],
                               td.settings.fs, 500.0)
        in_db = 20 * np.log10(max(in_band, 1e-12) / TONE_AMPLITUDE)
        check('in-band content survives the decimation',
              abs(in_db) < 1.0, '%.2f dB error at 500 Hz' % in_db)

        # --- 4. the delivered data is genuinely anti-aliased -------------
        # 5 kHz is far above the 1500 Hz Nyquist of a 3 kHz record, and
        # genuine at the 44.1 kHz capture rate. Naive decimation folds it
        # to 1000 Hz; the OS resampler was measured passing it at
        # -11.7 dB. Guard against a false pass by proving the tone is
        # really there in a full-rate capture first.
        with ToneOut(index, lowest, 5000.0):
            witness = log(index, int(lowest), 1.0)
            td = log(index, target_fs, 1.5)
        present = amplitude_at(witness.time_data[:, LOOPBACK_CHANNEL - 1],
                               witness.settings.fs, 5000.0)
        check('the 5 kHz probe tone is actually present at full rate',
              20 * np.log10(max(present, 1e-12) / TONE_AMPLITUDE) > -1.0,
              '%.2f dB' % (20 * np.log10(max(present, 1e-12) / TONE_AMPLITUDE)))
        fold = abs(((5000.0 + target_fs / 2) % target_fs) - target_fs / 2)
        alias = amplitude_at(td.time_data[:, LOOPBACK_CHANNEL - 1],
                             td.settings.fs, fold)
        alias_db = 20 * np.log10(max(alias, 1e-12) / TONE_AMPLITUDE)
        check('out-of-band tone is rejected, not folded in',
              alias_db < -60,
              '5000 Hz would fold to %g Hz; measured %.1f dB' % (fold, alias_db))

        # --- 5. stimulus survives the shared clock -----------------------
        # The device has ONE clock, so a stimulus generated at a target fs
        # the hardware cannot run must be moved onto the capture rate. If
        # that resampling is wrong the tone comes back scaled by
        # capture_fs/target_fs (200 Hz -> 2940 Hz here), which is exactly
        # the failure this guards.
        tone_hz = 200.0
        t = np.arange(0, 1.5, 1.0 / target_fs)
        wave = (TONE_AMPLITUDE * np.sin(2 * np.pi * tone_hz * t)).reshape(-1, 1)
        settings = options.MySettings(device_driver='soundcard',
                                      device_index=index, channels=4,
                                      fs=target_fs, chunk_size=1024,
                                      stored_time=1.2, output_fs=target_fs,
                                      output_device_index=index,
                                      output_channels=1)
        td = acquisition.log_data(settings, output=wave).time_data_list[0]
        played = td.time_data[:, LOOPBACK_CHANNEL - 1]
        got = amplitude_at(played, td.settings.fs, tone_hz)
        wrong = amplitude_at(played, td.settings.fs,
                             abs(((tone_hz * ladder[0] / target_fs
                                   + target_fs / 2) % target_fs) - target_fs / 2))
        check('stimulus plays at the right frequency on a shared clock',
              got > 4 * max(wrong, 1e-12),
              '%.1f dB at %g Hz vs %.1f dB at the mis-scaled frequency'
              % (20 * np.log10(max(got, 1e-12) / TONE_AMPLITUDE), tone_hz,
                 20 * np.log10(max(wrong, 1e-12) / TONE_AMPLITUDE)))

    finally:
        if original is not None:
            _coreaudio.set_nominal_rate(device_id, original)
            print('\nClock restored to %g Hz' % _coreaudio.get_nominal_rate(device_id))

    passed = sum(1 for _, ok in _results if ok)
    print('\n%d/%d checks passed' % (passed, len(_results)))
    return 0 if passed == len(_results) else 1


if __name__ == '__main__':
    sys.exit(main())
