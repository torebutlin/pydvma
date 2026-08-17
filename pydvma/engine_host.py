# -*- coding: utf-8 -*-
"""Native host for the engine ops: /engine websocket + worker subprocess.

The webui's compute requests (``pydvma.engine`` ops) are answered here in
ordinary CPython when the app is served by ``pydvma-serve`` — same ops,
same results as the in-browser pyodide worker, without the wasm32 memory
ceiling. See dev/plans/2026-08-17-native-engine-design.md.

Wire format (mirrors ``webui/src/lib/worker/frames.ts`` exactly): one
binary websocket frame per request and per reply —
``[u32 LE header_len][header JSON utf-8][blobs...]`` — where array/bytes
values anywhere inside the JSON are lifted into the trailing blobs and
replaced by ``{"__bin__": k, "kind": "f8"|"bytes", "len": n}``
placeholders (recursive through dicts and lists; blobs laid end-to-end
in index order). ``"f8"`` is flat little-endian float64. Progress and
the connect greeting are small text frames.
"""
import json
import struct

import numpy as np

#: /engine protocol version, advertised in the greeting and capabilities.
ENGINE_PROTOCOL_VERSION = 1

_HDR = struct.Struct('<I')


def encode_frame(header):
    """Encode ``header`` (a JSON-able tree that may contain float64
    ndarrays and bytes) into one binary frame.

    Arrays must be float64 (callers hold flat ``<f8`` per the engine-op
    convention); any other ndarray dtype raises ``TypeError`` rather
    than silently converting.
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
        return v

    head = json.dumps(lift(header)).encode('utf-8')
    return _HDR.pack(len(head)) + head + b''.join(blobs)


def decode_frame(data):
    """Decode one binary frame back into the header tree, placeholders
    replaced by float64 ndarrays / bytes."""
    data = bytes(data)
    (n,) = _HDR.unpack_from(data, 0)
    header = json.loads(data[4:4 + n].decode('utf-8'))
    blob_base = 4 + n

    # Blob k starts after the lengths of blobs 0..k-1; collect lengths by
    # walking once for placeholders in index order.
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

    def restore(v):
        if isinstance(v, dict):
            if '__bin__' in v:
                k, ln = v['__bin__'], v['len']
                raw = data[starts[k]:starts[k] + ln]
                if v['kind'] == 'f8':
                    return np.frombuffer(raw, dtype='<f8').copy()
                return bytes(raw)
            return {k: restore(x) for k, x in v.items()}
        if isinstance(v, list):
            return [restore(x) for x in v]
        return v

    return restore(header)
