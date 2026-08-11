"""9234 oversample-strategy verification (2026-08-10 checklist §2).

`streams.oversample_strategy` 'auto' resolves to 'lowest' on DSA
devices: an ``lpf_on`` capture runs at the lowest ladder rate with
2.56x headroom over fs instead of the device max, because a
delta-sigma converter is anti-aliased at its own rate. This script
proves (on the real cDAQ 9234/9260, ao0 -> ai0 BNC loopback):

  A. capture-rate choice — fs=2000 captures at 6400 under 'auto'
     (strategy asks 3x = 6000, ladder coerces to 6400), at 51200
     under 'highest'; delivered fs is exactly 2000 (lpf_on's promise:
     the target never needs ladder coercion because the resample is
     software). NB the BRIDGE path differs: serve's configure adopts
     the DSA-coerced scope rate (2048) as the target first, so a
     bridge lpf log delivers 2048 — self-consistent but not identical.
  B. alias rejection under 'auto' — a three-tone drive separates the
     two protection layers:
       400 Hz   in-band reference (must pass at unity),
       1500 Hz  above target Nyquist 1024 but below capture Nyquist
                3200 — reaches the capture unaliased, the software
                decimation FIR must crush it (fold target 548 Hz),
       5900 Hz  in the 9234's own delta-sigma stopband at the 6400
                capture rate — the HARDWARE filter must crush it
                (fold target 500 Hz).
  C. noise floor 'auto' vs 'highest' — same channel, no drive, PSD in
     the delivered band. The delta-sigma's input-referred noise
     density is nominally flat, so restricting to the same final band
     should cost little; this measures the actual dB difference so
     the 'lowest' default is a decision, not a guess.

Run:  python dev/cdaq_oversample_check.py

First run 2026-08-11 (cDAQ-9174, 9234 + 9260): 7/7. Alias rejection
holds under 'auto'/'lowest' — the FIR crushed the 1500 Hz tone by
113 dB, the 9234's own filter crushed 5900 Hz by 107 dB. Noise cost
of 'lowest' vs 'highest': +3.0 dB in-band PSD (133 vs 130 uV rms on
the loopback channel) — far below the naive 10*log10(8) = 9 dB
because the delta-sigma's noise floor is not flat white across the
capture band.
"""
import numpy as np
import pydvma as dvma
from pydvma import _ni_backend
from scipy.signal import welch

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append((name, detail))
    print(('  PASS  ' if cond else '  FAIL  ') + name
          + ('' if not detail else '  [' + str(detail) + ']'))


def find_cdaq():
    for i, e in enumerate(_ni_backend.enumerate_devices()):
        if e.get('is_chassis'):
            return i, e
    raise SystemExit('no cDAQ chassis connected')


def settings(idx, *, lpf_on=True, oversample=None, output=False, fs=2000,
             stored_time=2.0):
    kw = dict(device_driver='nidaq', device_index=idx, channels=2,
              fs=fs, stored_time=stored_time,
              NI_mode='DAQmx_Val_PseudoDiff', VmaxNI=5, lpf_on=lpf_on)
    if oversample is not None:
        kw['oversample'] = oversample
    if output:
        kw.update(output_device_driver='nidaq', output_device_index=idx,
                  output_channels=1, output_VmaxNI=4, output_fs=51200)
    return dvma.MySettings(**kw)


def tone_amp(sig, fs, f):
    n = len(sig)
    w = np.hanning(n)
    spec = np.abs(np.fft.rfft(sig * w)) * 2 / np.sum(w)
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    k = int(np.argmin(np.abs(freqs - f)))
    return float(np.max(spec[max(0, k - 2):k + 3]))


def main():
    idx, entry = find_cdaq()
    print('cDAQ chassis: index %d (%s)' % (idx, entry['product_type']))

    # ---- A. capture-rate choice ----
    print('A. capture rate: auto (DSA -> lowest) vs highest')
    caps = {}
    for mode in ('auto', 'highest'):
        s = settings(idx, oversample=mode)
        ds = dvma.log_data(s)
        td = ds.time_data_list[0]
        caps[mode] = (float(td.settings.fs),
                      float(getattr(td.settings, 'lpf_capture_fs', 0)))
    check('auto: delivered fs = requested 2000 exactly',
          caps['auto'][0] == 2000.0, caps['auto'][0])
    check('auto: captured at 6400 (lowest with 2.56x headroom)',
          caps['auto'][1] == 6400.0, caps['auto'][1])
    check('highest: captured at 51200', caps['highest'][1] == 51200.0,
          caps['highest'][1])

    # ---- B. alias rejection under 'auto' ----
    print('B. alias rejection at capture fs 6400 (three-tone drive)')
    out_fs = 51200
    t = np.arange(0, 1.4, 1.0 / out_fs)
    n_ramp = int(0.05 * out_fs)
    win = np.ones_like(t)
    win[:n_ramp] = 0.5 * (1 - np.cos(np.pi * np.arange(n_ramp) / n_ramp))
    win[-n_ramp:] = 0.5 * (1 + np.cos(np.pi * np.arange(n_ramp) / n_ramp))
    drive = (0.33 * np.sin(2 * np.pi * 400.0 * t)
             + 0.33 * np.sin(2 * np.pi * 1500.0 * t)
             + 0.33 * np.sin(2 * np.pi * 5900.0 * t)) * win

    s = settings(idx, output=True, stored_time=1.6)
    ds = dvma.log_data(s, output=drive[:, None])
    td = ds.time_data_list[0]
    fs = float(td.settings.fs)
    y = np.asarray(td.time_data)[:, 0]
    seg = y[int(0.3 * fs):int(1.1 * fs)]
    a_in = tone_amp(seg, fs, 400.0)
    a_fir = tone_amp(seg, fs, 548.0)    # 1500 Hz folded across 1024
    a_dsa = tone_amp(seg, fs, 500.0)    # 5900 Hz folded across 3200
    check('in-band 400 Hz preserved (0.23..0.43 V)', 0.23 < a_in < 0.43,
          round(a_in, 4))
    check('1500 Hz crushed by the decimation FIR (>40 dB below in-band)',
          a_fir < a_in / 100, '%.6f V (%.1f dB down)' % (
              a_fir, 20 * np.log10(a_fir / a_in) if a_fir > 0 else -999))
    check('5900 Hz crushed by the 9234 hardware filter (>40 dB below in-band)',
          a_dsa < a_in / 100, '%.6f V (%.1f dB down)' % (
              a_dsa, 20 * np.log10(a_dsa / a_in) if a_dsa > 0 else -999))

    # ---- C. noise floor, quiet loopback channel ----
    print('C. noise floor: auto (6400) vs highest (51200), no drive')
    floors = {}
    for mode in ('auto', 'highest'):
        s = settings(idx, oversample=mode, stored_time=5.0)
        ds = dvma.log_data(s)
        td = ds.time_data_list[0]
        y = np.asarray(td.time_data)[:, 0]
        fs_out = float(td.settings.fs)
        f, pxx = welch(y, fs=fs_out, nperseg=2048)
        band = (f > 50) & (f < 900)
        floors[mode] = (float(np.sqrt(np.mean(y ** 2))),
                        float(np.median(pxx[band])))
        print('  %-8s rms %.3f uV, median PSD %.3e V^2/Hz'
              % (mode, floors[mode][0] * 1e6, floors[mode][1]))
    delta_db = 10 * np.log10(floors['auto'][1] / floors['highest'][1])
    print('  in-band noise PSD: auto is %+.1f dB vs highest' % delta_db)
    check('noise floors measured (report only — the default is a '
          'judgement call)', True, '%+.1f dB' % delta_db)

    print()
    print('==== %d passed, %d failed ====' % (len(PASS), len(FAIL)))
    for name, detail in FAIL:
        print('FAILED: %s  [%s]' % (name, detail))
    return 1 if FAIL else 0


if __name__ == '__main__':
    raise SystemExit(main())
