# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 14:32:35 2018

@author: tb267
"""
import sys

from . import settings
from . import plotting
from . import logdata

import numpy as np
import os.path
from pyqtgraph.Qt import QtGui, QtCore


        
        
def load_data(*filename):
    '''
    Loads dataset from filename, or displays a dialog if no argument provided.
    '''
    if len(filename) == 0:
#        wid = QtGui.QWidget()
        filename = QtGui.QFileDialog.getOpenFileName(None,'title',None,'*.npy')
        filename = filename[0]
        if filename:
            d=np.load(filename)
            dataset = d[0]
        else:
            dataset = None

    
    elif (len(filename)==1) & (type(filename[0])==str):
        d=np.load(filename)
        dataset = d[0]
        
    else:
        print('Unexpected input arguments (expecting single filename string)')
        dataset = None
        
    return dataset
    
#    
#    
#    
#    ##fromfile means extracted 
#    open_root = tk.Tk()
#    open_root.attributes('-topmost', 1)
#    #open_root.attributes('-topmost', 0) # commented to force user to save or cancel
#    open_root.filename =  filedialog.askopenfilename()
#    if open_root.filename: # askopenfilename returns `False` if dialog closed with "cancel".
#        d=np.load(open_root.filename)
#        dataset = d[0]
#        open_root.destroy()
#    else:
#        open_root.destroy()
#        return
#
#    return dataset


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
        filename = QtGui.QFileDialog.getSaveFileName(None,'Save dataset',None,'*.npy')
        filename = filename[0]
        if filename:
            filename = filename.replace(".npy","")+".npy"
            np.save(filename,d)
            print("Data saved as " + filename)
      
    #if filename not specified, provide dialog
    elif (len(savename) == 1) & (type(savename[0]) == str):
        # use savename
        filename = savename[0].replace(".npy","")+".npy"
        if overwrite_without_prompt == True:
            if os.path.isfile(filename):
                print('Overwriting existing file')
            np.save(filename,d)
            print("Data saved as " + filename)  
            
        elif os.path.isfile(filename):
            answer = input('File \'' + filename + '\' already exists. Overwrite? [y/n]: ')
            if answer == 'y':
                np.save(savename+".npy",d)
                print("Data saved as " + filename + ' (existing file overwritten)')
            else:
                filename = QtGui.QFileDialog.getSaveFileName(None,'Save dataset',None,'*.npy')
                filename = filename[0]
                if filename:
                    filename = filename.replace(".npy","")+".npy"
                    np.save(filename,d)
                    print("Data saved as " + filename)
                    
        else:
            filename = filename.replace(".npy","")+".npy"
            np.save(filename,d)
            print("Data saved as " + filename)
            
        
    else:
        print('Unexpected input arguments')
        filename = None
    
    return filename
        
    
#    savename = savename.replace(".npy","")
#    
#    ## check if it exists
#    if os.path.isfile(savename+'.npy'):
#        if overwrite_without_prompt:
#            np.save(savename+".npy",d)
#            print('Data saved as \'' + savename + '.npy\': overwriting existing file')
#        else:
#            answer = input('File \'' + savename + '.npy\' already exists. Overwrite? [y/n]: ')
#            if answer == 'y':
#                np.save(savename+".npy",d)
#            else:
#                print('Data not saved. Write code to prompt for saving')
                
            
    
    
    
    



#TODO: Supressing little Tk window. Note that it already gets destroyed after performing its function
# to supress little tk window
#root=tk.Tk()
#root.withdraw()
            
#currently stays as the topmost dialog until exited.
#below line should fix it but instead hides it back
#try adding a pause inbetween the two lines
#tk_window.attributes('-topmost', 0)
#TODO:Sent dialog to the top but without being permanently there.

 
    
            
