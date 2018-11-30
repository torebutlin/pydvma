# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 14:32:35 2018

@author: tb267
"""
import sys

from . import logsettings
from . import plotting
from . import logdata

import numpy as np
import os.path
from pyqtgraph.Qt import QtGui, QtCore
import tkinter as tk
from tkinter import filedialog, messagebox



        
        
#def load_data(*filename):
#    '''
#    Loads dataset from filename, or displays a dialog if no argument provided.
#    '''
#    if len(filename) == 0:
#        wid = QtGui.QFileDialog()
#        wid.setModal(True)
#        
#        filename = wid.getOpenFileName(wid,'title',None,'*.npy')
#        
#        
#        
#        filename = filename[0]
#        if filename:
#            d=np.load(filename)
#            dataset = d[0]
#            print('dataset loaded')
#        else:
#            dataset = None
#            print('no data loaded')
#
#    
#    elif (len(filename)==1) & (type(filename[0])==str):
#        d=np.load(filename)
#        dataset = d[0]
#        print('dataset loaded')
#        
#    else:
#        print('Unexpected input arguments (expecting single filename string)')
#        dataset = None
#        
#    return dataset
    
def load_data(*filename):
    '''
    Loads dataset from filename, or displays a dialog if no argument provided.
    '''

    
    if len(filename) == 0:
        root = tk.Tk()
        root.attributes('-topmost', 1)
        root.withdraw()
        filename =  filedialog.askopenfilename(title = "Select data file",filetypes =[("numpy data","*.npy")])

        if filename:
            d=np.load(filename)
            dataset = d[0]
            print('dataset loaded')
        else:
            dataset = None
            print('no data loaded')
            
        root.destroy()
        
    elif (len(filename)==1) and (type(filename[0]) is str):
        d=np.load(filename[0])
        dataset = d[0]
        print('dataset loaded')
        
    else:
        print('Unexpected input arguments (expecting single filename string)')
        dataset = None
        
    return dataset








#def save_data(dataset,*savename,overwrite_without_prompt=False):
#    '''
#    Saves dataset class to file 'savename.npy', or provides dialog if no filename provided.
#    
#    Args:
#        dataset: An object of the class dataSet
#        savename: string
#        overwrite_without_prompt: bool
#    '''
#
#    
#    # put data into numpy array
#    d = np.array([dataset])
#    
#    #if filename not specified, provide dialog
#    if len(savename) == 0:
#        # PROMPT
#        filename = QtGui.QFileDialog.getSaveFileName(None,'Save dataset',None,'*.npy')
#        filename = filename[0]
#        if filename:
#            filename = filename.replace(".npy","")+".npy"
#            np.save(filename,d)
#            print("Data saved as " + filename)
#      
#    #if filename not specified, provide dialog
#    elif (len(savename) == 1) & (type(savename[0]) == str):
#        # use savename
#        filename = savename[0].replace(".npy","")+".npy"
#        if overwrite_without_prompt == True:
#            if os.path.isfile(filename):
#                print('Overwriting existing file')
#            np.save(filename,d)
#            print("Data saved as " + filename)  
#            
#        elif os.path.isfile(filename):
#            answer = input('File \'' + filename + '\' already exists. Overwrite? [y/n]: ')
#            if answer == 'y':
#                np.save(savename+".npy",d)
#                print("Data saved as " + filename + ' (existing file overwritten)')
#            else:
#                filename = QtGui.QFileDialog.getSaveFileName(None,'Save dataset',None,'*.npy')
#                filename = filename[0]
#                if filename:
#                    filename = filename.replace(".npy","")+".npy"
#                    np.save(filename,d)
#                    print("Data saved as " + filename)
#                    
#        else:
#            filename = filename.replace(".npy","")+".npy"
#            np.save(filename,d)
#            print("Data saved as " + filename)
#            
#        
#    else:
#        print('Unexpected input arguments')
#        filename = None
#    
#    return filename
        
    
def save_data(dataset,*savename,overwrite_without_prompt=False):
    '''
    Saves dataset class to file 'savename.npy', or provides dialog if no filename provided.
    
    Args:
        dataset: An object of the class dataSet
        savename: string
        overwrite_without_prompt: bool
    '''

    
    # put data into numpy array
    d = np.array([dataset])
    
    #if filename not specified, provide dialog
    if len(savename) == 0:
        # PROMPT
        root = tk.Tk()
        root.attributes('-topmost', 1)
        root.withdraw()
        filename = filedialog.asksaveasfilename(title = "Save dataset",filetypes =[("numpy data","*.npy")])
        
        if filename != '':
            filename = filename.replace(".npy","")+".npy"
            np.save(filename,d)
            print("Data saved as " + filename)
        else:
            print('Data not saved')
            
        root.destroy()
      
    #if filename not specified, provide dialog
    elif (len(savename) == 1) & (type(savename[0]) == str):
        # use savename
        filename = savename[0].replace(".npy","")+".npy"
        if overwrite_without_prompt == True:
            #if os.path.isfile(filename):
                #print('Overwriting existing file')
            np.save(filename,d)
            print("Data saved as " + filename)  
            
        elif os.path.isfile(filename):
            root = tk.Tk()
            root.attributes('-topmost', 1)
            root.withdraw()
            answer = messagebox.askyesno('Overwrite?','File \'' + filename + '\' already exists. Overwrite?')
            root.destroy()
            if answer:
                np.save(filename,d)
                print("Data saved as " + filename + ' (existing file overwritten)')
            else:
                root = tk.Tk()
                root.attributes('-topmost', 1)
                root.withdraw()
                filename = filedialog.asksaveasfilename(title = "Save dataset",filetypes =[("numpy data","*.npy")])
                if filename != '':
                    filename = filename.replace(".npy","")+".npy"
                    np.save(filename,d)
                    print("Data saved as " + filename)
                else:
                    print('Data not saved')
                    
                root.destroy()
                    
        else:
            filename = filename.replace(".npy","")+".npy"
            np.save(filename,d)
            print("Data saved as " + filename)
            
        
    else:
        print('Unexpected input arguments')
        filename = None
    
    return filename
 
    
            
