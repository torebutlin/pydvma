from .gui import Logger, Oscilloscope
from .options import MySettings, Output_Signal_Settings ,set_plot_colours
from .file import load_data, save_data, save_fig, export_to_matlab_jwlogger, export_to_matlab, export_to_csv, import_from_matlab_jwlogger
# from .oscilloscope import Oscilloscope
from .acquisition import log_data, output_signal, signal_generator, stream_snapshot
from .datastructure import DataSet, TimeData, FreqData, CrossSpecData, TfData, SonoData, MetaData, ModalData, update_dataset
from .testdata import create_test_impulse_data, create_test_impulse_ensemble, create_test_noise_data, create_test_impulse_data_nonlinear_v1, create_test_impulse_data_nonlinear_v2, create_test_impulse_data_multi_harmonics
from .plotting import PlotData
from .analysis import calculate_fft, calculate_cross_spectrum_matrix, calculate_cross_spectra_averaged, clean_impulse
from .analysis import calculate_tf, calculate_tf_averaged, multiply_by_power_of_iw, best_match, calculate_sonogram, calculate_damping_from_sono
from .streams import Recorder, Recorder_NI, start_stream, REC, setup_output_NI, setup_output_soundcard, list_available_devices, get_devices_NI, get_devices_soundcard
from .modal import modal_fit_single_channel, modal_fit_all_channels
# import faulthandler
# faulthandler.enable()
# from .gui_tk_test import Logger

