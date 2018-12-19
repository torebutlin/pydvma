from . import plotting
from . import datastructure
from . import acquisition
from . import analysis
from . import streams

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
matplotlib.rcParams.update({'font.size': 12,'font.family':'serif'})
from IPython.display import display
from ipywidgets import Button, HBox, VBox, Output, FloatText, IntText, Dropdown, IntSlider, Layout, Label




class InteractiveLogging():
    def __init__(self,settings):
        
        
        self.settings = settings
        self.dataset = datastructure.DataSet()
        
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out = Output()
        with self.out:
            if settings.device_driver is 'soundcard':
                self.rec = streams.Recorder(settings)
                self.rec.init_stream(settings)
            elif settings.device_driver is 'nidaq':
                self.rec = streams.Recorder_NI(settings)
                self.rec.init_stream(settings)
            else:
                print('unrecognised driver')
        
        self.current_view = 'Time'    
        self.N_frames = 1
        
        items_measure = ['Log Data','Delete Last Measurement']
        items_view = ['Plot Time', 'Plot FFT', 'Plot TF', 'Plot TF average']
        items_axes = ['xmin','xmax','ymin','ymax']
        items_save = ['Save Dataset','Save Figure']
        
        self.item_label = Label(value="Frame length = {:.2f} seconds.".format(settings.stored_time/self.N_frames))
        
        
        
        self.buttons_measure= [Button(description=i, layout=Layout(width='50%')) for i in items_measure]
        self.buttons_measure[0].button_style ='success'
        self.buttons_measure[0].style.font_weight = 'bold'
        self.buttons_measure[1].button_style ='warning'
        self.buttons_measure[1].style.font_weight = 'bold'
        
        self.buttons_view = [Button(description=i, layout=Layout(width='95%')) for i in items_view]
        self.buttons_view[0].button_style ='primary'
        self.buttons_view[1].button_style ='primary'
        self.buttons_view[2].button_style ='primary'
        self.buttons_view[3].button_style ='primary'
        
        self.buttons_save = [Button(description=i, layout=Layout(width='50%')) for i in items_save]
        self.buttons_save[0].button_style = 'success'
        self.buttons_save[0].style.font_weight = 'bold'
        self.buttons_save[1].button_style = 'success'
        self.buttons_save[1].style.font_weight = 'bold'
        
        self.item_axis_label = Label(value="Adjust axes manually:",layout=Layout(width='16%'))
        self.button_X = Button(description='Auto X', layout=Layout(width='10%'))
        self.button_Y = Button(description='Auto Y', layout=Layout(width='10%'))
        self.button_X.button_style ='primary'
        self.button_Y.button_style ='primary'
        self.text_axes = [FloatText(value=0,description=i, layout=Layout(width='16%')) for i in items_axes]
        
        self.text_axes = [self.button_X]+[self.button_Y] + [self.item_axis_label] + self.text_axes
        self.drop_window = Dropdown(options=['None', 'hanning'],value=None,description='Window:', layout=Layout(width='95%'))
        self.slide_Nframes = IntSlider(value=1,min=1,max=30,step=1,description='N_frames:',continuous_update=True,readout=False, layout=Layout(width='95%'))
        self.text_Nframes = IntText(value=1,description='N_frames:', layout=Layout(width='95%'))
        
        group1 = VBox([self.buttons_view[0]],layout=Layout(width='25%'))
        group2 = VBox([self.buttons_view[1],self.drop_window],layout=Layout(width='25%'))
        group3 = VBox([self.buttons_view[2],self.drop_window,self.slide_Nframes,self.text_Nframes,self.item_label],layout=Layout(width='25%'))
        group4 = VBox([self.buttons_view[3],self.drop_window],layout=Layout(width='25%'))
        
        display(HBox(self.buttons_measure))
        self.p = plotting.PlotData()
        display(HBox(self.text_axes))
        display(HBox([group1,group2,group3,group4]))
        display(HBox(self.buttons_save))
        
        
        
        
        #display(HBox([self.drop_window,self.slide_Nframes,self.text_Nframes]))
        
        self.text_axes[3].observe(self.xmin, names='value')
        self.text_axes[4].observe(self.xmax, names='value')
        self.text_axes[5].observe(self.ymin, names='value')
        self.text_axes[6].observe(self.ymax, names='value')
        
        self.button_X.on_click(self.auto_x)
        self.button_Y.on_click(self.auto_y)
        
        self.slide_Nframes.observe(self.nframes_slide)
        self.text_Nframes.observe(self.nframes_text)
        
        self.buttons_measure[0].on_click(self.measure)
        self.buttons_measure[1].on_click(self.undo)
        
        self.buttons_view[0].on_click(self.time)
        self.buttons_view[1].on_click(self.fft)
        self.buttons_view[2].on_click(self.tf)
        self.buttons_view[3].on_click(self.tf_av)
        
        self.buttons_save[0].on_click(self.save_data)
        self.buttons_save[1].on_click(self.save_fig)
        
        
        display(self.out)
        
#        self.buttons_save[0].on_click(self.save_data)
#        self.buttons_save[1].on_click(self.save_fig)
#        self.buttons_save[2].on_click(self.save_all)
    
    def xmin(self,v):
        xmin = self.text_axes[3].value
        xlim = self.p.ax.get_xlim()
        self.p.ax.set_xlim([xmin,xlim[1]])
        
    def xmax(self,v):
        xmax = self.text_axes[4].value
        xlim = self.p.ax.get_xlim()
        self.p.ax.set_xlim([xlim[0],xmax])
        
    def ymin(self,v):
        ymin = self.text_axes[5].value
        ylim = self.p.ax.get_ylim()
        self.p.ax.set_ylim([ymin,ylim[1]])
        
    def ymax(self,v):
        ymax = self.text_axes[6].value
        ylim = self.p.ax.get_ylim()
        self.p.ax.set_ylim([ylim[0],ymax])
        
    def auto_x(self,b):
        self.p.auto_x()
        
    def auto_y(self,b):
        self.p.auto_y()
        
    def nframes_slide(self,v):
        self.N_frames = self.slide_Nframes.value
        self.text_Nframes.value = self.N_frames
        self.item_label.value = "Frame length = {:.2f} seconds.".format(self.settings.stored_time/self.N_frames)
        if self.current_view is 'TF':
            self.tf(None)
        
    def nframes_text(self,v):
        self.N_frames = self.text_Nframes.value
        self.slide_Nframes.value = self.N_frames
        self.item_label.value = "Frame length = {:.2f} seconds.".format(self.settings.stored_time/self.N_frames)
        if self.current_view is 'TF':
            self.tf(None)
        
    def measure(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        #self.out = Output()
        #display(self.out)
        with self.out:
            d = acquisition.log_data(self.settings,rec=self.rec)
            self.dataset.add_to_dataset(d.time_data_list)
            N = len(self.dataset.time_data_list)
            self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
            self.p.auto_x()
            self.p.auto_y()
            
            
            
        xlim = self.p.ax.get_xlim()
        ylim = self.p.ax.get_ylim()
        self.text_axes[3].value = xlim[0]
        self.text_axes[4].value = xlim[1]
        self.text_axes[5].value = ylim[0]
        self.text_axes[6].value = ylim[1]
        
        
    def undo(self,b):
        self.dataset.remove_last_data_item('TimeData')
        N = len(self.dataset.time_data_list)
        self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
        
    def time(self,b):
        N = len(self.dataset.time_data_list)
        self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
        if self.current_view is not 'Time':
            self.current_view = 'Time'
            self.p.auto_x()
            self.p.auto_y()
        xlim = self.p.ax.get_xlim()
        ylim = self.p.ax.get_ylim()
        self.text_axes[3].value = xlim[0]
        self.text_axes[4].value = xlim[1]
        self.text_axes[5].value = ylim[0]
        self.text_axes[6].value = ylim[1]
            
    def fft(self,b):
        window = self.drop_window.value
        if window is 'None':
            window = None
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        #self.out = Output()
        #display(self.out)
        with self.out:
            self.dataset.calculate_fft_set(window=window)
            self.p.update(self.dataset.freq_data_list)
            if self.current_view is not 'FFT':
                self.current_view = 'FFT'
                self.p.auto_x()
                self.p.auto_y() 
                
            xlim = self.p.ax.get_xlim()
            ylim = self.p.ax.get_ylim()
            self.text_axes[3].value = xlim[0]
            self.text_axes[4].value = xlim[1]
            self.text_axes[5].value = ylim[0]
            self.text_axes[6].value = ylim[1]
        
    
    def tf(self,b):
        N_frames = self.N_frames
        window = self.drop_window.value
        if window is 'None':
            window = None
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        #self.out = Output()
        #display(self.out)
        with self.out:
            self.dataset.calculate_tf_set(window=window,N_frames=N_frames)
            self.p.update(self.dataset.tf_data_list)
            if self.current_view is not 'TF':
                self.current_view = 'TF'
                self.p.auto_x()
                self.p.auto_y()
            xlim = self.p.ax.get_xlim()
            ylim = self.p.ax.get_ylim()
            self.text_axes[3].value = xlim[0]
            self.text_axes[4].value = xlim[1]
            self.text_axes[5].value = ylim[0]
            self.text_axes[6].value = ylim[1]
    
    def tf_av(self,b):
        window = self.drop_window.value
        if window is 'None':
            window = None
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        #self.out = Output()
        #display(self.out)
        with self.out:
            self.dataset.calculate_tf_averaged(window=window)
            self.p.update(self.dataset.tf_data_list)
            if self.current_view is not 'TFAV':
                self.current_view = 'TFAV'
                self.p.auto_x()
                self.p.auto_y()
                
            xlim = self.p.ax.get_xlim()
            ylim = self.p.ax.get_ylim()
            self.text_axes[3].value = xlim[0]
            self.text_axes[4].value = xlim[1]
            self.text_axes[5].value = ylim[0]
            self.text_axes[6].value = ylim[1]
    
    def save_data(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        with self.out:
            print('Saving dataset:')
            print(self.dataset)
            self.dataset.save_data()
            
    
    def save_fig(self,b):
        pass
    
    def save_all(self,b):
        pass
    
    

                