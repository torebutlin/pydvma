"""Load and buffering A/B on a live sound-card input: does host load corrupt the stream, and does
user-space buffering recover it?

This is the harness behind the round-14d reproduction and the 2026-09-11 buffering sweep in
``dev/hardware-lessons-learnt.md``.  It records raw ``sounddevice`` captures (nothing of pydvma in the
loop) under a sequence of host conditions and reports, per capture:

* zero-fill runs and frames lost: the driver's stand-in for USB packets that arrived late (exact
  zeros on EVERY channel, invisible to PortAudio's overflow flag),
* PortAudio's own overflow count and the longest gap between callbacks (user-space starvation),
* each channel's >6 kHz noise floor and largest one-sample step relative to its RMS, and the
  common-cause ratio from ``channel_noise_check`` (above ~2 means frame-synchronous corruption in the
  interface's digital path; ~1 means independent per-channel noise),
* per-second coherence between channels 0 and 1 when ``--coherence`` is given (only meaningful with a
  signal on both inputs: a shaker rig, or a generator teed into both).

It needs no signal: an interface's own input noise floor is never exactly zero, so the dropout and
common-cause measures work with the rig switched off.

Conditions (``--conditions``, default ``quiet,churn,quiet``):

* ``quiet``  nothing added,
* ``churn``  four worker processes each FFT-ing fresh 100 MB arrays (the notebook-as-captures-
  accumulate pattern that reproduced the lab fault: memory commit pressure plus CPU),
* ``disk``   one process reading every file under ``--disk-root`` as fast as it can.

``--buffering`` replaces the sequence with the block-size / latency sweep under churn.  Each capture
lasts ``--seconds`` (default 30).  The device is resolved by name substring, preferring WASAPI, then
WDM-KS; ``--fs`` defaults to the first of 48000 / 44100 the device accepts.

Examples::

    python dev/soundcard_load_check.py                       # Focusrite, quiet / churn / quiet, 30 s each
    python dev/soundcard_load_check.py --buffering           # the block-size sweep under churn
    python dev/soundcard_load_check.py --device U24XL --conditions quiet,disk,quiet --seconds 20
    python dev/soundcard_load_check.py --conditions quiet --seconds 5   # smoke test

Interpretation: if churn adds zero-fill runs while PortAudio's overflow count stays 0 and the buffering
sweep changes nothing, the loss is below user space (audio engine / driver / USB link) and the levers
are the host's memory headroom and the driver's own buffer setting, not anything in pydvma.
"""
import argparse
import multiprocessing as mp
import os
import sys
import time

import numpy as np
import sounddevice as sd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channel_noise_check as cnc  # noqa: E402

CHURN_WORKERS = 4
CHURN_SAMPLES = 12_500_000  # 100 MB of float64 per array
BUFFERING_SWEEP = [(100, 'high'), (1600, 'high'), (9600, 'high'), (1600, 0.5), (9600, 1.0)]


def churn_worker(end):
    """FFT fresh 100 MB arrays until ``end`` (memory commit + CPU pressure)."""
    while time.time() < end:
        a = np.random.standard_normal(CHURN_SAMPLES)
        np.fft.rfft(a)
        del a


def disk_worker(root, end):
    """Read every file under ``root`` repeatedly until ``end``."""
    while time.time() < end:
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                if time.time() > end:
                    return
                try:
                    with open(os.path.join(dp, f), 'rb') as h:
                        while h.read(1 << 20):
                            pass
                except OSError:
                    pass


def start_load(kind, seconds, disk_root):
    """Start the load processes for ``kind``; returns the list to stop afterwards."""
    end = time.time() + seconds + 5
    if kind == 'churn':
        procs = [mp.Process(target=churn_worker, args=(end,)) for _ in range(CHURN_WORKERS)]
    elif kind == 'disk':
        procs = [mp.Process(target=disk_worker, args=(disk_root, end))]
    else:
        procs = []
    for p in procs:
        p.start()
    return procs


def stop_load(procs):
    for p in procs:
        if p.is_alive():
            p.terminate()
        p.join(timeout=5)


def resolve_device(name):
    """Input device index for the first entry whose name contains ``name``: WASAPI first, then WDM-KS, then any."""
    apis = sd.query_hostapis()
    devs = sd.query_devices()
    for api_pref in ('WASAPI', 'WDM-KS', 'Core Audio', ''):
        for i, d in enumerate(devs):
            if d['max_input_channels'] > 0 and name.lower() in d['name'].lower() and api_pref in apis[d['hostapi']]['name']:
                return i
    raise SystemExit('no input device matching %r; run pydvma-serve --list-devices' % name)


def pick_fs(dev, requested):
    """The requested rate if the device accepts it, else the first of 48000 / 44100 it does."""
    for rate in ([requested] if requested else [48000, 44100]):
        try:
            sd.check_input_settings(device=dev, channels=2, samplerate=rate)
            return rate
        except Exception:
            pass
    raise SystemExit('device refuses %s' % (requested or '48000 and 44100'))


def capture(dev, fs, seconds, blocksize, latency):
    """One raw capture; returns (samples or None, overflows, host buffer s, max callback gap s)."""
    chunks, t_cb, ovf = [], [], [0]

    def cb(indata, frames, t, status):
        if status.input_overflow:
            ovf[0] += 1
        chunks.append(indata.copy())
        t_cb.append(time.perf_counter())

    with sd.InputStream(device=dev, channels=2, samplerate=fs, blocksize=blocksize, dtype='float32',
                        latency=latency, callback=cb) as st:
        host_buf = st.latency
        time.sleep(seconds)
    if not chunks:
        return None, ovf[0], host_buf, 0.0
    gaps = np.diff(t_cb)
    return np.concatenate(chunks).astype(float), ovf[0], host_buf, float(gaps.max()) if len(gaps) else 0.0


def metrics(y, fs, coherence):
    """The per-capture numbers; the run of zeros at sample 0 is start-up priming and is dropped."""
    lag0, off, floors, steps, _hf = cnc.common_cause_test(y, fs)
    runs = [r for r in cnc.zero_runs(y, 8) if r[0] > 0]
    m = dict(ratio=lag0 / max(off, 0.02), floor0=floors[0], floor1=floors[1], step0=steps[0], step1=steps[1],
             zero_runs=len(runs), zero_frames=sum(n for _, n in runs))
    if coherence:
        c = cnc.per_second_coherence(y[:, 0], y[:, 1], fs)
        m['coh_med'], m['coh_min'] = float(np.median(c)), float(c.min())
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--device', default='Focusrite', help='input device name substring (default Focusrite)')
    ap.add_argument('--fs', type=int, default=None)
    ap.add_argument('--seconds', type=float, default=30.0)
    ap.add_argument('--conditions', default='quiet,churn,quiet', help='comma list of quiet / churn / disk')
    ap.add_argument('--buffering', action='store_true', help='block-size / latency sweep under churn instead')
    ap.add_argument('--disk-root', default=sys.prefix, help='tree the disk condition reads (default: the Python prefix)')
    ap.add_argument('--coherence', action='store_true', help='also report per-second coherence ch0/ch1 (needs a signal)')
    ap.add_argument('--blocksize', type=int, default=1600)
    args = ap.parse_args()

    dev = resolve_device(args.device)
    fs = pick_fs(dev, args.fs)
    apis = sd.query_hostapis()
    print('device %d %r via %s at %d Hz, %.0f s per capture' % (
        dev, sd.query_devices(dev)['name'], apis[sd.query_devices(dev)['hostapi']]['name'], fs, args.seconds), flush=True)

    if args.buffering:
        plan = ([('quiet', args.blocksize, 'high')] + [('churn', b, lat) for b, lat in BUFFERING_SWEEP]
                + [('quiet', args.blocksize, 'high')])
    else:
        plan = [(c.strip(), args.blocksize, 'high') for c in args.conditions.split(',') if c.strip()]

    for cond, blk, lat in plan:
        label = '%-5s blk %5d lat %-4s' % (cond, blk, lat)
        procs = start_load(cond, args.seconds, args.disk_root)
        time.sleep(2)
        try:
            y, ovf, host_buf, gap = capture(dev, fs, args.seconds, blk, lat)
        finally:
            stop_load(procs)
        if y is None:
            print('%s  NO DATA (endpoint wedged? see hardware-lessons-learnt.md section 2)' % label, flush=True)
            continue
        if not np.any(y):
            print('%s  SILENT INPUT (every sample exactly zero): a dead or redirected endpoint, nothing to measure' % label,
                  flush=True)
            continue
        m = metrics(y, fs, args.coherence)
        line = ('%s | host buf %.3f s | max cb gap %4.0f ms | overflows %d | zero-fill runs %3d (%6d frames = %4.1f %%) | '
                '>6k floors %6.1f / %6.1f dB | max step/rms %4.1f / %4.1f | lag-0 ratio %4.1f' % (
                    label, host_buf, 1000 * gap, ovf, m['zero_runs'], m['zero_frames'], 100.0 * m['zero_frames'] / len(y),
                    m['floor0'], m['floor1'], m['step0'], m['step1'], m['ratio']))
        if args.coherence:
            line += ' | coherence median %.2f min %.2f' % (m['coh_med'], m['coh_min'])
        print(line, flush=True)
        time.sleep(3)
    print('DONE')


if __name__ == '__main__':
    mp.freeze_support()
    main()
