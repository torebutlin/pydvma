# -*- coding: utf-8 -*-
"""
Created on Fri Aug  3 11:27:29 2018

@authors: ae407, tb267
"""      
import sys

from . import options
from . import file
from . import datastructure
from . import streams
# from .gui import app

import numpy as np
import pyqtgraph as pg
from qtpy import QtGui, QtCore
from qtpy.QtCore import QObject, Signal, Qt

import time
import datetime


class Oscilloscope():
    def __init__(self, settings):
        '''Creates an Oscilloscope
        Args:
            settings: An object of the class MySettings
        '''

        self.settings = settings
        
        streams.start_stream(settings)
        self.rec = streams.REC
        

        self.timer = QtCore.QTimer()
        self.create_figure()

        self.win.sigKeyPress.connect(self.keyPressed)
        self.win.sigClose.connect(self.on_close)

        # Start the update timer
        self.timer.timeout.connect(self.update) # update figure and buffer
        self.timer.start(60)

        if app.applicationState() != Qt.ApplicationActive:
            app.exec()  

    def create_figure(self):
        '''
        Creates a figure which is an object of the class KeyPressWindow.

        '''
        pg.setConfigOption('background', 'w')
        self.win = KeyPressWindow()
        self.win.setWindowIcon(QtGui.QIcon('icon.png'))
#        window_geometry = self.win.geometry()
        self.win.setGeometry(100,100,800,600)
        self.win.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
        
        # This ensures the window appears at front.
        self.win.showMinimized()
        

        self.win.setWindowTitle("Oscilloscope ('s': save new, 'space': autosave, 'p': pause, 'a': always top, 'y': autoscale)")
        # time.sleep(0.6)
        self.win.show()
        self.win.showNormal()
        self.win.raise_()

        self.view_time = self.settings.init_view_time
        self.view_freq = self.settings.init_view_freq
        self.view_levels = self.settings.init_view_levels

        self.toggle_view()
        
        self.auto_scale = False

        self.data_saved_counter = 0 #  to indicate not yet saved file

    def on_close(self, evt):
        self.timer.stop()
        # self.rec.end_stream()

    def toggle_view(self):
        '''
        Switches between views, triggered by keypress
        '''
        self.win.clear()

        if self.view_time:
            self.time_plot()

        if self.view_freq:
            self.freq_plot()

        if self.view_levels:
            self.levels_plot()

    def time_plot(self):
        # create a plot for the time domain
        self.view_time = True
        self.win.nextRow()
        self.osc_time_line = self.win.addPlot(title="Time Domain (toggle with 'T')")

        if self.settings.channels == 1:
            self.auto_scale = True
            self.osc_time_line.enableAutoRange()
        else:
            # Stack the channels -- channel 0 is centred on 0, channel 1
            # centred on 1 etc.
            self.auto_scale = False
            self.osc_time_line.setYRange(-1,self.settings.channels)

        self.osc_time_line.setXRange(self.rec.osc_time_axis[0],
                                     self.rec.osc_time_axis[-1])
        self.osc_time_line.showGrid(True, True)
        self.osc_time_line.addLegend()
        self.osc_time_line.setLabel('left', 'Normalised Amplitude')
        self.osc_time_line.setLabel('bottom', 'Time (s)')

        self.ax_time = self.osc_time_line.getAxis('left')
        self.ax_time.setTickSpacing(1, 1)

        self.osc_time_lineset = {}
        for i in range(self.settings.channels):
            pen_ = pg.mkPen(color=options.set_plot_colours(self.settings.channels)[i,:])
            self.osc_time_lineset[i] = self.osc_time_line.plot(
                pen=pen_, name='Channel %d' % i)

#        self.win.FillBetweenItem(curve1=osc_time_lineset[0], curve2=osc_time_lineset[1])

    def freq_plot(self):
        # create a plot for the frequency domain
        self.view_freq = True
        self.win.nextRow()
        self.osc_freq_line = self.win.addPlot(
            title="Frequency Domain (toggle with 'F')")
        self.osc_freq_line.enableAutoRange()
        self.osc_freq_line.setXRange(self.rec.osc_freq_axis[0],
                                     self.rec.osc_freq_axis[-1])
        self.osc_freq_line.showGrid(True, True)
        self.osc_freq_line.addLegend()
        self.osc_freq_line.setLabel('left', 'Power Spectrum (dB)')
        self.osc_freq_line.setLabel('bottom', 'Frequency (Hz)')

        self.osc_freq_lineset = {}
        for i in range(self.settings.channels):
            pen_ = pg.mkPen(color=options.set_plot_colours(self.settings.channels)[i,:])
            self.osc_freq_lineset[i] = self.osc_freq_line.plot(
                pen=pen_, name='Channel %d' % i)

    def levels_plot(self):
        # create a plot for the frequency domain
        self.view_levels = True
        self.win.nextRow()
        self.osc_levels_line = self.win.addPlot(title="Channel Levels (toggle with 'L')")
        self.osc_levels_line.setYRange(0, 1)
        self.osc_levels_line.setXRange(-0.5, self.settings.channels - 0.5)
        self.osc_levels_line.showGrid(False, True)
        self.osc_levels_line.setLabel('left', 'Normalised Amplitude')
        self.osc_levels_line.setLabel('bottom', 'Channel Index')

        self.ax_levels = self.osc_levels_line.getAxis('bottom')
        self.ax_levels.setTickSpacing(1, 1)
#        ax.showLabel(show=True)
#        self.osc_levels_line.setTicks(np.arange(self.settings.channels))
        self.osc_levels_lineset={}
        for i in range(self.settings.channels):
            pen_ = pg.mkPen(color=options.set_plot_colours(self.settings.channels)[i,:],width=3)
            pen_peak = pg.mkPen(color=options.set_plot_colours(self.settings.channels)[i,:],width=3)
            self.osc_levels_lineset[i]=self.osc_levels_line.plot(pen=pen_, name='vertical')
            self.osc_levels_lineset[self.settings.channels+i]=self.osc_levels_line.plot(pen=pen_, name='top')
            self.osc_levels_lineset[2*self.settings.channels+i]=self.osc_levels_line.plot(pen=pen_peak, name='peak hold')
#            self.osc_levels_lineset[3]=self.osc_levels_line.plot(pen=pen_, name='Channel')

        self.osc_levels_peak_hold = np.zeros(self.settings.channels)
        self.time_last_changed = np.zeros(self.settings.channels)

    def update(self):
        '''
        Updates plots with incoming data from __call__.
        Called with a 0s interval by QTimer.

        '''
        time_data_snapshot = np.copy(self.rec.osc_time_data)
        if self.view_levels == True:
            self.osc_levels_rms = np.sqrt(np.mean(time_data_snapshot**2,axis=0))
            self.osc_levels_max = np.max(np.abs(time_data_snapshot),axis=0)
            changed_indices = self.osc_levels_peak_hold < self.osc_levels_max
            self.time_last_changed[changed_indices] = time.time()
            self.osc_levels_peak_hold = np.maximum(self.osc_levels_peak_hold,self.osc_levels_max)
            self.osc_levels_peak_hold[time.time()-self.time_last_changed>2] = 0

        for i in range(self.settings.channels):
            offset = i
            if self.view_time == True:
                if (self.auto_scale is True) and (self.settings.channels==1):
                    shift = 0
                    scale_factor = 1
                    self.osc_time_line.enableAutoRange()
                elif (self.auto_scale is True) and (self.settings.channels!=1):
                    shift = np.mean(time_data_snapshot[:,i])
                    scale_factor = np.max(np.abs(time_data_snapshot[:,i]-shift))*2
                    self.osc_time_line.setYRange(-1,self.settings.channels)
                else:
                    shift = 0
                    scale_factor = 1
                    self.osc_time_line.setYRange(-1,self.settings.channels)
                    
                self.osc_time_lineset[i].setData(self.rec.osc_time_axis, (time_data_snapshot[:,i]-shift)/scale_factor + offset)

            if self.view_freq == True:
                # calculate the FFT
                self.rec.osc_time_data_windowed[:,i] = time_data_snapshot[:,i] * np.blackman(np.shape(time_data_snapshot)[0])
                fd = np.abs(np.fft.rfft(self.rec.osc_time_data_windowed[:,i]))/len(self.rec.osc_time_data_windowed[:,i])
                fd[fd==0] = np.min(fd+1e-16) # to avoid log10(0) warnings
                self.rec.osc_freq_data[:,i] = 20 * np.log10(fd)
                self.osc_freq_lineset[i].setData(self.rec.osc_freq_axis,self.rec.osc_freq_data[:,i])

            if self.view_levels == True:
                self.osc_levels_lineset[i].setData([i,i],[0,self.osc_levels_max[i]])
                self.osc_levels_lineset[self.settings.channels+i].setData([i-0.3,i+0.3],self.osc_levels_max[i]*np.ones(2))

                if self.osc_levels_peak_hold[i] > 0.98:
                    pen_peak = pg.mkPen(color=options.set_plot_colours(self.settings.channels)[i,:],width=10)
                else:
                    pen_peak = pg.mkPen(color=options.set_plot_colours(self.settings.channels)[i,:],width=3)
#                self.osc_levels_lineset[2*self.settings.channels+i]=self.osc_levels_line.plot(pen=pen_peak, name='peak hold')
                self.osc_levels_lineset[2*self.settings.channels+i].setData([i-0.3,i+0.3],self.osc_levels_peak_hold[i]*np.ones(2),pen=pen_peak)
#                self.osc_levels_lineset[3].setData(np.arange(2),np.ones(2))



    #KeyPressed function within osciolloscpe since can only take one argument
    def keyPressed(self, evt):
        '''
        Upon a Space Bar press, makes a copy of data from the past stored_time seconds,plots it in Bokeh and gives the user an option to save it.
        '''

        if evt.key() == QtCore.Qt.Key_T:

            if self.view_freq != False or self.view_levels != False:
#                print('toggled time domain view')
                self.view_time = not self.view_time
                self.toggle_view()
#            else:
#                print('toggling all views off is prevented')

        if evt.key() == QtCore.Qt.Key_F:

            if self.view_time != False or self.view_levels != False:
#                print('toggled frequency domain view')
                self.view_freq = not self.view_freq
                self.toggle_view()
#            else:
#                print('toggling all views off is prevented')

        if evt.key() == QtCore.Qt.Key_L:
            if self.view_time != False or self.view_freq != False:
#                print('toggled levels view')
                self.view_levels = not self.view_levels
                self.toggle_view()
#            else:
#                print('toggling all views off is prevented')
        
        if evt.key() == QtCore.Qt.Key_P:
            if self.timer.isActive():
                self.timer.stop()
            else:
                self.timer.start()
                
        if evt.key() == QtCore.Qt.Key_A:
            self.win.setWindowFlags(self.win.windowFlags() ^ QtCore.Qt.WindowStaysOnTopHint)       
            self.win.show()
                
            
        if evt.key() == QtCore.Qt.Key_Y:
            self.auto_scale = not self.auto_scale 
                
        if evt.key() == QtCore.Qt.Key_Space or evt.key() == QtCore.Qt.Key_S:

            stored_time_data_copy=np.copy(self.rec.stored_time_data)
            t = datetime.datetime.now()
            timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
#            print("key press trigger: saving data to file in working directory")

            ### make into dataset
            
            fs=self.settings.fs
            n_samp=len(stored_time_data_copy[:,0])
            dt=1/fs
            t_axis= np.arange(n_samp)*dt

            
            timedata = datastructure.TimeData(t_axis,stored_time_data_copy,self.settings,timestamp=t,timestring=timestring,test_name='Test_{}'.format(self.data_saved_counter))
            
            dataset = datastructure.DataSet()
            dataset.add_to_dataset(timedata)
            
            
            if evt.key() == QtCore.Qt.Key_S:
                self.data_saved_counter = 1
                self.last_filename = file.save_data(dataset,self.win)
            
#            # this version saves all data as new timedata objects within one file
#            if evt.key() == QtCore.Qt.Key_Space:
#                if self.data_saved_counter == 0:
#                    self.last_filename = file.save_data(dataset)
#                    if self.last_filename == '':
#                        self.data_saved_counter = 0
#                    else:
#                        self.data_saved_counter += 1
#                
#                else:
#                    d = file.load_data(self.last_filename)
#                    d.add_to_dataset(timedata)
#                    file.save_data(d,self.last_filename,overwrite_without_prompt=True)
#                    self.data_saved_counter += 1
            
            # this version saves each new dataset to new file
            if evt.key() == QtCore.Qt.Key_Space:
                if self.data_saved_counter == 0:
                    self.last_filename = file.save_data(dataset,self.win)
                    if self.last_filename == '':
                        self.data_saved_counter = 0
                    else:
                        self.data_saved_counter += 1
                
                else:
                    d = datastructure.DataSet()
                    d.add_to_dataset(timedata)
                    filename = self.last_filename.replace('.npy','_'+str(self.data_saved_counter)+'.npy')
                    file.save_data(d,self.win, filename,overwrite_without_prompt=True)
                    self.data_saved_counter += 1

class KeyPressWindow(pg.GraphicsLayoutWidget):
    '''
    A subclass of pyQtGraph GraphicsWindow that emits a signal when a key is pressed.

    '''
    sigKeyPress = Signal(object)
    sigClose = Signal(object)

    def __init__(self, *args, **kwargs):
        '''
        Re-implmented from parent.
        '''
        super().__init__(*args, **kwargs)

    def keyPressEvent(self, evt):
        '''
        Emits a signal upon a key press
        '''
        self.scene().keyPressEvent(evt)
        self.sigKeyPress.emit(evt)

    def closeEvent(self, evt):
        '''
        Emits a signal when the window is closed.
        '''
        self.sigClose.emit(evt)
        self.close()
