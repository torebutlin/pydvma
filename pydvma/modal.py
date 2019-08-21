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

def f_3dB(f,G0):
    
    ff = np.linspace(f[0],f[-1],np.max([len(f),1000]))
    GG = np.interp(ff,f,np.squeeze(G0))
    
    f=ff
    G0=GG
    
    
    fn0i = np.argmax(np.abs(G0))
    fn0 = f[fn0i]
    
    halfpower = np.max(np.abs(G0)) / np.sqrt(2)
    
    xi = np.where(np.squeeze(np.abs(G0)) > halfpower)[0]

    
    f1 = f[xi[1]]
    f2 = f[xi[-1]]

    
    df = f2-f1
    zn0 = df/2/fn0
    
    return fn0,zn0



def modal_fit_single(tf_data,freq_range=None,channel=0,measurement_type='acc'):
    '''
    Fit modal parameters for a single mode to data within specified freq_range
    '''
    
    if freq_range == None:
        freq_range = tf_data.freq_axis[[0,-1]]
    
    
    f = tf_data.freq_axis
    selected_range = np.where((f > freq_range[0]) & (f < freq_range[1]))
    
    f = f[selected_range]
    
    #NEED GOOD INITIAL GUESS!
    G0 = tf_data.tf_data[selected_range,channel]
    
    fn0,zn0 = f_3dB(f,G0)
    print(zn0)
    
    fn0i = np.argmax(np.abs(G0))
    fn0 = f[fn0i]
    zn0 = np.diff(freq_range)[0]/2/fn0
    an0 = np.max(np.abs(G0))*(2*np.pi*fn0)**2 * 2*zn0

    
    pn0 = 0
    Rr0 = 0
    Ri0 = 0
    
    
    x0 = np.array([an0,fn0,zn0,pn0,Rr0,Ri0])
    print(x0)
    

    bounds = ([-np.inf,freq_range[0],0,-np.pi/2,-np.inf,-np.inf],[np.inf,freq_range[1],np.inf,np.pi/2,np.inf,np.inf])
#    bounds = ((-np.inf,np.inf),(freq_range[0],freq_range[1]),(0,np.inf),(-np.pi/2,np.pi/2),(-np.inf,np.inf),(-np.inf,np.inf))
    
    r = optimize.least_squares(f_residual,x0, bounds=bounds, max_nfev=1000, args=(f,G0,measurement_type))
#    r = optimize.minimize(f_residual,x0, bounds=bounds, method='SLSQP', args=(f,G0,measurement_type))
    
    return r
    
    

def f_TF(x,f,measurement_type):
    an = x[0]
    fn = x[1]
    zn = x[2]
    pn = x[3]
    R  = x[4] + 1j*x[5]
    
    wn = 2*np.pi*fn
    w = 2*np.pi*f
    
    
    if measurement_type == 'acc':
        p = 2
    elif measurement_type == 'vel':
        p = 1
    elif measurement_type == 'dsp':
        p = 0
    
    G = an*np.exp(1j*pn)/(wn**2 + 2j*wn*zn*w - w**2)
    G = G*((1j*w)**p) + R
    
    return G



def f_residual(x,f,G0,measurement_type):
    
    G0 = np.squeeze(G0)
    G = f_TF(x,f,measurement_type)
        
    e = (G-G0)
    #e = np.abs(e)
    e = np.concatenate((np.real(e),np.imag(e)))
    
    
    return e


    