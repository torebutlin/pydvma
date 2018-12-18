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



class PlotData():
    def __init__(self,sets='all',channels='all'):
        self.fig, self.ax = plt.subplots(1,1,figsize=(9,5),dpi=100)
        self.ax.grid(True,alpha=0.3)
        self.fig.canvas.mpl_connect('pick_event', self.channel_select)
        self.fig.canvas.draw()
        
    def update(self,data_list,sets='all',channels='all'):
        
        
        if data_list.__class__.__name__ is 'TimeDataList':
            self.ax.set_xlabel('Time (s)')
            self.ax.set_ylabel('Amplitude')
        elif data_list.__class__.__name__ is 'FreqDataList':
            self.ax.set_xlabel('Frequency (Hz)')
            self.ax.set_ylabel('Amplitude')
        elif data_list.__class__.__name__ is 'TfDataList':
            self.ax.set_xlabel('Frequency (Hz)')
            self.ax.set_ylabel('Amplitude (dB)')
            
           
        N_sets = len(data_list)
        
        
        self.ax.lines=[]
        if sets is 'all':
            sets = range(N_sets)
        
        count = -1
        for n_set in range(len(data_list)):
            if data_list.__class__.__name__ is 'TfDataList':
                N_chans = len(data_list[0].tf_data[0,:])
            else:
                N_chans = data_list[0].settings.channels
                
            if channels is 'all':
                channels = range(N_chans)

            for n_chan in range(N_chans):
                count += 1
                
                if (n_set not in sets) or (n_chan not in channels):
                    alpha = 0.2
                else:
                    alpha = 0.8
                
                if data_list.__class__.__name__ is 'TimeDataList':
                    x = data_list[n_set].time_axis
                    y = data_list[n_set].time_data[:,n_chan]
                elif data_list.__class__.__name__ is 'FreqDataList':
                    x = data_list[n_set].freq_axis
                    y = 20*np.log10(np.abs(data_list[n_set].freq_data[:,n_chan]))
                elif data_list.__class__.__name__ is 'TfDataList':
                    x = data_list[n_set].freq_axis
                    y = 20*np.log10(np.abs(data_list[n_set].tf_data[:,n_chan]))
                    yc = 20*np.log10(np.abs(data_list[n_set].tf_coherence[:,n_chan]))
                    
                color = options.set_plot_colours(len(data_list)*data_list[n_set].settings.channels)[count,:]/255
                
                label = 'set{},ch{}'.format(n_set,n_chan)
                self.ax.plot(x,y,'-',linewidth=1,color = color,label=label,alpha=alpha)
                if data_list.__class__.__name__ is 'TfDataList':
                    self.ax.plot(x,yc,':',linewidth=1,color = color,label=label,alpha=alpha)
        
        if len(data_list) is not 0:
            self.legend = self.ax.legend()
            self.lines = self.ax.get_lines()
            self.lined = dict()
            
            xmin = min(x)
            xmax = max(x)
            ymin = min(y)
            ymax = max(y)
            self.ax.set_xlim([xmin,xmax])
            self.ax.set_ylim([ymin,ymax])
            for legline, origline in zip(self.legend.get_lines(), self.lines):
                legline.set_picker(10)  # 5 pts tolerance
                self.lined[legline] = origline 
        else:
            self.legend = self.ax.get_legend()
            if self.legend is not None:
                self.legend.remove()
            self.fig.canvas.draw()
    
    
    def channel_select(self,event):
        selected_line = event.artist
        
        a = selected_line.get_alpha()
        a = 1-a
        
        origline = self.lined[selected_line]
        selected_line.set_alpha(a)
        origline.set_alpha(a)
        self.fig.canvas.draw()
    



class PlotTimeData():
    def __init__(self,time_data_list,sets='all',channels='all'):
        self.fig, self.ax = plt.subplots(1,1,figsize=(9,5),dpi=100)
        self.ax.set_xlabel('Time (s)')
        self.ax.set_ylabel('Normalised Amplitude')
        self.ax.grid(True,alpha=0.3)
        self.update(time_data_list,sets,channels)
        self.fig.canvas.mpl_connect('pick_event', self.channel_select)
        self.fig.canvas.draw()
        
    def update(self,time_data_list,sets,channels):
        
        self.ax.lines=[]
        if sets is 'all':
            sets = range(len(time_data_list))
        
        count = -1
        for n_set in range(len(time_data_list)):
            if channels is 'all':
                channels = range(time_data_list[n_set].settings.channels)
        
            for n_chan in range(time_data_list[n_set].settings.channels):
                count += 1
                
                if (n_set not in sets) or (n_chan not in channels):
                    alpha = 0.1
                else:
                    alpha = 0.9
                    
                t = time_data_list[n_set].time_axis
                y = time_data_list[n_set].time_data[:,n_chan]
                color = options.set_plot_colours(len(time_data_list)*time_data_list[n_set].settings.channels)[count,:]/255
                
                label = 'set{},ch{}'.format(n_set,n_chan)
                self.ax.plot(t,y,'-',linewidth=1,color = color,label=label,alpha=alpha)
        
        if len(time_data_list) is not 0:
            self.legend = self.ax.legend()
            self.lines = self.ax.get_lines()
            self.lined = dict()
            for legline, origline in zip(self.legend.get_lines(), self.lines):
                legline.set_picker(10)  # 5 pts tolerance
                self.lined[legline] = origline 
        else:
            self.legend = self.ax.get_legend()
            if self.legend is not None:
                self.legend.remove()
            self.fig.canvas.draw()
    
    
    def channel_select(self,event):
        selected_line = event.artist
        
        a = selected_line.get_alpha()
        a = 1-a
        
        origline = self.lined[selected_line]
        selected_line.set_alpha(a)
        origline.set_alpha(a)
        self.fig.canvas.draw()

        
        


class PlotFreqData():
    def __init__(self,freq_data_list,sets='all',channels='all'):
        self.fig, self.ax = plt.subplots(1,1,figsize=(9,5),dpi=100)
        self.ax.set_xlabel('Frequency (Hz)')
        self.ax.set_ylabel('Normalised Amplitude')
        self.ax.grid(True,alpha=0.3)
        self.update(freq_data_list,sets,channels)
        self.fig.canvas.mpl_connect('pick_event', self.channel_select)
        self.fig.canvas.draw()
        
    def update(self,freq_data_list,sets,channels):
        
        self.ax.lines=[]
        if sets is 'all':
            sets = range(len(freq_data_list))
        
        count = -1
        for n_set in range(len(freq_data_list)):
            if channels is 'all':
                channels = range(freq_data_list[n_set].settings.channels)
        
            for n_chan in range(freq_data_list[n_set].settings.channels):
                count += 1
                
                if (n_set not in sets) or (n_chan not in channels):
                    alpha = 0.1
                else:
                    alpha = 0.9
                    
                f = freq_data_list[n_set].freq_axis
                Y = freq_data_list[n_set].freq_data[:,n_chan]
                color = options.set_plot_colours(len(freq_data_list)*freq_data_list[n_set].settings.channels)[count,:]/255
                
                label = 'set{},ch{}'.format(n_set,n_chan)
                self.ax.plot(f,20*np.log10(np.abs(Y)),'-',linewidth=1,color = color,label=label,alpha=alpha)
        
        if len(freq_data_list) is not 0:
            self.legend = self.ax.legend()
            self.lines = self.ax.get_lines()
            self.lined = dict()
            for legline, origline in zip(self.legend.get_lines(), self.lines):
                legline.set_picker(10)  # 5 pts tolerance
                self.lined[legline] = origline 
        else:
            self.legend = self.ax.get_legend()
            if self.legend is not None:
                self.legend.remove()
            self.fig.canvas.draw()
    
    
    def channel_select(self,event):
        selected_line = event.artist
        
        a = selected_line.get_alpha()
        a = 1-a
        
        origline = self.lined[selected_line]
        selected_line.set_alpha(a)
        origline.set_alpha(a)
        self.fig.canvas.draw()
        
        



class PlotData2(object):
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
        
        


    
    
    


