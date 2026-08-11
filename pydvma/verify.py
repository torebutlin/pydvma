# -*- coding: utf-8 -*-
"""Verify absolute input-chain scaling against a source of known level.

Every other acquisition check in pydvma is a *relative* sanity check —
clipping thresholds, coherence, level meters — none of them can catch a
wrong physical gain knob, because they never compare against a level
known independently of the digitiser. `verify_input_scaling` closes
that gap: it plays or commands a tone of a KNOWN RMS voltage, measures
what actually comes back through the whole analogue chain (preamp /
input range / ADC), and reports the ratio. See the "Input-scaling
verification tool" item in ``TODO.md`` for the design motivation (the
3C6 lab's ``check_setup`` level meter checks levels against a target
band but cannot verify absolute scaling without a known source).

Two known-source options:

- ``source='loopback'`` — pydvma generates the tone itself and plays it
  out the configured AO device, wired back to an AI input (NI
  ``ao0 -> ai0`` BNC loopback, or a sound card's line/digital loopback).
  On an NI device the AO voltage is hardware-calibrated, so this
  verifies ABSOLUTE input scaling through a real physical cable — no
  extra kit needed. On a sound card the analogue output level depends
  on an uncalibrated front-panel/OS volume knob, so loopback there only
  verifies chain CONSISTENCY, not absolute scaling (a warning is
  printed, not a refusal — see `_run_loopback_capture`).
- ``source=<instrument>`` — an external, independently-calibrated
  source such as `RigolDG1022Z`, commanded over SCPI. This is required
  for a sound card whose loopback is DIGITAL (e.g. the Scarlett 2i2's
  inputs 3/4): a digital loopback copies the output stream pre-preamp,
  so it cannot see the analogue input gain at all — an external source
  driven into a real analogue input is the only way to check it.

Per-channel attenuators, transducer sensitivities and calibration
factors are out of scope: this checks the digitiser chain in volts,
upstream of `MySettings.channel_sensitivities`.
"""

import copy
import time

import numpy as np
import scipy.signal as signal

from . import acquisition

try:
    import pyvisa
except ImportError:
    pyvisa = None


_PYVISA_IMPORT_MESSAGE = (
    "RigolDG1022Z needs the optional 'pyvisa' package (plus the "
    "'pyvisa-py' pure-Python VISA backend, which avoids NI-VISA -- "
    "patchy on macOS, especially Apple Silicon). Install with:\n"
    "    pip install pyvisa pyvisa-py\n"
    "See the DG1022Z SCPI notes for USB setup (libusb, resource "
    "strings) if list_resources() comes back empty."
)


class RigolDG1022Z:
    """Minimal SCPI wrapper for a Rigol DG1022Z (or compatible DG1000Z)
    function generator, used as a known-level source for
    `verify_input_scaling`.

    Talks VISA via ``pyvisa`` (``pyvisa-py`` backend, no NI-VISA
    dependency). Every method issues plain SCPI writes and is safe to
    call with nothing connected except the instrument itself — there is
    no polling loop or blocking wait beyond the VISA I/O timeout.

    Amplitude is always commanded in **Vrms**, not Vpp: the DG1022Z
    defaults to Vpp, but its ``:SOURn:VOLT:UNIT`` command accepts
    ``VRMS`` directly (confirmed in the DG1022Z working notes, section
    3), so `set_sine` switches the unit mode explicitly rather than
    converting via the x2*sqrt(2) Vpp<->Vrms factor. That keeps the
    amplitude math (and the number visible on the instrument's own
    display) in the same units end to end, with no extra place for an
    RMS/peak mixup to creep in.

    Use as a context manager to guarantee the output relay is switched
    OFF when done, even if the code in between raises:

        >>> with RigolDG1022Z() as gen:              # doctest: +SKIP
        ...     gen.set_sine(997, 0.1)
        ...     gen.output(True)
        ...     ...
        # output is OFF here, on ANY exit path
    """

    def __init__(self, resource=None):
        """Open a VISA session to a Rigol DG1022Z.

        Args:
            resource (str or None): Explicit VISA resource string (e.g.
                ``'USB0::0x1AB1::0x0642::DG1ZA000000::INSTR'``). ``None``
                (default) auto-discovers via ``pyvisa``'s
                ``list_resources()`` and picks the first resource string
                containing ``'DG1'``. Raises ``ValueError`` naming every
                resource that WAS found (so a wrong-but-present
                instrument is easy to spot) if none match.

        Raises ``ImportError`` with pip-install guidance if ``pyvisa``
        is not installed, and ``ValueError`` if auto-discovery finds no
        ``DG1*`` resource.
        """
        if pyvisa is None:
            raise ImportError(_PYVISA_IMPORT_MESSAGE)

        self._rm = pyvisa.ResourceManager('@py')
        self._inst = None

        if resource is None:
            found = list(self._rm.list_resources())
            matches = [r for r in found if 'DG1' in r]
            if not matches:
                raise ValueError(
                    'No Rigol DG1xxx auto-discovered over VISA. Resources '
                    'found: {}. Check the USB cable is in the rear-panel '
                    '"Device" port (not the front "Host" port), then pass '
                    'resource=... explicitly.'.format(found)
                )
            resource = matches[0]

        self.resource = resource
        self._inst = self._rm.open_resource(resource)
        self._inst.timeout = 5000

    def set_sine(self, freq_hz, vrms, channel=1):
        """Command a sine wave at ``freq_hz`` Hz, ``vrms`` V RMS, on
        ``channel``.

        Sends, in order (order matters: the DG1022Z notes warn that
        changing waveform shape while in Vrms mode recalculates the
        amplitude, so the shape is set first, then the level) with
        ``n`` = ``channel``:

        - ``:SOURn:FUNC SIN``
        - ``:OUTPn:LOAD INF`` — assume a high-impedance load. A DAQ or
          scope input IS high-Z; leaving the DG1022Z's default 50 ohm
          load assumption would make it report (and the RMS-mode math
          compute) exactly double the voltage that actually appears
          across a high-Z load, per the notes' load-mismatch gotcha.
        - ``:SOURn:VOLT:UNIT VRMS``
        - ``:SOURn:VOLT <vrms>``
        - ``:SOURn:VOLT:OFFS 0``
        - ``:SOURn:FREQ <freq_hz>``

        Args:
            freq_hz (float): Sine frequency in Hz.
            vrms (float): Sine RMS amplitude in volts.
            channel (int): DG1022Z output channel, 1 or 2 (default 1).
        """
        ch = int(channel)
        self._inst.write(':SOUR{}:FUNC SIN'.format(ch))
        self._inst.write(':OUTP{}:LOAD INF'.format(ch))
        self._inst.write(':SOUR{}:VOLT:UNIT VRMS'.format(ch))
        self._inst.write(':SOUR{}:VOLT {}'.format(ch, float(vrms)))
        self._inst.write(':SOUR{}:VOLT:OFFS 0'.format(ch))
        self._inst.write(':SOUR{}:FREQ {}'.format(ch, float(freq_hz)))

    def output(self, on, channel=1):
        """Switch ``channel``'s output relay ON or OFF.

        Sends ``:OUTPn:STAT ON`` or ``:OUTPn:STAT OFF`` (``n`` =
        ``channel``).

        Args:
            on (bool): ``True`` enables the output, ``False`` disables it.
            channel (int): DG1022Z output channel, 1 or 2 (default 1).
        """
        ch = int(channel)
        state = 'ON' if on else 'OFF'
        self._inst.write(':OUTP{}:STAT {}'.format(ch, state))

    def close(self):
        """Return the front panel to local control and close the VISA
        session.

        Sends ``:SYST:LOCal`` — SCPI control locks the front panel out
        until this is sent (or the instrument's own Local key is
        pressed) — before closing the underlying VISA resource. Safe to
        call more than once.
        """
        if self._inst is None:
            return
        try:
            self._inst.write(':SYST:LOCal')
        except Exception:
            pass
        try:
            self._inst.close()
        except Exception:
            pass
        self._inst = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Switch the output OFF and close, on every exit path
        including an exception — a bench source left running unattended
        is exactly the failure mode this class exists to avoid."""
        try:
            self.output(False)
        finally:
            self.close()
        return False


def _measure_tone_vrms(x, fs, freq, bin_neighbours=2):
    """Robust RMS amplitude of a single tone in ``x``, via a windowed
    periodogram, largely immune to broadband noise and other tones.

    Windows ``x`` with a periodic Hann window, computes the rFFT, and
    sums POWER over the ``2 * bin_neighbours + 1`` bins around the
    tone's expected bin — capturing spectral leakage from a tone that
    doesn't land exactly on a bin centre, without needing the capture
    to be an exact integer number of periods. The result is converted
    back to an RMS voltage via Parseval's theorem, normalising by
    ``sum(window**2)`` (the window's power gain): for ANY window and
    ANY tone frequency, the true windowed signal ENERGY equals
    ``(1/N) * (bin sum, with the doubling one-sided rfft implies)``, so
    dividing out the window's own power contribution recovers the
    tone's mean-square value exactly once (nearly) all of its leaked
    energy sits inside the summed neighbourhood — which a handful of
    bins either side comfortably covers for a Hann window's fast-decaying
    sidelobes. Because only a few bins around the tone are summed,
    broadband noise (spread over ALL bins) and any other tone more than
    ``bin_neighbours`` bins away contribute a negligible fraction of the
    total noise/other-tone power to the estimate.

    Args:
        x (np.ndarray): 1D real time-domain samples, in volts.
        fs (float): Sample rate of ``x`` in Hz.
        freq (float): Expected tone frequency in Hz.
        bin_neighbours (int): Bins summed either side of the tone's
            nearest bin (default 2, i.e. a 5-bin neighbourhood).

    Returns the estimated RMS amplitude of the tone at ``freq``, in the
    same units as ``x`` (volts).
    """
    x = np.asarray(x, dtype=float).ravel()
    N = x.shape[0]
    w = signal.windows.get_window('hann', N)
    X = np.fft.rfft(w * x)

    k0 = int(round(float(freq) * N / float(fs)))
    lo = max(k0 - int(bin_neighbours), 1)
    hi = min(k0 + int(bin_neighbours), len(X) - 2)
    if hi < lo:
        # Degenerate (N tiny relative to bin_neighbours); fall back to
        # whatever single bin is in range rather than raising.
        lo = hi = max(1, min(k0, len(X) - 2))

    tone_energy = (2.0 / N) * np.sum(np.abs(X[lo:hi + 1]) ** 2)
    return float(np.sqrt(tone_energy / np.sum(w ** 2)))


def _verdict(channel, measured_vrms, expected_vrms, tol):
    """Build one channel's `verify_input_scaling` result dict.

    Args:
        channel (int): Channel index the measurement was taken on.
        measured_vrms (float): Tone RMS amplitude measured on ``channel``,
            in volts.
        expected_vrms (float): Known/commanded RMS amplitude, in volts.
        tol (float): Fractional tolerance on ``measured/expected``; the
            channel is ``ok`` when ``abs(ratio - 1) <= tol``.

    Returns a dict ``{'channel', 'measured_vrms', 'expected_vrms',
    'ratio', 'error_db', 'ok'}``. ``error_db`` is
    ``20 * log10(measured / expected)`` -- positive means the channel
    reads HIGH (e.g. the gain is set higher than expected), negative
    means it reads LOW.
    """
    ratio = measured_vrms / expected_vrms if expected_vrms else float('nan')
    # Floor before log10 so an exact-zero (or pathological) measurement
    # produces a large-but-finite negative error_db instead of -inf,
    # which would otherwise still correctly fail `ok` but complicates
    # formatting/printing for no benefit.
    error_db = 20.0 * np.log10(max(ratio, 1e-15))
    ok = abs(ratio - 1.0) <= tol
    return {
        'channel': int(channel),
        'measured_vrms': float(measured_vrms),
        'expected_vrms': float(expected_vrms),
        'ratio': float(ratio),
        'error_db': float(error_db),
        'ok': bool(ok),
    }


def _validate_freq(freq, fs):
    """Raise ``ValueError`` unless ``0 < freq < 0.8 * (fs / 2)``.

    Args:
        freq (float): Tone frequency to validate, in Hz.
        fs (float): Sample rate the tone will be captured at, in Hz.
    """
    nyquist = float(fs) / 2.0
    limit = 0.8 * nyquist
    if not (0 < freq < limit):
        raise ValueError(
            'freq={:.6g} Hz must satisfy 0 < freq < 0.8*(fs/2) = {:.6g} Hz '
            'at fs={:.6g} Hz (headroom for the tone-estimation window and '
            'to stay well clear of aliasing near Nyquist).'
            .format(freq, limit, fs)
        )


def _run_loopback_capture(settings, freq, level_vrms, duration):
    """Generate a plain sine, play it out the AO device and capture it,
    for the ``source='loopback'`` path of `verify_input_scaling`.

    Args:
        settings (MySettings): Acquisition settings; a shallow copy with
            ``stored_time`` overridden to ``duration`` is used for the
            capture (the caller's ``settings`` is not mutated).
        freq (float): Tone frequency in Hz.
        level_vrms (float): Tone RMS amplitude in volts.
        duration (float): Capture duration in seconds.

    Returns the captured `TimeData`. Raises ``ValueError`` if the
    tone's peak (``level_vrms * sqrt(2)``) would exceed
    ``settings.output_vmax()`` — a hard error, matching
    `acquisition.multisine_generator`'s peak guard, rather than a
    silent clip.
    """
    local_settings = copy.copy(settings)
    local_settings.stored_time = float(duration)

    amplitude = float(level_vrms) * np.sqrt(2)
    vmax = local_settings.output_vmax()
    if amplitude > vmax:
        raise ValueError(
            'level_vrms={:.6g} V needs a peak of {:.6g} V, which exceeds '
            'settings.output_vmax() = {:.6g} V; lower level_vrms.'
            .format(level_vrms, amplitude, vmax)
        )

    n_samples = int(round(float(duration) * local_settings.output_fs))
    t = np.arange(n_samples) / local_settings.output_fs
    tone = amplitude * np.sin(2 * np.pi * float(freq) * t)
    # No fade window: a fade would taper the very samples the tone
    # estimator relies on for an unbiased amplitude, and a plain
    # continuous sine has no periodicity requirement to protect either
    # (unlike acquisition.multisine_generator).
    y = np.tile(tone[:, None], (1, local_settings.output_channels))

    if local_settings.output_device_driver == 'soundcard':
        print(
            'WARNING: loopback on a sound card only verifies chain '
            'CONSISTENCY, not absolute scaling -- the analogue output '
            'level (front-panel / OS volume) is not calibrated, so the '
            'volts actually played are not independently known. For '
            'absolute verification on a sound card, pass an external '
            'calibrated source instead, e.g. '
            'source=RigolDG1022Z(...).'
        )

    dataset = acquisition.log_data(local_settings, output=y)
    return dataset.time_data_list[0]


def _run_source_capture(settings, source, freq, level_vrms, duration):
    """Command an external known source and capture it, for the
    ``source=<instrument>`` path of `verify_input_scaling`.

    Args:
        settings (MySettings): Acquisition settings; a shallow copy with
            ``stored_time`` overridden to ``duration`` is used for the
            capture (the caller's ``settings`` is not mutated).
        source (object): Instrument with ``set_sine(freq_hz, vrms)`` and
            ``output(on)`` methods, e.g. `RigolDG1022Z`.
        freq (float): Tone frequency in Hz.
        level_vrms (float): Tone RMS amplitude in volts.
        duration (float): Capture duration in seconds.

    Returns the captured `TimeData`. The source's output is always
    switched off afterwards, even if the capture raises -- a bench
    source is never left running.
    """
    local_settings = copy.copy(settings)
    local_settings.stored_time = float(duration)

    source.set_sine(freq, level_vrms)
    source.output(True)
    try:
        time.sleep(0.5)  # let the relay/output settle before capturing
        dataset = acquisition.log_data(local_settings)
    finally:
        source.output(False)
    return dataset.time_data_list[0]


def verify_input_scaling(settings, source='loopback', freq=997.0,
                          level_vrms=0.1, duration=2.0, tol=0.05,
                          channels=None):
    """Verify the WHOLE input chain -- physical gain knobs included --
    by measuring a source of KNOWN level and comparing against the
    volts pydvma predicts.

    This is the check a coherence/level meter cannot do: those confirm
    a signal is present and roughly the right shape, but nothing
    upstream knows the true input level, so a wrong preamp gain, a
    wrong ``VmaxNI``/``VmaxSC``, or a stale ``input_gain_db`` all pass
    silently. Comparing against a KNOWN source closes that gap.

    Two ``source`` options, with different validity:

    - ``'loopback'`` (default): pydvma generates a plain sine and plays
      it out the configured AO device. On an NI device
      (``device_driver='nidaq'``/``output_device_driver='nidaq'``) the
      AO voltage is hardware-calibrated, so a physical AO->AI BNC cable
      exercises and verifies the WHOLE analogue input path with no
      extra equipment. On a sound card the analogue output level
      depends on an uncalibrated volume control, so this only proves
      chain CONSISTENCY (repeatable, internally coherent), not absolute
      scaling; a warning is printed (not a refusal -- consistency
      checks are still useful) when
      ``settings.output_device_driver == 'soundcard'``.
    - An object with ``set_sine(freq_hz, vrms)`` and ``output(on)``
      methods, e.g. `RigolDG1022Z`: the object is commanded to the
      requested tone, switched on, given ~0.5 s to settle, then
      ``settings`` captures it with no ``output`` argument (nothing is
      played by pydvma). The source is switched off again afterwards
      regardless of outcome. This is the only path that verifies
      absolute scaling on a sound card whose loopback is DIGITAL (e.g.
      a Scarlett 2i2's inputs 3/4 copy the output stream pre-preamp,
      so a digital loopback cannot see the analogue input gain).

    Per-channel attenuators, transducer sensitivities and
    ``channel_sensitivities`` calibration are OUT OF SCOPE: this
    function checks the digitiser chain in volts (the same domain
    `MySettings.channel_sensitivities` is applied on top of), not any
    downstream engineering-unit calibration.

    Args:
        settings (MySettings): Acquisition configuration; captured via a
            shallow copy internally, never mutated in place. Its
            ``fs``/``channels``/``device_driver`` govern the capture.
        source (str or object): ``'loopback'`` (default) or an
            instrument object exposing ``set_sine(freq_hz, vrms)`` and
            ``output(on)`` (e.g. `RigolDG1022Z`).
        freq (float): Tone frequency in Hz (default 997.0 -- avoids
            mains harmonics (50/60 Hz and multiples) and round-number
            divisor artefacts that 1000 Hz risks). Must satisfy
            ``0 < freq < 0.8 * (settings.fs / 2)``.
        level_vrms (float): Known tone RMS amplitude in volts (default
            0.1) -- this is also the "expected" value each measured
            channel is compared against.
        duration (float): Capture duration in seconds (default 2.0).
        tol (float): Fractional tolerance on the measured/expected
            ratio (default 0.05, i.e. +-5%, about +-0.42 dB). A channel
            passes when ``abs(ratio - 1) <= tol``.
        channels (list of int or None): Channel indices to check
            (default ``None`` = every channel, ``range(settings.channels)``).

    Returns a list of one dict per checked channel:
    ``{'channel': int, 'measured_vrms': float, 'expected_vrms': float,
    'ratio': float, 'error_db': float, 'ok': bool}``, where
    ``expected_vrms`` is ``level_vrms`` for every channel (per-channel
    sensitivity is out of scope, see above) and ``ok`` is
    ``abs(ratio - 1) <= tol``. As a side effect, prints a small aligned
    per-channel table with a PASS/FAIL verdict, followed by either
    "input scaling verified" or, per failing channel, a line like
    "channel 1 reads +2.3 dB high -- check the gain setting".
    """
    _validate_freq(freq, settings.fs)

    if channels is None:
        channels = list(range(settings.channels))

    if isinstance(source, str):
        if source != 'loopback':
            raise ValueError(
                "source must be 'loopback' or an object with "
                "set_sine(freq_hz, vrms)/output(on) methods (e.g. "
                "RigolDG1022Z); got string {!r}".format(source)
            )
        td = _run_loopback_capture(settings, freq, level_vrms, duration)
        source_label = 'loopback'
    elif hasattr(source, 'set_sine') and hasattr(source, 'output'):
        td = _run_source_capture(settings, source, freq, level_vrms, duration)
        source_label = getattr(source, 'resource', type(source).__name__)
    else:
        raise TypeError(
            "source must be 'loopback' or an object with "
            "set_sine(freq_hz, vrms)/output(on) methods (e.g. "
            "RigolDG1022Z); got {!r}".format(source)
        )

    fs = td.settings.fs
    results = [_verdict(ch, _measure_tone_vrms(td.time_data[:, ch], fs, freq),
                        float(level_vrms), tol)
               for ch in channels]

    print('Input-scaling check @ {:.1f} Hz, expected {:.4f} Vrms '
          '(source={})'.format(freq, level_vrms, source_label))
    print('  {:>3s}  {:>15s}  {:>15s}  {:>10s}  {:>7s}'.format(
        'ch', 'measured(Vrms)', 'expected(Vrms)', 'error(dB)', 'verdict'))
    for r in results:
        print('  {:>3d}  {:>15.4f}  {:>15.4f}  {:>+10.2f}  {:>7s}'.format(
            r['channel'], r['measured_vrms'], r['expected_vrms'],
            r['error_db'], 'PASS' if r['ok'] else 'FAIL'))

    if all(r['ok'] for r in results):
        print('input scaling verified')
    else:
        for r in results:
            if not r['ok']:
                direction = 'high' if r['error_db'] > 0 else 'low'
                print('channel {} reads {:+.1f} dB {} -- check the gain '
                      'setting'.format(r['channel'], r['error_db'], direction))

    return results
