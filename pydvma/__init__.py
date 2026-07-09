from .options import MySettings, Output_Signal_Settings ,set_plot_colours
from .file import load_data, save_data, save_fig, export_to_matlab_jwlogger, export_to_matlab, export_to_csv, import_from_matlab_jwlogger
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
from .analysis import calculate_cwt, calculate_damping_from_cwt, calculate_damping_by_band
from .streams import Recorder, Recorder_NI, start_stream, REC, setup_output_NI, setup_output_soundcard, list_available_devices, get_devices_NI, get_devices_soundcard
from ._ni_device_specs import suggest_ni_settings, get_device_info
from .modal import modal_fit_single_channel, modal_fit_all_channels
# import faulthandler
# faulthandler.enable()


# `pydvma.plotting` pulls matplotlib.pyplot (~0.3 s at import time on a
# Mac; plotting is Qt-free since the web-UI Stage 1 work). CLI /
# scripted / test users rarely touch PlotData, so defer that name to
# first attribute access via the Python 3.7+ module-level __getattr__
# hook.
_LAZY_NAMES = {
    'PlotData': '.plotting',
    # `serve` is the whole submodule (the local acquisition bridge),
    # not a class inside one — deferred so `import pydvma` never pulls
    # the optional `websockets` dependency.
    'serve': '.serve',
}

# Friendly-error hints for lazy modules whose optional deps may be
# missing: {module: (human-readable package list, extras name)}.
_LAZY_EXTRAS = {
    '.serve': ('websockets', 'serve'),
}

# Names retired when the Qt logger was removed after the web logger
# reached full parity (the last version with Qt is the `qt-final` git
# tag). They stay in the package namespace only as *tombstones*: an
# import of `pydvma` is unaffected (clean, Qt-free), but a returning
# labsheet or notebook doing `dvma.Logger(settings)` gets an
# actionable error naming the replacement rather than a bare
# "module 'pydvma' has no attribute 'Logger'". Access raises
# AttributeError (the natural "this attribute is gone" signal, so
# `hasattr(dvma, 'Logger')` correctly reports False).
_REMOVED_NAMES = ('Logger', 'Oscilloscope')

_REMOVED_MESSAGE = (
    "'pydvma.{name}' was removed. The Qt logger was retired after the "
    "web logger reached full parity. Use the web logger:\n"
    "    pip install pydvma[serve] && pydvma-serve --open\n"
    "(docs: https://torebutlin.github.io/pydvma/web-logger/).\n"
    "To run the old Qt GUI, check out the 'qt-final' git tag."
)


def __getattr__(name):
    if name in _REMOVED_NAMES:
        raise AttributeError(_REMOVED_MESSAGE.format(name=name))
    mod_name = _LAZY_NAMES.get(name)
    if mod_name is not None:
        import importlib
        try:
            mod = importlib.import_module(mod_name, __name__)
        except ImportError as e:
            extras = _LAZY_EXTRAS.get(mod_name)
            if extras is None:
                raise
            packages, extra = extras
            raise ImportError(
                'pydvma.{} needs optional dependencies ({}). Install '
                'them with: pip install pydvma[{}]. Original error: {}'
                .format(name, packages, extra, e)
            ) from e
        # Submodule entries (name == module basename) resolve to the
        # module itself; class entries resolve to the named attribute.
        if mod_name.lstrip('.') == name:
            return mod
        return getattr(mod, name)
    raise AttributeError(
        'module {!r} has no attribute {!r}'.format(__name__, name)
    )


def __dir__():
    return sorted(set(globals()) | _LAZY_NAMES.keys())
