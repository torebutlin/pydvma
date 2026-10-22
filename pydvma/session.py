# -*- coding: utf-8 -*-
"""The notebook front door: ``dvma.launch(settings)`` (stage 4).

Successor to the removed ``dvma.Logger``. Starts the full
``pydvma-serve`` stack — acquisition bridge, native ``/engine`` compute
host, session journal, embedded web UI — on a background thread INSIDE
the kernel process, opens the browser, and returns a `Session`
handle::

    import pydvma as dvma
    session = dvma.launch(dvma.MySettings(device_driver='nidaq',
                                          fs=3000, channels=2))
    session.data               # live view of the session document
    session.push(dataset)      # hand data back; the app offers to reload
    session.apply_settings(dvma.MySettings(device_driver='nidaq',
                                           fs=3000, channels=2,
                                           stored_time=6,
                                           pretrig_samples=100),
                           window=None)   # change Setup in the open app
    session.close()

Explicit handoff, not shared mutation: `Session.data`
materialises fresh pydvma objects from the journal under its lock, and
`Session.push` is the only write path — the kernel never holds
live references the engine is concurrently computing on.

The server runs on ITS OWN daemon thread and event loop, so
`launch` works identically from a plain script and from inside
Jupyter (whose kernel already runs an asyncio loop). The notebook is
optional — ``pydvma-serve --open`` starts the same server with no kernel
anywhere; the only difference is that no one holds a `Session`.
"""
import asyncio
import math
import threading
import webbrowser

from . import container
from . import datastructure

#: How many times `Session.push` re-reads and re-merges when the
#: journal moved under it (a capture landing, or another writer posting)
#: before giving up. Each retry only loses if something else writes
#: again in the merge window, so a handful is already generous for a
#: single-user lab session; the cap exists so a pathological writer
#: cannot spin here forever.
PUSH_MAX_ATTEMPTS = 10

#: Seconds `launch` waits for the background server to bind before
#: giving up and raising. Generous: binding a loopback port is instant,
#: so anything approaching this is a real failure, not slowness.
STARTUP_TIMEOUT_S = 10.0

#: Seconds `Session.close` waits for the server thread to finish
#: after stopping its loop. The thread is a daemon, so even a wedged
#: shutdown cannot keep the interpreter alive past this.
SHUTDOWN_TIMEOUT_S = 10.0

#: How often the server thread re-checks whether the listener is up (or
#: has failed) before signalling `launch`'s startup event.
_POLL_INTERVAL_S = 0.005

#: Sentinel distinguishing "attribute absent" from "attribute is None"
#: in `_settings_to_config_json`.
_MISSING = object()

#: Sentinel default for `Session.apply_settings`' and `launch`'s
#: ``window`` / ``tf_averaging``: "not given, leave the app's choice
#: alone". A plain None cannot mean that, because ``window=None`` is
#: pydvma's spelling of "no window" everywhere else.
_UNSET = object()

#: Window names `Session.apply_settings` and `launch` accept: the ones
#: BOTH the web app's Frequency and TF cards offer (the Frequency card's
#: ``flattop`` has no TF equivalent). ``None`` is accepted as ``'none'``.
APP_WINDOWS = ('none', 'hann', 'hamming')

#: The web app's TF averaging modes: ``'within'`` averages frames inside
#: each capture (noise excitation), ``'across'`` averages across the
#: captures in the tray (repeated hammer hits), ``'none'`` is one frame.
TF_AVERAGING_MODES = ('none', 'within', 'across')

#: ``/config`` keys carrying the analysis defaults for new sets. Not
#: MySettings fields: the app reads them alongside the acquisition
#: settings, and a hand-written ``pydvma-serve --settings`` file may
#: carry them too.
_ANALYSIS_KEYS = ('analysis_window', 'tf_averaging')

#: Why a push is refused while a capture runs — the same words the web app
#: answers with (``pushedSettingsRefusal`` in ``webui/src/lib/audio/
#: serveConfig.ts``), so the notebook reads the same whichever side noticed.
_CAPTURE_BUSY = ('a capture is in progress in the app (logging, or armed and '
                 'waiting for its trigger)')


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

    Used by `Session.push` to notice that wrapping its argument
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
    """Return ``value`` as a JSON-safe scalar, or `_MISSING`.

    ``bool`` is tested before ``int`` (it is a subclass) so True stays
    a JSON boolean. Non-finite floats are REJECTED rather than passed
    through: ``json.dumps`` writes them as bare ``Infinity``/``NaN``,
    which is not JSON, and the browser's ``JSON.parse`` throws on the
    whole document — one bad setting would cost the UI its entire
    prefill.

    Args:
        value (object): the candidate value, of any type.
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
    non-finite float (see `_json_scalar`) — is dropped key and
    all rather than breaking the document. Constructor arguments that
    MySettings consumes without storing (``device``, the by-name
    selector) are absent from the instance and so absent here too.

    A setting that is None is kept, as JSON ``null``, because the app
    reads a present ``null`` as "clear this setting":
    ``pretrig_samples=None`` disarms the trigger, and
    ``pretrig_threshold=None`` falls back to the app's 5 %-of-full-scale
    default. Keys that are absent from the document (only possible in a
    hand-written ``pydvma-serve --settings`` file) leave the app's value
    alone.

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


def _analysis_config(window, tf_averaging):
    """Validate the analysis keywords and return their ``/config`` keys.

    Shared by `launch` and `Session.apply_settings`. A keyword left at
    `_UNSET` contributes nothing.

    Args:
        window (str or None or _UNSET): one of `APP_WINDOWS`, or None
            for no window.
        tf_averaging (str or _UNSET): one of `TF_AVERAGING_MODES`.

    Raises:
        ValueError: an unknown window or averaging mode.
    """
    out = {}
    if window is not _UNSET:
        name = 'none' if window is None else str(window).lower()
        if name not in APP_WINDOWS:
            raise ValueError(
                'window must be one of %s or None (no window), got %r. '
                'The app\'s flattop window is on the Frequency card only, '
                'so it cannot be a default for both cards.'
                % (', '.join(repr(w) for w in APP_WINDOWS), window))
        out['analysis_window'] = name
    if tf_averaging is not _UNSET:
        mode = str(tf_averaging).lower() if tf_averaging is not None else None
        if mode not in TF_AVERAGING_MODES:
            raise ValueError(
                'tf_averaging must be one of %s, got %r'
                % (', '.join(repr(m) for m in TF_AVERAGING_MODES),
                   tf_averaging))
        out['tf_averaging'] = mode
    return out


def _merge_config(current, acquisition, analysis):
    """The ``/config`` document a settings push leaves behind.

    ``acquisition`` (a `_settings_to_config_json` document) replaces the
    acquisition part whole, or None keeps ``current``'s. The analysis
    defaults (`_ANALYSIS_KEYS`) carry over from ``current`` unless
    ``analysis`` sets them, so a later push that does not mention the
    window does not quietly drop it for tabs opened afterwards.

    Args:
        current (dict): the document served now.
        acquisition (dict or None): the new acquisition settings.
        analysis (dict): the analysis keys to set (`_analysis_config`).
    """
    if acquisition is None:
        doc = {k: v for k, v in current.items() if k not in _ANALYSIS_KEYS}
    else:
        doc = dict(acquisition)
    for key in _ANALYSIS_KEYS:
        if key in analysis:
            doc[key] = analysis[key]
        elif key in current:
            doc[key] = current[key]
    return doc


def _settings_summary(doc):
    """One-line description of a ``/config`` document, for the notebook.

    Reads the document rather than a MySettings, so it describes
    exactly what was sent (including a push that kept the previous
    acquisition settings). The trigger level is shown in volts when the
    capture is in volts (NI, or a soundcard with ``VmaxSC`` set — the
    rule `pydvma.serve._input_scale_fields` reports to the app),
    otherwise as a fraction of full scale, and an unset threshold is
    resolved the way the app and `pydvma.options.pretrig_level`
    resolve it.

    Args:
        doc (dict): the document, as `_merge_config` built it.
    """
    from . import options
    parts = []
    fs = doc.get('fs')
    if fs is not None:
        parts.append('%g Hz' % fs)
    channels = doc.get('channels')
    if channels is not None:
        parts.append('%d ch' % channels)
    stored = doc.get('stored_time')
    if stored is not None:
        parts.append('%g s' % stored)
    if 'pretrig_samples' in doc or 'fs' in doc:
        if doc.get('pretrig_samples') is None:
            parts.append('trigger off')
        else:
            probe = options.MySettings.__new__(options.MySettings)
            probe.device_driver = doc.get('device_driver')
            probe.VmaxNI = doc.get('VmaxNI', 5.0)
            probe.VmaxSC = doc.get('VmaxSC', 1.0)
            probe.pretrig_threshold = doc.get('pretrig_threshold')
            level = options.pretrig_level(probe)
            volts = (probe.device_driver == 'nidaq'
                     or abs(float(probe.VmaxSC or 1.0) - 1.0) > 1e-9)
            unit = ' V' if volts else ' × full scale'
            parts.append('trigger armed on ch %d at %g%s'
                         % (doc.get('pretrig_channel') or 0, level, unit))
    if 'analysis_window' in doc:
        parts.append('window %s' % doc['analysis_window'])
    if 'tf_averaging' in doc:
        parts.append('TF averaging %s' % doc['tf_averaging'])
    return ', '.join(parts)


async def _apply_on_loop(server, acquisition, analysis, default_driver,
                         answer_timeout):
    """Build the new document and push it, on the server's own loop.

    Reading the current ``/config`` and replacing it happen in one
    coroutine on the loop that serves ``/config``, so nothing can slip
    in between. Returns ``(doc, result)``, the document pushed and
    `pydvma.serve.BridgeServer.apply_settings`' result.
    """
    doc = _merge_config(server.settings_json, acquisition, analysis)
    result = await server.apply_settings(
        doc, default_driver=default_driver, answer_timeout=answer_timeout)
    return doc, result


def _shutdown(loop, thread):
    """Stop ``loop`` from another thread and join its ``thread``.

    Idempotent and safe on an already-finished thread: a dead thread is
    left alone, and a loop that closed between the liveness check and
    the call raises ``RuntimeError``, which is swallowed. Shared by
    `launch`'s failure path and `Session.close`.

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

    The body of `launch`'s daemon thread. Installs ``loop`` as
    this thread's event loop, schedules ``server.run()``, and polls
    every `_POLL_INTERVAL_S` until either the listener is up or
    the task has finished — setting ``ready`` in both cases, so a bind
    failure wakes `launch` immediately instead of stranding it
    until the startup timeout. On the way out it cancels the task,
    drains it (recording any real exception into ``failure`` for
    `launch` to chain), shuts down async generators, and closes
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

    Returned by `launch`; not constructed directly. Usable as a
    context manager, which closes the server on exit.

    Args:
        server (pydvma.serve.BridgeServer): the running server, whose
            `pydvma.serve.BridgeServer.journal` holds the
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

    @property
    def save_dir(self):
        """The app's working folder, where Save and Load open.

        Starts as `launch`'s ``save_dir`` (by default the notebook's
        folder) and follows the folder pill in the app, so after a save
        ``dvma.load_data(session.save_dir / name)`` finds the file.

        Returns:
            save_dir (pathlib.Path): the absolute folder path.
        """
        return self._server.save_folder.path

    @save_dir.setter
    def save_dir(self, path):
        """Set the working folder from the notebook (it must exist)."""
        self._server.save_folder.set_dir(path)

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
        `pydvma.journal.SessionJournal.set_doc` as
        ``expect_generation`` and be refused if anything changed in
        between. `data` is this without the bookkeeping.
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
        merged in by `_merge_dataset`. Nothing here is shared
        with the app or the engine — mutating what you pull changes
        nothing until you `push` it back, and the ids carried
        through the container round-trip are what make that push land
        in place.

        Still readable after `close`: pulling your data out of a
        session you have finished with is the point of the explicit
        handoff, and the journal outlives the server thread that fed
        it.

        Returns:
            dataset (DataSet): A new `DataSet` built from the journal on this
                access: the posted session document plus any captures
                logged since it was posted. Empty when the session has
                no document and no pending captures yet.
        """
        return self._snapshot()[0]

    def push(self, data):
        """Hand data to the session; connected apps offer to reload.

        Merges into the CURRENT session data (`data`) rather than
        replacing it, by `_merge_dataset`'s id rule — so pushing
        back something you pulled and edited updates that item in
        place, while genuinely new items append.

        The merge replaces a matched item WHOLE, so what you push is
        what is stored — including the app-side display state a pulled
        item carries invisibly (channel labels, per-set analysis
        settings: the manifest keys `pydvma.container` stashes as
        ``_container_extra`` rather than dropping). Pull → modify →
        push therefore preserves it; pushing a NEWLY built item in
        place of a stored one legitimately replaces that state with
        nothing, and the app re-seeds its defaults on reload.

        The read-merge-write cycle is guarded by the journal's
        generation counter, so nothing is lost to a race: if a capture
        lands, or the app's autosave posts, between the read and the
        write, the post is REFUSED and this retries from a fresh read
        (up to `PUSH_MAX_ATTEMPTS` times). Two concurrent pushes
        therefore serialise — one wins, the other re-merges on top of
        the winner's document — instead of one silently overwriting
        the other.

        Args:
            data (pydvma.datastructure.DataSet or a single data item):
                what to hand over. Anything that is not already a
                DataSet is wrapped in one, so a lone
                `pydvma.datastructure.TimeData` (or any other
                item ``DataSet.add_to_dataset`` accepts, or a
                homogeneous list of them) works directly.

        Raises:
            TypeError: ``data`` is neither a DataSet nor something
                ``DataSet.add_to_dataset`` recognises (which would
                otherwise post an unchanged document and look like
                success).
            RuntimeError: The session is closed, or the journal kept
                changing under every one of the `PUSH_MAX_ATTEMPTS`
                attempts.
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

    def apply_settings(self, settings=None, *, window=_UNSET,
                       tf_averaging=_UNSET):
        """Change the acquisition settings of the app that is already open.

        Every connected app tab applies ``settings`` to Setup and to the
        Acquire trigger exactly as it applies the ``launch`` settings at
        start-up, and shows a toast saying they came from the notebook.
        The served ``/config`` is replaced too, so a tab opened or
        reloaded later starts from these settings; with no tab open the
        call says so and the settings apply when one opens. Prints a
        one-line confirmation::

            logger settings: 3000 Hz, 2 ch, 6 s, trigger armed on ch 0 at 0.25 V (applied in 1 app tab)

        The settings replace the previous ones whole: a setting that is
        None CLEARS that setting in the app rather than leaving it.
        ``pretrig_samples=None`` (the MySettings default) disarms the
        trigger, so moving from hammer settings back to a noise capture
        needs no extra step, and ``pretrig_threshold=None`` (also the
        default) is 5 % of the input's full scale, as in the app.

        Nothing changes while a capture is in progress — logging, armed
        and waiting for its trigger, or a Nonlin run between its
        captures: the call raises and the app is left as it was. Let the
        capture finish, or press Stop, and run it again.

        A change that needs the live stream reopened (sample rate,
        channels, device, NI range) takes effect the way a Setup edit
        does: at the next capture, or when the live monitor is next
        started.

        Args:
            settings (pydvma.options.MySettings or None): the new
                acquisition settings. None keeps the current ones, for a
                change of ``window`` or ``tf_averaging`` alone.
            window (str or None): analysis window for both the Frequency
                and TF cards: one of `APP_WINDOWS`, or None for no window
                (pydvma's usual spelling). Applies to the captures taken
                from now on, and to loaded data that records no analysis
                settings (a file written from Python). Data already in
                the app keeps its own, and so does a file saved from the
                app, which records its settings and reopens exactly as
                saved. Omit to leave the app's choice (it starts at
                ``'hann'``).
            tf_averaging (str): TF averaging, applied like ``window``:
                ``'within'`` (frames within each capture, for noise),
                ``'across'`` (one average over the sets that are on
                ``'across'``, for repeated hammer hits; a set on another
                mode is never pulled in) or ``'none'``. Omit to leave the
                app's choice (it starts at ``'within'``).

        Raises:
            RuntimeError: The session is closed; a capture is in
                progress (nothing was changed); or a tab refused the
                change (the message gives its reason).
            ValueError: An unknown ``window`` or ``tf_averaging``.
        """
        with self._close_lock:
            if self._closed or not self._thread.is_alive():
                raise RuntimeError('session is closed')
        analysis = _analysis_config(window, tf_averaging)
        acquisition = (None if settings is None
                       else _settings_to_config_json(settings))
        driver = (None if settings is None
                  else getattr(settings, 'device_driver', None) or 'auto')
        from . import serve
        timeout = serve.APPLY_SETTINGS_ANSWER_TIMEOUT_S
        future = asyncio.run_coroutine_threadsafe(
            _apply_on_loop(self._server, acquisition, analysis, driver,
                           timeout), self._loop)
        doc, result = future.result(timeout=timeout + STARTUP_TIMEOUT_S)
        applied, refused, silent = (result['applied'], result['refused'],
                                    result['silent'])
        if result['busy']:
            # Seen by the server (its log is running) or, a moment earlier
            # or between a Nonlin run's captures, by the tab itself: worded
            # the same either way.
            refused = [_CAPTURE_BUSY]
        if refused and not applied:
            raise RuntimeError(
                '%s, so nothing was changed. Let it finish or press Stop, '
                'then run this again.' % '; '.join(sorted(set(refused))))
        if refused:
            raise RuntimeError(
                'applied in %d app tab%s, but %s in %d other%s, which kept '
                'its settings. Run this again when it has finished.'
                % (applied, 's' * (applied != 1),
                   '; '.join(sorted(set(refused))), len(refused),
                   's' * (len(refused) != 1)))
        summary = 'logger settings: ' + _settings_summary(doc)
        if result['tabs'] == 0:
            status = 'no app tab is open; they apply when one opens at %s' % self.url
        else:
            status = 'applied in %d app tab%s' % (applied, 's' * (applied != 1))
            if silent:
                status += ('; %d tab%s did not answer, reload %s'
                           % (silent, 's' * (silent != 1),
                              'them' if silent != 1 else 'it'))
        print('%s (%s)' % (summary, status))
        for note in result['notes']:
            print('  ' + note)

    def close(self):
        """Stop the server and its thread. Idempotent and thread-safe.

        A second call — from this thread or another — is a clean no-op
        rather than a second stop injected into a shutdown already in
        progress. Prints a WARNING if the thread has not finished
        within `SHUTDOWN_TIMEOUT_S`, in which case the port may
        still be bound; the thread is a daemon, so it cannot keep the
        interpreter alive either way.

        `data` keeps working afterwards (the journal is plain
        memory); `push` does not, since there is no longer an
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
           session_dir=None, recover=True, *, window=_UNSET,
           tf_averaging=_UNSET, save_dir=None):
    """Start a pydvma session and return its `Session` handle.

    Runs the same server as ``pydvma-serve`` — acquisition bridge,
    native ``/engine`` compute host, session journal, embedded UI — on
    a daemon thread with its own event loop inside the calling process,
    so this works unchanged from a plain script and from inside Jupyter
    (whose kernel already runs an asyncio loop of its own).

    The default ``port=0`` takes an ephemeral port, so several sessions
    can run side by side; read the one actually bound from
    `Session.url`. Printing that URL is how a session announces
    itself, matching ``pydvma-serve``'s startup line.

    Args:
        settings (pydvma.options.MySettings or None): acquisition
            settings the app opens with. Prefills Setup via ``/config``
            (see `_settings_to_config_json`) and supplies the
            default acquisition driver; ``None`` prefills nothing and
            leaves the driver at ``'auto'`` — a capture that names no
            device then records from the OS default input soundcard
            when there is one, else the mock generator (see
            `pydvma.serve.resolve_default_device`).
        open_browser (bool): open the app in a browser tab (default
            True). Pass False for a headless or scripted launch — the
            URL is still printed and on `Session.url`.
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
            `pydvma.serve.BridgeServer`; ``None`` means the
            system temp dir. Tests and advanced users point this at a
            directory they control.
        recover (bool): offer a previous run's spill file for recovery
            in the app (default True). Passed through to
            `pydvma.serve.BridgeServer`; False skips the
            startup scan entirely.
        window (str or None): analysis window the app gives new data
            sets on both the Frequency and TF cards, as in
            `Session.apply_settings`. Omit for the app's own default.
        tf_averaging (str): TF averaging mode for new data sets, as in
            `Session.apply_settings`. Omit for the app's own default.
        save_dir (str or pathlib.Path or None): the app's starting working
            folder, where Save and Load open. ``None`` (default) is the
            current working directory, which in Jupyter is the notebook's
            own folder, so saved files sit beside the notebook. The app's
            folder pill changes it; read it back with `Session.save_dir`.

    Returns:
        session (Session): The handle for the running server. Its `url` is the
            address actually bound. Change the settings later with
            `Session.apply_settings`.

    Raises:
        ValueError: An unknown ``window`` or ``tf_averaging``, or a
            ``save_dir`` that is not an existing folder.
        ImportError: The optional server dependencies are missing; the
            message names ``pip install pydvma[serve]``.
        RuntimeError: The server did not bind within
            `STARTUP_TIMEOUT_S`. It is chained to the underlying error
            when there was one (an ``OSError`` when an explicit ``port``
            is already taken).
    """
    analysis = _analysis_config(window, tf_averaging)
    try:
        import websockets                              # noqa: F401
    except ImportError as e:
        # Same message shape as pydvma/__init__.py's _LAZY_EXTRAS guard,
        # which does NOT fire for this module: importing pydvma.session
        # succeeds on a base install (nothing at module scope needs
        # websockets), so the miss surfaces only here, on the `serve`
        # import below, as a bare "No module named 'websockets'". The
        # retired dvma.Logger tombstone points people straight at
        # launch(), so this is a first-contact error and must name the
        # extra to install.
        raise ImportError(
            'pydvma.launch needs optional dependencies (websockets). '
            'Install them with: pip install pydvma[serve]. '
            'Original error: {}'.format(e)) from e
    from . import serve

    # No settings → 'auto': a capture that names no device records from
    # the OS default input soundcard when there is one (what the UI's
    # "Default" row is labelled with), else the mock generator. It was
    # 'mock' outright, which logged mock sines under a Focusrite label
    # (see serve.resolve_default_device).
    driver = getattr(settings, 'device_driver', None) or 'auto'
    resolved_ui_dir = serve._resolve_ui_dir(ui_dir)
    server = serve.BridgeServer(
        port=port, ui_dir=resolved_ui_dir,
        settings_json=_merge_config({}, _settings_to_config_json(settings),
                                    analysis),
        default_driver=driver, session_dir=session_dir, recover=recover,
        save_dir=save_dir)

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
    shown, default_note = driver, None
    if driver == 'auto':
        resolved_driver, _index, default_note = serve.resolve_default_device('auto')
        shown = '%s (auto)' % resolved_driver
    print('pydvma session listening on %s (ws at %s/ws, driver=%s)'
          % (url, url.rstrip('/'), shown))
    if default_note:
        print('  ' + default_note)
    print('  working folder (Save and Load): %s' % server.save_folder.path)
    if resolved_ui_dir is None:
        print('  no built UI found; serving the bridge + a help page. '
              'Build webui/dist or pass ui_dir=...')
    if open_browser:
        webbrowser.open(url)
    return Session(server, thread, loop, url)
