# -*- coding: utf-8 -*-
"""Compute-chain signatures (derived-data save round, 2026-08-19).

A derived item (FFT, TF) records a short signature of the SOURCE
samples it was computed from, so a loaded file can tell whether the
chain is intact ("this TF really is the TF of that time data") or
broken (the time data was edited/scaled/resampled after the compute) —
shown in the app as a "source changed — rederive?" flag, never a
silent recompute. Display-side state (calibration factors, units,
x(iw) power) is deliberately NOT hashed: it never changes the samples.

The algorithm is FNV-1a 64-bit over little-endian float64 bytes,
hex-encoded — chosen because it is ~20 identical lines in Python and
TypeScript with no dependencies. A TypeScript twin lands as
``webui/src/lib/codec/signature.ts``; the two are pinned to each other
by shared known-answer vectors (``tests/test_signature.py`` and its
vitest counterpart) and the JS<->Python fixture round-trip. This is an
integrity check against accidental edits, not a cryptographic
guarantee.

THE BYTE STREAM (the cross-language contract — change it and you must
change the TypeScript twin and every frozen vector in both suites).
The samples are treated as a 2-D block of ``n_rows`` time instants by
``n_cols`` channels, C-order (row-major), exactly as the ``.npy``
payload is laid out; a 1-D record has ``n_cols = 1``. Hashed, in order:

1. ``n_rows`` as one little-endian float64;
2. ``n_cols`` as one little-endian float64;
3. ``fs`` as one little-endian float64 — ``0.0`` when the source
   carries no ``settings`` or no ``settings.fs``, so a signature can
   always be taken;
4. the selected whole ROWS, each contributing all ``n_cols`` of its
   values as little-endian float64 in column order (the REDUCTION
   RULE):

   * ``rows_cap = max(1, 65536 // n_cols)`` — the per-row element
     budget, so the hashed value count stays bounded whatever the
     channel count;
   * ``n_rows <= rows_cap``: every row;
   * ``n_rows > rows_cap``: ``row_stride = ceil(n_rows / rows_cap)``
     (exact integer arithmetic), taking rows
     ``0, row_stride, 2*row_stride, ...`` below ``n_rows``, then the
     LAST row (index ``n_rows - 1``) appended unconditionally. The
     append may duplicate the final strided row; that is deliberate,
     and keeps the rule branch-free in both languages.

Because the threshold applies to ROWS with a per-row budget, reduction
starts at 65536 time samples for a 1-channel record but at 16384 time
samples for a 4-channel one (``65536 // 4``) — it is a cap on hashed
VALUES, not on time samples.

Special float values (NaN, +/-inf, -0.0) are hashed as their stored
bit patterns like any other sample; signatures are only ever compared
between parties hashing the same stored samples, so no normalisation
is applied.

The reduction exists because a naive per-byte hash of a 30 s x 4 ch x
51.2 kHz record (49 MB) measured 2.33 s in CPython — far too slow for
a save click. Reduced, the same record hashes in ~25 ms here, and
~11 ms in the JavaScript prototype checked in as
``dev/prototypes/signature_prototype.mjs`` (which also prints the
frozen known-answer vectors, so the cross-language claim in
``tests/test_signature.py`` can be re-checked by running it).

The honest limitation: above the cap the signature sees whole time
instants spaced ``row_stride`` apart, so EVERY channel of a sampled
instant is covered and any per-channel edit is visible as long as it
touches a sampled row — but an edit confined entirely to fewer than
``row_stride`` consecutive UNSAMPLED rows can go unnoticed. The
blind spot is purely temporal (never per-channel: an earlier flat-byte
striding rule aliased onto the channel count and could hash channel 0
only, which is exactly what row striding fixes). Every staleness case
this flag exists for — rescaling, resampling, impulse cleaning, a
re-capture, a trim — changes the row count or a large, contiguous
span of rows, and the row and channel counts are always hashed.
"""
import numpy as np

_FNV_OFFSET = 0xcbf29ce484222325
_FNV_PRIME = 0x100000001b3
_MASK = 0xFFFFFFFFFFFFFFFF

#: Budget of float64 VALUES hashed in full before the reduction rule
#: kicks in — divided by the channel count to give the row cap. Part of
#: the cross-language contract: the TypeScript twin uses the same value.
MAX_HASHED_VALUES = 65536


def fnv1a64(data):
    """FNV-1a 64-bit hash of some bytes.

    Args:
        data (bytes): the byte string to hash.

    Returns the hash as 16 lowercase hex characters.
    """
    h = _FNV_OFFSET
    for b in data:
        h = ((h ^ b) * _FNV_PRIME) & _MASK
    return '%016x' % h


def _as_rows(samples):
    """`samples` as a C-contiguous little-endian float64 2-D block.

    A 1-D record becomes one column; a scalar becomes a single 1x1
    row; anything with more than two dimensions is flattened to
    ``(shape[0], -1)`` so the first axis stays the time axis.

    Args:
        samples (np.ndarray): the sample array, any shape or dtype.

    Returns the ``(n_rows, n_cols)`` array, as `np.ndarray`.
    """
    arr = np.ascontiguousarray(samples, dtype='<f8')
    if arr.ndim == 0:
        return arr.reshape(1, 1)
    if arr.ndim == 1:
        return arr.reshape(-1, 1)
    if arr.ndim > 2:
        return arr.reshape(arr.shape[0], -1)
    return arr


def _sample_stream(samples, fs):
    """The exact bytes `signature_of_samples` hashes.

    Applies the reduction rule documented in the module docstring —
    whole rows only, so every channel of a sampled time instant is
    covered.

    Args:
        samples (np.ndarray): the sample array, any shape or dtype;
            read as ``(n_rows, n_cols)`` and cast to little-endian
            float64.
        fs (float): the sample rate, hashed as one little-endian
            float64.

    Returns the byte string, as `bytes`.
    """
    arr = _as_rows(samples)
    n_rows, n_cols = arr.shape
    head = np.array([float(n_rows), float(n_cols), float(fs)],
                    dtype='<f8').tobytes()
    rows_cap = (max(1, MAX_HASHED_VALUES // n_cols) if n_cols
                else MAX_HASHED_VALUES)
    if n_rows <= rows_cap:
        return head + arr.tobytes()
    # exact integer ceil; the final row is appended unconditionally and
    # may duplicate the last strided row (branch-free by design)
    row_stride = -(-n_rows // rows_cap)
    return (head + arr[::row_stride].tobytes()
            + arr[n_rows - 1:n_rows].tobytes())


def signature_of_samples(samples, fs):
    """Signature of a raw sample block plus its sample rate.

    This is the cross-language contract: the TypeScript twin hashes the
    same bytes and returns the same string, so a signature written by
    either side verifies on the other.

    Args:
        samples (np.ndarray): the samples, ``(n_samples, n_channels)``
            or 1-D (read as a single channel).
        fs (float): the sample rate in Hz.

    Returns 16 lowercase hex characters.
    """
    return fnv1a64(_sample_stream(samples, fs))


def source_signature(time_data):
    """Signature of a TimeData's samples plus its sample rate.

    A TimeData whose ``settings`` is missing (or carries no ``fs``)
    hashes its rate as ``0.0`` rather than raising, so a signature can
    always be taken.

    Args:
        time_data (TimeData or iterable): the source measurement, or an
            iterable of them (a ``TimeDataList``, as
            `analysis.calculate_tf_averaged` has). For several sources
            the per-source byte streams are concatenated in list order,
            so the order is part of the signature. The multi-source
            form is a Python-side extension — the browser only ever
            derives from a single source.

    Returns 16 lowercase hex characters.
    """
    if hasattr(time_data, 'time_data'):
        sources = [time_data]
    else:
        sources = list(time_data)
    stream = b''.join(_sample_stream(td.time_data, _fs_of(td))
                      for td in sources)
    return fnv1a64(stream)


def _fs_of(time_data):
    """The sample rate of one TimeData, or ``0.0`` when it has none.

    Args:
        time_data (TimeData): the measurement to read ``settings.fs``
            from.

    Returns the rate as a `float`.
    """
    fs = getattr(getattr(time_data, 'settings', None), 'fs', None)
    return 0.0 if fs is None else float(fs)
