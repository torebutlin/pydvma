"""A device index is a POSITION, not an identity.

`streams.resolve_device_index` re-points a stored index at the device it
was actually chosen for. Two live observations motivate it:

- macOS, 2026-08-10: a Scarlett 2i2 moved from index 2 to index 1 once
  another interface left the list.
- Windows, 2026-08-12: the whole WDM-KS block reordered between two
  enumerations minutes apart, with no hardware change and the same
  device count — an ESI U24 XL's line input went from index 36 to 27.

The Windows case is the harder one, and the reason for the host-API
argument: PortAudio lists one interface once per host API, all four
entries sharing a name, so a name-only match finds four candidates and
has to give up exactly where the protection is needed.
"""

import pytest

from pydvma import options, streams


WIN_NAMES = [
    'Microsoft Sound Mapper - Input',
    'Line (U24XL with SPDIF I/O)',        # 1  MME
    'Line (U24XL with SPDIF I/O)',        # 2  DirectSound
    'Line (U24XL with SPDIF I/O)',        # 3  WASAPI
    'Microphone (Realtek HD Audio)',      # 4  WDM-KS
    'Line (U24XL with SPDIF I/O)',        # 5  WDM-KS  <- the one that moves
]
WIN_APIS = [
    'MME', 'MME', 'Windows DirectSound', 'Windows WASAPI',
    'Windows WDM-KS', 'Windows WDM-KS',
]
U24 = 'Line (U24XL with SPDIF I/O)'


@pytest.fixture
def windows_enumeration(monkeypatch):
    """A Windows-shaped device list: one box, four host APIs, one name."""
    monkeypatch.setattr(streams, 'enumerated_device_names',
                        lambda driver: list(WIN_NAMES))
    monkeypatch.setattr(streams, 'enumerated_device_hostapis',
                        lambda driver: list(WIN_APIS))


class TestHostApiQualifiedResolution:

    def test_name_alone_cannot_disambiguate_four_identical_entries(
            self, windows_enumeration):
        """Without the host API this is genuinely ambiguous, and the
        contract is to leave the index alone rather than guess."""
        assert streams.resolve_device_index('soundcard', 0, U24) == (0, None)

    def test_host_api_follows_a_reordered_wdmks_block(self, windows_enumeration):
        """The real Windows failure mode."""
        idx, note = streams.resolve_device_index(
            'soundcard', 0, U24, 'Windows WDM-KS')
        assert idx == 5
        assert 'moved from device index 0 to 5' in note

    def test_host_api_picks_the_right_twin_of_one_box(self, windows_enumeration):
        """Same hardware, same name, different backend — and the
        backends are NOT equivalent (MME is 16-bit and fabricates
        rates; WDM-KS is 24-bit and refuses). Resolving to the wrong
        twin would silently change the data."""
        for api, expected in [('MME', 1),
                              ('Windows DirectSound', 2),
                              ('Windows WASAPI', 3),
                              ('Windows WDM-KS', 5)]:
            idx, _ = streams.resolve_device_index('soundcard', 0, U24, api)
            assert idx == expected, api

    def test_correct_index_is_left_untouched(self, windows_enumeration):
        assert streams.resolve_device_index(
            'soundcard', 5, U24, 'Windows WDM-KS') == (5, None)

    def test_gone_from_that_host_api_raises(self, windows_enumeration):
        """Present under other backends is not good enough: the caller
        asked for a specific one."""
        with pytest.raises(ValueError, match='no longer connected'):
            streams.resolve_device_index('soundcard', 1, U24, 'Windows WDM-KS-2')

    def test_error_names_the_host_api_it_looked_on(self, windows_enumeration):
        with pytest.raises(ValueError, match='on Windows WDM-KS-2'):
            streams.resolve_device_index('soundcard', 1, U24, 'Windows WDM-KS-2')

    def test_still_ambiguous_within_one_host_api_is_left_alone(self, monkeypatch):
        """Two identical boxes on the SAME backend: the index really is
        the only thing telling them apart."""
        monkeypatch.setattr(streams, 'enumerated_device_names',
                            lambda driver: [U24, U24])
        monkeypatch.setattr(streams, 'enumerated_device_hostapis',
                            lambda driver: ['MME', 'MME'])
        assert streams.resolve_device_index('soundcard', 1, U24, 'MME') == (1, None)


class TestUnqualifiedResolutionStillWorks:
    """macOS and NI list each device once, so name-only stays correct —
    and older callers (the bridge's `_reresolve_device_index`) pass no
    host API at all."""

    @pytest.fixture(autouse=True)
    def mac_enumeration(self, monkeypatch):
        monkeypatch.setattr(
            streams, 'enumerated_device_names',
            lambda driver: ['Built-in', 'Scarlett 2i2 4th Gen', 'BlackHole 2ch'])
        monkeypatch.setattr(streams, 'enumerated_device_hostapis',
                            lambda driver: [])

    def test_follows_a_moved_device(self):
        idx, note = streams.resolve_device_index(
            'soundcard', 2, 'Scarlett 2i2 4th Gen')
        assert idx == 1
        assert 'moved from device index 2 to 1' in note

    def test_raises_when_gone(self):
        monkey = 'Focusrite Nonesuch'
        with pytest.raises(ValueError, match='no longer connected'):
            streams.resolve_device_index('soundcard', 1, monkey)

    def test_no_expected_name_is_a_no_op(self):
        assert streams.resolve_device_index('soundcard', 3, None) == (3, None)
        assert streams.resolve_device_index('soundcard', 3, '') == (3, None)

    def test_none_index_is_a_no_op(self):
        assert streams.resolve_device_index(
            'soundcard', None, 'Scarlett 2i2 4th Gen') == (None, None)


class TestEnumerationIsBestEffort:
    """Never block a capture because the device list could not be read."""

    def test_empty_enumeration_leaves_the_index_alone(self, monkeypatch):
        monkeypatch.setattr(streams, 'enumerated_device_names',
                            lambda driver: [])
        assert streams.resolve_device_index('soundcard', 2, U24, 'MME') == (2, None)

    def test_unknown_driver_enumerates_to_nothing(self):
        assert streams.enumerated_device_names('mock') == []
        assert streams.enumerated_device_hostapis('mock') == []

    def test_nidaq_has_no_host_api_concept(self):
        assert streams.enumerated_device_hostapis('nidaq') == []


class TestSettingsCarryTheIdentity:

    def test_defaults_are_none(self):
        s = options.MySettings(device_driver='mock')
        assert s.device_name is None
        assert s.device_hostapi is None

    def test_both_halves_round_trip(self):
        s = options.MySettings(device_driver='mock', device_index=5,
                               device_name=U24,
                               device_hostapi='Windows WDM-KS')
        assert s.device_name == U24
        assert s.device_hostapi == 'Windows WDM-KS'

    def test_string_none_is_treated_as_unset(self):
        """`--settings` files and the JSON bridge can deliver the
        literal string 'None'."""
        s = options.MySettings(device_driver='mock', device_name='None',
                               device_hostapi='None')
        assert s.device_name is None
        assert s.device_hostapi is None


class TestStartStreamAppliesIt:

    def test_start_stream_repoints_a_stale_index(self, monkeypatch,
                                                 windows_enumeration):
        """The whole point: the capture opens on the device the operator
        chose, not on whatever now sits at that index."""
        opened = {}

        class FakeRecorder:
            def __init__(self, settings):
                pass

            def init_stream(self, settings):
                opened['index'] = settings.device_index

        monkeypatch.setattr(streams, 'Recorder', FakeRecorder)
        monkeypatch.setattr(streams, '_clamp_soundcard_input_channels',
                            lambda s: None)
        monkeypatch.setattr(streams, 'REC_SC', None)

        s = options.MySettings(device_driver='soundcard', device_index=0,
                               device_name=U24,
                               device_hostapi='Windows WDM-KS')
        streams.start_stream(s)
        assert opened['index'] == 5
        assert s.device_index == 5
