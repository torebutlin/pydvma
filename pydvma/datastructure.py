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
VERSION = '2.4.1' # keep in sync with pyproject.toml (enforced by tests/test_packaging.py)

def update_dataset(dataset):
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
        value: An `id_link`-shaped value — `None`, a `str`/`uuid.UUID`,
            or an arbitrarily nested list/tuple/set of those (or of
            `{'__uuid__': ...}` tag dicts).

    Yields:
        str: One id string per scalar leaf found in `value`.
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
        value: An `id_link`-shaped value, per `_flatten_link_ids`.
        wanted (set): Id strings to match against.

    Returns:
        bool: Whether any leaf of `value` is a member of `wanted`.
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
        bool: Whether `modal_item` should ride along with the subset.
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
        '''Restore a pickled DataSet, forward-normalising older layouts.

        Unpickling instantiates the CURRENT class but restores ONLY the
        attributes that were actually saved, so a DataSet written by an
        older pydvma is missing any ``*_list`` attribute that postdates it.
        Historically the lists were added at different times
        (``cross_spec_data_list`` with multi-channel analysis;
        ``sono_data_list`` with sonograms; ``modal_data_list`` with modal
        fitting), so a legacy ``.npy`` pickle can lack one or more of them —
        e.g. the 2019/4C6-era files lack ``modal_data_list``. The rest of
        the code (and ``container.save``) assumes every list is present, so
        loading such a file used to raise ``AttributeError: 'DataSet'
        object has no attribute 'modal_data_list'``.

        We fill in any absent list with an empty instance of the right type
        (and stamp a placeholder ``pydvma_version`` when the file predates
        the version field) so files saved by pydvma <= 1.4.0 load forever —
        the compatibility contract — on BOTH the Qt load path
        (``file.load_data`` → ``np.load``) and the browser legacy-import
        path (``glue.legacy_to_dvma`` → ``np.load`` → ``container.save_bytes``).
        Called only when unpickling; freshly constructed DataSets go through
        ``__init__`` and never touch this. Newly saved objects already carry
        every attribute, so this is a no-op for them.
        '''
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
        '''
        Calls analysis.calculate_fft on each TimeData item in the TimeDataList and adds FreqDataList object to dataset
        '''
        if len(self.time_data_list)>0:
            freq_data_list = self.time_data_list.calculate_fft_set(time_range=time_range,window=window)
            self.freq_data_list = freq_data_list
            #self.add_to_dataset(freq_data_list)
        else:
            self.freq_data_list = FreqDataList()
            print('No time data found in dataset')
            
    def calculate_tf_set(self, ch_in=0, time_range=None,window=None,N_frames=1,overlap=0.5):
        '''
        Calls analysis.calculate_tf on each TimeData item in the TimeDataList and adds TfDataList object to dataset
        '''
        if len(self.time_data_list)>0:
            tf_data_list = self.time_data_list.calculate_tf_set(ch_in=ch_in, time_range=time_range, window=window, N_frames=N_frames, overlap=overlap)
            self.tf_data_list = tf_data_list
            #self.add_to_dataset(tf_data_list)
        else:
            self.tf_data_list = TfDataList()
            print('No time data found in dataset')
            
    def calculate_cross_spectrum_matrix_set(self,ch_in=0, time_range=None,window='hann',N_frames=1,overlap=0.5):
        '''
        Calls analysis.calculate_cross_spectrum_matrix on each TimeData item in the TimeDataList and adds CrossSpecDataList object to dataset
        '''
        if len(self.time_data_list)>0:
            cross_spec_data_list = self.time_data_list.calculate_cross_spectrum_matrix_set(ch_in=ch_in, time_range=time_range,window=window,N_frames=N_frames,overlap=overlap)
            self.cross_spec_data_list = cross_spec_data_list
            #self.add_to_dataset(cross_spec_data_list)
        else:
            self.cross_spec_data_list = CrossSpecDataList()
            print('No time data found in dataset')
            
    def calculate_tf_averaged(self, ch_in=0, time_range=None,window='hann'):
        '''
        Calls analysis.calculate_tf_averaged on the whole TimeDataList (ensemble average) and adds a single-item TfDataList to dataset
        '''
        if len(self.time_data_list)>0:
            tf_data = self.time_data_list.calculate_tf_averaged(ch_in=ch_in, time_range=time_range ,window=window)
            self.tf_data_list = TfDataList([tf_data])
            #self.add_to_dataset(tf_data)
        else:
            self.tf_data_list = TfDataList()
            print('No time data found in dataset')
            
    def calculate_cross_spectra_averaged(self, time_range=None,window=None):
        '''
        Calls analysis.calculate_cross_spectra_averaged on the whole TimeDataList (ensemble average) and adds a single-item CrossSpecDataList to dataset
        '''
        if len(self.time_data_list)>0:
            cross_spec_data = self.time_data_list.calculate_cross_spectra_averaged(time_range=time_range,window=window)
            self.cross_spec_data_list = CrossSpecDataList([cross_spec_data])
            #self.add_to_dataset(cross_spec_data)
        else:
            self.cross_spec_data_list = CrossSpecDataList()
            print('No time data found in dataset')
            
    def calculate_sono_set(self, nperseg=None):
        if len(self.time_data_list)>0:
            sono_data_list = self.time_data_list.calculate_sono_set(nperseg=nperseg)
            self.sono_data_list = sono_data_list
        else:
            self.sono_data_list = SonoDataList()
            print('No time data found in dataset')
            
    def clean_impulse(self,ch_impulse=0):
        '''
        Calls analysis.clean_impulse on each TimeData item in the TimeDataList and returns a copy of the new dataset.
        
        Note that calling this function *does not* change the data, and just returns a copy.
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
        '''Return a new `DataSet` holding chosen measurement(s) and everything derived from them.

        This is the Python counterpart of the web app's Save
        "Choose sets…" picker (`subsetDataset` in
        `webui/src/lib/analysis/actions.ts`) — the same inclusion
        rule, mirrored here so a notebook workflow and the browser
        produce the same subset from the same dataset:

        1. the chosen `TimeData` item(s) themselves;
        2. every `FreqData` / `CrossSpecData` / `TfData` / `SonoData`
           item whose `id_link` resolves into a chosen item's
           `unique_id`. A scalar `id_link` (`analysis.calculate_fft`,
           `analysis.calculate_tf`, `analysis.calculate_cross_spectrum_matrix`,
           `analysis.calculate_sonogram`/`calculate_cwt`) matches
           directly; a LIST `id_link` (`analysis.calculate_tf_averaged`,
           `analysis.calculate_cross_spectra_averaged`,
           `analysis.calculate_bla` — one entry per source `TimeData`
           in the ensemble) matches on ANY member, not all — an
           ensemble result whose sources only partly overlap the pick
           still rides along;
        3. a `ModalData` fit when ANY of its links lands in the chosen
           lineage — see `_modal_item_in_subset` for the exact link
           shapes checked (own `id_link`, scalar or nested-list, plus
           a browser-authored `source_targets` extra when present).
           This is deliberately an ANY rule, not ALL: a fit is worth
           carrying with any set it describes. **Note the web app's
           own loader is stricter** — it re-seeds a *live, editable*
           fit only when EVERY `source_targets` link resolves — so a
           subset spanning only part of a shared-pole fit still
           carries the `ModalData` as data (readable, replottable,
           reloadable) without silently re-seeding a fit session for a
           model that no longer has all its sources; carrying the
           modes as DATA is the contract here, not re-seeding a fit.
        4. `MetaData`, and any derived item whose `id_link` cannot be
           resolved into the pick (an orphan, or a link to a
           `TimeData` outside the pick), are excluded — that is the
           point of a subset.

        **Items are SHARED, not copied.** The returned `DataSet`'s
        lists hold the SAME objects as `self`'s, so mutating a
        `TimeData` (or any derived item) reached through either
        dataset is visible through both — consistent with the rest of
        this class (`add_to_dataset`, `replace_data_item` never copy
        either). Take your own `copy.deepcopy` first if independent
        objects are needed. Lists keep their original relative order.

        Unlike the web app's `subsetDataset`, there is no
        "picking every set returns the live document" short-circuit:
        this always builds a fresh `DataSet` (still item-SHARING, per
        above), so passing every valid index is not the same as
        "everything" — a genuinely unattributable item (an orphan
        derived item, `MetaData`) is excluded even then, whereas the
        web app's "everything" pick keeps such items because it
        returns the untouched document unchanged.

        Args:
            sets (int or Iterable[int]): Index or indices into
                `time_data_list` to keep (0-based). Duplicate indices
                are ignored after the first.

        Returns:
            dataset (DataSet): A new `DataSet`, with `pydvma_version`
                copied from `self`, containing the chosen measurements
                and their resolved derived/modal items, sharing objects
                with `self`.

        Raises:
            IndexError: `sets` contains an index outside
                ``range(len(self.time_data_list))``.
        '''
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

    def save_data(self, filename=None, sets=None):
        '''
        Saves the whole DataSet via `file.save_data` — writes the
        .dvma container format by default (legacy pickle format if
        `filename` explicitly ends in ``.npy``). Shows a save dialog
        if no filename is given.

        Args:
            filename (str, optional): Output filename, dialog shown if not provided.
            sets (int or Iterable[int], optional): If given, saves
                `self.subset(sets)` instead of the whole dataset — see
                `subset` for the exact inclusion rule. `None` (the
                default) saves everything, unchanged.
        '''
        savename = file.save_data(self, filename=filename, overwrite_without_prompt=False, sets=sets)
        return savename
    
    def export_to_matlab(self, filename=None, overwrite_without_prompt=False):
        savename = file.export_to_matlab(self, filename=filename, overwrite_without_prompt=overwrite_without_prompt)
        return savename
    
    def export_to_matlab_jwlogger(self, filename=None, overwrite_without_prompt=False):
        savename = file.export_to_matlab_jwlogger(self, filename=filename, overwrite_without_prompt=overwrite_without_prompt)
        return savename
    
    def plot_time_data(self,sets='all',channels='all'):
        from . import plotting
        global pt
        pt = plotting.PlotData(window_title='Time Data')
        pt.update(self.time_data_list,sets=sets,channels=channels)
        return pt

    def plot_freq_data(self,sets='all',channels='all'):
        from . import plotting
        global pf
        pf = plotting.PlotData(window_title='Frequency Data')
        pf.update(self.freq_data_list,sets=sets,channels=channels)
        return pf

    def plot_tf_data(self,sets='all',channels='all'):
        from . import plotting
        global ptf
        ptf = plotting.PlotData(window_title='Transfer Function Data')
        ptf.update(self.tf_data_list,sets=sets,channels=channels)
        return ptf

    def plot_sono_data(self,n_set=0, n_chan=0, db_range=60):
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
    ### This will allow functions to be discovered that can take lists of TimeData is arguments
    def calculate_fft_set(self,time_range=None,window=None):
        '''
        Calls analysis.calculate_fft on each item in the list and returns FreqDataList object
        '''
        freq_data_list = FreqDataList()
        
        for td in self:
            freq_data = analysis.calculate_fft(td, time_range=time_range, window=window)
            freq_data_list += [freq_data]
            
        return freq_data_list
    
    
    def calculate_tf_set(self, ch_in=0, time_range=None,window=None,N_frames=1,overlap=0.5):
        '''
        Calls analysis.calculate_tf on each item in the list and returns TfDataList object
        '''
        tf_data_list = TfDataList()
        
        for td in self:
            tf_data = analysis.calculate_tf(td, ch_in=ch_in, time_range=time_range,window=window,N_frames=N_frames,overlap=overlap)
            tf_data_list += [tf_data]
            
        return tf_data_list
    
    def calculate_cross_spectrum_matrix_set(self, ch_in=0, time_range=None,window=None,N_frames=1,overlap=0.5):
        '''
        Calls analysis.calculate_tf on each item in the list and returns TfDataList object
        '''
        cross_spec_data_list = CrossSpecDataList()
        
        for td in self:
            cross_spec_data = analysis.calculate_cross_spectrum_matrix(td, time_range=time_range,window=window,N_frames=N_frames,overlap=overlap)
            cross_spec_data_list += [cross_spec_data]
            
        return cross_spec_data_list
    
    
    def calculate_tf_averaged(self, ch_in=0, time_range=None,window='hann'):
        '''
        Calls analysis.calculate_tf_averaged on whole list and returns TfData object
        '''
        tf_data = analysis.calculate_tf_averaged(self,ch_in=ch_in, time_range=time_range,window=window)
            
        return tf_data
    
    
    def calculate_cross_spectra_averaged(self, time_range=None,window=None):
        '''
        Calls analysis.calculate_cross_spectra_averaged on whole list and returns CrossSpecData object
        '''
        cross_spec_data = analysis.calculate_cross_spectra_averaged(self, time_range=time_range,window=window)
            
        return cross_spec_data
    
    def calculate_sono_set(self, nperseg=None):
        '''
        Calls analysis.calculate_sonogram on each item in the list and returns SonoDataList object
        '''
        sono_data_list = SonoDataList()
        
        for td in self:
            sono_data = analysis.calculate_sonogram(td,nperseg=nperseg)
            sono_data_list += [sono_data]
            
        return sono_data_list
    
    def get_calibration_factors(self):
        n_set = len(self)
        factors = []
        for ns in range(n_set):
            factors.append(self[ns].channel_cal_factors)
        
        return factors
            
    def set_calibration_factors_all(self,factors):
        n_set = len(self)
        for ns in range(n_set):
            self[ns].channel_cal_factors=factors[ns]
            
    def set_calibration_factor(self,factor, n_set=0, n_chan=0):
        if len(self) == 0:
            print('<TimeDataList> is empty. First log data, load data, or create test data.')
        elif n_set >= len(self):
            print('<TimeDataList> has {} set(s) of <TimeData>. Set requested (index={}) exceeds number of sets. Note indexing starts at 0.'.format(len(self),n_set))
        elif n_chan >= len(self[n_set].time_data[0,:]):
            print('<TimeDataList>[{}] has {} channel(s). Channel requested (index={}) exceeds number of channels. Note indexing starts at 0.'.format(n_set,len(self[n_set].time_data[0,:]),n_chan))
        else:
            self[n_set].channel_cal_factors[n_chan]=factor
    
    def export_to_csv(self, filename=None, overwrite_without_prompt=False):
        savename = file.export_to_csv(self,filename=filename,overwrite_without_prompt=overwrite_without_prompt)
        return savename

class FreqDataList(list):
    ### This will allow functions to be discovered that can take lists of FreqData is arguments
    def get_calibration_factors(self):
        n_set = len(self)
        factors = []
        for ns in range(n_set):
            factors.append(self[ns].channel_cal_factors)
        
        return factors
    
    def set_calibration_factors_all(self,factors):
        n_set = len(self)
        for ns in range(n_set):
            self[ns].channel_cal_factors=factors[ns]
            
    def set_calibration_factor(self,factor, n_set=0, n_chan=0):
        if len(self) == 0:
            print('<FreqDataList> is empty. First calculate FFT.')
        elif n_set >= len(self):
            print('<FreqDataList> has {} set(s) of <FreqData>. Set requested (index={}) exceeds number of sets. Note indexing starts at 0.'.format(len(self),n_set))
        elif n_chan >= len(self[n_set].freq_data[0,:]):
            print('<FreqDataList>[{}] has {} channel(s). Channel requested (index={}) exceeds number of channels. Note indexing starts at 0.'.format(n_set,len(self[n_set].freq_data[0,:]),n_chan))
        else:
            self[n_set].channel_cal_factors[n_chan]=factor
            
    def export_to_csv(self, filename=None, overwrite_without_prompt=False):
        savename = file.export_to_csv(self,filename=filename,overwrite_without_prompt=overwrite_without_prompt)
        return savename

class CrossSpecDataList(list):
    ### This will allow functions to be discovered that can take lists of CrossSpecData is arguments
    pass

class TfDataList(list):
    ### This will allow functions to be discovered that can take lists of TfData is arguments
    def get_calibration_factors(self):
        n_set = len(self)
        factors = []
        for ns in range(n_set):
            factors.append(self[ns].channel_cal_factors)
        
        return factors
    
    def set_calibration_factors_all(self,factors):
        n_set = len(self)
        for ns in range(n_set):
            self[ns].channel_cal_factors=factors[ns]
            
    def set_calibration_factor(self,factor, n_set=0, n_chan=0):
        if len(self) == 0:
            print('<TfDataList> is empty. First calculate transfer function.')
        elif n_set >= len(self):
            print('<TfDataList> has {} set(s) of <TfData>. Set requested (index={}) exceeds number of sets. Note indexing starts at 0.'.format(len(self),n_set))
        elif n_chan >= len(self[n_set].tf_data[0,:]):
            print('<TfDataList>[{}] has {} channel(s). Channel requested (index={}) exceeds number of channels. Note indexing starts at 0.'.format(n_set,len(self[n_set].tf_data[0,:]),n_chan))
        else:
            self[n_set].channel_cal_factors[n_chan]=factor
    
    def add_modal_reconstruction(self,tf_data,mode='replace'):
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
        savename = file.export_to_csv(self,filename=filename,overwrite_without_prompt=overwrite_without_prompt)
        return savename
      
class ModalDataList(list):
    ### This will allow functions to be discovered that can take lists of ModalData is arguments
    pass

class SonoDataList(list):
    ### This will allow functions to be discovered that can take lists of SonoData is arguments
    pass

class MetaDataList(list):
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
            trip through :class:`pydvma.session.Session` REPLACE this
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
            volts to engineering units.
        id_link: `unique_id` of the source TimeData (or list of
            ids when averaged across a TimeDataList).
        unique_id (uuid.UUID): This item's own identity, minted at
            construction — see `FreqData.unique_id` for why a derived
            item needs one.
        test_name (str or None): Free-form label.
        timestamp (datetime.datetime): When constructed.
        timestring (str): Filesystem-safe rendering of `timestamp`.
    '''

    def __init__(self,freq_axis,Pxy,Cxy,settings,units=None,channel_cal_factors=None,id_link=None,test_name=None):
        
        self.freq_axis = freq_axis
        self.Pxy = Pxy
        self.Cxy = Cxy
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
        flag_modal_TF (bool): True after a modal fit has consumed
            this TfData (avoids double-fitting); used by `modal.py`.
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
        '''
        Appends one mode (a packed parameter row as per 'x' in modal.py:
        [fn, zn, an x N, pn x N, rk x N, rm x N]) to the modal matrix,
        keeping rows sorted by natural frequency and refreshing the
        unpacked summary properties (fn, zn, an, pn).
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
        '''
        Deletes one or more modes (rows) from the modal matrix by index and
        refreshes the unpacked summary properties (fn, zn, an, pn).

        Deleting the LAST remaining mode is valid: the matrix becomes an
        empty ``(0, 2+4*channels)`` and the summaries become zero-length
        (fn/zn) / ``(0, channels)`` (an/pn). This no longer raises the
        IndexError that ``modal.unpack_matrix`` used to throw on an emptied
        matrix (the round-4 "Fit -> Reject" crash, and the same latent crash
        on Qt's Reject). ``channels`` is preserved — it is encoded in the
        column count, not the number of mode rows.
        '''
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
    b = np.shape(a)
    if len(b) == 1:
        a = a[:,None]
        
    return a