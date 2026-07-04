# -*- coding: utf-8 -*-
"""Worker-side glue: stateless compute wrappers around pydvma.

Loaded inside the pyodide engine worker (``engine.worker.ts``). Every op is
a plain function taking JSON-marshallable scalars plus flat float64 arrays
and returning a dict of arrays — no PyProxy state survives between calls, so
the worker stays stateless (spec §11).

Array boundary convention (matches the JS ``NpyArray`` convention in
``src/lib/codec/npy.ts``): every array crosses as

    {'shape': [...], 'data': <flat float64, row-major>, 'complex': bool}

Real arrays ravel; complex arrays interleave ``[re, im, re, im, ...]``. The
JS side has one uniform decoder for both. Maths always runs here in pydvma —
never reimplemented in JS.
"""
import io

import numpy as np
import pydvma as dvma
from pydvma import analysis, container, datastructure


def _arr(a):
    """Marshal a numpy array to the flat ``{shape, data, complex}`` dict.

    Real arrays are ravelled to float64. Complex arrays are flattened with
    real/imag interleaved (``flat[0::2]=re``, ``flat[1::2]=im``) so the JS
    decoder reads pairs — the same layout ``codec/npy.ts`` uses for ``<c16``.
    """
    a = np.asarray(a)
    if np.iscomplexobj(a):
        flat = np.empty(a.size * 2, dtype=np.float64)
        r = a.ravel()
        flat[0::2] = r.real
        flat[1::2] = r.imag
        return {'shape': list(a.shape), 'data': flat, 'complex': True}
    return {'shape': list(a.shape),
            'data': np.asarray(a, dtype=np.float64).ravel(),
            'complex': False}


def _settings(fs, channels):
    """Minimal MySettings for reconstructing a TimeData (mock driver)."""
    return dvma.MySettings(channels=int(channels), fs=float(fs), device_driver='mock')


def _time_data(time_axis, time_data, n_channels, fs):
    """Rebuild a pydvma ``TimeData`` from flat JS arrays.

    JS sends ``time_data`` as a FLAT float64 buffer plus ``n_channels``; it is
    reshaped to ``(N_samples, n_channels)`` row-major (pydvma's convention),
    with ``time_axis`` a length-``N_samples`` vector.
    """
    ta = np.asarray(time_axis, dtype=np.float64)
    td = np.asarray(time_data, dtype=np.float64).reshape(-1, int(n_channels))
    return datastructure.TimeData(ta, td, _settings(fs, td.shape[1]))


def calc_fft(time_axis, time_data, n_channels, fs, window):
    """FFT of every channel. Returns freq_axis (Nf,) and freq_data (Nf, Nc) complex."""
    td = _time_data(time_axis, time_data, n_channels, fs)
    fd = analysis.calculate_fft(td, window=(window or None))
    return {'freq_axis': _arr(fd.freq_axis), 'freq_data': _arr(fd.freq_data)}


def calc_psd(time_axis, time_data, n_channels, fs, window, n_frames):
    """Auto-power spectral density (real) + coherence matrix Cxy.

    PSD is the diagonal of the cross-spectrum matrix:
    ``real(einsum('iif->if', Pxy))`` -> (Nc, Nf). Cxy is (Nc, Nc, Nf).
    Defaults to a Hann window when none is given.
    """
    td = _time_data(time_axis, time_data, n_channels, fs)
    cs = analysis.calculate_cross_spectrum_matrix(
        td, window=(window or 'hann'), N_frames=int(n_frames))
    psd = np.real(np.einsum('iif->if', cs.Pxy))
    return {'freq_axis': _arr(cs.freq_axis), 'psd': _arr(psd), 'Cxy': _arr(cs.Cxy)}


def calc_tf(time_axis, time_data, n_channels, fs, ch_in, window, n_frames):
    """Transfer function from input channel ``ch_in`` to every output channel.

    Returns tf_data (Nf, N_out) complex and coherence (Nf, N_out). pydvma's
    ``calculate_tf`` always populates ``tf_coherence``; the ``None`` guard
    below is harmless defence, not a case that occurs in practice.
    """
    td = _time_data(time_axis, time_data, n_channels, fs)
    tf = analysis.calculate_tf(
        td, ch_in=int(ch_in), window=(window or None), N_frames=int(n_frames))
    coh = None if tf.tf_coherence is None else _arr(tf.tf_coherence)
    return {'freq_axis': _arr(tf.freq_axis), 'tf_data': _arr(tf.tf_data), 'coherence': coh}


def calc_sono(time_axis, time_data, n_channels, fs, ch, nperseg, noverlap):
    """Sonogram (STFT magnitude) of a single channel ``ch``.

    The coupled-resolution control maps to ``nperseg=nFft`` and
    ``noverlap=nFft//2`` on the JS side. sono_data is returned as a real
    magnitude image (Nf, Nt) — ``abs`` of the complex STFT for channel ``ch``.
    """
    td = _time_data(time_axis, time_data, n_channels, fs)
    sd = analysis.calculate_sonogram(td, nperseg=int(nperseg), noverlap=int(noverlap))
    return {'time_axis': _arr(sd.time_axis), 'freq_axis': _arr(sd.freq_axis),
            'sono_data': _arr(np.abs(sd.sono_data[:, :, int(ch)]))}


def calc_tf_averaged(sets, ch_in, window):
    """Ensemble-averaged transfer function across several TimeData sets.

    ``sets`` is a LIST of ``{time_axis, time_data, n_channels, fs}`` dicts —
    one per measurement in the ensemble (e.g. repeated impulse-hammer taps).
    Each is rebuilt into a pydvma ``TimeData`` and the whole list is wrapped
    in a ``TimeDataList`` so ``analysis.calculate_tf_averaged`` can average the
    cross-spectra BEFORE forming the H1 estimator (no per-set sub-frame
    averaging — this is averaging *across* independent measurements). Returns
    tf_data (Nf, N_out) complex and coherence (Nf, N_out), same marshalling as
    ``calc_tf``.
    """
    tdl = datastructure.TimeDataList([
        _time_data(s['time_axis'], s['time_data'], s['n_channels'], s['fs'])
        for s in sets
    ])
    tf = analysis.calculate_tf_averaged(tdl, ch_in=int(ch_in), window=(window or None))
    coh = None if tf.tf_coherence is None else _arr(tf.tf_coherence)
    return {'freq_axis': _arr(tf.freq_axis), 'tf_data': _arr(tf.tf_data), 'coherence': coh}


def legacy_to_dvma(npy_bytes):
    """Convert a legacy pickle ``.npy`` (pydvma <=1.4.0) to ``.dvma`` bytes.

    Old pydvma saved a dataset as a length-1 object ndarray pickled into a
    ``.npy`` file (``np.save(..., np.array([DataSet(...)]))``). ``npy_bytes``
    arrives as a JS ``Uint8Array`` (which ``bytes(...)`` faithfully turns into
    a Python ``bytes``); it is loaded with ``allow_pickle=True`` /
    ``fix_imports=True`` (Py2->Py3 pickle compatibility), the single ``DataSet``
    is pulled out (``d[0]``), and ``container.save`` writes a real ``.dvma``
    zip. That file is read back from pyodide's in-memory ``/tmp`` and returned
    as ``{'dvma': <bytes>}``.

    The returned Python ``bytes`` marshals across the worker's ``toJs``
    (``create_proxies=False``) boundary as a JS ``Uint8Array`` — exactly what
    the client feeds to ``readDvma``. (``container.save`` takes a FILENAME, not
    a buffer, so the ``/tmp`` hop is required; pyodide's FS is in-memory.)
    """
    d = np.load(io.BytesIO(bytes(npy_bytes)), allow_pickle=True, fix_imports=True)
    container.save(d[0], '/tmp/legacy.dvma')
    with open('/tmp/legacy.dvma', 'rb') as f:
        return {'dvma': f.read()}


def mat_to_dvma(mat_bytes):
    """Import a JW-logger MATLAB ``.mat`` file and return ``.dvma`` bytes.

    ``mat_bytes`` (a JS ``Uint8Array``) is written to pyodide's in-memory
    ``/tmp`` because ``pydvma.file.import_from_matlab_jwlogger`` reads from a
    FILENAME (signature ``(filename=None)``). The resulting dataset is saved
    with ``container.save`` and the ``.dvma`` bytes read back, returned as
    ``{'dvma': <bytes>}`` — marshalled to a JS ``Uint8Array`` for ``readDvma``,
    same as ``legacy_to_dvma``.
    """
    from pydvma import file as pfile
    with open('/tmp/import.mat', 'wb') as f:
        f.write(bytes(mat_bytes))
    ds = pfile.import_from_matlab_jwlogger(filename='/tmp/import.mat')
    container.save(ds, '/tmp/import.dvma')
    with open('/tmp/import.dvma', 'rb') as f:
        return {'dvma': f.read()}


def clean_impulse(time_axis, time_data, n_channels, fs, ch_impulse):
    """Zero the noise floor around an impulse on channel ``ch_impulse``.

    Rebuilds a ``TimeData`` from the flat JS arrays, runs
    ``analysis.clean_impulse`` (estimates the pulse width, keeps the data up to
    the peak, then half-cosine-ramps the tail to zero), and returns the cleaned
    capture as ``{time_axis, time_data}`` — ``time_data`` flattened row-major
    so the JS side can replace the source set's TimeData in place.
    """
    td = _time_data(time_axis, time_data, n_channels, fs)
    cleaned = analysis.clean_impulse(td, ch_impulse=int(ch_impulse))
    return {'time_axis': _arr(cleaned.time_axis), 'time_data': _arr(cleaned.time_data)}
