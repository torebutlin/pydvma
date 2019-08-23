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
        self.setStyleSheet("background-color: rgb(50, 50, 200)")
        self.setText(text) 

class GreenButton(QPushButton):
    def __init__(self,text):
        super().__init__(text)
        self.setStyleSheet("background-color: rgb(50, 200, 50);")
        self.setText(text)

class RedButton(QPushButton):
    def __init__(self,text):
        super().__init__(text)
        self.setStyleSheet("background-color: rgb(200, 50, 50)")
        self.setText(text)



class InteractiveLogging():
    def __init__(self,settings=None,test_name=None,default_window='hanning'):
        if default_window is None:
            default_window = 'None'
        self.settings = settings
        self.test_name = test_name
        self.dataset = datastructure.DataSet()
        
        
        QApplication.setStyle(QStyleFactory.create('Fusion'))
        
        
        self.window = QWidget()
        self.window.setStyleSheet("background-color: white")
        
        if test_name == None:
            self.window.setWindowTitle('Interactive Logger')
        else:
            self.window.setWindowTitle('Interactive Logger: ' + test_name)
        
        self.setup_tools_frame()
        self.setup_figure_frame()
        self.setup_view_frame()
        
        self.setup_main_layout()
        
        
        self.window.show()
        
    def setup_main_layout(self):

        # organise frames
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.frame_tools)
        self.splitter.addWidget(self.frame_figure)
        self.splitter.addWidget(self.frame_view)
        
        # frames to main layout
        self.main_layout = QGridLayout()
        self.main_layout.addWidget(self.splitter)
        
        # main layout to window
        self.window.setLayout(self.main_layout)
        
        
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
        
        
        
    
    def setup_view_frame(self):
        
        # design items
#        button_auto_x = QPushButton()
#        button_auto_x.setStyleSheet("background-color: red")
        
        button_x = GreenButton('Auto X')
        button_y = GreenButton('Auto Y')
        
        items_axes = ['xmin','xmax','ymin','ymax']
        label_axes = [QLabel(i) for i in items_axes]
        input_axes = [QLineEdit() for i in items_axes]

        
        # widgets to layout
        self.layout_view = QGridLayout()
        self.layout_view.addWidget(QLabel('Axes control:'),1,1,1,2)
        self.layout_view.addWidget(button_x,2,1,1,2)
        self.layout_view.addWidget(button_y,3,1,1,2)
        
        for n in range(4):
            self.layout_view.addWidget(label_axes[n],n+4,1)
            self.layout_view.addWidget(input_axes[n],n+4,2)
        
        
        self.layout_view.setAlignment(Qt.AlignTop)

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

