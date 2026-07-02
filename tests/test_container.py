# -*- coding: utf-8 -*-
"""Tests for the .dvma container format (format v2) and the legacy
pickle reader. See dev/2026-07-01-web-ui-design.md, Stage 0.5."""
import json
import pathlib
import uuid
import zipfile

import numpy as np
import pytest

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

    # manifest records the writer's version (== data's here, since
    # this dataset was created by the current pydvma)
    assert loaded.pydvma_version == datastructure.VERSION


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


def _write_manifest_zip(path, manifest):
    """Hand-craft a minimal .dvma zip containing only manifest.json."""
    with zipfile.ZipFile(str(path), 'w') as zf:
        zf.writestr('manifest.json', json.dumps(manifest))


def test_v2_manifest_strict_json_nonfinite(tmp_path):
    # Non-finite floats are reachable in real workflows (inf via
    # time_range, NaN via cal factors). The manifest must stay strict
    # JSON — JSON.parse rejects bare Infinity/NaN — so these must be
    # tagged, and must round-trip losslessly.
    data = dvma.create_test_impulse_data(noise_level=0)
    data.calculate_fft_set(time_range=[0.0, np.inf])
    data.time_data_list[0].channel_cal_factors = np.array([1.0, np.nan])
    path = tmp_path / 'nonfinite.dvma'
    container.save(data, str(path))

    # (b) manifest text is strict JSON: parse_constant only fires on
    # the non-strict tokens Infinity / -Infinity / NaN
    with zipfile.ZipFile(str(path)) as zf:
        text = zf.read('manifest.json').decode('utf-8')
    json.loads(text, parse_constant=lambda s: pytest.fail('non-strict JSON: ' + s))

    # (a) round-trip fidelity
    loaded = container.load(str(path))
    time_range = loaded.freq_data_list[0].settings.time_range
    assert time_range[0] == 0.0
    assert time_range[1] == np.inf
    cal = loaded.time_data_list[0].channel_cal_factors
    assert isinstance(cal, np.ndarray)
    assert cal[0] == 1.0
    assert np.isnan(cal[1])


def test_v2_load_rejects_future_format_version(tmp_path):
    path = tmp_path / 'future.dvma'
    _write_manifest_zip(path, {
        'format': container.FORMAT_NAME,
        'format_version': 2,
        'pydvma_version': '99.0.0',
        'storage': 'npy',
        'items': [],
    })
    with pytest.raises(ValueError, match='format_version'):
        container.load(str(path))


def test_v2_load_unknown_kind_clear_error(tmp_path):
    path = tmp_path / 'holo.dvma'
    _write_manifest_zip(path, {
        'format': container.FORMAT_NAME,
        'format_version': container.FORMAT_VERSION,
        'pydvma_version': '99.0.0',
        'storage': 'npy',
        'items': [{'kind': 'HologramData', 'arrays': {}, 'meta': {},
                   'settings': None}],
    })
    with pytest.raises(ValueError, match='HologramData'):
        container.load(str(path))


def test_v2_load_tolerates_sparse_and_unknown_manifest_keys(tmp_path):
    # Optional entry keys may be absent, and keys unknown to this
    # reader must be ignored (forward compatibility within v1).
    path = tmp_path / 'sparse.dvma'
    _write_manifest_zip(path, {
        'format': container.FORMAT_NAME,
        'format_version': container.FORMAT_VERSION,
        'pydvma_version': '1.5.0',
        'storage': 'npy',
        'future_hint': 42,
        'items': [{'kind': 'MetaData', 'future_field': 'ignored'}],
    })
    loaded = container.load(str(path))
    assert len(loaded.meta_data_list) == 1
    assert loaded.meta_data_list[0].units is None


def test_v2_atomic_save_preserves_original_on_crash(tmp_path, monkeypatch):
    data = _make_full_dataset()
    path = tmp_path / 'atomic.dvma'
    container.save(data, str(path))

    real_write = container._write_array
    calls = {'n': 0}

    def flaky_write(zf, member, arr):
        calls['n'] += 1
        if calls['n'] == 2:
            raise RuntimeError('disk full (simulated)')
        real_write(zf, member, arr)

    monkeypatch.setattr(container, '_write_array', flaky_write)
    with pytest.raises(RuntimeError, match='disk full'):
        container.save(dvma.create_test_impulse_data(noise_level=0), str(path))
    monkeypatch.undo()

    # the pre-existing good file survives the failed overwrite intact
    loaded = container.load(str(path))
    np.testing.assert_array_equal(loaded.time_data_list[0].time_data,
                                  data.time_data_list[0].time_data)
    # and no temp files are left behind
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != 'atomic.dvma']
    assert leftovers == []


def test_v2_pydvma_version_is_writer_version(tmp_path):
    # Resaving a dataset loaded from an old file must record the
    # version that wrote THIS file, not the one that wrote the source.
    data = dvma.create_test_impulse_data(noise_level=0)
    data.pydvma_version = '1.0.0'
    path = tmp_path / 'ver.dvma'
    container.save(data, str(path))
    loaded = container.load(str(path))
    assert loaded.pydvma_version == datastructure.VERSION


def test_v2_optional_analysis_attrs_roundtrip(tmp_path):
    # iw_power_counter (multiply_by_power_of_iw) and impulse_cleaned
    # (clean_impulse) are set post-construction and must survive.
    data = dvma.create_test_impulse_data(noise_level=0)
    data.calculate_fft_set()
    fd = data.freq_data_list[0]
    dvma.multiply_by_power_of_iw(fd, 1, [1])
    td_clean = dvma.clean_impulse(data.time_data_list[0], ch_impulse=0)
    data.time_data_list[0] = td_clean
    path = tmp_path / 'opt.dvma'
    container.save(data, str(path))
    loaded = container.load(str(path))

    fd1 = loaded.freq_data_list[0]
    assert hasattr(fd1, 'iw_power_counter')
    assert isinstance(fd1.iw_power_counter, np.ndarray)
    np.testing.assert_array_equal(fd1.iw_power_counter, fd.iw_power_counter)

    td1 = loaded.time_data_list[0]
    assert hasattr(td1, 'impulse_cleaned')
    assert td1.impulse_cleaned is True


def test_v2_optional_attrs_absent_stay_absent(tmp_path):
    # hasattr-guards downstream rely on absence — a round-trip must
    # not invent the attributes (not even as None).
    data = dvma.create_test_impulse_data(noise_level=0)
    data.calculate_fft_set()
    path = tmp_path / 'plain.dvma'
    container.save(data, str(path))
    loaded = container.load(str(path))
    assert not hasattr(loaded.time_data_list[0], 'impulse_cleaned')
    assert not hasattr(loaded.freq_data_list[0], 'iw_power_counter')


def test_v2_settings_device_full_info_dict(tmp_path):
    # settings.device_full_info is a dict (sounddevice.query_devices()
    # entry) and can carry numpy scalars / NaN — must round-trip.
    data = dvma.create_test_impulse_data(noise_level=0)
    s = data.time_data_list[0].settings
    s.device_full_info = {'name': 'Mock Soundcard',
                          'max_input_channels': np.int64(2),
                          'default_samplerate': np.float64(44100.0),
                          'default_low_input_latency': np.nan}
    path = tmp_path / 'dev.dvma'
    container.save(data, str(path))
    info = container.load(str(path)).time_data_list[0].settings.device_full_info
    assert info['name'] == 'Mock Soundcard'
    assert info['max_input_channels'] == 2
    assert info['default_samplerate'] == 44100.0
    assert np.isnan(info['default_low_input_latency'])


def test_v2_encode_error_names_kind_and_field(tmp_path):
    data = dvma.create_test_impulse_data(noise_level=0)
    path = tmp_path / 'bad.dvma'

    # reserved tag used as a dict key in user data
    data.time_data_list[0].test_name = {'__array__': [1, 2]}
    with pytest.raises(ValueError, match=r"TimeData.*'test_name'"):
        container.save(data, str(path))
    assert not path.exists()   # failed save leaves nothing behind

    # non-string dict keys would be silently coerced by JSON
    data.time_data_list[0].test_name = {1: 'x'}
    with pytest.raises(ValueError, match=r"TimeData.*'test_name'"):
        container.save(data, str(path))


def test_v2_metadata_roundtrip(tmp_path):
    md = datastructure.MetaData(units=['N', 'm/s'])
    data = dvma.DataSet(md)
    path = tmp_path / 'meta.dvma'
    container.save(data, str(path))
    md1 = container.load(str(path)).meta_data_list[0]
    assert md1.units == ['N', 'm/s']
    assert md1.timestamp == md.timestamp
    assert md1.channel_cal_factors is None
    assert md1.tf_cal_factors is None


def test_v2_empty_dataset_roundtrip(tmp_path):
    path = tmp_path / 'empty.dvma'
    container.save(dvma.DataSet(), str(path))
    loaded = container.load(str(path))
    assert len(loaded.time_data_list) == 0
    assert len(loaded.freq_data_list) == 0
    assert len(loaded.tf_data_list) == 0
    assert len(loaded.meta_data_list) == 0
    assert loaded.pydvma_version == datastructure.VERSION


def test_v2_id_link_list_roundtrip(tmp_path):
    # calculate_tf_averaged links a TfData to a LIST of source uuids
    settings = options.MySettings(channels=2, device_driver='mock')
    links = [uuid.uuid4(), uuid.uuid4()]
    tf = datastructure.TfData(np.arange(10.0), np.ones((10, 1), dtype=complex),
                              None, settings, id_link=links)
    data = dvma.DataSet(tf)
    path = tmp_path / 'links.dvma'
    container.save(data, str(path))
    tf1 = container.load(str(path)).tf_data_list[0]
    assert tf1.id_link == links
    assert all(isinstance(u, uuid.UUID) for u in tf1.id_link)


def test_save_data_defaults_to_dvma(tmp_path):
    data = _make_full_dataset()
    # no extension -> .dvma appended, container format written
    out = dvma.save_data(data, filename=str(tmp_path / 'mytest'))
    assert out.endswith('.dvma')
    import zipfile
    assert zipfile.is_zipfile(out)
    loaded = dvma.load_data(filename=out)
    np.testing.assert_array_equal(loaded.time_data_list[0].time_data,
                                  data.time_data_list[0].time_data)


def test_save_data_explicit_npy_writes_legacy(tmp_path):
    # escape hatch: an explicit .npy filename keeps the old pickle
    data = _make_full_dataset()
    out = dvma.save_data(data, filename=str(tmp_path / 'legacy.npy'),
                         overwrite_without_prompt=True)
    assert out.endswith('.npy')
    import zipfile
    assert not zipfile.is_zipfile(out)
    loaded = dvma.load_data(filename=out)
    assert len(loaded.time_data_list) == 1


def test_load_data_sniffs_by_content_not_extension(tmp_path):
    # a .dvma file renamed to .npy must still load as v2 (content sniff)
    data = _make_full_dataset()
    from pydvma import container
    odd = tmp_path / 'renamed.npy'
    container.save(data, str(odd))
    loaded = dvma.load_data(filename=str(odd))
    assert len(loaded.tf_data_list) == 1


def test_dataset_save_data_method_roundtrip(tmp_path):
    # the labsheet idiom: dataset.save_data(...) then dvma.load_data(...)
    data = _make_full_dataset()
    out = data.save_data(filename=str(tmp_path / 'method_path'))
    loaded = dvma.load_data(filename=out)
    assert loaded.pydvma_version == data.pydvma_version


def test_load_data_clear_error_on_foreign_zip(tmp_path):
    # a zip that isn't a dvma-dataset must give a clear error, not a
    # raw KeyError from the missing manifest
    import zipfile
    foreign = tmp_path / 'foreign.zip'
    with zipfile.ZipFile(str(foreign), 'w') as zf:
        zf.writestr('readme.txt', 'not a dataset')
    with pytest.raises(ValueError, match='manifest'):
        dvma.load_data(filename=str(foreign))


def test_load_data_missing_file_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        dvma.load_data(filename=str(tmp_path / 'no_such_file.dvma'))


def test_load_data_corrupt_dvma_raises_clear_error(tmp_path):
    # zero-byte / truncated .dvma must not be reported as a wrong
    # extension — say it's corrupt
    bad = tmp_path / 'truncated.dvma'
    bad.write_bytes(b'')
    with pytest.raises(ValueError, match='empty, truncated, or corrupted'):
        dvma.load_data(filename=str(bad))


def test_save_data_overwrite_prompt_on_normalised_name(tmp_path, monkeypatch):
    data = _make_full_dataset()
    target = tmp_path / 'mytest'
    dvma.save_data(data, filename=str(target))
    assert (tmp_path / 'mytest.dvma').is_file()
    # second save without extension must hit the overwrite prompt for
    # mytest.dvma; answer 'n' and verify the file is unchanged
    before = (tmp_path / 'mytest.dvma').read_bytes()
    monkeypatch.setattr('builtins.input', lambda prompt: 'n')
    out = dvma.save_data(data, filename=str(target))
    assert out is None
    assert (tmp_path / 'mytest.dvma').read_bytes() == before
