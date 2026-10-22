# -*- coding: utf-8 -*-
"""The served app's working folder: pydvma.savefolder and its /engine ops."""
import asyncio
import json
import os

import pytest

from pydvma import savefolder
from pydvma.savefolder import SaveFolder, is_local_app_request


# ---- the origin guard -------------------------------------------------------

@pytest.mark.parametrize('origin, host', [
    ('http://127.0.0.1:8760', '127.0.0.1:8760'),
    ('http://localhost:8760', 'localhost:8760'),
    ('http://[::1]:8760', '[::1]:8760'),
    ('http://LOCALHOST:8760', 'localhost:8760'),
])
def test_the_served_app_itself_may_use_files(origin, host):
    assert is_local_app_request(origin, host)


@pytest.mark.parametrize('origin, host', [
    ('https://evil.example', '127.0.0.1:8760'),          # another site
    ('http://127.0.0.1:4173', '127.0.0.1:8760'),         # another local port
    ('http://evil.example:8760', 'evil.example:8760'),   # DNS rebinding
    ('null', '127.0.0.1:8760'),                          # sandboxed/file page
    (None, '127.0.0.1:8760'),                            # not a browser
    ('http://127.0.0.1:8760', None),
    ('file:///x', '127.0.0.1:8760'),
])
def test_anything_else_may_not(origin, host):
    assert not is_local_app_request(origin, host)


# ---- SaveFolder ---------------------------------------------------------------

def test_starts_in_the_current_directory_by_default(tmp_path, monkeypatch):
    # dvma.launch from a notebook: the kernel's cwd is the notebook's folder.
    monkeypatch.chdir(tmp_path)
    f = SaveFolder()
    assert f.path == tmp_path.resolve() or os.path.samefile(f.path, tmp_path)
    assert f.info()['name'] == tmp_path.name
    assert f.info()['sep'] == os.sep


def test_a_missing_start_folder_is_refused(tmp_path):
    with pytest.raises(ValueError, match='does not exist'):
        SaveFolder(tmp_path / 'nope')


def test_save_writes_atomically_and_never_overwrites_silently(tmp_path):
    f = SaveFolder(tmp_path)
    first = f.save('run1.dvma', b'ONE')
    assert first == {'path': str(tmp_path / 'run1.dvma'), 'saved': True, 'exists': False}
    assert (tmp_path / 'run1.dvma').read_bytes() == b'ONE'

    again = f.save('run1.dvma', b'TWO')                      # no overwrite flag
    assert again['saved'] is False and again['exists'] is True
    assert (tmp_path / 'run1.dvma').read_bytes() == b'ONE'

    forced = f.save('run1.dvma', b'TWO', overwrite=True)
    assert forced['saved'] is True and forced['exists'] is True
    assert (tmp_path / 'run1.dvma').read_bytes() == b'TWO'
    # No temporary files left behind.
    assert sorted(p.name for p in tmp_path.iterdir()) == ['run1.dvma']


def test_save_accepts_a_subfolder_or_an_absolute_path(tmp_path):
    # The Save dialog's "Choose location" sends a path elsewhere for one
    # file; the working folder itself does not move.
    (tmp_path / 'sub').mkdir()
    other = tmp_path / 'elsewhere'
    other.mkdir()
    f = SaveFolder(tmp_path)
    assert f.save(os.path.join('sub', 'a.csv'), b'x')['saved']
    assert (tmp_path / 'sub' / 'a.csv').exists()
    assert f.save(str(other / 'b.mat'), b'y')['saved']
    assert (other / 'b.mat').exists()
    assert f.path == SaveFolder(tmp_path).path


@pytest.mark.parametrize('name', ['evil.bat', 'run.py', 'noext', 'x.exe', ''])
def test_save_writes_only_data_export_and_figure_files(tmp_path, name):
    with pytest.raises(ValueError):
        SaveFolder(tmp_path).save(name, b'x')
    assert list(tmp_path.iterdir()) == []


def test_save_into_a_missing_folder_says_so(tmp_path):
    with pytest.raises(ValueError, match='folder does not exist'):
        SaveFolder(tmp_path).save(os.path.join('nope', 'a.dvma'), b'x')


def test_listing_shows_subfolders_and_loadable_files(tmp_path):
    for d in ('B', 'a', '.hidden'):
        (tmp_path / d).mkdir()
    for n in ('z.dvma', 'Y.mat', 'notes.txt', 'x.csv', 'old.npy', '.secret.dvma'):
        (tmp_path / n).write_bytes(b'')
    f = SaveFolder(tmp_path)
    got = f.listing()
    assert got['dir'] == str(f.path)
    assert got['parent'] == str(f.path.parent)
    assert got['folders'] == ['a', 'B']
    assert got['files'] == ['old.npy', 'x.csv', 'Y.mat', 'z.dvma']
    # Listing another folder does not change the working folder.
    assert f.listing('a')['dir'] == str(f.path / 'a')
    assert f.path == SaveFolder(tmp_path).path


def test_set_dir_moves_the_working_folder(tmp_path):
    (tmp_path / 'lab2').mkdir()
    f = SaveFolder(tmp_path)
    assert f.set_dir('lab2')['name'] == 'lab2'
    assert f.save('r.dvma', b'x')['path'] == str(f.path / 'r.dvma')
    with pytest.raises(ValueError, match='not a folder'):
        f.set_dir(tmp_path / 'missing')


def test_read_returns_a_loadable_file_and_nothing_else(tmp_path):
    (tmp_path / 'r.dvma').write_bytes(b'DATA')
    (tmp_path / 'secret.txt').write_bytes(b'nope')
    f = SaveFolder(tmp_path)
    got = f.read('r.dvma')
    assert got == {'name': 'r.dvma', 'path': str(f.path / 'r.dvma'), 'data': b'DATA'}
    with pytest.raises(ValueError, match='cannot load'):
        f.read('secret.txt')
    with pytest.raises(ValueError, match='no such file'):
        f.read('missing.dvma')


# ---- over the /engine socket of a real BridgeServer ------------------------

def _run(coro_fn):
    asyncio.run(coro_fn())


async def _start(tmp_path, save_dir):
    from pydvma import serve as serve_mod
    server = serve_mod.BridgeServer(host='127.0.0.1', port=0, default_driver='mock',
                                    session_dir=tmp_path, recover=False,
                                    save_dir=save_dir)
    task = asyncio.create_task(server.run())
    for _ in range(500):
        if server.sockets:
            break
        await asyncio.sleep(0.005)
    return server, task, next(iter(server.sockets)).getsockname()[1]


async def _stop(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _call(ws, rid, op, payload):
    from pydvma import engine_host
    await ws.send(engine_host.encode_frame({'id': rid, 'op': op, 'payload': payload}))
    return engine_host.decode_frame(await asyncio.wait_for(ws.recv(), 5.0))


def test_the_served_app_saves_lists_and_loads_through_engine(tmp_path):
    from websockets.asyncio.client import connect
    work = tmp_path / 'notebook'
    work.mkdir()

    async def scenario():
        server, task, port = await _start(tmp_path, work)
        try:
            async with connect('ws://127.0.0.1:%d/engine' % port, max_size=None,
                               origin='http://127.0.0.1:%d' % port) as ws:
                greeting = json.loads(await asyncio.wait_for(ws.recv(), 5.0))
                assert greeting['files'] is True
                info = await _call(ws, 1, 'files_info', {})
                assert info['ok'] and info['result']['name'] == 'notebook'
                saved = await _call(ws, 2, 'files_save',
                                    {'name': 'run.dvma', 'data': b'DVMA'})
                assert saved['result']['saved'] is True
                assert (work / 'run.dvma').read_bytes() == b'DVMA'
                clash = await _call(ws, 3, 'files_save',
                                    {'name': 'run.dvma', 'data': b'NEW'})
                assert clash['result'] == {'path': str(server.save_folder.path / 'run.dvma'),
                                           'saved': False, 'exists': True}
                listing = await _call(ws, 4, 'files_list', {})
                assert listing['result']['files'] == ['run.dvma']
                read = await _call(ws, 5, 'files_read', {'path': 'run.dvma'})
                assert read['result']['data'] == b'DVMA'
                bad = await _call(ws, 6, 'files_save', {'name': 'x.bat', 'data': b'x'})
                assert bad['ok'] is False and 'cannot save' in bad['error']
                moved = await _call(ws, 7, 'files_set_dir', {'dir': str(tmp_path)})
                assert moved['ok'] and server.save_folder.path == tmp_path.resolve()
        finally:
            await _stop(task)
    _run(scenario)


def test_another_site_gets_no_file_access(tmp_path):
    # Any page in the browser can open a websocket to localhost; only the
    # served app itself may touch files.
    from websockets.asyncio.client import connect
    work = tmp_path / 'notebook'
    work.mkdir()

    async def scenario():
        server, task, port = await _start(tmp_path, work)
        try:
            async with connect('ws://127.0.0.1:%d/engine' % port, max_size=None,
                               origin='https://evil.example') as ws:
                greeting = json.loads(await asyncio.wait_for(ws.recv(), 5.0))
                assert greeting['files'] is False
                reply = await _call(ws, 1, 'files_save',
                                    {'name': 'x.dvma', 'data': b'x'})
                assert reply['ok'] is False
                reply = await _call(ws, 2, 'files_list', {'dir': '/'})
                assert reply['ok'] is False
            assert list(work.iterdir()) == []
        finally:
            await _stop(task)
    _run(scenario)


def test_extensions_are_the_documented_sets():
    assert savefolder.SAVE_EXTENSIONS == ('.dvma', '.mat', '.csv', '.png', '.pdf', '.svg')
    assert savefolder.LISTED_EXTENSIONS == ('.dvma', '.mat', '.csv', '.npy')
