# -*- coding: utf-8 -*-
"""pydvma-mat 1: a whole dataset as MATLAB data that loads back exactly.

Variables: ``pydvma_format``, ``pydvma_manifest`` (the ``.dvma`` manifest as
JSON text, which MATLAB's ``jsondecode`` reads) and ``pydvma_items`` (a cell
array with one struct per item holding its exact arrays), and nothing else:
the old interpolated ``*_all`` matrices are gone.
"""
import numpy as np
import pytest
import scipy.io

from pydvma import _exchange, container, datastructure, options
from _rich_dataset import assert_same_dataset, rich_dataset


@pytest.fixture(scope='module')
def ds():
    return rich_dataset()


@pytest.fixture(scope='module')
def loaded(ds, tmp_path_factory):
    path = tmp_path_factory.mktemp('mat') / 'x.mat'
    scipy.io.savemat(path, _exchange.dataset_to_mat_dict(ds), oned_as='column',
                     do_compression=True)
    return scipy.io.loadmat(path, simplify_cells=True)


def test_round_trip_through_a_file_equals_a_dvma_save(ds, loaded):
    back = _exchange.dataset_from_mat_dict(loaded, 'x.mat')
    assert_same_dataset(back, container.load_bytes(container.save_bytes(ds)))


def test_only_the_three_variables(loaded):
    assert sorted(k for k in loaded if not k.startswith('__')) == [
        'pydvma_format', 'pydvma_items', 'pydvma_manifest']
    assert loaded['pydvma_format'] == 'pydvma-mat 1'
    assert _exchange.is_pydvma_mat(loaded)
    assert not _exchange.is_pydvma_mat({'time_data_all': np.zeros(3)})


def test_what_matlab_sees(ds, loaded):
    items = loaded['pydvma_items']
    assert len(items) == 10                      # one struct per item, in order
    tf = items[4]
    assert tf['kind'] == 'TfData'
    assert tf['test_name'] == 'hammer · test – é'
    assert tf['fs'] == 128.0
    np.testing.assert_array_equal(tf['tf_data'], ds.tf_data_list[0].tf_data[:, 0])
    np.testing.assert_array_equal(tf['channel_cal_factors'], 2.5)
    assert list(items[0]['units']) == ['N', 'm/s²']
    assert isinstance(items[0]['timestamp'], str)
    # a raw-count capture keeps its integer type
    assert items[1]['time_data'].dtype == np.int32


def test_a_single_item_file(tmp_path):
    # MATLAB (and simplify_cells) turn a one-element cell into its struct
    one = datastructure.DataSet()
    one.add_to_dataset(datastructure.TfData(
        np.arange(3.0), np.ones((3, 1), dtype=complex), None,
        options.MySettings(channels=2, fs=10)))
    path = tmp_path / 'one.mat'
    scipy.io.savemat(path, _exchange.dataset_to_mat_dict(one), oned_as='column')
    back = _exchange.dataset_from_mat_dict(
        scipy.io.loadmat(path, simplify_cells=True), 'one.mat')
    assert_same_dataset(back, one)


def test_another_version_is_refused(loaded):
    newer = dict(loaded, pydvma_format='pydvma-mat 2')
    with pytest.raises(ValueError, match='pydvma-mat 2.*update pydvma'):
        _exchange.dataset_from_mat_dict(newer, 'x.mat')


def test_boolean_arrays_come_back_boolean(tmp_path):
    # savemat stores logicals as uint8; the manifest's dtype casts them back
    ds = datastructure.DataSet()
    ds.add_to_dataset(datastructure.TimeData(
        np.arange(4.0), np.array([[True, False], [False, True], [True, True], [False, False]]),
        options.MySettings(channels=2, fs=1)))
    path = tmp_path / 'b.mat'
    scipy.io.savemat(path, _exchange.dataset_to_mat_dict(ds), oned_as='column')
    back = _exchange.dataset_from_mat_dict(scipy.io.loadmat(path, simplify_cells=True), 'b')
    assert_same_dataset(back, ds)
    assert _exchange.dataset_from_csv_text(_exchange.dataset_to_csv_text(ds), 'b') \
        .time_data_list[0].time_data.dtype == bool


def test_complex_parts_and_empty_arrays_round_trip(tmp_path):
    z = np.array([1 + 1j * np.nan, complex(-0.0, -0.0), complex(2.0, -0.0)])[:, None]
    ds = datastructure.DataSet()
    ds.add_to_dataset(datastructure.TfData(np.arange(3.0), z, None,
                                           options.MySettings(channels=2, fs=10)))
    empty = datastructure.TimeData(np.zeros(1), np.zeros((1, 2)),
                                   options.MySettings(channels=2, fs=10))
    empty.time_axis, empty.time_data = np.zeros(0), np.zeros((0, 2))   # as a file could hold
    ds.add_to_dataset(empty)
    path = tmp_path / 'z.mat'
    scipy.io.savemat(path, _exchange.dataset_to_mat_dict(ds), oned_as='column')
    back = _exchange.dataset_from_mat_dict(scipy.io.loadmat(path, simplify_cells=True), 'z')
    assert_same_dataset(back, ds)
