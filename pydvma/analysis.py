# -*- coding: utf-8 -*-
"""
Created on Sun Sep  2 20:16:26 2018

@author: tb267
"""

from . import datastructure

import numpy as np
from scipy import signal
import copy
import peakutils as pu
from scipy.optimize import curve_fit

MESSAGE = ''


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

    return tfdata


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

    
    
#%% SONOGRAM    
def calculate_sonogram(time_data, nperseg=None, noverlap=None):
    '''
    Calculates a complex STFT spectrogram (sonogram) for every channel of
    a <TimeData> object using a Hann window, and returns a <SonoData>.

    Channel calibration factors and units are copied from the source, and
    `id_link` is set to the source's `unique_id` (same provenance
    convention as the other `calculate_*` functions).

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

    f,t,S = signal.spectrogram(y,fs=time_data.settings.fs,window='hann',nperseg=nperseg,noverlap=noverlap,axis=0,mode='complex')
    
    # put channel axis at end
    S_all_chans = np.swapaxes(S,1,2)
    
    sono_data = datastructure.SonoData(
        t, f, S_all_chans, time_data.settings,
        channel_cal_factors=np.asarray(time_data.channel_cal_factors, dtype=float).copy(),
        units=time_data.units,
        id_link=time_data.unique_id, test_name=time_data.test_name,
    )

    return sono_data

#%% CWT
#def calculate_cwt(time_data):
#    return None

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

def calculate_damping_from_sono(time_data,n_chan=1,nperseg=None,start_time=None):
    '''
    Calculate damping from sonogram data.

    Args:
        time_data (<TimeData> object): time series data
        n_chan (int, optional): channel index to analyze, default is 1
        nperseg (int, optional): number of samples per segment for spectrogram
        start_time (float, optional): start time for analysis

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
    '''
    sono_data = calculate_sonogram(time_data, nperseg=nperseg,noverlap=0)

    t = sono_data.time_axis
    f = sono_data.freq_axis
    S = sono_data.sono_data

    # find t index closest to t0
    if start_time is None:
        try:
            # pretrig_samples is None on captures without a trigger;
            # also guards against settings being an older struct that
            # predates that attribute.
            t0 = 2*sono_data.settings.pretrig_samples/sono_data.settings.fs
            time_slice = np.argmin(np.abs(t - t0))
        except (AttributeError, TypeError):
            t0 = t[-1]//20
            time_slice = np.argmin(np.abs(t - t0))

    time_slice_data = np.abs(S[:, time_slice, n_chan])
    threshold = 10 * np.median(time_slice_data)/np.max(time_slice_data)
    peaks = pu.indexes(time_slice_data, thres=threshold, min_dist=1)

    # Collect results locally
    zeta_n = []
    wn_n = []
    fits = []

    for peak in peaks:

        # Extract the real and imaginary parts of S at the peak frequency
        real_part = np.real(np.log(S[peak, :, n_chan]))
        imag_part = np.unwrap(np.imag(np.log(S[peak, :, n_chan])))

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
        W0 = 2*np.pi*f[peak] + W # corrected for the bin frequency

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
        'fits': fits
    }

    return fn, Qn, fit_data