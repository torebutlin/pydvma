from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QMessageBox, QTabWidget, QFormLayout, QToolBar, QLineEdit, QLabel, QComboBox, QSlider, QMessageBox
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QFrame, QStyleFactory, QSplitter, QFrame, QFormLayout
from PyQt5.QtWidgets import QToolTip
from PyQt5.QtCore import Qt, QThread, Signal, QTimer, QObject
from PyQt5.QtGui import QPalette, QDoubleValidator, QIntValidator, QFontMetrics
from PyQt5 import QtGui
import copy
from matplotlib.backends.backend_qt5agg import FigureCanvas, NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.ticker import AutoLocator
import numpy as np
import logging
logging.basicConfig(filename='example.log',level=logging.DEBUG)
#%%

from . import plotting
from . import datastructure
from . import acquisition
from . import analysis
from . import streams
from . import file
from . import modal
from . import options
import time
import sys


#%%

class BlueButton(QPushButton):
    def __init__(self,text):
        super().__init__(text)
        self.setStyleSheet("background-color: hsl(240, 170, 255)")
        self.setText(text) 

class GreenButton(QPushButton):
    def __init__(self,text):
        super().__init__(text)
        self.setStyleSheet("background-color: hsl(120, 170, 255);")
        self.setText(text)

class RedButton(QPushButton):
    def __init__(self,text):
        super().__init__(text)
        self.setStyleSheet("background-color: hsl(0, 170, 255)")
        self.setText(text)
        
class OrangeButton(QPushButton):
    def __init__(self,text):
        super().__init__(text)
        self.setStyleSheet("background-color: hsl(30, 170,255)")
        self.setText(text)

class QHLine(QFrame):
    def __init__(self):
        super(QHLine, self).__init__()
        self.setFrameShape(QFrame.HLine)
        self.setFrameShadow(QFrame.Sunken)
        
class newComboBox(QComboBox):
    def __init__(self,items_list):
        super().__init__()
        self.setStyleSheet('selection-background-color: hsl(240, 170, 255)')
        self.addItems(items_list)
        
class boldLabel(QLabel):
    def __init__(self,text):
        super().__init__(text)
        self.setStyleSheet('font: bold')
        
        
class LogDataThread(QThread):
    
    s = Signal(datastructure.DataSet)

    def __init__(self,settings,test_name,rec,output):
        super().__init__()
        
        self.settings = settings
        self.test_name = test_name
        self.rec = rec
        self.output = output
        
    def __del__(self):
        self.wait()
    
    def run(self):
        self.d = acquisition.log_data(self.settings,test_name=self.test_name, rec=self.rec, output=self.output)
        self.s.emit(self.d)
        
        
        
class PreviewWindow():
    def __init__(self,title='Time Data'):
        self.preview_window = QWidget()
        self.preview_window.setStyleSheet("background-color: white")
        self.preview_window.setWindowTitle('Output Signal Preview')
        
        self.fig = Figure(figsize=(9, 5),dpi=100)
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas,None)
        self.toolbar.setOrientation(Qt.Horizontal)
        self.p = plotting.PlotData(canvas=self.canvas,fig=self.fig)
        
        self.label_figure = boldLabel(title)
        self.label_figure.setMaximumHeight(20)
        self.label_figure.setAlignment(Qt.AlignCenter)
        
        # widgets to layout
        self.layout_figure = QVBoxLayout()
        self.layout_figure.addWidget(self.label_figure)
        self.layout_figure.addWidget(self.canvas)
        self.layout_figure.addWidget(self.toolbar)
        
        self.preview_window.setLayout(self.layout_figure)
        
        self.preview_window.showMinimized()
        self.preview_window.showNormal()

class Logger():
        
    def __init__(self,settings=None,test_name=None,default_window=None):
        
        # Initialise variables
        global MESSAGE
        if default_window is None:
            default_window = 'None'
        self.settings = settings
        self.test_name = test_name
        self.dataset = datastructure.DataSet()
        
        self.default_window = default_window
        self.current_view = 'Time'    
        self.N_frames = 1
        self.overlap = 0.5
        self.iw_fft_power = 0
        self.iw_tf_power = 0
        self.legend_loc = 'lower right'
        self.show_coherence = True
        self.show_data = True
        self.coherence_plot_type = 'linear'
        self.xlinlog = 'linear'
        self.plot_type = None
        self.freq_range = [0,np.inf]
        self.auto_xy = 'xy'
        self.sets = 'all'
        self.channels = 'all'
        self.last_action = None
        self.iw_power = 0
        self.selected_channels = []
        self.flag_scaling = False
        self.message_time = 0
        self.flag_log_and_replace = False
        self.flag_output = False
        self.message_timer = QTimer() # purely for pretrig live messages
        self.message = ''
        
        # SETUP GUI
        QApplication.setStyle(QStyleFactory.create('Fusion'))
        
        self.window = QWidget()
        self.window.setStyleSheet("background-color: white")
        self.window.setWindowTitle('Logger')
        self.window.setWindowIcon(QtGui.QIcon('icon.png'))
#        self.window.YOU.ARE.HERE.CLOSEWINDOW?

        # initiate all interface tool frames
        self.setup_frame_tools()
        self.setup_frame_input()
        self.setup_frame_figure()
        self.setup_frame_save()
        self.setup_frame_axes()
        
        # arrange frames and create window
        self.setup_layout_main()
        self.window.showMinimized()
        self.window.showNormal()
        
        # start stream if already passed settings
        self.start_stream()
        self.message_timer.timeout.connect(self.show_message_timer) # connect after stream started
        
    def setup_layout_main(self):

        # organise frames
        self.splitter_mid = QSplitter(Qt.Vertical)
        self.splitter_mid.addWidget(self.frame_input)
        self.splitter_mid.addWidget(self.frame_figure)
        self.splitter_mid.addWidget(self.frame_save)
        
        self.splitter_all = QSplitter(Qt.Horizontal)
        self.splitter_all.addWidget(self.frame_axes)
        self.splitter_all.addWidget(self.splitter_mid)
        self.splitter_all.addWidget(self.frame_tools)
        
        # frames to main layout
        self.layout_main = QGridLayout()
        self.layout_main.addWidget(self.splitter_all)
        
        # main layout to window
        self.window.setLayout(self.layout_main)
        

    def setup_frame_figure(self):
        # content
        
        self.fig = Figure(figsize=(9, 7),dpi=100)
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas,None)
        self.toolbar.setOrientation(Qt.Horizontal)
        self.p = plotting.PlotData(canvas=self.canvas,fig=self.fig)
        self.p.ax.callbacks.connect('xlim_changed', self.update_axes_values)
        self.p.ax.callbacks.connect('ylim_changed', self.update_axes_values)
        self.p.ax2.callbacks.connect('ylim_changed', self.update_co_axes_values)
        self.fig.canvas.mpl_connect('pick_event', self.update_selected_channels)
        
        self.label_figure = boldLabel('Time Data')
        self.label_figure.setMaximumHeight(20)
        self.label_figure.setAlignment(Qt.AlignCenter)
        
        # widgets to layout
        self.layout_figure = QVBoxLayout()
        self.layout_figure.addWidget(self.label_figure)
        self.layout_figure.addWidget(self.canvas)
        self.layout_figure.addWidget(self.toolbar)
        
        # layout to frame
        self.frame_figure = QFrame()
        self.frame_figure.setFrameShape(QFrame.StyledPanel)
        self.frame_figure.setLayout(self.layout_figure)
        
    def setup_frame_input(self):
        
        self.setup_frame_message()
        
        # content
        self.button_log_data = GreenButton('Log Data')
        self.button_del_data = OrangeButton('Delete Last')
        self.button_res_data = RedButton('Delete All')
        self.button_load_data = BlueButton('Load Data')
                
        self.button_log_data.clicked.connect(self.button_clicked_log_data)
        self.button_del_data.clicked.connect(self.delete_last_data)
        self.button_res_data.clicked.connect(self.reset_data)
        self.button_load_data.clicked.connect(self.load_data)
        
        # widgets to layout
        self.layout_input = QGridLayout()
        self.layout_input.addWidget(self.button_log_data,0,0,1,1)
        self.layout_input.addWidget(self.button_del_data,0,1,1,1)
        self.layout_input.addWidget(self.button_res_data,0,2,1,1)
        self.layout_input.addWidget(self.button_load_data,0,3,1,1)
        self.layout_input.addWidget(self.frame_message,1,0,1,4)
        self.layout_input.setAlignment(Qt.AlignTop)
        
        # layout to frame
        self.frame_input = QFrame()
        self.frame_input.setFrameShape(QFrame.StyledPanel)
        self.frame_input.setLayout(self.layout_input)
        
        
    def setup_frame_message(self):
        self.label_message = QLabel()
        self.button_message = GreenButton('OK')
        self.button_cancel = OrangeButton('Cancel')
        self.button_undo = RedButton('Undo')
        
        # function connections
        self.button_message.clicked.connect(self.hide_message)
        self.button_cancel.clicked.connect(self.cancel_logging)
        self.button_undo.clicked.connect(self.undo_last_action)
        
        self.layout_message = QGridLayout()
        
        self.layout_message.addWidget(self.label_message,0,0,1,3)
        self.layout_message.addWidget(self.button_message,0,3,1,1)
        self.layout_message.addWidget(self.button_cancel,0,3,1,1)
        self.layout_message.addWidget(self.button_undo,1,3,1,1)
        self.layout_message.setAlignment(Qt.AlignTop)
        
        self.frame_message = QFrame()
        self.frame_message.setLayout(self.layout_message)
        self.hide_message()
        
        
    def setup_frame_save(self):
        # design items
#        self.label_save = QLabel('Quick save:')
        self.buttons_save = [GreenButton(i) for i in ['Save Dataset','Save Figure']]
        self.buttons_save[0].clicked.connect(self.save_data)
        self.buttons_save[1].clicked.connect(self.save_fig)
        
        # widgets to layout
        self.layout_save = QHBoxLayout()
        for n in range(len(self.buttons_save)):
            self.layout_save.addWidget(self.buttons_save[n])
            
        # layout to frame
        self.frame_save = QFrame()
        self.frame_save.setFrameShape(QFrame.StyledPanel)
        self.frame_save.setLayout(self.layout_save)
        
    
    def setup_frame_axes(self):
        
        self.setup_frame_plot_details()
        
        self.input_list_figures = newComboBox(['Time Data','FFT Data','TF Data','Sono Data'])
        self.input_list_figures.currentIndexChanged.connect(self.select_view)
        
        self.button_x = GreenButton('Auto X')
        self.button_y = GreenButton('Auto Y')
        
        self.button_x.clicked.connect(self.auto_x)
        self.button_y.clicked.connect(self.auto_y)
        
        self.label_axes = [QLabel(i) for i in ['xmin:','xmax:','ymin:','ymax:']]
        self.input_axes = [QLineEdit() for i in range(4)]
        self.input_axes[0].setValidator(QDoubleValidator(np.float(0),np.float(np.inf),5)) 
        self.input_axes[0].editingFinished.connect(self.xmin)
        self.input_axes[1].setValidator(QDoubleValidator(np.float(0),np.float(np.inf),5)) 
        self.input_axes[1].editingFinished.connect(self.xmax)
        self.input_axes[2].setValidator(QDoubleValidator(np.float(-np.inf),np.float(np.inf),5)) 
        self.input_axes[2].editingFinished.connect(self.ymin)
        self.input_axes[3].setValidator(QDoubleValidator(np.float(-np.inf),np.float(np.inf),5)) 
        self.input_axes[3].editingFinished.connect(self.ymax)
        
        self.button_select_all_data = GreenButton('All')
        self.button_select_no_data = GreenButton('None')
        self.button_select_all_data.clicked.connect(self.select_all_data)
        self.button_select_no_data.clicked.connect(self.select_no_data)
        
        self.button_select_next = GreenButton('>')
        self.button_select_prev = GreenButton('<')
        self.button_select_next.clicked.connect(self.next_chans)
        self.button_select_prev.clicked.connect(self.prev_chans)
        width = self.button_select_next.fontMetrics().boundingRect('>').width()*4
        self.button_select_next.setMaximumWidth(width)
        self.button_select_prev.setMaximumWidth(width)
        
        self.button_select_set_only = BlueButton('Show Set Only')
        self.button_select_set_only.clicked.connect(self.show_set_only)
        self.button_select_chan_only = BlueButton('Show Chan Only')
        self.button_select_chan_only.clicked.connect(self.show_chan_only)
        
        self.input_select_set_only = QLineEdit('0')
        self.input_select_set_only.setValidator(QIntValidator(0,1000))
        self.input_select_chan_only = QLineEdit('0')
        self.input_select_chan_only.setValidator(QIntValidator(0,1000))
        
        self.legend_buttons = [BlueButton(i) for i in ['left','on/off','right']]
        self.legend_buttons[0].clicked.connect(self.legend_left)
        self.legend_buttons[1].clicked.connect(self.legend_onoff)
        self.legend_buttons[2].clicked.connect(self.legend_right)
        
        
        # widgets to layout
        self.layout_axes = QGridLayout()
        self.layout_axes.setAlignment(Qt.AlignTop)


        # Figure selection
        row_start = 0
        self.layout_axes.addWidget(boldLabel('Figure selection:'),row_start+0,0,1,6)
        self.layout_axes.addWidget(self.input_list_figures,row_start+1,0,1,6)
        
        # Axes control
        row_start = 3
        self.layout_axes.addWidget(QLabel(),row_start,0,1,6)
        self.layout_axes.addWidget(boldLabel('Axes control:'),row_start+1,0,1,6)
        self.layout_axes.addWidget(self.button_x,row_start+2,0,1,3)
        self.layout_axes.addWidget(self.button_y,row_start+2,3,1,3)
        
        for n in range(len(self.label_axes)):
            self.label_axes[n].setAlignment(Qt.AlignRight)
            self.layout_axes.addWidget(self.label_axes[n],row_start+n+4,0,1,2)
            self.layout_axes.addWidget(self.input_axes[n],row_start+n+4,2,1,4)
            
        # Line Selection
        row_start = 11
        self.layout_axes.addWidget(QLabel(),row_start,0,1,6)
        self.layout_axes.addWidget(boldLabel('Line Selection:'),row_start+1,0,1,6)
        self.layout_axes.addWidget(self.button_select_all_data,row_start+2,0,1,2)
        self.layout_axes.addWidget(self.button_select_no_data,row_start+2,2,1,2)
        self.layout_axes.addWidget(self.button_select_prev,row_start+2,4,1,1)
        self.layout_axes.addWidget(self.button_select_next,row_start+2,5,1,1)
        self.layout_axes.addWidget(self.button_select_set_only,row_start+3,0,1,3)
        self.layout_axes.addWidget(self.input_select_set_only,row_start+3,3,1,3)
        self.layout_axes.addWidget(self.button_select_chan_only,row_start+4,0,1,3)
        self.layout_axes.addWidget(self.input_select_chan_only,row_start+4,3,1,3)
        
        
        # Legend control
        row_start = 17
        self.layout_axes.addWidget(QLabel(),row_start,0,1,6)
        self.layout_axes.addWidget(boldLabel('Legend control:'),row_start+1,0,1,6)
        for n in range(len(self.legend_buttons)):
            self.layout_axes.addWidget(self.legend_buttons[n],row_start+2,2*n,1,2)
        
        
        # Plot-specific tools
        row_start = 20
        self.layout_axes.addWidget(self.frame_plot_details,row_start,0,1,6)
        self.frame_plot_details.setVisible(False)
        
        # layout to frame
        self.frame_axes = QFrame()
        self.frame_axes.setFrameShape(QFrame.StyledPanel)
        self.frame_axes.setLayout(self.layout_axes)
       
    def setup_frame_plot_details(self):
        #items
        self.items_list_plot_type = ['Amplitude (dB)','Amplitude (linear)', 'Real Part', 'Imag Part', 'Nyquist', 'Amplitude + Phase', 'Phase']
        self.input_list_plot_type = newComboBox(self.items_list_plot_type)
        self.button_xlinlog = BlueButton('X Lin/Log')
        self.button_data_toggle = BlueButton('Data on/off')
        self.button_coherence_toggle = BlueButton('Coherence on/off')
        
        
        self.label_co_freq_min = QLabel('co. min:')
        self.label_co_freq_max = QLabel('co. max:')
        self.input_co_min = QLineEdit('0')
        self.input_co_min.setValidator(QDoubleValidator(np.float(-np.inf),np.float(np.inf),5))
        self.input_co_max = QLineEdit('1')
        self.input_co_max.setValidator(QDoubleValidator(np.float(-np.inf),np.float(np.inf),5))
        
        # freq range for Nyquist
        self.input_freq_min = QLineEdit()
        self.input_freq_min.setValidator(QDoubleValidator(np.float(0),np.float(np.inf),5))
        self.input_freq_min.editingFinished.connect(self.freq_min)
        self.input_freq_max = QLineEdit()
        self.input_freq_max.setValidator(QDoubleValidator(np.float(0),np.float(np.inf),5))
        self.input_freq_max.editingFinished.connect(self.freq_max)
        
        #self.button_modal_fit_toggle = BlueButton('Modal Fit on/off')
        
        self.input_list_plot_type.currentIndexChanged.connect(self.select_view)
        self.input_co_min.editingFinished.connect(self.co_min)
        self.input_co_max.editingFinished.connect(self.co_max)
        self.button_data_toggle.clicked.connect(self.data_toggle)
        self.button_coherence_toggle.clicked.connect(self.coherence_toggle)
        self.button_xlinlog.clicked.connect(self.select_xlinlog)
        #layout
        self.layout_plot_details = QGridLayout()
        self.layout_plot_details.addWidget(QLabel(),0,0,1,1)
        self.layout_plot_details.addWidget(boldLabel('Plot Options:'),1,0,1,2)
        self.layout_plot_details.addWidget(self.input_list_plot_type,2,0,1,2)
        self.layout_plot_details.addWidget(self.button_xlinlog,3,0,1,2)
        self.layout_plot_details.addWidget(self.button_data_toggle,4,0,1,1)
        self.layout_plot_details.addWidget(self.button_coherence_toggle,4,1,1,1)
        self.layout_plot_details.addWidget(self.label_co_freq_min,5,0,1,1)
        self.layout_plot_details.addWidget(self.input_co_min,5,1,1,1)
        self.layout_plot_details.addWidget(self.input_freq_min,5,1,1,1)
        self.layout_plot_details.addWidget(self.label_co_freq_max,6,0,1,1)
        self.layout_plot_details.addWidget(self.input_co_max,6,1,1,1)
        self.layout_plot_details.addWidget(self.input_freq_max,6,1,1,1)
        #self.layout_plot_details.addWidget(self.button_modal_fit_toggle,7,0,1,2)        
        
        #only show these for Nyquist plots
        self.input_freq_min.setVisible(False)
        self.input_freq_max.setVisible(False)
        
        #frame
        self.frame_plot_details = QFrame()
        self.frame_plot_details.setLayout(self.layout_plot_details)
    
    
    def setup_frame_tools(self):
        
        # initiate all tools frames
        self.setup_frame_tools_selection()
        self.setup_frame_tools_time_domain()
        self.setup_frame_tools_fft()
        self.setup_frame_tools_tf()
        self.setup_frame_tools_scaling()
        self.setup_frame_tools_mode_fitting()
        self.setup_frame_tools_settings()
        self.setup_frame_tools_generate_output()
        self.setup_frame_tools_edit_dataset()
        self.setup_frame_tools_sonogram()
        self.setup_frame_tools_save_export()
        
        # widgets to layout
        self.layout_tools = QVBoxLayout()
        self.layout_tools.addWidget(self.frame_tools_selection)
        self.layout_tools.addWidget(self.frame_tools_time_domain)
        self.layout_tools.addWidget(self.frame_tools_fft)
        self.layout_tools.addWidget(self.frame_tools_tf)
        self.layout_tools.addWidget(self.frame_tools_scaling)
        self.layout_tools.addWidget(self.frame_tools_mode_fitting)
        self.layout_tools.addWidget(self.frame_tools_settings)
        self.layout_tools.addWidget(self.frame_tools_generate_output)
        self.layout_tools.addWidget(self.frame_tools_edit_dataset)
        self.layout_tools.addWidget(self.frame_tools_sonogram)
#        self.layout_tools.addWidget(self.frame_tools_save_export)
        
        self.layout_tools.setAlignment(Qt.AlignTop)
        
        # layout to frame
        self.frame_tools = QFrame()
        self.frame_tools.setFrameShape(QFrame.StyledPanel)
        self.frame_tools.setLayout(self.layout_tools)
        
        # widgets to layout according to selection
        self.input_list_tools.setCurrentText('Standard Tools')
        self.select_tool()
        
        
        
        
    def setup_frame_tools_selection(self):
        
        self.input_list_tools = newComboBox(['Standard Tools','Logger Settings','Generate Output','Pre-process','FFT','Transfer Function','Calibration / Scaling','Sonogram','Mode Fitting','Edit Dataset','Save / Export'])
        self.input_list_tools.setCurrentIndex(0)
        self.input_list_tools.currentIndexChanged.connect(self.select_tool)
        
        self.layout_tools_selection = QGridLayout()
        self.layout_tools_selection.addWidget(boldLabel('Tool selection:'),0,0,1,3)
        self.layout_tools_selection.addWidget(self.input_list_tools,1,0,1,3)
        
        self.frame_tools_selection = QFrame()
        self.frame_tools_selection.setLayout(self.layout_tools_selection)
        


    def setup_frame_tools_time_domain(self):
        
        self.button_clean_impulse = BlueButton('Clean Impulse')
        self.button_clean_impulse.clicked.connect(self.clean_impulse)
        
        self.input_impulse_channel = QLineEdit('0')
        self.input_impulse_channel.setValidator(QIntValidator(0,1000))
        self.layout_tools_time_domain = QGridLayout()
        self.layout_tools_time_domain.addWidget(boldLabel('Pre-process:'),0,0,1,3)
        self.layout_tools_time_domain.addWidget(QLabel('Impulse channel:'),1,0,1,1)
        self.layout_tools_time_domain.addWidget(self.input_impulse_channel,1,1,1,2)
        self.layout_tools_time_domain.addWidget(self.button_clean_impulse,2,0,1,3)
        
        self.frame_tools_time_domain = QFrame()
        self.frame_tools_time_domain.setLayout(self.layout_tools_time_domain)


    def setup_frame_tools_fft(self):
        
        self.input_list_window_fft = newComboBox(['None','hann'])
        self.input_list_window_fft.setCurrentText(self.default_window)
        self.button_FFT = BlueButton('Calc FFT')
        self.button_FFT.clicked.connect(self.calc_fft)
        
        self.layout_tools_fft = QGridLayout()
        self.layout_tools_fft.addWidget(boldLabel('FFT:'),0,0,1,3)
        self.layout_tools_fft.addWidget(QLabel('window:'),1,0,1,1)
        self.layout_tools_fft.addWidget(self.input_list_window_fft,1,1,1,2)
        self.layout_tools_fft.addWidget(self.button_FFT,2,0,1,3)
        
        self.frame_tools_fft = QFrame()
        self.frame_tools_fft.setLayout(self.layout_tools_fft)

    def setup_frame_tools_tf(self):
        self.input_list_window_tf = newComboBox(['None','hann'])
        self.input_list_average_TF = newComboBox(['None','within each set','across sets'])
        self.button_TF = BlueButton('Calc TF')
        self.button_TF.clicked.connect(self.calc_tf)
        self.input_list_average_TF.currentIndexChanged.connect(self.select_averaging_type)
        self.label_Nframes = QLabel('N frames:')
        self.input_Nframes = QLineEdit()
        self.input_Nframes.setValidator(QIntValidator(1,1000))
        self.input_Nframes.setText('1')
        self.input_Nframes.editingFinished.connect(self.refresh_Nframes_slider)
        self.input_Nframes.editingFinished.connect(self.calc_tf)
        
        self.slider_Nframes = QSlider(Qt.Horizontal)
        self.slider_Nframes.setMinimum(1)
        self.slider_Nframes.setMaximum(30)
        self.slider_Nframes.valueChanged.connect(self.refresh_Nframes_text)
        self.slider_Nframes.valueChanged.connect(self.calc_tf)
        
        self.label_Nframes_time = QLabel('')
        
        self.button_TFav = BlueButton('Calc TF average')
        self.button_TFav.clicked.connect(self.calc_tf_av)
        
        
        self.layout_tools_tf = QGridLayout()
        self.layout_tools_tf.addWidget(boldLabel('Transfer Function:'),0,0,1,3)
        self.layout_tools_tf.addWidget(QLabel('window:'),1,0,1,1)
        self.layout_tools_tf.addWidget(self.input_list_window_tf,1,1,1,2)
        self.layout_tools_tf.addWidget(QLabel('average:'),2,0,1,1)
        self.layout_tools_tf.addWidget(self.input_list_average_TF,2,1,1,2)
        self.layout_tools_tf.addWidget(self.label_Nframes,3,0,1,1)
        self.layout_tools_tf.addWidget(self.input_Nframes,3,1,1,2)
        self.layout_tools_tf.addWidget(self.slider_Nframes,4,0,1,3)
        self.layout_tools_tf.addWidget(self.label_Nframes_time,5,0,1,3)
        self.layout_tools_tf.addWidget(self.button_TF,6,0,1,3)
        self.layout_tools_tf.addWidget(self.button_TFav,6,0,1,3)
        
        # initiate view
        self.input_list_average_TF.setCurrentIndex(0)
        self.input_Nframes.setText('1')
        self.slider_Nframes.setValue(1)
        self.label_Nframes.setVisible(False)
        self.input_Nframes.setVisible(False)
        self.slider_Nframes.setVisible(False)
        self.label_Nframes_time.setVisible(False)
        self.button_TFav.setVisible(False)
        self.button_TF.setVisible(True)
        
        
        self.frame_tools_tf = QFrame()
        self.frame_tools_tf.setLayout(self.layout_tools_tf)
        
        
    def setup_frame_tools_scaling(self):
        self.input_iw_power = QLineEdit('0')
        self.input_iw_power.setValidator(QIntValidator(0,2))
        
        self.button_xiw = BlueButton('x (iw)')
        self.button_diw = BlueButton('x 1/(iw)')
        self.button_xiw.clicked.connect(self.xiw)
        self.button_diw.clicked.connect(self.diw)
        
        self.input_refset = QLineEdit('0')
        self.input_refset.setValidator(QIntValidator(0,1000))
        self.input_refchan = QLineEdit('0')
        self.input_refchan.setValidator(QIntValidator(0,1000))

        self.button_best_match = BlueButton('Best Match (to ref)')
        self.button_best_match.clicked.connect(self.best_match)
        self.button_undo_scaling = RedButton('Undo All Scaling')
        self.button_undo_scaling.clicked.connect(self.undo_scaling)        
        
        self.layout_tools_scaling = QGridLayout()
        self.layout_tools_scaling.addWidget(boldLabel('Calibration / Scaling:'),0,0,1,4)
        self.layout_tools_scaling.addWidget(self.button_xiw,1,0,1,2)
        self.layout_tools_scaling.addWidget(self.button_diw,1,2,1,2)
        
        self.layout_tools_scaling.addWidget(QLabel('Ref set / chan:'),2,0,1,2)
        self.layout_tools_scaling.addWidget(self.input_refset,2,2,1,1)
        self.layout_tools_scaling.addWidget(self.input_refchan,2,3,1,1)
        
        self.layout_tools_scaling.addWidget(self.button_best_match,3,0,1,4)
        self.layout_tools_scaling.addWidget(self.button_undo_scaling,4,0,1,4)
        
        self.frame_tools_scaling = QFrame()
        self.frame_tools_scaling.setLayout(self.layout_tools_scaling)
        
    def setup_frame_tools_mode_fitting(self):
        self.input_freq_min2 = QLineEdit()
        self.input_freq_min2.setValidator(QDoubleValidator(np.float(0),np.float(np.inf),5))
        self.input_freq_min2.editingFinished.connect(self.freq_min2)
        self.input_freq_max2 = QLineEdit()
        self.input_freq_max2.setValidator(QDoubleValidator(np.float(0),np.float(np.inf),5))
        self.input_freq_max2.editingFinished.connect(self.freq_max2)
        
        self.input_list_tf_type = newComboBox(['Acceleration','Velocity','Displacement'])
        
        self.button_fit_mode = GreenButton('Fit')
        self.button_fit_mode.clicked.connect(self.fit_mode)
        self.button_reject_mode = RedButton('Reject')
        self.button_reject_mode.clicked.connect(self.reject_mode)
        self.button_view_mode_summary = BlueButton('Summary')
        self.button_view_mode_summary.clicked.connect(self.view_mode_summary)
        self.button_view_modal_reconstruction = BlueButton('Reconstruction')
        self.button_view_modal_reconstruction.clicked.connect(self.view_modal_reconstruction)
        
        self.layout_tools_mode_fitting = QGridLayout()
        self.layout_tools_mode_fitting.addWidget(boldLabel('Mode Fitting:'),0,0,1,4)
        self.layout_tools_mode_fitting.addWidget(QLabel('TF type:'),1,0,1,1)
        self.layout_tools_mode_fitting.addWidget(self.input_list_tf_type,1,1,1,3)
        
        self.layout_tools_mode_fitting.addWidget(QLabel('Zoom to view a single peak:'),2,0,1,4)
        self.layout_tools_mode_fitting.addWidget(QLabel('fmin:'),3,0,1,1)
        self.layout_tools_mode_fitting.addWidget(self.input_freq_min2,3,1,1,3)
        self.layout_tools_mode_fitting.addWidget(QLabel('fmax:'),4,0,1,1)
        self.layout_tools_mode_fitting.addWidget(self.input_freq_max2,4,1,1,3)
        self.layout_tools_mode_fitting.addWidget(self.button_fit_mode,5,0,1,2)
        self.layout_tools_mode_fitting.addWidget(self.button_reject_mode,5,2,1,2)
        self.layout_tools_mode_fitting.addWidget(self.button_view_mode_summary,6,0,1,4)
        self.layout_tools_mode_fitting.addWidget(self.button_view_modal_reconstruction,7,0,1,4)
        
        self.frame_tools_mode_fitting = QFrame()
        self.frame_tools_mode_fitting.setLayout(self.layout_tools_mode_fitting)
        
    def setup_frame_tools_settings(self):
        
        if self.settings is None:
            self.settings = options.MySettings()
            
            
        self.button_apply_settings = GreenButton('Apply Settings')
        self.button_apply_settings.clicked.connect(self.apply_settings)
        
        self.button_show_available_devices = BlueButton('Show Available Devices')
        self.button_show_available_devices.clicked.connect(self.show_available_devices)
        
        self.settings_dict = self.settings.__dict__
        self.labels_settings = list(self.settings_dict.keys())
        self.values_settings = list(self.settings_dict.values())
        
        self.input_settings = dict()
        for (label,value) in self.settings_dict.items():
            self.input_settings[label] = QLineEdit(str(value))
        
            
        
        NI = streams.get_devices_NI()
        SC = streams.get_devices_soundcard()
        
        if NI == (None,None):
            self.input_list_devices = []
        else:
            self.input_list_devices = ['nidaq']
        if SC != None:
            self.input_list_devices += ['soundcard']
        
        self.input_test_name = QLineEdit()
        self.input_test_name.editingFinished.connect(self.refresh_test_name)
        
        self.layout_tools_settings = QFormLayout()
        
        self.layout_tools_settings.addWidget(boldLabel('Input Settings:'))
        self.layout_tools_settings.addRow(QLabel('Test Name:'),self.input_test_name)
        for n_row in range(9):
            self.layout_tools_settings.addRow(QLabel(self.labels_settings[n_row]),self.input_settings[self.labels_settings[n_row]])
        self.layout_tools_settings.addWidget(boldLabel('Output Settings:'))
        for n_row in range(9,13):
            self.layout_tools_settings.addRow(QLabel(self.labels_settings[n_row]),self.input_settings[self.labels_settings[n_row]])
        
        self.layout_tools_settings.addWidget(self.button_show_available_devices)
        self.layout_tools_settings.addWidget(self.button_apply_settings)
        self.frame_tools_settings = QFrame()
        self.frame_tools_settings.setLayout(self.layout_tools_settings)
        
    def setup_frame_tools_generate_output(self):
        self.list_output_options = ['None','sweep','gaussian','uniform']
        self.input_output_options = newComboBox(self.list_output_options)
        self.input_output_options.currentTextChanged.connect(self.update_output)
        
        self.input_output_amp = QLineEdit('0')
        v = QDoubleValidator(0.0,1.0,5)
        v.setNotation(QDoubleValidator.StandardNotation)
        self.input_output_amp.setValidator(v)
        
        self.input_output_f1 = QLineEdit('0')
        self.input_output_f1.setValidator(QDoubleValidator(0.0,np.float(np.inf),5))
        
        self.input_output_f2 = QLineEdit('0')
        self.input_output_f2.setValidator(QDoubleValidator(0.0,np.float(np.inf),5))
        
        self.input_output_duration = QLineEdit(str(self.settings.stored_time))
        self.input_output_duration.setValidator(QDoubleValidator(0.0,np.float(np.inf),5))
        
        self.button_output_preview = BlueButton('Preview Output')
        self.button_output_preview.clicked.connect(self.preview_output)
        
        self.button_start_output = BlueButton('Start Output')
        self.button_start_output.clicked.connect(self.start_output)
        
        self.button_log_with_output = GreenButton('Log with Output')
        self.button_log_with_output.clicked.connect(self.button_clicked_log_data)
        
        
        self.input_test_name2 = QLineEdit()
        self.input_test_name2.editingFinished.connect(self.refresh_test_name2)
        
        self.layout_tools_generate_output = QFormLayout()
        
        self.layout_tools_generate_output.addRow(boldLabel('Generate Outputs:'))
        self.layout_tools_generate_output.addRow(QLabel('Test Name:'),self.input_test_name2)
        self.layout_tools_generate_output.addRow(QLabel('Type:'),self.input_output_options)
        self.layout_tools_generate_output.addRow(QLabel('Amplitude (0-1):'),self.input_output_amp)
        self.layout_tools_generate_output.addRow(QLabel('f1 (Hz):'),self.input_output_f1)
        self.layout_tools_generate_output.addRow(QLabel('f2 (Hz):'),self.input_output_f2)
        self.layout_tools_generate_output.addRow(QLabel('Duration (s):'),self.input_output_duration)
        self.layout_tools_generate_output.addRow(self.button_output_preview)
        self.layout_tools_generate_output.addRow(self.button_start_output)
        self.layout_tools_generate_output.addRow(self.button_log_with_output)
        
        self.frame_tools_generate_output = QFrame()
        self.frame_tools_generate_output.setLayout(self.layout_tools_generate_output)
        
    
    def setup_frame_tools_edit_dataset(self):
        self.list_data_type = ['Time Data','FFT Data','TF Data','Modal Data','Sono Data']
        
        self.input_list_data_type = newComboBox(self.list_data_type)
        self.input_list_data_type.setCurrentText('Time Data')
        self.input_list_data_type.currentIndexChanged.connect(self.update_selected_set)
        
        self.button_delete_data_type = RedButton('Delete all data of this type')
        self.button_delete_data_type.clicked.connect(self.delete_data_type)
        
        self.button_delete_data_set = OrangeButton('Delete Selected Set')
        self.button_delete_data_set.clicked.connect(self.delete_data_set)
        
        self.input_selected_set = QLineEdit()
        self.input_selected_set.setValidator(QIntValidator(0,1000))

        self.button_log_replace = GreenButton('Log && Replace Selected Set')
        self.button_log_replace.clicked.connect(self.log_and_replace)
        
        text = self.dataset.__repr__()
        self.label_data_summary = QLabel(text)
        
        self.layout_tools_edit_dataset = QGridLayout()
        self.layout_tools_edit_dataset.addWidget(boldLabel('Dataset Summary'),0,0,1,4)
        self.layout_tools_edit_dataset.addWidget(self.label_data_summary,1,0,1,4)
        self.layout_tools_edit_dataset.addWidget(boldLabel('Edit Dataset'),2,0,1,4)
        self.layout_tools_edit_dataset.addWidget(QLabel('Selected Type:'),3,0,1,2)
        self.layout_tools_edit_dataset.addWidget(self.input_list_data_type,3,2,1,2)
        self.layout_tools_edit_dataset.addWidget(self.button_delete_data_type,4,0,1,4)
        self.layout_tools_edit_dataset.addWidget(QLabel('Selected Set:'),5,0,1,2)
        self.layout_tools_edit_dataset.addWidget(self.input_selected_set,5,2,1,2)
        self.layout_tools_edit_dataset.addWidget(self.button_delete_data_set,6,0,1,4)
        self.layout_tools_edit_dataset.addWidget(self.button_log_replace,7,0,1,4)
        
        self.frame_tools_edit_dataset = QFrame()
        self.frame_tools_edit_dataset.setLayout(self.layout_tools_edit_dataset)
        
    def setup_frame_tools_sonogram(self):
        self.input_sono_N_frames = QLineEdit('50')
        self.input_sono_N_frames.setValidator(QIntValidator(10,10000))
        self.input_sono_N_frames.editingFinished.connect(self.refresh_sono_N_frames_slider)
        self.input_sono_N_frames.editingFinished.connect(self.calc_sono)
        
        self.slider_sono_N_frames = QSlider(Qt.Horizontal)
        self.slider_sono_N_frames.setMinimum(10)
        self.slider_sono_N_frames.setMaximum(500)
        self.slider_sono_N_frames.setValue(50)
        self.slider_sono_N_frames.valueChanged.connect(self.refresh_sono_N_frames_text)
        self.slider_sono_N_frames.valueChanged.connect(self.calc_sono)
        
        self.input_sono_n_set = QLineEdit('0')
        self.input_sono_n_set.setValidator(QIntValidator(0,1000))
        self.input_sono_n_set.editingFinished.connect(self.calc_sono)
        self.input_sono_n_chan = QLineEdit('0')
        self.input_sono_n_chan.setValidator(QIntValidator(0,1000))
        self.input_sono_n_chan.editingFinished.connect(self.calc_sono)
        
        self.input_db_range = QLineEdit('60')
        self.input_db_range.setValidator(QIntValidator(1,200))
        self.input_db_range.editingFinished.connect(self.calc_sono)
        
        self.sono_info = QLabel('')
        
        
        self.button_calc_sono = BlueButton('Calc Sonogram')
        self.button_calc_sono.clicked.connect(self.calc_sono)
        
        self.layout_tools_sonogram = QGridLayout()
        self.layout_tools_sonogram.addWidget(boldLabel('Calculate Sonogram:'),0,0,1,4)
        self.layout_tools_sonogram.addWidget(QLabel('N frames:'),1,0,1,2)
        self.layout_tools_sonogram.addWidget(self.input_sono_N_frames,1,2,1,2)
        self.layout_tools_sonogram.addWidget(self.slider_sono_N_frames,2,0,1,4)
        self.layout_tools_sonogram.addWidget(self.sono_info,3,0,1,4)
        self.layout_tools_sonogram.addWidget(QLabel('Dynamic Range (dB):'),4,0,1,2)
        self.layout_tools_sonogram.addWidget(self.input_db_range,4,2,1,2)
        self.layout_tools_sonogram.addWidget(QLabel('Set / Chan:'),5,0,1,2)
        self.layout_tools_sonogram.addWidget(self.input_sono_n_set,5,2,1,1)
        self.layout_tools_sonogram.addWidget(self.input_sono_n_chan,5,3,1,1)
        self.layout_tools_sonogram.addWidget(self.button_calc_sono,6,0,1,4)
        
        self.frame_tools_sonogram = QFrame()
        self.frame_tools_sonogram.setLayout(self.layout_tools_sonogram)
        
    def setup_frame_tools_save_export(self):
        pass
        
        
    def update_frame_tools(self):
        self.frame_tools.setLayout(self.layout_tools)


    #%% INTERACTION FUNCTIONS
    
    def show(self):
        # allow logger to be opened again after closing
        self.window.showMinimized()
        self.window.showNormal()
        
    def close(self):
        # allow logger to be closed programmatically
        self.window.close()
    
    def start_stream(self):
        if self.settings != None:
            try:
                streams.start_stream(self.settings)
                self.rec = streams.REC
            except:
                self.rec = None
                message = 'Data stream can\'t be initialised.\n'
                message += 'Possible reasons: pyaudio or PyDAQmx not installed, or acquisition hardware not connected.\n' 
                message += 'Please note that it won\'t be possible to log data.'
                self.show_message(message)
                
        else:
            message = 'To enable data acquisition, please use \'Logger Settings\' tool.'
            self.show_message(message)
#            self.input_list_tools.setCurrentIndex(1)
            self.select_view()

    def show_message(self,message,b='ok'):
        # if multiple messages from different functions, then join them up
        time_since_last = time.time()-self.message_time
        if (time_since_last < 0.5) and (message not in self.message):# and (self.message not in message):
            self.message += message # join messages if not duplicating
        else:
            self.message = message
        self.message_time = time.time()
        
#        if (message not in self.message) and (self.message not in message):
#            self.message += message # join messages if not duplicating
#        else:
#            self.message = message
        if message != '':
            self.label_message.setText(self.message)
            if b == 'ok':
                self.button_message.setVisible(True)
                self.button_cancel.setVisible(False)
                self.button_undo.setVisible(False)
            elif b == 'cancel':
                self.button_message.setVisible(False)
                self.button_cancel.setVisible(True)
                self.button_undo.setVisible(False)
            elif b == 'undo':
                self.button_message.setVisible(True)
                self.button_cancel.setVisible(False)
                self.button_undo.setVisible(True)
                
            self.frame_message.setVisible(True)
        
        
    def hide_message(self):
        self.label_message.setText('')
        self.message = ''
        self.frame_message.setVisible(False)
      
    def show_message_timer(self):
        message = acquisition.MESSAGE
#        message += self.rec.MESSAGE
        self.show_message(message,b='cancel')

    def button_clicked_log_data(self):
        # delegate messages to acquisition global MESSAGE, and streams rec.MESSAGE
        # this lets messages be seen from within logging thread, with live updates
        self.message_timer.start(300) 
        
        # start stream
        if self.rec is None:
            self.start_stream()
            
        # generate output if specified
        self.create_output_signal()
        if self.output_time_data is not None:
            y = self.output_time_data.time_data
        else:
            y = None
        
        # reset trigger
        self.rec.trigger_detected = False # but need to do this again inside acquisition
        self.button_log_data.setStyleSheet("background-color: white")
        
#        # show message re trigger
#        if self.settings.pretrig_samples is None:
#            message = 'Logging data for {} seconds'.format(self.settings.stored_time)
#        else:
            #message = 'Logging data for {} seconds, with trigger.\n'.format(self.settings.stored_time)
            
            
        
        
#        # show message re output
#        if y is not None:
#            message += '\n\nOutput signal starting.'
#            self.show_message(message) # this one 
        
        
        self.thread = LogDataThread(self.settings,test_name=self.test_name, rec=self.rec, output=y)
        #self.thread.setPriority(QThread.TimeCriticalPriority)
#        self.show_message(message,'cancel')
        
        self.thread.start()
        self.thread.s.connect(self.add_logged_data)
        
        
    def add_logged_data(self,d):
        
        if self.flag_log_and_replace == False:
            self.dataset.add_to_dataset(d.time_data_list)
            N = len(self.dataset.time_data_list)
            self.sets = [N-1]
            # this doesn't make it through from acquisition.MESSAGE because polling stops first
            message = 'Logging complete.\n'
            if np.any(np.abs(d.time_data_list[0].time_data) > 0.95):
                message += '\nWARNING: Data may be clipped.\n'
            self.show_message(message)
#            message = ''
#            self.hide_message()
        else:
            self.dataset.replace_data_item(d.time_data_list[0],self.selected_set)
            self.sets = [self.selected_set]
            self.last_action = 'data replaced'
            # this doesn't make it through from acquisition.MESSAGE because polling stops first
            message = 'Logged data replaced set {}.\n'.format(self.selected_set)
            if np.any(np.abs(d.time_data_list[0].time_data) > 0.95):
                message += '\nWARNING: Data may be clipped.\n'
            self.show_message(message,b='undo')
            self.flag_log_and_replace = False

        
        # update figure then update selection
        self.channels = 'all'
        self.switch_view('Time Data') # need to switch to time and update plot so that get_selected_chans picks up new data
        
        # only show most recently logged data
        selection = self.p.get_selected_channels()
        for ns in range(len(selection)):
            for nc in range(len(selection[ns])):
                if ns in self.sets:
                    selection[ns][nc] = True
                else:
                    selection[ns][nc] = False
        self.selected_channels = selection
        
        # update with final selection and make -1 to 1, change button back to green
        self.update_figure()
        self.p.ax.set_ylim([-1,1])
        self.button_log_data.setStyleSheet('background-color: hsl(120, 170, 255)')
        self.message_timer.stop()
        
        
    def cancel_logging(self):
        self.thread.terminate() # stop thread
        streams.start_stream(self.settings) # reset stream
        self.rec = streams.REC # reset stream
        self.show_message('Logging cancelled')
        self.button_log_data.setStyleSheet('background-color: hsl(120, 170, 255)')
        self.message_timer.stop() # stop acquisition messages
        self.selected_channels = self.p.get_selected_channels()

    def delete_last_data(self):
        self.dataset_backup = copy.deepcopy(self.dataset)
        self.dataset.remove_last_data_item('TimeData')
        self.dataset.freq_data_list = datastructure.FreqDataList()
        self.dataset.tf_data_list = datastructure.TfDataList()
        N = len(self.dataset.time_data_list)
        self.sets = [N-1]
        self.channels = 'all'
        
        # only show most recently logged data
        if N > 0:
            selection = self.p.get_selected_channels()
            for ns in range(len(selection)):
                for nc in range(len(selection[ns])):
                    if ns in self.sets:
                        selection[ns][nc] = True
                    else:
                        selection[ns][nc] = False
            self.selected_channels = selection
        
        self.auto_xy = ''
        self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all', auto_xy=self.auto_xy)
#        update(self,data_list,sets='all',channels='all',xlinlog='linear',show_coherence=True,plot_type=None,coherence_plot_type='linear',freq_range=None, auto_xy='xyc'):
        self.switch_view('Time Data')
        self.last_action = 'delete data'
        message = 'Last logged time data deleted.\n'
        message += 'FFT and TF data also deleted.\n'
        message += 'For more data editing options select ''Edit Dataset'' tool.'
        self.show_message(message,b='undo')
#        self.selected_channels = self.p.get_selected_channels()
#        self.update_selected_set()
        
    def reset_data(self):
        self.dataset_backup = copy.deepcopy(self.dataset)
        self.dataset = datastructure.DataSet()
        N = len(self.dataset.time_data_list)
        self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
        self.switch_view('Time Data')
        self.last_action = 'delete data'
        message = 'All data deleted.\n'
        message += 'For more data editing options select ''Edit Dataset'' tool.'
        self.show_message(message,b='undo')
#        self.selected_channels = self.p.get_selected_channels()
#        self.update_selected_set()

    
    def load_data(self):
        d = file.load_data()
        if d is not None:
            d = datastructure.update_dataset(d) # updates data saved using previous logger versions
            self.dataset.add_to_dataset(d.time_data_list)
            self.dataset.add_to_dataset(d.freq_data_list)
            self.dataset.add_to_dataset(d.tf_data_list)
            self.dataset.add_to_dataset(d.cross_spec_data_list)
            self.dataset.add_to_dataset(d.sono_data_list)
            self.dataset.add_to_dataset(d.meta_data_list)
            self.dataset.add_to_dataset(d.modal_data_list)
            
        else:
            message = 'No data loaded'
            self.show_message(message)
            return None
    
        
        no_data = True
        self.auto_xy = 'xyc'
        if len(self.dataset.time_data_list) != 0:
            self.input_list_figures.setCurrentText('Time Data')
            self.select_view()
#            self.hide_message()
            no_data = False
        if len(self.dataset.freq_data_list) != 0:
            self.input_list_figures.setCurrentText('FFT Data')
            self.select_view()
#            self.hide_message()
            no_data = False
        if len(self.dataset.tf_data_list) != 0:
            self.input_list_figures.setCurrentText('TF Data')
            self.select_view()
#            self.hide_message()
            no_data = False
        if no_data == True:
            message = 'No data to view'
            self.show_message(message)
        self.input_list_data_type.setCurrentText(self.selected_view)
        self.selected_channels = self.p.get_selected_channels()
#        self.update_selected_set()
        
        
        
            
    def save_data(self):
        filename = self.dataset.save_data()
        if filename is not None:
            message = 'Saved dataset:\n\n'
            message += self.dataset.__repr__()
            message += '\n\n'
            message += 'to file '
            message += filename
        else:
            message = 'Save dataset cancelled'
        self.show_message(message)
            
    def save_fig(self):
        if self.plot_type == 'Nyquist':
            filename = file.save_fig(self.p,figsize=(9,9))
        else:
            filename = file.save_fig(self.p,figsize=(9,5))
        if filename is not None:
            message = 'Saved current figure to file:\n'
            message += filename
        else:
            message = 'Save figure cancelled'
        self.canvas.draw()
        self.show_message(message)

    def xmin(self):
        xmin = np.float(self.input_axes[0].text())
        xlim = self.p.ax.get_xlim()
        self.p.ax.set_xlim([xmin,xlim[1]])
        if ((self.current_view == 'TF Data') or (self.current_view == 'FFT Data')) and (self.plot_type != 'Nyquist'):
            self.freq_range = list(self.p.ax.get_xlim())
        self.canvas.draw()
        
    def xmax(self):
        xmax = np.float(self.input_axes[1].text())
        xlim = self.p.ax.get_xlim()
        self.p.ax.set_xlim([xlim[0],xmax])
        if ((self.current_view == 'TF Data') or (self.current_view == 'FFT Data')) and (self.plot_type != 'Nyquist'):
            self.freq_range = list(self.p.ax.get_xlim())
        self.canvas.draw()
        
    def ymin(self):
        ymin = np.float(self.input_axes[2].text())
        ylim = self.p.ax.get_ylim()
        self.p.ax.set_ylim([ymin,ylim[1]])
        self.canvas.draw()
        
    def ymax(self):
        ymax = np.float(self.input_axes[3].text())
        ylim = self.p.ax.get_ylim()
        self.p.ax.set_ylim([ylim[0],ymax])
        self.canvas.draw()
        
    def auto_x(self):
#        self.auto_xy = 'x'
#        self.update_figure()
        self.p.auto_x()
        
    def auto_y(self):
#        self.auto_xy = 'yc'
#        self.update_figure()
        self.p.auto_y()
        
    def update_axes_values(self,axes):
#        self.selected_channels = self.p.get_selected_channels()
        xlim = self.p.ax.get_xlim()
        ylim = self.p.ax.get_ylim()
        self.input_axes[0].setText('{:0.5g}'.format(xlim[0]))
        self.input_axes[1].setText('{:0.5g}'.format(xlim[1]))
        self.input_axes[2].setText('{:0.5g}'.format(ylim[0]))
        self.input_axes[3].setText('{:0.5g}'.format(ylim[1]))
        if ((self.current_view == 'TF Data') or (self.current_view == 'FFT Data')) and (self.plot_type != 'Nyquist'):
            self.freq_range = list(xlim)
            self.input_freq_min2.setText('{:0.5g}'.format(xlim[0]))
            self.input_freq_max2.setText('{:0.5g}'.format(xlim[1]))
        
        
        if (self.current_view == 'TF Data') and (len(self.dataset.modal_data_list) > 0) and (self.selected_tool == 'Mode Fitting'):
            # Show message to highlight modal fit, to allow removing or replacing a given fit
            fn_all = self.dataset.modal_data_list[0].M[:,0]
            self.fn_in_range = fn_all[(fn_all > self.freq_range[0]) & (fn_all < self.freq_range[1])]
            if len(self.fn_in_range) > 1:
                message = 'A total of {} modes have been fitted within this frequency range so far:\n\n'.format(len(self.fn_in_range))
                message += 'Fitted mode frequencies = {} (Hz)\n\n'.format(np.array2string(self.fn_in_range,precision=2))
                message += 'To delete all of these modal fits, press ''Reject Mode''.'
                self.show_message(message)
            elif len(self.fn_in_range) == 1:
                message = 'One mode has been fitted within this frequency range:\n\n'
                message += 'Fitted mode frequency = {} Hz\n\n'.format(np.array2string(self.fn_in_range,precision=2))
                message += 'To replace this mode fit with a new fit, press ''Fit Mode''.\n'
                message += 'To delete this mode fit, press ''Reject Mode''.'
                self.show_message(message)
            else:
                self.hide_message()
        
    def legend_left(self):
        self.legend_loc = 'lower left'
        self.p.update_legend(self.legend_loc)
        self.canvas.draw()
        
    def legend_right(self):
        self.legend_loc = 'lower right'
        self.p.update_legend(self.legend_loc)
        self.canvas.draw()
            
    def legend_onoff(self):
        self.selected_channels = self.p.get_selected_channels()
        visibility = self.p.ax.get_legend().get_visible()
        self.p.ax.get_legend().set_visible(not visibility)
        self.canvas.draw()
        
        
    def update_figure(self):
        try:
            # sometimes starting point with no legend object
            visibility = self.p.ax.get_legend().get_visible()
        except:
            pass
        # updates the currently viewed plot
        if self.current_view == 'Time Data':
            data_list = self.dataset.time_data_list
        elif self.current_view == 'FFT Data':
            data_list = self.dataset.freq_data_list
        elif self.current_view == 'TF Data':
            data_list = self.dataset.tf_data_list
        elif self.current_view == 'Sono Data':
            data_list = self.dataset.sono_data_list
            
        if self.current_view == 'Sono Data':
            if self.current_view_changed == True:
                auto_xy = 'xy'
            else:
                auto_xy=''
                
            n_set = np.int(self.input_sono_n_set.text())
            n_chan = np.int(self.input_sono_n_chan.text())
            db_range = np.int(self.input_db_range.text())
            self.p.update_sonogram(self.dataset.sono_data_list, n_set, n_chan, db_range=db_range,auto_xy=auto_xy)
            self.label_figure.setText(self.selected_view + ': Set {}, Channel {}'.format(n_set,n_chan))
        else:
            self.p.update(data_list, sets=self.sets, channels=self.channels, xlinlog=self.xlinlog,show_coherence=self.show_coherence,plot_type=self.plot_type,coherence_plot_type=self.coherence_plot_type,freq_range=self.freq_range,auto_xy=self.auto_xy)
            self.label_figure.setText(self.selected_view)
        if self.current_view_changed == False:
            try:
                # not robust as not consistent in keeping up to date
                # if only one data set then make sure it's visible
                if len(data_list) == 1:
                    selection = self.p.get_selected_channels()
                    for nc in range(len(selection[0])):
                        selection[0][nc] = True
                    self.selected_channels = selection
                # otherwise just inherit prev data selection
                self.p.set_selected_channels(self.selected_channels)
                self.p.ax.get_legend().set_visible(visibility)
                self.fig.canvas.draw()
            except:
                # get selected_channels back into sync
                self.selected_channels = self.p.get_selected_channels()
        
                   
    def update_selected_channels(self,_):
        self.selected_channels = self.p.get_selected_channels()
        
    def select_all_data(self):
        if len(self.p.ax.lines) > 0:
            for line in self.p.ax.lines:
                line.set_alpha(plotting.LINE_ALPHA)
            for line in self.p.legend.get_lines():
                line.set_alpha(plotting.LINE_ALPHA)
            self.canvas.draw()
        else:
            message = 'No data to show.'
            self.show_message(message)
        self.selected_channels = self.p.get_selected_channels()
        
        
        
    def select_no_data(self):
        if len(self.p.ax.lines) > 0:
            for line in self.p.ax.lines:
                line.set_alpha(1-plotting.LINE_ALPHA)
            for line in self.p.legend.get_lines():
                line.set_alpha(1-plotting.LINE_ALPHA)
            self.canvas.draw()
        else:
            message = 'No data to hide.'
            self.show_message(message)
        self.selected_channels = self.p.get_selected_channels()
            
    def show_set_only(self):
        n_set = np.int(self.input_select_set_only.text())
        selection = self.p.get_selected_channels()
        for ns in range(len(selection)):
            for nc in range(len(selection[ns])):
                if ns == n_set:
                    selection[ns][nc] = True
                else:
                    selection[ns][nc] = False
        self.p.set_selected_channels(selection)
        self.selected_channels = selection
        
    def show_chan_only(self):
        n_chan = np.int(self.input_select_chan_only.text())
        selection = self.p.get_selected_channels()
        for ns in range(len(selection)):
            for nc in range(len(selection[ns])):
                if nc == n_chan:
                    selection[ns][nc] = True
                else:
                    selection[ns][nc] = False
        self.p.set_selected_channels(selection)
        self.selected_channels = selection
        
    def next_chans(self):
        try:
            # sometimes starting point with no legend object
            visibility = self.p.ax.get_legend().get_visible()
        except:
            pass
        
        selection = self.p.get_selected_channels()
        prev_line = bool(selection[-1][-1])
        for ns in range(len(selection)):
            for nc in range(len(selection[ns])):
                this_line = bool(selection[ns][nc])
                selection[ns][nc] = bool(prev_line)
                prev_line = bool(this_line)
        
        self.p.set_selected_channels(selection)
        self.selected_channels = selection
        try:
            self.p.ax.get_legend().set_visible(visibility)
            self.fig.canvas.draw()
        except:
            pass
        
    def prev_chans(self):
        try:
            # sometimes starting point with no legend object
            visibility = self.p.ax.get_legend().get_visible()
        except:
            pass
        selection = self.p.get_selected_channels()
        prev_line = bool(selection[0][0])
        for ns in reversed(range(len(selection))):
            for nc in reversed(range(len(selection[ns]))):
                this_line = bool(selection[ns][nc])
                selection[ns][nc] = bool(prev_line)
                prev_line = bool(this_line)
        
        self.p.set_selected_channels(selection) 
        self.selected_channels = selection
        try:
            self.p.ax.get_legend().set_visible(visibility)
            self.fig.canvas.draw()
        except:
            pass

           
        
    def co_min(self):
        co_min = np.float(self.input_co_min.text())
        ylim = self.p.ax2.get_ylim()
        self.p.ax2.set_ylim([co_min,ylim[1]])
        self.canvas.draw()
    
    def co_max(self):
        co_max = np.float(self.input_co_max.text())
        ylim = self.p.ax2.get_ylim()
        self.p.ax2.set_ylim([ylim[0],co_max])
        self.canvas.draw()
        
    def freq_min(self):
        self.freq_range[0] = np.float(self.input_freq_min.text())
        self.input_freq_min2.setText(str(self.freq_range[0]))
        self.update_figure()
#        self.p.update(self.dataset.tf_data_list, xlinlog=self.xlinlog, show_coherence=self.show_coherence,plot_type=self.plot_type,coherence_plot_type=self.coherence_plot_type,freq_range=self.freq_range,auto_xy=self.auto_xy)
        
    def freq_max(self):
        self.freq_range[1] = np.float(self.input_freq_max.text())
        self.input_freq_max2.setText(str(self.freq_range[1]))
        self.update_figure()
#        self.p.update(self.dataset.tf_data_list, xlinlog=self.xlinlog, show_coherence=self.show_coherence,plot_type=self.plot_type,coherence_plot_type=self.coherence_plot_type,freq_range=self.freq_range,auto_xy=self.auto_xy)
        
    def update_co_axes_values(self,axes):
        ylim = self.p.ax2.get_ylim()
        self.input_co_min.setText('{:0.5g}'.format(ylim[0]))
        self.input_co_max.setText('{:0.5g}'.format(ylim[1]))
        
    def data_toggle(self):
        self.show_data = not self.show_data
        self.select_view()
        for line in self.p.ax.lines:
            line.set_visible(self.show_data)
        if self.show_data == False:
            self.p.ax.set_ylabel('')
            self.p.ax.set_yticks([])
        else:
            self.p.ax.yaxis.set_major_locator(AutoLocator())
            
        self.canvas.draw()

    def coherence_toggle(self):
        self.show_coherence = not self.show_coherence
        self.select_view()
                
        
    def select_xlinlog(self):
        if self.xlinlog == 'linear':
            self.xlinlog = 'log' # or symlog
        else:
            self.xlinlog = 'linear'
        
        self.update_figure()
    
    def switch_view(self,new_view_text):
        index = self.input_list_figures.findText(new_view_text, Qt.MatchFixedString)
        if self.input_list_figures.itemText(index) == 'Time Data':
            N = len(self.dataset.time_data_list)
        elif self.input_list_figures.itemText(index) == 'FFT Data':
            N = len(self.dataset.freq_data_list)
        elif self.input_list_figures.itemText(index) == 'TF Data':
            N = len(self.dataset.tf_data_list)
        elif self.input_list_figures.itemText(index) == 'Sono Data':
            N = len(self.dataset.sono_data_list)
        if N > 0:
            self.input_list_figures.setCurrentIndex(index)
            self.input_list_data_type.setCurrentText(self.input_list_figures.currentText())
            
        self.select_view()
        
    def select_view(self):
        # handles logic of what to show in gui depending on selected view options
        ci = self.input_list_figures.currentIndex()
        self.selected_view = self.input_list_figures.itemText(ci)
        
        if self.current_view == self.selected_view:
            self.current_view = np.copy(self.selected_view)
            self.current_view_changed = False
            self.plot_type_before = self.plot_type
            self.plot_type = self.items_list_plot_type[self.input_list_plot_type.currentIndex()]
            self.switch_to_nyquist = (self.plot_type == 'Nyquist') and ('Nyquist' != self.plot_type_before)
            self.switch_from_nyquist = (self.plot_type_before == 'Nyquist') and ('Nyquist' != self.plot_type)
#            self.selected_channels = self.p.get_selected_channels()
        else:
            self.current_view_changed = True
        
        # Time Data
        if self.selected_view == 'Time Data':
            ### set to time gui
            N = len(self.dataset.time_data_list)
            # check if any data present to display
            if N != 0:
                # no plot details needed for time display
                self.hide_plot_details()
                # reset data/coherence plot properties if changed view back to time
                if self.current_view_changed:
                    self.current_view = self.selected_view
                    self.show_data = True
                    self.show_coherence = True # won't plot but reests for other selections
                    self.xlinlog = 'linear'
                    self.auto_xy = 'xyc'
                    self.plot_type = 'Amplitude (dB)'
                    self.input_list_plot_type.setCurrentText(self.plot_type)
                    
                # plot
                self.update_figure()
                
            # show message if no data
            else:
                message = 'No time data to display.\n'
                self.show_message(message)
                
        # FFT Data
        elif self.selected_view == 'FFT Data':
            N = len(self.dataset.freq_data_list)
            # check if freq data exists
            if N != 0:
                # if main view changed reset plot properties
                if self.current_view_changed:
                    self.current_view = self.selected_view
                    self.show_data = True
                    self.show_coherence = True # won't plot but reests for other selections
                    self.auto_xy = 'xyc'
                    self.plot_type = 'Amplitude (dB)'
                    self.input_list_plot_type.setCurrentText(self.plot_type)
                    
                
                # if staying as FFT plot but changing to nyquist then switch to FFT Nyquist toolset
                elif self.switch_to_nyquist == True:
                    # get properties before switch so can go back to this view
                    self.freq_range = list(self.p.ax.get_xlim()) #force to list instead of tuple
                    self.show_coherence_before = self.show_coherence
                    self.show_coherence = False
                    self.xlinlog_before = self.xlinlog
                    # linear x axis for nyquist
                    self.xlinlog = 'linear'
                    # update freq range text
                    self.input_freq_min.setText('{:5f}'.format(self.freq_range[0]))
                    self.input_freq_max.setText('{:5f}'.format(self.freq_range[1]))
                    self.auto_xy = 'xy'
                    
                    
                # if moving from nyquist back, reset properties to previous
                elif self.switch_from_nyquist == True:
                    self.show_coherence = self.show_coherence_before
                    self.xlinlog = self.xlinlog_before
                    # freq range already set above as must have moved to nyquist first
                    self.auto_xy = 'fy'
                    
                else:
                    # update freq range if switching plot other than to/from nyquist
                    self.freq_range = list(self.p.ax.get_xlim()) # force to list instead of tuple
                    self.auto_xy = 'fy'
                    
                    
                # always reset figure heading
                self.label_figure.setText(self.selected_view)
                                
                # set gui to correct toolset
                if self.plot_type == 'Nyquist':
                    self.auto_xy = 'xy'
                    self.show_plot_details_with_nqyuist()
                else:
                    self.show_plot_details_basic()
                    
                self.update_figure()

                
            # show message if no data to plot
            else:
                message = 'No FFT data to display.\n'
                self.show_message(message)
        
        # TF Data
        elif self.selected_view == 'TF Data':
            N = len(self.dataset.tf_data_list)
            # check if data to plot
            if N != 0:
                # if main view changed reset plot properties
                if self.current_view_changed:
                    self.current_view = self.selected_view
                    self.show_data = True
                    self.show_coherence = True 
                    self.auto_xy = 'xyc'
                    self.plot_type = 'Amplitude (dB)'
                    self.input_list_plot_type.setCurrentText(self.plot_type)
                
                # if staying as TF plot but changing to nyquist then switch to TF Nyquist toolset
                elif self.switch_to_nyquist == True:
                    # get properties before switch so can go back to this view
                    self.freq_range = list(self.p.ax.get_xlim()) #force to list instead of tuple
                    self.show_coherence_before = self.show_coherence
                    self.show_coherence = False
                    self.xlinlog_before = self.xlinlog
                    # linear x axis for nyquist
                    self.xlinlog = 'linear'
                    # update freq range text
                    self.input_freq_min.setText('{:0.5g}'.format(self.freq_range[0]))
                    self.input_freq_max.setText('{:0.5g}'.format(self.freq_range[1]))
                    self.auto_xy = 'xy'
                
                # if moving from nyquist back, reset properties to previous
                elif self.switch_from_nyquist == True:
                    self.show_coherence = self.show_coherence_before
                    self.xlinlog = self.xlinlog_before
                    self.auto_xy = 'fy'
                    # freq range already set above as must have moved to nyquist first
            
                else:
                    # update freq range if switching plot other than to/from nyquist
                    self.freq_range = list(self.p.ax.get_xlim()) # force to list instead of tuple
                    self.auto_xy = 'fy'

                # plot now then auto-x/y according to nyquist or not
                self.update_figure()

                    
                # set gui to correct toolset
                self.label_figure.setText(self.selected_view)
                if self.plot_type == 'Nyquist':
                    self.show_plot_details_with_nqyuist()
                else:
                    self.show_plot_details_with_coherence()
                    
            # show message if no data
            else:
                message = 'No transfer function data to display.\n'
                self.show_message(message)
            
        elif self.selected_view == 'Sono Data':
             ### set to time gui
            N = len(self.dataset.sono_data_list)
            # check if any data present to display
            if N != 0:
                # no plot details needed for sonogram display
                self.hide_plot_details()
                # reset data/coherence plot properties if changed view back to time
                if self.current_view_changed:
                    self.current_view = self.selected_view
                    self.show_data = True
                    self.show_coherence = True # won't plot but reests for other selections
                    self.xlinlog = 'linear'
                    self.auto_xy = 'xyc'
                    self.plot_type = 'Amplitude (dB)'
                    self.input_list_plot_type.setCurrentText(self.plot_type)
                    
                # plot
                self.update_figure()
                
            # show message if no data
            else:
                message = 'No sonogram data to display'
                self.show_message(message)
            
            
        
    def hide_plot_details(self):
        self.frame_plot_details.setVisible(False)
        
    def show_plot_details_with_coherence(self):
        # Put Falses before Trues
        self.input_freq_min.setVisible(False)
        self.input_freq_max.setVisible(False)        

        self.button_xlinlog.setVisible(True)
        self.button_data_toggle.setVisible(True)
        self.button_coherence_toggle.setVisible(True)
        self.label_co_freq_min.setVisible(True)
        self.label_co_freq_max.setVisible(True)
        self.label_co_freq_min.setText('co. min:')
        self.label_co_freq_max.setText('co. max:')
        
        self.input_co_min.setVisible(True)
        self.input_co_max.setVisible(True)
        
        self.frame_plot_details.setVisible(True)
        
        
    def show_plot_details_with_nqyuist(self):
        # Put Falses before Trues
        self.button_xlinlog.setVisible(False)
        self.button_data_toggle.setVisible(False)
        self.button_coherence_toggle.setVisible(False)
        self.input_co_min.setVisible(False)
        self.input_co_max.setVisible(False)
        
        self.label_co_freq_min.setVisible(True)
        self.label_co_freq_max.setVisible(True)
        self.label_co_freq_min.setText('freq. min:')
        self.label_co_freq_max.setText('freq. max:')
        
        self.input_freq_min.setVisible(True)
        self.input_freq_max.setVisible(True)

        self.frame_plot_details.setVisible(True)
        
        
    def show_plot_details_basic(self):
        # put Falses before Trues
        self.button_data_toggle.setVisible(False)
        self.button_coherence_toggle.setVisible(False)
        self.label_co_freq_min.setVisible(False)
        self.label_co_freq_max.setVisible(False)
        
        self.input_co_min.setVisible(False)
        self.input_co_max.setVisible(False)
        self.input_freq_min.setVisible(False)
        self.input_freq_max.setVisible(False)
        
        self.button_xlinlog.setVisible(True)
        self.frame_plot_details.setVisible(True)
        
    def hide_all_tools(self):
        self.frame_tools_time_domain.setVisible(False)
        self.frame_tools_fft.setVisible(False)
        self.frame_tools_tf.setVisible(False)
        self.frame_tools_scaling.setVisible(False)
        self.frame_tools_mode_fitting.setVisible(False)
        self.frame_tools_settings.setVisible(False)
        self.frame_tools_generate_output.setVisible(False)
        self.frame_tools_edit_dataset.setVisible(False)
        self.frame_tools_sonogram.setVisible(False)
#        self.frame_tools_save_export.setVisible(False)
        
    def select_tool(self):
        self.selected_tool = self.input_list_tools.currentText()
        if self.selected_tool == 'Standard Tools':
            self.hide_all_tools()
            self.frame_tools_time_domain.setVisible(True)
            self.frame_tools_fft.setVisible(True)
            self.frame_tools_tf.setVisible(True)
            self.frame_tools_scaling.setVisible(True)
            
            
        elif self.selected_tool == 'Logger Settings':
            self.hide_all_tools()
            self.frame_tools_settings.setVisible(True)
            
        elif self.selected_tool == 'Generate Output':
            self.hide_all_tools()
            self.frame_tools_generate_output.setVisible(True)
            
        elif self.selected_tool == 'Pre-process':
            self.hide_all_tools()
            self.frame_tools_time_domain.setVisible(True)
            
        elif self.selected_tool == 'FFT':
            self.hide_all_tools()
            self.frame_tools_fft.setVisible(True)
            
        elif self.selected_tool == 'Transfer Function':
            self.hide_all_tools()
            self.frame_tools_tf.setVisible(True)
            
        elif self.selected_tool == 'Calibration / Scaling':
            self.hide_all_tools()
            self.frame_tools_scaling.setVisible(True)
            
        elif self.selected_tool == 'Sonogram':
            self.hide_all_tools()
            self.frame_tools_sonogram.setVisible(True)
            
        elif self.selected_tool == 'Mode Fitting':
            self.hide_all_tools()
            self.frame_tools_mode_fitting.setVisible(True)
            
        elif self.selected_tool == 'Edit Dataset':
            self.hide_all_tools()
            self.auto_xy = ''
            self.update_selected_set()
            self.frame_tools_edit_dataset.setVisible(True)

            
        elif self.selected_tool == 'Save / Export':
            self.hide_all_tools()
            self.frame_tools_save_export.setVisible(True)
            
    def apply_settings(self):
        settings_dict = dict()
        for n_row in range(13):
            label = self.labels_settings[n_row]
            text = self.input_settings[label].text()
            settings_dict[label] = text
        self.settings_dict = settings_dict
        self.settings = options.MySettings(**settings_dict)
        self.test_name = self.input_test_name.text()
        if self.test_name == '':
            self.test_name = None
        self.start_stream()
            
    
    def show_available_devices(self):
        message = streams.list_available_devices()
        self.show_message(message)

    def update_selected_set(self):
        data_type = self.input_list_data_type.currentText()
        if data_type == 'Time Data':
            self.data_list = self.dataset.time_data_list
            self.switch_view(data_type)
        elif data_type == 'FFT Data':
            self.data_list = self.dataset.freq_data_list
            self.switch_view(data_type)
        elif data_type == 'TF Data':
            self.data_list = self.dataset.tf_data_list
            self.switch_view(data_type)
        elif data_type == 'Modal Data':
            self.data_list = self.dataset.modal_data_list
        elif data_type == 'Sono Data':
            self.data_list = self.dataset.sono_data_list
        else:
            self.data_list = []
        
        self.update_data_summary()
        
    def update_data_summary(self):
        # also keeps validator up to date
        N = len(self.data_list)
        self.input_selected_set.setValidator(QIntValidator(0,N-1))
        text = self.dataset.__repr__()
        self.label_data_summary.setText(text)

    def delete_data_type(self):
        self.auto_xy = ''
        self.update_selected_set()
        if len(self.data_list) != 0:
            self.dataset_backup = copy.deepcopy(self.dataset)
            self.data_type = self.data_list[0].__class__.__name__
            self.dataset.remove_data_item_by_index(self.data_type,np.arange(len(self.data_list)))
            self.last_action = 'delete data'
            message = 'All {} items deleted.\n\n'.format(self.data_type)
            self.show_message(message, b='undo')
        else:
            message = 'No {} to delete.'.format(self.data_typye)
            self.show_message(message)
        self.update_selected_set()
            
    
    def delete_data_set(self):
        self.auto_xy = ''
        self.selected_set = np.int(self.input_selected_set.text())
        if len(self.data_list) != 0:
            self.dataset_backup = copy.deepcopy(self.dataset)
            self.data_type = self.data_list[0].__class__.__name__
            self.dataset.remove_data_item_by_index(self.data_type,self.selected_set)
            self.last_action = 'delete data'
            message = 'Set {} of type {} deleted.'.format(self.selected_set,self.data_type)
            self.show_message(message, b='undo')
        else:
            message = 'No {} to delete.'.format(self.data_typye)
            self.show_message(message)
        self.update_selected_set()
    
    def log_and_replace(self):
        self.auto_xy = ''
        self.dataset_backup = copy.deepcopy(self.dataset)
        self.selected_set = np.int(self.input_selected_set.text())
        self.flag_log_and_replace = True
        self.button_clicked_log_data()
        
#        ### DUPLICATES button_clicked_log_data FUNCTION SO THAT MESSAGE APPEARS ###
#        if self.rec is None:
#            self.start_stream()
#        self.rec.trigger_detected = False
#        self.button_log_data.setStyleSheet("background-color: white")
#        if self.settings.pretrig_samples is None:
#            message = 'Logging data for {} seconds'.format(self.settings.stored_time)
#        else:
#            message = 'Logging data for {} seconds, with trigger'.format(self.settings.stored_time)
#        self.thread = LogDataThread(self.settings,test_name=self.test_name, rec=self.rec)
#        self.show_message(message,'cancel')
#        self.thread.start()
#        self.thread.s.connect(self.add_logged_data)
        ###########################################################################
    
    def update_output(self):
        sig = self.input_output_options.currentText()
        if sig == 'None':
            self.flag_output = False
        else:
            self.flag_output = True
            
    def create_output_signal(self):
        sig = self.input_output_options.currentText()
        T = np.float(self.input_output_duration.text())
        amp = np.float(self.input_output_amp.text())
        f1 = np.float(self.input_output_f1.text())
        f2 = np.float(self.input_output_f2.text())
        f_max = np.max([f1,f2])
        fs_min = np.min([self.settings.fs,self.settings.output_fs])
            
        if sig != 'None':
            if f_max > fs_min/2:
                message = 'Highest output frequency {} Hz exceeds input or output sampling frequency {} Hz.'.format(f_max,fs_min)
                self.show_message(message)
                td = None
            else:
                t,y = acquisition.signal_generator(self.settings,sig=sig,T=T,amplitude=amp,f=[f1,f2],selected_channels='all')
                td = datastructure.TimeData(t,y,self.settings,test_name='output_signal')
                message = acquisition.MESSAGE
                self.show_message(message)
        else:
            td = None
#            message = 'Output signal turned off.'
#            self.show_message(message)         
        self.output_time_data = td
            
    def preview_output(self):
        self.create_output_signal()
        if self.output_time_data != None:
            d = datastructure.DataSet(self.output_time_data)
            d.calculate_fft_set()
            self.preview_window = PreviewWindow(title='Time Data')
            self.preview_window.p.update(d.time_data_list,auto_xy='xy')
            self.preview_window2 = PreviewWindow(title='FFT Data')
            self.preview_window2.p.update(d.freq_data_list, xlinlog='log',auto_xy='xy')
    
    def start_output(self):
        self.create_output_signal()
        if self.output_time_data != None:
            s = acquisition.output_signal(self.settings,self.output_time_data.time_data)
        else:
            message = 'No output data to generate.'
            self.show_message(message)
            

    #%% DATA PROCESSING
    def clean_impulse(self):
        try:
            ch_impulse = np.int(self.input_impulse_channel.text())
            
            dataset_new = self.dataset.clean_impulse(ch_impulse=ch_impulse)
            
            if 'data already cleaned' not in analysis.MESSAGE:
                # only make backup if first time cleaned, otherwise backup no longer contains original data
                self.dataset_backup = self.dataset
            self.dataset = dataset_new
            self.show_message(analysis.MESSAGE,b='undo')
            self.last_action = 'clean_impulse'
            self.auto_xy = ''
            selection = self.p.get_selected_channels()
            self.update_figure()
            self.p.set_selected_channels(selection)
        except:
            analysis.MESSAGE = 'Clean impulse not successful, no change made.\n'
            analysis.MESSAGE += 'Check if ch_{} exists for each set of data.'.format(ch_impulse)
            self.show_message(analysis.MESSAGE,b='ok')
            
            
    def undo_last_action(self):
        if self.last_action == 'clean_impulse':
            self.dataset = self.dataset_backup
            self.update_figure()
        if self.last_action == 'scaling':
            self.dataset = self.dataset_backup
            self.update_figure()
        if self.last_action == 'delete modes':
            self.dataset = self.dataset_backup
            self.selected_channels = self.selected_channels_backup
            self.update_figure()
            message = 'Deleted mode fits restored.'
            self.show_message(message)
        if self.last_action == 'delete data':
            self.dataset = self.dataset_backup
            self.update_figure()
            message = 'Deleted data restored.'
            self.show_message(message)
        if self.last_action == 'data replaced':
            self.dataset = self.dataset_backup
            self.update_figure()
            message = 'Replaced data restored.'
            self.show_message(message)
            
    def calc_fft(self):
        if len(self.dataset.time_data_list) == 0:
            message = 'No time data to calculate transfer function.'
            self.show_message(message)
        
        else:
            window = self.input_list_window_fft.currentText()
            if window == 'None':
                window = None
            
            self.dataset.calculate_fft_set(window=window)
            self.switch_view('FFT Data')
            
    def select_averaging_type(self):
        self.averaging_method = self.input_list_average_TF.currentText()
        if self.averaging_method == 'None':
            self.input_Nframes.setText('1')
            self.slider_Nframes.setValue(1)
            self.label_Nframes.setVisible(False)
            self.input_Nframes.setVisible(False)
            self.slider_Nframes.setVisible(False)
            self.label_Nframes_time.setVisible(False)
            self.button_TFav.setVisible(False)
            self.button_TF.setVisible(True)
            
        elif self.averaging_method == 'within each set':
            self.button_TFav.setVisible(False)
            self.button_TF.setVisible(True)
            self.label_Nframes.setVisible(True)
            self.input_Nframes.setVisible(True)
            self.label_Nframes_time.setVisible(True)
            self.slider_Nframes.setVisible(True)
            
        elif self.averaging_method == 'across sets':
            self.button_TF.setVisible(False)
            self.label_Nframes.setVisible(False)
            self.input_Nframes.setVisible(False)
            self.slider_Nframes.setVisible(False)
            self.label_Nframes_time.setVisible(False)
            self.button_TFav.setVisible(True)
            
    def refresh_Nframes_text(self):
        self.N_frames = self.slider_Nframes.value()
        self.input_Nframes.setText(str(self.N_frames))
        if len(self.dataset.time_data_list)>0:
            stored_time = self.dataset.time_data_list[0].settings.stored_time
            text = "Frame length = {:.2f} seconds.".format(stored_time/(self.N_frames-self.overlap*self.N_frames+self.overlap))
        else:   
            text = 'No time data'
        self.label_Nframes_time.setText(text)
        
        
    def refresh_Nframes_slider(self):
        self.N_frames = np.int(self.input_Nframes.text())
        # allows setting text to higher than max slider
        try:
            self.slider_Nframes.setValue(self.N_frames)
        except:
            pass
        if len(self.dataset.time_data_list)>0:
            stored_time = self.dataset.time_data_list[0].settings.stored_time
            text = "Frame length = {:.2f} seconds.".format(stored_time/(self.N_frames-self.overlap*self.N_frames+self.overlap))
        else:   
            text = 'No time data'
        self.label_Nframes_time.setText(text)
        
        
    def refresh_test_name(self):
        # keep both places for entering test_name up to date
        self.input_test_name2.setText(self.input_test_name.text())
        self.test_name = self.input_test_name.text()
        
    def refresh_test_name2(self):
        # keep both places for entering test_name up to date
        self.input_test_name.setText(self.input_test_name2.text())
        self.test_name = self.input_test_name2.text()
        
    def calc_tf(self):
        if len(self.dataset.time_data_list) == 0:
            message = 'No time data to calculate transfer function.'
            self.show_message(message)
        
        else:
            self.N_frames = np.int(self.input_Nframes.text())
            window = self.input_list_window_tf.currentText()
            if window == 'None':
                window = None

            self.dataset.calculate_tf_set(window=window,N_frames=self.N_frames,overlap=self.overlap)
            if self.current_view != 'TF Data':
                self.switch_view('TF Data')
            else:
                self.auto_xy = ''
                self.update_figure()
            
    
    def calc_tf_av(self,b):
        if len(self.dataset.time_data_list) == 0:
            message = 'No data to calculate FFT.'
            self.show_message(message)
        
        else:
            window = self.input_list_window_tf.currentText()
            if window == 'None':
                window = None
        
            self.dataset.calculate_tf_averaged(window=window)
            
            if self.current_view != 'TF Data':
                self.switch_view('TF Data')
            else:
                self.auto_xy = ''
                self.update_figure()
        
    def xiw(self):
        power = 1
        self.xiwp(power)
        
    def diw(self):
        power = -1
        self.xiwp(power)


        
    def xiwp(self,power):
        if self.flag_scaling == False:
                # create backup before any changes made - used to reset
                self.dataset_backup = copy.deepcopy(self.dataset)
                
        if self.current_view == 'FFT Data':
            data_list = self.dataset.freq_data_list
        elif self.current_view == 'TF Data':
            data_list = self.dataset.tf_data_list
        else:
            message = 'First select ''FFT Data'' or ''TF Data''.'
            self.show_message(message)
            return None
        
        if len(data_list) > 0:            
            s = self.p.get_selected_channels()
            if self.selected_channels != s:
                # reset gui's iw_power record if changed selection
                self.iw_fft_power = 0
                self.selected_channels = s
                
            
            for ns in range(len(s)):
                newdata = analysis.multiply_by_power_of_iw(data_list[ns],power=power,channel_list=s[ns])
                data_list[ns] = newdata
                self.flag_scaling = True
                
            if data_list.__class__.__name__ == 'FreqData':
                self.dataset.freq_data_list = data_list
            elif data_list.__class__.__name__ == 'TfData':
                self.dataset.tf_data_list = data_list
            
            
            if self.plot_type == 'Nyquist':
                self.auto_xy = 'xy'
            else:
                self.auto_xy = 'y'
            
            self.update_figure()
            self.p.set_selected_channels(s)
            
            self.iw_fft_power += power # local counter for currently selected channels
            self.last_action = 'scaling'
            message = 'Selected FFT data multiplied by (iw)**{}\n'.format(self.iw_fft_power)
            message += '(note that power counter resets when selection changes)'
            self.show_message(message)
        else:
            message = 'First calculate FFT or TF of data.'
            self.show_message(message)
        
    def undo_scaling(self):
        if self.last_action == 'scaling':
            self.undo_last_action()
            self.flag_scaling = False
            message = 'Scaling removed.'
        else:
            message = 'Can''t undo: scaling not last action carried out.'
        
        self.show_message(message)
        
        
    def best_match(self):
        if self.flag_scaling == False:
            # provide backup for undo
            self.dataset_backup = copy.deepcopy(self.dataset)
            self.flag_scaling = True
            
        self.refset  = np.int(self.input_refset.text())
        self.refchan = np.int(self.input_refchan.text())
        if self.current_view == 'TF Data':
            current_calibration_factors = self.dataset.tf_data_list.get_calibration_factors()
            reference = current_calibration_factors[self.refset][self.refchan]
            factors = analysis.best_match(self.dataset.tf_data_list,freq_range=self.freq_range,set_ref=self.refset,ch_ref=self.refchan)
            factors = [reference*x for x in factors]
            self.dataset.tf_data_list.set_calibration_factors_all(factors)
            self.auto_xy = ''
            self.update_figure()
            with np.printoptions(precision=3, suppress=False):
                message = 'Scale factors:\n'
                n_set = -1
                self.factors = factors
                for fs in factors:
                    n_set += 1
#                    message += 'Set {:>10:d}: factors = {:.5g}\n'.format(n_set,np.squeeze(fs))
#                    [[fill]align][sign][#][0][minimumwidth][.precision][type]
                    message += '{:<3} {:>4} {:<12} {}\n'.format('Set',n_set,': factors =',np.squeeze(fs))
                self.show_message(message)
            
            self.last_action = 'scaling'
            
        else:
            message = 'First select ''TF Data'' or ''Calc TF''.'
            self.show_message(message)
        
    def fit_mode(self):
        if self.current_view == 'TF Data':
            if self.input_list_tf_type.currentText() == 'Acceleration':
                self.measurement_type = 'acc'
            elif self.input_list_tf_type.currentText() == 'Velocity':
                self.measurement_type = 'vel'
            elif self.input_list_tf_type.currentText() == 'Displacement':
                self.measurement_type = 'dsp'
                
            m = modal.modal_fit_all_channels(self.dataset.tf_data_list,freq_range=self.freq_range, measurement_type=self.measurement_type)
            self.last_mode_fit = m
            self.show_message(modal.MESSAGE)
            if len(self.dataset.modal_data_list) == 0:
                self.dataset.modal_data_list = [m]
            elif len(self.fn_in_range) > 1:
                message = 'Several mode fits already in this range.\n\n'
                message += 'Fitted mode frequencies = {} (Hz)\n\n'.format(np.array2string(self.fn_in_range,precision=2))
                message += 'To delete them, press ''Reject''.'
                message += 'To replace a single fit, zoom into a single peak first.'
                self.show_message(message)
                return None
            elif len(self.fn_in_range) == 1:
                # find which mode and replace it
                fn_all = self.dataset.modal_data_list[0].M[:,0]
                mode_number = np.where((fn_all > self.freq_range[0]) & (fn_all < self.freq_range[1]))[0]
                self.dataset.modal_data_list[0].delete_mode(mode_number)
                self.dataset.modal_data_list[0].add_mode(m.M[0,:]) # only one mode in 'm'
            else:
                self.dataset.modal_data_list[0].add_mode(m.M[0,:]) # only one mode in 'm'
            
            # local reconstruction
            s = self.selected_channels # keep selection after auto-range
            
            f = np.linspace(self.freq_range[0],self.freq_range[1],3000)
            tf_data = modal.reconstruct_transfer_function(m,f,self.measurement_type)
            tf_data.flag_modal_TF = True
            self.dataset.tf_data_list.add_modal_reconstruction(tf_data,mode='replace')
            
            if self.plot_type == 'Nyquist':
                self.auto_xy = 'xy'
            else:
                self.auto_xy = 'fy'
                
            self.update_figure()
            s2 = self.p.get_selected_channels()
            for i in range(len(s2[-1])):
                s2[-1][i] = True
            if len(s) != len(s2):
                s += [[]]
            s[-1] = s2[-1]
            self.p.set_selected_channels(s) # keep selection after auto-range
            self.update_figure() # run a second time so autoscaling picks up new lines
            fn_all = self.dataset.modal_data_list[0].M[:,0]
            self.fn_in_range = m.fn
        else:
            message = 'First select ''TF Data''.'
            self.show_message(message)
            
    
    def freq_min2(self):
        self.freq_range[0] = np.float(self.input_freq_min2.text())
        self.input_freq_min.setText(str(self.freq_range[0]))
        self.freq_min()
    
    def freq_max2(self):
        self.freq_range[1] = np.float(self.input_freq_max2.text())
        self.input_freq_max.setText(str(self.freq_range[1]))
        self.freq_max
        
    def accept_mode(self):
        self.dataset.modal_data_list
        self.view_modal_reconstruction()
        
    
    def reject_mode(self):
        # reject mode fits currently in view
        if len(self.fn_in_range) >= 1:
            self.last_action = 'delete modes'
            self.dataset_backup = copy.deepcopy(self.dataset)
            self.selected_channels_backup = self.p.get_selected_channels()
            # find which mode and replace it
            fn_all = self.dataset.modal_data_list[0].M[:,0]
            mode_number = np.where((fn_all > self.freq_range[0]) & (fn_all < self.freq_range[1]))[0]
            self.dataset.modal_data_list[0].delete_mode(mode_number)
            if self.dataset.tf_data_list[-1].flag_modal_TF == True:
                self.dataset.remove_last_data_item('TfData')
                self.selected_channels.pop(-1) # updates selected channels
                self.update_figure()
            message = 'Mode fits deleted.'
            self.show_message(message,b='undo')
        
    def view_mode_summary(self):
        message = 'Modes fitted:\n\n'
        message += 'fn = {} (Hz)\n\n'.format(np.array2string(self.dataset.modal_data_list[0].fn,precision=2))
        message += 'zn = {} (Hz)'.format(np.array2string(self.dataset.modal_data_list[0].zn,precision=5))
        self.show_message(message)
    
    def view_modal_reconstruction(self):
        # Global reconstruction
        s = self.p.get_selected_channels() # keep selection after auto-range
        
        f = self.dataset.tf_data_list[0].freq_axis
        m = self.dataset.modal_data_list[0]
        tf_data = modal.reconstruct_transfer_function_global(m,f,self.measurement_type)
        tf_data.flag_modal_TF = True
        self.dataset.tf_data_list.add_modal_reconstruction(tf_data,mode='replace')
        
        self.update_figure()
        s2 = self.p.get_selected_channels()
        for i in range(len(s2[-1])):
            s2[-1][i] = True
        if len(s) != len(s2):
            s += [[]]
        s[-1] = s2[-1]
        self.p.set_selected_channels(s) # keep selection after auto-range
        self.fn_in_range = m.fn
        
    def refresh_sono_N_frames_slider(self):
        self.slider_sono_N_frames.setValue(np.int(self.input_sono_N_frames.text()))
    
    def refresh_sono_N_frames_text(self):
        self.input_sono_N_frames.setText(str(self.slider_sono_N_frames.value()))
    
    def calc_sono(self):
        if len(self.dataset.time_data_list) == 0:
            message = 'No time data to calculate transfer function.'
            self.show_message(message)
        else:
            self.N_frames_sono = np.int(self.input_sono_N_frames.text())
            n_set = np.int(self.input_sono_n_set.text())
            n_chan = np.int(self.input_sono_n_chan.text())
#            db_range = np.int(self.input_db_range.text())
            NT = len(self.dataset.time_data_list[n_set].time_data[:,n_chan])
            f = 1/4 # match overlap in sonogram
            print(1)
            self.nperseg = np.int(NT // (self.N_frames_sono * (1-f) + f)) # 1/8 is default overlap for spectrogram
            print(2)
            self.dataset.calculate_sono_set(nperseg=self.nperseg)
            
            # calc sonogram info
            npfft,npt = np.shape(self.dataset.sono_data_list[n_set].sono_data[:,:,n_chan])
            text = 'FFT length: {}\n'.format(self.nperseg)
            text += 'Freq resolution: {:5g} (Hz)\n'.format(np.diff(self.dataset.sono_data_list[n_set].freq_axis[[0,1]])[0])
            
            self.sono_info.setText(text)
            if self.current_view != 'Sono Data':
                self.switch_view('Sono Data')
            self.update_figure()
            
        
        
sys._excepthook = sys.excepthook 
def exception_hook(exctype, value, traceback):
    print(exctype, value, traceback)
    sys._excepthook(exctype, value, traceback) 
    sys.exit(1) 
sys.excepthook = exception_hook 