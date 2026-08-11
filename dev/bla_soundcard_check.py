"""Headless BLA smoke test on a soundcard with a digital loopback.

Designed for the Scarlett 2i2 4th Gen on the Mac: inputs 3/4 (0-indexed
channels 2/3) are a digital loopback of outputs 1/2, so a 2-excitation
MISO BLA run can be exercised end-to-end with no cables and no one in
the room. The loopback channels serve as BOTH the measured drives
(x_channels=[2, 3]) AND two of the responses, so the recovered G matrix
must come out as the 2x2 identity on the loopback rows (0 dB diagonal,
deep-null off-diagonal crosstalk) with sigma_NL at the resolution floor.
The analog inputs (channels 0/1, nothing plugged in) ride along as
noise-floor responses.

Run:  python3 dev/bla_soundcard_check.py
Exit code 0 = all checks pass. Prints a human-readable table either way.
"""

import sys
import numpy as np

sys.path.insert(0, '.')
import pydvma as dvma                                     # noqa: E402

FS = 48000
N = 4096            # period samples -> df = FS/N ~ 11.7 Hz
K1, K2 = 6, 400     # ~70 Hz .. ~4.7 kHz
M = 4
P = 3
T_TRANS = 2
N_EXC = 2
AMP_RMS = 0.1
SEED = 20260810

PASS = []


def check(name, ok, detail=''):
    PASS.append(bool(ok))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name,
                           (' — %s' % detail) if detail else ''))


def find_scarlett():
    import sounddevice as sd
    for i, d in enumerate(sd.query_devices()):
        if 'Scarlett' in d['name'] and d['max_input_channels'] >= 4 \
                and d['max_output_channels'] >= 2:
            return i
    raise SystemExit('No Scarlett with 4 in / 2 out found — is it plugged in?')


def main():
    dev = find_scarlett()
    print('Scarlett at sounddevice index %d' % dev)

    capture_s = (T_TRANS + P) * N / FS
    settings = dvma.MySettings(
        device_driver='soundcard', device_index=dev, channels=4,
        fs=FS, stored_time=capture_s + 0.1,
        output_device_driver='soundcard', output_device_index=dev,
        output_channels=N_EXC, output_fs=FS)

    base = dict(n_samples=N, k1=K1, k2=K2, p_periods=P, t_periods=T_TRANS,
                seed=SEED, n_exc=N_EXC, amp_rms=AMP_RMS)

    print('Capturing %d x %d = %d runs of %.2f s ...'
          % (M, N_EXC, M * N_EXC, capture_s))
    captures = []
    for m in range(M):
        for e in range(N_EXC):
            spec = dict(base, m=m, e=e)
            _, y = dvma.multisine_generator(settings, spec)
            ds = dvma.log_data(settings, output=y)
            td = ds.time_data_list[0]
            n_need = (T_TRANS + P) * N
            n_got = np.asarray(td.time_data).shape[0]
            if n_got < n_need:
                raise SystemExit('capture %d/%d too short: %d < %d samples'
                                 % (m, e, n_got, n_need))
            captures.append(td)

    run_spec = {
        'multisine': dict(base, M=M),
        'x_mode': 'measured',
        'x_channels': [2, 3],          # loopback of outputs 1/2
        'resp_channels': [0, 1, 2, 3],  # analog (open) + loopback
        'fs': float(FS),
    }
    tfs = dvma.calculate_bla(captures, run_spec)

    # tfs[q].tf_data is (n_k, n_resp) for excitation q; resp order [0,1,2,3].
    print('\nResults (medians over excited lines):')
    for q, tf in enumerate(tfs):
        g = np.asarray(tf.tf_data)
        s_nl = np.asarray(tf.bla_sigma_nl)
        s_n = np.asarray(tf.bla_sigma_n)
        loop_diag = 2 + q          # resp column that IS this excitation
        loop_x = 2 + (1 - q)       # the other loopback column
        diag = float(np.median(np.abs(g[:, loop_diag])))
        cross = float(np.median(np.abs(g[:, loop_x])))
        opench = float(np.median(np.abs(g[:, 0:2])))
        nl_med = float(np.median(s_nl[:, loop_diag]))
        n_med = float(np.median(s_n[:, loop_diag]))
        print(' q%d: |G|diag=%.6f  |G|cross=%.3g  |G|open=%.3g  '
              'sigmaNL=%.3g  sigmaN=%.3g'
              % (q, diag, cross, opench, nl_med, n_med))
        check('q%d loopback diagonal ~ unity (0.99..1.01)' % q,
              0.99 < diag < 1.01, '%.6f' % diag)
        check('q%d loopback crosstalk < -40 dB' % q,
              cross < 0.01, '%.3g' % cross)
        check('q%d open-input response < -30 dB' % q,
              opench < 0.032, '%.3g' % opench)
        check('q%d sigma_NL on loopback < -40 dB re G' % q,
              nl_med < 0.01 * max(diag, 1e-12), '%.3g' % nl_med)

    n = sum(PASS)
    print('\n%d/%d checks passed' % (n, len(PASS)))
    return 0 if n == len(PASS) else 1


if __name__ == '__main__':
    sys.exit(main())
