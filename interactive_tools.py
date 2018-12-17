from . import plotting
from . import datastructure
from . import acquisition
from . import analysis

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
matplotlib.rcParams.update({'font.size': 12,'font.family':'serif'})
import ipywidgets as widgets
from IPython.display import display



class InteractiveLogging():
    def __init__(self,settings):
        self.settings = settings
        self.dataset = datastructure.DataSet()
        
        words = ['Measure', 'Undo measurement', 'FFT', 'FFT av', 'TF', 'TF av','Save Data','Save Fig','Save ALL']
        self.buttons = [widgets.Button(description=w) for w in words]
        display(widgets.HBox(self.buttons))
        
        self.buttons[0].on_click(self.measure)
        self.buttons[1].on_click(self.undo)
        self.buttons[2].on_click(self.fft)   
        self.buttons[3].on_click(self.fft_av)
        self.buttons[4].on_click(self.tf)
        self.buttons[5].on_click(self.tf_av)
        self.buttons[6].on_click(self.save_data)
        self.buttons[7].on_click(self.save_fig)
        self.buttons[8].on_click(self.save_all)
    
    def measure(self,b):
        d = acquisition.log_data(self.settings)
        self.dataset.add_to_dataset(d.time_data_list)
        
        self.p=plotting.PlotData(d.time_data_list[-1])
        
    def undo(self,b):
        self.dataset.remove_last_data_item('TimeData')
        if len(self.dataset.time_data_list) > 0:
            self.p=plotting.PlotData(self.dataset.time_data_list[-1])
            
    def fft(self,b):
        pass
    
    def fft_av(self,b):
        pass
    
    def tf(self,b):
        pass
    
    def tf_av(self,b):
        pass
    
    def save_data(self,b):
        self.dataset.calculate_fft_set()
        self.dataset.calculate_tf_averaged(window=None)
        self.dataset.save_data()
    
    def save_fig(self,b):
        pass
    
    def save_all(self,b):
        pass
                