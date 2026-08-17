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


def _worker_main(req_q, res_q, cancel_ev):
    """Child entry: answer ``(id, op, kwargs)`` until ``None`` arrives.

    Emits ``('progress', id, done, total)`` frames via the installed
    engine progress hook (which doubles as the cooperative cancel
    checkpoint) and exactly one ``('done', id, ok, result_or_msg)`` per
    request.
    """
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
            # child) polls forever with no 'done' ever arriving. No shipped
            # op returns anything unpicklable today and only a >2 GiB
            # result could hit the Windows limit, so this is not fixed
            # here; revisit with a ``multiprocessing.queues.Queue``
            # subclass that surfaces its feeder thread's exception (the
            # ``_SafeQueue`` pattern used by e.g. loky/joblib) if a real op
            # ever gets large or exotic enough to trigger it.
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


async def handle_connection(websocket):
    """Serve one /engine connection: greeting, then serial op frames.

    One :class:`EngineWorker` per connection (one app tab is the expected
    client). Closing the socket is the client's Stop: cancel cooperatively,
    then terminate the child so the connection's resources are gone by the
    time the close completes.

    A frame that fails to decode gets a text ``{"type":"error"}`` reply
    (there is no id to correlate) and the connection lives on — one bad
    frame must not kill a session.
    """
    from pydvma import datastructure
    worker = EngineWorker()
    loop = asyncio.get_running_loop()
    try:
        await websocket.send(json.dumps({
            'type': 'engine_ready',
            'v': ENGINE_PROTOCOL_VERSION,
            'pydvma': datastructure.VERSION,
        }))
        async for raw in websocket:
            if not isinstance(raw, (bytes, bytearray)):
                continue                    # inbound text frames are unused
            try:
                req = decode_frame(raw)
                rid = req['id']
                op = req.get('op')
                payload = req.get('payload') or {}
            except Exception as e:
                await websocket.send(json.dumps({
                    'type': 'error',
                    'message': 'undecodable engine frame: %s' % e,
                }))
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
                asyncio.run_coroutine_threadsafe(
                    websocket.send(json.dumps({
                        'type': 'progress', 'callId': rid,
                        'done': done, 'total': total,
                    })), loop)

            # functools.partial binds rid/op/payload/on_progress by VALUE
            # at construction time -- the loop awaits this call before its
            # next iteration could rebind any of them, so a plain closure
            # would already be safe, but partial keeps that obviously true
            # without relying on the await ordering.
            call = functools.partial(worker.request, rid, op, payload,
                                     on_progress=on_progress)
            try:
                _kind, _rid, ok, result = await loop.run_in_executor(None, call)
            except Exception as e:
                # worker.request() is documented to always return a
                # ('done', rid, ok, ...) tuple rather than raise, but a
                # frame that hits an unexpected exception here (e.g. some
                # future edge case) must still get a reply -- not silently
                # drop the connection.
                ok, result = False, '%s: %s' % (type(e).__name__, e)
            reply = ({'id': rid, 'ok': True, 'result': result} if ok
                     else {'id': rid, 'ok': False, 'error': str(result)})
            await websocket.send(encode_frame(reply))
    finally:
        worker.cancel()
        worker.kill()
