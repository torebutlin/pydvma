"""Per-channel full scale (``VmaxSC``), gain, mode and pad.

The Audient iD44 has four independent preamps, each with its own
analogue gain knob and -10 dB pad, so the voltage that reads full scale
differs per channel. `pydvma.options.MySettings` therefore accepts a
per-channel sequence for ``VmaxSC``, ``input_gain_db``, ``input_mode``
and ``input_pad``, and the capture path (the soundcard recorder's
scaling, the trigger level, the dropout and clip checks) judges each
channel against its own full scale.

What these tests pin down:

* A scalar keeps its exact current meaning: one value for every
  channel, a float ``VmaxSC``, the same numbers as before.
* Settings restored from an old ``.dvma`` (no ``__init__``, scalar
  ``VmaxSC``, no ``input_pad`` attribute) still answer every question
  the capture path asks.
* A channel count that changes after per-channel values are set (a
  mutation, or the soundcard clamp) truncates or pads the arrays; it
  never crashes or misaligns them.

All hardware-free: device names are faked through ``monkeypatch`` on
`pydvma.streams.soundcard_device_name`, as
``tests/test_soundcard_specs.py::TestSettingsIntegration`` does, and the
capture runs on the ``'mock'`` driver.
"""
import json
from types import SimpleNamespace

import numpy as np
import pytest

import pydvma as dvma
from pydvma import _soundcard_specs as specs
from pydvma import acquisition, container, options, session, streams

ID44 = 'Audient iD44'
SCARLETT = 'Scarlett 2i2 4th Gen'


def _soundcard_settings(monkeypatch, name=ID44, **kwargs):
    """MySettings on a soundcard whose name lookup is faked."""
    monkeypatch.setattr(streams, 'soundcard_device_name', lambda s: name)
    monkeypatch.setattr(streams, 'all_soundcard_device_names',
                        lambda: [] if name is None else [name])
    kwargs.setdefault('device_driver', 'soundcard')
    kwargs.setdefault('device_index', 0)
    kwargs.setdefault('fs', 48000)
    return options.MySettings(**kwargs)


def _mock_settings(**kwargs):
    base = dict(device_driver='mock', output_device_driver='mock',
                channels=2, fs=10000, chunk_size=1000, num_chunks=4,
                stored_time=0.1)
    base.update(kwargs)
    return dvma.MySettings(**base)


@pytest.fixture
def clean_streams():
    """Reset the module-level recorders around a mock capture."""
    streams.REC = None
    streams.REC_MOCK = None
    yield
    if streams.REC is not None:
        try:
            streams.REC.end_stream()
        except Exception:
            pass
    streams.REC = None
    streams.REC_MOCK = None


def _square(n, amplitude):
    """A +/-amplitude square wave: its peak is exactly ``amplitude`` and
    it has no exact zeros (which the dropout check would count)."""
    return amplitude * np.where(np.arange(n) % 2, 1.0, -1.0)


def _mock_with_peaks(monkeypatch, peaks):
    """Make every MockRecorder carry a square wave of the given peak on
    each channel, in place of its default 0.1 V sines."""
    class PeakedMock(streams.MockRecorder):
        def __init__(self, settings):
            super().__init__(settings)
            n = self.stored_time_data.shape[0]
            for ch, peak in enumerate(peaks):
                self.stored_time_data[:, ch] = _square(n, peak)

    monkeypatch.setattr(streams, 'MockRecorder', PeakedMock)


class TestScalarSettingsUnchanged:

    def test_scalar_settings_unchanged(self, monkeypatch):
        monkeypatch.setattr(streams, 'soundcard_device_name', lambda s: None)
        s = options.MySettings(VmaxSC=2.5)
        assert s.VmaxSC == 2.5
        assert isinstance(s.VmaxSC, float)
        assert s.input_vmax() == 2.5
        assert s.input_vmax(1) == 2.5
        np.testing.assert_array_equal(s.input_vmax_channels(), [2.5, 2.5])
        np.testing.assert_array_equal(s.channels_in_volts(), [True, True])
        assert s.input_gain_db is None
        assert s.input_mode == 'line'
        assert s.input_pad is False
        assert s.output_VmaxSC == 2.5

        ni = options.MySettings(device_driver='nidaq', VmaxNI=5)
        np.testing.assert_array_equal(ni.input_vmax_channels(), [5, 5])
        assert ni.input_vmax() == 5.0
        np.testing.assert_array_equal(ni.channels_in_volts(), [True, True])

    def test_uncalibrated_default_is_not_volts(self, monkeypatch):
        monkeypatch.setattr(streams, 'soundcard_device_name', lambda s: None)
        s = options.MySettings()
        assert s.VmaxSC == 1.0
        np.testing.assert_array_equal(s.channels_in_volts(), [False, False])

    def test_scalar_stated_gain_is_one_float_for_every_channel(
            self, monkeypatch):
        s = _soundcard_settings(monkeypatch, channels=4, input_gain_db=60,
                                input_mode='mic')
        expected = specs.full_scale_volts(ID44, 60, 'mic')
        assert isinstance(s.VmaxSC, float)
        assert s.VmaxSC == expected
        assert s.input_gain_db == 60.0
        assert s.input_mode == 'mic'
        # Never the mic rail: see test_id44_output_vmax_defaults_to_one.
        assert s.output_VmaxSC == 1.0

    def test_scalar_pad_adds_ten_db(self, monkeypatch):
        s = _soundcard_settings(monkeypatch, channels=2, input_gain_db=60,
                                input_mode='mic', input_pad=True)
        assert isinstance(s.VmaxSC, float)
        assert s.VmaxSC == pytest.approx(
            specs.full_scale_volts(ID44, 60, 'mic', pad=True))
        assert s.input_pad is True

    def test_pad_on_a_device_without_one_raises(self, monkeypatch):
        with pytest.raises(ValueError, match='no input pad'):
            _soundcard_settings(monkeypatch, name=SCARLETT, input_gain_db=9,
                                input_pad=True)


class TestPerChannelDerivation:

    def test_per_channel_gain_derives_per_channel_vmax(self, monkeypatch):
        s = _soundcard_settings(monkeypatch, channels=4,
                                input_gain_db=[60, 60, None, 0],
                                input_mode='mic')
        top = specs.full_scale_volts(ID44, 60, 'mic')
        assert isinstance(s.VmaxSC, np.ndarray)
        assert s.VmaxSC.shape == (4,)
        assert s.VmaxSC[0] == pytest.approx(top)
        assert s.VmaxSC[1] == pytest.approx(top)
        assert s.VmaxSC[2] == 1.0
        assert s.VmaxSC[3] == pytest.approx(
            specs.full_scale_volts(ID44, 0, 'mic'))
        np.testing.assert_array_equal(s.channels_in_volts(),
                                      [True, True, False, True])
        assert s.input_gain_db == [60.0, 60.0, None, 0.0]
        assert s.input_mode == 'mic'                 # scalar stays scalar
        assert s.input_pad is False
        assert s.input_vmax() == pytest.approx(np.max(s.VmaxSC))
        assert s.input_vmax(2) == 1.0
        assert s.input_vmax(0) == pytest.approx(top)
        # A per-channel input rail says nothing about the output jack.
        assert s.output_VmaxSC == 1.0

    def test_equal_channels_collapse_to_a_float(self, monkeypatch):
        s = _soundcard_settings(monkeypatch, channels=2,
                                input_gain_db=[60, 60], input_mode='mic')
        assert isinstance(s.VmaxSC, float)
        assert s.VmaxSC == pytest.approx(specs.full_scale_volts(ID44, 60, 'mic'))
        assert s.input_gain_db == [60.0, 60.0]
        assert s.output_VmaxSC == 1.0

    def test_per_channel_mode(self, monkeypatch):
        s = _soundcard_settings(monkeypatch, channels=2, input_gain_db=10,
                                input_mode=['MIC', 'line'])
        assert s.input_mode == ['mic', 'line']
        np.testing.assert_allclose(
            s.VmaxSC, [specs.full_scale_volts(ID44, 10, 'mic'),
                       specs.full_scale_volts(ID44, 10, 'line')])

    def test_per_channel_pad(self, monkeypatch):
        s = _soundcard_settings(monkeypatch, channels=4, input_gain_db=60,
                                input_mode='mic',
                                input_pad=[False, True, False, False])
        assert isinstance(s.VmaxSC, np.ndarray)
        assert s.VmaxSC[0] == pytest.approx(
            specs.full_scale_volts(ID44, 60, 'mic'))
        assert 20 * np.log10(s.VmaxSC[1] / s.VmaxSC[0]) == pytest.approx(
            10.0, abs=1e-12)
        assert s.VmaxSC[2] == s.VmaxSC[0]
        assert s.input_pad == [False, True, False, False]
        assert s.input_gain_db == 60.0               # scalar stays scalar

    def test_explicit_per_channel_vmax_without_a_device(self, monkeypatch):
        s = _soundcard_settings(monkeypatch, name=None, channels=3,
                                VmaxSC=[1.0, 2.0, 0.5])
        np.testing.assert_array_equal(s.VmaxSC, [1.0, 2.0, 0.5])
        np.testing.assert_array_equal(s.channels_in_volts(),
                                      [False, True, True])

    def test_stated_gain_overrides_explicit_vmax_per_channel(self,
                                                             monkeypatch):
        s = _soundcard_settings(monkeypatch, channels=2,
                                VmaxSC=[3.0, 3.0],
                                input_gain_db=[None, 60], input_mode='mic')
        assert s.VmaxSC[0] == 3.0
        assert s.VmaxSC[1] == pytest.approx(
            specs.full_scale_volts(ID44, 60, 'mic'))

    def test_wrong_length_raises(self, monkeypatch):
        with pytest.raises(ValueError, match='input_gain_db'):
            _soundcard_settings(monkeypatch, channels=4,
                                input_gain_db=[60, 60, 60])
        with pytest.raises(ValueError, match='VmaxSC'):
            _soundcard_settings(monkeypatch, channels=2,
                                VmaxSC=[1.0, 2.0, 3.0])

    def test_bad_gain_on_one_channel_raises(self, monkeypatch):
        with pytest.raises(ValueError, match='outside'):
            _soundcard_settings(monkeypatch, channels=2,
                                input_gain_db=[60, 80], input_mode='mic')

    def test_a_none_gain_string_means_unstated(self, monkeypatch):
        s = _soundcard_settings(monkeypatch, channels=2,
                                input_gain_db=['None', 60], input_mode='mic')
        assert s.input_gain_db == [None, 60.0]
        assert s.VmaxSC[0] == 1.0

    def test_optical_and_loopback_take_no_rail(self, monkeypatch):
        """The iD44's 16 ADAT inputs and 2 DAW loopbacks have no preamp
        of the iD44 in front of them, so a stated gain gives them no
        volts: a one-number gain becomes a per-channel rail."""
        s = _soundcard_settings(monkeypatch, channels=22, input_gain_db=60,
                                input_mode='mic')
        in_volts = s.channels_in_volts()
        assert in_volts[:4].tolist() == [True] * 4
        assert in_volts[4:].tolist() == [False] * 18
        assert isinstance(s.VmaxSC, np.ndarray)
        assert s.VmaxSC[0] == pytest.approx(
            specs.full_scale_volts(ID44, 60, 'mic'))
        assert s.VmaxSC[4] == 1.0
        assert s.VmaxSC[20] == 1.0
        assert s.input_gain_db == 60.0               # scalar stays scalar
        assert s.input_mode == 'mic'

    def test_per_channel_gain_on_optical_gives_no_rail(self, monkeypatch):
        s = _soundcard_settings(monkeypatch, channels=6,
                                input_gain_db=[60, None, None, None, 60, 60],
                                input_mode='mic')
        assert s.VmaxSC[0] == pytest.approx(
            specs.full_scale_volts(ID44, 60, 'mic'))
        np.testing.assert_array_equal(s.VmaxSC[1:], [1.0] * 5)
        assert s.channels_in_volts().tolist() == [True] + [False] * 5

    def test_explicit_vmax_on_optical_is_kept(self, monkeypatch):
        """An ADAT expander's own full scale, given per channel, is the
        operator's calibration of that channel and stands."""
        s = _soundcard_settings(monkeypatch, channels=6, input_gain_db=60,
                                input_mode='mic',
                                VmaxSC=[1.0, 1.0, 1.0, 1.0, 2.0, 1.0])
        assert s.VmaxSC[4] == 2.0
        assert s.VmaxSC[5] == 1.0
        assert s.VmaxSC[0] == pytest.approx(
            specs.full_scale_volts(ID44, 60, 'mic'))
        assert s.channels_in_volts().tolist() == [True] * 5 + [False]

    def test_inst_on_channel_without_di_raises(self, monkeypatch):
        """The iD44's D.I. input is on inputs 1-2 only."""
        with pytest.raises(ValueError, match='channel 3') as err:
            _soundcard_settings(monkeypatch, channels=4, input_gain_db=20,
                                input_mode=['mic', 'mic', 'inst', 'mic'])
        assert 'line, mic' in str(err.value)
        # 'inst' where it exists is fine, and an unstated channel is not
        # checked (nothing is derived there).
        s = _soundcard_settings(monkeypatch, channels=4,
                                input_gain_db=[20, 20, None, None],
                                input_mode=['inst', 'inst', 'inst', 'mic'])
        assert s.VmaxSC[0] == pytest.approx(
            specs.full_scale_volts(ID44, 20, 'inst'))
        with pytest.raises(ValueError, match='channel 3'):
            _soundcard_settings(monkeypatch, channels=4, input_gain_db=20,
                                input_mode='inst')

    def test_id44_output_vmax_defaults_to_one(self, monkeypatch):
        """Equal mic gains collapse VmaxSC to one float (8.7 mV); the
        output rail must not follow it, or a stimulus would play some
        40 dB too hot into the speakers."""
        s = _soundcard_settings(monkeypatch, channels=4,
                                input_gain_db=[60, 60, 60, 60],
                                input_mode='mic')
        assert isinstance(s.VmaxSC, float)
        assert s.output_VmaxSC == 1.0
        explicit = _soundcard_settings(monkeypatch, channels=4,
                                       input_gain_db=[60, 60, 60, 60],
                                       input_mode='mic', output_VmaxSC=2.0)
        assert explicit.output_VmaxSC == 2.0
        # An explicit one-number input VmaxSC does not set it either.
        plain = _soundcard_settings(monkeypatch, channels=4, VmaxSC=2.5)
        assert plain.VmaxSC == 2.5
        assert plain.output_VmaxSC == 1.0

    def test_2i2_unchanged(self, monkeypatch):
        """Regression pin: one rail on every channel of a 2i2, its
        loopback inputs 3-4 included, and the output follows it."""
        s = _soundcard_settings(monkeypatch, name=SCARLETT, channels=4,
                                input_gain_db=9, input_mode='line')
        expected = specs.full_scale_volts(SCARLETT, 9, 'line')
        assert isinstance(s.VmaxSC, float)
        assert s.VmaxSC == expected
        assert s.VmaxSC == pytest.approx(4.8932, abs=1e-3)
        assert s.output_VmaxSC == s.VmaxSC
        assert s.channels_in_volts().tolist() == [True] * 4
        # The U24 XL likewise.
        u24 = _soundcard_settings(monkeypatch, name='U24XL with SPDIF I/O',
                                  channels=2)
        assert isinstance(u24.VmaxSC, float)
        assert u24.output_VmaxSC == u24.VmaxSC

    def test_nidaq_ignores_per_channel_soundcard_gain(self):
        s = options.MySettings(device_driver='nidaq', channels=2, VmaxNI=5,
                               input_gain_db=[60, None])
        np.testing.assert_array_equal(s.input_vmax_channels(), [5.0, 5.0])
        assert s.input_vmax() == 5.0


class TestChannelCountChanges:

    def _four(self, monkeypatch):
        return _soundcard_settings(
            monkeypatch, channels=4, input_gain_db=[60, 60, None, 0],
            input_mode='mic', input_pad=[False, True, False, False])

    def test_per_channel_arrays_follow_channel_count(self, monkeypatch):
        s = self._four(monkeypatch)
        full = np.array(s.VmaxSC)
        s.channels = 2
        rails = s.input_vmax_channels()
        assert rails.shape == (2,)
        np.testing.assert_array_equal(rails, full[:2])
        assert s.channels_in_volts().shape == (2,)
        assert s.input_vmax() == pytest.approx(np.max(full[:2]))

        s.channels = 6                       # padded: unknown full scale
        rails = s.input_vmax_channels()
        assert rails.shape == (6,)
        np.testing.assert_array_equal(rails[:4], full)
        np.testing.assert_array_equal(rails[4:], [1.0, 1.0])
        np.testing.assert_array_equal(s.channels_in_volts()[4:],
                                      [False, False])
        assert s.input_vmax(5) == 1.0

    def test_soundcard_clamp_trims_per_channel_settings(self, monkeypatch,
                                                        capsys):
        s = self._four(monkeypatch)
        full = np.array(s.VmaxSC)
        fake = SimpleNamespace(
            query_devices=lambda index=None, kind=None: {
                'name': ID44, 'max_input_channels': 2},
            default=SimpleNamespace(device=[0, 0]),
            PortAudioError=Exception,
        )
        monkeypatch.setattr(streams, 'sd', fake)
        streams._clamp_soundcard_input_channels(s)
        assert s.channels == 2
        assert 'Clamping to 2' in capsys.readouterr().out
        np.testing.assert_array_equal(np.atleast_1d(s.VmaxSC), full[:2])
        assert s.input_gain_db == [60.0, 60.0]
        assert s.input_pad == [False, True]
        assert s.input_mode == 'mic'
        assert s.channel_sensitivities.shape == (2,)
        assert s.iepe_excit_current_A.shape == (2,)

        # The recorder then scales a (chunk, 2) block channel by channel.
        rec = streams.Recorder(s)
        chunk = np.ones((s.chunk_size, 2), dtype='float32')
        rec.callback(chunk, s.chunk_size, None, None)
        np.testing.assert_allclose(rec.osc_data_chunk,
                                   np.tile(full[:2], (s.chunk_size, 1)))

    def test_clamp_collapses_a_now_uniform_vmax(self, monkeypatch):
        s = _soundcard_settings(monkeypatch, channels=3,
                                input_gain_db=[60, 60, 0], input_mode='mic')
        assert isinstance(s.VmaxSC, np.ndarray)
        fake = SimpleNamespace(
            query_devices=lambda index=None, kind=None: {
                'name': ID44, 'max_input_channels': 2},
            default=SimpleNamespace(device=[0, 0]),
            PortAudioError=Exception,
        )
        monkeypatch.setattr(streams, 'sd', fake)
        streams._clamp_soundcard_input_channels(s)
        assert isinstance(s.VmaxSC, float)
        assert s.VmaxSC == pytest.approx(specs.full_scale_volts(ID44, 60, 'mic'))


class TestOldSettings:
    """A `.dvma` saved before this work restores scalar settings without
    ``__init__`` and has no ``input_pad`` attribute at all."""

    def _old(self, monkeypatch, **kwargs):
        monkeypatch.setattr(streams, 'soundcard_device_name', lambda s: None)
        base = dict(device_driver='soundcard', device_index=0, channels=2,
                    fs=8000, chunk_size=8, num_chunks=4, stored_time=0.004,
                    VmaxSC=2.5)
        base.update(kwargs)
        s = options.MySettings(**base)
        d = container._settings_to_dict(s)
        del d['input_pad']                       # not in an old file
        d = json.loads(json.dumps(d))            # as read from a manifest
        restored = container._settings_from_dict(d)
        assert not hasattr(restored, 'input_pad')
        return s, restored

    def test_old_settings_restore_scalar_paths(self, monkeypatch):
        original, s = self._old(monkeypatch)
        assert s.VmaxSC == 2.5
        np.testing.assert_array_equal(s.input_vmax_channels(), [2.5, 2.5])
        assert s.input_vmax() == 2.5
        np.testing.assert_array_equal(s.channels_in_volts(), [True, True])
        assert options.pretrig_level(s) == float('%.2g' % (0.05 * 2.5))

        sig = streams._sc_settings_signature(s)
        hash(sig)
        assert sig == streams._sc_settings_signature(original)

        doc = session._settings_to_config_json(s)
        assert 'input_pad' not in doc
        doc['pretrig_samples'] = 4
        summary = session._settings_summary(doc)
        assert 'trigger armed on ch 0 at 0.12 V' in summary

        # The recorder's scaling of a (chunk, ch) block is today's.
        rec = streams.Recorder(s)
        rng = np.random.default_rng(1)
        chunk = rng.uniform(-1, 1, (s.chunk_size, 2)).astype('float32')
        rec.callback(chunk, s.chunk_size, None, None)
        expected = np.reshape(np.copy(chunk) * 2.5, [s.chunk_size, 2])
        np.testing.assert_array_equal(rec.osc_data_chunk, expected)
        assert rec.osc_data_chunk.dtype == expected.dtype

    def test_old_settings_with_no_scale_fields_at_all(self, monkeypatch):
        """A pre-2.2 file has neither input_gain_db nor input_mode."""
        _, s = self._old(monkeypatch)
        del s.input_gain_db
        del s.input_mode
        np.testing.assert_array_equal(s.input_vmax_channels(), [2.5, 2.5])
        np.testing.assert_array_equal(s.channels_in_volts(), [True, True])

    def test_restored_per_channel_settings_round_trip(self, monkeypatch):
        s = _soundcard_settings(monkeypatch, channels=4,
                                input_gain_db=[60, 60, None, 0],
                                input_mode='mic',
                                input_pad=[False, True, False, False])
        d = json.loads(json.dumps(container._settings_to_dict(s)))
        r = container._settings_from_dict(d)
        np.testing.assert_array_equal(r.input_vmax_channels(), s.VmaxSC)
        assert r.input_gain_db == [60.0, 60.0, None, 0.0]
        assert r.input_pad == [False, True, False, False]
        np.testing.assert_array_equal(r.channels_in_volts(),
                                      [True, True, False, True])


class TestPretrigLevel:

    def test_pretrig_level_uses_trigger_channel(self):
        s = _mock_settings(VmaxSC=[1.0, 0.01], pretrig_channel=1)
        assert options.pretrig_level(s) == pytest.approx(0.05 * 0.01)
        s.pretrig_channel = 0
        assert options.pretrig_level(s) == pytest.approx(0.05)

    def test_stand_in_settings_with_a_list(self):
        probe = SimpleNamespace(device_driver='soundcard',
                                VmaxSC=[1.0, 0.01], pretrig_channel=1,
                                pretrig_threshold=None)
        assert options.pretrig_level(probe) == pytest.approx(0.0005)
        probe.pretrig_channel = 7                 # beyond the list
        assert options.pretrig_level(probe) == pytest.approx(0.05)

    def test_explicit_threshold_still_wins(self):
        s = _mock_settings(VmaxSC=[1.0, 0.01], pretrig_channel=1,
                           pretrig_threshold=0.2)
        assert options.pretrig_level(s) == 0.2

    def test_summary_judges_volts_on_the_trigger_channel(self):
        doc = {'fs': 48000, 'channels': 2, 'pretrig_samples': 10,
               'device_driver': 'soundcard', 'VmaxSC': [1.0, 0.01],
               'pretrig_channel': 1}
        assert 'trigger armed on ch 1 at 0.0005 V' in session._settings_summary(
            doc)
        doc['pretrig_channel'] = 0
        assert 'at 0.05 × full scale' in session._settings_summary(doc)


class TestCaptureChecks:

    def test_clip_check_per_channel(self, monkeypatch, capsys, clean_streams):
        _mock_with_peaks(monkeypatch, [0.5, 0.0097])
        s = _mock_settings(VmaxSC=[1.0, 0.01])
        acquisition.log_data(s)
        out = capsys.readouterr().out
        assert 'Data may be clipped' in out
        assert 'input 2 (channel index 1)' in out
        assert 'channel index 0' not in out
        assert acquisition._clipped_channels(
            np.array([0.5, 0.0097]), np.array([1.0, 0.01])) == [1]

    def test_no_clip_when_each_channel_is_within_its_own_rail(
            self, monkeypatch, capsys, clean_streams):
        # Peak 0.5 V on channel 0 would clip channel 1's 0.01 V rail and
        # 0.009 V on channel 1 would not clip anything: a check against
        # one shared number would get one of them wrong.
        _mock_with_peaks(monkeypatch, [0.5, 0.009])
        acquisition.log_data(_mock_settings(VmaxSC=[1.0, 0.01]))
        assert 'clipped' not in capsys.readouterr().out

    def test_scalar_clip_check_is_unchanged(self, monkeypatch, capsys,
                                            clean_streams):
        _mock_with_peaks(monkeypatch, [0.2, 0.96])
        acquisition.log_data(_mock_settings(VmaxSC=1.0))
        out = capsys.readouterr().out
        assert 'Data may be clipped' in out
        assert 'input 2 (channel index 1)' in out

    def test_use_output_as_ch0_keeps_per_channel_scale(self, monkeypatch,
                                                       capsys, clean_streams):
        peaks = [0.5, 0.005]
        _mock_with_peaks(monkeypatch, peaks)
        s = _mock_settings(VmaxSC=[1.0, 0.01], use_output_as_ch0=True,
                           output_channels=1)
        n = int(s.stored_time * s.fs)
        output = _square(n, 0.9)[:, None]
        ds = acquisition.log_data(s, output=output)
        assert 'clipped' not in capsys.readouterr().out
        data = ds.time_data_list[0].time_data
        assert data.shape[1] == 3
        np.testing.assert_array_equal(data[:, 0], output[:, 0])
        np.testing.assert_array_equal(np.max(np.abs(data[:, 1:]), axis=0),
                                      peaks)
        np.testing.assert_array_equal(
            ds.time_data_list[0].channel_cal_factors, [1.0, 1.0, 1.0])

        # A clipped input is named by its input channel, not its column.
        _mock_with_peaks(monkeypatch, [0.5, 0.0097])
        acquisition.log_data(s, output=output)
        out = capsys.readouterr().out
        assert 'input 2 (channel index 1)' in out

    def test_dropout_silence_judged_per_channel(self):
        """A record is 'silent' only when every channel is below its own
        rail's silent fraction."""
        y = np.zeros((1000, 2))
        y[1:400, 0] = 1e-4                   # tiny on a 1 V rail...
        y[1:400, 1] = 1e-4                   # ...but 1 % of a 0.01 V rail
        # One shared 1 V full scale calls the record silent.
        assert acquisition.exact_zero_dropouts(y, 1000.0, 1.0) == (0, 0.0)
        # Per channel, channel 1 is live, so the zero run counts.
        n_runs, seconds = acquisition.exact_zero_dropouts(
            y, 1000.0, np.array([1.0, 0.01]))
        assert n_runs == 1
        assert seconds == pytest.approx(0.6)
