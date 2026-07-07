# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 17:08:42 2018

@author: tb267
"""

from . import analysis
from . import file
from . import modal

# `plotting` pulls qtpy + pyqtgraph + the matplotlib Qt5Agg backend
# (~0.7 s on a Mac). Only the four `DataSet.plot_*_data` methods need
# it; defer the import to each call site so analysis-only / CLI users
# don't pay the cost.

import numpy as np
import datetime
import uuid
import copy

#%% version
VERSION = '1.5.0' # keep in sync with pyproject.toml (enforced by tests/test_packaging.py)

def update_dataset(dataset):
    dataset_new = DataSet()
    dataset_new.add_to_dataset(dataset.time_data_list)
    dataset_new.add_to_dataset(dataset.freq_data_list)
    dataset_new.add_to_dataset(dataset.tf_data_list)
    dataset_new.add_to_dataset(dataset.cross_spec_data_list)
    dataset_new.add_to_dataset(dataset.sono_data_list)
    dataset_new.add_to_dataset(dataset.meta_data_list)
    if hasattr(dataset,'modal_data_list'):
        dataset_new.add_to_dataset(dataset.modal_data_list)
    else:
        dataset.modal_data_list = ModalDataList()
    for tf_data in dataset_new.tf_data_list:
        if not hasattr(tf_data,'flag_modal_TF'):
            tf_data.flag_modal_TF = False
    return dataset_new
    
#%% Data structure
class DataSet():
    def __init__(self,data=None):#,*,timedata=[],freqdata=[],cspecdata=[],tfdata=[],sonodata=[],metadata=[]):
        ## initialisation function to set up DataSet class
        
        self.time_data_list = TimeDataList()
        self.freq_data_list = FreqDataList()
        self.cross_spec_data_list = CrossSpecDataList()
        self.tf_data_list = TfDataList()
        self.modal_data_list = ModalDataList()
        self.sono_data_list = SonoDataList()
        self.meta_data_list = MetaDataList()
        
        if data is not None:
            self.add_to_dataset(data)
            
        self.pydvma_version = VERSION
            
        
    def add_to_dataset(self,data):
        ## find out what kind of data being added
        ## allow input to be list of single type of data, or unit data class
        if not 'list' in data.__class__.__name__.lower():
            # turn into list even if unit length
            data = [data]
        else:
            # check list contains set of same kind of data
            check = True
            for d in data:
                check = check and (d.__class__.__name__ == data[0].__class__.__name__)
            if check is False:
                raise ValueError('Data list needs to contain homogenous type of data')
        if len(data) != 0:
            data_class = data[0].__class__.__name__    
        else:
            data_class = None
            
        #print('')
        if data_class=='TimeData':
            self.time_data_list += data
            #print('{} added to dataset'.format(data))
        elif data_class=='FreqData':
            self.freq_data_list += data
            #print('{} added to dataset'.format(data))
        elif data_class=='CrossSpecData':
            self.cross_spec_data_list += data
            #print('{} added to dataset'.format(data))
        elif data_class=='TfData':
            self.tf_data_list += data
            #print('{} added to dataset'.format(data))
        elif data_class=='ModalData':
            self.modal_data_list += data
            #print('{} added to dataset'.format(data))
        elif data_class=='SonoData':
            self.sono_data_list += data
            #print('{} added to dataset'.format(data))
        elif data_class=='MetaData':
            self.meta_data_list += data
            #print('{} added to dataset'.format(data))
        else:
            pass#print('No data added')
        
    def replace_data_item(self,data,n_set):
        ## replace a specific data item
        ## useful for replacing logged data
        ## useful for replacing reconstructed modal data
        
        data_class = data.__class__.__name__    
            
        if data_class=='TimeData':
            self.time_data_list[n_set] = data
        elif data_class=='FreqData':
            self.freq_data_list[n_set] = data
        elif data_class=='CrossSpecData':
            self.cross_spec_data_list[n_set] = data
        elif data_class=='TfData':
            self.tf_data_list[n_set] = data
        elif data_class=='ModalData':
            self.modal_data_list[n_set] = data
        elif data_class=='SonoData':
            self.sono_data_list[n_set] = data
        elif data_class=='MetaData':
            self.meta_data_list[n_set] = data
        else:
            pass
        
            
    def remove_last_data_item(self,data_class):
        
        if data_class == 'TimeData':
            if len(self.time_data_list) != 0:
                del self.time_data_list[-1]
        if data_class == 'FreqData':
            if len(self.freq_data_list) != 0:
                del self.freq_data_list[-1]
        if data_class == 'CrossSpecData':
            if len(self.cross_spec_data_list) != 0:
                del self.cross_spec_data_list[-1]
        if data_class == 'TfData':
            if len(self.tf_data_list) != 0:
                del self.tf_data_list[-1]
        if data_class == 'ModalData':
            if len(self.modal_data_list) != 0:
                del self.modal_data_list[-1]
        if data_class == 'SonoData':
            if len(self.sono_data_list) != 0:
                del self.sono_data_list[-1]
        if data_class == 'MetaData':
            if len(self.meta_data_list) != 0:
                del self.meta_data_list[-1]
                
        #print(self)
                
    def remove_data_item_by_index(self,data_class,list_index):
        
        if list_index.__class__.__name__ == 'ndarray':
            list_index = list(list_index)
        elif type(list_index) is int:
            list_index = [list_index]
            
        list_index.sort()

        if data_class == 'TimeData':
            if len(self.time_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.time_data_list[i]
            else:
                print('indices out of range, no data removed')
                
        if data_class == 'FreqData':
            if len(self.freq_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.freq_data_list[i]
            else:
                print('indices out of range, no data removed')
        
        if data_class == 'CrossSpecData':
            if len(self.cross_spec_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.cross_spec_data_list[i]
            else:
                print('indices out of range, no data removed')
                
        if data_class == 'TfData':
            if len(self.tf_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.tf_data_list[i]
            else:
                print('indices out of range, no data removed')
                
        if data_class == 'ModalData':
            if len(self.modal_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.modal_data_list[i]
            else:
                print('indices out of range, no data removed')
                    
        if data_class == 'SonoData':
            if len(self.sono_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.sono_data_list[i]
            else:
                print('indices out of range, no data removed')
                
        if data_class == 'MetaData':
            if len(self.meta_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.meta_data_list[i] 
            else:
                print('indices out of range, no data removed')

        #print(self)
        
    def calculate_fft_set(self,time_range=None,window=None):
        '''
        Calls analysis.calculate_fft on each TimeData item in the TimeDataList and adds FreqDataList object to dataset
        '''
        if len(self.time_data_list)>0:
            freq_data_list = self.time_data_list.calculate_fft_set(time_range=time_range,window=window)
            self.freq_data_list = freq_data_list
            #self.add_to_dataset(freq_data_list)
        else:
            self.freq_data_list = FreqDataList()
            print('No time data found in dataset')
            
    def calculate_tf_set(self, ch_in=0, time_range=None,window=None,N_frames=1,overlap=0.5):
        '''
        Calls analysis.calculate_tf on each TimeData item in the TimeDataList and adds TfDataList object to dataset
        '''
        if len(self.time_data_list)>0:
            tf_data_list = self.time_data_list.calculate_tf_set(ch_in=ch_in, time_range=time_range, window=window, N_frames=N_frames, overlap=overlap)
            self.tf_data_list = tf_data_list
            #self.add_to_dataset(tf_data_list)
        else:
            self.tf_data_list = TfDataList()
            print('No time data found in dataset')
            
    def calculate_cross_spectrum_matrix_set(self,ch_in=0, time_range=None,window='hann',N_frames=1,overlap=0.5):
        '''
        Calls analysis.calculate_cross_spectrum_matrix on each TimeData item in the TimeDataList and adds CrossSpecDataList object to dataset
        '''
        if len(self.time_data_list)>0:
            cross_spec_data_list = self.time_data_list.calculate_cross_spectrum_matrix_set(ch_in=ch_in, time_range=time_range,window=window,N_frames=N_frames,overlap=overlap)
            self.cross_spec_data_list = cross_spec_data_list
            #self.add_to_dataset(cross_spec_data_list)
        else:
            self.cross_spec_data_list = CrossSpecDataList()
            print('No time data found in dataset')
            
    def calculate_tf_averaged(self, ch_in=0, time_range=None,window='hann'):
        '''
        Calls analysis.calculate_tf_averaged on the whole TimeDataList (ensemble average) and adds a single-item TfDataList to dataset
        '''
        if len(self.time_data_list)>0:
            tf_data = self.time_data_list.calculate_tf_averaged(ch_in=ch_in, time_range=time_range ,window=window)
            self.tf_data_list = TfDataList([tf_data])
            #self.add_to_dataset(tf_data)
        else:
            self.tf_data_list = TfDataList()
            print('No time data found in dataset')
            
    def calculate_cross_spectra_averaged(self, time_range=None,window=None):
        '''
        Calls analysis.calculate_cross_spectra_averaged on the whole TimeDataList (ensemble average) and adds a single-item CrossSpecDataList to dataset
        '''
        if len(self.time_data_list)>0:
            cross_spec_data = self.time_data_list.calculate_cross_spectra_averaged(time_range=time_range,window=window)
            self.cross_spec_data_list = CrossSpecDataList([cross_spec_data])
            #self.add_to_dataset(cross_spec_data)
        else:
            self.cross_spec_data_list = CrossSpecDataList()
            print('No time data found in dataset')
            
    def calculate_sono_set(self, nperseg=None):
        if len(self.time_data_list)>0:
            sono_data_list = self.time_data_list.calculate_sono_set(nperseg=nperseg)
            self.sono_data_list = sono_data_list
        else:
            self.sono_data_list = SonoDataList()
            print('No time data found in dataset')
            
    def clean_impulse(self,ch_impulse=0):
        '''
        Calls analysis.clean_impulse on each TimeData item in the TimeDataList and returns a copy of the new dataset.
        
        Note that calling this function *does not* change the data, and just returns a copy.
        '''
        dataset_copy = copy.deepcopy(self)
        dataset_copy.remove_data_item_by_index('TimeData',np.arange(len(dataset_copy.time_data_list)))
        if len(self.time_data_list)>0:
            for time_data in self.time_data_list:
                td = analysis.clean_impulse(time_data, ch_impulse=ch_impulse)
                dataset_copy.add_to_dataset(td)
            print('returning copy of data with impulses cleaned')
            return dataset_copy
        else:
            print('No time data found in dataset')
            return None
            
    def save_data(self, filename=None):
        '''
        Saves the whole DataSet via `file.save_data` — writes the
        .dvma container format by default (legacy pickle format if
        `filename` explicitly ends in ``.npy``). Shows a save dialog
        if no filename is given.
        '''
        savename = file.save_data(self, filename=filename, overwrite_without_prompt=False)
        return savename
    
    def export_to_matlab(self, filename=None, overwrite_without_prompt=False):
        savename = file.export_to_matlab(self, filename=filename, overwrite_without_prompt=overwrite_without_prompt)
        return savename
    
    def export_to_matlab_jwlogger(self, filename=None, overwrite_without_prompt=False):
        savename = file.export_to_matlab_jwlogger(self, filename=filename, overwrite_without_prompt=overwrite_without_prompt)
        return savename
    
    def plot_time_data(self,sets='all',channels='all'):
        from . import plotting
        global pt
        pt = plotting.PlotData(window_title='Time Data')
        pt.update(self.time_data_list,sets=sets,channels=channels)
        return pt

    def plot_freq_data(self,sets='all',channels='all'):
        from . import plotting
        global pf
        pf = plotting.PlotData(window_title='Frequency Data')
        pf.update(self.freq_data_list,sets=sets,channels=channels)
        return pf

    def plot_tf_data(self,sets='all',channels='all'):
        from . import plotting
        global ptf
        ptf = plotting.PlotData(window_title='Transfer Function Data')
        ptf.update(self.tf_data_list,sets=sets,channels=channels)
        return ptf

    def plot_sono_data(self,n_set=0, n_chan=0, db_range=60):
        from . import plotting
        global ptf
        ptf = plotting.PlotData(window_title='Sonogram Data')
        ptf.update_sonogram(self.sono_data_list,n_set=n_set,n_chan=n_chan, db_range=db_range)
        return ptf
    
    def __repr__(self):
        template = "{:>24}: {}"
        dataset_dict = self.__dict__
        text = '\n<DataSet> class:\n\n'
        for attr in dataset_dict:
            N = len(dataset_dict[attr])
            if N <= 3:
                text += template.format(attr,dataset_dict[attr])
                text += '\n'
            elif attr == 'pydvma_version':
                pass#text += template.format('pydvma_version',str(self.pydvma_version))
            else:
                text += template.format(attr,'[' + str(dataset_dict[attr][0]) + ',... (x' + str(N) + ')]')
                text += '\n'
        
        return text
    
class TimeDataList(list):
    ### This will allow functions to be discovered that can take lists of TimeData is arguments
    def calculate_fft_set(self,time_range=None,window=None):
        '''
        Calls analysis.calculate_fft on each item in the list and returns FreqDataList object
        '''
        freq_data_list = FreqDataList()
        
        for td in self:
            freq_data = analysis.calculate_fft(td, time_range=time_range, window=window)
            freq_data_list += [freq_data]
            
        return freq_data_list
    
    
    def calculate_tf_set(self, ch_in=0, time_range=None,window=None,N_frames=1,overlap=0.5):
        '''
        Calls analysis.calculate_tf on each item in the list and returns TfDataList object
        '''
        tf_data_list = TfDataList()
        
        for td in self:
            tf_data = analysis.calculate_tf(td, ch_in=ch_in, time_range=time_range,window=window,N_frames=N_frames,overlap=overlap)
            tf_data_list += [tf_data]
            
        return tf_data_list
    
    def calculate_cross_spectrum_matrix_set(self, ch_in=0, time_range=None,window=None,N_frames=1,overlap=0.5):
        '''
        Calls analysis.calculate_tf on each item in the list and returns TfDataList object
        '''
        cross_spec_data_list = CrossSpecDataList()
        
        for td in self:
            cross_spec_data = analysis.calculate_cross_spectrum_matrix(td, time_range=time_range,window=window,N_frames=N_frames,overlap=overlap)
            cross_spec_data_list += [cross_spec_data]
            
        return cross_spec_data_list
    
    
    def calculate_tf_averaged(self, ch_in=0, time_range=None,window='hann'):
        '''
        Calls analysis.calculate_tf_averaged on whole list and returns TfData object
        '''
        tf_data = analysis.calculate_tf_averaged(self,ch_in=ch_in, time_range=time_range,window=window)
            
        return tf_data
    
    
    def calculate_cross_spectra_averaged(self, time_range=None,window=None):
        '''
        Calls analysis.calculate_cross_spectra_averaged on whole list and returns CrossSpecData object
        '''
        cross_spec_data = analysis.calculate_cross_spectra_averaged(self, time_range=time_range,window=window)
            
        return cross_spec_data
    
    def calculate_sono_set(self, nperseg=None):
        '''
        Calls analysis.calculate_sonogram on each item in the list and returns SonoDataList object
        '''
        sono_data_list = SonoDataList()
        
        for td in self:
            sono_data = analysis.calculate_sonogram(td,nperseg=nperseg)
            sono_data_list += [sono_data]
            
        return sono_data_list
    
    def get_calibration_factors(self):
        n_set = len(self)
        factors = []
        for ns in range(n_set):
            factors.append(self[ns].channel_cal_factors)
        
        return factors
            
    def set_calibration_factors_all(self,factors):
        n_set = len(self)
        for ns in range(n_set):
            self[ns].channel_cal_factors=factors[ns]
            
    def set_calibration_factor(self,factor, n_set=0, n_chan=0):
        if len(self) == 0:
            print('<TimeDataList> is empty. First log data, load data, or create test data.')
        elif n_set >= len(self):
            print('<TimeDataList> has {} set(s) of <TimeData>. Set requested (index={}) exceeds number of sets. Note indexing starts at 0.'.format(len(self),n_set))
        elif n_chan >= len(self[n_set].time_data[0,:]):
            print('<TimeDataList>[{}] has {} channel(s). Channel requested (index={}) exceeds number of channels. Note indexing starts at 0.'.format(n_set,len(self[n_set].time_data[0,:]),n_chan))
        else:
            self[n_set].channel_cal_factors[n_chan]=factor
    
    def export_to_csv(self, filename=None, overwrite_without_prompt=False):
        savename = file.export_to_csv(self,filename=filename,overwrite_without_prompt=overwrite_without_prompt)
        return savename

class FreqDataList(list):
    ### This will allow functions to be discovered that can take lists of FreqData is arguments
    def get_calibration_factors(self):
        n_set = len(self)
        factors = []
        for ns in range(n_set):
            factors.append(self[ns].channel_cal_factors)
        
        return factors
    
    def set_calibration_factors_all(self,factors):
        n_set = len(self)
        for ns in range(n_set):
            self[ns].channel_cal_factors=factors[ns]
            
    def set_calibration_factor(self,factor, n_set=0, n_chan=0):
        if len(self) == 0:
            print('<FreqDataList> is empty. First calculate FFT.')
        elif n_set >= len(self):
            print('<FreqDataList> has {} set(s) of <FreqData>. Set requested (index={}) exceeds number of sets. Note indexing starts at 0.'.format(len(self),n_set))
        elif n_chan >= len(self[n_set].freq_data[0,:]):
            print('<FreqDataList>[{}] has {} channel(s). Channel requested (index={}) exceeds number of channels. Note indexing starts at 0.'.format(n_set,len(self[n_set].freq_data[0,:]),n_chan))
        else:
            self[n_set].channel_cal_factors[n_chan]=factor
            
    def export_to_csv(self, filename=None, overwrite_without_prompt=False):
        savename = file.export_to_csv(self,filename=filename,overwrite_without_prompt=overwrite_without_prompt)
        return savename

class CrossSpecDataList(list):
    ### This will allow functions to be discovered that can take lists of CrossSpecData is arguments
    pass

class TfDataList(list):
    ### This will allow functions to be discovered that can take lists of TfData is arguments
    def get_calibration_factors(self):
        n_set = len(self)
        factors = []
        for ns in range(n_set):
            factors.append(self[ns].channel_cal_factors)
        
        return factors
    
    def set_calibration_factors_all(self,factors):
        n_set = len(self)
        for ns in range(n_set):
            self[ns].channel_cal_factors=factors[ns]
            
    def set_calibration_factor(self,factor, n_set=0, n_chan=0):
        if len(self) == 0:
            print('<TfDataList> is empty. First calculate transfer function.')
        elif n_set >= len(self):
            print('<TfDataList> has {} set(s) of <TfData>. Set requested (index={}) exceeds number of sets. Note indexing starts at 0.'.format(len(self),n_set))
        elif n_chan >= len(self[n_set].tf_data[0,:]):
            print('<TfDataList>[{}] has {} channel(s). Channel requested (index={}) exceeds number of channels. Note indexing starts at 0.'.format(n_set,len(self[n_set].tf_data[0,:]),n_chan))
        else:
            self[n_set].channel_cal_factors[n_chan]=factor
    
    def add_modal_reconstruction(self,tf_data,mode='replace'):
        # identify number of TFs in list that are reconstructions
        N_reconstruction = 0
        for tf in self:
            if tf.flag_modal_TF == True:
                N_reconstruction += 1
                
        # append / replace reconstruction TFs
        if N_reconstruction == 0:
            self += [tf_data]
        elif mode == 'replace':
            self[-1] = tf_data
        elif mode == 'append':
            self += [tf_data]
            
        
    def export_to_csv(self, filename=None, overwrite_without_prompt=False):
        savename = file.export_to_csv(self,filename=filename,overwrite_without_prompt=overwrite_without_prompt)
        return savename
      
class ModalDataList(list):
    ### This will allow functions to be discovered that can take lists of ModalData is arguments
    pass

class SonoDataList(list):
    ### This will allow functions to be discovered that can take lists of SonoData is arguments
    pass

class MetaDataList(list):
    ### This will allow functions to be discovered that can take lists of MetaData is arguments
    pass

        
class TimeData():
    '''One block of acquired time-series data plus its acquisition metadata.

    Held inside a `DataSet.time_data_list`. Produced by `log_data`,
    by the test-data factories in `testdata`, and on import from
    Matlab. The numeric content is **in volts** (see "Voltage-Based
    I/O" in the user-guide acquisition page); apply
    `channel_cal_factors` to convert to engineering units at display
    or fit time. `analysis.calculate_*` functions copy `units` and
    `channel_cal_factors` onto their derived FreqData / TfData /
    CrossSpecData / SonoData outputs.

    Attributes:
        time_axis (np.ndarray): 1D sample times in seconds.
        time_data (np.ndarray): Shape ``(n_samples, n_channels)`` voltage samples.
        settings (MySettings): Snapshot of the acquisition configuration.
        timestamp (datetime.datetime): Capture start time.
        timestring (str): Filesystem-safe rendering of `timestamp`.
        units (list[str] or None): Engineering units per channel
            (e.g. ``['N', 'm/s', 'g']``). None if unset.
        channel_cal_factors (np.ndarray): Per-channel multipliers from
            volts to engineering units. Defaults to all-ones.
        id_link: Reference to a source TimeData (used when this object
            is derived rather than freshly acquired).
        test_name (str or None): Free-form label, displayed in plots.
        unique_id (uuid.UUID): Generated at construction; used by derived
            objects to link back to their source via `id_link`.
    '''

    def __init__(self,time_axis,time_data,settings,timestamp=None,timestring=None,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        
        time_data = reshape_arrays(time_data)
        if channel_cal_factors is None:
            channel_cal_factors = np.ones(len(time_data[0,:]))
        
        if timestamp is None:
            t = datetime.datetime.now()
            timestamp = t
            timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
        
        self.time_axis = time_axis
        self.time_data = time_data  
        self.settings = settings
        self.timestamp = timestamp
        self.timestring = timestring
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # this is used if data is derived from an existing <TimeData> measurement
        self.test_name = test_name
        self.unique_id = uuid.uuid4()
        
        
        
    def __repr__(self):
        return "<TimeData>"

        
class FreqData():
    '''One-sided complex frequency spectrum of a `TimeData` capture.

    Produced by `analysis.calculate_fft`. The spectrum is the raw
    `np.fft.rfft` of the (optionally windowed) time data — i.e. it is
    **not** scaled to a PSD or amplitude spectrum; consumers that need
    PSD should square the magnitude themselves. `units` and
    `channel_cal_factors` are copied verbatim from the source TimeData.

    Attributes:
        freq_axis (np.ndarray): Frequency bins in Hz (length ``N//2+1``).
        freq_data (np.ndarray): Shape ``(n_freq, n_channels)`` complex
            spectrum, one column per channel.
        settings (MySettings): Snapshot of the analysis configuration
            (includes the window choice and the time range that was used).
        units (list[str] or None): Engineering units per channel.
        channel_cal_factors (np.ndarray): Per-channel multipliers from
            volts to engineering units; applied at display time.
        id_link (uuid.UUID): `unique_id` of the source TimeData.
        test_name (str or None): Free-form label.
        timestamp (datetime.datetime): When this FreqData was constructed.
        timestring (str): Filesystem-safe rendering of `timestamp`.
    '''

    def __init__(self,freq_axis,freq_data,settings,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        
        freq_data = reshape_arrays(freq_data)
        if channel_cal_factors is None:
            channel_cal_factors = np.ones(len(freq_data[0,:]))
        
        self.freq_axis = freq_axis
        self.freq_data = freq_data
        self.settings = settings
        self.test_name = test_name
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # used to link data to specific <TimeData> object
        t = datetime.datetime.now()
        self.timestamp = t
        self.timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
        
    def __repr__(self):
        return "<FreqData>"
    
    
class CrossSpecData():
    '''Full cross-spectrum matrix Pxy[i,j,f] and coherence matrix Cxy[i,j,f].

    Produced by `analysis.calculate_cross_spectrum_matrix` (single
    TimeData) or `analysis.calculate_cross_spectra_averaged` (ensemble
    TimeDataList). The diagonal `Pxy[i, i, :]` is the per-channel
    auto-spectrum (= scipy.signal.welch with ``scaling='spectrum'``);
    off-diagonal `Pxy[i, j, :]` matches scipy.signal.csd with the same
    settings. Pxy is Hermitian — `Pxy[j, i, :] = conj(Pxy[i, j, :])`.

    Attributes:
        freq_axis (np.ndarray): One-sided frequency bins in Hz.
        Pxy (np.ndarray): Shape ``(n_channels, n_channels, n_freq)``,
            complex. Cross-spectrum matrix.
        Cxy (np.ndarray): Same shape, real, in [0, 1]. Coherence matrix.
        settings (MySettings): Includes `window`, `time_range`,
            `N_frames`, `overlap` actually used.
        units (list[str] or None): Engineering units per channel.
        channel_cal_factors (np.ndarray): Per-channel multipliers from
            volts to engineering units.
        id_link: `unique_id` of the source TimeData (or list of
            ids when averaged across a TimeDataList).
        test_name (str or None): Free-form label.
        timestamp (datetime.datetime): When constructed.
        timestring (str): Filesystem-safe rendering of `timestamp`.
    '''

    def __init__(self,freq_axis,Pxy,Cxy,settings,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        
        self.freq_axis = freq_axis
        self.Pxy = Pxy
        self.Cxy = Cxy
        self.settings = settings
        self.test_name = test_name
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # used to link data to specific <TimeData> object
        t = datetime.datetime.now()
        self.timestamp = t
        self.timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
        
    def __repr__(self):
        return "<CrossSpecData>"
    
        
class TfData():
    '''Transfer function H(f) from one input channel to one or more outputs.

    Produced by `analysis.calculate_tf` (single TimeData) or
    `analysis.calculate_tf_averaged` (ensemble TimeDataList). The
    convention is `Pxy[in, out] / Pxy[in, in]` per output channel;
    `tf_coherence` carries the corresponding coherence.

    Calibration: `channel_cal_factors[k]` holds the **ratio**
    ``cal[out_k] / cal[in]`` — i.e. multiplying `tf_data[:, k] *
    channel_cal_factors[k]` at display time gives the TF in
    engineering units. Units are constructed as
    ``"<out_unit>/<in_unit>"`` per output channel.

    Attributes:
        freq_axis (np.ndarray): One-sided frequency bins in Hz.
        tf_data (np.ndarray): Shape ``(n_freq, n_outputs)``, complex.
            One column per non-input channel.
        tf_coherence (np.ndarray): Same shape, real, in [0, 1].
        settings (MySettings): Snapshot including the chosen `ch_in`
            and the derived `ch_out_set` (the channel indices in
            `tf_data`'s second axis).
        units (list[str] or None): Per-output-channel unit strings
            (e.g. ``['m/s/N', 'g/N']``).
        channel_cal_factors (np.ndarray): Per-output cal *ratios*
            (cal[out] / cal[in]). A manual override here overwrites
            the inherited ratio.
        id_link: `unique_id` of the source TimeData (or list when averaged).
        test_name (str or None): Free-form label.
        timestamp (datetime.datetime): When constructed.
        timestring (str): Filesystem-safe rendering of `timestamp`.
        flag_modal_TF (bool): True after a modal fit has consumed
            this TfData (avoids double-fitting); used by `modal.py`.
    '''

    def __init__(self,freq_axis,tf_data,tf_coherence,settings,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        
        tf_data = reshape_arrays(tf_data)
        if channel_cal_factors is None:
            channel_cal_factors = np.ones(len(tf_data[0,:]))
        
        self.freq_axis = freq_axis
        self.tf_data = tf_data
        self.tf_coherence = tf_coherence
        self.settings = settings
        self.test_name = test_name
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # used to link data to specific <TimeData> object
        t = datetime.datetime.now()
        self.timestamp = t
        self.timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
        self.flag_modal_TF = False
        
    def __repr__(self):
        return "<TfData>"
    
    
class ModalData():
    '''A set of fitted modes — each row of `M` is one mode's
    `(fn, zn, an[chan...], pn[chan...], rk[chan...], rm[chan...])`
    parameter vector as produced by
    `modal.modal_fit_all_channels`.

    Use `add_mode` to append further modes (e.g. across separate
    frequency-band fits); rows are kept sorted by `fn`. After any
    add/delete, the summary arrays `fn`, `zn`, `an`, `pn` are
    refreshed and indexable per mode.

    Attributes:
        M (np.ndarray): Shape ``(n_modes, 2 + 4*n_channels)``. Each row
            packs ``[fn, zn, an_0..an_C, pn_0..pn_C, rk_0..rk_C,
            rm_0..rm_C]``.
        fn (np.ndarray): Per-mode natural frequencies in Hz.
        zn (np.ndarray): Per-mode damping ratios.
        an (np.ndarray): Shape ``(n_modes, n_channels)`` modal-constant
            amplitudes.
        pn (np.ndarray): Same shape; modal-constant phases in radians.
        channels (int): Number of channels (= `n_channels` above).
        settings (MySettings): Snapshot including the source TF's settings.
        units: Engineering units (passed through from source).
        id_link: `unique_id`(s) of the TFs that produced these modes.
        test_name (str or None): Free-form label.
    '''

    def __init__(self,xn=None,settings=None,units=None,id_link=None,test_name=None):
        
        self.M = []
        self.test_name = test_name
        # Own copy: add_mode/delete_mode rewrite settings.channels, and
        # the caller's settings (typically the source TfData's) must not
        # be mutated through the shared reference.
        self.settings = copy.copy(settings) if settings is not None else None
        self.channels = 0
        if settings is not None:
            self.settings.channels = 0
        self.units = units
        self.id_link = id_link # used to link data to specific <TimeData> object
        t = datetime.datetime.now()
        self.timestamp = t
        self.timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)

        if xn is not None:
            self.add_mode(xn)


    def add_mode(self,xn):
        '''
        Appends one mode (a packed parameter row as per 'x' in modal.py:
        [fn, zn, an x N, pn x N, rk x N, rm x N]) to the modal matrix,
        keeping rows sorted by natural frequency and refreshing the
        unpacked summary properties (fn, zn, an, pn).
        '''
        # Make modal matrix. Each row is modal vector stacked as per 'x' in modal.py
        if len(self.M) == 0:
            self.M = np.atleast_2d(xn)
        elif len(xn) == len(self.M[0,:]):
            self.M = np.vstack((self.M,xn))
        else:
            print('Incompatible mode: different number of channels to existing set.')
            return

        # sort by frequency (first column)
        sort_i = np.argsort(self.M[:,0])
        self.M = self.M[sort_i,:]
        # row layout is [fn, zn, an*N, pn*N, rk*N, rm*N] so the channel
        # count comes from the column count, not the number of rows (modes)
        self.channels = int((self.M.shape[1] - 2) / 4)
        if self.settings is not None:
            self.settings.channels = self.channels

        # separate properties for easier summary, and don't need summary of local residuals rk and rm
        fn,zn,an,pn,rk,rm = modal.unpack_matrix(self.M)
        self.fn = fn
        self.zn = zn
        self.an = an
        self.pn = pn

    def delete_mode(self,mode_number):
        '''
        Deletes one or more modes (rows) from the modal matrix by index and
        refreshes the unpacked summary properties (fn, zn, an, pn).

        Deleting the LAST remaining mode is valid: the matrix becomes an
        empty ``(0, 2+4*channels)`` and the summaries become zero-length
        (fn/zn) / ``(0, channels)`` (an/pn). This no longer raises the
        IndexError that ``modal.unpack_matrix`` used to throw on an emptied
        matrix (the round-4 "Fit -> Reject" crash, and the same latent crash
        on Qt's Reject). ``channels`` is preserved — it is encoded in the
        column count, not the number of mode rows.
        '''
        self.M = np.delete(self.M,mode_number,0)
        self.channels = int((self.M.shape[1] - 2) / 4)
        if self.settings is not None:
            self.settings.channels = self.channels

        # separate properties for easier summary, and don't need summary of local residuals rk and rm
        fn,zn,an,pn,rk,rm = modal.unpack_matrix(self.M)
        self.fn = fn
        self.zn = zn
        self.an = an
        self.pn = pn
        
            
    def __repr__(self):
        return "<ModalData>"
        
#    def __repr__(self):
#        with np.printoptions(precision=3, suppress=True):
#            template = "{}: {}"
#            modal_dict = self.__dict__
#            text = '\n<ModalData> class:\n\n'
#            for attr in modal_dict:
#                print(attr)
#                if (attr != 'xn') & (attr != 'rk') & (attr != 'rm') & (attr != 'units') & (attr != 'test_name')& (attr != 'id_link')& (attr != 'timestamp')& (attr != 'timestring'):
#                    text += template.format(attr,modal_dict[attr])
#                    text += '\n'
#            
#            return text
    
        
class SonoData():
    '''Short-time-FFT spectrogram (sonogram) of a multi-channel `TimeData`.

    Produced by `analysis.calculate_sonogram`. Each frame is a windowed
    FFT of a `nperseg`-sample segment of the source data; segments are
    overlapped by `noverlap` and the resulting matrix lets you see how
    spectral content evolves over time. Used by
    `analysis.calculate_damping_from_sono` to extract per-mode damping
    from free-decay measurements.

    Attributes:
        time_axis (np.ndarray): Frame midpoints in seconds.
        freq_axis (np.ndarray): One-sided frequency bins in Hz.
        sono_data (np.ndarray): Shape ``(n_freq, n_frames, n_channels)``,
            complex. Magnitude-squared gives a per-bin power spectrogram.
        settings (MySettings): Snapshot including `pretrig_samples`
            (used by `calculate_damping_from_sono` to pick the
            free-decay start time).
        units (list[str] or None): Engineering units per channel.
        channel_cal_factors (np.ndarray): Per-channel multipliers from
            volts to engineering units.
        id_link: `unique_id` of the source TimeData.
        test_name (str or None): Free-form label.
        timestamp (datetime.datetime): When constructed.
        timestring (str): Filesystem-safe rendering of `timestamp`.
    '''

    def __init__(self,time_axis,freq_axis,sono_data,settings,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        self.time_axis = time_axis
        self.freq_axis = freq_axis
        self.sono_data = sono_data
        self.settings = settings
        self.test_name = test_name
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # used to link data to specific <TimeData> object
        t = datetime.datetime.now()
        self.timestamp = t
        self.timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
        
    def __repr__(self):
        return "<SonoData>"
        
class MetaData():
    def __init__(self, units=None, channel_cal_factors=None, tf_cal_factors = None,test_name=None):
        ### not sure this is a helpful datafield: might delete. Metadata then contained within each data unit.
        self.units = units
        self.channel_cal_factors = None
        self.tf_cal_factors = None
        t = datetime.datetime.now()
        self.timestamp = t
        self.timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
        
    def __repr__(self):
        return "<MetaData>"
    
    
def reshape_arrays(a):
    b = np.shape(a)
    if len(b) == 1:
        a = a[:,None]
        
    return a