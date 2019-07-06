# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 17:08:42 2018

@author: tb267
"""

from . import datastructure
from . import streams

import numpy as np
import datetime
import time


#%% Main data acquisition function
def log_data(settings,test_name=None,rec=None,output=None):
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
        t0 = time.time()
        print('')
        print('Waiting for trigger on channel {}'.format(settings.pretrig_channel))
        while (time.time()-t0 < settings.pretrig_timeout) and not rec.trigger_detected:
            time.sleep(0.2)
        if (time.time()-t0 > settings.pretrig_timeout):
            raise Exception('Trigger not detected within timeout of {} seconds.'.format(settings.pretrig_timeout))
        
        print('')
        print('Logging complete.')
        
        # make copy of data
        stored_time_data_copy = np.copy(rec.stored_time_data)
        rec.trigger_detected = False
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
    timedata = datastructure.TimeData(time_axis,stored_time_data_copy,settings,timestamp=t,timestring=timestring,test_name=test_name)
    
    
    dataset  = datastructure.DataSet()
    dataset.add_to_dataset(timedata)
    
    # check for clipping
    if np.any(np.abs(stored_time_data_copy > 0.95)):
        print('WARNING: Data may be clipped')
    
    return dataset
    


def log_data_with_output(settings,output):
    # call log_data function
    # call output_signal function
    
    print('not yet implemented')

def output_signal(settings,output):
    # setup NI / audio stream
    print('not yet implemented')
    # send to device


def signal_generator(settings,signal='noise',fc=0.5,T=1):
    """
    Creates a signal ready for output to a chosen device
    """
    print('not yet implemented')
    #noise
    #sweep
    #how to handle multiple channels? decision needed
    



def stream_snapshot(rec):
    
    time_data_copy = np.copy(rec.osc_time_data)
    time_axis_copy = np.copy(rec.osc_time_axis)
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)    

    time_data = datastructure.TimeData(time_axis_copy,time_data_copy,rec.settings,timestamp=t,timestring=timestring,test_name='stream_snapshot')
    
    
    return time_data