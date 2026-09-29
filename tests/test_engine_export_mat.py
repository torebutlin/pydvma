# -*- coding: utf-8 -*-
"""The browser's Export Matlab (`engine.export_mat`) against Python's.

The web app's **Export Matlab** does not run `file.export_to_matlab` — it
sends each set's decoded arrays to the `export_mat` engine op, which rebuilds
the same file without a DataSet. The two must stay one file format: the 2.5.0
calibration keys (`time_cal_factors` / `time_units` and the `freq_` / `tf_`
twins) were written by Python but silently missing from the app's `.mat`.

These tests feed the engine op exactly what `actions.exportMat` sends —
per-set `axis`, row-major `data` (or `re`/`im`), `cols`, and the per-column
`cal_factors` / `units` that `actions.exportArrays` resolves for the CSV
header — and hold the result to `file.export_to_matlab` on the same dataset.
"""
import io

import numpy as np
import pytest
import scipy.io as sio

import pydvma as dvma
from pydvma import analysis, datastructure, engine, file, options

#: The MAT-file v5 text header (bytes 0..115) carries a creation timestamp;
#: everything after it — subsystem offset, version, endianness and every
#: variable — must be identical between the two writers.
MAT_TEXT_HEADER_BYTES = 116


def _calibrated_dataset():
    """The shared impulse fixture, calibrated off the identity.

    Channel 0 is the hammer (N), channel 1 the response (m/s2); the factors
    are deliberately non-unit so a writer that dropped or defaulted them would
    show. FFT and TF are added so all three kinds are exported.
    """
    ds = dvma.create_test_impulse_data()
    td = ds.time_data_list[0]
    td.channel_cal_factors = np.array([250.0, 4.0])
    td.units = ['N', 'm/s2']
    ds.add_to_dataset(analysis.calculate_fft(td))
    ds.add_to_dataset(analysis.calculate_tf(td, ch_in=0))
    return ds


def _app_payload(ds):
    """The `export_mat` payload `actions.exportMat` builds for `ds`.

    The per-column factors and units are what `exportArrays` resolves: the
    channel's own for time and FFT, and for a TF the ratio cal[out]/cal[in]
    with its '(out)/in' unit — which is what pydvma already stores on the
    FreqData / TfData items, so they are read straight off them here.
    """
    def cal(item):
        return {'cal_factors': [float(f) for f in item.channel_cal_factors],
                'units': [str(u) for u in item.units]}

    time_sets = [dict(axis=td.time_axis, data=td.time_data.ravel(),
                      cols=td.time_data.shape[1], **cal(td))
                 for td in ds.time_data_list]
    freq_sets = [dict(axis=fd.freq_axis, re=fd.freq_data.real.ravel(),
                      im=fd.freq_data.imag.ravel(),
                      cols=fd.freq_data.shape[1], **cal(fd))
                 for fd in ds.freq_data_list]
    tf_sets = [dict(axis=tf.freq_axis, re=tf.tf_data.real.ravel(),
                    im=tf.tf_data.imag.ravel(),
                    cols=tf.tf_data.shape[1], **cal(tf))
               for tf in ds.tf_data_list]
    return dict(time_sets=time_sets, freq_sets=freq_sets, tf_sets=tf_sets)


def _python_mat_bytes(ds, tmp_path):
    path = str(tmp_path / 'python.mat')
    file.export_to_matlab(ds, filename=path, overwrite_without_prompt=True)
    with open(path, 'rb') as f:
        return f.read()


def _variables(mat_bytes):
    m = sio.loadmat(io.BytesIO(mat_bytes))
    return {k: v for k, v in m.items() if not k.startswith('__')}


def _unit_strings(cell):
    return [str(u[0]) for u in cell.ravel()]


def test_engine_mat_carries_the_calibration_keys():
    ds = _calibrated_dataset()
    m = _variables(engine.export_mat(**_app_payload(ds))['mat'])
    np.testing.assert_array_equal(m['time_cal_factors'].ravel(), [250.0, 4.0])
    assert _unit_strings(m['time_units']) == ['N', 'm/s2']
    np.testing.assert_array_equal(m['freq_cal_factors'].ravel(), [250.0, 4.0])
    assert _unit_strings(m['freq_units']) == ['N', 'm/s2']
    np.testing.assert_array_equal(m['tf_cal_factors'].ravel(), [4.0 / 250.0])
    assert _unit_strings(m['tf_units']) == ['(m/s2)/N']


def test_engine_mat_matches_python_export_key_for_key(tmp_path):
    ds = _calibrated_dataset()
    py = _variables(_python_mat_bytes(ds, tmp_path))
    app = _variables(engine.export_mat(**_app_payload(ds))['mat'])
    assert sorted(app) == sorted(py)
    for key in py:
        if key.endswith('_units'):
            assert _unit_strings(app[key]) == _unit_strings(py[key]), key
        else:
            assert app[key].shape == py[key].shape, key
            np.testing.assert_array_equal(app[key], py[key], err_msg=key)


def test_engine_mat_is_byte_identical_to_python_after_the_timestamp(tmp_path):
    """Same variables, same order, same encoding: only the creation time in
    the text header may differ — the `.mat` twin of the CSV byte parity."""
    ds = _calibrated_dataset()
    py = _python_mat_bytes(ds, tmp_path)
    app = engine.export_mat(**_app_payload(ds))['mat']
    assert len(app) == len(py)
    assert app[MAT_TEXT_HEADER_BYTES:] == py[MAT_TEXT_HEADER_BYTES:]


def test_engine_mat_without_calibration_writes_the_identity():
    """A payload with no calibration (a set never calibrated, or an older
    caller) still gets the keys — at the identity, `'-'` for the unit, the
    same defaults `file._column_calibration` applies to absent metadata."""
    ds = _calibrated_dataset()
    payload = _app_payload(ds)
    for s in payload['time_sets']:
        del s['cal_factors'], s['units']
    m = _variables(engine.export_mat(**payload)['mat'])
    np.testing.assert_array_equal(m['time_cal_factors'].ravel(), [1.0, 1.0])
    assert _unit_strings(m['time_units']) == ['-', '-']


#: Sizes where the common grid went wrong in both writers: `np.arange`'s
#: float stop added a trailing zero row, or `np.interp(..., right=0)`
#: zeroed the last sample or bin because the grid's end fell one ulp past
#: it. Each is ``(fs, n, tf_frames)``; the faults hit were: 1000 x 1023,
#: time and FFT each a row too long; 8533 x 1000, the last time sample
#: zeroed and the FFT a bin too long; 1000 x 1060, the FFT's top bin
#: zeroed; 1000 x 2048 in 4 frames, the TF a bin too long; 1000 x 2056 in
#: 2 frames, the TF's top bin zeroed. `tests/test_file.py`'s
#: `TestMatlabExportGrid` holds Python's exporter to the same sizes.
FLOAT_EDGE_CASES = [(1000, 1023, 1), (8533, 1000, 1), (1000, 1060, 1),
                    (1000, 2048, 4), (1000, 2056, 2)]


def _edge_dataset(fs, n, tf_frames):
    """One calibrated capture of ``n`` samples at ``fs``, with its FFT and
    its TF over ``tf_frames`` frames."""
    rng = np.random.default_rng(0)
    td = datastructure.TimeData(
        np.arange(n) / fs, rng.standard_normal((n, 2)),
        options.MySettings(fs=fs, channels=2),
        channel_cal_factors=np.array([250.0, 4.0]), units=['N', 'm/s2'])
    ds = datastructure.DataSet()
    ds.add_to_dataset(td)
    ds.add_to_dataset(analysis.calculate_fft(td))
    ds.add_to_dataset(analysis.calculate_tf(td, ch_in=0, N_frames=tf_frames,
                                            window='hann'))
    return ds


@pytest.mark.parametrize('fs, n, tf_frames', FLOAT_EDGE_CASES)
def test_engine_mat_keeps_each_kind_on_its_own_grid(fs, n, tf_frames):
    ds = _edge_dataset(fs, n, tf_frames)
    m = _variables(engine.export_mat(**_app_payload(ds))['mat'])
    for kind, want in (('time', ds.time_data_list[0].time_data),
                       ('freq', ds.freq_data_list[0].freq_data),
                       ('tf', ds.tf_data_list[0].tf_data)):
        got = m[kind + '_data_all']
        assert got.shape == want.shape, kind
        np.testing.assert_allclose(got, want, err_msg=kind)


@pytest.mark.parametrize('fs, n, tf_frames', FLOAT_EDGE_CASES)
def test_engine_mat_is_byte_identical_to_python_at_float_edge_sizes(
        tmp_path, fs, n, tf_frames):
    """The grid fix must land in both writers alike: at these sizes a fix
    in one alone changes a row count or a last value in that one."""
    ds = _edge_dataset(fs, n, tf_frames)
    py = _python_mat_bytes(ds, tmp_path)
    app = engine.export_mat(**_app_payload(ds))['mat']
    assert len(app) == len(py)
    assert app[MAT_TEXT_HEADER_BYTES:] == py[MAT_TEXT_HEADER_BYTES:]
