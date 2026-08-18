# -*- coding: utf-8 -*-
"""The serve process's session store (native-engine stage 3).

One :class:`SessionJournal` per :class:`pydvma.serve.BridgeServer`
holds the AUTHORITATIVE session document — the same ``.dvma`` bytes the
browser app autosaves — plus any captures that were born server-side
since the last document post. Closing the tab therefore loses nothing:
on reconnect the app asks via the ``journal_get`` op (:meth:`state` is
the server-side call it resolves to) and offers to restore.

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

Pending-captures budget: a document post is what NORMALLY bounds the
pending list, but nothing forces one to ever land — a client that
predates journal support (or simply never opens the app after logging)
would otherwise let :meth:`add_capture` grow the list, and the bytes it
holds, without limit for as long as the server runs. So the pending list
is ALSO capped at :data:`PENDING_CAPTURES_MAX_BYTES` total: every
``add_capture`` that pushes the running total over the cap evicts
OLDEST-first until back under it, or the list is empty — including the
entry just added, if a single capture alone exceeds the whole budget.
This only ever bites when the cap is actually exceeded — an ordinary
session, where the app's autosave posts a clearing document well
before pending captures could add up to hundreds of megabytes, never
triggers it.

Thread-safe (one lock around all state): writers arrive from the
asyncio loop's executor threads, the bridge's log worker thread and the
notebook kernel thread. Listeners are called OUTSIDE the lock, and a
raising listener never blocks the others. The one exception is the
``bytes(...)`` coercion of an incoming payload in :meth:`set_doc` /
:meth:`add_capture`: that copy runs BEFORE the lock is taken, so a large
capture's memcpy never blocks another thread's unrelated journal call
for its duration — only the (cheap) list/dict mutation itself happens
under the lock.

The spill file is best-effort crash insurance only — an ordinary
``.dvma`` the user can open by hand if the serve process dies. On the
NEXT serve start it is offered for recovery in the app
(:meth:`adopt_recovered`); it is never silently auto-loaded. It mirrors
the DOCUMENT only, never pending captures — a crash artifact reflects
the last posted document, and anything captured after that is not in
it. Those captures are covered once the app's next autosave lands
(within its debounce window, currently 2 s); a crash on a fresh server
before any autosave has ever landed leaves no spill file at all.
"""
import os
import tempfile
import threading

_BYTES_TYPES = (bytes, bytearray, memoryview)

#: Total-bytes ceiling on the pending-captures list — see the module
#: docstring's "Pending-captures budget" paragraph. 256 MiB comfortably
#: covers a real lab session's captures between autosaves while still
#: bounding the worst case (a client that never posts a document at
#: all) to a fixed, modest amount of server memory.
PENDING_CAPTURES_MAX_BYTES = 256 * 1024 * 1024


def _check_bytes(value, param_name):
    """Raise ``TypeError`` unless ``value`` is bytes-like.

    Guards against a stray ``int`` (or other non-bytes payload) that
    would otherwise silently become NUL bytes via ``bytes(n)`` instead
    of raising.
    """
    if not isinstance(value, _BYTES_TYPES):
        raise TypeError(
            '{} must be bytes, bytearray, or memoryview, not {}'.format(
                param_name, type(value).__name__))


def _same_path(a, b):
    """Whether two spill-file identifiers (``str`` or ``pathlib.Path``,
    either may be ``None``) name the same file.

    Both sides are normalised through ``os.path.abspath`` on their
    ``str`` form before comparing, so a ``str`` spill path and a
    ``pathlib.Path`` recovered path naming the same file compare equal
    even though the raw objects would not.
    """
    if a is None or b is None:
        return a is b
    return os.path.abspath(str(a)) == os.path.abspath(str(b))


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
        self._spill_lock = threading.Lock()
        self._doc = None
        self._captures = []
        self._listeners = []
        self._spill_path = spill_path
        self._recovered = None
        self._recovered_path = None

    def set_doc(self, doc_bytes, notify=False):
        """Replace the session document (and clear pending captures).

        Args:
            doc_bytes (bytes, bytearray, or memoryview): the full
                session document (the same bytes written to a
                ``.dvma`` file).
            notify (bool): also call every registered listener after
                the replace. Used by
                :meth:`pydvma.session.Session.push` so connected apps
                reload; the app's own autosave posts use the default
                ``False`` (silent — the app already has what it just
                posted).
        """
        _check_bytes(doc_bytes, 'doc_bytes')
        # Coerce BEFORE taking the lock: a whole session document can be
        # tens of MB, and copying it is the expensive part of this call —
        # doing that copy while holding the lock would stall every other
        # thread's unrelated add_capture/state/etc. for its duration.
        doc = bytes(doc_bytes)
        with self._lock:
            self._doc = doc
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
        next document post (see the module docstring's contract).

        This does NOT touch the spill file — the spill mirrors only
        the posted document (see the module docstring), so a capture
        registered here is absent from the crash artifact until the
        app's next autosave lands.

        If appending pushes the pending list's total size over
        :data:`PENDING_CAPTURES_MAX_BYTES`, the OLDEST pending entries
        are evicted (silently — there is no error, no truncation
        signal, just fewer captures on the next :meth:`state`) until
        the total is back under the cap or the list is empty. Eviction
        is strictly oldest-first with no special case for the entry
        just appended: a single capture that alone exceeds the whole
        budget is evicted too, leaving the list empty rather than
        holding one capture over cap. See the module docstring's
        "Pending-captures budget" paragraph — this only matters when
        nothing ever posts a clearing document.

        Args:
            dvma_bytes (bytes, bytearray, or memoryview): one
                capture's full ``.dvma`` bytes.
        """
        _check_bytes(dvma_bytes, 'dvma_bytes')
        # Coerce BEFORE the lock -- see set_doc's matching comment.
        data = bytes(dvma_bytes)
        with self._lock:
            self._captures.append(data)
            total = sum(len(c) for c in self._captures)
            while total > PENDING_CAPTURES_MAX_BYTES and self._captures:
                total -= len(self._captures.pop(0))

    def state(self):
        """Current ``(doc_bytes_or_None, [capture_bytes, ...])``.

        The list is a copy — mutating it never touches the journal.
        The document is returned by reference, but ``bytes`` is
        immutable so that is equivalent to a copy for callers.
        """
        with self._lock:
            return self._doc, list(self._captures)

    def add_listener(self, cb):
        """Register a zero-arg callable invoked on ``notify`` updates.

        Returns an unsubscribe callable. Listener exceptions are
        swallowed (one broken listener must not silence the rest). An
        update already in flight when ``unsubscribe()`` returns may
        still call ``cb`` once more — :meth:`set_doc` snapshots the
        listener list before releasing the lock, so a race between an
        in-progress notify and a concurrent unsubscribe is possible;
        consumers must tolerate one extra call.

        Args:
            cb (callable): zero-argument callable to invoke on every
                ``notify=True`` update, until unsubscribed.
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
        ``BridgeServer`` only knows its real port after binding.

        Args:
            path (pathlib.Path or str or None): file to mirror the
                current document into on every update, or ``None`` to
                disable spilling.
        """
        with self._lock:
            self._spill_path = path

    @property
    def spill_path(self):
        """Where the document is mirrored, or None (read-only)."""
        with self._lock:
            return self._spill_path

    def adopt_recovered(self, path):
        """Read a PREVIOUS run's spill file into memory as a recovery
        offer. Reading now — not at offer time — makes a later
        overwrite of the same path harmless. A missing or unreadable
        file is a no-op, as is an empty one.

        Args:
            path (pathlib.Path or str): the previous run's spill file
                to read.
        """
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
        Dismiss).

        Skips the delete when the recovered file IS the current spill
        target — a same-port restart adopts what is now its own live
        spill file, and deleting it would remove the live mirror, not
        just the stale offer. The comparison is normalised through
        ``os.path.abspath`` on both sides so a ``str`` spill path and a
        ``pathlib.Path`` recovered path (or vice versa) still compare
        equal when they name the same file. Best-effort on the delete;
        idempotent.
        """
        with self._lock:
            path = self._recovered_path
            is_live_spill = (path is not None
                              and _same_path(path, self._spill_path))
            self._recovered = None
            self._recovered_path = None
        if path is not None and not is_live_spill:
            try:
                os.remove(path)
            except OSError:
                pass

    def _spill(self):
        """Mirror the current doc to ``spill_path``, atomically.

        Serialised against concurrent calls via ``_spill_lock`` (held
        for the whole body) so overlapping spills can never interleave
        their writes. The write itself goes to a temporary file in the
        same directory, then ``os.replace``s over ``spill_path`` — the
        same tempfile-then-rename idiom as
        :func:`pydvma.container.save` — so a crash mid-write can never
        truncate or tear the previous good copy. Best-effort: any
        ``OSError`` (including the temp file's own creation, e.g. a
        missing directory) is swallowed after cleaning up any partial
        temp file.
        """
        with self._spill_lock:
            with self._lock:
                doc = self._doc
                path = self._spill_path
            if path is None or doc is None:
                return
            path = str(path)
            try:
                tmp = tempfile.NamedTemporaryFile(
                    delete=False, suffix='.dvma.tmp',
                    dir=os.path.dirname(os.path.abspath(path)))
            except OSError:
                return
            try:
                tmp.write(doc)
                tmp.close()
                os.replace(tmp.name, path)
            except OSError:
                tmp.close()
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
