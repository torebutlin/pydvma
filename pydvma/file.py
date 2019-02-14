# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 14:32:35 2018

@author: tb267
"""

import os.path
import numpy as np

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