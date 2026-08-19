# -*- coding: utf-8 -*-
"""
Created on Sun Sep  2 20:16:26 2018

@author: tb267
"""

from . import datastructure
from . import _signature

import numpy as np
from scipy import signal
import copy
import peakutils as pu
from scipy.optimize import curve_fit

MESSAGE = ''


def _range_to_list(time_range):
    """A time range as two plain floats for the JSON manifest.

    Args:
        time_range (list or np.ndarray or None): the range to
            normalise; anything that is not a pair of numbers (None, a
            `PlotData`, a malformed argument) becomes ``None``.

    Returns ``[t_start, t_stop]`` as plain floats, or ``None``.
    """
    try:
        return [float(time_range[0]), float(time_range[1])]
    except (TypeError, ValueError, IndexError, KeyError):
        return None


def _stamp_source(result, time_data, source_settings):
    """Record the compute chain on a derived analysis result.

    Sets ``source_signature`` (a hash of the SOURCE samples + rate, see
    `pydvma._signature`) and ``source_settings`` (the analysis knobs
    that call used, as JSON-safe scalars) on `result`, in place. Both
    are optional attributes the container round-trips when present, so
    a loaded file can flag a chain whose source has since changed.

    Args:
        result (FreqData or TfData): the freshly built derived item.
        time_data (TimeData or iterable): the source measurement(s) the
            result was computed from.
        source_settings (dict): the analysis parameters actually used,
            already reduced to JSON-safe scalars.
    """
    result.source_signature = _signature.source_signature(time_data)
    result.source_settings = source_settings


def calculate_fft(time_data,time_range=None,window=None):
    '''
    Args:
        time_data (<TimeData> object): time series data
        time_range (list or np.ndarray, optional): 2x1 numpy array to specify data segment to use
        window (str, optional): window function name (e.g., 'hann', 'hamming', 'blackman'), or None for rectangular (boxcar) window
    '''
    
    if time_data.__class__.__name__ != 'TimeData':
        raise Exception('Input data needs to be single <TimeData> object')
    

    if time_range is None:
        ### use all data
        time_range_copy = time_data.time_axis[[0,-1]]

    elif time_range.__class__.__name__ == 'PlotData':
        time_range_copy=time_range.ax.get_xbound()

    else:
        # Plain list / ndarray of [t_start, t_stop]
        time_range_copy = time_range

    settings = copy.copy(time_data.settings)
    settings.window = window
    settings.time_range = time_range_copy

    s1 = time_data.time_axis >= time_range_copy[0]
    s2 = time_data.time_axis <= time_range_copy[1]
    selection = s1 & s2
    data_selected = time_data.time_data[selection,:]
    N = len(data_selected[:,0])
    
    if window is None:
        w = signal.windows.get_window('boxcar',N)
    else:
        w = signal.windows.get_window(window,N)
        
    # Broadcast the window across potentially multiple channels
    data_selected = w[:, None] * data_selected
        
    fdata = np.fft.rfft(data_selected,axis=0)
    faxis = np.fft.rfftfreq(N,1/time_data.settings.fs)

    freq_data = datastructure.FreqData(
        faxis, fdata, settings,
        channel_cal_factors=np.asarray(time_data.channel_cal_factors, dtype=float).copy(),
        units=time_data.units,
        id_link=time_data.unique_id, test_name=time_data.test_name,
    )

    _stamp_source(freq_data, time_data, {
        'calc': 'fft',
        'window': None if window is None else str(window),
        'time_range': _range_to_list(time_range_copy),
    })

    return freq_data

def multiply_by_power_of_iw(data,power,channel_list):
    
    if data.__class__.__name__ == 'TfData':
        iw = 1j*2*np.pi * data.freq_axis[:,None]
        if power<0:
            iw[0]=np.inf
        data.tf_data[:,channel_list] = (iw**power) * data.tf_data[:,channel_list]
        # keep track of multiplication powers
        if hasattr(data,'iw_power_counter'):
            data.iw_power_counter[channel_list] += power
        else:
            data.iw_power_counter = np.zeros(len(data.tf_data[0,:]))
            data.iw_power_counter[channel_list] = power
            
    elif data.__class__.__name__ == 'FreqData':
        iw = 1j*2*np.pi * data.freq_axis[:,None]
        if power<0:
            iw[0]=np.inf
        data.freq_data[:,channel_list] = (iw**power) * data.freq_data[:,channel_list]
        if hasattr(data,'iw_power_counter'):
            data.iw_power_counter[channel_list] += power
        else:
            data.iw_power_counter = np.zeros(len(data.freq_data[0,:]))
            data.iw_power_counter[channel_list] = power
    else:
        print('Expecting input argument of type <FreqData> or <TfData>')

            
    return data




def best_match(tf_data_list,freq_range=None,set_ref=0,ch_ref=0):
    '''
    Args:
        tf_data_list (<TfDataList> object): transfer function data
        freq_range (list or np.ndarray, optional): 2x1 numpy array to specify data segment to use
        set_ref (int, optional): reference set index, default is 0
        ch_ref (int, optional): reference channel index, default is 0
    '''
    
    if tf_data_list.__class__.__name__ != 'TfDataList':
        raise ValueError('Input data needs to be single <TfData> object')
    

    if freq_range is None:
        ### use all data
        freq_range_copy = tf_data_list[set_ref].freq_axis[[0,-1]]
        
    elif freq_range.__class__.__name__ == 'PlotData':
        freq_range_copy=freq_range.tfax.get_xbound()
        
    else:
        freq_range_copy = freq_range
        
    
    settings = copy.copy(tf_data_list[0].settings)
    settings.freq_range = freq_range_copy

    
    n_set = len(tf_data_list)
    
    s1 = tf_data_list[set_ref].freq_axis >= freq_range_copy[0]
    s2 = tf_data_list[set_ref].freq_axis <= freq_range_copy[1]
    selection_ref = s1 & s2
    # choose 0-1 scale to make dimensions of data compatible
    f_ref = tf_data_list[set_ref].freq_axis[selection_ref]
        
    factors = []
    for ns in range(n_set):
        f=[]
        n_chan = len(tf_data_list[ns].tf_data[0,:])
        s1 = tf_data_list[ns].freq_axis >= freq_range_copy[0]
        s2 = tf_data_list[ns].freq_axis <= freq_range_copy[1]
        selection = s1 & s2
        f_sel = tf_data_list[ns].freq_axis[selection]
        N_ref = len(f_ref)
        N_sel = len(f_sel)
        f_newref = np.linspace(freq_range[0],freq_range[1],np.max([N_ref,N_sel]))
        
        for nc in range(n_chan):
            # could make more efficient by doing all channels at once
            x = tf_data_list[ns].freq_axis
            y = tf_data_list[ns].tf_data[:,nc]
            a = np.interp(f_newref,x,y)
            a2d = a.reshape(np.size(a),1)
            
            x = tf_data_list[set_ref].freq_axis
            y = tf_data_list[set_ref].tf_data[:,ch_ref]
            b = np.interp(f_newref,x,y)
            b2d = b.reshape(np.size(b),1)
            
            # use least squares only to get sign of factor
            # get scale factor just by matching rms values
            LS = np.linalg.lstsq(a2d.real, b2d.real, rcond=None)
            sign = np.sign(LS[0][0])
            f += [sign*np.sqrt(np.mean(np.abs(b)**2)) / np.sqrt(np.mean(np.abs(a)**2))]
            
            
        f = np.array(f)
        factors.append(f)
    
    return factors



def calculate_cross_spectrum_matrix(time_data, time_range=None, window=None, N_frames=1, overlap=0.5):
    '''
    Compute the full cross-spectrum matrix and coherence matrix of a
    multi-channel `TimeData` block using Welch's method.

    Equivalent to looping ``scipy.signal.csd`` (with ``scaling='spectrum'``)
    and ``scipy.signal.coherence`` over every channel pair, but vectorised:
    each segment is FFT'd once across all channels, and the cross-spectrum
    matrix is formed as a tensor outer product ``conj(X[:,f,i]) * X[:,f,j]``
    averaged over segments. Output is byte-equivalent to the scipy reference
    to within FFT round-off.

    The DC bin (and, for an even segment length, the Nyquist bin) of the
    coherence matrix is undefined under a boxcar window: constant detrending
    zeroes each segment's mean, so the auto-spectra there are pure round-off
    and ``Cxy`` is a 0/0 ratio. It is returned as 0 in that degenerate case
    rather than NaN; treat it as "no information at DC", not a real coherence.

    Memory: the per-segment windows are built with ``as_strided`` directly at
    the final ``(N_chans, N_seg, nperseg)`` shape rather than via
    ``sliding_window_view`` + slicing. The latter materialises an intermediate
    whose *nominal* size is ``N_chans * (N_samples - nperseg + 1) * nperseg``;
    on a 32-bit build (pyodide/WASM, ``npy_intp`` = int32) numpy rejects that
    view with "array is too big" for a large ``nperseg`` on a long, high-rate
    record, even though it is only a view. The direct stride keeps the nominal
    size at ``N_chans * N_seg * nperseg`` and is numerically byte-identical.

    Args:
        time_data (<TimeData> object): time series data
        time_range (list or np.ndarray, optional): 2x1 numpy array to specify data segment to use
        window (None or str): window function name; None defaults to 'boxcar'
        N_frames (int): number of frames to average over
        overlap (float): frame overlap fraction between 0 and 1
    '''
    # TODO iterate over list of timedata... but need new dataset type?

    if window is None:
        window = 'boxcar'

    if time_data.__class__.__name__ != 'TimeData':
        raise Exception('Input data needs to be single <TimeData> object')

    if time_range is None:
        ### use all data
        time_range = time_data.time_axis[[0,-1]]

    elif time_range.__class__.__name__ == 'PlotData':
        time_range=time_range.ax.get_xbound()

    settings = copy.copy(time_data.settings)
    settings.window = window
    settings.time_range = time_range
    settings.N_frames = N_frames
    settings.overlap = overlap

    ## Select data range to use
    s1 = time_data.time_axis >= time_range[0]
    s2 = time_data.time_axis <= time_range[1]
    selection = s1 & s2
    data_selected = time_data.time_data[selection,:]

    N_samples, N_chans = data_selected.shape
    nperseg = int(np.ceil(N_samples / (N_frames+1) / (1-overlap)))
    noverlap = int(np.ceil(overlap*nperseg))
    step = nperseg - noverlap
    # scipy._spectral_helper uses (N_samples - noverlap) // step segments.
    N_seg = max(1, (N_samples - noverlap) // step)
    fs = time_data.settings.fs
    # Guard BEFORE the as_strided below: a window longer than the record
    # (only possible for N_frames < 1) must raise, not read out of bounds.
    # The previous sliding_window_view raised its own ValueError here;
    # as_strided performs no bounds checking, so the check is now ours.
    if nperseg > N_samples:
        raise ValueError(
            f'N_frames={N_frames} gives a segment length nperseg={nperseg} '
            f'longer than the record ({N_samples} samples); N_frames must '
            f'be at least 1.'
        )

    win = signal.windows.get_window(window, nperseg)

    # Build segments with the FFT axis last and contiguous, matching
    # scipy's `_fft_helper` layout. This is important: numpy's pairwise
    # summation block order depends on memory layout, and detrending a
    # non-contiguous axis subtly changes the per-segment residual at the
    # DC bin (~1e-17 in the mean → O(1) noise in coherence at DC).
    # Output shape: (N_chans, N_seg, nperseg).
    #
    # Stride DIRECTLY to the N_seg decimated windows. The obvious
    # `sliding_window_view(data_T, nperseg)[..., ::step, :]` first
    # materialises EVERY one of the (N_samples - nperseg + 1) sliding
    # windows and then throws most away; even though that intermediate is
    # only a strided view, numpy validates its NOMINAL size
    # (N_chans × (N_samples - nperseg + 1) × nperseg). On a 32-bit build
    # (e.g. pyodide/WASM, where ``npy_intp`` is int32 and the size ceiling
    # is 2**31-1 bytes) that check raises "array is too big" for large
    # nFFT on a long, high-fs record — a 2 s, 44.1 kHz capture at
    # N_frames≈23 gives nperseg≈7350 and a ~4.7 GB nominal view — even
    # though the real work is tiny. Building the final
    # (N_chans, N_seg, nperseg) view by hand with `as_strided` has the
    # SAME strides and memory layout (so detrend/FFT stay byte-identical)
    # but a nominal size of only N_chans × N_seg × nperseg.
    data_T = np.ascontiguousarray(data_selected.T)
    row_stride, col_stride = data_T.strides
    sv = np.lib.stride_tricks.as_strided(
        data_T,
        shape=(N_chans, N_seg, nperseg),
        strides=(row_stride, step * col_stride, col_stride),
        writeable=False,
    )
    segs = signal.detrend(sv, axis=-1, type='constant')
    segs *= win

    # (N_chans, N_seg, N_freq)
    X = np.fft.rfft(segs, axis=-1)

    # Cross-spectrum: Pxy[i, j, f] = mean_seg conj(X[i,seg,f]) * X[j,seg,f]
    # matches scipy.signal.csd(x=channel_i, y=channel_j) convention.
    Pxy = np.einsum('isf,jsf->ijf', X.conj(), X) / N_seg

    # Spectrum scaling and one-sided correction.
    Pxy *= 1.0 / (win.sum() ** 2)
    if nperseg % 2 == 0:
        Pxy[:, :, 1:-1] *= 2.0
    else:
        Pxy[:, :, 1:] *= 2.0

    # Coherence Cxy[i,j,f] = |Pxy[i,j,f]|^2 / (Pxx[i,i,f] * Pxx[j,j,f]).
    # The spectrum-vs-density scaling and the one-sided 2x factor cancel,
    # so this is identical to scipy.signal.coherence's output.
    #
    # Guard the division: where a channel carries no energy at a bin the
    # denominator is zero and the cross-coherence is genuinely 0/0
    # (undefined). Computing it anyway either raises an "invalid value
    # encountered in divide" RuntimeWarning (exactly-zero auto-power) or
    # returns a meaningless ratio of floating-point round-off (underflowed
    # auto-power). `where=denom > 0` handles the first; the explicit mask
    # below handles the second.
    Pxx_diag = np.real(np.diagonal(Pxy, axis1=0, axis2=1)).T   # (N_chans, N_freq)
    denom = Pxx_diag[:, None, :] * Pxx_diag[None, :, :]
    Cxy = np.divide(np.abs(Pxy) ** 2, denom,
                    out=np.zeros(Pxy.shape, dtype=float),
                    where=denom > 0)

    # Explicitly zero the cross-coherence at degenerate bins -- those whose
    # auto-spectrum is only floating-point round-off, not real energy. This
    # catches the DC bin (and, for an even segment length, the Nyquist bin) of
    # a mean-detrended boxcar segment, where constant detrending leaves the
    # auto-power at ~1e-34. Averaging conj(X_i)X_j and |X_i|^2 independently
    # over segments there gives a 0/0 ratio of round-off; reporting 0 ("no
    # measurable coherence") is honest and deterministic, rather than the
    # ~O(1) noise the division emits.
    #
    # Only applies with more than one segment. With a single segment the
    # estimator is conj(X_i)X_j / (|X_i| |X_j|), which is identically 1 for
    # every pair and bin regardless of magnitude (the tiny DC values cancel
    # exactly) -- the well-known "single-frame coherence is 1" property, which
    # must not be clobbered. The diagonal (auto-coherence) is always left at 1.
    # Window functions other than boxcar reintroduce a non-zero segment mean,
    # so their DC bin carries real energy and is untouched.
    if N_seg > 1:
        peak = Pxx_diag.max(axis=1, keepdims=True)             # (N_chans, 1)
        degenerate = Pxx_diag <= 1e-12 * peak                  # (N_chans, N_freq)
        deg_pair = degenerate[:, None, :] | degenerate[None, :, :]
        diag = np.arange(N_chans)
        deg_pair[diag, diag, :] = False
        Cxy[deg_pair] = 0.0

    f = np.fft.rfftfreq(nperseg, 1.0 / fs)

    cross_spec_data = datastructure.CrossSpecData(
        f, Pxy, Cxy, settings,
        channel_cal_factors=np.asarray(time_data.channel_cal_factors, dtype=float).copy(),
        units=time_data.units,
        id_link=time_data.unique_id, test_name=time_data.test_name,
    )

    return cross_spec_data


def calculate_cross_spectra_averaged(time_data_list, time_range=None, window=None):
    '''
    Calculates cross spectra averaged across ensemble of time_data_list. Note that
    this expects a <TimeDataList> of <TimeData> objects.

    Takes each time series as an independent measurement.

    Intended for averaged transfer functions from separate measurements, e.g. impulse hammer tests.

    Does not average data across sub-frames.

    Args:
        time_data_list (<TimeDataList> object): a list of time series data
        time_range (list or np.ndarray, optional): 2x1 numpy array to specify data segment to use
        window (None or str): type of window to use, default is None.
    '''
    
    if time_data_list.__class__.__name__ != 'TimeDataList':
        raise Exception('Input argument must be <TimeDataList> object.')

    id_link_list = []
    for td in time_data_list:
        id_link_list += [td.unique_id]
    
    settings = copy.copy(time_data_list[0].settings)
    settings.window = window
    settings.time_range = time_range

    
    N_ensemble = len(time_data_list)
    Pxy_av = 0
    for td in time_data_list:
        cross_spec_data = calculate_cross_spectrum_matrix(td, time_range=time_range, window=window, N_frames=1)
        Pxy_av += cross_spec_data.Pxy / N_ensemble
    
    ch_all = np.arange(time_data_list[0].settings.channels)
    Cxy = np.zeros([len(ch_all),len(ch_all),len(Pxy_av[0,0,:])])
    for ch_in in ch_all:
        for ch_out in ch_all:
            Cxy[ch_in,ch_out,:] = np.abs(Pxy_av[ch_in,ch_out,:])**2 / (np.abs(Pxy_av[ch_in,ch_in,:]) * np.abs(Pxy_av[ch_out,ch_out,:]))
    
    
    cross_spec_data_av = datastructure.CrossSpecData(
        cross_spec_data.freq_axis, Pxy_av, Cxy, settings,
        channel_cal_factors=np.asarray(time_data_list[0].channel_cal_factors, dtype=float).copy(),
        units=time_data_list[0].units,
        id_link=id_link_list, test_name=time_data_list[0].test_name,
    )

    return cross_spec_data_av


def calculate_tf(time_data, ch_in=0, time_range=None, window=None, N_frames=1, overlap=0.5):
    '''
    Args:
        time_data (<TimeData> object): time series data
        ch_in (int): index of input channel
        time_range (list or np.ndarray, optional): 2x1 numpy array to specify data segment to use
        window (None or str): apply filter to data before fft or not
        N_frames (int): number of frames to average over
        overlap (float): frame overlap fraction between 0 and 1
    '''
    if time_data.__class__.__name__ != 'TimeData':
        raise Exception('Input data needs to be single <TimeData> object')


    settings = copy.copy(time_data.settings)
    settings.window = window
    settings.time_range = time_range
    
    ## compute cross spectra
    cross_spec_data = calculate_cross_spectrum_matrix(time_data, time_range=time_range, window=window, N_frames=N_frames, overlap=overlap)
    f = cross_spec_data.freq_axis
    Pxy = cross_spec_data.Pxy
    Cxy = cross_spec_data.Cxy
    ## identify transfer functions and corresponding coherence
    
    ch_all = np.arange(len(time_data.time_data[0,:]))
    ch_out_set = np.setxor1d(ch_all,ch_in)
    
    tf_data = np.zeros([len(f),len(ch_out_set)],dtype=complex)
    tf_coherence = np.zeros([len(f),len(ch_out_set)])
    ch_count = -1
    for ch_out in ch_out_set:
        ch_count += 1
        tf_data[:,ch_count] = Pxy[ch_in,ch_out,:] / Pxy[ch_in,ch_in,:]
        tf_coherence[:,ch_count] = Cxy[ch_out,ch_in,:]
        
    settings.ch_in = ch_in
    settings.ch_out_set = ch_out_set

    # TF inherits the calibration *ratio*: a calibrated input x_phys =
    # cal_in * x_raw and output y_phys = cal_out * y_raw give a calibrated
    # TF of (cal_out / cal_in) * (Y_raw / X_raw). So the stored per-output
    # cal_factor is cal[ch_out] / cal[ch_in]. Consumers (plotting.py,
    # modal.py) multiply tf_data by these to get the calibrated TF.
    src_cal = np.asarray(time_data.channel_cal_factors, dtype=float)
    tf_cal = src_cal[ch_out_set] / src_cal[ch_in]

    # Units of the TF are out/in by convention. We carry both through so
    # downstream code (or the user) can recover the ratio.
    tf_units = _tf_units_from_source(time_data.units, ch_in, ch_out_set)

    tfdata = datastructure.TfData(
        f, tf_data, tf_coherence, settings,
        channel_cal_factors=tf_cal,
        units=tf_units,
        id_link=time_data.unique_id, test_name=time_data.test_name,
    )

    _stamp_source(tfdata, time_data, {
        'calc': 'tf',
        'window': None if window is None else str(window),
        # the EFFECTIVE range: cross_spec_data.settings.time_range is
        # the full record when the argument was None
        'time_range': _range_to_list(cross_spec_data.settings.time_range),
        'ch_in': int(ch_in),
        'N_frames': int(N_frames),
        'overlap': float(overlap),
    })

    return tfdata


def _tf_units_from_source(src_units, ch_in, ch_out_set):
    '''Build the TF units list as "<out_unit>/<in_unit>" per output
    channel, or return None if the source units are not set. Safe against
    short/missing entries — returns None on any indexing trouble.'''
    if src_units is None:
        return None
    try:
        in_unit = src_units[ch_in]
        return ['{}/{}'.format(src_units[k], in_unit) for k in ch_out_set]
    except (IndexError, TypeError):
        return None


def calculate_tf_averaged(time_data_list, ch_in=0, time_range=None, window=None):
    '''
    Calculates transfer function averaged across an ensemble of separate
    measurements. Note that this expects a <TimeDataList> object.

    Takes each time series as an independent measurement: the
    cross-spectra are averaged across the ensemble, then the H1
    estimator ``Pxy[ch_in, ch_out] / Pxy[ch_in, ch_in]`` is formed —
    the same phase convention as `calculate_tf`.

    Intended for averaged transfer functions from separate measurements, e.g. impulse hammer tests.

    Does not average data across sub-frames.

    Args:
        time_data_list (<TimeDataList> object): a list of time series data
        ch_in (int): index of input channel
        time_range (list or np.ndarray, optional): 2x1 numpy array to specify data segment to use
        window (None or str): type of window to use, default is None.
    '''
    
    if time_data_list.__class__.__name__ != 'TimeDataList':
        raise Exception('Input argument must be <TimeDataList> object.')


    id_link_list = []
    for td in time_data_list:
        id_link_list += [td.unique_id]
        
    N_ensemble = len(time_data_list)
    Pxy_av = 0
    count = -1
    for td in time_data_list:
        count += 1
        ch_all = np.arange(len(td.time_data[0,:]))
        ch_out_set = np.setxor1d(ch_all,ch_in)
        cross_spec_data = calculate_cross_spectrum_matrix(td, time_range=time_range, window=window, N_frames=1)
        f = cross_spec_data.freq_axis
        Pxy = cross_spec_data.Pxy
        Pxy_av += Pxy / N_ensemble
    
    tf_data = np.zeros([len(f),len(ch_out_set)],dtype=complex)
    tf_coherence = np.zeros([len(f),len(ch_out_set)])    
    ch_count = -1
    for ch_out in ch_out_set:
        ch_count += 1
        # H1 estimator, same convention as calculate_tf: with
        # Pxy[i, j] = conj(X_i)·X_j the numerator must be
        # Pxy[ch_in, ch_out] — the transposed element is its complex
        # conjugate and silently negates the TF phase.
        tf_data[:,ch_count] = Pxy_av[ch_in,ch_out,:] / Pxy_av[ch_in,ch_in,:]
        tf_coherence[:,ch_count] = np.abs(Pxy_av[ch_in,ch_out,:])**2 / (np.abs(Pxy_av[ch_in,ch_in,:]) * np.abs(Pxy_av[ch_out,ch_out,:]))

    settings = copy.copy(td.settings)
    settings.window = window
    settings.time_range = time_range
    settings.ch_in = ch_in
    settings.ch_out_set = ch_out_set

    src_cal = np.asarray(time_data_list[0].channel_cal_factors, dtype=float)
    tf_cal = src_cal[ch_out_set] / src_cal[ch_in]
    tf_units = _tf_units_from_source(time_data_list[0].units, ch_in, ch_out_set)

    tfdata = datastructure.TfData(
        f, tf_data, tf_coherence, settings,
        channel_cal_factors=tf_cal,
        units=tf_units,
        id_link=id_link_list, test_name=time_data_list[0].test_name,
    )

    _stamp_source(tfdata, time_data_list, {
        'calc': 'tf_averaged',
        'window': None if window is None else str(window),
        # the raw argument: the ensemble has no single effective range
        'time_range': _range_to_list(time_range),
        'ch_in': int(ch_in),
        'N_ensemble': int(N_ensemble),
    })

    return tfdata


#%% BEST LINEAR APPROXIMATION
def calculate_bla(time_data_list, run_spec):
    '''
    Best Linear Approximation with noise/nonlinearity separation
    (Schoukens random-phase multisine method, SISO and MISO unified).

    Consumes the ``M x n_exc`` captures of a BLA run (ordering
    ``[(m, e) for m in range(M) for e in range(n_exc)]``), slices exact
    ``N``-sample periods after discarding ``t_periods`` transients, DFTs
    each period (no window — the data is periodic by construction) and
    estimates, per response channel: the BLA frequency-response matrix
    (mean over realisations of the per-realisation ``n_exc x n_exc``
    solve), the noise standard deviation ``bla_sigma_n`` (period-to-
    period scatter propagated through the input-matrix inverse, with the
    ``1/P`` of the period average folded in) and the nonlinear-distortion
    standard deviation ``bla_sigma_nl`` (realisation scatter minus that
    noise variance, floored at zero).

    Only the excited bins are analysed, so the returned frequency axis is
    ``k * fs / N`` over ``k1..k2`` — a sparse, exactly-on-bin axis, not
    the full rfft grid.

    Start-time offsets between captures are harmless for measured x: x
    and y share the ADC clock, so the common phase rotation
    ``exp(-j*w*tau)`` cancels in the solve. For ``x_mode='commanded'``
    the input spectra are instead regenerated analytically from the
    seed, using the same phase and scaling law as
    `acquisition.multisine_generator`; that is only valid when AO and AI
    are hardware-synced (the caller enforces that), because otherwise
    per-capture start jitter leaks into the realisation scatter and
    corrupts sigma_NL.

    Unlike the other ensemble entry points this takes a plain list, not a
    <DataSet> or a <TimeDataList> method: the captures carry no record of
    their own ``(m, e)`` indices, so the ORDER of the list is load-bearing
    input, and a DataSet — an unordered bag the user can add to, reorder
    or partly delete — cannot express it. The caller assembles the list in
    run order; a wrong length is caught here, a wrong order is not.

    Args:
        time_data_list (list): The ``M * n_exc`` <TimeData> captures of
            the run, in ``(m, e)`` order — realisation outer, experiment
            inner.
        run_spec (dict): BlaRunSpec — ``multisine`` (a dict of
            n_samples, k1, k2, p_periods, t_periods, seed, amp_rms,
            n_exc, M), ``x_mode`` ('measured' or 'commanded'),
            ``x_channels`` (per-excitation input channel indices, or
            None for commanded x), ``resp_channels`` (response channel
            indices) and ``fs`` (the actual capture rate in Hz).

    Returns a <TfDataList> of ``n_exc`` <TfData> objects, one per
    excitation, each holding every response channel as a column of
    `tf_data` and carrying `bla_sigma_nl`, `bla_sigma_n` and the `bla`
    run-spec dict. `tf_coherence` is None: coherence is not the right
    quality measure here — the sigma pair is. Both sigmas are
    PER-REALISATION standard deviations in linear FRF units — the
    distortion and noise level of a single realisation, not the error bar
    on the returned BLA, which is ``sqrt(M)`` smaller
    (``sigma_BLA = sigma_tot / sqrt(M)``).
    '''
    # Unpack the WHOLE spec up front, including the fields only one
    # branch needs: a missing key must fail before the analysis spends
    # minutes on the capture loop, not after it.
    ms = run_spec['multisine']
    N, P, T_per = int(ms['n_samples']), int(ms['p_periods']), int(ms['t_periods'])
    M, n_exc = int(ms['M']), int(ms['n_exc'])
    seed, amp_rms = int(ms['seed']), float(ms['amp_rms'])
    fs = float(run_spec['fs'])
    k_bins = np.arange(int(ms['k1']), int(ms['k2']) + 1)
    resp = [int(c) for c in run_spec['resp_channels']]
    n_resp = len(resp)
    commanded = (run_spec.get('x_mode') == 'commanded')
    x_ch = None if commanded else run_spec.get('x_channels')

    if len(time_data_list) != M * n_exc:
        raise ValueError(
            'BLA run needs M*n_exc = {} captures, got {}'.format(
                M * n_exc, len(time_data_list)))
    if M < 2:
        raise ValueError('BLA needs at least M = 2 realisations to '
                          'estimate the realisation scatter (got {})'.format(M))
    if P < 2:
        raise ValueError('BLA needs at least P = 2 steady-state periods to '
                          'estimate the noise (got {})'.format(P))
    # Same bound as acquisition.multisine_generator: for even N that
    # excludes the Nyquist bin, whose rfft coefficient is real and cannot
    # carry the random phase the commanded-x regeneration assumes.
    if not (1 <= int(ms['k1']) <= int(ms['k2']) <= (N - 1) // 2):
        raise ValueError(
            'excited bins must satisfy 1 <= k1 <= k2 <= (N-1)//2 '
            '(got k1={}, k2={}, N={})'.format(ms['k1'], ms['k2'], N))
    if n_resp < 1:
        raise ValueError('BLA needs at least one response channel')
    if not commanded:
        if x_ch is None or len(x_ch) != n_exc:
            raise ValueError(
                "measured-x mode needs one 'x_channels' entry per "
                'excitation: n_exc={} but x_channels={}'.format(n_exc, x_ch))
        x_ch = [int(c) for c in x_ch]
    n_ch = time_data_list[0].time_data.shape[1]
    for label, chans in (('x_channels', x_ch or []), ('resp_channels', resp)):
        bad = [c for c in chans if not (0 <= c < n_ch)]
        if bad:
            raise ValueError(
                '{} {} out of range: the captures have {} channels'.format(
                    label, bad, n_ch))

    n_k = len(k_bins)
    # Index letters used throughout: m = realisation, e = experiment
    # within a realisation, q = excitation channel, r = response channel,
    # k = excited frequency bin.
    #
    # Xbar is [m, q, e, k] and Ybar is [m, e, r, k]: the input's (q, e)
    # plane is the SQUARE matrix to be inverted at each bin — one column
    # per experiment, one row per excitation — whereas the output has no
    # q axis at all, only however many responses were measured (n_resp is
    # independent of n_exc). Y's e axis is therefore the one that
    # contracts against X's inverse, and r rides along untouched.
    #
    # Memory: phase 1 allocates M*n_exc*(n_exc + 2*n_resp)*n_k values and
    # phase 2 below allocates a further 2*M*n_exc*n_resp*n_k while those
    # are still live, so the guard has to span BOTH — the solve is the
    # more likely place to hit a 32-bit ceiling, not the capture loop.
    try:
        Xbar = np.zeros((M, n_exc, n_exc, n_k), dtype=complex)
        Ybar = np.zeros((M, n_exc, n_resp, n_k), dtype=complex)
        varY = np.zeros((M, n_exc, n_resp, n_k))
        for m in range(M):
            for e in range(n_exc):
                td = time_data_list[m * n_exc + e]
                data = td.time_data[T_per * N:(T_per + P) * N, :]
                if data.shape[0] != P * N:
                    raise ValueError(
                        'capture too short: need {} samples in total '
                        '({} transient + {} steady-state periods of {} '
                        'samples), capture {} has {}'.format(
                            (T_per + P) * N, T_per, P, N, m * n_exc + e,
                            td.time_data.shape[0]))
                per = data.reshape(P, N, -1)
                # No window and no detrend: each slice is a whole number
                # of periods of a periodic signal, so the excited bins are
                # exact and leakage is identically zero.
                spec = np.fft.rfft(per, axis=1)[:, k_bins, :]   # (P, n_k, n_ch)
                if not commanded:
                    Xbar[m, :, e, :] = spec[:, :, x_ch].mean(axis=0).T
                Yp = spec[:, :, resp]                  # (P, n_k, n_resp)
                Ym = Yp.mean(axis=0)                   # (n_k, n_resp)
                Ybar[m, e] = Ym.T
                varY[m, e] = (np.abs(Yp - Ym) ** 2).sum(axis=0).T / (P - 1)

        if commanded:
            # Regenerate the commanded drive spectra from the seed. The
            # phase and scaling law lives in ONE place — the same helper
            # acquisition.multisine_generator builds its buffer from — so
            # generation and analysis cannot drift apart.
            from . import acquisition   # lazy: acquisition imports us
            for m in range(M):
                for e in range(n_exc):
                    Xbar[m, :, e, :] = acquisition._multisine_line_spectrum(
                        N, k_bins, amp_rms, seed, m, e, n_exc)

        G = np.zeros((M, n_resp, n_exc, n_k), dtype=complex)
        var_nG = np.zeros((M, n_resp, n_exc, n_k))
        for m in range(M):
            Xk = np.transpose(Xbar[m], (2, 0, 1))          # (n_k, q, e)
            try:
                # inv of the (q x e) matrix is indexed (e, q)
                Xinv = np.linalg.inv(Xk)                   # (n_k, e, q)
            except np.linalg.LinAlgError as err:
                raise ValueError(
                    'BLA input matrix is singular — are two excitations '
                    'identical, or an x channel silent?') from err
            Yk = np.transpose(Ybar[m], (2, 1, 0))          # (n_k, r, e)
            G[m] = np.transpose(Yk @ Xinv, (1, 2, 0))      # (r, q, n_k)
            # G_rq = sum_e Ybar_re * Xinv_eq, so the (independent) output
            # noise variances add weighted by |Xinv|^2; /P because Ybar is
            # the mean of P periods and varY is the single-period variance.
            w = np.abs(Xinv) ** 2                          # (n_k, e, q)
            vY = np.transpose(varY[m], (2, 1, 0))          # (n_k, r, e)
            var_nG[m] = np.transpose(vY @ w, (1, 2, 0)) / P
    except (ValueError, MemoryError) as err:
        # 32-bit builds (pyodide/WASM) surface an oversized allocation as
        # a ValueError saying "array is too big" rather than MemoryError.
        # Precedent: the same classify-and-rethrow guard in
        # pydvma/engine.py (calc_psd / calc_sono). Anything
        # else — our own validation errors, the singular-matrix error —
        # propagates untouched.
        msg = str(err).lower()
        if (isinstance(err, MemoryError) or 'too big' in msg
                or 'maximum possible size' in msg):
            raise ValueError(
                'BLA analysis needs too large an internal buffer for this '
                'engine ({} realisations x {} experiments x {} responses x {} '
                'excited bins). Use fewer realisations, a narrower band or a '
                'coarser frequency resolution.'.format(
                    M, n_exc, n_resp, n_k)) from err
        raise

    G_bla = G.mean(axis=0)                             # (r, q, n_k)
    var_tot = (np.abs(G - G_bla) ** 2).sum(axis=0) / (M - 1)
    var_n = var_nG.mean(axis=0)
    # Both variances estimate the same quantity when the system is
    # linear, so the difference is noisy and can go negative; floor it.
    sigma_nl = np.sqrt(np.maximum(var_tot - var_n, 0.0))
    sigma_n = np.sqrt(var_n)

    freq_axis = k_bins * fs / N
    id_link_list = [getattr(td, 'unique_id', None) for td in time_data_list]
    src = time_data_list[0]
    src_cal = np.asarray(src.channel_cal_factors, dtype=float)
    excited_bins = [int(k) for k in k_bins]

    tf_data_list = datastructure.TfDataList()
    for q in range(n_exc):
        ch_in = None if commanded else x_ch[q]
        settings = copy.copy(src.settings)
        settings.ch_in = ch_in
        settings.ch_out_set = np.array(resp)

        if commanded:
            # The commanded drive is a voltage the analysis knows
            # exactly, so it carries no calibration and no channel unit.
            tf_cal = src_cal[resp]
            tf_units = _tf_units_from_source_volts(src.units, resp)
        else:
            tf_cal = src_cal[resp] / src_cal[ch_in]
            tf_units = _tf_units_from_source(src.units, ch_in, resp)

        # Own copy per excitation, scrubbed of numpy scalars so it
        # survives the strict-JSON .dvma manifest unchanged. excited_bins
        # is copied too — sharing one list across the n_exc dicts would
        # let an edit through one TfData mutate its siblings.
        bla_meta = _json_clean(run_spec)
        bla_meta['excited_bins'] = list(excited_bins)
        bla_meta['q'] = int(q)

        # Contiguous copies, not views into the (r, q, k) stacks: each
        # TfData is an independent object that can be edited, saved or
        # dropped without touching its siblings.
        tfdata = datastructure.TfData(
            freq_axis.copy(), np.ascontiguousarray(G_bla[:, q, :].T),
            None, settings,
            channel_cal_factors=tf_cal,
            units=tf_units,
            id_link=list(id_link_list), test_name=src.test_name,
        )
        tfdata.bla_sigma_nl = np.ascontiguousarray(sigma_nl[:, q, :].T)
        tfdata.bla_sigma_n = np.ascontiguousarray(sigma_n[:, q, :].T)
        tfdata.bla = bla_meta
        tf_data_list += [tfdata]

    return tf_data_list


def _json_clean(value):
    '''Recursively convert a metadata value to plain JSON types.

    numpy scalars become Python scalars and arrays become nested lists,
    so a run spec assembled from numpy-typed values can be stored on a
    data object and written into the strict-JSON ``.dvma`` manifest (and
    read back in the browser) without type tags. Containers are rebuilt,
    so the result shares no mutable state with the input.'''
    if isinstance(value, np.ndarray):
        return _json_clean(value.tolist())
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, dict):
        return {str(k): _json_clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_clean(v) for v in value]
    return value


def _tf_units_from_source_volts(src_units, ch_out_set):
    '''Build the TF units list as "<out_unit>/V" per output channel —
    the commanded-drive case, where the input is a known voltage rather
    than a measured channel. Like `_tf_units_from_source`, returns None
    when the source units are unset or on any indexing trouble.'''
    if src_units is None:
        return None
    try:
        return ['{}/V'.format(src_units[k]) for k in ch_out_set]
    except (IndexError, TypeError):
        return None


#%% CLEAN IMPULSE
def clean_impulse(time_data, ch_impulse=0):
    '''
    Sets all data outside of impulse to zero.
    
    Pulse width is estimated by assuming half cosine impulse, using width of half peak amplitude.
    
    Data before peak is unchanged. Data after estimated end of impulse is ramped to zero using half cosine pulse of width 10x estimated pulse width.
    '''
    global MESSAGE
    if not hasattr(time_data,'impulse_cleaned'):
        time_data.impulse_cleaned = False
    
    if time_data.impulse_cleaned == False:    
        y = copy.deepcopy(time_data.time_data[:,ch_impulse])
        yi_max = np.argmax(np.abs(y))
        y_max = np.max(np.abs(y))
        yi_out = np.where(np.abs(y)<y_max/2)[0]
        yi_out1 = yi_out[yi_out < yi_max]
        yi_out2 = yi_out[yi_out > yi_max]
        y1 = yi_out1[-1]
        y2 = yi_out2[0]
        
        
        N = y2-y1
        b = int(3*N/2) #half cosine estimate
        end = int(yi_max + b/2)
        b = 10*b # less agressive roll off
        #print(time_data.settings.fs/b)
    
        ramp = np.hanning(2*b+1)    
        win = np.ones(len(y))
        win[end:end+b+1] = ramp[b:2*b+1]
        win[end+b:] = 0
        
        y2 = win * y
        
        td = copy.deepcopy(time_data)
        td.time_data[:,ch_impulse] = y2
        td.impulse_cleaned = True
        
        yd = y2-y
        if np.max(np.abs(yd)) > 0.1*np.max(np.abs(y)):
            MESSAGE = 'Cleaned impulse data contained significant signal content.\n'
            MESSAGE += 'Check for possible multiple impacts, or correct channel using ch_impulse.'
        else:
            MESSAGE = 'Impulse data cleaned.'
        print(MESSAGE)
        
        return td
    
    else:
        MESSAGE ='Impulse data already cleaned. No change made.'
        print(MESSAGE)
        return time_data


#%% RESAMPLING (band-limited, noise-reducing)
def _simplest_fraction_between(lo, hi):
    '''Smallest-denominator ``Fraction`` in the closed interval [lo, hi].

    Stern–Brocot / continued-fraction walk. Unlike
    ``Fraction.limit_denominator`` (closest fraction under a denominator
    BOUND), this finds the simplest fraction within a TOLERANCE — which
    is what rate-matching needs: ``8000/48019.2077`` is 833/5000, a
    ratio ``limit_denominator(1024)`` can only miss (it returns 1/6).

    Args:
        lo: lower interval edge (``Fraction`` or number), > 0.
        hi: upper interval edge, >= lo.

    Returns:
        The ``Fraction`` with the smallest denominator inside [lo, hi].
    '''
    from fractions import Fraction

    lo, hi = Fraction(lo), Fraction(hi)
    if lo > hi:
        lo, hi = hi, lo
    fl = lo.numerator // lo.denominator          # floor(lo)
    if lo == fl:
        return Fraction(fl)
    if fl + 1 <= hi:                             # an integer in (lo, hi]
        return Fraction(fl + 1)
    # Both edges inside (fl, fl+1): recurse on the reciprocal remainder.
    return fl + 1 / _simplest_fraction_between(1 / (hi - fl), 1 / (lo - fl))


def resample_to_fs(y, fs, fs_new, stopband_db=96.0):
    '''Band-limited rational resampling to a target sample rate.

    One principled engine for three jobs (round-9): the logger's digital
    low-pass (oversample at the device maximum, resample DOWN to the
    chosen fs), the Time view's Resample tool, and "resample to match"
    across sets. The rate change is rational — ``fs_new/fs`` is
    approximated by ``up/down`` (``Fraction.limit_denominator``, refined
    when needed by the simplest fraction within a 1e-9 relative
    tolerance), so a device-coerced capture rate still lands exactly on
    a round target: the NI 9234's 8533.33 Hz -> 2000 is up/down = 15/64,
    and the USB-6003's 80 MHz-timebase 48019.2077 Hz -> 8000 is 833/5000
    (a ratio the coarse 1024-denominator bound alone would miss). A
    ratio whose exact form would need an unreasonably large polyphase
    FIR (> 2^19 taps — this code also runs under 32-bit WASM) degrades
    gracefully to the coarse fraction, in which case ``fs_out`` may
    differ slightly from ``fs_new``. The rate change
    is applied as polyphase FIR filtering (``scipy.signal.resample_poly``)
    with a Kaiser-designed linear-phase kernel, group-delay compensated
    (effectively zero-phase; an IIR resampler would distort phase, which
    matters for transfer-function and modal work).

    Filter placement (``f_Nyq = min(fs, fs_new)/2``):

    - **Downsampling** (``fs_new < fs``): stopband at the NEW Nyquist,
      passband edge at ``fs_new/2.56`` — the standard DSA guard-band
      convention (passband to 0.78x Nyquist), the same margin a
      delta-sigma module's built-in anti-alias filter uses. Everything
      above the new Nyquist is attenuated by ``stopband_db`` (default
      96 dB) BEFORE the rate drops, so nothing aliases; rejecting the
      out-of-band noise also buys ~10*log10(fs/fs_new) dB of
      broadband-noise process gain. This is what makes it the
      noise-REDUCING method (multiplexed-SAR hardware — NI USB-6003/6212,
      sound cards — has no analogue anti-alias filter at all, so this
      chain is what stands between out-of-band content and your band).
    - **Upsampling** (``fs_new > fs``): stopband at the ORIGINAL Nyquist
      (kills the zero-stuffing images, so NO frequency content above the
      original band is invented — the failure mode of linear
      interpolation, whose triangular kernel is a sinc^2 filter that both
      droops the passband and leaks imaging residue), passband to 0.92x
      the original Nyquist so the recorded band passes essentially
      untouched.

    The first/last ~``numtaps/(2*down)`` output samples carry the usual
    FIR edge transient. Sample 0 maps to sample 0 (delay-compensated), so
    a pretrigger position at input index ``k`` lands at output index
    ``k * up/down``.

    Args:
        y: array of shape ``(N,)`` or ``(N, n_channels)`` — time series
            in columns.
        fs: current sample rate in Hz.
        fs_new: target sample rate in Hz (> 0). ``fs_new == fs`` returns
            the input unchanged.
        stopband_db: stopband attenuation for the Kaiser design in dB.

    Returns:
        Tuple ``(y_out, fs_out, (up, down))`` — the resampled array (same
        dimensionality as ``y``), the exact output rate ``fs * up/down``
        (equal to ``fs_new`` whenever the ratio is representable), and the
        rational factors used.
    '''
    from fractions import Fraction

    y = np.asarray(y, dtype=float)
    if not (fs > 0 and fs_new > 0):
        raise ValueError('fs and fs_new must be positive; got fs={}, fs_new={}'
                         .format(fs, fs_new))

    def _kernel_size(up, down):
        '''(numtaps, beta) of the Kaiser design for this up/down pair.
        Transition band around the smaller Nyquist; the filter runs at
        the upsampled internal rate fs*up.'''
        fs_out = fs * up / down
        f_nyq = min(fs, fs_out) / 2
        f_pass = f_nyq / 1.28 if fs_out < fs else 0.92 * f_nyq
        fs_up = fs * up
        numtaps, beta = signal.kaiserord(stopband_db,
                                         (f_nyq - f_pass) / (fs_up / 2))
        return numtaps | 1, beta                 # odd -> type I, integer delay

    frac = Fraction(fs_new / fs).limit_denominator(1024)
    if abs(fs * frac.numerator / frac.denominator - fs_new) > 1e-9 * fs_new:
        # The coarse rational missed the target. This happens when the
        # source rate is a device-coerced capture rate whose exact ratio
        # needs a denominator past 1024 — e.g. the USB-6003's 80 MHz
        # timebase coerces a 48 kHz digital-low-pass capture to
        # 48019.2077 Hz, and 8000/48019.2077 = 833/5000 (measured on
        # hardware, 2026-07-10; the coarse 1/6 landed the log at
        # 8003.2 Hz). It also bites rate-matching between such sets:
        # 8000/8003.2 = 2499/2500 coarsens to 1/1, a silent no-op.
        # Take the SIMPLEST fraction within tolerance instead, unless
        # its FIR would be unreasonably large (this also runs under
        # 32-bit WASM — a pathological ratio must degrade gracefully to
        # the coarse fraction, not exhaust memory).
        tol = Fraction(fs_new) * Fraction(1, 10**9)
        exact = _simplest_fraction_between((Fraction(fs_new) - tol) / Fraction(fs),
                                           (Fraction(fs_new) + tol) / Fraction(fs))
        if exact.numerator > 0 and _kernel_size(exact.numerator,
                                                exact.denominator)[0] <= (1 << 19):
            frac = exact
    up, down = frac.numerator, frac.denominator
    if up == 0:
        raise ValueError('fs_new={} is too small relative to fs={}'.format(fs_new, fs))
    fs_out = fs * up / down
    if up == down:
        return y, float(fs), (1, 1)

    f_nyq = min(fs, fs_out) / 2
    f_pass = f_nyq / 1.28 if fs_out < fs else 0.92 * f_nyq
    fs_up = fs * up
    numtaps, beta = _kernel_size(up, down)
    # Unity-gain design: resample_poly itself scales an array window by
    # `up` to compensate the power lost to zero-stuffing (verified — a
    # pre-scaled kernel comes out 20*log10(up) dB hot).
    h = signal.firwin(numtaps, (f_pass + f_nyq) / 2, fs=fs_up,
                      window=('kaiser', beta))

    one_d = y.ndim == 1
    y2 = y[:, None] if one_d else y
    y_out = signal.resample_poly(y2, up, down, axis=0, window=h)
    return (y_out[:, 0] if one_d else y_out), float(fs_out), (up, down)


#%% SONOGRAM
def _spectrogram_complex_lowmem(y, fs, nperseg, noverlap):
    '''Byte-identical, low-memory drop-in for::

        scipy.signal.spectrogram(y, fs=fs, window='hann', nperseg=nperseg,
                                 noverlap=noverlap, axis=0, mode='complex')

    for a 2-D ``y`` of shape ``(N_samples, N_channels)`` (the time axis is
    axis 0). Returns ``(freqs, time, S)`` with ``S`` of shape
    ``(N_freq, N_channels, N_seg)`` — exactly what scipy returns before the
    caller's ``swapaxes``.

    WHY THIS EXISTS (32-bit WASM / pyodide):
        ``scipy.signal.spectrogram`` segments the signal inside
        ``_fft_helper`` with ``sliding_window_view(x, nperseg, axis=-1)`` and
        then decimates it ``[..., 0::step, :]``. That first materialises
        EVERY one of the ``N_samples - nperseg + 1`` sliding windows; even
        though the intermediate is only a strided view, numpy validates its
        NOMINAL size ``N_channels * (N_samples - nperseg + 1) * nperseg``. On
        a 32-bit build (pyodide/WASM, where ``npy_intp`` is int32 and the
        nbytes ceiling is ``2**31 - 1``) numpy rejects that view with "array
        is too big" for a large ``nperseg`` on a long, high-rate record —
        e.g. a 2 s, 44.1 kHz capture at ``nperseg=4096`` gives a ~2.75 GB
        nominal view — even though the real work is tiny. This is the SAME
        limit that broke ``calculate_cross_spectrum_matrix`` (commit
        dac749c); the difference is that this instance lives in SCIPY's
        helper, so the fix must re-segment here.

        We stride DIRECTLY to the ``(N_channels, N_seg, nperseg)`` decimated
        windows with ``as_strided``. Those windows have the IDENTICAL strides
        and memory layout to scipy's ``sliding_window_view(...)[..., 0::step,
        :]`` slice, so the detrend + window + rfft that follow are
        byte-identical (numpy's pairwise-summation block order, which the DC
        bin is sensitive to, depends on memory layout) — but the nominal size
        is only ``N_channels * N_seg * nperseg``. Everything else (Hann
        window, constant detrend, density scaling with the ``sqrt`` for the
        ``'stft'`` mode, one-sided rfft with NO ``psd`` doubling,
        ``boundary=None``/``padded=False`` defaults, and the time/frequency
        axes) matches scipy exactly. Pinned byte-for-byte against
        ``scipy.signal.spectrogram`` in ``tests/test_analysis.py``.

    ``as_strided`` performs no bounds checking, so this replicates scipy's
    own validation: ``nperseg`` is clamped to the record length (scipy warns
    and clamps rather than erroring), and ``noverlap`` must be < ``nperseg``.
    '''
    from scipy import fft as sp_fft     # the SAME FFT backend scipy.spectrogram uses

    y = np.asarray(y)
    N_samples = y.shape[0]
    nperseg = int(nperseg)
    if nperseg < 1:
        raise ValueError('nperseg must be a positive integer')
    if nperseg > N_samples:
        # scipy._triage_segments clamps (with a warning) rather than erroring.
        import warnings
        warnings.warn('nperseg = {:d} is greater than input length = {:d}, '
                      'using nperseg = {:d}'.format(nperseg, N_samples, N_samples),
                      stacklevel=2)
        nperseg = N_samples
    noverlap = nperseg // 2 if noverlap is None else int(noverlap)
    if noverlap >= nperseg:
        raise ValueError('noverlap must be less than nperseg.')

    nfft = nperseg
    step = nperseg - noverlap
    # scipy's _fft_helper takes sliding_window_view(len N_samples-nperseg+1)
    # then [..., 0::step, :]; that leaves (N_samples - nperseg)//step + 1 segs.
    N_seg = (N_samples - nperseg) // step + 1

    win = signal.windows.get_window('hann', nperseg)      # float64, as scipy

    # scipy does x = moveaxis(y, axis=0, -1) -> (N_channels, N_samples), a
    # NON-contiguous view. Keep that exact layout so the strided windows below
    # match scipy's memory order byte-for-byte.
    xT = np.moveaxis(y, 0, -1)
    N_channels = xT.shape[0]
    row_stride, col_stride = xT.strides
    sv = np.lib.stride_tricks.as_strided(
        xT,
        shape=(N_channels, N_seg, nperseg),
        strides=(row_stride, step * col_stride, col_stride),
        writeable=False,
    )
    # detrend (constant) -> window -> rfft, in scipy's order.
    result = signal.detrend(sv, axis=-1, type='constant')
    result = win * result
    result = sp_fft.rfft(result.real, n=nfft)             # (N_channels, N_seg, N_freq)

    # Density scaling with the stft-mode sqrt (mode='stft'); NO one-sided
    # doubling (that is applied only in mode='psd').
    scale = 1.0 / (fs * (win * win).sum())
    scale = np.sqrt(scale)
    result = result * scale
    result = result.astype(np.result_type(y, np.complex64))   # complex128

    freqs = sp_fft.rfftfreq(nfft, 1.0 / fs)
    time = np.arange(nperseg / 2, N_samples - nperseg / 2 + 1, step) / float(fs)

    # scipy rolls the freq axis (last) back to the original data axis (0):
    # (N_channels, N_seg, N_freq) -> (N_freq, N_channels, N_seg).
    S = np.moveaxis(result, -1, 0)
    return freqs, time, S


def calculate_sonogram(time_data, nperseg=None, noverlap=None):
    '''
    Calculates a complex STFT spectrogram (sonogram) for every channel of
    a <TimeData> object using a Hann window, and returns a <SonoData>.

    Channel calibration factors and units are copied from the source, and
    `id_link` is set to the source's `unique_id` (same provenance
    convention as the other `calculate_*` functions).

    The segmentation is done by `_spectrogram_complex_lowmem` rather than
    `scipy.signal.spectrogram` directly: scipy's internal
    `sliding_window_view` builds a huge NOMINAL intermediate that the 32-bit
    WASM/pyodide engine rejects with "array is too big" for a large `nperseg`
    on a long, high-rate record. The low-memory helper strides directly to
    the decimated windows and is byte-identical to scipy (pinned in the test
    suite). See that helper's docstring for the full rationale.

    Args:
        time_data (<TimeData> object): time series data
        nperseg (int, optional): STFT segment length; defaults to ~1/50th
            of the time series so roughly 50 segments span the data
        noverlap (int, optional): overlap between segments, default
            ``nperseg // 2``
    '''
    y = np.copy(time_data.time_data) # handles all channels simultaneously
    if nperseg is None:
        nperseg = int(len(time_data.time_axis)/50) #roughly 50 fft's per time-series not counting overlap
    if noverlap is None:
        noverlap = nperseg//2

    f, t, S = _spectrogram_complex_lowmem(y, time_data.settings.fs, nperseg, noverlap)

    # put channel axis at end
    S_all_chans = np.swapaxes(S,1,2)

    sono_data = datastructure.SonoData(
        t, f, S_all_chans, time_data.settings,
        channel_cal_factors=np.asarray(time_data.channel_cal_factors, dtype=float).copy(),
        units=time_data.units,
        id_link=time_data.unique_id, test_name=time_data.test_name,
    )

    return sono_data

#%% CWT (continuous wavelet transform)

def _morlet_daughter_fourier(omega, scale, w0):
    '''Amplitude-normalised complex Morlet daughter wavelet in Fourier space.

    Returns ``Psi_hat(scale * omega)`` for the analytic (one-sided) complex
    Morlet mother ``psi(t) = exp(i*w0*t) * exp(-t**2/2)``, evaluated on the
    angular-frequency grid ``omega`` (rad/s) at dilation ``scale`` (seconds):

        Psi_hat(s*w) = 2 * exp(-0.5 * (s*w - w0)**2) * H(w)

    where ``H`` is the Heaviside step (only positive frequencies contribute —
    this makes the transform analytic, so the coefficient's phase advances at
    the SIGNAL's instantaneous frequency).

    NORMALISATION (pinned by ``tests/test_analysis.py``): the leading factor
    ``2`` is an L-infinity / amplitude normalisation. The daughter peaks at
    ``1`` in the frequency domain (at ``s*w == w0``); the factor ``2``
    compensates the one-sided (analytic) halving of a REAL signal's energy so
    that a unit-amplitude real cosine at the wavelet's centre frequency yields
    a coefficient of peak magnitude ``|W| ~= 1``, independent of frequency.
    ``|W|`` is therefore directly an amplitude estimate and is comparable
    across the band and against the STFT magnitude sonogram (unlike the
    Torrence & Compo L2/energy normalisation, whose peak magnitude scales as
    ``1/sqrt(f)``). Only the per-scale CONSTANT differs between conventions, so
    the damping fit (which reads the time-SLOPE of ``log|W|`` at a fixed scale)
    is unaffected by the choice.
    '''
    psi = np.zeros_like(omega)
    pos = omega > 0.0
    psi[pos] = 2.0 * np.exp(-0.5 * (scale * omega[pos] - w0) ** 2)
    return psi


def _cwt_default_frequencies(fs, N, f_range, voices_per_octave, w0=6.0):
    '''Log-spaced (constant-Q) analysis frequencies for the Morlet CWT.

    With ``f_range=None`` the band spans ``4*max(1, w0/6)/T`` up to ``0.4*fs``
    where ``T = N/fs`` is the record length:

    - LOW end ``4*max(1, w0/6)/T``: the binding constraint is the lowest
      wavelet's e-folding time ``sqrt(2)*s = sqrt(2)*w0/(2*pi*f)``, which must
      stay below ``T/2`` or the row is dominated by edge (cone-of-influence)
      effects and by the FFT convolution's circular wrap. That time grows
      LINEARLY with the wavelet Q, so the low end must track ``w0``: the plain
      ``4/T`` of the ``w0=6`` default (also "at least four oscillations of the
      lowest wavelet fit in the record") leaves the e-folding time at
      ``0.34*T`` — but at ``w0=64`` the same bound would put it at ``3.6*T``.
      Scaling by ``w0/6`` pins the ratio at ``0.34*T`` for every ``w0 >= 6``
      and leaves the ``w0=6`` band bit-for-bit unchanged.
    - HIGH end ``0.4*fs`` (= ``0.8 * Nyquist``): a safe margin below Nyquist so
      the highest wavelet is adequately sampled.

    Frequencies are geometrically spaced at ``voices_per_octave`` samples per
    octave (default 16), the natural constant-Q ladder of a wavelet transform.

    An explicit ``f_range=(f_min, f_max)`` in Hz overrides the default band
    (clamped to ``(0, ~Nyquist)``). EITHER side may be ``None`` to keep that
    side's automatic value, so a lone lower bound is meaningful. A reversed,
    zero-width, non-positive or entirely super-Nyquist band raises
    ``ValueError`` rather than being silently substituted — the old
    ``f_max = 2*f_min`` fallback turned a typo into a plausible-looking
    analysis over a band nobody asked for. (The AUTOMATIC band keeps that
    fallback: it can only collapse on a pathologically short record.)
    '''
    T = N / float(fs)
    auto_min = 4.0 * max(1.0, float(w0) / 6.0) / T
    auto_max = 0.4 * fs
    if f_range is None:
        f_min, f_max = auto_min, auto_max
    else:
        lo, hi = f_range[0], f_range[1]
        f_min = auto_min if lo is None else float(lo)
        f_max = auto_max if hi is None else float(hi)
        if not (f_max > f_min > 0.0):
            raise ValueError(
                'f_range must be an increasing, positive (f_min, f_max) band '
                'in Hz — got ({:g}, {:g}). Pass None for either side to keep '
                'its automatic bound.'.format(f_min, f_max))
    f_min = max(f_min, 1e-9)
    f_max = min(f_max, 0.5 * fs * 0.999)
    if f_max <= f_min:
        if f_range is not None:
            raise ValueError(
                'f_range leaves no analysable band below Nyquist: f_min '
                '{:g} Hz is at or above the {:g} Hz Nyquist limit of a {:g} Hz '
                'capture.'.format(f_min, 0.5 * fs, fs))
        f_max = f_min * 2.0
    n_octaves = np.log2(f_max / f_min)
    n_freqs = int(np.ceil(voices_per_octave * n_octaves)) + 1
    return np.geomspace(f_min, f_max, max(2, n_freqs))


# Largest complex time-frequency image ONE `_morlet_cwt_1d` call may allocate,
# in bytes (768 MiB). The hard wall is numpy's 32-bit ``2**31-1`` (~2.15 GB) on
# the WASM/pyodide engine, where an over-size allocation raises a bare "array is
# too big" the user cannot act on; this ceiling sits well below it so the
# single-scale FFT temporaries and the caller's own arrays still fit, and above
# the largest image the shipped defaults produce (~0.30 GB for the 2 s, 44.1 kHz
# worst case documented in `_morlet_cwt_1d`). Module-level so a desktop user
# with plenty of RAM can raise it deliberately.
CWT_MAX_IMAGE_BYTES = 768 * 1024 ** 2


def _morlet_cwt_1d(y, fs, freqs, w0=6.0, time_step=1, progress_callback=None):
    '''FFT-based complex Morlet CWT of a single 1-D real signal.

    Computes the continuous wavelet transform by per-scale convolution in the
    frequency domain (one forward FFT of the whole signal, then one inverse
    FFT per scale) — the standard Torrence & Compo (1998) construction. No
    dependency on the removed ``scipy.signal.cwt`` (gone in scipy >= 1.15);
    uses only ``numpy`` and ``scipy.fft`` so it behaves identically on the
    desktop and on the 32-bit WASM/pyodide engine.

    Args:
        y (np.ndarray): 1-D real signal, length ``N``.
        fs (float): sample rate (Hz).
        freqs (np.ndarray): analysis centre frequencies (Hz); the scale for
            each is ``s = w0 / (2*pi*f)``.
        w0 (float): non-dimensional Morlet frequency (default 6.0; the usual
            admissibility-safe value giving ~``w0`` oscillations under the
            envelope). Acts as the wavelet Q: HIGHER ``w0`` means more cycles
            under the Gaussian envelope, i.e. FINER frequency resolution at
            the cost of COARSER time resolution (and vice versa).
        time_step (int): decimation of the output time axis. ``1`` keeps every
            sample (full time resolution). ``>1`` subsamples the columns to
            bound the returned image size. A damping fit reads the coefficient's
            unwrapped PHASE, which aliases once the column rate falls below
            ``2*f`` for the highest analysed frequency, so a fitting caller must
            keep ``time_step <= fs/(2*f_max)`` — see
            `_cwt_damping_time_step`, which applies that bound with margin.
        progress_callback (callable or None): optional ``f(done, total)``
            invoked after EVERY scale, with ``total = len(freqs)`` and ``done``
            counting from 1 — the transform's only natural progress unit (one
            inverse FFT per scale, all the same cost). ``None`` (default) is a
            true no-op: nothing is called and the numerical result is
            bit-identical either way. Intended for a long-running UI (the web
            engine's worker posts a frame from it, so a lab-length CWT shows a
            determinate bar); it is called on the hot loop, so it must be cheap
            and must not raise — an exception propagates out of the transform.

    Returns:
        (W, t_idx): ``W`` of shape ``(len(freqs), ceil(N/time_step))`` complex,
        and ``t_idx`` the sample indices of the kept time columns.

    MEMORY (32-bit WASM): the transform is done ONE SCALE AT A TIME — the only
    full-length temporaries are the signal's FFT and a single inverse-FFT row
    (each ``N`` complex). The returned ``W`` is ``len(freqs) x N_out`` complex;
    at full time resolution (``time_step=1``) a 2 s, 44.1 kHz record over the
    default ~211-frequency band costs ``211 * 88200 * 16 B ~= 0.30 GB``, but a
    LAB-length record blows straight past the 32-bit ``2**31-1`` byte ceiling
    (30 s at 48 kHz over the default band is ~16 GB). The image size is
    therefore CHECKED against `CWT_MAX_IMAGE_BYTES` before allocating and an
    over-size request raises a ``ValueError`` naming the record, the grid and
    the remedies — numpy's own bare "array is too big" must never reach the
    user.
    '''
    from scipy import fft as sp_fft

    y = np.asarray(y, dtype=float)
    N = y.shape[0]
    dt = 1.0 / fs
    freqs = np.asarray(freqs, dtype=float)
    scales = w0 / (2.0 * np.pi * freqs)
    t_idx = np.arange(0, N, int(time_step))

    # Pre-flight the image allocation (before the FFT, so an over-size request
    # costs nothing) and refuse with an actionable message.
    n_bytes = int(freqs.shape[0]) * int(t_idx.shape[0]) * 16
    if n_bytes > CWT_MAX_IMAGE_BYTES:
        raise ValueError(
            'CWT image too large for the analysis engine: {} frequencies x {} '
            'time columns x 16 B = {:.2f} GB, over the {:.2f} GB limit. The '
            'record is {} samples ({:.3g} s at {:g} Hz) and the wavelet Q is '
            'w0={:g}. Remedies: analyse a SHORTER record, NARROW the frequency '
            'range (its top also sets how far the time axis can be decimated), '
            'use FEWER voices/octave, or pass a larger time_step.'.format(
                freqs.shape[0], t_idx.shape[0], n_bytes / 1024 ** 3,
                CWT_MAX_IMAGE_BYTES / 1024 ** 3, N, N / float(fs), fs, w0))

    # Angular-frequency grid (rad/s), negative for the upper half (Torrence &
    # Compo eq. 5). The Morlet daughter is one-sided, so only the positive
    # half contributes.
    k = np.arange(N)
    omega = 2.0 * np.pi * k / (N * dt)
    omega[k > N // 2] -= 2.0 * np.pi / dt

    yhat = sp_fft.fft(y)
    W = np.empty((freqs.shape[0], t_idx.shape[0]), dtype=complex)
    n_scales = freqs.shape[0]
    for i, s in enumerate(scales):
        psi_hat = _morlet_daughter_fourier(omega, s, w0)
        row = sp_fft.ifft(yhat * psi_hat)
        W[i] = row[t_idx]
        if progress_callback is not None:
            progress_callback(i + 1, n_scales)
    return W, t_idx


def _resample_freq_axis(freqs, W, f_out):
    '''Linearly resample a complex time-frequency image onto a new freq axis.

    ``W`` is ``(len(freqs), Nt)`` complex on the (increasing) ``freqs`` grid;
    returns ``(len(f_out), Nt)`` interpolated column-wise along frequency onto
    ``f_out``. Vectorised (no per-column Python loop). Used to put the CWT's
    natural LOG-spaced image onto a UNIFORM display grid — see
    ``calculate_cwt``'s ``uniform_freq`` argument for the rationale.
    '''
    freqs = np.asarray(freqs, dtype=float)
    f_out = np.asarray(f_out, dtype=float)
    idx = np.clip(np.searchsorted(freqs, f_out), 1, len(freqs) - 1)
    lo = idx - 1
    hi = idx
    denom = freqs[hi] - freqs[lo]
    frac = np.where(denom > 0, (f_out - freqs[lo]) / denom, 0.0)[:, None]
    return (1.0 - frac) * W[lo] + frac * W[hi]


def calculate_cwt(time_data, f_range=None, voices_per_octave=16, w0=6.0,
                  max_time_columns=2000, uniform_freq=True,
                  progress_callback=None):
    '''Continuous wavelet transform (complex Morlet) as a `SonoData`.

    A drop-in ALTERNATIVE to `calculate_sonogram`: produces the SAME
    `SonoData` shape (``sono_data`` of shape ``(n_freq, n_frames, n_channels)``,
    complex, with ``time_axis`` and ``freq_axis``) so the whole downstream
    pipeline — the ``.dvma`` container, the web-UI heat map, and the damping
    fit — reuses unchanged. Where the STFT sonogram has a FIXED time-frequency
    resolution, the wavelet transform is constant-Q: long (narrow-band)
    wavelets at low frequency and short (wide-band) wavelets at high frequency,
    which is why it separates closely-spaced low-frequency modes that a
    single-window STFT smears together (demonstrated in the damping tests).

    The transform is computed on LOG-spaced frequencies (``voices_per_octave``
    per octave; see `_cwt_default_frequencies` for the default band and
    `_morlet_cwt_1d` for the FFT construction and amplitude normalisation).

    FREQUENCY AXIS (``uniform_freq``): the CWT is naturally sampled on a
    log-frequency grid, but the web-UI heat renderer maps each frequency
    ROW-INDEX linearly to a canvas pixel row and labels a LINEAR frequency
    axis, i.e. it assumes UNIFORM bin spacing. With ``uniform_freq=True``
    (default, the display path) the complex image is therefore resampled onto a
    uniform grid spanning the same band (via `_resample_freq_axis`) so the
    existing renderer places and labels it correctly with no renderer change.
    TRADE-OFF: a uniform linear axis compresses low frequencies (exactly as the
    STFT sonogram already does), so the wavelet's finer low-frequency detail is
    not fully resolved in the heat MAP; it IS retained in the analysis and in
    the damping fit, which uses ``uniform_freq=False`` to keep the native
    log grid. (A log-y heat renderer — owned by the plot layer — would let the
    native log axis display with full low-frequency detail.)

    TIME AXIS / MEMORY: the output time axis is decimated so it has at most
    ``max_time_columns`` frames (``None`` keeps every sample). This bounds the
    returned image — it is a display/analysis picture, not raw data — and,
    together with the per-channel loop, keeps peak memory low on the 32-bit
    WASM engine. Worst case is ``n_freq x max_time_columns`` complex per
    returned image (~7 MB at the defaults), with only single-channel,
    single-scale full-length FFT temporaries alive during the compute. The
    default cap keeps the image far below `CWT_MAX_IMAGE_BYTES`;
    ``max_time_columns=None`` on a long record can exceed it, and then
    `_morlet_cwt_1d` refuses with a sizing error rather than allocating.

    Args:
        time_data (<TimeData> object): time series data (all channels).
        f_range (tuple or None): ``(f_min, f_max)`` in Hz; ``None`` uses the
            default band (see `_cwt_default_frequencies`). Either side may be
            ``None`` to keep that side automatic; a reversed band raises.
        voices_per_octave (int): log-frequency density (default 16).
        w0 (float): non-dimensional Morlet frequency (default 6.0) — the
            wavelet Q. Higher = more cycles under the envelope = finer
            frequency resolution but coarser time resolution; lower sharpens
            time localisation at the cost of frequency smearing.
        max_time_columns (int or None): cap on output time frames (default
            2000); ``None`` disables time decimation.
        uniform_freq (bool): resample onto a uniform frequency grid for display
            (default True); ``False`` returns the native log grid (used by the
            damping fit).
        progress_callback (callable or None): optional ``f(done, total)`` for a
            long-running caller. It covers the WHOLE call — ``total =
            n_channels * n_freqs`` and ``done`` counts scales across every
            channel, so a 2-channel transform reads 50 % when the first
            channel finishes. ``None`` (default) is a no-op and the result is
            bit-identical either way; see `_morlet_cwt_1d` for the per-scale
            contract and the cheap-and-never-raises requirement.
    '''
    y = np.asarray(time_data.time_data)
    if y.ndim == 1:
        y = y[:, None]
    N, n_chans = y.shape
    fs = time_data.settings.fs

    freqs = _cwt_default_frequencies(fs, N, f_range, voices_per_octave, w0=w0)
    n_freq = len(freqs)

    if max_time_columns is None:
        time_step = 1
    else:
        time_step = max(1, int(np.ceil(N / float(max_time_columns))))
    t_idx = np.arange(0, N, time_step)
    t = np.asarray(time_data.time_axis)[t_idx]
    n_frames = len(t_idx)

    # Uniform display grid (same count as the log grid) or the native log grid.
    f_out = np.linspace(freqs[0], freqs[-1], n_freq) if uniform_freq else freqs

    # Per-channel to bound peak memory (never hold all channels' full transform
    # at once on WASM).
    S = np.empty((len(f_out), n_frames, n_chans), dtype=complex)
    # Progress spans the whole call: `_morlet_cwt_1d` counts scales within ONE
    # channel, so each channel's frames are re-based onto the channels x scales
    # total. `cb` stays None when the caller passed none — no per-scale call.
    total = n_chans * n_freq
    for c in range(n_chans):
        if progress_callback is None:
            cb = None
        else:
            base = c * n_freq
            def cb(done, _total, base=base, total=total):
                progress_callback(base + done, total)
        Wc, _ = _morlet_cwt_1d(y[:, c], fs, freqs, w0=w0, time_step=time_step,
                               progress_callback=cb)
        S[:, :, c] = _resample_freq_axis(freqs, Wc, f_out) if uniform_freq else Wc

    sono_data = datastructure.SonoData(
        t, f_out, S, time_data.settings,
        channel_cal_factors=np.asarray(time_data.channel_cal_factors, dtype=float).copy(),
        units=time_data.units,
        id_link=time_data.unique_id, test_name=time_data.test_name,
    )

    return sono_data


#%% Damping from sonogram

# define a custom functions for fitting
def func_real(t, A,B,N):
    #ensure exp(A) and exp(N) are positive
    f = np.log(np.exp(A)*np.exp(-B*t) + 1j*np.exp(N))
    f = np.real(f)
    return f

def func_imag(t, W, C):
    f = W*t + C
    return f

def _resolve_damping_start_slice(t, start_time, settings, default_start_frac=None):
    '''Pick the free-decay start frame index for a damping fit.

    An explicit ``start_time`` (seconds) snaps to the nearest time frame.
    Otherwise the start is inferred from the pretrigger: ``2 *
    pretrig_samples / fs`` places it just after the impact. ``pretrig_samples``
    is ``None`` on captures without a trigger (and absent on older settings
    structs), so that path falls back:

    - ``default_start_frac=None`` (STFT default) uses ``t[-1] // 20`` — the
      exact convention the original `calculate_damping_from_sono` used. Note
      that floors to frame 0 for any sub-20-second record; that is harmless for
      the STFT, whose first frame is already centred ``nperseg/2`` samples in.
    - ``default_start_frac=frac`` (the CWT path passes ``0.05``) starts
      ``frac`` of the way into the record BY INDEX. The full-resolution CWT's
      frame 0 IS the raw ``t=0`` edge — inside the cone of influence and
      corrupted by the FFT's circular wrap — so it must skip a little in.
    '''
    if start_time is not None:
        return int(np.argmin(np.abs(t - start_time)))
    try:
        # pretrig_samples is None on captures without a trigger; also guards
        # against settings being an older struct that predates that attribute.
        t0 = 2 * settings.pretrig_samples / settings.fs
        return int(np.argmin(np.abs(t - t0)))
    except (AttributeError, TypeError):
        if default_start_frac is not None:
            return int(min(len(t) - 1, max(0, round(default_start_frac * len(t)))))
        t0 = t[-1] // 20
        return int(np.argmin(np.abs(t - t0)))


def _fit_modes_from_image(t, f, Sc, time_slice, phase_has_carrier,
                          peak_threshold=None):
    '''Shared modal-damping fit core over a complex time-frequency image.

    Works on ANY complex single-channel image ``Sc`` of shape
    ``(n_freq, n_frames)`` — a Hann STFT sonogram (`calculate_sonogram`) or a
    complex Morlet CWT (`calculate_cwt`). Peaks in the magnitude at
    ``time_slice`` mark candidate modes; for each, the log-magnitude decay of
    ``Sc`` over time gives the damping and the unwrapped phase slope gives the
    (damped) frequency, from which ``fn`` and ``Qn = 1/(2*zeta)`` follow.

    ``phase_has_carrier`` selects how the phase slope maps to frequency:

    - ``False`` (STFT): scipy's spectrogram references each bin's phase to the
      bin centre, so the fitted phase slope ``W`` is the beat frequency and the
      true angular frequency is ``2*pi*f[peak] + W``.
    - ``True`` (CWT): the analytic Morlet coefficient's phase advances at the
      signal's OWN instantaneous frequency, so the fitted slope IS the angular
      frequency directly (``W0 = W``). (Verified against synthetic tones — see
      the CWT damping tests.)

    ``peak_threshold`` is the NORMALISED peak-picking threshold handed to
    ``peakutils.indexes`` (a fraction of the start-slice magnitude's min→max
    range, clipped to 0..1): only bins whose magnitude at ``time_slice``
    rises above it become candidate modes. ``None`` keeps the historic
    automatic choice ``10 * median / max`` of the slice magnitude (which can
    exceed 1 on a flat spectrum, deliberately yielding no peaks).

    Returns ``(fn, Qn, fit_data)`` exactly as `calculate_damping_from_sono`
    documents.
    '''
    time_slice_data = np.abs(Sc[:, time_slice])
    if peak_threshold is None:
        threshold = 10 * np.median(time_slice_data) / np.max(time_slice_data)
    else:
        threshold = float(np.clip(peak_threshold, 0.0, 1.0))
    peaks = pu.indexes(time_slice_data, thres=threshold, min_dist=1)

    # Collect results locally
    zeta_n = []
    wn_n = []
    fits = []

    for peak in peaks:

        # Extract the real and imaginary parts of Sc at the peak frequency
        real_part = np.real(np.log(Sc[peak, :]))
        imag_part = np.unwrap(np.imag(np.log(Sc[peak, :])))

        # Fit the real part to a custom function
        try:
            popt_real, _ = curve_fit(func_real, t[time_slice:], real_part[time_slice:])
        except Exception:
            # Skip this peak if the fit fails
            continue
        real_fit = func_real(t, *popt_real)
        A = popt_real[0]
        B = popt_real[1]
        N = popt_real[2]

        # Identify crossover time when noise starts to dominate
        t_cross = (A - N)/B if B != 0 else t[-1]
        # nearest time index
        time_cross = np.argmin(np.abs(t - t_cross))

        # Fit the imaginary part to a linear function for clean part of the signal
        t0_idx = time_slice
        dt = int(np.ceil(0.9*(time_cross - time_slice)))
        dt = np.max([2,dt])
        t1_idx = t0_idx + dt

        # Only continue if there are enough datapoints for imaginary part fitting
        if dt <= 4:
            continue

        # Fit the imaginary part to a linear function for clean part of the signal
        try:
            popt_imag,_ = curve_fit(func_imag, t[t0_idx:t1_idx], imag_part[t0_idx:t1_idx])
        except Exception:
            # Skip this peak if the fit fails
            continue
        W = popt_imag[0]
        # Map the fitted phase slope to the angular frequency. For the STFT the
        # phase is referenced to the bin, so add the bin carrier; for the
        # analytic CWT the slope is already the angular frequency.
        W0 = W if phase_has_carrier else (2*np.pi*f[peak] + W)

        # Calculate the damping factor and frequency from the fit coefficients
        zeta = B / np.sqrt(W0**2 + B**2)
        # Guard against numerical issues if zeta >= 1
        zeta = np.clip(zeta, 0.0, 0.999999)
        w = W0 / np.sqrt(1 - zeta**2)
        Qn = 1/(2*zeta)

        # Store fit data for plotting
        fits.append({
            't_fit': t[t0_idx:t1_idx],
            'real_fit': real_fit[t0_idx:t1_idx],
            'real_data': real_part[t0_idx:t1_idx],
            'f_peak': f[peak],
            'Qn': Qn
        })

        # Store the results
        zeta_n.append(zeta)
        wn_n.append(w)

    zn = np.array(zeta_n)
    Qn = 1/(2*zn) if len(zn) > 0 else np.array([])
    wn = np.array(wn_n)
    fn = wn / (2*np.pi) if len(wn) > 0 else np.array([])

    fit_data = {
        't': t,
        'fits': fits,
        # Peak-picking context (round-7 interactive damping UI): the exact
        # inputs the picker saw, so a front-end can draw the start-time line,
        # the start-slice spectrum with its threshold line and candidate
        # peaks, and re-fit with edited values. `threshold` echoes the value
        # actually used (the automatic choice when `peak_threshold` was
        # None), normalised to the slice magnitude's min->max range exactly
        # as `peakutils.indexes` interprets it.
        'time_slice': int(time_slice),
        'start_time': float(t[time_slice]),
        'threshold': float(threshold),
        'slice_freq': np.asarray(f),
        'slice_mag': time_slice_data,
        'peaks_freq': np.asarray(f)[peaks] if len(peaks) else np.array([]),
        'peaks_mag': time_slice_data[peaks] if len(peaks) else np.array([]),
    }

    return fn, Qn, fit_data


def calculate_damping_from_sono(time_data,n_chan=1,nperseg=None,start_time=None,
                                peak_threshold=None):
    '''
    Calculate damping from an STFT sonogram.

    Computes a Hann-window sonogram (``noverlap=0``) and fits the free-decay of
    each detected band. See `_fit_modes_from_image` for the fit core (this is
    the ``phase_has_carrier=False`` / STFT case) and `calculate_damping_from_cwt`
    for the wavelet alternative.

    Args:
        time_data (<TimeData> object): time series data
        n_chan (int, optional): channel index to analyze, default is 1
        nperseg (int, optional): number of samples per segment for spectrogram
        start_time (float, optional): start time (seconds) for analysis; None
            infers it from the pretrigger (see `_resolve_damping_start_slice`)
        peak_threshold (float, optional): normalised peak-picking threshold in
            0..1 (fraction of the start-slice magnitude's min→max range, as
            ``peakutils.indexes`` interprets it); None keeps the automatic
            ``10 * median / max`` choice (see `_fit_modes_from_image`)

    Returns:
        fn (np.ndarray): array of natural frequencies (Hz)
        Qn (np.ndarray): array of Q factors (1/(2*zeta))
        fit_data (dict): dict containing data needed for plotting the fits:
            - 't': time axis
            - 'fits': list of dicts, each with keys:
                - 't_fit': time values for the fit region
                - 'real_fit': fitted real part values
                - 'real_data': actual real part data values
                - 'f_peak': peak frequency (Hz)
                - 'Qn': Q factor for this mode
            - 'time_slice' / 'start_time': the fit-start frame index and its
              time (s) — the resolved free-decay start
            - 'threshold': the normalised peak threshold actually used
            - 'slice_freq' / 'slice_mag': the start-slice magnitude spectrum
              the peak picker scanned
            - 'peaks_freq' / 'peaks_mag': the candidate peaks it detected
              (before any per-peak fit failures are dropped)
    '''
    sono_data = calculate_sonogram(time_data, nperseg=nperseg,noverlap=0)

    t = sono_data.time_axis
    f = sono_data.freq_axis
    S = sono_data.sono_data

    time_slice = _resolve_damping_start_slice(t, start_time, sono_data.settings)
    return _fit_modes_from_image(t, f, S[:, :, n_chan], time_slice,
                                 phase_has_carrier=False,
                                 peak_threshold=peak_threshold)


# Columns per cycle of the highest analysed frequency kept by the CWT damping
# fit. The hard bound is 2 (Nyquist for the phase unwrap); 4x that leaves the
# envelope and the phase slope generously sampled while still shrinking a
# narrow-band fit's image by the same factor.
_CWT_DAMPING_OVERSAMPLE = 4


def _cwt_damping_time_step(fs, f_max, oversample=_CWT_DAMPING_OVERSAMPLE):
    '''Time decimation for a CWT damping fit over a band topping out at ``f_max``.

    The fit reads the log-magnitude decay and the UNWRAPPED phase of one CWT
    row over time. The unwrap aliases once the phase advances by more than
    ``pi`` between kept columns, i.e. once the column rate drops below
    ``2*f_max``; sampling ``oversample`` times faster than that leaves the
    phase step at ``pi/oversample`` and the decay envelope well resolved.
    Returns ``max(1, floor(fs / (2*f_max) / oversample))``, so a full-band fit
    (``f_max = 0.4*fs``) is undecimated exactly as before and a narrow low-
    frequency band — the case that used to blow the engine's memory ceiling —
    shrinks by the full factor.
    '''
    f_max = float(f_max)
    if not (f_max > 0.0):
        return 1
    return max(1, int(np.floor(float(fs) / (2.0 * f_max) / float(oversample))))


def calculate_damping_from_cwt(time_data, n_chan=1, start_time=None,
                               f_range=None, voices_per_octave=16, w0=6.0,
                               peak_threshold=None, progress_callback=None):
    '''
    Calculate damping from a continuous wavelet transform (complex Morlet).

    The wavelet alternative to `calculate_damping_from_sono`: it fits the same
    per-mode free-decay, but on the CWT image, whose constant-Q resolution
    separates closely-spaced low-frequency modes that a fixed-window STFT
    smears into one band. Only channel ``n_chan`` is transformed, on the NATIVE
    log-frequency grid (`_cwt_default_frequencies`).

    The phase-to-frequency mapping differs from the STFT: the analytic Morlet
    coefficient's phase advances at the signal's own frequency, so the fit core
    is called with ``phase_has_carrier=True`` (see `_fit_modes_from_image`).

    SIZE / MEMORY. The fit image is ``n_freqs x n_columns`` complex, and at full
    rate that is ruinous on a lab-length record: 30 s at 48 kHz over the default
    band is ~16 GB, which on the 32-bit WASM engine surfaced as numpy's bare
    "array is too big". Two bounds now apply. (1) The time axis is decimated to
    `_cwt_damping_time_step` — the coarsest step the phase unwrap tolerates for
    the band's top frequency, with margin. A DEFAULT-band fit tops out at
    ``0.4*fs`` so its step stays 1 and its numbers are unchanged; ``f_range``
    is what buys the decimation, and it shrinks ``n_freqs`` at the same time.
    (2) Whatever remains is checked against `CWT_MAX_IMAGE_BYTES` before
    allocation, so an impossible request raises a ``ValueError`` that names the
    record, the grid and the remedies instead of failing opaquely. A long
    record therefore needs an explicit ``f_range`` — which is also the honest
    analysis, since a 30 s record has nothing to say about a 19 kHz mode's
    decay.

    Args:
        time_data (<TimeData> object): time series data
        n_chan (int, optional): channel index to analyze, default is 1
        start_time (float, optional): start time (seconds); None infers it from
            the pretrigger (see `_resolve_damping_start_slice`)
        f_range (tuple or None): ``(f_min, f_max)`` Hz restricting the fitted
            band; None uses the default band (see `_cwt_default_frequencies`).
            Either side may be None to keep that side automatic; a reversed
            band raises ``ValueError``
        voices_per_octave (int, optional): log-frequency density, default 16
        w0 (float, optional): non-dimensional Morlet frequency, default 6.0
        peak_threshold (float, optional): normalised peak-picking threshold in
            0..1; None keeps the automatic choice (see
            `calculate_damping_from_sono`)
        progress_callback (callable or None): optional ``f(done, total)``
            reporting the TRANSFORM only — ``total`` is the number of analysis
            frequencies and ``done`` counts scales (see `_morlet_cwt_1d`). The
            per-mode curve fits that follow are deliberately NOT counted: the
            mode count is unknown until the transform has finished and the
            peaks have been picked, so including them would grow ``total``
            mid-call and make a progress bar jump backwards. They are also the
            cheap half — a handful of `scipy.optimize.curve_fit` calls against
            one inverse FFT per scale. None (default) is a no-op.

    Returns:
        Same ``(fn, Qn, fit_data)`` triple as `calculate_damping_from_sono`.
    '''
    fs = time_data.settings.fs
    y = np.asarray(time_data.time_data)
    if y.ndim == 1:
        y = y[:, None]
    yc = y[:, n_chan]
    N = yc.shape[0]

    freqs = _cwt_default_frequencies(fs, N, f_range, voices_per_octave, w0=w0)
    time_step = _cwt_damping_time_step(fs, freqs[-1])
    Wc, t_idx = _morlet_cwt_1d(yc, fs, freqs, w0=w0, time_step=time_step,
                               progress_callback=progress_callback)
    t = np.asarray(time_data.time_axis)[t_idx]

    time_slice = _resolve_damping_start_slice(t, start_time, time_data.settings,
                                              default_start_frac=0.05)
    return _fit_modes_from_image(t, freqs, Wc, time_slice,
                                 phase_has_carrier=True,
                                 peak_threshold=peak_threshold)


#%% Damping by band (band-pass filter bank + Schroeder decay integral)

# Band-ladder frequency ratios, anchored at the acoustics-standard 1000 Hz
# centre. 'tenth-decade' (10^(1/10) ~ 1.2589) is numerically close to a third
# octave (2^(1/3) ~ 1.2599) but lands on base-10-preferred centres.
_BAND_RATIOS = {
    'octave': 2.0,
    'third-octave': 2.0 ** (1.0 / 3.0),
    'tenth-decade': 10.0 ** 0.1,
}


def _band_centres(f_lo, f_hi, bands):
    '''Band-centre ladder covering ``f_lo..f_hi`` (Hz), anchored at 1000 Hz.

    Returns the centres ``fc = 1000 * r**k`` (``r`` from `_BAND_RATIOS`) whose
    FULL band ``fc/sqrt(r) .. fc*sqrt(r)`` lies inside the range — a band that
    hangs over either edge would fit a decay its filter never fully captured.
    '''
    r = _BAND_RATIOS[bands]
    sr = np.sqrt(r)
    k_lo = int(np.ceil(np.log(f_lo * sr / 1000.0) / np.log(r)))
    k_hi = int(np.floor(np.log(f_hi / sr / 1000.0) / np.log(r)))
    return 1000.0 * r ** np.arange(k_lo, k_hi + 1)


def _schroeder_db(y):
    '''Schroeder backward-integrated energy-decay curve in dB (max 0 dB).

    ``E(t) = integral of y^2 from t to the end``, normalised to its initial
    value: the ensemble-average decay of the squared envelope, far smoother
    than the raw squared signal (Schroeder 1965). Floored at -300 dB so the
    zero tail sample never hits log10(0).
    '''
    e = np.flip(np.cumsum(np.flip(np.asarray(y, dtype=np.float64) ** 2)))
    e0 = e[0] if e[0] > 0 else 1.0
    return 10.0 * np.log10(np.maximum(e / e0, 1e-30))


def _fit_decay_time(t, L, top_db, bottom_db):
    '''Straight-line fit of the EDC ``L`` (dB) over the ``top_db..bottom_db``
    window, extrapolated to the 60 dB decay time.

    Returns ``(T60, i0, i1, slope, intercept)`` — the decay time (s), the
    fitted window's index bounds, and the fitted line's coefficients (dB/s,
    dB) — or ``(nan, 0, 0, nan, nan)`` when the curve never reaches
    ``bottom_db`` (insufficient decay range for this window), the window
    holds too few samples, or the slope is not a decay.
    '''
    bad = (np.nan, 0, 0, np.nan, np.nan)
    i0 = int(np.argmax(L <= top_db))
    if L[-1] > bottom_db or L[i0] > top_db + 1e-12:
        return bad
    i1 = int(np.argmax(L <= bottom_db))
    if i1 - i0 < 5:
        return bad
    slope, icpt = np.polyfit(t[i0:i1], L[i0:i1], 1)
    if not (slope < 0):
        return bad
    return -60.0 / slope, i0, i1, float(slope), float(icpt)


def calculate_damping_by_band(time_data, n_chan=1, bands='octave',
                              start_time=None, f_range=None, filter_order=4):
    '''
    Band-centred decay metrics via a filter bank + the Schroeder integral.

    The room-acoustics alternative to the sonogram peak fits
    (`calculate_damping_from_sono` / `_from_cwt`): instead of picking modal
    peaks, the free decay is band-pass filtered into standard bands
    (zero-phase Butterworth, ``sosfiltfilt``), each band's energy-decay curve
    is formed with the Schroeder backward integral, and straight-line fits of
    that curve give the band's decay metrics:

    - ``EDT``  — early decay time, 0 to -10 dB fit x6 (perceived reverberance)
    - ``T20``  — -5 to -25 dB fit x3
    - ``T30``  — -5 to -35 dB fit x2
    - ``T60``  — the reverberation time: T30 when its 35 dB range exists,
      else T20 (the standard fallback); NaN when neither window fits
    - ``Qn``   — the equivalent band-centred Q factor, ``Q = pi*fc*T60 /
      (3*ln 10)`` (~= ``fc*T60/2.20``), from ``T60 = 3*ln10/(zeta*wn)``

    A metric is NaN when the band's EDC never spans that fit window
    (insufficient decay range above the noise floor) — not an error.

    Args:
        time_data (<TimeData> object): time series data
        n_chan (int, optional): channel index to analyze, default is 1
        bands (str, optional): ``'all'`` (one broadband band over the whole
            ``f_range``), ``'octave'``, ``'third-octave'`` or
            ``'tenth-decade'`` (10^(1/10) spacing, ~a third octave on
            base-10-preferred centres). Ladders anchor at 1000 Hz and keep
            only bands whose FULL width lies inside ``f_range``.
        start_time (float, optional): free-decay start (seconds); None infers
            it from the pretrigger (see `_resolve_damping_start_slice`), with
            t=0 as the fallback
        f_range (tuple, optional): ``(f_min, f_max)`` Hz analysis range; None
            uses ``4/T .. 0.4*fs`` (the CWT's ``w0=6`` default convention)
        filter_order (int, optional): Butterworth section order, default 4
            (applied forward-backward, so the effective roll-off doubles)

    Returns:
        dict with the ladder arrays (``fc``, ``f_lo``, ``f_hi``, ``EDT``,
        ``T20``, ``T30``, ``T60``, ``Qn`` — NaN where unfittable),
        ``start_time`` (the resolved decay start, s) and ``band_data``: one
        dict per band carrying the plotting payload — the (decimated) EDC
        ``edc_t`` / ``edc_db`` and the T60 fit window ``fit_t`` / ``fit_db``.
    '''
    if bands != 'all' and bands not in _BAND_RATIOS:
        raise ValueError(
            f"bands must be 'all', 'octave', 'third-octave' or 'tenth-decade', "
            f"got {bands!r}")

    fs = time_data.settings.fs
    y = np.asarray(time_data.time_data)
    if y.ndim == 1:
        y = y[:, None]
    yc = y[:, n_chan].astype(np.float64)
    t = np.asarray(time_data.time_axis, dtype=np.float64)

    # Resolve the decay start on the RAW time axis (default: the very start —
    # unlike the STFT there is no window-centring to skip past).
    i_start = _resolve_damping_start_slice(t, start_time, time_data.settings,
                                           default_start_frac=0.0)
    y_dec = yc[i_start:]
    t_dec = t[i_start:] - t[i_start]
    if y_dec.size < 64:
        raise ValueError('too few samples after the decay start for a band fit')
    T = t_dec[-1] if t_dec[-1] > 0 else y_dec.size / fs

    if f_range is None:
        f_range = (4.0 / T, 0.4 * fs)
    f_min = max(float(f_range[0]), 1e-3)
    f_max = min(float(f_range[1]), 0.499 * fs)

    if bands == 'all':
        centres = np.array([np.sqrt(f_min * f_max)])
        edges = [(f_min, f_max)]
    else:
        centres = _band_centres(f_min, f_max, bands)
        sr = np.sqrt(_BAND_RATIOS[bands])
        edges = [(fc / sr, fc * sr) for fc in centres]

    n = len(centres)
    out = {
        'bands': bands,
        'start_time': float(t[i_start]),
        'fc': centres,
        'f_lo': np.array([e[0] for e in edges]),
        'f_hi': np.array([e[1] for e in edges]),
        'EDT': np.full(n, np.nan), 'T20': np.full(n, np.nan),
        'T30': np.full(n, np.nan), 'T60': np.full(n, np.nan),
        'Qn': np.full(n, np.nan),
        'band_data': [],
    }
    # Q = 1/(2 zeta) with T60 = 3 ln10 / (zeta * 2 pi fc).
    q_per_fct60 = np.pi / (3.0 * np.log(10.0))

    for i, (fc, (lo, hi)) in enumerate(zip(centres, edges)):
        sos = signal.butter(filter_order, [lo, hi], btype='bandpass',
                            fs=fs, output='sos')
        yb = signal.sosfiltfilt(sos, y_dec)
        L = _schroeder_db(yb)

        # Each _fit_decay_time already extrapolates its window's slope to the
        # full 60 dB decay time (that IS the standard definition of EDT/T20/
        # T30 — a 60 dB extrapolation of the 10/20/30 dB fit).
        edt = _fit_decay_time(t_dec, L, 0.0, -10.0)[0]
        f20 = _fit_decay_time(t_dec, L, -5.0, -25.0)
        f30 = _fit_decay_time(t_dec, L, -5.0, -35.0)
        # T60 preference: T30's wider window when it exists, else T20.
        best = f30 if np.isfinite(f30[0]) else f20
        t60, j0, j1, slope, icpt = best

        out['EDT'][i] = edt
        out['T20'][i] = f20[0]
        out['T30'][i] = f30[0]
        out['T60'][i] = t60
        out['Qn'][i] = q_per_fct60 * fc * t60 if np.isfinite(t60) else np.nan

        # Plotting payload, decimated to keep the FFI transfer small: the EDC
        # plus the T60 fit LINE over its fitted window.
        step = max(1, L.size // 1024)
        band = {
            'fc': float(fc), 'f_lo': float(lo), 'f_hi': float(hi),
            'edc_t': t_dec[::step], 'edc_db': L[::step],
        }
        if np.isfinite(t60) and j1 > j0:
            band['fit_t'] = np.array([t_dec[j0], t_dec[j1]])
            band['fit_db'] = slope * band['fit_t'] + icpt
        out['band_data'].append(band)

    return out