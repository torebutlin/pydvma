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
    def __init__(self,data):
        '''
        Args:
            data: plots data which can be class of type:
                    logdata.DataSet
                    logdata.TimeData
                    logdata.FreqData
                    logdata.TfData
        '''
        if not isinstance(data,list):
            # if a raw data object is passed, first put it into expected list format
            data = [data]
            
        if data[0].__class__.__name__ == 'DataSet':
            # if DataSet class then undo turning it into a list
            data = data[0]
            if len(data.timedata)>0:
                self.plot_time_data(data.timedata)
            if len(data.freqdata)>0:
                self.plot_freq_data(data.freqdata)
            if len(data.tfdata)>0:
                self.plot_tf_data(data.tfdata)

          
        elif data[0].__class__.__name__ == 'TimeData':
            self.plot_time_data(data)
        
        elif data[0].__class__.__name__  == 'FreqData':
            self.plot_freq_data(data)
            
        elif data[0].__class__.__name__  == 'TfData':
            self.plot_tf_data(data)
            
            
            
    def plot_time_data(self,timedata):
        ### plot time domain data
        self.timefig, self.timeax = plt.subplots(figsize = (9,5),dpi=100)
    
        self.timeax.set_xlabel('Time (s)')
        self.timeax.set_ylabel('Normalised Amplitude')
        self.timeax.grid()
        
        count = -1
        for n_set in range(len(timedata)):
            for n_chan in range(timedata[n_set].settings.channels):
                count += 1
                self.timeax.plot(timedata[n_set].time_axis,timedata[n_set].time_data[:,n_chan],'-',linewidth=1,color = logsettings.set_plot_colours(len(timedata)*timedata[n_set].settings.channels)[count,:]/255,label='set{},ch{}'.format(n_set,n_chan))
            
        self.timeax.legend()
        
        plt.show()
        
    def plot_freq_data(self,freqdata):
        ### plot frequency domain data
        self.freqfig, self.freqax = plt.subplots(figsize = (9,5),dpi=100)
    
        self.freqax.set_xlabel('Frequency (Hz)')
        self.freqax.set_ylabel('Amplitude (dB)')
        self.freqax.grid()
        
        count = -1
        for n_set in range(len(freqdata)):
            for n_chan in range(freqdata[n_set].settings.channels):
                count += 1
                self.freqax.plot(freqdata[n_set].freq_axis,freqdata[n_set].freq_data[:,n_chan],'-',linewidth=1,color = logsettings.set_plot_colours(len(freqdata)*freqdata[n_set].settings.channels)[count,:]/255,label='set{},ch{}'.format(n_set,n_chan))
            
        self.freqax.legend()
        
        plt.show()
        
    def plot_tf_data(self,tfdata):
        ### plot transfer function data
        self.tffig, self.tfax = plt.subplots(figsize = (9,5),dpi=100)
    
        self.tfax.set_xlabel('Frequency (Hz)')
        self.tfax.set_ylabel('Amplitude (dB)')
        self.freqax.grid()
        
        count = -1
        for n_set in range(len(tfdata)):
            for n_chan in range(tfdata[n_set].settings.channels):
                count += 1
                self.tfax.plot(tfdata[n_set].freq_axis,tfdata[n_set].tf_data[:,n_chan],'-',linewidth=1,color = logsettings.set_plot_colours(len(tfdata)*tfdata[n_set].settings.channels)[count,:]/255,label='set{},ch{}'.format(n_set,n_chan))
            
        self.tfax.legend()
        
        plt.show()
        
        


    
    
    


