"""Regression tests for `pydvma.datastructure` list/dataset operations.

Covers the June 2026 review fixes: the broken calibration setters on
TimeDataList/FreqDataList, ModalData deletion mutating the wrong list,
ModalData.add_mode/delete_mode corrupting the channel count, the
DataSet cross-spectrum wrapper ignoring its `window` argument, and
ModalData.__init__ mutating the caller's settings object.

Pure-Python, no hardware required.
"""

import numpy as np
import pytest

from pydvma import analysis, datastructure, modal, options


# ---------- helpers ----------

def _make_time_data(n_chans=2, fs=1000, n_samples=1024, seed=0):
    rng = np.random.default_rng(seed)
    settings = options.MySettings(fs=fs, channels=n_chans)
    time_axis = np.arange(n_samples) / fs
    return datastructure.TimeData(
        time_axis,
        rng.standard_normal((n_samples, n_chans)),
        settings,
        channel_cal_factors=np.ones(n_chans),
        test_name='test',
    )


def _make_modal_row(fn, zn, n_tfs, an=1.0, pn=0.0, rk=0.0, rm=0.0):
    """Pack one mode's parameters in the modal.py 'x' layout:
    [fn, zn, an×N, pn×N, rk×N, rm×N]."""
    return np.concatenate((
        [fn], [zn],
        np.full(n_tfs, an), np.full(n_tfs, pn),
        np.full(n_tfs, rk), np.full(n_tfs, rm),
    ))


# ---------- set_calibration_factor ----------

class TestSetCalibrationFactor:

    def test_timedatalist_sets_single_channel(self):
        tdl = datastructure.TimeDataList([_make_time_data(n_chans=2)])
        tdl.set_calibration_factor(2.5, n_set=0, n_chan=1)
        np.testing.assert_allclose(tdl[0].channel_cal_factors, [1.0, 2.5])

    def test_timedatalist_out_of_range_channel_is_noop(self):
        tdl = datastructure.TimeDataList([_make_time_data(n_chans=2)])
        tdl.set_calibration_factor(2.5, n_set=0, n_chan=5)  # prints, no raise
        np.testing.assert_allclose(tdl[0].channel_cal_factors, [1.0, 1.0])

    def test_freqdatalist_sets_single_channel(self):
        td = _make_time_data(n_chans=2)
        fdl = datastructure.FreqDataList([analysis.calculate_fft(td)])
        fdl.set_calibration_factor(3.0, n_set=0, n_chan=0)
        np.testing.assert_allclose(fdl[0].channel_cal_factors, [3.0, 1.0])

    def test_freqdatalist_out_of_range_channel_is_noop(self):
        td = _make_time_data(n_chans=2)
        fdl = datastructure.FreqDataList([analysis.calculate_fft(td)])
        fdl.set_calibration_factor(3.0, n_set=0, n_chan=7)  # prints, no raise
        np.testing.assert_allclose(fdl[0].channel_cal_factors, [1.0, 1.0])


# ---------- DataSet.remove_data_item_by_index ----------

class TestRemoveModalDataByIndex:

    def test_removes_from_modal_list_not_tf_list(self):
        ds = datastructure.DataSet()
        td = _make_time_data(n_chans=2)
        ds.add_to_dataset(datastructure.TfDataList(
            [analysis.calculate_tf(td, ch_in=0)]
        ))
        m0 = datastructure.ModalData(_make_modal_row(100.0, 0.01, n_tfs=1))
        m1 = datastructure.ModalData(_make_modal_row(200.0, 0.02, n_tfs=1))
        ds.add_to_dataset(datastructure.ModalDataList([m0, m1]))

        ds.remove_data_item_by_index('ModalData', 0)

        assert len(ds.modal_data_list) == 1
        assert len(ds.tf_data_list) == 1
        assert ds.modal_data_list[0] is m1


# ---------- ModalData add_mode / delete_mode ----------

class TestModalDataModeBookkeeping:

    def test_add_mode_channels_is_channel_count_not_mode_count(self):
        n_tfs = 3
        m = datastructure.ModalData(_make_modal_row(100.0, 0.01, n_tfs))
        assert m.channels == n_tfs
        m.add_mode(_make_modal_row(50.0, 0.02, n_tfs))
        assert m.channels == n_tfs  # was returning 2 (= number of modes)

    def test_delete_mode_channels_and_unpacked_properties(self):
        n_tfs = 3
        m = datastructure.ModalData(_make_modal_row(100.0, 0.01, n_tfs, an=2.0, pn=0.5))
        m.add_mode(_make_modal_row(50.0, 0.02, n_tfs, an=4.0, pn=-0.5))
        m.delete_mode(0)  # modes are frequency-sorted: removes the 50 Hz one

        assert m.channels == n_tfs
        fn, zn, an, pn, rk, rm = modal.unpack_matrix(m.M)
        np.testing.assert_allclose(m.fn, fn)
        np.testing.assert_allclose(m.zn, zn)
        np.testing.assert_allclose(m.an, an)
        np.testing.assert_allclose(m.pn, pn)
        assert np.shape(m.an) == (1, n_tfs)
        np.testing.assert_allclose(m.fn, [100.0])
        np.testing.assert_allclose(np.asarray(m.an), 2.0)

    def test_init_does_not_mutate_callers_settings(self):
        settings = options.MySettings(fs=1000, channels=5)
        datastructure.ModalData(settings=settings)
        assert settings.channels == 5  # was being zeroed in place

    def test_delete_last_mode_empties_model_without_raising(self):
        """Round-4 bug 2: deleting the LAST remaining mode used to raise
        IndexError inside modal.unpack_matrix (X[0, :] on a (0, 6) matrix),
        crashing both the webui Reject and Qt's Reject. The model must end
        up valid and empty."""
        n_tfs = 2
        m = datastructure.ModalData(_make_modal_row(100.0, 0.01, n_tfs))
        m.add_mode(_make_modal_row(200.0, 0.02, n_tfs))

        m.delete_mode(0)          # down to one mode — always worked
        m.delete_mode(0)          # delete the LAST mode — used to raise

        assert m.M.shape[0] == 0
        assert m.channels == n_tfs          # channel count preserved
        assert m.fn.size == 0 and m.zn.size == 0
        assert np.shape(m.an) == (0, n_tfs)
        assert np.shape(m.pn) == (0, n_tfs)

    def test_delete_all_modes_at_once_empties_model(self):
        """Deleting every row in a single call (the glue reject path) must
        also leave a valid empty model rather than raising."""
        n_tfs = 3
        m = datastructure.ModalData(_make_modal_row(100.0, 0.01, n_tfs))
        m.add_mode(_make_modal_row(200.0, 0.02, n_tfs))
        m.delete_mode([0, 1])
        assert m.M.shape[0] == 0
        assert m.fn.size == 0
        assert m.channels == n_tfs


# ---------- DataSet.calculate_cross_spectrum_matrix_set ----------

class TestCrossSpectrumSetWindowForwarding:

    def test_window_argument_is_forwarded(self):
        td = _make_time_data(n_chans=2, n_samples=2048)
        ds = datastructure.DataSet()
        ds.add_to_dataset(td)
        ds.calculate_cross_spectrum_matrix_set(window=None)
        # was hardcoded to 'hann' regardless of the argument; None must
        # reach analysis (which normalises it to scipy's 'boxcar')
        direct = analysis.calculate_cross_spectrum_matrix(td, window=None)
        np.testing.assert_allclose(ds.cross_spec_data_list[0].Pxy, direct.Pxy)
        assert ds.cross_spec_data_list[0].settings.window == 'boxcar'
