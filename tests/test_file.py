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
