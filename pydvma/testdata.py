# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 17:08:42 2018

@author: tb267
"""

from . import options
from . import datastructure

import numpy as np
import datetime


    

#%% Create test data
def create_test_impulse_data(noise_level=0):
    '''
    Creates example time domain data simulating impulse hammer test
    '''
    settings = options.MySettings(fs=10000)
    N = int(1e4)
    time_axis = np.arange(N)/settings.fs
    
    time_data = np.zeros([N,2])
    pulse_width = 0.002
    N_pulse = int(np.ceil(pulse_width*settings.fs))
    n = np.arange(N_pulse)
    pulse = 0.5*(1-np.cos(2*np.pi*n/N_pulse))
    time_data[n,0] = pulse
    
    test_freq = 100
    test_time_const = 0.1
    y = np.exp(-time_axis/test_time_const) * np.sin(2*np.pi*test_freq*time_axis)
    
    y += noise_level*2*(np.random.rand(len(y)) - 0.5)
    
    time_data[:,1] = y
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    timedata = datastructure.TimeData(time_axis,time_data,settings,timestamp=t, timestring=timestring, units=['N','m/s'], channel_cal_factors=[1,1], test_name='Synthesised data')
    #metadata = MetaData(, tf_cal_factors=1)
    
    dataset = datastructure.DataSet()
    dataset.add_to_dataset(timedata)
    
    return dataset

def create_test_impulse_ensemble(N_ensemble=5, noise_level=0.1):
    '''
    Creates ensemble of example time domain data simulating impulse hammer tests
    '''
    dataset = datastructure.DataSet()
    for n in range(N_ensemble):
        d = create_test_impulse_data(noise_level=noise_level)
        dataset.add_to_dataset(d.time_data_list)
    
    return dataset


def create_test_noise_data(added_noise_level=0.1):
    '''
    Creates example time domain data simulating noise input test
    '''
    settings = options.MySettings(fs=10000)
    N = int(10*1e4)
    time_axis = np.arange(N)/settings.fs
    
    time_data = np.zeros([N,2])
    x = np.random.rand(N) - 0.5
    test_freq = 100
    test_time_const = 0.1
    g = np.exp(-time_axis/test_time_const) * np.sin(2*np.pi*test_freq*time_axis)
    y = np.convolve(x,g)
    y = y[0:len(x)]
    
    added_noise = added_noise_level*2*(np.random.rand(N)-0.5)
    time_data[:,0] = x
    time_data[:,1] = y + added_noise
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    timedata = datastructure.TimeData(time_axis,time_data,settings,timestamp=t, timestring=timestring, units=['N','m/s'], channel_cal_factors=[1,1], test_name='Synthesised data')
    
    dataset = datastructure.DataSet()
    dataset.add_to_dataset(timedata)
    
    return dataset
    

def create_test_impulse_data_nonlinear_v1(noise_level=0):
    '''
    Creates example time domain data simulating impulse hammer test
    with double exponential decay (two time constants)
    '''
    settings = options.MySettings(fs=10000)
    N = int(1e4)
    time_axis = np.arange(N)/settings.fs
    
    time_data = np.zeros([N,2])
    pulse_width = 0.002
    N_pulse = int(np.ceil(pulse_width*settings.fs))
    n = np.arange(N_pulse)
    pulse = 0.5*(1-np.cos(2*np.pi*n/N_pulse))
    time_data[n,0] = pulse
    
    test_freq = 100
    test_time_const_1 = 0.05  # Fast decay component
    test_time_const_2 = 0.2   # Slow decay component
    amplitude_1 = 0.7         # Amplitude of fast component
    amplitude_2 = 0.3         # Amplitude of slow component
    
    # Double exponential decay with constant frequency
    y = (amplitude_1 * np.exp(-time_axis/test_time_const_1) + 
            amplitude_2 * np.exp(-time_axis/test_time_const_2)) * np.sin(2*np.pi*test_freq*time_axis)
    
    y += noise_level*2*(np.random.rand(len(y)) - 0.5)
    
    time_data[:,1] = y
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    timedata = datastructure.TimeData(time_axis,time_data,settings,timestamp=t, timestring=timestring, units=['N','m/s'], channel_cal_factors=[1,1], test_name='Synthesised nonlinear data v1')
    
    dataset = datastructure.DataSet()
    dataset.add_to_dataset(timedata)
    
    return dataset


def create_test_impulse_data_nonlinear_v2(noise_level=0):
    '''
    Creates example time domain data simulating impulse hammer test
    with exponential decay and frequency shifting from f2 to f1 using tanh transition
    '''
    settings = options.MySettings(fs=10000)
    N = int(1e4)
    time_axis = np.arange(N)/settings.fs
    
    time_data = np.zeros([N,2])
    pulse_width = 0.002
    N_pulse = int(np.ceil(pulse_width*settings.fs))
    n = np.arange(N_pulse)
    pulse = 0.5*(1-np.cos(2*np.pi*n/N_pulse))
    time_data[n,0] = pulse
    
    f1 = 100   # Final frequency (Hz)
    f2 = 200  # Initial frequency (Hz)
    test_time_const = 0.1
    transition_time = 0.4  # Time scale for frequency transition
    transition_center = 0.2  # Center time of transition
    
    # Frequency varies from f2 to f1 using tanh transition
    freq_transition = 0.5 * (np.tanh((time_axis - transition_center) / transition_time) + 1)
    instantaneous_freq = f2 - (f2 - f1) * freq_transition
    
    # Calculate instantaneous phase
    phase = 2 * np.pi * np.cumsum(instantaneous_freq) / settings.fs
    
    # Response with exponential decay and frequency shift
    y = np.exp(-time_axis/test_time_const) * np.sin(phase)
    
    y += noise_level*2*(np.random.rand(len(y)) - 0.5)
    
    time_data[:,1] = y
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    timedata = datastructure.TimeData(time_axis,time_data,settings,timestamp=t, timestring=timestring, units=['N','m/s'], channel_cal_factors=[1,1], test_name='Synthesised nonlinear data v2')
    
    dataset = datastructure.DataSet()
    dataset.add_to_dataset(timedata)
    
    return dataset