# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 13:28:39 2018

@author: tb267
"""

import numpy as np

# Heavy / circular imports deferred to the functions that need them:
#   - `streams`     -> MySettings.__init__ fallback (line ~158)
#   - `matplotlib`  -> set_plot_colours
#   - `seaborn`     -> set_plot_colours (optional; only used for
#                      channels > 1, and only if installed — falls back
#                      to a stdlib `colorsys` reimplementation of the
#                      same palette when seaborn is absent, e.g. on a
#                      base install / pyodide)
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
except (ImportError, NotImplementedError, OSError):
    # OSError = package present but the PortAudio C library is
    # missing (default on ubuntu CI runners and some student
    # machines); treat it the same as sounddevice being absent.
    sd = None

class MySettings(object):
    '''
    A container for every acquisition setting used by a recording.

    A single ``MySettings`` instance configures all acquisition entry
    points — `acquisition.log_data`, `acquisition.signal_generator`,
    the `streams` recorders and the Logger GUI. All constructor
    arguments are keyword-only and have defaults, so override only the
    few you need; attributes are plain and may also be set after
    construction (``settings.fs = 12800``). See the Data Acquisition
    user guide for worked end-to-end examples.

    Conventions used throughout:

    - **Everything is in volts.** Acquired data and generated output are
      in volts; engineering-unit scaling is applied at display/fit time
      from ``channel_sensitivities``, never by rescaling the stored data.
    - **Per-channel fields take a scalar or a sequence.**
      ``iepe_excit_current_A`` and ``channel_sensitivities`` accept one
      value (broadcast to all ``channels``) or a list of length
      ``channels``, indexed in captured-column order — on a cDAQ chassis
      that is slot order (see ``input_channels_spec``).
    - **The ``output_*`` fields** configure the generation/AO path and
      default to their input counterparts when left unset.

    Attributes:
        channels (int): Number of input channels (default ``2``). On the
            soundcard backend this is clamped to the device's
            ``max_input_channels`` at ``start_stream`` time (with a
            printed warning) — so the default of 2 becomes 1 on a mono
            mic rather than failing with PortAudio ``-9998``. The NI
            backend instead raises ``ValueError`` if the count exceeds
            the device's available AI channels.
        fs (int): Input sampling frequency in Hz (default ``44100``). On
            a DSA module (NI 9234) the driver coerces this to the nearest
            rate on its discrete divider ladder.
        nbits (int): Sample bit depth — 8, 16, 24 or 32 (default ``16``).
        chunk_size (int): Samples acquired per channel per callback
            (default ``100``; values below 10 are raised to 10). Also the
            upper bound on ``pretrig_samples``.
        num_chunks (int): Chunks held in the oscilloscope circular buffer
            (default ``6``); recomputed from ``viewed_time`` when set.
        viewed_time (float or None): Oscilloscope display window in
            seconds (default ``0.3``). When set, overrides ``num_chunks``
            as ``ceil(viewed_time * fs / chunk_size)``. Set to None to
            size the oscilloscope buffer directly from ``num_chunks``
            instead.
        stored_time (float): Duration of the recorded capture in seconds
            (default ``2``).
        pretrig_samples (int or None): Samples retained before the
            trigger, or ``None`` (default) for untriggered recording.
            Must not exceed ``chunk_size`` (the pretrigger buffer holds
            only one chunk of pre-trigger context).
        pretrig_threshold (float): Trigger level, in the units the chosen
            device delivers — volts on NI, ±1-normalised on the soundcard
            (default ``0.05``).
        pretrig_channel (int): Channel index monitored for the trigger
            (default ``0``).
        pretrig_timeout (float): Seconds to wait for a trigger before
            recording anyway (default ``20``).
        device_driver (str): Input backend — ``'soundcard'`` (default),
            ``'nidaq'`` or ``'mock'`` (the hardware-free test backend).
        device_index (int or None): Index into the enumerated device list
            for the chosen driver; ``None`` picks a default (the system
            default input soundcard, or NI device 0). For a cDAQ chassis
            this indexes the **chassis as a whole**, not a module — list
            candidates with ``dvma.list_available_devices()`` (its nidaq
            section is indexed the same way ``device_index`` is).
        input_channels_spec (str or None): Optional raw DAQmx
            physical-channel string for the AI task, e.g.
            ``'cDAQ1Mod1/ai0:3,cDAQ1Mod3/ai0'``. Overrides the auto-built
            ``'<dev>/ai0:N-1'`` string when set — use it for gappy or
            mixed-module layouts the count-based builder cannot express.
            nidaqmx backend only.
        VmaxNI (float): Full-scale input voltage for the NI AI task
            (default ``5``); ±VmaxNI is passed as min/max to
            ``add_ai_voltage_chan``. Pick the smallest range covering the
            signal for best resolution. Fixed at ±5 V on the 9234 (other
            values are accepted but ignored by the hardware).
        VmaxSC (float): Soundcard input calibration (default ``1.0``) —
            the jack voltage corresponding to a normalised reading of
            1.0. Default ``1.0`` treats normalised samples as volts at
            unit scale (no calibration); set it to your measured input
            sensitivity to calibrate captures in volts.
        NI_mode (str): NI terminal configuration — ``'DAQmx_Val_RSE'``
            (default), ``'DAQmx_Val_NRSE'``, ``'DAQmx_Val_Diff'`` or
            ``'DAQmx_Val_PseudoDiff'``. DSA modules (9234) are
            pseudo-differential only.
        iepe_excit_current_A (float or sequence of float): Per-channel
            IEPE / ICP excitation current in amps (default ``0.0`` = off
            on every channel). Scalar broadcasts; a sequence must be
            length ``channels``. Only NI 9234-class DSA modules support
            it; the legal discrete values on the 9234 are ``0.0`` and
            ``0.002`` (2 mA), validated against the module that actually
            owns each channel. A channel with current ``> 0`` is switched
            to **AC coupling** and the recorder blocks ~2 s after start
            for the sensor bias to settle through the AC-coupling HPF.
            Requires ``device_driver='nidaq'`` (raises ``ValueError``
            otherwise). Never enable it on a channel wired to an AO
            output (e.g. a loopback) — the current drives back into the
            AO terminal.
        channel_sensitivities (float or sequence of float): Per-channel
            sensitivity in volts per engineering unit — V/g for an
            accelerometer, V/N for a force transducer, V/Pa for a
            microphone, etc. (default ``1.0`` = no calibration applied).
            Scalar broadcasts; a sequence must be length ``channels`` and
            every value must be non-zero. ``log_data`` stores the
            reciprocal as ``TimeData.channel_cal_factors``, which
            plotting and modal fitting apply automatically, so a
            ``100 mV/g`` accelerometer (``0.1`` here) gives a cal factor
            of ``10`` and plots read in ``g``. The stored ``time_data``
            array itself stays in volts.
        output_device_driver (str): Backend for the output/AO path;
            defaults to ``device_driver`` (same device as the input).
        output_device_index (int or None): Device index for the output
            path. ``None`` resolves per backend: for ``soundcard`` it
            picks the default *output* soundcard (the input device is
            typically a microphone with no output channels); for
            ``nidaq``/``mock`` it follows ``device_index`` when the
            output driver matches the input driver (the stimulus goes
            out of the same device the input is on), falling back to
            device 0 for cross-driver output.
        output_channels (int): Number of output (AO) channels
            (default ``1``).
        output_channels_spec (str or None): Raw DAQmx physical-channel
            string for the AO task, e.g. ``'cDAQ1Mod2/ao0'``; the output
            analogue of ``input_channels_spec``. nidaqmx backend only.
        output_fs (int): Output sample rate in Hz; defaults to ``fs``.
        output_VmaxNI (float or None): Full-scale output voltage for the
            NI AO task; defaults to ``VmaxNI``. (The NI 9260 is limited to
            ±4.24 V.)
        output_VmaxSC (float or None): Full-scale output voltage for the
            soundcard AO path — the jack voltage corresponding to a ±1
            sounddevice sample; defaults to ``VmaxSC``.
        use_output_as_ch0 (bool): When ``True`` and an ``output`` array
            is passed to ``log_data``, the generated drive signal is
            prepended as channel 0 of the recorded data (default
            ``False``). Useful for transfer-function tests where the
            excitation should be the reference channel; the prepended
            column passes through with a cal factor of 1.
        init_view_time (bool): Show the time-domain oscilloscope view on
            launch (default ``True``).
        init_view_freq (bool): Show the frequency-domain oscilloscope
            view on launch (default ``True``).
        init_view_levels (bool): Show the channel-levels oscilloscope
            view on launch (default ``True``).

    Examples:
        IEPE accelerometers on a cDAQ with per-channel calibration —
        100 mV/g ICP accelerometers on the 9234's ``ai0``/``ai1`` and a
        2.3 mV/N force probe on ``ai2`` (channel index 3 unused):

        >>> settings = dvma.MySettings(
        ...     device_driver='nidaq',
        ...     device_index=0,                  # the cDAQ chassis
        ...     channels=3,
        ...     NI_mode='DAQmx_Val_PseudoDiff',  # required by the 9234
        ...     VmaxNI=5,                        # 9234 fixed at ±5 V
        ...     fs=12800,
        ...     iepe_excit_current_A=[0.002, 0.002, 0.0],  # 2 mA accels only
        ...     channel_sensitivities=[0.1, 0.1, 0.0023],  # V/g, V/g, V/N
        ... )
        >>> dataset = dvma.log_data(settings)

        Scalars broadcast to every channel — four identical IEPE-powered
        100 mV/g accelerometers:

        >>> settings = dvma.MySettings(
        ...     device_driver='nidaq', channels=4,
        ...     iepe_excit_current_A=0.002, channel_sensitivities=0.1,
        ... )

    See Also:
        acquisition.log_data: Run a capture using these settings.
        list_available_devices: Print soundcard + nidaq devices by index.
        suggest_ni_settings: Safe NI ranges/rate/mode for a device.
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
                # guess over enumerated devices. No device name may
                # contain 'output' at all (e.g. input-only Mac setups),
                # so guard the scan before indexing into it.
                from . import streams  # lazy import to avoid heavy/circular load at module import
                devices = streams.get_devices_soundcard()
                output_devices = None
                if devices is not None:
                    matches = np.where(['output' in names for names in devices])[0]
                    if len(matches) > 0:
                        output_devices = int(matches[0])
                self.output_device_index = output_devices if output_devices is not None else 1
        elif (output_device_driver in ('nidaq', 'mock')) and ((output_device_index is None) or (output_device_index == 'None')):
            # "Same device as the input": an unset NI/mock output index
            # follows the resolved input device when the drivers match,
            # so e.g. an input on NI device 2 drives that device's AO —
            # not device 0's. Cross-driver output falls back to device 0.
            # Soundcard is deliberately different (above): its unset
            # output resolves to the default OUTPUT device, because the
            # input is typically a microphone with no output channels.
            if output_device_driver == device_driver:
                self.output_device_index = self.device_index
            else:
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
    '''Pre-set values for the Logger GUI's "Generate output" panel.

    A lightweight holder for the four output-generation fields the
    Logger GUI exposes. Pass an instance to
    ``gui.Logger(..., output_signal_settings=...)`` to pre-fill that
    panel; the GUI then feeds the chosen values to
    `acquisition.signal_generator` when you preview or play the output.
    It is **only** consumed by the GUI — for scripted output, call
    `acquisition.signal_generator` / ``log_data(output=...)`` directly
    (see the Data Acquisition user guide).

    The signal **duration is not stored here** — it is a separate field
    in the GUI panel (and the ``T=`` argument of ``signal_generator``
    when scripting).

    Attributes:
        type (str): Output waveform, matching the panel's drop-down —
            one of ``'None'`` (output off; the default), ``'sweep'`` (a
            linear chirp from ``f1`` to ``f2``), ``'gaussian'``
            (band-limited Gaussian noise) or ``'uniform'`` (band-limited
            uniform noise). Maps to ``signal_generator``'s ``sig``.
        amp (float): Peak amplitude in **volts** (default ``0``). Clamped
            to ±``settings.output_vmax()`` at generation time.
        f1 (float): Lower frequency in Hz (default ``0``). For ``'sweep'``
            the start frequency; for the noise types the lower band-pass
            corner. Passed through as ``f=[f1, f2]``.
        f2 (float): Upper frequency in Hz (default ``0``). For ``'sweep'``
            the end frequency; for noise the upper band-pass corner. The
            GUI rejects ``max(f1, f2) > fs/2`` (Nyquist).

    Examples:
        >>> # band-limited noise, 0.1 V, 100-300 Hz, pre-loaded in the GUI
        >>> oss = dvma.Output_Signal_Settings(type='gaussian',
        ...                                   amp=0.1, f1=100, f2=300)
        >>> logger = dvma.Logger(settings, output_signal_settings=oss)
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

    For a single channel this uses matplotlib's ``tab10`` colormap. For
    multiple channels it uses seaborn's ``hls_palette`` (evenly-spaced
    hues) when seaborn is installed. seaborn is not a declared
    dependency (it was only in the retired ``[qt]`` extra), so on a base
    install (e.g. pyodide) this falls back to a stdlib
    ``colorsys``-based reimplementation of the same palette — see the
    ``except ImportError`` branch below.
    '''
    # Lazy import: matplotlib is only needed here, and pulling it (plus
    # seaborn, when present) out of module top-level keeps `import
    # pydvma` fast for script / CLI users who never touch the GUI or
    # call set_plot_colours.
    import matplotlib.pyplot as plt
    #TODO: Accessible colours
    if channels <= 1:
        cmap = plt.get_cmap('tab10')
#        cmap = sns.color_palette('paired')
        c_list = np.array((np.array(cmap.colors) * 255),dtype=int)
    else:
#        cmap = plt.get_cmap('plasma')
#        v = np.linspace(0,1,channels)
#        c_list = np.array(cmap(v) * 255,dtype=int)
        try:
            import seaborn as sns
            cmap = sns.hls_palette(channels, l=.3, s=1)
        except ImportError:
            # base install (no seaborn, e.g. pyodide): reproduce
            # sns.hls_palette(n, l=.3, s=1) with the stdlib — evenly
            # spaced hues (seaborn offsets them by 0.01) at fixed
            # lightness/saturation.
            import colorsys
            hues = (np.linspace(0, 1, channels, endpoint=False) + 0.01) % 1
            cmap = [colorsys.hls_to_rgb(h, 0.3, 1.0) for h in hues]
        c_list = np.array(np.array(cmap) * 255,dtype=int)
    
#    val = [0.0,0.5,1.0]
#    colour = np.array([[255,0,0,255],[0,255,0,255],[0,0,255,255]], dtype = np.ubyte)
#    plot_colourmap =  pg.ColorMap(val,colour)
#    c_list = plot_colourmap.getLookupTable(nPts =channels,alpha=True)
    return c_list 
