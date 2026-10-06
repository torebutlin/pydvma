# -*- coding: utf-8 -*-
"""Importing the Vibration Apps' transfer-function CSV.

The Transfer function app on the 3C6 course site
(torebutlin.github.io/vibration_apps/apps/frf/) saves every measurement it
holds as one CSV, format ``vibration-apps-tf-csv 1``: a block of ``#``
lines (one line of ``key=value`` pairs and one of notes per measurement),
a line of column names, then the rows, each starting with its measurement
number and each measurement on its own frequencies. The layout is written
up in ``dev/2026-10-06-vibration-apps-csv-import.md``.

``tests/data/vibration_apps_example.csv`` is a real file from the app (its
demo system): five measurements, a noise test in frames of 8192, a sweep
x4, a 20-point stepped sine, one frame of 2 s of noise (so no coherence),
and the noise test again with an added mass, hidden in the app when saved.
It carries an ``H_power`` column that this importer does not read.
"""
import datetime
import os
import re
import uuid
import warnings

import numpy as np
import pytest
import scipy.signal

from pydvma import container, datastructure, file, options

EXAMPLE = os.path.join(os.path.dirname(__file__), 'data',
                       'vibration_apps_example.csv')
# Format 2: the same, plus each measurement's time data (the app's "time
# data" box). Noise 1 s in frames of 4096, a sweep 0.5 s x2, and a 20-point
# stepped sine, which never has time data.
EXAMPLE_V2 = os.path.join(os.path.dirname(__file__), 'data',
                          'vibration_apps_example_v2_time.csv')

UTC = datetime.timezone.utc


def _small_csv(path, meta_lines, column_line, rows, first_line=None,
               newline='\n', bom=False):
    """Write a small file in the app's layout, for the edge cases."""
    lines = [first_line or '# Vibration Apps transfer functions '
                           '(vibration-apps-tf-csv 1)',
             '# units: H in microphone full scale per speaker full scale']
    lines += meta_lines
    lines.append(column_line)
    lines += rows
    text = newline.join(lines) + newline
    with open(path, 'w', encoding='utf-8-sig' if bom else 'utf-8',
              newline='') as fh:
        fh.write(text)
    return str(path)


COLUMNS = 'measurement,f_Hz,H1_re,H1_im,H1_dB,H1_phase_deg,coherence,H2_re,H2_im'


@pytest.fixture(scope='module')
def example():
    return file.import_from_vibration_apps_csv(EXAMPLE)


class TestExampleFile:
    def test_one_tf_per_measurement_in_file_order(self, example):
        tfs = example.tf_data_list
        assert [len(t.freq_axis) for t in tfs] == [836, 13380, 20, 13380, 836]
        assert [t.test_name for t in tfs] == [
            'm1 noise 10 s · 100 Hz–5 kHz',
            'm2 sweep 1 s ×4 · 100 Hz–5 kHz',
            'm3 sine 20 pts · 100 Hz–5 kHz',
            'm4 noise 2 s · 100 Hz–5 kHz',
            'm5 noise 10 s · 100 Hz–5 kHz + mass',
        ]
        # A TF file only: nothing else is made up.
        assert len(example.time_data_list) == 0
        assert len(example.freq_data_list) == 0

    def test_h1_and_coherence_are_the_rows(self, example):
        tf = example.tf_data_list[0]
        assert tf.freq_axis[0] == 105.46875
        assert tf.tf_data.shape == (836, 1)
        assert tf.tf_data[0, 0] == complex(-0.0332106, 0.00111427)
        assert tf.tf_coherence.shape == (836, 1)
        assert tf.tf_coherence[0, 0] == 0.97815
        # The stepped sine's points are not a uniform grid, and are kept so.
        f3 = example.tf_data_list[2].freq_axis
        assert not np.allclose(np.diff(f3), np.diff(f3)[0])

    def test_each_measurement_keeps_its_own_frequencies(self, example):
        # Not put onto a common grid: frames of 8192 start at the bin
        # 18*48000/8192, a sweep's repeat at its own padded length's bin.
        f1, f2 = example.tf_data_list[0].freq_axis, example.tf_data_list[1].freq_axis
        assert f1[0] == 105.46875
        assert f2[0] == 100.3418
        # (the app writes f to about 8 significant figures)
        np.testing.assert_allclose(np.diff(f1), 48000 / 8192, rtol=2e-5)

    def test_a_one_frame_result_has_no_coherence(self, example):
        # m4 is one frame of 2 s: its coherence column is empty (it is 1 by
        # definition), and an absent coherence is None, as for a BLA set.
        assert example.tf_data_list[3].tf_coherence is None

    def test_a_hidden_measurement_is_imported_all_the_same(self, example):
        tf = example.tf_data_list[4]
        assert tf.source_settings['vibration_apps']['view'] == 'hidden'
        assert len(tf.freq_axis) == 836

    def test_settings_units_and_calibration(self, example):
        for tf in example.tf_data_list:
            assert tf.settings.fs == 48000
            assert tf.settings.channels == 2       # one output + the input
            assert tf.settings.ch_in == 0
            assert list(tf.units) == ['-']
            np.testing.assert_array_equal(tf.channel_cal_factors, [1.0])
            # no time data behind it: a link id of its own (see TestCrossSpectra)
            assert isinstance(tf.id_link, uuid.UUID)

    def test_timestamp_is_when_it_was_measured(self, example):
        tf = example.tf_data_list[0]
        assert tf.timestamp == datetime.datetime(2026, 10, 6, 10, 31, 19,
                                                 223000, tzinfo=UTC)
        t = tf.timestamp.astimezone()
        assert tf.timestring == '_%d_%d_%d_at_%d_%d_%d' % (
            t.year, t.month, t.day, t.hour, t.minute, t.second)

    def test_provenance_and_the_apps_own_keys(self, example):
        ss = example.tf_data_list[0].source_settings
        assert ss['calc'] == 'vibration_apps_noise'
        assert ss['window'] == 'hann'
        assert ss['N_frames'] == 120
        assert ss['overlap'] == 0.5
        assert ss['nperseg'] == 8192
        va = ss['vibration_apps']
        assert va['delay_s'] == '0.03848005'
        assert va['estimator'] == 'H1'
        assert len(va['notes']) == 3
        assert va['notes'][0].startswith('delay through the measurement')
        # A stepped sine has no window or frames: those stay None.
        ss3 = example.tf_data_list[2].source_settings
        assert ss3['calc'] == 'vibration_apps_sine'
        assert ss3['window'] is None
        assert ss3['nperseg'] is None
        # No time data behind these, so no claim about a compute chain.
        assert not hasattr(example.tf_data_list[0], 'source_signature')

    def test_round_trips_through_dvma(self, example, tmp_path):
        path = str(tmp_path / 'va.dvma')
        file.save_data(example, filename=path, overwrite_without_prompt=True)
        back = file.load_data(path)
        assert [t.test_name for t in back.tf_data_list] == \
            [t.test_name for t in example.tf_data_list]
        for a, b in zip(example.tf_data_list, back.tf_data_list):
            np.testing.assert_array_equal(a.freq_axis, b.freq_axis)
            np.testing.assert_array_equal(a.tf_data, b.tf_data)
            assert b.timestamp == a.timestamp
            assert b.source_settings == a.source_settings
        assert back.tf_data_list[3].tf_coherence is None


class TestLoadData:
    def test_load_data_recognises_the_file(self):
        ds = file.load_data(EXAMPLE)
        assert [len(t.freq_axis) for t in ds.tf_data_list] == \
            [836, 13380, 20, 13380, 836]

    def test_recognised_by_content_not_extension(self, tmp_path):
        path = tmp_path / 'renamed.txt'
        with open(EXAMPLE, 'rb') as src:
            path.write_bytes(src.read())
        ds = file.load_data(str(path))
        assert len(ds.tf_data_list) == 5

    def test_pydvma_csv_loads_and_any_other_csv_is_refused(self, tmp_path):
        # pydvma's own CSV export is the obvious other CSV to try.
        tf = datastructure.TfData(np.linspace(0, 100, 11),
                                  np.ones((11, 1), dtype=complex), None,
                                  options.MySettings(channels=2, fs=1000))
        tfl = datastructure.TfDataList()
        tfl.append(tf)
        path = file.export_to_csv(tfl, filename=str(tmp_path / 'own.csv'),
                                  overwrite_without_prompt=True)
        # load_data reads it (pydvma's own export); this importer refuses it
        assert len(file.load_data(path).tf_data_list) == 1
        with pytest.raises(ValueError, match='vibration-apps-tf-csv'):
            file.import_from_vibration_apps_csv(path)
        # and a CSV that is neither is refused by load_data, with the reason
        other = tmp_path / 'other.csv'
        other.write_text('a,b\n1,2\n')
        with pytest.raises(ValueError, match='not a CSV pydvma can load'):
            file.load_data(str(other))


class TestFormatTolerance:
    def test_another_format_version_is_refused(self, tmp_path):
        path = _small_csv(
            tmp_path / 'v2.csv', ['# m1: test_name=a; fs=48000'], COLUMNS,
            ['1,100,1,0,0,0,0.9,1,0'],
            first_line='# Vibration Apps transfer functions '
                       '(vibration-apps-tf-csv 3)')
        with pytest.raises(ValueError, match='vibration-apps-tf-csv 3'):
            file.import_from_vibration_apps_csv(path)

    def test_unknown_keys_and_columns_are_ignored(self, tmp_path):
        # A later file may add keys and columns, and in any order: columns
        # are read by name.
        path = _small_csv(
            tmp_path / 'more.csv',
            ['# m1: test_name=a; fs=8000; wobble=3; channels=1; ch_in=0'],
            'f_Hz,extra,measurement,H2_im,H2_re,coherence,H1_im,H1_re',
            ['100,7,1,0,2,0.5,0.25,1.5',
             '200,7,1,0,2,0.75,0.5,2.5'])
        tf = file.import_from_vibration_apps_csv(path).tf_data_list[0]
        np.testing.assert_array_equal(tf.freq_axis, [100, 200])
        np.testing.assert_array_equal(tf.tf_data[:, 0], [1.5 + 0.25j, 2.5 + 0.5j])
        np.testing.assert_array_equal(tf.tf_coherence[:, 0], [0.5, 0.75])
        assert tf.settings.fs == 8000
        assert tf.source_settings['vibration_apps']['wobble'] == '3'

    def test_measurement_numbers_need_not_run_from_one(self, tmp_path):
        # Deleted cards leave gaps: the numbers are the app's card numbers.
        path = _small_csv(
            tmp_path / 'gaps.csv',
            ['# measurements: 2,7',
             '# m2: test_name=b; fs=48000', '# m2 notes: x | y',
             '# m7: test_name=g; fs=48000'],
            COLUMNS,
            ['2,100,1,0.1,0,0,0.9,1,0', '2,110,1,0.1,0,0,0.9,1,0',
             '7,300,2,0.1,0,0,,2,0'])
        ds = file.import_from_vibration_apps_csv(path)
        assert [t.test_name for t in ds.tf_data_list] == ['m2 b', 'm7 g']
        assert len(ds.tf_data_list[0].freq_axis) == 2
        assert ds.tf_data_list[1].tf_coherence is None
        assert ds.tf_data_list[0].source_settings['vibration_apps']['notes'] == ['x', 'y']

    def test_windows_line_endings_and_a_bom_are_read(self, tmp_path):
        # A file opened and saved again on Windows (Excel) can gain both.
        path = _small_csv(
            tmp_path / 'crlf.csv', ['# m1: test_name=a; fs=48000'], COLUMNS,
            ['1,100,1,0.1,0,0,0.9,1,0'], newline='\r\n', bom=True)
        assert len(file.load_data(path).tf_data_list) == 1

    def test_rows_without_a_header_line_are_refused(self, tmp_path):
        # Measurement 3 has rows but no '# m3:' line: an edited or
        # truncated file, not something to import partly.
        path = _small_csv(
            tmp_path / 'cut.csv', ['# m1: test_name=a; fs=48000'], COLUMNS,
            ['1,100,1,0,0,0,0.9,1,0', '3,100,1,0,0,0,0.9,1,0'])
        with pytest.raises(ValueError, match='measurement 3'):
            file.import_from_vibration_apps_csv(path)


def _format1_from(v2_path, out_path):
    """The format-1 file the app writes for the same measurements: format 2
    without its time section and the time_* keys that point into it (see
    the note: format 2 is "everything in format 1, then a second table")."""
    text = open(v2_path, encoding='utf-8').read().split('\n# section: time\n')[0] + '\n'
    text = text.replace('(vibration-apps-tf-csv 2)', '(vibration-apps-tf-csv 1)', 1)
    text = re.sub(r'; time_[a-z_]+=[^;\n]*', '', text)
    with open(out_path, 'w', encoding='utf-8') as fh:
        fh.write(text)
    return str(out_path)


class TestCrossSpectra:
    """Gxx and Gyy (one-sided densities, full scale^2/Hz) become a
    CrossSpecData per measurement, in pydvma's convention: Pxy a one-sided
    power SPECTRUM, density = Pxy / enbw_hz."""

    @pytest.fixture(scope='class')
    def v2(self):
        return file.import_from_vibration_apps_csv(EXAMPLE_V2)

    def test_one_per_measurement_with_auto_spectra(self, v2):
        # The stepped sine (m3) has no Gxx/Gyy, so no cross-spectrum.
        assert [c.test_name for c in v2.cross_spec_data_list] == [
            'm1 noise 1 s · 100 Hz–5 kHz', 'm2 sweep 0.5 s ×2 · 100 Hz–5 kHz']

    def test_none_from_a_file_without_the_columns(self, example):
        # The earlier format-1 example predates Gxx/Gyy.
        assert len(example.cross_spec_data_list) == 0

    def test_it_holds_the_files_spectra_and_h1(self, v2):
        tf = v2.tf_data_list[0]
        cs = v2.cross_spec_data_list[0]
        np.testing.assert_array_equal(cs.freq_axis, tf.freq_axis)
        assert cs.Pxy.shape == (2, 2, 418)
        w = scipy.signal.get_window('hann', 4096)
        assert cs.enbw_hz == pytest.approx(48000 * np.sum(w ** 2) / np.sum(w) ** 2, rel=1e-12)
        # the app's density back, and H1 = Pxy[in, out] / Pxy[in, in]
        assert np.real(cs.Pxy[0, 0, 0]) / cs.enbw_hz == pytest.approx(1.70675e-06, rel=1e-12)
        np.testing.assert_allclose(cs.Pxy[0, 1] / cs.Pxy[0, 0], tf.tf_data[:, 0], rtol=1e-12)
        np.testing.assert_allclose(cs.Pxy[1, 0], np.conj(cs.Pxy[0, 1]))
        np.testing.assert_allclose(cs.Cxy[0, 1], tf.tf_coherence[:, 0])
        np.testing.assert_allclose(cs.Cxy[0, 0], 1.0)
        # a sweep's repeat is rectangular, over its own length
        assert v2.cross_spec_data_list[1].enbw_hz == pytest.approx(48000 / 65536, rel=1e-12)

    def test_a_one_frame_result_has_coherence_one(self, tmp_path):
        path = _small_csv(
            tmp_path / 'one.csv',
            ['# m1: test_name=a; fs=8; window=hann; nperseg=8; N_frames=1'],
            COLUMNS + ',H_power,Gxx,Gyy',
            ['1,1,1,0.5,0,0,,1,0,,2,2', '1,2,1,0.5,0,0,,1,0,,3,3'])
        cs = file.import_from_vibration_apps_csv(path).cross_spec_data_list[0]
        np.testing.assert_allclose(cs.Cxy[0, 1], 1.0)

    def test_without_time_data_a_measurement_is_still_one_card(self, tmp_path):
        # The TF and the cross-spectrum share a link id of their own, so the
        # web app shows them as ONE set; each measurement has a different one.
        ds = file.import_from_vibration_apps_csv(
            _format1_from(EXAMPLE_V2, tmp_path / 'v1.csv'))
        assert len(ds.time_data_list) == 0
        links = [tf.id_link for tf in ds.tf_data_list]
        assert all(isinstance(k, uuid.UUID) for k in links)
        assert len(set(links)) == 3
        assert [c.id_link for c in ds.cross_spec_data_list] == links[:2]

    def test_round_trips_through_dvma(self, v2, tmp_path):
        path = str(tmp_path / 'cs.dvma')
        file.save_data(v2, filename=path, overwrite_without_prompt=True)
        back = file.load_data(path)
        a, b = v2.cross_spec_data_list[0], back.cross_spec_data_list[0]
        np.testing.assert_array_equal(a.Pxy, b.Pxy)
        assert b.enbw_hz == a.enbw_hz
        assert b.id_link == back.tf_data_list[0].id_link


class TestFormat2TimeData:
    @pytest.fixture(scope='class')
    def v2(self):
        return file.import_from_vibration_apps_csv(EXAMPLE_V2)

    def test_time_data_for_the_measurements_that_have_it(self, v2):
        assert [len(t.freq_axis) for t in v2.tf_data_list] == [418, 6690, 20]
        assert [t.test_name for t in v2.time_data_list] == [
            'm1 noise 1 s · 100 Hz–5 kHz', 'm2 sweep 0.5 s ×2 · 100 Hz–5 kHz']
        assert [t.time_data.shape for t in v2.time_data_list] == [(67200, 2), (86400, 2)]

    def test_time_axis_is_exact_from_fs(self, v2):
        td = v2.time_data_list[0]
        # the file rounds t_s to the microsecond; the axis is rebuilt from fs
        np.testing.assert_array_equal(td.time_axis, np.arange(67200) / 48000)
        assert td.settings.fs == 48000
        assert td.settings.channels == 2
        assert list(td.units) == ['-', '-']
        np.testing.assert_array_equal(td.channel_cal_factors, [1.0, 1.0])
        assert td.time_data[1, 0] == -1.559042e-9   # x, what was played
        assert td.time_data[1, 1] == 0.00139905     # y, the microphone
        assert td.timestamp == v2.tf_data_list[0].timestamp

    def test_tf_and_cross_spectrum_link_to_their_time_data(self, v2):
        for td, tf, cs in zip(v2.time_data_list, v2.tf_data_list,
                              v2.cross_spec_data_list):
            assert tf.id_link == td.unique_id
            assert cs.id_link == td.unique_id
        # the stepped sine has no time data and no cross-spectrum
        assert len(v2.cross_spec_data_list) == 2
        assert v2.tf_data_list[2].id_link not in \
            [td.unique_id for td in v2.time_data_list]

    def test_cross_spectrum_matches_welch_on_the_time_data(self, v2):
        # The app averages frames of 4096 with half overlap: pydvma's Pxx is
        # scipy's one-sided power SPECTRUM of x over the same frames.
        x = v2.time_data_list[0].time_data[:, 0]
        f, Pxx = scipy.signal.welch(x, 48000, 'hann', 4096, 2048, scaling='spectrum')
        cs = v2.cross_spec_data_list[0]
        k = np.rint(cs.freq_axis / (48000 / 4096)).astype(int)   # f is rounded in the file
        np.testing.assert_allclose(np.real(cs.Pxy[0, 0]), Pxx[k], rtol=1e-3)

    def test_the_time_section_is_not_read_as_tf_rows(self, v2):
        # every one of the file's 7128 TF rows, and nothing from the time table
        assert sum(len(t.freq_axis) for t in v2.tf_data_list) == 7128

    def test_round_trips_through_dvma(self, v2, tmp_path):
        path = str(tmp_path / 'v2.dvma')
        file.save_data(v2, filename=path, overwrite_without_prompt=True)
        back = file.load_data(path)
        np.testing.assert_array_equal(back.time_data_list[1].time_data,
                                      v2.time_data_list[1].time_data)
        assert back.tf_data_list[1].id_link == back.time_data_list[1].unique_id

    def test_time_rows_that_disagree_with_the_header_are_refused(self, tmp_path):
        path = _small_csv(
            tmp_path / 'short.csv',
            ['# m1: test_name=a; fs=4; time_rows=3'], COLUMNS,
            ['1,1,1,0,0,0,0.9,1,0', '# section: time', 'measurement,t_s,x,y',
             '1,0,0.1,0.2', '1,0.25,0.3,0.4'],
            first_line='# Vibration Apps transfer functions '
                       '(vibration-apps-tf-csv 2)')
        with pytest.raises(ValueError, match='measurement 1 .*2 time rows.*3'):
            file.import_from_vibration_apps_csv(path)


class TestNoPhase:
    def test_an_h1_without_phase_is_flagged(self, tmp_path):
        # An |H| from the powers alone, written as H1 with zero phase: its
        # phase, and so any modal fit, means nothing. Say so on the set.
        path = _small_csv(
            tmp_path / 'mag.csv', ['# m1: test_name=a; fs=48000'], COLUMNS,
            ['1,100,0.5,0,0,0,0.9,0.5,0', '1,110,0.7,0,0,0,0.9,0.7,0'])
        with pytest.warns(UserWarning, match='no phase'):
            tf = file.import_from_vibration_apps_csv(path).tf_data_list[0]
        assert tf.test_name == 'm1 a (|H| only, no phase)'
        assert tf.source_settings['magnitude_only'] is True

    def test_an_ordinary_h1_is_not(self, example):
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            ds = file.import_from_vibration_apps_csv(EXAMPLE)
        assert 'magnitude_only' not in ds.tf_data_list[0].source_settings
