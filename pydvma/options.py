# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 13:28:39 2018

@author: tb267
"""


import numpy as np
import pyaudio
import pyqtgraph as pg


class MySettings(object):
    '''
    A class that stores the acquisition settings.
    
    Attributes:
    --------------       
    channels: int
        Number of Channels
    fs: int
        Sampling Frequency
    nbits: int
        Number of bits - either 8, 16, 24 or 32
    chunk_size: int
        Number of samples obtained from each channel in one chunk
    num_chunks: int
        Number of chunks to store in circular buffer
    view_time: float
        If specified, overrides num_chunks to display view_time in seconds for oscilloscope
    stored_time: float
        Length of the pre-trigger when the space button is hit, in seconds
    device_index: int
        device index, will prompt if not specified
    init_view_time: bool
        flag for time domain view in oscilloscope
    init_view_freq: bool
        flag for frequency domain view in oscilloscope
    init_view_levels: bool
        flag for channel levels view in oscilloscope
    '''
        
    def __init__(self, *, 
                 channels=2, 
                 fs=44100, 
                 nbits=16, 
                 chunk_size=100, 
                 num_chunks=6,
                 viewed_time=None,
                 stored_time=2,
                 pretrig_samples=None,
                 pretrig_threshold=0.2,
                 pretrig_channel=0,
                 pretrig_timeout=20,
                 device_driver='soundcard',
                 device_index=None,
                 VmaxNI=10.0,
                 init_view_time=True,
                 init_view_freq=True,
                 init_view_levels=True):
        
        self.channels=channels
        self.fs=fs
        self.chunk_size=chunk_size
        self.num_chunks=num_chunks
        self.viewed_time=viewed_time
        self.nbits=nbits
        self.stored_time=stored_time
        self.pretrig_samples=pretrig_samples
        self.pretrig_threshold=pretrig_threshold
        self.pretrig_channel=pretrig_channel
        self.pretrig_timeout=pretrig_timeout
        self.device_driver=device_driver
        self.device_index=device_index
        self.VmaxNI=VmaxNI
        self.init_view_time=init_view_time
        self.init_view_freq=init_view_freq
        self.init_view_levels=init_view_levels
        
        ### derived settings
        if viewed_time != None:
            self.num_chunks = int(np.ceil(viewed_time*fs/chunk_size))
        
        if self.chunk_size < 10:
            self.chunk_size = np.int16(10)
            print('Resetting ''chunk_size'' to minimum value of 10')
            
        self.format = eval('pyaudio.paInt'+str(self.nbits))
        self.device_name = None # until initialise stream
        
        if pretrig_samples != None:
            if pretrig_samples > chunk_size:
                raise Exception('pretrig_samples must be less than or equal to chunk_size.')
        
    
    def __repr__(self):
        template = "{:>24}: {}" # column widths: 8, 10, 15, 7, 10
        #print template.format("CLASSID", "DEPT", "COURSE NUMBER", "AREA", "TITLE") # header
        settings_dict = self.__dict__
        text = '\n<MySettings class>\n\n'
        for attr in settings_dict: 
            text += template.format(attr,settings_dict[attr])
            text += '\n'
        
        return text

        
        
def set_plot_colours(channels):
    '''
    Returns a list of RGB colours depending on the number of channels required.
    '''
    #TODO: Accessible colours
    val = [0.0,0.5,1.0]
    colour = np.array([[255,0,0,255],[0,255,0,255],[0,0,255,255]], dtype = np.ubyte)
    plot_colourmap =  pg.ColorMap(val,colour)
    c_list = plot_colourmap.getLookupTable(nPts =channels,alpha=True)
    return c_list 
