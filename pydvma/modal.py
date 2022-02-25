# -*- coding: utf-8 -*-
"""
Created on Mon Aug 19 17:29:30 2019

@author: tb267
"""


from . import datastructure
from . import options

import numpy as np
from scipy import signal
from scipy import optimize
import copy

MESSAGE = ''

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

    
    f1 = f[xi[0]]
    f2 = f[xi[-1]]

    
    df = f2-f1
    zn0 = df/2/fn0
    
    return fn0,zn0



def modal_fit_single_channel(tf_data,freq_range=None,channel=0,measurement_type='acc'):
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
    
    
    
    an0 = np.max(np.abs(G0))*(2*np.pi*fn0)**2 * 2*zn0
    pn0 = 0
    Rk0 = np.max(np.abs(G0))/1e3
    Rm0 = np.max(np.abs(G0))*((2*np.pi*fn0)**2)/1e3
    
    
    #x0 = np.array([fn0,zn0,an0,pn0,Rk0,Rm0])
    x0 = np.concatenate(([fn0],[zn0],an0,pn0,Rk0,Rm0))
    
    bounds = ([freq_range[0],0,-np.inf,-np.pi/2,0,0],[freq_range[1],1,np.inf,np.pi/2,np.inf,np.inf])
#    bounds = ((-np.inf,np.inf),(freq_range[0],freq_range[1]),(0,np.inf),(-np.pi/2,np.pi/2),(-np.inf,np.inf),(-np.inf,np.inf))
    
    r = optimize.least_squares(f_residual,x0, bounds=bounds, max_nfev=1000, args=(f,G0,measurement_type))
#    r = optimize.minimize(f_residual,x0, bounds=bounds, method='SLSQP', args=(f,G0,measurement_type))
    print('')
    print('fn={:.4g} (Hz), zn={:.4g}, an={:.4g}, phase={:.4g} (deg)'.format(r.x[0],r.x[1],r.x[2],r.x[3]*180/np.pi))
    print('')
    if (np.abs(r.x[3])*180/np.pi > 60):
        print('Phase is significant, check ''measurement_type'' setting is correct')
    return r
    
    

def f_TF(x,f,measurement_type):

    fn = x[0]
    zn = x[1]
    an = x[2]
    pn = x[3]
#    R  = x[4] + 1j*x[5]
    R1 = x[4]
    R2 = x[5]
    
    wn = 2*np.pi*fn
    w = 2*np.pi*f
    
    
    if measurement_type == 'acc':
        p = 2
    elif measurement_type == 'vel':
        p = 1
    elif measurement_type == 'dsp':
        p = 0
    
    G = an*np.exp(1j*pn)/(wn**2 + 2j*wn*zn*w - w**2) + R1 - R2/(w**2)
    G = G*((1j*w)**p)
    
    return G



def f_residual(x,f,G0,measurement_type):
    
    G0 = np.squeeze(G0)
    G = f_TF(x,f,measurement_type)
        
    e = (G-G0)
    #e = np.abs(e)
    e = np.concatenate((np.real(e),np.imag(e)))
    
    
    return e



#%%
def f_TF_all_channels(x,f,measurement_type):

    N_tfs = np.int((len(x)-2)/4)
    
    fn = x[0]
    zn = x[1]
    an = x[2:2+N_tfs].reshape(1,N_tfs)
    pn = x[2+N_tfs:2+2*N_tfs].reshape(1,N_tfs)
#    R  = x[4] + 1j*x[5]
    R1 = x[2+2*N_tfs:2+3*N_tfs].reshape(1,N_tfs)
    R2 = x[2+3*N_tfs:2+4*N_tfs].reshape(1,N_tfs)
    
    wn = 2*np.pi*fn
    w = 2*np.pi*f
    w = w.reshape(len(w),1)
    
    
    if measurement_type == 'acc':
        p = 2
    elif measurement_type == 'vel':
        p = 1
    elif measurement_type == 'dsp':
        p = 0

    if w[0]==0:
        # avoid singularity at w=0
        w[0] = w[1]
    G = an*np.exp(1j*pn)/(wn**2 + 2j*wn*zn*w - w**2) + R1 - R2/(w**2)
    G = G*((1j*w)**p)
    
    return G


def f_residual_all_channels(x,f,G0,measurement_type):
    
    G = f_TF_all_channels(x,f,measurement_type)
        
    e = (G-G0)
    #e = np.abs(e)
    e = np.concatenate((np.real(e),np.imag(e)))
    e = e.reshape(np.size(e))
    
    return e

#%% MULTI-CHANNEL MODAL FIT
def modal_fit_all_channels(tf_data_list,freq_range=None,measurement_type='acc'):
    '''
    Fit modal parameters for a single mode to data within specified freq_range.
    
    Assumes all tf_data in tf_data_list have same frequency axes
    '''
    global MESSAGE
    
    if measurement_type == 'acc':
        p = 2
    elif measurement_type == 'vel':
        p = 1
    elif measurement_type == 'dsp':
        p = 0
    
    # Find out how many TFs in dataset
    N_tfs = 0
    for tf_data in tf_data_list:
        if tf_data.flag_modal_TF == False:
            N_tfs += len(tf_data.tf_data[0,:])
    
    if freq_range == None:
        freq_range = tf_data.freq_axis[[0,-1]]
    
    # get selected frequency axis
    f = tf_data_list[0].freq_axis
    selected_range = np.where((f > freq_range[0]) & (f < freq_range[1]))
    
    f = f[selected_range]
    
    # compile transfer functions into single array, and get initial guesses
    G0 = np.zeros((len(f),N_tfs),dtype=complex)
    fn0 = np.zeros(N_tfs)
    zn0 = np.zeros(N_tfs)
    counter = -1
    for tf_data in tf_data_list:
        if tf_data.flag_modal_TF == False:
            for n_chan in range(len(tf_data.tf_data[0,:])):
                counter += 1
                G0[:,counter] = tf_data.tf_data[selected_range,n_chan] * tf_data.channel_cal_factors[n_chan]
                fn0[counter],zn0[counter] = f_3dB(f,G0[:,counter])
            

    # initial global guess for fn0,zn0 discarding any outliers
    fn0 = np.median(fn0)
    zn0 = np.median(zn0)
    fn0i = np.argmin(np.abs(f - fn0))
    
    
    # initial guesses for each channel
    an0 = np.zeros(N_tfs)
    pn0 = np.zeros(N_tfs)
    Rk0 = np.zeros(N_tfs)
    Rm0 = np.zeros(N_tfs)
    id_link = []
    counter = -1
    for tf_data in tf_data_list:
        if tf_data.flag_modal_TF == False:
            id_link += [tf_data.id_link]
            for n_chan in range(len(tf_data.tf_data[0,:])):
                counter += 1
                an0[counter] = np.max(np.abs(G0[:,counter]))*(2*np.pi*fn0)**(2-p) * 2*zn0
    #            an0[counter] = an0[counter] * np.sign(np.real(G0[fn0i,counter] / ((2j*np.pi*fn0)**p)))
                an0[counter] = an0[counter] * np.sign(-np.imag(G0[fn0i,counter] / ((1j)**p)))
                
                pn0[counter] = 0
                Rk0[counter] = np.max(np.abs(G0[:,counter]))/1e6
                Rm0[counter] = np.max(np.abs(G0[:,counter]))*((2*np.pi*fn0)**2)/1e6
    
    x0 = np.concatenate(([fn0],[zn0],an0,pn0,Rk0,Rm0))
    
    
    # bounds
    B_fn = freq_range
    B_zn = [0,1]
    B_an = np.zeros((N_tfs,2))
    B_an[:,0] = -np.inf
    B_an[:,1] =  np.inf
    B_pn = np.zeros((N_tfs,2))
    B_pn[:,0] = -np.pi/2
    B_pn[:,1] =  np.pi/2
    B_rk = np.zeros((N_tfs,2))
    B_rk[:,0] = 0
    B_rk[:,1] = np.inf
    B_rm = np.copy(B_rk)
    
    lower_bounds = np.concatenate(([B_fn[0]],[B_zn[0]],B_an[:,0],B_pn[:,0],B_rk[:,0],B_rm[:,0]))
    upper_bounds = np.concatenate(([B_fn[1]],[B_zn[1]],B_an[:,1],B_pn[:,1],B_rk[:,1],B_rm[:,1]))
    
    bounds = (lower_bounds,upper_bounds)
    
    r = optimize.least_squares(f_residual_all_channels,x0, bounds=bounds, max_nfev=1000, args=(f,G0,measurement_type))
    
    settings = tf_data_list[0].settings
    test_name = tf_data_list[0].test_name
    m = datastructure.ModalData(r.x, settings=settings, id_link=id_link, test_name=test_name)

    fn,zn,an,pn,rk,rm = unpack(r.x)

#    with np.printoptions(precision=3, suppress=True):
    MESSAGE = 'fn={:.2f} (Hz), zn={:.3g}, Qn = 1/(2 zn) = {:.1f}\n\n'.format(fn,zn,1/2/zn)
    MESSAGE += 'an={}\n\n'.format(np.array2string(an,precision=3))
    MESSAGE += 'pn={} deg\n\n'.format(np.array2string(pn*180/np.pi,precision=2))
    print(MESSAGE)
    if np.any(np.abs(pn)*180/np.pi > 60):
        MESSAGE += '\nPhase is significant, check ''TF type'' setting is correct.\n'
        print(MESSAGE)
        
    # Check quality of fit
    e = f_residual_all_channels(r.x,f,G0,measurement_type)
    G0rms = np.mean(np.abs(G0)**2)
    erms = np.mean(np.abs(e)**2)
    e_rel = erms/G0rms
    if e_rel > 0.1:
        MESSAGE += '\nPoor quality fit: try adjusting frequency range.\n'
        print(MESSAGE)

    return m
    
#%%% Reconstruction
def unpack(x):
    # unpacks modal parameters into set of variables
    N_tfs = np.int((len(x)-2)/4)
    
    fn = x[0]
    zn = x[1]
    an = x[2:2+N_tfs]
    pn = x[2+N_tfs:2+2*N_tfs]
    rk = x[2+2*N_tfs:2+3*N_tfs]
    rm = x[2+3*N_tfs:2+4*N_tfs]
    
    return fn,zn,an,pn,rk,rm

def unpack_matrix(X):
    # unpacks modal parameters into set of variables
    N_tfs = np.int((len(X[0,:])-2)/4)

    fn = X[:,0]
    zn = X[:,1]
    an = X[:,2:2+N_tfs]
    pn = X[:,2+N_tfs:2+2*N_tfs]
    rk = X[:,2+2*N_tfs:2+3*N_tfs]
    rm = X[:,2+3*N_tfs:2+4*N_tfs]

    return fn,zn,an,pn,rk,rm
    
def pack(fn,zn,an,pn,rk,rm):
    # packs modal parameters into single variable for optimisation
    x = np.concatenate(([fn],[zn],an,pn,rk,rm))
    return x
    

def reconstruct_transfer_function(modal_data,f,measurement_type='acc'):
    '''
    Reconstructs transfer functions from modal_data and returns TfData object
    '''
    G = 0
    for n_row in range(len(modal_data.M[:,0])):
        xn = modal_data.M[n_row,:]
        G += f_TF_all_channels(xn,f,measurement_type=measurement_type)
    
    settings = modal_data.settings
    settings.channels = modal_data.channels
    tf_data = datastructure.TfData(f,G,None,settings,units=modal_data.units,channel_cal_factors=None,id_link=modal_data.id_link,test_name=modal_data.test_name)
    tf_data.flag_modal_TF = True
    return tf_data

def reconstruct_transfer_function_global(modal_data,f,measurement_type='acc'):
    '''
    Reconstructs transfer functions from modal_data and returns TfData object
    '''
    G = 0
    N_tfs = np.int((len(modal_data.M[0,:])-2)/4)
    for n_row in range(len(modal_data.M[:,0])):
        xn = modal_data.M[n_row,:]
        xn[2+2*N_tfs:] = 0 #don't want local residual fits for global fits - i.e. rk and rm
        G += f_TF_all_channels(xn,f,measurement_type=measurement_type)
    
    settings = modal_data.settings
    settings.channels = modal_data.channels
    tf_data = datastructure.TfData(f,G,None,settings,units=modal_data.units,channel_cal_factors=None,id_link=modal_data.id_link,test_name=modal_data.test_name)
    tf_data.flag_modal_TF = True
    return tf_data