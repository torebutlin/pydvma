# -*- coding: utf-8 -*-
"""
Created on Mon Aug 13 15:37:24 2018

@author: ae407
"""
import numpy as np
import scipy as sp
import peakutils
import pydvma as dvma
        

DEFAULT_SETTINGS = dvma.MySettings(channels=1,fs=8000,stored_time=2,viewed_time=2,device_index=1)


class Beam(object):
    ''' Defines Beam data for m1 lab'''
    
    def __init__(self,*,L,b,d,M):
        """
        Args:
            L: length (mm)
            b: width (mm)
            d: thickness (mm)
            M: mass (grams)
            
        Note units are in millimeters or grams

        """
        self.L = L/1e3
        self.b = b/1e3
        self.d = d/1e3
        self.M = M/1e3
        self.rho = self.M/(self.L*self.b*self.d)
        self.I = (self.b*(self.d**3))/12
        self.A = self.b*self.d
        self.alphaL = np.array([4.730, 7.853, 10.996, 14.137])
        

def E_calculator(*,beam,frequency,mode):
    '''
    Args:
        beam (class): Beam data object
        frequency: frequency of mode in Hz.
        mode (int): mode number

    Returns:
        E: Calculation of Young's Modulus
    '''
    rho = beam.rho
    
    if type(mode)!=int:
        print('Insert an integer for mode')
        return
    elif mode < 1 or mode > 4:
        print('Invalid mode number. Please give a number between 1 and 4')
        return
    
    alpha = beam.alphaL[mode-1] / beam.L
    
    E = ((2*np.pi*frequency)**2)*((1/alpha)**4)*beam.rho*beam.A/beam.I
    print('The Young\'s Modulus calculated from Mode %i is %.2f GPa' %(mode,E*1e-9))  
    print('Density = %.2f kgm^-3' % beam.rho)
    return E,rho
        
    
    
#####some data####
"""
beam_data=m1.beam(200,25,1.37,16)
f1=153.45
f2=424.22
f3=833.09
f4=1387.50
"""


def find_peaks(freq_data,channel=0,threshold=0,freq_range=None):
    '''
    Returns a list of the n most prominent peaks in plot.
    
    Args:
        freq_data:
        freq_range:
    '''
    if freq_range == None:
        ### use all data
        freq_range = freq_data.freq_axis[[0,-1]]
        
    elif freq_range.__class__.__name__ == 'PlotData':
        threshold=freq_range.ax.get_ybound()
        threshold=threshold[0]
        freq_range=freq_range.ax.get_xbound()
        
        

    s1 = freq_data.freq_axis >= freq_range[0]
    s2 = freq_data.freq_axis <= freq_range[1]
    selection = s1 & s2
    
    faxis = freq_data.freq_axis[selection]
    fdata = freq_data.freq_data[selection,:]
    fdata = fdata[:,channel]
    
    peaks = sp.signal.find_peaks(np.abs(fdata))
    peaks = peaks[0]
    
    df = freq_data.freq_axis[1]
    peaks = peakutils.indexes(20*np.log10(np.abs(fdata)), thres=threshold, min_dist=np.round(10/df),thres_abs=True)

    peak_frequencies = faxis[peaks]
    peak_amplitudes= np.abs(fdata[peaks])
    

    
    if len(peak_frequencies) < 10:    
        print('The most significant peaks above %.2f dB in the specified range are at the following frequencies:' %(threshold))
        freq_list = ''
        for f in peak_frequencies:
            freq_list = freq_list + '%.4g'%f + '  '
        print(freq_list)
    else:
        print('%i peaks have been found. The first 10 are:' % len(peak_frequencies))
        freq_list = ''
        for f in peak_frequencies[0:10]:
            freq_list = freq_list + '%.4g'%f + '  '
        print(freq_list)
        print('To reduce the number of peaks, use a higher threshold. If using a plot to specifiy the threshold then use the zoom to view only the peaks and not the noisy data underneath.')
        
    return peak_frequencies, peak_amplitudes



def find_peaks2(freq_data,channel=0,threshold=0,freq_range=None):
    '''
    Returns a list of the n most prominent peaks in plot.
    
    Args:
        freq_data:
        freq_range:
    '''
    if freq_range == None:
        ### use all data
        freq_range = freq_data.freq_axis[[0,-1]]
        
    elif freq_range.__class__.__name__ == 'PlotData':
        threshold=freq_range.ax.get_ybound()
        threshold=threshold[0]
        freq_range=freq_range.ax.get_xbound()
        
        


    s1 = np.argwhere(freq_range[0] <= freq_data.freq_axis <= freq_range[1])
    s2 = 49 < freq_data.freq_axis < 51
    s3 = 149 < freq_data.freq_axis < 151
    selection = s1 & s2 & s3
    selection = np.argwhere(selection)
    
    fdata = np.abs(fdata[:,channel])
    max_gap = np.ceil(len(selection)/20)
    
    ip = []
    while sum(selection) > 0:
        imax = np.argmax(fdata[selection])
        imax = selection[imax]
        ip = [ip,imax]
        selection = selection[(imax-max_gap) < selection < (imax+max_gap)]
    
    peak_frequencies = freq_data.freq_axis[ip]
    peak_amplitudes = fdata[ip]
    
    return peak_frequencies, peak_amplitudes