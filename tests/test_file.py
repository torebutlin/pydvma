"""Tests for `pydvma.file` export paths that need no dialogs.

Covers the June 2026 review fix: the JW-logger MATLAB exporter's TF
branch tested `freq_data_all` (the FFT accumulator, which is the int 0
when no FFT data exists) instead of `tf_data_all`.
"""

import os
import sys
import warnings

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


def _time_data(fs, n, n_chans=2, seed=0):
    rng = np.random.default_rng(seed)
    return datastructure.TimeData(
        np.arange(n) / fs, rng.standard_normal((n, n_chans)),
        options.MySettings(fs=fs, channels=n_chans),
        channel_cal_factors=np.ones(n_chans))


def _dataset(*items):
    ds = datastructure.DataSet()
    for item in items:
        ds.add_to_dataset(item)
    return ds


def _jw_round_trip(tmp_path, ds, name='jw.mat'):
    """Export `ds` in the JW-logger layout; return (raw .mat dict, import)."""
    path = str(tmp_path / name)
    file.export_to_matlab_jwlogger(ds, filename=path,
                                   overwrite_without_prompt=True)
    return sio.loadmat(path), file.import_from_matlab_jwlogger(filename=path)


class TestJwloggerExportRoundTrip:
    """pydvma's own JW-logger export must import back. It did not: a
    time-only export wrote no `freq` (the sample rate — TypeError building
    the time axis) and a spectral one no `tfun` (KeyError). Genuine logger
    files carry both. Row 0 of `yspec` is skipped in comparisons: the
    writer copies the first positive bin into the DC row, as JW's does."""

    # Sizes where float rounding bit: 1000 Hz x 1023 grew a trailing zero
    # sample, 8533 Hz x 1000 zeroed the last real one.
    @pytest.mark.parametrize('fs, n', [(1000, 1024), (1000, 1023),
                                       (8533, 1000), (44100, 999)])
    def test_time_only_export_imports_back(self, tmp_path, fs, n):
        td = _time_data(fs=fs, n=n)
        raw, ds = _jw_round_trip(tmp_path, _dataset(td))
        assert float(np.ravel(raw['freq'])[0]) == pytest.approx(fs)
        assert 'tfun' not in raw          # JW time files carry no tfun
        back = ds.time_data_list[0]
        assert back.settings.fs == pytest.approx(fs)
        assert back.time_data.shape == td.time_data.shape
        np.testing.assert_allclose(back.time_axis, td.time_axis)
        np.testing.assert_allclose(back.time_data, td.time_data)
        assert ds.freq_data_list == [] and ds.tf_data_list == []

    def test_tsmax_is_the_amplitude_scale(self, tmp_path):
        """The logger plots its time window over [-tsmax, tsmax]
        (tsinit.m) and saves max|indata| there (tsmenu.m). pydvma wrote
        the capture's duration instead."""
        td = _time_data(fs=1000, n=3000)
        td.time_data *= 0.01
        raw, _ = _jw_round_trip(tmp_path, _dataset(td))
        assert float(np.ravel(raw['tsmax'])[0]) == pytest.approx(
            np.max(np.abs(td.time_data)))

    # 1021 Hz x 1000: freq = 2*fmax came out as 1020.9999999999999, which
    # MySettings's int() truncated to 1021 - 1. At an odd length 2*fmax is
    # not the sample rate at all: 1000 Hz x 1023 gave 999.02 Hz.
    @pytest.mark.parametrize('fs, n', [(1000, 1024), (1021, 1000),
                                       (1000, 1023)])
    def test_fft_export_imports_back_as_spectrum(self, tmp_path, fs, n):
        fft = analysis.calculate_fft(_time_data(fs=fs, n=n))
        raw, ds = _jw_round_trip(tmp_path, _dataset(fft))
        assert float(np.ravel(raw['freq'])[0]) == fs
        assert int(np.ravel(raw['tfun'])[0]) == 0
        assert ds.tf_data_list == []
        back = ds.freq_data_list[0]
        assert back.settings.fs == fs
        np.testing.assert_allclose(back.freq_axis, fft.freq_axis)
        np.testing.assert_allclose(back.freq_data[1:], fft.freq_data[1:])

    @pytest.mark.parametrize('fs, n', [(1000, 2048), (38399, 3001)])
    def test_tf_export_imports_back(self, tmp_path, fs, n):
        tf = analysis.calculate_tf(_time_data(fs=fs, n=n), ch_in=0,
                                   N_frames=4, window='hann')
        raw, ds = _jw_round_trip(tmp_path, _dataset(tf))
        assert float(np.ravel(raw['freq'])[0]) == fs
        assert int(np.ravel(raw['tfun'])[0]) == 1
        assert ds.freq_data_list == []
        back = ds.tf_data_list[0]
        assert back.settings.fs == fs
        np.testing.assert_allclose(back.freq_axis, tf.freq_axis)
        np.testing.assert_allclose(back.tf_data[1:], tf.tf_data[1:])

    def test_tf_takes_yspec_and_tfun_when_fft_is_present_too(self, tmp_path):
        td = _time_data(fs=1000, n=2048)
        fft = analysis.calculate_fft(td)
        tf = analysis.calculate_tf(td, ch_in=0, N_frames=4, window='hann')
        raw, ds = _jw_round_trip(tmp_path, _dataset(fft, tf))
        assert int(np.ravel(raw['tfun'])[0]) == 1
        assert ds.freq_data_list == []
        np.testing.assert_allclose(ds.tf_data_list[0].tf_data[1:],
                                   tf.tf_data[1:])

    # At these sizes the top bin used to come back as the pad value 1.
    @pytest.mark.parametrize('fs, n', [(1000, 1024), (44100, 999),
                                       (48019, 4096)])
    @pytest.mark.parametrize('kind', ['fft', 'tf'])
    def test_time_and_spectrum_from_one_capture_both_import(
            self, tmp_path, fs, n, kind):
        td = _time_data(fs=fs, n=n)
        if kind == 'fft':
            spec = analysis.calculate_fft(td)
        else:
            spec = analysis.calculate_tf(td, ch_in=0, N_frames=4,
                                         window='hann')
        raw, ds = _jw_round_trip(tmp_path, _dataset(td, spec))
        assert float(np.ravel(raw['freq'])[0]) == pytest.approx(fs)
        np.testing.assert_allclose(ds.time_data_list[0].time_data,
                                   td.time_data)
        if kind == 'fft':
            back, want = ds.freq_data_list[0].freq_data, spec.freq_data
            axis = ds.freq_data_list[0].freq_axis
        else:
            back, want = ds.tf_data_list[0].tf_data, spec.tf_data
            axis = ds.tf_data_list[0].freq_axis
        np.testing.assert_allclose(axis, spec.freq_axis)
        np.testing.assert_allclose(back[1:], want[1:])

    def test_time_rate_wins_and_spectra_follow_its_grid(self, tmp_path):
        """One `freq` serves both blocks (JW's logger shares it between its
        time and spectrum windows), so the TIME rate is written and the
        spectra are laid on `rfftfreq(npts, 1/freq)`: here a 500 Hz
        capture's TF, exported beside 1 kHz time data, keeps its own
        spacing and values and is padded with 1 above its 250 Hz band."""
        td = _time_data(fs=1000, n=1000)
        tf = analysis.calculate_tf(_time_data(fs=500, n=2048, seed=1),
                                   ch_in=0, N_frames=4, window='hann')
        raw, ds = _jw_round_trip(tmp_path, _dataset(td, tf))
        assert float(np.ravel(raw['freq'])[0]) == pytest.approx(1000)
        np.testing.assert_allclose(ds.time_data_list[0].time_axis,
                                   td.time_axis)
        back = ds.tf_data_list[0]
        df = tf.freq_axis[1] - tf.freq_axis[0]
        assert back.freq_axis[1] - back.freq_axis[0] == pytest.approx(df)
        assert back.freq_axis[-1] == pytest.approx(500)
        n = len(tf.freq_axis)
        np.testing.assert_allclose(back.freq_axis[:n], tf.freq_axis)
        np.testing.assert_allclose(back.tf_data[1:n], tf.tf_data[1:])
        np.testing.assert_allclose(back.tf_data[n:], 1)

    def test_spectra_above_the_time_nyquist_are_dropped_with_a_warning(
            self, tmp_path):
        td = _time_data(fs=500, n=500)
        tf = analysis.calculate_tf(_time_data(fs=1000, n=2048, seed=1),
                                   ch_in=0, N_frames=4, window='hann')
        with pytest.warns(UserWarning, match='above 250 Hz'):
            raw, ds = _jw_round_trip(tmp_path, _dataset(td, tf))
        back = ds.tf_data_list[0]
        assert back.freq_axis[-1] == pytest.approx(250)
        n = len(back.freq_axis)
        np.testing.assert_allclose(back.freq_axis, tf.freq_axis[:n])
        np.testing.assert_allclose(back.tf_data[1:], tf.tf_data[1:n])


class TestImportFromMatlabJwloggerMissingKeys:
    """A .mat with the logger's data but not the variables its axes need
    raises a ValueError naming the variable, not a bare TypeError or
    KeyError. pydvma's own JW export omitted both before they were fixed,
    so such files exist."""

    def test_missing_freq(self, tmp_path):
        path = str(tmp_path / 'nofreq.mat')
        sio.savemat(path, {'indata': np.zeros((8, 1)),
                           'buflen': np.array([[8]]),
                           'dt2': np.array([[1, 0, 0]]),
                           'tsmax': np.array([[1.0]])})
        with pytest.raises(ValueError, match="'freq'"):
            file.import_from_matlab_jwlogger(filename=path)

    def test_missing_tfun(self, tmp_path):
        path = _jw_tf_mat(tmp_path, [_frf(5)], npts=8, fs=100)
        d = sio.loadmat(path)
        del d['tfun']
        sio.savemat(path, {k: v for k, v in d.items()
                           if not k.startswith('__')})
        with pytest.raises(ValueError, match="'tfun'"):
            file.import_from_matlab_jwlogger(filename=path)

    def test_missing_npts(self, tmp_path):
        path = _jw_tf_mat(tmp_path, [_frf(5)], npts=8, fs=100)
        d = sio.loadmat(path)
        del d['npts']
        sio.savemat(path, {k: v for k, v in d.items()
                           if not k.startswith('__')})
        with pytest.raises(ValueError, match="'npts'"):
            file.import_from_matlab_jwlogger(filename=path)


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

    def test_datasets_own_save_data_can_overwrite_without_prompt(self, tmp_path, monkeypatch):
        """The method hard-coded ``overwrite_without_prompt=False``, so a
        scripted re-save blocked on ``input()``. Any prompt now fails the
        test instead of hanging it."""
        def no_prompt(*args):
            raise AssertionError('prompted: %r' % (args,))
        monkeypatch.setattr('builtins.input', no_prompt)
        ds = _make_multiset_dataset(n_sets=2)
        target = str(tmp_path / 'resave.dvma')
        ds.save_data(filename=target, sets=0, overwrite_without_prompt=True)
        out = ds.save_data(filename=target, overwrite_without_prompt=True)
        assert out == target
        assert len(container.load(target).time_data_list) == 2

    def test_datasets_own_save_data_still_prompts_by_default(self, tmp_path, monkeypatch):
        ds = _make_multiset_dataset(n_sets=1)
        target = str(tmp_path / 'resave.dvma')
        ds.save_data(filename=target)
        asked = []
        monkeypatch.setattr('builtins.input', lambda q: asked.append(q) or 'n')
        assert ds.save_data(filename=target) is None
        assert len(asked) == 1


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

    def test_calibration_travels_with_the_exports(self, tmp_path):
        """CSV and MATLAB hold the RAW values plus each item's own
        calibration and units, exactly as a .dvma does."""
        ds = self._calibrated_dataset()
        for name, export in (('out.csv', file.export_to_csv),
                             ('out.mat', file.export_to_matlab)):
            back = file.load_data(export(ds, str(tmp_path / name),
                                         overwrite_without_prompt=True))
            td, tf = back.time_data_list[0], back.tf_data_list[0]
            np.testing.assert_array_equal(td.time_data, ds.time_data_list[0].time_data)
            np.testing.assert_allclose(td.channel_cal_factors, [10.0, 0.5])
            assert list(td.units) == ['m/s2', 'N']
            np.testing.assert_allclose(tf.channel_cal_factors, [20.0])
            assert list(tf.units) == ['(m/s2)/N']

    def test_the_csv_heading_shows_the_calibration(self, tmp_path):
        ds = self._calibrated_dataset()
        path = file.export_to_csv(ds, str(tmp_path / 'out.csv'))
        text = open(path, encoding='utf-8').read()
        assert '# Values are RAW, calibration NOT applied' in text
        assert 'TimeData; units m/s2, N; cal_factors 10, 0.5' in text

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
        path = file.export_to_matlab(ds, str(tmp_path / 'o.mat'))
        cols = file.load_data(path).time_data_list[0].time_data
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


class TestExportsLoadBack:
    """CSV and MATLAB exports carry what a .dvma holds and `load_data`
    reads them back (the lossless-export round, 2026-10-06)."""

    @pytest.mark.parametrize('ext, export', [('csv', file.export_to_csv),
                                             ('mat', file.export_to_matlab)])
    def test_a_dataset_comes_back_as_a_dvma_would(self, tmp_path, ext, export):
        from _rich_dataset import assert_same_dataset, rich_dataset
        ds = rich_dataset()
        out = export(ds, str(tmp_path / ('x.' + ext)))
        dvma = file.save_data(ds, str(tmp_path / 'x.dvma'))
        assert_same_dataset(file.load_data(out), file.load_data(dvma))

    @pytest.mark.parametrize('ext, export', [('csv', file.export_to_csv),
                                             ('mat', file.export_to_matlab)])
    def test_a_bare_data_list_exports(self, tmp_path, ext, export):
        ds = _make_multiset_dataset(n_sets=2)
        back = file.load_data(export(ds.tf_data_list, str(tmp_path / ('t.' + ext))))
        assert len(back.tf_data_list) == 2 and len(back.time_data_list) == 0
        np.testing.assert_array_equal(back.tf_data_list[1].tf_data,
                                      ds.tf_data_list[1].tf_data)

    @pytest.mark.parametrize('ext, export', [('csv', file.export_to_csv),
                                             ('mat', file.export_to_matlab)])
    def test_sets_of_different_lengths_export(self, tmp_path, ext, export):
        """Today's CSV crashed in np.append, and the .mat interpolated them
        onto one grid; each now keeps its own axis."""
        a, b = _time_data(fs=1000, n=64), _time_data(fs=3000, n=100, seed=1)
        back = file.load_data(export(_dataset(a, b), str(tmp_path / ('d.' + ext))))
        np.testing.assert_array_equal(back.time_data_list[0].time_axis, a.time_axis)
        np.testing.assert_array_equal(back.time_data_list[1].time_data, b.time_data)

    @pytest.mark.parametrize('export', [file.export_to_csv, file.export_to_matlab])
    def test_an_empty_export_is_refused(self, tmp_path, export):
        with pytest.raises(ValueError, match='nothing to export'):
            export(datastructure.DataSet(), str(tmp_path / 'empty.x'))
        assert not list(tmp_path.iterdir())

    def test_something_else_is_a_typeerror(self, tmp_path):
        with pytest.raises(TypeError, match='DataSet or a data list'):
            file.export_to_csv(np.zeros(3), str(tmp_path / 'z.csv'))

    def test_an_old_csv_export_is_refused_with_the_reason(self, tmp_path):
        path = tmp_path / 'old.csv'
        path.write_text('# pydvma export: RAW data, calibration NOT applied.\n'
                        '# Column 1 is the shared axis (s); the rest are data columns.\n'
                        '0,1\n1,2\n')
        with pytest.raises(ValueError, match='pydvma 2.6 or earlier'):
            file.load_data(str(path))

    def test_an_old_matlab_export_is_refused_with_the_reason(self, tmp_path):
        path = str(tmp_path / 'old.mat')
        sio.savemat(path, {'time_axis_all': np.arange(3.0)[:, None],
                           'time_data_all': np.ones((3, 2))})
        for load in (file.load_data, file.import_from_matlab_jwlogger):
            with pytest.raises(ValueError, match='pydvma 2.6 or earlier'):
                load(path)

    def test_a_vibration_apps_import_exports_and_comes_back(self, tmp_path):
        import warnings
        from _rich_dataset import assert_same_dataset
        v2 = os.path.join(os.path.dirname(__file__), 'data',
                          'vibration_apps_example_v2_time.csv')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            ds = file.load_data(v2)
        for ext, export in (('csv', file.export_to_csv), ('mat', file.export_to_matlab)):
            assert_same_dataset(file.load_data(export(ds, str(tmp_path / ('va.' + ext)))), ds)


@pytest.fixture
def no_qt(monkeypatch):
    """Make qtpy unimportable, as on a clean pydvma install. The file
    functions no longer touch Qt at all; with this in place, any code path
    that still tried would fail with ModuleNotFoundError instead of passing.
    Both names are blocked: a cached ``qtpy.QtWidgets`` would otherwise
    satisfy the import even with the parent package blocked."""
    monkeypatch.setitem(sys.modules, 'qtpy', None)
    monkeypatch.setitem(sys.modules, 'qtpy.QtWidgets', None)


class TestPositionalFilename:
    """Every file function takes a Qt dialog ``parent`` BEFORE ``filename``
    (a relic of the removed Qt logger), so ``dvma.load_data('x.dvma')``
    bound the path to ``parent`` and went to the dialog: TypeError inside
    QFileDialog, or ModuleNotFoundError for qtpy on a clean install. A
    str/PathLike ``parent`` with no ``filename`` is now the filename."""

    def test_load_data_positional_str(self, tmp_path, no_qt):
        ds = _make_multiset_dataset(n_sets=1)
        path = file.save_data(ds, filename=str(tmp_path / 'm.dvma'),
                              overwrite_without_prompt=True)
        loaded = file.load_data(path)
        assert len(loaded.time_data_list) == 1
        assert loaded.time_data_list[0].test_name == 'set0'

    def test_load_data_positional_pathlike(self, tmp_path, no_qt):
        ds = _make_multiset_dataset(n_sets=1)
        file.save_data(ds, filename=str(tmp_path / 'm.dvma'),
                       overwrite_without_prompt=True)
        loaded = file.load_data(tmp_path / 'm.dvma')
        assert len(loaded.time_data_list) == 1

    def test_save_data_positional_round_trips(self, tmp_path, no_qt):
        ds = _make_multiset_dataset(n_sets=2)
        out = file.save_data(ds, str(tmp_path / 'pos'))
        assert out == str(tmp_path / 'pos.dvma')
        loaded = file.load_data(out)
        assert len(loaded.time_data_list) == 2
        assert len(loaded.tf_data_list) == 2

    def test_save_data_positional_pathlike(self, tmp_path, no_qt):
        ds = _make_multiset_dataset(n_sets=1)
        out = file.save_data(ds, tmp_path / 'pos.dvma')
        assert out == str(tmp_path / 'pos.dvma')
        assert len(file.load_data(out).time_data_list) == 1

    def test_export_to_matlab_positional(self, tmp_path, no_qt):
        ds = _make_multiset_dataset(n_sets=1)
        out = file.export_to_matlab(ds, str(tmp_path / 'e.mat'))
        assert file.load_data(out).time_data_list[0].time_data.shape[1] == 2

    def test_export_to_matlab_jwlogger_positional(self, tmp_path, no_qt):
        ds = _make_multiset_dataset(n_sets=1)
        out = file.export_to_matlab_jwlogger(ds, str(tmp_path / 'jw.mat'))
        assert sio.loadmat(out)['indata'].shape[1] == 2

    def test_export_to_csv_positional(self, tmp_path, no_qt):
        ds = _make_multiset_dataset(n_sets=1)
        out = file.export_to_csv(ds.time_data_list, str(tmp_path / 't.csv'))
        assert out == str(tmp_path / 't.csv')
        assert file.load_data(out).time_data_list[0].time_data.shape[1] == 2

    def test_save_fig_positional(self, tmp_path, no_qt):
        from matplotlib.figure import Figure
        fig = Figure()
        fig.add_subplot().plot([0, 1], [0, 1])
        out = file.save_fig(fig, str(tmp_path / 'fig'))
        assert out == str(tmp_path / 'fig.pdf')
        assert (tmp_path / 'fig.png').is_file()
        assert (tmp_path / 'fig.pdf').is_file()

    def test_keyword_filename_ignores_parent(self, tmp_path, no_qt):
        """Keyword calls still work whatever ``parent`` is: it is ignored,
        with a DeprecationWarning, since there is no dialog for it."""
        ds = _make_multiset_dataset(n_sets=1)
        with pytest.warns(DeprecationWarning, match='parent'):
            out = file.save_data(ds, parent=object(),
                                 filename=str(tmp_path / 'kw.dvma'))
        assert out == str(tmp_path / 'kw.dvma')
        with pytest.warns(DeprecationWarning, match='parent'):
            loaded = file.load_data(parent=object(), filename=out)
        assert len(loaded.time_data_list) == 1

    def test_an_explicit_none_parent_is_silent(self, tmp_path, no_qt):
        ds = _make_multiset_dataset(n_sets=1)
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            out = file.save_data(ds, None, str(tmp_path / 'none.dvma'))
        assert out == str(tmp_path / 'none.dvma')


def _file_calls(tmp_path):
    """One no-filename call per file function, keyed by name."""
    from matplotlib.figure import Figure
    ds = _make_multiset_dataset(n_sets=1)
    fig = Figure()
    fig.add_subplot().plot([0, 1], [0, 1])
    return {
        'load_data': lambda: file.load_data(),
        'save_data': lambda: file.save_data(ds),
        'export_to_matlab': lambda: file.export_to_matlab(ds),
        'export_to_matlab_jwlogger': lambda: file.export_to_matlab_jwlogger(ds),
        'export_to_csv': lambda: file.export_to_csv(ds.time_data_list),
        'save_fig': lambda: file.save_fig(fig),
        'import_from_matlab_jwlogger': lambda: file.import_from_matlab_jwlogger(),
    }


class TestNoFilename:
    """pydvma no longer opens a Qt file dialog (Tore, 2026-09-29: the Qt
    GUI went in 2.0.0 and nothing else uses Qt). A call with no filename is
    a TypeError that names the function and shows a call that works, and no
    code path imports Qt (``no_qt`` would turn that into a
    ModuleNotFoundError)."""

    @pytest.mark.parametrize('name', [
        'load_data', 'save_data', 'export_to_matlab', 'export_to_matlab_jwlogger',
        'export_to_csv', 'save_fig', 'import_from_matlab_jwlogger'])
    def test_no_filename_is_a_typeerror_naming_the_function(self, tmp_path, no_qt, name):
        with pytest.raises(TypeError, match=r'%s\(\) needs a filename, e\.g\. %s\(' % (name, name)):
            _file_calls(tmp_path)[name]()

    def test_the_error_says_there_is_no_dialog(self, tmp_path, no_qt):
        with pytest.raises(TypeError, match='no longer opens a file dialog'):
            file.load_data()

    def test_nothing_is_written_when_the_filename_is_missing(self, tmp_path, no_qt, monkeypatch):
        monkeypatch.chdir(tmp_path)
        calls = _file_calls(tmp_path)
        for name in ('save_data', 'export_to_matlab', 'export_to_csv', 'save_fig'):
            with pytest.raises(TypeError):
                calls[name]()
        assert list(tmp_path.iterdir()) == []

    def test_no_qt_left_in_the_module(self):
        import inspect
        src = inspect.getsource(file)
        assert 'qtpy' not in src and 'QFileDialog' not in src


class TestImportFromMatlabJwloggerFileChecks:
    """A .mat with neither of the logger's variables imported as a
    silently EMPTY DataSet. (Its no-filename case is in `TestNoFilename`;
    pydvma 2.6's own exports are refused in `TestExportsLoadBack`.)"""

    def test_a_pydvma_export_is_sent_to_load_data(self, tmp_path):
        ds = _make_multiset_dataset(n_sets=1)
        path = file.export_to_matlab(ds, filename=str(tmp_path / 'own.mat'))
        with pytest.raises(ValueError, match='load it with load_data'):
            file.import_from_matlab_jwlogger(path)
        assert len(file.load_data(path).time_data_list) == 1

    def test_unrelated_mat_is_refused(self, tmp_path):
        path = str(tmp_path / 'other.mat')
        sio.savemat(path, {'x': np.arange(3.0)})
        with pytest.raises(ValueError,
                           match='Only JW-logger .mat files can be imported'):
            file.import_from_matlab_jwlogger(path)


def test_load_data_extensions_are_case_insensitive(tmp_path):
    """The web app sends `GUITAR.MAT` as named; it must load as a .mat."""
    path = str(tmp_path / 'GUITAR.MAT')
    sio.savemat(path, {'indata': np.ones((8, 1)), 'buflen': 8.0, 'freq': 4.0,
                       'dt2': np.array([[1.0, 0.0, 0.0]]), 'tsmax': 1.0})
    assert len(file.load_data(path).time_data_list) == 1
