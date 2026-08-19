"""Regression tests for `pydvma.datastructure` list/dataset operations.

Covers the June 2026 review fixes: the broken calibration setters on
TimeDataList/FreqDataList, ModalData deletion mutating the wrong list,
ModalData.add_mode/delete_mode corrupting the channel count, the
DataSet cross-spectrum wrapper ignoring its `window` argument, and
ModalData.__init__ mutating the caller's settings object.

Pure-Python, no hardware required.
"""

import uuid

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


def _make_dataset(n_sets=3, n_chans=2, fs=1000, n_samples=1024):
    """A DataSet with `n_sets` independent TimeData captures, unfitted."""
    ds = datastructure.DataSet()
    for i in range(n_sets):
        ds.add_to_dataset(_make_time_data(n_chans=n_chans, fs=fs, n_samples=n_samples, seed=i))
    return ds


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


# ---------- DataSet.subset — notebook parity with the web app's
# "Choose sets…" picker (subsetDataset in
# webui/src/lib/analysis/actions.ts) ----------

class TestDataSetSubset:

    def test_picks_time_and_scalar_derived_items_by_kind(self):
        ds = _make_dataset(n_sets=3)
        ds.calculate_fft_set()
        ds.calculate_tf_set(ch_in=0)
        ds.calculate_sono_set()

        sub = ds.subset(1)

        assert list(sub.time_data_list) == [ds.time_data_list[1]]
        assert list(sub.freq_data_list) == [ds.freq_data_list[1]]
        assert list(sub.tf_data_list) == [ds.tf_data_list[1]]
        assert list(sub.sono_data_list) == [ds.sono_data_list[1]]
        # objects are the SAME ones, not copies
        assert sub.time_data_list[0] is ds.time_data_list[1]
        assert sub.freq_data_list[0] is ds.freq_data_list[1]

    def test_int_and_iterable_forms_are_equivalent(self):
        ds = _make_dataset(n_sets=3)
        ds.calculate_fft_set()

        sub_int = ds.subset(1)
        sub_list = ds.subset([1])
        sub_tuple = ds.subset((1,))

        for other in (sub_list, sub_tuple):
            assert list(sub_int.time_data_list) == list(other.time_data_list)
            assert list(sub_int.freq_data_list) == list(other.freq_data_list)

    def test_duplicate_indices_are_collapsed(self):
        ds = _make_dataset(n_sets=3)
        sub = ds.subset([1, 1, 1])
        assert len(sub.time_data_list) == 1
        assert sub.time_data_list[0] is ds.time_data_list[1]

    def test_out_of_range_index_raises_indexerror_with_valid_range(self):
        ds = _make_dataset(n_sets=3)
        with pytest.raises(IndexError, match=r'0\.\.2'):
            ds.subset(3)
        with pytest.raises(IndexError, match=r'0\.\.2'):
            ds.subset([0, 5])
        with pytest.raises(IndexError, match=r'0\.\.2'):
            ds.subset(-1)

    def test_empty_dataset_out_of_range_message_is_helpful(self):
        ds = datastructure.DataSet()
        with pytest.raises(IndexError, match='no TimeData items'):
            ds.subset(0)

    def test_scalar_and_list_id_link_any_but_not_all(self):
        """`analysis.calculate_tf_set` stamps a SCALAR id_link (one TF per
        TimeData); `analysis.calculate_tf_averaged` stamps a LIST id_link
        (one entry per source TimeData in the ensemble) — pin both shapes,
        and confirm the list case matches on ANY member, including a
        PARTIAL overlap with the picked sets, not on every member."""
        ds = _make_dataset(n_sets=3, n_chans=2)
        ds.calculate_tf_set(ch_in=0)
        assert all(isinstance(tf.id_link, uuid.UUID) for tf in ds.tf_data_list)

        avg_tf = analysis.calculate_tf_averaged(
            datastructure.TimeDataList(ds.time_data_list[0:2]), ch_in=0)
        assert avg_tf.id_link == [ds.time_data_list[0].unique_id, ds.time_data_list[1].unique_id]
        ds.add_to_dataset(avg_tf)

        sub0 = ds.subset([0])
        sub2 = ds.subset([2])
        sub_both = ds.subset([0, 2])

        # scalar per-set TF: exact match only
        assert ds.tf_data_list[0] in list(sub0.tf_data_list)
        assert ds.tf_data_list[2] not in list(sub0.tf_data_list)

        # list id_link: ANY member matching is enough
        assert avg_tf in list(sub0.tf_data_list)       # set 0 is a member
        assert avg_tf not in list(sub2.tf_data_list)    # set 2 is not a member at all
        # ANY, not ALL: set 2 doesn't overlap the ensemble, set 0 does
        assert avg_tf in list(sub_both.tf_data_list)

    def test_modal_data_any_rule_rides_the_set_it_links_to(self):
        """Mirrors modal.py's own construction (`modal_fit_all_channels`,
        `modal_refine`): `ModalData.id_link` is a LIST of the source
        TF(s)' own `id_link`, in `tf_data_list` order. A fit built from
        set 2's TF alone must ride a `[2]` subset, not a `[1]` subset."""
        ds = _make_dataset(n_sets=3, n_chans=2)
        ds.calculate_tf_set(ch_in=0)
        n_out = ds.tf_data_list[0].tf_data.shape[1]

        m = datastructure.ModalData(
            _make_modal_row(120.0, 0.01, n_out),
            id_link=[ds.tf_data_list[2].id_link],
        )
        ds.add_to_dataset(m)

        sub2 = ds.subset([2])
        sub1 = ds.subset([1])

        assert m in list(sub2.modal_data_list)
        assert m not in list(sub1.modal_data_list)

    def test_orphans_and_metadata_excluded_even_from_a_full_pick(self):
        """A derived item whose id_link resolves to nothing in this
        dataset, and MetaData (which never carries an id_link at all),
        are excluded from a subset — even one covering every valid
        TimeData index (subset() never falls back to "return everything
        unfiltered", unlike the web app's live-document short-circuit;
        see the DataSet.subset docstring)."""
        ds = _make_dataset(n_sets=2, n_chans=2)
        ds.calculate_fft_set()
        orphan = analysis.calculate_fft(_make_time_data(n_chans=2, seed=99))
        ds.add_to_dataset(orphan)
        ds.add_to_dataset(datastructure.MetaData())

        sub = ds.subset([0, 1])  # every valid TimeData index

        assert orphan not in list(sub.freq_data_list)
        assert len(sub.meta_data_list) == 0
        assert len(sub.freq_data_list) == 2  # the attributable items remain

    def test_items_are_shared_not_copied(self):
        ds = _make_dataset(n_sets=2, n_chans=2)
        ds.calculate_fft_set()
        sub = ds.subset([0])

        sub.time_data_list[0].test_name = 'mutated-through-subset'
        assert ds.time_data_list[0].test_name == 'mutated-through-subset'

        ds.freq_data_list[0].test_name = 'mutated-through-original'
        assert sub.freq_data_list[0].test_name == 'mutated-through-original'
