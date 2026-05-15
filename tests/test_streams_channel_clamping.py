"""Mac/Linux/Windows-runnable tests for soundcard channel-count
clamping in `pydvma.streams`.

Background
----------
The soundcard backend used to pass ``settings.channels`` straight
into ``sd.InputStream(channels=...)`` with no validation. On a Mac
built-in mono mic this surfaced as ``PortAudioError -9998``
(``paInvalidChannelCount``) on the default ``MySettings()`` (which
asks for 2 channels). The fix introduced two helpers that clamp
channel counts to the device's reported capability with a printed
warning. These tests exercise that clamp logic with a mocked
``sounddevice`` module — no audio hardware required.

The NI backend already raises ``ValueError`` for the analogous
case (`Recorder_NI_nidaqmx.__init__`), so this test file targets
only the soundcard path.
"""

from types import SimpleNamespace

import pytest

from pydvma import streams


def _fake_sd(input_max=1, output_max=2,
             input_name='built-in mic', output_name='built-in speakers',
             default_input=0, default_output=1):
    """Build a stand-in for the `sounddevice` module exposing just
    enough surface for the clamp helpers to run.
    """
    devices = {
        default_input: {
            'name': input_name,
            'max_input_channels': input_max,
            'max_output_channels': 0,
        },
        default_output: {
            'name': output_name,
            'max_input_channels': 0,
            'max_output_channels': output_max,
        },
    }

    return SimpleNamespace(
        query_devices=lambda idx: devices[idx],
        default=SimpleNamespace(device=[default_input, default_output]),
        PortAudioError=Exception,
    )


def _settings(**overrides):
    """Build a `MySettings`-like SimpleNamespace with the attributes
    the clamp helpers and the integration paths (`Recorder.__init__`,
    `setup_output_soundcard`) touch. Avoids constructing a real
    `MySettings` (which would trigger sd.default lookup at init time)
    so each test can set up its own mocked sd cleanly.
    """
    base = dict(
        # Used by both clamp helpers
        device_index=None,
        channels=2,
        device_driver='soundcard',
        output_device_index=None,
        output_channels=1,
        output_device_driver='soundcard',
        # Used by Recorder.__init__ buffer allocation
        fs=44100,
        chunk_size=100,
        num_chunks=4,
        stored_time=0.1,
        # Used by setup_output_soundcard
        output_fs=44100,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestClampInputChannels:

    def test_clamps_when_requested_exceeds_device_max(self, monkeypatch, capsys):
        monkeypatch.setattr(streams, 'sd', _fake_sd(input_max=1))
        s = _settings(channels=2)

        streams._clamp_soundcard_input_channels(s)

        assert s.channels == 1
        assert s.device_index == 0  # resolved from default
        out = capsys.readouterr().out
        assert 'WARNING' in out
        assert 'built-in mic' in out
        assert 'Clamping to 1' in out

    def test_no_clamp_when_within_device_capacity(self, monkeypatch, capsys):
        monkeypatch.setattr(streams, 'sd', _fake_sd(input_max=8))
        s = _settings(channels=2)

        streams._clamp_soundcard_input_channels(s)

        assert s.channels == 2
        assert capsys.readouterr().out == ''

    def test_explicit_device_index_is_respected(self, monkeypatch):
        # User picked a specific device index — helper must not
        # overwrite it with the default.
        monkeypatch.setattr(streams, 'sd', _fake_sd(input_max=4))
        s = _settings(channels=2, device_index=1)

        streams._clamp_soundcard_input_channels(s)

        assert s.device_index == 1

    def test_no_op_when_sd_unavailable(self, monkeypatch):
        monkeypatch.setattr(streams, 'sd', None)
        s = _settings(channels=99)

        streams._clamp_soundcard_input_channels(s)

        # Nothing to query — no clamp, no exception. The eventual
        # sd.InputStream call (which can't run anyway) would surface.
        assert s.channels == 99
        assert s.device_index is None


class TestClampOutputChannels:

    def test_clamps_when_requested_exceeds_device_max(self, monkeypatch, capsys):
        monkeypatch.setattr(streams, 'sd', _fake_sd(output_max=1))
        s = _settings(output_channels=2)

        streams._clamp_soundcard_output_channels(s)

        assert s.output_channels == 1
        assert s.output_device_index == 1  # resolved from default
        out = capsys.readouterr().out
        assert 'WARNING' in out
        assert 'built-in speakers' in out

    def test_no_clamp_when_within_device_capacity(self, monkeypatch, capsys):
        monkeypatch.setattr(streams, 'sd', _fake_sd(output_max=8))
        s = _settings(output_channels=2)

        streams._clamp_soundcard_output_channels(s)

        assert s.output_channels == 2
        assert capsys.readouterr().out == ''


class TestStartStreamCallsInputClamp:
    """Integration: confirm `start_stream` invokes the input clamp
    *before* constructing `Recorder` (so buffer shapes match).
    """

    def test_buffers_match_clamped_channel_count(self, monkeypatch):
        # Mac built-in mic scenario: settings ask for 2 channels,
        # device reports max_input_channels=1.
        monkeypatch.setattr(streams, 'sd', _fake_sd(input_max=1))

        # Avoid actually opening an InputStream — stub init_stream
        # to just remember the settings it saw.
        seen = {}

        def stub_init_stream(self, settings, _input_=True, _output_=False):
            seen['channels'] = settings.channels
            self.audio_stream = None  # satisfies attribute existence

        monkeypatch.setattr(streams.Recorder, 'init_stream', stub_init_stream)

        s = _settings(channels=2)
        # Reset module-level globals before/after via try/finally
        prior_REC, prior_REC_SC = streams.REC, streams.REC_SC
        try:
            streams.start_stream(s)

            assert s.channels == 1, 'settings.channels should be clamped to 1'
            assert seen['channels'] == 1, (
                'Recorder.init_stream should see the clamped value'
            )
            # The Recorder buffers were sized using settings.channels.
            assert streams.REC_SC.osc_time_data.shape[1] == 1
            assert streams.REC_SC.stored_time_data.shape[1] == 1
        finally:
            streams.REC, streams.REC_SC = prior_REC, prior_REC_SC


class TestSetupOutputSoundcardCallsOutputClamp:
    """Integration: confirm `setup_output_soundcard` clamps before
    opening `sd.OutputStream`.
    """

    def test_clamps_then_opens_with_clamped_value(self, monkeypatch):
        monkeypatch.setattr(streams, 'sd', _fake_sd(output_max=1))

        opened = {}

        class FakeOutputStream:
            def __init__(self, *, channels, **kw):
                opened['channels'] = channels

            def start(self):
                pass

        monkeypatch.setattr(streams.sd, 'OutputStream', FakeOutputStream,
                            raising=False)

        s = _settings(output_channels=2)
        streams.setup_output_soundcard(s)

        assert s.output_channels == 1
        assert opened['channels'] == 1
