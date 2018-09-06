# -*- coding: utf-8 -*-
"""
Created on Sun Sep  2 20:16:26 2018

@author: tb267
"""
import sys

from . import settings
from . import file
from . import logdata
from . import plotting

import numpy as np
import scipy.signal as sp
import time
import datetime
import copy

def convert_to_frequency(time_data,time_range=None,window=False):
    '''
    Args:
        timeData (class): time series data
        time_range: 2x1 numpy array to specify data segment to use
        window (bool): apply blackman filter to data before fft or not
    '''
    
    if time_range == None:
        ### use all data
        time_range = time_data.time_axis[[0,-1]]
        
    elif time_range.__class__.__name__ == 'plotdata':
        time_range=time_range.ax.get_xbound()
        
    settings = copy.copy(time_data.settings)
    settings.window = window
    settings.time_range = time_range

    
    s1 = time_data.time_axis >= time_range[0]
    s2 = time_data.time_axis <= time_range[1]
    selection = s1 & s2
    data_selected = time_data.time_data[selection,:]
    N = len(data_selected[:,0])
    if window == True:
        data_selected = np.blackman(N)
        
    fdata = np.fft.rfft(data_selected,axis=0)
    faxis = np.fft.rfftfreq(N,1/time_data.settings.fs)
    
    freq_data = logdata.freqData(faxis,fdata,settings)
    
    return freq_data