# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 14:32:35 2018

@author: tb267
"""

import os.path
import numpy as np

from pyqtgraph.Qt import QtGui


def load_data(filename=None):
    '''
    Loads dataset from filename, or displays a dialog if no argument provided.
    '''
    if filename is None:
        filename, _ = QtGui.QFileDialog.getOpenFileName(None, 'Open data file', '', '*.npy')
        if not filename:
            return None

    d = np.load(filename)
    dataset = d[0]
    return dataset


def save_data(dataset, filename=None, overwrite_without_prompt=False):
    '''Saves dataset class to file 'filename.npy', or provides dialog if no
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
        filename, _ = QtGui.QFileDialog.getSaveFileName(None, 'Save dataset', '', '*.npy')
        if not filename:
            # No filename chosen, give up on saving
            print('Giving up on saving')
            return None

    # Make sure it ends with .npy
    if not filename.endswith('.npy'):
        filename += '.npy'

    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    if os.path.isfile(filename) and not overwrite_without_prompt:
        answer = input('File %r already exists. Overwrite? [y/n]: ' % filename)
        if answer != 'y':
            print('Giving up on saving')
            return None
        print('Will overwrite existing file')

    # Actually save!
    np.save(filename, d)
    print("Data saved as %s" % filename)

    return filename
