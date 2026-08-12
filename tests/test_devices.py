"""Choosing a device by name, and knowing what you chose.

Everything here runs against a fake PortAudio shaped like the Windows
enumeration that motivated the module: one ESI U24 XL published four
times (once per host API) plus its S/PDIF receiver, a Realtek input with
a Stereo Mix sibling, and MME's routing alias.
"""

import pytest

from pydvma import devices, streams


U24 = 'Line (U24XL with SPDIF I/O)'
U24_SPDIF = 'SPDIF Interface (U24XL with SPDIF I/O)'
U24_MME = 'SPDIF Interface (U24XL with SPD'          # MME truncates at 31

# name, hostapi, max_in, max_out, default_sr
FAKE = [
    ('Microsoft Sound Mapper - Input', 'MME', 2, 0, 44100),
    (U24, 'MME', 2, 0, 44100),
    (U24_MME, 'MME', 2, 0, 48000),
    (U24, 'Windows DirectSound', 2, 0, 44100),
    (U24_SPDIF, 'Windows WASAPI', 2, 0, 48000),
    (U24, 'Windows WASAPI', 2, 0, 44100),
    ('Microphone (Realtek HD Audio Mic input)', 'Windows WDM-KS', 2, 0, 44100),
    ('Stereo Mix (Realtek HD Audio Stereo input)', 'Windows WDM-KS', 2, 0, 48000),
    ('Microphone (NVIDIA Broadcast)', 'Windows WASAPI', 2, 0, 48000),
    (U24, 'Windows WDM-KS', 2, 0, 48000),
    ('Speakers (Realtek)', 'Windows WDM-KS', 0, 2, 48000),
]

HW_LADDER = [8000.0, 16000.0, 32000.0, 44100.0, 48000.0]
#: What each backend will actually clock, mirroring the bench result.
BACKEND_RATES = {
    'Windows WDM-KS': [44100.0, 48000.0],
    'Windows WASAPI': HW_LADDER,
}


@pytest.fixture
def fake_portaudio(monkeypatch):
    hostapi_names = []
    for _n, api, _i, _o, _sr in FAKE:
        if api not in hostapi_names:
            hostapi_names.append(api)

    class FakeSd:
        @staticmethod
        def query_devices():
            return [{'name': n, 'hostapi': hostapi_names.index(a),
                     'max_input_channels': i, 'max_output_channels': o,
                     'default_samplerate': sr}
                    for n, a, i, o, sr in FAKE]

        @staticmethod
        def query_hostapis(index=None):
            entries = [{'name': a} for a in hostapi_names]
            return entries[index] if index is not None else entries

        @staticmethod
        def check_input_settings(device=None, channels=None, samplerate=None,
                                 extra_settings=None):
            api = FAKE[device][1]
            allowed = BACKEND_RATES.get(api)
            if allowed is None:                 # MME / DirectSound: accept all
                return
            if float(samplerate) not in allowed:
                raise RuntimeError('unsupported rate')

        class WasapiSettings:
            def __init__(self, exclusive=False):
                self.exclusive = exclusive

    monkeypatch.setattr(devices, 'sd', FakeSd)
    monkeypatch.setattr(streams, 'sd', FakeSd)
    monkeypatch.setattr(streams, 'all_soundcard_device_names',
                        lambda: [n for n, _a, _i, _o, _s in FAKE])
    monkeypatch.setattr(streams, 'native_input_rates',
                        lambda settings: list(HW_LADDER))
    return FakeSd


class TestEndpointRole:
    """The trap this cost a round to find: the U24 XL's MODEL name
    contains the words 'SPDIF I/O', so a substring test over the whole
    name flags its ANALOGUE line input as digital."""

    def test_role_is_the_text_before_the_bracket(self):
        assert devices.endpoint_role(U24) == 'line'
        assert devices.endpoint_role(U24_SPDIF) == 'spdif interface'

    def test_the_line_input_of_a_spdif_capable_box_is_not_auxiliary(self):
        assert devices.is_auxiliary(U24) is False

    def test_the_spdif_receiver_is_auxiliary(self):
        assert devices.is_auxiliary(U24_SPDIF) is True

    def test_stereo_mix_is_auxiliary(self):
        assert devices.is_auxiliary('Stereo Mix (Realtek HD Audio)') is True

    def test_names_without_brackets_fall_back_to_the_whole_name(self):
        assert devices.endpoint_role('Scarlett 2i2 4th Gen') == \
            'scarlett 2i2 4th gen'

    def test_alias_detection(self):
        assert devices.is_alias('Microsoft Sound Mapper - Input') is True
        assert devices.is_alias('Primary Sound Capture Driver') is True
        assert devices.is_alias(U24) is False


class TestDisplayName:

    def test_collapses_embedded_newlines(self):
        """A Bluetooth headset really does enumerate with a literal
        newline in its name, which would break the report layout."""
        assert '\n' not in devices.display_name('Headset (bthhfenum\n;(Clip))')

    def test_elides_in_the_middle_and_respects_width(self):
        out = devices.display_name('x' * 200, width=40)
        assert len(out) == 40 and '...' in out

    def test_short_names_are_untouched(self):
        assert devices.display_name(U24) == U24


class TestCalibrationStatus:
    """Sample rates are equally knowable for any interface. Volts are
    not, and the report must not let one pass for the other."""

    def test_fixed_gain_device_is_characterised_with_no_stated_gain(self):
        status, volts, _advice = devices.calibration_status(U24)
        assert status == 'characterised'
        assert volts == pytest.approx(1.8819, abs=1e-3)

    def test_variable_gain_device_needs_the_knob_position(self):
        status, volts, advice = devices.calibration_status(
            'Scarlett 2i2 4th Gen')
        assert status == 'needs_gain'
        assert volts is None
        assert 'input_gain_db' in advice

    def test_variable_gain_device_with_a_stated_gain_is_characterised(self):
        status, volts, _ = devices.calibration_status(
            'Scarlett 2i2 4th Gen', input_gain_db=9.0)
        assert status == 'characterised'
        assert volts > 0

    def test_unknown_interface_is_uncalibrated_and_says_so(self):
        status, volts, advice = devices.calibration_status('Generic USB Audio')
        assert status == 'uncalibrated'
        assert volts is None
        assert 'FS units' in advice
        assert 'verify_input_scaling' in advice


class TestBackendRanking:

    def test_wdmks_outranks_the_shared_mode_apis(self):
        assert devices._rank('Windows WDM-KS') < devices._rank('MME')
        assert devices._rank('Windows WASAPI') < devices._rank('MME')
        assert devices._rank('Windows WASAPI') < \
            devices._rank('Windows DirectSound')

    def test_an_unknown_host_api_sorts_mid_table_not_last(self):
        """Unknown is not the same as bad."""
        assert devices._rank('MME') > devices._rank('Some Future API')
        assert devices._rank('Some Future API') > devices._rank('Core Audio')


def _index_of(name, hostapi):
    """Look the fake device up by identity, not position — hard-coding an
    index into a test about not hard-coding indices ages badly, as this
    file found out when a device was inserted into FAKE."""
    for i, (n, a, _in, _out, _sr) in enumerate(FAKE):
        if n == name and a == hostapi:
            return i
    raise AssertionError('no %r on %s in FAKE' % (name, hostapi))


class TestUsableRates:

    def test_shared_mode_apis_report_only_the_default_format(self, fake_portaudio):
        """MME accepts every rate and resamples to reach it, so reporting
        what it ACCEPTS would reproduce the fiction."""
        assert devices.entry_usable_rates(
            _index_of(U24, 'MME'), 'MME', 2, 44100, HW_LADDER) == [44100.0]
        assert devices.entry_usable_rates(
            _index_of(U24, 'Windows DirectSound'), 'Windows DirectSound',
            2, 44100, HW_LADDER) == [44100.0]

    def test_exclusive_apis_report_what_they_actually_clock(self, fake_portaudio):
        assert devices.entry_usable_rates(
            _index_of(U24, 'Windows WDM-KS'), 'Windows WDM-KS',
            2, 48000, HW_LADDER) == [44100.0, 48000.0]
        assert devices.entry_usable_rates(
            _index_of(U24, 'Windows WASAPI'), 'Windows WASAPI',
            2, 44100, HW_LADDER) == HW_LADDER


class TestInventoryGrouping:

    def test_one_box_becomes_one_row_with_four_backends(self, fake_portaudio):
        groups = devices.inventory()
        u24 = [g for g in groups if g['name'] == U24]
        assert len(u24) == 1
        assert len(u24[0]['entries']) == 4

    def test_mme_truncated_name_folds_into_the_full_one(self, fake_portaudio):
        """The truncated form is enumerated FIRST here, which is the
        ordering that broke an earlier version of the fold."""
        groups = devices.inventory()
        spdif = [g for g in groups if 'SPDIF Interface' in g['name']]
        assert len(spdif) == 1
        assert spdif[0]['name'] == U24_SPDIF        # the longer name wins
        assert len(spdif[0]['entries']) == 2

    def test_entries_are_sorted_best_backend_first(self, fake_portaudio):
        group = [g for g in devices.inventory() if g['name'] == U24][0]
        assert group['entries'][0]['hostapi'] == 'Windows WDM-KS'
        assert group['entries'][-1]['hostapi'] == 'MME'
        assert devices.preferred_backend(group)['hostapi'] == 'Windows WDM-KS'

    def test_output_devices_are_excluded_from_an_input_listing(self, fake_portaudio):
        names = [g['name'] for g in devices.inventory(kind='input')]
        assert 'Speakers (Realtek)' not in names

    def test_the_profile_reaches_every_entry_of_the_group(self, fake_portaudio):
        group = [g for g in devices.inventory() if g['name'] == U24][0]
        assert group['profile'] == 'ESI U24 XL'
        assert group['status'] == 'characterised'


class TestResolve:

    def test_a_partial_name_finds_the_device(self, fake_portaudio):
        index, entry, note = devices.resolve('U24XL')
        assert entry['hostapi'] == 'Windows WDM-KS'
        assert 'Windows WDM-KS' in note

    def test_the_spdif_sibling_is_tie_broken_away_and_reported(self, fake_portaudio):
        """'U24XL' hits both the line input and the S/PDIF receiver. The
        receiver has no analogue voltage scale at all, so it loses — but
        the caller is told."""
        _index, entry, note = devices.resolve('U24XL')
        assert entry['name'] == U24
        assert 'auxiliary' in note and 'SPDIF Interface' in note

    def test_an_exact_name_beats_a_partial_one(self, fake_portaudio):
        _i, entry, _n = devices.resolve(U24_SPDIF)
        assert entry['name'] == U24_SPDIF

    def test_stereo_mix_loses_to_the_real_input(self, fake_portaudio):
        _i, entry, _n = devices.resolve('Realtek')
        assert entry['name'].startswith('Microphone')

    def test_requested_rate_moves_the_choice_off_the_default_backend(
            self, fake_portaudio):
        """fs=8000 cannot be clocked by WDM-KS, so WASAPI wins — the
        alternative is a silent resample."""
        _i, entry, note = devices.resolve('U24XL', fs=8000)
        assert entry['hostapi'] == 'Windows WASAPI'
        assert 'cannot clock 8000' in note

    def test_the_default_backend_is_kept_when_it_can_clock_the_rate(
            self, fake_portaudio):
        _i, entry, _n = devices.resolve('U24XL', fs=48000)
        assert entry['hostapi'] == 'Windows WDM-KS'

    def test_a_rate_no_backend_clocks_warns_rather_than_pretending(
            self, fake_portaudio):
        _i, _e, note = devices.resolve('U24XL', fs=96000)
        assert 'WARNING' in note and 'resample' in note

    def test_no_match_raises_and_lists_what_is_present(self, fake_portaudio):
        with pytest.raises(ValueError, match='matches no'):
            devices.resolve('Nonexistent Interface')

    def test_a_genuinely_ambiguous_name_refuses_to_guess(self, fake_portaudio):
        """Two real inputs both called 'Microphone ...': no principled
        reason to prefer either, so refuse rather than record the wrong
        instrument. The tie-break only settles auxiliary-vs-analogue."""
        with pytest.raises(ValueError, match='be more specific'):
            devices.resolve('Microphone')

    def test_the_refusal_names_every_candidate(self, fake_portaudio):
        with pytest.raises(ValueError, match='NVIDIA Broadcast'):
            devices.resolve('Microphone')

    def test_an_integer_spec_is_passed_straight_through(self, fake_portaudio):
        target = _index_of(U24, 'Windows WDM-KS')
        index, _entry, note = devices.resolve(target)
        assert index == target
        assert 'index %d' % target in note

    def test_a_digit_string_is_also_an_index(self, fake_portaudio):
        target = _index_of(U24, 'Windows WDM-KS')
        assert devices.resolve(str(target))[0] == target


class TestModelMatchingIsPortable:
    """The name an OS gives a device is not portable, so a settings file
    that names the raw device works only on the machine it was written
    on. Matching the MODEL closes that.

    macOS calls this box 'U24XL with SPDIF I/O'; Windows calls it 'Line
    (U24XL with SPDIF I/O)'. A Scarlett 2i2 is worse — Windows names it
    'Analogue 1 + 2 (Focusrite USB Audio)', which does not contain the
    model at all.
    """

    MAC = [('U24XL with SPDIF I/O', 'Core Audio', 2, 2, 48000)]
    WIN = [(U24, 'Windows WDM-KS', 2, 0, 48000)]

    @staticmethod
    def _enumeration(monkeypatch, table):
        class FakeSd:
            @staticmethod
            def query_devices():
                return [{'name': n, 'hostapi': 0, 'max_input_channels': i,
                         'max_output_channels': o, 'default_samplerate': sr}
                        for n, _a, i, o, sr in table]

            @staticmethod
            def query_hostapis(index=None):
                entries = [{'name': table[0][1]}]
                return entries[index] if index is not None else entries

            @staticmethod
            def check_input_settings(**kwargs):
                return None

            class WasapiSettings:
                def __init__(self, exclusive=False):
                    self.exclusive = exclusive

        monkeypatch.setattr(devices, 'sd', FakeSd)
        monkeypatch.setattr(streams, 'sd', FakeSd)
        monkeypatch.setattr(streams, 'all_soundcard_device_names',
                            lambda: [n for n, _a, _i, _o, _s in table])
        monkeypatch.setattr(streams, 'native_input_rates',
                            lambda settings: [48000.0])

    def test_the_same_model_spec_resolves_on_both_platforms(self, monkeypatch):
        """The whole point: one settings file, either machine."""
        for table in (self.MAC, self.WIN):
            self._enumeration(monkeypatch, table)
            _i, entry, note = devices.resolve('ESI U24 XL')
            assert entry['profile'] == 'ESI U24 XL'
            assert 'by model' in note

    def test_the_raw_windows_name_does_NOT_resolve_on_the_mac(self, monkeypatch):
        """Which is exactly why model matching had to be added."""
        self._enumeration(monkeypatch, self.MAC)
        with pytest.raises(ValueError):
            devices.resolve(U24)

    def test_model_matching_ignores_case_and_punctuation(self, monkeypatch):
        self._enumeration(monkeypatch, self.WIN)
        for spec in ('ESI U24 XL', 'esi u24 xl', 'esi-u24-xl', 'ESIU24XL'):
            assert devices.resolve(spec)[1]['profile'] == 'ESI U24 XL'

    def test_a_device_name_match_still_wins_and_is_not_flagged(self, monkeypatch):
        self._enumeration(monkeypatch, self.WIN)
        _i, _e, note = devices.resolve('U24XL')
        assert 'by model' not in note

    def test_the_error_lists_the_models_it_could_have_matched(self, monkeypatch):
        self._enumeration(monkeypatch, self.WIN)
        with pytest.raises(ValueError, match="Recognised models: 'ESI U24 XL'"):
            devices.resolve('Behringer XR18')

    def test_an_uncharacterised_device_cannot_be_model_matched(self, monkeypatch):
        self._enumeration(monkeypatch, [('Generic USB Audio', 'Core Audio',
                                         2, 0, 48000)])
        with pytest.raises(ValueError, match='by name or model'):
            devices.resolve('ESI U24 XL')


class TestSquash:

    def test_strips_punctuation_and_case(self):
        assert devices._squash('ESI U24-XL!') == 'esiu24xl'

    def test_empty_needle_never_matches(self):
        """Otherwise '' would match every model."""
        assert devices._loose_match('', 'ESI U24 XL') is False
        assert devices._loose_match('-', 'ESI U24 XL') is False


class TestFormatInventory:

    def test_report_marks_the_recommended_backend(self, fake_portaudio):
        text = devices.format_inventory(driver='soundcard')
        assert '>>' in text
        assert 'Windows WDM-KS' in text

    def test_report_states_the_calibration_status_of_each_device(
            self, fake_portaudio):
        text = devices.format_inventory(driver='soundcard')
        assert 'CHARACTERISED' in text
        assert 'uncalibrated' in text
        assert '1.8819 V peak' in text

    def test_report_flags_a_routing_alias(self, fake_portaudio):
        text = devices.format_inventory(driver='soundcard')
        assert 'routing alias' in text

    def test_report_separates_hardware_ladder_from_what_a_backend_delivers(
            self, fake_portaudio):
        """The distinction the whole module exists for."""
        text = devices.format_inventory(driver='soundcard')
        assert 'hardware    : clocks 8000/16000/32000/44100/48000 Hz' in text
        assert 'delivers 44100/48000' in text          # WDM-KS
        assert 'delivers 44100 ' in text                # MME, resampled above

    def test_report_is_ascii_for_a_windows_console(self, fake_portaudio):
        text = devices.format_inventory(driver='soundcard')
        text.encode('ascii')       # raises if a stray en/em dash crept in

    def test_legend_explains_the_statuses(self, fake_portaudio):
        text = devices.format_inventory(driver='soundcard', legend=True)
        assert 'NEEDS GAIN' in text and 'verify_input_scaling' in text

    def test_legend_can_be_suppressed(self, fake_portaudio):
        text = devices.format_inventory(driver='soundcard', legend=False)
        assert 'verify_input_scaling' not in text
