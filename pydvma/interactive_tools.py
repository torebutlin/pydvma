from . import plotting
from . import datastructure
from . import acquisition
from . import analysis
from . import streams
from . import file

import numpy as np
from IPython.display import display
from ipywidgets import Button, HBox, VBox, Output, FloatText, IntText, Dropdown, IntSlider, Layout, Label


#%%
class InteractiveLogging():
    def __init__(self,settings,test_name=None,default_window='hanning'):
        
        if default_window is None:
            default_window = 'None'
        self.settings = settings
        self.test_name = test_name
        self.dataset = datastructure.DataSet()
        
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out = Output()
        self.out_logging = Output()
        streams.start_stream(settings)
        self.rec = streams.REC
        
        # Initialise variables
        self.current_view = 'Time'    
        self.N_frames = 1
        self.iw_fft_power = 0
        self.iw_tf_power = 0

        # puts plot inside widget so can have buttons next to plot
        self.outplot = Output(layout=Layout(width='85%'))
                
        # BUTTONS
        items_measure = ['Log Data','Delete Last Measurement','Reset (clears all data)','Load Data']
        items_view = ['View Time', 'View FFT', 'View TF']
        items_calc = ['Calc FFT', 'Calc TF', 'Calc TF average']
        items_axes = ['xmin','xmax','ymin','ymax']
        items_save = ['Save Dataset','Save Figure']
        items_iw   = ['multiply iw','divide iw']
        
        self.buttons_measure= [Button(description=i, layout=Layout(width='33%')) for i in items_measure]
        self.buttons_measure[0].button_style ='success'
        self.buttons_measure[0].style.font_weight = 'bold'
        self.buttons_measure[1].button_style ='warning'
        self.buttons_measure[1].style.font_weight = 'bold'
        self.buttons_measure[2].button_style ='danger'
        self.buttons_measure[2].style.font_weight = 'bold'
        self.buttons_measure[3].button_style ='primary'
        self.buttons_measure[3].style.font_weight = 'bold'
        
        self.buttons_view = [Button(description=i, layout=Layout(width='95%')) for i in items_view]
        self.buttons_view[0].button_style ='info'
        self.buttons_view[1].button_style ='info'
        self.buttons_view[2].button_style ='info'
        
        self.buttons_calc = [Button(description=i, layout=Layout(width='99%')) for i in items_calc]
        self.buttons_calc[0].button_style ='primary'
        self.buttons_calc[1].button_style ='primary'
        self.buttons_calc[2].button_style ='primary'

        
        self.buttons_iw_fft = [Button(description=i, layout=Layout(width='50%')) for i in items_iw]
        self.buttons_iw_fft[0].button_style = 'info'
        self.buttons_iw_fft[1].button_style = 'info'
        
        self.buttons_iw_tf = [Button(description=i, layout=Layout(width='50%')) for i in items_iw]
        self.buttons_iw_tf[0].button_style = 'info'
        self.buttons_iw_tf[1].button_style = 'info'
        
        self.buttons_match = Button(description='Match Amplitudes', layout=Layout(width='99%'))
        self.buttons_match.button_style = 'info'
        
        self.buttons_save = [Button(description=i, layout=Layout(width='50%')) for i in items_save]
        self.buttons_save[0].button_style = 'success'
        self.buttons_save[0].style.font_weight = 'bold'
        self.buttons_save[1].button_style = 'success'
        self.buttons_save[1].style.font_weight = 'bold'
        
        self.button_warning = Button(description='WARNING: Data may be clipped. Press here to delete last measurement.', layout=Layout(width='100%'))
        self.button_warning.button_style = 'danger'
        self.button_warning.style.font_weight='bold'
        
        self.button_X = Button(description='Auto X', layout=Layout(width='95%'))
        self.button_Y = Button(description='Auto Y', layout=Layout(width='95%'))
        self.button_X.button_style ='success'
        self.button_Y.button_style ='success'
        
        # TEXT/LABELS/DROPDOWNS
        self.item_iw_fft_label = Label(value='iw power={}'.format(0),layout=Layout(width='100%'))
        self.item_iw_tf_label  = Label(value='iw power={}'.format(0),layout=Layout(width='100%'))
        self.item_label = Label(value="Frame length = {:.2f} seconds.".format(settings.stored_time/self.N_frames))
        self.item_axis_label = Label(value="Axes control:",layout=Layout(width='95%'))
        self.item_view_label = Label(value="View data:",layout=Layout(width='95%'))
        self.item_blank_label = Label(value="",layout=Layout(width='95%'))
        self.text_axes = [FloatText(value=0,description=i, layout=Layout(width='95%')) for i in items_axes]
        self.text_axes =  [self.button_X]+[self.button_Y] + self.text_axes
        self.drop_window = Dropdown(options=['None', 'hanning'],value=default_window,description='Window:', layout=Layout(width='99%'))
        self.slide_Nframes = IntSlider(value=1,min=1,max=30,step=1,description='N_frames:',continuous_update=True,readout=False, layout=Layout(width='99%'))
        self.text_Nframes = IntText(value=1,description='N_frames:', layout=Layout(width='99%'))
        
        # VERTICAL GROUPS
        
        group0 = VBox([self.buttons_calc[0],self.drop_window,HBox(self.buttons_iw_fft)],layout=Layout(width='33%'))
        group1 = VBox([self.buttons_calc[1],self.drop_window,self.slide_Nframes,self.text_Nframes,self.item_label,HBox(self.buttons_iw_tf),self.buttons_match],layout=Layout(width='33%'))
        group2 = VBox([self.buttons_calc[2],self.drop_window,HBox(self.buttons_iw_tf),self.buttons_match],layout=Layout(width='33%'))
        
        group_view = VBox([self.item_blank_label,self.item_axis_label]+self.text_axes+[self.item_blank_label,self.item_view_label]+self.buttons_view,layout=Layout(width='20%'))
        
        # ASSEMBLE
        display(HBox([self.button_warning]))
        display(HBox(self.buttons_measure))
        display(self.out_logging)
        display(HBox([self.outplot,group_view]))
        display(HBox([group0,group1,group2]))
        display(HBox(self.buttons_save))
        self.button_warning.layout.visibility='hidden'
        
        # second part to putting plot inside widget
        with self.outplot:
            self.p = plotting.PlotData(figsize=(7.5,4))
        
        
        ## Make buttons/boxes interactive
        
        self.text_axes[2].observe(self.xmin, names='value')
        self.text_axes[3].observe(self.xmax, names='value')
        self.text_axes[4].observe(self.ymin, names='value')
        self.text_axes[5].observe(self.ymax, names='value')
        
        self.button_X.on_click(self.auto_x)
        self.button_Y.on_click(self.auto_y)
        
        self.slide_Nframes.observe(self.nframes_slide)
        self.text_Nframes.observe(self.nframes_text)
        
        self.buttons_measure[0].on_click(self.measure)
        self.buttons_measure[1].on_click(self.undo)
        self.buttons_measure[2].on_click(self.reset)
        self.buttons_measure[3].on_click(self.load_data)
        
        self.buttons_view[0].on_click(self.view_time)
        self.buttons_view[1].on_click(self.view_fft)
        self.buttons_view[2].on_click(self.view_tf)
        
        self.buttons_calc[0].on_click(self.fft)
        self.buttons_calc[1].on_click(self.tf)
        self.buttons_calc[2].on_click(self.tf_av)
        
        self.buttons_iw_fft[0].on_click(self.xiw_fft)
        self.buttons_iw_fft[1].on_click(self.diw_fft)
        self.buttons_iw_tf[0].on_click(self.xiw_tf)
        self.buttons_iw_tf[1].on_click(self.diw_tf)
        
        self.buttons_match.on_click(self.match)
        
        self.buttons_save[0].on_click(self.save_data)
        self.buttons_save[1].on_click(self.save_fig)
        
        self.button_warning.on_click(self.undo)
        
        self.refresh_buttons()
        
        # Put output text at bottom of display
        display(self.out)
        
    
    def xmin(self,v):
        xmin = self.text_axes[2].value
        xlim = self.p.ax.get_xlim()
        self.p.ax.set_xlim([xmin,xlim[1]])
        
    def xmax(self,v):
        xmax = self.text_axes[3].value
        xlim = self.p.ax.get_xlim()
        self.p.ax.set_xlim([xlim[0],xmax])
        
    def ymin(self,v):
        ymin = self.text_axes[4].value
        ylim = self.p.ax.get_ylim()
        self.p.ax.set_ylim([ymin,ylim[1]])
        
    def ymax(self,v):
        ymax = self.text_axes[5].value
        ylim = self.p.ax.get_ylim()
        self.p.ax.set_ylim([ylim[0],ymax])
        
    def auto_x(self,b):
        self.p.auto_x()
        
    def auto_y(self,b):
        self.p.auto_y()
        
    def nframes_slide(self,v):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            self.N_frames = self.slide_Nframes.value
            self.text_Nframes.value = self.N_frames
            if len(self.dataset.time_data_list) is not 0:
                stored_time = self.dataset.time_data_list[0].settings.stored_time
            elif len(self.dataset.tf_data_list) is not 0:
                stored_time = self.dataset.tf_data_list[0].settings.stored_time
            else:
                stored_time = 0
                print('Time or TF data settings not found')
                
            self.item_label.value = "Frame length = {:.2f} seconds.".format(stored_time/self.N_frames)
            if self.current_view is 'TF':
                self.tf(None)
        
    def nframes_text(self,v):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            self.N_frames = self.text_Nframes.value
            self.slide_Nframes.value = self.N_frames
            self.item_label.value = "Frame length = {:.2f} seconds.".format(self.settings.stored_time/self.N_frames)
            if self.current_view is 'TF':
                self.tf(None)
        
    def measure(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            self.rec.trigger_detected = False
            d = acquisition.log_data(self.settings,test_name=self.test_name, rec=self.rec)
            self.dataset.add_to_dataset(d.time_data_list)
            N = len(self.dataset.time_data_list)
            self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
            self.p.auto_x()
#            self.p.auto_y()
            self.p.ax.set_ylim([-1,1])
            self.current_view='Time'
            if np.any(np.abs(d.time_data_list[-1].time_data) > 0.95):
                self.button_warning.layout.visibility = 'visible'
            else:
                self.button_warning.layout.visibility = 'hidden'
            
            xlim = self.p.ax.get_xlim()
            ylim =  self.p.ax.get_ylim()
            self.text_axes[2].value = xlim[0]
            self.text_axes[3].value = xlim[1]
            self.text_axes[4].value = ylim[0]
            self.text_axes[5].value = ylim[1]
            self.refresh_buttons()
        
        
    def undo(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            self.dataset.remove_last_data_item('TimeData')
            self.dataset.freq_data_list = datastructure.FreqDataList()
            self.dataset.tf_data_list = datastructure.TfDataList()
            N = len(self.dataset.time_data_list)
            self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
            self.button_warning.layout.visibility = 'hidden'
            self.refresh_buttons()
            
    def reset(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.dataset = datastructure.DataSet()
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            N = len(self.dataset.time_data_list)
            self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
            self.refresh_buttons()
        
    def load_data_old(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            self.dataset=file.load_data()
            self.refresh_buttons()
            self.current_view=None
            if len(self.dataset.time_data_list) is not 0:
                self.settings = self.dataset.time_data_list[0].settings
                self.view_time(None)
            elif len(self.dataset.freq_data_list) is not 0:
                self.settings = self.dataset.freq_data_list[0].settings
                self.view_fft(None)
            elif len(self.dataset.tf_data_list) is not 0:
                self.settings = self.dataset.tf_data_list[0].settings
                self.view_tf(None)
            else:
                print('no data to view')
                
    def load_data(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            d = file.load_data()
            if d is not None:
                self.dataset.add_to_dataset(d.time_data_list)
                self.dataset.add_to_dataset(d.freq_data_list)
                self.dataset.add_to_dataset(d.tf_data_list)
                self.dataset.add_to_dataset(d.cross_spec_data_list)
                self.dataset.add_to_dataset(d.sono_data_list)
            else:
                print('No data loaded')
            
            if len(self.dataset.time_data_list) is not 0:
                N = len(self.dataset.time_data_list)
                self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
            elif len(self.dataset.freq_data_list) is not 0:
                N = len(self.dataset.freq_data_list)
                self.p.update(self.dataset.freq_data_list,sets=[N-1],channels='all')
            elif len(self.dataset.tf_data_list) is not 0:
                N = len(self.dataset.tf_data_list)
            else:
                print('No data to view')
           
            self.refresh_buttons()
        
            self.p.auto_x()
            self.p.auto_y()
            
            xlim = self.p.ax.get_xlim()
            ylim = self.p.ax.get_ylim()
            self.text_axes[2].value = xlim[0]
            self.text_axes[3].value = xlim[1]
            self.text_axes[4].value = ylim[0]
            self.text_axes[5].value = ylim[1]
            
        
        
    def view_time(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            self.refresh_buttons()
            N = len(self.dataset.time_data_list)
            if N is not 0:
                self.p.update(self.dataset.time_data_list)
                if self.current_view is not 'Time':
                    self.current_view = 'Time'
                    self.p.auto_x()
                    self.p.auto_y()

                xlim = self.p.ax.get_xlim()
                ylim = self.p.ax.get_ylim()
                self.text_axes[2].value = xlim[0]
                self.text_axes[3].value = xlim[1]
                self.text_axes[4].value = ylim[0]
                self.text_axes[5].value = ylim[1]
            else:
                print('no time data to display')
                
    def view_fft(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            N = len(self.dataset.freq_data_list)
            self.refresh_buttons()
            if N is not 0:
                self.p.update(self.dataset.freq_data_list)
                if self.current_view is not 'FFT':
                    self.current_view = 'FFT'
                    self.p.auto_x()
                    self.p.auto_y() 
                    
                xlim = self.p.ax.get_xlim()
                ylim = self.p.ax.get_ylim()
                self.text_axes[2].value = xlim[0]
                self.text_axes[3].value = xlim[1]
                self.text_axes[4].value = ylim[0]
                self.text_axes[5].value = ylim[1]
            else:
                print('no FFT data to display')
                
    def view_tf(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            N = len(self.dataset.tf_data_list)
            self.refresh_buttons()
            if N is not 0:
                self.p.update(self.dataset.tf_data_list)
                if self.current_view is not 'TF':
                    self.current_view = 'TF'
                    self.p.auto_x()
                    self.p.auto_y()
                xlim = self.p.ax.get_xlim()
                ylim = self.p.ax.get_ylim()
                self.text_axes[2].value = xlim[0]
                self.text_axes[3].value = xlim[1]
                self.text_axes[4].value = ylim[0]
                self.text_axes[5].value = ylim[1]
            else:
                print('no TF data to display')
            
    def fft(self,b):
        window = self.drop_window.value
        if window is 'None':
            window = None
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            self.dataset.calculate_fft_set(window=window)
            self.p.update(self.dataset.freq_data_list)
            if self.current_view is not 'FFT':
                self.current_view = 'FFT'
                self.p.auto_x()
                self.p.auto_y() 
                
            xlim = self.p.ax.get_xlim()
            ylim = self.p.ax.get_ylim()
            self.text_axes[2].value = xlim[0]
            self.text_axes[3].value = xlim[1]
            self.text_axes[4].value = ylim[0]
            self.text_axes[5].value = ylim[1]
            self.refresh_buttons()
        
    
    def tf(self,b):
        N_frames = self.N_frames
        window = self.drop_window.value
        if window is 'None':
            window = None
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            self.dataset.calculate_tf_set(window=window,N_frames=N_frames)
            self.p.update(self.dataset.tf_data_list)
            if self.current_view is not 'TF':
                self.current_view = 'TF'
                self.p.auto_x()
                self.p.auto_y()
            xlim = self.p.ax.get_xlim()
            ylim = self.p.ax.get_ylim()
            self.text_axes[2].value = xlim[0]
            self.text_axes[3].value = xlim[1]
            self.text_axes[4].value = ylim[0]
            self.text_axes[5].value = ylim[1]
            self.refresh_buttons()
    
    def tf_av(self,b):
        window = self.drop_window.value
        if window is 'None':
            window = None
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            self.dataset.calculate_tf_averaged(window=window)
            self.p.update(self.dataset.tf_data_list)
            if self.current_view is not 'TFAV':
                self.current_view = 'TFAV'
                self.p.auto_x()
                self.p.auto_y()
                
            xlim = self.p.ax.get_xlim()
            ylim = self.p.ax.get_ylim()
            self.text_axes[2].value = xlim[0]
            self.text_axes[3].value = xlim[1]
            self.text_axes[4].value = ylim[0]
            self.text_axes[5].value = ylim[1]
            self.refresh_buttons()
            
    def xiw_fft(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            if self.current_view is 'FFT':
                s = self.p.get_selected_channels()
                n_sets,n_chans = np.shape(s)
                for ns in range(n_sets):
                    newdata = analysis.multiply_by_power_of_iw(self.dataset.freq_data_list[ns],power=1,channel_list=s[ns,:])
                    self.dataset.freq_data_list[ns] = newdata
                self.p.update(self.dataset.freq_data_list)
                self.p.auto_y()
                self.iw_fft_power += 1
                print('Multiplied by (iw)**{}'.format(self.iw_fft_power))
            else:
                print('First press <Calc FFT>')
    
    def diw_fft(self,b):
       # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            if self.current_view is 'FFT':
                s = self.p.get_selected_channels()
                n_sets,n_chans = np.shape(s)
                for ns in range(n_sets):
                    newdata = analysis.multiply_by_power_of_iw(self.dataset.freq_data_list[ns],power=-1,channel_list=s[ns,:])
                    self.dataset.freq_data_list[ns] = newdata
                self.p.update(self.dataset.freq_data_list)
                self.p.auto_y()
                self.iw_fft_power -= 1
                print('Multiplied by (iw)**{}'.format(self.iw_fft_power))
            else:
                print('First press <Calc FFT>')
                
    def xiw_tf(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            if (self.current_view is 'TF') or (self.current_view is 'TFAV'):
                s = self.p.get_selected_channels()
                n_sets,n_chans = np.shape(s)
                for ns in range(n_sets):
                    newdata = analysis.multiply_by_power_of_iw(self.dataset.tf_data_list[ns],power=1,channel_list=s[ns,:])
                    self.dataset.tf_data_list[ns] = newdata
                self.p.update(self.dataset.tf_data_list)
                self.p.auto_y()
                self.iw_tf_power += 1
                print('Multiplied selected channel by (iw)**{}'.format(self.iw_tf_power))
            else:
                print('First press <Calc TF> or <Calc TF average>')
                
    def diw_tf(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            if (self.current_view is 'TF') or (self.current_view is 'TFAV'):
                s = self.p.get_selected_channels()
                n_sets,n_chans = np.shape(s)
                for ns in range(n_sets):
                    newdata = analysis.multiply_by_power_of_iw(self.dataset.tf_data_list[ns],power=-1,channel_list=s[ns,:])
                    self.dataset.tf_data_list[ns] = newdata
                self.p.update(self.dataset.tf_data_list)
                self.p.auto_y()
                self.iw_tf_power -= 1
                print('Multiplied selected channel by (iw)**{}'.format(self.iw_tf_power))
            else:
                print('First press <Calc TF> or <Calc TF average>')
                
    def match(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            if (self.current_view is 'TF') or (self.current_view is 'TFAV'):
                freq_range = self.p.ax.get_xlim()
                current_calibration_factors = self.dataset.tf_data_list.get_calibration_factors()
                reference = current_calibration_factors[0][0]
                factors = analysis.best_match(self.dataset.tf_data_list,freq_range=freq_range,set_ref=0,ch_ref=0)
                factors = [reference*x for x in factors]
                self.dataset.tf_data_list.set_calibration_factors_all(factors)
                self.p.update(self.dataset.tf_data_list)
                print('scale factors:')
                print(factors)
                #self.p.auto_y()
            else:
                print('First press <View TF> or <Calc TF> or <Calc TF average>')
    
    def save_data(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            print('Saving dataset:')
            print(self.dataset)
            self.dataset.save_data()
            
    
    def save_fig(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        self.out_logging.clear_output(wait=False)
        with self.out_logging:
            file.save_fig(self.p)
            
    def refresh_buttons(self):
        if len(self.dataset.time_data_list) is 0:
            self.buttons_view[0].button_style =''
        else:
            self.buttons_view[0].button_style ='info'
            
        if len(self.dataset.freq_data_list) is 0:
            self.buttons_view[1].button_style =''
        else:
            self.buttons_view[1].button_style ='info'
            
        if len(self.dataset.tf_data_list) is 0:
            self.buttons_view[2].button_style =''
        else:
            self.buttons_view[2].button_style ='info'
    




#%%
class InteractiveView():
    def __init__(self):
        
        
        self.dataset = datastructure.DataSet()
        
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out = Output()
        self.out_logging = Output()
        
        # Initialise
        self.current_view = 'Time'    
        self.N_frames = 1
        
        # BUTTONS
        items_load = ['Load Data','Reset (deletes loaded data)']
        items_view = ['View Time', 'View FFT', 'View TF']
        items_axes = ['xmin','xmax','ymin','ymax']
        items_save = ['Save Dataset','Save Figure']
        
        
        self.buttons_load = [Button(description=i, layout=Layout(width='50%')) for i in items_load]
        self.buttons_load[0].button_style ='primary'
        self.buttons_load[0].style.font_weight = 'bold'
        self.buttons_load[1].button_style ='warning'
        self.buttons_load[1].style.font_weight = 'bold'

        
        self.buttons_view = [Button(description=i, layout=Layout(width='99%')) for i in items_view]
        self.buttons_view[0].button_style ='info'
        self.buttons_view[1].button_style ='info'
        self.buttons_view[2].button_style ='info'
        
        self.buttons_match = Button(description='Match Amplitudes', layout=Layout(width='99%'))
        self.buttons_match.button_style = 'info'
        
        
        self.buttons_save = [Button(description=i, layout=Layout(width='50%')) for i in items_save]
        self.buttons_save[0].button_style = 'success'
        self.buttons_save[0].style.font_weight = 'bold'
        self.buttons_save[1].button_style = 'success'
        self.buttons_save[1].style.font_weight = 'bold'
        
        
        self.button_X = Button(description='Auto X', layout=Layout(width='10%'))
        self.button_Y = Button(description='Auto Y', layout=Layout(width='10%'))
        self.button_X.button_style ='success'
        self.button_Y.button_style ='success'
        
        # TEXT/LABELS/DROPDOWNS
        self.item_axis_label = Label(value="Adjust axes manually:",layout=Layout(width='16%'))
        self.text_axes = [FloatText(value=0,description=i, layout=Layout(width='16%')) for i in items_axes]
        self.text_axes = [self.button_X]+[self.button_Y] + [self.item_axis_label] + self.text_axes
        
        group1 = VBox([self.buttons_view[0]],layout=Layout(width='33%'))
        group2 = VBox([self.buttons_view[1]],layout=Layout(width='33%'))
        group3 = VBox([self.buttons_view[2],self.buttons_match],layout=Layout(width='33%'))
        
        # ASSEMBLE
        display(HBox(self.buttons_load))
        self.p = plotting.PlotData()
        display(HBox(self.text_axes))
        display(HBox([group1,group2,group3]))
        display(HBox(self.buttons_save))
        
        
        # Make interactive
        self.text_axes[3].observe(self.xmin, names='value')
        self.text_axes[4].observe(self.xmax, names='value')
        self.text_axes[5].observe(self.ymin, names='value')
        self.text_axes[6].observe(self.ymax, names='value')
        
        self.button_X.on_click(self.auto_x)
        self.button_Y.on_click(self.auto_y)
        
        
        
        self.buttons_load[0].on_click(self.load_data)
        self.buttons_load[1].on_click(self.undo)
        
        self.buttons_view[0].on_click(self.time)
        self.buttons_view[1].on_click(self.fft)
        self.buttons_view[2].on_click(self.tf)
        
        self.buttons_match.on_click(self.match)
        
        self.buttons_save[0].on_click(self.save_data)
        self.buttons_save[1].on_click(self.save_fig)
        
        self.refresh_buttons()
        
        # Put output text at bottom
        display(self.out)
        
    
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
        
        
    def load_data(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        with self.out:
            d = file.load_data()
            if d is not None:
                self.dataset.add_to_dataset(d.time_data_list)
                self.dataset.add_to_dataset(d.freq_data_list)
                self.dataset.add_to_dataset(d.tf_data_list)
                self.dataset.add_to_dataset(d.cross_spec_data_list)
                self.dataset.add_to_dataset(d.sono_data_list)
            else:
                print('No data loaded')
            
            if len(self.dataset.time_data_list) is not 0:
                N = len(self.dataset.time_data_list)
                self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
            elif len(self.dataset.freq_data_list) is not 0:
                N = len(self.dataset.freq_data_list)
                self.p.update(self.dataset.freq_data_list,sets=[N-1],channels='all')
            elif len(self.dataset.tf_data_list) is not 0:
                N = len(self.dataset.tf_data_list)
            else:
                print('No data to view')
           
            self.refresh_buttons()
        
            self.p.auto_x()
            self.p.auto_y()
            
            xlim = self.p.ax.get_xlim()
            ylim = self.p.ax.get_ylim()
            self.text_axes[3].value = xlim[0]
            self.text_axes[4].value = xlim[1]
            self.text_axes[5].value = ylim[0]
            self.text_axes[6].value = ylim[1]
        
        
    def undo(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.dataset = datastructure.DataSet()
        self.out.clear_output(wait=False)
        with self.out:
            N = len(self.dataset.time_data_list)
            self.p.update(self.dataset.time_data_list,sets=[N-1],channels='all')
        

        
    def time(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        with self.out:
            N = len(self.dataset.time_data_list)
            if N is not 0:
                self.p.update(self.dataset.time_data_list)
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
            else:
                print('no time data to display')
            
    def fft(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        with self.out:
            N = len(self.dataset.freq_data_list)
            if N is not 0:
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
            else:
                print('no FFT data to display')
    
    def tf(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        with self.out:
            N = len(self.dataset.tf_data_list)
            if N is not 0:
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
            else:
                print('no TF data to display')
                
    def match(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        with self.out:
            if self.current_view is 'TF':
                freq_range = self.p.ax.get_xlim()
                current_calibration_factors = self.dataset.tf_data_list.get_calibration_factors()
                reference = current_calibration_factors[0][0]
                factors = analysis.best_match(self.dataset.tf_data_list,freq_range=freq_range,set_ref=0,ch_ref=0)
                factors = [reference*x for x in factors]
                self.dataset.tf_data_list.set_calibration_factors_all(factors)
                self.p.update(self.dataset.tf_data_list)
                print('scale factors:')
                print(factors)
                #self.p.auto_y()
            else:
                print('First press <View TF>')
            
    
    
    def save_data(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        with self.out:
            print('Saving dataset:')
            print(self.dataset)
            self.dataset.save_data()
            
    
    def save_fig(self,b):
        # the 'out' construction is to refresh the text output at each update 
        # to stop text building up in the widget display
        self.out.clear_output(wait=False)
        with self.out:
            file.save_fig(self.p)
    
    def refresh_buttons(self):
        if len(self.dataset.time_data_list) is 0:
            self.buttons_view[0].button_style =''
        else:
            self.buttons_view[0].button_style ='info'
            
        if len(self.dataset.freq_data_list) is 0:
            self.buttons_view[1].button_style =''
        else:
            self.buttons_view[1].button_style ='info'
            
        if len(self.dataset.tf_data_list) is 0:
            self.buttons_view[2].button_style =''
        else:
            self.buttons_view[2].button_style ='info'
                