from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QMessageBox, QTabWidget, QFormLayout, QToolBar, QLineEdit, QLabel
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
        self.setup_frame_view()
        self.setup_frame_axes()
        
        # arrange frames and create window
        self.setup_layout_main()
        self.window.show()
        
    def setup_layout_main(self):

        # organise frames
        self.splitter_mid = QSplitter(Qt.Vertical)
        self.splitter_mid.addWidget(self.frame_input)
        self.splitter_mid.addWidget(self.frame_figure)
        self.splitter_mid.addWidget(self.frame_view)
        
        self.splitter_all = QSplitter(Qt.Horizontal)
        self.splitter_all.addWidget(self.frame_axes)
        self.splitter_all.addWidget(self.splitter_mid)
        self.splitter_all.addWidget(self.frame_tools)
        
        # frames to main layout
        self.layout_main = QGridLayout()
        self.layout_main.addWidget(self.splitter_all)
        
        # main layout to window
        self.window.setLayout(self.layout_main)
        
    
        
    def setup_frame_tools(self):
        
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
        
    def setup_frame_view(self):
        # design items
        self.view_buttons = [QPushButton(i) for i in ['Time Data','FFT Data','TF Data']]
        
        
        # widgets to layout
        self.layout_view = QHBoxLayout()
#        self.layout_view.setAlignment(Qt.AlignTop)

        # View control
        self.layout_view.addWidget(QLabel('View Data Type:'))
        for n in range(len(self.view_buttons)):
            self.layout_view.addWidget(self.view_buttons[n])
            
        # layout to frame
        self.frame_view = QFrame()
        self.frame_view.setFrameShape(QFrame.StyledPanel)
        self.frame_view.setLayout(self.layout_view)
        
    
    def setup_frame_axes(self):
        
        
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


        
        # Axes control
        row_start = 0
        self.layout_axes.addWidget(QLabel(),row_start,0,1,3)
        self.layout_axes.addWidget(QLabel('Axes control:'),row_start+1,0,1,3)
        self.layout_axes.addWidget(self.button_x,row_start+2,0,1,3)
        self.layout_axes.addWidget(self.button_y,row_start+3,0,1,3)
        
        for n in range(len(self.label_axes)):
            self.label_axes[n].setAlignment(Qt.AlignRight)
            self.layout_axes.addWidget(self.label_axes[n],row_start+n+4,0)
            self.layout_axes.addWidget(self.input_axes[n],row_start+n+4,1,1,2)
            
            
        
        # Legend control
        row_start = 8
        self.layout_axes.addWidget(QLabel(),row_start,0,1,3)
        self.layout_axes.addWidget(QLabel('Legend control:'),row_start+1,0,1,2)
        for n in range(len(self.legend_buttons)):
            self.layout_axes.addWidget(self.legend_buttons[n],row_start+2,n)
        
        
        # layout to frame
        self.frame_axes = QFrame()
        self.frame_axes.setFrameShape(QFrame.StyledPanel)
        self.frame_axes.setLayout(self.layout_axes)
        

    def setup_layout_tools_standard(self):
        pass

    def setup_layout_tools_standard(self):
        pass


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

