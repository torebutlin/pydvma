"""Headless hardware check for an audio interface on WINDOWS.

The Windows counterpart to ``dev/u24xl_hw_check.py`` (macOS). Run it
after any change to the soundcard acquisition path::

    python dev/u24xl_win_check.py
    python dev/u24xl_win_check.py --device "U24XL"
    python dev/u24xl_win_check.py --source-vpp 3.0 --source-hz 1000

**No cable required.** Every check but the last is source-free — it uses
the device's own noise floor, its capability reports and its endpoint
volume — because which box is plugged in, and whether a generator is
attached, varies from session to session. The device defaults to
whatever PortAudio calls the default input, so it also works on a
machine with no ESI at all; ``--device`` picks another by substring.

Pass ``--source-vpp`` when a calibrated generator IS wired to the LEFT
input (Rigol DG1022Z, high-Z load) and the absolute-scale check runs
too. That is the one check needing a source, and the one that catches a
wrong ``VmaxSC``.

What it proves, beyond the generic capture path:

1. the device resolves to a characterised profile under EVERY host API,
   and a fixed-gain profile derives ``VmaxSC`` with no stated gain;
2. the sample-rate report is honest — no host API claims a rate the
   hardware cannot clock (Windows MME and DirectSound accept anything
   and let the audio engine resample, so ``max_input_fs`` used to report
   192 kHz for a 48 kHz box);
3. the endpoint volume is a DIGITAL gain, demonstrated with no source at
   all: the noise floor tracks the setting dB for dB, which an analogue
   gain ahead of the converter could not do;
4. pydvma PINS that control for the duration of a capture and puts the
   previous per-channel values back afterwards, so a stray Windows
   slider cannot rescale a log;
5. a stored ``device_index`` is re-resolved by name + host API, so a
   reordered enumeration cannot point a capture at the wrong hardware;
6. with ``--source-vpp``, the whole chain lands on the right ABSOLUTE
   voltage.

See ``dev/2026-08-12-u24xl-windows-bench.md`` for the measurements these
thresholds come from.
"""

import argparse
import sys

import numpy as np

try:
    import sounddevice as sd
except Exception as exc:                      # pragma: no cover - dev harness
    sys.exit('sounddevice unavailable: %s' % exc)

sys.path.insert(0, __file__.rsplit('dev', 1)[0])

import pydvma as dvma                                          # noqa: E402
from pydvma import (_soundcard_specs, _win_audio, options,     # noqa: E402
                    streams, verify)

PASS, FAIL = '  PASS', '  FAIL'
_results = []


def check(name, ok, detail=''):
    _results.append((name, bool(ok)))
    print('%s  %s%s' % (PASS if ok else FAIL, name,
                        ('  [%s]' % detail) if detail else ''))
    return ok


def host_api(index):
    try:
        return sd.query_hostapis(sd.query_devices()[index]['hostapi'])['name']
    except Exception:
        return None


def find_inputs(match):
    """Every input device index whose name contains ``match``."""
    out = []
    for i, dev in enumerate(sd.query_devices()):
        if dev['max_input_channels'] and match.lower() in dev['name'].lower():
            out.append(i)
    return out


def capture(index, fs, secs, channels=2, dtype='int32', extra=None):
    rec = sd.rec(int(secs * fs), samplerate=fs, channels=channels,
                 device=index, dtype=dtype, extra_settings=extra,
                 blocking=True)
    sd.wait()
    return np.asarray(rec, dtype=float) / 2.0 ** 31


def noise_dbfs(x, fs, ch, lo=20.0, hi=None):
    """Integrated noise in a band, dBFS, tone-free channels assumed."""
    v = x[:, ch] - x[:, ch].mean()
    n = len(v)
    w = np.hanning(n)
    P = np.abs(np.fft.rfft(v * w)) ** 2 * 2 / (n * np.sum(w ** 2))
    f = np.fft.rfftfreq(n, 1 / fs)
    m = (f >= lo) & (f < (hi if hi else 0.45 * fs))
    return 10 * np.log10(P[m].sum() + 1e-30)


def word_bits(index, fs=None, extra=None):
    """Effective word length PortAudio delivers, from the int32 LSBs.

    ``fs`` defaults to the device's own default rate, because a
    shared-mode WASAPI endpoint only accepts the rate the Sound control
    panel has it parked at and would otherwise refuse the probe.
    Returns ``None`` if the device cannot be opened at all.
    """
    if fs is None:
        fs = sd.query_devices()[index]['default_samplerate']
    for rate in (fs, sd.query_devices()[index]['default_samplerate'], 44100.0):
        try:
            raw = sd.rec(int(0.5 * rate), samplerate=rate, channels=2,
                         device=index, dtype='int32', extra_settings=extra,
                         blocking=True)
            sd.wait()
        except Exception:
            continue
        allbits = np.bitwise_or.reduce(
            np.abs(np.asarray(raw)).astype(np.int64).ravel())
        low = 0
        while low < 32 and not (allbits >> low) & 1:
            low += 1
        return 32 - low
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--device', default=None,
                    help='substring of the input device name (default: the '
                         'PortAudio default input)')
    ap.add_argument('--fs', type=float, default=48000.0)
    ap.add_argument('--source-vpp', type=float, default=None,
                    help='peak-to-peak volts of a calibrated generator on '
                         'the LEFT input, high-Z (enables the absolute-scale '
                         'check)')
    ap.add_argument('--source-hz', type=float, default=1000.0)
    args = ap.parse_args()

    if sys.platform != 'win32':
        sys.exit('This check is Windows-only; use dev/u24xl_hw_check.py on macOS.')

    if args.device:
        candidates = find_inputs(args.device)
        if not candidates:
            sys.exit('No input device matching %r.' % args.device)
        index = candidates[0]
    else:
        index = sd.default.device[0]
    name = sd.query_devices()[index]['name']
    neighbours = streams.all_soundcard_device_names()
    print('device [%d] %r on %s' % (index, name, host_api(index)))
    profile = _soundcard_specs.device_profile(name, neighbours=neighbours)
    print('profile: %s\n' % (profile['label'] if profile else 'UNCHARACTERISED'))

    # --- 1. identity and calibration -------------------------------
    twins = find_inputs(name[:24])
    apis = {host_api(i) for i in twins}
    check('device is visible under more than one host API',
          len(apis) > 1, '%d entries: %s' % (len(twins), ', '.join(sorted(a or '?' for a in apis))))

    if profile is not None:
        resolved = [i for i in twins
                    if _soundcard_specs.device_profile(
                        sd.query_devices()[i]['name'], neighbours=neighbours)
                    is not None]
        check('profile resolves on EVERY host-API entry',
              len(resolved) == len(twins),
              '%d/%d' % (len(resolved), len(twins)))

        fixed = _soundcard_specs.fixed_gain(name, neighbours=neighbours)
        if fixed:
            s = options.MySettings(device_driver='soundcard', device_index=index,
                                   channels=2, fs=args.fs)
            expected = _soundcard_specs.full_scale_volts(
                name, 0.0, 'line', neighbours=neighbours)
            check('fixed-gain profile derives VmaxSC with no stated gain',
                  abs(s.VmaxSC - expected) < 1e-6,
                  'VmaxSC %.4f V' % s.VmaxSC)
    else:
        print('  SKIP  profile checks (device not in _soundcard_specs)')

    # --- 2. rate honesty -------------------------------------------
    s = options.MySettings(device_driver='soundcard', device_index=index,
                           channels=2, fs=args.fs)
    native = streams.native_input_rates(s)
    check('native rate ladder is reported', bool(native), str(native))
    if native:
        for i in twins:
            si = options.MySettings(device_driver='soundcard', device_index=i,
                                    channels=2, fs=args.fs)
            top = streams.max_input_fs(si)
            if not check('max_input_fs is honest on %-20s' % host_api(i),
                         top <= max(native) + 1, '%g Hz' % top):
                print('        (a shared-mode host API accepting a rate the '
                      'hardware cannot clock — the engine resamples)')

    # --- 3. endpoint volume, and that it is DIGITAL ----------------
    eid, endpoint_name = _win_audio.find_device(name)
    if eid is None:
        print('  SKIP  endpoint-volume checks (no unambiguous endpoint for %r)'
              % name)
    else:
        rng = _win_audio.volume_range_db(eid)
        original = _win_audio.input_volume_db(eid)
        check('endpoint volume is reachable', bool(original),
              '%s, range %s' % (original, rng))
        if rng and rng[1] > 0.5:
            print('        NB range maxes at %+g dB — the slider can BOOST, '
                  'and post-ADC boost only clips.' % rng[1])

        if original:
            # Source-free digital-gain proof: with the gain applied
            # AFTER the converter, the device's own noise floor is
            # rescaled along with everything else, so it tracks the
            # setting dB for dB. An analogue gain ahead of the ADC could
            # not move the converter's own noise at all.
            #
            # This needs a 24-bit path. On a 16-bit host API the
            # quantisation floor (~-91 dBFS) sits only a few dB below
            # the converter's own, so attenuating runs into it almost
            # immediately and the floor stops tracking (measured: a
            # -20 dB setting moved an MME floor by only -7.7 dB). That
            # is the quantiser, not evidence about the gain.
            wide = [(word_bits(i) or 0, i) for i in twins]
            bits, best = max(wide) if wide else (0, index)
            if bits < 24:
                print('  SKIP  digital-gain proof (no 24-bit host API '
                      'available; a %d-bit quantisation floor masks the '
                      'device floor before it can track)' % bits)
            else:
                try:
                    step = -20.0 if (rng and rng[0] <= -20.0) else -6.0
                    _win_audio.set_input_volume_db(eid, 0.0)
                    base = noise_dbfs(capture(best, args.fs, 2.0), args.fs, 1)
                    _win_audio.set_input_volume_db(eid, step)
                    moved = noise_dbfs(capture(best, args.fs, 2.0), args.fs, 1)
                    delta = moved - base
                    check('noise floor tracks the gain => it is DIGITAL',
                          abs(delta - step) < 2.0,
                          'via %s (%d-bit): set %+g dB, floor moved %+.2f dB'
                          % (host_api(best), bits, step, delta))
                finally:
                    _win_audio.set_input_volume_db(eid, 0.0, channels=original)

            # --- 4. pydvma pins it, and restores it ----------------
            mis = {ch: (-9.0 if i % 2 == 0 else 4.5)
                   for i, ch in enumerate(sorted(original))}
            try:
                _win_audio.set_input_volume_db(eid, 0.0, channels=mis)
                st = options.MySettings(device_driver='soundcard',
                                        device_index=index, channels=2,
                                        fs=args.fs, stored_time=1)
                dvma.log_data(st)
                during = _win_audio.input_volume_db(eid)
                check('capture pins the control to 0 dB',
                      all(abs(v) <= 0.25 for v in during.values()), str(during))
                if streams.REC_SC is not None:
                    streams.REC_SC.end_stream()
                    streams.REC_SC = None
                after = _win_audio.input_volume_db(eid)
                check('mismatched per-channel values are restored exactly',
                      after == mis, '%s -> %s' % (mis, after))
            finally:
                _win_audio.set_input_volume_db(eid, 0.0, channels=original)

    # --- 5. word length per host API -------------------------------
    for i in twins:
        api = host_api(i)
        bits = word_bits(i)
        if bits is None:
            print('  SKIP  %s word length (device would not open)' % api)
            continue
        check('%-20s delivers a %d-bit word' % (api, bits), True,
              '' if bits >= 24 else 'throws away %d bits' % (24 - bits))

    # --- 6. device identity survives a reordered enumeration -------
    try:
        moved, note = streams.resolve_device_index(
            'soundcard', (index + 3) % len(sd.query_devices()), name,
            host_api(index))
        check('stored index is re-resolved by name + host API',
              moved == index, note or 'index already correct')
    except ValueError as exc:
        check('stored index is re-resolved by name + host API', False, str(exc))

    # --- 7. absolute scale (needs a calibrated source) -------------
    if args.source_vpp:
        vrms = args.source_vpp / (2 * np.sqrt(2))

        class ManualSource:
            """The generator is set by hand; expose the interface
            `verify_input_scaling` wants without commanding anything."""
            resource = 'manual source (%.3f Vpp @ %g Hz, high-Z)' % (
                args.source_vpp, args.source_hz)

            def set_sine(self, freq_hz, level_vrms):
                pass

            def output(self, on):
                pass

        st = options.MySettings(device_driver='soundcard', device_index=index,
                                channels=2, fs=args.fs)
        res = verify.verify_input_scaling(st, source=ManualSource(),
                                          freq=args.source_hz,
                                          level_vrms=vrms, duration=4.0,
                                          tol=0.05, channels=[0])
        check('absolute input scaling within 5%%', res[0]['ok'],
              '%+.2f dB' % res[0]['error_db'])
    else:
        print('  SKIP  absolute-scale check (pass --source-vpp with a '
              'calibrated generator on the left input)')

    passed = sum(ok for _, ok in _results)
    print('\n%d/%d checks passed' % (passed, len(_results)))
    return 0 if passed == len(_results) else 1


if __name__ == '__main__':
    sys.exit(main())
