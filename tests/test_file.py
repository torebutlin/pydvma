"""Tests for `pydvma.file` export paths that need no dialogs.

Covers the June 2026 review fix: the JW-logger MATLAB exporter's TF
branch tested `freq_data_all` (the FFT accumulator, which is the int 0
when no FFT data exists) instead of `tf_data_all`.
"""

import numpy as np
import pytest
from scipy import io as sio

from pydvma import analysis, datastructure, file, options


def _make_tf_only_dataset(n_chans=2, fs=1000, n_samples=2048, seed=0):
    rng = np.random.default_rng(seed)
    settings = options.MySettings(fs=fs, channels=n_chans)
    time_axis = np.arange(n_samples) / fs
    td = datastructure.TimeData(
        time_axis,
        rng.standard_normal((n_samples, n_chans)),
        settings,
        channel_cal_factors=np.ones(n_chans),
        test_name='test',
    )
    tf = analysis.calculate_tf(td, ch_in=0, N_frames=4, window='hann')
    ds = datastructure.DataSet()
    ds.add_to_dataset(datastructure.TfDataList([tf]))
    return ds


class TestExportToMatlabJwloggerTf:

    def test_tf_only_dataset_exports(self, tmp_path):
        """A dataset holding TF data but no FFT data crashed with
        TypeError: the zero-handling line indexed `freq_data_all`
        (set to the int 0) instead of `tf_data_all`."""
        ds = _make_tf_only_dataset()
        out = str(tmp_path / 'tf_only.mat')
        file.export_to_matlab_jwlogger(ds, filename=out,
                                       overwrite_without_prompt=True)

        d = sio.loadmat(out)
        yspec = d['yspec']
        assert yspec.shape[1] == 1  # one TF channel (ch_out)
        assert np.iscomplexobj(yspec)
        assert np.all(np.isfinite(yspec))
        assert np.any(np.abs(yspec) > 0)


def _jw_tf_mat(tmp_path, cols, npts=1024, fs=2000, name='jw.mat'):
    """Write a synthetic JW-logger TF .mat: `yspec` from the given columns."""
    path = str(tmp_path / name)
    sio.savemat(path, {
        'yspec': np.column_stack(cols),
        'tfun': np.array([[1]], dtype=np.uint8),
        'npts': np.array([[npts]], dtype=np.uint16),
        'freq': np.array([[fs]], dtype=np.uint16),
        'dt2': np.array([[0, len(cols), 0]], dtype=np.uint8),
    })
    return path


def _frf(n, fn_bin=40, zeta=0.02, seed=1):
    """A complex SDOF-ish FRF column over n one-sided bins."""
    rng = np.random.default_rng(seed)
    w = np.arange(n, dtype=float)
    h = 1.0 / (fn_bin ** 2 - w ** 2 + 2j * zeta * fn_bin * w)
    return h + 1e-6 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))


class TestImportFromMatlabJwloggerTf:
    """Round-7e: JW TF import — frequency-axis convention and coherence
    columns (a coherence trace imported as a TF channel poisons modal fits;
    verified on JW guitar admittance files)."""

    def test_axis_is_rfftfreq_of_npts_at_fs(self, tmp_path):
        n = 1024 // 2 + 1
        path = _jw_tf_mat(tmp_path, [_frf(n)], npts=1024, fs=2000)
        ds = file.import_from_matlab_jwlogger(filename=path)
        tf = ds.tf_data_list[0]
        fa = np.asarray(tf.freq_axis)
        assert fa.shape == (n,)
        assert fa[0] == 0.0
        assert fa[-1] == pytest.approx(1000.0)          # fs/2
        assert fa[1] - fa[0] == pytest.approx(2000 / 1024)  # fs/npts

    def test_coherence_column_attaches_as_tf_coherence(self, tmp_path):
        n = 1024 // 2 + 1
        coh = np.clip(0.5 + 0.5 * np.cos(np.linspace(0, 3, n)), 0, 1)
        path = _jw_tf_mat(tmp_path, [_frf(n), coh.astype(complex)])
        ds = file.import_from_matlab_jwlogger(filename=path)
        tf = ds.tf_data_list[0]
        assert tf.tf_data.shape == (n, 1)               # coherence NOT a channel
        assert np.iscomplexobj(tf.tf_data)
        assert tf.tf_coherence is not None
        assert tf.tf_coherence.shape == (n, 1)
        assert not np.iscomplexobj(tf.tf_coherence)
        np.testing.assert_allclose(np.ravel(tf.tf_coherence), coh)
        assert tf.settings.channels == 1

    def test_column_order_is_preserved_when_coherence_leads(self, tmp_path):
        n = 1024 // 2 + 1
        coh = np.clip(np.linspace(0.2, 1.0, n), 0, 1)
        frf = _frf(n)
        path = _jw_tf_mat(tmp_path, [coh.astype(complex), frf])
        ds = file.import_from_matlab_jwlogger(filename=path)
        tf = ds.tf_data_list[0]
        np.testing.assert_allclose(np.ravel(tf.tf_data), frf)
        np.testing.assert_allclose(np.ravel(tf.tf_coherence), coh)

    def test_all_complex_columns_stay_tf_channels(self, tmp_path):
        n = 1024 // 2 + 1
        path = _jw_tf_mat(tmp_path, [_frf(n, seed=1), _frf(n, fn_bin=80, seed=2),
                                     _frf(n, fn_bin=120, seed=3)])
        ds = file.import_from_matlab_jwlogger(filename=path)
        tf = ds.tf_data_list[0]
        assert tf.tf_data.shape == (n, 3)
        assert tf.tf_coherence is None

    def test_documented_interleaved_layout_pairs_positionally(self, tmp_path):
        """The averaged-TF writer's layout (avtflogpars.m in the recovered
        V2.9a source): yspec = [H1, coh1, H2, coh2, ...] — each channel's TF
        followed by its coherence."""
        n = 1024 // 2 + 1
        h1, h2 = _frf(n, fn_bin=40, seed=1), _frf(n, fn_bin=90, seed=2)
        c1 = np.clip(np.linspace(0.9, 0.5, n), 0, 1)
        c2 = np.clip(np.linspace(0.3, 1.0, n), 0, 1)
        path = _jw_tf_mat(tmp_path, [h1, c1.astype(complex), h2, c2.astype(complex)])
        ds = file.import_from_matlab_jwlogger(filename=path)
        tf = ds.tf_data_list[0]
        assert tf.tf_data.shape == (n, 2)
        assert tf.tf_coherence.shape == (n, 2)
        np.testing.assert_allclose(tf.tf_data[:, 0], h1)
        np.testing.assert_allclose(tf.tf_data[:, 1], h2)
        np.testing.assert_allclose(tf.tf_coherence[:, 0], c1)
        np.testing.assert_allclose(tf.tf_coherence[:, 1], c2)
        assert tf.settings.channels == 2

    def test_ambiguous_mix_falls_back_to_all_tf(self, tmp_path):
        """2 FRFs + 1 coherence-like column: no clean pairing, so the historic
        behaviour (every column a TF channel) is kept — no data dropped."""
        n = 1024 // 2 + 1
        coh = np.clip(np.linspace(0.1, 0.9, n), 0, 1)
        path = _jw_tf_mat(tmp_path, [_frf(n, seed=1), _frf(n, fn_bin=90, seed=2),
                                     coh.astype(complex)])
        ds = file.import_from_matlab_jwlogger(filename=path)
        tf = ds.tf_data_list[0]
        assert tf.tf_data.shape == (n, 3)
        assert tf.tf_coherence is None
