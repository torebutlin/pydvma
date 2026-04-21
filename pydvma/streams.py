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
    import PyDAQmx as pdaq
    from PyDAQmx import Task
except ImportError:
    pdaq = None
except NotImplementedError:
    pdaq = None


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
    backend = getattr(settings, 'ni_backend', 'pydaqmx')
    if backend == 'pydaqmx':
        if pdaq is None:
            raise RuntimeError("ni_backend='pydaqmx' selected but PyDAQmx is not installed")
        return Recorder_NI_PyDAQmx
    if backend == 'nidaqmx':
        if ni is None:
            raise RuntimeError("ni_backend='nidaqmx' selected but nidaqmx is not installed")
        return Recorder_NI_nidaqmx
    raise ValueError('Unknown ni_backend: %r' % (backend,))


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
    
    # NI list (PyDAQmx view — flat, one entry per Dev/Module)
    message += '______________________________________________________\n'
    message += '\n'
    message += "Devices available using device_driver='nidaq', ni_backend='pydaqmx', by index:\n"
    message += '______________________________________________________\n'
    message += '\n'

    device_name_list,device_type_list = get_devices_NI()
    if device_name_list is not None:
        N = np.size(device_name_list)
        for i in range(N):
            message += '{}: {} {}\n'.format(i,device_name_list[i],device_type_list[i])
    else:
        message += 'no NI devices found via PyDAQmx\n'

    # NI list (nidaqmx view — cDAQ chassis collapsed into a single entry)
    message += '\n______________________________________________________\n'
    message += '\n'
    message += "Devices available using device_driver='nidaq', ni_backend='nidaqmx', by index:\n"
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
    # NI list
    try:
        numBytesneeded = pdaq.DAQmxGetSysDevNames(None,0)
        databuffer = pdaq.create_string_buffer(numBytesneeded)
        pdaq.DAQmxGetSysDevNames(databuffer,numBytesneeded)
    
        device_name_list = pdaq.string_at(databuffer).decode('utf-8').split(',')
        device_type_list = []
        
        counter = -1
        for dev in device_name_list:
            counter += 1
            numBytesneeded = pdaq.DAQmxGetDevProductType(dev,None,0)
            databuffer = pdaq.create_string_buffer(numBytesneeded)
            pdaq.DAQmxGetDevProductType(dev,databuffer,numBytesneeded)
            device_type_list.append(pdaq.string_at(databuffer).decode('utf-8'))
    except:
        return None,None
        
    return device_name_list,device_type_list


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
        '''
        t0 = time.time()
        # self.osc_data_chunk = (np.frombuffer(in_data, dtype='int'+str(self.settings.nbits))/2**(self.settings.nbits-1))
        self.osc_data_chunk = np.copy(in_data)
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

        
        



#%% NI stream (PyDAQmx backend)


class Recorder_NI_PyDAQmx(object):
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
            
         
        devices = self.available_devices()[0]
        if settings.device_index is None:
            self.device_name = devices[0]
        else:
            self.device_name = devices[settings.device_index]
        #self.set_device_by_name(self.device_name)
        
    def set_device_by_name(self, name, settings):
        """
         Set the recording audio device by name.
         Uses the first device found if no such device found.
        """
        devices = self.available_devices()[0]
        selected_device = None
        if not devices:
            print('No NI devices found')
            return

        if not name in devices:
            print('Input device name not found, using the first device')
            selected_device = devices[settings.device_index]
        else:
            selected_device = name

        print('Selected devices: %s' % selected_device)
        self.device_name = selected_device

     # Get audio device names
    def available_devices(self):
        """
        Get all the available input National Instrument devices.

        Returns
        ----------
        devices_name: List of str
            Name of the device, e.g. Dev0
        device_type: List of str
            Type of device, e.g. USB-6003
        """
        numBytesneeded = pdaq.DAQmxGetSysDevNames(None,0)
        databuffer = pdaq.create_string_buffer(numBytesneeded)
        pdaq.DAQmxGetSysDevNames(databuffer,numBytesneeded)

        #device_list = []
        devices_name = pdaq.string_at(databuffer).decode('utf-8').split(',')

        device_type = []
        for dev in devices_name:
            numBytesneeded = pdaq.DAQmxGetDevProductType(dev,None,0)
            databuffer = pdaq.create_string_buffer(numBytesneeded)
            pdaq.DAQmxGetDevProductType(dev,databuffer,numBytesneeded)
            device_type.append(pdaq.string_at(databuffer).decode('utf-8'))

        #device_list.append(devices_name)
        #device_list.append(device_type)

        return(devices_name,device_type)

    # Display the current selected device info
    def current_device_info(self):
        """
        Prints information about the current device set
        """
        device_info = {}
        info = ('Category', 'Type','Product', 'Number',
                'Analog Trigger Support','Analog Input Trigger Types','Analog Input Channels (ai)', 'Analog Output Channels (ao)',
                'ai Minimum Rate(Hz)', 'ai Maximum Rate(Single)(Hz)', 'ai Maximum Rate(Multi)(Hz)',
                'Digital Trigger Support','Digital Input Trigger Types','Digital Ports', 'Digital Lines', 'Terminals')
        funcs = (pdaq.DAQmxGetDevProductCategory, pdaq.DAQmxGetDevProductType,
                 pdaq.DAQmxGetDevProductNum, pdaq.DAQmxGetDevSerialNum,
                 pdaq.DAQmxGetDevAnlgTrigSupported,  pdaq.DAQmxGetDevAITrigUsage,
                 pdaq.DAQmxGetDevAIPhysicalChans,pdaq.DAQmxGetDevAOPhysicalChans,
                 pdaq.DAQmxGetDevAIMinRate, pdaq.DAQmxGetDevAIMaxSingleChanRate, pdaq.DAQmxGetDevAIMaxMultiChanRate,
                 pdaq.DAQmxGetDevDigTrigSupported,pdaq.DAQmxGetDevDITrigUsage,
                 pdaq.DAQmxGetDevDIPorts,pdaq.DAQmxGetDevDILines,
                 pdaq.DAQmxGetDevTerminals)
        var_types = (pdaq.int32, str, pdaq.uint32, pdaq.uint32,
                     pdaq.bool32,pdaq.int32,str,str,
                     pdaq.float64, pdaq.float64, pdaq.float64,
                     pdaq.bool32,pdaq.int32,str,str,str)

        for i,f,v in zip(info,funcs,var_types):
            try:
                if v == str:
                    nBytes = f(self.device_name,None,0)
                    string_ptr = pdaq.create_string_buffer(nBytes)
                    f(self.device_name,string_ptr,nBytes)
                    if any( x in i for x in ('Channels','Ports')):
                        device_info[i] = len(string_ptr.value.decode().split(','))
                    else:
                        device_info[i] = string_ptr.value.decode()
                else:
                    data = v()
                    f(self.device_name,data)
                    if 'Types' in i:
                        device_info[i] = bin(data.value)[2:].zfill(6)
                    else:
                        device_info[i] = data.value
            except Exception as e:
                print(e)
                device_info[i] = '-'

        pp.pprint(device_info)
            
    def stream_audio_callback(self):
        '''
        Obtains data from the audio stream.
        '''
        in_data = np.zeros(self.settings.chunk_size*self.settings.channels,dtype = 'int16')
        read = pdaq.int32()
        self.audio_stream.ReadBinaryI16(self.settings.chunk_size,10.0,pdaq.DAQmx_Val_GroupByScanNumber,
                           in_data,self.settings.chunk_size*self.settings.channels,pdaq.byref(read),None)

        data_array = in_data.reshape((-1,self.settings.channels))/(2**15)
            
        self.osc_data_chunk = data_array#(np.frombuffer(in_data, dtype=eval('int'+str(self.settings.nbits)))/2**(self.settings.nbits-1))
        #self.osc_data_chunk=np.reshape(self.osc_data_chunk,[self.settings.chunk_size,self.settings.channels])
        for i in range(self.settings.channels):
            self.osc_time_data[:-(self.settings.chunk_size),i] = self.osc_time_data[self.settings.chunk_size:,i]
            self.osc_time_data[-(self.settings.chunk_size):,i] = self.osc_data_chunk[:,i]
            if (not self.trigger_detected) or (self.settings.pretrig_samples is None):
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
#        for i in range(self.settings.channels):
#            self.osc_time_data[:-(self.settings.chunk_size),i] = self.osc_time_data[self.settings.chunk_size:,i]
#            self.osc_time_data[-(self.settings.chunk_size):,i] = self.osc_data_chunk[:,i]
#            self.stored_time_data[:-(self.settings.chunk_size),i] = self.stored_time_data[self.settings.chunk_size:,i]
#            self.stored_time_data[-(self.settings.chunk_size):,i] = self.osc_data_chunk[:,i]
        return 0
    

    def set_channels(self):
        """
        Create the string to initiate the channels when assigning a Task

        Returns
        ----------
        channelname: str
            The channel names to be used when assigning Task
            e.g. Dev0/ai0:Dev0/ai1
        """
        if self.settings.channels >1:
            channelname =  '%s/ai0:%s/ai%i' % (self.device_name, self.device_name,self.settings.channels-1)
        elif self.settings.channels == 1:
            channelname = '%s/ai0' % self.device_name

        #print('Channels Name: %s' % channelname)
        return channelname
    
    
    def set_output_channels(self):
        """
        Create the string to initiate the output channels when assigning a Task

        Returns
        ----------
        channelname: str
            The channel names to be used when assigning Task
            e.g. Dev0/ao0:Dev0/ao1
        """
        if self.settings.output_channels >1:
            channelname =  '%s/ao0:%s/ao%i' % (self.device_name, self.device_name,self.settings.output_channels-1)
        elif self.settings.output_channels == 1:
            channelname = '%s/ao0' % self.device_name

        #print('Channels Name: %s' % channelname)
        return channelname
    

    
    def init_stream(self,settings,_input_=True,_output_=False):
        '''
        Initialises an audio stream. Gives the user a choice of which device to access.
        '''
        
    
        try:
            self.audio_stream.end_stream()
        except:
            pass
        
        # Make AutoRegN be one of set of possible numbers that works with nidaqmx
        AutoRegN = np.array([10,100,1000],dtype=int)
        check = np.where(AutoRegN <= settings.chunk_size)
        AutoRegN = AutoRegN[check[0][-1]]
        
        if settings.NI_mode == 'DAQmx_Val_RSE':
            pdaq_mode = pdaq.DAQmx_Val_RSE
        elif settings.NI_mode == 'DAQmx_Val_PseudoDiff':
            pdaq_mode = pdaq.DAQmx_Val_PseudoDiff
        
        self.audio_stream = Task()
        self.audio_stream.stream_audio_callback = self.stream_audio_callback
        self.audio_stream.CreateAIVoltageChan(self.set_channels(),"",
                                 pdaq_mode,-settings.VmaxNI,settings.VmaxNI,
                                 pdaq.DAQmx_Val_Volts,None)
        self.audio_stream.CfgSampClkTiming("",self.settings.fs,
                              pdaq.DAQmx_Val_Rising,pdaq.DAQmx_Val_ContSamps,
                              self.settings.chunk_size)
        self.audio_stream.AutoRegisterEveryNSamplesEvent(pdaq.DAQmx_Val_Acquired_Into_Buffer,
                                            AutoRegN,0,name = 'stream_audio_callback')
        self.audio_stream.StopTask()
        self.audio_stream.SetReadAutoStart(True)
        self.audio_stream.StartTask()


    def setup_output(self,settings,output):

#        output_channel_name = '%s/ao0' % self.device_name
        
        output_shape = np.shape(output)
        N_output = output_shape[0]
        N_channel_check = output_shape[1]
        if N_channel_check != settings.output_channels:
            print('output matrix doesn''t match number of output channels')
            
            
        self.output_stream = Task()
        print(self.set_output_channels())
        self.output_stream.CreateAOVoltageChan(self.set_output_channels(),"",-settings.output_VmaxNI,settings.output_VmaxNI,pdaq.DAQmx_Val_Volts,None)
        self.output_stream.CfgSampClkTiming("",settings.output_fs,
                              pdaq.DAQmx_Val_Rising,pdaq.DAQmx_Val_FiniteSamps,
                              N_output)
        
#        self.output_stream.StartTask()
        
        timeout = 5
        self.output_stream.WriteAnalogF64(N_output, True, timeout, pdaq.DAQmx_Val_GroupByScanNumber,output,None,None)
        
        ### Attempt below to link to input stream. Problem trying to sync initiation of input and output tasks.
        
#        if settings.fs == settings.output_fs:
#            N_input = N_output
#        else:
#            N_input = int(N_output * settings.fs / settings.output_fs)
#        
#        self.input_stream = Task()
#        self.input_stream.CreateAIVoltageChan(self.set_channels(),"",
#                                 pdaq.DAQmx_Val_RSE,-settings.VmaxNI,settings.VmaxNI,
#                                 pdaq.DAQmx_Val_Volts,None)
#        self.input_stream.CfgSampClkTiming("",self.settings.fs,
#                              pdaq.DAQmx_Val_Rising,pdaq.DAQmx_Val_FiniteSamps,
#                              N_input)
#        self.input_stream.CfgTimeStartTrig(1,pdaq.DAQmx_Val_HostTime)
        
        
        
        
#        self.output_stream.StopTask()
             
        ### NEED TO SYNC IN/OUT CLOCKS FOR EACH TASK
        ### pdaq.DAQmxCfgSampClkTiming(taskHandle_input,"ao/SampleClock",fs,daq.DAQmx_Val_Falling,daq.DAQmx_Val_ContSamps,block)
        ### pdaq.CfgDigEdgeRefTrig(...)
        
        ###
        
        
        
#        return (audio_stream,audio)
        
    
    def end_stream(self):
        '''
        Closes an audio stream.
        '''
        global REC
        REC = None
        if self.audio_stream is not None:
            self.audio_stream.StopTask()
            self.audio_stream.ClearTask()
            self.audio_stream = None


# Backwards-compatibility alias: public API has always been `Recorder_NI`.
Recorder_NI = Recorder_NI_PyDAQmx


#%% NI stream (nidaqmx backend)


class Recorder_NI_nidaqmx(object):
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
        # (chunk_size, channels) to match the PyDAQmx path.
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

        # AutoRegN must divide evenly into chunk_size; pick the largest
        # of {10, 100, 1000} that fits. Matches the PyDAQmx sibling.
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


#%% NI output

def setup_output_NI(settings, output):
    '''Dispatch to the NI output setup for the selected backend.'''
    backend = getattr(settings, 'ni_backend', 'pydaqmx')
    if backend == 'nidaqmx':
        if ni is None:
            raise RuntimeError("ni_backend='nidaqmx' selected but nidaqmx is not installed")
        return setup_output_NI_nidaqmx(settings, output)
    if backend == 'pydaqmx':
        if pdaq is None:
            raise RuntimeError("ni_backend='pydaqmx' selected but PyDAQmx is not installed")
        return setup_output_NI_pydaqmx(settings, output)
    raise ValueError('Unknown ni_backend: %r' % (backend,))


def setup_output_NI_pydaqmx(settings,output):
    output = settings.VmaxNI * output # ie. output was normalised to 0-1
    output_shape = np.shape(output)
    N_output = output_shape[0]
    N_channel_check = output_shape[1]
    if N_channel_check != settings.output_channels:
        print('output matrix doesn''t match number of output channels')

    device_name_list,device_type_list = get_devices_NI()
    device_name = device_name_list[settings.output_device_index]

    if settings.output_channels > 1:
        channelname =  '%s/ao0:%s/ao%i' % (device_name, device_name,settings.output_channels-1)
    elif settings.output_channels == 1:
        channelname = '%s/ao0' % device_name

    output_stream = Task()

    output_stream.CreateAOVoltageChan(channelname,"",-settings.VmaxNI,settings.VmaxNI,pdaq.DAQmx_Val_Volts,None)
    output_stream.CfgSampClkTiming("",settings.output_fs,
                          pdaq.DAQmx_Val_Rising,pdaq.DAQmx_Val_FiniteSamps,
                          N_output)

#        self.output_stream.StartTask()

    timeout = 5
    output_stream.WriteAnalogF64(N_output, False, timeout, pdaq.DAQmx_Val_GroupByScanNumber,output,None,None)

    return output_stream


class _NidaqmxTaskAdapter(object):
    '''Expose the PyDAQmx-style PascalCase methods acquisition.py calls on
    the NI output stream (StartTask, StopTask, WaitUntilTaskDone). Any other
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
    '''Build and stage (but do not start) a finite-sample AO task on nidaqmx.

    Returns a task adapter with PyDAQmx-style methods so the caller in
    `acquisition.py` can stay backend-agnostic.
    '''
    output = settings.output_VmaxNI * output  # output is normalised 0..1
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