# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 17:08:42 2018

@author: tb267
"""

from . import analysis
from . import file
from . import modal

# `plotting` pulls matplotlib.pyplot (~0.3 s on a Mac; it is Qt-free).
# Only the four `DataSet.plot_*_data` methods need it; defer the import
# to each call site so analysis-only / CLI users don't pay the cost.

import numpy as np
import datetime
import uuid
import copy

#%% version
VERSION = '2.5.0' # keep in sync with pyproject.toml (enforced by tests/test_packaging.py)

def update_dataset(dataset):
    '''Rebuild a DataSet from an older pydvma version in the current layout.

    Copies every item list of ``dataset`` into a fresh `DataSet`, so the
    result has every list the current version expects, and gives every
    `TfData` a ``flag_modal_TF`` attribute (False) if it lacks one. The
    items are shared with ``dataset``, not copied, so that attribute is
    added to the original items too; if ``dataset`` has no
    `modal_data_list`, an empty one is added to it.

    Args:
        dataset (DataSet): The dataset to rebuild. It must have
            `time_data_list`, `freq_data_list`, `tf_data_list`,
            `cross_spec_data_list`, `sono_data_list` and
            `meta_data_list`; `modal_data_list` is optional.

    Returns:
        dataset_new (DataSet): A new DataSet holding the same items.
    '''
    dataset_new = DataSet()
    dataset_new.add_to_dataset(dataset.time_data_list)
    dataset_new.add_to_dataset(dataset.freq_data_list)
    dataset_new.add_to_dataset(dataset.tf_data_list)
    dataset_new.add_to_dataset(dataset.cross_spec_data_list)
    dataset_new.add_to_dataset(dataset.sono_data_list)
    dataset_new.add_to_dataset(dataset.meta_data_list)
    if hasattr(dataset,'modal_data_list'):
        dataset_new.add_to_dataset(dataset.modal_data_list)
    else:
        dataset.modal_data_list = ModalDataList()
    for tf_data in dataset_new.tf_data_list:
        if not hasattr(tf_data,'flag_modal_TF'):
            tf_data.flag_modal_TF = False
    return dataset_new


#%% subset() helpers — id_link resolution shared by DataSet.subset

def _flatten_link_ids(value):
    '''Yield the string form of every scalar id nested inside `value`.

    `id_link` conventions across `analysis.py` and `modal.py` are not
    uniform: a single-source result (e.g. `analysis.calculate_fft`)
    stores a bare `uuid.UUID`, while an ensemble result
    (`analysis.calculate_tf_averaged`, `analysis.calculate_cross_spectra_averaged`,
    `analysis.calculate_bla`, `modal.modal_fit_all_channels`,
    `modal.modal_refine`) stores a LIST — and a modal fit's list can
    itself contain list-valued entries, one per spanned TF that was
    itself an ensemble average. This walks lists/tuples/sets
    recursively and yields `str(...)` of every leaf, so a single
    membership test against a set of wanted id strings covers every
    shape uniformly.

    A dict leaf tagged ``{'__uuid__': '...'}`` — the raw `.dvma`
    manifest encoding `container` stashes verbatim for manifest keys
    it does not consume (see `ModalData`'s `source_targets` extra) —
    is unwrapped to its id string; any other dict, and `None`, are
    skipped (not everything nested inside an `id_link` or a
    `source_targets` entry is an id).

    Args:
        value (object): An `id_link`-shaped value — `None`, a
            `str`/`uuid.UUID`, or an arbitrarily nested list/tuple/set of
            those (or of `{'__uuid__': ...}` tag dicts).

    Yields:
        leaf (str): One id string per scalar leaf found in `value`.
    '''
    if value is None:
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            for leaf in _flatten_link_ids(item):
                yield leaf
        return
    if isinstance(value, dict):
        if '__uuid__' in value:
            yield str(value['__uuid__'])
        return
    yield str(value)


def _links_intersect(value, wanted):
    '''True if any id flattened out of `value` (see `_flatten_link_ids`) is in `wanted`.

    Args:
        value (object): An `id_link`-shaped value, per `_flatten_link_ids`.
        wanted (set): Id strings to match against.

    Returns:
        found (bool): Whether any leaf of `value` is a member of `wanted`.
    '''
    for leaf in _flatten_link_ids(value):
        if leaf in wanted:
            return True
    return False


def _modal_item_in_subset(modal_item, wanted):
    '''Whether a `ModalData` item belongs in a `DataSet.subset` pick.

    ANY of its links resolving into `wanted` is enough (see
    `DataSet.subset`): its own `id_link` — scalar for a single-set
    fit, or a possibly-nested list for a multi-set/ensemble-sourced
    fit (`modal.modal_fit_all_channels`, `modal.modal_refine`; see
    `_flatten_link_ids`) — OR, for a dataset that round-tripped
    through the web app, any `source_targets[].id_link` entry. pydvma
    itself never writes `source_targets`; only the browser's
    shared-pole-fit UI does (one entry per spanned set), and it
    survives a Python load->save round trip only because `container`
    stashes every manifest key this reader does not consume verbatim
    on `_container_extra` (see `container.py`'s module docstring). The
    equivalent web-side rule is `subsetDataset` in
    `webui/src/lib/analysis/actions.ts`.

    Args:
        modal_item (ModalData): The item being tested.
        wanted (set): Id strings the chosen `TimeData` items resolve to.

    Returns:
        keep (bool): Whether `modal_item` should ride along with the subset.
    '''
    if _links_intersect(getattr(modal_item, 'id_link', None), wanted):
        return True
    extra = getattr(modal_item, '_container_extra', None)
    if isinstance(extra, dict):
        meta_extra = extra.get('meta')
        if isinstance(meta_extra, dict):
            targets = meta_extra.get('source_targets')
            if isinstance(targets, list):
                for target in targets:
                    if isinstance(target, dict) and _links_intersect(target.get('id_link'), wanted):
                        return True
    return False


#%% Data structure
class DataSet():
    '''The container for a set of measurements and everything derived from them.

    `log_data`, `load_data` and the `create_test_*` functions all return
    one. A DataSet holds seven lists, one per kind of data item (see
    Attributes). Add items with `add_to_dataset`; items are stored by
    reference, never copied.

    The `calculate_*` methods run the matching `analysis` function over
    `time_data_list` and REPLACE the corresponding list with the
    results rather than appending to it, so calling `calculate_fft_set`
    twice leaves one set of spectra, and `calculate_tf_set` also drops
    any modal reconstruction held in `tf_data_list`. With no time data
    they empty that list and print a message. The `plot_*` methods draw
    one list in a new matplotlib figure and return its `PlotData`.
    `save_data` writes a ``.dvma`` file, optionally with only some of
    the measurements (see `subset`).

    Args:
        data (object, optional): An item, or a homogeneous list of
            items, to add at construction; see `add_to_dataset`.

    Attributes:
        time_data_list (TimeDataList): The measurements (`TimeData`).
        freq_data_list (FreqDataList): Spectra (`FreqData`).
        cross_spec_data_list (CrossSpecDataList): Cross-spectrum and
            coherence matrices (`CrossSpecData`).
        tf_data_list (TfDataList): Transfer functions (`TfData`),
            including modal reconstructions.
        modal_data_list (ModalDataList): Modal fits (`ModalData`).
        sono_data_list (SonoDataList): Sonograms (`SonoData`).
        meta_data_list (MetaDataList): Legacy dataset-level metadata
            (`MetaData`).
        pydvma_version (str): The pydvma version that created the
            DataSet or, for one loaded from a file, the version that
            wrote the file (``'unknown (pre-1.4.0)'`` for an old file
            with no version stamp).
    '''
    def __init__(self,data=None):#,*,timedata=[],freqdata=[],cspecdata=[],tfdata=[],sonodata=[],metadata=[]):
        ## initialisation function to set up DataSet class
        
        self.time_data_list = TimeDataList()
        self.freq_data_list = FreqDataList()
        self.cross_spec_data_list = CrossSpecDataList()
        self.tf_data_list = TfDataList()
        self.modal_data_list = ModalDataList()
        self.sono_data_list = SonoDataList()
        self.meta_data_list = MetaDataList()
        
        if data is not None:
            self.add_to_dataset(data)

        self.pydvma_version = VERSION

    # Names of the per-kind list attributes every DataSet must carry, mapped
    # to the list class that supplies an empty default. Consulted by
    # __setstate__ to normalise pickles written by older pydvma versions.
    # The classes are referenced by name (resolved lazily inside the method)
    # because they are defined AFTER this class in the module.
    _LIST_ATTRS = (
        'time_data_list', 'freq_data_list', 'cross_spec_data_list',
        'tf_data_list', 'modal_data_list', 'sono_data_list', 'meta_data_list',
    )

    def __setstate__(self, state):
        '''Restore a pickled DataSet, filling in lists older versions lacked.

        Unpickling restores only the attributes that were saved, so a
        DataSet written by an older pydvma can lack a list that was added
        later (files from 2019, for example, have no `modal_data_list`).
        Each missing list is created empty, and a file with no version
        stamp gets ``pydvma_version = 'unknown (pre-1.4.0)'``, so files
        saved by pydvma 1.4.0 and earlier keep loading. Called only when
        unpickling, e.g. by `load_data` on a legacy ``.npy`` file.

        Args:
            state (dict): The unpickled attribute dictionary.
        '''
        # Both legacy load paths rely on this: `file.load_data` -> `np.load`,
        # and the browser's legacy import (`glue.legacy_to_dvma` -> `np.load`
        # -> `container.save_bytes`). The rest of the code, `container.save`
        # included, assumes every list is present; without this such a file
        # raised AttributeError: 'DataSet' object has no attribute
        # 'modal_data_list'.
        self.__dict__.update(state)
        list_classes = {
            'time_data_list': TimeDataList,
            'freq_data_list': FreqDataList,
            'cross_spec_data_list': CrossSpecDataList,
            'tf_data_list': TfDataList,
            'modal_data_list': ModalDataList,
            'sono_data_list': SonoDataList,
            'meta_data_list': MetaDataList,
        }
        for name in self._LIST_ATTRS:
            if not hasattr(self, name):
                setattr(self, name, list_classes[name]())
        if not hasattr(self, 'pydvma_version'):
            # Old files predate the version stamp; mark it unknown rather
            # than claiming the current version authored them.
            self.pydvma_version = 'unknown (pre-1.4.0)'

    def add_to_dataset(self,data):
        '''Append one data item, or a homogeneous list of them, to the matching list.

        The item's class picks the list (a `TimeData` goes to
        `time_data_list`, and so on). Items are appended by reference,
        not copied. An object of any other class, and an empty list, are
        ignored without a message.

        Args:
            data (object): A `TimeData`, `FreqData`, `CrossSpecData`,
                `TfData`, `ModalData`, `SonoData` or `MetaData`, or a list
                (a Python list or one of the ``*DataList`` classes) of
                items that are all of one of those classes.

        Raises:
            ValueError: ``data`` is a list of mixed item types.
        '''
        ## find out what kind of data being added
        ## allow input to be list of single type of data, or unit data class
        if not 'list' in data.__class__.__name__.lower():
            # turn into list even if unit length
            data = [data]
        else:
            # check list contains set of same kind of data
            check = True
            for d in data:
                check = check and (d.__class__.__name__ == data[0].__class__.__name__)
            if check is False:
                raise ValueError('Data list needs to contain homogenous type of data')
        if len(data) != 0:
            data_class = data[0].__class__.__name__    
        else:
            data_class = None
            
        #print('')
        if data_class=='TimeData':
            self.time_data_list += data
            #print('{} added to dataset'.format(data))
        elif data_class=='FreqData':
            self.freq_data_list += data
            #print('{} added to dataset'.format(data))
        elif data_class=='CrossSpecData':
            self.cross_spec_data_list += data
            #print('{} added to dataset'.format(data))
        elif data_class=='TfData':
            self.tf_data_list += data
            #print('{} added to dataset'.format(data))
        elif data_class=='ModalData':
            self.modal_data_list += data
            #print('{} added to dataset'.format(data))
        elif data_class=='SonoData':
            self.sono_data_list += data
            #print('{} added to dataset'.format(data))
        elif data_class=='MetaData':
            self.meta_data_list += data
            #print('{} added to dataset'.format(data))
        else:
            pass#print('No data added')
        
    def replace_data_item(self,data,n_set):
        '''Replace the item at one index of the matching list.

        The list is chosen by the class of ``data``, as in
        `add_to_dataset`; an object of any other class is ignored.

        Args:
            data (object): The replacement data item.
            n_set (int): Index, in that list, of the item to replace.

        Raises:
            IndexError: ``n_set`` is out of range for that list.
        '''
        ## replace a specific data item
        ## useful for replacing logged data
        ## useful for replacing reconstructed modal data
        
        data_class = data.__class__.__name__    
            
        if data_class=='TimeData':
            self.time_data_list[n_set] = data
        elif data_class=='FreqData':
            self.freq_data_list[n_set] = data
        elif data_class=='CrossSpecData':
            self.cross_spec_data_list[n_set] = data
        elif data_class=='TfData':
            self.tf_data_list[n_set] = data
        elif data_class=='ModalData':
            self.modal_data_list[n_set] = data
        elif data_class=='SonoData':
            self.sono_data_list[n_set] = data
        elif data_class=='MetaData':
            self.meta_data_list[n_set] = data
        else:
            pass
        
            
    def remove_last_data_item(self,data_class):
        '''Remove the last item of one list, if the list is not empty.

        Args:
            data_class (str): Class name of the items whose list to
                shorten: ``'TimeData'``, ``'FreqData'``,
                ``'CrossSpecData'``, ``'TfData'``, ``'ModalData'``,
                ``'SonoData'`` or ``'MetaData'``. Any other value does
                nothing.
        '''
        
        if data_class == 'TimeData':
            if len(self.time_data_list) != 0:
                del self.time_data_list[-1]
        if data_class == 'FreqData':
            if len(self.freq_data_list) != 0:
                del self.freq_data_list[-1]
        if data_class == 'CrossSpecData':
            if len(self.cross_spec_data_list) != 0:
                del self.cross_spec_data_list[-1]
        if data_class == 'TfData':
            if len(self.tf_data_list) != 0:
                del self.tf_data_list[-1]
        if data_class == 'ModalData':
            if len(self.modal_data_list) != 0:
                del self.modal_data_list[-1]
        if data_class == 'SonoData':
            if len(self.sono_data_list) != 0:
                del self.sono_data_list[-1]
        if data_class == 'MetaData':
            if len(self.meta_data_list) != 0:
                del self.meta_data_list[-1]
                
        #print(self)
                
    def remove_data_item_by_index(self,data_class,list_index):
        '''Remove items from one list by index.

        If any index is out of range, nothing is removed and a message is
        printed.

        Args:
            data_class (str): Class name of the items whose list to
                shorten, as for `remove_last_data_item`.
            list_index (int or list[int] or np.ndarray): Index or indices
                to remove. A list passed here is sorted in place.
        '''
        
        if list_index.__class__.__name__ == 'ndarray':
            list_index = list(list_index)
        elif type(list_index) is int:
            list_index = [list_index]
            
        list_index.sort()

        if data_class == 'TimeData':
            if len(self.time_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.time_data_list[i]
            else:
                print('indices out of range, no data removed')
                
        if data_class == 'FreqData':
            if len(self.freq_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.freq_data_list[i]
            else:
                print('indices out of range, no data removed')
        
        if data_class == 'CrossSpecData':
            if len(self.cross_spec_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.cross_spec_data_list[i]
            else:
                print('indices out of range, no data removed')
                
        if data_class == 'TfData':
            if len(self.tf_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.tf_data_list[i]
            else:
                print('indices out of range, no data removed')
                
        if data_class == 'ModalData':
            if len(self.modal_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.modal_data_list[i]
            else:
                print('indices out of range, no data removed')
                    
        if data_class == 'SonoData':
            if len(self.sono_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.sono_data_list[i]
            else:
                print('indices out of range, no data removed')
                
        if data_class == 'MetaData':
            if len(self.meta_data_list) > np.max(list_index):
                for i in reversed(list_index):
                    del self.meta_data_list[i] 
            else:
                print('indices out of range, no data removed')

        #print(self)
        
    def calculate_fft_set(self,time_range=None,window=None):
        '''Calculate the FFT of every measurement, replacing `freq_data_list`.

        Runs `analysis.calculate_fft` on each item of `time_data_list`.
        The previous contents of `freq_data_list` are discarded, not
        appended to.

        Args:
            time_range (list or np.ndarray or PlotData, optional):
                ``[t_start, t_stop]`` in seconds, applied to every
                measurement; None (the default) uses each whole record.
            window (str, optional): A ``scipy.signal.windows`` name, or
                None (the default) for a rectangular window.
        '''
        if len(self.time_data_list)>0:
            freq_data_list = self.time_data_list.calculate_fft_set(time_range=time_range,window=window)
            self.freq_data_list = freq_data_list
            #self.add_to_dataset(freq_data_list)
        else:
            self.freq_data_list = FreqDataList()
            print('No time data found in dataset')
            
    def calculate_tf_set(self, ch_in=0, time_range=None,window=None,N_frames=1,overlap=0.5):
        '''Calculate the transfer functions of every measurement, replacing `tf_data_list`.

        Runs `analysis.calculate_tf` on each item of `time_data_list`.
        The previous contents of `tf_data_list`, modal reconstructions
        included, are discarded.

        Args:
            ch_in (int): Column index of the input (reference) channel
                (default 0).
            time_range (list or np.ndarray, optional):
                ``[t_start, t_stop]`` in seconds; None (the default) uses
                each whole record.
            window (str, optional): A ``scipy.signal.windows`` name, or
                None (the default) for a rectangular window.
            N_frames (int): Number of averaging frames per measurement
                (default 1).
            overlap (float): Fractional overlap between frames (default
                0.5).
        '''
        if len(self.time_data_list)>0:
            tf_data_list = self.time_data_list.calculate_tf_set(ch_in=ch_in, time_range=time_range, window=window, N_frames=N_frames, overlap=overlap)
            self.tf_data_list = tf_data_list
            #self.add_to_dataset(tf_data_list)
        else:
            self.tf_data_list = TfDataList()
            print('No time data found in dataset')
            
    def calculate_cross_spectrum_matrix_set(self,ch_in=0, time_range=None,window=None,N_frames=1,overlap=0.5):
        '''Calculate the cross-spectrum matrix of every measurement, replacing `cross_spec_data_list`.

        Runs `analysis.calculate_cross_spectrum_matrix` on each item of
        `time_data_list`. The previous contents of
        `cross_spec_data_list` are discarded.

        Args:
            ch_in (int): Accepted for symmetry with `calculate_tf_set`
                and ignored: the matrix covers every channel pair.
            time_range (list or np.ndarray or PlotData, optional):
                ``[t_start, t_stop]`` in seconds; None (the default) uses
                each whole record.
            window (str, optional): A ``scipy.signal.windows`` name,
                e.g. ``'hann'`` for random excitation. None (the default)
                applies no window, which suits impacts.
            N_frames (int): Number of averaging frames per measurement
                (default 1).
            overlap (float): Fractional overlap between frames (default
                0.5).
        '''
        if len(self.time_data_list)>0:
            cross_spec_data_list = self.time_data_list.calculate_cross_spectrum_matrix_set(ch_in=ch_in, time_range=time_range,window=window,N_frames=N_frames,overlap=overlap)
            self.cross_spec_data_list = cross_spec_data_list
            #self.add_to_dataset(cross_spec_data_list)
        else:
            self.cross_spec_data_list = CrossSpecDataList()
            print('No time data found in dataset')
            
    def calculate_tf_averaged(self, ch_in=0, time_range=None,window=None):
        '''Calculate one ensemble-averaged TF from all measurements, replacing `tf_data_list`.

        Runs `analysis.calculate_tf_averaged` on the whole of
        `time_data_list`, treating each measurement as one frame of the
        average, and sets `tf_data_list` to a one-item list holding the
        result.

        Args:
            ch_in (int): Column index of the input (reference) channel
                (default 0).
            time_range (list or np.ndarray, optional):
                ``[t_start, t_stop]`` in seconds, applied to every
                measurement; None (the default) uses each whole record.
            window (str, optional): A ``scipy.signal.windows`` name,
                e.g. ``'hann'`` for random excitation. None (the default)
                applies no window, which suits impacts.
        '''
        if len(self.time_data_list)>0:
            tf_data = self.time_data_list.calculate_tf_averaged(ch_in=ch_in, time_range=time_range ,window=window)
            self.tf_data_list = TfDataList([tf_data])
            #self.add_to_dataset(tf_data)
        else:
            self.tf_data_list = TfDataList()
            print('No time data found in dataset')
            
    def calculate_cross_spectra_averaged(self, time_range=None,window=None):
        '''Calculate one ensemble-averaged cross-spectrum matrix, replacing `cross_spec_data_list`.

        Runs `analysis.calculate_cross_spectra_averaged` on the whole of
        `time_data_list` and sets `cross_spec_data_list` to a one-item
        list holding the result.

        Args:
            time_range (list or np.ndarray, optional):
                ``[t_start, t_stop]`` in seconds, applied to every
                measurement; None (the default) uses each whole record.
            window (str, optional): A ``scipy.signal.windows`` name, or
                None (the default) for a rectangular window.
        '''
        if len(self.time_data_list)>0:
            cross_spec_data = self.time_data_list.calculate_cross_spectra_averaged(time_range=time_range,window=window)
            self.cross_spec_data_list = CrossSpecDataList([cross_spec_data])
            #self.add_to_dataset(cross_spec_data)
        else:
            self.cross_spec_data_list = CrossSpecDataList()
            print('No time data found in dataset')
            
    def calculate_sono_set(self, nperseg=None):
        '''Calculate the sonogram of every measurement, replacing `sono_data_list`.

        Runs `analysis.calculate_sonogram` on each item of
        `time_data_list`. The previous contents of `sono_data_list` are
        discarded.

        Args:
            nperseg (int, optional): STFT segment length in samples;
                None (the default) uses about 1/50 of each record.
        '''
        if len(self.time_data_list)>0:
            sono_data_list = self.time_data_list.calculate_sono_set(nperseg=nperseg)
            self.sono_data_list = sono_data_list
        else:
            self.sono_data_list = SonoDataList()
            print('No time data found in dataset')
            
    def clean_impulse(self,ch_impulse=0):
        '''Return a copy of the DataSet with the hammer channel of every measurement cleaned.

        Runs `analysis.clean_impulse` on each item of `time_data_list`
        and returns a deep copy of the DataSet whose measurements are
        the cleaned versions. This DataSet's data is not changed. The
        copy's other lists (spectra, TFs, and so on) are copied as they
        are and are not recomputed from the cleaned data. A measurement
        that was already cleaned is placed in the copy as the same
        object, not a copy.

        Args:
            ch_impulse (int): Column index of the force (impulse)
                channel in every measurement (default 0).

        Returns:
            dataset (DataSet or None): The cleaned copy, or None (with a
                message) when there is no time data.
        '''
        dataset_copy = copy.deepcopy(self)
        dataset_copy.remove_data_item_by_index('TimeData',np.arange(len(dataset_copy.time_data_list)))
        if len(self.time_data_list)>0:
            for time_data in self.time_data_list:
                td = analysis.clean_impulse(time_data, ch_impulse=ch_impulse)
                dataset_copy.add_to_dataset(td)
            print('returning copy of data with impulses cleaned')
            return dataset_copy
        else:
            print('No time data found in dataset')
            return None
            
    def subset(self, sets):
        '''Return a new DataSet holding chosen measurements and the results derived from them.

        A spectrum, cross-spectrum, transfer function or sonogram is kept
        when it was computed from at least one of the chosen
        measurements, so an ensemble-averaged result comes along if any
        of its source measurements is chosen. A modal fit is kept when
        any of the transfer functions it was fitted to came from a chosen
        measurement. `MetaData`, and derived items whose source is not
        among the chosen measurements (or is missing from the DataSet
        altogether), are left out, even when every index is chosen.

        Items are shared, not copied: the new DataSet's lists hold the
        same objects as this one's, so changing an item through either
        DataSet changes it in both. Take a ``copy.deepcopy`` first if
        you need independent objects. Items keep their original order.

        Args:
            sets (int or Iterable[int]): Index or indices into
                `time_data_list` to keep (0-based). A repeated index
                counts once.

        Returns:
            dataset (DataSet): The new DataSet, with `pydvma_version`
                copied from this one.

        Raises:
            IndexError: ``sets`` contains an index outside
                ``range(len(self.time_data_list))``.
        '''
        # Mirrors the web app's Save "Choose sets..." picker (`subsetDataset`
        # in webui/src/lib/analysis/actions.ts) so a notebook and the browser
        # build the same subset from the same dataset. Matching is by id_link:
        # a scalar id_link (calculate_fft / calculate_tf /
        # calculate_cross_spectrum_matrix / calculate_sonogram / calculate_cwt)
        # matches directly; a LIST id_link (calculate_tf_averaged /
        # calculate_cross_spectra_averaged / calculate_bla, one entry per
        # source) matches on ANY member. ModalData: see `_modal_item_in_subset`
        # (own id_link, scalar or nested list, plus a browser-authored
        # `source_targets` extra). ANY rather than ALL is deliberate: a fit is
        # worth carrying with any set it describes. The web app's own loader
        # is stricter (it re-seeds a live, editable fit only when EVERY
        # source_targets link resolves), so a partial subset carries the modes
        # as data without re-seeding a fit session. Unlike `subsetDataset`
        # there is no "every set picked returns the live document"
        # short-circuit: this always builds a fresh DataSet, so orphans and
        # MetaData are dropped even then.
        n = len(self.time_data_list)
        if isinstance(sets, (int, np.integer)):
            requested = [int(sets)]
        else:
            requested = [int(s) for s in sets]

        valid_range = '0..{}'.format(n - 1) if n > 0 else 'none (this DataSet has no TimeData items)'
        indices = []
        seen = set()
        for idx in requested:
            if idx < 0 or idx >= n:
                raise IndexError(
                    'subset() index {} out of range: this DataSet has {} '
                    'TimeData item(s) (valid indices: {})'.format(idx, n, valid_range))
            if idx not in seen:
                seen.add(idx)
                indices.append(idx)

        chosen_time = [self.time_data_list[i] for i in indices]
        wanted = set(str(td.unique_id) for td in chosen_time)

        new_dataset = DataSet()
        new_dataset.time_data_list = TimeDataList(chosen_time)
        new_dataset.freq_data_list = FreqDataList(
            fd for fd in self.freq_data_list
            if _links_intersect(getattr(fd, 'id_link', None), wanted))
        new_dataset.cross_spec_data_list = CrossSpecDataList(
            cs for cs in self.cross_spec_data_list
            if _links_intersect(getattr(cs, 'id_link', None), wanted))
        new_dataset.tf_data_list = TfDataList(
            tf for tf in self.tf_data_list
            if _links_intersect(getattr(tf, 'id_link', None), wanted))
        new_dataset.sono_data_list = SonoDataList(
            sd for sd in self.sono_data_list
            if _links_intersect(getattr(sd, 'id_link', None), wanted))
        new_dataset.modal_data_list = ModalDataList(
            md for md in self.modal_data_list
            if _modal_item_in_subset(md, wanted))
        new_dataset.meta_data_list = MetaDataList()
        new_dataset.pydvma_version = self.pydvma_version
        return new_dataset

    def save_data(self, filename=None, sets=None, overwrite_without_prompt=False):
        '''Save the DataSet to a file with `file.save_data`.

        Writes the ``.dvma`` container format, adding ``.dvma`` when the
        name ends in neither ``.dvma`` nor ``.npy``; a name ending in
        ``.npy`` writes the legacy pickle format instead. If the file
        already exists you are asked at the terminal whether to
        overwrite it (``y`` overwrites; anything else cancels), unless
        `overwrite_without_prompt` is True, which a scripted re-save
        needs.

        Args:
            filename (str, optional): Output file name. If omitted, a Qt
                file dialog is opened, which needs ``qtpy`` and a Qt
                binding installed separately (pydvma no longer installs
                them), so pass a name in scripts and notebooks.
            sets (int or Iterable[int], optional): If given, saves
                ``self.subset(sets)`` instead of the whole DataSet; see
                `subset`. None (the default) saves everything.
            overwrite_without_prompt (bool, optional): If True, overwrite
                an existing file without asking. Default False.

        Returns:
            filename (str or None): The file written, or None if the save
                was cancelled.
        '''
        savename = file.save_data(self, filename=filename,
                                  overwrite_without_prompt=overwrite_without_prompt,
                                  sets=sets)
        return savename
    
    def export_to_matlab(self, filename=None, overwrite_without_prompt=False):
        '''Export the DataSet to a MATLAB ``.mat`` file with `file.export_to_matlab`.

        The data arrays are written raw (in volts), with the time,
        frequency and TF calibration factors and units alongside; see
        `file.export_to_matlab` for the variable names.

        Args:
            filename (str, optional): Output file name (``.mat`` is added
                if missing). If omitted, a Qt file dialog is opened, which
                needs ``qtpy`` and a Qt binding installed separately.
            overwrite_without_prompt (bool): If False (the default), an
                existing file triggers a y/n question at the terminal.

        Returns:
            filename (str or None): The file written, or None if the
                export was cancelled.
        '''
        savename = file.export_to_matlab(self, filename=filename, overwrite_without_prompt=overwrite_without_prompt)
        return savename
    
    def export_to_matlab_jwlogger(self, filename=None, overwrite_without_prompt=False):
        '''Export the DataSet in Jim Woodhouse's MATLAB logger format.

        Uses `file.export_to_matlab_jwlogger`; the ``.mat`` file can be
        opened by that MATLAB logger.

        Args:
            filename (str, optional): Output file name (``.mat`` is added
                if missing). If omitted, a Qt file dialog is opened, which
                needs ``qtpy`` and a Qt binding installed separately.
            overwrite_without_prompt (bool): If False (the default), an
                existing file triggers a y/n question at the terminal.

        Returns:
            filename (str or None): The file written, or None if the
                export was cancelled.
        '''
        savename = file.export_to_matlab_jwlogger(self, filename=filename, overwrite_without_prompt=overwrite_without_prompt)
        return savename
    
    def plot_time_data(self,sets='all',channels='all'):
        '''Plot `time_data_list` in a new matplotlib figure.

        Each channel is multiplied by its `channel_cal_factors`. Lines
        outside ``sets`` / ``channels`` are drawn faint; clicking a
        legend entry toggles a line between faint and full.

        Args:
            sets (str or list[int]): ``'all'`` (the default) or the set
                indices to highlight.
            channels (str or list[int]): ``'all'`` (the default) or the
                channel indices to highlight in every set.

        Returns:
            plot (PlotData): The plot; ``plot.fig`` and ``plot.ax`` are
                its matplotlib Figure and Axes. Pass it as ``time_range``
                to `calculate_fft_set` (or `analysis.calculate_fft`) to
                analyse the time range currently shown.
        '''
        from . import plotting
        global pt
        pt = plotting.PlotData(window_title='Time Data')
        pt.update(self.time_data_list,sets=sets,channels=channels)
        return pt

    def plot_freq_data(self,sets='all',channels='all'):
        '''Plot `freq_data_list` as calibrated magnitude in dB in a new figure.

        Lines outside ``sets`` / ``channels`` are drawn faint; clicking a
        legend entry toggles a line. Other views (linear, real,
        imaginary, phase, Nyquist) are available through
        `PlotData.update`.

        Args:
            sets (str or list[int]): ``'all'`` (the default) or the set
                indices to highlight.
            channels (str or list[int]): ``'all'`` (the default) or the
                channel indices to highlight in every set.

        Returns:
            plot (PlotData): The plot; ``plot.fig`` and ``plot.ax`` are
                its matplotlib Figure and Axes.
        '''
        from . import plotting
        global pf
        pf = plotting.PlotData(window_title='Frequency Data')
        pf.update(self.freq_data_list,sets=sets,channels=channels)
        return pf

    def plot_tf_data(self,sets='all',channels='all'):
        '''Plot `tf_data_list` as calibrated magnitude in dB in a new figure.

        Coherence is drawn dotted on a second y-axis (``plot.ax2``),
        unless every set's coherence is missing or identically 1. Modal
        reconstructions are labelled ``fit``. NaN values in a set's
        ``tf_coherence`` are replaced by 1 in place when plotted.

        Args:
            sets (str or list[int]): ``'all'`` (the default) or the set
                indices to highlight.
            channels (str or list[int]): ``'all'`` (the default) or the
                channel indices to highlight in every set.

        Returns:
            plot (PlotData): The plot; ``plot.fig``, ``plot.ax`` and
                ``plot.ax2`` are its matplotlib Figure, main Axes and
                coherence Axes.
        '''
        from . import plotting
        global ptf
        ptf = plotting.PlotData(window_title='Transfer Function Data')
        ptf.update(self.tf_data_list,sets=sets,channels=channels)
        return ptf

    def plot_sono_data(self,n_set=0, n_chan=0, db_range=60):
        '''Plot one channel of one sonogram as a colour map in a new figure.

        The magnitude is shown in dB. Exact zeros in that channel's
        `sono_data` are replaced by 1e-16 in place, to avoid taking the
        log of zero.

        Args:
            n_set (int): Index into `sono_data_list` (default 0).
            n_chan (int): Channel (plane) index within that sonogram
                (default 0).
            db_range (float): Colour-scale range in dB below the maximum
                (default 60).

        Returns:
            plot (PlotData): The plot; ``plot.fig`` and ``plot.ax`` are
                its matplotlib Figure and Axes.
        '''
        from . import plotting
        global ptf
        ptf = plotting.PlotData(window_title='Sonogram Data')
        ptf.update_sonogram(self.sono_data_list,n_set=n_set,n_chan=n_chan, db_range=db_range)
        return ptf
    
    def __repr__(self):
        template = "{:>24}: {}"
        dataset_dict = self.__dict__
        text = '\n<DataSet> class:\n\n'
        for attr in dataset_dict:
            N = len(dataset_dict[attr])
            if N <= 3:
                text += template.format(attr,dataset_dict[attr])
                text += '\n'
            elif attr == 'pydvma_version':
                pass#text += template.format('pydvma_version',str(self.pydvma_version))
            else:
                text += template.format(attr,'[' + str(dataset_dict[attr][0]) + ',... (x' + str(N) + ')]')
                text += '\n'
        
        return text
    
class TimeDataList(list):
    '''A list of `TimeData` measurements: a DataSet's `time_data_list`.

    An ordinary Python list with methods that run an analysis over every
    item, and that read or set the items' calibration factors.
    '''
    ### This will allow functions to be discovered that can take lists of TimeData is arguments
    def calculate_fft_set(self,time_range=None,window=None):
        '''Calculate the FFT of every item.

        Args:
            time_range (list or np.ndarray or PlotData, optional):
                ``[t_start, t_stop]`` in seconds; None (the default) uses
                each whole record. See `analysis.calculate_fft`.
            window (str, optional): A ``scipy.signal.windows`` name, or
                None (the default) for a rectangular window.

        Returns:
            freq_data_list (FreqDataList): One `FreqData` per item, in
                order.
        '''
        freq_data_list = FreqDataList()
        
        for td in self:
            freq_data = analysis.calculate_fft(td, time_range=time_range, window=window)
            freq_data_list += [freq_data]
            
        return freq_data_list
    
    
    def calculate_tf_set(self, ch_in=0, time_range=None,window=None,N_frames=1,overlap=0.5):
        '''Calculate the transfer functions of every item.

        Args:
            ch_in (int): Column index of the input (reference) channel
                (default 0).
            time_range (list or np.ndarray, optional):
                ``[t_start, t_stop]`` in seconds; None (the default) uses
                each whole record.
            window (str, optional): A ``scipy.signal.windows`` name, or
                None (the default) for a rectangular window.
            N_frames (int): Number of averaging frames per item (default
                1).
            overlap (float): Fractional overlap between frames (default
                0.5).

        Returns:
            tf_data_list (TfDataList): One `TfData` per item, in order,
                from `analysis.calculate_tf`.
        '''
        tf_data_list = TfDataList()
        
        for td in self:
            tf_data = analysis.calculate_tf(td, ch_in=ch_in, time_range=time_range,window=window,N_frames=N_frames,overlap=overlap)
            tf_data_list += [tf_data]
            
        return tf_data_list
    
    def calculate_cross_spectrum_matrix_set(self, ch_in=0, time_range=None,window=None,N_frames=1,overlap=0.5):
        '''Calculate the cross-spectrum matrix of every item.

        Args:
            ch_in (int): Accepted for symmetry with `calculate_tf_set`
                and ignored: the matrix covers every channel pair.
            time_range (list or np.ndarray or PlotData, optional):
                ``[t_start, t_stop]`` in seconds; None (the default) uses
                each whole record.
            window (str, optional): A ``scipy.signal.windows`` name, or
                None (the default) for a rectangular window.
            N_frames (int): Number of averaging frames per item (default
                1).
            overlap (float): Fractional overlap between frames (default
                0.5).

        Returns:
            cross_spec_data_list (CrossSpecDataList): One `CrossSpecData`
                per item, in order, from
                `analysis.calculate_cross_spectrum_matrix`.
        '''
        cross_spec_data_list = CrossSpecDataList()
        
        for td in self:
            cross_spec_data = analysis.calculate_cross_spectrum_matrix(td, time_range=time_range,window=window,N_frames=N_frames,overlap=overlap)
            cross_spec_data_list += [cross_spec_data]
            
        return cross_spec_data_list
    
    
    def calculate_tf_averaged(self, ch_in=0, time_range=None,window=None):
        '''Calculate one TF averaged across all items with `analysis.calculate_tf_averaged`.

        Args:
            ch_in (int): Column index of the input (reference) channel
                (default 0).
            time_range (list or np.ndarray, optional):
                ``[t_start, t_stop]`` in seconds, applied to every item;
                None (the default) uses each whole record.
            window (str, optional): A ``scipy.signal.windows`` name,
                e.g. ``'hann'`` for random excitation. None (the default)
                applies no window, which suits impacts.

        Returns:
            tf_data (TfData): The ensemble-averaged transfer functions.
        '''
        tf_data = analysis.calculate_tf_averaged(self,ch_in=ch_in, time_range=time_range,window=window)
            
        return tf_data
    
    
    def calculate_cross_spectra_averaged(self, time_range=None,window=None):
        '''Calculate one cross-spectrum matrix averaged across all items.

        Uses `analysis.calculate_cross_spectra_averaged`.

        Args:
            time_range (list or np.ndarray, optional):
                ``[t_start, t_stop]`` in seconds, applied to every item;
                None (the default) uses each whole record.
            window (str, optional): A ``scipy.signal.windows`` name, or
                None (the default) for a rectangular window.

        Returns:
            cross_spec_data (CrossSpecData): The ensemble average.
        '''
        cross_spec_data = analysis.calculate_cross_spectra_averaged(self, time_range=time_range,window=window)
            
        return cross_spec_data
    
    def calculate_sono_set(self, nperseg=None):
        '''Calculate the sonogram of every item.

        Args:
            nperseg (int, optional): STFT segment length in samples;
                None (the default) uses about 1/50 of each record.

        Returns:
            sono_data_list (SonoDataList): One `SonoData` per item, in
                order, from `analysis.calculate_sonogram`.
        '''
        sono_data_list = SonoDataList()
        
        for td in self:
            sono_data = analysis.calculate_sonogram(td,nperseg=nperseg)
            sono_data_list += [sono_data]
            
        return sono_data_list
    
    def get_calibration_factors(self):
        '''Return every item's `channel_cal_factors`.

        Returns:
            factors (list): One per-channel array per item, in order.
                These are the items' own arrays, not copies, so changing
                an element changes the item.
        '''
        n_set = len(self)
        factors = []
        for ns in range(n_set):
            factors.append(self[ns].channel_cal_factors)
        
        return factors
            
    def set_calibration_factors_all(self,factors):
        '''Set every item's `channel_cal_factors` at once.

        Args:
            factors (list): One per-channel array per item, in order, as
                returned by `get_calibration_factors`. Item ``i`` is given
                ``factors[i]`` itself (not a copy).

        Raises:
            IndexError: ``factors`` has fewer entries than the list.
        '''
        n_set = len(self)
        for ns in range(n_set):
            self[ns].channel_cal_factors=factors[ns]
            
    def set_calibration_factor(self,factor, n_set=0, n_chan=0):
        '''Set the calibration factor of one channel of one item, in place.

        Prints a message and changes nothing if the list is empty or an
        index is out of range.

        Args:
            factor (float): The new factor (volts to engineering units).
            n_set (int): Index of the item in the list (default 0).
            n_chan (int): Channel (column) index within that item
                (default 0).
        '''
        if len(self) == 0:
            print('<TimeDataList> is empty. First log data, load data, or create test data.')
        elif n_set >= len(self):
            print('<TimeDataList> has {} set(s) of <TimeData>. Set requested (index={}) exceeds number of sets. Note indexing starts at 0.'.format(len(self),n_set))
        elif n_chan >= len(self[n_set].time_data[0,:]):
            print('<TimeDataList>[{}] has {} channel(s). Channel requested (index={}) exceeds number of channels. Note indexing starts at 0.'.format(n_set,len(self[n_set].time_data[0,:]),n_chan))
        else:
            self[n_set].channel_cal_factors[n_chan]=factor
    
    def export_to_csv(self, filename=None, overwrite_without_prompt=False):
        '''Export the time data to a CSV file with `file.export_to_csv`.

        The numbers are written raw (uncalibrated); a ``#``-commented
        header line carries each column's calibration factor and units.
        See `file.export_to_csv` for the column layout.

        Args:
            filename (str, optional): Output file name (``.csv`` is added
                if missing). If omitted, a Qt file dialog is opened, which
                needs ``qtpy`` and a Qt binding installed separately.
            overwrite_without_prompt (bool): If False (the default), an
                existing file triggers a y/n question at the terminal.

        Returns:
            filename (str or None): The file written, or None if the
                export was cancelled.
        '''
        savename = file.export_to_csv(self,filename=filename,overwrite_without_prompt=overwrite_without_prompt)
        return savename

class FreqDataList(list):
    '''A list of `FreqData` spectra: a DataSet's `freq_data_list`.

    An ordinary Python list with methods that read or set the items'
    calibration factors and export them to CSV.
    '''
    ### This will allow functions to be discovered that can take lists of FreqData is arguments
    def get_calibration_factors(self):
        '''Return every item's `channel_cal_factors`.

        Returns:
            factors (list): One per-channel array per item, in order.
                These are the items' own arrays, not copies, so changing
                an element changes the item.
        '''
        n_set = len(self)
        factors = []
        for ns in range(n_set):
            factors.append(self[ns].channel_cal_factors)
        
        return factors
    
    def set_calibration_factors_all(self,factors):
        '''Set every item's `channel_cal_factors` at once.

        Args:
            factors (list): One per-channel array per item, in order, as
                returned by `get_calibration_factors`. Item ``i`` is given
                ``factors[i]`` itself (not a copy).

        Raises:
            IndexError: ``factors`` has fewer entries than the list.
        '''
        n_set = len(self)
        for ns in range(n_set):
            self[ns].channel_cal_factors=factors[ns]
            
    def set_calibration_factor(self,factor, n_set=0, n_chan=0):
        '''Set the calibration factor of one channel of one item, in place.

        Prints a message and changes nothing if the list is empty or an
        index is out of range.

        Args:
            factor (float): The new factor (volts to engineering units).
            n_set (int): Index of the item in the list (default 0).
            n_chan (int): Channel (column) index within that item
                (default 0).
        '''
        if len(self) == 0:
            print('<FreqDataList> is empty. First calculate FFT.')
        elif n_set >= len(self):
            print('<FreqDataList> has {} set(s) of <FreqData>. Set requested (index={}) exceeds number of sets. Note indexing starts at 0.'.format(len(self),n_set))
        elif n_chan >= len(self[n_set].freq_data[0,:]):
            print('<FreqDataList>[{}] has {} channel(s). Channel requested (index={}) exceeds number of channels. Note indexing starts at 0.'.format(n_set,len(self[n_set].freq_data[0,:]),n_chan))
        else:
            self[n_set].channel_cal_factors[n_chan]=factor
            
    def export_to_csv(self, filename=None, overwrite_without_prompt=False):
        '''Export the spectra to a CSV file with `file.export_to_csv`.

        The numbers are written raw (uncalibrated); a ``#``-commented
        header line carries each column's calibration factor and units.
        See `file.export_to_csv` for the column layout.

        Args:
            filename (str, optional): Output file name (``.csv`` is added
                if missing). If omitted, a Qt file dialog is opened, which
                needs ``qtpy`` and a Qt binding installed separately.
            overwrite_without_prompt (bool): If False (the default), an
                existing file triggers a y/n question at the terminal.

        Returns:
            filename (str or None): The file written, or None if the
                export was cancelled.
        '''
        savename = file.export_to_csv(self,filename=filename,overwrite_without_prompt=overwrite_without_prompt)
        return savename

class CrossSpecDataList(list):
    '''A list of `CrossSpecData` items: a DataSet's `cross_spec_data_list`.

    An ordinary Python list; it adds no methods.
    '''
    ### This will allow functions to be discovered that can take lists of CrossSpecData is arguments
    pass

class TfDataList(list):
    '''A list of `TfData` transfer functions: a DataSet's `tf_data_list`.

    An ordinary Python list with methods that read or set the items'
    calibration factors, manage a modal reconstruction and export to
    CSV. The modal fitting functions in `pydvma.modal` take one.
    '''
    ### This will allow functions to be discovered that can take lists of TfData is arguments
    def get_calibration_factors(self):
        '''Return every item's `channel_cal_factors`.

        Returns:
            factors (list): One per-channel array per item, in order.
                These are the items' own arrays, not copies, so changing
                an element changes the item. For a TF each factor is the
                ratio ``cal[out] / cal[in]``.
        '''
        n_set = len(self)
        factors = []
        for ns in range(n_set):
            factors.append(self[ns].channel_cal_factors)
        
        return factors
    
    def set_calibration_factors_all(self,factors):
        '''Set every item's `channel_cal_factors` at once.

        Args:
            factors (list): One per-channel array per item, in order, as
                returned by `get_calibration_factors`. Item ``i`` is given
                ``factors[i]`` itself (not a copy). For a TF each factor
                is the ratio ``cal[out] / cal[in]``.

        Raises:
            IndexError: ``factors`` has fewer entries than the list.
        '''
        n_set = len(self)
        for ns in range(n_set):
            self[ns].channel_cal_factors=factors[ns]
            
    def set_calibration_factor(self,factor, n_set=0, n_chan=0):
        '''Set the calibration factor of one channel of one item, in place.

        Prints a message and changes nothing if the list is empty or an
        index is out of range.

        Args:
            factor (float): The new factor, the ratio
                ``cal[out] / cal[in]`` for a TF.
            n_set (int): Index of the item in the list (default 0).
            n_chan (int): Channel (column) index within that item
                (default 0).
        '''
        if len(self) == 0:
            print('<TfDataList> is empty. First calculate transfer function.')
        elif n_set >= len(self):
            print('<TfDataList> has {} set(s) of <TfData>. Set requested (index={}) exceeds number of sets. Note indexing starts at 0.'.format(len(self),n_set))
        elif n_chan >= len(self[n_set].tf_data[0,:]):
            print('<TfDataList>[{}] has {} channel(s). Channel requested (index={}) exceeds number of channels. Note indexing starts at 0.'.format(n_set,len(self[n_set].tf_data[0,:]),n_chan))
        else:
            self[n_set].channel_cal_factors[n_chan]=factor
    
    def add_modal_reconstruction(self,tf_data,mode='replace'):
        '''Add a modal reconstruction TF to the list, or replace the existing one.

        If no item is a reconstruction (``flag_modal_TF`` True),
        ``tf_data`` is appended. Otherwise ``mode='replace'`` overwrites
        the LAST item of the list (so the reconstruction is assumed to be
        last) and ``mode='append'`` appends; any other mode then does
        nothing.

        Args:
            tf_data (TfData): The reconstruction, for example from
                `modal.reconstruct_transfer_function`.
            mode (str): ``'replace'`` (the default) or ``'append'``.
        '''
        # identify number of TFs in list that are reconstructions
        N_reconstruction = 0
        for tf in self:
            if tf.flag_modal_TF == True:
                N_reconstruction += 1
                
        # append / replace reconstruction TFs
        if N_reconstruction == 0:
            self += [tf_data]
        elif mode == 'replace':
            self[-1] = tf_data
        elif mode == 'append':
            self += [tf_data]
            
        
    def export_to_csv(self, filename=None, overwrite_without_prompt=False):
        '''Export the transfer functions to a CSV file with `file.export_to_csv`.

        The numbers are written raw (uncalibrated); a ``#``-commented
        header line carries each column's calibration factor and units.
        See `file.export_to_csv` for the column layout.

        Args:
            filename (str, optional): Output file name (``.csv`` is added
                if missing). If omitted, a Qt file dialog is opened, which
                needs ``qtpy`` and a Qt binding installed separately.
            overwrite_without_prompt (bool): If False (the default), an
                existing file triggers a y/n question at the terminal.

        Returns:
            filename (str or None): The file written, or None if the
                export was cancelled.
        '''
        savename = file.export_to_csv(self,filename=filename,overwrite_without_prompt=overwrite_without_prompt)
        return savename
      
class ModalDataList(list):
    '''A list of `ModalData` fits: a DataSet's `modal_data_list`.

    An ordinary Python list; it adds no methods.
    '''
    ### This will allow functions to be discovered that can take lists of ModalData is arguments
    pass

class SonoDataList(list):
    '''A list of `SonoData` sonograms: a DataSet's `sono_data_list`.

    An ordinary Python list; it adds no methods.
    '''
    ### This will allow functions to be discovered that can take lists of SonoData is arguments
    pass

class MetaDataList(list):
    '''A list of `MetaData` items: a DataSet's `meta_data_list`.

    An ordinary Python list; it adds no methods.
    '''
    ### This will allow functions to be discovered that can take lists of MetaData is arguments
    pass

        
class TimeData():
    '''One block of acquired time-series data plus its acquisition metadata.

    Held inside a `DataSet.time_data_list`. Produced by `log_data`,
    by the test-data factories in `testdata`, and on import from
    Matlab. The numeric content is **in volts** (see "Voltage-Based
    I/O" in the user-guide acquisition page); apply
    `channel_cal_factors` to convert to engineering units at display
    or fit time. `analysis.calculate_*` functions copy `units` and
    `channel_cal_factors` onto their derived FreqData / TfData /
    CrossSpecData / SonoData outputs.

    Attributes:
        time_axis (np.ndarray): 1D sample times in seconds.
        time_data (np.ndarray): Shape ``(n_samples, n_channels)`` voltage samples.
        settings (MySettings): Snapshot of the acquisition configuration.
        timestamp (datetime.datetime): Capture start time.
        timestring (str): Filesystem-safe rendering of `timestamp`.
        units (list[str] or None): Engineering units per channel
            (e.g. ``['N', 'm/s', 'g']``). None if unset.
        channel_cal_factors (np.ndarray): Per-channel multipliers from
            volts to engineering units. Defaults to all-ones.
        id_link: Reference to a source TimeData (used when this object
            is derived rather than freshly acquired).
        test_name (str or None): Free-form label, displayed in plots.
        unique_id (uuid.UUID): Generated at construction; used by derived
            objects to link back to their source via `id_link`.
    '''

    def __init__(self,time_axis,time_data,settings,timestamp=None,timestring=None,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        
        time_data = reshape_arrays(time_data)
        if channel_cal_factors is None:
            channel_cal_factors = np.ones(len(time_data[0,:]))
        
        if timestamp is None:
            t = datetime.datetime.now()
            timestamp = t
            timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
        
        self.time_axis = time_axis
        self.time_data = time_data  
        self.settings = settings
        self.timestamp = timestamp
        self.timestring = timestring
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # this is used if data is derived from an existing <TimeData> measurement
        self.test_name = test_name
        self.unique_id = uuid.uuid4()
        
        
        
    def __repr__(self):
        return "<TimeData>"

        
class FreqData():
    '''One-sided complex frequency spectrum of a `TimeData` capture.

    Produced by `analysis.calculate_fft`. The spectrum is the raw
    `np.fft.rfft` of the (optionally windowed) time data — i.e. it is
    **not** scaled to a PSD or amplitude spectrum; consumers that need
    PSD should square the magnitude themselves. `units` and
    `channel_cal_factors` are copied verbatim from the source TimeData.

    Attributes:
        freq_axis (np.ndarray): Frequency bins in Hz (length ``N//2+1``).
        freq_data (np.ndarray): Shape ``(n_freq, n_channels)`` complex
            spectrum, one column per channel.
        settings (MySettings): Snapshot of the analysis configuration
            (includes the window choice and the time range that was used).
        units (list[str] or None): Engineering units per channel.
        channel_cal_factors (np.ndarray): Per-channel multipliers from
            volts to engineering units; applied at display time.
        id_link (uuid.UUID): `unique_id` of the source TimeData.
        unique_id (uuid.UUID): This item's own identity, minted at
            construction. It is what makes a pull → modify → push round
            trip through `pydvma.session.Session` REPLACE this
            result in place instead of appending a second copy beside
            it. Optional in the container: a file written before
            derived items carried ids restores without the attribute.
        test_name (str or None): Free-form label.
        timestamp (datetime.datetime): When this FreqData was constructed.
        timestring (str): Filesystem-safe rendering of `timestamp`.
        source_signature (str): OPTIONAL, set post-construction by
            `analysis.calculate_fft` — a 16-hex-character hash of the
            SOURCE samples and rate (`pydvma._signature`), so a loaded
            file can tell an intact compute chain from one whose time
            data changed after the compute. Genuinely optional (needs a
            `hasattr` guard): items written before signatures existed
            make no claim about their chain.
        source_settings (dict): OPTIONAL, set alongside
            `source_signature` — the analysis knobs that call used, as
            JSON-safe scalars, so the result is self-describing. A
            settings change does NOT invalidate a stored result; only a
            source-sample change does.
    '''

    def __init__(self,freq_axis,freq_data,settings,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        
        freq_data = reshape_arrays(freq_data)
        if channel_cal_factors is None:
            channel_cal_factors = np.ones(len(freq_data[0,:]))
        
        self.freq_axis = freq_axis
        self.freq_data = freq_data
        self.settings = settings
        self.test_name = test_name
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # used to link data to specific <TimeData> object
        t = datetime.datetime.now()
        self.timestamp = t
        self.timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
        # Own identity, like TimeData's: Session.push merges by unique_id,
        # so a derived item without one appends a duplicate on every push.
        self.unique_id = uuid.uuid4()

    def __repr__(self):
        return "<FreqData>"
    
    
class CrossSpecData():
    '''Full cross-spectrum matrix Pxy[i,j,f] and coherence matrix Cxy[i,j,f].

    Produced by `analysis.calculate_cross_spectrum_matrix` (single
    TimeData) or `analysis.calculate_cross_spectra_averaged` (ensemble
    TimeDataList). The diagonal `Pxy[i, i, :]` is the per-channel
    auto-spectrum (= scipy.signal.welch with ``scaling='spectrum'``);
    off-diagonal `Pxy[i, j, :]` matches scipy.signal.csd with the same
    settings. Pxy is Hermitian — `Pxy[j, i, :] = conj(Pxy[i, j, :])`.

    Attributes:
        freq_axis (np.ndarray): One-sided frequency bins in Hz.
        Pxy (np.ndarray): Shape ``(n_channels, n_channels, n_freq)``,
            complex. Cross-spectrum matrix.
        Cxy (np.ndarray): Same shape, real, in [0, 1]. Coherence matrix.
        settings (MySettings): Includes `window`, `time_range`,
            `N_frames`, `overlap` actually used.
        units (list[str] or None): Engineering units per channel.
        channel_cal_factors (np.ndarray): Per-channel multipliers from
            volts to engineering units. Defaults to all-ones. These are
            AMPLITUDE factors per channel, so a consumer combines them for
            the quantity it wants: the auto-spectrum ``Pxy[i, i]`` is a
            power and takes ``cal[i]**2``, while the cross-spectrum
            ``Pxy[i, j]`` takes ``cal[i] * cal[j]``. ``Cxy`` is a
            normalised ratio and is calibration-INVARIANT — never scale it.
        enbw_hz (float or None): Effective noise bandwidth of the window
            in Hz, ``fs * sum(w**2) / sum(w)**2``. `Pxy` is a power
            SPECTRUM (scipy ``scaling='spectrum'``), whose level scales
            with the frequency resolution; dividing by this converts it
            to a spectral DENSITY, whose level does not:
            ``density = Pxy / enbw_hz``. None on an object built before
            this was recorded, or by hand.
        id_link: `unique_id` of the source TimeData (or list of
            ids when averaged across a TimeDataList).
        unique_id (uuid.UUID): This item's own identity, minted at
            construction — see `FreqData.unique_id` for why a derived
            item needs one.
        test_name (str or None): Free-form label.
        timestamp (datetime.datetime): When constructed.
        timestring (str): Filesystem-safe rendering of `timestamp`.
    '''

    def __init__(self,freq_axis,Pxy,Cxy,settings,units=None,channel_cal_factors=None,id_link=None,test_name=None,enbw_hz=None):
        
        # Default to identity, like TimeData / FreqData / TfData. Leaving this
        # as None made CrossSpecData the one exception to "an absent
        # calibration is all-ones", so a consumer indexing the array had to
        # special-case this class alone.
        if channel_cal_factors is None:
            channel_cal_factors = np.ones(np.shape(Pxy)[0])
        
        self.freq_axis = freq_axis
        self.Pxy = Pxy
        self.Cxy = Cxy
        self.enbw_hz = enbw_hz
        self.settings = settings
        self.test_name = test_name
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # used to link data to specific <TimeData> object
        t = datetime.datetime.now()
        self.timestamp = t
        self.timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
        # Own identity, like TimeData's — see FreqData.unique_id.
        self.unique_id = uuid.uuid4()

    def __repr__(self):
        return "<CrossSpecData>"
    
        
class TfData():
    '''Transfer function H(f) from one input channel to one or more outputs.

    Produced by `analysis.calculate_tf` (single TimeData),
    `analysis.calculate_tf_averaged` (ensemble TimeDataList) or
    `analysis.calculate_bla` (a best-linear-approximation run). For the
    first two the convention is `Pxy[in, out] / Pxy[in, in]` per output
    channel and `tf_coherence` carries the corresponding coherence.

    **BLA sets are different**: no cross-spectrum estimator is involved
    at all — the FRF comes from inverting the excitation matrix at each
    excited bin — so the `Pxy` convention does not describe them,
    `tf_coherence` is None (the `bla_sigma_*` pair is the quality
    measure instead), `settings.ch_in` may be None (commanded-drive
    mode has no measured input channel), and `freq_axis` holds only the
    excited bins rather than a full rfft grid. `bla` is non-None exactly
    on those sets.

    Calibration: `channel_cal_factors[k]` holds the **ratio**
    ``cal[out_k] / cal[in]`` — i.e. multiplying `tf_data[:, k] *
    channel_cal_factors[k]` at display time gives the TF in
    engineering units. Units are constructed as
    ``"<out_unit>/<in_unit>"`` per output channel.

    Attributes:
        freq_axis (np.ndarray): One-sided frequency bins in Hz.
        tf_data (np.ndarray): Shape ``(n_freq, n_outputs)``, complex.
            One column per non-input channel.
        tf_coherence (np.ndarray): Same shape, real, in [0, 1].
        settings (MySettings): Snapshot including the chosen `ch_in`
            and the derived `ch_out_set` (the channel indices in
            `tf_data`'s second axis).
        units (list[str] or None): Per-output-channel unit strings
            (e.g. ``['m/s/N', 'g/N']``).
        channel_cal_factors (np.ndarray): Per-output cal *ratios*
            (cal[out] / cal[in]). A manual override here overwrites
            the inherited ratio.
        id_link: `unique_id` of the source TimeData (or list when averaged).
        unique_id (uuid.UUID): This item's own identity, minted at
            construction — see `FreqData.unique_id` for why a derived
            item needs one.
        test_name (str or None): Free-form label.
        timestamp (datetime.datetime): When constructed.
        timestring (str): Filesystem-safe rendering of `timestamp`.
        flag_modal_TF (bool): True when this TfData is a modal
            reconstruction (from `modal.reconstruct_transfer_function`
            or `modal.reconstruct_transfer_function_global`) rather than
            a measurement. The modal fits skip such items.
        bla_sigma_nl (np.ndarray or None): Nonlinear-distortion standard
            deviation, shape ``(n_freq, n_outputs)``, real, in the same
            linear units as ``abs(tf_data)`` — a std, not a variance, so
            it goes straight onto a dB axis with no further square root.
            PER-REALISATION: it is the distortion level of one
            realisation, not the error bar on `tf_data`, which is
            ``sqrt(M)`` smaller. Set by `analysis.calculate_bla`; None on
            an ordinary transfer function.
        bla_sigma_n (np.ndarray or None): Measurement-noise standard
            deviation, same shape, units and per-realisation reading as
            `bla_sigma_nl`. Set by `analysis.calculate_bla`; None on an
            ordinary transfer function.
        bla (dict or None): The BLA run spec that produced this
            estimate (multisine design, x-mode, channel roles, capture
            fs, excited bins and which excitation ``q`` this TfData
            belongs to). JSON-clean scalars only, so it round-trips
            through the .dvma manifest. None on an ordinary transfer
            function.
        source_signature (str): OPTIONAL, set post-construction by
            `analysis.calculate_tf` / `analysis.calculate_tf_averaged` —
            a 16-hex-character hash of the SOURCE samples and rate
            (`pydvma._signature`; for an ensemble, every source in list
            order), so a loaded file can tell an intact compute chain
            from one whose time data changed after the compute.
            Genuinely optional (needs a `hasattr` guard): items written
            before signatures existed, and BLA estimates, carry no
            signature and make no claim about their chain.
        source_settings (dict): OPTIONAL, set alongside
            `source_signature` — the analysis knobs that call used, as
            JSON-safe scalars, so the result is self-describing. A
            settings change does NOT invalidate a stored result; only a
            source-sample change does.

    All three BLA attributes are set in `__init__` and are declared
    container fields, so they survive a .dvma round trip as None or as
    their value — no `hasattr` guard needed, unlike the genuinely
    optional `iw_power_counter`.
    '''

    def __init__(self,freq_axis,tf_data,tf_coherence,settings,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        
        tf_data = reshape_arrays(tf_data)
        if channel_cal_factors is None:
            channel_cal_factors = np.ones(len(tf_data[0,:]))
        
        self.freq_axis = freq_axis
        self.tf_data = tf_data
        self.tf_coherence = tf_coherence
        self.settings = settings
        self.test_name = test_name
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # used to link data to specific <TimeData> object
        t = datetime.datetime.now()
        self.timestamp = t
        self.timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
        self.flag_modal_TF = False
        # Best-linear-approximation extras (analysis.calculate_bla), None
        # for every ordinary transfer function. All three are declared
        # container fields (two arrays + one meta), so they always
        # restore from .dvma rather than going absent.
        self.bla_sigma_nl = None
        self.bla_sigma_n = None
        self.bla = None
        # Own identity, like TimeData's — see FreqData.unique_id.
        self.unique_id = uuid.uuid4()

    def __repr__(self):
        return "<TfData>"
    
    
class ModalData():
    '''A set of fitted modes — each row of `M` is one mode's
    `(fn, zn, an[chan...], pn[chan...], rk[chan...], rm[chan...])`
    parameter vector as produced by
    `modal.modal_fit_all_channels`.

    Use `add_mode` to append further modes (e.g. across separate
    frequency-band fits); rows are kept sorted by `fn`. After any
    add/delete, the summary arrays `fn`, `zn`, `an`, `pn` are
    refreshed and indexable per mode.

    Attributes:
        M (np.ndarray): Shape ``(n_modes, 2 + 4*n_channels)``. Each row
            packs ``[fn, zn, an_0..an_C, pn_0..pn_C, rk_0..rk_C,
            rm_0..rm_C]``.
        fn (np.ndarray): Per-mode natural frequencies in Hz.
        zn (np.ndarray): Per-mode damping ratios.
        an (np.ndarray): Shape ``(n_modes, n_channels)`` modal-constant
            amplitudes.
        pn (np.ndarray): Same shape; modal-constant phases in radians.
        channels (int): Number of channels (= `n_channels` above).
        settings (MySettings): Snapshot including the source TF's settings.
        units: Engineering units (passed through from source).
        id_link: `unique_id`(s) of the TFs that produced these modes.
        unique_id (uuid.UUID): This item's own identity, minted at
            construction — see `FreqData.unique_id`. Modal fits are
            pushed back from notebooks like any other item, and without
            an id every push would append another copy of the fit.
        test_name (str or None): Free-form label.
    '''

    def __init__(self,xn=None,settings=None,units=None,id_link=None,test_name=None):
        
        self.M = []
        self.test_name = test_name
        # Own copy: add_mode/delete_mode rewrite settings.channels, and
        # the caller's settings (typically the source TfData's) must not
        # be mutated through the shared reference.
        self.settings = copy.copy(settings) if settings is not None else None
        self.channels = 0
        if settings is not None:
            self.settings.channels = 0
        self.units = units
        self.id_link = id_link # used to link data to specific <TimeData> object
        t = datetime.datetime.now()
        self.timestamp = t
        self.timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
        # Own identity, like TimeData's — see FreqData.unique_id.
        self.unique_id = uuid.uuid4()

        if xn is not None:
            self.add_mode(xn)


    def add_mode(self,xn):
        '''Add one mode to the modal matrix `M`.

        Rows stay sorted by natural frequency, and the summaries `fn`,
        `zn`, `an` and `pn` are refreshed. A row whose length does not
        match the existing rows is rejected with a printed message.

        Args:
            xn (np.ndarray): One packed mode,
                ``[fn, zn, an_0..an_C, pn_0..pn_C, rk_0..rk_C,
                rm_0..rm_C]`` for C+1 channels (the layout of
                `modal.unpack_matrix`).
        '''
        # Make modal matrix. Each row is modal vector stacked as per 'x' in modal.py
        if len(self.M) == 0:
            self.M = np.atleast_2d(xn)
        elif len(xn) == len(self.M[0,:]):
            self.M = np.vstack((self.M,xn))
        else:
            print('Incompatible mode: different number of channels to existing set.')
            return

        # sort by frequency (first column)
        sort_i = np.argsort(self.M[:,0])
        self.M = self.M[sort_i,:]
        # row layout is [fn, zn, an*N, pn*N, rk*N, rm*N] so the channel
        # count comes from the column count, not the number of rows (modes)
        self.channels = int((self.M.shape[1] - 2) / 4)
        if self.settings is not None:
            self.settings.channels = self.channels

        # separate properties for easier summary, and don't need summary of local residuals rk and rm
        fn,zn,an,pn,rk,rm = modal.unpack_matrix(self.M)
        self.fn = fn
        self.zn = zn
        self.an = an
        self.pn = pn

    def delete_mode(self,mode_number):
        '''Delete one or more modes (rows of `M`) and refresh the summaries.

        Deleting the last remaining mode is allowed: `M` becomes an empty
        ``(0, 2 + 4*channels)`` array, `fn` and `zn` become empty and
        `an` and `pn` have shape ``(0, channels)``. `channels` is kept,
        since it comes from the column count.

        Args:
            mode_number (int or list[int]): Row index or indices of `M` to
                delete (rows are sorted by `fn`).
        '''
        # Emptying the matrix used to crash `modal.unpack_matrix` with an
        # IndexError (the web app's Fit -> Reject); it now reads the channel
        # count from the column count instead of row 0.
        self.M = np.delete(self.M,mode_number,0)
        self.channels = int((self.M.shape[1] - 2) / 4)
        if self.settings is not None:
            self.settings.channels = self.channels

        # separate properties for easier summary, and don't need summary of local residuals rk and rm
        fn,zn,an,pn,rk,rm = modal.unpack_matrix(self.M)
        self.fn = fn
        self.zn = zn
        self.an = an
        self.pn = pn
        
            
    def __repr__(self):
        return "<ModalData>"
        
#    def __repr__(self):
#        with np.printoptions(precision=3, suppress=True):
#            template = "{}: {}"
#            modal_dict = self.__dict__
#            text = '\n<ModalData> class:\n\n'
#            for attr in modal_dict:
#                print(attr)
#                if (attr != 'xn') & (attr != 'rk') & (attr != 'rm') & (attr != 'units') & (attr != 'test_name')& (attr != 'id_link')& (attr != 'timestamp')& (attr != 'timestring'):
#                    text += template.format(attr,modal_dict[attr])
#                    text += '\n'
#            
#            return text
    
        
class SonoData():
    '''Short-time-FFT spectrogram (sonogram) of a multi-channel `TimeData`.

    Produced by `analysis.calculate_sonogram`. Each frame is a windowed
    FFT of a `nperseg`-sample segment of the source data; segments are
    overlapped by `noverlap` and the resulting matrix lets you see how
    spectral content evolves over time. `analysis.calculate_cwt` produces
    the same object from a Morlet wavelet transform instead. Used by
    `analysis.calculate_damping_from_sono` to extract per-mode damping
    from free-decay measurements.

    Also produced by the WEB APP, when a Save is told to include the
    sonogram. Such an item differs in one way a reader must know about:
    its third axis holds only the channels the user chose to save, in
    the order they were saved, NOT every channel of the source. So
    ``sono_data[:, :, k]``, ``units[k]`` and ``channel_cal_factors[k]``
    are all indexed by PLANE, and the source channel each plane came
    from is recorded in ``source_settings['channels'][k]``. A
    single-channel save is the common case (it is the default the prompt
    offers), and then ``sono_data.shape[2] == 1`` however many channels
    the measurement has.

    Attributes:
        time_axis (np.ndarray): Frame midpoints in seconds.
        freq_axis (np.ndarray): One-sided frequency bins in Hz.
        sono_data (np.ndarray): Shape ``(n_freq, n_frames, n_channels)``,
            complex. Magnitude-squared gives a per-bin power spectrogram.
            For an app-written item the last axis is the SAVED channel
            subset — see above.
        settings (MySettings): Snapshot including `pretrig_samples`
            (used by `calculate_damping_from_sono` to pick the
            free-decay start time).
        units (list[str] or None): Engineering units, one per PLANE of
            `sono_data`.
        channel_cal_factors (np.ndarray): Multipliers from volts to
            engineering units, one per PLANE of `sono_data`.
        id_link: `unique_id` of the source TimeData.
        unique_id (uuid.UUID): This item's own identity, minted at
            construction — see `FreqData.unique_id` for why a derived
            item needs one.
        test_name (str or None): Free-form label.
        timestamp (datetime.datetime): When constructed.
        timestring (str): Filesystem-safe rendering of `timestamp`.
    '''

    def __init__(self,time_axis,freq_axis,sono_data,settings,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        self.time_axis = time_axis
        self.freq_axis = freq_axis
        self.sono_data = sono_data
        self.settings = settings
        self.test_name = test_name
        self.units = units
        self.channel_cal_factors = channel_cal_factors
        self.id_link = id_link # used to link data to specific <TimeData> object
        t = datetime.datetime.now()
        self.timestamp = t
        self.timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
        # Own identity, like TimeData's — see FreqData.unique_id.
        self.unique_id = uuid.uuid4()

    def __repr__(self):
        return "<SonoData>"
        
class MetaData():
    '''Dataset-level units and calibration, kept for legacy datasets.

    Attributes:
        units: Engineering units.
        channel_cal_factors: Per-channel multipliers (legacy; always
            None here — calibration lives on each data item instead).
        tf_cal_factors: Per-TF multipliers (legacy; always None here).
        timestamp (datetime.datetime): When this MetaData was built.
        timestring (str): Filesystem-safe rendering of `timestamp`.
        unique_id (uuid.UUID): This item's own identity, minted at
            construction — see `FreqData.unique_id`.
    '''

    def __init__(self, units=None, channel_cal_factors=None, tf_cal_factors = None,test_name=None):
        ### not sure this is a helpful datafield: might delete. Metadata then contained within each data unit.
        self.units = units
        self.channel_cal_factors = None
        self.tf_cal_factors = None
        t = datetime.datetime.now()
        self.timestamp = t
        self.timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
        # Own identity, like TimeData's — see FreqData.unique_id.
        self.unique_id = uuid.uuid4()
        
    def __repr__(self):
        return "<MetaData>"
    
    
def reshape_arrays(a):
    '''Return a 1-D array as a single column; leave anything else unchanged.

    Used by the data classes so a single channel can be passed as a 1-D
    array.

    Args:
        a (np.ndarray): The array.

    Returns:
        a (np.ndarray): A view of shape ``(N, 1)`` when ``a`` is 1-D of
            length N, otherwise ``a`` itself.
    '''
    b = np.shape(a)
    if len(b) == 1:
        a = a[:,None]
        
    return a