"""NI capture-integrity check: does a long capture lose samples?

The NI twin of ``dev/soundcard_drop_check.py``. Runs ONE ``log_data``
capture through the ordinary Python API with the every-N-samples
callback instrumented, plays a linear sweep on ao0 (BNC loopback to
ai0 expected), and reports the four things that went wrong in the
2026-09-04 cDAQ lab round (dev/2026-09-04-round13-cdaq-lab-feedback.md):

* per-chunk callback cost against the ``chunk_size/fs`` budget, and the
  DAQmx backlog (``avail_samp_per_chan``) over time — the old O(buffer)
  shift ran at 99 % of budget on a desktop for the lab geometry;
* DAQmx input overflows (``-200279``) — under overflow the driver keeps
  the task running and about every other read fails, so samples vanish
  silently unless counted (``Recorder_NI_nidaqmx.input_overflows``);
* leading exact-zero rows and quiet stretches on ai0 (the buffer held a
  time-compressed history: pre-/post-stimulus quiet spliced in);
* the sweep's instantaneous frequency vs time — a lost stretch is a
  frequency JUMP, and a wrong slope means the stimulus played at the
  wrong rate (the AO coercion bug: generated at 12500, played at 12800).

Usage (machine with the NI device; nothing else using it)::

    python dev/ni_drop_check.py                       # 12.5 kHz x 4 ch x 60 s
    python dev/ni_drop_check.py --T=150 --fs=12500    # over-budget geometry
    python dev/ni_drop_check.py --device=0 --ch=4 --out=run.npz

Bench history (cDAQ-9174, 9234 + 9260, this PC): before the ring fix
the T=150 run showed 66 s of leading zeros, 45 % of reads failing and
the sweep at 1.9x its rate; after it, 0 overflows, 0 zeros, median
0.46 ms/chunk, slope exact. See the round doc for the full table.
"""
import sys
import time

import numpy as np

from pydvma import acquisition, options, streams


def _arg(name, default):
    for a in sys.argv[1:]:
        if a.startswith('--%s=' % name):
            return type(default)(a.split('=', 1)[1])
    return default


def main():
    T = _arg('T', 60.0)
    fs = _arg('fs', 12500.0)
    n_ch = _arg('ch', 4)
    dev = _arg('device', 0)
    out = _arg('out', '')
    f1, f2 = 10.0, 500.0

    log = []
    orig = streams.Recorder_NI_nidaqmx._read_and_process_chunk

    def instrumented(self):
        t0 = time.perf_counter()
        try:
            avail = int(self.audio_stream.in_stream.avail_samp_per_chan)
        except Exception:
            avail = -1
        ok = orig(self)
        log.append((t0, avail, time.perf_counter() - t0, ok))
        return ok

    streams.Recorder_NI_nidaqmx._read_and_process_chunk = instrumented

    iepe = [0.0] * n_ch
    if n_ch > 1:
        iepe[1] = 0.002      # the bench accelerometer sits on ai1
    s = options.MySettings(
        device_driver='nidaq', device_index=dev, fs=fs, channels=n_ch,
        stored_time=T, NI_mode='DAQmx_Val_PseudoDiff', VmaxNI=5.0,
        output_device_driver='nidaq', output_device_index=dev,
        output_channels=1, output_VmaxNI=3.0, iepe_excit_current_A=iepe)
    print('requested fs %g, chunk %d, stored_time %g s, %d ch'
          % (s.fs, s.chunk_size, s.stored_time, n_ch))
    _t, y = acquisition.signal_generator(s, sig='sweep', T=T, amplitude=0.5,
                                         f=[f1, f2])
    t_start = time.perf_counter()
    d = acquisition.log_data(s, test_name='ni_drop_check', output=y)
    wall = time.perf_counter() - t_start
    rec = streams.REC
    td = d.time_data_list[0]
    x = td.time_data
    fs_act = float(td.settings.fs)
    try:
        buf = rec.audio_stream.in_stream.input_buf_size
        print('DAQmx input buffer: %d samples = %.1f s' % (buf, buf / fs_act))
    except Exception:
        pass
    print('captured %s at fs=%g in %.1f s wall; overflows=%d'
          % (x.shape, fs_act, wall, getattr(rec, 'input_overflows', -1)))

    ok_all = True
    lg = np.array(log, dtype=float)
    if len(lg):
        t = lg[:, 0] - lg[0, 0]
        dur = lg[:, 2] * 1e3
        fails = int(np.sum(lg[:, 3] == 0))
        budget = s.chunk_size / fs_act * 1e3
        print('callback: %d reads, %d failed; per chunk median %.2f ms, '
              'p95 %.2f ms, max %.2f ms (budget %.2f ms); backlog max %.2f s'
              % (len(lg), fails, np.median(dur), np.percentile(dur, 95),
                 dur.max(), budget, lg[:, 1].max() / fs_act))
        ok_all &= fails == 0 and np.median(dur) < budget
    nz = np.flatnonzero(np.any(x != 0, axis=1))
    lead = int(nz[0]) if len(nz) else x.shape[0]
    print('leading exact-zero rows: %d (%.3f s)' % (lead, lead / fs_act))
    ok_all &= lead == 0

    win = int(fs_act * 0.25)
    n = x.shape[0] // win
    rms = np.sqrt(np.mean(x[:n * win, 0].reshape(n, win) ** 2, axis=1))
    quiet = rms < 0.05 * np.median(rms)
    if quiet.any():
        idx = np.flatnonzero(np.diff(np.concatenate(
            [[0], quiet.astype(int), [0]]))).reshape(-1, 2)
        runs = [(round(a * 0.25, 2), round((b - a) * 0.25, 2)) for a, b in idx]
        print('ai0 quiet runs (start s, length s):', runs)
        ok_all &= False
    else:
        print('ai0: driven throughout (no quiet runs)')

    seg = int(fs_act * 0.5)
    fpk, tt = [], []
    for k in range(x.shape[0] // seg):
        blk = x[k * seg:(k + 1) * seg, 0]
        if np.sqrt(np.mean(blk ** 2)) < 0.02:
            continue
        F = np.abs(np.fft.rfft(blk * np.hanning(seg)))
        f = np.fft.rfftfreq(seg, 1 / fs_act)
        fpk.append(f[np.argmax(F)])
        tt.append((k + 0.5) * 0.5)
    fpk, tt = np.array(fpk), np.array(tt)
    if len(fpk) > 4:
        slope = np.polyfit(tt, fpk, 1)[0]
        expected = (f2 - f1) / T
        step = np.diff(fpk)
        jumps = np.flatnonzero(np.abs(step - np.median(step)) > 3 * expected)
        print('sweep: %.3f Hz/s measured vs %.3f generated (%.3fx); '
              'frequency jumps at t = %s'
              % (slope, expected, slope / expected,
                 [round(tt[j], 1) for j in jumps][:12]))
        ok_all &= abs(slope / expected - 1) < 0.03 and len(jumps) == 0
    if out:
        np.savez(out, x=x, fs=fs_act, log=lg, T=T)
        print('saved', out)
    print('RESULT:', 'PASS' if ok_all else 'FAIL')
    try:
        rec.end_stream()
    except Exception:
        pass
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())
