"""2i2 loopback discriminator: analogue inputs vs the digital loopback pair.

Round-14 checklist item 5, no rig needed. The Scarlett 2i2 4th Gen
exposes four capture channels on its MME/DirectSound/WASAPI endpoints:
1-2 are the analogue inputs, 3-4 a DIGITAL loopback of the output mix
(user guide p44). This script plays band-limited noise to the 2i2's own
output (so channels 3-4 carry it, entirely in the digital domain) while
whatever is on the analogue inputs — the cDAQ known source, a generator,
the lab rig — is recorded on 1-2, all four in ONE stream, then reports
each pair's per-second coherence, lag, exact-zero runs and one-sample
steps, and the round-14 common-cause test between an analogue channel
and a loopback channel.

Reading it (the corruption case from the lab, if it is present):

* impulses / dropouts on 3-4 as well as 1-2, in the SAME frames → the
  USB link, the driver or the host: the loopback never touched the
  converters;
* 3-4 pristine while 1-2 show them → the 2i2's converter / analogue
  power section;
* nothing anywhere → this PC + link + unit are clean (the office-bench
  result); take the same script to the lab PC.

Usage (device resolved by name; MME preferred because its capture
endpoint is the one that exposes all four channels)::

    python dev/twoi2_loopback_check.py --T=60
    python dev/twoi2_loopback_check.py --T=60 --in-api=DirectSound --out-api=WASAPI
"""
import argparse
import os
import sys
import time

import numpy as np
import sounddevice as sd
from scipy import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channel_noise_check as cnc  # noqa: E402
from twoi2_known_source_check import make_stimulus, start_ao  # noqa: E402


def find(kind, api_want):
    apis = sd.query_hostapis()
    key = 'max_input_channels' if kind == 'input' else 'max_output_channels'
    for i, d in enumerate(sd.query_devices()):
        n = d['name'].lower()
        if d[key] > 0 and ('focusrite' in n or 'scarlett' in n or '4800_8219' in n) \
                and api_want.lower() in apis[d['hostapi']]['name'].lower():
            print('%s: %d %r via %s (%d ch)' % (kind, i, d['name'], apis[d['hostapi']]['name'], d[key]))
            return i
    raise RuntimeError('no 2i2 %s on %s' % (kind, api_want))


def per_second(a, b, fs, band=(20.0, 3000.0)):
    n1 = int(fs)
    cohs, lags = [], []
    for k in range(len(a) // n1):
        x, y = a[k * n1:(k + 1) * n1], b[k * n1:(k + 1) * n1]
        f, c = signal.coherence(x, y, fs=fs, nperseg=4096)
        m = (f >= band[0]) & (f <= band[1])
        cohs.append(float(np.mean(c[m])))
        xc = signal.correlate(x, y, mode='full', method='fft')
        lags.append(int(np.argmax(np.abs(xc)) - (n1 - 1)))
    return np.array(cohs), np.array(lags)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--T', type=float, default=60.0)
    ap.add_argument('--fs', type=float, default=48000.0)
    ap.add_argument('--in-api', default='MME')
    ap.add_argument('--out-api', default='MME', help='playback endpoint backend (MME by default: a WASAPI shared open can block on a freshly enumerated endpoint)')
    ap.add_argument('--with-ao', action='store_true', help='also drive the analogue inputs from the cDAQ (ao0/ao1, identical noise)')
    ap.add_argument('--amp', type=float, default=0.5, help='cDAQ AO peak volts for --with-ao')
    ap.add_argument('--level', type=float, default=0.3, help='playback peak, fraction of full scale')
    ap.add_argument('--out', default='')
    args = ap.parse_args()
    fs = int(args.fs)
    dev_in = find('input', args.in_api)
    dev_out = find('output', args.out_api)
    ao = None
    if args.with_ao:
        xa = make_stimulus(51200, 10.0, args.amp, seed=99)
        ao, fs_ao = start_ao(xa, xa, 51200)
        print('cDAQ AO running into the analogue inputs at %g Hz, %.2f Vpk (identical on ao0/ao1)' % (fs_ao, args.amp))
        time.sleep(0.5)

    noise = make_stimulus(fs, 10.0, args.level).astype('float32')
    play = np.column_stack([noise, noise])
    pos = {'i': 0}

    def out_cb(outdata, frames, t, status):
        i = pos['i']
        idx = (np.arange(frames) + i) % len(noise)
        outdata[:] = play[idx]
        pos['i'] = (i + frames) % len(noise)

    chunks, flags = [], {'n': 0}

    def in_cb(indata, frames, t, status):
        if status:
            flags['n'] += 1
        chunks.append(indata.copy())

    n_target = int(fs * args.T)
    with sd.OutputStream(device=dev_out, channels=2, samplerate=fs, dtype='float32',
                         blocksize=480, latency='high', callback=out_cb):
        time.sleep(0.5)
        with sd.InputStream(device=dev_in, channels=4, samplerate=fs, dtype='float32',
                            blocksize=480, latency='high', callback=in_cb):
            t0 = time.time()
            while sum(c.shape[0] for c in chunks) < n_target + fs and time.time() - t0 < args.T + 20:
                time.sleep(0.1)
    if ao is not None:
        ao.stop(); ao.close()
    y = np.concatenate(chunks).astype(float)
    nz = np.flatnonzero(np.any(y != 0, axis=1))
    y = y[nz[0]:] if len(nz) else y
    y = y[-n_target:]
    print('captured %s at %d Hz, PortAudio status flags %d' % (y.shape, fs, flags['n']))
    print('rms per channel (1,2 analogue | 3,4 loopback): %s' % np.round(np.sqrt(np.mean(y ** 2, axis=0)), 5).tolist())
    for name, (a, b) in (('analogue 1 vs 2', (0, 1)), ('loopback 3 vs 4', (2, 3)), ('analogue 1 vs loopback 3', (0, 2))):
        c, l = per_second(y[:, a], y[:, b], fs)
        print('%-26s coherence min %.4f median %.4f (seconds < 0.99: %d of %d); lag values %s'
              % (name, c.min(), np.median(c), int(np.sum(c < 0.99)), len(c), sorted(set(l.tolist()))[:8]))
    for pair, label in (((0, 1), 'analogue pair'), ((2, 3), 'loopback pair'), ((0, 2), 'analogue-1 / loopback-3')):
        cc = cnc.common_cause_test(y[:, list(pair)], fs)
        if cc:
            lag0, off, floors, steps, hf_coh = cc
            print('%-26s common-cause lag-0 %.2f vs off-lag %.2f (ratio %.1f, >6 kHz waveform coherence %.2f); >6 kHz floors %s dB; max step/rms %s'
                  % (label, lag0, off, lag0 / max(off, 0.02), hf_coh, np.round(floors, 1).tolist(), np.round(steps, 1).tolist()))
    # MME/DirectSound deliver 16-bit samples: a quiet channel then sits on
    # exact zeros half the time, so short runs mean nothing there. Count
    # only runs a live analogue input cannot produce (>= 8 frames on ALL
    # channels at once), the acquisition.exact_zero_dropouts convention.
    runs_all = cnc.zero_runs(y, 8)
    print('exact-zero runs (>= 8 frames) on ALL four channels: %d %s' % (len(runs_all), runs_all[:5]))
    if args.out:
        np.savez(args.out, y=y, fs=fs)
        print('saved', args.out)


if __name__ == '__main__':
    main()
