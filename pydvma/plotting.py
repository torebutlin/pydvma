# -*- coding: utf-8 -*-
"""
Created on Tue Aug 28 19:04:14 2018

@author: tb267
"""



from . import settings
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


class plotdata(object):
    def __init__(self,data):
        '''
        Args:
            data: plots data which can be class of type:
                    logdata.dataSet
                    logdata.timeData
                    logdata.freqData
        '''
        
        
        if data.__class__.__name__ == 'dataSet':
            tdata = data.timeData
            fdata = data.freqData
            self.dataset = data
            
        elif data.__class__.__name__  == 'timeData':
            tdata = data
            fdata = None
            self.dataset = logdata.dataSet(timeData=tdata,settings=tdata.settings)
            
        elif data.__class__.__name__  == 'freqData':
            tdata = None
            fdata = data
            self.dataset = logdata.dataSet(freqData=fdata,settings=fdata.settings)
            
        if tdata != None and fdata != None:
            ### plot time and frequency domain data together
            self.fig, self.ax = plt.subplots(2, 1,figsize = (9,5),dpi=100)
            
            self.ax[0].set_xlabel('Time (s)')
            self.ax[0].set_ylabel('Amplitude')
#            self.ax[0].set_xlim(fdata.settings.time_range)
            self.ax[0].axvspan(fdata.settings.time_range[0], fdata.settings.time_range[1], color='blue', alpha=0.25)
            self.ax[0].grid()
            self.ax[1].set_xlabel('Frequency (Hz)')
            self.ax[1].set_ylabel('Amplitude')
            self.ax[1].grid()
            
            
            for n in range(data.settings.channels):
                self.ax[0].plot(tdata.time_axis,tdata.time_data[:,n],'-',linewidth=2,color = settings.set_plot_colours(data.settings.channels)[n,:]/255,label='ch '+str(n))
                self.ax[1].plot(fdata.freq_axis,20*np.log10(np.abs(fdata.freq_data[:,n])),'-',linewidth=2,color = settings.set_plot_colours(data.settings.channels)[n,:]/255,label='ch '+str(n))
                
            self.ax[0].legend()
            self.ax[1].legend()
            
        elif tdata != None:
            ### plot time domain data
            self.fig, self.ax = plt.subplots(figsize = (9,5),dpi=100)
        
            self.ax.set_xlabel('Time (s)')
            self.ax.set_ylabel('Amplitude')
            self.ax.grid()
            
            for n in range(data.settings.channels):
                self.ax.plot(tdata.time_axis,tdata.time_data[:,n],'-',linewidth=2,color = settings.set_plot_colours(data.settings.channels)[n,:]/255,label='ch '+str(n))
                
            self.ax.legend()
            
        elif fdata != None:
            ### plot frequency domain data
            self.fig, self.ax = plt.subplots(figsize = (9,5),dpi=100)
        
            self.ax.set_xlabel('Frequency (Hz)')
            self.ax.set_ylabel('Amplitude')
            self.ax.grid()
            
            for n in range(data.settings.channels):
                self.ax.plot(fdata.freq_axis,20*np.log10(np.abs(fdata.freq_data[:,n])),'-',linewidth=2,color = settings.set_plot_colours(data.settings.channels)[n,:]/255,label='ch '+str(n))
                
            self.ax.legend()
            

        
        plt.show()
        
        
        
#class plot_timeData
    
    
    

