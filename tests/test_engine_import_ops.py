# -*- coding: utf-8 -*-
"""pydvma.engine import ops: legacy ``.npy`` and ``file_to_dvma``.

``file_to_dvma`` takes the bytes of any file Load Data accepts other than a
``.dvma`` (pydvma's own CSV and MATLAB exports, a JW-logger ``.mat``, the
Vibration Apps' CSV) and returns ``.dvma`` bytes, through
``pydvma.file.load_data`` itself, so the web app accepts exactly what
Python does. Its input goes through a per-call temporary directory (a real
filesystem write under the native host, so never a fixed ``/tmp`` path);
``legacy_to_dvma`` unpickles from memory. Each test runs from a CWD that is
not ``/tmp`` and checks the returned bytes load back with ``container.load``.
"""
import io

import numpy as np
import pytest
import scipy.io

from pydvma import container, datastructure, options
from pydvma import engine


def _legacy_npy_bytes():
    # `legacy_to_dvma` unpickles a length-1 OBJECT ndarray holding one
    # DataSet (`np.array([DataSet(...)])`) — the exact shape pre-1.4.0
    # pydvma pickled. A plain numeric array would skip the real
    # `d[0]` / `_normalise_legacy_dataset` / `container.save` path
    # entirely, so build a genuine DataSet with one TimeData instead.
    fs = 100.0
    t = np.arange(0, 1, 1 / fs)
    sig = np.sin(2 * np.pi * 5 * t)[:, None]
    settings = options.MySettings(channels=1, fs=fs)
    time_data = datastructure.TimeData(t, sig, settings)
    ds = datastructure.DataSet()
    ds.add_to_dataset(time_data)
    buf = io.BytesIO()
    np.save(buf, np.array([ds], dtype=object))
    return buf.getvalue()


def _load_dvma_bytes(tmp_path, dvma_bytes, name):
    # container.load_bytes could read `dvma_bytes` directly, but this
    # helper deliberately writes through tmp_path (a directory distinct
    # from wherever the op itself ran) first -- that proves the returned
    # bytes are a genuine on-disk-valid .dvma, not just "non-empty".
    path = tmp_path / name
    path.write_bytes(dvma_bytes)
    return container.load(str(path))


def test_legacy_to_dvma_roundtrips(tmp_path, monkeypatch):
    # legacy_to_dvma no longer touches the filesystem at all (it writes
    # straight to bytes via container.save_bytes); this chdir just keeps
    # the test independent of any stray /tmp state, matching its
    # mat_to_dvma sibling below.
    monkeypatch.chdir(tmp_path)
    out = engine.legacy_to_dvma(_legacy_npy_bytes())
    assert isinstance(out['dvma'], (bytes, bytearray))
    assert len(out['dvma']) > 0

    ds = _load_dvma_bytes(tmp_path, out['dvma'], 'legacy_roundtrip.dvma')
    assert len(ds.time_data_list) == 1
    td = ds.time_data_list[0]
    assert td.settings.fs == 100
    assert td.time_data.shape[0] == 100  # np.arange(0, 1, 1/100.0) -> 100 samples


def test_file_to_dvma_reads_a_jw_logger_mat(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fs = 100.0
    n = 200
    t = np.arange(n) / fs
    buf = io.BytesIO()
    scipy.io.savemat(buf, {'indata': np.sin(2 * np.pi * 5 * t)[:, None],
                           'buflen': float(n), 'freq': fs,
                           'dt2': np.array([[1.0, 0.0, 0.0]]), 'tsmax': 1.0})
    out = engine.file_to_dvma(buf.getvalue(), 'capture.mat')
    ds = _load_dvma_bytes(tmp_path, out['dvma'], 'mat_roundtrip.dvma')
    assert len(ds.time_data_list) == 1
    td = ds.time_data_list[0]
    assert td.settings.fs == 100
    assert td.time_data.shape[0] == n


@pytest.mark.parametrize('ext, export', [('csv', 'export_to_csv'),
                                         ('mat', 'export_to_matlab')])
def test_file_to_dvma_reads_pydvmas_own_exports(tmp_path, monkeypatch, ext, export):
    from pydvma import file
    from _rich_dataset import assert_same_dataset, rich_dataset
    monkeypatch.chdir(tmp_path)
    ds = rich_dataset()
    path = getattr(file, export)(ds, str(tmp_path / ('x.' + ext)))
    with open(path, 'rb') as f:
        out = engine.file_to_dvma(f.read(), 'x.' + ext)
    assert_same_dataset(_load_dvma_bytes(tmp_path, out['dvma'], 'x.dvma'), ds)


def test_file_to_dvma_reads_a_vibration_apps_csv(tmp_path, monkeypatch):
    import os
    monkeypatch.chdir(tmp_path)
    example = os.path.join(os.path.dirname(__file__), 'data',
                           'vibration_apps_example.csv')
    with open(example, 'rb') as f:
        out = engine.file_to_dvma(f.read(), 'measurements.csv')
    ds = _load_dvma_bytes(tmp_path, out['dvma'], 'va_roundtrip.dvma')
    assert [len(t.freq_axis) for t in ds.tf_data_list] == [836, 13380, 20, 13380, 836]
    assert ds.tf_data_list[3].tf_coherence is None


def test_file_to_dvma_refuses_other_files_by_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="mine.csv is not a CSV pydvma can load"):
        engine.file_to_dvma(b'a,b\n1,2\n', 'mine.csv')
    with pytest.raises(ValueError, match="pydvma 2.6 or earlier"):
        engine.file_to_dvma(b'# pydvma export: RAW data, calibration NOT applied.\n0,1\n', 'old.csv')
    with pytest.raises(ValueError, match="notes.txt"):
        engine.file_to_dvma(b'hello', 'notes.txt')


def test_file_to_dvma_keeps_only_the_base_name(tmp_path, monkeypatch):
    # a name from the browser is a file name, never a path to write to
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="evil.csv is not a CSV"):
        engine.file_to_dvma(b'a,b\n', '../../evil.csv')
    assert not (tmp_path.parent / 'evil.csv').exists()


@pytest.mark.parametrize('name', ['..', '.', ''])
def test_file_to_dvma_odd_names_are_a_clear_refusal(tmp_path, monkeypatch, name):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match='not a file pydvma can load'):
        engine.file_to_dvma(b'hello', name)
