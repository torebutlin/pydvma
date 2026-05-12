from .options import MySettings, Output_Signal_Settings ,set_plot_colours
from .file import load_data, save_data, save_fig, export_to_matlab_jwlogger, export_to_matlab, export_to_csv, import_from_matlab_jwlogger
# from .oscilloscope import Oscilloscope
from .acquisition import log_data, output_signal, signal_generator, stream_snapshot
from .datastructure import (
    DataSet,
    TimeData,
    TimeDataList,
    FreqData,
    FreqDataList,
    CrossSpecData,
    CrossSpecDataList,
    TfData,
    TfDataList,
    SonoData,
    SonoDataList,
    MetaData,
    MetaDataList,
    ModalData,
    ModalDataList,
    update_dataset,
)
from .testdata import create_test_impulse_data, create_test_impulse_ensemble, create_test_noise_data, create_test_impulse_data_nonlinear_v1, create_test_impulse_data_nonlinear_v2, create_test_impulse_data_multi_harmonics
from .analysis import calculate_fft, calculate_cross_spectrum_matrix, calculate_cross_spectra_averaged, clean_impulse
from .analysis import calculate_tf, calculate_tf_averaged, multiply_by_power_of_iw, best_match, calculate_sonogram, calculate_damping_from_sono
from .streams import Recorder, Recorder_NI, start_stream, REC, setup_output_NI, setup_output_soundcard, list_available_devices, get_devices_NI, get_devices_soundcard
from ._ni_device_specs import suggest_ni_settings, get_device_info
from .modal import modal_fit_single_channel, modal_fit_all_channels
# import faulthandler
# faulthandler.enable()


# `pydvma.gui` and `pydvma.plotting` together pull qtpy + pyqtgraph +
# the matplotlib Qt5Agg backend, which cost ~0.7 s at import time on a
# Mac. CLI / scripted / test users never touch Logger, Oscilloscope, or
# PlotData, so defer those names to first attribute access via the
# Python 3.7+ module-level __getattr__ hook.
_LAZY_NAMES = {
    'Logger': '.gui',
    'Oscilloscope': '.gui',
    'PlotData': '.plotting',
}


def __getattr__(name):
    mod_name = _LAZY_NAMES.get(name)
    if mod_name is not None:
        import importlib
        mod = importlib.import_module(mod_name, __name__)
        return getattr(mod, name)
    raise AttributeError(
        'module {!r} has no attribute {!r}'.format(__name__, name)
    )


def __dir__():
    return sorted(set(globals()) | _LAZY_NAMES.keys())
