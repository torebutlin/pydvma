"""Basic acoustics maths: frequency weighting, band levels, tone level.

Pure numpy/scipy so it can be imported from `verify`, the engine and
tests without pulling in acquisition or analysis. The web app has a
twin in ``webui/src/lib/analysis/acoustics.ts`` pinned by
`ACOUSTICS_VECTORS`.
"""
import numpy as np
from scipy import signal

P_REF = 20e-6
"""Reference sound pressure, 20 micropascals."""

_POLES = (20.6, 107.7, 737.9, 12194.0)

# (f, A dB, C dB), frozen from the implementation (1e-6).
ACOUSTICS_VECTORS = (
    (10.0, -70.435081, -14.330693),
    (31.5, -39.529007, -3.030738),
    (100.0, -19.145096, -0.299668),
    (1000.0, 0.0, 0.0),
    (4000.0, 0.963456, -0.826015),
    (16000.0, -6.70626, -8.63479),
)

# Nominal midband multipliers for third-octave index n = 0..9 within a decade
# (centre 1000*10**(n/10)), IEC 61260 labels.
_NOMINAL_PATTERN = (1.0, 1.25, 1.6, 2.0, 2.5, 3.15, 4.0, 5.0, 6.3, 8.0)


def _raw_weighting(f, curve):
    f2 = np.asarray(f, dtype=float) ** 2
    p1, p2, p3, p4 = (p * p for p in _POLES)
    if curve == 'A':
        num = p4 * f2 * f2
        den = (f2 + p1) * (f2 + p4) * np.sqrt((f2 + p2) * (f2 + p3))
    else:
        num = p4 * f2
        den = (f2 + p1) * (f2 + p4)
    with np.errstate(divide='ignore'):
        return 20.0 * np.log10(num / den)


def weighting_db(f, curve):
    """IEC 61672-1 frequency weighting in dB.

    The analytic A and C curves (poles 20.6, 107.7, 737.9 and 12194 Hz),
    normalised to exactly 0 dB at 1 kHz.

    Args:
        f (array_like): Frequencies in Hz.
        curve (str): 'Z' (flat), 'A' or 'C'.

    Returns an array of weightings in dB shaped like ``f``. 'Z' gives
    zeros; ``f <= 0`` gives ``-inf`` for 'A' and 'C'.

    Raises:
        ValueError: ``curve`` is not 'Z', 'A' or 'C'.
    """
    f = np.asarray(f, dtype=float)
    if curve == 'Z':
        return np.zeros(f.shape)
    if curve not in ('A', 'C'):
        raise ValueError("curve must be 'Z', 'A' or 'C', got {!r}".format(curve))
    norm = float(_raw_weighting(1000.0, curve))
    out = np.full(f.shape, -np.inf)
    pos = f > 0
    out[pos] = _raw_weighting(f[pos], curve) - norm
    return out


def _nominal(n):
    d, r = divmod(int(n), 10)
    return float(float('%.4g' % (_NOMINAL_PATTERN[r] * 1000.0 * 10.0 ** d)))


def band_table(bands, f_lo, f_hi):
    """IEC 61260 base-10 octave or third-octave bands inside a range.

    Args:
        bands (str): 'octave' or 'third-octave'.
        f_lo (float): Lowest frequency a band may reach, Hz.
        f_hi (float): Highest frequency a band may reach, Hz.

    Returns a dict of equal-length lists ``centre`` (exact midbands),
    ``nominal`` (IEC labels), ``lower`` and ``upper`` (band edges). Only
    bands with ``lower >= f_lo`` and ``upper <= f_hi`` are listed.

    Raises:
        ValueError: ``bands`` is not a known kind.
    """
    if bands == 'octave':
        b, step = 1, 3
    elif bands in ('third-octave', 'third'):
        b, step = 3, 1
    else:
        raise ValueError("bands must be 'octave' or 'third-octave', got {!r}".format(bands))
    out = {'centre': [], 'nominal': [], 'lower': [], 'upper': []}
    for x in range(-30 * b, 30 * b + 1):
        c = 1000.0 * 10.0 ** (0.3 * x / b)
        lo, hi = c * 10.0 ** (-0.15 / b), c * 10.0 ** (0.15 / b)
        if lo >= f_lo and hi <= f_hi:
            out['centre'].append(c)
            out['nominal'].append(_nominal(step * x))
            out['lower'].append(lo)
            out['upper'].append(hi)
    return out


def band_levels(f, psd, bands='octave', weighting='Z', min_bins=3):
    """Band powers from a power spectral DENSITY.

    ``power = sum(psd * 10**(W/10) * df)`` over the bins with
    ``lower <= f < upper``. A power SPECTRUM would over-count broadband
    power by the window's noise bandwidth, so a density is required.

    Args:
        f (array_like): Frequency axis in Hz, uniformly spaced.
        psd (array_like): Density in unit^2/Hz, shape ``(Nf,)`` or ``(Nc, Nf)``.
        bands (str): 'octave' or 'third-octave'.
        weighting (str): 'Z', 'A' or 'C'.
        min_bins (int): Bands with fewer bins are dropped.

    Returns a dict with the `band_table` keys plus ``power`` (shape
    ``(Nb,)`` or ``(Nc, Nb)``, unit^2) and ``n_bins``. The weighting at
    0 Hz is ``-inf`` dB, i.e. zero weight, so the DC bin adds nothing.
    """
    f = np.asarray(f, dtype=float)
    psd = np.asarray(psd, dtype=float)
    df = float(f[1] - f[0]) if f.size > 1 else 0.0
    gain = np.zeros(f.shape)
    pos = f > 0
    gain[pos] = 10.0 ** (weighting_db(f[pos], weighting) / 10.0)
    weighted = psd * gain
    tab = band_table(bands, max(float(f[0]), 0.0) if f.size else 0.0,
                     float(f[-1]) + df if f.size else 0.0)
    keep = {k: [] for k in tab}
    powers, counts = [], []
    for i in range(len(tab['centre'])):
        sel = (f >= tab['lower'][i]) & (f < tab['upper'][i])
        n = int(sel.sum())
        if n < min_bins:
            continue
        for k in tab:
            keep[k].append(tab[k][i])
        powers.append(weighted[..., sel].sum(axis=-1) * df)
        counts.append(n)
    keep['power'] = (np.stack(powers, axis=-1) if powers
                     else np.zeros(psd.shape[:-1] + (0,)))
    keep['n_bins'] = counts
    return keep


def tone_rms(x, fs, freq, bin_neighbours=2):
    """Robust RMS amplitude of a single tone, via a windowed periodogram.

    Windows ``x`` with a periodic Hann window and sums power over the
    ``2 * bin_neighbours + 1`` bins around the tone's expected bin, then
    normalises by the window's power gain (Parseval), so leakage from a tone
    off a bin centre is captured while broadband noise elsewhere is not.

    Args:
        x (np.ndarray): 1D real time-domain samples.
        fs (float): Sample rate in Hz.
        freq (float): Expected tone frequency in Hz.
        bin_neighbours (int): Bins summed either side of the nearest bin.

    Returns the tone's RMS amplitude in the units of ``x``.
    """
    x = np.asarray(x, dtype=float).ravel()
    N = x.shape[0]
    w = signal.windows.get_window('hann', N)
    X = np.fft.rfft(w * x)
    k0 = int(round(float(freq) * N / float(fs)))
    lo = max(k0 - int(bin_neighbours), 1)
    hi = min(k0 + int(bin_neighbours), len(X) - 2)
    if hi < lo:
        lo = hi = max(1, min(k0, len(X) - 2))
    tone_energy = (2.0 / N) * np.sum(np.abs(X[lo:hi + 1]) ** 2)
    return float(np.sqrt(tone_energy / np.sum(w ** 2)))


def reference_tone_calibration(time_data, channel, ref_rms, freq, *, freq_tolerance=0.05,
                               check_clip=True):
    """Sensitivity of one channel from an acoustic calibrator's tone.

    Analyses the middle 80 % of the record. The sensitivity is the measured
    tone rms (stored units) over ``ref_rms`` (engineering units, e.g. 1 Pa).

    Args:
        time_data (TimeData): The capture; ``settings.input_vmax(channel)``
            is used for the clip check when available.
        channel (int): Channel holding the calibrator tone.
        ref_rms (float): The calibrator's rms level in engineering units;
            a finite number above zero.
        freq (float): The calibrator's frequency in Hz.
        freq_tolerance (float): Allowed fractional offset of the spectral
            peak from ``freq`` before a warning is raised.
        check_clip (bool): False skips the clip check, for a capture whose
            settings state no input rail (``clipped`` is then False).

    Returns a dict: ``sensitivity`` (stored units per engineering unit),
    ``measured_rms``, ``peak_freq``, ``tone_to_total_db``, ``clipped`` and
    ``warnings`` (strings quoting the numbers). Warnings cover a peak more
    than ``freq_tolerance`` from ``freq``, broadband rms more than 1 dB
    above the tone, and a peak at or above 0.95 of the input rail.

    Raises:
        ValueError: ``ref_rms`` is not a finite number above zero, which
            has no sensitivity to give.
    """
    ref = float(ref_rms)
    if not (np.isfinite(ref) and ref > 0):
        raise ValueError('ref_rms must be a finite number above zero (the '
                         "calibrator's rms level), got {!r}.".format(ref_rms))
    full = np.asarray(time_data.time_data, dtype=float)
    if full.ndim == 1:
        full = full[:, None]
    ta = np.asarray(time_data.time_axis, dtype=float)
    n = full.shape[0]
    fs = 1.0 / float(ta[1] - ta[0]) if n > 1 else 1.0
    seg = full[int(n * 0.1):n - int(n * 0.1), int(channel)]
    if seg.size < 8:
        seg = full[:, int(channel)]
    seg_ac = seg - seg.mean()
    measured = tone_rms(seg_ac, fs, freq)
    total = float(np.sqrt(np.mean(seg_ac ** 2)))
    ratio_db = 20.0 * np.log10(max(measured, 1e-300) / max(total, 1e-300))
    w = signal.windows.get_window('hann', seg_ac.size)
    spec = np.abs(np.fft.rfft(w * seg_ac))
    spec[0] = 0.0
    peak_freq = float(np.argmax(spec) * fs / seg_ac.size)
    peak = float(np.max(np.abs(seg)))
    rail = None
    settings = getattr(time_data, 'settings', None)
    try:
        if check_clip and settings is not None:
            rail = float(settings.input_vmax(int(channel)))
    except Exception:
        rail = None
    clipped = bool(rail is not None and rail > 0 and peak >= 0.95 * rail)
    warnings = []
    if freq and abs(peak_freq - freq) > freq_tolerance * freq:
        warnings.append('Strongest frequency is {:.1f} Hz, more than {:.0f} % from the '
                        'expected {:.1f} Hz: is the calibrator on this channel?'
                        .format(peak_freq, freq_tolerance * 100, freq))
    if ratio_db < -1.0:
        warnings.append('Broadband noise is high: tone is {:.1f} dB below the total rms '
                        '(tone {:.4g}, total {:.4g}).'.format(-ratio_db, measured, total))
    if clipped:
        warnings.append('Signal may be clipping: peak {:.4g} is at least 95 % of the '
                        'input range {:.4g}.'.format(peak, rail))
    return {
        'sensitivity': float(measured / ref),
        'measured_rms': float(measured),
        'peak_freq': peak_freq,
        'tone_to_total_db': float(ratio_db),
        'clipped': clipped,
        'warnings': warnings,
    }
