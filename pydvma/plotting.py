# -*- coding: utf-8 -*-
"""
Created on Tue Aug 28 19:04:14 2018

@author: tb267
"""



from . import options
from . import datastructure

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
matplotlib.rcParams.update({'font.size': 10,'font.family':'serif'})
from matplotlib.ticker import AutoLocator

LINE_ALPHA = 0.9

class PlotSonoData():
    def __init__(self,figsize=(9,5),canvas=None,fig=None):
        if canvas==None:
            self.fig, self.ax = plt.subplots(1,1,figsize=figsize,dpi=100)#,constrained_layout=True)
        else:
            self.fig = fig
            self.canvas = canvas
            self.ax = self.canvas.figure.subplots()
        
        self.ax.grid(False)
        self.fig.canvas.draw()
        
    def update(self,sono_data_list,n_set=0,n_chan=0):
        
        f = sono_data_list[n_set].freq_axis
        t = sono_data_list[n_set].time_axis
        S = sono_data_list[n_set].sono_data[:,:,n_chan]
        self.ax.pcolor(t,f,20*np.log10(np.abs(S)))
        self.ax.set_xlabel('Time (s)')
        self.ax.set_ylabel('Frequency (Hz)')
    

class PlotData():
    def __init__(self,sets='all',channels='all',figsize=(9,5),canvas=None,fig=None):
        if canvas==None:
            self.fig, self.ax = plt.subplots(1,1,figsize=figsize,dpi=100)
        else:
            self.fig = fig
            self.canvas = canvas
            self.ax = self.canvas.figure.subplots()

        #ax2 is for coherence
        self.ax2 = self.ax.twinx()
        self.ax2.set_visible(False)
        self.ax.set_zorder(self.ax2.get_zorder()+1)
        self.ax.patch.set_visible(False)
        
#        #ax3 is for sonograms: 
#        self.ax2 = self.ax.twinx()
#        self.ax2.set_visible(False)
#        self.ax.set_zorder(self.ax2.get_zorder()+1)
#        self.ax.patch.set_visible(False)

        self.ax.lines.clear()
        self.ax2.lines.clear()
        self.line_listbyset = []
        self.line2_listbyset = []
        self.pcolor_sono = None
        self.visibility = True
        
        self.ax.grid(True,alpha=0.2)
        self.fig.canvas.mpl_connect('pick_event', self.channel_select)
        self.fig.canvas.draw()
        
    def update(self,data_list,sets='all',channels='all',xlinlog='linear',show_coherence=True,plot_type=None,coherence_plot_type='linear',freq_range=None, auto_xy='xyc'):
        global LINE_ALPHA
        
        # when switching back from sonogram, remove all pcolormesh parts of plot
        for ch in self.ax.get_children():
                if ch.__class__.__name__ == 'QuadMesh':
                    ch.remove()
                    self.visibility = True # turn legend back on
        
        
        self.ax.grid(True,alpha=0.2)
        self.data_list = data_list
        self.plot_type = plot_type
        self.freq_range = freq_range
        self.xlinlog = xlinlog
        
        if data_list.__class__.__name__ == 'TimeDataList':
            self.ax2.set_visible(False)
            self.ax.set_xlabel('Time (s)')
            self.ax.set_ylabel('Amplitude')
            self.ax.axis('auto')
        elif data_list.__class__.__name__ == 'FreqDataList':
            self.ax2.set_visible(False)
            if (plot_type == 'Amplitude (dB)') or (plot_type == None):
                self.ax.set_xlabel('Frequency (Hz)')
                self.ax.set_ylabel('Amplitude (dB)')
                self.ax.axis('auto')
            elif plot_type == 'Amplitude (linear)':
                self.ax.set_xlabel('Frequency (Hz)')
                self.ax.set_ylabel('Amplitude')
                self.ax.axis('auto')
            elif plot_type == 'Real Part':
                self.ax.set_xlabel('Frequency (Hz)')
                self.ax.set_ylabel('Real Part')
                self.ax.axis('auto')
            elif plot_type == 'Imag Part':
                self.ax.set_xlabel('Frequency (Hz)')
                self.ax.set_ylabel('Imag Part')
                self.ax.axis('auto')
            elif plot_type == 'Nyquist':
                self.ax.set_xlabel('Real Part')
                self.ax.set_ylabel('Imag Part')
                self.ax.set_aspect('equal','datalim')
            elif plot_type == 'Phase':
                self.ax.set_xlabel('Frequency (Hz)')
                self.ax.set_ylabel('Phase (deg)')
                self.ax.axis('auto')
                
            self.ax.set_xscale(xlinlog)
            if 'log' in xlinlog:
                self.ax.grid(b=True, which='minor',axis='x',alpha=0.2)
            else:
                self.ax.grid(b=False)
            
        elif data_list.__class__.__name__ == 'TfDataList':
            if (plot_type == 'Amplitude (dB)') or (plot_type == None):
                self.ax.set_xlabel('Frequency (Hz)')
                self.ax.set_ylabel('Amplitude (dB)')
                self.ax.axis('auto')
            elif plot_type == 'Amplitude (linear)':
                self.ax.set_xlabel('Frequency (Hz)')
                self.ax.set_ylabel('Amplitude')
                self.ax.axis('auto')
            elif plot_type == 'Real Part':
                self.ax.set_xlabel('Frequency (Hz)')
                self.ax.set_ylabel('Real Part')
                self.ax.axis('auto')
            elif plot_type == 'Imag Part':
                self.ax.set_xlabel('Frequency (Hz)')
                self.ax.set_ylabel('Imag Part')
                self.ax.axis('auto')
            elif plot_type == 'Nyquist':
                self.ax.set_xlabel('Real Part')
                self.ax.set_ylabel('Imag Part')
                self.ax.set_aspect('equal','datalim')
            elif plot_type == 'Phase':
                self.ax.set_xlabel('Frequency (Hz)')
                self.ax.set_ylabel('Phase (deg)')
                self.ax.axis('auto')
            
            
            self.ax.set_xscale(xlinlog)
            if 'log' in xlinlog:
                self.ax.grid(b=True, which='minor',axis='x',alpha=0.2)
            else:
                self.ax.grid(b=False)
            
            # setup twin axis
            # don't plot coherence if no data, or if all coherence is one
            flag_coherence = []
            for n_set in range(len(data_list)):
                if data_list[n_set].tf_coherence is None:
                    flag_coherence += [True]
                else:
                    tfc = data_list[n_set].tf_coherence
                    i = np.isnan(tfc)
                    tfc[i] = 1
                    diff_to_one = np.abs(tfc - 1)
                    flag_coherence += [np.all(diff_to_one<1e-10)]
            if np.all(flag_coherence):
                show_coherence = False
            
            if show_coherence == True:
                self.ax2.set_ylabel('Coherence')
                self.ax2.set_visible(True)
            else:
                self.ax2.set_visible(False)
    
        # sonogram plot completely different, use separate function
        
        N_sets = len(data_list)

        # pre-count how many channels total
        ch_counter = 0
        for n_set in range(N_sets):
            if data_list.__class__.__name__ == 'TimeDataList':
                ch_counter += len(data_list[n_set].time_data[0,:])
            elif data_list.__class__.__name__ == 'FreqDataList':
                ch_counter += len(data_list[n_set].freq_data[0,:])
            elif data_list.__class__.__name__ == 'TfDataList':
                ch_counter += len(data_list[n_set].tf_data[0,:])

        self.ch_total = ch_counter
        if self.ch_total <= 12:
            LINE_ALPHA = 0.9
        else:
            # option to make lines fainter when more lines... needs some tweaking to make feel right
            LINE_ALPHA = 1-1/self.ch_total # make deselected lines fainter if more channels
        
        self.ax.lines.clear()
        self.ax2.lines.clear()
        self.line_listbyset = []
        self.line2_listbyset = []
        
        if sets == 'all':
            sets = range(N_sets)
        count = -1
        for n_set in range(len(data_list)):
            self.line_listbyset.append([])
            self.line2_listbyset.append([])
            
            if data_list.__class__.__name__ == 'TfDataList':
                N_chans = len(data_list[n_set].tf_data[0,:])
            elif data_list.__class__.__name__ == 'FreqDataList':
                N_chans = len(data_list[n_set].freq_data[0,:])
            elif data_list.__class__.__name__ == 'TimeDataList':
                N_chans = len(data_list[n_set].time_data[0,:])
                
            if channels == 'all':
                channels = range(N_chans)

            

            for n_chan in range(N_chans):
                count += 1
                if (n_set not in sets) or (n_chan not in channels):
                    alpha = 1-LINE_ALPHA
                else:
                    alpha = LINE_ALPHA
                
                if data_list.__class__.__name__ == 'TimeDataList':
                    x = data_list[n_set].time_axis
                    y = data_list[n_set].time_data[:,n_chan] * data_list[n_set].channel_cal_factors[n_chan]
        
                elif data_list.__class__.__name__ == 'FreqDataList':
                    x = data_list[n_set].freq_axis
                    ylin = data_list[n_set].freq_data[:,n_chan] * data_list[n_set].channel_cal_factors[n_chan]
                    
                    
                    if (plot_type == 'Amplitude (dB)') or (plot_type == None):
                        # handle log(0) manually to avoid warnings
                        y = np.zeros(np.shape(ylin))
                        izero = ylin==0
                        y[~izero] = 20*np.log10(np.abs(ylin[~izero]))
                        y[izero] = -np.inf
                    elif plot_type == 'Amplitude (linear)':
                        y = np.abs(ylin)
                    elif plot_type == 'Real Part':
                        y = np.real(ylin)
                    elif plot_type == 'Imag Part':
                        y = np.imag(ylin)
                    elif plot_type == 'Nyquist':
                        if freq_range == None:
                            freq_range = [-1,np.inf]
                        selected_data = np.where((x>freq_range[0]) * (x<freq_range[1]))[0]
                        x = np.real(ylin[selected_data])
                        y = np.imag(ylin[selected_data])
                        
                    elif plot_type == 'Phase':
                        y = np.angle(ylin,deg=True)
                        
                    
                elif data_list.__class__.__name__ == 'TfDataList':
                    x = data_list[n_set].freq_axis
                    ylin = data_list[n_set].tf_data[:,n_chan] * data_list[n_set].channel_cal_factors[n_chan]
                    if (plot_type == 'Amplitude (dB)') or (plot_type == None):
                        # handle log(0) manually to avoid warnings
                        y = np.zeros(np.shape(ylin))
                        izero = ylin==0
                        y[~izero] = 20*np.log10(np.abs(ylin[~izero]))
                        y[izero] = -np.inf
                        
                    elif plot_type == 'Amplitude (linear)':
                        y = np.abs(ylin)
                    elif plot_type == 'Real Part':
                        y = np.real(ylin)
                    elif plot_type == 'Imag Part':
                        y = np.imag(ylin)
                    elif plot_type == 'Nyquist':
                        if freq_range == None:
                            freq_range = [-1,np.inf]
                        selected_data = np.where((x>freq_range[0]) * (x<freq_range[1]))[0]
                        x = np.real(ylin[selected_data])
                        y = np.imag(ylin[selected_data])
                    elif plot_type == 'Phase':
                        y = np.angle(ylin,deg=True)
                    if data_list[n_set].tf_coherence is not None:
                        # handle log(0) manually to avoid warnings
                        yclin = data_list[n_set].tf_coherence[:,n_chan]
                        if coherence_plot_type == 'linear':
                            yc = yclin
                        elif coherence_plot_type == 'log':
                            yc = np.zeros(np.shape(yclin))
                            izero = yclin==0
                            yc[~izero] = 20*np.log10(np.abs(yclin[~izero]))
                            yc[izero] = -np.inf
                            yc = 20*np.log10(np.abs(yclin))
                    else:
                        yc = np.ones(np.shape(data_list[n_set].tf_data))
                        
                        
                color = options.set_plot_colours(ch_counter)[count,:]/255
                
                if type(data_list[n_set].test_name) is str:
                    test_name = data_list[n_set].test_name
                else:
                    test_name = ''
                    
                if test_name != '':
                    test_name = test_name + ': '
                    
                if self.ch_total < 10:
                    label = '{}set_{}, ch_{}'.format(test_name,n_set,n_chan)
                else:
                    label = 'set{},ch{}'.format(n_set,n_chan)
                    
                if data_list.__class__.__name__ == 'TfDataList':
                    if data_list[n_set].flag_modal_TF == True:
                        label = 'fit{}'.format(n_chan)
                        
                self.line_listbyset[n_set] += self.ax.plot(x,y,'-',linewidth=1,color = color,label=label,alpha=alpha)
                
                if data_list.__class__.__name__ == 'TfDataList':
                    if show_coherence == True:
                        self.line2_listbyset[n_set] += self.ax2.plot(x,yc,':',linewidth=1,color = color,label=label+' (coherence)',alpha=alpha)
                        self.ax2.set_visible(True)
                    else:
                        self.ax2.set_visible(False)
        
        self.fig.tight_layout()
        self.fig.canvas.draw()
        self.update_legend()
        if 'x' in auto_xy:
            self.auto_x()
        if 'f' in auto_xy: # use freq_range for x axis
            if ('log' in xlinlog) and freq_range[0]==0:
                self.lines = self.ax.get_lines()
                xminlog = np.inf
                for line in self.lines:
                    if line.get_alpha() > 0.5:
                        data = line.get_data()
                        xxlog = data[0][1] # first nonzero freq axis
                        xminlog = min([xminlog,xxlog])
                        freq_range[0] = xminlog
                self.ax.set_xlim(freq_range)
            else:
                self.ax.set_xlim(freq_range)
            self.fig.canvas.draw()
            self.auto_y()
        if 'y' in auto_xy:
            self.auto_y()
        if 'c' in auto_xy: # auto coherence y
            self.ax2.set_ylim([0,1])
            
#        self.ax.xaxis.set_major_locator(AutoLocator())
#        self.ax.yaxis.set_major_locator(AutoLocator())
        self.fig.canvas.draw()
        
        
        
    def update_legend(self,loc='lower right',draggable=False):
        
        if len(self.data_list) != 0:
            if self.ax.get_legend() is None:
                self.visibility = True
                
            if self.ch_total >= 10:
                # make legend more compact
                col_sizes = np.arange(10,7,-1)
                rem = np.remainder(self.ch_total,col_sizes)
                if any(rem==0):
                    remi = np.where(rem==0)[0]
                    remi = remi[0]
                    ncol = np.int(self.ch_total / col_sizes[remi])
                else:
                    remi = np.argmax(rem)
                    ncol = np.int(np.ceil(self.ch_total/ col_sizes[remi]))
            else:
                ncol = 1
                
            self.legend = self.ax.legend(loc=loc, ncol=ncol)
#            self.ax.legend()
            self.legend.set_draggable(draggable,use_blit=True)#(True),update='bbox',use_blit=True
            self.lines = self.ax.get_lines()
            self.lines2 = self.ax2.get_lines()
            self.lined = dict()
            self.lined2 = dict()

            # make dictionary of legend lines for selection    
            for legline, origline in zip(self.legend.get_lines(), self.lines):
                legline.set_picker(True)  # argument tolerance
                legline.set_pickradius(10)  # argument tolerance
                self.lined[legline] = origline
                legline.set_alpha(origline.get_alpha())

            # make dictionary of coherence lines to select with legend - only for TF Data
            if len(self.ax2.lines) > 0:
                for legline, origline2 in zip(self.legend.get_lines(), self.lines2):
                    self.lined2[legline] = origline2 
                    origline2.set_alpha(legline.get_alpha())
                    
            self.ax.get_legend().set_visible(self.visibility)
        else:
            self.legend = self.ax.get_legend()
            if self.legend is not None:
                self.legend.remove()
            self.fig.canvas.draw()
    
    
    def auto_x(self):
        if self.data_list.__class__.__name__ == 'SonoDataList':
            xlim = self.data_list[self.n_set].time_axis[[0,-1]]
            self.ax.set_xlim(xlim)
        else:
            self.lines = self.ax.get_lines()
            xmin = np.inf
            xminlog = np.inf
            xmax = -np.inf
            ymin = np.inf # for Nyquist to stop cropping
            ymax = -np.inf
            for line in self.lines:
                if line.get_alpha() > 0.5:
                    data = line.get_data()
                    try:
                        # handle when some lines are out of view
                        xx = min(data[0])
                        xmin = min([xx,xmin])
                        
                        xxlog = data[0][1] # first nonzero freq axis
                        xminlog = min([xminlog,xxlog])
                        
                        xx = max(data[0])
                        xmax = max([xx,xmax])
                        if self.plot_type == 'Nyquist':
                            yy = min(data[1])
                            ymin = min([yy,ymin])
                            yy = max(data[1])
                            ymax = max([yy,ymax])
                    except:
                        pass
            try:
                if 'log' in self.xlinlog:
                    self.ax.set_xlim([xminlog,xmax])
                else:
                    if self.plot_type == 'Nyquist':
                        # equal axis means need x range needs to stay greater than y range
                        yrange = ymax-ymin
                        # get bounding box bb to know current aspect ratio ar
                        bb=self.ax.get_window_extent().transformed(self.fig.dpi_scale_trans.inverted())
                        ar = bb.width / bb.height
                        if (xmax-xmin) < (ar*yrange):
                            xmid = (xmin+xmax)/2
                            xmax = xmid + ar*yrange/2
                            xmin = xmid - ar*yrange/2
                        
                    self.ax.set_xlim([xmin,xmax])
                    
            except:
                pass
        self.fig.canvas.draw()
        
        
    def auto_y(self):
        if self.data_list.__class__.__name__ == 'SonoDataList':
            ylim = self.data_list[self.n_set].freq_axis[[0,-1]]
            self.ax.set_ylim(ylim)
        else:
            self.lines = self.ax.get_lines()
            if (self.data_list.__class__.__name__ == 'TfData') and (self.plot_type != 'Nyquist'):
                # at the moment this doesn't get called
                # it should be TfDataList in condition
                # and it should be == nyquist not !=
                # but plot behaviour correct as it stands and probably just need this setting to xlim always
                xview = self.freq_range
            else:
                xview = self.ax.get_xlim()
            ymin = np.inf
            ymax = -np.inf
            c=-1
            for line in self.lines:
                c+=1
                data = line.get_data() 
                x = data[0]
                selection = (xview[0] < x) & (x < xview[1])
                if line.get_alpha() > 0.5:
                    try:
                        # handle case when some lines out of view
                        yy = min(data[1][selection])
                        ymin = min([yy,ymin])
                        yy = max(data[1][selection])
                        ymax = max([yy,ymax])
                    except:
                        pass
            try:
                self.ax.set_ylim([ymin,ymax])
            except:
                pass
        if self.data_list.__class__.__name__ == 'TfDataList':
            # reset coherence to 0-1
            self.ax2.set_ylim([0,1])
            
        self.fig.canvas.draw()
        
    def channel_select(self,event):
        selected_line = event.artist
        
        a = selected_line.get_alpha()
        # This function is called when legend dragged, and a is None
        # So only want to change line opacity when line actually selected.
        if a is not None:
            # change opacity of both legend line and actual line
            a = 1-a
            origline = self.lined[selected_line]
            

            selected_line.set_alpha(a)
            origline.set_alpha(a)
            
            # change z order to bring selected line to foreground
            for line in self.ax.lines:
                line.set_zorder(0)
            if a > 0.5:
                origline.set_zorder(1)
            else:
                origline.set_zorder(0)
                
            # also select matching coherence lines
            if len(self.ax2.lines) > 0:
                origline2 = self.lined2[selected_line]
                origline2.set_alpha(a)
                for line2 in self.ax2.lines:
                    line2.set_zorder(0)
                if a > 0.5:
                    origline2.set_zorder(1)
                else:
                    origline2.set_zorder(0)
            self.fig.canvas.draw()
    
    def get_selected_channels(self):
        # find the sets and channels higlighted in figure
        
        n_sets = len(self.line_listbyset)
        selected_data = []
        
        for ns in range(n_sets):
            selected_data += [[]]
            for line in self.line_listbyset[ns]:
                selected_data[ns] += [line.get_alpha() > 0.5] # skip coherence lines
            
        return selected_data
    
    def set_selected_channels(self,s):
        global LINE_ALPHA
        # relies on all sets of data with same number of channels. Need to make more general.
        for n_set in range(len(s)):
            for n_chan in range(len(s[n_set])):
                if s[n_set][n_chan] == True:
                    self.line_listbyset[n_set][n_chan].set_alpha(LINE_ALPHA)
                else:
                    self.line_listbyset[n_set][n_chan].set_alpha(1-LINE_ALPHA)
        # make legend line alphas match actual lines, but keep visibility as before
        self.update_legend()
        self.fig.canvas.draw()
        
    def update_sonogram(self,sono_data_list,n_set,n_chan,db_range=60,auto_xy='xy'):
        self.data_list = sono_data_list # makes auto_x/y work!
        
        for ch in self.ax.get_children():
                if ch.__class__.__name__ == 'QuadMesh':
                    ch.remove()
        
        self.n_set = n_set
        self.n_chan = n_chan
        self.ax2.set_visible(False)
        self.ax.set_xlabel('Time (s)')
        self.ax.set_ylabel('Frequency (Hz)')
        self.ax.grid(False)
        if self.ax.get_legend() is not None:
            self.ax.get_legend().set_visible(False)
        
        self.ax.lines.clear()
        self.ax2.lines.clear()
        self.line_listbyset = []
        self.line2_listbyset = []
        
        f = sono_data_list[n_set].freq_axis
        t = sono_data_list[n_set].time_axis
        S = sono_data_list[n_set].sono_data[:,:,n_chan]
        SdB = 20*np.log10(np.abs(S))
        vmax = SdB.max()
        vmin = np.max([SdB.min(),vmax-db_range])
        self.pcolor_sono = self.ax.pcolormesh(t,f,SdB,shading='gouraud',cmap='Blues',vmax=vmax,vmin=vmin,rasterized=True)
        if 'x' in auto_xy:
            self.auto_x()
        if 'y' in auto_xy:
            self.auto_y()

#        self.fig.colorbar(ax=self.ax)
        self.fig.canvas.draw()
        
        
    
    
    


