# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 17:08:42 2018

@author: tb267
"""

from . import logsettings
from . import streams
from . import oscilloscope

import numpy as np
import datetime
import time


#%% Main data acquisition function
def log_data(settings):
    '''
    Logs data according to settings and returns DataSet class
    '''
    
    # Stream is object within Oscilloscope (whether or not Oscilloscope is being viewed)
    if settings.device_driver == 'soundcard':
        oscilloscope.Oscilloscope.rec = streams.Recorder(settings)
        oscilloscope.Oscilloscope.rec.init_stream(settings)
    elif settings.device_driver == 'nidaq':
        oscilloscope.Oscilloscope.rec = streams.Recorder_NI(settings)
        oscilloscope.Oscilloscope.rec.init_stream(settings)
    else:
        print('unrecognised driver')
    
    # make recording stream easier to reference    
    rec = oscilloscope.Oscilloscope.rec
    rec.trigger_detected = False
    
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    
    # Stream is slightly longer than settings.stored_time, so need to add delay
    # from initialisation to allow stream to fill up and prevent zeros at start
    # of logged data.
    time.sleep(2*settings.chunk_size/settings.fs)
    
    if settings.pretrig_samples == None:

        print('')
        print('Logging data for {} seconds'.format(settings.stored_time))
        
        # basic way to control logging time: won't be precise time from calling function
        time.sleep(settings.stored_time)
        
        # make copy of data
        stored_time_data_copy = np.copy(rec.stored_time_data)
        number_samples = rec.settings.stored_time * rec.settings.fs
        stored_time_data_copy = stored_time_data_copy[-number_samples:,:]
        print('')
        print('Logging complete.')
        

        
    else:
        rec.trigger_first_detected_message = True
        t0 = time.time()
        print('')
        print('Waiting for trigger on channel {}'.format(settings.pretrig_channel))
        while (time.time()-t0 < settings.pretrig_timeout) and not rec.trigger_detected:
            time.sleep(0.2)
        if (time.time()-t0 > settings.pretrig_timeout):
            raise Exception('Trigger not detected within timeout of {} seconds.'.format(settings.pretrig_timeout))
            
            
        # make copy of data
        print('')
        print('Logging complete.')
        
        stored_time_data_copy = np.copy(rec.stored_time_data)
        trigger_check = rec.stored_time_data[(rec.settings.chunk_size):(2*rec.settings.chunk_size),rec.settings.pretrig_channel]
        detected_sample = rec.settings.chunk_size + np.where(np.abs(trigger_check) > rec.settings.pretrig_threshold)[0][0]
        number_samples = rec.settings.stored_time * rec.settings.fs
        start_index = detected_sample - rec.settings.pretrig_samples
        end_index   = start_index + number_samples

        stored_time_data_copy = stored_time_data_copy[start_index:end_index,:]
        
    # make into dataset
    fs = settings.fs
    n_samp = len(stored_time_data_copy[:,0])
    dt = 1/fs
    t_samp = n_samp*dt
    time_axis = np.arange(0,t_samp,dt)
    timedata = TimeData(time_axis,stored_time_data_copy,settings)
    metadata = MetaData(timestamp=t,timestring=timestring)
    dataset  = DataSet(timedata=timedata, metadata=metadata)
    
    return dataset
    
    
    # TODO  make pretrigger



#%% Create test data
def create_test_data():
    '''
    Creates example time domain data
    '''
    settings = logsettings.MySettings(fs=10000)
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
    
    time_data[:,1] = y
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    timedata = TimeData(time_axis,time_data,settings)
    metadata = MetaData(timestamp=t, timestring=timestring, units=['N','m/s'], channel_cal_factors=[1,1], tf_cal_factors=1)
    
    dataset = DataSet(timedata=timedata,metadata=metadata)
    
    return dataset



    
    



#%% Data structure
class DataSet():
    def __init__(self,*,timedata=None,freqdata=None,tfdata=None,sonodata=None,metadata=None):
        self.timedata = timedata
        self.freqdata = freqdata
        self.tfdata   = tfdata
        self.sonodata = sonodata
        self.metadata = metadata
        
    def __repr__(self):
        text = '<DataSet class containing: '
        if repr(self.timedata) != 'None':
            text += repr(self.timedata)
        if repr(self.freqdata) != 'None':
            text += repr(self.freqdata)
        if repr(self.tfdata) != 'None':
            text += repr(self.tfdata)
        if repr(self.sonodata) != 'None':
            text += repr(self.sonodata)
        if repr(self.metadata) != 'None':
            text += repr(self.metadata)
        
        text += '>'
        return text
        
        
class TimeData():
    def __init__(self,time_axis,time_data,settings):
        self.time_axis = time_axis
        self.time_data = time_data  
        self.settings = settings
        
    def __repr__(self):
        return "<TimeData>"

        
class FreqData():
    def __init__(self,freq_axis,freq_data,settings):
        self.freq_axis = freq_axis
        self.freq_data = freq_data
        self.settings = settings
        
    def __repr__(self):
        return "<FreqData>"
        
class TfData():
    def __init__(self,freq_axis,tf_data,tf_coherence,settings):
        self.freq_axis = freq_axis
        self.tf_data = tf_data
        self.tf_coherence = tf_coherence
        self.settings = settings
        
    def __repr__(self):
        return "<TfData>"
        
class SonoData():
    def __init__(self,time_axis,freq_axis,sono_data,settings):
        self.time_axis = time_axis
        self.freq_axis = freq_axis
        self.sono_data = sono_data
        self.settings = settings
        
    def __repr__(self):
        return "<SonoData>"
        
class MetaData():
    def __init__(self, timestamp=None, timestring=None, units=None, channel_cal_factors=None, tf_cal_factors = None):
        self.timestamp = timestamp
        self.timestring = timestring
        self.units = units
        self.channel_cal_factors = None
        self.tf_cal_factors = None
        
    def __repr__(self):
        return "<MetaData>"