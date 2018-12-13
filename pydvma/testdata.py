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
    N = np.int16(1e4)
    time_axis = np.arange(N)/settings.fs
    
    time_data = np.zeros([N,2])
    pulse_width = 0.002
    N_pulse = np.int16(np.ceil(pulse_width*settings.fs))
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
    N = np.int32(10*1e4)
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
    
