"""Tests for the Windows Core Audio endpoint-volume helper.

The endpoint volume is a DIGITAL gain on a class-compliant interface —
measured −40..+12 dB on an ESI U24 XL with SNR identical at every
setting (``dev/2026-08-12-u24xl-windows-bench.md``) — so a non-zero
setting rescales captured data while ``VmaxSC`` goes on asserting the
device's published full scale. pydvma pins it to 0 dB per stream, the
same defence :mod:`pydvma._coreaudio` provides on macOS.

The pure-logic paths run everywhere against fakes; anything needing a
real endpoint skips off Windows.
"""

import sys

import pytest

from pydvma import _coreaudio, _win_audio, streams


windows_only = pytest.mark.skipif(sys.platform != 'win32',
                                  reason='needs Windows Core Audio')


class TestNameMatching:
    """PortAudio does not pass device names through unchanged, so the
    endpoint lookup cannot be an equality test."""

    def test_exact_name_matches(self):
        assert _win_audio._names_match('Line (U24XL with SPDIF I/O)',
                                       'Line (U24XL with SPDIF I/O)')

    def test_mme_truncation_to_31_chars_still_matches(self):
        """MME truncates, so the PortAudio name is a PREFIX of the
        endpoint's. Real example from the bench."""
        assert _win_audio._names_match('SPDIF Interface (U24XL with SPD',
                                       'SPDIF Interface (U24XL with SPDIF I/O)')

    def test_match_is_case_and_whitespace_insensitive(self):
        assert _win_audio._names_match('  line (u24xl with spdif i/o) ',
                                       'Line (U24XL with SPDIF I/O)')

    def test_different_devices_do_not_match(self):
        assert not _win_audio._names_match('Microphone (NVIDIA Broadcast)',
                                           'Line (U24XL with SPDIF I/O)')

    def test_a_shared_word_is_not_enough(self):
        """Pinning the volume on the WRONG endpoint silently rescales
        another device, so matching stays strict about prefixes."""
        assert not _win_audio._names_match('Realtek Line In',
                                           'Line (U24XL with SPDIF I/O)')

    def test_empty_names_never_match(self):
        assert not _win_audio._names_match('', 'Line (U24XL)')
        assert not _win_audio._names_match('Line (U24XL)', None)
        assert not _win_audio._names_match(None, None)


class TestGuidParsing:

    def test_round_trips_a_known_guid(self):
        g = _win_audio.GUID('BCDE0395-E52F-467C-8E3D-C4579291692E')
        assert g.Data1 == 0xBCDE0395
        assert g.Data2 == 0xE52F
        assert g.Data3 == 0x467C
        assert bytes(g.Data4) == bytes.fromhex('8E3DC4579291692E')

    def test_none_leaves_it_zeroed(self):
        g = _win_audio.GUID()
        assert g.Data1 == 0 and bytes(g.Data4) == b'\x00' * 8


class _FakeBackend:
    """Stand-in for either platform volume module."""

    def __init__(self, volumes=None, settable=True, device=('id', 'Fake')):
        self.volumes = dict(volumes or {})
        self.settable = settable
        self.device = device
        self.writes = []

    def available(self):
        return True

    def find_device(self, name):
        return self.device if name else (None, None)

    def input_volume_db(self, device_id):
        return dict(self.volumes)

    def set_input_volume_db(self, device_id, db, tolerance=0.25,
                            channels=None, elements=None):
        self.writes.append((db, channels, elements))
        if not self.settable:
            return False
        if channels is not None:
            self.volumes.update(channels)
        elif elements is not None:
            for e in elements:
                self.volumes[e] = db
        else:
            self.volumes = {k: db for k in self.volumes}
        return True


class TestBackendSelection:

    def test_prefers_coreaudio_when_it_answers(self, monkeypatch):
        monkeypatch.setattr(_coreaudio, 'available', lambda: True)
        monkeypatch.setattr(_win_audio, 'available', lambda: True)
        assert streams._volume_backend() is _coreaudio

    def test_falls_back_to_windows(self, monkeypatch):
        monkeypatch.setattr(_coreaudio, 'available', lambda: False)
        monkeypatch.setattr(_win_audio, 'available', lambda: True)
        assert streams._volume_backend() is _win_audio

    def test_none_when_neither_answers(self, monkeypatch):
        monkeypatch.setattr(_coreaudio, 'available', lambda: False)
        monkeypatch.setattr(_win_audio, 'available', lambda: False)
        assert streams._volume_backend() is None


class TestPinAndRestore:
    """`Recorder._pin_input_volume` must treat both platform modules
    interchangeably, and put back exactly what it found."""

    def _recorder(self):
        return streams.Recorder.__new__(streams.Recorder)

    class _Settings:
        device_name = 'Fake Interface'

    def test_a_mis_set_control_is_pinned_to_unity(self, monkeypatch, capsys):
        backend = _FakeBackend({0: -12.0, 1: -12.0})
        monkeypatch.setattr(streams, '_volume_backend', lambda: backend)
        rec = self._recorder()
        rec._pin_input_volume(self._Settings())
        assert backend.volumes == {0: 0.0, 1: 0.0}
        assert 'pinned to 0 dB' in capsys.readouterr().out

    def test_a_control_already_at_unity_is_left_alone(self, monkeypatch, capsys):
        """The common case must make no writes and print nothing."""
        backend = _FakeBackend({0: 0.0, 1: 0.0})
        monkeypatch.setattr(streams, '_volume_backend', lambda: backend)
        rec = self._recorder()
        rec._pin_input_volume(self._Settings())
        assert backend.writes == []
        assert capsys.readouterr().out == ''

    def test_restore_returns_mismatched_channels_individually(self, monkeypatch):
        """Channels can hold DIFFERENT values — seen on a U24 XL — so a
        single value written everywhere would not be a restore."""
        backend = _FakeBackend({0: -3.0, 1: 7.5})
        monkeypatch.setattr(streams, '_volume_backend', lambda: backend)
        rec = self._recorder()
        rec._pin_input_volume(self._Settings())
        assert backend.volumes == {0: 0.0, 1: 0.0}
        rec._restore_input_volume()
        assert backend.volumes == {0: -3.0, 1: 7.5}

    def test_an_unpinnable_control_warns_loudly(self, monkeypatch, capsys):
        """Silence would leave the operator with data scaled by an
        unknown amount."""
        backend = _FakeBackend({0: 9.0}, settable=False)
        monkeypatch.setattr(streams, '_volume_backend', lambda: backend)
        rec = self._recorder()
        rec._pin_input_volume(self._Settings())
        out = capsys.readouterr().out
        assert 'WARNING' in out and 'could not be' in out

    def test_no_backend_is_a_silent_no_op(self, monkeypatch, capsys):
        monkeypatch.setattr(streams, '_volume_backend', lambda: None)
        rec = self._recorder()
        rec._pin_input_volume(self._Settings())
        rec._restore_input_volume()
        assert capsys.readouterr().out == ''

    def test_unknown_device_is_a_no_op(self, monkeypatch, capsys):
        backend = _FakeBackend({0: -12.0}, device=(None, None))
        monkeypatch.setattr(streams, '_volume_backend', lambda: backend)
        rec = self._recorder()

        class NoName:
            device_name = None

        rec._pin_input_volume(NoName())
        assert backend.writes == []
        assert capsys.readouterr().out == ''

    def test_restore_without_a_pin_does_nothing(self, monkeypatch):
        backend = _FakeBackend({0: 4.0})
        monkeypatch.setattr(streams, '_volume_backend', lambda: backend)
        rec = self._recorder()
        rec._volume_device_id = None
        rec._volume_previous = None
        rec._restore_input_volume()
        assert backend.volumes == {0: 4.0}


class TestOffWindowsDegradesQuietly:

    @pytest.mark.skipif(sys.platform == 'win32', reason='non-Windows path')
    def test_available_is_false_and_nothing_raises(self):
        assert _win_audio.available() is False
        assert _win_audio.find_device('anything') == (None, None)
        assert _win_audio.capture_endpoint_names() == []
        assert _win_audio.input_volume_db('x') == {}
        assert _win_audio.set_input_volume_db('x', 0.0) is False
        assert _win_audio.volume_range_db('x') is None


@windows_only
class TestAgainstRealEndpoints:

    def test_available(self):
        assert _win_audio.available() is True

    def test_enumerates_capture_endpoints(self):
        names = _win_audio.capture_endpoint_names()
        assert isinstance(names, list)
        assert all(isinstance(n, str) for n in names)

    def test_unknown_device_resolves_to_nothing(self):
        assert _win_audio.find_device('No Such Interface Here') == (None, None)

    def test_volume_round_trip_on_the_first_endpoint_with_a_control(self):
        """Set/read/restore against whatever is actually plugged in, so
        the test survives a re-wire. Skips if nothing has a volume."""
        for name in _win_audio.capture_endpoint_names():
            eid, _ = _win_audio.find_device(name)
            if eid is None:
                continue
            original = _win_audio.input_volume_db(eid)
            rng = _win_audio.volume_range_db(eid)
            if not original or rng is None:
                continue
            lo, hi, _step = rng
            target = max(lo, min(hi, -6.0))
            try:
                assert _win_audio.set_input_volume_db(eid, target) is True
                got = _win_audio.input_volume_db(eid)
                assert all(abs(v - target) <= 0.5 for v in got.values())
            finally:
                _win_audio.set_input_volume_db(eid, 0.0, channels=original)
            assert _win_audio.input_volume_db(eid) == original
            return
        pytest.skip('no capture endpoint with a volume control')
