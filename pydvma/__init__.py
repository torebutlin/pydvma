from .settings import mySettings
from .file import read_data
#from .oscilloscope import view_oscilloscope
from .oscilloscope import oscilloscope, recorder
from .logdata import dataSet, timeData, freqData, tfData, sonoData, metaData
from .plotting import plotdata
from .analysis import convert_to_frequency

#from .logdata import get_oscilloscope_data

__all__ = ['setup','file']
