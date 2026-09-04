"""Known-source test of a 2i2 (or any 2-in soundcard): cDAQ AO -> L/R.

Round-14 follow-up (2026-09-04, office PC). The 3C6 session concluded
the 2i2 corrupts samples on BOTH channels in its digital path, from
captures of a rig whose true signals were unknown. This harness removes
the rig: the bench cDAQ's 9260 plays a KNOWN signal into both 2i2 line
inputs at once, so anything that differs between the two recorded
channels beyond a gain constant is the interface (or its USB link,
driver, host) — not a sensor, a cable or a structure.

Modes (``--mode``):

* ``identical`` (default): ao0 == ao1. Coherence L/R must be 1.0 in the
  signal band, the inter-channel lag exactly 0 samples in every second,
  the residual L - g.R pure interface noise.
* ``ratio``: ao1 = ao0 / 2 — the fitted gain must read the ratio flat.
* ``delay``: ao1 = ao0 delayed by 10 AO samples — the lag must read the
  delay in every second (a per-channel sample slip would move it).

The stimulus is brick-wall band-limited (20-3000 Hz, FFT-designed) so
the >6 kHz band the round-14 common-cause test looks at holds only
noise floor / corruption, never signal. The AO task regenerates its
buffer continuously, so the capture windows are arbitrary.

Each run records the same window twice — raw ``sounddevice`` (no
pydvma in the loop) and ``pydvma.log_data`` — and prints, for each:
the round-14 ``dev/channel_noise_check.report`` (dropouts, band
envelopes, common-cause lag-0 correlation, per-second coherence and
lag), then the identical-signal metrics, then the effective sample
resolution (bits) from the value grid the host delivered.

Usage (cDAQ ao0 -> 2i2 L, ao1 -> 2i2 R; 2i2 line inputs at a known gain)::

    python dev/twoi2_known_source_check.py --T=60 --gain=15 --sc-device=5
    python dev/twoi2_known_source_check.py --mode=delay --T=30
"""
import argparse
import os
import sys
import time
from types import SimpleNamespace

import numpy as np
import sounddevice as sd
from scipy import signal, stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channel_noise_check as cnc  # noqa: E402

import pydvma as dvma  # noqa: E402
from pydvma import acquisition, streams  # noqa: E402


def make_stimulus(fs_ao, seconds, amp, f_lo=20.0, f_hi=3000.0, seed=1234):
    """Brick-wall band-limited Gaussian noise, peak ``amp`` volts."""
    n = int(fs_ao * seconds)
    rng = np.random.default_rng(seed)
    spec = np.zeros(n // 2 + 1, dtype=complex)
    f = np.fft.rfftfreq(n, 1.0 / fs_ao)
    band = (f >= f_lo) & (f <= f_hi)
    spec[band] = rng.standard_normal(band.sum()) + 1j * rng.standard_normal(band.sum())
    x = np.fft.irfft(spec, n)
    x *= amp / np.max(np.abs(x))
    return x


def start_ao(x_left, x_right, fs_ao, device='cDAQ1Mod2', vmax=4.0):
    import nidaqmx
    from nidaqmx.constants import AcquisitionType
    task = nidaqmx.Task()
    task.ao_channels.add_ao_voltage_chan('%s/ao0:1' % device, min_val=-vmax, max_val=vmax)
    task.timing.cfg_samp_clk_timing(rate=fs_ao, sample_mode=AcquisitionType.CONTINUOUS,
                                    samps_per_chan=len(x_left))
    actual = float(task.timing.samp_clk_rate)
    task.write(np.vstack([x_left, x_right]), auto_start=False)
    task.start()
    return task, actual


def resolve_input(token='4800_8219', prefer_api='WDM-KS'):
    """Index of the input pin whose name contains ``token`` (the 2i2's USB
    product id under WDM-KS; also matches the WASAPI/MME names when the
    token is 'Focusrite'), preferring ``prefer_api``. PortAudio renumbers
    devices whenever the audio stack churns — measured twice on this PC
    in one session — so bench scripts must resolve by NAME every time."""
    apis = sd.query_hostapis()
    hits = [(i, d) for i, d in enumerate(sd.query_devices())
            if d['max_input_channels'] > 0 and (token.lower() in d['name'].lower()
                                                 or 'focusrite' in d['name'].lower()
                                                 or 'scarlett' in d['name'].lower())]
    if not hits:
        raise RuntimeError('no input device matching %r among %s' % (token, [d['name'] for d in sd.query_devices()]))
    hits.sort(key=lambda h: 0 if prefer_api.lower() in apis[h[1]['hostapi']]['name'].lower() else 1)
    i, d = hits[0]
    print('input device: %d %r via %s (%d in)' % (i, d['name'], apis[d['hostapi']]['name'], d['max_input_channels']))
    return i


def capture_raw(device, fs, seconds, channels=2):
    if device is None:
        device = resolve_input()
    chunks, flags = [], 0
    n_target = int(fs * seconds)

    def cb(indata, frames, t, status):
        nonlocal flags
        if status:
            flags += 1
        chunks.append(indata.copy())

    with sd.InputStream(device=device, channels=channels, samplerate=fs, dtype='float32',
                        blocksize=480, latency='high', callback=cb):
        t0 = time.time()
        while sum(c.shape[0] for c in chunks) < n_target + 4800:
            time.sleep(0.05)
            if time.time() - t0 > seconds + 20:
                break
    y = np.concatenate(chunks).astype(float)
    # Drop the startup priming (leading exact-zero frames), then the window.
    nz = np.flatnonzero(np.any(y != 0, axis=1))
    y = y[nz[0]:] if len(nz) else y
    return y[-n_target:], flags


def effective_bits(y):
    out = []
    for c in range(y.shape[1]):
        u = np.unique(y[:, c])
        d = np.diff(u)
        d = d[d > 0]
        lsb = float(np.min(d)) if len(d) else float('nan')
        out.append(np.log2(2.0 / lsb) if lsb and np.isfinite(lsb) else float('nan'))
    return out


def identical_metrics(y, fs, band=(20.0, 3000.0), expect_lag=0):
    L, R = y[:, 0], y[:, 1]
    # lag-0 least-squares gain L = g R
    g = float(np.dot(L, R) / np.dot(R, R))
    e = L - g * R
    rms_L = np.sqrt(np.mean(L ** 2))
    rms_e = np.sqrt(np.mean(e ** 2))
    hf_hi = min(15000.0, 0.45 * fs)
    if hf_hi > 2500.0:
        sos = signal.butter(4, [2000.0, hf_hi], btype='band', fs=fs, output='sos')
        e_hf = signal.sosfiltfilt(sos, e)
    else:
        e_hf = e   # decimated capture: no HF band to isolate
    print('   identical-signal: gain L/R = %.4f (%.2f dB); residual rms %.2e = %.1f dB below L; '
          'max|resid| / rms_L = %.2f; residual kurtosis full %.1f, 2-15 kHz %.1f (Gaussian = 3)'
          % (g, 20 * np.log10(abs(g)), rms_e, 20 * np.log10(rms_L / rms_e),
             np.max(np.abs(e)) / rms_L, stats.kurtosis(e, fisher=False),
             stats.kurtosis(e_hf, fisher=False)))
    # per-second coherence in the signal band and per-second lag
    n1 = int(fs)
    nsec = len(L) // n1
    cohs, lags = [], []
    for k in range(nsec):
        a = L[k * n1:(k + 1) * n1]
        b = R[k * n1:(k + 1) * n1]
        f, c = signal.coherence(a, b, fs=fs, nperseg=4096)
        m = (f >= band[0]) & (f <= min(band[1], 0.45 * fs))
        cohs.append(float(np.mean(c[m])))
        xc = signal.correlate(a, b, mode='full', method='fft')
        lags.append(int(np.argmax(np.abs(xc)) - (n1 - 1)))
    cohs = np.array(cohs)
    lags = np.array(lags)
    print('   per-second coherence %g-%g Hz: min %.4f median %.4f; seconds < 0.99: %d of %d'
          % (band[0], band[1], cohs.min(), np.median(cohs), int(np.sum(cohs < 0.99)), nsec))
    print('   per-second lag L->R: expected %d; observed values %s; seconds off-expected: %d'
          % (expect_lag, sorted(set(lags.tolist())), int(np.sum(lags != expect_lag))))
    # where is the residual energy in time? top 5 seconds
    er = np.array([np.sqrt(np.mean(e[k * n1:(k + 1) * n1] ** 2)) for k in range(nsec)])
    top = np.argsort(er)[::-1][:5]
    print('   residual rms per second: median %.2e, worst seconds %s'
          % (np.median(er), [(int(t), '%.1e' % er[t]) for t in top]))
    return dict(g=g, rms_e=rms_e, coh=cohs, lags=lags, resid_sec=er)


def analyse(y, fs, label, gain_db, band, expect_lag=0):
    td = SimpleNamespace(time_data=y, test_name=label, settings=SimpleNamespace(
        fs=fs, device_driver='soundcard', device_index=None, device_name=label,
        device_hostapi=None, lpf_capture_fs=None, stored_time=y.shape[0] / fs))
    cnc.report(td, 0, 0, band)
    m = identical_metrics(y, fs, expect_lag=expect_lag)
    print('   effective resolution per channel: %s bits' % np.round(effective_bits(y), 1).tolist())
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--T', type=float, default=60.0)
    ap.add_argument('--amp', type=float, default=0.5, help='AO peak volts')
    ap.add_argument('--fs-ao', type=float, default=51200.0)
    ap.add_argument('--fs', type=float, default=48000.0, help='soundcard capture rate')
    ap.add_argument('--sc-device', type=int, default=None, help='sounddevice index; default: resolve the 2i2 by name (WDM-KS preferred)')
    ap.add_argument('--gain', type=float, default=15.0, help='2i2 preamp gain stated on the knobs, dB')
    ap.add_argument('--mode', choices=('identical', 'ratio', 'delay'), default='identical')
    ap.add_argument('--band', type=float, nargs=2, default=(3500.0, 5500.0),
                    help='floor band for the envelope test (must be clear of the 20-3000 Hz stimulus)')
    ap.add_argument('--skip-raw', action='store_true')
    ap.add_argument('--skip-pydvma', action='store_true')
    ap.add_argument('--out', default='')
    args = ap.parse_args()

    x = make_stimulus(args.fs_ao, 10.0, args.amp)
    if args.mode == 'identical':
        xr, expect_lag = x, 0
    elif args.mode == 'ratio':
        xr, expect_lag = x / 2.0, 0
    else:
        # ao1 lags ao0 by 10 AO samples = 9.4 capture samples at 48 kHz: the
        # per-second lag L->R must read -round(10 * fs / fs_ao) in EVERY second
        # (measured: -9 in 30 of 30 s on the office 2i2, 2026-09-04).
        xr, expect_lag = np.roll(x, 10), -int(round(10 * args.fs / args.fs_ao))
    task, fs_ao_actual = start_ao(x, xr, args.fs_ao)
    print('AO running: %s at %g Hz, %.2f Vpk, 20-3000 Hz brick-wall noise, 10 s regenerating'
          % (args.mode, fs_ao_actual, args.amp))
    time.sleep(1.0)
    if args.sc_device is None:
        args.sc_device = resolve_input()
    results = {}
    try:
        if not args.skip_raw:
            print('\n### RAW sounddevice capture: device %d, %g Hz, %.0f s' % (args.sc_device, args.fs, args.T))
            y_raw, flags = capture_raw(args.sc_device, args.fs, args.T)
            print('   PortAudio status flags: %d' % flags)
            results['raw'] = analyse(y_raw, args.fs, 'raw-sounddevice', args.gain, tuple(args.band), expect_lag)
            results['raw']['y'] = y_raw
        if not args.skip_pydvma:
            print('\n### pydvma log_data capture: device %d, %g Hz, %.0f s, gain %g dB'
                  % (args.sc_device, args.fs, args.T, args.gain))
            # By NAME, not index: pydvma's own probes re-initialise PortAudio,
            # which renumbers devices within the process; a name also lets
            # MySettings derive VmaxSC from the stated gain.
            sc_name = sd.query_devices(args.sc_device)['name']
            s = dvma.MySettings(device_driver='soundcard', device=sc_name, channels=2,
                                fs=args.fs, stored_time=args.T, input_gain_db=args.gain)
            print('   VmaxSC derived: %s V (full scale)' % getattr(s, 'VmaxSC', None))
            d = dvma.log_data(s, test_name='known-source-%s' % args.mode)
            td = d.time_data_list[0]
            print('   overflows %s dropouts %s' % (acquisition.LAST_CAPTURE_OVERFLOWS,
                                                   getattr(acquisition, 'LAST_CAPTURE_DROPOUTS', None)))
            y_pv = np.asarray(td.time_data, dtype=float) / float(getattr(s, 'VmaxSC', 1.0))  # back to FS units
            results['pydvma'] = analyse(y_pv, float(td.settings.fs), 'pydvma-log_data', args.gain, tuple(args.band),
                                        -int(round(10 * float(td.settings.fs) / args.fs_ao)) if args.mode == 'delay' else 0)
            results['pydvma']['y'] = y_pv
            if args.out:
                dvma.save_data(d, filename=args.out + '_pydvma.dvma')
            try:
                streams.REC.end_stream()
            except Exception:
                pass
    finally:
        task.stop()
        task.close()
    if args.out:
        np.savez(args.out + '.npz', **{k + '_y': v['y'] for k, v in results.items()}, fs=args.fs)
        print('saved', args.out + '.npz')


if __name__ == '__main__':
    main()
