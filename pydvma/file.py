# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 14:32:35 2018

@author: tb267
"""

import datetime
import io as io_text
import os.path
import re
import uuid
import warnings
import zipfile
import numpy as np
import scipy.io as io
from scipy import signal
from . import _exchange
from . import container
from . import datastructure
from . import options


def _resolve_filename(parent, filename, func, example):
    """The filename a file function was given, positionally or by keyword.

    Every function here takes a ``parent`` BEFORE ``filename``: the Qt
    dialog parent of the removed Qt logger. So ``load_data('x.dvma')``
    binds the path to ``parent``, and a str or os.PathLike ``parent`` with
    no ``filename`` is taken as the filename. Any other ``parent`` is
    ignored with a DeprecationWarning (the parameter goes in 3.0), since
    pydvma no longer opens a file dialog. A PathLike filename comes back
    as str, because the callers use str methods.

    Args:
        parent: The function's ``parent`` argument.
        filename: The function's ``filename`` argument.
        func (str): The function's name, for the messages.
        example (str): A call to show when the filename is missing.

    Returns the filename as a str.

    Raises:
        TypeError: If no filename was given either way.
    """
    if filename is None and isinstance(parent, (str, os.PathLike)):
        parent, filename = None, parent
    if parent is not None:
        warnings.warn(
            '{}(): `parent` is ignored and will be removed in pydvma 3.0; '
            'pydvma no longer opens a file dialog.'.format(func),
            DeprecationWarning, stacklevel=3)
    if filename is None:
        raise TypeError(
            '{}() needs a filename, e.g. {}. pydvma no longer opens a file '
            'dialog.'.format(func, example))
    if isinstance(filename, os.PathLike):
        filename = os.fspath(filename)
    return filename


_OLD_CSV_EXPORT_LINE = '# pydvma export: RAW data'
_OLD_EXPORT_MESSAGE = (
    "%s was exported by pydvma 2.6 or earlier, whose %s export could not be "
    "read back (every set on one axis, with no record of what the columns "
    "were). Load the .dvma it was exported from, or export it again with "
    "this pydvma.")


def _first_line(filename):
    """The first line of `filename` as text (BOM dropped), from at most 256
    bytes; '' for an empty or binary file."""
    with open(filename, 'rb') as fh:
        head = fh.read(256).decode('utf-8-sig', errors='replace')
    return head.splitlines()[0] if head else ''


def load_data(parent=None, filename=None):
    '''
    Loads a dataset from `filename`.

    The filename can be given positionally, ``load_data('name.dvma')``,
    or as ``filename=``, and is required: there is no file dialog.

    Detection is by content for ``.dvma`` (zip magic bytes) and CSV (the
    first line names the format); ``.mat`` and legacy ``.npy`` fall back
    to extension:

    - ``.dvma`` container files (zip magic bytes) — the default
      format since 1.5.0; safe, pickle-free (see `container`).
    - legacy ``.npy`` pickle saves from pydvma <= 1.4.0 — supported
      forever. **Trust model:** the legacy path uses
      ``np.load(allow_pickle=True)``, and unpickling can execute
      arbitrary code, so only open legacy .npy files you or your lab
      created. `.dvma` files do not have this caveat.
    - pydvma's own CSV and MATLAB exports (`export_to_csv`,
      `export_to_matlab`, and the web app's Export CSV / Export Matlab):
      they hold what a .dvma holds and load back exactly. Exports from
      pydvma 2.6 and earlier could not be read back and raise ValueError.
    - ``.mat`` files from Jim Woodhouse's MATLAB logger, via
      `import_from_matlab_jwlogger`.
    - the CSV that the Vibration Apps' Transfer function app saves
      (first line names ``vibration-apps-tf-csv``), via
      `import_from_vibration_apps_csv`. Any other ``.csv`` raises
      ValueError.

    Args:
       parent (optional): Deprecated and ignored, and going in pydvma
           3.0 (it was the Qt file dialog's parent). A str or path here
           is taken as the filename.
       filename (str or os.PathLike): File to load, given positionally or
           as ``filename=``.

    Returns:
       dataset (DataSet or None): The loaded data, or None if the file
           is none of the above and its extension is not .csv.

    Raises:
       FileNotFoundError: If `filename` does not exist.
       ValueError: If a ``.dvma`` file is not a valid container, a
           ``.mat`` file is neither a pydvma export nor a JW-logger file,
           a ``.csv`` file is neither a pydvma export nor a Vibration Apps
           CSV this version reads, or an export was changed after it was
           written or comes from pydvma 2.6 or earlier.
       TypeError: If no filename is given.
    '''
    filename = _resolve_filename(parent, filename, 'load_data',
                                 "load_data('data.dvma')")
    if not os.path.isfile(filename):
        raise FileNotFoundError(
            'No such data file: {!r}'.format(filename))

    if zipfile.is_zipfile(filename):
        return container.load(filename)
    first = _first_line(filename)
    name = os.path.basename(filename)
    if _exchange.is_pydvma_csv_line(first):
        with open(filename, encoding='utf-8-sig', newline='') as fh:
            dataset = _exchange.dataset_from_csv_text(fh.read(), name)
    elif _is_vibration_apps_csv(filename):
        dataset = import_from_vibration_apps_csv(filename=filename)
    elif filename.lower().endswith('.mat'):
        d = io.loadmat(filename, simplify_cells=True)
        if _exchange.is_pydvma_mat(d):
            dataset = _exchange.dataset_from_mat_dict(d, name)
        else:
            dataset = import_from_matlab_jwlogger(filename=filename)
    elif filename.lower().endswith('.npy'):
        d = np.load(filename, allow_pickle=True, fix_imports=True)
        dataset = d[0]
    elif filename.lower().endswith('.dvma'):
        raise ValueError(
            '{!r} has the .dvma extension but is not a valid container '
            '— empty, truncated, or corrupted?'.format(filename))
    elif filename.lower().endswith('.csv'):
        if first.startswith(_OLD_CSV_EXPORT_LINE):
            raise ValueError(_OLD_EXPORT_MESSAGE % (name, 'CSV'))
        raise ValueError(
            "%s is not a CSV pydvma can load. load_data reads pydvma's own "
            "CSV exports (first line '# pydvma dataset (pydvma-csv 1)') and "
            "the Vibration Apps' Transfer function CSV (first line naming "
            "'vibration-apps-tf-csv')." % name)
    else:
        print('Expecting file to be .dvma, .npy, .mat or .csv')
        return None

    return dataset


def save_data(dataset, parent=None, filename=None, overwrite_without_prompt=False, sets=None):
    '''
    Saves a DataSet to 'filename.dvma' (the .dvma container format, a zip
    of manifest.json + pickle-free .npy arrays; see `container`).

    The filename can be given positionally, ``save_data(dataset,
    'name.dvma')``, or as ``filename=``; ``.dvma`` is added when it ends
    in neither ``.dvma`` nor ``.npy``. If that file already exists you
    are asked at the terminal whether to overwrite it, unless
    `overwrite_without_prompt` is True. The filename is required: there
    is no file dialog.

    Legacy escape hatch: an explicit filename ending in ``.npy``
    writes the pre-1.5.0 pickle format instead, for workflows that
    still need it. New saves should prefer .dvma — it is safe to
    share (loading executes no code) and readable outside Python.

    Args:
       dataset (DataSet): An object of the class DataSet
       parent (optional): Deprecated and ignored, and going in pydvma
           3.0 (it was the Qt file dialog's parent). A str or path here
           is taken as the filename.
       filename (str or os.PathLike): Output filename, given positionally or
           as ``filename=``.
       overwrite_without_prompt (bool, optional): If True, overwrite an
           existing file without asking.
       sets (int or Iterable[int], optional): If given, writes
           ``dataset.subset(sets)`` instead of the whole dataset — the
           notebook counterpart of the web app's Save "Choose sets…"
           picker (see `datastructure.DataSet.subset` for the exact
           inclusion rule). `None` (the default) writes `dataset`
           unchanged.

    Returns:
       filename (str or None): The file written, or None if the
           overwrite was declined.

    Raises:
       TypeError: If no filename is given.
    '''
    filename = _resolve_filename(parent, filename, 'save_data',
                                 "save_data(dataset, 'data.dvma')")
    if sets is not None:
        dataset = dataset.subset(sets)

    # Normalise the extension FIRST, so the overwrite prompt below checks
    # the same filename we're about to write.
    if not filename.endswith('.npy') and not filename.endswith('.dvma'):
        filename += '.dvma'

    if os.path.isfile(filename) and not overwrite_without_prompt:
        answer = input('File %r already exists. Overwrite? [y/n]: ' % filename)
        if answer != 'y':
            print('Save cancelled')
            return None
        print('Will overwrite existing file')

    if filename.endswith('.npy'):
        # legacy pickle format, kept for explicit opt-in only
        d = np.array([dataset])
        np.save(filename, d)
        print("Data saved (legacy pickle format) as %s" % filename)
        return filename

    container.save(dataset, filename)
    print("Data saved as %s" % filename)
    return filename



def save_fig(plot, parent=None, figsize=None, filename=None, overwrite_without_prompt=False):
    '''
    Saves a figure as both 'filename.png' and 'filename.pdf'.

    Any extension on the filename is replaced, so both files are always
    written. The filename can be given positionally, ``save_fig(plot,
    'name')``, or as ``filename=``, and is required: there is no file
    dialog.

    Args:
       plot (PlotData or Figure): A PlotData object or matplotlib Figure object
       parent (optional): Deprecated and ignored, and going in pydvma
           3.0 (it was the Qt file dialog's parent). A str or path here
           is taken as the filename.
       figsize (tuple, optional): Size in inches for the saved files; the
           figure is restored to its own size afterwards.
       filename (str or os.PathLike): Output filename, given positionally or
           as ``filename=``.
       overwrite_without_prompt (bool, optional): If True, overwrite without asking

    Returns:
       filename (str or None): The PDF written (the PNG is beside it), or
           None if the overwrite was declined.

    Raises:
       TypeError: If no filename is given.
    '''
    filename = _resolve_filename(parent, filename, 'save_fig',
                                 "save_fig(plot, 'figure')")
    if plot.__class__.__name__ == 'PlotData':
        fig = plot.fig
    elif plot.__class__.__name__ == 'Figure':
        fig = plot

    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    if os.path.isfile(filename) and not overwrite_without_prompt:
        answer = input('File %r already exists. Overwrite? [y/n]: ' % filename)
        if answer != 'y':
            print('Save cancelled')
            return None
        print('Will overwrite existing file')

    # Set figsize...
    original_size = fig.get_size_inches()
    if figsize is not None:
        fig.set_size_inches(figsize,forward=False)
        
    # Make sure it ends with .png then .pdf
    filename = os.path.splitext(filename)[0]
    if not filename.endswith('.png'):
        filename += '.png'
    fig.savefig(filename, dpi=300)
    print("Figure saved as %s" % filename)
    
    filename = os.path.splitext(filename)[0]
    if not filename.endswith('.pdf'):
        filename += '.pdf'
    fig.savefig(filename, dpi=300)
    print("Figure saved as %s" % filename)

    # return to original size
    fig.set_size_inches(original_size,forward=False)
    
    
    return filename



#%% EXPORT: SHARED HELPERS
_DATA_LIST_CLASSES = ('TimeDataList', 'FreqDataList', 'CrossSpecDataList',
                      'TfDataList', 'ModalDataList', 'SonoDataList',
                      'MetaDataList')


def _as_dataset(data, func):
    """`data` as a DataSet: a DataSet as it is, a data list's items in a new
    one. Raises TypeError for anything else, ValueError when it is empty."""
    if isinstance(data, datastructure.DataSet):
        dataset = data
    elif data.__class__.__name__ in _DATA_LIST_CLASSES:
        dataset = datastructure.DataSet()
        for item in data:
            dataset.add_to_dataset(item)
    else:
        raise TypeError(
            '{} needs a DataSet or a data list (TimeDataList, TfDataList, '
            '...); got {}.'.format(func, type(data).__name__))
    lists = (dataset.time_data_list, dataset.freq_data_list,
             dataset.cross_spec_data_list, dataset.tf_data_list,
             dataset.modal_data_list, dataset.sono_data_list,
             dataset.meta_data_list)
    if not any(len(lst) for lst in lists):
        raise ValueError('{}: there is nothing to export (no data).'.format(func))
    return dataset


def _export_target(filename, ext, overwrite_without_prompt):
    """`filename` with `ext` added if missing, or None if the user declined
    to overwrite an existing file."""
    if not filename.endswith(ext):
        filename += ext
    if os.path.isfile(filename) and not overwrite_without_prompt:
        answer = input('File %r already exists. Overwrite? [y/n]: ' % filename)
        if answer != 'y':
            print('Save cancelled')
            return None
        print('Will overwrite existing file')
    return filename


#%% EXPORT TO MATLAB
def export_to_matlab(dataset, parent=None, filename=None, overwrite_without_prompt=False):
    '''
    Exports data to a MATLAB .mat file that `load_data` reads back.

    The file holds exactly what a `save_data` .dvma holds (format
    ``pydvma-mat 1``), laid out for MATLAB:

    - ``pydvma_items``: a cell array with one struct per item, in order:
      ``kind``, ``test_name``, ``units``, ``fs``, ``timestamp`` (ISO text),
      ``channel_cal_factors``, and each array under its own name at its
      exact shape (``time_axis``, ``time_data``, ``freq_axis``, ``tf_data``,
      ``tf_coherence``, ``Pxy``, ``sono_data``, ``M``, ...). In MATLAB,
      ``d = load('x.mat'); d.pydvma_items{2}.tf_data``.
    - ``pydvma_manifest``: every item's metadata and settings as JSON text
      (``jsondecode(d.pydvma_manifest)`` in MATLAB).
    - ``pydvma_format``: ``'pydvma-mat 1'``.

    Values are RAW (volts for a capture): multiply by the item's
    ``channel_cal_factors`` for engineering units. Each measurement keeps
    its own axis; nothing is interpolated. (pydvma 2.6 and earlier wrote
    ``time_data_all`` / ``freq_data_all`` / ``tf_data_all`` on one common
    grid instead, and could not read the file back.) The filename can be
    given positionally, ``export_to_matlab(dataset, 'name.mat')``, or as
    ``filename=``; ``.mat`` is added if missing. The filename is required:
    there is no file dialog.

    Args:
       dataset (DataSet or data list): The data: a whole DataSet, or one
           data list (``dataset.tf_data_list``, ...).
       parent (optional): Deprecated and ignored, and going in pydvma
           3.0 (it was the Qt file dialog's parent). A str or path here
           is taken as the filename.
       filename (str or os.PathLike): Output filename, given positionally or
           as ``filename=``.
       overwrite_without_prompt (bool, optional): If True, overwrite without asking

    Returns:
       filename (str or None): The file written, or None if the
           overwrite was declined.

    Raises:
       TypeError: If no filename is given, or `dataset` is neither a
           DataSet nor a data list.
       ValueError: If there is no data to export.
    '''
    filename = _resolve_filename(parent, filename, 'export_to_matlab',
                                 "export_to_matlab(dataset, 'data.mat')")
    variables = _exchange.dataset_to_mat_dict(_as_dataset(dataset, 'export_to_matlab()'))
    filename = _export_target(filename, '.mat', overwrite_without_prompt)
    if filename is None:
        return None
    io.savemat(filename, variables, oned_as='column', do_compression=True)
    print("Data saved as %s" % filename)
    return filename



#%% EXPORT TO MATLAB JWLOGGER
def export_to_matlab_jwlogger(dataset, parent=None, filename=None, overwrite_without_prompt=False):
    '''
    Exports a DataSet to 'filename.mat' in the JW-logger format.

    Saved file is compatible with Jim Woodhouse logger file format, and
    `import_from_matlab_jwlogger` reads it back. The filename can be
    given positionally, ``export_to_matlab_jwlogger(dataset, 'name.mat')``,
    or as ``filename=``; ``.mat`` is added if missing. The filename is
    required: there is no file dialog.

    The file holds up to two blocks, each resampled onto one grid:

    - TIME: every channel of every TimeData as a column of ``indata``, at
      the highest sample rate, zero-padded after a shorter capture; with
      ``buflen`` (the row count) and ``tsmax``, the largest absolute
      value, which the logger uses as its time plot's y-limit.
    - SPECTRAL: the transfer functions if there are any (``tfun`` = 1,
      coherence not exported), otherwise the FFTs (``tfun`` = 0), as the
      columns of ``yspec``, with ``npts`` (the FFT length). The logger
      stores no frequency axis: it is ``rfftfreq(npts, 1/freq)``, at the
      finest spacing of the spectra, padded with 1 above a spectrum's
      band. Sonograms and cross-spectra are not exported.

    ``freq`` is the sample rate, and one value serves both blocks, as in
    the logger itself. With time data it is the time data's rate and the
    spectra are laid on that rate's grid, so spectral data above half the
    time data's rate is left out, with a warning. Without time data it is
    the spectra's own sample rate. ``dt2`` holds the column counts
    ``[n_time, n_spectral, 0]``. Values are the raw stored numbers, and
    unlike `export_to_matlab` no calibration factors are written: the
    logger's layout has no variable for them.

    Args:
       dataset (DataSet): An object of the class DataSet
       parent (optional): Deprecated and ignored, and going in pydvma
           3.0 (it was the Qt file dialog's parent). A str or path here
           is taken as the filename.
       filename (str or os.PathLike): Output filename, given positionally or
           as ``filename=``.
       overwrite_without_prompt (bool, optional): If True, overwrite without asking

    Returns:
       filename (str or None): The file written, or None if the
           overwrite was declined.

    Raises:
       TypeError: If no filename is given.
    '''
    filename = _resolve_filename(parent, filename, 'export_to_matlab_jwlogger',
                                 "export_to_matlab_jwlogger(dataset, 'data.mat')")

    # convert data into dictionary ready for Matlab
    data_jwlogger = dict()
    
    #%% TIME
    if len(dataset.time_data_list) > 0:
        T=0
        fs=0
        n_time=0
        for time_data in dataset.time_data_list:
            N = len(time_data.time_axis)
            T = np.max([time_data.time_axis[-1]*N/(N-1),T])
            fs = np.max([1/np.mean(np.diff(time_data.time_axis)),fs])
            # COLUMN COUNT COMES FROM THE ARRAY, never settings.channels:
            # `use_output_as_ch0` PREPENDS the drive column to `time_data`
            # without bumping `settings.channels`, so trusting the setting
            # silently dropped the last measured channel from the export.
            n_time += time_data.time_data.shape[1]
        
        fs = _clean_rate(fs)
        # A sample COUNT, not np.arange(0, T, 1/fs): that float stop
        # sometimes admits one extra sample past the end.
        t = np.arange(int(round(T*fs))) / fs
        time_data_all = np.zeros((len(t),n_time))
        counter = -1
        for time_data in dataset.time_data_list:
            for i in range(time_data.time_data.shape[1]):
                counter += 1
                time_data_all[:,counter] = _interp_onto(t,time_data.time_axis,time_data.time_data[:,i],0)

        data_jwlogger['buflen'] = float(np.size(t))
        data_jwlogger['indata'] = time_data_all
        # The logger's time-plot y-limit, +/-tsmax (tsinit.m), which its own
        # save path sets to max|indata| (tsmenu.m) - not a time. Kept
        # nonzero: MATLAB rejects a zero-height axis.
        data_jwlogger['tsmax'] = float(np.max(np.abs(time_data_all))) or 1.0
        data_jwlogger['freq'] = float(fs)
        fs_time = fs
    else:
        n_time = 0
        fs_time = None


    #%% SPECTRA: TF (without its coherence) if any, else FFT
    if len(dataset.tf_data_list) > 0:
        spec_list, attr, tfun = dataset.tf_data_list, 'tf_data', 1
    else:
        spec_list, attr, tfun = dataset.freq_data_list, 'freq_data', 0
    if len(spec_list) > 0:
        yspec, npts, fs_spec = _jwlogger_yspec(spec_list, attr, fs_time)
        data_jwlogger['freq'] = float(fs_spec)
        data_jwlogger['npts'] = float(npts)
        data_jwlogger['yspec'] = yspec
        data_jwlogger['tfun'] = float(tfun)
        N = yspec.shape[1]
    else:
        N = 0

    data_jwlogger['dt2'] = np.array([n_time,N,0],dtype=float)
    data_jwlogger['dtype'] = np.array([n_time,N,0],dtype=float)
    

    # SAVE

    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    if os.path.isfile(filename) and not overwrite_without_prompt:
        answer = input('File %r already exists. Overwrite? [y/n]: ' % filename)
        if answer != 'y':
            print('Save cancelled')
            return None
        print('Will overwrite existing file')
        
    # Make sure it ends with .npy
    if not filename.endswith('.mat'):
        filename += '.mat'
        
    # Actually save!
    io.savemat(filename,data_jwlogger)
    print("Data saved as %s" % filename)

    return filename


def _jwlogger_yspec(spec_list, attr, fs=None):
    '''
    Lay spectra on the JW-logger frequency grid, one column per channel.

    A JW-logger file stores no frequency axis: the logger (and
    `import_from_matlab_jwlogger`) rebuilds it as
    ``rfftfreq(npts, 1/freq)``, so this picks ``npts`` for the given rate
    and interpolates every channel onto that grid. The spacing is the
    finest of the spectra's. Above a spectrum's own band the column is
    padded with 1, and the DC row copies the first positive bin, as the
    logger's own writer does.

    Args:
       spec_list (list): FreqData or TfData objects.
       attr (str): The data attribute, ``'freq_data'`` or ``'tf_data'``.
       fs (float, optional): The file's sample rate ``freq``, set by its
           time data. If None it is the spectra's own sample rate (the
           highest ``settings.fs``) when that reproduces their frequency
           grid exactly, and otherwise twice the highest frequency, which
           covers every spectrum. Spectra above ``fs/2`` are left out,
           with a warning.

    Returns:
       spectra (tuple): ``(yspec, npts, freq)`` — the complex
           ``(npts//2 + 1, n_columns)`` array, the FFT length and the
           sample rate.
    '''
    df = min(np.mean(np.diff(s.freq_axis)) for s in spec_list)
    fmax = max(s.freq_axis[-1] for s in spec_list)
    if fs is None:
        # `freq` is the SAMPLE RATE. 2*fmax equals it only for an even FFT
        # length: an odd-length rfftfreq(N, 1/fs) stops at fs*(N-1)/(2N).
        fs = _clean_rate(2 * fmax)
        declared = max(getattr(s.settings, 'fs', 0) or 0 for s in spec_list)
        if declared > 0:
            n_declared = int(round(declared / df))
            if (abs(declared / n_declared - df) <= 1e-9 * df
                    and fmax <= declared / 2 * (1 + 1e-9)):
                fs = float(declared)
    npts = int(round(fs / df))
    f = np.fft.rfftfreq(npts, 1 / fs)
    if fmax > f[-1] + df / 2:
        warnings.warn(
            "JW-logger export: the time data's sample rate (%g Hz) is the "
            "file's 'freq', so spectral data above %g Hz is not exported."
            % (fs, f[-1]), stacklevel=3)

    n_columns = sum(np.shape(getattr(s, attr))[1] for s in spec_list)
    yspec = np.zeros((len(f), n_columns), dtype=complex)
    counter = -1
    for s in spec_list:
        data = getattr(s, attr)
        for i in range(np.shape(data)[1]):
            counter += 1
            yspec[:,counter] = _interp_onto(f,s.freq_axis,data[:,i],1)
            yspec[0,counter] = yspec[1,counter] # to match equivalent tweak in JW Logger for handling DC singularities
            zero_test = yspec[:,counter] == 0
            yspec[zero_test,counter] = np.min(np.abs(yspec[:,counter])) # handle zeros
    return yspec, npts, fs


def _clean_rate(fs):
    '''
    Strip float noise from a sample rate estimated from an axis.

    ``1/mean(diff(t))`` or ``2*f[-1]`` gives 8532.999999999998 for an
    8533 Hz axis, which `options.MySettings` (it stores ``int(fs)``)
    truncates to 8532. The estimate is good to about 13 significant
    figures, so rounding to 12 recovers the rate.

    Args:
       fs (float): The estimated sample rate in Hz.

    Returns:
       fs (float): The rate, rounded to 12 significant figures.
    '''
    return float('%.12g' % fs)


def _interp_onto(grid, axis, values, pad):
    '''
    Interpolate samples onto a uniform grid, padding beyond their end.

    A grid point past the end of ``axis`` by float rounding alone (within
    a millionth of a grid step) counts as the end point. Without that, a
    grid that matches the axis loses its last sample to the pad value.

    Args:
       grid (np.ndarray): Uniform, increasing points to evaluate at.
       axis (np.ndarray): Increasing points the values are sampled at.
       values (np.ndarray): The samples, real or complex.
       pad (float): The value beyond the end of ``axis``.

    Returns:
       resampled (np.ndarray): ``values`` at each ``grid`` point.
    '''
    step = grid[1] - grid[0] if len(grid) > 1 else 0.0
    rounding = (grid > axis[-1]) & (grid <= axis[-1] + 1e-6 * step)
    return np.interp(np.where(rounding, axis[-1], grid), axis, values,
                     right=pad)


#%% CALIBRATION FACTOR TEXT
def format_cal_factor(value):
    """Render one calibration factor as text, as ``'%.12g'``.

    The form pydvma's CSV table headings use for an item's calibration
    (the exact factors travel in the file's manifest). ``%.12g`` is short
    enough to read, round-trips every realistic factor, and its C
    semantics (exponential below 1e-4 or at/above 12 significant digits,
    trailing zeros stripped) are pinned by the known-answer vectors in
    ``CAL_FACTOR_FORMAT_VECTORS``. Public since 2.5.0, when the web app's
    CSV writer had a JavaScript twin of it; that writer is gone.

    A non-finite factor renders as ``'1'``: the identity, matching how every
    consumer already treats an unusable factor, rather than writing a ``nan``
    into a header a script may parse.
    """
    v = float(value)
    if not np.isfinite(v):
        return '1'
    return '{:.12g}'.format(v)


#: Known-answer vectors pinning `format_cal_factor`'s output.
CAL_FACTOR_FORMAT_VECTORS = (
    (1.0, '1'),
    (10.0, '10'),
    (0.5, '0.5'),
    (-0.5, '-0.5'),
    (1000.0, '1000'),
    (0.001, '0.001'),
    (1e-05, '1e-05'),
    (1.5e-07, '1.5e-07'),
    (123456789012.0, '123456789012'),
    (1234567890123.0, '1.23456789012e+12'),
    (1.0 / 3.0, '0.333333333333'),
    (2.0 / 3.0, '0.666666666667'),
    (0.0001, '0.0001'),
    (1e+16, '1e+16'),
)


#%% EXPORT TO CSV
def export_to_csv(data_list, parent=None, filename=None, overwrite_without_prompt=False):
    '''
    Exports data to one CSV file that `load_data` reads back.

    The file holds exactly what a `save_data` .dvma holds (format
    ``pydvma-csv 1``), laid out as tables a spreadsheet or pandas can read:

    - a few ``#`` lines saying what the file is, then every item's
      metadata and settings as JSON on one ``# manifest:`` line;
    - one table per item (and one of its own for an array that cannot
      share the item's rows, such as a sonogram's frequency axis): a
      ``# table`` heading line (kind, name, units, calibration), a line
      of column names, then the rows. The rows run
      along the item's axis, so a TF table reads ``freq_axis,
      tf_data[0].re, tf_data[0].im, tf_coherence[0]``; complex values are
      ``.re``/``.im`` column pairs; each measurement keeps its own length.

    Values are RAW (volts for a capture): multiply by the item's
    ``channel_cal_factors`` for engineering units. Numbers are written as
    the shortest text that reads back to the same value, so nothing is
    lost. To read one table with pandas, pass it the lines between its
    ``# table`` line and the next (``pd.read_csv(io.StringIO(...))``).
    (pydvma 2.6 and earlier wrote one kind per file on the first set's
    axis, which could not be read back.)

    The filename can be given positionally, ``export_to_csv(dataset,
    'name.csv')``, or as ``filename=``; ``.csv`` is added if missing. The
    filename is required: there is no file dialog.

    Args:
       data_list (DataSet or data list): The data: a whole DataSet, or one
           data list (``dataset.time_data_list``, ...).
       parent (optional): Deprecated and ignored, and going in pydvma
           3.0 (it was the Qt file dialog's parent). A str or path here
           is taken as the filename.
       filename (str or os.PathLike): Output filename, given positionally or
           as ``filename=``.
       overwrite_without_prompt (bool, optional): If True, overwrite without asking

    Returns:
       filename (str or None): The file written, or None if the
           overwrite was declined.

    Raises:
       TypeError: If no filename is given, or `data_list` is neither a
           DataSet nor a data list.
       ValueError: If there is no data to export.
    '''
    filename = _resolve_filename(parent, filename, 'export_to_csv',
                                 "export_to_csv(dataset, 'data.csv')")
    text = _exchange.dataset_to_csv_text(_as_dataset(data_list, 'export_to_csv()'))
    filename = _export_target(filename, '.csv', overwrite_without_prompt)
    if filename is None:
        return None
    with open(filename, 'w', encoding='utf-8', newline='') as fh:
        fh.write(text)
    print("Data saved as %s" % filename)
    return filename



#%% IMPORT FROM MATLAB JWLOGGER
# Variables only pydvma 2.6's (and earlier) `export_to_matlab` wrote: they
# mark one of its exports, which cannot be read back.
_PYDVMA_MATLAB_KEYS = ('time_data_all', 'freq_data_all', 'tf_data_all')


def _jw_scalar(d, key, meaning):
    '''
    Read one scalar variable of a loaded JW-logger .mat file.

    MATLAB saves a scalar as a (1, 1) array, so this unwraps it.

    Args:
       d (dict): The variables, as returned by `scipy.io.loadmat`.
       key (str): The variable's name.
       meaning (str): What the variable holds, for the error message.

    Returns:
       value (float): The scalar.

    Raises:
       ValueError: If the file has no such variable. pydvma 2.5.0 and
           earlier wrote JW-logger files without ``freq`` (time-only
           exports) or ``tfun`` (spectral exports), so such files exist.
    '''
    if key not in d:
        raise ValueError(
            "This JW-logger .mat file has no '%s' variable (%s), so it "
            "cannot be imported. Files written by export_to_matlab_jwlogger "
            "in pydvma 2.5.0 and earlier can lack 'freq' or 'tfun': export "
            "the data again, or add the variable to the file in MATLAB."
            % (key, meaning))
    return float(np.ravel(d[key])[0])


def import_from_matlab_jwlogger(filename=None):
    '''
    Imports a JW-logger .mat file (Jim Woodhouse's MATLAB data logger).

    Only JW-logger files can be imported here. pydvma's own MATLAB exports
    are refused with a ValueError saying to use `load_data` (which reads
    them; those from pydvma 2.6 and earlier cannot be read at all), as is
    any other .mat with neither of the logger's ``indata`` / ``yspec``
    variables. The filename is required: there is no file dialog.

    The conventions below were confirmed against the recovered MATLAB source
    ("Data logger V2.9a": ``specmenu.m`` save path, ``avtflogpars.m``
    averaged-TF computation, ``dospec.m``):

    - SPECTRAL files save ``yspec, dt2, npts, freq, tfun``. ``freq`` is
      the SAMPLE RATE, ``npts`` the FFT length, so ``yspec`` has
      ``npts/2 + 1`` rows on the one-sided axis ``rfftfreq(npts, 1/freq)``
      (df = freq/npts).
    - TIME files save ``indata, buflen, freq, dt2, tsmax`` — there is NO
      ``npts`` and no ``tfun`` (JW's guitar_string captures confirmed
      this; the old import assumed ``npts`` and raised KeyError). The
      time axis comes from ``indata``'s own length at fs = ``freq``;
      ``buflen`` duplicates that length and ``tsmax`` records the
      capture's scale (the data is already in physical units — do NOT
      rescale by it).
    - ``tfun`` selects spectrum (0) / transfer function (1).
    - ``dt2`` is the saved ``dtype`` vector ``[n_time_channels,
      n_yspec_columns, n_sonogram]`` — column COUNTS, not column types.
    - The averaged-TF logger writes ``yspec`` as INTERLEAVED pairs
      ``[H1, coh1, H2, coh2, ...]`` — each output channel's H1-estimator TF
      followed by its coherence (``avtflogpars.m``: ``thing(:,2k-1) =
      cross/autoin``; ``thing(:,2k) = |cross|^2/(autoin*autoout)``).
    - The save menu also allows ARBITRARY column subsets ("Channels to
      save": one / all / displayed / custom) and files can be composited by
      the Add-on-load path — so real archives also contain bare-H files
      (coherence stripped) and multi-instrument H collections.
    - The writer duplicates the first positive bin into the DC row
      (``yspec(1,:) = yspec(2,:)``), so the DC bin is cosmetic.

    Import behaviour for TF files: coherence columns are detected
    unambiguously (real-valued AND within [0, 1] — no measured complex FRF
    is both). The documented interleaved ``[H, coh, ...]`` layout is
    recognised and split with positional pairing; an equal split in any
    other order pairs by order of appearance; files with no coherence
    columns, or an ambiguous mix, import as before (every column a TF
    channel — nothing is dropped).

    Args:
       filename (str or os.PathLike): File to import, given positionally or
           as ``filename=``.

    Returns:
       dataset (DataSet): The imported data.

    Raises:
       ValueError: If the file is not a JW-logger .mat file, including a
           .mat written by `export_to_matlab`; if it lacks ``freq``, or
           has ``yspec`` without ``npts`` or ``tfun``; or if ``tfun`` is
           neither 0 nor 1.
       TypeError: If no filename is given.
    '''
    filename = _resolve_filename(None, filename, 'import_from_matlab_jwlogger',
                                 "import_from_matlab_jwlogger('capture.mat')")

    d = io.loadmat(filename)
    if 'indata' not in d and 'yspec' not in d:
        # Without these the branches below all skip and the result is an
        # EMPTY DataSet, silently. The browser's .mat import
        # (`engine.file_to_dvma`, via `load_data`) comes through here too.
        if _exchange.is_pydvma_mat(d):
            raise ValueError(
                "This .mat file is pydvma's own export (export_to_matlab), "
                "not a JW-logger file: load it with load_data.")
        if any(k in d for k in _PYDVMA_MATLAB_KEYS):
            raise ValueError(_OLD_EXPORT_MESSAGE % (
                os.path.basename(filename), 'MATLAB'))
        raise ValueError(
            "Not a JW-logger .mat file: it has no 'indata' (time) or "
            "'yspec' (spectrum or TF) variable. Only JW-logger .mat files "
            "can be imported here; load_data also reads pydvma's own "
            ".mat exports.")
    dataset = datastructure.DataSet()

    # Every axis is built from `freq` (the sample rate), and a spectrum's
    # from `npts` too, so a file without them cannot be imported.
    fs = _jw_scalar(d, 'freq', 'the sample rate')
    if 'yspec' in d:
        tfun = _jw_scalar(d, 'tfun', '0 = spectrum, 1 = transfer function')
        if tfun not in (0, 1):
            raise ValueError(
                "This JW-logger .mat file has tfun = %g; it must be 0 "
                "(spectrum) or 1 (transfer function)." % tfun)
        fa = np.fft.rfftfreq(int(_jw_scalar(d, 'npts', 'the FFT length')),
                             1/fs)

    #%% TIME
    if 'indata' in d:
        td = np.asarray(d['indata'], dtype=float)
        if td.ndim == 1:
            td = td[:, None]
        elif td.shape[0] == 1 and td.shape[1] > 1:
            td = td.T                       # row vector -> one column channel
        # Time files carry NO `npts` (that's the FFT length of the spectral
        # save path) — the record length is the data's own row count (the
        # saved `buflen` duplicates it). `tsmax` is the capture's scale
        # marker; `indata` is already in physical units, so it is not used.
        ta = np.arange(td.shape[0]) / fs
        settings = options.MySettings(channels=td.shape[1], fs=fs)

        time_data = datastructure.TimeData(ta,td,settings)
        time_data.timestamp = os.path.getmtime(filename)
        dataset.add_to_dataset(time_data)
    
    #%% FFT
    if ('yspec' in d) and (tfun == 0):
        fd = d['yspec']
        settings = options.MySettings(channels=np.size(fd,1),
                                      fs=fs)
        
        freq_data = datastructure.FreqData(fa,fd,settings)
        freq_data.timestamp = os.path.getmtime(filename)
        dataset.add_to_dataset(freq_data)

    
    #%% TF
    if ('yspec' in d) and (tfun == 1):
        tf = d['yspec']

        # Split coherence traces from the TF columns (see docstring). This
        # matters beyond labelling: a coherence trace imported as a TF
        # channel POISONS any multi-channel modal fit — the fitter chases a
        # bounded real curve and rails fn/zeta to the window edge (verified
        # on JW guitar admittance files). Detection: real-valued AND within
        # [0, 1]; a measured complex FRF never satisfies both across the
        # whole axis. Layouts, in order of preference:
        #   1. the DOCUMENTED averaged-TF layout [H1, coh1, H2, coh2, ...]
        #      (avtflogpars.m) — positional pairs;
        #   2. any other clean equal split — paired in column order;
        #   3. no coherence columns, or an ambiguous mix — historic
        #      all-columns-are-TF import, so no data is dropped.
        coherence = None
        ncols = np.size(tf, 1)
        col_is_coh = []
        for c in range(ncols):
            col = tf[:, c]
            scale = max(float(np.max(np.abs(col))), 1e-300)
            real_only = float(np.max(np.abs(np.imag(col)))) <= 1e-9 * scale
            bounded = (float(np.min(np.real(col))) >= -1e-6
                       and float(np.max(np.real(col))) <= 1 + 1e-6)
            col_is_coh.append(real_only and bounded)
        coh_idx = [c for c in range(ncols) if col_is_coh[c]]
        tf_idx = [c for c in range(ncols) if not col_is_coh[c]]
        interleaved = (
            ncols >= 2 and ncols % 2 == 0
            and all(not col_is_coh[c] for c in range(0, ncols, 2))
            and all(col_is_coh[c] for c in range(1, ncols, 2))
        )
        if interleaved:
            coherence = np.real(tf[:, 1::2])
            tf = tf[:, 0::2]
        elif coh_idx and tf_idx and len(coh_idx) == len(tf_idx):
            coherence = np.real(tf[:, coh_idx])
            tf = tf[:, tf_idx]

        settings = options.MySettings(channels=np.size(tf,1),
                                      fs=fs)

        tf_data = datastructure.TfData(fa,tf,coherence,settings)
        tf_data.timestamp = os.path.getmtime(filename)
        dataset.add_to_dataset(tf_data)

    return dataset

#%% IMPORT FROM THE VIBRATION APPS (TRANSFER FUNCTION CSV)
VIBRATION_APPS_CSV_FORMATS = ('vibration-apps-tf-csv 1', 'vibration-apps-tf-csv 2')
_VA_FORMAT_RE = re.compile(r'vibration-apps-tf-csv ([^\s)]+)')
_VA_MEASUREMENT_RE = re.compile(r'#\s*m(\d+)( notes)?:\s?(.*)$')
_VA_COLUMNS = ('measurement', 'f_Hz', 'H1_re', 'H1_im', 'coherence')
_VA_TIME_COLUMNS = ('measurement', 't_s', 'x', 'y')
_VA_TIME_SECTION = '\n# section: time\n'
_VA_WINDOWS = {'hann': 'hann', 'rect': 'boxcar'}


def _not_vibration_apps_csv(name):
    """The ValueError for a CSV that the Vibration Apps did not save."""
    return ValueError(
        "%s is not a CSV saved by the Vibration Apps' Transfer function "
        "app: its first line does not name the format "
        "'vibration-apps-tf-csv'. (load_data also reads pydvma's own CSV "
        "exports.)" % name)


def _is_vibration_apps_csv(filename):
    """True if `filename`'s first line names the Vibration Apps TF CSV format
    (any version, so that a newer one is refused with a reason, not as
    an unknown file)."""
    with open(filename, 'rb') as fh:
        head = fh.read(256).decode('utf-8-sig', errors='replace')
    first = head.splitlines()[0] if head else ''
    return first.startswith('#') and _VA_FORMAT_RE.search(first) is not None


def _va_num(text):
    """A header value as a float, or None if it is empty or not a number."""
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _va_timestamp(text):
    """The app's ISO 8601 UTC time as an aware datetime, or None."""
    try:
        t = datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo is not None else t.replace(tzinfo=datetime.timezone.utc)


def _va_stamp(item, t):
    """Give `item` the measurement time `t` and its local-time timestring."""
    item.timestamp = t
    lt = t.astimezone()
    item.timestring = '_%d_%d_%d_at_%d_%d_%d' % (
        lt.year, lt.month, lt.day, lt.hour, lt.minute, lt.second)


def _va_table(lines, name, need, what):
    """Column names (first line) and rows (the rest) of one CSV table, read
    by name: returns ``{column: array}`` for the `need` columns, empty
    fields as NaN."""
    names = [c.strip() for c in lines[0].split(',')] if lines else []
    missing = [c for c in need if c not in names]
    if missing:
        raise ValueError('%s has no %s column in its %s table, so it cannot '
                         'be imported.' % (name, ', '.join(missing), what))
    rows = [ln for ln in lines[1:] if ln.strip() and not ln.startswith('#')]
    if not rows:
        raise ValueError('%s has no %s rows.' % (name, what))
    try:
        data = np.atleast_2d(np.genfromtxt(rows, delimiter=',', dtype=float))
    except ValueError as e:
        raise ValueError('%s: the %s rows cannot be read (%s).'
                         % (name, what, e)) from e
    if data.shape[1] < len(names):
        raise ValueError('%s: its %s rows have %d columns but its column names '
                         'list %d; the file looks edited or cut short.'
                         % (name, what, data.shape[1], len(names)))
    return {c: data[:, i] for i, c in enumerate(names) if c}


def _va_time_table(text, name):
    """The time table (format 2) read in one pass: ``{column: array}``."""
    head, _, body = text.partition('\n')
    names = [c.strip() for c in head.split(',')]
    missing = [c for c in _VA_TIME_COLUMNS if c not in names]
    if missing:
        raise ValueError('%s has no %s column in its time table, so it cannot '
                         'be imported.' % (name, ', '.join(missing)))
    try:
        data = np.atleast_2d(np.loadtxt(io_text.StringIO(body), delimiter=',',
                                        usecols=[names.index(c) for c in _VA_TIME_COLUMNS],
                                        ndmin=2))
    except ValueError as e:
        raise ValueError('%s: the time rows cannot be read (%s).' % (name, e)) from e
    return dict(zip(_VA_TIME_COLUMNS, data.T))


def _va_enbw(md, fs):
    """Effective noise bandwidth (Hz) of the app's window for a measurement,
    or None when its window or frame length is not stated."""
    win = _VA_WINDOWS.get(md.get('window', ''))
    nperseg = _va_num(md.get('nperseg'))
    if win is None or not nperseg or not fs:
        return None
    w = signal.get_window(win, int(nperseg))
    return float(fs * np.sum(w ** 2) / np.sum(w) ** 2)


def _vibration_apps_dataset(text, name):
    """Parse the text of a Vibration Apps TF CSV into a DataSet.

    The body of `import_from_vibration_apps_csv`, which see; `name` is
    only used in error messages. The browser's import
    (`engine.file_to_dvma`, via `load_data`) comes through here too.
    """
    text = text.lstrip('﻿').replace('\r\n', '\n')
    first = text.partition('\n')[0]
    found = _VA_FORMAT_RE.search(first) if first.startswith('#') else None
    if found is None:
        raise _not_vibration_apps_csv(name)
    if found.group(0) not in VIBRATION_APPS_CSV_FORMATS:
        raise ValueError(
            "%s is format '%s', and this pydvma reads '%s' only. Update "
            "pydvma (pip install --upgrade pydvma) to load it."
            % (name, found.group(0), "' and '".join(VIBRATION_APPS_CSV_FORMATS)))

    # Format 2 puts a time table after the TF table; split there first, so
    # the (large) time rows are read in one pass and never line by line.
    tf_text, has_time, time_text = text.partition(_VA_TIME_SECTION)
    lines = tf_text.splitlines()

    # The '#' block: one line of key=value pairs and one of notes per
    # measurement, in the order the app lists them; other lines describe
    # the file and are not needed here.
    meta, notes, at = {}, {}, 0
    while at < len(lines) and lines[at].startswith('#'):
        m = _VA_MEASUREMENT_RE.match(lines[at])
        if m and m.group(2):
            notes[int(m.group(1))] = [s for s in m.group(3).split(' | ') if s]
        elif m:
            pairs = (kv.partition('=') for kv in m.group(3).split('; '))
            meta[int(m.group(1))] = {k.strip(): v.strip()
                                     for k, _, v in pairs if k.strip()}
        at += 1
    col = _va_table(lines[at:], name, _VA_COLUMNS, 'transfer function')
    timecol = _va_time_table(time_text, name) if has_time else None

    numbers = col['measurement']
    unlisted = sorted(set(numbers[~np.isnan(numbers)].astype(int)) - set(meta))
    if unlisted:
        raise ValueError(
            "%s: measurement %d has rows but no '# m%d:' line; the file "
            "looks edited or cut short." % (name, unlisted[0], unlisted[0]))

    dataset = datastructure.DataSet()
    for no, md in meta.items():
        sel = numbers == no
        if not sel.any():
            raise ValueError(
                "%s: measurement %d has a '# m%d:' line but no rows; the "
                "file looks edited or cut short." % (name, no, no))
        n_out = int(_va_num(md.get('channels')) or 1)
        fs = _va_num(md.get('fs'))
        t = _va_timestamp(md.get('timestamp'))
        test_name = ('m%d %s' % (no, md.get('test_name', ''))).strip()

        def settings_for(channels):
            s = (options.MySettings(channels=channels, fs=fs) if fs
                 else options.MySettings(channels=channels))
            if md.get('device_name'):
                s.device_name = md['device_name']
            return s

        # The measurement's time data (format 2, `time_rows=` in its line):
        # channel 0 x (what was played, or the reference channel), channel 1
        # y (the microphone, moved earlier by the loop delay to the nearest
        # sample). The file rounds t_s to the microsecond, so the axis is
        # rebuilt exactly from fs.
        link = uuid.uuid4()
        n_time = int(_va_num(md.get('time_rows')) or 0)
        if n_time and not fs:
            raise ValueError(
                "%s: measurement %d has time data but no fs= in its '# m%d:' "
                "line, so its time axis cannot be built." % (name, no, no))
        if n_time:
            tsel = (timecol['measurement'] == no) if timecol is not None else np.zeros(0, bool)
            if int(np.count_nonzero(tsel)) != n_time:
                raise ValueError(
                    "%s: measurement %d has %d time rows, but its header says "
                    "time_rows=%d; the file looks edited or cut short."
                    % (name, no, int(np.count_nonzero(tsel)), n_time))
            t0 = timecol['t_s'][tsel][0]
            td = datastructure.TimeData(
                t0 + np.arange(n_time) / fs,
                np.column_stack([timecol['x'][tsel], timecol['y'][tsel]]),
                settings_for(2), units=['-', '-'],
                channel_cal_factors=np.ones(2), test_name=test_name)
            if t is not None:
                _va_stamp(td, t)
            dataset.add_to_dataset(td)
            link = td.unique_id

        f = col['f_Hz'][sel]
        H1 = col['H1_re'][sel] + 1j * col['H1_im'][sel]
        coh = col['coherence'][sel]

        # An |H| with no phase (from the powers alone): its phase, and any
        # modal fit to it, mean nothing, so the set says so in its name.
        magnitude_only = (md.get('estimator', 'H1') not in ('H1', '')
                          or not np.any(col['H1_im'][sel][np.isfinite(H1)]))
        if magnitude_only:
            test_name += ' (|H| only, no phase)'
            warnings.warn(
                '%s: measurement %d has an |H| with no phase (zero '
                'everywhere); its phase and any modal fit to it are not '
                'meaningful.' % (name, no), UserWarning, stacklevel=3)

        tf_settings = settings_for(n_out + 1)
        tf_settings.ch_in = int(_va_num(md.get('ch_in')) or 0)
        tf_settings.ch_out_set = np.setxor1d(np.arange(n_out + 1), tf_settings.ch_in)
        tf = datastructure.TfData(
            f, H1[:, None], None if np.all(np.isnan(coh)) else coh[:, None],
            tf_settings, units=[md.get('units') or '-'],
            channel_cal_factors=np.array([_va_num(md.get('channel_cal_factors')) or 1.0]),
            id_link=link, test_name=test_name)
        if t is not None:
            _va_stamp(tf, t)
        nperseg = _va_num(md.get('nperseg'))
        tf.source_settings = {
            'calc': 'vibration_apps_' + md.get('kind', ''),
            'window': md.get('window') or None,
            'N_frames': int(_va_num(md.get('N_frames')) or 1),
            'overlap': _va_num(md.get('overlap')),
            'nperseg': None if nperseg is None else int(nperseg),
            'ch_in': tf_settings.ch_in,
            'vibration_apps': dict(md, notes=notes.get(no, [])),
        }
        if magnitude_only:
            tf.source_settings['magnitude_only'] = True

        # Gxx, Gyy (one-sided densities) with H1 and the coherence give the
        # whole 2x2 cross-spectral matrix, in pydvma's convention a one-sided
        # power SPECTRUM: P = G * enbw_hz (see `CrossSpecData.enbw_hz`).
        # Gxy = H1 * Gxx; a one-frame result's coherence is 1 by definition.
        enbw = _va_enbw(md, fs)
        if 'Gxx' in col and 'Gyy' in col and enbw is not None:
            Gxx, Gyy = col['Gxx'][sel], col['Gyy'][sel]
            if np.all(np.isfinite(Gxx)) and np.all(np.isfinite(Gyy)) and not magnitude_only:
                Pxy = np.empty((2, 2, f.size), dtype=complex)
                Pxy[0, 0] = Gxx * enbw
                Pxy[1, 1] = Gyy * enbw
                Pxy[0, 1] = H1 * Gxx * enbw
                Pxy[1, 0] = np.conj(Pxy[0, 1])
                gamma2 = np.where(np.isnan(coh), 1.0, coh)
                Cxy = np.ones((2, 2, f.size))
                Cxy[0, 1] = Cxy[1, 0] = gamma2
                cs_settings = settings_for(2)
                cs_settings.window = _VA_WINDOWS[md['window']]
                cs = datastructure.CrossSpecData(
                    f.copy(), Pxy, Cxy, cs_settings, units=['-', '-'],
                    channel_cal_factors=np.ones(2), id_link=link,
                    test_name=('m%d %s' % (no, md.get('test_name', ''))).strip(),
                    enbw_hz=enbw)
                if t is not None:
                    _va_stamp(cs, t)
                dataset.add_to_dataset(cs)
        dataset.add_to_dataset(tf)
    return dataset


def import_from_vibration_apps_csv(filename=None):
    '''
    Imports the CSV that the Vibration Apps' Transfer function app saves.

    The app (https://torebutlin.github.io/vibration_apps/apps/frf/, used
    in 3C6) measures speaker to microphone in a browser and saves every
    measurement it holds as one CSV: format ``vibration-apps-tf-csv 1``,
    or ``vibration-apps-tf-csv 2`` when its "time data" box is ticked,
    which adds each measurement's time series after the transfer
    functions. `load_data` recognises the file by its first line, so
    ``load_data('x.csv')`` comes here too.

    Each measurement gives, in the file's order and all named
    ``m<no> <the app's name>`` with the app's card number:

    - a `TimeData` (format 2, when the measurement has time data; never
      for a stepped sine): channel 0 x, what was played (or the app's
      reference channel), channel 1 y, the microphone, moved earlier by
      the app's loop delay to the nearest sample so the two line up as
      the app analysed them. The time axis is rebuilt exactly from fs.
    - a `TfData`: ``freq_axis`` the measurement's own frequencies (they
      differ between measurements and need not be a uniform grid: a
      stepped sine's points); ``tf_data`` H1 = S_xy/S_xx, one column,
      with the loop delay already out of its phase; ``tf_coherence`` one
      column, or None for a result of one frame (the app leaves it empty:
      it is 1 by definition).
    - a `CrossSpecData`, when the file has the ``Gxx`` / ``Gyy`` columns
      (not for a stepped sine): the 2x2 cross-spectral matrix from the
      auto-spectra, H1 and the coherence, in pydvma's convention (``Pxy``
      a one-sided power spectrum, the app's density times ``enbw_hz``, the
      effective noise bandwidth of the app's window and frame length).

    The items of one measurement share one ``id_link``: the `TimeData`'s
    ``unique_id`` when there is time data, otherwise an id of their own,
    so the web app shows each measurement as one set.

    All are uncalibrated, microphone full scale per speaker full scale
    (``units`` ``'-'``, ``channel_cal_factors`` 1). ``settings`` carry
    ``fs`` and ``device_name`` (the microphone, when the browser named
    it); the TF's carry ``channels`` (outputs + 1) and ``ch_in``.
    ``timestamp`` is when the measurement was made, a timezone-aware UTC
    datetime. The TF's ``source_settings`` hold ``calc``
    (``'vibration_apps_'`` + the kind: ``noise``, ``sweep``, ``sine``,
    ``file``), ``window``, ``N_frames``, ``overlap``, ``nperseg``,
    ``ch_in``, and ``vibration_apps``, every key=value of the app's as a
    string plus its ``notes`` (a list), so the test signal, loop delay and
    quality figures survive a .dvma round trip. There is no
    ``source_signature``: pydvma did not compute these.

    An H1 with no phase anywhere (an |H| from the powers alone) is
    imported with ``' (|H| only, no phase)'`` added to its name,
    ``source_settings['magnitude_only']`` True, no cross-spectrum, and a
    UserWarning: its phase and any modal fit to it are not meaningful.
    The file's H2 and H_power columns are not imported. A measurement the
    app was hiding when it saved is imported all the same. Keys and
    columns this version does not know are ignored.

    Args:
       filename (str or os.PathLike): File to import, given positionally or
           as ``filename=``.

    Returns:
       dataset (DataSet): The measurements' TimeData, CrossSpecData and
           TfData.

    Raises:
       ValueError: If the file's first line does not name the format,
           including pydvma's own `export_to_csv` files; if it names
           another version of it; or if columns, rows, time rows or a
           measurement's header line are missing.
       TypeError: If no filename is given.
    '''
    filename = _resolve_filename(None, filename, 'import_from_vibration_apps_csv',
                                 "import_from_vibration_apps_csv('measurements.csv')")
    with open(filename, encoding='utf-8-sig') as fh:
        text = fh.read()
    return _vibration_apps_dataset(text, os.path.basename(filename))
