# -*- coding: utf-8 -*-
"""pydvma-csv 1: a whole dataset as one CSV that loads back exactly.

The CSV carries the ``.dvma`` manifest on one ``#`` line and every array in
readable tables, so loading it back must give what a ``.dvma`` save/load
gives: the same manifest and bit-identical arrays.
"""
import io
import time

import numpy as np
import pytest

from pydvma import _exchange, container, datastructure, options
from _rich_dataset import assert_same_dataset, rich_dataset


@pytest.fixture(scope='module')
def ds():
    return rich_dataset()


@pytest.fixture(scope='module')
def text(ds):
    return _exchange.dataset_to_csv_text(ds)


def test_round_trip_equals_a_dvma_save(ds, text):
    back = _exchange.dataset_from_csv_text(text, 'x.csv')
    assert_same_dataset(back, container.load_bytes(container.save_bytes(ds)))


def test_first_line_names_the_format(text):
    assert text.split('\n', 1)[0] == '# pydvma dataset (pydvma-csv 1)'
    assert _exchange.is_pydvma_csv_line('# pydvma dataset (pydvma-csv 1)')
    assert _exchange.is_pydvma_csv_line('# pydvma dataset (pydvma-csv 7)')
    assert not _exchange.is_pydvma_csv_line('# pydvma export: RAW data, calibration NOT applied.')


def test_tables_are_readable(text):
    lines = text.split('\n')
    headings = [ln for ln in lines if ln.startswith('# table ')]
    assert headings[0].startswith("# table 0: item 0, TimeData 'hammer · test – é'")
    # a TF table: its axis, then re/im pairs, then the coherence beside them
    tf_head = next(i for i, ln in enumerate(lines)
                   if ln.startswith('# table') and 'TfData' in ln)
    assert lines[tf_head + 1] == 'freq_axis,tf_data[0].re,tf_data[0].im,tf_coherence[0]'
    # cross-spectra: the frequency axis is the rows, the matrix the columns
    cs_head = next(i for i, ln in enumerate(lines)
                   if ln.startswith('# table') and 'CrossSpecData' in ln)
    assert lines[cs_head + 1].startswith('freq_axis,Pxy[0][0].re,Pxy[0][0].im,Pxy[0][1].re')


def test_every_item_keeps_its_own_length():
    ds = datastructure.DataSet()
    for n in (5, 7):
        ds.add_to_dataset(datastructure.TfData(
            np.arange(n, dtype=float), np.ones((n, 1), dtype=complex), None,
            options.MySettings(channels=2, fs=10)))
    back = _exchange.dataset_from_csv_text(_exchange.dataset_to_csv_text(ds), 'x')
    assert [len(t.freq_axis) for t in back.tf_data_list] == [5, 7]


def test_windows_line_ends_and_a_bom_are_read(ds, text):
    edited = '﻿' + text.replace('\n', '\r\n')
    assert_same_dataset(_exchange.dataset_from_csv_text(edited, 'x.csv'),
                        _exchange.dataset_from_csv_text(text, 'x.csv'))


def test_a_lost_row_is_refused_with_the_reason(text):
    lines = text.split('\n')
    first_data = next(i for i, ln in enumerate(lines)
                      if ln.startswith('# table')) + 2
    del lines[first_data]
    with pytest.raises(ValueError, match=r'x\.csv: table 0 has 255 rows .* 256'):
        _exchange.dataset_from_csv_text('\n'.join(lines), 'x.csv')


def test_a_newline_in_a_name_does_not_break_the_file(ds, text):
    # 'odd\nname, with comma' is a test name in the rich dataset
    back = _exchange.dataset_from_csv_text(text, 'x.csv')
    assert 'odd\nname, with comma' in [t.test_name for t in back.tf_data_list]
    assert not any(ln.startswith('name, with comma') for ln in text.split('\n'))


def test_another_version_is_refused(text):
    newer = text.replace('(pydvma-csv 1)', '(pydvma-csv 2)', 1)
    with pytest.raises(ValueError, match="pydvma-csv 2.*update pydvma"):
        _exchange.dataset_from_csv_text(newer, 'x.csv')


def test_pandas_reads_one_table(text):
    pd = pytest.importorskip('pandas')
    lines = text.split('\n')
    start = next(i for i, ln in enumerate(lines) if ln.startswith('# table 0'))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith('# table'))
    df = pd.read_csv(io.StringIO('\n'.join(lines[start + 1:end])))
    assert list(df.columns) == ['time_axis', 'time_data[0]', 'time_data[1]']
    assert len(df) == 256


def test_two_million_values_in_seconds():
    n = 500_000
    ds = datastructure.DataSet()
    ds.add_to_dataset(datastructure.TimeData(
        np.arange(n) / 50_000, np.random.default_rng(1).standard_normal((n, 4)),
        options.MySettings(channels=4, fs=50_000)))
    t0 = time.perf_counter()
    text = _exchange.dataset_to_csv_text(ds)
    back = _exchange.dataset_from_csv_text(text, 'big.csv')
    assert time.perf_counter() - t0 < 20
    np.testing.assert_array_equal(back.time_data_list[0].time_data,
                                  ds.time_data_list[0].time_data)


def test_complex_parts_come_back_exactly():
    # 1+nanj must not become nan+nanj, nor an imaginary -0.0 (conj() at a
    # real bin) become +0.0: each part is restored on its own.
    z = np.array([1 + 1j * np.nan, np.inf + 1j * np.nan, complex(-0.0, -0.0),
                  complex(2.0, -0.0), complex(-np.inf, 0.0)])[:, None]
    ds = datastructure.DataSet()
    ds.add_to_dataset(datastructure.TfData(np.arange(5.0), z, None,
                                           options.MySettings(channels=2, fs=10)))
    back = _exchange.dataset_from_csv_text(_exchange.dataset_to_csv_text(ds), 'z')
    assert_same_dataset(back, ds)


def test_empty_arrays_round_trip():
    ds = datastructure.DataSet()
    empty = datastructure.TimeData(np.zeros(1), np.zeros((1, 2)),
                                   options.MySettings(channels=2, fs=10))
    empty.time_axis, empty.time_data = np.zeros(0), np.zeros((0, 2))   # as a file could hold
    ds.add_to_dataset(empty)
    ds.add_to_dataset(datastructure.FreqData(
        np.arange(4.0), np.zeros((4, 0), dtype=complex), options.MySettings(channels=1, fs=10)))
    back = _exchange.dataset_from_csv_text(_exchange.dataset_to_csv_text(ds), 'e')
    assert_same_dataset(back, ds)
