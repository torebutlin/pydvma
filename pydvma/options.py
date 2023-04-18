# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 13:28:39 2018

@author: tb267
"""

from . import streams

import numpy as np

import pyqtgraph as pg
import matplotlib.pyplot as plt
import seaborn as sns

# try:
#     import pyaudio
# except ImportError:
#     pyaudio = None
# except NotImplementedError:
#     pyaudio = None


try:
    import sounddevice as sd
except ImportError:
    sd = None
except NotImplementedError:
    sd = None

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
                 viewed_time=0.3,
                 stored_time=2,
                 pretrig_samples=None,
                 pretrig_threshold=0.05,
                 pretrig_channel=0,
                 pretrig_timeout=20,
                 device_driver='soundcard',
                 device_index=None,
                 VmaxNI=5,
                 NI_mode='DAQmx_Val_RSE',
                 init_view_time=True,
                 init_view_freq=True,
                 init_view_levels=True,
                 output_device_driver=None,
                 output_device_index=None,
                 output_channels=None,
                 output_fs=None,
                 use_output_as_ch0=False):
        
        #INPUT SETTINGS
        self.fs=int(fs)
        self.channels=int(channels)
        self.stored_time=float(stored_time)
        
        if pretrig_samples is not None:
            self.pretrig_samples=int(pretrig_samples)
        
        self.pretrig_threshold=float(pretrig_threshold)
        self.pretrig_channel=int(pretrig_channel)
        self.pretrig_timeout=float(pretrig_timeout)
        
        self.device_driver=device_driver
        self.device_index=device_index
        
        
        # ADVANCED SETTINGS
        self.VmaxNI=float(VmaxNI)
        self.NI_mode=NI_mode
        self.chunk_size=int(chunk_size)
        self.num_chunks=int(num_chunks)
        self.viewed_time=float(viewed_time)
        self.nbits=int(nbits)
        self.init_view_time=bool(init_view_time)
        self.init_view_freq=bool(init_view_freq)
        self.init_view_levels=bool(init_view_levels)
        
        #OUTPUT SETTINGS
        if (output_fs is None) or (output_fs == 'None'):
            self.output_fs = int(self.fs)
        else:
            self.output_fs = int(output_fs)
            
        if (output_channels is None) or (output_channels == 'None'):
            self.output_channels = int(1)
        else:
            self.output_channels = int(output_channels)
            
        # if output device driver not specified then use same as input device
        if (output_device_driver == None) or (output_device_driver == 'None'):
            output_device_driver = device_driver
            self.output_device_driver = output_device_driver

        self.use_output_as_ch0 = bool(use_output_as_ch0)
            
        if (device_driver == 'soundcard') and ((device_index == None) or (device_index == 'None')):
            try:
                # try to find default input soundcard device
                self.device_index = sd.default.device[0]
            except:
                # if info not available, select index 1
                self.device_index = 1
        elif (device_driver == 'nidaq') and ((device_index == None) or (device_index == 'None')):
            self.device_index = 0
        else:
            self.device_index = int(device_index)
                
        # set output device index to defaults if not specified
        if (output_device_driver == 'soundcard') and ((output_device_index == None) or  (output_device_index == 'None')):
            try:
                # try to find default output soundcard device
                self.output_device_index = sd.default.device[1]
            except:
                # try to guess sensible default output soundcard by string matching device names
                devices = streams.get_devices_soundcard()
                if devices != None:
                    output_devices = np.where(['output' in names for names in devices])
                    self.output_device_index = output_devices[0][0]
                else:
                    self.output_device_index = 1
        elif (output_device_driver == 'nidaq') and ((output_device_index == None) or (output_device_index == 'None')):
            self.output_device_index = 0
        else:
            self.output_device_index = int(output_device_index)
        
        ### derived settings
        if (viewed_time != None) and (viewed_time != 'None'):
            self.viewed_time = float(viewed_time)
            self.num_chunks = int(np.ceil(self.viewed_time*self.fs/self.chunk_size))
        else:
            self.viewed_time = None
        
        if self.chunk_size < 10:
            self.chunk_size = int(10)
            print('Resetting ''chunk_size'' to minimum value of 10')
            
        try:    
            self.format = eval('int'+str(self.nbits))
        except:
            pass
        
        self.device_name = None # until initialise stream
        
        if (pretrig_samples == None) or (pretrig_samples == 'None'):
            self.pretrig_samples = None
        else:
            self.pretrig_samples = int(pretrig_samples)
            if self.pretrig_samples > self.chunk_size:
                raise Exception('pretrig_samples must be less than or equal to chunk_size (chunk_size={}).'.format(self.chunk_size))
        
            
        
    
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
    if channels <= 1:
        cmap = plt.get_cmap('tab10')
#        cmap = sns.color_palette('paired')
        c_list = np.array((np.array(cmap.colors) * 255),dtype=int)
    else:
#        cmap = plt.get_cmap('plasma')
#        v = np.linspace(0,1,channels)
#        c_list = np.array(cmap(v) * 255,dtype=int)
        cmap = sns.hls_palette(channels, l=.3, s=1)
        c_list = np.array(np.array(cmap) * 255,dtype=int)
    
#    val = [0.0,0.5,1.0]
#    colour = np.array([[255,0,0,255],[0,255,0,255],[0,0,255,255]], dtype = np.ubyte)
#    plot_colourmap =  pg.ColorMap(val,colour)
#    c_list = plot_colourmap.getLookupTable(nPts =channels,alpha=True)
    return c_list 
