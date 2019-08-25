from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QMessageBox, QTabWidget, QFormLayout, QToolBar, QLineEdit, QLabel, QComboBox
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QFrame, QStyleFactory, QSplitter, QFrame
from PyQt5.QtWidgets import QToolTip
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QDoubleValidator
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
        self.window.show()
        
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
        self.p = plotting.PlotData(canvas=self.canvas,fig=self.fig)
        
        
        # widgets to layout
        self.layout_figure = QVBoxLayout()
        self.layout_figure.addWidget(self.canvas)
        self.layout_figure.addWidget(self.toolbar)
        
        # layout to frame
        self.frame_figure = QFrame()
        self.frame_figure.setFrameShape(QFrame.StyledPanel)
        self.frame_figure.setLayout(self.layout_figure)
        
    def setup_frame_input(self):
        
        # content
        log_data_button = GreenButton('Log Data')
        del_data_button = OrangeButton('Delete Last')
        res_data_button = RedButton('Delete All')
        load_data_button = BlueButton('Load Data')
        
        # widgets to layout
        self.layout_input = QHBoxLayout()
        self.layout_input.addWidget(log_data_button)
        self.layout_input.addWidget(del_data_button)
        self.layout_input.addWidget(res_data_button)
        self.layout_input.addWidget(load_data_button)
        
        # layout to frame
        self.frame_input = QFrame()
        self.frame_input.setFrameShape(QFrame.StyledPanel)
        self.frame_input.setLayout(self.layout_input)
        
    def setup_frame_save(self):
        # design items
#        self.label_save = QLabel('Quick save:')
        self.buttons_save = [GreenButton(i) for i in ['Save Dataset','Save Figure']]
        
        
        # widgets to layout
        self.layout_save = QHBoxLayout()
#        self.layout_view.setAlignment(Qt.AlignTop)

        # View control
#        self.layout_save.addWidget(self.label_save)
#        self.label_save.setAlignment(Qt.AlignCenter)
        for n in range(len(self.buttons_save)):
            self.layout_save.addWidget(self.buttons_save[n])
            
        # layout to frame
        self.frame_save = QFrame()
        self.frame_save.setFrameShape(QFrame.StyledPanel)
        self.frame_save.setLayout(self.layout_save)
        
    
    def setup_frame_axes(self):
        
        self.input_list_figures = newComboBox(['Time Data','FFT Data','TF Data'])
        
        
        self.button_x = GreenButton('Auto X')
        self.button_y = GreenButton('Auto Y')
        
        self.label_axes = [QLabel(i) for i in ['xmin:','xmax:','ymin:','ymax:']]
        self.input_axes = [QLineEdit() for i in range(4)]
        self.input_axes[0].setValidator(QDoubleValidator(np.float(0),np.float(np.inf),5)) 
        self.input_axes[1].setValidator(QDoubleValidator(np.float(0),np.float(np.inf),5)) 
        self.input_axes[2].setValidator(QDoubleValidator(np.float(-np.inf),np.float(np.inf),5)) 
        self.input_axes[3].setValidator(QDoubleValidator(np.float(-np.inf),np.float(np.inf),5)) 
        
        self.legend_buttons = [BlueButton(i) for i in ['left','on/off','right']]
        
        
        # widgets to layout
        self.layout_axes = QGridLayout()
        self.layout_axes.setAlignment(Qt.AlignTop)


        # Figure selection
        row_start = 0
        self.layout_axes.addWidget(QLabel('Figure selection:'),row_start+0,0,1,3)
        self.layout_axes.addWidget(self.input_list_figures,row_start+1,0,1,3)
        
        # Axes control
        row_start = 3
        self.layout_axes.addWidget(QLabel(),row_start,0,1,3)
        self.layout_axes.addWidget(QLabel('Axes control:'),row_start+1,0,1,3)
        self.layout_axes.addWidget(self.button_x,row_start+2,0,1,3)
        self.layout_axes.addWidget(self.button_y,row_start+3,0,1,3)
        
        for n in range(len(self.label_axes)):
            self.label_axes[n].setAlignment(Qt.AlignRight)
            self.layout_axes.addWidget(self.label_axes[n],row_start+n+4,0)
            self.layout_axes.addWidget(self.input_axes[n],row_start+n+4,1,1,2)
            
            
        
        # Legend control
        row_start = 11
        self.layout_axes.addWidget(QLabel(),row_start,0,1,3)
        self.layout_axes.addWidget(QLabel('Legend control:'),row_start+1,0,1,2)
        for n in range(len(self.legend_buttons)):
            self.layout_axes.addWidget(self.legend_buttons[n],row_start+2,n)
        
        
        # layout to frame
        self.frame_axes = QFrame()
        self.frame_axes.setFrameShape(QFrame.StyledPanel)
        self.frame_axes.setLayout(self.layout_axes)
       
        
        
    def setup_frame_tools(self):
        
        # initiate all tools frames
        self.setup_frame_tools_selection()
        self.setup_frame_tools_fft()
        self.setup_frame_tools_tf()
        
        # widgets to layout
        self.layout_tools = QVBoxLayout()
        self.layout_tools.addWidget(self.frame_tools_selection)
        self.layout_tools.addWidget(self.frame_tools_fft)
        self.layout_tools.addWidget(self.frame_tools_tf)
        self.layout_tools.setAlignment(Qt.AlignTop)
        
        # layout to frame
        self.frame_tools = QFrame()
        self.frame_tools.setFrameShape(QFrame.StyledPanel)
        self.frame_tools.setLayout(self.layout_tools)
        
        
    def setup_frame_tools_selection(self):
        
        self.input_list_tools = newComboBox(['Standard tools','FFT','Transfer Function','Mode Fitting','Dataset Summary','Logging Settings'])
        
        
        self.layout_tools_selection = QGridLayout()
        self.layout_tools_selection.addWidget(QLabel('Tool selection:'),0,0,1,3)
        self.layout_tools_selection.addWidget(self.input_list_tools)
        
        self.frame_tools_selection = QFrame()
        self.frame_tools_selection.setLayout(self.layout_tools_selection)
        

    def setup_frame_tools_fft(self):
        
        self.input_list_window = newComboBox(['None','hanning'])
        self.button_FFT = BlueButton('Calc FFT')
        
        self.layout_tools_fft = QGridLayout()
        self.layout_tools_fft.addWidget(QHLine(),0,0,1,3)
        self.layout_tools_fft.addWidget(QLabel('___FFT___'),1,0,1,3)
        self.layout_tools_fft.addWidget(QLabel('window:'),2,0,1,1)
        self.layout_tools_fft.addWidget(self.input_list_window,2,1,1,2)
        self.layout_tools_fft.addWidget(self.button_FFT,3,0,1,3)
        
        self.frame_tools_fft = QFrame()
        self.frame_tools_fft.setLayout(self.layout_tools_fft)

    def setup_frame_tools_tf(self):
        self.input_list_window = newComboBox(['None','hanning'])
        self.button_TF = BlueButton('Calc TF')
        
        self.layout_tools_tf = QGridLayout()
        self.layout_tools_tf.addWidget(QHLine(),0,0,1,3)
        self.layout_tools_tf.addWidget(QLabel('Transfer Functions'),1,0,1,3)
        self.layout_tools_tf.addWidget(QLabel('window:'),2,0,1,1)
        self.layout_tools_tf.addWidget(self.input_list_window,2,1,1,2)
        self.layout_tools_tf.addWidget(self.button_TF,3,0,1,3)
        
        self.frame_tools_tf = QFrame()
        self.frame_tools_tf.setLayout(self.layout_tools_tf)


    def update_frame_tools(self):
        self.frame_tools.setLayout(self.layout_tools)


#def on_button_clicked():
#    alert = QMessageBox()
#    alert.setText('You clicked the button!')
#    alert.exec_()
#
#
#button = QPushButton('Click')
#button.clicked.connect(on_button_clicked)
#
#

#layout.addWidget(button)

