# -*- coding: utf-8 -*-
"""
Created on Tue Aug 28 19:04:14 2018

@author: tb267
"""



from . import options
from . import datastructure

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
matplotlib.rcParams.update({'font.size': 12,'font.family':'serif'})



class PlotData(object):
    def __init__(self,data,channels='all',plot_coherence=True):
        '''
        Args:
            data: plots data which can be class of type:
                    datastructure.DataSet
                    datastructure.TimeData
                    datastructure.FreqData
                    datastructure.TfData
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
            self.data = datastructure.DataSet()
            self.data.add_to_dataset(data)
            self.plot_time_data(data,channels)
        
        elif data[0].__class__.__name__  == 'FreqData':
            self.data = datastructure.DataSet()
            self.data.add_to_dataset(data)
            self.plot_freq_data(data,channels)
            
        elif data[0].__class__.__name__  == 'TfData':
            self.data = datastructure.DataSet()
            self.data.add_to_dataset(data)
            self.plot_tf_data(data,channels,plot_coherence)
            
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
                    self.timeax.plot(time_data_list[n_set].time_axis,time_data_list[n_set].time_data[:,n_chan],'-',linewidth=1,color = options.set_plot_colours(len(time_data_list)*time_data_list[n_set].settings.channels)[count,:]/255,label='set{},ch{}'.format(n_set,n_chan))
            
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
                    self.freqax.plot(freq_data_list[n_set].freq_axis,20*np.log10(np.abs(freq_data_list[n_set].freq_data[:,n_chan])),'-',linewidth=1,color = options.set_plot_colours(len(freq_data_list)*freq_data_list[n_set].settings.channels)[count,:]/255,label='set{},ch{}'.format(n_set,n_chan))
            
        self.freqax.legend()
        
        plt.show()
        
    def plot_tf_data(self,tf_data_list,channels,plot_coherence=True):
        ### plot transfer function data
        self.tffig, self.tfax = plt.subplots(figsize = (9,5),dpi=100)
    
        self.tfax.set_xlabel('Frequency (Hz)')
        self.tfax.set_ylabel('Amplitude (dB)')
        self.tfax.grid()
        
        if channels == 'all':
            channels = list(range(tf_data_list[0].settings.channels-1))
        
        count = -1
        for n_set in range(len(tf_data_list)):
            for n_chan in range(tf_data_list[n_set].settings.channels-1):
                count += 1
                if n_chan in channels:
                    self.tfax.plot(tf_data_list[n_set].freq_axis,20*np.log10(np.abs(tf_data_list[n_set].tf_data[:,n_chan])),'-',linewidth=1,color = options.set_plot_colours(len(tf_data_list)*tf_data_list[n_set].settings.channels)[count,:]/255,label='set{},ch{}'.format(n_set,n_chan))
                    if plot_coherence and not np.any(tf_data_list[n_set].tf_coherence == None):
                        self.tfax.plot(tf_data_list[n_set].freq_axis,20*np.log10(np.abs(tf_data_list[n_set].tf_coherence[:,n_chan])),'--',linewidth=1,color = options.set_plot_colours(len(tf_data_list)*tf_data_list[n_set].settings.channels)[count,:]/255,label='set{},ch{} (coherence)'.format(n_set,n_chan))
            
        self.tfax.legend()
        
        plt.show()
        
        


    
    
    


