# -*- coding: utf-8 -*-
"""
Created on Fri Aug  3 11:27:29 2018

@authors: ae407, tb267
"""      
import sys

from . import settings
from . import file
from . import logdata
from . import plotting

import pyaudio
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtGui, QtCore
import matplotlib
import matplotlib.pyplot as plt
import time
import datetime





class oscilloscope():
    
    app = None
    win = None

    def __init__(self,settings):
        '''Creates an Oscilloscope
        Args:
            settings: An object of the class mySettings
        '''

        
        self.settings = settings
            
        rec = recorder(settings)
        audio_stream,audio = rec.init_pyaudio(settings)
        self.rec = rec
        self.audio_stream = audio_stream
        self.audio = audio    
        
        if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
            
            
            self.create_figure()
            
            
            oscilloscope.win.sigKeyPress.connect(self.keyPressed)
            
            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(lambda:self.update(audio_stream)) # update figure and buffer
            self.timer.start(0)
                
            oscilloscope.app.instance().exec_()
            
            
    def create_figure(self):
        '''
        Creates a figure which is an object of the class KeyPressWindow.
        
        '''
        pg.setConfigOption('background', 'w')
        if oscilloscope.app == None:
            oscilloscope.app = QtGui.QApplication([])
            
#        if oscilloscope.win == None:
        oscilloscope.win = KeyPressWindow(self)
#        oscilloscope.win.setWindowIcon(QtGui.QIcon('icon.png'))
        
        
        window_geometry = oscilloscope.win.geometry()
        

        
        oscilloscope.win.setGeometry(100,100,800,600)
        
        oscilloscope.win.showMinimized()
        oscilloscope.win.showNormal()


        oscilloscope.win.setWindowTitle("Oscilloscope (to save to new filename press 's', to autosave press 'space')")
        self.view_time = self.settings.init_view_time
        self.view_freq = self.settings.init_view_freq
        self.view_levels = self.settings.init_view_levels
        
        self.toggle_view()
        
        self.data_saved_counter = 0 #  to indicate not yet saved file
           
            

    def toggle_view(self):
        '''
        Switches between views, triggered by keypress
        '''
        oscilloscope.win.clear()
        
        
        if self.view_time == True:
            self.time_plot()
            
        if self.view_freq == True:
            self.freq_plot()
            
        if self.view_levels == True:
            self.levels_plot()
        
        
            
            
    
        
    
    def time_plot(self):
        # create a plot for the time domain
        self.view_time = True
        oscilloscope.win.nextRow()
        self.osc_time_line = oscilloscope.win.addPlot(title="Time Domain (toggle with 'T')")
        if self.settings.channels==1:
            self.osc_time_line.enableAutoRange()
        else:
            self.osc_time_line.setYRange(-1,self.settings.channels)
        self.osc_time_line.setXRange(self.rec.osc_time_axis[0],self.rec.osc_time_axis[-1])
        self.osc_time_line.showGrid(True, True)
        self.osc_time_line.addLegend()
        self.osc_time_line.setLabel('left','Normalised Amplitude')
        self.osc_time_line.setLabel('bottom','Time (s)')  
        
        ax=self.osc_time_line.getAxis('left')
        ax.setTickSpacing(1,1)
        
        self.osc_time_lineset={}
        for i in range(self.settings.channels):
            pen_ = pg.mkPen(color=settings.set_plot_colours(self.settings.channels)[i,:])
            self.osc_time_lineset[i]=self.osc_time_line.plot(pen=pen_, name='Channel '+str(i))
        
#        oscilloscope.win.FillBetweenItem(curve1=osc_time_lineset[0], curve2=osc_time_lineset[1])
        
    def freq_plot(self):
        # create a plot for the frequency domain
        self.view_freq = True
        oscilloscope.win.nextRow()
        self.osc_freq_line = oscilloscope.win.addPlot(title="Frequency Domain (toggle with 'F')") 
        self.osc_freq_line.enableAutoRange()
        self.osc_freq_line.setXRange(self.rec.osc_freq_axis[0],self.rec.osc_freq_axis[-1])
        self.osc_freq_line.showGrid(True, True)
        self.osc_freq_line.addLegend()
        self.osc_freq_line.setLabel('left','Power Spectrum (dB)')
        self.osc_freq_line.setLabel('bottom','Frequency (Hz)')
        
        self.osc_freq_lineset={}
        for i in range(self.settings.channels):
            pen_ = pg.mkPen(color=settings.set_plot_colours(self.settings.channels)[i,:])
            self.osc_freq_lineset[i]=self.osc_freq_line.plot(pen=pen_, name='Channel'+str(i))
            
    def levels_plot(self):
        # create a plot for the frequency domain
        self.view_levels = True
        oscilloscope.win.nextRow()
        
        self.osc_levels_line = oscilloscope.win.addPlot(title="Channel Levels (toggle with 'L')")
        self.osc_levels_line.setYRange(0,1)
        self.osc_levels_line.setXRange(-0.5,self.settings.channels-0.5)
        self.osc_levels_line.showGrid(False,True)
        self.osc_levels_line.setLabel('left','Normalised Amplitude')
        self.osc_levels_line.setLabel('bottom','Channel Index')
        
        
        ax=self.osc_levels_line.getAxis('bottom')
        ax.setTickSpacing(1,1)    
#        ax.showLabel(show=True)
#        self.osc_levels_line.setTicks(np.arange(self.settings.channels))
        self.osc_levels_lineset={}
        for i in range(self.settings.channels):
            pen_ = pg.mkPen(color=settings.set_plot_colours(self.settings.channels)[i,:],width=3)
            pen_peak = pg.mkPen(color=settings.set_plot_colours(self.settings.channels)[i,:],width=3)
            self.osc_levels_lineset[i]=self.osc_levels_line.plot(pen=pen_, name='vertical')
            self.osc_levels_lineset[self.settings.channels+i]=self.osc_levels_line.plot(pen=pen_, name='top')
            self.osc_levels_lineset[2*self.settings.channels+i]=self.osc_levels_line.plot(pen=pen_peak, name='peak hold')    
#            self.osc_levels_lineset[3]=self.osc_levels_line.plot(pen=pen_, name='Channel')
        
        self.osc_levels_peak_hold = np.zeros(self.settings.channels)
        self.time_last_changed = np.zeros(self.settings.channels)
        
    
    def update(self,audio_stream):
        '''
        Updates plots with incoming data from __call__. 
        Called with a 0s interval by QTimer.
        
        '''
        if self.view_levels == True:
            self.osc_levels_rms = np.sqrt(np.mean(self.rec.osc_time_data**2,axis=0))
            self.osc_levels_max = np.max(np.abs(self.rec.osc_time_data),axis=0)
            changed_indices = self.osc_levels_peak_hold < self.osc_levels_max
            self.time_last_changed[changed_indices] = time.time()
            self.osc_levels_peak_hold = np.maximum(self.osc_levels_peak_hold,self.osc_levels_max)
            self.osc_levels_peak_hold[time.time()-self.time_last_changed>2] = 0
            
                
        for i in range(self.settings.channels):
            offset=i
            if self.view_time == True:
                self.osc_time_lineset[i].setData(self.rec.osc_time_axis,self.rec.osc_time_data[:,i] + offset)
            
            if self.view_freq == True:
                # calculate the FFT
                self.rec.osc_time_data_windowed[:,i] = self.rec.osc_time_data[:,i] * np.blackman(np.shape(self.rec.osc_time_data)[0])
                self.rec.osc_freq_data[:,i] = 20 * np.log10(np.abs(np.fft.rfft(self.rec.osc_time_data_windowed[:,i]))/len(self.rec.osc_time_data_windowed[:,i]))
                self.osc_freq_lineset[i].setData(self.rec.osc_freq_axis,self.rec.osc_freq_data[:,i])
                
            if self.view_levels == True:
                self.osc_levels_lineset[i].setData([i,i],[0,self.osc_levels_max[i]])
                self.osc_levels_lineset[self.settings.channels+i].setData([i-0.3,i+0.3],self.osc_levels_max[i]*np.ones(2))
                
                if self.osc_levels_peak_hold[i] > 0.98:
                    pen_peak = pg.mkPen(color=settings.set_plot_colours(self.settings.channels)[i,:],width=10)
                else:
                    pen_peak = pg.mkPen(color=settings.set_plot_colours(self.settings.channels)[i,:],width=3)
#                self.osc_levels_lineset[2*self.settings.channels+i]=self.osc_levels_line.plot(pen=pen_peak, name='peak hold')
                self.osc_levels_lineset[2*self.settings.channels+i].setData([i-0.3,i+0.3],self.osc_levels_peak_hold[i]*np.ones(2),pen=pen_peak)
#                self.osc_levels_lineset[3].setData(np.arange(2),np.ones(2))
                
                
            #updates for the stored
            self.rec.stored_time_data_windowed[:,i] = self.rec.stored_time_data[:,i] * np.blackman(np.shape(self.rec.stored_time_data)[0])
            self.rec.stored_freq_data[:,i] = 20 * np.log10(np.abs(np.fft.rfft(self.rec.stored_time_data_windowed[:,i]))/len(self.rec.stored_time_data_windowed[:,i]))
    

        
            
            
    #KeyPressed function within osciolloscpe since can only take one argument        
    def keyPressed(self, evt):
        '''
        Upon a Space Bar press, makes a copy of data from the past stored_time seconds,plots it in Bokeh and gives the user an option to save it.
        '''
        
        if evt.key() == QtCore.Qt.Key_T:

            if self.view_freq != False or self.view_levels != False:
                print('toggled time domain view')
                self.view_time = not self.view_time
                self.toggle_view()
            else:
                print('toggling all views off is prevented')
            
            
        if evt.key() == QtCore.Qt.Key_F:

            if self.view_time != False or self.view_levels != False:
                print('toggled frequency domain view')
                self.view_freq = not self.view_freq
                self.toggle_view()
            else:
                print('toggling all views off is prevented')
            
            
        if evt.key() == QtCore.Qt.Key_L:
            if self.view_time != False or self.view_freq != False:
                print('toggled levels view')
                self.view_levels = not self.view_levels
                self.toggle_view()
            else:
                print('toggling all views off is prevented')
        
        
        if evt.key() == QtCore.Qt.Key_Space or evt.key() == QtCore.Qt.Key_S:
            
            stored_time_data_copy=np.copy(self.rec.stored_time_data)
            t = datetime.datetime.now()
            timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
            
            
            print("key press trigger: saving data to file in working directory")
            
            ### make into dataset
            
            fs=self.settings.fs
            n_samp=len(stored_time_data_copy[:,0])
            dt=1/fs
            t_samp=n_samp*dt
            t_axis= np.arange(0,t_samp,dt)
#            f_axis=np.fft.rfftfreq(len(t_axis),1/fs)
#            freq_data=np.fft.rfft(stored_time_data_copy,axis=0)
            
            
            t_data = logdata.timeData(t_axis,stored_time_data_copy,self.settings)
            metadata = logdata.metaData(timestamp=t,timestring=timestring)
            dataset = logdata.dataSet(timeData=t_data, settings=self.settings, metaData=metadata)
            
            #plotting.plotdata(dataset)
            
            
            
            
            if evt.key() == QtCore.Qt.Key_S:
                self.data_saved_counter = 0
            
            
            if self.data_saved_counter == 0:
                self.last_filename = file.save_data(dataset)
                if self.last_filename != None:
                    self.data_saved_counter += 1
            
            else:
                filename = self.last_filename.replace('.npy','') + '_' + str(self.data_saved_counter) + '.npy'
                file.save_data(dataset,filename)
                self.data_saved_counter += 1


        
        
class recorder(object):
    def __init__(self,settings):
        self.settings = settings
        self.osc_time_axis=np.arange(0,(self.settings.num_chunks*self.settings.chunk_size)/self.settings.fs,1/self.settings.fs)
        self.osc_freq_axis=np.fft.rfftfreq(len(self.osc_time_axis),1/self.settings.fs)
        self.osc_time_data=np.zeros(shape=((self.settings.num_chunks*self.settings.chunk_size),self.settings.channels))  
        self.osc_time_data_windowed=np.zeros_like(self.osc_time_data)
        if (self.settings.num_chunks*self.settings.chunk_size)%2==0:
            self.osc_freq_data=np.zeros(shape=(int(((self.settings.num_chunks*self.settings.chunk_size)/2)+1),self.settings.channels))
        else:
            self.osc_freq_data=np.zeros(shape=(int((self.settings.num_chunks*self.settings.chunk_size+1)/2),self.settings.channels))
        
        #rounds up the number of chunks needed in the pretrig array    
        self.stored_num_chunks=int(np.ceil((self.settings.stored_time*self.settings.fs)/self.settings.chunk_size))
        #the +2 is to allow for the updating process on either side
        self.stored_time_data=np.zeros(shape=((self.stored_num_chunks*self.settings.chunk_size)+2,self.settings.channels))
        self.stored_time_data_windowed=np.zeros_like(self.stored_time_data)
        #note the +2s to match up the length of stored_num_chunks
        #formula used from the np.fft.rfft documentation
        if (self.stored_num_chunks*self.settings.chunk_size)%2==0:
            self.stored_freq_data=np.zeros(shape=(int(((
                    self.stored_num_chunks*self.settings.chunk_size+2)/2)+1),self.settings.channels))
        else:
            self.stored_freq_data=np.zeros(shape=(int((
                    self.stored_num_chunks*self.settings.chunk_size+2+1)/2),self.settings.channels))
            
            
    def __call__(self,in_data, frame_count, time_info, status):
        '''
        Obtains data from the audio stream.
        '''
        self.osc_data_chunk = (np.frombuffer(in_data, dtype=eval('np.int'+str(self.settings.nbits)))/2**(self.settings.nbits-1))
        self.osc_data_chunk=np.reshape(self.osc_data_chunk,[self.settings.chunk_size,self.settings.channels])
        for i in range(self.settings.channels):
            self.osc_time_data[:-(self.settings.chunk_size),i] = self.osc_time_data[self.settings.chunk_size:,i]
            self.osc_time_data[-(self.settings.chunk_size):,i] = self.osc_data_chunk[:,i]
            self.stored_time_data[:-(self.settings.chunk_size),i] = self.stored_time_data[self.settings.chunk_size:,i]
            self.stored_time_data[-(self.settings.chunk_size):,i] = self.osc_data_chunk[:,i]
        return (in_data, pyaudio.paContinue)
    
    
    def init_pyaudio(self,settings,_input_=True,_output_=False):
        '''
        Initialises an audio stream. Gives the user a choice of which device to access.
        '''
        global audio,audio_stream
        
        audio = pyaudio.PyAudio()
        
        if settings.device_index == None:
    
            device_count = audio.get_device_count()
            print ('Number of devices available is: %i' %device_count)
            print ('')
            print('Devices available, by index:')
            print ('')
            for i in range(device_count):
                device = audio.get_device_info_by_index(i)
                print(device['index'], device['name'])
            print ('')
            default_device = audio.get_default_input_device_info()
            print('Default device is: %i %s'
                  %(default_device['index'],default_device['name']))
            print ('')
            settings.device_index=int(input('Insert index of required device:'))
            
        settings.device_name = audio.get_device_info_by_index(settings.device_index)['name']
        settings.device_full_info = audio.get_device_info_by_index(settings.device_index)
        
        print(settings.device_full_info['index'], settings.device_full_info['name'])
        print("Selected device: %i : %s" %(settings.device_index,settings.device_name))    
        
        audio_stream = audio.open(format=settings.format,
                                        channels=settings.channels,
                                        rate=settings.fs,
                                        input=_input_,
                                        output=_output_,
                                        frames_per_buffer=settings.chunk_size,
                                        input_device_index=settings.device_index,
                                        stream_callback=self.__call__)  
        audio_stream.start_stream()
        
        return (audio_stream,audio)
        
    
    def end_pyaudio(self,audio_stream,audio):
        '''
        Closes an audio stream.
        '''
        if not audio_stream.is_stopped():
            audio_stream.stop_stream()
        else: 
            pass
        audio_stream.close()
        audio.terminate()
        
        

    

     

    
class KeyPressWindow(pg.GraphicsWindow):
    '''
    A subclass of pyQtGraph GraphicsWindow that emits a signal when a key is pressed.
    
    '''
    sigKeyPress = QtCore.pyqtSignal(object)
    

    def __init__(self, oscilloscope, *args, **kwargs):
        '''
        Re-implmented from parent.
        '''
        super().__init__(*args, **kwargs)
        self.oscilloscope = oscilloscope

    def keyPressEvent(self, evt):
        '''
        Emits a signal upon a key press 
        '''
        self.scene().keyPressEvent(evt)
        self.sigKeyPress.emit(evt)
        
    def closeEvent(self,event):
        '''
        Stops QTimer,exits QApplication and closes the audio stream when the user exits the oscilloscope window.
        '''
        self.oscilloscope.timer.stop()
        self.close()
        self.oscilloscope.rec.end_pyaudio(self.oscilloscope.audio_stream,self.oscilloscope.audio)
#        pg.exit()

        


   

         