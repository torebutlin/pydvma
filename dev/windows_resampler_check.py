"""Measure how Windows treats a capture-rate request the hardware can't run.

The Windows counterpart of the CoreAudio investigation in
``dev/plans/2026-08-10-focusrite-scarlett-design.md`` (whose measured
answer lives in that doc's §6). Two questions, per host API:

1. **Does the API lie?** ``sd.check_input_settings`` per rate: WASAPI
   and WDM-KS accept ONLY the endpoint mix rate; MME and DirectSound
   accept everything and resample via the Windows mixer.
2. **Does it matter?** With an EXTERNAL tone of known frequency and
   level wired into input 1, capture at a rate whose Nyquist sits
   below the tone and look for it folded in-band, plus a passband
   droop reading just under Nyquist.

First run (2026-08-11, 2i2 4th Gen, Rigol 1 kHz 5 Vpp on input 1 at
9 dB Line gain): the Windows mixer resampler is measurement-grade —
fold rejection ~ -100 dB (at the noise floor), droop -0.30 dB at
0.91x Nyquist — so, unlike macOS, the ``'unknown'`` capture-rate path
does not corrupt data here. Full numbers in the design doc §6.

Method rules learned the hard way:

- **The probe tone must sit well clear of the external tone** (> ~10
  bins): the peak search spans +/-3 bins and a Hann mainlobe is +/-2
  bins wide, so a probe 3 Hz from the Rigol's 1 kHz read the Rigol's
  own skirt and "measured" a tone that was never played.
- **Never capture channels=1 on a shared-mode endpoint**: Windows
  delivers the (ch1+ch2)/2 MONO DOWNMIX, which silently halves a
  single-input signal (-6.02 dB). Capture >= 2 channels and index.

Assumes an external generator on input 1 (TONE_HZ / TONE_VPP below);
edit the constants to match the bench. Run:

    python dev/windows_resampler_check.py
"""

import sys

import numpy as np

try:
    import sounddevice as sd
except Exception as exc:                       # pragma: no cover - dev harness
    sys.exit('sounddevice unavailable: %s' % exc)

from pydvma import _soundcard_specs as specs


TONE_HZ = 1000.0        # external known source (Rigol) on input 1
TONE_VPP = 5.0
GAIN_DB = 9.0           # 2i2 front-panel gain, stated not read
INPUT_MODE = 'line'

PROBE_RATES = (1600, 3000, 8000, 22050, 44100, 48000, 88200, 96000,
               176400, 192000)
FOLD_FS = 1600          # Nyquist 800 < TONE_HZ: a bad resample folds 1 kHz
DROOP_FS = 2200         # 1 kHz = 0.91 x Nyquist: passband droop reading

PASS, FAIL = [], []


def check(name, ok, detail=''):
    (PASS if ok else FAIL).append(name)
    print(('  PASS  ' if ok else '  FAIL  ') + name
          + ('  [%s]' % detail if detail else ''))


def amp_at(x, fs, f):
    """Windowed peak amplitude near ``f`` (same units as the signal)."""
    x = np.asarray(x, float)
    x = x - x.mean()
    w = np.hanning(len(x))
    spec = np.abs(np.fft.rfft(x * w)) / (w.sum() / 2)
    ax = np.fft.rfftfreq(len(x), 1 / fs)
    i = int(np.argmin(np.abs(ax - f)))
    return float(spec[max(0, i - 3):i + 4].max())


def capture(dev, fs, seconds=2.0, channels=2):
    x = sd.rec(int(seconds * fs), samplerate=fs, channels=channels,
               device=dev, dtype='float32')
    sd.wait()
    return x


def find_endpoints():
    """Characterised input endpoints, one per host API: {api_name: index}."""
    devices = sd.query_devices()
    names = [d['name'] for d in devices]
    apis = sd.query_hostapis()
    found = {}
    for i, d in enumerate(devices):
        if d['max_input_channels'] < 1:
            continue
        if specs.device_profile(d['name'], neighbours=names) is None:
            continue
        api = apis[d['hostapi']]['name']
        found.setdefault(api, i)
    return found


def main():
    endpoints = find_endpoints()
    if not endpoints:
        sys.exit('No characterised interface found — is the 2i2 plugged in?')
    for api, idx in endpoints.items():
        print('%s: index %d  %r' % (api, idx, sd.query_devices(idx)['name']))
    print()

    # --- 1. what each host API claims -----------------------------------
    for api, idx in endpoints.items():
        accepted = []
        for r in PROBE_RATES:
            try:
                sd.check_input_settings(device=idx, samplerate=r, channels=1)
                accepted.append(r)
            except Exception:
                pass
        print('%s accepts: %s' % (api, accepted))
        if api in ('Windows WASAPI', 'Windows WDM-KS'):
            check('%s accepts only the mix rate (no silent resample)' % api,
                  len(accepted) == 1, accepted)
        else:
            check('%s accepts everything (mixer resamples)' % api,
                  len(accepted) == len(PROBE_RATES), accepted)

    # --- 2. does the mixer resampler corrupt data? ----------------------
    mme = endpoints.get('MME')
    if mme is None:
        sys.exit('no MME endpoint — cannot run the measurement half')

    name = sd.query_devices(mme)['name']
    fs_native = int(sd.query_devices(mme)['default_samplerate'])
    v_fs = specs.full_scale_volts(
        name, GAIN_DB, INPUT_MODE,
        neighbours=[d['name'] for d in sd.query_devices()])
    expect = (TONE_VPP / 2) / v_fs if v_fs else None

    wit = capture(mme, fs_native)
    a_ref = amp_at(wit[:, 0], fs_native, TONE_HZ)
    print('\nwitness @%d Hz: input 1 reads %.6f FS' % (fs_native, a_ref))
    check('external tone present at the native rate', a_ref > 0.01,
          '%.4f FS' % a_ref)
    if expect:
        err_db = 20 * np.log10(a_ref / expect)
        check('calibrated volts within 0.25 dB of the stated-gain model',
              abs(err_db) < 0.25, '%+.3f dB vs %.4f FS expected'
              % (err_db, expect))

    x = capture(mme, DROOP_FS)
    droop = 20 * np.log10(max(amp_at(x[:, 0], DROOP_FS, TONE_HZ), 1e-12)
                          / a_ref)
    check('passband droop at %.2fx Nyquist is small (> -1 dB)'
          % (TONE_HZ / (DROOP_FS / 2)), droop > -1.0, '%.2f dB' % droop)

    x = capture(mme, FOLD_FS)
    fold = abs(((TONE_HZ + FOLD_FS / 2) % FOLD_FS) - FOLD_FS / 2)
    alias = 20 * np.log10(max(amp_at(x[:, 0], FOLD_FS, fold), 1e-12) / a_ref)
    check('tone above Nyquist is rejected, not folded (< -60 dB)',
          alias < -60, '%g Hz fold measured %.1f dB' % (fold, alias))

    # --- 3. the mono-downmix trap ---------------------------------------
    mono = capture(mme, fs_native, channels=1)
    a_mono = amp_at(mono[:, 0], fs_native, TONE_HZ)
    check('channels=1 delivers the (ch1+ch2)/2 downmix (-6 dB) — capture '
          '>= 2 channels for calibrated work',
          abs(20 * np.log10(max(a_mono, 1e-12) / a_ref) + 6.02) < 0.5,
          '%.2f dB re witness' % (20 * np.log10(max(a_mono, 1e-12) / a_ref)))

    print('\n%d/%d checks passed' % (len(PASS), len(PASS) + len(FAIL)))
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
