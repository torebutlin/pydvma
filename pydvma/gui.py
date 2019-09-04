from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QMessageBox, QTabWidget, QFormLayout, QToolBar, QLineEdit, QLabel, QComboBox, QSlider, QMessageBox
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QFrame, QStyleFactory, QSplitter, QFrame
from PyQt5.QtWidgets import QToolTip
from PyQt5.QtCore import Qt, QThread, Signal, QTimer
from PyQt5.QtGui import QPalette, QDoubleValidator, QIntValidator, QFontMetrics
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
import time
import sys
import numpy as np

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

    def __init__(self,settings,test_name,rec):
        super().__init__()
        
        self.settings = settings
        self.test_name = test_name
        self.rec = rec
        
    def __del__(self):
        self.wait()
    
    def run(self):
        self.d = acquisition.log_data(self.settings,test_name=self.test_name, rec=self.rec)
        self.s.emit(self.d)
        

class InteractiveLogger():
        
    def __init__(self,settings=None,test_name=None,default_window='hanning'):
        
        # Initialise variables
        global MESSAGE
        if default_window is None:
            default_window = 'None'
        self.settings = settings
        self.test_name = test_name
        self.dataset = datastructure.DataSet()
        
        
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
        
        # SETUP GUI
        QApplication.setStyle(QStyleFactory.create('Fusion'))
        
        self.window = QWidget()
        self.window.setStyleSheet("background-color: white")
        self.window.setWindowTitle('Interactive Logger')

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
        
        self.input_list_figures = newComboBox(['Time Data','FFT Data','TF Data'])
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
        
        self.button_select_all_data = GreenButton('Show All')
        self.button_select_no_data = GreenButton('Hide All')
        self.input_selection_list = QLineEdit()
        self.input_selection_list.editingFinished.connect(self.select_set_chan_list)
        self.button_select_all_data.clicked.connect(self.select_all_data)
        self.button_select_no_data.clicked.connect(self.select_no_data)
        
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
        self.layout_axes.addWidget(self.button_select_all_data,row_start+2,0,1,3)
        self.layout_axes.addWidget(self.button_select_no_data,row_start+2,3,1,3)
        
        
        # Legend control
        row_start = 15
        self.layout_axes.addWidget(QLabel(),row_start,0,1,6)
        self.layout_axes.addWidget(boldLabel('Legend control:'),row_start+1,0,1,6)
        for n in range(len(self.legend_buttons)):
            self.layout_axes.addWidget(self.legend_buttons[n],row_start+2,2*n,1,2)
        
        
        # Plot-specific tools
        row_start = 18
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
        self.input_freq_min.setValidator(QDoubleValidator(np.float(-np.inf),np.float(np.inf),5))
        self.input_freq_min.editingFinished.connect(self.freq_min)
        self.input_freq_max = QLineEdit()
        self.input_freq_max.setValidator(QDoubleValidator(np.float(-np.inf),np.float(np.inf),5))
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
        
        # widgets to layout
        self.layout_tools = QVBoxLayout()
        self.layout_tools.addWidget(self.frame_tools_selection)
        self.layout_tools.addWidget(self.frame_tools_time_domain)
        self.layout_tools.addWidget(self.frame_tools_fft)
        self.layout_tools.addWidget(self.frame_tools_tf)
        self.layout_tools.addWidget(self.frame_tools_scaling)
        self.layout_tools.setAlignment(Qt.AlignTop)
        
        # layout to frame
        self.frame_tools = QFrame()
        self.frame_tools.setFrameShape(QFrame.StyledPanel)
        self.frame_tools.setLayout(self.layout_tools)
        
        
    def setup_frame_tools_selection(self):
        
        self.input_list_tools = newComboBox(['Standard Tools','Logger Settings','Pre-process','FFT','Transfer Function','Calibration / Scaling','Mode Fitting','Save / Export'])
        
        
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
        self.layout_tools_tf.addWidget(self.button_TF,5,0,1,3)
        self.layout_tools_tf.addWidget(self.button_TFav,5,0,1,3)
        
        # initiate view
        self.input_list_average_TF.setCurrentIndex(0)
        self.input_Nframes.setText('1')
        self.slider_Nframes.setValue(1)
        self.label_Nframes.setVisible(False)
        self.input_Nframes.setVisible(False)
        self.slider_Nframes.setVisible(False)
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


    def update_frame_tools(self):
        self.frame_tools.setLayout(self.layout_tools)


    #%% INTERACTION FUNCTIONS
    
    def show(self):
        # allow logger to be opened again after closing
        self.window.showMinimized()
        self.window.showNormal()
    
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
            self.input_list_tools.setCurrentIndex(1)
            self.select_view()

    def show_message(self,message,b='ok'):
        if message != '':
            self.label_message.setText(message)
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
        self.frame_message.setVisible(False)
      
        

    def button_clicked_log_data(self):
        
        if self.rec is None:
            self.start_stream()
        
        self.rec.trigger_detected = False
        self.button_log_data.setStyleSheet("background-color: white")
        
        if self.settings.pretrig_samples is None:
            message = 'Logging data for {} seconds'.format(self.settings.stored_time)
        else:
            message = 'Logging data for {} seconds, with trigger)'.format(self.settings.stored_time)
        
        self.thread = LogDataThread(self.settings,test_name=self.test_name, rec=self.rec)
        
        self.show_message(message,'cancel')
        
        
        self.thread.start()
        self.thread.s.connect(self.add_logged_data)
        
    
    def add_logged_data(self,d):
        self.dataset.add_to_dataset(d.time_data_list)
        N = len(self.dataset.time_data_list)
        self.sets = [N-1]
        self.channels = 'all'
        self.input_list_figures.setCurrentIndex(0)
        self.select_view()
        self.p.ax.set_ylim([-1,1])
        self.button_log_data.setStyleSheet('background-color: hsl(120, 170, 255)')
        self.hide_message()
        
    def cancel_logging(self):
        self.thread.terminate()
        self.show_message('Logging cancelled')
        self.button_log_data.setStyleSheet('background-color: hsl(120, 170, 255)')
        

    def delete_last_data(self):
        self.dataset.remove_last_data_item('TimeData')
        self.dataset.freq_data_list = datastructure.FreqDataList()
        self.dataset.tf_data_list = datastructure.TfDataList()
        N = len(self.dataset.time_data_list)
        self.sets = [N-1]
        self.channels = 'all'
        self.input_list_figures.setCurrentIndex(0)
        self.select_view()
        
    def reset_data(self):
        
        self.dataset = datastructure.DataSet()
        N = len(self.dataset.time_data_list)
        self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
        self.input_list_figures.setCurrentIndex(0)
        self.select_view()

    
    def load_data(self):
        d = file.load_data()
        if d is not None:
            self.dataset.add_to_dataset(d.time_data_list)
            self.dataset.add_to_dataset(d.freq_data_list)
            self.dataset.add_to_dataset(d.tf_data_list)
            self.dataset.add_to_dataset(d.cross_spec_data_list)
            self.dataset.add_to_dataset(d.sono_data_list)
            self.dataset.add_to_dataset(d.meta_data_list)
            try:
                self.dataset.add_to_dataset(d.modal_data_list)
            except:
                pass
            
        else:
            message = 'No data loaded'
            self.show_message(message)
            return None
        
        no_data = True
        self.auto_xy = 'xyc'
        if len(self.dataset.time_data_list) != 0:
            self.input_list_figures.setCurrentText('Time Data')
            self.select_view()
            self.hide_message()
            no_data = False
        if len(self.dataset.freq_data_list) != 0:
            self.input_list_figures.setCurrentText('FFT Data')
            self.select_view()
            self.hide_message()
            no_data = False
        if len(self.dataset.tf_data_list) != 0:
            self.input_list_figures.setCurrentText('TF Data')
            self.select_view()
            self.hide_message()
            no_data = False
        else:
            message = 'No data to view'
            self.show_message(message)
        
        
        
            
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
        if (self.current_view == 'TF Data') or (self.current_view == 'FFT Data'):
            self.freq_range = list(self.p.ax.get_xlim())
        self.canvas.draw()
        
    def xmax(self):
        xmax = np.float(self.input_axes[1].text())
        xlim = self.p.ax.get_xlim()
        self.p.ax.set_xlim([xlim[0],xmax])
        if (self.current_view == 'TF Data') or (self.current_view == 'FFT Data'):
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
        self.auto_xy = 'x'
        self.update_figure()
#        self.p.auto_x()
#        self.update_axes_values([])
        
    def auto_y(self):
        self.auto_xy = 'yc'
        self.update_figure()
#        self.p.auto_y()
#        self.p.ax2.set_ylim([0,1])
#        self.update_axes_values([])
#        self.update_co_axes_values([])
        
    def update_axes_values(self,axes):
        xlim = self.p.ax.get_xlim()
        ylim = self.p.ax.get_ylim()
        self.input_axes[0].setText('{:0.5g}'.format(xlim[0]))
        self.input_axes[1].setText('{:0.5g}'.format(xlim[1]))
        self.input_axes[2].setText('{:0.5g}'.format(ylim[0]))
        self.input_axes[3].setText('{:0.5g}'.format(ylim[1]))
        if self.plot_type != 'Nyquist':
            # keep freq_range up to date with zooming
            self.freq_range = list(xlim)
        
    def legend_left(self):
        self.legend_loc = 'lower left'
        self.p.update_legend(self.legend_loc)
        self.canvas.draw()
        
    def legend_right(self):
        self.legend_loc = 'lower right'
        self.p.update_legend(self.legend_loc)
        self.canvas.draw()
            
    def legend_onoff(self):
        visibility = self.p.ax.get_legend().get_visible()
        self.p.ax.get_legend().set_visible(not visibility)
        self.canvas.draw()
        
        
    def update_figure(self):
        # updates the currently viewed plot
        if self.current_view == 'Time Data':
            data_list = self.dataset.time_data_list
        elif self.current_view == 'FFT Data':
            data_list = self.dataset.freq_data_list
        elif self.current_view == 'TF Data':
            data_list = self.dataset.tf_data_list

        self.label_figure.setText(self.selected_view)
        self.p.update(data_list, sets=self.sets, channels=self.channels, xlinlog=self.xlinlog,show_coherence=self.show_coherence,plot_type=self.plot_type,coherence_plot_type=self.coherence_plot_type,freq_range=self.freq_range,auto_xy=self.auto_xy)
        
    def select_all_data(self):
        for line in self.p.ax.lines:
            line.set_alpha(plotting.LINE_ALPHA)
        for line in self.p.legend.get_lines():
            line.set_alpha(plotting.LINE_ALPHA)
        
        self.canvas.draw()
        
        
    def select_no_data(self):
        for line in self.p.ax.lines:
            line.set_alpha(1-plotting.LINE_ALPHA)
        for line in self.p.legend.get_lines():
            line.set_alpha(1-plotting.LINE_ALPHA)
        self.canvas.draw()
    
    def select_set_chan_list(self):
        for line in self.p.ax.lines:
            line.set_alpha = 1 - plotting.LINE_ALPHA
           
        
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
        self.p.update(self.dataset.tf_data_list, xlinlog=self.xlinlog, show_coherence=self.show_coherence,plot_type=self.plot_type,coherence_plot_type=self.coherence_plot_type,freq_range=self.freq_range,auto_xy=self.auto_xy)
        
    def freq_max(self):
        self.freq_range[1] = np.float(self.input_freq_max.text())
        self.p.update(self.dataset.tf_data_list, xlinlog=self.xlinlog, show_coherence=self.show_coherence,plot_type=self.plot_type,coherence_plot_type=self.coherence_plot_type,freq_range=self.freq_range,auto_xy=self.auto_xy)
        
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
            self.xlinlog = 'symlog'
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
        if N > 0:
            self.input_list_figures.setCurrentIndex(index)
        
    def select_view(self):
        # handles logic of what to show in gui depending on selected view options
        ci = self.input_list_figures.currentIndex()
        self.selected_view = self.input_list_figures.itemText(ci)

        if self.current_view == self.selected_view:
            self.current_view_changed = False
            self.plot_type_before = self.plot_type
            self.plot_type = self.items_list_plot_type[self.input_list_plot_type.currentIndex()]
            self.switch_to_nyquist = (self.plot_type == 'Nyquist') and ('Nyquist' != self.plot_type_before)
            self.switch_from_nyquist = (self.plot_type_before == 'Nyquist') and ('Nyquist' != self.plot_type)
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
                # plot
                self.update_figure()
                
            # show message if no data
            else:
                message = 'No time data to display'
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
                message = 'No FFT data to display'
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
                message = 'No transfer function data to display'
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
        self.label_co_freq_min.setText('co. max:')
        
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
        self.label_co_freq_min.setText('freq. max:')
        
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

    def clean_impulse(self):
        try:
            ch_impulse = np.int(self.input_impulse_channel.text())
            dataset_new = self.dataset.clean_impulse(ch_impulse=ch_impulse)
            self.dataset_backup = self.dataset
            self.dataset = dataset_new
            self.show_message(analysis.MESSAGE,b='undo')
            self.last_action = 'clean_impulse'
            self.update_figure()
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
            self.select_view()
            
    def select_averaging_type(self):
        self.averaging_method = self.input_list_average_TF.currentText()
        if self.averaging_method == 'None':
            self.input_Nframes.setText('1')
            self.slider_Nframes.setValue(1)
            self.label_Nframes.setVisible(False)
            self.input_Nframes.setVisible(False)
            self.slider_Nframes.setVisible(False)
            self.button_TFav.setVisible(False)
            self.button_TF.setVisible(True)
            
        elif self.averaging_method == 'within each set':
            self.button_TFav.setVisible(False)
            self.button_TF.setVisible(True)
            self.label_Nframes.setVisible(True)
            self.input_Nframes.setVisible(True)
            self.slider_Nframes.setVisible(True)
            
        elif self.averaging_method == 'across sets':
            self.button_TF.setVisible(False)
            self.label_Nframes.setVisible(False)
            self.input_Nframes.setVisible(False)
            self.slider_Nframes.setVisible(False)
            self.button_TFav.setVisible(True)
            
    def refresh_Nframes_text(self):
        self.input_Nframes.setText(str(self.slider_Nframes.value()))
        
    def refresh_Nframes_slider(self):
        self.slider_Nframes.setValue(np.int(self.input_Nframes.text()))
    
        
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
                self.select_view()
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
                self.select_view()
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
            if np.shape(self.selected_channels) != np.shape(s):
                # reset gui's iw_power record if changed selection
                self.iw_fft_power = 0
                self.selected_channels = s
            elif (self.selected_channels != s).any():
                # reset gui's iw_power record if changed selection - two ways this can change
                self.iw_fft_power = 0
                self.selected_channels = s
                
            n_sets,n_chans = np.shape(s)
            for ns in range(n_sets):
                newdata = analysis.multiply_by_power_of_iw(data_list[ns],power=power,channel_list=s[ns,:])
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
                    message += 'Set {:d}: factors = {}\n'.format(n_set,fs)
                self.show_message(message)
            
            self.last_action = 'scaling'
            
        else:
            message = 'First select ''TF Data'' or ''Calc TF''.'
            self.show_message(message)
        
sys._excepthook = sys.excepthook 
def exception_hook(exctype, value, traceback):
    print(exctype, value, traceback)
    sys._excepthook(exctype, value, traceback) 
    sys.exit(1) 
sys.excepthook = exception_hook 