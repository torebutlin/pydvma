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
"""
import datetime
import os

import numpy as np
import pytest

from pydvma import container, datastructure, file, options

EXAMPLE = os.path.join(os.path.dirname(__file__), 'data',
                       'vibration_apps_example.csv')

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
        assert tf.tf_data[0, 0] == complex(-0.0331715, 0.000979455)
        assert tf.tf_coherence.shape == (836, 1)
        assert tf.tf_coherence[0, 0] == 0.97966
        # The stepped sine's points are not a uniform grid, and are kept so.
        f3 = example.tf_data_list[2].freq_axis
        assert not np.allclose(np.diff(f3), np.diff(f3)[0])

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
            assert tf.id_link is None              # no time data behind it

    def test_timestamp_is_when_it_was_measured(self, example):
        tf = example.tf_data_list[0]
        assert tf.timestamp == datetime.datetime(2026, 10, 6, 10, 1, 46,
                                                 523000, tzinfo=UTC)
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
        assert va['delay_s'] == '0.04241788'
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

    def test_any_other_csv_is_refused_with_a_reason(self, tmp_path):
        # pydvma's own CSV export is the obvious other CSV to try.
        tf = datastructure.TfData(np.linspace(0, 100, 11),
                                  np.ones((11, 1), dtype=complex), None,
                                  options.MySettings(channels=2, fs=1000))
        tfl = datastructure.TfDataList()
        tfl.append(tf)
        path = file.export_to_csv(tfl, filename=str(tmp_path / 'own.csv'),
                                  overwrite_without_prompt=True)
        with pytest.raises(ValueError, match='vibration-apps-tf-csv'):
            file.load_data(path)
        with pytest.raises(ValueError, match='vibration-apps-tf-csv'):
            file.import_from_vibration_apps_csv(path)


class TestFormatTolerance:
    def test_another_format_version_is_refused(self, tmp_path):
        path = _small_csv(
            tmp_path / 'v2.csv', ['# m1: test_name=a; fs=48000'], COLUMNS,
            ['1,100,1,0,0,0,0.9,1,0'],
            first_line='# Vibration Apps transfer functions '
                       '(vibration-apps-tf-csv 2)')
        with pytest.raises(ValueError, match='vibration-apps-tf-csv 2'):
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
            ['2,100,1,0,0,0,0.9,1,0', '2,110,1,0,0,0,0.9,1,0',
             '7,300,2,0,0,0,,2,0'])
        ds = file.import_from_vibration_apps_csv(path)
        assert [t.test_name for t in ds.tf_data_list] == ['m2 b', 'm7 g']
        assert len(ds.tf_data_list[0].freq_axis) == 2
        assert ds.tf_data_list[1].tf_coherence is None
        assert ds.tf_data_list[0].source_settings['vibration_apps']['notes'] == ['x', 'y']

    def test_windows_line_endings_and_a_bom_are_read(self, tmp_path):
        # A file opened and saved again on Windows (Excel) can gain both.
        path = _small_csv(
            tmp_path / 'crlf.csv', ['# m1: test_name=a; fs=48000'], COLUMNS,
            ['1,100,1,0,0,0,0.9,1,0'], newline='\r\n', bom=True)
        assert len(file.load_data(path).tf_data_list) == 1

    def test_rows_without_a_header_line_are_refused(self, tmp_path):
        # Measurement 3 has rows but no '# m3:' line: an edited or
        # truncated file, not something to import partly.
        path = _small_csv(
            tmp_path / 'cut.csv', ['# m1: test_name=a; fs=48000'], COLUMNS,
            ['1,100,1,0,0,0,0.9,1,0', '3,100,1,0,0,0,0.9,1,0'])
        with pytest.raises(ValueError, match='measurement 3'):
            file.import_from_vibration_apps_csv(path)
