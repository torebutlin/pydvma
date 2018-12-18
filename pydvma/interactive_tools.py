from . import plotting
from . import datastructure
from . import acquisition
from . import analysis
from . import streams

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
matplotlib.rcParams.update({'font.size': 12,'font.family':'serif'})
import ipywidgets as widgets
from IPython.display import display




class InteractiveLogging():
    def __init__(self,settings):
        self.out = widgets.Output()
        display(self.out)
        self.settings = settings
        self.dataset = datastructure.DataSet()
        if settings.device_driver is 'soundcard':
            self.rec = streams.Recorder(settings)
            self.rec.init_stream(settings)
        elif settings.device_driver is 'nidaq':
            self.rec = streams.Recorder_NI(settings)
            self.rec.init_stream(settings)
        else:
            print('unrecognised driver')
            
        self.p = plotting.PlotData()
        
        words = ['Measure', 'Undo measurement', 'Time', 'FFT', 'TF', 'TF av','Save Data','Save Fig','Save ALL']
        self.buttons = [widgets.Button(description=w) for w in words]
        display(widgets.HBox(self.buttons))
        
        self.buttons[0].on_click(self.measure)
        self.buttons[1].on_click(self.undo)
        self.buttons[2].on_click(self.time)
        self.buttons[3].on_click(self.fft)
        self.buttons[4].on_click(self.tf)
        self.buttons[5].on_click(self.tf_av)
        self.buttons[6].on_click(self.save_data)
        self.buttons[7].on_click(self.save_fig)
        self.buttons[8].on_click(self.save_all)
    
    def measure(self,b):
        self.out.clear_output()
        self.out = widgets.Output()
        display(self.out)
        with self.out:
            d = acquisition.log_data(self.settings,self.rec)
            
        self.dataset.add_to_dataset(d.time_data_list)
        
        N = len(self.dataset.time_data_list)
        self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
        
    def undo(self,b):
        self.dataset.remove_last_data_item('TimeData')
        N = len(self.dataset.time_data_list)
        self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
        
    def time(self,b):
        N = len(self.dataset.time_data_list)
        self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
            
    def fft(self,b):
        self.out.clear_output()
        self.out = widgets.Output()
        display(self.out)
        with self.out:
            self.dataset.calculate_fft_set()
        self.p.update(self.dataset.freq_data_list)
        
    
    def tf(self,b):
        self.out.clear_output()
        self.out = widgets.Output()
        display(self.out)
        with self.out:
            self.dataset.calculate_tf_set()
        self.p.update(self.dataset.tf_data_list)
    
    def tf_av(self,b):
        self.out.clear_output()
        self.out = widgets.Output()
        display(self.out)
        with self.out:
            self.dataset.calculate_tf_averaged()
        self.p.update(self.dataset.tf_data_list)
    
    def save_data(self,b):
        self.out.clear_output()
        self.out = widgets.Output()
        display(self.out)
        with self.out:
            self.dataset.save_data()
    
    def save_fig(self,b):
        pass
    
    def save_all(self,b):
        pass
    
    

                