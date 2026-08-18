# -*- coding: utf-8 -*-
"""The serve process's session store (native-engine stage 3).

One :class:`SessionJournal` per :class:`pydvma.serve.BridgeServer`
holds the AUTHORITATIVE session document — the same ``.dvma`` bytes the
browser app autosaves — plus any captures that were born server-side
since the last document post. Closing the tab therefore loses nothing:
on reconnect the app asks for :meth:`state` and offers to restore.

Writers:

* the app's debounced autosave, arriving as a ``journal_set`` op on the
  ``/engine`` socket (:func:`pydvma.engine_host.handle_connection`);
* the serve log path, registering each capture's ``.dvma`` bytes at
  birth (:meth:`add_capture`) — belt-and-braces for a tab that closes
  inside the app's 2 s autosave debounce window;
* :meth:`pydvma.session.Session.push` from a notebook kernel
  (``notify=True`` so connected apps reload).

The clears-pending contract: a document post CLEARS the pending capture
list, because the app serialises its whole dataset at post time — any
capture it had already received is inside that document. A capture
landing after the post stays pending until the next one.

Thread-safe (one lock around all state): writers arrive from the
asyncio loop's executor threads, the bridge's log worker thread and the
notebook kernel thread. Listeners are called OUTSIDE the lock, and a
raising listener never blocks the others.

The spill file is best-effort crash insurance only — an ordinary
``.dvma`` the user can open by hand if the serve process dies. On the
NEXT serve start it is offered for recovery in the app
(:meth:`adopt_recovered`); it is never silently auto-loaded.
"""
import os
import threading


class SessionJournal(object):
    """In-memory session document + pending captures + listeners.

    Args:
        spill_path (pathlib.Path or str or None): file to mirror the
            current document into on every update (best-effort; errors
            are swallowed). ``None`` disables spilling; it can be set
            later with :meth:`set_spill_path` (a server on an
            ephemeral port only knows its identity after binding).
    """

    def __init__(self, spill_path=None):
        self._lock = threading.Lock()
        self._doc = None
        self._captures = []
        self._listeners = []
        self._spill_path = spill_path
        self._recovered = None
        self._recovered_path = None

    def set_doc(self, doc_bytes, notify=False):
        """Replace the session document (and clear pending captures).

        ``notify=True`` additionally calls every registered listener —
        used by :meth:`pydvma.session.Session.push` so connected apps
        reload; the app's own autosave posts use the default silent
        form (the app already has what it posted).
        """
        with self._lock:
            self._doc = bytes(doc_bytes)
            self._captures = []
            listeners = list(self._listeners) if notify else []
        self._spill()
        for cb in listeners:
            try:
                cb()
            except Exception:
                pass

    def add_capture(self, dvma_bytes):
        """Register one capture's ``.dvma`` bytes, pending until the
        next document post (see the module docstring's contract)."""
        with self._lock:
            self._captures.append(bytes(dvma_bytes))
        self._spill()

    def state(self):
        """Current ``(doc_bytes_or_None, [capture_bytes, ...])``.

        Returns copies — mutating the returned list never touches the
        journal.
        """
        with self._lock:
            return self._doc, list(self._captures)

    def add_listener(self, cb):
        """Register a zero-arg callable invoked on ``notify`` updates.

        Returns an unsubscribe callable. Listener exceptions are
        swallowed (one broken listener must not silence the rest).
        """
        with self._lock:
            self._listeners.append(cb)

        def unsubscribe():
            with self._lock:
                try:
                    self._listeners.remove(cb)
                except ValueError:
                    pass
        return unsubscribe

    def set_spill_path(self, path):
        """Set (or move) the spill target after construction —
        ``BridgeServer`` only knows its real port after binding."""
        with self._lock:
            self._spill_path = path

    @property
    def spill_path(self):
        """Where the document is mirrored, or None (read-only)."""
        return self._spill_path

    def adopt_recovered(self, path):
        """Read a PREVIOUS run's spill file into memory as a recovery
        offer. Reading now — not at offer time — makes a later
        overwrite of the same path harmless. A missing or unreadable
        file is a no-op, as is an empty one."""
        try:
            with open(path, 'rb') as fh:
                data = fh.read()
        except OSError:
            return
        if not data:
            return
        with self._lock:
            self._recovered = data
            self._recovered_path = path

    def recovered(self):
        """The adopted previous-run document bytes, or None."""
        with self._lock:
            return self._recovered

    def discard_recovered(self):
        """Drop the recovery offer and delete its file (the app's
        Dismiss). Best-effort on the delete; idempotent."""
        with self._lock:
            path = self._recovered_path
            self._recovered = None
            self._recovered_path = None
        if path is not None:
            try:
                os.remove(path)
            except OSError:
                pass

    def _spill(self):
        """Mirror the current doc to ``spill_path``, best-effort."""
        with self._lock:
            doc = self._doc
            path = self._spill_path
        if path is None or doc is None:
            return
        try:
            with open(path, 'wb') as fh:
                fh.write(doc)
        except OSError:
            pass
