from . import acquisition
from . import _ni_backend

import numpy as np
import pprint as pp
import time

try:
    import sounddevice as sd
except ImportError:
    sd = None
except NotImplementedError:
    sd = None


try:
    import nidaqmx as ni
    from nidaqmx.stream_readers import AnalogMultiChannelReader
except ImportError:
    ni = None
    AnalogMultiChannelReader = None
except NotImplementedError:
    ni = None
    AnalogMultiChannelReader = None


#%% Handles the different cases of starting soundcard/NI streams


REC_SC = None # create global variable for creating only a single NI stream instance. Not needed for pyaudio.
REC_NI = None
REC = None


def _ni_recorder_class(settings):
    if ni is None:
        raise RuntimeError('nidaqmx is not installed; pip install nidaqmx')
    return Recorder_NI_nidaqmx


def start_stream(settings):
    global REC_SC, REC_NI, REC
    if settings.device_driver == 'soundcard':
        REC_SC = Recorder(settings)
        REC_SC.init_stream(settings)
        REC = REC_SC
    elif settings.device_driver == 'nidaq':
        cls = _ni_recorder_class(settings)
        # If an existing REC_NI was created by a different backend, drop it.
        if REC_NI is not None and not isinstance(REC_NI, cls):
            try:
                REC_NI.end_stream()
            except Exception:
                pass
            REC_NI = None
        if REC_NI is None:
            REC_NI = cls(settings)
        else:
            try:
                REC_NI.end_stream()
            except Exception:
                pass
        REC_NI.__init__(settings)
        REC_NI.init_stream(settings)
        REC = REC_NI
        print(REC)
    else:
        raise ValueError('Unknown driver: %r' % settings.device_driver)
        
#%% Find information on available devices
def list_available_devices(io=''):
    # soundcard devices list
    message = '__________________________________________________________\n'
    message += '\n'
    message += 'Devices available using device_driver=''soundcard'', by index:\n'
    message += '__________________________________________________________\n'
    message += '\n'

    device_name_list = get_devices_soundcard()
    if device_name_list is not None:
        N = np.size(device_name_list)
        for i in range(N):
            if io.lower() in device_name_list[i].lower(): # option to only look for input devices
                message += '{}: {}\n'.format(i,device_name_list[i])
    
        try:
            default_input_device = sd.default.device[0]
            message += '\nDefault device is: [%i] %s\n' %(default_input_device,device_name_list[default_input_device])
            message += '\n'
            default_output_device = sd.default.device[1]
            message += 'Default device is: [%i] %s\n' %(default_output_device,device_name_list[default_output_device])
            message += '\n\n'
        except:
            message += 'default information not available\n'
    else:
        message += 'no soundcards found\n'
    
    # NI list (nidaqmx view — cDAQ chassis collapsed into a single entry)
    message += '______________________________________________________\n'
    message += '\n'
    message += "Devices available using device_driver='nidaq', by index:\n"
    message += '______________________________________________________\n'
    message += '\n'
    if ni is None:
        message += 'nidaqmx is not installed\n'
    else:
        entries = _ni_backend.enumerate_devices()
        if not entries:
            message += 'no NI devices found via nidaqmx\n'
        else:
            for i, e in enumerate(entries):
                tag = 'chassis' if e['is_chassis'] else 'device'
                message += '{}: {} ({}, {}) AI={} AO={}'.format(
                    i, e['name'], e['product_type'], tag,
                    e['ai_channel_count'], e['ao_channel_count'],
                )
                if e['is_chassis']:
                    message += ' modules={}'.format(e['module_names'])
                message += '\n'

    print(message)
    return message
    
    
        

def get_devices_NI():
    '''Return (names, types) of every NI device/module visible to nidaqmx.

    Flat list — a cDAQ chassis appears alongside each of its slotted
    modules (e.g. ``['cDAQ1', 'cDAQ1Mod1', 'cDAQ1Mod2']``). For the
    chassis-collapsed view used by `Recorder_NI_nidaqmx` itself, call
    `_ni_backend.enumerate_devices` directly.

    Returns ``(None, None)`` if nidaqmx is not installed or no devices
    are visible, keeping the pre-nidaqmx API shape.
    '''
    if ni is None:
        return None, None
    try:
        system = ni.system.System.local()
        names = [d.name for d in system.devices]
        types = [d.product_type for d in system.devices]
    except Exception:
        return None, None
    if not names:
        return None, None
    return names, types


def get_devices_soundcard():
    try:
        devices = sd.query_devices()
        device_name_list = []
        for device in devices:
            device_name_list.append(device['name'])
    except:
        return None
    
    return device_name_list

# def get_devices_soundcard():
#     try:
#         audio = pyaudio.PyAudio()
#         device_count = audio.get_device_count()
#         device_name_list = []
#         for i in range(device_count):
#             device = audio.get_device_info_by_index(i)
#             device_name_list.append(device['name'])
#     except:
#         return None
    
#     return device_name_list


#%% sounddevice stream
class Recorder(object):
    '''Soundcard acquisition recorder (via `sounddevice`).

    Owns two circular buffers:

    * ``osc_time_data`` — shape ``(num_chunks * chunk_size, channels)``
      — always live; fed the most-recent samples for the oscilloscope.
    * ``stored_time_data`` — shape ``(stored_num_chunks * chunk_size,
      channels)`` where ``stored_num_chunks = 2 + ceil(stored_time * fs
      / chunk_size)`` — the capture buffer used by `log_data`.

    Trigger / pretrigger state machine
    ----------------------------------
    Each incoming chunk (``chunk_size`` samples, ``channels`` wide)
    runs through `callback`:

    1. Shift both buffers left by ``chunk_size`` and append the new
       chunk at the end. When ``pretrig_samples is not None`` and
       ``trigger_detected`` is already True, `stored_time_data` is
       **frozen** — only `osc_time_data` keeps scrolling.
    2. "First-detect" message: if any sample in the just-read chunk
       exceeds ``pretrig_threshold`` on the monitored
       ``pretrig_channel``, print a one-shot notice. Independent of
       whether the trigger has actually been committed yet.
    3. Trigger check: look at ``stored_time_data[chunk_size :
       2*chunk_size, pretrig_channel]`` (the *second-oldest* chunk in
       the buffer — see below). If any sample exceeds
       ``pretrig_threshold``, set ``trigger_detected = True`` and
       freeze the buffer on subsequent callbacks.

    The "check the second-oldest chunk" design means that by the
    time a trigger is detected, the buffer already holds ~``stored_time
    * fs`` samples of *post*-trigger data and up to ``chunk_size``
    samples of *pre*-trigger data. `log_data` uses this to return a
    window straddling the trigger with ``pretrig_samples`` samples of
    context before it — see `pydvma.acquisition.log_data`. The
    ``chunk_size`` ceiling on the pre-trigger context is why
    ``pretrig_samples > chunk_size`` is rejected.

    Data convention
    ---------------
    Both buffers store voltages. sounddevice delivers float32 samples
    in ±1 normalised units; the callback scales by
    ``settings.VmaxSC`` on the way in, so consumers see a calibrated
    reading at the input jack (``VmaxSC`` = the voltage corresponding
    to a normalised 1.0). Default ``VmaxSC=1.0`` means no calibration
    — ±1 normalised is returned as ±1 "V" — which keeps behaviour
    byte-identical to the old convention for anyone who hasn't
    measured their soundcard's sensitivity.
    '''
    def __init__(self,settings):
        self.settings = settings
        self.trigger_detected = False
        self.trigger_first_detected_message = False
        self.osc_time_axis=np.arange(0,(self.settings.num_chunks*self.settings.chunk_size)/self.settings.fs,1/self.settings.fs)
        self.osc_freq_axis=np.fft.rfftfreq(len(self.osc_time_axis),1/self.settings.fs)
        self.osc_time_data=np.zeros(shape=((self.settings.num_chunks*self.settings.chunk_size),self.settings.channels))  
        self.osc_time_data_windowed=np.zeros_like(self.osc_time_data)
        self.osc_freq_data = np.abs(np.fft.rfft(self.osc_time_data,axis=0))

        
        #rounds up the number of chunks needed in the pretrig array    
        self.stored_num_chunks=2+int(np.ceil((self.settings.stored_time*self.settings.fs)/self.settings.chunk_size))
        #the +2 is to allow for the updating process on either side
        self.stored_time_data=np.zeros(shape=(self.stored_num_chunks*self.settings.chunk_size,self.settings.channels))
        self.stored_time_data_windowed=np.zeros_like(self.stored_time_data)
        #note the +2s to match up the length of stored_num_chunks
        #formula used from the np.fft.rfft documentation
        self.stored_freq_data = np.abs(np.fft.rfft(self.stored_time_data,axis=0))
        # self.list_dt = []
    
    def callback(self, in_data, frame_count, time_info, status):
        '''
        Obtains data from the audio stream.

        The sounddevice callback delivers float32 samples in ±1
        normalised units; we scale by ``settings.VmaxSC`` on the way
        in so both `osc_time_data` and `stored_time_data` are in
        volts (where "volts" means "ŷ × VmaxSC", with ŷ the
        normalised sample). VmaxSC defaults to 1.0 so uncalibrated
        soundcards keep identical numeric behaviour to the old ±1
        convention.
        '''
        t0 = time.time()
        # self.osc_data_chunk = (np.frombuffer(in_data, dtype='int'+str(self.settings.nbits))/2**(self.settings.nbits-1))
        self.osc_data_chunk = np.copy(in_data) * self.settings.VmaxSC
        self.osc_data_chunk=np.reshape(self.osc_data_chunk,[self.settings.chunk_size,self.settings.channels])
        for i in range(self.settings.channels):
            self.osc_time_data[:-(self.settings.chunk_size),i] = self.osc_time_data[self.settings.chunk_size:,i]
            self.osc_time_data[-(self.settings.chunk_size):,i] = self.osc_data_chunk[:,i]
            if (not self.trigger_detected)  or (self.settings.pretrig_samples is None):
                self.stored_time_data[:-(self.settings.chunk_size),i] = self.stored_time_data[self.settings.chunk_size:,i]
                self.stored_time_data[-(self.settings.chunk_size):,i] = self.osc_data_chunk[:,i]
        
        trigger_first_detected = np.any(np.abs(self.osc_data_chunk[:,self.settings.pretrig_channel])>self.settings.pretrig_threshold)
        if trigger_first_detected and self.trigger_first_detected_message:
            acquisition.MESSAGE += 'Trigger detected. Logging data for {} seconds.\n'.format(self.settings.stored_time)
            print('')
            print(acquisition.MESSAGE)
            self.trigger_first_detected_message=False
            
            
        trigger_check = self.stored_time_data[(self.settings.chunk_size):(2*self.settings.chunk_size),self.settings.pretrig_channel]
        if np.any(np.abs(trigger_check)>self.settings.pretrig_threshold):
            # freeze updating stored_time_data
            self.trigger_detected = True

        # self.list_dt += [time.time()-t0]

        # return in_data
    
    
    def init_stream(self,settings,_input_=True,_output_=False):
        '''
        Initialises an audio stream. Gives the user a choice of which device to access.
        '''
        
        if settings.device_index is None:
    
            devices = sd.query_devices()
            print('No device specified. Using default:\n\n%i %s'
                  %(sd.default.device[0],devices[sd.default.device[0]]['name']))
            print ('')
            settings.device_index=sd.default.device[0]
            
        settings.device_name = sd.query_devices()[settings.device_index]['name']
        settings.device_full_info = sd.query_devices()[settings.device_index]
        
        dtype = 'float32'
        self.audio_stream = sd.InputStream(samplerate=settings.fs, 
                                      blocksize=settings.chunk_size, 
                                      device=settings.device_index, 
                                      channels=settings.channels, 
                                      dtype=dtype, 
                                      latency='low', 
                                      extra_settings=None, 
                                      callback=self.callback, 
                                      finished_callback=None, 
                                      clip_off=None, 
                                      dither_off=None, 
                                      never_drop_input=None, 
                                      prime_output_buffers_using_stream_callback=None) 
        self.audio_stream.start()
        
        
    
    def end_stream(self):
        '''
        Closes an audio stream.
        '''
        global REC
        REC = None
        if self.audio_stream.active:
            self.audio_stream.stop()
        else: 
            pass
        self.audio_stream.close()

        
        



#%% NI stream (nidaqmx backend)


class Recorder_NI_nidaqmx(object):
    '''NI acquisition recorder using the official nidaqmx Python wrapper.

    Exposes the same public attribute shape the soundcard `Recorder`
    does — `audio_stream`, `osc_time_data`, `stored_time_data`,
    `trigger_detected`, etc. — so `acquisition.py` is driver-agnostic.

    Trigger / pretrigger state machine
    ----------------------------------
    Identical to `Recorder` — see that class's docstring for the full
    description. The only differences in this path are (a) the data
    source (the nidaqmx every-N-samples callback calling
    `read_many_sample` rather than a sounddevice input-stream callback)
    and (b) the sample units: **raw volts** from
    `AnalogMultiChannelReader`, not ±1-normalised float. Thresholds
    (`pretrig_threshold`) are applied with identical code but mean
    different things in the two paths — always specify thresholds in
    the units your chosen device delivers.

    Hardware-specific notes picked up while getting this working:

    * **cDAQ chassis** are addressed via a single entry in the
      enumerated device list. A chassis with an N-channel AI module and
      an M-channel AO module appears as one device with
      ``ai_channel_count=N`` and ``ao_channel_count=M``. Requesting
      ``channels=N`` builds the correct cross-module channel string
      (``cDAQ1Mod1/ai0:N-1``). For mixed / gappy layouts, use the
      ``input_channels_spec`` / ``output_channels_spec`` settings to
      pass a raw physical-channel string.
    * **NI 9234** (and DSA modules generally) are pseudo-differential
      only; set ``NI_mode='DAQmx_Val_PseudoDiff'``. Voltage range is
      fixed at ±5 V; any other ``VmaxNI`` will be accepted silently
      by the driver.
    * **NI 9260** AO is ±4.24 V peak (= 3 V_rms). Setting
      ``output_VmaxNI=10`` triggers DAQmx error -200077.
    * **USB-600x low-cost devices** have software-timed AO: AI/AO
      cannot share a hardware sample clock; the output path falls back
      to an independent (unsynchronised) task.
    * **Data is read in volts** directly via `AnalogMultiChannelReader`,
      not as a normalised float — no ±1 scaling is applied. This
      differs from the soundcard path, which returns ±1-normalised
      float32.
    '''

    def __init__(self, settings):
        self.settings = settings
        self.trigger_detected = False
        self.trigger_first_detected_message = False

        self.osc_time_axis = np.arange(
            0,
            (settings.num_chunks * settings.chunk_size) / settings.fs,
            1 / settings.fs,
        )
        self.osc_freq_axis = np.fft.rfftfreq(len(self.osc_time_axis), 1 / settings.fs)
        self.osc_time_data = np.zeros(
            shape=(settings.num_chunks * settings.chunk_size, settings.channels)
        )
        self.osc_time_data_windowed = np.zeros_like(self.osc_time_data)
        self.osc_freq_data = np.abs(np.fft.rfft(self.osc_time_data, axis=0))

        self.stored_num_chunks = 2 + int(
            np.ceil((settings.stored_time * settings.fs) / settings.chunk_size)
        )
        self.stored_time_data = np.zeros(
            shape=(self.stored_num_chunks * settings.chunk_size, settings.channels)
        )
        self.stored_time_data_windowed = np.zeros_like(self.stored_time_data)
        self.stored_freq_data = np.abs(np.fft.rfft(self.stored_time_data, axis=0))

        entries = _ni_backend.enumerate_devices()
        if not entries:
            raise RuntimeError('No NI devices found via nidaqmx')
        idx = settings.device_index if settings.device_index is not None else 0
        if idx >= len(entries):
            raise ValueError(
                'device_index %r out of range; nidaqmx sees %d device(s)'
                % (settings.device_index, len(entries))
            )
        self.device_entry = entries[idx]
        self.device_name = self.device_entry['name']

        if settings.channels > self.device_entry['ai_channel_count'] and not settings.input_channels_spec:
            raise ValueError(
                'Requested %d AI channels but %r has only %d available'
                % (settings.channels, self.device_name, self.device_entry['ai_channel_count'])
            )

        # Preserve hardware-level state across re-__init__ calls:
        # acquisition.py re-invokes __init__ to zero the numpy buffers
        # before a pretrigger wait, but the NI task is still running and
        # its callback expects the reader to still exist. Only set these
        # on first construction.
        if not hasattr(self, 'audio_stream'):
            self.audio_stream = None
            self._reader = None
            self._read_buffer = None
            self._callback_ref = None  # keep a strong reference for nidaqmx

    def available_devices(self):
        entries = _ni_backend.enumerate_devices()
        return ([e['name'] for e in entries], [e['product_type'] for e in entries])

    def current_device_info(self):
        pp.pprint(self.device_entry)

    def set_channels(self):
        return _ni_backend.build_ai_channel_string(
            self.device_entry,
            self.settings.channels,
            self.settings.input_channels_spec,
        )

    def set_output_channels(self):
        return _ni_backend.build_ao_channel_string(
            self.device_entry,
            self.settings.output_channels,
            self.settings.output_channels_spec,
        )

    def stream_audio_callback(self):
        try:
            self._reader.read_many_sample(
                self._read_buffer,
                number_of_samples_per_channel=self.settings.chunk_size,
                timeout=10.0,
            )
        except Exception as e:
            print('nidaqmx read error:', e)
            return 0

        # Reader fills shape (channels, chunk_size); downstream wants
        # (chunk_size, channels) to match the soundcard path.
        data_array = self._read_buffer.T
        self.osc_data_chunk = data_array

        for i in range(self.settings.channels):
            self.osc_time_data[:-(self.settings.chunk_size), i] = self.osc_time_data[self.settings.chunk_size:, i]
            self.osc_time_data[-(self.settings.chunk_size):, i] = self.osc_data_chunk[:, i]
            if (not self.trigger_detected) or (self.settings.pretrig_samples is None):
                self.stored_time_data[:-(self.settings.chunk_size), i] = self.stored_time_data[self.settings.chunk_size:, i]
                self.stored_time_data[-(self.settings.chunk_size):, i] = self.osc_data_chunk[:, i]

        trigger_first_detected = np.any(
            np.abs(self.osc_data_chunk[:, self.settings.pretrig_channel])
            > self.settings.pretrig_threshold
        )
        if trigger_first_detected and self.trigger_first_detected_message:
            acquisition.MESSAGE += 'Trigger detected. Logging data for {} seconds.\n'.format(
                self.settings.stored_time
            )
            print('')
            print(acquisition.MESSAGE)
            self.trigger_first_detected_message = False

        trigger_check = self.stored_time_data[
            self.settings.chunk_size:(2 * self.settings.chunk_size),
            self.settings.pretrig_channel,
        ]
        if np.any(np.abs(trigger_check) > self.settings.pretrig_threshold):
            self.trigger_detected = True
        return 0

    def init_stream(self, settings, _input_=True, _output_=False):
        # Tear down any previous task on this recorder
        if self.audio_stream is not None:
            try:
                self.audio_stream.stop()
            except Exception:
                pass
            try:
                self.audio_stream.close()
            except Exception:
                pass
            self.audio_stream = None

        try:
            self._build_and_start_ai_task(settings)
        except ni.errors.DaqError as e:
            # -50103 "The specified resource is reserved" usually means a
            # prior Python process leaked the task (notebook kernel crash,
            # Ctrl-C, etc.) and Windows is still holding the reservation.
            # Reset the device once to clear it and retry; surface any
            # other DAQmx error unchanged.
            if e.error_code != -50103:
                raise
            if self.audio_stream is not None:
                try:
                    self.audio_stream.close()
                except Exception:
                    pass
                self.audio_stream = None
            try:
                ni.system.Device(self.device_name).reset_device()
            except Exception:
                pass
            self._build_and_start_ai_task(settings)

    def _build_and_start_ai_task(self, settings):
        # AutoRegN must divide evenly into chunk_size; pick the largest
        # of {10, 100, 1000} that fits.
        AutoRegN_choices = np.array([10, 100, 1000], dtype=int)
        check = np.where(AutoRegN_choices <= settings.chunk_size)
        AutoRegN = int(AutoRegN_choices[check[0][-1]])

        term_config = _ni_backend.resolve_terminal_config(settings.NI_mode)
        task = ni.Task()
        task.ai_channels.add_ai_voltage_chan(
            self.set_channels(),
            terminal_config=term_config,
            min_val=-float(settings.VmaxNI),
            max_val=+float(settings.VmaxNI),
        )
        task.timing.cfg_samp_clk_timing(
            rate=float(settings.fs),
            sample_mode=ni.constants.AcquisitionType.CONTINUOUS,
            samps_per_chan=int(settings.chunk_size),
        )

        self._read_buffer = np.zeros(
            (settings.channels, settings.chunk_size), dtype=np.float64
        )
        self._reader = AnalogMultiChannelReader(task.in_stream)

        def _cb(task_handle, event_type, number_of_samples, callback_data):
            try:
                return self.stream_audio_callback()
            except Exception as e:
                print('stream_audio_callback error:', e)
                return 0

        self._callback_ref = _cb
        task.register_every_n_samples_acquired_into_buffer_event(AutoRegN, _cb)

        # Assign before start so the retry path in ``init_stream`` can
        # find the task to close if ``task.start()`` raises -50103.
        self.audio_stream = task
        task.start()

    def setup_output(self, settings, output):
        # Delegate to the module-level helper so both call paths share the
        # same (validated) implementation.
        return setup_output_NI_nidaqmx(settings, output)

    def end_stream(self):
        global REC
        REC = None
        if self.audio_stream is not None:
            try:
                self.audio_stream.stop()
            except Exception:
                pass
            try:
                self.audio_stream.close()
            except Exception:
                pass
            self.audio_stream = None
        self._reader = None
        self._read_buffer = None
        self._callback_ref = None


# Backwards-compatibility alias: the public API has always exposed
# `Recorder_NI`, and external notebooks/scripts may still import it
# by that name. Kept pointing at the (now sole) nidaqmx recorder.
Recorder_NI = Recorder_NI_nidaqmx


#%% NI output

def setup_output_NI(settings, output):
    '''Build and stage (but not start) an NI AO task.

    Thin wrapper that defers to `setup_output_NI_nidaqmx` — the
    nidaqmx backend is now the only NI path.
    '''
    if ni is None:
        raise RuntimeError('nidaqmx is not installed; pip install nidaqmx')
    return setup_output_NI_nidaqmx(settings, output)


class _NidaqmxTaskAdapter(object):
    '''Expose the PascalCase methods acquisition.py calls on the NI
    output stream (StartTask, StopTask, WaitUntilTaskDone). Any other
    attribute access falls through to the underlying nidaqmx.Task.
    '''
    def __init__(self, task):
        self._task = task

    def StartTask(self):
        self._task.start()

    def StopTask(self):
        try:
            self._task.stop()
        except Exception:
            pass
        try:
            self._task.close()
        except Exception:
            pass

    def WaitUntilTaskDone(self, timeout):
        self._task.wait_until_done(timeout=float(timeout))

    def ClearTask(self):
        try:
            self._task.close()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._task, name)


def setup_output_NI_nidaqmx(settings, output):
    '''Build and stage (but not start) a finite-sample AO task on nidaqmx.

    Parameters
    ----------
    settings : MySettings
        Must have ``output_device_driver='nidaq'``. ``output`` is
        expected in **volts**; the AO task is configured with ranges
        ±``output_VmaxNI`` so any sample outside that range will be
        rejected by DAQmx (error -200077).
    output : ndarray, shape (N_samples, output_channels)
        Playback waveform, in volts. Must stay within ±``output_VmaxNI``
        (e.g. NI 9260 is ±4.24 V peak regardless of the requested
        range).

    Returns
    -------
    _NidaqmxTaskAdapter
        Wrapper exposing ``StartTask`` / ``StopTask`` /
        ``WaitUntilTaskDone`` so `acquisition.py` can call the same
        methods regardless of whether the source is an NI or soundcard
        stream.

    Notes on AI/AO hardware sync
    ----------------------------
    When the AI recorder is a `Recorder_NI_nidaqmx` on the **same
    device or chassis** and that hardware supports hardware-timed AO
    (see `_ni_backend.supports_hw_ao_sync`), the AO task routes the
    AI sample clock as its source — the resulting AO samples step on
    exactly the AI tick. This works on M/X-series USB (e.g.
    USB-6212). It is **not** used for cDAQ chassis: per-module AI
    sample clocks are not routable as AO sources there; AI and AO
    instead share the chassis 80 MHz timebase implicitly, which is
    phase-coherent but not sample-accurate across tasks. USB-600x
    low-cost devices have software-timed AO and always run
    unsynchronised.
    '''
    # `output` is already in volts; no pre-scaling needed.
    output = np.asarray(output)
    output_shape = np.shape(output)
    N_output = output_shape[0]
    N_channel_check = output_shape[1]
    if N_channel_check != settings.output_channels:
        print("output matrix doesn't match number of output channels")

    entries = _ni_backend.enumerate_devices()
    if not entries:
        raise RuntimeError('No NI devices found via nidaqmx')
    if settings.output_device_index is None or settings.output_device_index >= len(entries):
        raise ValueError(
            'output_device_index %r out of range; nidaqmx sees %d device(s)'
            % (settings.output_device_index, len(entries))
        )
    device_entry = entries[settings.output_device_index]
    channel_string = _ni_backend.build_ao_channel_string(
        device_entry, settings.output_channels, settings.output_channels_spec,
    )

    task = ni.Task()
    task.ao_channels.add_ao_voltage_chan(
        channel_string,
        min_val=-float(settings.output_VmaxNI),
        max_val=+float(settings.output_VmaxNI),
    )

    # Share the AI sample clock when possible: both input and output are NI,
    # the AI recorder is on the same device/chassis, and hardware-timed AO
    # is supported. Falls back to the device's own timebase otherwise.
    clock_source = ''
    if (settings.device_driver == 'nidaq'
            and _ni_backend.supports_hw_ao_sync(device_entry)
            and isinstance(REC_NI, Recorder_NI_nidaqmx)
            and REC_NI.device_entry is not None
            and REC_NI.device_entry['name'] == device_entry['name']):
        clock_source = _ni_backend.ai_sample_clock_source(device_entry) or ''

    task.timing.cfg_samp_clk_timing(
        rate=float(settings.output_fs),
        source=clock_source,
        sample_mode=ni.constants.AcquisitionType.FINITE,
        samps_per_chan=int(N_output),
    )

    # nidaqmx write: shape is (n_channels, n_samples) for multi-channel,
    # or 1D for single channel. `output` here is (N_output, n_channels).
    data = np.asarray(output, dtype=np.float64).T
    if settings.output_channels == 1:
        data = data[0]
    task.write(data, auto_start=False)

    return _NidaqmxTaskAdapter(task)

def setup_output_soundcard(settings):
    dtype = 'float32'

    output_stream = sd.OutputStream(samplerate=settings.output_fs, 
                                  blocksize=settings.chunk_size, 
                                  device=settings.output_device_index, 
                                  channels=settings.output_channels, 
                                  dtype=dtype, 
                                  latency=None, 
                                  extra_settings=None, 
                                  callback=None, 
                                  finished_callback=None, 
                                  clip_off=None, 
                                  dither_off=None, 
                                  never_drop_input=None, 
                                  prime_output_buffers_using_stream_callback=None) 
    output_stream.start()
    return output_stream