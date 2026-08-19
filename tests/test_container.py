# -*- coding: utf-8 -*-
"""Tests for the .dvma container format (format v2) and the legacy
pickle reader. See dev/2026-07-01-web-ui-design.md, Stage 0.5."""
import io
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


def _write_prelist_legacy_npy(path, missing):
    """Write a synthetic pre-1.4.0 legacy .npy whose pickled DataSet is
    MISSING the ``*_list`` attributes named in ``missing``.

    Old pydvma pickles predate one or more of the per-kind list attributes
    (``modal_data_list`` arrived with modal fitting; ``sono_data_list`` with
    sonograms; ``cross_spec_data_list`` with multi-channel), so an unpickled
    DataSet lacks them. We simulate that by deleting the attributes from a
    real DataSet's ``__dict__`` before pickling it in the legacy
    ``np.array([DataSet])`` object-array form — deleting from ``__dict__``
    means the saved pickle state genuinely omits them, exactly as an old
    file would.
    """
    fs = 200.0
    n = 64
    settings = dvma.MySettings(channels=2, fs=fs, device_driver='mock')
    ta = np.arange(n) / fs
    tdata = np.column_stack([np.sin(2 * np.pi * 10 * ta), np.cos(2 * np.pi * 10 * ta)])
    td = datastructure.TimeData(ta, tdata, settings,
                                units=['N', 'm/s'], test_name='legacy set')
    ds = datastructure.DataSet(td)
    # Make it look old: drop the version stamp and the requested lists.
    del ds.__dict__['pydvma_version']
    for name in missing:
        del ds.__dict__[name]
    np.save(path, np.array([ds]))


def test_prelist_legacy_pickle_normalises_missing_modal_list(tmp_path):
    """A pre-1.4.0 pickle lacking ``modal_data_list`` must LOAD (compat
    contract) and normalise to an empty list — the round-5 grid_data.npy
    crash ``AttributeError: 'DataSet' object has no attribute
    'modal_data_list'`` at ``container.save``."""
    path = tmp_path / 'legacy_no_modal.npy'
    _write_prelist_legacy_npy(path, missing=['modal_data_list'])

    d = dvma.load_data(filename=str(path))
    assert isinstance(d.modal_data_list, datastructure.ModalDataList)
    assert len(d.modal_data_list) == 0
    # Real data survives the normalisation.
    assert len(d.time_data_list) == 1
    assert d.time_data_list[0].units == ['N', 'm/s']
    # No version stamp on the old file -> a placeholder, not a false claim.
    assert d.pydvma_version.startswith('unknown')
    # And it now saves to a real .dvma without raising (the crashing path).
    out = tmp_path / 'converted.dvma'
    container.save(d, str(out))
    d2 = container.load(str(out))
    assert len(d2.time_data_list) == 1


def test_prelist_legacy_pickle_normalises_all_missing_lists(tmp_path):
    """Audit: a very old pickle can lack SEVERAL lists at once
    (cross-spectrum / sonogram / modal all postdate the earliest saves).
    Every absent list must come back as an empty instance of the right
    type so the whole codebase's ``len()``/iteration contracts hold."""
    path = tmp_path / 'legacy_no_lists.npy'
    missing = ['cross_spec_data_list', 'sono_data_list', 'modal_data_list']
    _write_prelist_legacy_npy(path, missing=missing)

    d = dvma.load_data(filename=str(path))
    assert isinstance(d.cross_spec_data_list, datastructure.CrossSpecDataList)
    assert isinstance(d.sono_data_list, datastructure.SonoDataList)
    assert isinstance(d.modal_data_list, datastructure.ModalDataList)
    for name in missing:
        assert len(getattr(d, name)) == 0
    # Fresh, fully-current DataSets are unaffected (no double-normalisation).
    fresh = datastructure.DataSet()
    assert len(fresh.modal_data_list) == 0
    container.save(d, str(tmp_path / 'ok.dvma'))


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


def test_v2_source_signature_and_settings_roundtrip(tmp_path):
    # Compute-chain provenance (derived-data save round): FFT/TF results
    # carry source_signature + source_settings, both optional meta.
    from pydvma import _signature
    data = dvma.create_test_impulse_data(noise_level=0)
    td = data.time_data_list[0]
    data.add_to_dataset(dvma.calculate_fft(td, window='hann'))
    data.add_to_dataset(dvma.calculate_tf(td, ch_in=0, N_frames=2))
    path = tmp_path / 'sig.dvma'
    container.save(data, str(path))
    loaded = container.load(str(path))

    expected = _signature.source_signature(td)
    fd = loaded.freq_data_list[0]
    assert fd.source_signature == expected
    assert fd.source_settings == {'calc': 'fft', 'window': 'hann',
                                  'time_range': [0.0, td.time_axis[-1]]}
    tf = loaded.tf_data_list[0]
    assert tf.source_signature == expected
    assert tf.source_settings['calc'] == 'tf'
    assert tf.source_settings['ch_in'] == 0
    assert tf.source_settings['N_frames'] == 2
    assert tf.source_settings['overlap'] == 0.5
    # the chain verifies against the time data that travelled with it
    assert (_signature.source_signature(loaded.time_data_list[0])
            == tf.source_signature)


def test_v2_sono_source_signature_and_settings_roundtrip(tmp_path):
    # Task 5b: SonoData joins the optional-meta provenance set, so a
    # sonogram saved by the app (or by a notebook) carries the chain it
    # was computed from — complex cube and all.
    from pydvma import _signature
    data = dvma.create_test_impulse_data(noise_level=0)
    td = data.time_data_list[0]
    sd = dvma.calculate_sonogram(td, nperseg=64, noverlap=32)
    data.add_to_dataset(sd)
    path = tmp_path / 'sono_sig.dvma'
    container.save(data, str(path))
    loaded = container.load(str(path))

    back = loaded.sono_data_list[0]
    assert back.source_signature == _signature.source_signature(td)
    assert back.source_settings == {'calc': 'sonogram', 'method': 'stft',
                                    'nperseg': 64, 'noverlap': 32}
    # the cube itself survives complex and 3-D, as it always did
    assert back.sono_data.shape == sd.sono_data.shape
    assert np.iscomplexobj(back.sono_data)
    np.testing.assert_allclose(back.sono_data, sd.sono_data)


def test_v2_sono_source_signature_absent_stays_absent(tmp_path):
    # Same "absence is no claim" contract as FreqData/TfData.
    data = dvma.create_test_impulse_data(noise_level=0)
    sd = dvma.calculate_sonogram(data.time_data_list[0], nperseg=64)
    del sd.source_signature
    del sd.source_settings
    data.add_to_dataset(sd)
    path = tmp_path / 'sono_nosig.dvma'
    container.save(data, str(path))
    loaded = container.load(str(path))
    assert not hasattr(loaded.sono_data_list[0], 'source_signature')
    assert not hasattr(loaded.sono_data_list[0], 'source_settings')


def test_v2_source_signature_absent_stays_absent(tmp_path):
    # A file whose derived items predate signatures must not gain them:
    # the app treats absence as "no claim", not as a broken chain.
    data = dvma.create_test_impulse_data(noise_level=0)
    data.calculate_fft_set()
    for fd in data.freq_data_list:
        del fd.source_signature
        del fd.source_settings
    path = tmp_path / 'nosig.dvma'
    container.save(data, str(path))
    loaded = container.load(str(path))
    assert not hasattr(loaded.freq_data_list[0], 'source_signature')
    assert not hasattr(loaded.freq_data_list[0], 'source_settings')


def test_v2_broken_chain_is_detectable_after_roundtrip(tmp_path):
    # The whole point: edit the time data after computing, and the
    # stored signature no longer matches its source.
    from pydvma import _signature
    data = dvma.create_test_impulse_data(noise_level=0)
    td = data.time_data_list[0]
    data.add_to_dataset(dvma.calculate_fft(td))
    td.time_data = td.time_data * 2.0        # e.g. a calibration rescale
    path = tmp_path / 'stale.dvma'
    container.save(data, str(path))
    loaded = container.load(str(path))
    assert (loaded.freq_data_list[0].source_signature
            != _signature.source_signature(loaded.time_data_list[0]))


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


def test_save_data_dialog_path_appends_extension(tmp_path, monkeypatch):
    # a user typing a bare name in the file-picker save dialog must
    # still get a .dvma file (the dialog path bypasses the explicit-
    # filename normalisation branch). file.py's no-filename fallback
    # pops a QFileDialog, which needs qtpy; that is no longer a declared
    # dependency (the Qt logger was removed at tag qt-final), so skip
    # gracefully on a base install where qtpy is absent.
    qw = pytest.importorskip('qtpy.QtWidgets')
    data = _make_full_dataset()
    target = str(tmp_path / 'typed_name')
    monkeypatch.setattr(qw.QFileDialog, 'getSaveFileName',
                        staticmethod(lambda *a, **k: (target, '')))
    out = dvma.save_data(data)
    assert out == target + '.dvma'
    assert (tmp_path / 'typed_name.dvma').is_file()


FIXTURE_DVMA = (pathlib.Path(__file__).resolve().parent.parent
                / 'webui' / 'tests' / 'fixtures' / 'impulse.dvma')


def _manifest_of(blob):
    with zipfile.ZipFile(io.BytesIO(blob), 'r') as zf:
        return json.loads(zf.read('manifest.json'))


def _extras_of(manifest):
    """Per-item {top-level extras} + {meta extras} for comparison."""
    out = []
    for entry in manifest['items']:
        out.append(container._collect_item_extra(entry, entry['kind']))
    return out


class TestManifestExtraPassthrough:
    """Manifest keys Python does not consume must SURVIVE a Python
    round-trip: the browser app stores per-item document state there
    (its `ui` block; ModalData's measurement_type / source_targets),
    and Session.push's load→merge→save cycle would otherwise destroy it
    on every push."""

    def test_unknown_item_and_meta_keys_survive_load_save_load(self):
        # A dataset as the app would have written it: a top-level `ui`
        # block on the capture, and unknown meta keys on the modal fit.
        ds = _make_full_dataset()
        blob = container.save_bytes(ds)
        manifest = _manifest_of(blob)
        for entry in manifest['items']:
            if entry['kind'] == 'TimeData':
                entry['ui'] = {'labels': ['hammer', 'accel'],
                               'analysis': {'nfft': 4096, 'iw_power': -2}}
            if entry['kind'] == 'ModalData':
                entry['meta']['measurement_type'] = 'acc'
                entry['meta']['source_targets'] = [
                    {'id_link': 'abc', 'ch_in': 0, 'n_channels': 2}]
        authored = _rezip_with_manifest(blob, manifest)

        loaded = container.load_bytes(authored)
        out = _manifest_of(container.save_bytes(loaded))

        by_kind = {e['kind']: e for e in out['items']}
        assert by_kind['TimeData']['ui'] == {
            'labels': ['hammer', 'accel'],
            'analysis': {'nfft': 4096, 'iw_power': -2}}
        assert by_kind['ModalData']['meta']['measurement_type'] == 'acc'
        assert by_kind['ModalData']['meta']['source_targets'] == [
            {'id_link': 'abc', 'ch_in': 0, 'n_channels': 2}]

    def test_second_round_trip_is_stable(self):
        # The stash must survive REPEATED cycles (every Session.push is
        # another one), not just the first.
        ds = _make_full_dataset()
        manifest = _manifest_of(container.save_bytes(ds))
        manifest['items'][0]['ui'] = {'labels': ['x']}
        authored = _rezip_with_manifest(container.save_bytes(ds), manifest)
        once = container.save_bytes(container.load_bytes(authored))
        twice = container.save_bytes(container.load_bytes(once))
        assert _manifest_of(twice)['items'][0]['ui'] == {'labels': ['x']}

    def test_known_fields_win_on_collision(self):
        # A stash whose key collides with a field Python owns must NOT
        # overwrite the object's own value.
        ds = _make_full_dataset()
        td = ds.time_data_list[0]
        setattr(td, container._ITEM_EXTRA_ATTR,
                {'kind': 'Nonsense', 'settings': 'nonsense',
                 'meta': {'test_name': 'stale', 'ui_only': 1}})
        entry = _manifest_of(container.save_bytes(ds))['items'][0]
        assert entry['kind'] == 'TimeData'
        assert entry['settings'] is None or isinstance(entry['settings'], dict)
        assert entry['meta']['test_name'] == 'roundtrip'
        assert entry['meta']['ui_only'] == 1      # genuinely unknown: kept

    def test_ordinary_objects_have_no_stash(self):
        # Absence must stay absence: nothing built in Python, and no
        # item from a file without extras, grows the attribute.
        ds = _make_full_dataset()
        loaded = container.load_bytes(container.save_bytes(ds))
        for name in datastructure.DataSet._LIST_ATTRS:
            for item in getattr(loaded, name):
                assert not hasattr(item, container._ITEM_EXTRA_ATTR)

    def test_stash_is_not_written_as_a_data_field(self):
        # It merges into the manifest dict only — never into `meta`
        # under its own name, and never as an array member.
        ds = _make_full_dataset()
        setattr(ds.time_data_list[0], container._ITEM_EXTRA_ATTR,
                {'ui': {'labels': ['a']}})
        entry = _manifest_of(container.save_bytes(ds))['items'][0]
        assert container._ITEM_EXTRA_ATTR not in entry
        assert container._ITEM_EXTRA_ATTR not in entry['meta']
        assert container._ITEM_EXTRA_ATTR not in entry['arrays']

    def test_non_dict_stash_is_ignored(self):
        ds = _make_full_dataset()
        setattr(ds.time_data_list[0], container._ITEM_EXTRA_ATTR, 'garbage')
        entry = _manifest_of(container.save_bytes(ds))['items'][0]
        assert entry['kind'] == 'TimeData'

    def test_real_webui_fixture_round_trips_losslessly(self):
        # REAL browser-authored bytes (webui's own test fixture): every
        # item's unconsumed manifest keys must come back byte-for-value
        # after load_bytes -> save_bytes. Generic on purpose — it holds
        # whatever that fixture carries today, and keeps holding when
        # the fixture is regenerated by a newer app.
        if not FIXTURE_DVMA.is_file():
            pytest.skip('webui fixture %s not present' % FIXTURE_DVMA)
        original = FIXTURE_DVMA.read_bytes()
        before = _manifest_of(original)
        after = _manifest_of(container.save_bytes(
            container.load_bytes(original)))
        assert [e['kind'] for e in after['items']] == \
            [e['kind'] for e in before['items']]
        assert _extras_of(after) == _extras_of(before)

    def test_pickle_round_trip_keeps_the_stash(self):
        # The stash is a plain dict attribute: pickling (the legacy .npy
        # path, and DataSet.__setstate__) must be unaffected by it.
        import pickle
        ds = _make_full_dataset()
        setattr(ds.time_data_list[0], container._ITEM_EXTRA_ATTR,
                {'ui': {'labels': ['a']}})
        out = pickle.loads(pickle.dumps(ds))
        assert getattr(out.time_data_list[0],
                       container._ITEM_EXTRA_ATTR) == {'ui': {'labels': ['a']}}


def _rezip_with_manifest(blob, manifest):
    """Rebuild `blob` with `manifest` swapped in (arrays untouched)."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(blob), 'r') as src:
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dst:
            for name in src.namelist():
                if name == 'manifest.json':
                    dst.writestr(name, json.dumps(manifest, indent=1))
                else:
                    dst.writestr(name, src.read(name))
    return out.getvalue()


class TestManifestIds:
    """container.manifest_ids: the journal's cheap capture identity."""

    def test_returns_every_item_unique_id(self):
        # Captures AND derived items (which have carried their own id
        # since the derived-data save round). The journal only ever asks
        # whether a capture's ids are a SUBSET of a document's, so the
        # wider set cannot make that test wrongly true — but it must
        # still contain every capture.
        ds = _make_full_dataset()
        blob = container.save_bytes(ds)
        captures = {str(td.unique_id) for td in ds.time_data_list}
        found = container.manifest_ids(blob)
        assert captures                                  # non-trivial
        assert captures <= found
        expected = set()
        for name in datastructure.DataSet._LIST_ATTRS:
            for item in getattr(ds, name, []) or []:
                uid = getattr(item, 'unique_id', None)
                if uid is not None:
                    expected.add(str(uid))
        assert found == expected

    def test_reads_manifest_only(self, monkeypatch):
        # No .npy member may be decompressed: this runs on whole
        # session documents, on the caller's thread.
        ds = _make_full_dataset()
        blob = container.save_bytes(ds)
        read = zipfile.ZipFile.read
        seen = []

        def spy(self, name, *a, **k):
            seen.append(name if isinstance(name, str) else name.filename)
            return read(self, name, *a, **k)

        monkeypatch.setattr(zipfile.ZipFile, 'read', spy)
        container.manifest_ids(blob)
        assert seen == ['manifest.json']

    def test_accepts_untagged_string_ids(self):
        # A hand-built / browser-authored manifest may carry the id as a
        # plain string rather than {'__uuid__': ...}.
        ds = _make_full_dataset()
        blob = container.save_bytes(ds)
        manifest = _manifest_of(blob)
        manifest['items'][0]['meta']['unique_id'] = 'plain-string-id'
        assert 'plain-string-id' in container.manifest_ids(
            _rezip_with_manifest(blob, manifest))

    @pytest.mark.parametrize('bad', [
        b'', b'not a zip at all', b'PK\x03\x04truncated',
    ])
    def test_malformed_bytes_give_an_empty_set(self, bad):
        assert container.manifest_ids(bad) == set()

    def test_zip_without_manifest_gives_an_empty_set(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('other.txt', 'hello')
        assert container.manifest_ids(buf.getvalue()) == set()

    def test_empty_dataset_has_no_ids(self):
        assert container.manifest_ids(
            container.save_bytes(datastructure.DataSet())) == set()


class TestBytesRoundTrip:

    def test_save_bytes_load_bytes_round_trip(self):
        ds = _make_full_dataset()
        blob = container.save_bytes(ds)
        out = container.load_bytes(blob)
        assert len(out.time_data_list) == len(ds.time_data_list)
        np.testing.assert_array_equal(out.time_data_list[0].time_data,
                                       ds.time_data_list[0].time_data)
        np.testing.assert_array_equal(out.freq_data_list[0].freq_data,
                                       ds.freq_data_list[0].freq_data)

    def test_load_bytes_reads_a_file_written_by_save(self, tmp_path):
        ds = _make_full_dataset()
        p = tmp_path / 'x.dvma'
        container.save(ds, str(p))
        out = container.load_bytes(p.read_bytes())
        assert len(out.time_data_list) == len(ds.time_data_list)
        np.testing.assert_array_equal(out.time_data_list[0].time_data,
                                       ds.time_data_list[0].time_data)
        np.testing.assert_array_equal(out.freq_data_list[0].freq_data,
                                       ds.freq_data_list[0].freq_data)

    def test_save_and_save_bytes_share_one_writer(self, tmp_path):
        # save() and save_bytes() must share ONE writer: assert the
        # member NAMES, manifest content, AND every member's raw payload
        # bytes agree between the two (byte-identity of the whole zip is
        # not required — zip metadata may embed timestamps — but the
        # member list, manifest, and each member's read() payload must
        # match exactly).
        ds = _make_full_dataset()
        p = tmp_path / 'x.dvma'
        container.save(ds, str(p))

        blob = container.save_bytes(ds)

        with zipfile.ZipFile(p, 'r') as zf_file:
            file_names = sorted(zf_file.namelist())
            file_manifest = json.loads(zf_file.read('manifest.json'))
            file_payloads = {name: zf_file.read(name) for name in file_names}
            file_compress = {name: zf_file.getinfo(name).compress_type
                              for name in file_names}
        with zipfile.ZipFile(io.BytesIO(blob), 'r') as zf_bytes:
            bytes_names = sorted(zf_bytes.namelist())
            bytes_manifest = json.loads(zf_bytes.read('manifest.json'))
            bytes_payloads = {name: zf_bytes.read(name) for name in bytes_names}
            bytes_compress = {name: zf_bytes.getinfo(name).compress_type
                               for name in bytes_names}

        assert file_names == bytes_names
        assert file_manifest == bytes_manifest
        assert file_payloads == bytes_payloads
        assert file_compress == bytes_compress

    def test_save_bytes_output_is_a_zip(self):
        ds = _make_full_dataset()
        assert container.save_bytes(ds)[:2] == b'PK'


class TestDerivedItemUniqueId:
    '''`unique_id` on the DERIVED kinds — the identity that makes a
    notebook pull -> push round trip REPLACE a stored result instead of
    appending a second copy of it (see `session._merge_dataset`).

    Optional meta by design: a file written before derived items carried
    ids must load with the attribute genuinely ABSENT, so
    ``getattr(item, 'unique_id', None)`` keeps reading "no identity".
    '''

    def test_every_derived_kind_mints_one(self):
        data = dvma.create_test_impulse_data(noise_level=0)
        td = data.time_data_list[0]
        derived = [
            dvma.calculate_fft(td),
            dvma.calculate_tf(td, ch_in=0, N_frames=2),
            dvma.calculate_cross_spectrum_matrix(td, N_frames=2),
            dvma.calculate_sonogram(td, nperseg=64, noverlap=32),
        ]
        ids = [item.unique_id for item in derived]
        assert all(isinstance(i, uuid.UUID) for i in ids)
        assert len(set(ids)) == len(ids)          # each item its own identity

    def test_roundtrip_preserves_each_id(self, tmp_path):
        data = dvma.create_test_impulse_data(noise_level=0)
        td = data.time_data_list[0]
        data.add_to_dataset(dvma.calculate_fft(td))
        data.add_to_dataset(dvma.calculate_tf(td, ch_in=0, N_frames=2))
        data.add_to_dataset(dvma.calculate_cross_spectrum_matrix(td, N_frames=2))
        data.add_to_dataset(dvma.calculate_sonogram(td, nperseg=64, noverlap=32))
        path = tmp_path / 'ids.dvma'
        container.save(data, str(path))
        loaded = container.load(str(path))

        for name in ('freq_data_list', 'tf_data_list',
                     'cross_spec_data_list', 'sono_data_list'):
            before = getattr(data, name)[0].unique_id
            after = getattr(loaded, name)[0].unique_id
            assert after == before, name
            # decoded back to a real UUID, not the manifest's tag dict
            assert isinstance(after, uuid.UUID), name

    def test_absent_id_stays_absent(self, tmp_path):
        # A pre-round file: no unique_id on the derived item. Loading must
        # not invent one, and must not leave a None behind either — some
        # later index map could key on it.
        data = dvma.create_test_impulse_data(noise_level=0)
        fd = dvma.calculate_fft(data.time_data_list[0])
        del fd.unique_id
        data.add_to_dataset(fd)
        path = tmp_path / 'no_id.dvma'
        container.save(data, str(path))
        loaded = container.load(str(path))
        assert not hasattr(loaded.freq_data_list[0], 'unique_id')

    def test_a_browser_written_string_id_survives(self, tmp_path):
        # The app mints a plain-string uuid (no `{'__uuid__': ...}` tag —
        # it does not apply pydvma's JSON tag scheme), so the reader must
        # hand that back unchanged rather than insisting on a UUID.
        data = dvma.create_test_impulse_data(noise_level=0)
        fd = dvma.calculate_fft(data.time_data_list[0])
        fd.unique_id = 'b6a0f1de-0000-4000-8000-000000000001'
        data.add_to_dataset(fd)
        path = tmp_path / 'str_id.dvma'
        container.save(data, str(path))
        loaded = container.load(str(path))
        assert loaded.freq_data_list[0].unique_id == fd.unique_id
