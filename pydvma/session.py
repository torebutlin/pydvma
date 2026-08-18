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
import math
import threading
import webbrowser

from . import container
from . import datastructure

#: How many times :meth:`Session.push` re-reads and re-merges when the
#: journal moved under it (a capture landing, or another writer posting)
#: before giving up. Each retry only loses if something else writes
#: again in the merge window, so a handful is already generous for a
#: single-user lab session; the cap exists so a pathological writer
#: cannot spin here forever.
PUSH_MAX_ATTEMPTS = 10

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
    list REPLACES that entry IN PLACE, at its existing index — so the
    pull → filter/scale → push-back flow updates data where it sits
    instead of duplicating it or reordering the set — and anything else
    appends. Items without a ``unique_id`` always append. Should the
    target somehow already hold two items sharing one ``unique_id``,
    the LAST of them is the one replaced (the index map is a dict
    comprehension, so a later duplicate wins the key) and the earlier
    copies are left alone. ``DataSet.add_to_dataset`` accepts one item
    or one HOMOGENEOUS list, hence the per-kind walk over
    ``DataSet._LIST_ATTRS``.

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


def _count_items(dataset):
    """Total number of data items a DataSet holds, across every kind.

    Used by :meth:`Session.push` to notice that wrapping its argument
    produced an EMPTY DataSet — ``DataSet.add_to_dataset`` silently
    ignores anything it does not recognise, so without this an
    unsupported object would post an unchanged document and look like
    a successful push.

    Args:
        dataset (pydvma.datastructure.DataSet): the dataset to count.
    """
    return sum(len(getattr(dataset, name, []) or [])
               for name in datastructure.DataSet._LIST_ATTRS)


def _json_scalar(value):
    """Return ``value`` as a JSON-safe scalar, or :data:`_MISSING`.

    ``bool`` is tested before ``int`` (it is a subclass) so True stays
    a JSON boolean. Non-finite floats are REJECTED rather than passed
    through: ``json.dumps`` writes them as bare ``Infinity``/``NaN``,
    which is not JSON, and the browser's ``JSON.parse`` throws on the
    whole document — one bad setting would cost the UI its entire
    prefill.

    Args:
        value: the candidate value, of any type.
    """
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _MISSING
    return _MISSING


def _settings_to_config_json(settings):
    """Convert MySettings to the JSON dict served at ``/config``.

    That document is the web UI's Setup prefill. Keys come from the
    serve module's settings whitelist (derived from the
    ``MySettings.__init__`` signature) so the launch path and the
    ``--settings`` CLI path accept exactly the same set, and every
    value is coerced to what a hand-written settings JSON could carry:
    numpy arrays and scalars go through ``tolist()``, so the per-channel
    settings (``iepe_excit_current_A``, ``channel_sensitivities``) reach
    the UI in the array form it already reads, and anything still
    unrepresentable — a nested array, a resolved device object, a
    non-finite float (see :func:`_json_scalar`) — is dropped key and
    all rather than breaking the document. Constructor arguments that
    MySettings consumes without storing (``device``, the by-name
    selector) are absent from the instance and so absent here too.

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
        if hasattr(value, 'tolist'):
            # numpy array OR numpy scalar: both grow Python equivalents
            # this way (np.float64 -> float, array -> nested lists).
            value = value.tolist()
        if isinstance(value, (list, tuple)):
            items = [_json_scalar(v) for v in value]
            if _MISSING not in items:
                out[name] = items
            continue
        scalar = _json_scalar(value)
        if scalar is not _MISSING:
            out[name] = scalar
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
        self._closed = False
        self._close_lock = threading.Lock()

    def __repr__(self):
        """Notebook-facing summary: URL, driver, and open/closed."""
        state = 'closed' if (self._closed or not self._thread.is_alive()) \
            else 'open'
        return '<Session %s (driver=%s, %s)>' % (
            self.url, self._server.default_driver, state)

    def _snapshot(self):
        """Return ``(dataset, generation)`` — the journal, materialised.

        The generation belongs to the same read as the data, so a
        writer can hand it back to
        :meth:`pydvma.journal.SessionJournal.set_doc` as
        ``expect_generation`` and be refused if anything changed in
        between. :attr:`data` is this without the bookkeeping.
        """
        doc, captures, generation = self._server.journal.state()
        dataset = (container.load_bytes(doc) if doc
                   else datastructure.DataSet())
        for capture in captures:
            _merge_dataset(dataset, container.load_bytes(capture))
        return dataset, generation

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
        pending captures yet. Still readable after :meth:`close` —
        pulling your data out of a session you have finished with is
        the point of the explicit handoff, and the journal outlives
        the server thread that fed it.
        """
        return self._snapshot()[0]

    def push(self, data):
        """Hand data to the session; connected apps offer to reload.

        Merges into the CURRENT session data (:attr:`data`) rather than
        replacing it, by :func:`_merge_dataset`'s id rule — so pushing
        back something you pulled and edited updates that item in
        place, while genuinely new items append.

        The read-merge-write cycle is guarded by the journal's
        generation counter, so nothing is lost to a race: if a capture
        lands, or the app's autosave posts, between the read and the
        write, the post is REFUSED and this retries from a fresh read
        (up to :data:`PUSH_MAX_ATTEMPTS` times). Two concurrent pushes
        therefore serialise — one wins, the other re-merges on top of
        the winner's document — instead of one silently overwriting
        the other.

        Raises ``TypeError`` if ``data`` is not a DataSet and is not
        something ``DataSet.add_to_dataset`` recognises (which would
        otherwise post an unchanged document and look like success),
        ``RuntimeError`` if the session is closed, and ``RuntimeError``
        if the journal kept changing under every attempt.

        Args:
            data (pydvma.datastructure.DataSet or a single data item):
                what to hand over. Anything that is not already a
                DataSet is wrapped in one, so a lone
                :class:`~pydvma.datastructure.TimeData` (or any other
                item ``DataSet.add_to_dataset`` accepts) works
                directly.
        """
        with self._close_lock:
            if self._closed:
                raise RuntimeError('session is closed')
        if isinstance(data, datastructure.DataSet):
            source = data
        else:
            source = datastructure.DataSet(data)
            if _count_items(source) == 0:
                raise TypeError(
                    'cannot push %s: expected a DataSet or a single data '
                    'item (TimeData, FreqData, CrossSpecData, TfData, '
                    'ModalData, SonoData, MetaData), or a homogeneous '
                    'list of them' % type(data).__name__)
        journal = self._server.journal
        for _ in range(PUSH_MAX_ATTEMPTS):
            merged, generation = self._snapshot()
            _merge_dataset(merged, source)
            if journal.set_doc(container.save_bytes(merged), notify=True,
                               expect_generation=generation):
                return
        raise RuntimeError(
            'session changed repeatedly during push — retry')

    def close(self):
        """Stop the server and its thread. Idempotent and thread-safe.

        A second call — from this thread or another — is a clean no-op
        rather than a second stop injected into a shutdown already in
        progress. Prints a WARNING if the thread has not finished
        within :data:`SHUTDOWN_TIMEOUT_S`, in which case the port may
        still be bound; the thread is a daemon, so it cannot keep the
        interpreter alive either way.

        :attr:`data` keeps working afterwards (the journal is plain
        memory); :meth:`push` does not, since there is no longer an
        app to notify.
        """
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            _shutdown(self._loop, self._thread)
            if self._thread.is_alive():
                print('WARNING: pydvma session server thread did not stop '
                      'within %g s; %s may still be bound'
                      % (SHUTDOWN_TIMEOUT_S, self.url))

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
