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
  ``"f8"`` it is therefore always a multiple of 8.
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
"""
import json
import math
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
    """
    blobs = []

    def lift(v):
        if isinstance(v, np.ndarray):
            if v.dtype != np.dtype('<f8'):
                raise TypeError('engine frames carry float64 arrays only, '
                                'got dtype %s' % v.dtype)
            b = np.ascontiguousarray(v).tobytes()
            blobs.append(b)
            return {'__bin__': len(blobs) - 1, 'kind': 'f8', 'len': len(b)}
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

    # One allocation, blit header + blobs directly into it -- avoids the
    # pack + head + b''.join(blobs) triple-copy (this host exists to keep
    # captures off the wasm32 memory ceiling, so per-frame copies matter).
    blob_total = sum(len(b) for b in blobs)
    out = bytearray(4 + len(head) + blob_total)
    _HDR.pack_into(out, 0, len(head))
    out[4:4 + len(head)] = head
    pos = 4 + len(head)
    for b in blobs:
        out[pos:pos + len(b)] = b
        pos += len(b)
    return bytes(out)


def decode_frame(data):
    """Decode one binary frame back into the header tree; the inverse of ``encode_frame``.

    Placeholders are replaced by float64 ndarrays / bytes reconstructed
    from the frame's blob tail (one copy per f8 array via
    ``np.frombuffer(...).copy()``, not a slice-then-frombuffer double
    copy). Raises ``ValueError`` if the header declares more blob bytes
    than the frame actually carries (a truncated frame), or if a
    placeholder names an unrecognised ``kind``.
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

    if pos > len(data):
        raise ValueError('engine frame truncated: header declares %d blob bytes, '
                         'frame carries %d' % (pos - blob_base, len(data) - blob_base))

    def restore(v):
        if isinstance(v, dict):
            if '__bin__' in v:
                k, ln, kind = v['__bin__'], v['len'], v['kind']
                if kind == 'f8':
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
