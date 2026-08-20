"""Headless soundcard capture-integrity harness (round-12, 2026-08-20).

Feeds a known sine into the interface (any signal generator — a Rigol
DG1022Z was used for the round-12 bench) and phase-tracks the captured
tone: a dropped block of D samples appears as a step of ``-2*pi*f0*D/fs``
radians in the detrended demodulated phase, localised to the sample. The
method sees drops COMMON to both channels — which inter-channel coherence
cannot — and those common drops are exactly what destroys input->output
TF coherence on a resonant rig (the filter memory spans the excised
samples).

Wiring: generator CH1 -> interface input L at ``--f0`` Hz, CH2 -> input R
at ``--f1`` Hz (any level comfortably above the noise floor; 0.5 Vpp into
a line input works). Then::

    python dev/soundcard_drop_check.py --device "Analogue 1 + 2"
    python dev/soundcard_drop_check.py --device "Scarlett" --fs 3000 --seconds 30

Checks per case: leading exact-zero count (startup-latency bug),
``acquisition.LAST_CAPTURE_OVERFLOWS`` (the host's own drop report), and
the phase-step event count per channel (0 = no drops). A healthy
interface shows 0 / 0 / 0 and a residual of a few millirad.

Round-12 reference numbers (Scarlett 2i2 4th Gen, WDM-KS, Windows 11,
over RDP): BEFORE the ring-buffer/latency/priming fixes a 30 s x 48 kHz
capture carried 5-11 step events and ~5000 leading zeros; AFTER: 0 and 0
with residual p2p ~0.001 rad, matching a raw ``sd.rec`` control.
"""
import argparse
import time

import numpy as np
from scipy import signal

from pydvma import acquisition, options, streams


def find_input_device(name_substring):
    import sounddevice as sd
    for i, d in enumerate(sd.query_devices()):
        if name_substring.lower() in d['name'].lower() and d['max_input_channels'] > 0:
            return i, d['name']
    raise SystemExit('no input device matching %r' % name_substring)


def phase_steps(y, fs, f0, skip_s=0.3, threshold=0.05):
    """(n_events, resid_p2p): step events in the detrended demod phase."""
    n = len(y)
    t = np.arange(n) / fs
    z = y * np.exp(-2j * np.pi * f0 * t)
    sos = signal.butter(4, min(100.0, 0.4 * f0) / (fs / 2), output='sos')
    zf = signal.sosfiltfilt(sos, z.real) + 1j * signal.sosfiltfilt(sos, z.imag)
    phi = np.unwrap(np.angle(zf))
    i0 = int(skip_s * fs)
    phi, tt = phi[i0:-i0], t[i0:-i0]
    p = np.polyfit(tt, phi, 1)
    resid = phi - np.polyval(p, tt)
    gap = max(4, int(0.02 * fs))
    d = resid[gap:] - resid[:-gap]
    hits = np.abs(d) > threshold
    events = []
    i = 0
    while i < len(hits):
        if hits[i]:
            j = i
            while j < len(hits) and (hits[j] or (j - i) < gap):
                j += 1
            k = i + int(np.argmax(np.abs(d[i:j])))
            events.append((float(tt[k]), float(d[k])))
            i = j
        else:
            i += 1
    return events, float(resid.max() - resid.min())


def run_case(device_index, fs, seconds, tones, label):
    print('=' * 78)
    print('%s: fs=%g, %gs' % (label, fs, seconds))
    s = options.MySettings(device_driver='soundcard', device_index=device_index,
                           channels=2, fs=fs, stored_time=seconds)
    d = acquisition.log_data(s)
    td = d.time_data_list[0]
    y = np.asarray(td.time_data)
    fs_out = float(td.settings.fs)
    ok = True
    for c in range(min(2, y.shape[1])):
        col = y[:, c]
        nz = np.flatnonzero(col != 0.0)
        lead = int(nz[0]) if nz.size else len(col)
        f0 = tones[c]
        line = '  ch%d: leading zeros %d' % (c, lead)
        if f0 < 0.4 * fs_out:  # tone survives this rate
            events, p2p = phase_steps(col.astype(float), fs_out, f0)
            line += ', %d step events (f0=%g, resid p2p %.4f rad)' % (
                len(events), f0, p2p)
            for et, ed in events[:8]:
                line += '\n      step at t=%.3fs %+0.3f rad' % (et, ed)
            ok = ok and not events
        print(line)
        ok = ok and lead == 0
    print('  overflows reported: %d' % acquisition.LAST_CAPTURE_OVERFLOWS)
    ok = ok and acquisition.LAST_CAPTURE_OVERFLOWS == 0
    print('  %s' % ('PASS' if ok else 'FAIL'))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--device', required=True,
                    help='input-device name substring (e.g. "Scarlett")')
    ap.add_argument('--f0', type=float, default=1000.0,
                    help='generator tone on input L, Hz (default 1000)')
    ap.add_argument('--f1', type=float, default=1700.0,
                    help='generator tone on input R, Hz (default 1700)')
    ap.add_argument('--fs', type=float, default=None,
                    help='run ONLY this rate (default: 48000 long+short, 3000 long)')
    ap.add_argument('--seconds', type=float, default=30.0)
    args = ap.parse_args()

    idx, name = find_input_device(args.device)
    print('device %d: %s' % (idx, name))
    tones = (args.f0, args.f1)

    results = []
    if args.fs is not None:
        results.append(run_case(idx, args.fs, args.seconds, tones,
                                'requested case'))
    else:
        results.append(run_case(idx, 48000, args.seconds, tones, 'native long'))
        results.append(run_case(idx, 48000, 2, tones, 'native short'))
        results.append(run_case(idx, 3000, args.seconds, tones,
                                'sub-native (capture high + decimate)'))
    try:
        streams.REC.end_stream()
    except Exception:
        pass
    print('=' * 78)
    print('%d/%d cases clean' % (sum(results), len(results)))
    raise SystemExit(0 if all(results) else 1)


if __name__ == '__main__':
    main()
