# tests/test_session_launch.py
"""dvma.launch / Session: background-thread server, pull/push, close.

Mock driver end to end — no hardware, no browser (open_browser=False
throughout). Ephemeral ports only (port=0). Every launch passes an
isolated session_dir + recover=False so the suite never touches the
real system temp dir (same hygiene as tests/test_serve_protocol.py).
"""
import asyncio

import numpy as np
import pytest

pytest.importorskip('websockets')

from pydvma import container, datastructure, options
from pydvma.session import Session, launch, _settings_to_config_json


def _mock_settings():
    return options.MySettings(device_driver='mock', channels=2,
                              fs=8000, stored_time=0.1)


def _tiny_dataset(name='pushed'):
    td = datastructure.TimeData(
        time_axis=np.arange(80) / 8000.0,
        time_data=np.zeros((80, 1)),
        settings=_mock_settings(), test_name=name)
    return datastructure.DataSet(td)


def _launch(tmp_path, **over):
    kw = dict(open_browser=False, port=0,
              session_dir=tmp_path, recover=False)
    kw.update(over)
    return launch(_mock_settings(), **kw)


class TestLaunchLifecycle:

    def test_launch_starts_and_closes(self, tmp_path):
        session = _launch(tmp_path)
        try:
            assert session.url.startswith('http://127.0.0.1:')
        finally:
            session.close()
        assert not session._thread.is_alive()

    def test_close_is_idempotent(self, tmp_path):
        session = _launch(tmp_path)
        session.close()
        session.close()          # second close must be a clean no-op
        assert not session._thread.is_alive()

    def test_launch_inside_running_loop(self, tmp_path):
        # The kernel-thread asyncio clash (design doc, risks): launch
        # must work when the CALLER already runs an asyncio loop
        # (Jupyter). It runs the server on its own thread + loop.
        async def run():
            s = _launch(tmp_path)
            s.close()
            return True
        assert asyncio.run(run()) is True

    def test_context_manager(self, tmp_path):
        with _launch(tmp_path) as s:
            assert s.url
        assert not s._thread.is_alive()

    def test_config_prefill_served(self, tmp_path):
        import json
        import urllib.request
        with _launch(tmp_path) as s:
            cfg = json.loads(urllib.request.urlopen(
                s.url + 'config', timeout=5).read())
        assert cfg['device_driver'] == 'mock'
        assert cfg['fs'] == 8000

    def test_two_sessions_coexist(self, tmp_path):
        with _launch(tmp_path / 'a') as s1, _launch(tmp_path / 'b') as s2:
            assert s1.url != s2.url


class TestSessionData:

    def test_empty_session_data(self, tmp_path):
        with _launch(tmp_path) as s:
            ds = s.data
        assert len(ds.time_data_list) == 0

    def test_push_then_data_round_trip(self, tmp_path):
        with _launch(tmp_path) as s:
            s.push(_tiny_dataset())
            ds = s.data
        assert len(ds.time_data_list) == 1
        assert ds.time_data_list[0].test_name == 'pushed'

    def test_push_timedata_wraps(self, tmp_path):
        with _launch(tmp_path) as s:
            s.push(_tiny_dataset().time_data_list[0])
            assert len(s.data.time_data_list) == 1

    def test_push_appends_to_existing_doc(self, tmp_path):
        with _launch(tmp_path) as s:
            s._server.journal.set_doc(
                container.save_bytes(_tiny_dataset('a')))
            s.push(_tiny_dataset('b'))
            names = [t.test_name for t in s.data.time_data_list]
        assert names == ['a', 'b']

    def test_push_same_unique_id_replaces(self, tmp_path):
        # pull -> modify -> push back updates IN PLACE (smart merge).
        with _launch(tmp_path) as s:
            s.push(_tiny_dataset('original'))
            td = s.data.time_data_list[0]
            td.test_name = 'modified'          # same unique_id
            s.push(td)
            names = [t.test_name for t in s.data.time_data_list]
        assert names == ['modified']

    def test_data_includes_pending_captures(self, tmp_path):
        with _launch(tmp_path) as s:
            s._server.journal.add_capture(
                container.save_bytes(_tiny_dataset('cap')))
            names = [t.test_name for t in s.data.time_data_list]
        assert names == ['cap']

    def test_data_returns_fresh_objects(self, tmp_path):
        # explicit handoff: mutating a pulled object does NOT change
        # the session until pushed back.
        with _launch(tmp_path) as s:
            s.push(_tiny_dataset('original'))
            pulled = s.data.time_data_list[0]
            pulled.test_name = 'mutated-locally'
            assert s.data.time_data_list[0].test_name == 'original'


class TestSettingsToConfigJson:

    def test_json_safe_and_whitelisted(self):
        d = _settings_to_config_json(_mock_settings())
        import json
        json.dumps(d)                      # must be JSON-serialisable
        assert d['device_driver'] == 'mock'
        assert 'device_full_info' not in d  # non-JSON fields dropped

    def test_none_settings_gives_empty(self):
        assert _settings_to_config_json(None) == {}
