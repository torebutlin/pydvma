# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 17:08:42 2018

@author: tb267
"""

from . import analysis
from . import file
from . import plotting
from . import modal

import numpy as np
import datetime
import uuid
import copy

#%% version
VERSION = '0.5.2' # keep in sync with setup.py

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
        
        if not data == None:
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
                    del self.tf_data_list[i]
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
        Calls analysis.calculate_fft on each TimeData item in the TimeDataList and adds FreqDataList object to dataset
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
        Calls analysis.calculate_fft on each TimeData item in the TimeDataList and adds FreqDataList object to dataset
        '''
        if len(self.time_data_list)>0:
            cross_spec_data_list = self.time_data_list.calculate_cross_spectrum_matrix_set(ch_in=ch_in, time_range=time_range,window='hann',N_frames=N_frames,overlap=overlap)
            self.cross_spec_data_list = cross_spec_data_list
            #self.add_to_dataset(cross_spec_data_list)
        else:
            self.cross_spec_data_list = CrossSpecDataList()
            print('No time data found in dataset')
            
    def calculate_tf_averaged(self, ch_in=0, time_range=None,window='hann'):
        '''
        Calls analysis.calculate_fft on each TimeData item in the TimeDataList and adds FreqDataList object to dataset
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
        Calls analysis.calculate_fft on each TimeData item in the TimeDataList and adds FreqDataList object to dataset
        '''
        if len(self.time_data_list)>0:
            cross_spec_data = self.time_data_list.calculate_cross_spectra_averaged(time_range=time_range,window=window)
            self.cross_spec_data_list = CrossSpecDataList([cross_spec_data])
            #self.add_to_dataset(cross_spec_data)
        else:
            self.cross_spec_data_list = CrossSpecDataList()
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
        savename = file.save_data(self, filename=filename, overwrite_without_prompt=False)
        return savename
    
    def export_to_matlab(self, filename=None, overwrite_without_prompt=False):
        savename = file.export_to_matlab(self, filename=filename, overwrite_without_prompt=overwrite_without_prompt)
        return savename
    
    def export_to_matlab_jwlogger(self, filename=None, overwrite_without_prompt=False):
        savename = file.export_to_matlab_jwlogger(self, filename=filename, overwrite_without_prompt=overwrite_without_prompt)
        return savename
    
    def plot_time_data(self,sets='all',channels='all'):
        global pt
        pt = plotting.PlotData()
        pt.update(self.time_data_list,sets=sets,channels=channels)
        return pt
        
    def plot_freq_data(self,sets='all',channels='all'):
        global pf
        pf = plotting.PlotData()
        pf.update(self.freq_data_list,sets=sets,channels=channels)
        return pf
        
    def plot_tf_data(self,sets='all',channels='all'):
        global ptf
        ptf = plotting.PlotData()
        ptf.update(self.tf_data_list,sets=sets,channels=channels)
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
    def calculate_fft_set(self,time_range=None,window=False):
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
        Calls analysis.calculate_tf_averaged on whole list and returns TfData object
        '''
        cross_spec_data = analysis.calculate_cross_spectra_averaged(self, time_range=time_range,window=window)
            
        return cross_spec_data
    
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
        elif n_chan >= len(self[n_set].tf_data[0,:]):
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
        elif n_chan >= len(self[n_set].tf_data[0,:]):
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
    def __init__(self,time_axis,time_data,settings,timestamp,timestring,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        
        time_data = reshape_arrays(time_data)
        if channel_cal_factors is None:
            channel_cal_factors = np.ones(len(time_data[0,:]))
        
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
    def __init__(self,xn=None,settings=None,units=None,id_link=None,test_name=None):
        
        self.M = None
        self.test_name = test_name
        self.settings = settings
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
        # Make modal matrix. Each row is modal vector stacked as per 'x' in modal.py
        if self.M is None:
            self.M = np.atleast_2d(xn)
        elif len(xn) == len(self.M[0,:]):
            self.M = np.vstack((self.M,xn))
        else:
            print('Incompatible mode: different number of channels to existing set.')
            return
        
        # sort by frequency (first column)
        sort_i = np.argsort(self.M[:,0])
        self.M = self.M[sort_i,:]
        self.channels = len(sort_i)
        self.settings.channels = self.channels
        
        # separate properties for easier summary, and don't need summary of local residuals rk and rm
        self.fn = self.M[:,0]
        self.zn = self.M[:,1]
        self.an = self.M[:,2]
        self.pn = self.M[:,3]
        
    def delete_mode(self,mode_number):
        self.M = np.delete(self.M,mode_number,0)
        self.channels = len(self.M[:,0])
        self.settings.channels = self.channels
        
        # separate properties for easier summary, and don't need summary of local residuals rk and rm
        self.fn = self.M[:,0]
        self.zn = self.M[:,1]
        self.an = self.M[:,2]
        self.pn = self.M[:,3]
            
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
    def __init__(self,time_axis,freq_axis,sono_data,settings,timestamp,timestring,units=None,channel_cal_factors=None,id_link=None,test_name=None):
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