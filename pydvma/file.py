# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 14:32:35 2018

@author: tb267
"""

import os.path
import warnings
import zipfile
import numpy as np
import scipy.io as io
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


def load_data(parent=None, filename=None):
    '''
    Loads a dataset from `filename`.

    The filename can be given positionally, ``load_data('name.dvma')``,
    or as ``filename=``, and is required: there is no file dialog.

    Container detection is by content (zip magic bytes); ``.mat`` and
    legacy ``.npy`` fall back to extension:

    - ``.dvma`` container files (zip magic bytes) — the default
      format since 1.5.0; safe, pickle-free (see `container`).
    - legacy ``.npy`` pickle saves from pydvma <= 1.4.0 — supported
      forever. **Trust model:** the legacy path uses
      ``np.load(allow_pickle=True)``, and unpickling can execute
      arbitrary code, so only open legacy .npy files you or your lab
      created. `.dvma` files do not have this caveat.
    - ``.mat`` (by extension) — JW-logger imports only, via
      `import_from_matlab_jwlogger`. The .mat that `export_to_matlab`
      writes is export-only and raises ValueError.

    Args:
       parent (optional): Deprecated and ignored, and going in pydvma
           3.0 (it was the Qt file dialog's parent). A str or path here
           is taken as the filename.
       filename (str or os.PathLike): File to load, given positionally or
           as ``filename=``.

    Returns:
       dataset (DataSet or None): The loaded data, or None if the
           extension is not .dvma, .npy or .mat.

    Raises:
       FileNotFoundError: If `filename` does not exist.
       ValueError: If a ``.dvma`` file is not a valid container, or a
           ``.mat`` file is not a JW-logger file.
       TypeError: If no filename is given.
    '''
    filename = _resolve_filename(parent, filename, 'load_data',
                                 "load_data('data.dvma')")
    if not os.path.isfile(filename):
        raise FileNotFoundError(
            'No such data file: {!r}'.format(filename))

    if zipfile.is_zipfile(filename):
        dataset = container.load(filename)
    elif filename.endswith('.mat'):
        dataset = import_from_matlab_jwlogger(filename=filename)
    elif filename.endswith('.npy'):
        d = np.load(filename, allow_pickle=True, fix_imports=True)
        dataset = d[0]
    elif filename.endswith('.dvma'):
        raise ValueError(
            '{!r} has the .dvma extension but is not a valid container '
            '— empty, truncated, or corrupted?'.format(filename))
    else:
        print('Expecting file to be .dvma, .npy or .mat')
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



#%% EXPORT TO MATLAB
def export_to_matlab(dataset, parent=None, filename=None, overwrite_without_prompt=False):
    '''
    Exports a DataSet to 'filename.mat' for MATLAB.

    Each kind of data (time, FFT, transfer function) is one block, with
    every channel of every measurement of that kind as a column, and the
    measurements interpolated onto one common axis: for time, the highest
    sample rate over the longest capture; for FFT and TF, the finest
    spacing up to the highest frequency. A column is zero past the end of
    a shorter record, so a single measurement keeps exactly its own
    samples or bins. Coherence, sonograms and cross-spectra are not
    exported. The web app's Export Matlab writes the same variables.

    The file loads directly in MATLAB as a set of arrays. It is
    export-only: pydvma cannot read it back (`load_data` refuses it), so
    keep a `save_data` .dvma alongside it. The filename can be given
    positionally, ``export_to_matlab(dataset, 'name.mat')``, or as
    ``filename=``; ``.mat`` is added if missing. The filename is
    required: there is no file dialog.

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
    filename = _resolve_filename(parent, filename, 'export_to_matlab',
                                 "export_to_matlab(dataset, 'data.mat')")
    
    # convert data into dictionary ready for Matlab
    data_matlab = dict()
    
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
        
        t = _time_grid(T, fs)
        time_data_all = np.zeros((len(t),n_time))
        counter = -1
        for time_data in dataset.time_data_list:
            for i in range(time_data.time_data.shape[1]):
                counter += 1
                time_data_all[:,counter] = _interp_onto(t,time_data.time_axis,time_data.time_data[:,i],0)
                
        data_matlab['time_axis_all'] = np.transpose(np.atleast_2d(t))
        data_matlab['time_data_all'] = time_data_all
        # The columns above are RAW (volts); these say how to calibrate them.
        _attach_matlab_calibration(data_matlab, 'time', dataset.time_data_list)

    


    #%% FFT - doesn't export coherence
    if len(dataset.freq_data_list) > 0:
        df=np.inf
        fmax=0
        n_tf=0
        for freq_data in dataset.freq_data_list:
            df_check = np.mean(np.diff(freq_data.freq_axis))
            df = np.min([df,df_check])
            fmax = np.max([freq_data.freq_axis[-1],fmax])
            tf_shape = np.shape(freq_data.freq_data)
            n_tf += tf_shape[1]
        
        f = _spectral_grid(fmax, df)
        npts = 2*(len(f)-1)
        fs_tf = 2*f[-1]
        freq_data_all = np.zeros((len(f),n_tf),dtype=complex)
        counter = -1
        for freq_data in dataset.freq_data_list:
            freq_shape = np.shape(freq_data.freq_data)
            for i in range(freq_shape[1]):
                counter += 1
                freq_data_all[:,counter] = _interp_onto(f,freq_data.freq_axis,freq_data.freq_data[:,i],0)
        
        data_matlab['freq_axis_all'] = np.transpose(np.atleast_2d(f))
        data_matlab['freq_data_all'] = freq_data_all
        _attach_matlab_calibration(data_matlab, 'freq', dataset.freq_data_list)
        
 


    #%% Transfer Function - doesn't export coherence
    if len(dataset.tf_data_list) > 0:
        df=np.inf
        fmax=0
        n_tf=0
        for tf_data in dataset.tf_data_list:
            df_check = np.mean(np.diff(tf_data.freq_axis))
            df = np.min([df,df_check])
            fmax = np.max([tf_data.freq_axis[-1],fmax])
            tf_shape = np.shape(tf_data.tf_data)
            n_tf += tf_shape[1]
        
        f = _spectral_grid(fmax, df)
        npts = 2*(len(f)-1)
        fs_tf = 2*f[-1]
        tf_data_all = np.zeros((len(f),n_tf),dtype=complex)
        counter = -1
        for tf_data in dataset.tf_data_list:
            tf_shape = np.shape(tf_data.tf_data)
            for i in range(tf_shape[1]):
                counter += 1
                tf_data_all[:,counter] = _interp_onto(f,tf_data.freq_axis,tf_data.tf_data[:,i],0)
        
        data_matlab['tf_axis_all'] = np.transpose(np.atleast_2d(f))
        data_matlab['tf_data_all'] = tf_data_all
        # TF factors are the cal RATIO cal[out]/cal[in] per output column,
        # and the units the matching 'out/in' strings.
        _attach_matlab_calibration(data_matlab, 'tf', dataset.tf_data_list)
        

    


    #%% SAVE

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
    io.savemat(filename,data_matlab)
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


def _time_grid(T, fs):
    '''
    The common time axis of an `export_to_matlab` time block.

    ``round(T*fs)`` samples at ``fs``, counted rather than stepped:
    ``np.arange(0, T, 1/fs)`` sometimes admits one sample past the end
    through float rounding (1000 Hz x 1023 samples, 3000 Hz x 999), which
    became a spurious trailing row of zeros. The rate is estimated from an
    axis, so `_clean_rate` strips its float noise first. The browser's
    Export Matlab (`engine.export_mat`) builds its grid here too, which is
    how the two files stay identical.

    Args:
       T (float): The longest capture's duration in seconds, its sample
           count over its rate.
       fs (float): The highest sample rate in Hz.

    Returns:
       t (np.ndarray): The sample times ``k/fs``, starting at 0.
    '''
    fs = _clean_rate(fs)
    return np.arange(int(round(T * fs))) / fs


def _spectral_grid(fmax, df):
    '''
    The common frequency axis of an `export_to_matlab` FFT or TF block.

    ``round(fmax/df) + 1`` bins at spacing ``df`` from 0, counted rather
    than stepped: ``np.arange(0, fmax + df, df)`` sometimes admits one bin
    past ``fmax`` through float rounding (the FFT of 1000 Hz x 1023
    samples), which became a spurious trailing row of zeros. When the
    spectra's spacings differ, the grid ends within half a step of
    ``fmax``. The browser's Export Matlab (`engine.export_mat`) builds its
    grid here too, which is how the two files stay identical.

    Args:
       fmax (float): The highest frequency of any spectrum, in Hz.
       df (float): The finest bin spacing of any spectrum, in Hz.

    Returns:
       f (np.ndarray): The bin frequencies ``k*df``, starting at 0.
    '''
    return np.arange(int(round(fmax / df)) + 1) * df


#%% CALIBRATION METADATA FOR THE RAW-DATA EXPORTS
def _column_calibration(data_list):
    """Per-column calibration factors and units for a CSV/Matlab export.

    The CSV and Matlab exporters write the stored arrays VERBATIM — in volts,
    with no calibration applied — which is the right default for a raw-data
    export but leaves the file unable to say so. This returns what the header
    needs to close that gap: one ``(cal_factor, unit)`` pair per exported
    column, in the same order the exporters emit them, so a reader can
    recover engineering units by multiplying column *k* by ``cal_factors[k]``.

    The AXIS column is not included — it is time in seconds or frequency in
    hertz and carries no calibration.

    Column counts come from each item's ARRAY, never ``settings.channels``:
    ``use_output_as_ch0`` prepends the drive column without bumping the
    setting. A short or absent ``channel_cal_factors`` pads with 1.0 (the
    identity, matching every constructor's default) and an absent unit
    renders as ``'-'`` rather than asserting a unit nobody stated.

    Args:
        data_list: A TimeDataList, FreqDataList or TfDataList.

    Returns a ``(cal_factors, units)`` pair of equal-length lists.
    """
    attr = {'TimeDataList': 'time_data',
            'FreqDataList': 'freq_data',
            'TfDataList': 'tf_data'}.get(data_list.__class__.__name__)
    cal_factors = []
    units = []
    if attr is None:
        return cal_factors, units
    for item in data_list:
        n_cols = np.shape(getattr(item, attr))[1]
        factors = getattr(item, 'channel_cal_factors', None)
        item_units = getattr(item, 'units', None)
        for c in range(n_cols):
            f = 1.0
            if factors is not None and c < len(factors):
                try:
                    f = float(factors[c])
                except (TypeError, ValueError):
                    f = 1.0
            cal_factors.append(f)
            u = '-'
            if item_units is not None and c < len(item_units):
                u = str(item_units[c])
            units.append(u)
    return cal_factors, units


def _attach_matlab_calibration(data_matlab, prefix, data_list):
    """Add ``<prefix>_cal_factors`` / ``<prefix>_units`` to a Matlab export.

    The exported arrays are the stored ones — RAW, in volts, with no
    calibration applied — so the file needs somewhere to state the factor
    that turns each column into engineering units. These two extra keys are
    that place: ``<prefix>_cal_factors`` is a column vector aligned with the
    data columns of ``<prefix>_data_all``, and ``<prefix>_units`` the
    matching cell array of unit strings (``'-'`` where none was recorded).

    Purely ADDITIVE — every key the exporter already wrote is untouched, so
    existing MATLAB scripts keep working and only gain the metadata.
    """
    cal_factors, units = _column_calibration(data_list)
    _attach_matlab_column_calibration(data_matlab, prefix, cal_factors, units)


def _attach_matlab_column_calibration(data_matlab, prefix, cal_factors, units):
    """Write already-resolved per-column calibration into a Matlab export.

    The half of `_attach_matlab_calibration` that owns the key names and
    their MATLAB encoding, split out so the browser's Export Matlab (the
    `pydvma.engine.export_mat` op, which has per-column arrays but no
    DataSet) writes the SAME keys the same way as `export_to_matlab`.
    ``<prefix>_cal_factors`` becomes a float column vector and
    ``<prefix>_units`` a cell array of strings; nothing is written when
    there are no columns.

    Args:
        data_matlab (dict): The ``scipy.io.savemat`` dict to add keys to.
        prefix (str): ``'time'``, ``'freq'`` or ``'tf'``.
        cal_factors (list of float): One factor per exported data column.
        units (list of str): One unit per exported data column.
    """
    if not cal_factors:
        return
    data_matlab[prefix + '_cal_factors'] = np.transpose(
        np.atleast_2d(np.asarray(cal_factors, dtype=float)))
    data_matlab[prefix + '_units'] = np.array(units, dtype=object)


def format_cal_factor(value):
    """Render one calibration factor for a CSV header, as ``'%.12g'``.

    Shared format, not a local choice: the browser UI writes byte-identical
    CSVs (``webui/src/lib/export/data.ts``), so both sides must render these
    numbers the same way. ``%.12g`` is short enough to read, round-trips every
    realistic factor, and its C semantics (exponential below 1e-4 or at/above
    12 significant digits, trailing zeros stripped) are reproducible in
    JavaScript — the JS twin is ``fmtCalFactor``, pinned against this one by
    the known-answer vectors in ``CAL_FACTOR_FORMAT_VECTORS``.

    A non-finite factor renders as ``'1'``: the identity, matching how every
    consumer already treats an unusable factor, rather than writing a ``nan``
    into a header a script may parse.
    """
    v = float(value)
    if not np.isfinite(v):
        return '1'
    return '{:.12g}'.format(v)


#: Known-answer vectors pinning `format_cal_factor` and its JavaScript twin
#: `fmtCalFactor` to the same output. Mirrored verbatim in
#: `webui/tests/export/data.test.ts`; a change here must change both.
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


def _csv_header(data_list):
    """The comment block `export_to_csv` prefixes to its data rows.

    Written through ``np.savetxt(header=...)``, so every line comes out
    prefixed with ``'# '`` and the numeric rows below are byte-identical to
    what the exporter has always produced — ``np.loadtxt`` / ``np.genfromtxt``
    skip it by default, and ``pandas.read_csv(..., comment='#')`` does too.

    It states three things the bare numbers could not: that the values are
    RAW (uncalibrated), the per-column factor that converts each to
    engineering units, and the unit that factor lands in.
    """
    cal_factors, units = _column_calibration(data_list)
    axis_unit = 's' if data_list.__class__.__name__ == 'TimeDataList' else 'Hz'
    return '\n'.join([
        'pydvma export: RAW data, calibration NOT applied.',
        'Column 1 is the shared axis ({}); the rest are data columns.'.format(axis_unit),
        'Multiply data column k by cal_factors[k] for engineering units.',
        'cal_factors: ' + ','.join(format_cal_factor(f) for f in cal_factors),
        'units: ' + ','.join(units),
    ])


def export_to_csv(data_list, parent=None, filename=None, overwrite_without_prompt=False):
    '''
    Exports a TimeDataList, FreqDataList or TfDataList to 'filename.csv'.

    The first column is the shared axis and the rest are the data columns,
    raw (calibration NOT applied); a ``#`` comment header gives each
    column's calibration factor and unit. The filename can be given
    positionally, ``export_to_csv(data_list, 'name.csv')``, or as
    ``filename=``; ``.csv`` is added if missing. The filename is
    required: there is no file dialog.

    Args:
       data_list (TimeDataList, FreqDataList, or TfDataList): Data list to export
       parent (optional): Deprecated and ignored, and going in pydvma
           3.0 (it was the Qt file dialog's parent). A str or path here
           is taken as the filename.
       filename (str or os.PathLike): Output filename, given positionally or
           as ``filename=``.
       overwrite_without_prompt (bool, optional): If True, overwrite without asking

    Returns:
       filename (str or None): The file written, or None if the
           overwrite was declined or `data_list` is not one of the three
           list types.

    Raises:
       TypeError: If no filename is given.
    '''
    filename = _resolve_filename(parent, filename, 'export_to_csv',
                                 "export_to_csv(data_list, 'data.csv')")
    
    data_list_type = data_list.__class__.__name__
    
    if data_list_type == 'TimeDataList':
        darray = np.transpose(np.atleast_2d(data_list[0].time_axis))
        for time_data in data_list:
            darray = np.append(darray,time_data.time_data,axis=1)
        
            
            
    elif data_list_type == 'FreqDataList':
        darray = np.transpose(np.atleast_2d(data_list[0].freq_axis))
        for freq_data in data_list:
            darray = np.append(darray,freq_data.freq_data,axis=1)
        
    elif data_list_type == 'TfDataList':
        darray = np.transpose(np.atleast_2d(data_list[0].freq_axis))
        for tf_data in data_list:
            darray = np.append(darray,tf_data.tf_data,axis=1)
        
    else:
        print('Expecting input to be one of TimeDataList, FreqDataList, or TfDataList')
        return None
    
    # SAVE

    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    if os.path.isfile(filename) and not overwrite_without_prompt:
        answer = input('File %r already exists. Overwrite? [y/n]: ' % filename)
        if answer != 'y':
            print('Save cancelled')
            return None
        print('Will overwrite existing file')
        
    # Make sure it ends with .csv
    if not filename.endswith('.csv'):
        filename += '.csv'
        
    # Actually save! The header names the per-column calibration the data
    # rows deliberately do NOT carry (see `_csv_header`); numpy prefixes it
    # with '# ', so the numeric rows are unchanged and every standard reader
    # skips it.
    np.savetxt(filename, darray, delimiter=",", header=_csv_header(data_list))
    print("Data saved as %s" % filename)

    return filename



#%% IMPORT FROM MATLAB JWLOGGER
# Variables only `export_to_matlab` writes: they mark pydvma's own export.
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

    Only JW-logger files can be imported. The .mat that pydvma's own
    `export_to_matlab` writes is export-only and is refused with a
    ValueError, as is any other .mat with neither of the logger's
    ``indata`` / ``yspec`` variables. The filename is required: there is
    no file dialog.

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
        # (`engine.mat_to_dvma`) comes through here too.
        if any(k in d for k in _PYDVMA_MATLAB_KEYS):
            raise ValueError(
                "This .mat file was written by pydvma's export_to_matlab, "
                "which is export-only (for MATLAB): pydvma cannot read it "
                "back. Only JW-logger .mat files can be imported. To reload "
                "the data, load a .dvma written by save_data instead.")
        raise ValueError(
            "Not a JW-logger .mat file: it has no 'indata' (time) or "
            "'yspec' (spectrum or TF) variable. Only JW-logger .mat files "
            "can be imported; the .mat that pydvma's export_to_matlab "
            "writes is export-only.")
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