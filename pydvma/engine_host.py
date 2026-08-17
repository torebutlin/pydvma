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
import json
import math
import multiprocessing as _mp
import queue as _queue
import struct

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

#: Seconds to wait for a cancelled op to unwind before terminating the child.
CANCEL_GRACE_S = 0.5


class EngineCancelled(Exception):
    """Raised inside the child when the cancel event is set mid-op."""


def _worker_main(req_q, res_q, cancel_ev):
    """Child entry: answer ``(id, op, kwargs)`` until ``None`` arrives.

    Emits ``('progress', id, done, total)`` frames via the installed
    engine progress hook (which doubles as the cooperative cancel
    checkpoint) and exactly one ``('done', id, ok, result_or_msg)`` per
    request.
    """
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
            res_q.put(('done', rid, True, fn(**kwargs)))
        except EngineCancelled:
            res_q.put(('done', rid, False, 'cancelled'))
        except Exception as e:
            res_q.put(('done', rid, False, '%s: %s' % (type(e).__name__, e)))


class EngineWorker:
    """Owner of one engine subprocess; blocking request/response API.

    Thread-safety: one request at a time (the /engine connection task
    serialises calls). ``request`` blocks until the op's ``done`` arrives,
    invoking ``on_progress(done, total)`` for each progress frame.
    """

    def __init__(self):
        self._ctx = _mp.get_context('spawn')
        self._proc = None
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
        """Run one op; returns ``('done', rid, ok, result_or_errmsg)``."""
        if self._proc is None or not self._proc.is_alive():
            self._spawn()
        self._req.put((rid, op, kwargs))
        while True:
            try:
                item = self._res.get(timeout=1.0)
            except _queue.Empty:
                if not self._proc.is_alive():
                    # The child may have managed to put its result before
                    # dying (e.g. it returned normally and was then reaped) --
                    # drain once more before declaring it lost.
                    try:
                        item = self._res.get_nowait()
                    except _queue.Empty:
                        return ('done', rid, False, 'engine worker died')
                else:
                    continue
            if item[0] == 'progress':
                if on_progress is not None and item[1] == rid:
                    on_progress(item[2], item[3])
                continue
            return item

    def cancel(self):
        """Cooperative cancel; escalate to terminate after CANCEL_GRACE_S."""
        self._cancel.set()

    def kill(self):
        """Hard stop: terminate the child (next request respawns)."""
        if self._proc is not None and self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout=2.0)
        self._proc = None

    def close(self):
        """Graceful shutdown for tests/teardown."""
        try:
            if self._proc is not None and self._proc.is_alive():
                self._req.put(None)
                self._proc.join(timeout=2.0)
        finally:
            self.kill()
