# -*- coding: utf-8 -*-
"""pydvma.engine legacy/mat import ops — native-host safety (no fixed /tmp).

``mat_to_dvma`` round-trips its ``.mat`` INPUT through a file path
(``import_from_matlab_jwlogger`` takes a FILENAME, not a buffer). In
pyodide that path is an in-memory FS, so a hard-coded ``/tmp/...`` name
was harmless; under the native CPython host it is a real filesystem
write, and a fixed ``/tmp`` path is unsafe cross-platform (absent on
Windows, and a fixed name collides between concurrent connections).
``legacy_to_dvma`` has no such need at all — it serialises its
``.dvma`` output straight to bytes via ``container.save_bytes`` — so
only ``mat_to_dvma`` still exercises the tempfile-safety story below;
its test is kept here alongside a plain bytes-in/bytes-out correctness
check for ``legacy_to_dvma``.

NOTE on what `monkeypatch.chdir` does and does not prove: it only
changes the CWD, so it cannot itself catch a regression to an ABSOLUTE
`/tmp/...` path (that would still resolve the same way regardless of
CWD) — these tests do not claim otherwise (see names below). What they
verify is the actual end-to-end behaviour of the ops: the returned
`.dvma` bytes load back with `container.load` into the same data that
went in (fs, sample count, item count), from a CWD that is NOT `/tmp`.
For `mat_to_dvma` that is real coverage of the tempfile mechanism, and
it is the regression net for a fixed-path bug on a system where `/tmp`
is simply absent (e.g. Windows) — such a system fails at the `open()`
call itself, which no CWD trick is needed to catch. They are expected
to ALREADY PASS on macOS/Linux (where `/tmp` exists) even before the
tempfile fix landed; their job is to keep passing once it did.
"""
import io

import numpy as np
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


def test_mat_to_dvma_roundtrips(tmp_path, monkeypatch):
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

    ds = _load_dvma_bytes(tmp_path, out['dvma'], 'mat_roundtrip.dvma')
    assert len(ds.time_data_list) == 1
    td = ds.time_data_list[0]
    assert td.settings.fs == 100
    assert td.time_data.shape[0] == n
