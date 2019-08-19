# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 14:32:35 2018

@author: tb267
"""

import os.path
import numpy as np
import scipy.io as io

from pyqtgraph.Qt import QtGui, QtWidgets


def load_data(filename=None):
    '''
    Loads dataset from filename, or displays a dialog if no argument provided.
    '''
    if filename is None:
        wid = QtWidgets.QWidget()
        filename, _ = QtGui.QFileDialog.getOpenFileName(wid, 'Open data file', '', '*.npy')
        if not filename:
            return None

    d = np.load(filename)
    dataset = d[0]
    return dataset


def save_data(dataset, filename=None, overwrite_without_prompt=False):
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
        wid = QtWidgets.QWidget()
        filename, _ = QtGui.QFileDialog.getSaveFileName(wid, 'Save dataset', '', '*.npy')
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



def save_fig(plot, figsize=None, filename=None, overwrite_without_prompt=False):
    '''
    Saves figure to file 'filename.png' and 'filename.pdf', or provides dialog if no
    filename provided.

    Args:
       fig: A matplotlib fig object
       filename: string [optional]
       overwrite_without_prompt: boo
    '''
    if plot.__class__.__name__ is 'PlotData':
        fig = plot.fig
    elif plot.__class__.__name__ is 'Figure':
        fig = plot

    # If filename not specified, provide dialog
    if filename is None:
        wid = QtWidgets.QWidget()
        filename, _ = QtGui.QFileDialog.getSaveFileName(wid, 'Save figure', '')
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


def export_to_matlab_jwlogger(dataset, filename=None, overwrite_without_prompt=False):
    '''
    Saves dataset class to file 'filename.npy', or provides dialog if no
    filename provided.

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
        n=0
        for time_data in dataset.time_data_list:
            T = np.max([time_data.settings.stored_time,T])
            fs = np.max([time_data.settings.fs,fs])
            n += time_data.settings.channels
        
        t=np.arange(0,T,1/fs)
        time_data_all = np.zeros((np.size(t),n))
        counter = -1
        for time_data in dataset.time_data_list:
            for i in range(time_data.settings.channels):
                counter += 1
                time_data_all[:,counter] = np.interp(t,time_data.time_axis,time_data.time_data[:,i],right=0)
    
    
    #%% Transfer Function
    df=np.inf
    fmax=0
    n=0
    for tf_data in dataset.tf_data_list:
        df = np.min([df,tf_data.freq_axis[-1]/len(tf_data.freq_axis)])
        fmax = np.max([tf_data.freq_axis[-1],fmax])
        n += tf_data.settings.channels
    
    f=np.arange(0,fmax+df,df)
    tf_data_all = np.zeros((np.size(f),n))
    counter = -1
    for tf_data in dataset.tf_data_list:
        for i in range(tf_data.settings.channels):
            counter += 1
            tf_data_all[:,counter] = np.interp(f,tf_data.tf_axis,tf_data.tf_data[:,i],right=0)
    
    #%% Convert
    data_jwlogger['buflen'] = np.float(np.size(t))
    data_jwlogger['dt2'] = np.array([n,0,0],dtype=float)
    data_jwlogger['freq'] = np.float(fs)
    data_jwlogger['indata'] = time_data_all
    data_jwlogger['tsmax'] = np.float(t[-1])#np.float(fs*np.size(t))


    # If filename not specified, provide dialog
    if filename is None:
        wid = QtWidgets.QWidget()
        filename, _ = QtGui.QFileDialog.getSaveFileName(wid, 'Save dataset', '', '*.mat')
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