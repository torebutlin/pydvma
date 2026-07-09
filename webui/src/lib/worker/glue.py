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
from pydvma import analysis, container, datastructure, modal

try:
    import peakutils as _pu
except Exception:                       # pragma: no cover - peakutils ships in the wheel
    _pu = None


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

    Engine guard: the shipped pyodide wheel (pydvma 1.5.0) builds the
    per-segment windows inside ``calculate_cross_spectrum_matrix`` via a
    ``sliding_window_view`` whose *nominal* size is
    ``Nc * (N_samples - nperseg + 1) * nperseg``. On the 32-bit WASM engine
    numpy rejects that view with "array is too big" for a large ``nperseg``
    on a long, high-rate record (e.g. a 2 s, 44.1 kHz capture at a fine Δf) —
    an opaque failure the user cannot act on. We catch that specific overflow
    and re-raise a clear, actionable message so ONE oversized set surfaces a
    named error while the other sets still compute (the JS ``calcPsd`` runs
    each set independently). Upstream (repo) pydvma now strides directly to
    the decimated windows and no longer overflows, so this branch is inert
    once a wheel with that fix ships — no fixed size cap is imposed here that
    would over-block the fixed engine.
    """
    td = _time_data(time_axis, time_data, n_channels, fs)
    try:
        cs = analysis.calculate_cross_spectrum_matrix(
            td, window=(window or 'hann'), N_frames=int(n_frames))
    except (ValueError, MemoryError) as e:
        msg = str(e).lower()
        if isinstance(e, MemoryError) or 'too big' in msg or 'maximum possible size' in msg:
            n_samples = int(td.time_data.shape[0])
            raise ValueError(
                'PSD at this resolution needs too large an internal buffer for '
                'the browser engine ({} samples × {} averaging frames). '
                'Use a coarser Δf (fewer or shorter frames).'.format(
                    n_samples, int(n_frames))
            ) from e
        raise
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


def calc_sono(time_axis, time_data, n_channels, fs, ch, nperseg, noverlap,
              method='stft', voices_per_octave=16, w0=6.0, f_min=None, f_max=None):
    """Sonogram of a single channel ``ch`` — STFT (default) or CWT.

    ``method='stft'`` (default, unchanged behaviour): a Hann STFT where the
    coupled-resolution control maps to ``nperseg=nFft`` and
    ``noverlap=nFft//2`` on the JS side.

    ``method='cwt'``: a complex Morlet continuous wavelet transform
    (``analysis.calculate_cwt``) over ``voices_per_octave`` log-spaced
    frequencies with non-dimensional frequency ``w0``. ``nperseg``/``noverlap``
    are IGNORED (the wavelet has no fixed window); an optional ``f_min``/``f_max``
    (Hz) overrides the default ``4/T .. 0.4*fs`` band. The CWT image is returned
    on its NATIVE LOG-spaced frequency grid (``uniform_freq=False``): the heat
    renderer now maps each frequency VALUE (not row-index) to a pixel through the
    chosen axis scale and binary-searches the nearest bin, so it places and
    labels a non-uniform grid correctly — and a log-y display then shows the
    wavelet's full low-frequency detail (previously a uniform resample threw
    that detail away for the display).

    Either way ``sono_data`` is returned as a real magnitude image (Nf, Nt) —
    ``abs`` of the complex transform for channel ``ch`` — plus its two axes.

    Engine guards:
    - STFT: the shipped pyodide wheel (pydvma 1.5.0) segments inside
      ``scipy.signal.spectrogram`` → ``sliding_window_view``, whose NOMINAL
      size ``Nc * (N_samples - nperseg + 1) * nperseg`` overflows the 32-bit
      WASM ``2**31-1`` byte ceiling for a large ``nperseg`` on a long,
      high-rate record (e.g. a 2 s, 44.1 kHz capture at nFFT=4096 — a ~2.75 GB
      nominal view). We catch that specific overflow and re-raise a clear
      message. Repo pydvma now strides directly to the decimated windows and no
      longer overflows (``analysis._spectrogram_complex_lowmem``), so this
      branch is inert once a wheel with that fix ships.
    - CWT: ``analysis.calculate_cwt`` only exists in a wheel that shipped the
      CWT feature. Against a STALE wheel (no ``calculate_cwt``) we raise a clear
      "engine wheel too old" message instead of an opaque ``AttributeError``.
    """
    td = _time_data(time_axis, time_data, n_channels, fs)
    if str(method) == 'cwt':
        if not hasattr(analysis, 'calculate_cwt'):
            raise ValueError(
                'CWT sonogram needs a newer engine: the loaded pydvma wheel has '
                'no calculate_cwt. Reload once builds settle, or fall back to the '
                'STFT method.'
            )
        f_range = None
        if f_min is not None and f_max is not None:
            f_range = (float(f_min), float(f_max))
        sd = analysis.calculate_cwt(
            td, f_range=f_range, voices_per_octave=int(voices_per_octave),
            w0=float(w0), uniform_freq=False)
    else:
        try:
            sd = analysis.calculate_sonogram(td, nperseg=int(nperseg), noverlap=int(noverlap))
        except (ValueError, MemoryError) as e:
            msg = str(e).lower()
            if isinstance(e, MemoryError) or 'too big' in msg or 'maximum possible size' in msg:
                n_samples = int(td.time_data.shape[0])
                raise ValueError(
                    'Sonogram at this window size needs too large an internal buffer '
                    'for the browser engine ({} samples × {}-pt STFT window). '
                    'Use a smaller nFFT.'.format(n_samples, int(nperseg))
                ) from e
            raise
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


def calc_best_match(sets, freq_range=None, set_ref=0, ch_ref=0):
    """Relative TF scaling factors (Qt's ``analysis.best_match``).

    Mirrors the Qt logger's Scaling tool (``gui.py:best_match`` →
    ``analysis.best_match``): every set's transfer-function columns are rescaled
    to best match ONE reference column of ONE reference set over the visible
    frequency window, so a family of TFs measured at different drive levels /
    gains can be overlaid. The factor is the RMS-magnitude ratio to the
    reference (with the sign taken from a real least-squares fit), computed on a
    common interpolated grid.

    ``sets`` is a LIST of ``{freq_axis, tf_data, n_tf}`` payloads — one per set's
    measured TF (the same interleaved-complex ``[re, im, ...]`` marshalling the
    fit path uses; ``n_tf`` is the OUTPUT-column count). Each is rebuilt into a
    pydvma ``TfData`` and wrapped in a ``TfDataList`` so ``analysis.best_match``
    interpolates every set/column onto the reference grid over ``freq_range``.

    ``freq_range`` is ``[lo, hi]`` Hz (the app's committed shared frequency
    window); ``None`` (or a malformed range) falls back to the reference set's
    full band. ``set_ref``/``ch_ref`` index the reference set (in ``sets`` order)
    and its reference OUTPUT column.

    Returns ``{'factors': [<per-column array>, ...]}`` — one marshalled real
    array of per-column factors per set, in ``sets`` order. The JS side
    (``actions.calcBestMatch``) folds each column's factor into the SOURCE
    channel's ``channel_cal_factors`` through the existing calibration path
    (display-time ``cal[out]/cal[in]`` scaling + ``.dvma`` persistence), so
    Best Match is Undo-able by resetting calibration and the factors stay
    visible/editable in the Calibrate dialog — the pragmatic webui adaptation of
    Qt's ``set_calibration_factors_all`` (Qt stores the factor per TF column;
    the webui stores it per source channel).
    """
    tfs = []
    for s in sets:
        fa = np.asarray(_get(s, 'freq_axis'), dtype=np.float64)
        ntf = int(_get(s, 'n_tf'))
        G = _complex_grid(_get(s, 'tf_data'), ntf)
        # settings only carry a nominal channel count; best_match ignores fs.
        tfs.append(datastructure.TfData(fa, G, None, _settings(1.0, ntf + 1)))
    tdl = datastructure.TfDataList(tfs)
    sref = int(set_ref)
    # A concrete 2-element range is required: analysis.best_match indexes
    # freq_range[0]/[1] directly (its own linspace). `not freq_range` catches
    # Python None, a JS-null proxy (JsNull — truthy to `is None`, so it must be
    # tested with `not`), and an empty range; a real [lo, hi] is truthy.
    if not freq_range or (hasattr(freq_range, '__len__') and len(freq_range) < 2):
        fr = np.asarray(tdl[sref].freq_axis[[0, -1]], dtype=np.float64)
    else:
        fr = np.asarray([float(freq_range[0]), float(freq_range[1])], dtype=np.float64)
    factors = analysis.best_match(tdl, freq_range=fr, set_ref=sref, ch_ref=int(ch_ref))
    return {'factors': [_arr(np.asarray(f, dtype=np.float64)) for f in factors]}


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

    STALE-WHEEL GUARD: old pydvma pickles (<= 1.4.0) predate one or more of
    the per-kind ``*_list`` attributes on ``DataSet`` (e.g. the 2019/4C6-era
    files lack ``modal_data_list``), and ``container.save`` reads every list,
    so it would raise ``AttributeError: 'DataSet' object has no attribute
    'modal_data_list'``. Repo pydvma fixes this in ``DataSet.__setstate__``,
    but a browser session may still be running an OLD cached engine wheel
    without that fix. We re-apply the same normalisation here so a legacy
    ``.npy`` loads even against a stale wheel. Idempotent on a DataSet that
    ``__setstate__`` (new wheel) already normalised.
    """
    d = np.load(io.BytesIO(bytes(npy_bytes)), allow_pickle=True, fix_imports=True)
    ds = _normalise_legacy_dataset(d[0])
    container.save(ds, '/tmp/legacy.dvma')
    with open('/tmp/legacy.dvma', 'rb') as f:
        return {'dvma': f.read()}


def _normalise_legacy_dataset(ds):
    """Ensure a legacy-unpickled ``DataSet`` carries every ``*_list``.

    Fills in any per-kind list attribute a pre-1.4.0 pickle predates with an
    empty instance of the right type, so ``container.save`` never trips over
    a missing list. Mirrors ``DataSet.__setstate__`` in repo pydvma; kept
    here as well so stale engine wheels (shipped before that fix) still
    import legacy files. Returns ``ds`` (mutated in place).
    """
    list_classes = {
        'time_data_list': datastructure.TimeDataList,
        'freq_data_list': datastructure.FreqDataList,
        'cross_spec_data_list': datastructure.CrossSpecDataList,
        'tf_data_list': datastructure.TfDataList,
        'modal_data_list': datastructure.ModalDataList,
        'sono_data_list': datastructure.SonoDataList,
        'meta_data_list': datastructure.MetaDataList,
    }
    for name, cls in list_classes.items():
        if not hasattr(ds, name):
            setattr(ds, name, cls())
    return ds


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


# --------------------------------------------------------------------------- #
# Modal fitting (Wave-A Task A1)
# --------------------------------------------------------------------------- #

def _complex_grid(flat, n_cols):
    """De-interleave a flat complex buffer into a ``(rows, n_cols)`` array.

    JS marshals a complex array as ``[re, im, re, im, ...]`` (row-major); this
    reverses that into a numpy complex matrix. ``n_cols`` is the column count
    (TF output channels), so ``rows`` follows from the buffer length.
    """
    g = np.asarray(flat, dtype=np.float64).ravel()
    z = g[0::2] + 1j * g[1::2]
    return z.reshape(-1, int(n_cols))


def _tf_from_flat(freq_axis, tf_data, n_tf, fs, n_channels):
    """Rebuild a pydvma ``TfData`` from the marshalled measured TF columns.

    ``tf_data`` is the interleaved-complex buffer of shape ``(Nf, n_tf)`` (the
    OUTPUT columns ``calculate_tf`` produced), ``n_tf`` the output-column count.
    A minimal ``MySettings`` carries ``fs`` / source ``n_channels`` for the
    reconstruction helpers (which override ``settings.channels`` themselves).
    ``channel_cal_factors`` defaults to ones — the browser applies calibration
    at display time (model.ts seam), so the engine fits RAW columns and the
    overlay stays consistent with the plotted (uncalibrated) TF.
    """
    f = np.asarray(freq_axis, dtype=np.float64)
    G = _complex_grid(tf_data, n_tf)
    return datastructure.TfData(f, G, None, _settings(fs, n_channels))


def _rebuild_modal(M, settings, test_name=None):
    """Reconstruct a ``ModalData`` from a marshalled ``M`` matrix (or ``None``).

    ``M`` is the ``{shape, data, complex}`` dict the JS modal store round-trips
    (stateless engine — the store holds ``M`` and re-sends it). Each row is a
    packed mode ``[fn, zn, an*N, pn*N, rk*N, rm*N]``; they are replayed through
    ``add_mode`` so the summary arrays (fn/zn/an/pn) and channel count refresh.
    Returns ``None`` when there is no prior matrix (a fresh model).
    """
    if not M:                            # None / JsNull / empty
        return None
    shape = list(_get(M, 'shape') or [])
    data = np.asarray(_get(M, 'data'), dtype=np.float64).ravel()
    if data.size == 0 or len(shape) != 2 or shape[0] == 0:
        return None
    rows = data.reshape(int(shape[0]), int(shape[1]))
    md = datastructure.ModalData(settings=settings, test_name=test_name)
    for row in rows:
        md.add_mode(row)
    return md


def _get(d, k):
    """Read key ``k`` from a payload that may arrive as a dict, a Map-like
    JsProxy, or a plain-object JsProxy.

    Top-level kwargs are converted by ``callKwargs``, but payload values
    NESTED inside lists/objects cross the FFI as ``JsProxy``. A Map-like
    proxy exposes ``.get``; a plain-object proxy exposes its properties as
    Python attributes — but does NOT support ``in`` (raises "argument of
    type 'pyodide.ffi.JsProxy' is not iterable", the export_mat bug), so
    the membership test must not be used here. Missing keys → None.
    """
    if isinstance(d, dict):
        return d.get(k)
    get = getattr(d, 'get', None)
    if callable(get):
        return get(k)
    return getattr(d, k, None)


def _fit_subranges(f, mag, freq_range, n_modes):
    """Split ``freq_range`` into up to ``n_modes`` single-peak sub-windows.

    pydvma's ``modal_fit_all_channels`` fits ONE mode per call, so multi-mode
    ("Fit 2 / Fit 3") is realised by detecting the strongest peaks in the
    visible window (peakutils, shipped in the engine) and fitting each in its
    own sub-range, split at the midpoints between adjacent peaks. Degrades
    gracefully: ``n_modes == 1``, too few points, a flat window, or a missing
    peakutils all fall back to a single fit over the whole ``freq_range``; if
    fewer than ``n_modes`` peaks are found only those are fitted.
    """
    lo, hi = float(freq_range[0]), float(freq_range[1])
    if n_modes <= 1 or _pu is None:
        return [[lo, hi]]
    sel = np.where((f > lo) & (f < hi))[0]
    if sel.size < 3:
        return [[lo, hi]]
    fw = f[sel]
    mw = np.asarray(mag, dtype=np.float64)[sel]
    mmax = np.max(mw)
    if not np.isfinite(mmax) or mmax <= 0:
        return [[lo, hi]]
    min_dist = max(1, int(mw.size * 0.02))
    try:
        idx = _pu.indexes(mw / mmax, thres=0.1, min_dist=min_dist)
    except Exception:
        idx = np.array([], dtype=int)
    idx = np.asarray(idx, dtype=int)
    if idx.size == 0:
        return [[lo, hi]]
    # Keep the n_modes strongest peaks, then order them by frequency.
    order = np.argsort(mw[idx])[::-1][:int(n_modes)]
    chosen = np.sort(fw[idx[order]])
    edges = [lo]
    for i in range(len(chosen) - 1):
        edges.append(0.5 * (chosen[i] + chosen[i + 1]))
    edges.append(hi)
    return [[edges[i], edges[i + 1]] for i in range(len(chosen))]


def _delete_modes(md, indices):
    """Delete rows ``indices`` from ``md``, returning the shrunk ModalData —
    or ``None`` when every mode is removed.

    Works around a pydvma bug (present in the shipped 1.5.0 wheel and repo
    ``datastructure.py``): ``ModalData.delete_mode`` unconditionally calls
    ``modal.unpack_matrix(self.M)`` on the POST-delete matrix, and
    ``unpack_matrix`` indexes ``X[0, :]`` — so deleting the LAST remaining
    mode leaves a ``(0, 6)`` matrix and raises ``IndexError: index 0 is out
    of bounds for axis 0 with size 0`` (the round-4 "Fit → Reject" crash at
    ``glue.py`` line ~410, and the same latent crash when a re-fit replaces
    every existing mode in its window). We detect the "no survivors" case up
    front and return an empty model (``None``) instead of invoking the
    crashing path; when at least one mode survives, ``delete_mode`` is safe
    and is used directly. Stateless: the caller re-marshals whatever we
    return, so ``None`` cleanly clears the JS store's mode chip.
    """
    rows = np.atleast_2d(md.M)
    keep = np.ones(rows.shape[0], dtype=bool)
    keep[np.asarray(indices, dtype=int)] = False
    if not keep.any():
        return None
    md.delete_mode(np.asarray(indices, dtype=int))
    return md


def _modal_summary(md):
    """Marshal a ModalData's matrix + per-mode summary arrays for the JS store.

    Returns ``M`` (the full parameter matrix the store re-sends) plus the
    fn/zn/an/pn summaries that drive the floating mode chip. An empty / ``None``
    model returns zero-length arrays so the store can clear its table.
    """
    if md is None or len(np.atleast_2d(md.M)) == 0 or np.size(md.M) == 0:
        empty = np.zeros(0)
        return {'M': _arr(np.zeros((0, 0))), 'fn': _arr(empty), 'zn': _arr(empty),
                'an': _arr(np.zeros((0, 0))), 'pn': _arr(np.zeros((0, 0)))}
    return {'M': _arr(md.M), 'fn': _arr(md.fn), 'zn': _arr(md.zn),
            'an': _arr(np.atleast_2d(md.an)), 'pn': _arr(np.atleast_2d(md.pn))}


def _global_recon_slice(md, f, measurement_type, mute, off, ncols):
    """GLOBAL (residual-free) reconstruction of ``md`` over ``f``, EXCLUDING
    muted modes, sliced to columns ``[off : off+ncols]``.

    ``mute`` is the list of mode-row indices the user has muted in the chip
    (round-4 item 9 — a muted mode stays in ``M`` and in the summary, but is
    dropped from the whole-model overlay). Muting is realised statelessly: the
    JS store keeps the full ``M`` and re-sends the mute list, and here we
    reconstruct from a filtered copy so nothing in the stored model changes.

    ``off``/``ncols`` pick this SET's block of the joint reconstruction: a
    shared-pole model spanning several sets (item 7) fits one ``M`` whose
    ``an``/``pn``/… columns concatenate every set's TF columns in list order,
    so ``reconstruct_transfer_function_global`` yields ``(Nf, total_cols)`` and
    each set's lines are the contiguous block starting at its cumulative column
    offset. For the single-set case ``off == 0`` and ``ncols`` is the set's TF
    column count (identical to the pre-item-7 behaviour). Returns
    ``(freq_axis_arr, tf_data_arr)`` marshalled — empty when the filtered model
    has no surviving modes.
    """
    empty = (_arr(np.zeros(0)), _arr(np.zeros((0, int(ncols)), dtype=complex)))
    if md is None or np.size(md.M) == 0:
        return empty
    rows = np.atleast_2d(md.M)
    mute_idx = set(int(i) for i in (mute or []))
    keep = [i for i in range(rows.shape[0]) if i not in mute_idx]
    if not keep:
        return empty
    md_vis = datastructure.ModalData(settings=md.settings, test_name=md.test_name)
    for i in keep:
        md_vis.add_mode(rows[i])
    rg = modal.reconstruct_transfer_function_global(md_vis, f, measurement_type)
    return _arr(rg.freq_axis), _arr(rg.tf_data[:, int(off):int(off) + int(ncols)])


def _build_fit_specs(freq_axis, tf_data, n_tf, ch_in, n_channels, fs, sets):
    """Normalise the single-set top-level args OR a multi-set ``sets`` list into
    a uniform list of per-set fit specs.

    Each returned spec is ``{'tf': TfData, 'n_cols': int}`` — the rebuilt
    ``TfData`` (on the set's OWN frequency axis) and its TF column count. When
    ``sets`` is provided (item 7, shared-pole joint fitting) every element is a
    ``{freq_axis, tf_data, n_tf, ch_in, n_channels, fs}`` payload (``ch_in`` is
    bookkeeping only — the TF is already computed, and ``modal_fit_all_channels``
    consumes the columns directly regardless of which channel was the input);
    an orphan set simply passes ``ch_in=None``. When ``sets`` is falsy the single
    top-level payload is wrapped into a length-1 list, so the downstream fit /
    reconstruction path is identical for one set or many.

    ``ch_in`` is accepted purely so the JS side may send it uniformly; it does
    not affect the fit or the reconstruction geometry here (the browser tracks
    the out/in remap on its side — see ``tfChannels.ts``).
    """
    if sets:
        raw = list(sets)
    else:
        raw = [{'freq_axis': freq_axis, 'tf_data': tf_data, 'n_tf': n_tf,
                'ch_in': ch_in, 'n_channels': n_channels, 'fs': fs}]
    specs = []
    for s in raw:
        fa = _get(s, 'freq_axis')
        td = _get(s, 'tf_data')
        ntf = int(_get(s, 'n_tf'))
        nch = _get(s, 'n_channels')
        nch = int(nch) if nch is not None else ntf + 1
        s_fs = _get(s, 'fs')
        s_fs = float(s_fs) if s_fs is not None else (float(fs) if fs is not None else 1.0)
        tf = _tf_from_flat(fa, td, ntf, s_fs, nch)
        specs.append({'tf': tf, 'n_cols': ntf})
    return specs


def _align_fit_list(tf_list):
    """Return ``tf_list`` on ONE common frequency axis for the joint fitter.

    ``modal_fit_all_channels`` selects the fit window from ``tf_data_list[0]``'s
    axis and applies that SAME index mask to every set, so a shared-pole fit
    across sets with differing axes (e.g. different fs) needs them aligned. If
    all sets already share an identical axis (the common hammer-test case — one
    fs, one Δf) the list is returned untouched (byte-identical fit to today).
    Otherwise each later set's complex columns are ``np.interp``-ed (real/imag
    separately) onto the first set's axis. Reconstruction still runs on each
    set's OWN axis (the caller keeps the un-aligned specs), so this alignment
    only ever touches the fit target ``G0``, never the returned recon.
    """
    if len(tf_list) <= 1:
        return tf_list
    f0 = tf_list[0].freq_axis
    if all(t.freq_axis.shape == f0.shape and np.allclose(t.freq_axis, f0)
           for t in tf_list):
        return tf_list
    aligned = [tf_list[0]]
    for t in tf_list[1:]:
        G = t.tf_data
        Gi = np.empty((f0.size, G.shape[1]), dtype=complex)
        for c in range(G.shape[1]):
            Gi[:, c] = (np.interp(f0, t.freq_axis, G[:, c].real)
                        + 1j * np.interp(f0, t.freq_axis, G[:, c].imag))
        ta = datastructure.TfData(f0, Gi, None, t.settings)
        ta.flag_modal_TF = False
        aligned.append(ta)
    return aligned


def calc_fit(freq_axis=None, tf_data=None, n_tf=None, ch_in=None, n_channels=None,
             fs=None, sets=None, M=None, freq_range=None, measurement_type='acc',
             action='fit', n_modes=1, index=None, mute=None):
    """Modal fit / reject / delete-one / refine / reconstruction over one OR
    several sets' TFs (with SHARED poles across sets — item 7).

    STATELESS (spec §11): the JS modal store owns the accumulated modal matrix
    ``M`` and re-sends it every call; this op never keeps state between calls.
    Mirrors the Qt driver (``gui.py:fit_mode`` / ``reject_mode`` /
    ``view_modal_reconstruction``), whose ``fit_mode`` passes the WHOLE
    ``tf_data_list`` so one ``fn``/``zn`` per mode is fitted jointly across
    every set's columns with per-column amplitudes (the hammer-test workflow).

    TARGET SHAPE:
    - Single set (backward compatible): the top-level ``freq_axis / tf_data /
      n_tf / ch_in / n_channels / fs`` describe one TF. ``ch_in`` is BOOKKEEPING
      only (the TF is already computed; the fit and reconstruction never re-drop
      an input channel) and now defaults to ``None`` so an ORPHAN TF — whose
      columns ARE the lines and which the JS side sends with no ``ch_in`` (round-5
      item 3 / round-6 bug 1) — fits without the previous
      ``TypeError: missing 'ch_in'``.
    - Multiple sets (``sets`` is a LIST of ``{freq_axis, tf_data, n_tf, ch_in,
      n_channels, fs}`` payloads): the sets are jointly fitted with SHARED poles;
      the reconstruction columns concatenate every set's columns in list order
      and are returned SLICED per set (see ``slices``).

    ACTIONS (identical for one or many sets):
    - ``'fit'``  — fit ``n_modes`` mode(s) over ``freq_range``
      (``modal_fit_all_channels``; Fit 2/3 via ``_fit_subranges`` on set 0's
      magnitude — a shared peak appears in every set), delete any existing modes
      whose ``fn`` falls in that window (re-fitting a peak REPLACES it), then
      ``add_mode`` the new one(s).
    - ``'reject'`` — delete modes with ``fn`` in ``freq_range``.
    - ``'delete_one'`` — delete the single mode at row ``index`` (chip × button).
    - ``'refine'`` — simultaneously refine EVERY mode from the current ``M``
      (``modal.modal_refine`` over the joint list; seeded from ``M``). Adds
      ``{converged, cost_before, cost_after}`` so the store auto-reverts a
      non-improving refine (round-4 item 10).
    - ``'recon'`` — no fit; just recompute the overlays from ``M`` (mute change).

    RETURN: ``{M, fn, zn, an, pn, message}`` (the SHARED model — one ``M``, one
    ``fn``/``zn`` per mode) plus, for backward compatibility, the FIRST set's
    ``recon_freq_axis / recon_tf_data`` (local, pink) and ``global_freq_axis /
    global_tf_data`` (grey dashed) exactly as before, AND a ``slices`` list —
    one entry PER target set, in column order, each
    ``{recon_freq_axis, recon_tf_data, global_freq_axis, global_tf_data,
    n_cols}`` (its own block of the joint reconstruction). The JS side maps each
    slice back to its set's lines. ``refine`` also carries
    ``converged``/``cost_before``/``cost_after``. All arrays via ``_arr``; recon
    TFs are complex ``(Nf, n_cols)`` matching that set's measured columns 1:1
    (empty for a reject / a model that ends empty).
    """
    specs = _build_fit_specs(freq_axis, tf_data, n_tf, ch_in, n_channels, fs, sets)
    tf_list = [sp['tf'] for sp in specs]
    fit_list = _align_fit_list(tf_list)          # common axis for the joint fit
    fit_settings = fit_list[0].settings
    fit_test_name = fit_list[0].test_name
    f = fit_list[0].freq_axis
    # `not freq_range` catches None, a JS-null proxy, and an empty range; a
    # real [lo, hi] (Python list or JS array proxy) is truthy.
    if not freq_range:
        freq_range = [float(f[0]), float(f[-1])]
    else:
        freq_range = [float(freq_range[0]), float(freq_range[1])]

    # Cumulative column offsets: set i owns recon columns [off_i : off_i+n_cols].
    offsets = []
    off = 0
    for sp in specs:
        offsets.append(off)
        off += int(sp['n_cols'])

    md = _rebuild_modal(M, fit_settings, fit_test_name)
    new_modes = []
    message = ''
    refine_info = None

    if action == 'fit':
        mag = (np.abs(fit_list[0].tf_data[:, 0])
               if fit_list[0].tf_data.shape[1] > 0 else np.abs(f) * 0)
        for lo, hi in _fit_subranges(f, mag, freq_range, int(n_modes)):
            m = modal.modal_fit_all_channels(
                datastructure.TfDataList(list(fit_list)), freq_range=[lo, hi],
                measurement_type=measurement_type)
            new_modes.append(np.asarray(m.M[0, :], dtype=np.float64))
        message = modal.MESSAGE
        # Replace any existing modes in the fitted window, then add the new ones.
        if md is not None and np.size(md.M) > 0:
            fn_all = np.atleast_2d(md.M)[:, 0]
            in_range = np.where((fn_all > freq_range[0]) & (fn_all < freq_range[1]))[0]
            if in_range.size > 0:
                md = _delete_modes(md, in_range)   # None if the window covered them all
        for row in new_modes:
            if md is None or np.size(md.M) == 0:
                md = datastructure.ModalData(row, settings=fit_settings, test_name=fit_test_name)
            else:
                md.add_mode(row)

    elif action == 'reject':
        if md is not None and np.size(md.M) > 0:
            fn_all = np.atleast_2d(md.M)[:, 0]
            in_range = np.where((fn_all > freq_range[0]) & (fn_all < freq_range[1]))[0]
            if in_range.size > 0:
                md = _delete_modes(md, in_range)   # None when the last mode(s) go
                message = 'Mode fits deleted.'

    elif action == 'delete_one':
        if md is not None and np.size(md.M) > 0 and index is not None:
            n_rows = np.atleast_2d(md.M).shape[0]
            idx = int(index)
            if 0 <= idx < n_rows:
                md = _delete_modes(md, [idx])      # None when it was the last mode
                message = 'Mode deleted.'

    elif action == 'refine':
        # Ignore any visible window: refine the WHOLE model over the modes' band
        # (modal_refine's own default). Seeded from the current M, joint over
        # every set's columns (shared poles).
        if md is not None and np.atleast_2d(md.M).shape[0] >= 1:
            md_refined, refine_info = modal.modal_refine(
                md, datastructure.TfDataList(list(fit_list)),
                freq_range=None, measurement_type=measurement_type)
            md = md_refined
            message = ('Refined {} mode(s).'.format(np.atleast_2d(md.M).shape[0])
                       if refine_info['converged'] else 'Refinement did not improve the fit.')

    # action == 'recon' (or any other) just re-marshals md + overlays below.

    out = _modal_summary(md)
    out['message'] = message
    if refine_info is not None:
        out['converged'] = bool(refine_info['converged'])
        out['cost_before'] = float(refine_info['cost_before'])
        out['cost_after'] = float(refine_info['cost_after'])

    # Local reconstruction (pink) — only the just-fitted modes, dense over the
    # fit window, one (Nf, total_cols) image sliced per set. Empty for reject /
    # recon (no fresh fit to highlight).
    rc_full = None
    f_local = None
    if new_modes:
        m_local = datastructure.ModalData(settings=fit_settings, test_name=fit_test_name)
        for row in new_modes:
            m_local.add_mode(row)
        f_local = np.linspace(freq_range[0], freq_range[1], 500)
        rc_full = modal.reconstruct_transfer_function(m_local, f_local, measurement_type)

    # Per-set slices: local (shared dense window axis) + global (each set's own
    # measured axis), each sliced to that set's column block.
    slices = []
    for sp, off_i in zip(specs, offsets):
        ncols = int(sp['n_cols'])
        if rc_full is not None:
            loc_axis = _arr(f_local)
            loc_data = _arr(rc_full.tf_data[:, off_i:off_i + ncols])
        else:
            loc_axis = _arr(np.zeros(0))
            loc_data = _arr(np.zeros((0, ncols), dtype=complex))
        g_axis, g_data = _global_recon_slice(
            md, sp['tf'].freq_axis, measurement_type, mute, off_i, ncols)
        slices.append({'recon_freq_axis': loc_axis, 'recon_tf_data': loc_data,
                       'global_freq_axis': g_axis, 'global_tf_data': g_data,
                       'n_cols': ncols})
    out['slices'] = slices

    # Backward-compatible top-level = FIRST set's overlays (single-set callers
    # and the existing tests read these; the store reads `slices`).
    first = slices[0]
    out['recon_freq_axis'] = first['recon_freq_axis']
    out['recon_tf_data'] = first['recon_tf_data']
    out['global_freq_axis'] = first['global_freq_axis']
    out['global_tf_data'] = first['global_tf_data']

    return out


def calc_damping(time_axis, time_data, n_channels, fs, ch, nperseg, start_time=None,
                 method='stft', voices_per_octave=16, w0=6.0, peak_threshold=None):
    """Modal damping from a time-frequency image's per-band free decay (Sono card).

    ``method='stft'`` (default) wraps ``analysis.calculate_damping_from_sono``:
    the log-decrement fit on channel ``ch``'s STFT bands (``nperseg`` window).
    ``method='cwt'`` wraps ``analysis.calculate_damping_from_cwt``: the same fit
    on a complex Morlet CWT image (``voices_per_octave`` / ``w0``), whose
    constant-Q resolution separates closely-spaced low-frequency modes an STFT
    window smears together; ``nperseg`` is ignored for CWT.

    ``start_time`` (seconds) picks the free-decay start; ``None`` lets pydvma
    infer it (pretrigger-based, with a fallback). ``peak_threshold`` is the
    normalised 0..1 peak-picking threshold; ``None`` keeps pydvma's automatic
    choice. Both are the knobs of the round-7 interactive damping UI.

    Returns per-detected-mode ``fn`` (Hz) and ``Qn = 1/(2 zeta)`` PLUS the full
    peak-picking / fit context the interactive panel draws (the round-7
    rebuild — this used to be discarded): ``start_time`` / ``threshold``
    actually used, the start-slice spectrum (``slice_freq`` / ``slice_mag``),
    the candidate peaks (``peaks_freq`` / ``peaks_mag``), and per-fitted-mode
    decay arrays (``fits[i].t_fit / real_fit / real_data / f_peak / Qn`` — the
    "Real Part of Log(S) vs fitted curve" lines the Qt DampingFitWindow drew).

    Stale-wheel guard: ``method='cwt'`` against a wheel without
    ``calculate_damping_from_cwt`` raises a clear "engine wheel too old"
    message instead of an opaque ``AttributeError``.
    """
    td = _time_data(time_axis, time_data, n_channels, fs)
    # `not start_time` handles None / a JS-null proxy (an explicit 0.0 start
    # also defers to inference — harmless, the free-decay start is never 0).
    st = float(start_time) if start_time else None
    # 0.0 is a legal explicit threshold, so test against None-ish only. A JS
    # null arrives as a falsy proxy; a real number survives float().
    try:
        thr = float(peak_threshold) if peak_threshold is not None else None
    except (TypeError, ValueError):
        thr = None
    # Only pass the new kwarg when actually set, so a cached pre-round-7 wheel
    # (no `peak_threshold` in its signature) still serves the default flow; an
    # EXPLICIT threshold against such a wheel gets the clear stale-wheel error.
    kw = {} if thr is None else {'peak_threshold': thr}
    stale = ('Damping needs a newer engine: the loaded pydvma wheel predates '
             'the interactive damping controls. Reload once builds settle.')
    if str(method) == 'cwt':
        if not hasattr(analysis, 'calculate_damping_from_cwt'):
            raise ValueError(
                'CWT damping needs a newer engine: the loaded pydvma wheel has no '
                'calculate_damping_from_cwt. Reload once builds settle, or use the '
                'STFT method.'
            )
        try:
            fn, Qn, fit = analysis.calculate_damping_from_cwt(
                td, n_chan=int(ch), start_time=st,
                voices_per_octave=int(voices_per_octave), w0=float(w0), **kw)
        except TypeError:
            raise ValueError(stale)
    else:
        try:
            fn, Qn, fit = analysis.calculate_damping_from_sono(
                td, n_chan=int(ch), nperseg=int(nperseg), start_time=st, **kw)
        except TypeError:
            raise ValueError(stale)
    out = {
        'fn': _arr(np.asarray(fn)), 'Qn': _arr(np.asarray(Qn)),
        # Per-fitted-mode decay lines: present on EVERY wheel vintage (the Qt
        # DampingFitWindow always consumed these).
        'fits': [
            {
                't_fit': _arr(np.asarray(m['t_fit'], dtype=np.float64)),
                'real_fit': _arr(np.asarray(m['real_fit'], dtype=np.float64)),
                'real_data': _arr(np.asarray(m['real_data'], dtype=np.float64)),
                'f_peak': float(m['f_peak']),
                'Qn': float(m['Qn']),
            }
            for m in fit['fits']
        ],
    }
    if 'threshold' in fit:
        # Round-7+ wheels: the peak-picking context for the interactive panel.
        out.update({
            'start_time': float(fit['start_time']),
            'threshold': float(fit['threshold']),
            'slice_freq': _arr(np.asarray(fit['slice_freq'], dtype=np.float64)),
            'slice_mag': _arr(np.asarray(fit['slice_mag'], dtype=np.float64)),
            'peaks_freq': _arr(np.asarray(fit['peaks_freq'], dtype=np.float64)),
            'peaks_mag': _arr(np.asarray(fit['peaks_mag'], dtype=np.float64)),
        })
    return out


def calc_damping_bands(time_axis, time_data, n_channels, fs, ch, bands='octave',
                       start_time=None, f_min=None, f_max=None):
    """Band-centred decay metrics via the Schroeder integral (Sono card,
    round-7 'by band' damping mode).

    Wraps ``analysis.calculate_damping_by_band``: zero-phase band-pass filter
    bank (``bands``: 'all' | 'octave' | 'third-octave' | 'tenth-decade'),
    per-band Schroeder EDC, straight-line fits -> EDT / T20 / T30 / T60 and
    the equivalent band-centred ``Qn``. NaN metrics mean that band's EDC
    lacked the fit window's decay range — the UI shows those as gaps, not
    errors.

    ``start_time`` (s) picks the decay start (None infers from pretrigger);
    ``f_min`` / ``f_max`` bound the ladder (None -> pydvma's ``4/T .. 0.4*fs``
    default). Returns the ladder arrays plus per-band EDC + T60-fit-line
    plotting payloads (decimated in pydvma to keep the transfer small).

    Stale-wheel guard: raises a clear "needs a newer engine" error when the
    loaded wheel predates ``calculate_damping_by_band``.
    """
    if not hasattr(analysis, 'calculate_damping_by_band'):
        raise ValueError(
            'Band damping needs a newer engine: the loaded pydvma wheel has no '
            'calculate_damping_by_band. Reload once builds settle, or use the '
            'peaks method.'
        )
    td = _time_data(time_axis, time_data, n_channels, fs)
    st = float(start_time) if start_time else None
    fr = None
    if f_min and f_max:
        fr = (float(f_min), float(f_max))
    out = analysis.calculate_damping_by_band(
        td, n_chan=int(ch), bands=str(bands), start_time=st, f_range=fr)
    res = {
        'bands': out['bands'],
        'start_time': float(out['start_time']),
        'fc': _arr(out['fc']),
        'f_lo': _arr(out['f_lo']), 'f_hi': _arr(out['f_hi']),
        'EDT': _arr(out['EDT']), 'T20': _arr(out['T20']),
        'T30': _arr(out['T30']), 'T60': _arr(out['T60']),
        'Qn': _arr(out['Qn']),
        'band_data': [],
    }
    for b in out['band_data']:
        item = {
            'fc': b['fc'], 'f_lo': b['f_lo'], 'f_hi': b['f_hi'],
            'edc_t': _arr(b['edc_t']), 'edc_db': _arr(b['edc_db']),
        }
        if 'fit_t' in b:
            item['fit_t'] = _arr(b['fit_t'])
            item['fit_db'] = _arr(b['fit_db'])
        res['band_data'].append(item)
    return res


# --------------------------------------------------------------------------- #
# Matlab export (Wave-A shared spine — Agent 2 calls this)
# --------------------------------------------------------------------------- #

def _common_axis(axes, decimated=False):
    """Common axis for interpolation, matching ``file.export_to_matlab``.

    For frequency/tf: ``arange(0, fmax + df, df)`` with the FINEST ``df`` and
    the largest ``fmax`` across sets. For time (``decimated=False`` unused here;
    time uses its own branch). Sets are then ``np.interp``-ed onto this axis and
    column-concatenated.
    """
    df = np.inf
    fmax = 0.0
    for ax in axes:
        a = np.asarray(ax, dtype=np.float64)
        if a.size < 2:
            continue
        df = min(df, float(np.mean(np.diff(a))))
        fmax = max(fmax, float(a[-1]))
    if not np.isfinite(df) or df <= 0:
        return np.zeros(0)
    return np.arange(0, fmax + df, df)


def export_mat(time_sets=None, freq_sets=None, tf_sets=None):
    """Build a MATLAB ``.mat`` from the working sets, matching pydvma's schema.

    Reproduces ``file.export_to_matlab`` (spec brief §D) WITHOUT reconstructing
    a full DataSet: each per-kind set arrives as ``{axis, data|re/im, cols}``
    from ``actions.exportMat`` and is interpolated onto a per-kind common axis
    (finest resolution, widest span), then column-concatenated. Keys:
    ``time_axis_all/time_data_all`` (real), ``freq_axis_all/freq_data_all`` and
    ``tf_axis_all/tf_data_all`` (complex, preserved). No coherence; RAW values
    (calibration is a display-time transform, not baked into exports). Only
    kinds with data are included. Returns ``{'mat': <bytes>}`` — a JS
    ``Uint8Array`` the client saves.
    """
    from scipy import io as sio

    data_matlab = {}
    time_sets = list(time_sets or [])
    freq_sets = list(freq_sets or [])
    tf_sets = list(tf_sets or [])

    # TIME (real) — common axis arange(0, T, 1/fs) with the max T / max fs.
    if time_sets:
        T = 0.0
        fs = 0.0
        n_time = 0
        parsed = []
        for s in time_sets:
            ax = np.asarray(_get(s, 'axis'), dtype=np.float64)
            cols = int(_get(s, 'cols'))
            dat = np.asarray(_get(s, 'data'), dtype=np.float64).reshape(-1, cols)
            parsed.append((ax, dat))
            n = ax.size
            if n > 1:
                T = max(T, float(ax[-1] * n / (n - 1)))
                fs = max(fs, 1.0 / float(np.mean(np.diff(ax))))
            n_time += cols
        if fs > 0 and T > 0:
            t = np.arange(0, T, 1.0 / fs)
            all_ = np.zeros((len(t), n_time))
            c = -1
            for ax, dat in parsed:
                for i in range(dat.shape[1]):
                    c += 1
                    all_[:, c] = np.interp(t, ax, dat[:, i], right=0)
            data_matlab['time_axis_all'] = np.transpose(np.atleast_2d(t))
            data_matlab['time_data_all'] = all_

    # FFT + TF (complex) share the same interp/concat shape.
    for key, sets in (('freq', freq_sets), ('tf', tf_sets)):
        if not sets:
            continue
        parsed = []
        n_cols = 0
        for s in sets:
            ax = np.asarray(_get(s, 'axis'), dtype=np.float64)
            cols = int(_get(s, 'cols'))
            re = np.asarray(_get(s, 're'), dtype=np.float64).reshape(-1, cols)
            im_raw = _get(s, 'im')
            im = (np.zeros_like(re) if im_raw is None
                  else np.asarray(im_raw, dtype=np.float64).reshape(-1, cols))
            parsed.append((ax, re + 1j * im))
            n_cols += cols
        f = _common_axis([ax for ax, _ in parsed])
        if f.size == 0:
            continue
        all_ = np.zeros((len(f), n_cols), dtype=complex)
        c = -1
        for ax, G in parsed:
            for i in range(G.shape[1]):
                c += 1
                all_[:, c] = np.interp(f, ax, G[:, i], right=0)
        data_matlab['{}_axis_all'.format(key)] = np.transpose(np.atleast_2d(f))
        data_matlab['{}_data_all'.format(key)] = all_

    buf = io.BytesIO()
    sio.savemat(buf, data_matlab)
    return {'mat': buf.getvalue()}
