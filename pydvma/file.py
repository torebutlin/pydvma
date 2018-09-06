# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 14:32:35 2018

@author: tb267
"""
import sys

from . import settings
from . import plotting
from . import logdata

import numpy as np
import tkinter as tk
from tkinter import filedialog


def read_data():
    '''
    Gives the user a filedialog to select a .npy file.
    '''
    
    ##fromfile means extracted 
    open_root = tk.Tk()
    open_root.attributes('-topmost', 1)
    #open_root.attributes('-topmost', 0) # commented to force user to save or cancel
    open_root.filename =  filedialog.askopenfilename()
    if open_root.filename: # askopenfilename returns `False` if dialog closed with "cancel".
        d=np.load(open_root.filename)
        dataset = d[0]
        open_root.destroy()
    else:
        open_root.destroy()
        return

    return dataset
#    
#    fromfile_settings=fromfile_data_array[0]
#    fromfile_data=fromfile_data_array[1]
#    fs=fromfile_settings.fs
#    n_samp=len(fromfile_data[:,0])
#    dt=1/fs
#    t_samp=n_samp*dt
#    fromfile_t_axis= np.arange(0,t_samp,dt)
#    fromfile_freq_axis=np.fft.rfftfreq(len(fromfile_t_axis),1/fs)
#    fromfile_time_data_windowed=np.zeros_like(fromfile_data)
#    fromfile_num_chunks=int(np.ceil((fromfile_settings.stored_time*fromfile_settings.fs)/fromfile_settings.chunk_size))
#    if (fromfile_num_chunks*fromfile_settings.chunk_size)%2==0:
#        fromfile_freq_data=np.zeros(shape=(int(((fromfile_num_chunks*fromfile_settings.chunk_size+2)/2)+1),fromfile_settings.channels))
#    else:
#        fromfile_freq_data=np.zeros(shape=(int((fromfile_num_chunks*fromfile_settings.chunk_size+2+1)/2),fromfile_settings.channels))
#    for i in range(fromfile_settings.channels) :  
#        fromfile_time_data_windowed[:,i] = fromfile_data[:,i] * np.hanning(np.shape(fromfile_data)[0])
#        fromfile_freq_data[:,i] = 20 * np.log10(np.abs(np.fft.rfft(fromfile_time_data_windowed[:,i]))/len(fromfile_time_data_windowed[:,i]))
#        
#    
#    fromfile_time_line = figure(title="Audio Signal Vs. Time", x_axis_label='Time (s)', y_axis_label='Normalised Amplitude')
#    fromfile_freq_line = figure(title="Power Vs Frequency Domain", x_axis_label='Frequency (Hz)', y_axis_label='Power Spectrum (dB)')
#
#    fromfile_time_line.add_tools(pltm.HoverTool())
#    fromfile_freq_line.add_tools(pltm.HoverTool())
#   
#    #this holds on to a label when tapped on but doesn't seem necessary for now
#    #fromfile_time_line.add_tools(pltm.TapTool())
#    #fromfile_freq_line.add_tools(pltm.TapTool())
#    
#    for i in range(fromfile_settings.channels):
#        #plot the time and fft domains
#        fromfile_time_line.line(fromfile_t_axis, fromfile_data[:,i], legend='Channel'+str(i),line_color=tuple(setup.set_plot_colours(fromfile_settings.channels)[i,:]), line_width=0.7)
#        fromfile_freq_line.line(fromfile_freq_axis, fromfile_freq_data[:,i], legend='Channel'+str(i),line_color=tuple(setup.set_plot_colours(fromfile_settings.channels)[i,:]), line_width=0.7)
#    
#    #have to determine the legend.click_policy after defining the line
#    fromfile_time_line.legend.click_policy="hide"
#    fromfile_freq_line.legend.click_policy="hide"
#    
#    #resets the output of the implicit bokeh current document.
#    #Initially, when read_data() was called severally, new figures would be added to the older ones.
#    reset_output()
#    
#    show(row(fromfile_time_line,fromfile_freq_line))




#TODO: Supressing little Tk window. Note that it already gets destroyed after performing its function
# to supress little tk window
#root=tk.Tk()
#root.withdraw()
            
#currently stays as the topmost dialog until exited.
#below line should fix it but instead hides it back
#try adding a pause inbetween the two lines
#tk_window.attributes('-topmost', 0)
#TODO:Sent dialog to the top but without being permanently there.

 
    
            
