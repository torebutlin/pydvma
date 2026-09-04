"""Which channel is misbehaving? Per-capture noise-burst / dropout / coherence report.

Round-14 diagnostic (2026-09-04). On the 3C6 rig the 2i2's TF coherence
collapsed intermittently with no dropped samples anywhere; what cracked
it was looking at each channel's OWN band-limited noise floor against
the per-second coherence: the accelerometer channel's floor jumped
10-15 dB in exactly the seconds the coherence died, while the drive
channel in the same USB frames stayed flat. That pattern cannot come
from acquisition (one stream, one callback, one ring buffer feeds both
channels) - it is noise entering upstream of the converter on ONE
input. This script prints that view for every time set in one or more
``.dvma`` files so the question "is it the acquisition or the rig?" is
answered from the data rather than argued::

    python dev/channel_noise_check.py data/not-working-examples/pydvma_2026-09-04_1704.dvma
    python dev/channel_noise_check.py a.dvma b.dvma --ref 0 --band 420 700

Per time set it reports the capture settings, per-channel RMS, exact-
zero runs (dropouts: both channels zero at once is the host/driver
zero-filling; one channel alone is not a digital event), the
common-cause test (`common_cause_test`: are the above-6 kHz noise
envelopes of the two channels correlated at lag zero? — that is how the
2026-09-04 round found the "accelerometer noise" was really
frame-synchronous corruption of BOTH channels, only visible on the
weaker one), per-second coherence of every channel against ``--ref``
(min / median / max and how many seconds fall below 0.3), each
channel's band-envelope "noisy" window count (50 ms windows more than
6 dB over that channel's own median - the burst signature), and the
inter-channel lag in the good seconds (a stable physical delay when the
pair is healthy).

Reading it: a noisy channel whose bursts are NOT simultaneous with the
other channel's is an analogue problem on that input (cable, connector,
preamp). Bursts that ARE simultaneous, with waveforms uncorrelated and
one-sample steps far above the channel RMS, are the interface's data
path — USB link, power, firmware — and no amount of cable swapping
will move them.

The band defaults to 420-700 Hz - between the rig's 310 Hz and 760 Hz
modes, where the structural response is small and an added floor shows
plainly; pick a band clear of your own resonances with ``--band``. Reads
the container directly (no Qt, no file dialog).
"""
import argparse

import numpy as np
from scipy import signal

from pydvma import container


def band_envelope_db(x, fs, band, win=0.05):
    """50 ms RMS envelope of ``x`` band-passed to ``band``, in dB."""
    hi = min(band[1], 0.45 * fs)
    lo = min(band[0], 0.5 * hi)
    sos = signal.butter(4, [lo, hi], btype='band', fs=fs, output='sos')
    xf = signal.sosfiltfilt(sos, x)
    w = max(8, int(win * fs))
    n = len(xf) // w
    e = np.sqrt(np.mean(xf[:n * w].reshape(n, w) ** 2, axis=1))
    return 20 * np.log10(e + 1e-12)


def zero_runs(y, min_len):
    """(start, length) of runs where every column is exactly zero."""
    z = np.all(y == 0, axis=1)
    edges = np.diff(np.concatenate([[0], z.astype(int), [0]]))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    return [(int(a), int(b - a)) for a, b in zip(starts, ends) if b - a >= min_len]


def per_second_coherence(x, y, fs, f_lo=20.0, f_hi=1000.0):
    nper = 256 if fs <= 6000 else 2048
    blk = int(fs)
    out = []
    for b in range(len(x) // blk):
        f, c = signal.coherence(x[b * blk:(b + 1) * blk], y[b * blk:(b + 1) * blk],
                                fs=fs, nperseg=nper)
        band = (f > f_lo) & (f < min(f_hi, 0.45 * fs))
        out.append(float(c[band].mean()))
    return np.array(out)


def lag_samples(x, y, fs, seconds):
    """Peak cross-correlation lag of y relative to x over the given seconds."""
    if not len(seconds):
        return None
    hi = min(1000.0, 0.45 * fs)
    sos = signal.butter(4, [20, hi], btype='band', fs=fs, output='sos')
    lags = []
    for s in seconds[:10]:
        a = signal.sosfiltfilt(sos, x[int(s * fs):int((s + 1) * fs)])
        b = signal.sosfiltfilt(sos, y[int(s * fs):int((s + 1) * fs)])
        xc = signal.correlate(b, a, mode='full', method='fft')
        lags.append(int(signal.correlation_lags(len(b), len(a))[np.argmax(np.abs(xc))]))
    return lags


def common_cause_test(y, fs, hf_hz=6000.0):
    """Is the noise arriving on ALL channels at the same instants?

    Band-pass each channel above ``hf_hz`` — where neither a shaker
    drive nor a structural response has content, so what is left is
    noise — rectify, and cross-correlate the envelopes of channel pairs.
    Returns ``(lag0, off_lag_max, floors_db, max_step_ratio)``:

    - ``lag0``: envelope correlation at zero lag (bad 2i2 captures on
      2026-09-04: 0.63 on every one, the raw-sounddevice controls
      included; the one clean capture: 0.19; any other lag: ~0.01).
      Noise that is simultaneous on both channels but uncorrelated in
      waveform is frame-level corruption in the interface's digital
      path — samples wrong on every channel of the same frames — not a
      cable, connector or preamp on one input.
    - ``off_lag_max``: the largest envelope correlation at lags 6..200,
      the yardstick for ``lag0``.
    - ``floors_db``: per-channel RMS level above ``hf_hz`` in dB — a
      floor 10–20 dB above a known-clean capture of the same rig is the
      same corruption seen from the other side.
    - ``max_step_ratio``: per-channel largest sample-to-sample jump
      divided by the channel RMS. A one-sample outlier with no ringing
      cannot come through an anti-alias filter from the analogue side.

    Needs a capture rate well above ``2 * hf_hz``; returns ``None``
    below 20 kHz.
    """
    if fs < 20000 or y.shape[1] < 2:
        return None
    sos = signal.butter(4, hf_hz, btype='high', fs=fs, output='sos')
    hp = np.column_stack([signal.sosfiltfilt(sos, y[:, c]) for c in range(y.shape[1])])
    floors = 20 * np.log10(np.sqrt(np.mean(hp ** 2, axis=0)) + 1e-12)
    env = np.abs(hp) - np.mean(np.abs(hp), axis=0)
    a, b = env[:, 0], env[:, 1]
    xc = signal.correlate(b, a, mode='full', method='fft') / np.sqrt(np.dot(a, a) * np.dot(b, b))
    mid = len(a) - 1
    off = np.concatenate([xc[mid - 200:mid - 5], xc[mid + 6:mid + 201]])
    steps = np.max(np.abs(np.diff(y, axis=0)), axis=0) / (np.sqrt(np.mean(y ** 2, axis=0)) + 1e-12)
    return float(xc[mid]), float(off.max()), floors, steps


def report(td, index, ref, band):
    s = td.settings
    y = np.asarray(td.time_data, dtype=float)
    fs = float(s.fs)
    n_ch = y.shape[1]
    print('== set %d  %s' % (index, getattr(td, 'test_name', '')))
    print('   driver=%s device=%s (%s, %s) fs=%g capture_fs=%s stored_time=%s channels=%d'
          % (getattr(s, 'device_driver', '?'), getattr(s, 'device_index', '?'),
             getattr(s, 'device_name', None), getattr(s, 'device_hostapi', None),
             fs, getattr(s, 'lpf_capture_fs', None), getattr(s, 'stored_time', None), n_ch))
    print('   rms per channel: %s   max|x|: %s'
          % (np.round(np.sqrt(np.mean(y ** 2, axis=0)), 4), np.round(np.abs(y).max(axis=0), 4)))
    both = zero_runs(y, 4)
    if both:
        print('   DROPOUTS: %d run(s) of exact zeros on ALL channels: %s'
              % (len(both), [(round(a / fs, 3), round(n / fs, 3)) for a, n in both[:8]]))
    for ch in range(n_ch):
        single = zero_runs(y[:, [ch]], 4)
        if len(single) > len(both):
            print('   ch%d alone has %d exact-zero run(s) (first %s)' % (ch, len(single), single[:3]))
    envs = [band_envelope_db(y[:, ch], fs, band) for ch in range(n_ch)]
    for ch in range(n_ch):
        e = envs[ch]
        med = float(np.median(e))
        noisy = np.flatnonzero(e > med + 6)
        print('   ch%d %d-%d Hz floor: median %.1f dB, noisy 50 ms windows %d of %d (%.0f%%), first at t=%s'
              % (ch, band[0], band[1], med, len(noisy), len(e), 100 * len(noisy) / max(1, len(e)),
                 np.round(noisy[:6] * 0.05, 2).tolist()))
    cc = common_cause_test(y, fs)
    if cc is None:
        print('   common-cause test: needs a capture at >= 20 kHz (this one is %g Hz)' % fs)
    else:
        lag0, off, floors, steps = cc
        verdict = ('SIMULTANEOUS on both channels -> frame-level corruption in the '
                   'interface digital path' if lag0 > 0.4 else
                   'not simultaneous -> per-channel (analogue) or none')
        print('   common-cause test (>6 kHz envelopes): lag-0 correlation %.2f vs other lags max %.2f -> %s'
              % (lag0, off, verdict))
        print('      >6 kHz floor per channel: %s dB; largest one-sample step / rms: %s'
              % (np.round(floors, 1).tolist(), np.round(steps, 1).tolist()))
    for ch in range(n_ch):
        if ch == ref:
            continue
        c = per_second_coherence(y[:, ref], y[:, ch], fs)
        if not len(c):
            continue
        good = np.flatnonzero(c > 0.6)
        bad = np.flatnonzero(c < 0.3)
        print('   coherence ch%d vs ch%d (20-1000 Hz, 1 s blocks): min %.2f median %.2f max %.2f; %d of %d s below 0.3'
              % (ch, ref, c.min(), np.median(c), c.max(), len(bad), len(c)))
        print('      per second: %s' % np.round(c, 2).tolist())
        lags = lag_samples(y[:, ref], y[:, ch], fs, good)
        if lags:
            print('      lag of ch%d behind ch%d in good seconds: %s samples (%.1f ms typical)'
                  % (ch, ref, lags, 1000 * float(np.median(lags)) / fs))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('files', nargs='+')
    ap.add_argument('--ref', type=int, default=0, help='reference channel (default 0)')
    ap.add_argument('--band', type=float, nargs=2, default=(420.0, 700.0),
                    help='floor band in Hz, clear of the rig modes (default 420 700)')
    args = ap.parse_args()
    for path in args.files:
        d = container.load(path)
        sets = list(d.time_data_list)
        print('#### %s: %d time set(s)' % (path, len(sets)))
        for i, td in enumerate(sets):
            report(td, i, args.ref, tuple(args.band))


if __name__ == '__main__':
    main()
