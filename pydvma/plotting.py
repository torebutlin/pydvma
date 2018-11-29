# -*- coding: utf-8 -*-
"""
Created on Tue Aug 28 19:04:14 2018

@author: tb267
"""



from . import logsettings
from . import file
from . import logdata


###----------------------------------------------------------------------------
import numpy as np
import scipy as sp

###----------------------------------------------------------------------------
import matplotlib
import matplotlib.pyplot as plt
matplotlib.rcParams.update({'font.size': 12,'font.family':'serif'})
###----------------------------------------------------------------------------


class PlotData(object):
    def __init__(self,data,channels='all'):
        '''
        Args:
            data: plots data which can be class of type:
                    logdata.DataSet
                    logdata.TimeData
                    logdata.FreqData
                    logdata.TfData
            channels: list of channels to plot
        '''
        if type(channels) is int:
            channels = [channels]
            
        if not 'list' in data.__class__.__name__.lower():
            # if a raw data object is passed, first put it into expected list format
            data = [data]
            
        if data[0].__class__.__name__ == 'DataSet':
            # if DataSet class then undo turning it into a list
            data = data[0]
            self.data = data
            
            if len(data.time_data_list)>0:
                self.plot_time_data(data.time_data_list,channels)
            if len(data.freq_data_list)>0:
                self.plot_freq_data(data.freq_data_list,channels)
            if len(data.tf_data_list)>0:
                self.plot_tf_data(data.tf_data_list,channels)
            
        elif data[0].__class__.__name__ == 'TimeData':
            self.data = logdata.DataSet()
            self.data.add_to_dataset(data)
            self.plot_time_data(data,channels)
        
        elif data[0].__class__.__name__  == 'FreqData':
            self.data = logdata.DataSet()
            self.data.add_to_dataset(data)
            self.plot_freq_data(data,channels)
            
        elif data[0].__class__.__name__  == 'TfData':
            self.data = logdata.DataSet()
            self.data.add_to_dataset(data)
            self.plot_tf_data(data,channels)
            
        self.channels = channels
            
            
            
    def plot_time_data(self,time_data_list,channels):
        ### plot time domain data
        self.timefig, self.timeax = plt.subplots(figsize = (9,5),dpi=100)
    
        self.timeax.set_xlabel('Time (s)')
        self.timeax.set_ylabel('Normalised Amplitude')
        self.timeax.grid()
        
        if channels == 'all':
            channels = list(range(time_data_list[0].settings.channels))
            print(channels)
            
        count = -1
        for n_set in range(len(time_data_list)):
            for n_chan in range(time_data_list[n_set].settings.channels):
                count += 1
                if n_chan in channels:
                    self.timeax.plot(time_data_list[n_set].time_axis,time_data_list[n_set].time_data[:,n_chan],'-',linewidth=1,color = logsettings.set_plot_colours(len(time_data_list)*time_data_list[n_set].settings.channels)[count,:]/255,label='set{},ch{}'.format(n_set,n_chan))
            
        self.timeax.legend()
        
        plt.show()
        
    def plot_freq_data(self,freq_data_list,channels):
        ### plot frequency domain data
        self.freqfig, self.freqax = plt.subplots(figsize = (9,5),dpi=100)
    
        self.freqax.set_xlabel('Frequency (Hz)')
        self.freqax.set_ylabel('Amplitude (dB)')
        self.freqax.grid()
        
        if channels == 'all':
            channels = list(range(freq_data_list[0].settings.channels))
            
        count = -1
        for n_set in range(len(freq_data_list)):
            for n_chan in range(freq_data_list[n_set].settings.channels):
                count += 1
                if n_chan in channels:
                    self.freqax.plot(freq_data_list[n_set].freq_axis,freq_data_list[n_set].freq_data[:,n_chan],'-',linewidth=1,color = logsettings.set_plot_colours(len(freq_data_list)*freq_data_list[n_set].settings.channels)[count,:]/255,label='set{},ch{}'.format(n_set,n_chan))
            
        self.freqax.legend()
        
        plt.show()
        
    def plot_tf_data(self,tf_data_list,channels):
        ### plot transfer function data
        self.tffig, self.tfax = plt.subplots(figsize = (9,5),dpi=100)
    
        self.tfax.set_xlabel('Frequency (Hz)')
        self.tfax.set_ylabel('Amplitude (dB)')
        self.freqax.grid()
        
        if channels == 'all':
            channels = list(range(tf_data_list[0].settings.channels))
        
        count = -1
        for n_set in range(len(tf_data_list)):
            for n_chan in range(tf_data_list[n_set].settings.channels):
                count += 1
                if n_chan in channels:
                    self.tfax.plot(tf_data_list[n_set].freq_axis,tf_data_list[n_set].tf_data[:,n_chan],'-',linewidth=1,color = logsettings.set_plot_colours(len(tf_data_list)*tf_data_list[n_set].settings.channels)[count,:]/255,label='set{},ch{}'.format(n_set,n_chan))
            
        self.tfax.legend()
        
        plt.show()
        
        


    
    
    


