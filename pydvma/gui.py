from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QMessageBox, QTabWidget, QFormLayout, QToolBar, QLineEdit, QLabel, QComboBox, QSlider, QMessageBox
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QFrame, QStyleFactory, QSplitter, QFrame
from PyQt5.QtWidgets import QToolTip
from PyQt5.QtCore import Qt, QThread, Signal, QTimer
from PyQt5.QtGui import QPalette, QDoubleValidator, QIntValidator, QFontMetrics
import copy
from matplotlib.backends.backend_qt5agg import FigureCanvas, NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import numpy as np
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

sys._excepthook = sys.excepthook 
def exception_hook(exctype, value, traceback):
    print(exctype, value, traceback)
    sys._excepthook(exctype, value, traceback) 
    sys.exit(1) 
sys.excepthook = exception_hook 

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
        

class InteractiveLogging():
    def __init__(self,settings=None,test_name=None,default_window='hanning'):
        
        # Initialise variables
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
        self.coherence_plot_type = 'lin'
        
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
        self.button_cancel = RedButton('Cancel')
        
        # function connections
        self.button_message.clicked.connect(self.hide_message)
        self.button_cancel.clicked.connect(self.cancel_logging)
        
        self.layout_message = QGridLayout()
        
        self.layout_message.addWidget(self.label_message,0,0,1,3)
        self.layout_message.addWidget(self.button_message,0,3,1,1)
        self.layout_message.addWidget(self.button_cancel,0,3,1,1)
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
        self.input_axes[0].textChanged.connect(self.xmin)
        self.input_axes[1].setValidator(QDoubleValidator(np.float(0),np.float(np.inf),5)) 
        self.input_axes[1].textChanged.connect(self.xmax)
        self.input_axes[2].setValidator(QDoubleValidator(np.float(-np.inf),np.float(np.inf),5)) 
        self.input_axes[2].textChanged.connect(self.ymin)
        self.input_axes[3].setValidator(QDoubleValidator(np.float(-np.inf),np.float(np.inf),5)) 
        self.input_axes[3].textChanged.connect(self.ymax)
        
        self.legend_buttons = [BlueButton(i) for i in ['left','on/off','right']]
        self.legend_buttons[0].clicked.connect(self.legend_left)
        self.legend_buttons[1].clicked.connect(self.legend_onoff)
        self.legend_buttons[2].clicked.connect(self.legend_right)
        
        
        # widgets to layout
        self.layout_axes = QGridLayout()
        self.layout_axes.setAlignment(Qt.AlignTop)


        # Figure selection
        row_start = 0
        self.layout_axes.addWidget(boldLabel('Figure selection:'),row_start+0,0,1,3)
        self.layout_axes.addWidget(self.input_list_figures,row_start+1,0,1,3)
        
        # Axes control
        row_start = 3
        self.layout_axes.addWidget(QLabel(),row_start,0,1,3)
        self.layout_axes.addWidget(boldLabel('Axes control:'),row_start+1,0,1,3)
        self.layout_axes.addWidget(self.button_x,row_start+2,0,1,3)
        self.layout_axes.addWidget(self.button_y,row_start+3,0,1,3)
        
        for n in range(len(self.label_axes)):
            self.label_axes[n].setAlignment(Qt.AlignRight)
            self.layout_axes.addWidget(self.label_axes[n],row_start+n+4,0)
            self.layout_axes.addWidget(self.input_axes[n],row_start+n+4,1,1,2)
            
            
        
        # Legend control
        row_start = 11
        self.layout_axes.addWidget(QLabel(),row_start,0,1,3)
        self.layout_axes.addWidget(boldLabel('Legend control:'),row_start+1,0,1,2)
        for n in range(len(self.legend_buttons)):
            self.layout_axes.addWidget(self.legend_buttons[n],row_start+2,n)
        
        
        # Plot-specific tools
        row_start = 14
        self.layout_axes.addWidget(self.frame_plot_details,row_start,0,1,3)
        self.frame_plot_details.setVisible(False)
        
        # layout to frame
        self.frame_axes = QFrame()
        self.frame_axes.setFrameShape(QFrame.StyledPanel)
        self.frame_axes.setLayout(self.layout_axes)
       
    def setup_frame_plot_details(self):
        #items
        self.items_list_plot_type = ['Amplitude (dB)','Amplitude (linear)', 'Real Part', 'Imag Part', 'Nyquist', 'Amplitude + Phase', 'Phase']
        self.input_list_plot_type = newComboBox(self.items_list_plot_type)
        self.button_lin_log_x = BlueButton('X Lin/Log')
        self.button_data_toggle = BlueButton('Data on/off')
        self.button_coherence_toggle = BlueButton('Coherence on/off')
        
        self.input_co_min = QLineEdit('0')
        self.input_co_min.setValidator(QDoubleValidator(np.float(-np.inf),np.float(np.inf),5))
        self.input_co_max = QLineEdit('1')
        self.input_co_max.setValidator(QDoubleValidator(np.float(-np.inf),np.float(np.inf),5))
        
        self.button_modal_fit_toggle = BlueButton('Modal Fit on/off')
        
        self.input_list_plot_type.currentIndexChanged.connect(self.select_plot_type)
        self.input_co_min.textChanged.connect(self.co_min)
        self.input_co_max.textChanged.connect(self.co_max)
        self.button_data_toggle.clicked.connect(self.data_toggle)
        self.button_coherence_toggle.clicked.connect(self.coherence_toggle)
        
        #layout
        self.layout_plot_details = QGridLayout()
        self.layout_plot_details.addWidget(QLabel(),0,0,1,1)
        self.layout_plot_details.addWidget(boldLabel('Plot Options:'),1,0,1,2)
        self.layout_plot_details.addWidget(self.input_list_plot_type,2,0,1,2)
        self.layout_plot_details.addWidget(self.button_lin_log_x,3,0,1,2)
        self.layout_plot_details.addWidget(self.button_data_toggle,4,0,1,1)
        self.layout_plot_details.addWidget(self.button_coherence_toggle,4,1,1,1)
        self.layout_plot_details.addWidget(QLabel('co. min:'),5,0,1,1)
        self.layout_plot_details.addWidget(self.input_co_min,5,1,1,1)
        self.layout_plot_details.addWidget(QLabel('co. max:'),6,0,1,1)
        self.layout_plot_details.addWidget(self.input_co_max,6,1,1,1)
        self.layout_plot_details.addWidget(self.button_modal_fit_toggle,7,0,1,2)        
        
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
        
        self.input_list_window = newComboBox(['None','hanning'])
        self.button_FFT = BlueButton('Calc FFT')
        
        self.layout_tools_fft = QGridLayout()
        self.layout_tools_fft.addWidget(boldLabel('FFT:'),0,0,1,3)
        self.layout_tools_fft.addWidget(QLabel('window:'),1,0,1,1)
        self.layout_tools_fft.addWidget(self.input_list_window,1,1,1,2)
        self.layout_tools_fft.addWidget(self.button_FFT,2,0,1,3)
        
        self.frame_tools_fft = QFrame()
        self.frame_tools_fft.setLayout(self.layout_tools_fft)

    def setup_frame_tools_tf(self):
        self.input_list_window = newComboBox(['None','hanning'])
        self.input_list_average_TF = newComboBox(['None','within each set','across sets'])
        self.button_TF = BlueButton('Calc TF')
        self.input_Nframes = QLineEdit()
        self.input_Nframes.setValidator(QIntValidator(1,1000))
        self.input_Nframes.setText('1')
        self.slider_Nframes = QSlider(Qt.Horizontal)
        self.slider_Nframes.setMinimum(1)
        self.slider_Nframes.setMaximum(30)
        self.button_TFav = BlueButton('Calc TF average')
        
        
        self.layout_tools_tf = QGridLayout()
        self.layout_tools_tf.addWidget(boldLabel('Transfer Function:'),0,0,1,3)
        self.layout_tools_tf.addWidget(QLabel('window:'),1,0,1,1)
        self.layout_tools_tf.addWidget(self.input_list_window,1,1,1,2)
        self.layout_tools_tf.addWidget(QLabel('average:'),2,0,1,1)
        self.layout_tools_tf.addWidget(self.input_list_average_TF,2,1,1,2)
        self.layout_tools_tf.addWidget(QLabel('N frames:'),3,0,1,1)
        self.layout_tools_tf.addWidget(self.input_Nframes,3,1,1,2)
        self.layout_tools_tf.addWidget(self.slider_Nframes,4,0,1,3)
        self.layout_tools_tf.addWidget(self.button_TF,5,0,1,3)
        
        self.frame_tools_tf = QFrame()
        self.frame_tools_tf.setLayout(self.layout_tools_tf)
        
        
    def setup_frame_tools_scaling(self):
        self.input_iw_power = QLineEdit('0')
        self.input_iw_power.setValidator(QIntValidator(0,2))

        self.button_best_match = BlueButton('Best Match')
        
        
        self.layout_tools_scaling = QGridLayout()
        self.layout_tools_scaling.addWidget(boldLabel('Calibration / Scaling:'),0,0,1,3)
        self.layout_tools_scaling.addWidget(QLabel('iw power:'),1,0,1,1)
        self.layout_tools_scaling.addWidget(self.input_iw_power,1,1,1,2)
        
        self.layout_tools_scaling.addWidget(self.button_best_match,2,0,1,3)
        
        self.frame_tools_scaling = QFrame()
        self.frame_tools_scaling.setLayout(self.layout_tools_scaling)


    def update_frame_tools(self):
        self.frame_tools.setLayout(self.layout_tools)


    #%% INTERACTION FUNCTIONS
    
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
            message = 'To enable data acquisition, pease use \'Logger Settings\' tool.'
            self.show_message(message)
            self.input_list_tools.setCurrentIndex(1)
            self.update_tool_selection()

    def show_message(self,message,b='ok'):
        self.label_message.setText(message)
        if b == 'ok':
            self.button_message.setVisible(True)
            self.button_cancel.setVisible(False)
        elif b == 'cancel':
            self.button_message.setVisible(False)
            self.button_cancel.setVisible(True)
            
        self.frame_message.setVisible(True)
        
        
    def hide_message(self):
        self.frame_message.setVisible(False)
            
    def update_tool_selection(self):
        pass
            

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
        self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
        
        self.p.auto_x()
#            self.p.auto_y()
        self.p.ax.set_ylim([-1,1])
        self.canvas.draw()
        self.current_view='Time'
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
        self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
        self.canvas.draw()
        
    def reset_data(self):
        
        self.dataset = datastructure.DataSet()
        N = len(self.dataset.time_data_list)
        self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
        self.canvas.draw()
    
    def load_data(self):
        d = file.load_data()
        if d is not None:
            self.dataset.add_to_dataset(d.time_data_list)
            self.dataset.add_to_dataset(d.freq_data_list)
            self.dataset.add_to_dataset(d.tf_data_list)
            self.dataset.add_to_dataset(d.cross_spec_data_list)
            self.dataset.add_to_dataset(d.sono_data_list)
        else:
            message = 'No data loaded'
            self.show_message(message)
            return None
        
        if len(self.dataset.time_data_list) != 0:
            self.p.update(self.dataset.time_data_list,sets='all',channels='all')
            self.hide_message()
        elif len(self.dataset.freq_data_list) != 0:
            self.p.update(self.dataset.freq_data_list,sets='all',channels='all')
            self.hide_message()
        elif len(self.dataset.tf_data_list) != 0:
            self.p.update(self.dataset.tf_data_list,sets='all',channels='all')
            self.hide_message()
        else:
            message = 'No data to view'
            self.show_message(message)
        
        self.select_view()
        self.p.auto_x()
        self.p.auto_y()
        
            
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
        self.canvas.draw()
        
    def xmax(self):
        xmax = np.float(self.input_axes[1].text())
        xlim = self.p.ax.get_xlim()
        self.p.ax.set_xlim([xlim[0],xmax])
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
        self.p.auto_x()
        self.update_axes_values()
        
    def auto_y(self):
        self.p.auto_y()
        self.p.ax2.set_ylim([0,1])
        self.update_axes_values()
        self.update_co_axes_values()
        
    def update_axes_values(self,axes):
        xlim = self.p.ax.get_xlim()
        ylim = self.p.ax.get_ylim()
        self.input_axes[0].setText('{:0.5g}'.format(xlim[0]))
        self.input_axes[1].setText('{:0.5g}'.format(xlim[1]))
        self.input_axes[2].setText('{:0.5g}'.format(ylim[0]))
        self.input_axes[3].setText('{:0.5g}'.format(ylim[1]))
        
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
                
    def select_view(self):

        if self.input_list_figures.currentIndex() == 0:
            N = len(self.dataset.time_data_list)
            if N != 0:
                self.p.update(self.dataset.time_data_list)
                if self.current_view != 'Time':
                    self.current_view = 'Time'
                    self.show_data = True
                    self.show_coherence = True
                    self.p.auto_x()
                    self.p.auto_y()
                    self.frame_plot_details.setVisible(False)
            else:
                message = 'No time data to display'
                self.show_message(message)
                
        if self.input_list_figures.currentIndex() == 1:
            N = len(self.dataset.freq_data_list)
            if N != 0:
                self.p.update(self.dataset.freq_data_list)
                if self.current_view != 'FFT':
                    self.current_view = 'FFT'
                    self.show_data = True
                    self.p.ax.set_visible(True)
                    self.p.auto_x()
                    self.p.auto_y()
                    self.frame_plot_details.setVisible(True)
                    self.button_coherence_toggle.setVisible(False)
                    self.button_modal_fit_toggle.setVisible(False)
            else:
                message = 'No FFT data to display'
                self.show_message(message)
        if self.input_list_figures.currentIndex() == 2:
            
            N = len(self.dataset.tf_data_list)
            if N != 0:
                self.p.update(self.dataset.tf_data_list)
                if self.current_view != 'TF':
                    self.current_view = 'TF'
                    self.show_data = True
                    self.show_coherence = True
                    self.p.ax.set_visible(True)
                    self.p.ax2.set_visible(True)
                    self.p.auto_x()
                    self.p.auto_y()
                    self.frame_plot_details.setVisible(True)
                    self.button_coherence_toggle.setVisible(True)
#                    if self.flag_modal_data == True:
#                        self.button_modal_fit_toggle.setVisible(True)
#                    else:
#                        self.button_modal_fit_toggle.setVisible(False)
                    
            else:
                message = 'No transfer function data to display'
                self.show_message(message)
    
    def select_plot_type(self):
        self.plot_type = self.items_list_plot_type(self.input_list_plot_type.currentIndex())
        
        if self.plot_type == 'Amplitude (dB)':
            pass
        
        elif self.plot_type == 'Amplitude (linear)':
            pass
        
        elif self.plot_type == 'Real Part':
            pass
        
        elif self.plot_type == 'Imag Part':
            pass
        
        elif self.plot_type == 'Nyquist':
            pass
        
        elif self.plot_type == 'Phase':
            pass            
        
        if self.current_view == 'Time':
            self.p.update(self.dataset.time_data_list)
        elif self.current_view == 'FFT':
            self.p.update(self.dataset.freq_data_list,xlinlog='lin',plot_type=self.plot_type)
        elif self.current_view == 'TF':
            self.p.update(self.dataset.tf_data_list,xlinlog='lin',show_coherence=self.show_coherence, plot_type=self.plot_type, coherence_plot_type=self.coherence_plot_type)
            
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
        
    def update_co_axes_values(self,axes):
        ylim = self.p.ax2.get_ylim()
        self.input_co_min.setText('{:0.5g}'.format(ylim[0]))
        self.input_co_max.setText('{:0.5g}'.format(ylim[1]))
        
    def data_toggle(self):
        self.show_data = not self.show_data
        for line in self.p.ax.lines:
            line.set_visible(self.show_data)
        self.canvas.draw()

    def coherence_toggle(self):
        self.show_coherence = not self.show_coherence
        for line in self.p.ax2.lines:
            line.set_visible(self.show_coherence)
        self.canvas.draw()