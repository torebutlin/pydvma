# -*- coding: utf-8 -*-
"""
Created on Mon Aug 13 15:37:24 2018

@author: ae407
"""
import numpy as np
import scipy as sp
import peakutils
        

class beam_data(object):
    ''' Defines beam data for m1 lab'''
    
    def __init__(self,*,L,b,d,M):
        """
        Args:
            L: length (m)
            b: width (m)
            d: thickness (m)
            M: mass (kg)
            
        Note units are in m or kg
            
        """
        self.L = L
        self.b = b
        self.d = d
        self.M = M
        self.rho = self.M/(self.L*self.b*self.d)
        self.I = (self.b*(self.d**3))/12
        self.A = self.b*self.d
        self.alphaL = np.array([4.730, 7.853, 10.996, 14.137])
        

def E_calculator(*,beam_data,frequency,mode):
    '''
    Args:
        beam_data (class): Beam data object
        frequency: frequency of mode in Hz.
        mode (int): mode number

    Returns:
        E: Calculation of Young's Modulus
    '''
    
    if type(mode)!=int:
        print('Insert an integer for mode')
        return
    elif mode < 1 or mode > 4:
        print('Invalid mode number. Please give a number between 1 and 4')
        return
    
    alpha = beam_data.alphaL[mode-1] / beam_data.L
    
    E = ((2*np.pi*frequency)**2)*((beam_data.L/alpha)**4)*beam_data.rho*beam_data.A/beam_data.I
    print('The Young\'s Modulus calculated from Mode %i is %.2f GPa' %(mode,E*1e-9))  
    print('Density= %.2f kgm^-3' % beam_data.rho)
    return E
        
    
    
#####some data####
"""
beam_data=m1.beam_data(200,25,1.37,16)
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
        
    elif freq_range.__class__.__name__ == 'plotdata':
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
    
#    keep = 20*np.log10(np.abs(peak_amplitudes)) > threshold
#    
##    largest = np.argsort(-peak_amplitudes)
##    largest = largest[0:n]
##    peak_frequencies = peak_frequencies[largest]
##    peak_amplitudes = peak_amplitudes[largest]
##    indices = np.argsort(peak_frequencies)
#    peak_frequencies = peak_frequencies[keep]
#    peak_amplitudes  = peak_amplitudes[keep]
    
    if len(peak_frequencies) < 10:    
        print('The most significant peaks above %s dB in the specified range are at the following frequencies:' % str(np.round(threshold,decimals=1)))
        print(round2nsf(peak_frequencies,4))
    else:
        print('%i peaks have been found. The first 10 are:' % len(peak_frequencies))
        print(round2nsf(peak_frequencies[0:10],4))
        print('To reduce the number of peaks, use a higher threshold. If using a plot to specifiy the threshold then use the zoom to view only the peaks and not the noisy data underneath.')
        
    return peak_frequencies, peak_amplitudes


def round2nsf(x,nsf):
    '''
    round x to nsf significant figures
    '''
    
    temp = 10**(np.floor(np.log10(np.abs(x)) - nsf + 1));
    y = np.round(x/temp)*temp;
    
    return y
