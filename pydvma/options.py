# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 13:28:39 2018

@author: tb267
"""

import numpy as np

# Heavy / circular imports deferred to the functions that need them:
#   - `streams`     -> MySettings.__init__ fallback (line ~158)
#   - `matplotlib`  -> set_plot_colours
#   - `seaborn`     -> set_plot_colours
# This keeps `import pydvma` fast for script / CLI users who never touch
# the GUI or call set_plot_colours (seaborn alone pulls in ipywidgets
# and IPython, which cost ~0.5 s at import time).

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
        Number of input channels
    fs: int
        Sampling frequency (Hz)
    nbits: int
        Number of bits - either 8, 16, 24 or 32
    chunk_size: int
        Number of samples obtained from each channel in one chunk
    num_chunks: int
        Number of chunks to store in circular buffer
    viewed_time: float
        If specified, overrides num_chunks to display viewed_time in seconds for oscilloscope
    stored_time: float
        Duration of recorded data in seconds
    pretrig_samples: int or None
        Number of samples to keep before trigger, or None for no triggering
    pretrig_threshold: float
        Voltage threshold for trigger detection
    pretrig_channel: int
        Channel index to monitor for trigger
    pretrig_timeout: float
        Timeout in seconds when waiting for trigger
    device_driver: str
        Device type: 'soundcard' or 'nidaq'
    device_index: int
        Device index, will prompt if not specified
    input_channels_spec: str or None
        Optional raw NI physical-channel string for the AI task (e.g.
        'cDAQ1Mod1/ai0:3,cDAQ1Mod3/ai0'). Overrides the auto-constructed
        'dev/ai0:N-1' string when set. Only used by the nidaqmx backend.
    output_channels_spec: str or None
        Same as input_channels_spec but for the AO task.
    VmaxNI: float
        Full-scale input voltage for the NI AI task (±VmaxNI is passed
        as min/max to add_ai_voltage_chan). Default 5 V.
    VmaxSC: float
        Full-scale input voltage for the soundcard path — the voltage
        at the jack that corresponds to a normalised reading of 1.0.
        Default 1.0, meaning "treat the soundcard's normalised output
        as volts at unit scale" (no calibration). If you've measured
        your soundcard's input sensitivity, set this accordingly and
        `log_data` will return voltages with calibrated magnitudes.
    output_VmaxNI: float or None
        Full-scale output voltage for the NI AO task. Defaults to
        VmaxNI if not set.
    output_VmaxSC: float or None
        Full-scale output voltage for the soundcard AO path (i.e. the
        voltage at the jack corresponding to a ±1 sounddevice sample).
        Defaults to VmaxSC if not set.
    NI_mode: str
        Terminal configuration for NI DAQ (e.g., 'DAQmx_Val_RSE', 'DAQmx_Val_Diff')
    init_view_time: bool
        Flag for time domain view in oscilloscope
    init_view_freq: bool
        Flag for frequency domain view in oscilloscope
    init_view_levels: bool
        Flag for channel levels view in oscilloscope
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
                 input_channels_spec=None,
                 VmaxNI=5,
                 VmaxSC=1.0,
                 NI_mode='DAQmx_Val_RSE',
                 init_view_time=True,
                 init_view_freq=True,
                 init_view_levels=True,
                 output_device_driver=None,
                 output_device_index=None,
                 output_channels=None,
                 output_channels_spec=None,
                 output_fs=None,
                 output_VmaxNI=None,
                 output_VmaxSC=None,
                 use_output_as_ch0=False):
        
        #INPUT SETTINGS
        self.fs=int(fs)
        self.channels=int(channels)
        self.stored_time=float(stored_time)
        
        if (pretrig_samples is None) or (pretrig_samples == 'None'):
            self.pretrig_samples=None
        else:
            self.pretrig_samples=int(pretrig_samples)
        
        self.pretrig_threshold=float(pretrig_threshold)
        self.pretrig_channel=int(pretrig_channel)
        self.pretrig_timeout=float(pretrig_timeout)
        
        self.device_driver=device_driver
        self.device_index=device_index

        if (input_channels_spec is None) or (input_channels_spec == 'None') or (input_channels_spec == ''):
            self.input_channels_spec = None
        else:
            self.input_channels_spec = str(input_channels_spec)

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
        if (output_device_driver is None) or (output_device_driver == 'None'):
            output_device_driver = device_driver

        self.output_device_driver = output_device_driver

        if (output_channels_spec is None) or (output_channels_spec == 'None') or (output_channels_spec == ''):
            self.output_channels_spec = None
        else:
            self.output_channels_spec = str(output_channels_spec)

        if (device_driver == 'soundcard') and ((device_index is None) or (device_index == 'None')):
            try:
                # try to find default input soundcard device
                self.device_index = sd.default.device[0]
            except:
                # if info not available, select index 1
                self.device_index = 1
        elif (device_driver == 'nidaq') and ((device_index is None) or (device_index == 'None')):
            self.device_index = 0
        else:
            self.device_index = int(device_index)

       
                
        # set output device index to defaults if not specified
        if (output_device_driver == 'soundcard') and ((output_device_index is None) or  (output_device_index == 'None')):
            try:
                # try to find default output soundcard device
                self.output_device_index = sd.default.device[1]
            except:
                # try to guess sensible default output soundcard by string matching device names
                from . import streams  # lazy import to avoid heavy/circular load at module import
                devices = streams.get_devices_soundcard()
                if devices is not None:
                    output_devices = np.where(['output' in names for names in devices])
                    self.output_device_index = output_devices[0][0]
                else:
                    self.output_device_index = 1
        elif (output_device_driver == 'nidaq') and ((output_device_index is None) or (output_device_index == 'None')):
            self.output_device_index = 0
        else:
            self.output_device_index = int(output_device_index)
        
        self.use_output_as_ch0 = bool(use_output_as_ch0)

        
        # ADVANCED SETTINGS
        self.VmaxNI=float(VmaxNI)
        self.VmaxSC=float(VmaxSC)
        self.NI_mode=NI_mode
        self.chunk_size=int(chunk_size)
        self.num_chunks=int(num_chunks)
        self.viewed_time=float(viewed_time)
        self.nbits=int(nbits)
        self.init_view_time=bool(init_view_time)
        self.init_view_freq=bool(init_view_freq)
        self.init_view_levels=bool(init_view_levels)

        if output_VmaxNI is None:
            self.output_VmaxNI = self.VmaxNI
        else:
            self.output_VmaxNI = float(output_VmaxNI)

        if output_VmaxSC is None:
            self.output_VmaxSC = self.VmaxSC
        else:
            self.output_VmaxSC = float(output_VmaxSC)

        ### derived settings
        if (viewed_time is not None) and (viewed_time != 'None'):
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
        
        if (pretrig_samples is None) or (pretrig_samples == 'None'):
            self.pretrig_samples = None
        else:
            self.pretrig_samples = int(pretrig_samples)
            # The recorder only retains `chunk_size` samples of pre-
            # trigger context (see `streams.Recorder` state-machine
            # docstring); anything larger would produce a malformed
            # window at capture time. Caught again in
            # `acquisition.log_data` in case settings are mutated
            # after construction.
            if self.pretrig_samples > self.chunk_size:
                raise ValueError(
                    'pretrig_samples ({}) must not exceed chunk_size ({}). '
                    'The pretrigger buffer only retains chunk_size samples '
                    'of context before the trigger; increase chunk_size '
                    '(or reduce pretrig_samples) to fit.'
                    .format(self.pretrig_samples, self.chunk_size)
                )


    # Driver-selecting accessors for the full-scale voltages.  Internal
    # code (streams callbacks, oscilloscope display, clipping warning,
    # signal_generator) uses these so it doesn't have to branch on
    # device_driver.  All values are in volts.

    def input_vmax(self):
        '''Effective full-scale input voltage for the current driver.

        Returns ``VmaxNI`` for ``device_driver='nidaq'`` (the configured
        AI range), ``VmaxSC`` for ``device_driver='soundcard'`` (the
        user-supplied jack calibration; defaults to 1.0 = no
        calibration, treating ±1 normalised samples as ±1 V).
        '''
        return self.VmaxNI if self.device_driver == 'nidaq' else self.VmaxSC

    def output_vmax(self):
        '''Effective full-scale output voltage for the current driver.

        Mirror of `input_vmax` for the AO path, based on
        ``output_device_driver``.
        '''
        return (self.output_VmaxNI
                if self.output_device_driver == 'nidaq'
                else self.output_VmaxSC)


    def __repr__(self):
        template = "{:>24}: {}" # column widths: 8, 10, 15, 7, 10
        #print template.format("CLASSID", "DEPT", "COURSE NUMBER", "AREA", "TITLE") # header
        settings_dict = self.__dict__
        text = '\n<MySettings class>\n\n'
        for attr in settings_dict: 
            text += template.format(attr,settings_dict[attr])
            text += '\n'
        
        return text

        


class Output_Signal_Settings(object):
    '''
    A class that stores the output signal settings.
    '''
    def __init__(self,type='None',
                 amp = 0,
                 f1 = 0,
                 f2 = 0):
        self.type = type
        self.amp = amp
        self.f1 = f1
        self.f2 = f2
        
    

def set_plot_colours(channels):
    '''
    Returns a list of RGB colours depending on the number of channels required.
    '''
    # Lazy imports: matplotlib and seaborn are only needed here, and seaborn
    # in particular pulls in ipywidgets/IPython (~0.5 s), so keeping them
    # out of module top-level makes `import pydvma` substantially faster.
    import matplotlib.pyplot as plt
    import seaborn as sns
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
