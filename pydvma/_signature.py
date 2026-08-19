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
hex-encoded — chosen because it is ~15 identical lines in Python and
TypeScript with no dependencies. The TypeScript twin is
``webui/src/lib/codec/signature.ts``; the two are pinned to each other
by shared known-answer vectors (``tests/test_signature.py`` and
``webui/tests/codec/signature.test.ts``) and the JS<->Python fixture
round-trip. This is an integrity check against accidental edits, not a
cryptographic guarantee.

THE BYTE STREAM (the cross-language contract — change it and you must
change the TypeScript twin and every frozen vector in both suites):

1. the sample count ``n`` as one little-endian float64;
2. the sample rate ``fs`` as one little-endian float64;
3. the SELECTED samples as little-endian float64, in order, where the
   selection depends on ``n`` (the REDUCTION RULE):

   * ``n <= MAX_HASHED_SAMPLES`` (65536): every sample, in C-order
     (row-major) flat order — i.e. the channels of one sample are
     adjacent, exactly as the ``.npy`` payload is laid out;
   * ``n > MAX_HASHED_SAMPLES``: a strided subset, ``stride =
     ceil(n / MAX_HASHED_SAMPLES)``, taking flat indices
     ``0, stride, 2*stride, ...`` below ``n`` (at most
     ``MAX_HASHED_SAMPLES`` values), followed by the LAST sample
     (flat index ``n - 1``) appended unconditionally. The append may
     duplicate the final strided sample; that is deliberate, and keeps
     the rule branch-free in both languages.

The reduction exists because a naive per-byte hash of a 30 s x 4 ch x
51.2 kHz record (49 MB) measured 2.33 s in CPython — far too slow for
a save click. Reduced, the same record hashes in ~36 ms (Python) and
~10 ms (JS/BigInt). The honest cost: for a record longer than 65536
samples the signature sees roughly one sample in ``stride``, so an
edit confined to fewer than ``stride`` consecutive samples can go
unnoticed. Every realistic staleness case this flag exists for —
rescaling, resampling, impulse cleaning, a re-capture — changes the
sample count or a large fraction of the samples, and the sample count
itself is always hashed.
"""
import numpy as np

_FNV_OFFSET = 0xcbf29ce484222325
_FNV_PRIME = 0x100000001b3
_MASK = 0xFFFFFFFFFFFFFFFF

#: Samples hashed in full before the reduction rule kicks in. Part of
#: the cross-language contract — the TypeScript twin uses the same
#: value.
MAX_HASHED_SAMPLES = 65536


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


def _sample_stream(samples, fs):
    """The exact bytes `signature_of_samples` hashes.

    Applies the reduction rule documented in the module docstring.

    Args:
        samples (np.ndarray): the sample array, any shape or dtype;
            flattened in C order and cast to little-endian float64.
        fs (float): the sample rate, hashed as one little-endian
            float64.

    Returns the byte string, as `bytes`.
    """
    flat = np.ascontiguousarray(samples, dtype='<f8').reshape(-1)
    n = flat.size
    head = np.array([float(n), float(fs)], dtype='<f8').tobytes()
    if n <= MAX_HASHED_SAMPLES:
        return head + flat.tobytes()
    stride = -(-n // MAX_HASHED_SAMPLES)      # ceil(n / MAX), integer-only
    return head + flat[::stride].tobytes() + flat[n - 1:n].tobytes()


def signature_of_samples(samples, fs):
    """Signature of a raw sample array plus its sample rate.

    This is the cross-language contract: the TypeScript
    ``sourceSignature(samples, fs)`` hashes the same bytes and returns
    the same string, so a signature written by either side verifies on
    the other.

    Args:
        samples (np.ndarray): the samples, ``(N_samples, N_channels)``
            or any shape; flattened in C order.
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
