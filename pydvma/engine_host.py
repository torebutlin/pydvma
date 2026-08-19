# -*- coding: utf-8 -*-
"""Native host for the engine ops: /engine websocket + worker subprocess.

The webui's compute requests (``pydvma.engine`` ops) are answered here in
ordinary CPython when the app is served by ``pydvma-serve`` — same ops,
same results as the in-browser pyodide worker, without the wasm32 memory
ceiling. See dev/plans/2026-08-17-native-engine-design.md.

Wire format — THIS DOCSTRING, together with the protocol block in
``dev/plans/2026-08-17-native-engine-plan.md``, is the normative spec for
BOTH this Python codec and the JS mirror
(``webui/src/lib/worker/frames.ts``, Task 6). Implement either side from
this text alone:

- One binary websocket frame per request and per reply:
  ``[u32 LE header_len][header JSON utf-8][blobs...]``.
- ``header_len`` counts BYTES of the encoded JSON — never characters,
  never elements.
- Any array/bytes value anywhere inside the JSON tree is lifted out into
  a trailing blob and replaced in place by a placeholder
  ``{"__bin__": k, "kind": "f8"|"bytes", "len": n}``. The lift/restore
  walk is RECURSIVE through dicts/objects and lists/arrays (payloads
  like ``calc_fit``'s ``sets`` nest arrays inside lists of dicts).
- ``k`` is a contiguous 0-based blob index, assigned in the order each
  value is lifted (0, 1, 2, ...). Blobs are laid end-to-end in the frame
  tail in ASCENDING INDEX order. A decoder reconstructs every blob's
  start offset purely from the declared ``len`` values walked in index
  order — NEVER from wherever the placeholder happens to sit in the JSON
  tree — so key/array reordering in a payload can never desync the
  offsets.
- ``len`` is always the blob's size in BYTES, not elements. For
  ``"f8"`` it is therefore always a multiple of 8. The blob region is
  EXACTLY the sum of every placeholder's declared ``len`` — no padding,
  no trailing bytes; a frame where that sum disagrees with the bytes
  actually present is rejected, whichever direction the mismatch runs.
- ``"f8"`` reconstructs as flat little-endian float64 (JS
  ``Float64Array`` / numpy ``<f8``). Arrays cross FLAT: shape lives in
  the engine ops' own ``{shape, data, complex}`` envelope (see
  ``pydvma.engine._arr``), never in the placeholder itself.
- ``"bytes"`` reconstructs as raw bytes (JS ``Uint8Array`` / Python
  ``bytes``).
- ``__bin__`` is a RESERVED key: no op payload may legitimately contain
  a dict with that key, since the codec would mistake it for a
  placeholder.
- Non-finite scalar floats (``NaN`` / ``Infinity`` / ``-Infinity``) are
  not valid JSON, so a bare scalar crosses the header as ``null``
  (Python ``None``) instead — mirroring the reverse hop, where JS
  ``JSON.stringify(NaN)`` already produces ``null``. ``pydvma.engine``'s
  ``_opt_float`` already treats an incoming ``None``/``null`` as
  "unset", so this costs existing op-payload consumers nothing. Array
  VALUES are unaffected: an ``"f8"`` blob is raw IEEE-754 bytes that
  never passes through ``json.dumps``, so it carries NaN/Inf natively.
- Progress frames and the connect greeting are small TEXT frames, not
  this binary format.
- The header JSON's TEXT need not match byte-for-byte between the
  Python and JS implementations (e.g. Python's ``json.dumps`` escapes
  non-ASCII, JS's ``JSON.stringify`` doesn't) — only the FRAMING and
  PLACEHOLDER SEMANTICS above are normative. ``header_len`` is always
  the byte length of whatever UTF-8 text ``header`` actually encodes to.
"""
import asyncio
import functools
import json
import math
import multiprocessing as _mp
import queue as _queue
import signal
import struct
import threading
import time
import traceback

import numpy as np

#: /engine protocol version, advertised in the greeting and capabilities.
ENGINE_PROTOCOL_VERSION = 1

_HDR = struct.Struct('<I')


def encode_frame(header):
    """Encode ``header`` into one binary frame; the inverse of ``decode_frame``.

    ``header`` is a JSON-able tree that may also hold float64 ndarrays
    and bytes-like values anywhere inside it — see the module docstring
    for the full wire format. Arrays must be float64 (callers hold flat
    ``<f8`` per the engine-op convention); any other ndarray dtype raises
    ``TypeError`` rather than silently converting. Non-finite scalar
    floats (``NaN``/``±Infinity``) are sanitised to ``None`` before
    encoding, and ``json.dumps`` itself runs with ``allow_nan=False`` so
    any path this walk misses fails loudly instead of emitting invalid
    JSON tokens a JS ``JSON.parse`` would reject.

    Returns a ``bytearray`` (bytes-like: ``websockets`` accepts it
    directly, and it compares equal to ``bytes`` by value) rather than
    ``bytes`` — the frame is assembled with exactly one allocation and
    each blob is blitted straight in via a raw memoryview, so an array
    payload is never materialised as an intermediate ``bytes`` copy on
    its way into the frame (this host exists to keep big captures off
    the wasm32 memory ceiling, so per-frame copies matter).
    """
    blobs = []

    def lift(v):
        if isinstance(v, np.ndarray):
            if v.dtype != np.dtype('<f8'):
                raise TypeError('engine frames carry float64 arrays only, '
                                'got dtype %s' % v.dtype)
            a = np.ascontiguousarray(v)
            blobs.append(a)
            return {'__bin__': len(blobs) - 1, 'kind': 'f8', 'len': a.nbytes}
        if isinstance(v, (bytes, bytearray, memoryview)):
            b = bytes(v)
            blobs.append(b)
            return {'__bin__': len(blobs) - 1, 'kind': 'bytes', 'len': len(b)}
        if isinstance(v, dict):
            return {k: lift(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [lift(x) for x in v]
        if isinstance(v, float) and not math.isfinite(v):
            return None
        return v

    head = json.dumps(lift(header), allow_nan=False).encode('utf-8')

    def _nbytes(b):
        return b.nbytes if isinstance(b, np.ndarray) else len(b)

    blob_total = sum(_nbytes(b) for b in blobs)
    out = bytearray(4 + len(head) + blob_total)
    _HDR.pack_into(out, 0, len(head))
    out[4:4 + len(head)] = head
    pos = 4 + len(head)
    for b in blobs:
        n = _nbytes(b)
        out[pos:pos + n] = memoryview(b).cast('B') if isinstance(b, np.ndarray) else b
        pos += n
    return out


def decode_frame(data):
    """Decode one binary frame back into the header tree; the inverse of ``encode_frame``.

    Placeholders are replaced by float64 ndarrays / bytes reconstructed
    from the frame's blob tail (one copy per f8 array via
    ``np.frombuffer(...).copy()``, not a slice-then-frombuffer double
    copy). Raises ``ValueError`` if the blob region's declared total size
    disagrees with the bytes actually present (truncated OR corrupt with
    trailing bytes — the format has no padding, so this must be an exact
    fit), if an ``"f8"`` placeholder's ``len`` isn't a whole number of
    float64 elements, or if a placeholder names an unrecognised ``kind``.
    """
    data = bytes(data)
    (n,) = _HDR.unpack_from(data, 0)
    header = json.loads(data[4:4 + n].decode('utf-8'))
    blob_base = 4 + n

    # Blob k starts after the lengths of blobs 0..k-1; collect lengths by
    # walking once for placeholders, then lay out offsets in ASCENDING
    # INDEX order (never JSON-tree traversal order -- see module docstring).
    offsets = {}

    def index(v):
        if isinstance(v, dict):
            if '__bin__' in v:
                offsets[v['__bin__']] = v['len']
            else:
                for x in v.values():
                    index(x)
        elif isinstance(v, list):
            for x in v:
                index(x)

    index(header)
    starts = {}
    pos = blob_base
    for k in sorted(offsets):
        starts[k] = pos
        pos += offsets[k]

    if pos != len(data):
        raise ValueError('engine frame truncated or corrupt: blob region is '
                         '%d bytes, header declares %d' %
                         (len(data) - blob_base, pos - blob_base))

    def restore(v):
        if isinstance(v, dict):
            if '__bin__' in v:
                k, ln, kind = v['__bin__'], v['len'], v['kind']
                if kind == 'f8':
                    if ln % 8:
                        raise ValueError(
                            'f8 blob len must be a multiple of 8, got %d' % ln)
                    return np.frombuffer(data, dtype='<f8', count=ln // 8,
                                         offset=starts[k]).copy()
                if kind == 'bytes':
                    return bytes(data[starts[k]:starts[k] + ln])
                raise ValueError('unknown blob kind %r' % kind)
            return {k: restore(x) for k, x in v.items()}
        if isinstance(v, list):
            return [restore(x) for x in v]
        return v

    return restore(header)


# --- worker subprocess ------------------------------------------------------
#
# One persistent spawn-context subprocess executes ops SERIALLY — the same
# semantics as the single-threaded pyodide worker. Spawn (not fork): it is
# the only context on Windows and the safe one under macOS CoreAudio. The
# child imports numpy/scipy/pydvma once and stays warm; a hard stop
# terminates just the child and the next request respawns it.
#
# DECISION (recorded, no code change intended): every result crosses the
# multiprocessing.Queue between child and parent, which pickles it in the
# child and unpickles it in the parent -- roughly two extra full copies of
# each returned array on top of whatever ``fn(**kwargs)`` itself allocated.
# ``encode_frame``'s single-allocation guarantee (module docstring, top of
# this file) is about the WEBSOCKET FRAME only and says nothing about this
# hop. A shared-memory / out-of-band buffer (e.g. ``multiprocessing.shared_
# memory`` or ``Queue`` subclassed to hand back a raw buffer) is the
# recorded future option if this copy ever shows up as a bottleneck; not
# worth the complexity until then.


class EngineCancelled(Exception):
    """Raised inside the child when the cancel event is set mid-op."""


def _configure_child_limits():
    """Raise per-process resource ceilings that default to a wasm32-safe
    value in shared ``pydvma`` code, called once as the FIRST thing
    ``_worker_main`` does -- in the CHILD process only, never the parent
    (which never allocates a CWT image itself).

    ``analysis.CWT_MAX_IMAGE_BYTES`` defaults to 768 MiB specifically to
    protect the pyodide/wasm32 worker's 32-bit address space, where an
    over-size allocation would otherwise hit numpy's bare "array is too
    big" past the ``2**31-1`` byte ceiling (see that constant's own
    docstring in ``analysis.py``). Applying that wasm32-era default here
    too would leave the native engine's headline benefit -- no memory wall
    -- UNREALISED for CWT specifically, the one op shaped by that ceiling;
    every other op already benefits just by running outside wasm.

    This is an ordinary 64-bit CPython child process (``sys.maxsize >
    2**32`` on every desktop/server platform pydvma-serve targets), so the
    ceiling is raised to 8 GiB -- still a genuine CAP, not unlimited (a
    runaway-allocation guard, exercising the constant's own "a desktop user
    with plenty of RAM can raise it deliberately" affordance), chosen to
    clear any realistic lab capture on a 16 GB machine while staying
    comfortably under it. A 32-bit interpreter (not a real deployment
    target) is left at the wasm32-safe default rather than risking an
    8 GiB request it cannot actually address.
    """
    import sys
    from pydvma import analysis
    if sys.maxsize > 2 ** 32:
        analysis.CWT_MAX_IMAGE_BYTES = 8 * 1024 ** 3


def _worker_main(req_q, res_q, cancel_ev):
    """Child entry: answer ``(id, op, kwargs)`` until ``None`` arrives.

    Emits ``('progress', id, done, total)`` frames via the installed
    engine progress hook (which doubles as the cooperative cancel
    checkpoint) and exactly one ``('done', id, ok, result_or_msg)`` per
    request.
    """
    _configure_child_limits()

    # Ignore Ctrl-C here: the PARENT owns SIGINT (it decides whether to
    # cancel(), kill(), or let a request run to completion). Without this,
    # an interactive ``pydvma-serve`` session's ^C hits every spawned child
    # too, printing a KeyboardInterrupt traceback per worker for no benefit
    # -- the parent's own shutdown path already tears children down.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    from pydvma import engine
    current = {'id': None}

    def hook(done, total):
        if cancel_ev.is_set():
            raise EngineCancelled()
        res_q.put(('progress', current['id'], int(done), int(total)))

    engine.set_progress_hook(hook)
    while True:
        item = req_q.get()
        if item is None:
            return
        rid, op, kwargs = item
        current['id'] = rid
        cancel_ev.clear()
        try:
            fn = getattr(engine, op, None)
            if fn is None or op.startswith('_') or not callable(fn):
                raise ValueError('unknown op: %s' % op)
            # DECISION (recorded, no code change intended): if this result
            # is unpicklable or exceeds the platform pipe limit (Windows:
            # ~2 GiB), the failure happens inside multiprocessing.Queue's
            # background FEEDER THREAD, not in this call frame -- a
            # child-side try/except around ``put()`` cannot catch it, the
            # item is silently dropped, and the parent (a live, responsive
            # child) polls forever with no 'done' ever arriving.
            #
            # No shipped op returns anything unpicklable. The SIZE half of
            # the premise changed when ``calc_sono_full`` landed (the
            # derived-data save round): it is the first op whose result is
            # user-sized rather than display-sized -- a whole complex
            # sonogram cube, which at 8 GiB of headroom could in principle
            # exceed the Windows pipe limit. What keeps this unreachable is
            # that op's own SIZE PREFLIGHT: it predicts the cube's bytes
            # and refuses above ``analysis.CWT_MAX_IMAGE_BYTES`` before
            # transforming, so nothing over that ceiling is ever built, let
            # alone put on this queue. Should a future op grow past it
            # without such a guard, fix it with a
            # ``multiprocessing.queues.Queue`` subclass that surfaces its
            # feeder thread's exception (the ``_SafeQueue`` pattern used by
            # e.g. loky/joblib) rather than relying on per-op discipline.
            res_q.put(('done', rid, True, fn(**kwargs)))
        except EngineCancelled:
            res_q.put(('done', rid, False, 'cancelled'))
        except Exception as e:
            # Full traceback to the serve terminal for whoever is running
            # pydvma-serve; the wire reply itself stays the one-line
            # summary (below) -- the browser has no use for a Python stack.
            traceback.print_exc()
            res_q.put(('done', rid, False, '%s: %s' % (type(e).__name__, e)))


class EngineWorker:
    """Owner of one engine subprocess; blocking request/response API.

    Thread-safety: ``request()`` holds a private lock for its ENTIRE
    duration, turning "one request at a time" from a documented convention
    into a checked invariant -- a second thread calling ``request()``
    concurrently simply blocks until the first one's ``done`` (or died/
    cancelled) reply comes back. ``cancel()`` and ``kill()`` stay LOCK-FREE
    on purpose: they are the cross-thread controls a caller uses to
    interrupt the request that is *currently* blocked inside another
    thread's ``request()`` call, so taking the same lock there would
    deadlock against the very call they exist to interrupt.
    """

    def __init__(self):
        self._ctx = _mp.get_context('spawn')
        self._proc = None
        self._lock = threading.Lock()
        self._closed = False
        self._spawn()

    def _spawn(self):
        # Fresh queues/event every spawn: any ('progress', old_id, ...) or
        # ('done', old_id, ...) items still sitting in a PRIOR worker's
        # result queue die with that queue object rather than leaking into
        # the new worker's request/response cycle -- self._res always
        # refers to the queue the CURRENTLY-live child was handed.
        self._req = self._ctx.Queue()
        self._res = self._ctx.Queue()
        self._cancel = self._ctx.Event()
        self._proc = self._ctx.Process(
            target=_worker_main, args=(self._req, self._res, self._cancel),
            daemon=True)
        self._proc.start()

    def request(self, rid, op, kwargs, on_progress=None):
        """Run one op; returns ``('done', rid, ok, result_or_errmsg)``.

        Blocks until the op's ``done`` reply arrives (or the worker is
        cancelled/killed from another thread), invoking
        ``on_progress(done, total)`` for each progress frame in between.
        Holds ``self._lock`` for the whole call -- see the class
        docstring for why ``cancel()``/``kill()`` stay reachable from
        another thread regardless.
        """
        with self._lock:
            if self._closed:
                return ('done', rid, False, 'engine worker closed')
            if self._proc is None or not self._proc.is_alive():
                self._spawn()
            self._req.put((rid, op, kwargs))
            while True:
                try:
                    item = self._res.get(timeout=1.0)
                except (_queue.Empty, EOFError, OSError):
                    # Empty: an ordinary poll timeout. EOFError/OSError: a
                    # kill() racing this poll from another thread can
                    # terminate() the child mid write, truncating the pipe
                    # this queue reads from -- route that to the same
                    # died-check below instead of letting it escape as an
                    # unhandled exception.
                    #
                    # Local ref: kill() may rebind self._proc to None from
                    # another thread at any point from here on, so capture
                    # it once and use only this snapshot for the rest of
                    # the except block.
                    proc = self._proc
                    if proc is None or not proc.is_alive():
                        # The child may have managed to put its result
                        # before dying (e.g. it finished normally and was
                        # then reaped) -- drain once more before declaring
                        # it lost.
                        try:
                            item = self._res.get_nowait()
                        except (_queue.Empty, EOFError, OSError):
                            exitcode = 'unknown' if proc is None else proc.exitcode
                            msg = 'engine worker died (exit %s)' % (exitcode,)
                            if exitcode in (-9, -15):
                                msg += ' — killed by the OS (out of memory?)'
                            return ('done', rid, False, msg)
                    else:
                        continue
                if item[0] == 'progress':
                    if on_progress is not None and item[1] == rid:
                        on_progress(item[2], item[3])
                    continue
                return item

    def cancel(self):
        """Ask the running op to stop at its next progress checkpoint.

        Sets the cancel event; the CHILD observes it the next time the
        engine progress hook fires (one call per wavelet scale on the CWT
        path -- see ``_worker_main.hook``) and raises ``EngineCancelled``,
        which turns into a ``('done', rid, False, 'cancelled')`` reply. An
        op with no progress checkpoints (anything that never calls the
        hook) cannot observe a cancel this way at all -- the CALLER is
        responsible for escalating to ``kill()`` if a bounded response
        time is required. The event is cleared again at the top of the
        next request (``_worker_main``'s loop), so a ``cancel()`` that
        arrives before any request has started running -- or after the
        current one has already finished -- is deliberately LOST rather
        than pre-arming the next unrelated request.
        """
        self._cancel.set()

    def kill(self):
        """Hard stop: terminate the child (next request respawns)."""
        if self._proc is not None and self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout=2.0)
        self._proc = None

    def close(self):
        """Graceful shutdown for tests/teardown.

        Lock-free like ``cancel()``/``kill()`` so it can tear the worker
        down even while another thread is blocked inside ``request()``.
        Sets ``self._closed`` first so any request that hasn't yet taken
        the lock (or a future one) gets a clean 'engine worker closed'
        reply instead of racing a queue this call is about to kill.
        """
        self._closed = True
        proc = self._proc
        try:
            if proc is not None and proc.is_alive():
                self._req.put(None)
                proc.join(timeout=2.0)
        finally:
            self.kill()


# --- /engine websocket handler ---------------------------------------------

#: Minimum seconds between forwarded progress frames (terminal always sent) —
#: parity with the pyodide worker's ~10 Hz throttle (progress.ts).
PROGRESS_MIN_INTERVAL_S = 0.1


async def handle_connection(websocket, journal=None):
    """Serve one /engine connection: greeting, then serial op frames.

    ``journal`` is the serve process's :class:`pydvma.journal.
    SessionJournal` -- when given, ``journal_set``/``journal_get``/
    ``journal_discard_recovered`` op frames are answered INLINE, right
    here in the host, and never reach the calc worker subprocess (which
    only knows compute ops). ``None`` (a bare harness serving this
    handler directly) declines journal ops with an ``ok: False`` error
    reply instead of raising or forwarding it. A journal update
    posted with ``notify=True``
    (:meth:`pydvma.journal.SessionJournal.set_doc`) is forwarded to this
    connection's client as a ``{"type": "journal", "event": "updated"}``
    text frame for as long as the connection lives. Whether a journal is
    present at all is advertised in the greeting as ``journal`` (see the
    ``engine_ready`` send below), which is how the app decides whether to
    use the journal ops without ever opening the ``/ws`` bridge socket.

    One :class:`EngineWorker` per connection (one app tab is the expected
    client). Closing the socket is the client's Stop -- and, crucially,
    it INTERRUPTS an op that is still running: each op is raced against
    ``websocket.wait_closed()`` (``websockets`` does not cancel a running
    handler task on peer close by itself, so without this the child would
    keep computing -- potentially minutes of CPU and gigabytes of RAM --
    until it finished on its own, a fresh connection's re-init would spin
    up a second worker alongside the abandoned one, and the orphaned
    executor thread would sit on the thread pool for as long as the op
    took). Losing that race cancels cooperatively then terminates the
    child, so the connection's resources are gone promptly, not at the
    op's natural end.

    A frame that fails to decode gets a text ``{"type":"error"}`` reply
    (there is no id to correlate) and the connection lives on — one bad
    frame must not kill a session.

    Every outbound ``send`` here can race the client closing the socket
    (the canonical case: Stop, or a tab close, during a long CWT calc) --
    ``websockets.exceptions.ConnectionClosed`` from any of them is treated
    as that clean Stop, not an error: the ``finally`` below already
    cancels + kills the worker, so there is nothing left to do but return.
    Without this, the reply send after an op finishes on an already-closed
    socket propagates out of this coroutine and ``websockets`` logs a full
    "connection handler failed" traceback server-side for what is, from
    the client's point of view, entirely routine.
    """
    # Imported here rather than at module top: this module must stay
    # importable with no ``websockets`` package present at all -- the
    # frame codec / worker classes (and their tests) have no such
    # dependency, and serve.py's capabilities builder imports this module
    # purely for ENGINE_PROTOCOL_VERSION. Only handle_connection, which is
    # never reached unless a real websockets server is already running,
    # needs the exception type.
    from websockets.exceptions import ConnectionClosed

    from pydvma import datastructure
    worker = EngineWorker()
    loop = asyncio.get_running_loop()
    # Hoisted out of the try (rather than set as its first statement) so a
    # future early raise there can never leave the finally's read unbound.
    unsubscribe_journal = None
    try:
        try:
            await websocket.send(json.dumps({
                'type': 'engine_ready',
                'v': ENGINE_PROTOCOL_VERSION,
                'pydvma': datastructure.VERSION,
                # Session-journal capability, for the client that has
                # already connected -- the twin of the same flag in
                # serve.build_capabilities' ``engine`` block, which is for
                # a client deciding whether to connect at all (and which
                # reaches the app only over /ws, a socket the analysis-only
                # page never opens). Capability-gated, NOT version-gated:
                # a serve predating the journal greets with this same
                # protocol version and simply omits the key, and the app
                # (worker/socketClient.ts) reads anything but ``true`` as
                # "no journal here" and never sends a journal op.
                'journal': journal is not None,
            }))
        except ConnectionClosed:
            return  # closed before the greeting landed -- nothing to serve

        if journal is not None:
            def _notify_journal_update():
                # Called from ANY thread (see SessionJournal.add_listener's
                # docstring) -- hop back onto this connection's event loop
                # the same way on_progress does below.
                fut = asyncio.run_coroutine_threadsafe(
                    websocket.send(json.dumps(
                        {'type': 'journal', 'event': 'updated'})), loop)
                # Fire-and-forget, same reasoning as on_progress's callback
                # below: a notify racing a client close is routine, not an
                # error, and must not surface as an unretrieved-exception
                # warning.
                fut.add_done_callback(lambda f: f.exception())
            unsubscribe_journal = journal.add_listener(_notify_journal_update)

        async for raw in websocket:
            if not isinstance(raw, (bytes, bytearray)):
                continue                    # inbound text frames are unused
            try:
                req = decode_frame(raw)
                rid = req['id']
                op = req.get('op')
                payload = req.get('payload') or {}
                if not isinstance(payload, dict):
                    # A non-dict payload (e.g. a bare list) must not reach
                    # payload.get(...) below and blow up the connection --
                    # one bad frame must not kill a session (see docstring).
                    payload = {}
            except Exception as e:
                try:
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': 'undecodable engine frame: %s' % e,
                    }))
                except ConnectionClosed:
                    break                    # client's Stop -- exit cleanly
                continue

            # Journal ops are host-state ops -- answered here, never
            # shipped to the calc worker (which only knows compute ops).
            if op in ('journal_set', 'journal_get',
                      'journal_discard_recovered'):
                if journal is None:
                    reply = {'id': rid, 'ok': False,
                             'error': 'no session journal on this server'}
                elif op == 'journal_set':
                    doc = payload.get('doc')
                    # decode_frame only ever yields bytes for a 'bytes'
                    # blob (never memoryview) -- see the module docstring.
                    if not isinstance(doc, (bytes, bytearray)):
                        reply = {'id': rid, 'ok': False,
                                 'error': 'journal_set needs doc bytes'}
                    else:
                        # set_doc's spill does synchronous disk I/O (a
                        # tempfile write of the whole doc + os.replace,
                        # tens of MB for a lab session) -- off the loop so
                        # it never stalls the monitor feed, /ws, or any
                        # other /engine connection sharing it (see the
                        # loop-discipline note on the close-mid-op path
                        # below).
                        await loop.run_in_executor(None, journal.set_doc, doc)
                        reply = {'id': rid, 'ok': True, 'result': {}}
                elif op == 'journal_discard_recovered':
                    # os.remove is a syscall too -- same off-loop reasoning
                    # as journal_set above.
                    await loop.run_in_executor(None, journal.discard_recovered)
                    reply = {'id': rid, 'ok': True, 'result': {}}
                else:
                    # The generation is a WRITER's concern (see
                    # SessionJournal.set_doc's expect_generation); the
                    # app's autosave owns the whole document and posts
                    # unconditionally, so it stays off this wire.
                    doc, captures, _generation = journal.state()
                    reply = {'id': rid, 'ok': True,
                             'result': {'doc': doc, 'captures': captures,
                                        'recovered': journal.recovered()}}
                try:
                    await websocket.send(encode_frame(reply))
                except ConnectionClosed:
                    break
                continue

            last_sent = [0.0]

            def on_progress(done, total, rid=rid, last_sent=last_sent):
                # Called from the executor thread -- hop to the loop.
                # Throttled to ~10 Hz; the terminal frame always goes
                # through, however recently the last one was sent.
                now = time.monotonic()
                if done < total and now - last_sent[0] < PROGRESS_MIN_INTERVAL_S:
                    return
                last_sent[0] = now
                fut = asyncio.run_coroutine_threadsafe(
                    websocket.send(json.dumps({
                        'type': 'progress', 'callId': rid,
                        'done': done, 'total': total,
                    })), loop)
                # Fire-and-forget: a progress frame racing a client close
                # is expected (the socket can drop between any two of a
                # long CWT's scale steps), not an error. Retrieve and drop
                # the Future's exception so it never surfaces as an
                # unhandled "Future exception was never retrieved" warning.
                fut.add_done_callback(lambda f: f.exception())

            # functools.partial binds rid/op/payload/on_progress by VALUE
            # at construction time -- the loop awaits this call before its
            # next iteration could rebind any of them, so a plain closure
            # would already be safe, but partial keeps that obviously true
            # without relying on the await ordering.
            call = functools.partial(worker.request, rid, op, payload,
                                     on_progress=on_progress)
            op_fut = loop.run_in_executor(None, call)
            # Race the op against the peer closing the socket -- see the
            # docstring above. wait_closed() resolves only once the closing
            # handshake AND the TCP teardown are both done, so losing this
            # race means the peer is genuinely gone, not just mid-handshake.
            closed_fut = asyncio.ensure_future(websocket.wait_closed())
            try:
                done, _pending = await asyncio.wait(
                    {op_fut, closed_fut}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                if not closed_fut.done():
                    closed_fut.cancel()

            if op_fut not in done:
                # Client's Stop landed before the op finished. The outer
                # `finally` below cancels + kills the worker, which is what
                # actually unblocks the still-running executor thread --
                # kill()ing the child makes the blocked request() call
                # notice (at its next 1s queue-poll timeout) that the
                # process died and return an 'engine worker died' reply,
                # so the thread does unwind, just not on this tick. Its
                # result is never retrieved; drop the exception the same
                # way the progress futures above do (worker.request() is
                # documented to never raise, so this is a belt-and-braces
                # match for the same-shaped guard below, not an expected
                # path).
                op_fut.add_done_callback(lambda f: f.exception())
                break

            try:
                _kind, _rid, ok, result = op_fut.result()
            except Exception as e:
                # worker.request() is documented to always return a
                # ('done', rid, ok, ...) tuple rather than raise, but a
                # frame that hits an unexpected exception here (e.g. some
                # future edge case) must still get a reply -- not silently
                # drop the connection.
                ok, result = False, '%s: %s' % (type(e).__name__, e)
            reply = ({'id': rid, 'ok': True, 'result': result} if ok
                     else {'id': rid, 'ok': False, 'error': str(result)})
            try:
                frame = encode_frame(reply)
            except Exception as e:
                # A result that fails to encode (e.g. an op accidentally
                # returning a non-f8 ndarray) must still get a diagnostic
                # reply, not silently kill the connection -- this
                # replacement reply is built entirely from plain types, so
                # it cannot itself fail to encode.
                reply = {'id': rid, 'ok': False,
                         'error': 'unencodable result: %s: %s' %
                                  (type(e).__name__, e)}
                frame = encode_frame(reply)
            try:
                await websocket.send(frame)
            except ConnectionClosed:
                break  # client closed mid-op (its Stop) -- exit cleanly
    finally:
        if unsubscribe_journal is not None:
            unsubscribe_journal()
        worker.cancel()
        # kill() joins the dying child for up to 2s; run it off the loop
        # thread so a slow teardown doesn't stall the event loop (the
        # monitor feed, any /ws connection, and every other /engine
        # connection all share this loop).
        await loop.run_in_executor(None, worker.kill)
