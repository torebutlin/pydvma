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
import uuid


#%% Main data acquisition function
def log_data(settings,test_name=None):
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
            
        print('')
        print('Logging complete.')
        
        # make copy of data
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
    timedata = TimeData(time_axis,stored_time_data_copy,settings,timestamp=t,timestring=timestring,test_name=test_name)
    #metadata = MetaData(timestamp=t,timestring=timestring)
    dataset  = DataSet(timedata=timedata)
    
    return dataset
    
    




#%% Create test data
def create_test_data(noise_level=0):
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
    
    y += noise_level*2*(np.random.rand(len(y)) - 0.5)
    
    time_data[:,1] = y
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    timedata = TimeData(time_axis,time_data,settings,timestamp=t, timestring=timestring, units=['N','m/s'], channel_cal_factors=[1,1], test_name='Synthesised data')
    #metadata = MetaData(, tf_cal_factors=1)
    
    dataset = DataSet(timedata=timedata)
    
    return dataset



    
    



#%% Data structure
class DataSet():
    def __init__(self,*,timedata=[],freqdata=[],cspecdata=[],tfdata=[],sonodata=[],metadata=[]):
        ## initialisation function to set up DataSet class
        
        self.timedata = []
        if isinstance(timedata,TimeData):
            self.timedata.append(timedata)
        elif isinstance(timedata,list):
            self.timedata = timedata
        
        self.freqdata = []
        if isinstance(freqdata,FreqData):
            self.freqdata.append(freqdata)
        elif isinstance(freqdata,list):
            self.freqdata = freqdata
            
        self.cspecdata = []
        if isinstance(cspecdata,CrossSpecData):
            self.cspecdata.append(cspecdata)
        elif isinstance(cspecdata,list):
            self.cspecdata = cspecdata
            
        self.tfdata = []
        if isinstance(tfdata,TfData):
            self.tfdata.append(tfdata)
        elif isinstance(tfdata,list):
            self.tfdata = tfdata

        self.sonodata = []
        if isinstance(sonodata,SonoData):
            self.sonodata.append(sonodata)
        elif isinstance(sonodata,list):
            self.sonodata = sonodata
        
        self.metadata = []
        if isinstance(metadata,MetaData):
            self.metadata.append(metadata)
        elif isinstance(metadata,list):
            self.metadata = metadata
            
        
    def add_to_dataset(self,data):
        ## find out what kind of data being added
        ## allow input to be list of single type of data, or unit data class
        if not type(data) is list:
            # turn into list even if unit length
            data = [data]
        else:
            # check list contains set of same kind of data
            check = True
            for d in data:
                check = check and (d.__class__.__name__ == data[0].__class__.__name__)
            if check is False:
                raise('data list needs to contain homogenous type of data')
                
        data_class = data[0].__class__.__name__    
            
        if data_class=='TimeData':
            self.timedata += data
            print('{} added to dataset'.format(data))
        elif data_class=='FreqData':
            self.freqdata += data
            print('{} added to dataset'.format(data))
        elif data_class=='TfData':
            self.tfdata += data
            print('{} added to dataset'.format(data))
        elif data_class=='SonoData':
            self.sonodata += data
            print('{} added to dataset'.format(data))
        elif data_class=='MetaData':
            self.metadata += data
            print('{} added to dataset'.format(data))
        else:
            print('No data added')
            
    def remove_last_data_item(self,data_class):
        
        if data_class == 'TimeData':
            if len(self.timedata) != 0:
                del self.timedata[-1]
        if data_class == 'FreqData':
            if len(self.freqdata) != 0:
                del self.freqdata[-1]
        if data_class == 'TfData':
            if len(self.tfdata) != 0:
                del self.tfdata[-1]
        if data_class == 'SonoData':
            if len(self.sonodata) != 0:
                del self.sonodata[-1]
        if data_class == 'MetaData':
            if len(self.metadata) != 0:
                del self.metadata[-1]
                
    def remove_data(self,data_class,list_index):
        
        if list_index.__class__.__name__ == 'ndarray':
            list_index = list(list_index)
        elif type(list_index) is int:
            list_index = [list_index]
            
        list_index.sort()


        if data_class == 'TimeData':
            if len(self.timedata) > np.max(list_index):
                for i in reversed(list_index):
                    del self.timedata[i]
            else:
                print('indices out of range, no data removed')
                
        if data_class == 'FreqData':
            if len(self.freqdata) > np.max(list_index):
                for i in reversed(list_index):
                    del self.freqdata[i]
            else:
                print('indices out of range, no data removed')
            
        if data_class == 'TfData':
            if len(self.tfdata) > np.max(list_index):
                for i in reversed(list_index):
                    del self.tfdata[i]
            else:
                print('indices out of range, no data removed')
                    
        if data_class == 'SonoData':
            if len(self.sonodata) > np.max(list_index):
                for i in reversed(list_index):
                    del self.sonodata[i]
            else:
                print('indices out of range, no data removed')
                
        if data_class == 'MetaData':
            if len(self.metadata) > np.max(list_index):
                for i in reversed(list_index):
                    del self.metadata[i] 
            else:
                print('indices out of range, no data removed')

            
    
    def __repr__(self):
        template = "{:>24}: {}" # column widths: 8, 10, 15, 7, 10
        #print template.format("CLASSID", "DEPT", "COURSE NUMBER", "AREA", "TITLE") # header
        dataset_dict = self.__dict__
        text = '\n<DataSet class>\n\n'
        for attr in dataset_dict: 
            text += template.format(attr,dataset_dict[attr])
            text += '\n'
        
        return text
    
   
        
class TimeData():
    def __init__(self,time_axis,time_data,settings,timestamp,timestring,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        self.time_axis = time_axis
        self.time_data = time_data  
        self.settings = settings
        self.timestamp = timestamp
        self.timestring = timestring
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # this is used if data is derived from an existing <TimeData> measurement
        self.test_name = test_name
        self.unique_id = uuid.uuid4()
        
    def __repr__(self):
        return "<TimeData>"

        
class FreqData():
    def __init__(self,freq_axis,freq_data,settings,timestamp,timestring,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        self.freq_axis = freq_axis
        self.freq_data = freq_data
        self.settings = settings
        self.test_name = test_name
        self.timestamp = timestamp
        self.timestring = timestring
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # used to link data to specific <TimeData> object
        
    def __repr__(self):
        return "<FreqData>"
    
    
class CrossSpecData():
    def __init__(self,freq_axis,Pxy,Cxy,settings,timestamp,timestring,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        self.freq_axis = freq_axis
        self.Pxy = Pxy
        self.Cxy = Cxy
        self.settings = settings
        self.test_name = test_name
        self.timestamp = timestamp
        self.timestring = timestring
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # used to link data to specific <TimeData> object
        
    def __repr__(self):
        return "<CrossSpecData>"
    
        
class TfData():
    def __init__(self,freq_axis,tf_data,tf_coherence,settings,timestamp,timestring,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        self.freq_axis = freq_axis
        self.tf_data = tf_data
        self.tf_coherence = tf_coherence
        self.settings = settings
        self.test_name = test_name
        self.timestamp = timestamp
        self.timestring = timestring
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # used to link data to specific <TimeData> object
        
    def __repr__(self):
        return "<TfData>"
    
        
class SonoData():
    def __init__(self,time_axis,freq_axis,sono_data,settings,timestamp,timestring,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        self.time_axis = time_axis
        self.freq_axis = freq_axis
        self.sono_data = sono_data
        self.settings = settings
        self.test_name = test_name
        self.timestamp = timestamp
        self.timestring = timestring
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # used to link data to specific <TimeData> object
        
    def __repr__(self):
        return "<SonoData>"
        
class MetaData():
    def __init__(self, timestamp=None, timestring=None, units=None, channel_cal_factors=None, tf_cal_factors = None,test_name=None):
        ### not sure this is a helpful datafield: might delete. Metadata then contained within each data unit.
        self.timestamp = timestamp
        self.timestring = timestring
        self.units = units
        self.channel_cal_factors = None
        self.tf_cal_factors = None
        
    def __repr__(self):
        return "<MetaData>"