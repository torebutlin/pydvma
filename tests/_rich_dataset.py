# -*- coding: utf-8 -*-
"""A dataset with one of everything a ``.dvma`` can hold, and a comparison.

Shared by the container and exchange (CSV / MATLAB) round-trip tests: if an
export is lossless, loading it back gives a dataset whose manifest and arrays
are exactly those of the original, so ``assert_same_dataset`` compares the
two through ``container.dataset_manifest`` rather than attribute by attribute
(the manifest IS what a ``.dvma`` save keeps).
"""
import uuid

import numpy as np

from pydvma import analysis, container, datastructure, options


def rich_dataset():
    """Time, FFT, cross-spectrum, TF (two), sonogram, modal fits (two),
    meta: calibration, units, non-ASCII names, NaN/inf, an integer-typed
    capture, the web app's per-item extras and a dangling link."""
    fs = 128.0
    t = np.arange(256) / fs
    rng = np.random.default_rng(7)
    x = np.sin(2 * np.pi * 10 * t) + 0.1 * rng.standard_normal(t.size)
    y = np.convolve(x, np.exp(-np.arange(40) / 6.0), mode='same') * 0.2
    settings = options.MySettings(channels=2, fs=fs)
    td = datastructure.TimeData(
        t, np.column_stack([x, y]), settings,
        units=['N', 'm/s²'], channel_cal_factors=np.array([1.0, 2.5]),
        test_name='hammer · test – é')
    # the browser app's per-item state rides as manifest extras
    setattr(td, container._ITEM_EXTRA_ATTR,
            {'ui': {'channel_labels': {'0': 'hammer', '1': 'accel, tip'}}})

    # raw ADC counts: an integer-typed capture
    counts = datastructure.TimeData(
        np.arange(8) / 4.0, np.arange(16, dtype=np.int32).reshape(8, 2) - 5,
        options.MySettings(channels=2, fs=4.0), test_name='counts')

    fd = analysis.calculate_fft(td, window='hann')
    cs = analysis.calculate_cross_spectrum_matrix(td, window='hann', N_frames=3)
    tf = analysis.calculate_tf(td, ch_in=0, window='hann', N_frames=3)

    # a TfData with no coherence, BLA sigmas, NaN/inf, a dangling link
    f = np.linspace(0, 64, 9)
    odd = datastructure.TfData(
        f, np.array([1 + 1j, np.nan, np.inf, -np.inf + 2j, 0, 1, 2, 3, 4])[:, None],
        None, options.MySettings(channels=2, fs=fs),
        units=['m/s/N'], id_link=uuid.uuid4(), test_name='odd\nname, with comma')
    odd.bla_sigma_nl = np.abs(np.linspace(0, 1, 9))[:, None]
    odd.bla_sigma_n = np.full((9, 1), np.nan)
    odd.bla = {'P': 2, 'excited_bins': [1, 2, 3], 'x_mode': 'measured'}

    sono = analysis.calculate_sonogram(td, nperseg=32)

    md = datastructure.ModalData(
        np.array([10.0, 0.02, 1.5, 0.1, 0.0, 0.0]), settings=settings,
        id_link=[td.unique_id], test_name='fit')
    setattr(md, container._ITEM_EXTRA_ATTR,
            {'meta': {'measurement_type': 'vel',
                      'source_targets': [{'id_link': str(td.unique_id), 'n_cols': 1}]}})
    empty_md = datastructure.ModalData(settings=settings, test_name='no modes yet')

    meta = datastructure.MetaData(units=['N', 'm/s²'],
                                  channel_cal_factors=np.array([1.0, 2.5]),
                                  tf_cal_factors=np.array([2.5]),
                                  test_name='meta')

    ds = datastructure.DataSet()
    for item in (td, counts, fd, cs, tf, odd, sono, md, empty_md, meta):
        ds.add_to_dataset(item)
    return ds


def assert_same_dataset(a, b):
    """``a`` and ``b`` hold the same manifest and bit-identical arrays
    (shape, dtype, values, NaN and inf in place)."""
    man_a, arr_a = container.dataset_manifest(a)
    man_b, arr_b = container.dataset_manifest(b)
    assert man_a == man_b
    assert sorted(arr_a) == sorted(arr_b)
    for member in arr_a:
        x, y = arr_a[member], arr_b[member]
        assert x.dtype == y.dtype, (member, x.dtype, y.dtype)
        assert x.shape == y.shape, (member, x.shape, y.shape)
        _assert_identical_values(x, y, member)


def _assert_identical_values(x, y, member):
    """Equal values part by part: a complex value's real and imaginary
    parts each, NaN where NaN, and the sign of every zero and infinity
    (assert_array_equal alone counts 1+nanj equal to nan+nanj, and -0.0
    equal to 0.0). Only a NaN's payload bits are not compared: text and
    MATLAB keep "nan", not which NaN."""
    parts = ((x.real, y.real), (x.imag, y.imag)) if np.iscomplexobj(x) else ((x, y),)
    for a, b in parts:
        np.testing.assert_array_equal(a, b, err_msg=member)
        if a.dtype.kind == 'f':
            np.testing.assert_array_equal(np.signbit(a) | np.isnan(a),
                                          np.signbit(b) | np.isnan(b), err_msg=member)
