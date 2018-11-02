# -*- coding: utf-8 -*-
"""
Created on Sun Sep  2 20:16:26 2018

@author: tb267
"""
import sys

from . import logsettings
from . import file
from . import logdata
from . import plotting

import numpy as np
from scipy import signal
import time
import datetime
import copy

def convert_to_frequency(timedata,time_range=None,window=False):
    '''
    Args:
        timedata (class): time series data
        time_range: 2x1 numpy array to specify data segment to use
        window (bool): apply blackman filter to data before fft or not
    '''
    
    if time_range == None:
        ### use all data
        time_range = timedata.time_axis[[0,-1]]
        
    elif time_range.__class__.__name__ == 'PlotData':
        time_range=time_range.ax.get_xbound()
        
    settings = copy.copy(timedata.settings)
    settings.window = window
    settings.time_range = time_range

    
    s1 = timedata.time_axis >= time_range[0]
    s2 = timedata.time_axis <= time_range[1]
    selection = s1 & s2
    data_selected = timedata.timedata[selection,:]
    N = len(data_selected[:,0])
    if window == True:
        data_selected = np.blackman(N)
        
    fdata = np.fft.rfft(data_selected,axis=0)
    faxis = np.fft.rfftfreq(N,1/timedata.settings.fs)
    
    freq_data = logdata.FreqData(faxis,fdata,settings)
    
    return freq_data



def calculate_cross_spectrum_matrix(timedata, time_range=None, window='hann', N_frames=1, overlap=0.5):
    '''
    Args:
        timedata (class): time series data
        time_range: 2x1 numpy array to specify data segment to use
        window (None or str): apply filter to data before fft or not
        N_frames (int): number of frames to average over
        overlap (between 0,1): frame overlap fraction
    '''
    
    if time_range == None:
        ### use all data
        time_range = timedata.time_axis[[0,-1]]
        
    elif time_range.__class__.__name__ == 'PlotData':
        time_range=time_range.ax.get_xbound()
        
    settings = copy.copy(timedata.settings)
    settings.window = window
    settings.time_range = time_range

    ## Select data range to use
    s1 = timedata.time_axis >= time_range[0]
    s2 = timedata.time_axis <= time_range[1]
    selection = s1 & s2
    data_selected = timedata.time_data[selection,:]
    time_selected = timedata.time_axis[selection]
    
    N_samples = len(data_selected[:,0])
    nperseg = np.int32(np.ceil(N_samples / (N_frames+1) / (1-overlap)))
    freqlength = len(np.fft.rfftfreq(nperseg))
    
    if window==None:
        window='boxcar'
        
    window_vector = signal.get_window(window,nperseg)
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
            
    return f,Pxy,Cxy


def calculate_tf(timedata, ch_in=0, time_range=None, window='hann', N_frames=1, overlap=0.5):
    '''
    Args:
        timedata (class): time series data
        ch_in (int): index of input channel
        time_range: 2x1 numpy array to specify data segment to use
        window (None or str): apply filter to data before fft or not
        N_frames (int): number of frames to average over
        overlap (between 0,1): frame overlap fraction
    '''
    settings = copy.copy(timedata.settings)
    settings.window = window
    settings.time_range = time_range
    
    ## compute cross spectra
    f,Pxy,Cxy = calculate_cross_spectrum_matrix(timedata, time_range=time_range, window=window, N_frames=N_frames, overlap=overlap)
    
    ## identify transfer functions and corresponding coherence
    
    ch_all = np.arange(timedata.settings.channels)
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
    
    tfdata = logdata.TfData(f,tf_data,tf_coherence,settings)
    
    return tfdata
    

def calculate_tf_averaged(timedata, ch_in=0, time_range=None, window=None):
    '''
    Calculates transfer function averaged across ensemble of timedata. Note that 
    this expects a Python list of timedata objects.
    
    Takes each time series as an independent measurement.
    
    Intended for averaged transfer functions from separate measurements, e.g. impulse hammer tests.
    
    Does not average data across sub-frames.    
    
    Args:
        timedata (class): a list of time series data
        ch_in (int): index of input channel
        time_range: 2x1 numpy array to specify data segment to use
        window (None or str): type of window to use, default is None.
    '''
    
    if type(timedata) is not list:
        timedata = [timedata]

    
    N_ensemble = len(timedata)
    Pxy_av = 0
    count = -1
    for td in timedata:
        count += 1
        ch_all = np.arange(td.settings.channels)
        ch_out_set = np.setxor1d(ch_all,ch_in)
        f,Pxy,Cxy = calculate_cross_spectrum_matrix(td, time_range=time_range, window=window, N_frames=1)
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
    
    #tf_coherence= 0
    
    tfdata = logdata.TfData(f,tf_data,tf_coherence,settings)
    
    return tfdata