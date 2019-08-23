from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QMessageBox, QTabWidget, QFormLayout, QToolBar, QLineEdit, QLabel
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QFrame, QStyleFactory, QSplitter, QFrame
from PyQt5.QtWidgets import QToolTip
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette
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

        self.setup_tools_frame()
        self.setup_input_frame()
        self.setup_figure_frame()
        self.setup_view_frame()
        
        self.setup_main_layout()
        self.window.show()
        
    def setup_main_layout(self):

        # organise frames
        self.splitter_mid = QSplitter(Qt.Vertical)
        self.splitter_mid.addWidget(self.frame_input)
        self.splitter_mid.addWidget(self.frame_figure)
        
        self.splitter_all = QSplitter(Qt.Horizontal)
        self.splitter_all.addWidget(self.frame_view)
        self.splitter_all.addWidget(self.splitter_mid)
        self.splitter_all.addWidget(self.frame_tools)
        
        
        
        # frames to main layout
        self.main_layout = QGridLayout()
        
        
        self.main_layout.addWidget(self.splitter_all)
        
        
        
#        self.main_layout.addWidget(self.splitter3)
        
        # main layout to window
        self.window.setLayout(self.main_layout)
        
    
    def setup_middle_frame(self):
        self.layout_middle = QVBoxLayout()
        self.layout_middle.addWidget(self.frame_input)
        self.layout_middle.addWidget(self.frame_figure)
        
    def setup_tools_frame(self):
        
        # widgets to layout
        self.layout_tools = QGridLayout()
        self.layout_tools.addWidget(QPushButton('A'),1,1)
        self.layout_tools.addWidget(QPushButton('B'),1,2)
        self.layout_tools.addWidget(QPushButton('B'),2,1)
        self.layout_tools.addWidget(QPushButton('B'),2,2)
        
        # layout to frame
        self.frame_tools = QFrame()
        self.frame_tools.setFrameShape(QFrame.StyledPanel)
        self.frame_tools.setLayout(self.layout_tools)
       

    def setup_figure_frame(self):
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
        
    def setup_input_frame(self):
        
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
        
        
    
    def setup_view_frame(self):
        
        # design items
        self.view_buttons = [QPushButton(i) for i in ['View Time','View FFT','View TF']]
        
        self.button_x = GreenButton('Auto X')
        self.button_y = GreenButton('Auto Y')
        
        self.label_axes = [QLabel(i) for i in ['xmin:','xmax:','ymin:','ymax:']]
        self.input_axes = [QLineEdit() for i in range(4)]

        self.legend_buttons = [BlueButton(i) for i in ['left','on/off','right']]
        
        
        # widgets to layout
        self.layout_view = QGridLayout()
        self.layout_view.setAlignment(Qt.AlignTop)


        # View control
        row_start = 0
        self.layout_view.addWidget(QLabel('View Data Type:'),row_start,0,1,3)
        for n in range(len(self.view_buttons)):
            self.layout_view.addWidget(self.view_buttons[n],row_start+n+1,0,1,3)
        
        # Axes control
        row_start = 4
        self.layout_view.addWidget(QLabel(),row_start,0,1,3)
        self.layout_view.addWidget(QLabel('Axes control:'),row_start+1,0,1,3)
        self.layout_view.addWidget(self.button_x,row_start+2,0,1,3)
        self.layout_view.addWidget(self.button_y,row_start+3,0,1,3)
        
        for n in range(len(self.label_axes)):
            self.label_axes[n].setAlignment(Qt.AlignRight)
            self.layout_view.addWidget(self.label_axes[n],row_start+n+4,0)
            self.layout_view.addWidget(self.input_axes[n],row_start+n+4,1,1,2)
            
            
        
        # Legend control
        row_start = 12
        self.layout_view.addWidget(QLabel(),row_start,0,1,3)
        self.layout_view.addWidget(QLabel('Legend control:'),row_start+1,0,1,2)
        for n in range(len(self.legend_buttons)):
            self.layout_view.addWidget(self.legend_buttons[n],row_start+2,n)
        
        
        # layout to frame
        self.frame_view = QFrame()
        self.frame_view.setFrameShape(QFrame.StyledPanel)
        self.frame_view.setLayout(self.layout_view)
        



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

