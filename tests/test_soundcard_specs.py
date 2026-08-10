"""Tests for audio-interface facts the audio APIs don't expose.

Channel roles and full-scale voltage are both static per model and both
invisible to PortAudio/CoreAudio — see
``dev/plans/2026-08-10-focusrite-scarlett-design.md``.
"""

import math

import pytest

from pydvma import _soundcard_specs as specs
from pydvma import options


SCARLETT = 'Scarlett 2i2 4th Gen'


class TestDeviceProfile:
    def test_matches_case_insensitively_on_a_substring(self):
        assert specs.device_profile('scarlett 2i2 4th gen') is not None
        assert specs.device_profile('Scarlett 2i2 4th Gen') is not None

    def test_unknown_device_has_no_profile(self):
        assert specs.device_profile('MacBook Pro Microphone') is None
        assert specs.device_profile('') is None
        assert specs.device_profile(None) is None


class TestChannelRoles:
    def test_scarlett_inputs_3_and_4_are_loopback(self):
        """The 2i2 reports four inputs but only two are wired to the
        outside world; 3/4 are a digital tap of the output mix."""
        assert specs.channel_roles(SCARLETT, 4) == [
            'analogue', 'analogue', 'loopback', 'loopback']
        assert specs.loopback_channels(SCARLETT, 4) == [2, 3]

    def test_roles_are_truncated_to_the_channels_asked_for(self):
        assert specs.channel_roles(SCARLETT, 2) == ['analogue', 'analogue']
        assert specs.loopback_channels(SCARLETT, 2) == []

    def test_channels_beyond_the_table_default_to_analogue(self):
        """A short table must never hide a real input."""
        assert specs.channel_roles(SCARLETT, 6) == [
            'analogue', 'analogue', 'loopback', 'loopback',
            'analogue', 'analogue']

    def test_uncharacterised_device_reports_unknown_not_empty(self):
        """None means 'treat every channel as ordinary', which is very
        different from 'this device has no channels'."""
        assert specs.channel_roles('Some Other Interface', 2) is None
        assert specs.loopback_channels('Some Other Interface', 2) == []


class TestFullScaleVolts:
    def test_matches_the_value_measured_on_hardware(self):
        """A 5.000 Vpp sine at 9 dB Line gain read 0.505072 FS, implying
        4.9498 V pk. The published table predicts 4.8932 — 0.10 dB."""
        v = specs.full_scale_volts(SCARLETT, 9.0, 'line')
        assert v == pytest.approx(4.8932, abs=1e-3)
        assert abs(20 * math.log10(4.9498 / v)) < 0.15

    def test_minimum_gain_gives_the_published_maximum_input(self):
        """22 dBu at minimum gain, per the user guide."""
        v = specs.full_scale_volts(SCARLETT, 0.0, 'line')
        assert 20 * math.log10((v / math.sqrt(2)) / 0.7746) == pytest.approx(22.0)

    def test_gain_reduces_full_scale_decibel_for_decibel(self):
        a = specs.full_scale_volts(SCARLETT, 0.0, 'line')
        b = specs.full_scale_volts(SCARLETT, 20.0, 'line')
        assert 20 * math.log10(a / b) == pytest.approx(20.0)

    def test_input_modes_have_different_ceilings(self):
        line = specs.full_scale_volts(SCARLETT, 0.0, 'line')
        inst = specs.full_scale_volts(SCARLETT, 0.0, 'inst')
        mic = specs.full_scale_volts(SCARLETT, 0.0, 'mic')
        assert 20 * math.log10(line / inst) == pytest.approx(10.0)   # 22 vs 12 dBu
        assert 20 * math.log10(line / mic) == pytest.approx(6.0)     # 22 vs 16 dBu

    def test_unknown_device_returns_none_rather_than_guessing(self):
        assert specs.full_scale_volts('Some Other Interface', 9.0) is None

    def test_no_gain_stated_returns_none(self):
        assert specs.full_scale_volts(SCARLETT, None) is None

    def test_rejects_an_unavailable_input_mode(self):
        with pytest.raises(ValueError, match='input_mode'):
            specs.full_scale_volts(SCARLETT, 9.0, 'aes')

    def test_rejects_a_gain_outside_the_device_range(self):
        """A silently wrong full scale would propagate into every
        derived result, so an impossible gain is an error."""
        with pytest.raises(ValueError, match='outside'):
            specs.full_scale_volts(SCARLETT, 80.0, 'line')
        with pytest.raises(ValueError, match='outside'):
            specs.full_scale_volts(SCARLETT, -3.0, 'line')

    def test_inst_range_is_shorter_than_line(self):
        specs.full_scale_volts(SCARLETT, 62.0, 'inst')
        with pytest.raises(ValueError, match='outside'):
            specs.full_scale_volts(SCARLETT, 65.0, 'inst')


class TestSettingsIntegration:
    """`input_gain_db` derives VmaxSC — it does not add a new layer.

    The chain stays: raw +/-1 -> xVmaxSC -> volts -> xcal_factor -> units.
    """

    def _settings(self, monkeypatch, name=SCARLETT, **kwargs):
        from pydvma import streams
        monkeypatch.setattr(streams, 'soundcard_device_name', lambda s: name)
        kwargs.setdefault('device_driver', 'soundcard')
        kwargs.setdefault('device_index', 0)
        kwargs.setdefault('fs', 44100)
        return options.MySettings(**kwargs)

    def test_stated_gain_sets_vmaxsc(self, monkeypatch):
        s = self._settings(monkeypatch, input_gain_db=9)
        assert s.VmaxSC == pytest.approx(4.8932, abs=1e-3)
        assert s.input_vmax() == pytest.approx(4.8932, abs=1e-3)

    def test_stated_gain_overrides_an_explicit_vmaxsc(self, monkeypatch):
        """Two answers to the same question; the stated gain wins and is
        what gets recorded."""
        s = self._settings(monkeypatch, input_gain_db=9, VmaxSC=1.0)
        assert s.VmaxSC == pytest.approx(4.8932, abs=1e-3)

    def test_gain_and_mode_are_recorded_on_the_settings(self, monkeypatch):
        s = self._settings(monkeypatch, input_gain_db=9, input_mode='INST')
        assert (s.input_gain_db, s.input_mode) == (9.0, 'inst')

    def test_default_is_no_gain_stated_and_vmaxsc_untouched(self, monkeypatch):
        s = self._settings(monkeypatch, VmaxSC=2.5)
        assert s.input_gain_db is None
        assert s.VmaxSC == 2.5

    def test_uncharacterised_device_leaves_vmaxsc_alone(self, monkeypatch):
        """No profile means no way to know; keep the user's value rather
        than inventing one."""
        s = self._settings(monkeypatch, name='Some Other Interface',
                           input_gain_db=9, VmaxSC=2.5)
        assert s.VmaxSC == 2.5
        assert s.input_gain_db == 9.0

    def test_unidentifiable_device_does_not_raise(self, monkeypatch):
        from pydvma import streams
        monkeypatch.setattr(streams, 'soundcard_device_name', lambda s: None)
        s = options.MySettings(device_driver='soundcard', device_index=0,
                               fs=44100, input_gain_db=9, VmaxSC=1.0)
        assert s.VmaxSC == 1.0

    def test_nidaq_ignores_the_soundcard_gain_model(self, monkeypatch):
        s = options.MySettings(device_driver='nidaq', device_index=0,
                               fs=44100, input_gain_db=9, VmaxSC=1.0)
        assert s.VmaxSC == 1.0

    def test_a_bad_gain_still_raises_through_settings(self, monkeypatch):
        with pytest.raises(ValueError, match='outside'):
            self._settings(monkeypatch, input_gain_db=80)
