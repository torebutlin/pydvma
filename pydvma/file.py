# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 14:32:35 2018

@author: tb267
"""

import os.path
import zipfile
import numpy as np
import scipy.io as io
# `QFileDialog` (and via qtpy, the whole Qt binding) is only needed
# when a save/load function is called with `filename=None` and has to
# prompt the user with an interactive file picker. Deferring the import
# means analysis-only / CLI callers that always pass `filename=...`
# never pay the Qt load cost. NOTE: since the Qt logger was removed
# (tag qt-final) there is no `[qt]` extra, so qtpy is no longer
# installed by any pydvma extra — the no-filename picker fallback now
# requires a separate `pip install qtpy` (or a PyQt/PySide binding).
# Always passing an explicit `filename=...` needs no Qt at all.
from . import container
from . import datastructure
from . import options


def load_data(parent=None, filename=None):
    '''
    Loads a dataset from `filename`, or displays a file dialog if no
    filename is given (the dialog needs the GUI extras installed).

    Container detection is by content (zip magic bytes); ``.mat`` and
    legacy ``.npy`` fall back to extension:

    - ``.dvma`` container files (zip magic bytes) — the default
      format since 1.5.0; safe, pickle-free (see `container`).
    - legacy ``.npy`` pickle saves from pydvma <= 1.4.0 — supported
      forever. **Trust model:** the legacy path uses
      ``np.load(allow_pickle=True)``, and unpickling can execute
      arbitrary code, so only open legacy .npy files you or your lab
      created. `.dvma` files do not have this caveat.
    - ``.mat`` (by extension) — JW-logger imports.
    '''
    if filename is None:
        from qtpy.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getOpenFileName(
            parent, 'Open data file', '', '*.dvma *.npy *.mat')
        if not filename:
            return None

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
    Saves a DataSet to 'filename.dvma' (container format v2 — a zip
    of manifest.json + pickle-free .npy arrays; see `container`), or
    provides a dialog if no filename is given.

    Legacy escape hatch: an explicit filename ending in ``.npy``
    writes the pre-1.5.0 pickle format instead, for workflows that
    still need it. New saves should prefer .dvma — it is safe to
    share (loading executes no code) and readable outside Python.

    Args:
       dataset (DataSet): An object of the class DataSet
       parent (optional): Parent widget for file dialog
       filename (str, optional): Output filename, dialog shown if not provided
       overwrite_without_prompt (bool, optional): If True, overwrite without asking
       sets (int or Iterable[int], optional): If given, writes
           ``dataset.subset(sets)`` instead of the whole dataset — the
           notebook counterpart of the web app's Save "Choose sets…"
           picker (see `datastructure.DataSet.subset` for the exact
           inclusion rule). `None` (the default) writes `dataset`
           unchanged.
    '''
    if sets is not None:
        dataset = dataset.subset(sets)

    # If filename not specified, provide dialog
    from_dialog = filename is None
    if from_dialog:
        from qtpy.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getSaveFileName(
            parent, 'Save dataset', '', '*.dvma')
        if not filename:
            print('Save cancelled')
            return None

    # Normalise the extension FIRST, so both the dialog and explicit
    # paths write a real extension and the overwrite prompt below
    # checks the same filename we're about to write.
    if not filename.endswith('.npy') and not filename.endswith('.dvma'):
        filename += '.dvma'

    # Explicit-filename path only: terminal overwrite prompt. The
    # dialog path keeps Qt's own replace-file confirmation and must
    # never block on terminal input().
    if (not from_dialog and os.path.isfile(filename)
            and not overwrite_without_prompt):
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
    Saves figure to file 'filename.png' and 'filename.pdf', or provides dialog if no
    filename provided.

    Args:
       plot (PlotData or Figure): A PlotData object or matplotlib Figure object
       parent (optional): Parent widget for file dialog
       figsize (tuple, optional): Tuple for figure size
       filename (str, optional): Output filename, dialog shown if not provided
       overwrite_without_prompt (bool, optional): If True, overwrite without asking
    '''
    if plot.__class__.__name__ == 'PlotData':
        fig = plot.fig
    elif plot.__class__.__name__ == 'Figure':
        fig = plot

    # If filename not specified, provide dialog
    if filename is None:
        from qtpy.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getSaveFileName(parent, 'Save figure', '')
        if not filename:
            # No filename chosen, give up on saving
            print('Save cancelled')
            return None


    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    elif os.path.isfile(filename) and not overwrite_without_prompt:
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
    Exports dataset class to file 'filename.mat', or provides dialog if no
    filename provided.

    Saved file can be loaded directly in Matlab as set of arrays.

    Args:
       dataset (DataSet): An object of the class DataSet
       parent (optional): Parent widget for file dialog
       filename (str, optional): Output filename, dialog shown if not provided
       overwrite_without_prompt (bool, optional): If True, overwrite without asking

    '''
    
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
        
        t=np.arange(0,T,1/fs)
        time_data_all = np.zeros((len(t),n_time))
        counter = -1
        for time_data in dataset.time_data_list:
            for i in range(time_data.time_data.shape[1]):
                counter += 1
                time_data_all[:,counter] = np.interp(t,time_data.time_axis,time_data.time_data[:,i],right=0)
                
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
        
        f=np.arange(0,fmax+df,df)
        npts = 2*(len(f)-1)
        fs_tf = 2*f[-1]
        freq_data_all = np.zeros((len(f),n_tf),dtype=complex)
        counter = -1
        for freq_data in dataset.freq_data_list:
            freq_shape = np.shape(freq_data.freq_data)
            for i in range(freq_shape[1]):
                counter += 1
                freq_data_all[:,counter] = np.interp(f,freq_data.freq_axis,freq_data.freq_data[:,i],right=0)
        
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
        
        f=np.arange(0,fmax+df,df)
        npts = 2*(len(f)-1)
        fs_tf = 2*f[-1]
        tf_data_all = np.zeros((len(f),n_tf),dtype=complex)
        counter = -1
        for tf_data in dataset.tf_data_list:
            tf_shape = np.shape(tf_data.tf_data)
            for i in range(tf_shape[1]):
                counter += 1
                tf_data_all[:,counter] = np.interp(f,tf_data.freq_axis,tf_data.tf_data[:,i],right=0)
        
        data_matlab['tf_axis_all'] = np.transpose(np.atleast_2d(f))
        data_matlab['tf_data_all'] = tf_data_all
        # TF factors are the cal RATIO cal[out]/cal[in] per output column,
        # and the units the matching 'out/in' strings.
        _attach_matlab_calibration(data_matlab, 'tf', dataset.tf_data_list)
        

    


    #%% SAVE

    # If filename not specified, provide dialog
    if filename is None:
        from qtpy.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getSaveFileName(parent, 'Save dataset', '', '*.mat')
        if not filename:
            # No filename chosen, give up on saving
            print('Save cancelled')
            return None


    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    elif os.path.isfile(filename) and not overwrite_without_prompt:
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
    Exports dataset class to file 'filename.mat', or provides dialog if no
    filename provided.

    Saved file is compatible with Jim Woodhouse logger file format.

    Args:
       dataset (DataSet): An object of the class DataSet
       parent (optional): Parent widget for file dialog
       filename (str, optional): Output filename, dialog shown if not provided
       overwrite_without_prompt (bool, optional): If True, overwrite without asking

    '''

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
        
        t=np.arange(0,T,1/fs)
        time_data_all = np.zeros((len(t),n_time))
        counter = -1
        for time_data in dataset.time_data_list:
            for i in range(time_data.time_data.shape[1]):
                counter += 1
                time_data_all[:,counter] = np.interp(t,time_data.time_axis,time_data.time_data[:,i],right=0)
                
        data_jwlogger['buflen'] = float(np.size(t))
        data_jwlogger['indata'] = time_data_all
        data_jwlogger['tsmax'] = float(t[-1])
    else:
        n_time = 0
        time_data_all = 0
    
    
    #%% FFT: get's overwritten by TF if exists
    if len(dataset.freq_data_list) > 0:
        df=np.inf
        fmax=0
        n_freq=0
        for freq_data in dataset.freq_data_list:
            df_check = np.mean(np.diff(freq_data.freq_axis))
            df = np.min([df,df_check])
            fmax = np.max([freq_data.freq_axis[-1],fmax])
            freq_shape = np.shape(freq_data.freq_data)
            n_freq += freq_shape[1]
        
        f=np.arange(0,fmax+df,df)
        npts = 2*(len(f)-1)
        fs_freq = 2*f[-1]
        freq_data_all = np.zeros((len(f),n_freq),dtype=complex)
        counter = -1
        for freq_data in dataset.freq_data_list:
            freq_shape = np.shape(freq_data.freq_data)
            for i in range(freq_shape[1]):
                counter += 1
                freq_data_all[:,counter] = np.interp(f,freq_data.freq_axis,freq_data.freq_data[:,i],right=1)
                freq_data_all[0,counter] = freq_data_all[1,counter] # to match equivalent tweak in JW Logger for handling DC singularities
                zero_test = freq_data_all[:,counter] == 0
                freq_data_all[zero_test,counter] = np.min(np.abs(freq_data_all[:,counter])) # handle zeros
        
        # convert
        data_jwlogger['freq'] = float(fs_freq)
        data_jwlogger['npts'] = float(npts)
        data_jwlogger['yspec'] = freq_data_all
    else:
        n_freq = 0
        freq_data_all = 0
    
    
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
        
        f=np.arange(0,fmax+df,df)
        npts = 2*(len(f)-1)
        fs_tf = 2*f[-1]
        tf_data_all = np.zeros((len(f),n_tf),dtype=complex)
        counter = -1
        for tf_data in dataset.tf_data_list:
            tf_shape = np.shape(tf_data.tf_data)
            for i in range(tf_shape[1]):
                counter += 1
                tf_data_all[:,counter] = np.interp(f,tf_data.freq_axis,tf_data.tf_data[:,i],right=1)
                tf_data_all[0,counter] = tf_data_all[1,counter] # to match equivalent tweak in JW Logger for handling DC singularities
                zero_test = tf_data_all[:,counter] == 0
                tf_data_all[zero_test,counter] = np.min(np.abs(tf_data_all[:,counter])) # handle zeros
        
        # convert
        data_jwlogger['freq'] = float(fs_tf)
        data_jwlogger['npts'] = float(npts)
        data_jwlogger['yspec'] = tf_data_all
    else:
        n_tf = 0
        tf_data_all = 0
    
    #%% Convert
    
    if (n_freq > 0) & (n_tf > 0):
        # if both FFT and TF data present then TF overwrites
        N = n_tf
    else:
        # if only one of FFT or TF, or neither, then keep non-zero one, or neither
        N = np.max([n_tf,n_freq])
    
    data_jwlogger['dt2'] = np.array([n_time,N,0],dtype=float)
    data_jwlogger['dtype'] = np.array([n_time,N,0],dtype=float)
    

    # SAVE

    # If filename not specified, provide dialog
    if filename is None:
        from qtpy.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getSaveFileName(parent, 'Save dataset', '', '*.mat')
        if not filename:
            # No filename chosen, give up on saving
            print('Save cancelled')
            return None


    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    elif os.path.isfile(filename) and not overwrite_without_prompt:
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
    Exports data to file 'filename.csv', or provides dialog if no
    filename provided.

    Saved file is *.csv

    Args:
       data_list (TimeDataList, FreqDataList, or TfDataList): Data list to export
       parent (optional): Parent widget for file dialog
       filename (str, optional): Output filename, dialog shown if not provided
       overwrite_without_prompt (bool, optional): If True, overwrite without asking
    '''
    
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

    # If filename not specified, provide dialog
    if filename is None:
        from qtpy.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getSaveFileName(parent, 'Save dataset', '', '*.csv')
        if not filename:
            # No filename chosen, give up on saving
            print('Save cancelled')
            return None


    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    elif os.path.isfile(filename) and not overwrite_without_prompt:
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
def import_from_matlab_jwlogger(filename=None):
    '''
    Imports dataset class from file 'filename.mat', or provides dialog if no
    filename provided.

    Saved file is compatible with Jim Woodhouse logger file format. The
    conventions below were confirmed against the recovered MATLAB source
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
       filename (str, optional): Input filename, dialog shown if not provided
    '''
    
    d = io.loadmat(filename)
    dataset = datastructure.DataSet()

    # `freq` (the sample rate) is a (1,1) MATLAB scalar array — unwrap once.
    fs = float(np.ravel(d['freq'])[0]) if 'freq' in d else None

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
    if ('yspec' in d) and (d['tfun'] == 0):
        fd = d['yspec']
        fa = np.fft.rfftfreq(int(np.ravel(d['npts'])[0]),1/fs)
        fa = np.squeeze(fa)
        settings = options.MySettings(channels=np.size(fd,1),
                                      fs=fs)
        
        freq_data = datastructure.FreqData(fa,fd,settings)
        freq_data.timestamp = os.path.getmtime(filename)
        dataset.add_to_dataset(freq_data)

    
    #%% TF
    if ('yspec' in d) and (d['tfun'] == 1):
        tf = d['yspec']
        fa = np.fft.rfftfreq(int(np.ravel(d['npts'])[0]),1/fs)
        fa = np.squeeze(fa)

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