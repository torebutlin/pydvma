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

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtGui, QtCore
import time
import datetime


class Oscilloscope():
    def __init__(self, settings):
        '''Creates an Oscilloscope
        Args:
            settings: An object of the class MySettings
        '''

        self.settings = settings

        if settings.device_driver == 'soundcard':
            self.rec = streams.Recorder(settings)
        elif settings.device_driver == 'nidaq':
            self.rec = streams.Recorder_NI(settings)
        else:
            raise ValueError('Unknown driver: %r' % settings.device_driver)
        self.rec.init_stream(settings)

        # XXX What is this check for?
        if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
            self.timer = QtCore.QTimer()
            self.create_figure()

            self.win.sigKeyPress.connect(self.keyPressed)
            self.win.sigClose.connect(self.on_close)

            # Start the update timer
            self.timer.timeout.connect(self.update) # update figure and buffer
            self.timer.start(60)

    def create_figure(self):
        '''
        Creates a figure which is an object of the class KeyPressWindow.

        '''
        pg.setConfigOption('background', 'w')
        self.win = KeyPressWindow()
#        self.win.setWindowIcon(QtGui.QIcon('icon.png'))

        window_geometry = self.win.geometry()
        self.win.setGeometry(100,100,800,600)

        # XXX Do you really want it to start minimized then appear?
        self.win.showMinimized()
        self.win.showNormal()

        self.win.setWindowTitle("Oscilloscope (to save to new filename press "
                                "'s', to autosave press 'space')")
        self.view_time = self.settings.init_view_time
        self.view_freq = self.settings.init_view_freq
        self.view_levels = self.settings.init_view_levels

        self.toggle_view()

        self.data_saved_counter = 0 #  to indicate not yet saved file

    def on_close(self, evt):
        self.timer.stop()
        self.rec.end_stream()

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
            self.osc_time_line.enableAutoRange()
        else:
            # Stack the channels -- channel 0 is centred on 0, channel 1
            # centred on 1 etc.
            self.osc_time_line.setYRange(-1,self.settings.channels)

        self.osc_time_line.setXRange(self.rec.osc_time_axis[0],
                                     self.rec.osc_time_axis[-1])
        self.osc_time_line.showGrid(True, True)
        self.osc_time_line.addLegend()
        self.osc_time_line.setLabel('left', 'Normalised Amplitude')
        self.osc_time_line.setLabel('bottom', 'Time (s)')

        ax = self.osc_time_line.getAxis('left')
        ax.setTickSpacing(1, 1)

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

        ax = self.osc_levels_line.getAxis('bottom')
        ax.setTickSpacing(1, 1)
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
        if self.view_levels == True:
            self.osc_levels_rms = np.sqrt(np.mean(self.rec.osc_time_data**2,axis=0))
            self.osc_levels_max = np.max(np.abs(self.rec.osc_time_data),axis=0)
            changed_indices = self.osc_levels_peak_hold < self.osc_levels_max
            self.time_last_changed[changed_indices] = time.time()
            self.osc_levels_peak_hold = np.maximum(self.osc_levels_peak_hold,self.osc_levels_max)
            self.osc_levels_peak_hold[time.time()-self.time_last_changed>2] = 0

        for i in range(self.settings.channels):
            offset = i
            if self.view_time == True:
                self.osc_time_lineset[i].setData(self.rec.osc_time_axis, self.rec.osc_time_data[:,i] + offset)

            if self.view_freq == True:
                # calculate the FFT
                self.rec.osc_time_data_windowed[:,i] = self.rec.osc_time_data[:,i] * np.blackman(np.shape(self.rec.osc_time_data)[0])
                self.rec.osc_freq_data[:,i] = 20 * np.log10(np.abs(np.fft.rfft(self.rec.osc_time_data_windowed[:,i]))/len(self.rec.osc_time_data_windowed[:,i]))
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
            t_axis= np.arange(n_samp)*dt

            
            timedata = datastructure.TimeData(t_axis,stored_time_data_copy,self.settings,timestamp=t,timestring=timestring,test_name='Test_{}'.format(self.data_saved_counter))
            
            dataset = datastructure.DataSet()
            dataset.add_to_dataset(timedata)
            
            
            if evt.key() == QtCore.Qt.Key_S:
                self.data_saved_counter = 1
                self.last_filename = file.save_data(dataset)
            
            if evt.key() == QtCore.Qt.Key_Space:
                if self.data_saved_counter == 0:
                    self.last_filename = file.save_data(dataset)
                    if self.last_filename == '':
                        self.data_saved_counter = 0
                    else:
                        self.data_saved_counter += 1
                
                else:
                    d = file.load_data(self.last_filename)
                    d.add_to_dataset(timedata)
                    file.save_data(d,self.last_filename,overwrite_without_prompt=True)
                    self.data_saved_counter += 1


class KeyPressWindow(pg.GraphicsWindow):
    '''
    A subclass of pyQtGraph GraphicsWindow that emits a signal when a key is pressed.

    '''
    sigKeyPress = QtCore.pyqtSignal(object)
    sigClose = QtCore.pyqtSignal(object)

    def __init__(self, *args, **kwargs):
        '''
        Re-implmented from parent.
        '''
        super().__init__(*args, **kwargs)
        #self.rec = rec

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
