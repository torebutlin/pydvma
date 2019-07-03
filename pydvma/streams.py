

import numpy as np
import pprint as pp

try:
    import pyaudio
except ImportError:
    pyaudio = None
except NotImplementedError:
    pyaudio = None
    
try:
    import PyDAQmx as pdaq
    from PyDAQmx import Task
except ImportError:
    pdaq = None
except NotImplementedError:
    pdaq = None

#%% Handles the different cases of starting soundcard/NI streams


REC_SC = None # create global variable for creating only a single NI stream instance. Not needed for pyaudio.
REC_NI = None
REC = None

def start_stream(settings):
    global REC_SC, REC_NI, REC
    if settings.device_driver == 'soundcard':
        REC_SC = Recorder(settings)
        REC_SC.init_stream(settings)
        REC = REC_SC
    elif settings.device_driver == 'nidaq':
        
        if REC_NI is None:
            REC_NI = Recorder_NI(settings)
        else:
            try:
                REC_NI.end_stream()
            except:
                pass
        REC_NI.__init__(settings)
        REC_NI.init_stream(settings)
        REC = REC_NI
        print(REC)
    else:
        raise ValueError('Unknown driver: %r' % settings.device_driver)
        


#%% pyaudio stream
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
            
            
    def __call__(self, in_data, frame_count, time_info, status):
        '''
        Obtains data from the audio stream.
        '''
        self.osc_data_chunk = (np.frombuffer(in_data, dtype=eval('np.int'+str(self.settings.nbits)))/2**(self.settings.nbits-1))
        self.osc_data_chunk=np.reshape(self.osc_data_chunk,[self.settings.chunk_size,self.settings.channels])
        for i in range(self.settings.channels):
            self.osc_time_data[:-(self.settings.chunk_size),i] = self.osc_time_data[self.settings.chunk_size:,i]
            self.osc_time_data[-(self.settings.chunk_size):,i] = self.osc_data_chunk[:,i]
            if (not self.trigger_detected)  or (self.settings.pretrig_samples is None):
                self.stored_time_data[:-(self.settings.chunk_size),i] = self.stored_time_data[self.settings.chunk_size:,i]
                self.stored_time_data[-(self.settings.chunk_size):,i] = self.osc_data_chunk[:,i]
        
        trigger_first_detected = np.any(np.abs(self.osc_data_chunk[:,self.settings.pretrig_channel])>self.settings.pretrig_threshold)
        if trigger_first_detected and self.trigger_first_detected_message:
            print('')
            print('Trigger detected. Logging data for {} seconds'.format(self.settings.stored_time))
            self.trigger_first_detected_message=False
            
            
        trigger_check = self.stored_time_data[(self.settings.chunk_size):(2*self.settings.chunk_size),self.settings.pretrig_channel]
        if np.any(np.abs(trigger_check)>self.settings.pretrig_threshold):
            # freeze updating stored_time_data
            self.trigger_detected = True
                
        return (in_data, pyaudio.paContinue)
    
    
    def init_stream(self,settings,_input_=True,_output_=False):
        '''
        Initialises an audio stream. Gives the user a choice of which device to access.
        '''
        
        self.audio = pyaudio.PyAudio()
        
        if settings.device_index == None:
    
            device_count = self.audio.get_device_count()
            print ('Number of devices available is: %i' %device_count)
            print ('')
            print('Devices available, by index:')
            print ('')
            for i in range(device_count):
                device = self.audio.get_device_info_by_index(i)
                print(device['index'], device['name'])
            print ('')
            default_device = self.audio.get_default_input_device_info()
            print('Default device is: %i %s'
                  %(default_device['index'],default_device['name']))
            print ('')
            settings.device_index=int(input('Insert index of required device:'))
            
        settings.device_name = self.audio.get_device_info_by_index(settings.device_index)['name']
        settings.device_full_info = self.audio.get_device_info_by_index(settings.device_index)
        
        print(settings.device_full_info['index'], settings.device_full_info['name'])
        print("Selected device: %i : %s" %(settings.device_index,settings.device_name))    
        
        self.audio_stream = self.audio.open(format=settings.format,
                                        channels=settings.channels,
                                        rate=settings.fs,
                                        input=_input_,
                                        output=_output_,
                                        frames_per_buffer=settings.chunk_size,
                                        input_device_index=settings.device_index,
                                        stream_callback=self.__call__)  
        self.audio_stream.start_stream()
        
#        return (audio_stream,audio)
        
    
    def end_stream(self):
        '''
        Closes an audio stream.
        '''
        if not self.audio_stream.is_stopped():
            self.audio_stream.stop_stream()
        else: 
            pass
        self.audio_stream.close()
        self.audio.terminate()
        
        
        
#%% NI stream
   
        
class Recorder_NI(object):
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
        self.device_name = devices[0]
        #self.set_device_by_name(self.device_name)
        
    def set_device_by_name(self, name):
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
            selected_device = devices[0]
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
        in_data = np.zeros(self.settings.chunk_size*self.settings.channels,dtype = np.int16)
        read = pdaq.int32()
        self.audio_stream.ReadBinaryI16(self.settings.chunk_size,10.0,pdaq.DAQmx_Val_GroupByScanNumber,
                           in_data,self.settings.chunk_size*self.settings.channels,pdaq.byref(read),None)

        data_array = in_data.reshape((-1,self.settings.channels))/(2**15)
            
        self.osc_data_chunk = data_array#(np.frombuffer(in_data, dtype=eval('np.int'+str(self.settings.nbits)))/2**(self.settings.nbits-1))
        #self.osc_data_chunk=np.reshape(self.osc_data_chunk,[self.settings.chunk_size,self.settings.channels])
        for i in range(self.settings.channels):
            self.osc_time_data[:-(self.settings.chunk_size),i] = self.osc_time_data[self.settings.chunk_size:,i]
            self.osc_time_data[-(self.settings.chunk_size):,i] = self.osc_data_chunk[:,i]
            if (not self.trigger_detected) or (self.settings.pretrig_samples is None):
                self.stored_time_data[:-(self.settings.chunk_size),i] = self.stored_time_data[self.settings.chunk_size:,i]
                self.stored_time_data[-(self.settings.chunk_size):,i] = self.osc_data_chunk[:,i]
        
        trigger_first_detected = np.any(np.abs(self.osc_data_chunk[:,self.settings.pretrig_channel])>self.settings.pretrig_threshold)
        if trigger_first_detected and self.trigger_first_detected_message:
            print('')
            print('Trigger detected. Logging data for {} seconds'.format(self.settings.stored_time))
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
    

    
    def init_stream(self,settings,_input_=True,_output_=False):
        '''
        Initialises an audio stream. Gives the user a choice of which device to access.
        '''
        
    
        try:
            self.audio_stream.end_stream()
        except:
            pass
        
        # Make AutoRegN be one of set of possible numbers that works with nidaqmx
        AutoRegN = np.int16([10,100,1000])
        check = np.where(AutoRegN <= settings.chunk_size)
        AutoRegN = AutoRegN[check[0][-1]]
        
        self.audio_stream = Task()
        self.audio_stream.stream_audio_callback = self.stream_audio_callback
        self.audio_stream.CreateAIVoltageChan(self.set_channels(),"",
                                 pdaq.DAQmx_Val_RSE,-settings.VmaxNI,settings.VmaxNI,
                                 pdaq.DAQmx_Val_Volts,None)
        self.audio_stream.CfgSampClkTiming("",self.settings.fs,
                              pdaq.DAQmx_Val_Rising,pdaq.DAQmx_Val_ContSamps,
                              self.settings.chunk_size)
        self.audio_stream.AutoRegisterEveryNSamplesEvent(pdaq.DAQmx_Val_Acquired_Into_Buffer,
                                            AutoRegN,0,name = 'stream_audio_callback')
        self.audio_stream.StopTask()
        self.audio_stream.StartTask()


    def start_output(self,settings,output):

#        output_channel_name = '%s/ao0' % self.device_name
        output_channel_name =  '%s/ao0:%s/ao%i' % (self.device_name, self.device_name,2-1)
        print(output_channel_name)
        self.output_stream = Task()
        self.output_stream.CreateAOVoltageChan(output_channel_name,"",-settings.VmaxNI,settings.VmaxNI,pdaq.DAQmx_Val_Volts,None)
        self.output_stream.CfgSampClkTiming("",5000,
                              pdaq.DAQmx_Val_Rising,pdaq.DAQmx_Val_FiniteSamps,
                              np.int(np.size(output)/2))
        
#        self.output_stream.StartTask()
        
        timeout = 5
        self.output_stream.WriteAnalogF64(np.int(np.size(output)/2),True, timeout, pdaq.DAQmx_Val_GroupByChannel,output,None,None)
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
        if self.audio_stream is not None:
            self.audio_stream.StopTask()
            self.audio_stream.ClearTask()
            self.audio_stream = None
