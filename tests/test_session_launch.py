# tests/test_session_launch.py
"""dvma.launch / Session: background-thread server, pull/push, close.

Mock driver end to end — no hardware, no browser (open_browser=False
throughout). Ephemeral ports only (port=0). Every launch passes an
isolated session_dir + recover=False so the suite never touches the
real system temp dir (same hygiene as tests/test_serve_protocol.py).
"""
import asyncio
import socket
import threading

import numpy as np
import pytest

pytest.importorskip('websockets')

from pydvma import container, datastructure, options
from pydvma.session import (Session, _merge_dataset, _settings_to_config_json,
                            launch)


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

    def test_bind_failure_raises_and_leaves_no_thread(self, tmp_path):
        # Hold an ephemeral port ourselves, then ask launch for it: the
        # readiness poll must notice the FAILED task rather than waiting
        # out the whole startup timeout, and must chain the real OSError.
        # (No hardcoded port -- the OS picks it.)
        held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        held.bind(('127.0.0.1', 0))
        held.listen(1)
        taken = held.getsockname()[1]
        try:
            with pytest.raises(RuntimeError) as excinfo:
                _launch(tmp_path, port=taken)
        finally:
            held.close()
        assert isinstance(excinfo.value.__cause__, OSError)
        assert str(taken) in str(excinfo.value)
        assert not [t for t in threading.enumerate()
                    if t.name == 'pydvma-session-server' and t.is_alive()]

    def test_repr_reports_url_driver_and_state(self, tmp_path):
        s = _launch(tmp_path)
        try:
            assert repr(s) == '<Session %s (driver=mock, open)>' % s.url
        finally:
            s.close()
        assert repr(s) == '<Session %s (driver=mock, closed)>' % s.url


class TestLaunchDependencies:
    """The tombstone for the removed `dvma.Logger` sends people straight
    to `launch()`, so a base install (no [serve] extra) must meet an
    actionable ImportError there, not a bare missing-module error."""

    def test_missing_websockets_names_the_extra(self, monkeypatch, tmp_path):
        import sys
        # None in sys.modules makes `import websockets` raise ImportError
        # — the standard way to simulate an absent dependency.
        monkeypatch.setitem(sys.modules, 'websockets', None)
        with pytest.raises(ImportError) as excinfo:
            launch(_mock_settings(), open_browser=False, port=0,
                   session_dir=tmp_path, recover=False)
        message = str(excinfo.value)
        assert 'pydvma[serve]' in message
        assert 'websockets' in message


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

    def test_push_preserves_app_authored_document_state(self, tmp_path):
        # A pull -> modify -> push round trip must not destroy the
        # per-item manifest keys only the browser app understands (its
        # `ui` block). The pulled item carries them as _container_extra,
        # and the whole-item replacement carries them back.
        import io
        import json
        import zipfile

        doc = container.save_bytes(_tiny_dataset('original'))
        with zipfile.ZipFile(io.BytesIO(doc)) as zf:
            manifest = json.loads(zf.read('manifest.json'))
            members = {n: zf.read(n) for n in zf.namelist()}
        manifest['items'][0]['ui'] = {'labels': ['hammer', 'accel']}
        members['manifest.json'] = json.dumps(manifest).encode()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, blob in members.items():
                zf.writestr(name, blob)

        with _launch(tmp_path) as s:
            s._server.journal.set_doc(buf.getvalue())
            td = s.data.time_data_list[0]          # pulled: carries the stash
            td.test_name = 'modified'
            s.push(td)
            out, _, _ = s._server.journal.state()
        with zipfile.ZipFile(io.BytesIO(out)) as zf:
            entry = json.loads(zf.read('manifest.json'))['items'][0]
        assert entry['ui'] == {'labels': ['hammer', 'accel']}
        assert entry['meta']['test_name'] == 'modified'

    def test_push_of_a_new_item_carries_no_app_state(self, tmp_path):
        # The documented flip side: a NEWLY created item replacing a
        # stored one has no display state, and none is invented.
        with _launch(tmp_path) as s:
            s.push(_tiny_dataset('fresh'))
            out, _, _ = s._server.journal.state()
        item = container.load_bytes(out).time_data_list[0]
        assert not hasattr(item, '_container_extra')

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

    def test_data_still_readable_after_close(self, tmp_path):
        s = _launch(tmp_path)
        s.push(_tiny_dataset('kept'))
        s.close()
        assert [t.test_name for t in s.data.time_data_list] == ['kept']


class TestPushGuards:
    """`push` must be loud when it cannot do what it was asked, and
    must never lose a write it raced with.
    """

    def test_push_notifies_listeners(self, tmp_path):
        # notify=True is what makes a connected app offer to reload --
        # pin it, since a silent post would look identical here.
        with _launch(tmp_path) as s:
            hits = []
            s._server.journal.add_listener(lambda: hits.append(1))
            s.push(_tiny_dataset())
        assert hits == [1]

    def test_push_unsupported_object_raises_and_leaves_journal(self, tmp_path):
        with _launch(tmp_path) as s:
            before = s._server.journal.generation
            with pytest.raises(TypeError) as excinfo:
                s.push(42)
            assert 'TimeData' in str(excinfo.value)   # names what IS accepted
            assert s._server.journal.generation == before

    def test_push_after_close_raises(self, tmp_path):
        s = _launch(tmp_path)
        s.close()
        with pytest.raises(RuntimeError, match='closed'):
            s.push(_tiny_dataset())

    def test_push_retries_when_a_capture_lands_mid_merge(self, tmp_path):
        # The capture-loss window: a capture registered between push's
        # read and its write used to be wiped by set_doc's clear. The
        # generation check turns that into a refusal + re-merge, so BOTH
        # survive. Simulated by a listener-free one-shot hook on the
        # journal's own state() -- the only moment the race matters.
        with _launch(tmp_path) as s:
            journal = s._server.journal
            real_state = journal.state
            fired = []

            def racing_state():
                result = real_state()
                if not fired:
                    fired.append(1)
                    journal.add_capture(
                        container.save_bytes(_tiny_dataset('raced')))
                return result

            journal.state = racing_state
            try:
                s.push(_tiny_dataset('pushed'))
            finally:
                journal.state = real_state
            names = sorted(t.test_name for t in s.data.time_data_list)
        assert fired == [1]              # the race really happened
        assert names == ['pushed', 'raced']

    def test_push_gives_up_after_bounded_retries(self, tmp_path):
        # A journal that changes on EVERY read can never be posted to;
        # push must raise rather than spin forever.
        with _launch(tmp_path) as s:
            journal = s._server.journal
            real_state = journal.state

            def always_racing_state():
                result = real_state()
                journal.add_capture(container.save_bytes(_tiny_dataset('r')))
                return result

            journal.state = always_racing_state
            try:
                with pytest.raises(RuntimeError, match='changed repeatedly'):
                    s.push(_tiny_dataset('pushed'))
            finally:
                journal.state = real_state


class TestMergeDataset:
    """`_merge_dataset` on its own -- the id rule that makes push
    idempotent rather than duplicating.
    """

    def test_empty_source_is_a_no_op(self):
        target = _tiny_dataset('a')
        _merge_dataset(target, datastructure.DataSet())
        assert [t.test_name for t in target.time_data_list] == ['a']

    def test_new_ids_append(self):
        target = _tiny_dataset('a')
        _merge_dataset(target, _tiny_dataset('b'))
        assert [t.test_name for t in target.time_data_list] == ['a', 'b']

    def test_replacement_preserves_index(self):
        target = _tiny_dataset('a')
        target.add_to_dataset(_tiny_dataset('b').time_data_list[0])
        target.add_to_dataset(_tiny_dataset('c').time_data_list[0])
        edited = datastructure.DataSet(target.time_data_list[1])
        edited.time_data_list[0].test_name = 'b-edited'
        _merge_dataset(target, edited)
        assert [t.test_name for t in target.time_data_list] == [
            'a', 'b-edited', 'c']

    def test_item_without_unique_id_appends(self):
        target = _tiny_dataset('a')
        source = _tiny_dataset('b')
        del source.time_data_list[0].unique_id
        _merge_dataset(target, source)
        assert [t.test_name for t in target.time_data_list] == ['a', 'b']

    def test_merges_every_kind_at_once(self):
        target = datastructure.DataSet()
        source = _tiny_dataset('td')
        source.add_to_dataset(datastructure.MetaData(test_name='md'))
        _merge_dataset(target, source)
        assert len(target.time_data_list) == 1
        assert len(target.meta_data_list) == 1


class TestSettingsToConfigJson:

    def test_json_safe_and_whitelisted(self):
        d = _settings_to_config_json(_mock_settings())
        import json
        json.dumps(d)                      # must be JSON-serialisable
        assert d['device_driver'] == 'mock'
        assert 'device' not in d           # constructor-only, never stored

    def test_arrays_reach_the_ui_as_lists(self):
        # serveConfig.ts reads iepe_excit_current_A as an array (or a
        # scalar); dropping it entirely -- as a naive JSON filter does,
        # since these default to numpy arrays -- silently loses the
        # prefill.
        d = _settings_to_config_json(_mock_settings())
        assert d['iepe_excit_current_A'] == [0.0, 0.0]
        assert d['channel_sensitivities'] == [1.0, 1.0]
        assert isinstance(d['iepe_excit_current_A'], list)

    def test_non_finite_values_are_dropped(self):
        # json.dumps would emit bare NaN/Infinity, which JSON.parse
        # rejects -- taking the WHOLE prefill document down with it.
        import json
        s = _mock_settings()
        s.VmaxSC = float('nan')
        s.pretrig_timeout = float('inf')
        s.channel_sensitivities = np.array([1.0, np.nan])
        d = _settings_to_config_json(s)
        assert 'VmaxSC' not in d
        assert 'pretrig_timeout' not in d
        assert 'channel_sensitivities' not in d
        assert 'NaN' not in json.dumps(d) and 'Infinity' not in json.dumps(d)

    def test_none_settings_gives_empty(self):
        assert _settings_to_config_json(None) == {}
