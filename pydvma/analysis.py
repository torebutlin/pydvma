# -*- coding: utf-8 -*-
"""
Created on Sun Sep  2 20:16:26 2018

@author: tb267
"""

from . import datastructure

import numpy as np
from scipy import signal
import copy


def calculate_fft(time_data,time_range=None,window=None):
    '''
    Args:
        time_data (<TimeData> object): time series data
        time_range: 2x1 numpy array to specify data segment to use
        window (bool): apply blackman filter to data before fft or not
    '''
    
    if not time_data.__class__.__name__ is 'TimeData':
        raise Exception('Input data needs to be single <TimeData> object')
    

    if time_range == None:
        ### use all data
        time_range_copy = time_data.time_axis[[0,-1]]
        
    elif time_range.__class__.__name__ == 'PlotData':
        time_range_copy=time_range.ax.get_xbound()
        
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
    
    freq_data = datastructure.FreqData(faxis,fdata,settings,id_link=time_data.unique_id,test_name=time_data.test_name)
    
    return freq_data

def multiply_by_power_of_iw(data,power,channel_list):
    
    if data.__class__.__name__ is 'TfData':
        iw = 1j*2*np.pi * data.freq_axis[:,None]
        if power<0:
            iw[0]=np.inf
        data.tf_data[:,channel_list] = (iw**power) * data.tf_data[:,channel_list]
    elif data.__class__.__name__ is 'FreqData':
        iw = 1j*2*np.pi * data.freq_axis[:,None]
        if power<0:
            iw[0]=np.inf
        data.freq_data[:,channel_list] = (iw**power) * data.freq_data[:,channel_list]
    else:
        raise ValueError('Expecting input argument of type <FreqData> or <TfData>')
        
    return data


def best_match(tf_data_list,freq_range=None,set_ref=0,ch_ref=0):
    '''
    Args:
        tf_data (<TfData> object): transfer function data
        freq_range: 2x1 numpy array to specify data segment to use
    '''
    
    if not tf_data_list.__class__.__name__ is 'TfDataList':
        raise ValueError('Input data needs to be single <TfData> object')
    

    if freq_range == None:
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
        
    factors = []
    for ns in range(n_set):
        f=[]
        n_chan = len(tf_data_list[ns].tf_data[0,:])
        s1 = tf_data_list[ns].freq_axis >= freq_range_copy[0]
        s2 = tf_data_list[ns].freq_axis <= freq_range_copy[1]
        selection = s1 & s2
        for nc in range(n_chan):
            a = tf_data_list[ns].tf_data[selection,nc]
            b = tf_data_list[set_ref].tf_data[selection_ref,ch_ref]
#            f += [np.abs(np.sum(np.conj(a)*b) / np.sum(np.conj(a)*a))]
            f += [np.sqrt(np.mean(np.abs(b**2))) / np.sqrt(np.mean(np.abs(a**2)))]
            
        f = np.array(f)
        factors.append(f)
    
    return factors



def calculate_cross_spectrum_matrix(time_data, time_range=None, window=None, N_frames=1, overlap=0.5):
    '''
    Args:
        time_data (<TimeData> object): time series data
        time_range: 2x1 numpy array to specify data segment to use
        window (None or str): apply filter to data before fft or not
        N_frames (int): number of frames to average over
        overlap (between 0,1): frame overlap fraction
    '''
    # TODO iterate over list of timedata... but need new dataset type?
    
    if window==None:
        window='boxcar'
        
    if not time_data.__class__.__name__ is 'TimeData':
        raise Exception('Input data needs to be single <TimeData> object')

    if time_range == None:
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
    #time_selected = timedata.time_axis[selection]
    
    N_samples = len(data_selected[:,0])
    nperseg = np.int32(np.ceil(N_samples / (N_frames+1) / (1-overlap)))
    freqlength = len(np.fft.rfftfreq(nperseg))
    

    noverlap = np.ceil(overlap*nperseg)
    
    Pxy = np.zeros([settings.channels,settings.channels,freqlength],dtype=complex)
    Cxy = np.zeros([settings.channels,settings.channels,freqlength])
    for nx in np.arange(settings.channels):
        for ny in np.arange(settings.channels):
            if nx > ny:
                Pxy[nx,ny,:] = np.conjugate(Pxy[ny,nx,:])
                Cxy[nx,ny,:] = Cxy[ny,nx,:]
            else:
                x = data_selected[:,nx]
                y = data_selected[:,ny]
                f,P = signal.csd(x,y,settings.fs,window=window, nperseg=nperseg, noverlap=noverlap,scaling='spectrum')
                f,C = signal.coherence(x,y,settings.fs,window=window, nperseg=nperseg, noverlap=noverlap)
                Pxy[nx,ny,:] = P
                Cxy[nx,ny,:] = C
            
    cross_spec_data = datastructure.CrossSpecData(f,Pxy,Cxy,settings,id_link=time_data.unique_id,test_name=time_data.test_name)
    
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
        time_range: 2x1 numpy array to specify data segment to use
        window (None or str): type of window to use, default is None.
    '''
    
    if time_data_list.__class__.__name__ is not 'TimeDataList':
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
    
    
    cross_spec_data_av = datastructure.CrossSpecData(cross_spec_data.freq_axis,Pxy_av,Cxy,settings,id_link=id_link_list,test_name=time_data_list[0].test_name)

    return cross_spec_data_av


def calculate_tf(time_data, ch_in=0, time_range=None, window=None, N_frames=1, overlap=0.5):
    '''
    Args:
        time_data (<TimeData> object): time series data
        ch_in (int): index of input channel
        time_range: 2x1 numpy array to specify data segment to use
        window (None or str): apply filter to data before fft or not
        N_frames (int): number of frames to average over
        overlap (between 0,1): frame overlap fraction
    '''
    if not time_data.__class__.__name__ is 'TimeData':
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
    
    ch_all = np.arange(time_data.settings.channels)
    ch_out_set = np.setxor1d(ch_all,ch_in)
    
    tf_data = np.zeros([len(f),len(ch_out_set)],dtype=complex)
    tf_coherence = np.zeros([len(f),len(ch_out_set)])
    ch_count = -1
    for ch_out in ch_out_set:
        ch_count += 1
        tf_data[:,ch_count] = Pxy[ch_out,ch_in,:] / Pxy[ch_in,ch_in,:]
        tf_coherence[:,ch_count] = Cxy[ch_out,ch_in,:]
        
    settings.ch_in = ch_in
    settings.ch_out_set = ch_out_set
    
    tfdata = datastructure.TfData(f,tf_data,tf_coherence,settings,id_link=time_data.unique_id,test_name=time_data.test_name)
    
    return tfdata
    

def calculate_tf_averaged(time_data_list, ch_in=0, time_range=None, window=None):
    '''
    Calculates transfer function averaged across ensemble of timedata. Note that 
    this expects a Python list of timedata objects.
    
    Takes each time series as an independent measurement.
    
    Intended for averaged transfer functions from separate measurements, e.g. impulse hammer tests.
    
    Does not average data across sub-frames.    
    
    Args:
        time_data_list (<TimeDataList> object): a list of time series data
        ch_in (int): index of input channel
        time_range: 2x1 numpy array to specify data segment to use
        window (None or str): type of window to use, default is None.
    '''
    
    if time_data_list.__class__.__name__ is not 'TimeDataList':
        raise Exception('Input argument must be <TimeDataList> object.')


    id_link_list = []
    for td in time_data_list:
        id_link_list += [td.unique_id]
        
    N_ensemble = len(time_data_list)
    Pxy_av = 0
    count = -1
    for td in time_data_list:
        count += 1
        ch_all = np.arange(td.settings.channels)
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
        tf_data[:,ch_count] = Pxy_av[ch_out,ch_in,:] / Pxy_av[ch_in,ch_in,:]
        tf_coherence[:,ch_count] = np.abs(Pxy_av[ch_in,ch_out,:])**2 / (np.abs(Pxy_av[ch_in,ch_in,:]) * np.abs(Pxy_av[ch_out,ch_out,:]))

    settings = copy.copy(td.settings)
    settings.window = window
    settings.time_range = time_range
    settings.ch_in = ch_in
    settings.ch_out_set = ch_out_set
    
    
    tfdata = datastructure.TfData(f,tf_data,tf_coherence,settings,id_link=id_link_list,test_name=time_data_list[0].test_name)
    
    return tfdata
