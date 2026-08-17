# Native Engine (stages 0–2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Repo rules that bind every task:** edit `master` directly, commit small and often, NEVER run `git stash` or `git reset` (shared tree — see CLAUDE.md + auto-memory), push only when Tore asks. Run Playwright ONLY from `webui/`.

**Goal:** The webui's compute ops become answerable by two hosts — the existing pyodide worker (Pages, unchanged) or CPython inside `pydvma-serve` over a new `/engine` websocket — with the native host becoming the default when the app is served by `pydvma-serve`.

**Architecture:** Stage 0 moves `webui/src/lib/worker/glue.py` into the package as `pydvma/engine.py` (one implementation, version-locked to the wheel; the pyodide worker imports it from the installed wheel). Stage 1 adds `pydvma/engine_host.py` (binary frame codec + a persistent spawn-context worker subprocess per connection + the `/engine` ws handler) and a webui `SocketEngineClient` implementing the existing `EngineClient` interface, opt-in via `?enginehost=`. Stage 2 flips the default: served-by-pydvma-serve + version-matching greeting → native, silent fallback to pyodide.

**Design doc:** `dev/plans/2026-08-17-native-engine-design.md` (stages 3–4 are a later plan).

**Tech stack:** Python 3.11+ (`websockets` asyncio API, `multiprocessing` spawn context, numpy), TypeScript (Svelte 5, Vite, vitest, Playwright).

**Verified facts the plan relies on** (explored 2026-08-17):

- `glue.py` has **no pyodide imports** — JsProxy handling is duck-typed defensiveness; 5 pytest files already run it under CPython via a `sys.path` hack (`tests/test_webui_glue_{bla,bestmatch,fit,damping,progress}.py`).
- The worker installs the pydvma wheel via micropip **before** importing glue (`engine.worker.ts` boot), so `pyimport('pydvma.engine')` works once the module is in the wheel. Wheels rebuild via `cd webui && npm run vendor:wheels` (same `pydvma-2.3.0-py3-none-any.whl` name — `ENGINE_WHEELS` in `stores/engine.ts:151` needs no change).
- Worker wire protocol: `{id, op, payload}` → `{id, ok, result|error}` + unsolicited `{type:'progress', callId, done, total}` (throttled ~10 Hz worker-side, terminal frame always sent). `EngineClient` interface: `webui/src/lib/worker/client.ts:50-72`. Store integration point: `createEngineStore(client, baseUrl)` at `stores/engine.ts:184`; all actions call `engine.enqueue(op, payload)`.
- serve routing: `websockets.asyncio.server.serve(self._handler, host, port, process_request=self._process_request)` — ONE handler; `_process_request` (`serve.py:1248`) returns `None` for `/ws` to allow upgrade; `_handler` (`serve.py:1265`) must branch on `websocket.request.path` for a second ws route. Capabilities dict literal: `serve.py:890-906`.
- **`websockets` inbound `max_size` defaults to 1 MiB** — `/engine` request frames carry multi-MB arrays; `serve()` must pass `max_size=None`.
- Result decoding app-side goes through `mval()` (`actions.ts:96`) which handles plain objects (the JSON path) as well as Maps — no actions changes needed for a new transport.
- Bridge e2e pattern: `webui/e2e/bridge.spec.ts` — `BRIDGE_E2E=1` gate, spawns `python -m pydvma.serve --driver mock --port 8763`, app connects cross-origin via `?bridge=ws://127.0.0.1:8763/ws`. Engine self-test page: `?engine=1` → `EngineProbe.svelte` → `window.__engineSelfTest()`.
- `EngineProbe.svelte:26` and `App.svelte:76` both call `createEngineStore()` with no args — putting transport resolution in the store's *default* client factory wires both without touching either component.
- pytest runs from repo root (no ini options); `mkdocs build --strict` from root; `npm run check` / `npx vitest run` / `npx playwright test` from `webui/`.

**File map:**

| File | Change |
|---|---|
| `pydvma/engine.py` | Create (git mv of `webui/src/lib/worker/glue.py`, header docstring updated) |
| `pydvma/engine_host.py` | Create (frame codec, worker subprocess, `/engine` ws handler) |
| `pydvma/__init__.py` | Modify (`_LAZY_NAMES['engine'] = '.engine'`) |
| `pydvma/serve.py` | Modify (`/engine` route, `max_size=None`, capabilities `engine` key) |
| `tests/test_webui_glue_*.py` (5 files) | Modify (import `pydvma.engine`, drop sys.path hack) |
| `tests/test_engine_host.py` | Create |
| `webui/src/lib/worker/engine.worker.ts` | Modify (import glue from wheel) |
| `webui/src/lib/worker/frames.ts` | Create (JS frame codec) |
| `webui/src/lib/worker/socketClient.ts` | Create (`EngineClient` over ws) |
| `webui/src/lib/worker/selectEngine.ts` | Create (transport resolution policy) |
| `webui/src/lib/stores/engine.ts` | Modify (client factory default, `host` readable) |
| `webui/src/components/BusyChip.svelte` | Modify (engine-host indicator attr) |
| `webui/tests/worker/frames.test.ts` | Create |
| `webui/tests/worker/socketClient.test.ts` | Create |
| `webui/e2e/engine-native.spec.ts` | Create |
| `CHANGELOG.md`, docs, `CLAUDE.md`, `TODO.md` | Modify (final task) |

**The `/engine` wire protocol** (referenced by Tasks 3–7; defined once here, both codecs implement exactly this):

- On connect, server sends a text frame: `{"type":"engine_ready","v":1,"pydvma":"<datastructure.VERSION>"}`.
- Request and reply are each **one binary websocket frame**: `[u32 LE header_len][header JSON, utf-8][blob bytes...]`. Placeholders inside the JSON mark lifted binary values: `{"__bin__": k, "kind": "f8"|"bytes", "len": <bytes>}` — blob `k` is the k-th blob, laid end-to-end in index order after the header. `"f8"` reconstructs as flat little-endian float64 (JS `Float64Array` / numpy `<f8`); `"bytes"` as raw bytes (JS `Uint8Array` / Python `bytes`). The placeholder walk is **recursive** through dicts/objects and lists/arrays (payloads like `calc_fit`'s `sets` nest arrays inside lists of dicts).
- Request header: `{id, op, payload}`. Reply header: `{id, ok: true, result}` or `{id, ok: false, error}`.
- Progress is a small **text** frame: `{"type":"progress","callId":<id>,"done":d,"total":t}`.
- Ops execute **serially** per connection (matches the single-threaded pyodide worker's semantics); requests queue server-side.
- There is no cancel message: the client **closes the socket** to stop (mirror of worker `terminate()`); the server then sets the cancel event, terminates the worker subprocess if it doesn't unwind promptly, and tears down. Reconnect = fresh `init`.

---

### Task 1: Move glue.py into the package (stage 0, Python side)

**Files:**
- Create: `pydvma/engine.py` (via `git mv`)
- Modify: `pydvma/__init__.py:41-44` (`_LAZY_NAMES`)
- Modify: `tests/test_webui_glue_bla.py`, `tests/test_webui_glue_bestmatch.py`, `tests/test_webui_glue_fit.py`, `tests/test_webui_glue_damping.py`, `tests/test_webui_glue_progress.py`

- [ ] **Step 1: Move the file with history**

```bash
git mv webui/src/lib/worker/glue.py pydvma/engine.py
```

- [ ] **Step 2: Update the module docstring header**

In `pydvma/engine.py`, replace only the first two paragraphs of the module docstring (keep the array-boundary-convention paragraph verbatim):

```python
# -*- coding: utf-8 -*-
"""Engine ops: stateless compute wrappers around pydvma, host-agnostic.

One module, two hosts. In the browser the pyodide engine worker
(``webui/src/lib/worker/engine.worker.ts``) imports this from the
installed pydvma wheel and answers the app's ``{id, op, payload}``
requests; locally ``pydvma.engine_host`` answers the same ops over the
``/engine`` websocket in ordinary CPython. Every op is a plain function
taking JSON-marshallable scalars plus flat float64 arrays and returning
a dict of arrays — or, where the op is inherently plural, a LIST of
such dicts (``calc_bla`` returns one entry per excitation) — no state
survives between calls, so both hosts stay stateless.
```

- [ ] **Step 3: Register the lazy name**

In `pydvma/__init__.py`, extend `_LAZY_NAMES` (currently `{'PlotData': '.plotting', 'serve': '.serve'}`):

```python
_LAZY_NAMES = {
    'PlotData': '.plotting',
    'serve': '.serve',
    'engine': '.engine',
}
```

(No `_LAZY_EXTRAS` entry: engine.py needs only base deps. Do NOT add to `_PUBLIC_SURFACE` in `tests/test_packaging.py` — it is presence-only and additive names don't break it.)

- [ ] **Step 4: Repoint the five glue pytest files**

In each `tests/test_webui_glue_*.py`, delete the `_WORKER_DIR` / `sys.path.insert` block and the `pytest.importorskip('glue', ...)` line, replacing with:

```python
from pydvma import engine as glue
```

(Keep the local alias `glue` so no other line in those files changes. Remove the now-unused `sys`/`os` imports if nothing else uses them.)

- [ ] **Step 5: Run the moved tests and the packaging tests**

Run (repo root): `pytest tests/test_webui_glue_bla.py tests/test_webui_glue_bestmatch.py tests/test_webui_glue_fit.py tests/test_webui_glue_damping.py tests/test_webui_glue_progress.py tests/test_packaging.py -q`
Expected: all PASS (the five files exercised the identical code before the move).

- [ ] **Step 6: Full pytest**

Run: `pytest -q -m "not hardware"`
Expected: PASS (same skip counts as before the task).

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "refactor(engine): glue.py moves into the package as pydvma.engine

One compute-ops module, version-locked to the wheel, importable by both
the pyodide worker and the coming native host. Stage 0 of the
native-engine design (dev/plans/2026-08-17-native-engine-design.md)."
```

---

### Task 2: Worker imports engine from the wheel (stage 0, webui side)

**Files:**
- Modify: `webui/src/lib/worker/engine.worker.ts:27-31` (drop `?raw`), `:87-94` (import from wheel)

- [ ] **Step 1: Remove the `?raw` bundling**

In `engine.worker.ts`, delete the line `import glueSource from './glue.py?raw';` (and the comment block at lines 27–30 explaining it).

- [ ] **Step 2: Import from the installed wheel**

Replace the FS-write block (currently `pyodide.FS.mkdirTree('/engine'); pyodide.FS.writeFile('/engine/glue.py', glueSource); const sys = pyodide.pyimport('sys'); sys.path.append('/engine'); glue = pyodide.pyimport('glue');`) with:

```ts
  // Engine ops ship INSIDE the pydvma wheel installed above (stage 0 of the
  // native-engine design) — no more ?raw bundling, no FS write, and the ops
  // can never be newer or older than the pydvma they call.
  glue = pyodide.pyimport('pydvma.engine');
```

(The `set_progress_hook` wiring below it is unchanged — the moved module still exports it.)

- [ ] **Step 3: Rebuild the engine wheel (it must now contain engine.py)**

Run: `cd webui && npm run vendor:wheels`
Expected: `webui/public/pypi/pydvma-2.3.0-py3-none-any.whl` regenerated. Verify the module is inside:

Run: `python -c "import zipfile; print([n for n in zipfile.ZipFile('webui/public/pypi/pydvma-2.3.0-py3-none-any.whl').namelist() if 'engine' in n])"` (repo root)
Expected: `['pydvma/engine.py']`

- [ ] **Step 4: Typecheck + unit tests**

Run (from `webui/`): `npm run check && npx vitest run`
Expected: 0 errors / all vitest pass (nothing imports glue.py from TS except the deleted line).

- [ ] **Step 5: Real-engine e2e (proves the wheel-import path end to end)**

Run (from `webui/`): `npx playwright test --grep @engine --workers=1`
Expected: PASS (engine.spec.ts boots real pyodide, runs `__engineSelfTest` → `calc_fft` through the new import path).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "refactor(webui): worker imports pydvma.engine from the installed wheel

Drops the ?raw + FS-write + sys.path dance; the ops module now rides the
wheel micropip already installs. Engine wheel rebuilt (same 2.3.0 name).
Dev-loop note: editing pydvma/engine.py now needs 'npm run vendor:wheels'
before the browser sees it."
```

---

### Task 3: Python frame codec (stage 1)

**Files:**
- Create: `pydvma/engine_host.py` (codec section)
- Create: `tests/test_engine_host.py` (codec tests)

- [ ] **Step 1: Write the failing codec tests**

Create `tests/test_engine_host.py`:

```python
# -*- coding: utf-8 -*-
"""Native engine host: frame codec, worker subprocess, /engine endpoint."""
import numpy as np
import pytest

from pydvma import engine_host


def test_frame_roundtrip_scalars_only():
    header = {'id': 1, 'op': 'calc_fft', 'payload': {'fs': 8000, 'window': None}}
    frame = engine_host.encode_frame(header)
    out = engine_host.decode_frame(frame)
    assert out == header


def test_frame_roundtrip_lifts_arrays_recursively():
    a = np.arange(6, dtype='<f8')
    header = {'id': 2, 'op': 'calc_tf_averaged',
              'payload': {'sets': [{'time_data': a, 'fs': 100.0}],
                          'blob': b'\x00\x01\x02'}}
    frame = engine_host.encode_frame(header)
    out = engine_host.decode_frame(frame)
    got = out['payload']['sets'][0]['time_data']
    assert isinstance(got, np.ndarray) and got.dtype == np.dtype('<f8')
    np.testing.assert_array_equal(got, a)
    assert out['payload']['sets'][0]['fs'] == 100.0
    assert out['payload']['blob'] == b'\x00\x01\x02'


def test_frame_rejects_non_f8_ndarray():
    with pytest.raises(TypeError):
        engine_host.encode_frame({'x': np.arange(3, dtype='int32')})
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_engine_host.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pydvma.engine_host'`.

- [ ] **Step 3: Implement the codec**

Create `pydvma/engine_host.py`:

```python
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
```

- [ ] **Step 4: Run codec tests**

Run: `pytest tests/test_engine_host.py -q`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add pydvma/engine_host.py tests/test_engine_host.py
git commit -m "feat(engine-host): binary frame codec for the /engine protocol"
```

---

### Task 4: Worker subprocess (stage 1)

**Files:**
- Modify: `pydvma/engine_host.py` (append worker section)
- Modify: `tests/test_engine_host.py` (append worker tests)

- [ ] **Step 1: Write the failing worker tests** (append to `tests/test_engine_host.py`)

```python
def _mk_time(n=256, fs=1000.0, ch=2):
    t = np.arange(n) / fs
    d = np.sin(2 * np.pi * 50 * t)
    return {'time_axis': t, 'time_data': np.column_stack([d] * ch).ravel(),
            'n_channels': ch, 'fs': fs, 'window': None}


def test_worker_answers_calc_fft():
    w = engine_host.EngineWorker()
    try:
        kind, rid, ok, result = w.request(7, 'calc_fft', _mk_time())
        assert (kind, rid, ok) == ('done', 7, True)
        assert result['freq_data']['complex'] is True
        assert isinstance(result['freq_data']['data'], np.ndarray)
    finally:
        w.close()


def test_worker_reports_error_not_crash():
    w = engine_host.EngineWorker()
    try:
        kind, rid, ok, err = w.request(1, 'no_such_op', {})
        assert (kind, ok) == ('done', False)
        assert 'no_such_op' in err
        # Worker survives a bad op:
        kind, rid, ok, _ = w.request(2, 'calc_fft', _mk_time())
        assert ok is True
    finally:
        w.close()


def test_worker_streams_progress_for_cwt_sono():
    w = engine_host.EngineWorker()
    frames = []
    try:
        payload = _mk_time(n=4096)
        payload.pop('window')
        payload.update(ch=0, nperseg=256, noverlap=128, method='cwt')
        kind, rid, ok, _ = w.request(3, 'calc_sono', payload,
                                     on_progress=lambda d, t: frames.append((d, t)))
        assert ok is True
        assert frames and frames[-1][0] == frames[-1][1]  # terminal frame
    finally:
        w.close()


def test_worker_kill_and_respawn():
    w = engine_host.EngineWorker()
    try:
        w.kill()
        kind, rid, ok, _ = w.request(4, 'calc_fft', _mk_time())
        assert ok is True  # respawned transparently
    finally:
        w.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_engine_host.py -q`
Expected: codec tests PASS, new tests FAIL with `AttributeError: ... 'EngineWorker'`.

- [ ] **Step 3: Implement the worker** (append to `pydvma/engine_host.py`)

```python
# --- worker subprocess ------------------------------------------------------
#
# One persistent spawn-context subprocess executes ops SERIALLY — the same
# semantics as the single-threaded pyodide worker. Spawn (not fork): it is
# the only context on Windows and the safe one under macOS CoreAudio. The
# child imports numpy/scipy/pydvma once and stays warm; a hard stop
# terminates just the child and the next request respawns it.
import multiprocessing as _mp
import queue as _queue

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
            if fn is None or op.startswith('_'):
                raise ValueError('unknown op: %s' % op)
            res_q.put(('done', rid, True, fn(**kwargs)))
        except EngineCancelled:
            res_q.put(('done', rid, False, 'cancelled'))
        except Exception as e:                      # noqa: BLE001 — op errors go to the client
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
                    return ('done', rid, False, 'engine worker died')
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
```

- [ ] **Step 4: Run worker tests**

Run: `pytest tests/test_engine_host.py -q`
Expected: all PASS (spawn + numpy import in the child makes this a few seconds).

- [ ] **Step 5: Commit**

```bash
git add pydvma/engine_host.py tests/test_engine_host.py
git commit -m "feat(engine-host): persistent spawn-context worker subprocess

Serial op execution (pyodide-worker semantics), progress via the engine
hook (which doubles as the cooperative cancel checkpoint), hard kill +
transparent respawn."
```

---

### Task 5: `/engine` endpoint in serve (stage 1)

**Files:**
- Modify: `pydvma/engine_host.py` (append ws handler)
- Modify: `pydvma/serve.py:1248-1261` (`_process_request`), `:1265-1280` (`_handler`), `:1282-1295` (`run` — `max_size=None`), `:890-906` (capabilities)
- Modify: `tests/test_engine_host.py` (append endpoint tests)

- [ ] **Step 1: Write the failing endpoint tests** (append to `tests/test_engine_host.py`; the mini-harness mirrors `tests/test_serve_protocol.py:51-105`)

```python
import asyncio
import json as _json

from websockets.asyncio.client import connect

from pydvma import serve as serve_mod


async def _start_server(**kwargs):
    kwargs.setdefault('default_driver', 'mock')
    server = serve_mod.BridgeServer(host='127.0.0.1', port=0, **kwargs)
    task = asyncio.create_task(server.run())
    for _ in range(500):
        if server.sockets:
            break
        await asyncio.sleep(0.005)
    port = next(iter(server.sockets)).getsockname()[1]
    return server, task, port


async def _stop_server(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def run_async(coro_fn):
    asyncio.run(coro_fn())


def test_engine_endpoint_greets_and_answers_calc_fft():
    async def scenario():
        _s, task, port = await _start_server()
        try:
            async with connect('ws://127.0.0.1:%d/engine' % port,
                               max_size=None) as ws:
                greeting = _json.loads(await ws.recv())
                assert greeting['type'] == 'engine_ready'
                assert greeting['v'] == engine_host.ENGINE_PROTOCOL_VERSION
                await ws.send(engine_host.encode_frame(
                    {'id': 1, 'op': 'calc_fft', 'payload': _mk_time()}))
                raw = await ws.recv()
                assert isinstance(raw, (bytes, bytearray))
                reply = engine_host.decode_frame(raw)
                assert reply['id'] == 1 and reply['ok'] is True
                fd = reply['result']['freq_data']
                assert fd['complex'] is True
                assert isinstance(fd['data'], np.ndarray) and fd['data'].size > 0
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_engine_endpoint_error_reply_keeps_connection():
    async def scenario():
        _s, task, port = await _start_server()
        try:
            async with connect('ws://127.0.0.1:%d/engine' % port,
                               max_size=None) as ws:
                await ws.recv()  # greeting
                await ws.send(engine_host.encode_frame(
                    {'id': 5, 'op': 'nope', 'payload': {}}))
                reply = engine_host.decode_frame(await ws.recv())
                assert reply['ok'] is False and 'nope' in reply['error']
                await ws.send(engine_host.encode_frame(
                    {'id': 6, 'op': 'calc_fft', 'payload': _mk_time()}))
                assert engine_host.decode_frame(await ws.recv())['ok'] is True
        finally:
            await _stop_server(task)
    run_async(scenario)


def test_bridge_ws_still_works_alongside_engine():
    async def scenario():
        _s, task, port = await _start_server()
        try:
            async with connect('ws://127.0.0.1:%d/ws' % port) as ws:
                await ws.send(_json.dumps({'type': 'hello'}))
                cap = _json.loads(await ws.recv())
                assert cap['type'] == 'capabilities'
                assert cap['engine'] == {
                    'v': engine_host.ENGINE_PROTOCOL_VERSION,
                    'pydvma': serve_mod.datastructure.VERSION,
                }
        finally:
            await _stop_server(task)
    run_async(scenario)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_engine_host.py -q -k "endpoint or alongside"`
Expected: FAIL (connect to `/engine` is rejected / no greeting; capabilities has no `engine` key).

- [ ] **Step 3: Implement the ws handler** (append to `pydvma/engine_host.py`)

```python
# --- /engine websocket handler ---------------------------------------------
import asyncio


async def handle_connection(websocket):
    """Serve one /engine connection: greeting, then serial op frames.

    One EngineWorker per connection (one app tab is the expected client).
    Closing the socket is the client's Stop: cancel cooperatively, then
    terminate the child if it does not unwind within CANCEL_GRACE_S.
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
                continue                    # text frames are unused inbound
            req = decode_frame(raw)
            rid = req.get('id')

            def on_progress(done, total, rid=rid):
                # Called from the executor thread — hop to the loop.
                asyncio.run_coroutine_threadsafe(
                    websocket.send(json.dumps({
                        'type': 'progress', 'callId': rid,
                        'done': done, 'total': total,
                    })), loop)

            kind, _rid, ok, result = await loop.run_in_executor(
                None, lambda: worker.request(
                    rid, req.get('op'), req.get('payload') or {},
                    on_progress=on_progress))
            reply = ({'id': rid, 'ok': True, 'result': result} if ok
                     else {'id': rid, 'ok': False, 'error': str(result)})
            await websocket.send(encode_frame(reply))
    finally:
        worker.cancel()
        await asyncio.sleep(0)              # let a fast unwind land
        worker.kill()
```

- [ ] **Step 4: Route `/engine` in serve.py**

In `_process_request` (`serve.py:1248`), after the `/ws` branch add:

```python
        if path == '/engine':
            return None                     # WebSocket upgrade (native engine)
```

In `_handler` (`serve.py:1265`), branch on the path before building `_Connection`:

```python
    async def _handler(self, websocket):
        path = websocket.request.path.split('?', 1)[0]
        if path == '/engine':
            from . import engine_host
            await engine_host.handle_connection(websocket)
            return
        conn = _Connection(websocket)
        ...
```

In `run()` (`serve.py:1289`), add `max_size=None` to the `serve(...)` call with a comment:

```python
        async with serve(
            self._handler, self.host, self.port,
            process_request=self._process_request,
            # /engine request frames carry full capture arrays; the default
            # 1 MiB inbound cap would sever the connection mid-calc. Localhost
            # trust model — no cap.
            max_size=None,
        ) as server:
```

- [ ] **Step 5: Advertise in capabilities**

In `build_capabilities()`'s return dict (`serve.py:890-906`) add:

```python
        'engine': {
            'v': engine_host.ENGINE_PROTOCOL_VERSION,
            'pydvma': datastructure.VERSION,
        },
```

with `from . import engine_host` at the top of the function (local import, matching serve.py's deferred-import style) and confirm `datastructure` is already imported in serve.py (it is — used for `.dvma` assembly).

- [ ] **Step 6: Run the new tests, then the full serve suite**

Run: `pytest tests/test_engine_host.py tests/test_serve_protocol.py -q`
Expected: all PASS (the capabilities test in test_serve_protocol asserts known keys are present, additive keys don't break it — if a strict-equality assertion trips, update that test to include `engine`).

- [ ] **Step 7: Commit**

```bash
git add pydvma/engine_host.py pydvma/serve.py tests/test_engine_host.py
git commit -m "feat(serve): /engine websocket — native engine ops endpoint

Second ws route on the same port; greeting carries protocol + pydvma
version; ops run serially in the per-connection worker subprocess with
progress frames; socket close = cancel + kill. Capabilities advertise
{engine: {v, pydvma}}. max_size=None (frames carry capture arrays)."
```

---

### Task 6: JS frame codec (stage 1)

**Files:**
- Create: `webui/src/lib/worker/frames.ts`
- Create: `webui/tests/worker/frames.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `webui/tests/worker/frames.test.ts`:

```ts
import { describe, expect, test } from 'vitest';
import { encodeFrame, decodeFrame } from '../../src/lib/worker/frames';

describe('engine frame codec', () => {
  test('scalars round-trip', () => {
    const h = { id: 1, op: 'calc_fft', payload: { fs: 8000, window: null } };
    expect(decodeFrame(encodeFrame(h))).toEqual(h);
  });

  test('typed arrays lift recursively and round-trip', () => {
    const a = Float64Array.from([1, 2, 3]);
    const h = {
      id: 2, op: 'calc_tf_averaged',
      payload: { sets: [{ time_data: a, fs: 100 }], blob: Uint8Array.from([0, 1, 2]) },
    };
    const out = decodeFrame(encodeFrame(h)) as any;
    expect(out.payload.sets[0].time_data).toBeInstanceOf(Float64Array);
    expect([...out.payload.sets[0].time_data]).toEqual([1, 2, 3]);
    expect(out.payload.sets[0].fs).toBe(100);
    expect(out.payload.blob).toBeInstanceOf(Uint8Array);
    expect([...out.payload.blob]).toEqual([0, 1, 2]);
  });

  test('python-encoded frame layout decodes (u32 LE + JSON + blobs)', () => {
    // Hand-built frame: header {"x":{"__bin__":0,"kind":"f8","len":8}} + one 8-byte blob.
    const head = new TextEncoder().encode(JSON.stringify({ x: { __bin__: 0, kind: 'f8', len: 8 } }));
    const buf = new Uint8Array(4 + head.length + 8);
    new DataView(buf.buffer).setUint32(0, head.length, true);
    buf.set(head, 4);
    new DataView(buf.buffer).setFloat64(4 + head.length, 42.5, true);
    const out = decodeFrame(buf.buffer) as any;
    expect(out.x).toBeInstanceOf(Float64Array);
    expect(out.x[0]).toBe(42.5);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `webui/`): `npx vitest run tests/worker/frames.test.ts`
Expected: FAIL — cannot resolve `../../src/lib/worker/frames`.

- [ ] **Step 3: Implement**

Create `webui/src/lib/worker/frames.ts`:

```ts
// frames.ts — binary codec for the /engine websocket protocol.
//
// Mirrors pydvma/engine_host.py exactly: one binary frame =
// [u32 LE header_len][header JSON utf-8][blobs...]; Float64Array /
// Uint8Array values anywhere in the tree are lifted into the trailing
// blobs and replaced by {__bin__, kind: 'f8'|'bytes', len} placeholders
// (recursive; blobs end-to-end in index order).

interface BinPlaceholder { __bin__: number; kind: 'f8' | 'bytes'; len: number }

export function encodeFrame(header: unknown): ArrayBuffer {
  const blobs: Uint8Array[] = [];

  function lift(v: unknown): unknown {
    if (v instanceof Float64Array) {
      const b = new Uint8Array(v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength));
      blobs.push(b);
      return { __bin__: blobs.length - 1, kind: 'f8', len: b.byteLength };
    }
    if (v instanceof Uint8Array) {
      blobs.push(v);
      return { __bin__: blobs.length - 1, kind: 'bytes', len: v.byteLength };
    }
    if (Array.isArray(v)) return v.map(lift);
    if (v !== null && typeof v === 'object') {
      return Object.fromEntries(Object.entries(v as object).map(([k, x]) => [k, lift(x)]));
    }
    return v;
  }

  const head = new TextEncoder().encode(JSON.stringify(lift(header)));
  const total = 4 + head.byteLength + blobs.reduce((n, b) => n + b.byteLength, 0);
  const out = new Uint8Array(total);
  new DataView(out.buffer).setUint32(0, head.byteLength, true);
  out.set(head, 4);
  let pos = 4 + head.byteLength;
  for (const b of blobs) { out.set(b, pos); pos += b.byteLength; }
  return out.buffer;
}

export function decodeFrame(data: ArrayBuffer): unknown {
  const view = new DataView(data);
  const n = view.getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(data, 4, n)));
  const blobBase = 4 + n;

  const lens = new Map<number, number>();
  (function index(v: unknown): void {
    if (Array.isArray(v)) { v.forEach(index); return; }
    if (v !== null && typeof v === 'object') {
      const p = v as Partial<BinPlaceholder>;
      if (typeof p.__bin__ === 'number') { lens.set(p.__bin__, p.len ?? 0); return; }
      Object.values(v as object).forEach(index);
    }
  })(header);
  const starts = new Map<number, number>();
  let pos = blobBase;
  for (const k of [...lens.keys()].sort((a, b) => a - b)) {
    starts.set(k, pos);
    pos += lens.get(k)!;
  }

  function restore(v: unknown): unknown {
    if (Array.isArray(v)) return v.map(restore);
    if (v !== null && typeof v === 'object') {
      const p = v as Partial<BinPlaceholder>;
      if (typeof p.__bin__ === 'number') {
        const start = starts.get(p.__bin__)!;
        const bytes = data.slice(start, start + (p.len ?? 0));
        return p.kind === 'f8' ? new Float64Array(bytes) : new Uint8Array(bytes);
      }
      return Object.fromEntries(Object.entries(v as object).map(([k, x]) => [k, restore(x)]));
    }
    return v;
  }
  return restore(header);
}
```

- [ ] **Step 4: Run tests + typecheck**

Run (from `webui/`): `npx vitest run tests/worker/frames.test.ts && npm run check`
Expected: 3 PASS, 0 check errors.

- [ ] **Step 5: Commit**

```bash
git add webui/src/lib/worker/frames.ts webui/tests/worker/frames.test.ts
git commit -m "feat(webui): JS frame codec for the /engine protocol (mirrors engine_host)"
```

---

### Task 7: SocketEngineClient (stage 1)

**Files:**
- Create: `webui/src/lib/worker/socketClient.ts`
- Create: `webui/tests/worker/socketClient.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `webui/tests/worker/socketClient.test.ts` (fake-socket pattern mirrors `protocol.test.ts` and `bridge.ts`'s `WsLike`):

```ts
import { describe, expect, test } from 'vitest';
import { createSocketEngineClient, type EngineWsLike } from '../../src/lib/worker/socketClient';
import { encodeFrame, decodeFrame } from '../../src/lib/worker/frames';

function makeFakeWs() {
  const sent: unknown[] = [];
  const ws: EngineWsLike = {
    readyState: 0, binaryType: 'arraybuffer',
    send(d) { sent.push(d); },
    close() { this.readyState = 3; this.onclose?.(); },
    onopen: null, onmessage: null, onerror: null, onclose: null,
  };
  const open = () => { ws.readyState = 1; ws.onopen?.(); };
  const greet = () => ws.onmessage?.({ data: JSON.stringify({ type: 'engine_ready', v: 1, pydvma: '2.3.0' }) });
  const reply = (frame: ArrayBuffer) => ws.onmessage?.({ data: frame });
  const text = (obj: unknown) => ws.onmessage?.({ data: JSON.stringify(obj) });
  return { ws, sent, open, greet, reply, text };
}

describe('socket engine client', () => {
  test('init resolves on greeting; call round-trips a frame by id', async () => {
    const f = makeFakeWs();
    const client = createSocketEngineClient('ws://x/engine', () => f.ws);
    const initP = client.init('http://x/', [], '0');
    f.open(); f.greet();
    await initP;

    const p = client.call<{ n: number }>('calc_fft', { fs: 8000 });
    const req = decodeFrame(f.sent[0] as ArrayBuffer) as any;
    expect(req.op).toBe('calc_fft');
    f.reply(encodeFrame({ id: req.id, ok: true, result: { n: 1 } }));
    await expect(p).resolves.toEqual({ n: 1 });
  });

  test('progress frames reach observers; error replies reject', async () => {
    const f = makeFakeWs();
    const client = createSocketEngineClient('ws://x/engine', () => f.ws);
    const frames: unknown[] = [];
    client.observe?.({ onProgress: (fr) => frames.push(fr) });
    const initP = client.init('http://x/', [], '0');
    f.open(); f.greet();
    await initP;

    const p = client.call('calc_sono', {});
    const req = decodeFrame(f.sent[0] as ArrayBuffer) as any;
    f.text({ type: 'progress', callId: req.id, done: 1, total: 4 });
    expect(frames).toEqual([{ callId: req.id, op: 'calc_sono', done: 1, total: 4 }]);
    f.reply(encodeFrame({ id: req.id, ok: false, error: 'boom' }));
    await expect(p).rejects.toThrow('boom');
  });

  test('restart closes the socket and rejects in-flight; next init reconnects', async () => {
    const factories: ReturnType<typeof makeFakeWs>[] = [];
    const client = createSocketEngineClient('ws://x/engine', () => {
      const f = makeFakeWs(); factories.push(f); return f.ws;
    });
    const initP = client.init('http://x/', [], '0');
    factories[0].open(); factories[0].greet();
    await initP;
    const p = client.call('calc_fft', {});
    client.restart(new Error('stopped'));
    await expect(p).rejects.toThrow('stopped');
    const init2 = client.init('http://x/', [], '0');
    factories[1].open(); factories[1].greet();
    await expect(init2).resolves.toBeUndefined();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `webui/`): `npx vitest run tests/worker/socketClient.test.ts`
Expected: FAIL — cannot resolve `../../src/lib/worker/socketClient`.

- [ ] **Step 3: Implement**

Create `webui/src/lib/worker/socketClient.ts`:

```ts
// socketClient.ts — EngineClient over the /engine websocket (native host).
//
// Same contract as worker/client.ts (id-correlated request/response +
// unsolicited progress), different transport: binary frames per
// frames.ts to a CPython pydvma-serve. init() connects and waits for the
// engine_ready greeting; restart() closes the socket (the server treats
// close as cancel-and-kill) and the store's re-boot reconnects.
import type { EngineCallEvents, EngineClient } from './client';
import { decodeFrame, encodeFrame } from './frames';

/** The WebSocket slice we depend on (mirrors bridge.ts's WsLike). */
export interface EngineWsLike {
  readyState: number;
  binaryType: string;
  send(data: string | ArrayBufferLike | ArrayBufferView): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev?: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onerror: ((ev?: unknown) => void) | null;
  onclose: ((ev?: unknown) => void) | null;
}

function defaultWsFactory(url: string): EngineWsLike {
  const ws = new WebSocket(url) as unknown as EngineWsLike;
  ws.binaryType = 'arraybuffer';
  return ws;
}

export function createSocketEngineClient(
  url: string,
  wsFactory: (url: string) => EngineWsLike = defaultWsFactory,
): EngineClient {
  interface Pending { op: string; resolve: (v: any) => void; reject: (e: any) => void }
  const pending = new Map<number, Pending>();
  let nextId = 1;
  let ws: EngineWsLike | null = null;
  let disposed = false;
  let events: EngineCallEvents = {};

  function finish(id: number): Pending | undefined {
    const entry = pending.get(id);
    if (!entry) return undefined;
    pending.delete(id);
    events.onSettled?.({ callId: id, op: entry.op });
    return entry;
  }

  function rejectAll(err: Error) {
    for (const id of [...pending.keys()]) finish(id)?.reject(err);
  }

  function handleMessage(data: unknown) {
    if (typeof data === 'string') {
      const msg = JSON.parse(data);
      if (msg?.type === 'progress') {
        const entry = pending.get(msg.callId);
        if (entry) events.onProgress?.({ callId: msg.callId, op: entry.op, done: msg.done, total: msg.total });
      }
      return; // engine_ready is consumed by init's own handler
    }
    const reply = decodeFrame(data as ArrayBuffer) as { id: number; ok: boolean; result?: unknown; error?: string };
    const entry = finish(reply.id);
    if (!entry) return;
    if (reply.ok) entry.resolve(reply.result);
    else entry.reject(new Error(reply.error ?? 'engine error'));
  }

  return {
    // baseUrl/wheels/pyodideVersion are pyodide concerns — ignored here.
    init(): Promise<void> {
      if (disposed) return Promise.reject(new Error('engine client disposed'));
      return new Promise<void>((resolve, reject) => {
        const sock = wsFactory(url);
        ws = sock;
        sock.onerror = () => reject(new Error('native engine connect failed'));
        sock.onclose = () => {
          rejectAll(new Error('native engine connection closed'));
          reject(new Error('native engine connection closed'));
        };
        sock.onmessage = (e) => {
          if (typeof e.data === 'string') {
            const msg = JSON.parse(e.data);
            if (msg?.type === 'engine_ready') {
              // Steady-state handler from here on.
              sock.onmessage = (ev) => handleMessage(ev.data);
              sock.onclose = () => rejectAll(new Error('native engine connection closed'));
              resolve();
              return;
            }
          }
          handleMessage(e.data);
        };
        sock.onopen = () => { /* wait for engine_ready */ };
      });
    },

    call<T = unknown>(op: string, payload?: Record<string, unknown>): Promise<T> {
      if (disposed) return Promise.reject(new Error('engine client disposed'));
      if (!ws || ws.readyState !== 1) return Promise.reject(new Error('native engine not connected'));
      const id = nextId++;
      return new Promise<T>((resolve, reject) => {
        pending.set(id, { op, resolve, reject });
        ws!.send(encodeFrame({ id, op, payload: payload ?? {} }));
      });
    },

    observe(ev: EngineCallEvents) { events = ev; },

    restart(reason: Error) {
      if (disposed) return;
      rejectAll(reason);
      const old = ws;
      ws = null;
      if (old) { old.onclose = null; old.close(); }
      // Caller (the store's stop()) re-inits, which reconnects.
    },

    dispose(reason?: Error) {
      disposed = true;
      rejectAll(reason ?? new Error('engine client disposed'));
      const old = ws;
      ws = null;
      if (old) { old.onclose = null; old.close(); }
    },
  };
}
```

- [ ] **Step 4: Run tests + typecheck**

Run (from `webui/`): `npx vitest run tests/worker/socketClient.test.ts && npm run check`
Expected: 3 PASS, 0 check errors.

- [ ] **Step 5: Commit**

```bash
git add webui/src/lib/worker/socketClient.ts webui/tests/worker/socketClient.test.ts
git commit -m "feat(webui): SocketEngineClient — EngineClient over the /engine websocket"
```

---

### Task 8: Transport resolution + store wiring, opt-in (stage 1)

> **Carry-over from Task 3's review (host-parity at the decode boundary):**
> the native codec sanitises non-finite scalar floats to `null` (JSON can't
> carry NaN/Infinity), but the app decodes damping scalars with
> `Number(mval(...))` (`actions.ts:2342-2343`) and `Number(null) === 0` —
> so a degenerate mode would render as a plausible-looking `Qn=0` on the
> native host where pyodide shows `Infinity`/`NaN`. When wiring the socket
> transport into the store, change those decode sites to `Number(v ?? NaN)`
> (grep actions.ts for `Number(mval` and audit each) so null decodes as NaN
> on both hosts. Add a vitest asserting it.

**Files:**
- Create: `webui/src/lib/worker/selectEngine.ts`
- Modify: `webui/src/lib/stores/engine.ts:184-187` (factory default), plus a `host` readable
- Modify: `webui/src/components/BusyChip.svelte` (indicator attribute)
- Modify: `webui/tests/worker/protocol.test.ts` (store factory test appended)

- [ ] **Step 1: Write the failing store test** (append to the `createEngineStore` describe block in `webui/tests/worker/protocol.test.ts`, alongside the existing `makeFakeClient()` tests)

```ts
  test('async client factory resolves at boot; host store reports it', async () => {
    const { client } = makeFakeClient();
    const store = createEngineStore(async () => ({ client, host: 'native' as const }));
    expect(get(store.host)).toBeNull();
    await store.boot();
    expect(get(store.status)).toBe('ready');
    expect(get(store.host)).toBe('native');
  });
```

- [ ] **Step 2: Run to verify failure**

Run (from `webui/`): `npx vitest run tests/worker/protocol.test.ts`
Expected: new test FAILS (factory signature unsupported, no `host` export); existing tests PASS.

- [ ] **Step 3: Implement the resolution policy**

Create `webui/src/lib/worker/selectEngine.ts`:

```ts
// selectEngine.ts — which engine host answers this session's compute?
//
// Stage-1 policy (opt-in): the native engine is used ONLY when the page
// carries ?enginehost=native (same-origin /engine) or ?enginehost=ws://…
// (explicit URL, the e2e cross-origin form). ?enginehost=pyodide forces
// the worker. Anything else — and any native connect/greeting failure —
// falls back to the pyodide worker, which is today's behaviour.
import { createEngineClient, type EngineClient } from './client';
import { createSocketEngineClient } from './socketClient';

export type EngineHostKind = 'pyodide' | 'native';
export interface ResolvedEngine { client: EngineClient; host: EngineHostKind }

/** Same-origin /engine ws URL (mirror of provider.ts's defaultBridgeWsUrl). */
export function defaultEngineWsUrl(): string {
  if (typeof window === 'undefined') return 'ws://127.0.0.1:8760/engine';
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/engine`;
}

function param(): string | null {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get('enginehost');
}

/** Try native (connect + greeting via client.init); fall back to pyodide. */
async function tryNative(url: string): Promise<ResolvedEngine | null> {
  const client = createSocketEngineClient(url);
  try {
    await client.init('', [], '');
    return { client, host: 'native' };
  } catch {
    client.dispose();
    return null;
  }
}

export async function resolveEngineClient(): Promise<ResolvedEngine> {
  const p = param();
  if (p && p !== 'pyodide') {
    const url = p === 'native' ? defaultEngineWsUrl() : p;
    const native = await tryNative(url);
    if (native) return native;
  }
  return { client: createEngineClient(), host: 'pyodide' };
}
```

- [ ] **Step 4: Teach the store the factory form**

In `webui/src/lib/stores/engine.ts`:

1. Import: `import { resolveEngineClient, type EngineHostKind, type ResolvedEngine } from '../worker/selectEngine';`
2. Change the factory signature (`:184-187`). The store currently closes over `client` directly; make `client` late-bound:

```ts
export function createEngineStore(
  clientSource: EngineClient | (() => Promise<ResolvedEngine>) = resolveEngineClient,
  baseUrl: string = defaultBaseUrl(),
) {
  // Late-bound: resolved in boot(). Tests that pass a client object keep
  // exactly the old semantics (host reports 'pyodide').
  let client: EngineClient | null =
    typeof clientSource === 'function' ? null : clientSource;
  const host = writable<EngineHostKind | null>(
    typeof clientSource === 'function' ? null : 'pyodide');
```

3. In `boot()`, before the existing `client.init(...)` call, resolve the client once:

```ts
      if (client === null) {
        const resolved = await (clientSource as () => Promise<ResolvedEngine>)();
        client = resolved.client;
        host.set(resolved.host);
        wireObserve();          // the observe() registration moves into this helper
      }
      await client.init(baseUrl, ENGINE_WHEELS, PYODIDE_VERSION);
```

   Extract the existing `client.observe?.({...})` registration (currently at store-construction time, `:206-220`) into a `wireObserve()` function called both from the constructor path (when `client` was passed directly) and after factory resolution. Every other `client.` use in the store (`enqueue`, `stop`) already runs only in `'ready'`/post-boot states where `client` is non-null; add a `client!` assertion or a narrow guard where TS demands it — do NOT restructure the queue/stop logic.

4. `stop()` re-runs `boot()` after `client.restart(err)` — for a factory-resolved native client this reconnects the socket via `init` (Task 7's restart contract). No change needed beyond the null-guard.
5. Export `host` from the returned store object (readable).

- [ ] **Step 5: Run the store tests**

Run (from `webui/`): `npx vitest run tests/worker/protocol.test.ts && npm run check`
Expected: all PASS (old direct-client tests untouched), 0 check errors.

- [ ] **Step 6: Indicator**

In `webui/src/components/BusyChip.svelte`, the component already receives/derives engine state from the store (find its props where `engineStatus` is passed from `App.svelte:~110`). Pass `engineHost = engine.host` alongside from App.svelte and render it as a data attribute + tooltip on the chip's root element:

```svelte
<div class="busy-chip" data-engine-host={$engineHost ?? 'unresolved'}
     title={`computing — engine: ${$engineHost === 'native' ? 'local Python' : 'browser'}`}>
```

(Exact insertion adapts to the chip's existing root markup; keep the visible design unchanged — this is a tooltip + testable attribute, not new chrome. If BusyChip renders nothing when idle, ALSO add the same attribute to the engine status element in `EngineProbe.svelte` so e2e can assert host without waiting for a busy state.)

- [ ] **Step 7: Full webui suite**

Run (from `webui/`): `npx vitest run && npm run check`
Expected: all PASS, 0 errors.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat(webui): engine transport resolution — ?enginehost= opt-in, host indicator

createEngineStore accepts an async client factory (default: resolve
?enginehost= → native socket client with greeting check, else pyodide);
store exposes host; BusyChip carries data-engine-host + tooltip."
```

---

### Task 9: Native-engine e2e (stage 1)

**Files:**
- Create: `webui/e2e/engine-native.spec.ts`
- Modify: `webui/src/components/EngineProbe.svelte` (honour `?enginehost=` — it creates its own store with no args, so it gets the default factory for free; verify only)

- [ ] **Step 1: Write the spec** (pattern copied from `bridge.spec.ts`'s spawn/waitForPort + `engine.spec.ts`'s probe; keep the BRIDGE_E2E gate so CI without python skips)

Create `webui/e2e/engine-native.spec.ts`:

```ts
// Native-engine e2e: the EngineProbe self-test driven through the
// SocketEngineClient against a real spawned pydvma-serve (mock driver).
// Run: BRIDGE_E2E=1 npx playwright test e2e/engine-native.spec.ts
import { spawn, type ChildProcess } from 'node:child_process';
import net from 'node:net';
import path from 'node:path';
import { expect, test } from '@playwright/test';

const BRIDGE_E2E = !!process.env.BRIDGE_E2E;
const PYTHON = process.env.PYDVMA_PYTHON ?? 'python3';
const PORT = Number(process.env.ENGINE_PORT ?? 8764);
const REPO_ROOT = path.resolve(__dirname, '..', '..');

function waitForPort(port: number, timeoutMs = 15000): Promise<void> {
  const t0 = Date.now();
  return new Promise((resolve, reject) => {
    const tryOnce = () => {
      const sock = net.connect(port, '127.0.0.1');
      sock.once('connect', () => { sock.destroy(); resolve(); });
      sock.once('error', () => {
        sock.destroy();
        if (Date.now() - t0 > timeoutMs) reject(new Error('port timeout'));
        else setTimeout(tryOnce, 200);
      });
    };
    tryOnce();
  });
}

test.describe('native engine', () => {
  test.skip(!BRIDGE_E2E, 'set BRIDGE_E2E=1 (needs pydvma + websockets; spawns python -m pydvma.serve)');
  let server: ChildProcess;

  test.beforeAll(async () => {
    server = spawn(PYTHON, ['-m', 'pydvma.serve', '--driver', 'mock', '--port', String(PORT)],
      { cwd: REPO_ROOT, stdio: 'pipe' });
    await waitForPort(PORT);
  });
  test.afterAll(() => { server?.kill('SIGINT'); });

  test('probe self-test runs calc_fft through the socket client', async ({ page }) => {
    await page.goto(`/?engine=1&enginehost=ws://127.0.0.1:${PORT}/engine`);
    await expect(page.getByTestId('engine-status')).toHaveText('ready', { timeout: 30000 });
    const result = await page.evaluate(() => (window as any).__engineSelfTest());
    expect(result.ok).toBe(true);
  });

  test('bad enginehost falls back to pyodide silently', async ({ page }) => {
    await page.goto('/?engine=1&enginehost=ws://127.0.0.1:1/engine');
    await expect(page.getByTestId('engine-status')).toHaveText('ready', { timeout: 200000 });
    const result = await page.evaluate(() => (window as any).__engineSelfTest());
    expect(result.ok).toBe(true);
  });
});
```

Adapt the exact `engine-status` selector/ready text and `__engineSelfTest` result shape to what `engine.spec.ts` + `EngineProbe.svelte` actually use (read both first — the probe's self-test result field names must be asserted as they are, not invented). If the probe's status element does not yet carry `data-engine-host`, assert host via the attribute added in Task 8 in the first test: `await expect(page.getByTestId('engine-status')).toHaveAttribute('data-engine-host', 'native')`.

- [ ] **Step 2: Run it**

Run (from `webui/`): `BRIDGE_E2E=1 npx playwright test e2e/engine-native.spec.ts --workers=1`
Expected: 2 PASS (first test needs NO pyodide boot — ready should arrive in ~1-3 s; the fallback test boots real pyodide, hence the long timeout).

- [ ] **Step 3: Run the whole non-engine Playwright set to prove no regression**

Run (from `webui/`): `npx playwright test --grep-invert @engine`
Expected: same pass/skip counts as before this plan.

- [ ] **Step 4: Commit**

```bash
git add webui/e2e/engine-native.spec.ts
git commit -m "test(e2e): native engine — probe self-test via SocketEngineClient vs real serve, plus silent-fallback proof"
```

---

### Task 10: Flip the default when served by pydvma-serve (stage 2)

**Files:**
- Modify: `webui/src/lib/worker/selectEngine.ts` (auto-detection)
- Modify: `webui/tests/worker/socketClient.test.ts` or new `webui/tests/worker/selectEngine.test.ts` (policy tests)
- Modify: `webui/e2e/engine-native.spec.ts` (served-mode default test)

- [ ] **Step 1: Write the failing policy tests**

Create `webui/tests/worker/selectEngine.test.ts`:

```ts
import { describe, expect, test } from 'vitest';
import { decideEnginePolicy } from '../../src/lib/worker/selectEngine';

describe('engine host policy', () => {
  test('explicit param wins in both directions', () => {
    expect(decideEnginePolicy('pyodide', true)).toEqual({ kind: 'pyodide' });
    expect(decideEnginePolicy('native', false)).toEqual({ kind: 'native', url: 'same-origin' });
    expect(decideEnginePolicy('ws://h/engine', false)).toEqual({ kind: 'native', url: 'ws://h/engine' });
  });
  test('served by pydvma-serve defaults to native; Pages stays pyodide', () => {
    expect(decideEnginePolicy(null, true)).toEqual({ kind: 'native', url: 'same-origin' });
    expect(decideEnginePolicy(null, false)).toEqual({ kind: 'pyodide' });
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `webui/`): `npx vitest run tests/worker/selectEngine.test.ts`
Expected: FAIL — `decideEnginePolicy` not exported.

- [ ] **Step 3: Implement**

In `selectEngine.ts`, extract the decision into a pure exported function and add the served-detection (reusing the existing `/config` probe — `fetchServeConfig` is already exported from `../audio/provider`):

```ts
import { fetchServeConfig } from '../audio/provider';

export type EnginePolicy = { kind: 'pyodide' } | { kind: 'native'; url: string };

/** Pure policy: explicit param beats detection; served-by-serve → native. */
export function decideEnginePolicy(param: string | null, served: boolean): EnginePolicy {
  if (param === 'pyodide') return { kind: 'pyodide' };
  if (param === 'native') return { kind: 'native', url: 'same-origin' };
  if (param) return { kind: 'native', url: param };
  return served ? { kind: 'native', url: 'same-origin' } : { kind: 'pyodide' };
}

export async function resolveEngineClient(): Promise<ResolvedEngine> {
  const p = param();
  // Only probe /config when no explicit param — Pages never pays the probe
  // beyond what selectProvider already does, and dev/vite (no serve) gets a
  // fast null.
  const served = p ? false : (await fetchServeConfig()) !== null;
  const policy = decideEnginePolicy(p, served);
  if (policy.kind === 'native') {
    const url = policy.url === 'same-origin' ? defaultEngineWsUrl() : policy.url;
    const native = await tryNative(url);
    if (native) return native;
    console.warn('pydvma: native engine unavailable, using browser engine');
  }
  return { client: createEngineClient(), host: 'pyodide' };
}
```

(The Task-8 version of `resolveEngineClient` is replaced by this; `tryNative`/`defaultEngineWsUrl`/`param` are unchanged. Version gating lives in the greeting check inside `init` — extend `socketClient.ts`'s greeting handler to reject when `msg.v !== 1`, which `tryNative` already converts into fallback.)

In `socketClient.ts`'s init greeting branch, add the version gate:

```ts
            if (msg?.type === 'engine_ready') {
              if (msg.v !== 1) {
                reject(new Error(`native engine protocol v${msg.v} unsupported`));
                sock.close();
                return;
              }
```

- [ ] **Step 4: Run policy + client tests**

Run (from `webui/`): `npx vitest run tests/worker/ && npm run check`
Expected: all PASS, 0 errors.

- [ ] **Step 5: e2e — served mode defaults to native**

Append to `engine-native.spec.ts` (inside the gated describe): a test that opens the app **through the spawned serve itself** (it serves the built UI — `webui/dist` resolution is automatic in a dev checkout) with NO `enginehost` param, and asserts native host:

```ts
  test('served by pydvma-serve → native engine by default', async ({ page }) => {
    await page.goto(`http://127.0.0.1:${PORT}/?engine=1`);
    await expect(page.getByTestId('engine-status')).toHaveText('ready', { timeout: 30000 });
    await expect(page.getByTestId('engine-status')).toHaveAttribute('data-engine-host', 'native');
    const result = await page.evaluate(() => (window as any).__engineSelfTest());
    expect(result.ok).toBe(true);
  });
```

(Requires `webui/dist` to exist: `npm run build` runs in the Playwright webServer already. The `baseURL` doesn't apply to an absolute `page.goto` — this is deliberate: the page must come from serve's origin for same-origin detection.)

- [ ] **Step 6: Run the full e2e**

Run (from `webui/`): `BRIDGE_E2E=1 npx playwright test e2e/engine-native.spec.ts e2e/bridge.spec.ts --workers=1`
Expected: all PASS — including every pre-existing bridge test (proves /ws is untouched by the default flip).

- [ ] **Step 7: The regression floor, natively**

Run the 3c6 envelope through the native engine by hand once: `pydvma-serve --driver mock --open`, load/log ~30 s of 2-ch data, run FFT/TF/CWT sonogram + CWT damping. Confirm results render, progress bar moves during CWT, Stop works and the next calc succeeds.
Then force pyodide (`?enginehost=pyodide`) and confirm the same flows still work.
Expected: both hosts green; note anything odd in the round doc rather than fixing drive-by.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat(webui): native engine is the default when served by pydvma-serve

Pure decideEnginePolicy (param beats detection; /config probe = served),
greeting version gate, silent pyodide fallback with a console warn.
e2e: served-mode default asserted end-to-end against a real serve."
```

---

### Task 11: Docs, changelog, project state

**Files:**
- Modify: `CHANGELOG.md` (Unreleased), `docs/web-logger/index.md`, `docs/web-logger/migration.md`, `CLAUDE.md` (Current focus), `TODO.md`

- [ ] **Step 1: CHANGELOG**

Under `## Unreleased` add (matching the bold-lead-phrase house style):

```markdown
### Added

- **Native compute engine.** When the app is served by `pydvma-serve`,
  analysis ops now run in ordinary CPython on the serving machine
  (a new `/engine` websocket + `pydvma.engine_host`) instead of the
  in-browser pyodide engine — no wasm 2 GB memory ceiling, full BLAS
  speed, and Stop terminates just a worker subprocess (the session
  survives). The Pages app is unchanged: the browser engine remains the
  zero-install path and the automatic fallback whenever the native host
  is absent or version-mismatched. Force a host with `?enginehost=`
  (`native`, `pyodide`, or an explicit `ws://` URL).

### Changed

- **Engine ops live in the package.** The compute glue that the browser
  worker used to bundle privately is now `pydvma.engine`, shipped in the
  wheel and shared verbatim by both engine hosts.
```

- [ ] **Step 2: Docs corrections**

- `docs/web-logger/migration.md` (and the equivalent phrase in `docs/web-logger/index.md`): the sentence "in a pyodide worker in the browser, or in the `pydvma serve` process" was aspirational until now — reword to describe the real rule: *"analysis runs the same pydvma core in both modes — in a pyodide worker in the browser (Pages), or natively in the `pydvma serve` process when the app is served locally"*.
- Add a short subsection to `docs/web-logger/index.md`'s bridge-mode description naming the engine indicator (BusyChip tooltip: "engine: local Python / browser") and the `?enginehost=` override.

Run: `python -m mkdocs build --strict` (repo root)
Expected: clean.

- [ ] **Step 3: CLAUDE.md + TODO.md**

- CLAUDE.md "Current focus": prepend a dated paragraph — native engine stages 0–2 landed (design + this plan's path), stages 3–4 (session journal, `dvma.launch`) are the next arc with their own plan.
- TODO.md: add stages 3–4 pointer; remove/adjust anything the engine move obsoleted (e.g. the old-wheel `_accepts_kw` probes in `pydvma/engine.py` are now vestigial — note as optional cleanup).

- [ ] **Step 4: Full suite gate (the round-close standard)**

Run (repo root): `pytest -q -m "not hardware"` → expected green.
Run (webui/): `npx vitest run && npm run check && npx playwright test --grep-invert @engine && npx playwright test --grep @engine --workers=1` → expected green.
Run (webui/): `BRIDGE_E2E=1 npx playwright test e2e/bridge.spec.ts e2e/engine-native.spec.ts --workers=1` → expected green.
Run (repo root): `python -m mkdocs build --strict` → expected clean.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "docs: native engine documented; CHANGELOG, CLAUDE.md focus, TODO next-arc pointers"
```

---

## Self-review notes (done at write time)

- **Spec coverage:** design §4.1 → Tasks 1–2; §4.2 → Tasks 3–5; §4.3 → Tasks 6–8; stage-2 flip + indicator + fallback → Tasks 8, 10; testing strategy §6 → per-task tests + Task 10 step 7 (regression floor) + Task 11 step 4 (full gate); §5 non-changes guarded by Task 5's bridge-alongside test and Task 9 step 3. Session journal / launch (§4.4–4.5) deliberately deferred to the stages-3–4 plan.
- **Known adaptation points** (flagged in-task, not placeholders): BusyChip root markup (Task 8 step 6), EngineProbe status selector + self-test result shape (Task 9 step 1) — both instruct the implementer to read the real component first and adapt assertions to it.
- **Type consistency:** `EngineWsLike`/`ResolvedEngine`/`EngineHostKind`/`decideEnginePolicy` names used consistently across Tasks 7–10; Python `EngineWorker.request` tuple shape consistent between Tasks 4 and 5.
- **Risk watch during execution:** if `websocket.request.path` is unavailable in the installed websockets version, the fallback is routing state captured in `_process_request` — surface it rather than hacking around; if spawn-context Queue pickling of the results dict trips on any op's return type (all are dicts of ndarrays/scalars/lists — expected fine), fix by normalising in `_worker_main`, never by changing op signatures.
