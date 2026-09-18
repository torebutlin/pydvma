"""Tests for `pydvma.file` export paths that need no dialogs.

Covers the June 2026 review fix: the JW-logger MATLAB exporter's TF
branch tested `freq_data_all` (the FFT accumulator, which is the int 0
when no FFT data exists) instead of `tf_data_all`.
"""

import numpy as np
import pytest
from scipy import io as sio

from pydvma import analysis, container, datastructure, file, options


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


def _make_multiset_dataset(n_sets=3, n_chans=2, fs=1000, n_samples=1024):
    """A DataSet with `n_sets` TimeData captures plus their FFTs/TFs,
    computed via the DataSet wrappers so id_links are real."""
    ds = datastructure.DataSet()
    for i in range(n_sets):
        rng = np.random.default_rng(i)
        settings = options.MySettings(fs=fs, channels=n_chans)
        time_axis = np.arange(n_samples) / fs
        td = datastructure.TimeData(
            time_axis,
            rng.standard_normal((n_samples, n_chans)),
            settings,
            channel_cal_factors=np.ones(n_chans),
            test_name='set{}'.format(i),
        )
        ds.add_to_dataset(td)
    ds.calculate_fft_set()
    ds.calculate_tf_set(ch_in=0)
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


class TestImportFromMatlabJwloggerTime:
    """Round-10 (JW's own testing): TIME files from the V2.9a logger save
    `indata, buflen, freq, dt2, tsmax` — NO `npts`, no `tfun`. The old
    import assumed `npts` and raised KeyError on JW's guitar_string
    captures. The axis must come from indata's own length at fs=freq, and
    the data must NOT be rescaled by tsmax (indata is already physical)."""

    @staticmethod
    def _jw_time_mat(tmp_path, y, fs=40000, name='jw_time.mat'):
        path = str(tmp_path / name)
        sio.savemat(path, {
            'indata': np.asarray(y),
            'buflen': np.array([[np.asarray(y).shape[0]]], dtype=np.int32),
            'freq': np.array([[fs]], dtype=np.uint16),
            'dt2': np.array([[np.atleast_2d(np.asarray(y).T).shape[0], 0, 0]],
                            dtype=np.uint8),
            'tsmax': np.array([[1.23]]),
        })
        return path

    def test_time_file_without_npts_imports(self, tmp_path):
        n, fs = 4000, 40000
        y = 0.5 * np.sin(2 * np.pi * 100 * np.arange(n) / fs)[:, None]
        path = self._jw_time_mat(tmp_path, y, fs=fs)
        ds = file.import_from_matlab_jwlogger(filename=path)
        td = ds.time_data_list[0]
        assert td.time_data.shape == (n, 1)
        assert td.settings.fs == fs
        assert td.time_axis[0] == 0.0
        assert td.time_axis[-1] == pytest.approx((n - 1) / fs)
        np.testing.assert_allclose(td.time_data, y)   # no tsmax rescale
        assert ds.tf_data_list == [] and ds.freq_data_list == []

    def test_multichannel_time_file(self, tmp_path):
        n, fs = 1000, 8000
        y = np.column_stack([np.sin(np.arange(n) / 7.0),
                             np.cos(np.arange(n) / 11.0)])
        path = self._jw_time_mat(tmp_path, y, fs=fs)
        ds = file.import_from_matlab_jwlogger(filename=path)
        td = ds.time_data_list[0]
        assert td.time_data.shape == (n, 2)
        assert td.settings.channels == 2


class TestSaveDataSets:
    """`save_data(..., sets=...)` — the notebook counterpart of the web
    app's Save "Choose sets…" picker: `None` writes the dataset
    unchanged, an int/iterable writes `dataset.subset(sets)` instead
    (see `datastructure.DataSet.subset`)."""

    def test_sets_none_matches_the_unfiltered_save(self, tmp_path):
        ds = _make_multiset_dataset(n_sets=2)

        path_plain = file.save_data(
            ds, filename=str(tmp_path / 'plain'), overwrite_without_prompt=True)
        path_explicit_none = file.save_data(
            ds, filename=str(tmp_path / 'explicit_none'),
            overwrite_without_prompt=True, sets=None)

        loaded_plain = container.load(path_plain)
        loaded_none = container.load(path_explicit_none)

        assert len(loaded_plain.time_data_list) == len(loaded_none.time_data_list) == 2
        assert len(loaded_plain.freq_data_list) == len(loaded_none.freq_data_list) == 2
        assert len(loaded_plain.tf_data_list) == len(loaded_none.tf_data_list) == 2

    def test_sets_int_writes_exactly_that_measurements_family(self, tmp_path):
        ds = _make_multiset_dataset(n_sets=3)

        path = file.save_data(
            ds, filename=str(tmp_path / 'subset'),
            overwrite_without_prompt=True, sets=1)
        loaded = container.load(path)

        assert len(loaded.time_data_list) == 1
        assert str(loaded.time_data_list[0].unique_id) == str(ds.time_data_list[1].unique_id)
        assert loaded.time_data_list[0].test_name == 'set1'
        assert len(loaded.freq_data_list) == 1
        assert len(loaded.tf_data_list) == 1
        assert str(loaded.freq_data_list[0].id_link) == str(ds.time_data_list[1].unique_id)
        assert str(loaded.tf_data_list[0].id_link) == str(ds.time_data_list[1].unique_id)

    def test_sets_iterable_writes_the_union_of_those_measurements(self, tmp_path):
        ds = _make_multiset_dataset(n_sets=3)

        path = file.save_data(
            ds, filename=str(tmp_path / 'subset_two'),
            overwrite_without_prompt=True, sets=[0, 2])
        loaded = container.load(path)

        loaded_names = sorted(td.test_name for td in loaded.time_data_list)
        assert loaded_names == ['set0', 'set2']
        assert len(loaded.freq_data_list) == 2
        assert len(loaded.tf_data_list) == 2

    def test_datasets_own_save_data_forwards_sets(self, tmp_path):
        """`DataSet.save_data(sets=...)` is the method-form equivalent of
        `file.save_data(dataset, sets=...)`."""
        ds = _make_multiset_dataset(n_sets=2)
        path = ds.save_data(filename=str(tmp_path / 'via_method'), sets=0)
        loaded = container.load(path)
        assert len(loaded.time_data_list) == 1
        assert loaded.time_data_list[0].test_name == 'set0'


class TestExportCalibrationMetadata:
    """The CSV and Matlab data exports write RAW (uncalibrated) arrays —
    deliberately — so they must at least SAY so and carry the factor that
    converts each column to engineering units.

    Before this, a channel calibrated to 100 mV/g read 5 g on screen and
    exported 0.5 with nothing in the file to explain the difference. The
    numbers are unchanged; only the metadata is new.
    """

    @staticmethod
    def _calibrated_dataset():
        fs, n = 1000, 64
        settings = options.MySettings(
            fs=fs, channels=2, channel_sensitivities=[0.1, 2.0])
        cal = 1.0 / np.asarray(settings.channel_sensitivities)
        td = datastructure.TimeData(
            np.arange(n) / fs,
            np.random.default_rng(0).standard_normal((n, 2)),
            settings,
            units=['m/s2', 'N'],
            channel_cal_factors=cal,
        )
        ds = datastructure.DataSet()
        ds.add_to_dataset(td)
        ds.add_to_dataset(analysis.calculate_tf(td, ch_in=1))
        return ds

    def test_csv_header_names_the_factors_and_units(self, tmp_path):
        ds = self._calibrated_dataset()
        path = str(tmp_path / 'out.csv')
        file.export_to_csv(ds.time_data_list, filename=path,
                           overwrite_without_prompt=True)
        text = open(path, encoding='utf-8').read()
        assert '# pydvma export: RAW data, calibration NOT applied.' in text
        assert '# cal_factors: 10,0.5' in text
        assert '# units: m/s2,N' in text

    def test_csv_header_does_not_disturb_the_data_rows(self, tmp_path):
        """np.loadtxt and friends skip '#' lines, so the numbers a reader
        gets back are exactly what they always were."""
        ds = self._calibrated_dataset()
        path = str(tmp_path / 'out.csv')
        file.export_to_csv(ds.time_data_list, filename=path,
                           overwrite_without_prompt=True)
        loaded = np.loadtxt(path, delimiter=',')
        td = ds.time_data_list[0]
        assert loaded.shape == (len(td.time_axis), 3)
        np.testing.assert_allclose(loaded[:, 1:], td.time_data)   # RAW, uncalibrated

    def test_csv_tf_header_carries_the_ratio_and_out_over_in_unit(self, tmp_path):
        ds = self._calibrated_dataset()
        path = str(tmp_path / 'tf.csv')
        file.export_to_csv(ds.tf_data_list, filename=path,
                           overwrite_without_prompt=True)
        text = open(path, encoding='utf-8').read()
        assert '(Hz)' in text                       # axis unit follows the kind
        assert '# cal_factors: 20' in text          # cal[out]/cal[in] = 10/0.5
        # Parenthesised so the ratio cannot be read as m/(s2*N) —
        # `analysis.wrap_unit`, matched byte-for-byte by the browser.
        assert '# units: (m/s2)/N' in text

    def test_matlab_export_carries_cal_factors_and_units(self, tmp_path):
        ds = self._calibrated_dataset()
        path = str(tmp_path / 'out.mat')
        file.export_to_matlab(ds, filename=path, overwrite_without_prompt=True)
        m = sio.loadmat(path)
        # Additive: every key the exporter always wrote is still there.
        assert 'time_data_all' in m and 'time_axis_all' in m
        np.testing.assert_allclose(m['time_cal_factors'].ravel(), [10.0, 0.5])
        assert [str(u[0]) for u in m['time_units'].ravel()] == ['m/s2', 'N']
        np.testing.assert_allclose(m['tf_cal_factors'].ravel(), [20.0])

    def test_absent_calibration_renders_as_identity_not_blank(self, tmp_path):
        settings = options.MySettings(fs=100, channels=2)
        td = datastructure.TimeData(
            np.arange(8) / 100, np.zeros((8, 2)), settings)   # no units given
        ds = datastructure.DataSet()
        ds.add_to_dataset(td)
        path = str(tmp_path / 'plain.csv')
        file.export_to_csv(ds.time_data_list, filename=path,
                           overwrite_without_prompt=True)
        text = open(path, encoding='utf-8').read()
        assert '# cal_factors: 1,1' in text
        assert '# units: -,-' in text

    def test_format_cal_factor_matches_its_pinned_vectors(self):
        """These vectors are mirrored in `webui/tests/export/data.test.ts`,
        where the JavaScript twin `fmtCalFactor` is checked against the same
        table — the two must render a header identically."""
        for value, expected in file.CAL_FACTOR_FORMAT_VECTORS:
            assert file.format_cal_factor(value) == expected, value

    def test_format_cal_factor_never_writes_nan(self):
        for bad in (float('nan'), float('inf'), float('-inf')):
            assert file.format_cal_factor(bad) == '1'


class TestExportColumnCountFromArray:
    """`use_output_as_ch0` PREPENDS the drive column to `time_data` without
    bumping `settings.channels`, so any consumer trusting the setting reads
    one column short. The Matlab exporters did exactly that and silently
    dropped the last measured channel."""

    @staticmethod
    def _output_ch0_dataset():
        fs, n = 100, 32
        settings = options.MySettings(fs=fs, channels=2, use_output_as_ch0=True)
        # [drive, ch0, ch1] — three columns against settings.channels == 2.
        data = np.column_stack([np.full(n, 9.0), np.full(n, 1.0), np.full(n, 2.0)])
        td = datastructure.TimeData(
            np.arange(n) / fs, data, settings,
            channel_cal_factors=np.array([1.0, 1.0, 1.0]),
        )
        ds = datastructure.DataSet()
        ds.add_to_dataset(td)
        return ds

    def test_matlab_export_keeps_every_stored_column(self, tmp_path):
        ds = self._output_ch0_dataset()
        path = str(tmp_path / 'o.mat')
        file.export_to_matlab(ds, filename=path, overwrite_without_prompt=True)
        cols = sio.loadmat(path)['time_data_all']
        assert cols.shape[1] == 3                  # was 2: ch1 was dropped
        np.testing.assert_allclose(cols[0], [9.0, 1.0, 2.0])

    def test_jwlogger_export_keeps_every_stored_column(self, tmp_path):
        ds = self._output_ch0_dataset()
        path = str(tmp_path / 'o_jw.mat')
        file.export_to_matlab_jwlogger(ds, filename=path,
                                       overwrite_without_prompt=True)
        cols = sio.loadmat(path)['indata']
        assert cols.shape[1] == 3
        np.testing.assert_allclose(cols[0], [9.0, 1.0, 2.0])
