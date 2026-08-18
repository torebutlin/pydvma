# -*- coding: utf-8 -*-
"""The notebook front door: ``dvma.launch(settings)`` (stage 4).

Successor to the removed ``dvma.Logger``. Starts the full
``pydvma-serve`` stack — acquisition bridge, native ``/engine`` compute
host, session journal, embedded web UI — on a background thread INSIDE
the kernel process, opens the browser, and returns a :class:`Session`
handle::

    import pydvma as dvma
    session = dvma.launch(dvma.MySettings(device_driver='nidaq',
                                          fs=3000, channels=2))
    session.data               # live view of the session document
    session.push(dataset)      # hand data back; the app offers to reload
    session.close()

Explicit handoff, not shared mutation: :attr:`Session.data`
materialises fresh pydvma objects from the journal under its lock, and
:meth:`Session.push` is the only write path — the kernel never holds
live references the engine is concurrently computing on.

The server runs on ITS OWN daemon thread and event loop, so
:func:`launch` works identically from a plain script and from inside
Jupyter (whose kernel already runs an asyncio loop). The notebook is
optional — ``pydvma-serve --open`` starts the same server with no kernel
anywhere; the only difference is that no one holds a :class:`Session`.
"""
import asyncio
import threading
import webbrowser

from . import container
from . import datastructure

#: Seconds :func:`launch` waits for the background server to bind before
#: giving up and raising. Generous: binding a loopback port is instant,
#: so anything approaching this is a real failure, not slowness.
STARTUP_TIMEOUT_S = 10.0

#: Seconds :meth:`Session.close` waits for the server thread to finish
#: after stopping its loop. The thread is a daemon, so even a wedged
#: shutdown cannot keep the interpreter alive past this.
SHUTDOWN_TIMEOUT_S = 10.0

#: How often the server thread re-checks whether the listener is up (or
#: has failed) before signalling :func:`launch`'s startup event.
_POLL_INTERVAL_S = 0.005

#: Sentinel distinguishing "attribute absent" from "attribute is None"
#: in :func:`_settings_to_config_json`.
_MISSING = object()


def _merge_dataset(target, source):
    """Merge every item of ``source`` into ``target``, replacing by id.

    An item whose ``unique_id`` already exists in the target's same-kind
    list REPLACES that entry — so the pull → filter/scale → push-back
    flow updates data in place instead of duplicating it — and anything
    else appends. Items without a ``unique_id`` always append.
    ``DataSet.add_to_dataset`` accepts one item or one HOMOGENEOUS list,
    hence the per-kind walk over ``DataSet._LIST_ATTRS``.

    Mutates ``target`` in place and returns nothing.

    Args:
        target (pydvma.datastructure.DataSet): the dataset merged into.
        source (pydvma.datastructure.DataSet): the dataset merged from;
            never modified.
    """
    for name in datastructure.DataSet._LIST_ATTRS:
        target_list = getattr(target, name)
        by_id = {getattr(t, 'unique_id', None): i
                 for i, t in enumerate(target_list)}
        by_id.pop(None, None)
        appends = []
        for item in list(getattr(source, name, []) or []):
            uid = getattr(item, 'unique_id', None)
            if uid is not None and uid in by_id:
                target_list[by_id[uid]] = item
            else:
                appends.append(item)
        if appends:
            target.add_to_dataset(appends)


def _settings_to_config_json(settings):
    """Convert MySettings to the JSON dict served at ``/config``.

    That document is the web UI's Setup prefill. Keys come from the
    serve module's settings whitelist (derived from the
    ``MySettings.__init__`` signature) so the launch path and the
    ``--settings`` CLI path accept exactly the same set, and only
    JSON-representable values survive: array-valued settings
    (``iepe_excit_current_A``, ``channel_sensitivities``) and any other
    resolved runtime baggage are dropped, matching what a hand-written
    settings JSON could contain. Constructor arguments that MySettings
    consumes without storing (``device``, the by-name selector) are
    absent from the instance and so absent here too.

    Returns an empty dict when ``settings`` is None.

    Args:
        settings (pydvma.options.MySettings or None): the settings the
            UI should open with.
    """
    if settings is None:
        return {}
    from . import serve
    out = {}
    for name in sorted(serve._SETTINGS_WHITELIST):
        value = getattr(settings, name, _MISSING)
        if value is _MISSING:
            continue
        if isinstance(value, (list, tuple)):
            if all(isinstance(v, (int, float, str, bool)) for v in value):
                out[name] = list(value)
        elif isinstance(value, (bool, int, float, str)) or value is None:
            out[name] = value
    return out


def _shutdown(loop, thread):
    """Stop ``loop`` from another thread and join its ``thread``.

    Idempotent and safe on an already-finished thread: a dead thread is
    left alone, and a loop that closed between the liveness check and
    the call raises ``RuntimeError``, which is swallowed. Shared by
    :func:`launch`'s failure path and :meth:`Session.close`.

    Args:
        loop (asyncio.AbstractEventLoop): the server's event loop.
        thread (threading.Thread): the daemon thread running it.
    """
    if not thread.is_alive():
        return
    try:
        loop.call_soon_threadsafe(loop.stop)
    except RuntimeError:
        pass
    thread.join(timeout=SHUTDOWN_TIMEOUT_S)


def _serve_forever(server, loop, ready, failure):
    """Run ``server`` on ``loop`` until the loop is stopped.

    The body of :func:`launch`'s daemon thread. Installs ``loop`` as
    this thread's event loop, schedules ``server.run()``, and polls
    every :data:`_POLL_INTERVAL_S` until either the listener is up or
    the task has finished — setting ``ready`` in both cases, so a bind
    failure wakes :func:`launch` immediately instead of stranding it
    until the startup timeout. On the way out it cancels the task,
    drains it (recording any real exception into ``failure`` for
    :func:`launch` to chain), shuts down async generators, and closes
    the loop.

    Args:
        server (pydvma.serve.BridgeServer): the server to run.
        loop (asyncio.AbstractEventLoop): the loop to own.
        ready (threading.Event): set once the listener is up or the
            server task has finished, and again once the thread exits.
        failure (list): single-slot output list an exception from
            ``server.run()`` is appended to.
    """
    asyncio.set_event_loop(loop)
    task = loop.create_task(server.run())

    def _poll_ready():
        if ready.is_set():
            return
        if server.sockets or task.done():
            ready.set()
        else:
            loop.call_later(_POLL_INTERVAL_S, _poll_ready)

    loop.call_soon(_poll_ready)
    try:
        loop.run_forever()
    finally:
        task.cancel()
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        except BaseException as exc:  # surfaced by launch(), never swallowed
            failure.append(exc)
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except BaseException:
            pass
        asyncio.set_event_loop(None)
        loop.close()
        # Belt-and-braces: a thread that died before ever binding must
        # not leave launch() blocked for the whole startup timeout.
        ready.set()


class Session(object):
    """A running pydvma session: the served app plus its data.

    Returned by :func:`launch`; not constructed directly. Usable as a
    context manager, which closes the server on exit.

    Args:
        server (pydvma.serve.BridgeServer): the running server, whose
            :attr:`~pydvma.serve.BridgeServer.journal` holds the
            authoritative session document.
        thread (threading.Thread): the daemon thread running it.
        loop (asyncio.AbstractEventLoop): that thread's event loop.
        url (str): where the app is served, with a trailing slash.

    Attributes:
        url (str): where the app is served (e.g.
            ``'http://127.0.0.1:8760/'``) — hand it to a browser on
            another window, or re-open it after closing the tab; the
            session document survives (that is what the journal is
            for).
    """

    def __init__(self, server, thread, loop, url):
        self._server = server
        self._thread = thread
        self._loop = loop
        self.url = url

    @property
    def data(self):
        """The session's data as a fresh DataSet (read-only view).

        Materialised from the journal on EVERY access: the posted
        session document, with any captures logged since that post
        merged in by :func:`_merge_dataset`. Nothing here is shared
        with the app or the engine — mutating what you pull changes
        nothing until you :meth:`push` it back, and the ids carried
        through the container round-trip are what make that push land
        in place.

        An empty DataSet when the session has no document and no
        pending captures yet.
        """
        doc, captures = self._server.journal.state()
        dataset = (container.load_bytes(doc) if doc
                   else datastructure.DataSet())
        for capture in captures:
            _merge_dataset(dataset, container.load_bytes(capture))
        return dataset

    def push(self, data):
        """Hand data to the session; connected apps offer to reload.

        Merges into the CURRENT session data (:attr:`data`) rather than
        replacing it, by :func:`_merge_dataset`'s id rule — so pushing
        back something you pulled and edited updates that item in
        place, while genuinely new items append.

        Not atomic against a concurrent capture: the read and the write
        are each individually locked by the journal, but a capture that
        lands between them stays pending and is picked up by the next
        read (and by the app's next autosave), rather than being lost.
        Acceptable for a single-user lab session, where a push from the
        kernel and a capture from the bridge are not simultaneous in
        practice.

        Args:
            data (pydvma.datastructure.DataSet or a single data item):
                what to hand over. Anything that is not already a
                DataSet is wrapped in one, so a lone
                :class:`~pydvma.datastructure.TimeData` (or any other
                item ``DataSet.add_to_dataset`` accepts) works
                directly.
        """
        if isinstance(data, datastructure.DataSet):
            source = data
        else:
            source = datastructure.DataSet(data)
        merged = self.data
        _merge_dataset(merged, source)
        self._server.journal.set_doc(container.save_bytes(merged),
                                     notify=True)

    def close(self):
        """Stop the server and its thread. Idempotent.

        A second call on an already-closed session is a clean no-op.
        The served app stops responding immediately; anything the
        journal held goes with it, so save or :attr:`data` out
        whatever you still want first.
        """
        _shutdown(self._loop, self._thread)

    def __enter__(self):
        """Return self, so ``with launch(...) as session:`` works."""
        return self

    def __exit__(self, exc_type, exc, tb):
        """Close the session on context-manager exit.

        Returns None, so an exception raised inside the ``with`` block
        propagates after the server is stopped.
        """
        self.close()


def launch(settings=None, open_browser=True, port=0, ui_dir=None,
           session_dir=None, recover=True):
    """Start a pydvma session and return its :class:`Session` handle.

    Runs the same server as ``pydvma-serve`` — acquisition bridge,
    native ``/engine`` compute host, session journal, embedded UI — on
    a daemon thread with its own event loop inside the calling process,
    so this works unchanged from a plain script and from inside Jupyter
    (whose kernel already runs an asyncio loop of its own).

    The default ``port=0`` takes an ephemeral port, so several sessions
    can run side by side; read the one actually bound from
    :attr:`Session.url`. Printing that URL is how a session announces
    itself, matching ``pydvma-serve``'s startup line.

    Raises ``RuntimeError`` if the server does not bind within
    :data:`STARTUP_TIMEOUT_S` — chained to the underlying error (an
    ``OSError`` when an explicit ``port`` is already taken) when there
    was one.

    Args:
        settings (pydvma.options.MySettings or None): acquisition
            settings the app opens with. Prefills Setup via ``/config``
            (see :func:`_settings_to_config_json`) and supplies the
            default acquisition driver; ``None`` prefills nothing and
            leaves the driver at ``'mock'``.
        open_browser (bool): open the app in a browser tab (default
            True). Pass False for a headless or scripted launch — the
            URL is still printed and on :attr:`Session.url`.
        port (int): TCP port to bind, or 0 (default) for an ephemeral
            one.
        ui_dir (str or pathlib.Path or None): built UI directory to
            serve. ``None`` (default) resolves exactly as
            ``pydvma-serve`` does — the dev checkout's ``webui/dist``
            if present, else the copy packaged in the wheel, else no UI
            at all (the bridge still serves, with a help page).
        session_dir (pathlib.Path or str or None): where the journal's
            spill file lives and previous-run sessions are recovered
            from. Passed through to
            :class:`~pydvma.serve.BridgeServer`; ``None`` means the
            system temp dir. Tests and advanced users point this at a
            directory they control.
        recover (bool): offer a previous run's spill file for recovery
            in the app (default True). Passed through to
            :class:`~pydvma.serve.BridgeServer`; False skips the
            startup scan entirely.
    """
    from . import serve

    driver = getattr(settings, 'device_driver', None) or 'mock'
    resolved_ui_dir = serve._resolve_ui_dir(ui_dir)
    server = serve.BridgeServer(
        port=port, ui_dir=resolved_ui_dir,
        settings_json=_settings_to_config_json(settings),
        default_driver=driver, session_dir=session_dir, recover=recover)

    ready = threading.Event()
    failure = []
    loop = asyncio.new_event_loop()
    thread = threading.Thread(
        target=_serve_forever, args=(server, loop, ready, failure),
        name='pydvma-session-server', daemon=True)
    thread.start()

    if not ready.wait(STARTUP_TIMEOUT_S) or not server.sockets:
        # Join FIRST: the failing task's exception is only recorded once
        # the thread has drained it on the way out.
        _shutdown(loop, thread)
        message = ('pydvma session server failed to start on port %r '
                   '(host %s)' % (port, server.host))
        if failure:
            raise RuntimeError(message) from failure[0]
        raise RuntimeError(message + ' within %g s' % STARTUP_TIMEOUT_S)

    real_port = server.sockets[0].getsockname()[1]
    url = 'http://%s:%d/' % (server.host, real_port)
    print('pydvma session listening on %s (ws at %s/ws, driver=%s)'
          % (url, url.rstrip('/'), driver))
    if resolved_ui_dir is None:
        print('  no built UI found; serving the bridge + a help page. '
              'Build webui/dist or pass ui_dir=...')
    if open_browser:
        webbrowser.open(url)
    return Session(server, thread, loop, url)
