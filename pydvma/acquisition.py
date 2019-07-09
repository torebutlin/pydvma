# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 17:08:42 2018

@author: tb267
"""

from . import datastructure
from . import streams

import numpy as np
import scipy.signal as signal
import datetime
import time


#%% Main data acquisition function
def log_data(settings,test_name=None,rec=None, output=None):
    '''
    Logs data according to settings and returns DataSet class
    '''
    
    if rec is None:
        streams.start_stream(settings)
        rec = streams.REC
        
    
    rec.trigger_detected = False
    
    # Stream is slightly longer than settings.stored_time, so need to add delay
    # from initialisation to allow stream to fill up and prevent zeros at start
    # of logged data.
    time.sleep(2*settings.chunk_size/settings.fs)
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    if settings.pretrig_samples == None:

        print('')
        print('Logging data for {} seconds'.format(settings.stored_time))
        
        
        # basic way to control logging time: won't be precise time from calling function
        # also won't be exactly synced to output signal
        if not(np.any(output==None)):
            output_signal(settings,output)
        time.sleep(settings.stored_time)
        
        # make copy of data
        stored_time_data_copy = np.copy(rec.stored_time_data)
        number_samples = np.int64(rec.settings.stored_time * rec.settings.fs)
        
        stored_time_data_copy = stored_time_data_copy[-number_samples:,:]
        print('')
        print('Logging complete.')
        

        
    else:
        rec.__init__(settings)
        rec.trigger_first_detected_message = True
        
        print('')
        print('Waiting for trigger on channel {}'.format(settings.pretrig_channel))
        
        if not(np.any(output==None)):
            output_signal(settings,output)
        t0 = time.time()
        while (time.time()-t0 < settings.pretrig_timeout) and not rec.trigger_detected:
            time.sleep(0.2)
        if (time.time()-t0 > settings.pretrig_timeout):
            raise Exception('Trigger not detected within timeout of {} seconds.'.format(settings.pretrig_timeout))
        
        # make copy of data
        stored_time_data_copy = np.copy(rec.stored_time_data)
        rec.trigger_detected = False
        trigger_check = rec.stored_time_data[(rec.settings.chunk_size):(2*rec.settings.chunk_size),rec.settings.pretrig_channel]
        detected_sample = rec.settings.chunk_size + np.where(np.abs(trigger_check) > rec.settings.pretrig_threshold)[0][0]
        number_samples = rec.settings.stored_time * rec.settings.fs
        start_index = detected_sample - rec.settings.pretrig_samples
        end_index   = start_index + number_samples

        stored_time_data_copy = stored_time_data_copy[start_index:end_index,:]
        
        print('')
        print('Logging complete.')
        
    # make into dataset
    fs = settings.fs
    n_samp = len(stored_time_data_copy[:,0])
    dt = 1/fs
    t_samp = n_samp*dt
    time_axis = np.arange(0,t_samp,dt)
    timedata = datastructure.TimeData(time_axis,stored_time_data_copy,settings,timestamp=t,timestring=timestring,test_name=test_name)
    
    
    dataset  = datastructure.DataSet()
    dataset.add_to_dataset(timedata)
    
    # check for clipping
    if np.any(np.abs(stored_time_data_copy > 0.95)):
        print('WARNING: Data may be clipped')
    
    return dataset
    


def log_data_with_output(settings, output,test_name=None, rec=None):

    
    # call log_data function
    dataset = log_data(settings, test_name, rec)
    
    # call output_signal function
    output_signal(settings,output)
    
    return dataset
    


def output_signal(settings,output):
    # setup NI / audio stream
    if settings.output_device_driver == 'soundcard':
        s = streams.setup_output_soundcard(settings)
        data = output.astype(np.float32).tostring()
        s.write(data)
        
    elif settings.output_device_driver == 'nidaq':
        sh = np.shape(output)
        T = sh[0]/settings.fs
        s = streams.setup_output_NI(settings,output)
        s.StartTask()
        s.WaitUntilTaskDone(T+5)
        s.StopTask()
    else:
        print('device_driver not recognised')
        
    # send to device


def signal_generator(settings,sig='gaussian',T=1,amplitude=1,f=None,selected_channels='all'):
    """
    Creates a signal ready for output to a chosen device
    """
    if selected_channels == 'all':
        selected_channels = np.arange(0,settings.output_channels)
       
    # initiate variables
    t = np.arange(0,T,1/settings.output_fs)
    N_per_channel = np.size(t)
    y = np.zeros((N_per_channel,settings.output_channels))
    win = np.ones((N_per_channel,1))
    T_ramp = np.min([T/10,0.1])
    N_ramp = np.int(T_ramp*settings.output_fs)
    win[0:N_ramp,0] = 0.5*(1-np.cos(np.arange(0,N_ramp)/N_ramp*np.pi))
    win[-N_ramp:,0] = 0.5*(1+np.cos(np.arange(0,N_ramp)/N_ramp*np.pi))
    
    # Create sig. Note 'sig' is choice of signal, while 'signal' is scipy.signal
    if sig == 'gaussian':
        y[:,selected_channels] = np.random.randn(N_per_channel,np.size(selected_channels))
        if f is not None:
            b,a = signal.butter(2,f,btype='bandpass',fs=settings.output_fs)
            y = signal.filtfilt(b,a,y,axis=0,padtype=None)
            y = amplitude * y / np.sqrt(np.mean(y**2))
    elif sig == 'uniform':
        y[:,selected_channels] = np.random.uniform(low=-amplitude,high=amplitude,size=(N_per_channel,np.size(selected_channels)))
        if f is not None:
            b,a = signal.butter(2,f,btype='bandpass',fs=settings.output_fs)
            y = signal.filtfilt(b,a,y,axis=0,padtype=None)
            y = amplitude * y / np.sqrt(np.mean(y**2))
    elif sig == 'sweep':
        if f is None:
            f = [0,settings.output_fs/2]
        
        for ch in selected_channels:
            y[:,ch] = signal.chirp(t,f[0],T,f[1])
    else:
        print('signal type must be one of {''noise'',''sweep''}')
        y = np.zeros((N_per_channel,settings.output_channels))
    
    y = win * y
    return y


def stream_snapshot(rec):
    
    time_data_copy = np.copy(rec.osc_time_data)
    time_axis_copy = np.copy(rec.osc_time_axis)
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)    

    time_data = datastructure.TimeData(time_axis_copy,time_data_copy,rec.settings,timestamp=t,timestring=timestring,test_name='stream_snapshot')
    
    
    return time_data