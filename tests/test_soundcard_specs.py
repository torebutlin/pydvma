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
U24XL = 'U24XL with SPDIF I/O'  # the name CoreAudio reports


class TestDeviceProfile:
    def test_matches_case_insensitively_on_a_substring(self):
        assert specs.device_profile('scarlett 2i2 4th gen') is not None
        assert specs.device_profile('Scarlett 2i2 4th Gen') is not None

    def test_unknown_device_has_no_profile(self):
        assert specs.device_profile('MacBook Pro Microphone') is None
        assert specs.device_profile('') is None
        assert specs.device_profile(None) is None


class TestWindowsProfileResolution:
    """On Windows the model name never reaches PortAudio.

    A 2i2 4th Gen enumerates as generic 'Focusrite USB Audio' endpoints
    (MME truncates names to 31 chars); only the WDM-KS twin's name
    embeds the per-model USB product id ('wc4800_8219'). Measured on
    the real PC, 2026-08-11.
    """

    # The real Windows enumeration, abbreviated to the 2i2's entries.
    WINDOWS_NAMES = [
        'Analogue 1 + 2 (Focusrite USB A',       # MME, truncated
        'Analogue 1 + 2 (Focusrite USB Audio)',  # DirectSound / WASAPI
        'Speakers (Focusrite USB Audio)',
        'Analogue 1 + 2 (wc4800_8219)',          # WDM-KS capture
        'Speakers (wr4800_8219)',                # WDM-KS render
        'Microphone (Realtek HD Audio Mic input)',
    ]

    def test_ks_name_matches_directly_via_the_product_id(self):
        assert specs.device_profile('Analogue 1 + 2 (wc4800_8219)') is not None
        assert specs.device_profile('Speakers (wr4800_8219)') is not None

    def test_generic_endpoint_resolves_through_the_ks_sibling(self):
        for name in ('Analogue 1 + 2 (Focusrite USB Audio)',
                     'Analogue 1 + 2 (Focusrite USB A',
                     'Speakers (Focusrite USB Audio)'):
            profile = specs.device_profile(name, neighbours=self.WINDOWS_NAMES)
            assert profile is not None, name
            assert profile['label'] == 'Focusrite Scarlett 2i2 4th Gen'

    def test_generic_endpoint_alone_stays_uncharacterised(self):
        """Without the sibling list the generic name proves nothing."""
        assert specs.device_profile(
            'Analogue 1 + 2 (Focusrite USB Audio)') is None

    def test_vendor_gate_blocks_unrelated_endpoints(self):
        """The 2i2 being present must not characterise the Realtek."""
        assert specs.device_profile(
            'Microphone (Realtek HD Audio Mic input)',
            neighbours=self.WINDOWS_NAMES) is None

    def test_no_characterised_sibling_means_no_match(self):
        """An uncharacterised Focusrite model must not inherit the 2i2
        profile just by brand."""
        names = ['Analogue 1 + 2 (Focusrite USB Audio)',
                 'Analogue 1 + 2 (wc4800_9999)']  # some other model
        assert specs.device_profile(
            'Analogue 1 + 2 (Focusrite USB Audio)', neighbours=names) is None

    def test_windows_channel_roles_and_volts_resolve(self):
        roles = specs.channel_roles('Analogue 1 + 2 (Focusrite USB A', 4,
                                    neighbours=self.WINDOWS_NAMES)
        assert roles == ['analogue', 'analogue', 'loopback', 'loopback']
        v = specs.full_scale_volts('Analogue 1 + 2 (Focusrite USB Audio)',
                                   9.0, 'line', neighbours=self.WINDOWS_NAMES)
        assert v == pytest.approx(4.8932, abs=1e-3)


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

    def test_a_measured_stop_just_past_the_published_range_is_accepted(self):
        """A real unit's knob stops sit a little off the manual's figures
        (an iD44's measured +60.51 / +0.79 dB mic stops against 60 / 0), so a
        MEASURED stop must be stateable: GAIN_RANGE_SLACK_DB either side."""
        id44 = 'Audient iD44'
        assert specs.GAIN_RANGE_SLACK_DB == 2.0
        top = specs.full_scale_volts(id44, 60.51, 'mic')
        assert top == pytest.approx(specs.full_scale_volts(id44, 60.0, 'mic')
                                    * 10 ** (-0.51 / 20))
        assert specs.full_scale_volts(id44, -1.9, 'mic') > specs.full_scale_volts(id44, 0.0, 'mic')
        assert specs.full_scale_volts(id44, 51.9, 'line') is not None
        with pytest.raises(ValueError, match='outside'):
            specs.full_scale_volts(id44, 62.5, 'mic')
        with pytest.raises(ValueError, match='outside'):
            specs.full_scale_volts(id44, -12.5, 'line')

    def test_an_out_of_range_gain_names_the_modes_it_fits(self):
        """`MySettings(input_gain_db=60)` on an iD44 is a mic gain read on
        the default line mode: the error says which mode it would fit."""
        id44 = 'Audient iD44'
        with pytest.raises(ValueError, match='outside') as err:
            specs.full_scale_volts(id44, 60.0, 'line')
        assert "Did you mean input_mode='mic' or input_mode='inst'?" in str(err.value)
        with pytest.raises(ValueError) as err:
            specs.full_scale_volts(id44, -10.0, 'mic')
        assert "Did you mean input_mode='line'?" in str(err.value)
        # No other mode fits: no hint.
        with pytest.raises(ValueError) as err:
            specs.full_scale_volts(id44, 80.0, 'mic')
        assert 'Did you mean' not in str(err.value)


class TestU24XLProfile:
    """The ESI U24 XL is the first FIXED-GAIN profile: no analogue gain
    exists anywhere in its input path, so full scale is a hardware
    constant (+4.7 dBu, user's guide §6; bench-confirmed to 0.07 dB on
    2026-08-11 — see ``dev/2026-08-11-u24xl-bench.md``)."""

    def test_the_coreaudio_name_matches(self):
        profile = specs.device_profile(U24XL)
        assert profile is not None
        assert profile['label'] == 'ESI U24 XL'

    def test_both_channels_are_analogue(self):
        assert specs.channel_roles(U24XL, 2) == ['analogue', 'analogue']
        assert specs.loopback_channels(U24XL, 2) == []

    def test_line_is_the_only_input_mode(self):
        assert specs.input_modes(U24XL) == ['line']

    def test_fixed_gain_is_true_only_for_gainless_profiles(self):
        assert specs.fixed_gain(U24XL) is True
        assert specs.fixed_gain(SCARLETT) is False
        assert specs.fixed_gain('Some Other Interface') is False
        assert specs.fixed_gain(None) is False

    def test_full_scale_matches_the_published_input_level(self):
        """+4.7 dBu is 1.33 V rms, so a full-scale reading is 1.88 V
        peak — with gain pinned at 0 dB there is nothing else to state."""
        expected = math.sqrt(2) * 0.7746 * 10 ** (4.7 / 20)
        assert specs.full_scale_volts(U24XL, 0.0) == pytest.approx(expected)
        assert expected == pytest.approx(1.882, abs=1e-3)

    def test_any_nonzero_gain_is_rejected(self):
        """The only gain this device has is DIGITAL (data scaling), which
        pydvma pins to 0 dB — a stated gain would be a mistake."""
        with pytest.raises(ValueError, match='outside'):
            specs.full_scale_volts(U24XL, 12.0)
        with pytest.raises(ValueError, match='outside'):
            specs.full_scale_volts(U24XL, -6.0)
        # no knob, so no slack for a measured stop either
        with pytest.raises(ValueError, match='outside'):
            specs.full_scale_volts(U24XL, 1.0)


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

    def test_fixed_gain_device_derives_vmaxsc_unasked(self, monkeypatch):
        """A fixed-gain interface has nothing for the operator to state:
        the default settings come out calibrated in volts."""
        s = self._settings(monkeypatch, name=U24XL)
        assert s.input_gain_db is None
        assert s.VmaxSC == pytest.approx(1.882, abs=1e-3)
        assert s.input_vmax() == pytest.approx(1.882, abs=1e-3)

    def test_fixed_gain_explicit_vmaxsc_wins(self, monkeypatch):
        """An explicit VmaxSC is the operator's own calibration — the
        auto-derivation only replaces the untouched default."""
        s = self._settings(monkeypatch, name=U24XL, VmaxSC=2.5)
        assert s.VmaxSC == 2.5

    def test_fixed_gain_stated_zero_gain_also_derives(self, monkeypatch):
        s = self._settings(monkeypatch, name=U24XL, input_gain_db=0)
        assert s.VmaxSC == pytest.approx(1.882, abs=1e-3)

    def test_variable_gain_device_still_needs_a_stated_gain(self, monkeypatch):
        """The 2i2 keeps its behaviour: no stated gain, no derivation —
        its knob position is unknowable."""
        s = self._settings(monkeypatch, name=SCARLETT)
        assert s.VmaxSC == 1.0


class TestID44Profile:
    """Audient iD44: per-channel gain with a minimum, a pad, optical roles.

    iD44MKII Manual V4 p16, p18, p19, p55; bench 2026-11-06.
    """

    NAME = 'Audient iD44'
    K = math.sqrt(2) * 0.7746

    def test_profile_is_found(self):
        assert specs.device_profile(self.NAME)['label'] == 'Audient iD44'

    def test_roles(self):
        roles = specs.channel_roles(self.NAME, 22)
        assert roles.count('analogue') == 4
        assert roles.count('optical') == 16
        assert roles.count('loopback') == 2
        assert specs.loopback_channels(self.NAME, 22) == [20, 21]
        assert specs.optical_channels(self.NAME, 22) == list(range(4, 20))
        assert specs.optical_channels('Scarlett 2i2 4th Gen', 4) == []

    @pytest.mark.parametrize('gain, mode, pad, exp_db', [
        (0.0, 'mic', False, 18), (60.0, 'mic', False, -42),
        (60.0, 'mic', True, -32), (-10.0, 'line', False, 28),
        (50.0, 'line', False, -32),
    ])
    def test_full_scale_volts(self, gain, mode, pad, exp_db):
        assert specs.full_scale_volts(
            self.NAME, gain, mode, pad=pad) == pytest.approx(
                self.K * 10 ** (exp_db / 20))

    def test_out_of_range_raises(self):
        # past the range AND its GAIN_RANGE_SLACK_DB for a measured stop
        with pytest.raises(ValueError):
            specs.full_scale_volts(self.NAME, 62.5, 'mic')
        with pytest.raises(ValueError):
            specs.full_scale_volts(self.NAME, -12.5, 'line')
        with pytest.raises(ValueError):
            specs.full_scale_volts('Scarlett 2i2 4th Gen', 9.0, 'line',
                                   pad=True)

    def test_gain_range(self):
        assert specs.gain_range(self.NAME, 'line') == (-10.0, 50.0)
        assert specs.gain_range('Scarlett 2i2 4th Gen', 'line') == (0.0, 69.0)
        assert specs.gain_range('Generic', 'line') is None

    def test_channel_input_modes(self):
        assert specs.channel_input_modes(self.NAME, 0) == [
            'inst', 'line', 'mic']
        assert specs.channel_input_modes(self.NAME, 2) == ['line', 'mic']
        assert specs.channel_input_modes(self.NAME, 5) == []
        assert specs.channel_input_modes(self.NAME, 21) == []

    def test_per_channel_gain_and_fs(self):
        assert specs.per_channel_gain(self.NAME) is True
        assert specs.per_channel_gain('Scarlett 2i2 4th Gen') is False
        assert specs.preferred_fs(self.NAME) == 48000
        assert specs.preferred_fs('Scarlett 2i2 4th Gen') is None

    def test_analogue_floor(self):
        assert specs.analogue_floor_dbfs(
            self.NAME, 60.0, 'mic') == pytest.approx(-84.0, abs=0.2)
        assert specs.analogue_floor_dbfs(
            self.NAME, 0.0, 'mic') == pytest.approx(-117.0, abs=0.1)
        assert specs.analogue_floor_dbfs(
            'Scarlett 2i2 4th Gen', 9.0, 'line') is None

    def test_not_fixed_gain(self):
        assert specs.fixed_gain(self.NAME) is False
