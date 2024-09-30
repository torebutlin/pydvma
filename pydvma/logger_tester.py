#%% logger tester
import pydvma as ma
import numpy as np
import matplotlib.pyplot as plt

%matplotlib qt

#%% create logger
settings = ma.MySettings(fs=44100,
                       channels=1,
                       stored_time=3,
                       device_driver='soundcard',
                       output_device_driver='soundcard',
                       output_channels=2,
                       output_fs=44100,
                       use_output_as_ch0=True)
# %%
t,y = ma.signal_generator(settings,sig='gaussian',T=3,amplitude=0.1,f=[100,300],selected_channels='all')
d = ma.log_data(settings,output=y)
#%%
ax = d.plot_time_data()
# %%
output_signal_settings = ma.Output_Signal_Settings(type='gaussian',amp=0.1,f1=100,f2=300)
logger = ma.Logger(settings,output_signal_settings=output_signal_settings)

# %%
