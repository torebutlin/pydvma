# tests/test_session_apply_settings.py
"""Session.apply_settings: settings pushed into an app that is already open.

Mock driver end to end, no browser: an "app tab" here is a websockets
client on /ws that answers the server's ``apply_settings`` frame the way
the web app's BridgeProvider does. Ephemeral ports, an isolated
session_dir and recover=False throughout, like tests/test_session_launch.py.
Also covers the two items that ride with it: the ``pretrig_threshold=None``
default (5 % of full scale, resolved by `options.pretrig_level`) and the
second-launch liveness probe that used to log a handshake traceback.
"""
import json
import logging
import threading
import time
import urllib.request
from types import SimpleNamespace

import pytest

pytest.importorskip('websockets')
from websockets.sync.client import connect

from pydvma import options, serve
from pydvma.session import _settings_to_config_json, launch


def _launch(tmp_path, settings=None, **over):
    kw = dict(open_browser=False, port=0, session_dir=tmp_path,
              recover=False)
    kw.update(over)
    return launch(settings, **kw)


def _config(session):
    with urllib.request.urlopen(session.url + 'config', timeout=5) as r:
        return json.loads(r.read().decode('utf-8'))


def _hammer():
    return options.MySettings(channels=2, fs=3000, stored_time=6,
                              pretrig_samples=100, pretrig_threshold=0.25,
                              device_driver='nidaq')


def _noise(stored_time=30):
    return options.MySettings(channels=2, fs=3000, stored_time=stored_time,
                              device_driver='nidaq')


class _Tab(object):
    """A stand-in app tab: answers each ``apply_settings`` push.

    ``answer`` is the dict sent back beside ``type``/``id`` (``None`` =
    never answer, like an app build predating the frame). Every pushed
    frame is kept in ``frames``.
    """

    def __init__(self, session, answer=None):
        self.answer = {'ok': True} if answer is None else answer
        self.silent = answer is False
        self.frames = []
        self.ws = connect(session.url.replace('http', 'ws') + 'ws')
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        time.sleep(0.1)   # let the server register the connection

    def _run(self):
        while not self._stop.is_set():
            try:
                raw = self.ws.recv(timeout=0.1)
            except TimeoutError:
                continue
            except Exception:
                return
            msg = json.loads(raw) if isinstance(raw, str) else {}
            if msg.get('type') != 'apply_settings':
                continue
            self.frames.append(msg)
            if not self.silent:
                self.ws.send(json.dumps(dict(self.answer,
                                             type='settings_applied',
                                             id=msg['id'])))

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2)
        self.ws.close()


# ---- the push itself --------------------------------------------------

def test_with_no_tab_open_config_is_replaced_and_the_call_says_so(tmp_path, capsys):
    session = _launch(tmp_path, _noise())
    try:
        session.apply_settings(_hammer())
        out = capsys.readouterr().out
        assert ('logger settings: 3000 Hz, 2 ch, 6 s, trigger armed on ch 0 '
                'at 0.25 V (no app tab is open; they apply when one opens at '
                '%s)' % session.url) in out
        doc = _config(session)
        assert (doc['fs'], doc['channels'], doc['stored_time']) == (3000, 2, 6.0)
        assert doc['pretrig_samples'] == 100
        assert doc['pretrig_threshold'] == 0.25
    finally:
        session.close()


def test_a_connected_tab_gets_the_whole_document_and_none_travels_as_null(
        tmp_path, capsys):
    session = _launch(tmp_path, _hammer())
    tab = _Tab(session)
    try:
        session.apply_settings(_noise())
        out = capsys.readouterr().out
        assert out.strip().endswith('(applied in 1 app tab)')
        assert 'trigger off' in out
        (frame,) = tab.frames
        assert frame['source'] == 'notebook'
        doc = frame['settings']
        # Present-null is what makes the app DISARM and fall back to its
        # own threshold, instead of keeping the hammer settings.
        assert 'pretrig_samples' in doc and doc['pretrig_samples'] is None
        assert 'pretrig_threshold' in doc and doc['pretrig_threshold'] is None
        assert doc == _config(session)
    finally:
        tab.close()
        session.close()


def test_the_notebook_example_line(tmp_path, capsys):
    session = _launch(tmp_path)
    tab = _Tab(session)
    capsys.readouterr()   # the launch banner
    try:
        session.apply_settings(_hammer())
        assert capsys.readouterr().out.strip() == (
            'logger settings: 3000 Hz, 2 ch, 6 s, trigger armed on ch 0 at '
            '0.25 V (applied in 1 app tab)')
    finally:
        tab.close()
        session.close()


def test_a_default_threshold_is_shown_resolved(tmp_path, capsys):
    session = _launch(tmp_path)
    try:
        session.apply_settings(options.MySettings(
            channels=2, fs=3000, stored_time=6, pretrig_samples=100,
            device_driver='nidaq', VmaxNI=5))
        assert 'trigger armed on ch 0 at 0.25 V' in capsys.readouterr().out
        session.apply_settings(options.MySettings(
            channels=1, fs=48000, stored_time=2, pretrig_samples=50,
            device_driver='mock'))
        assert 'at 0.05 × full scale' in capsys.readouterr().out
    finally:
        session.close()


def test_two_tabs_both_apply(tmp_path, capsys):
    session = _launch(tmp_path)
    tabs = [_Tab(session), _Tab(session)]
    try:
        session.apply_settings(_hammer())
        assert '(applied in 2 app tabs)' in capsys.readouterr().out
        assert all(len(t.frames) == 1 for t in tabs)
    finally:
        for t in tabs:
            t.close()
        session.close()


def test_a_refusing_tab_raises_and_leaves_config_alone(tmp_path):
    session = _launch(tmp_path, _noise())
    before = _config(session)
    tab = _Tab(session, {'ok': False,
                         'reason': 'a Nonlin run is in progress in the app'})
    try:
        with pytest.raises(RuntimeError, match='Nonlin run is in progress'):
            session.apply_settings(_hammer())
        assert _config(session) == before
    finally:
        tab.close()
        session.close()


def test_a_silent_tab_is_reported_and_config_still_changes(
        tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(serve, 'APPLY_SETTINGS_ANSWER_TIMEOUT_S', 0.3)
    session = _launch(tmp_path, _noise())
    tab = _Tab(session, answer=False)
    try:
        session.apply_settings(_hammer())
        assert '1 tab did not answer, reload it' in capsys.readouterr().out
        assert _config(session)['pretrig_samples'] == 100
    finally:
        tab.close()
        session.close()


def test_a_capture_in_flight_refuses_and_changes_nothing(tmp_path):
    session = _launch(tmp_path, _noise())
    before = _config(session)
    ws = connect(session.url.replace('http', 'ws') + 'ws')
    try:
        ws.send(json.dumps({'type': 'configure', 'settings': {
            'device_driver': 'mock', 'fs': 1000, 'channels': 1}}))
        assert json.loads(ws.recv(timeout=10))['event'] == 'configured'
        ws.send(json.dumps({'type': 'log', 'duration': 5.0,
                            'pretrigger': None}))
        time.sleep(0.3)
        with pytest.raises(RuntimeError, match='capture is in progress'):
            session.apply_settings(_hammer())
        assert _config(session) == before
        ws.send(json.dumps({'type': 'cancel'}))
    finally:
        ws.close()
        session.close()


def test_apply_after_close_raises(tmp_path):
    session = _launch(tmp_path)
    session.close()
    with pytest.raises(RuntimeError, match='closed'):
        session.apply_settings(_hammer())


def test_the_default_driver_follows_the_pushed_settings(tmp_path):
    session = _launch(tmp_path, options.MySettings(device_driver='mock'))
    try:
        session.apply_settings(_hammer())
        assert session._server.default_driver == 'nidaq'
    finally:
        session.close()


# ---- window / TF averaging ---------------------------------------------

def test_window_and_averaging_ride_in_config_and_carry_over(tmp_path, capsys):
    session = _launch(tmp_path, _noise(), window='hann',
                      tf_averaging='within')
    try:
        assert _config(session)['analysis_window'] == 'hann'
        session.apply_settings(_hammer(), window=None, tf_averaging='across')
        out = capsys.readouterr().out
        assert 'window none, TF averaging across' in out
        doc = _config(session)
        assert (doc['analysis_window'], doc['tf_averaging']) == ('none', 'across')
        # A later push that does not mention them keeps them for new tabs.
        session.apply_settings(_noise())
        doc = _config(session)
        assert (doc['analysis_window'], doc['tf_averaging']) == ('none', 'across')
        assert doc['pretrig_samples'] is None
    finally:
        session.close()


def test_settings_none_changes_only_the_analysis_defaults(tmp_path):
    session = _launch(tmp_path, _hammer())
    try:
        session.apply_settings(window='hamming')
        doc = _config(session)
        assert doc['analysis_window'] == 'hamming'
        assert doc['pretrig_samples'] == 100     # acquisition kept
    finally:
        session.close()


@pytest.mark.parametrize('kw', [{'window': 'flattop'}, {'window': 'boxcar'},
                                {'tf_averaging': 'sideways'},
                                {'tf_averaging': None}])
def test_bad_analysis_keywords_raise_before_anything_is_sent(tmp_path, kw):
    session = _launch(tmp_path, _noise())
    before = _config(session)
    try:
        with pytest.raises(ValueError):
            session.apply_settings(_hammer(), **kw)
        assert _config(session) == before
    finally:
        session.close()


def test_launch_rejects_a_bad_window_without_starting(tmp_path):
    with pytest.raises(ValueError, match='window'):
        _launch(tmp_path, window='flattop')


# ---- pretrig_threshold=None: 5 % of full scale ---------------------------

def test_pretrig_threshold_defaults_to_none_and_travels_as_null():
    s = options.MySettings()
    assert s.pretrig_threshold is None
    doc = _settings_to_config_json(s)
    assert 'pretrig_threshold' in doc and doc['pretrig_threshold'] is None


@pytest.mark.parametrize('settings, level', [
    (SimpleNamespace(device_driver='nidaq', VmaxNI=5.0, VmaxSC=1.0,
                     pretrig_threshold=None), 0.25),
    (SimpleNamespace(device_driver='nidaq', VmaxNI=10.0,
                     pretrig_threshold=None), 0.5),
    (SimpleNamespace(device_driver='soundcard', VmaxSC=1.0,
                     pretrig_threshold=None), 0.05),
    # Rounded to 2 significant figures, as the app rounds its default.
    (SimpleNamespace(device_driver='soundcard', VmaxSC=13.8,
                     pretrig_threshold=None), 0.69),
    (SimpleNamespace(device_driver='nidaq', VmaxNI=5.0,
                     pretrig_threshold=0.1), 0.1),
    (SimpleNamespace(pretrig_threshold=None), 0.05),
])
def test_pretrig_level(settings, level):
    assert options.pretrig_level(settings) == pytest.approx(level)


def test_pretrig_level_on_a_real_mysettings():
    s = options.MySettings(device_driver='nidaq', VmaxNI=5)
    assert options.pretrig_level(s) == 0.25
    s = options.MySettings(device_driver='nidaq', VmaxNI=5,
                           pretrig_threshold=0.05)
    assert options.pretrig_level(s) == 0.05


# ---- the second launch's liveness probe -----------------------------------

def test_probing_a_live_server_logs_no_handshake_error(tmp_path, caplog):
    session = _launch(tmp_path)
    try:
        port = int(session.url.rsplit(':', 1)[1].strip('/'))
        with caplog.at_level(logging.DEBUG):
            assert serve._port_is_live(port, host=session._server.host)
            time.sleep(0.3)
        errors = [r for r in caplog.records
                  if r.levelno >= logging.WARNING
                  and r.name.startswith('websockets')]
        assert errors == []
    finally:
        session.close()


def test_bare_connects_and_head_requests_log_no_error(tmp_path, caplog):
    """Something else probing the port (an old pydvma, a launcher's
    health check) used to log a red traceback in the kernel too."""
    import socket
    session = _launch(tmp_path)
    try:
        host = session._server.host
        port = int(session.url.rsplit(':', 1)[1].strip('/'))
        with caplog.at_level(logging.DEBUG):
            socket.create_connection((host, port), timeout=1).close()
            with socket.create_connection((host, port), timeout=1) as sock:
                sock.sendall(b'HEAD / HTTP/1.1\r\nHost: x\r\n\r\n')
                time.sleep(0.2)
            time.sleep(0.3)
        loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert loud == []
        quiet = [r for r in caplog.records
                 if r.getMessage().startswith('opening handshake failed')]
        assert len(quiet) == 2 and all(r.levelno == logging.DEBUG for r in quiet)
        # The server still answers normally afterwards.
        assert _config(session) is not None
    finally:
        session.close()
