"""Headless tests for the pure-logic parts of `pydvma.gui`.

Importing `pydvma.gui` creates a module-level QApplication, so the Qt
offscreen platform is forced before import; the module is skipped
entirely where the Qt stack can't load (bare CI without PyQt).

Covers the June 2026 review fixes in the GUI layer:
- the four ±1-era assumptions left from the volts refactor (output
  amplitude guard, clipping warning, post-log y-limits) via the new
  module-level helpers,
- the oscilloscope auto-scale divide-by-zero,
- the embedded-oscilloscope stream-reuse decision,
- `freq_max2` never calling `freq_max`, and the `data_typye` typo
  crashing empty-list deletes (tested as unbound methods on stubs).
"""

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest

try:
    from pydvma import gui
except Exception as e:  # pragma: no cover - environment-dependent
    pytest.skip('Qt GUI stack unavailable: {}'.format(e),
                allow_module_level=True)

import pydvma as dvma
from pydvma import datastructure, options, streams


# ---------- tiny stub building blocks ----------

class _Box:
    """Stand-in for a QLineEdit: .text() / .setText()."""

    def __init__(self, text=''):
        self._text = text
        self.set_calls = []

    def text(self):
        return self._text

    def setText(self, text):
        self.set_calls.append(text)


class _Combo:
    def __init__(self, text):
        self._text = text

    def currentText(self):
        return self._text


class _Stub:
    pass


def _make_time_data(values, settings):
    n = len(values)
    t = np.arange(n) / settings.fs
    return datastructure.TimeData(
        t, np.asarray(values).reshape(n, 1), settings,
        channel_cal_factors=np.ones(1),
    )


# ---------- voltage-aware helpers (were hard-coded to ±1) ----------

class TestPostLogClipWarning:

    def test_ni_data_below_vmax_is_clean(self):
        s = dvma.MySettings(device_driver='nidaq', VmaxNI=5.0, channels=1)
        td = _make_time_data(3.0 * np.sin(np.linspace(0, 20, 500)), s)
        assert gui._post_log_clip_warning(td, s) == ''

    def test_ni_data_near_vmax_warns(self):
        s = dvma.MySettings(device_driver='nidaq', VmaxNI=5.0, channels=1)
        td = _make_time_data(4.9 * np.ones(100), s)
        assert 'clip' in gui._post_log_clip_warning(td, s).lower()

    def test_uncalibrated_soundcard_keeps_old_threshold(self):
        s = dvma.MySettings(device_driver='soundcard', channels=1)
        td = _make_time_data(0.96 * np.ones(100), s)
        assert 'clip' in gui._post_log_clip_warning(td, s).lower()


class TestOutputWithinRange:

    def test_volts_above_one_allowed_within_output_vmax(self):
        s = dvma.MySettings(device_driver='mock',
                            output_device_driver='soundcard',
                            output_VmaxSC=2.0)
        y = 1.5 * np.ones((100, 1))
        assert gui._output_within_range(y, s) is True

    def test_above_output_vmax_rejected(self):
        s = dvma.MySettings(device_driver='mock',
                            output_device_driver='soundcard',
                            output_VmaxSC=2.0)
        y = 2.5 * np.ones((100, 1))
        assert gui._output_within_range(y, s) is False


class TestInputYlim:

    def test_ni_full_scale(self):
        s = dvma.MySettings(device_driver='nidaq', VmaxNI=5.0)
        assert gui._input_ylim(s) == [-5.0, 5.0]

    def test_uncalibrated_soundcard_is_unit(self):
        s = dvma.MySettings(device_driver='soundcard')
        assert gui._input_ylim(s) == [-1.0, 1.0]


# ---------- oscilloscope auto-scale ----------

class TestAutoscaleFactor:

    def test_constant_channel_gives_finite_positive(self):
        col = np.zeros(100)
        sf = gui._autoscale_factor(col, shift=0.0)
        assert np.isfinite(sf) and sf > 0

    def test_sine_channel_gives_twice_peak(self):
        col = 2.0 * np.sin(np.linspace(0, 20, 1000))
        sf = gui._autoscale_factor(col, shift=0.0)
        assert sf == pytest.approx(4.0, rel=1e-3)


# ---------- embedded oscilloscope stream reuse ----------

class TestOscStreamReuse:

    def test_reuses_live_matching_stream(self):
        s = dvma.MySettings(device_driver='mock', channels=2)
        streams.start_stream(s)
        try:
            assert gui._osc_can_reuse_stream(s) is True
            other = dvma.MySettings(device_driver='mock', channels=2)
            assert gui._osc_can_reuse_stream(other) is False
        finally:
            streams.REC.end_stream()

    def test_no_live_stream_means_no_reuse(self):
        s = dvma.MySettings(device_driver='mock', channels=2)
        streams.start_stream(s)
        streams.REC.end_stream()
        assert gui._osc_can_reuse_stream(s) is False


# ---------- unbound-method logic fixes ----------

class TestFreqMax2:

    def test_freq_max2_applies_and_refreshes(self):
        stub = _Stub()
        stub.freq_range = [0.0, 100.0]
        stub.input_freq_max2 = _Box('150.0')
        stub.input_freq_max = _Box()
        calls = []
        stub.freq_max = lambda: calls.append('freq_max')

        gui.Logger.freq_max2(stub)

        assert stub.freq_range[1] == 150.0
        assert stub.input_freq_max.set_calls == ['150.0']
        assert calls == ['freq_max']  # was referenced without calling


class TestDeleteWithEmptyList:

    def _stub(self):
        stub = _Stub()
        stub.auto_xy = ''
        stub.data_list = []
        stub.messages = []
        stub.update_selected_set = lambda: None
        stub.show_message = (
            lambda message, b=None: stub.messages.append(message))
        stub.input_list_data_type = _Combo('Time Data')
        stub.input_selected_set = _Box('0')
        return stub

    def test_delete_data_type_empty_shows_message(self):
        stub = self._stub()
        gui.Logger.delete_data_type(stub)  # was AttributeError data_typye
        assert any('Time Data' in m for m in stub.messages)

    def test_delete_data_set_empty_shows_message(self):
        stub = self._stub()
        gui.Logger.delete_data_set(stub)  # was AttributeError data_typye
        assert any('Time Data' in m for m in stub.messages)


class TestIncrementedFilename:

    def test_incremented_filename_extension_agnostic(self):
        from pydvma.gui import _incremented_filename
        assert _incremented_filename('run.dvma', 1) == 'run_1.dvma'
        assert _incremented_filename('run.npy', 3) == 'run_3.npy'
        assert _incremented_filename('/tmp/a b/run.dvma', 2) == '/tmp/a b/run_2.dvma'
        # no extension: counter still appended, extension left absent
        assert _incremented_filename('run', 1) == 'run_1'
