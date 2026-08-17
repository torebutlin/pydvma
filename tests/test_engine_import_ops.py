# -*- coding: utf-8 -*-
"""pydvma.engine legacy/mat import ops — native-host safety (no fixed /tmp).

``legacy_to_dvma`` and ``mat_to_dvma`` round-trip through a file path
(``container.save`` / ``import_from_matlab_jwlogger`` both take a
FILENAME, not a buffer). In pyodide that path is an in-memory FS, so a
hard-coded ``/tmp/...`` name was harmless; under the native CPython host
it is a real filesystem write, and a fixed ``/tmp`` path is unsafe
cross-platform (absent on Windows, and a fixed name collides between
concurrent connections). These tests exercise the real import paths and
guard the ``tempfile``-based fix; they are expected to ALREADY PASS on
macOS/Linux (where ``/tmp`` exists) even before the fix — their job is
to keep passing once the fix lands, and to be the tests that would catch
a regression back to a fixed path on a system without one.
"""
import io

import numpy as np
import scipy.io

from pydvma import datastructure, options
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


def test_legacy_to_dvma_roundtrips_without_fixed_tmp(tmp_path, monkeypatch):
    # Run from a directory where a literal '/tmp' write would be caught if
    # the implementation regressed to fixed paths on a system without /tmp.
    monkeypatch.chdir(tmp_path)
    out = engine.legacy_to_dvma(_legacy_npy_bytes())
    assert isinstance(out['dvma'], (bytes, bytearray))
    assert len(out['dvma']) > 0


def test_mat_to_dvma_roundtrips_without_fixed_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fs = 100.0
    n = 200
    t = np.arange(n) / fs
    buf = io.BytesIO()
    scipy.io.savemat(buf, {'indata': np.sin(2 * np.pi * 5 * t)[:, None],
                           'buflen': float(n), 'freq': fs,
                           'dt2': np.array([[1.0, 0.0, 0.0]]), 'tsmax': 1.0})
    out = engine.mat_to_dvma(buf.getvalue())
    assert isinstance(out['dvma'], (bytes, bytearray))
    assert len(out['dvma']) > 0
