# -*- coding: utf-8 -*-
"""
Created on Mon Aug 19 17:29:30 2019

@author: tb267
"""


from . import datastructure

import numpy as np
from scipy import signal
from scipy import optimize
import copy

#%% single peak fit

def modal_fit_single(tf_data,freq_range=None,channel=0,measurement_type='acc'):
    '''
    Fit modal parameters for a single mode to data within specified freq_range
    '''
    
    if freq_range == None:
        freq_range = tf_data.freq_axis[[0,-1]]
    
    
    f = tf_data.freq_axis
    selected_range = np.where((f > freq_range[0]) & (f < freq_range[1]))
    
    f = f[selected_range]
    w = 2*np.pi*f
    
    G0 = tf_data.tf_data[selected_range,channel]
    
    fn0 = np.mean(freq_range)
    zn0 = 0.01
    an0 = np.max(np.abs(G0))*fn0*2*np.pi * 2 * zn0
    
    pn0 = 0
    
    x0 = np.array([an0,fn0,zn0,pn0])
    
    r = optimize.minimize(f_single_mode, x0, args=(w,G0,measurement_type))
    
    return r
    
    
def f_single_mode(x,w,G0,measurement_type):
    
    an = x[0]
    fn = x[1]
    zn = x[2]
    pn = x[3]
    
    wn = 2*np.pi*fn
    
    if measurement_type == 'acc':
        p = 2
    elif measurement_type == 'vel':
        p = 1
    elif measurement_type == 'dsp':
        p = 0
    
    G = an*np.exp(1j*pn)/(wn**2 + 2j*wn*zn*w - w**2)
    G = G*(1j*w)**p
    
    e = np.sum((np.abs(G - G0)**2))/np.sum(np.abs(G)**2)
    
    
    return e
