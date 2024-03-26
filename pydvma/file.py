# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 14:32:35 2018

@author: tb267
"""

import os.path
import numpy as np
import scipy.io as io
import pyqtgraph as pg
from qtpy import QtWidgets
from qtpy.QtWidgets import QFileDialog
from . import datastructure
from . import options


def load_data(parent=None, filename=None):
    '''
    Loads dataset from filename, or displays a dialog if no argument provided.
    '''
    if filename is None:
        # wid = QtWidgets.QWidget()
        filename, _ = QFileDialog.getOpenFileName(parent, 'Open data file', '', '*.npy *.mat')
        
        # file_dialog = QFileDialog(parent, 'Open data file', '', '*.npy')
        # file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        # file_dialog.exec()
        # filename = file_dialog.selectedFiles()

        if not filename:
            return None

    # determine if file is .npy or .mat
    if filename.endswith('.npy'):
        dataset = d = np.load(filename,allow_pickle=True,fix_imports=True)
        dataset = d[0]
    elif filename.endswith('.mat'):
        dataset = import_from_matlab_jwlogger(filename=filename)
    else:
        print('Expecting file to be .npy or .mat')
        return None
    
    
    return dataset


def save_data(dataset, parent=None, filename=None, overwrite_without_prompt=False):
    '''
    Saves dataset class to file 'filename.npy', or provides dialog if no
    filename provided.

    Args:
       dataset: An object of the class dataSet
       filename: string [optional]
       overwrite_without_prompt: bool

    '''

    # put data into numpy array
    d = np.array([dataset])

    # If filename not specified, provide dialog
    if filename is None:
        filename, _ = QFileDialog.getSaveFileName(parent, 'Save dataset', '', '*.npy')
        if not filename:
            # No filename chosen, give up on saving
            print('Save cancelled')
            return None


    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    elif os.path.isfile(filename) and not overwrite_without_prompt:
        answer = input('File %r already exists. Overwrite? [y/n]: ' % filename)
        if answer != 'y':
            print('Save cancelled')
            return None
        print('Will overwrite existing file')
        
    # Make sure it ends with .npy
    if not filename.endswith('.npy'):
        filename += '.npy'
        
    # Actually save!
    np.save(filename, d)
    print("Data saved as %s" % filename)

    return filename



def save_fig(plot, parent=None, figsize=None, filename=None, overwrite_without_prompt=False):
    '''
    Saves figure to file 'filename.png' and 'filename.pdf', or provides dialog if no
    filename provided.

    Args:
       fig: A matplotlib fig object
       filename: string [optional]
       overwrite_without_prompt: boo
    '''
    if plot.__class__.__name__ == 'PlotData':
        fig = plot.fig
    elif plot.__class__.__name__ == 'Figure':
        fig = plot

    # If filename not specified, provide dialog
    if filename is None:
        filename, _ = QFileDialog.getSaveFileName(parent, 'Save figure', '')
        if not filename:
            # No filename chosen, give up on saving
            print('Save cancelled')
            return None


    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    elif os.path.isfile(filename) and not overwrite_without_prompt:
        answer = input('File %r already exists. Overwrite? [y/n]: ' % filename)
        if answer != 'y':
            print('Save cancelled')
            return None
        print('Will overwrite existing file')

    # Set figsize...
    original_size = fig.get_size_inches()
    if figsize is not None:
        fig.set_size_inches(figsize,forward=False)
        
    # Make sure it ends with .png then .pdf
    filename = os.path.splitext(filename)[0]
    if not filename.endswith('.png'):
        filename += '.png'
    fig.savefig(filename, dpi=300)
    print("Figure saved as %s" % filename)
    
    filename = os.path.splitext(filename)[0]
    if not filename.endswith('.pdf'):
        filename += '.pdf'
    fig.savefig(filename, dpi=300)
    print("Figure saved as %s" % filename)

    # return to original size
    fig.set_size_inches(original_size,forward=False)
    
    
    return filename



#%% EXPORT TO MATLAB
def export_to_matlab(dataset, parent=None, filename=None, overwrite_without_prompt=False):
    '''
    Exports dataset class to file 'filename.mat', or provides dialog if no
    filename provided.
    
    Saved file can be loaded directly in Matlab as set of arrays.

    Args:
       dataset: An object of the class dataSet
       filename: string [optional]
       overwrite_without_prompt: bool

    '''
    
    # convert data into dictionary ready for Matlab
    data_matlab = dict()
    
    #%% TIME
    if len(dataset.time_data_list) > 0:
        T=0
        fs=0
        n_time=0
        for time_data in dataset.time_data_list:
            N = len(time_data.time_axis)
            T = np.max([time_data.time_axis[-1]*N/(N-1),T])
            fs = np.max([1/np.mean(np.diff(time_data.time_axis)),fs])
            n_time += time_data.settings.channels
        
        t=np.arange(0,T,1/fs)
        time_data_all = np.zeros((len(t),n_time))
        counter = -1
        for time_data in dataset.time_data_list:
            for i in range(time_data.settings.channels):
                counter += 1
                time_data_all[:,counter] = np.interp(t,time_data.time_axis,time_data.time_data[:,i],right=0)
                
        data_matlab['time_axis_all'] = np.transpose(np.atleast_2d(t))
        data_matlab['time_data_all'] = time_data_all

    


    #%% FFT - doesn't export coherence
    if len(dataset.freq_data_list) > 0:
        df=np.inf
        fmax=0
        n_tf=0
        for freq_data in dataset.freq_data_list:
            df_check = np.mean(np.diff(freq_data.freq_axis))
            df = np.min([df,df_check])
            fmax = np.max([freq_data.freq_axis[-1],fmax])
            tf_shape = np.shape(freq_data.freq_data)
            n_tf += tf_shape[1]
        
        f=np.arange(0,fmax+df,df)
        npts = 2*(len(f)-1)
        fs_tf = 2*f[-1]
        freq_data_all = np.zeros((len(f),n_tf),dtype=complex)
        counter = -1
        for freq_data in dataset.freq_data_list:
            freq_shape = np.shape(freq_data.freq_data)
            for i in range(freq_shape[1]):
                counter += 1
                freq_data_all[:,counter] = np.interp(f,freq_data.freq_axis,freq_data.freq_data[:,i],right=0)
        
        data_matlab['freq_axis_all'] = np.transpose(np.atleast_2d(f))
        data_matlab['freq_data_all'] = freq_data_all
        
 


    #%% Transfer Function - doesn't export coherence
    if len(dataset.tf_data_list) > 0:
        df=np.inf
        fmax=0
        n_tf=0
        for tf_data in dataset.tf_data_list:
            df_check = np.mean(np.diff(tf_data.freq_axis))
            df = np.min([df,df_check])
            fmax = np.max([tf_data.freq_axis[-1],fmax])
            tf_shape = np.shape(tf_data.tf_data)
            n_tf += tf_shape[1]
        
        f=np.arange(0,fmax+df,df)
        npts = 2*(len(f)-1)
        fs_tf = 2*f[-1]
        tf_data_all = np.zeros((len(f),n_tf),dtype=complex)
        counter = -1
        for tf_data in dataset.tf_data_list:
            tf_shape = np.shape(tf_data.tf_data)
            for i in range(tf_shape[1]):
                counter += 1
                tf_data_all[:,counter] = np.interp(f,tf_data.freq_axis,tf_data.tf_data[:,i],right=0)
        
        data_matlab['tf_axis_all'] = np.transpose(np.atleast_2d(f))
        data_matlab['tf_data_all'] = tf_data_all
        

    


    #%% SAVE

    # If filename not specified, provide dialog
    if filename is None:
        filename, _ = QFileDialog.getSaveFileName(parent, 'Save dataset', '', '*.mat')
        if not filename:
            # No filename chosen, give up on saving
            print('Save cancelled')
            return None


    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    elif os.path.isfile(filename) and not overwrite_without_prompt:
        answer = input('File %r already exists. Overwrite? [y/n]: ' % filename)
        if answer != 'y':
            print('Save cancelled')
            return None
        print('Will overwrite existing file')
        
    # Make sure it ends with .npy
    if not filename.endswith('.mat'):
        filename += '.mat'
        
    # Actually save!
    io.savemat(filename,data_matlab)
    print("Data saved as %s" % filename)

    return filename



#%% EXPORT TO MATLAB JWLOGGER
def export_to_matlab_jwlogger(dataset, parent=None, filename=None, overwrite_without_prompt=False):
    '''
    Exports dataset class to file 'filename.mat', or provides dialog if no
    filename provided.
    
    Saved file is compatible with Jim Woodhouse logger file format.

    Args:
       dataset: An object of the class dataSet
       filename: string [optional]
       overwrite_without_prompt: bool

    '''

    # convert data into dictionary ready for Matlab
    data_jwlogger = dict()
    
    #%% TIME
    if len(dataset.time_data_list) > 0:
        T=0
        fs=0
        n_time=0
        for time_data in dataset.time_data_list:
            N = len(time_data.time_axis)
            T = np.max([time_data.time_axis[-1]*N/(N-1),T])
            fs = np.max([1/np.mean(np.diff(time_data.time_axis)),fs])
            n_time += time_data.settings.channels
        
        t=np.arange(0,T,1/fs)
        time_data_all = np.zeros((len(t),n_time))
        counter = -1
        for time_data in dataset.time_data_list:
            for i in range(time_data.settings.channels):
                counter += 1
                time_data_all[:,counter] = np.interp(t,time_data.time_axis,time_data.time_data[:,i],right=0)
                
        data_jwlogger['buflen'] = float(np.size(t))
        data_jwlogger['indata'] = time_data_all
        data_jwlogger['tsmax'] = float(t[-1])
    else:
        n_time = 0
        time_data_all = 0
    
    
    #%% FFT: get's overwritten by TF if exists
    if len(dataset.freq_data_list) > 0:
        df=np.inf
        fmax=0
        n_freq=0
        for freq_data in dataset.freq_data_list:
            df_check = np.mean(np.diff(freq_data.freq_axis))
            df = np.min([df,df_check])
            fmax = np.max([freq_data.freq_axis[-1],fmax])
            freq_shape = np.shape(freq_data.freq_data)
            n_freq += freq_shape[1]
        
        f=np.arange(0,fmax+df,df)
        npts = 2*(len(f)-1)
        fs_freq = 2*f[-1]
        freq_data_all = np.zeros((len(f),n_freq),dtype=complex)
        counter = -1
        for freq_data in dataset.freq_data_list:
            freq_shape = np.shape(freq_data.freq_data)
            for i in range(freq_shape[1]):
                counter += 1
                freq_data_all[:,counter] = np.interp(f,freq_data.freq_axis,freq_data.freq_data[:,i],right=1)
                freq_data_all[0,counter] = freq_data_all[1,counter] # to match equivalent tweak in JW Logger for handling DC singularities
                zero_test = freq_data_all[:,counter] == 0
                freq_data_all[zero_test,counter] = np.min(np.abs(freq_data_all[:,counter])) # handle zeros
        
        # convert
        data_jwlogger['freq'] = float(fs_freq)
        data_jwlogger['npts'] = float(npts)
        data_jwlogger['yspec'] = freq_data_all
    else:
        n_freq = 0
        freq_data_all = 0
    
    
    #%% Transfer Function - doesn't export coherence
    if len(dataset.tf_data_list) > 0:
        df=np.inf
        fmax=0
        n_tf=0
        for tf_data in dataset.tf_data_list:
            df_check = np.mean(np.diff(tf_data.freq_axis))
            df = np.min([df,df_check])
            fmax = np.max([tf_data.freq_axis[-1],fmax])
            tf_shape = np.shape(tf_data.tf_data)
            n_tf += tf_shape[1]
        
        f=np.arange(0,fmax+df,df)
        npts = 2*(len(f)-1)
        fs_tf = 2*f[-1]
        tf_data_all = np.zeros((len(f),n_tf),dtype=complex)
        counter = -1
        for tf_data in dataset.tf_data_list:
            tf_shape = np.shape(tf_data.tf_data)
            for i in range(tf_shape[1]):
                counter += 1
                tf_data_all[:,counter] = np.interp(f,tf_data.freq_axis,tf_data.tf_data[:,i],right=1)
                tf_data_all[0,counter] = tf_data_all[1,counter] # to match equivalent tweak in JW Logger for handling DC singularities
                zero_test = freq_data_all[:,counter] == 0
                tf_data_all[zero_test,counter] = np.min(np.abs(tf_data_all[:,counter])) # handle zeros
        
        # convert
        data_jwlogger['freq'] = float(fs_tf)
        data_jwlogger['npts'] = float(npts)
        data_jwlogger['yspec'] = tf_data_all
    else:
        n_tf = 0
        tf_data_all = 0
    
    #%% Convert
    
    if (n_freq > 0) & (n_tf > 0):
        # if both FFT and TF data present then TF overwrites
        N = n_tf
    else:
        # if only one of FFT or TF, or neither, then keep non-zero one, or neither
        N = np.max([n_tf,n_freq])
    
    data_jwlogger['dt2'] = np.array([n_time,N,0],dtype=float)
    data_jwlogger['dtype'] = np.array([n_time,N,0],dtype=float)
    

    # SAVE

    # If filename not specified, provide dialog
    if filename is None:
        filename, _ = QFileDialog.getSaveFileName(parent, 'Save dataset', '', '*.mat')
        if not filename:
            # No filename chosen, give up on saving
            print('Save cancelled')
            return None


    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    elif os.path.isfile(filename) and not overwrite_without_prompt:
        answer = input('File %r already exists. Overwrite? [y/n]: ' % filename)
        if answer != 'y':
            print('Save cancelled')
            return None
        print('Will overwrite existing file')
        
    # Make sure it ends with .npy
    if not filename.endswith('.mat'):
        filename += '.mat'
        
    # Actually save!
    io.savemat(filename,data_jwlogger)
    print("Data saved as %s" % filename)

    return filename


def export_to_csv(data_list, parent=None, filename=None, overwrite_without_prompt=False):
    '''
    Exports data to file 'filename.csv', or provides dialog if no
    filename provided.
    
    Saved file is *.csv

    Args:
       data_list: An object of the class TimeDataList, FreqDataList, or TfDataList
       filename: string [optional]
       overwrite_without_prompt: bool
    '''
    
    data_list_type = data_list.__class__.__name__
    
    if data_list_type == 'TimeDataList':
        darray = np.transpose(np.atleast_2d(data_list[0].time_axis))
        for time_data in data_list:
            darray = np.append(darray,time_data.time_data,axis=1)
        
            
            
    elif data_list_type == 'FreqDataList':
        darray = np.transpose(np.atleast_2d(data_list[0].freq_axis))
        for freq_data in data_list:
            darray = np.append(darray,freq_data.freq_data,axis=1)
        
    elif data_list_type == 'TfDataList':
        darray = np.transpose(np.atleast_2d(data_list[0].freq_axis))
        for tf_data in data_list:
            darray = np.append(darray,tf_data.tf_data,axis=1)
        
    else:
        print('Expecting input to be one of TimeDataList, FreqDataList, or TfDataList')
        return None
    
    # SAVE

    # If filename not specified, provide dialog
    if filename is None:
        filename, _ = QFileDialog.getSaveFileName(parent, 'Save dataset', '', '*.csv')
        if not filename:
            # No filename chosen, give up on saving
            print('Save cancelled')
            return None


    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    elif os.path.isfile(filename) and not overwrite_without_prompt:
        answer = input('File %r already exists. Overwrite? [y/n]: ' % filename)
        if answer != 'y':
            print('Save cancelled')
            return None
        print('Will overwrite existing file')
        
    # Make sure it ends with .csv
    if not filename.endswith('.csv'):
        filename += '.csv'
        
    # Actually save!
    np.savetxt(filename, darray, delimiter=",")
    print("Data saved as %s" % filename)

    return filename



#%% IMPORT FROM MATLAB JWLOGGER
def import_from_matlab_jwlogger(filename=None):
    '''
    Imports dataset class from file 'filename.mat', or provides dialog if no
    filename provided.
    
    Saved file is compatible with Jim Woodhouse logger file format.

    Args:
       filename: string [optional]
    '''
    
    d = io.loadmat(filename)
    dataset = datastructure.DataSet()
    
    #%% TIME
    if 'indata' in d:
        td = d['indata']
        ta = np.arange(0,d['npts']/d['freq'],1/d['freq'])
        ta = np.squeeze(ta)
        settings = options.MySettings(channels=np.size(td,1),
                                      fs=d['freq'])
        
        time_data = datastructure.TimeData(ta,td,settings)
        time_data.timestamp = os.path.getmtime(filename)
        dataset.add_to_dataset(time_data)
    
    #%% FFT
    if ('yspec' in d) and (d['tfun'] == 0):
        fd = d['yspec']
        fa = np.fft.rfftfreq(int(d['npts']),1/d['freq'])
        fa = np.squeeze(fa)
        settings = options.MySettings(channels=np.size(fd,1),
                                      fs=d['freq'])
        
        freq_data = datastructure.FreqData(fa,fd,settings)
        freq_data.timestamp = os.path.getmtime(filename)
        dataset.add_to_dataset(freq_data)

    
    #%% TF
    if ('yspec' in d) and (d['tfun'] == 1):
        tf = d['yspec']
        fa = np.fft.rfftfreq(int(d['npts']),1/d['freq'])
        fa = np.squeeze(fa)
        settings = options.MySettings(channels=np.size(tf,1),
                                      fs=d['freq'])
        
        tf_data = datastructure.TfData(fa,tf,None,settings)
        tf_data.timestamp = os.path.getmtime(filename)
        dataset.add_to_dataset(tf_data)
    
    return dataset