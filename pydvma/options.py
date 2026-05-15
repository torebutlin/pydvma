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
        Number of input channels. On the soundcard backend this is
        clamped down to the device's ``max_input_channels`` at
        ``start_stream`` time (with a printed warning) — so the default
        of 2 silently becomes 1 on a Mac built-in mono mic, rather
        than failing with PortAudio ``-9998``. The NI backend instead
        raises ``ValueError`` if the requested count exceeds the
        device's available AI channels.
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
    iepe_excit_current_A: float or sequence of float
        Per-channel IEPE / ICP excitation current in amps. Pass a
        scalar (broadcast to every channel) or a list of length
        ``channels``. Default ``0.0`` = excitation off on every
        channel. Only the NI 9234-class DSA modules in this lab
        support IEPE; the discrete legal values on the 9234 are
        ``0.0`` (off) and ``0.002`` (2 mA on). Per-channel allows
        e.g. ``[0.002, 0.002, 0.0, 0.0]`` for ICP accels on
        ``ai0``/``ai1`` and a charge-amp force input on ``ai2``.
        With excitation enabled, the channel is also switched to
        AC coupling (the standard for IEPE sensors).
    channel_sensitivities: float or sequence of float
        Per-channel sensitivity in volts per engineering unit (V/g
        for an accelerometer, V/N for a force transducer, V/Pa for a
        microphone, etc.). Scalar broadcasts to every channel.
        Default ``1.0`` = no calibration applied (raw volts pass
        through). The reciprocal becomes ``TimeData.channel_cal_factors``,
        so a ``100 mV/g`` accelerometer is ``0.1`` here and yields a
        ``cal_factor`` of ``10`` so plots read in ``g``.
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
                 iepe_excit_current_A=0.0,
                 channel_sensitivities=1.0,
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
            except (AttributeError, TypeError, IndexError):
                # sounddevice not importable, sd.default missing, or
                # no default configured (device is -1 / not indexable).
                self.device_index = 1
        elif (device_driver == 'nidaq') and ((device_index is None) or (device_index == 'None')):
            self.device_index = 0
        elif (device_driver == 'mock') and ((device_index is None) or (device_index == 'None')):
            # `'mock'` is the hardware-free test backend (see
            # `streams.MockRecorder`). No real device to enumerate;
            # just hold a stable index so downstream code that prints
            # or stores `device_index` works.
            self.device_index = 0
        else:
            self.device_index = int(device_index)

       
                
        # set output device index to defaults if not specified
        if (output_device_driver == 'soundcard') and ((output_device_index is None) or  (output_device_index == 'None')):
            try:
                # try to find default output soundcard device
                self.output_device_index = sd.default.device[1]
            except (AttributeError, TypeError, IndexError):
                # sd.default unavailable — fall back to a name-based
                # guess over enumerated devices.
                from . import streams  # lazy import to avoid heavy/circular load at module import
                devices = streams.get_devices_soundcard()
                if devices is not None:
                    output_devices = np.where(['output' in names for names in devices])
                    self.output_device_index = output_devices[0][0]
                else:
                    self.output_device_index = 1
        elif (output_device_driver == 'nidaq') and ((output_device_index is None) or (output_device_index == 'None')):
            self.output_device_index = 0
        elif (output_device_driver == 'mock') and ((output_device_index is None) or (output_device_index == 'None')):
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

        # Per-channel arrays. Scalars broadcast to all channels;
        # sequences must match `channels` exactly. Stored as float
        # numpy arrays so downstream code can multiply / divide
        # element-wise without further coercion.
        self.iepe_excit_current_A = self._broadcast_per_channel(
            iepe_excit_current_A, 'iepe_excit_current_A',
        )
        self.channel_sensitivities = self._broadcast_per_channel(
            channel_sensitivities, 'channel_sensitivities',
        )
        if np.any(self.channel_sensitivities == 0):
            raise ValueError(
                'channel_sensitivities must be non-zero (got {!r}); a '
                'zero sensitivity would imply an infinite calibration '
                'factor. Use 1.0 for "no calibration applied".'
                .format(self.channel_sensitivities.tolist())
            )
        if (self.device_driver != 'nidaq'
                and np.any(self.iepe_excit_current_A > 0)):
            raise ValueError(
                'iepe_excit_current_A > 0 requires device_driver="nidaq"; '
                'soundcard inputs do not have configurable excitation. '
                '(got device_driver={!r}, iepe_excit_current_A={!r})'
                .format(self.device_driver,
                        self.iepe_excit_current_A.tolist())
            )

        ### derived settings
        if (viewed_time is not None) and (viewed_time != 'None'):
            self.viewed_time = float(viewed_time)
            self.num_chunks = int(np.ceil(self.viewed_time*self.fs/self.chunk_size))
        else:
            self.viewed_time = None
        
        if self.chunk_size < 10:
            self.chunk_size = int(10)
            print('Resetting ''chunk_size'' to minimum value of 10')

        # (Previously: try/except-everything around `eval('int' +
        # str(nbits))` to set self.format. The eval always failed —
        # `int16` isn't imported at module scope — and `settings.format`
        # is never read anywhere in the package. Removed as dead code.)

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


    def _broadcast_per_channel(self, value, name):
        '''Coerce ``value`` to a float ndarray of length ``channels``.

        Scalars (int / float / 0-d array) broadcast across all
        channels; a list / tuple / 1-d ndarray must already be the
        right length. Used by `iepe_excit_current_A` and
        `channel_sensitivities` so callers can pass either.
        '''
        arr = np.atleast_1d(np.asarray(value, dtype=float))
        if arr.ndim != 1:
            raise ValueError(
                '{} must be a scalar or 1-D sequence (got shape {})'
                .format(name, arr.shape)
            )
        if arr.size == 1:
            arr = np.full(self.channels, float(arr[0]))
        elif arr.size != self.channels:
            raise ValueError(
                '{} length {} does not match channels={}'
                .format(name, arr.size, self.channels)
            )
        return arr


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
