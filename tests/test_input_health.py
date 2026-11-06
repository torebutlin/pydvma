"""`acquisition.input_health`: dead-input notices after a capture."""
import numpy as np
import pytest

from pydvma import acquisition, options

ID44 = 'Audient iD44'


@pytest.fixture
def id44(monkeypatch):
    monkeypatch.setattr(options, '_soundcard_identity',
                        lambda settings: (ID44, [ID44]))


def _settings(gain=None, channels=22, mode='mic'):
    # Built under the monkeypatched identity so the iD44 rails derive.
    return options.MySettings(device_driver='soundcard', channels=channels,
                              input_gain_db=gain, input_mode=mode)


def _noise(channels=22, n=4800, dbfs=-20.0):
    rng = np.random.default_rng(0)
    x = rng.standard_normal((n, channels))
    return x * 10 ** (dbfs / 20) / x.std()


def test_silent_optical_channel_is_reported(id44):
    data = _noise()
    data[:, 5] = 0.0
    issues = acquisition.input_health(data, _settings())
    assert [(i['channel'], i['kind']) for i in issues
            if i['kind'] == 'optical_silent'][0] == (5, 'optical_silent')
    assert 'channel 6 is an optical (ADAT) input' in issues[0]['message']


def test_live_optical_channel_is_fine(id44):
    assert acquisition.input_health(_noise(), _settings()) == []


def test_dead_analogue_channel_with_stated_gain(id44):
    settings = _settings(gain=[60.0, 60.0, 60.0, 60.0] + [None] * 18)
    data = _noise()
    data[:, 0] = _noise(1, dbfs=-100.0)[:, 0] * settings.input_vmax(0)
    issues = acquisition.input_health(data, settings)
    kinds = [(i['channel'], i['kind']) for i in issues]
    assert (0, 'no_signal') in kinds
    assert 'noise floor' in issues[0]['message']


def test_unstated_gain_gives_no_judgement(id44):
    data = _noise()
    data[:, 0] = 1e-6
    issues = acquisition.input_health(data, _settings())
    assert not [i for i in issues if i['kind'] == 'no_signal']


def test_healthy_analogue_channel_is_quiet(id44):
    settings = _settings(gain=[30.0] * 4 + [None] * 18)
    data = _noise(dbfs=-20.0) * settings.input_vmax_channels()
    assert acquisition.input_health(data, settings) == []


def test_uncharacterised_device_gives_nothing(monkeypatch):
    monkeypatch.setattr(options, '_soundcard_identity',
                        lambda settings: ('Mystery USB Mic', ['x']))
    settings = options.MySettings(device_driver='soundcard', channels=2)
    assert acquisition.input_health(np.zeros((100, 2)), settings) == []
