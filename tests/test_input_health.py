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


def test_contiguous_silent_optical_inputs_are_one_issue(id44):
    # An iD44 asked for 22 channels with no ADAT expander: one line for the
    # sixteen optical inputs, not sixteen toasts' worth.
    data = _noise()
    data[:, 4:20] = 0.0
    issues = [i for i in acquisition.input_health(data, _settings())
              if i['kind'] == 'optical_silent']
    assert len(issues) == 1
    assert issues[0]['channel'] == 4
    assert issues[0]['channels'] == list(range(4, 20))
    assert 'channels 5-20 are optical (ADAT) inputs' in issues[0]['message']


def test_separate_runs_of_silent_optical_inputs_are_separate_issues(id44):
    data = _noise()
    data[:, 5] = 0.0
    data[:, 8:11] = 0.0
    issues = [i for i in acquisition.input_health(data, _settings())
              if i['kind'] == 'optical_silent']
    assert [i['channels'] for i in issues] == [[5], [8, 9, 10]]
    assert 'channel 6 is an optical (ADAT) input' in issues[0]['message']
    assert 'channels 9-11 are optical (ADAT) inputs' in issues[1]['message']


def _mock_settings():
    return options.MySettings(device_driver='mock', channels=2, fs=8000,
                              stored_time=0.1, chunk_size=100, num_chunks=4)


def test_log_data_clears_the_last_issues_before_it_captures():
    # A capture that fails early must not leave the previous capture's
    # notices for the next reader.
    acquisition.LAST_CAPTURE_INPUT_HEALTH = [{'channel': 0, 'kind': 'no_signal',
                                              'message': 'stale'}]
    settings = _mock_settings()
    settings.pretrig_samples = settings.chunk_size + 1     # refused in log_data
    try:
        with pytest.raises(ValueError, match='pretrig_samples'):
            acquisition.log_data(settings)
        assert acquisition.LAST_CAPTURE_INPUT_HEALTH == []
    finally:
        acquisition.LAST_CAPTURE_INPUT_HEALTH = []


def test_a_failing_health_check_is_logged_not_raised(monkeypatch, caplog):
    import logging
    from pydvma import streams

    def broken(data, settings):
        raise RuntimeError('health check exploded')

    monkeypatch.setattr(acquisition, 'input_health', broken)
    try:
        with caplog.at_level(logging.DEBUG, logger='pydvma.acquisition'):
            acquisition.log_data(_mock_settings())
        assert acquisition.LAST_CAPTURE_INPUT_HEALTH == []
        assert any('health check exploded' in r.getMessage()
                   and r.levelno == logging.DEBUG for r in caplog.records)
    finally:
        try:
            streams.REC.end_stream()
        except Exception:
            pass
