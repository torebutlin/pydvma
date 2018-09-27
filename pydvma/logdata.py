# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 17:08:42 2018

@author: tb267
"""



class DataSet():
    def __init__(self,timedata=None,freqdata=None,tfdata=None,sonodata=None,metadata=None):
        self.timedata = timedata
        self.freqdata = freqdata
        self.tfdata   = tfdata
        self.sonodata = sonodata
        self.metadata = metadata
        
    def __repr__(self):
        text = '<DataSet class containing: '
        if repr(self.timedata) != 'None':
            text += repr(self.timedata)
        if repr(self.freqdata) != 'None':
            text += repr(self.freqdata)
        if repr(self.tfdata) != 'None':
            text += repr(self.tfdata)
        if repr(self.sonodata) != 'None':
            text += repr(self.sonodata)
        if repr(self.metadata) != 'None':
            text += repr(self.metadata)
        
        text += '>'
        return text
        
        
class TimeData():
    def __init__(self,time_axis,time_data,settings):
        self.time_axis = time_axis
        self.time_data = time_data  
        self.settings = settings
        
    def __repr__(self):
        return "<TimeData>"

        
class FreqData():
    def __init__(self,freq_axis,freq_data,settings):
        self.freq_axis = freq_axis
        self.freq_data = freq_data
        self.settings = settings
        
    def __repr__(self):
        return "<FreqData>"
        
class TfData():
    def __init__(self,freq_axis,tf_data,settings):
        self.freq_axis = freq_axis
        self.tf_data = tf_data
        self.settings = settings
        
    def __repr__(self):
        return "<TfData>"
        
class SonoData():
    def __init__(self,time_axis,freq_axis,sono_data,settings):
        self.time_axis = time_axis
        self.freq_axis = freq_axis
        self.sono_data = sono_data
        self.settings = settings
        
    def __repr__(self):
        return "<SonoData>"
        
class MetaData():
    def __init__(self, timestamp=None, timestring=None, units=None, channel_cal_factors=None, tf_cal_factors = None):
        self.timestamp = timestamp
        self.timestring = timestring
        self.units = units
        self.channel_cal_factors = None
        self.tf_cal_factors = None
        
    def __repr__(self):
        return "<MetaData>"