"""Headless hardware check for the Audient iD44 (MkII) on macOS.

Run this after any change to the soundcard acquisition path that the
iD44 relies on (per-channel gain, the duplex stimulus path, the rate pin)::

    python dev/id44_hw_check.py
    python dev/id44_hw_check.py --daw-thru-channel 2 --expect-gain 50.46

WIRING. Nothing is needed for the basic checks: the iD44's inputs 21-22
are its own digital LOOPBACK of DAW playback 1+2, so a tone sent there
must come back exactly. ``--daw-thru-channel N`` needs a cable from line
output 3 to input N, with outputs 3+4 set to DAW THRU in the iD app and
the iD mixer's inputs muted (otherwise the input tone reaches the
speakers). The line outputs run +18 dBu at 0 dBFS (manual), so that path
is an electrical reference for the input gain, the only one available
without a calibrator: measured 2026-11-06 at +50.46 dB into input 2, line
mode, knob at its top stop (``dev/2026-11-06-id44-bench.md``).

What it proves:

1. the device is found by name and resolves to the ``audient_id44``
   profile, per-channel gain, 4 analogue + 16 optical + 2 loopback;
2. its native rate ladder holds 48 kHz and the nominal rate IS 48 kHz.
   The check never changes the rate unless ``--rate`` is given: a rate
   change restarts the iD mixer and clicks the outputs;
3. the input stream is 24-bit;
4. the loopback is exact: DAW 1 and 2 at -70 dBFS come back on inputs
   21 and 22 within 0.01 dB, on the right channel each;
5. (``--daw-thru-channel N``) the tone on line output 3 arrives on input
   N at a steady gain, linear over -80/-70/-60 dBFS within 0.05 dB, and
   within 0.05 dB of ``--expect-gain`` when given;
6. (``--daw-thru-channel N --line-gain-db G``) the full pydvma path,
   ``acquisition.log_data`` with the stimulus played through the capture
   stream itself, reads input N in VOLTS within 1 dB of the voltage the
   line output drove, using only the profile and the stated gain. The
   iD44 is selected by index here: choosing it by name builds the device
   list, which probes every other device's rate ladder by opening test
   streams on it.

Only one stream is ever open on the iD44 (CoreAudio refuses a second one
with -10863 while the first runs), and nothing here opens any other
device. Levels stay at or below -60 dBFS on every output.
"""

import argparse
import sys
import time

import numpy as np

try:
    import sounddevice as sd
except Exception as exc:                      # pragma: no cover - dev harness
    sys.exit('sounddevice unavailable: %s' % exc)

from pydvma import _coreaudio, _soundcard_specs, acquisition, options

if not _coreaudio.available():
    sys.exit('CoreAudio unavailable: this check is macOS-only.')


DEVICE_MATCH = 'Audient iD44'
PROFILE_KEY = 'audient_id44'
LOOPBACK_INPUTS = (21, 22)          # 1-based input numbers
LOOPBACK_SOURCES = (1, 2)           # DAW playback channels they carry
DAW_THRU_OUTPUT = 3                 # line output 3, DAW THRU
LINE_OUT_DBU = 18.0                 # line outputs: +18 dBu at 0 dBFS
MAX_LEVEL_DBFS = -60.0              # the loudest tone this check sends
DBU_VRMS = 0.7746
SINE_FS_DB = 20 * np.log10(np.sqrt(2))   # +3.01: rms re 1.0 vs re a FS sine

PASS, FAIL = '  PASS', '  FAIL'
_results = []


def check(name, ok, detail=''):
    """Record and print one PASS/FAIL line."""
    _results.append((name, bool(ok)))
    print('%s  %s%s' % (PASS if ok else FAIL, name,
                        ('  [%s]' % detail) if detail else ''))
    return ok


def db(value):
    """20 log10 with a floor, for printing levels."""
    return 20 * np.log10(max(float(value), 1e-15))


def find_device():
    """Return (sounddevice index, CoreAudio id, name) of the iD44."""
    index, name = None, None
    for i, dev in enumerate(sd.query_devices()):
        if DEVICE_MATCH.lower() in dev['name'].lower() \
                and dev['max_input_channels'] >= 22:
            index, name = i, dev['name']
            break
    found = _coreaudio.find_device(DEVICE_MATCH)
    device_id = found[0] if found else None
    return index, device_id, name


def tone(n, fs, level_dbfs, freq, fade=0.05):
    """A sine at ``level_dbfs`` rms (re a full-scale sine), faded in/out."""
    if level_dbfs > MAX_LEVEL_DBFS + 1e-9:
        raise ValueError('refusing a tone above %g dBFS' % MAX_LEVEL_DBFS)
    t = np.arange(n) / fs
    sig = np.sqrt(2) * 10 ** (level_dbfs / 20) * np.sin(2 * np.pi * freq * t)
    r = int(fade * fs)
    sig[:r] *= np.linspace(0, 1, r)
    sig[-r:] *= np.linspace(1, 0, r)
    return sig


def play_record(index, fs, n_in, n_out, tones, secs):
    """Play ``tones`` {output: (dBFS, Hz)} and record every input, in ONE
    duplex stream. Returns (inputs (n, n_in) float64, status flags seen)."""
    n = int(secs * fs)
    buf = np.zeros((n, n_out), 'float32')
    for out, (level, freq) in tones.items():
        buf[:, out - 1] = tone(n, fs, level, freq)
    blocks, pos, flags = [], [0], []

    def callback(indata, outdata, frames, _time, status):
        if status:
            flags.append(str(status))
        blocks.append(indata.copy())
        a = pos[0]
        b = min(a + frames, n)
        outdata[:b - a] = buf[a:b]
        outdata[b - a:] = 0
        pos[0] = b

    with sd.Stream(device=(index, index), channels=(n_in, n_out),
                   samplerate=fs, dtype='float32', latency='high',
                   callback=callback):
        time.sleep(secs + 0.4)
    return np.concatenate(blocks).astype(float), flags


def lockin_rms(x, fs, freq):
    """Rms of the ``freq`` component of ``x`` (re a full-scale sine)."""
    t = np.arange(len(x)) / fs
    return 2 * np.abs(np.mean(x * np.exp(-2j * np.pi * freq * t))) / np.sqrt(2)


def tone_span(x, fs, freq, block=0.02, trim=0.25):
    """Sample range of the steady part of a tone in ``x``.

    A duplex stream's start-up delay varies from run to run by a few
    hundred ms, so a fixed window can catch silence (a -70 dBFS run read
    0.47 dB low that way). This finds where the tone is above half its
    peak level, in ``block``-second lock-in blocks, and trims ``trim``
    seconds off each end, clear of the fades.
    """
    n = int(block * fs)
    t = np.arange(n) / fs
    ref = np.exp(-2j * np.pi * freq * t)
    amps = np.array([np.abs(np.mean(x[i:i + n] * ref))
                     for i in range(0, len(x) - n, n)])
    on = np.flatnonzero(amps >= 0.5 * amps.max())
    a = (on[0] * n) + int(trim * fs)
    b = (on[-1] + 1) * n - int(trim * fs)
    return (a, b) if b - a > int(0.5 * fs) else (0, len(x))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--rate', type=float, default=None,
                    help='pin this nominal rate for the run (restored '
                         'after); without it the rate is never changed')
    ap.add_argument('--daw-thru-channel', type=int, default=None,
                    help='input number cabled from line output 3')
    ap.add_argument('--expect-gain', type=float, default=None,
                    help='expected output-3 to input-N gain in dB')
    ap.add_argument('--line-gain-db', type=float, default=None,
                    help='the stated line gain on input N, for the '
                         'pydvma-path volts check')
    args = ap.parse_args()

    index, device_id, name = find_device()
    if not check('iD44 found by name', index is not None
                 and device_id is not None,
                 'sounddevice %s, CoreAudio %s, %r' % (index, device_id,
                                                      name)):
        return 1
    info = sd.query_devices(index)
    n_in, n_out = info['max_input_channels'], info['max_output_channels']

    profile = _soundcard_specs.device_profile(name)
    roles = _soundcard_specs.channel_roles(name, n_in)
    check('profile resolves', profile is not None
          and profile.get('label') == 'Audient iD44'
          and _soundcard_specs.per_channel_gain(name),
          'per-channel gain, preferred fs %s'
          % _soundcard_specs.preferred_fs(name))
    check('channel roles 4 analogue + 16 optical + 2 loopback',
          roles is not None
          and list(roles).count('analogue') == 4
          and list(roles).count('optical') == 16
          and list(roles).count('loopback') == 2
          and [i + 1 for i, r in enumerate(roles) if r == 'loopback']
          == list(LOOPBACK_INPUTS),
          '%d inputs, %d outputs' % (n_in, n_out))

    ladder = _coreaudio.native_rates(device_id)
    check('native rates include 48 kHz', 48000.0 in [float(r) for r in ladder],
          'ladder %s' % [int(r) for r in ladder])

    before = _coreaudio.get_nominal_rate(device_id)
    target = float(args.rate) if args.rate else 48000.0
    if args.rate is None and before != 48000.0:
        check('nominal rate is 48 kHz', False,
              'it is %g; run with --rate 48000 to set it (restarts the '
              'iD mixer)' % before)
        return summary()
    check('nominal rate', True, '%g Hz%s' % (
        before, '' if args.rate is None else ', pinning %g' % target))

    with _coreaudio.pinned_rate(device_id, target):
        fs = _coreaudio.get_nominal_rate(device_id)
        check('nominal rate during the run', fs == target, '%g Hz' % fs)

        # 3 + 4: loopback, opened at the device's own format
        secs = 4.0
        freqs = {LOOPBACK_SOURCES[0]: 997.0, LOOPBACK_SOURCES[1]: 1499.0}
        level = -70.0
        x, flags = play_record(index, fs, n_in, n_out,
                               {o: (level, f) for o, f in freqs.items()},
                               secs)
        bits = _coreaudio.input_bit_depth(device_id)
        check('input stream is 24-bit', bits == 24, '%s bit' % bits)
        check('no stream over/underflow', not flags,
              ', '.join(sorted(set(flags))) or 'none')
        for inp, src in zip(LOOPBACK_INPUTS, LOOPBACK_SOURCES):
            a, b = tone_span(x[:, inp - 1], fs, freqs[src])
            seg = x[a:b, inp - 1]
            mine = db(lockin_rms(seg, fs, freqs[src]))
            other = [s for s in LOOPBACK_SOURCES if s != src][0]
            leak = db(lockin_rms(seg, fs, freqs[other]))
            # Anything else on the loopback (it carries a MIX when the iD
            # app's loop-back source is not DAW 1+2, e.g. a mic's room
            # rumble) limits the exactness check, so name it.
            t = np.arange(len(seg)) / fs
            tones = sum(2 * np.real(np.mean(seg * np.exp(-2j * np.pi * f * t))
                                    * np.exp(2j * np.pi * f * t))
                        for f in freqs.values())
            rest = db(np.sqrt(np.mean((seg - tones) ** 2)))
            hint = ('' if rest < -100 else
                    '; it carries other signals too, %.0f dBFS rms: set the '
                    "iD app's loop-back source to DAW 1+2" % rest)
            check('loopback input %d carries DAW %d exactly' % (inp, src),
                  abs(mine - level) <= 0.01 and leak < level - 60,
                  '%+.3f dB, the other channel %.1f dBFS%s'
                  % (mine - level, leak, hint))

        # 5: DAW THRU into an analogue input
        gain_70 = None
        if args.daw_thru_channel:
            ch = args.daw_thru_channel
            gains = {}
            for lvl in (-80.0, -70.0, -60.0):
                x, flags = play_record(index, fs, n_in, n_out,
                                       {DAW_THRU_OUTPUT: (lvl, 997.0)}, secs)
                a, b = tone_span(x[:, ch - 1], fs, 997.0)
                got = db(lockin_rms(x[a:b, ch - 1], fs, 997.0))
                gains[lvl] = got - lvl
                print('       output %d at %+.0f dBFS -> input %d %+.2f dBFS'
                      '  gain %+.2f dB'
                      % (DAW_THRU_OUTPUT, lvl, ch, got, gains[lvl]))
            spread = max(gains.values()) - min(gains.values())
            gain_70 = gains[-70.0]
            check('DAW THRU gain linear over -80..-60 dBFS', spread <= 0.05,
                  'spread %.3f dB' % spread)
            if args.expect_gain is not None:
                check('DAW THRU gain %+.2f dB' % args.expect_gain,
                      abs(gain_70 - args.expect_gain) <= 0.05,
                      'measured %+.2f dB' % gain_70)

    after = _coreaudio.get_nominal_rate(device_id)
    check('nominal rate back to where it was', after == before,
          '%g Hz' % after)

    # 6: the full pydvma path in volts (opens its own single stream)
    if args.daw_thru_channel and args.line_gain_db is not None:
        ch = args.daw_thru_channel
        fs = 48000.0
        modes = ['mic'] * 4
        modes[ch - 1] = 'line'
        gain = [None] * 4
        gain[ch - 1] = float(args.line_gain_db)
        # By index, not by name: resolving a NAME builds the device list,
        # which probes every other device's rate ladder, and on macOS each
        # probe opens a test stream (it would disturb another program's
        # stream on, say, a Scarlett).
        settings = options.MySettings(
            device_driver='soundcard', device_index=index, channels=4,
            fs=fs, stored_time=4.0,
            input_mode=modes, input_gain_db=gain,
            output_device_driver='soundcard', output_channels=DAW_THRU_OUTPUT,
            output_fs=fs)
        n = int(settings.stored_time * fs)
        lvl = -70.0
        out = np.zeros((n, DAW_THRU_OUTPUT))
        out[:, DAW_THRU_OUTPUT - 1] = tone(n, fs, lvl, 997.0)
        data = acquisition.log_data(settings, output=out)
        td = data.time_data_list[-1]
        a, b = tone_span(td.time_data[:, ch - 1], fs, 997.0)
        got_v = lockin_rms(td.time_data[a:b, ch - 1], fs, 997.0)
        # The levels here are rms re a digital 1.0, so a full-scale sine
        # is -3.01 dB on this scale and +18 dBu = 0 dBFS (a full-scale
        # sine) puts a digital rms of 1.0 at +21.01 dBu.
        sent_v = DBU_VRMS * 10 ** ((LINE_OUT_DBU + SINE_FS_DB + lvl) / 20)
        vmax = settings.input_vmax_channels()
        check('pydvma reads input %d in volts' % ch,
              settings.channels_in_volts()[ch - 1]
              and abs(db(got_v) - db(sent_v)) <= 1.0,
              'read %.4g V rms, line output drove %.4g V rms (%+.2f dB); '
              'full scale %.4g V peak' % (got_v, sent_v,
                                          db(got_v) - db(sent_v),
                                          vmax[ch - 1]))
        if gain_70 is not None:
            implied = LINE_OUT_DBU - gain_70
            stated = 20 * np.log10(vmax[ch - 1] / np.sqrt(2) / DBU_VRMS)
            print('       full scale: measured %.2f dBu, profile %.2f dBu '
                  '(%+.2f dB)' % (implied, stated, stated - implied))
        check('rate still %g after the pydvma capture' % before,
              _coreaudio.get_nominal_rate(device_id) == before)

    return summary()


def summary():
    """Print the tally and return the exit code."""
    bad = [n for n, ok in _results if not ok]
    print('\n%d/%d passed' % (len(_results) - len(bad), len(_results)))
    for n in bad:
        print('  failed: %s' % n)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
