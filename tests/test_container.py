# -*- coding: utf-8 -*-
"""Tests for the .dvma container format (format v2) and the legacy
pickle reader. See dev/2026-07-01-web-ui-design.md, Stage 0.5."""
import pathlib

import numpy as np

import pydvma as dvma
from pydvma import container, datastructure, options

DATA_DIR = pathlib.Path(__file__).resolve().parent / 'data'
REFERENCE_V140 = DATA_DIR / 'reference_dataset_v140.npy'


def test_legacy_pickle_file_still_loads():
    # Contract: files saved by <=1.4.0 remain loadable forever.
    d = dvma.load_data(filename=str(REFERENCE_V140))
    assert d.pydvma_version == '1.4.0'
    assert len(d.time_data_list) == 1
    assert d.time_data_list[0].units == ['N', 'm/s']
    assert d.time_data_list[0].test_name == 'reference impulse'
    assert d.time_data_list[0].time_data.shape == (10000, 2)
    assert len(d.freq_data_list) == 1
    assert len(d.tf_data_list) == 1
    assert len(d.cross_spec_data_list) == 1
    assert len(d.sono_data_list) == 1
    assert np.isfinite(d.tf_data_list[0].tf_data).all()


def _make_full_dataset():
    # create_test_impulse_data returns a populated DataSet
    data = dvma.create_test_impulse_data(noise_level=0)
    td = data.time_data_list[0]
    td.test_name = 'roundtrip'
    td.units = ['N', 'm/s']
    data.calculate_fft_set()
    data.calculate_tf_set(ch_in=0)
    data.calculate_cross_spectrum_matrix_set(window='hann')
    data.calculate_sono_set()
    # a ModalData with one synthetic mode: [fn, zn, an*N, pn*N, rk*N, rm*N], N=2
    md = datastructure.ModalData(settings=td.settings)
    md.add_mode(np.array([100.0, 0.01, 1.0, 2.0, 0.1, 0.2, 0.0, 0.0, 0.0, 0.0]))
    data.add_to_dataset(md)
    return data


def test_v2_roundtrip_all_kinds(tmp_path):
    data = _make_full_dataset()
    path = tmp_path / 'roundtrip.dvma'
    container.save(data, str(path))
    loaded = container.load(str(path))

    td0, td1 = data.time_data_list[0], loaded.time_data_list[0]
    np.testing.assert_array_equal(td0.time_data, td1.time_data)
    np.testing.assert_array_equal(td0.time_axis, td1.time_axis)
    assert td1.units == ['N', 'm/s']
    assert td1.test_name == 'roundtrip'
    assert td1.unique_id == td0.unique_id            # uuid.UUID preserved
    assert td1.timestamp == td0.timestamp            # datetime preserved
    np.testing.assert_array_equal(td1.channel_cal_factors, td0.channel_cal_factors)

    fd0, fd1 = data.freq_data_list[0], loaded.freq_data_list[0]
    np.testing.assert_array_equal(fd0.freq_data, fd1.freq_data)  # complex survives
    assert fd1.id_link == td0.unique_id

    tf0, tf1 = data.tf_data_list[0], loaded.tf_data_list[0]
    np.testing.assert_array_equal(tf0.tf_data, tf1.tf_data)
    np.testing.assert_array_equal(tf0.tf_coherence, tf1.tf_coherence)
    assert tf1.flag_modal_TF == tf0.flag_modal_TF

    cs0, cs1 = data.cross_spec_data_list[0], loaded.cross_spec_data_list[0]
    np.testing.assert_array_equal(cs0.Pxy, cs1.Pxy)
    np.testing.assert_array_equal(cs0.Cxy, cs1.Cxy)

    sd0, sd1 = data.sono_data_list[0], loaded.sono_data_list[0]
    np.testing.assert_array_equal(sd0.sono_data, sd1.sono_data)

    md0, md1 = data.modal_data_list[0], loaded.modal_data_list[0]
    np.testing.assert_array_equal(md0.M, md1.M)
    np.testing.assert_array_equal(md0.fn, md1.fn)    # summary attrs rebuilt
    assert md1.channels == md0.channels

    assert loaded.pydvma_version == data.pydvma_version


def test_v2_roundtrip_settings(tmp_path):
    settings = options.MySettings(channels=3, fs=12800, device_driver='mock',
                                  channel_sensitivities=[0.1, 0.1, 0.0023])
    data = dvma.create_test_impulse_data(noise_level=0)
    data.time_data_list[0].settings = settings
    path = tmp_path / 's.dvma'
    container.save(data, str(path))
    s1 = container.load(str(path)).time_data_list[0].settings
    assert isinstance(s1, options.MySettings)
    assert s1.fs == 12800 and s1.channels == 3
    assert isinstance(s1.channel_sensitivities, np.ndarray)
    np.testing.assert_array_equal(s1.channel_sensitivities,
                                  settings.channel_sensitivities)
    assert s1.input_vmax() == settings.input_vmax()  # methods work on restored object


def test_v2_roundtrip_none_coherence(tmp_path):
    # TfData from stepped-sine / matlab import has tf_coherence=None
    settings = options.MySettings(channels=2, device_driver='mock')
    tf = datastructure.TfData(np.arange(10.0), np.ones((10, 1), dtype=complex),
                              None, settings)
    data = dvma.DataSet(tf)
    path = tmp_path / 'nc.dvma'
    container.save(data, str(path))
    tf1 = container.load(str(path)).tf_data_list[0]
    assert tf1.tf_coherence is None
    np.testing.assert_array_equal(tf1.tf_data, tf.tf_data)


def test_v2_no_pickle_anywhere(tmp_path):
    # every .npy member must load with allow_pickle=False
    import io
    import zipfile
    data = _make_full_dataset()
    path = tmp_path / 'p.dvma'
    container.save(data, str(path))
    with zipfile.ZipFile(str(path)) as zf:
        names = zf.namelist()
        assert 'manifest.json' in names
        for name in names:
            if name.endswith('.npy'):
                np.load(io.BytesIO(zf.read(name)), allow_pickle=False)
