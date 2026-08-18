# Session Journal + `dvma.launch` (stages 3–4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.
> House rules: edit master directly, commit per task, NEVER `git stash`
> or `git reset` in the shared tree, run Playwright ONLY from `webui/`.

**Goal:** The `pydvma-serve` process owns the session document (closing
the tab loses nothing; reopening offers a restore), and
`dvma.launch(settings)` starts the whole logger from a notebook kernel
with `session.data` / `session.push` pull/push access — the successor
to the removed `dvma.Logger`.

**Architecture:** Stage 3 adds a `SessionJournal` (in-memory
authoritative doc + best-effort spill file) owned by `BridgeServer`,
fed by two writers — the app's existing debounced autosave (a new
`journal_set` op on the `/engine` socket) and the serve log path
(captures registered at birth) — and read back by `journal_get` on
reconnect (the app reuses its existing "Restore last session?" toast).
Stage 4 adds `pydvma/session.py`: `launch()` runs `BridgeServer` on a
background thread with its own asyncio loop; `Session.data`
materialises pydvma objects from the journal, `Session.push` merges a
dataset in and notifies the app over `/engine`.

**Design doc:** `dev/plans/2026-08-17-native-engine-design.md` §4.4–4.5
(ownership model §3.1; testing §6; staging §7). Stages 0–2 are landed
and verified on both benches.

**Tech stack:** Python 3.11+ (`websockets` asyncio, `threading`,
`zipfile`/`io`), TypeScript (Svelte 5, vitest, Playwright).

---

## Decisions taken in this plan (approve/adjust before execution)

1. **Restore is an OFFER, not an auto-restore.** Native mode reuses the
   exact "Restore last session?" toast the app already shows for
   IndexedDB autosaves (App.svelte `bootFileRestore`). Flipping to
   auto-restore later is a one-line change; offering keeps Pages and
   native behaviour identical. (Design left this open — "UX decided at
   implementation".)
2. **When both exist, the server document wins.** On boot in native
   mode the app asks the journal first; only if the journal is empty
   does the IndexedDB offer appear. Rationale: in native mode the
   journal is written by the same autosaves that feed IndexedDB, plus
   captures at birth — it is always at least as new.
3. **Spill file** = `<tempdir>/pydvma-session-<pid>.dvma`, best-effort,
   written on every journal update, path printed at serve start. It is
   an ordinary `.dvma` the user can open by hand after a serve crash.
   Serve does NOT auto-load it on start — the journal's restore scope
   is tab-close/reopen while serve lives (the design's promise);
   crash recovery stays manual-but-possible.
4. **`/engine` protocol version stays 1.** The journal ops are
   additive and capability-gated: `/ws` capabilities advertise
   `engine: {v, pydvma, journal: true}`; an app without the flag never
   sends journal ops, an old server never receives them. (The
   socketClient's exact-`v` gate is untouched.)
5. **`session.push` appends** (a new dataset merged into the doc, the
   app notified to reload) — no in-place mutation semantics, matching
   the design's "explicit handoff, not shared mutation".
6. **Module is `pydvma/session.py`** (`launch` + `Session`), not
   `launch.py`: the lazy-name registry in `pydvma/__init__.py` returns
   the MODULE when the lazy name equals the module basename, so a
   `launch.py` would make `dvma.launch(...)` a module call. `'launch':
   '.session'` resolves the function attribute per the existing
   `PlotData` pattern.

## Verified facts this plan relies on (explored 2026-08-18)

- `engine_host.handle_connection(websocket)` (serve.py:1300) owns the
  `/engine` loop; every decoded op goes to the worker subprocess via
  `worker.request`. Journal ops must be intercepted BEFORE that
  dispatch (the calc worker knows only `pydvma.engine` ops).
- The `/engine` frame codec already carries raw bytes: blob kind
  `'bytes'` (`engine_host.encode_frame`/`decode_frame`), so `.dvma`
  bytes ride the existing frames with no codec change.
- `serve._capture_to_dvma` (serve.py:930) already produces the capture
  `.dvma` bytes; `_Connection._on_log` sends them at serve.py:1830 via
  `encode_container` — the add-capture hook point.
- `_Connection` is constructed in `BridgeServer._handler`
  (serve.py:1302) — the journal handle threads through there.
- `build_capabilities` puts `engine: {'v': ENGINE_PROTOCOL_VERSION,
  'pydvma': ...}` in the `/ws` capabilities (serve.py:916–922).
- App autosave: `webui/src/lib/files/autosave.ts` — debounced thunk;
  `persist()` is the single write point. App.svelte:425–428 schedules
  it on every dataset mutation; App.svelte `bootFileRestore`
  (473–504) shows the restore toast from `restoreOffer()`.
- `container.save(dataset, filename)` / `container.load(filename)`;
  `load` opens `zipfile.ZipFile(filename)`, which accepts file
  objects. `save` writes tempfile-then-rename (path semantics).
- `_SETTINGS_WHITELIST` (serve.py:338) is derived from the
  `MySettings.__init__` signature — reuse it to serialise a
  `MySettings` into the `/config` prefill JSON.
- Tombstones: `pydvma/__init__.py` `_REMOVED_NAMES` /
  `_REMOVED_MESSAGE` (currently points at `pydvma-serve --open`).
- Ports already claimed by e2e specs: 8763 (`bridge.spec.ts`), 8765
  (`bla.spec.ts` BLA_BRIDGE_PORT), 8766 (`engine-native.spec.ts`).
  This plan claims **8767** and must add itself to the claimants
  comment in `engine-native.spec.ts`.

**File map:**

- Create: `pydvma/journal.py` — `SessionJournal` (doc + captures +
  listeners + spill; thread-safe; no asyncio, no websockets).
- Create: `pydvma/session.py` — `launch()`, `Session`,
  `_settings_to_config_json()`.
- Create: `tests/test_journal.py`, `tests/test_session_launch.py`.
- Modify: `pydvma/engine_host.py` — journal op interception +
  journal-update notify frames on `/engine`.
- Modify: `pydvma/serve.py` — `BridgeServer` owns a journal;
  `_Connection` gets the handle; `_on_log` registers captures;
  capabilities advertise `journal: true`.
- Modify: `pydvma/container.py` — `save_bytes` / `load_bytes`.
- Modify: `pydvma/__init__.py` — lazy names + tombstone text.
- Modify: `tests/test_engine_host.py`, `tests/test_serve_protocol.py`,
  `tests/test_container.py`.
- Modify: `webui/src/lib/files/autosave.ts` (+ its vitest) — journal
  sink.
- Modify: `webui/src/lib/worker/socketClient.ts` (+ vitest) — journal
  text-frame → subscriber callbacks.
- Modify: `webui/src/lib/stores/engine.ts` — `journalSet` /
  `journalGet` / `journalAvailable` / `onJournalUpdate` helpers.
- Modify: `webui/src/App.svelte` — sink wiring + native restore path.
- Create: `webui/e2e/session-journal.spec.ts` (BRIDGE_E2E, port 8767).
- Docs: `docs/web-logger/migration.md`, `docs/web-logger/index.md`,
  `docs/examples/basic.md`, `CHANGELOG.md`.

---

## Stage 3 — session journal

### Task 1: `SessionJournal` (pure Python store)

**Files:**
- Create: `pydvma/journal.py`
- Create: `tests/test_journal.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_journal.py
"""SessionJournal: the serve process's in-memory session store.

Pure-Python (no websockets, no asyncio): doc replace, capture
registration, the clears-pending contract, listener fan-out and the
best-effort spill file.
"""
import threading

from pydvma.journal import SessionJournal


class TestDocAndCaptures:

    def test_empty_state(self):
        j = SessionJournal()
        doc, captures = j.state()
        assert doc is None
        assert captures == []

    def test_set_doc_replaces(self):
        j = SessionJournal()
        j.set_doc(b'v1')
        j.set_doc(b'v2')
        doc, _ = j.state()
        assert doc == b'v2'

    def test_add_capture_accumulates_in_order(self):
        j = SessionJournal()
        j.add_capture(b'c1')
        j.add_capture(b'c2')
        _, captures = j.state()
        assert captures == [b'c1', b'c2']

    def test_set_doc_clears_pending_captures(self):
        # A doc posted by the app AFTER a capture arrived includes that
        # capture (the app serialises its dataset at post time), so the
        # pending copy is redundant the moment a doc lands.
        j = SessionJournal()
        j.add_capture(b'c1')
        j.set_doc(b'doc')
        _, captures = j.state()
        assert captures == []

    def test_capture_after_doc_stays_pending(self):
        j = SessionJournal()
        j.set_doc(b'doc')
        j.add_capture(b'c1')
        doc, captures = j.state()
        assert doc == b'doc'
        assert captures == [b'c1']

    def test_state_returns_copies(self):
        j = SessionJournal()
        j.add_capture(b'c1')
        _, captures = j.state()
        captures.append(b'evil')
        assert j.state()[1] == [b'c1']


class TestListeners:

    def test_notify_fans_out(self):
        j = SessionJournal()
        hits = []
        j.add_listener(lambda: hits.append(1))
        j.add_listener(lambda: hits.append(2))
        j.set_doc(b'doc', notify=True)
        assert sorted(hits) == [1, 2]

    def test_set_doc_without_notify_is_silent(self):
        j = SessionJournal()
        hits = []
        j.add_listener(lambda: hits.append(1))
        j.set_doc(b'doc')
        assert hits == []

    def test_remove_listener(self):
        j = SessionJournal()
        hits = []
        unsub = j.add_listener(lambda: hits.append(1))
        unsub()
        j.set_doc(b'doc', notify=True)
        assert hits == []

    def test_listener_error_does_not_break_others(self):
        j = SessionJournal()
        hits = []

        def bad():
            raise RuntimeError('boom')

        j.add_listener(bad)
        j.add_listener(lambda: hits.append(1))
        j.set_doc(b'doc', notify=True)
        assert hits == [1]


class TestSpill:

    def test_set_doc_spills_to_file(self, tmp_path):
        spill = tmp_path / 'session.dvma'
        j = SessionJournal(spill_path=spill)
        j.set_doc(b'doc-bytes')
        assert spill.read_bytes() == b'doc-bytes'

    def test_spill_failure_is_swallowed(self, tmp_path):
        # Best-effort: an unwritable spill path must never break the op.
        j = SessionJournal(spill_path=tmp_path / 'no' / 'such' / 'dir' / 'f.dvma')
        j.set_doc(b'doc')          # must not raise
        assert j.state()[0] == b'doc'


class TestThreadSafety:

    def test_concurrent_writers(self):
        j = SessionJournal()
        n = 200

        def capture_writer():
            for i in range(n):
                j.add_capture(b'c%d' % i)

        def doc_writer():
            for i in range(n):
                j.set_doc(b'd%d' % i)

        threads = [threading.Thread(target=capture_writer),
                   threading.Thread(target=doc_writer)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        doc, captures = j.state()
        assert doc == b'd%d' % (n - 1)
        # Pending list is consistent (no torn state); exact content
        # depends on interleaving.
        assert all(c.startswith(b'c') for c in captures)
```

- [ ] **Step 2: Run to verify failure**

Run (repo root): `python -m pytest tests/test_journal.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pydvma.journal'`

- [ ] **Step 3: Implement `pydvma/journal.py`**

```python
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
``.dvma`` the user can open by hand if the serve process dies. It is
never auto-loaded; the journal's restore scope is tab-close/reopen
while the serve process lives.
"""
import threading


class SessionJournal(object):
    """In-memory session document + pending captures + listeners.

    Args:
        spill_path (pathlib.Path or str or None): file to mirror the
            current document into on every update (best-effort; errors
            are swallowed). ``None`` disables spilling.
    """

    def __init__(self, spill_path=None):
        self._lock = threading.Lock()
        self._doc = None
        self._captures = []
        self._listeners = []
        self._spill_path = spill_path

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

    def _spill(self):
        """Mirror the current doc to ``spill_path``, best-effort."""
        if self._spill_path is None:
            return
        with self._lock:
            doc = self._doc
        if doc is None:
            return
        try:
            with open(self._spill_path, 'wb') as fh:
                fh.write(doc)
        except OSError:
            pass
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_journal.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add pydvma/journal.py tests/test_journal.py
git commit -m "feat(journal): SessionJournal — serve-side session store (stage 3 groundwork)"
```

### Task 2: Journal ops + notify on the `/engine` socket

**Files:**
- Modify: `pydvma/engine_host.py` (handle_connection)
- Modify: `tests/test_engine_host.py` (the ws mini-harness added in the
  stage-1 plan is already there — extend it)

- [ ] **Step 1: Write the failing tests** (append to
  `tests/test_engine_host.py`; reuse the file's existing
  websocket-harness fixtures — read the file's harness section first
  and follow its patterns for spinning up `handle_connection`)

```python
class TestJournalOps:
    """journal_set / journal_get are answered by the HOST inline (never
    the calc worker), and a notify-listener broadcast reaches the
    client as a text frame."""

    async def _connect(self, journal):
        # Use the file's existing pattern for serving
        # handle_connection on an ephemeral port; pass journal=journal.
        raise NotImplementedError  # replace with the harness call

    async def test_journal_set_stores_doc(self, journal_server):
        ws, journal = journal_server
        await ws.send(encode_frame({'id': 1, 'op': 'journal_set',
                                    'payload': {'doc': b'DOCBYTES'}}))
        reply = decode_frame(await recv_binary(ws))
        assert reply['ok'] is True
        assert journal.state()[0] == b'DOCBYTES'

    async def test_journal_get_returns_doc_and_captures(self, journal_server):
        ws, journal = journal_server
        journal.set_doc(b'DOC')
        journal.add_capture(b'CAP1')
        await ws.send(encode_frame({'id': 2, 'op': 'journal_get',
                                    'payload': {}}))
        reply = decode_frame(await recv_binary(ws))
        assert reply['ok'] is True
        assert reply['result']['doc'] == b'DOC'
        assert reply['result']['captures'] == [b'CAP1']

    async def test_journal_get_empty(self, journal_server):
        ws, journal = journal_server
        await ws.send(encode_frame({'id': 3, 'op': 'journal_get',
                                    'payload': {}}))
        reply = decode_frame(await recv_binary(ws))
        assert reply['ok'] is True
        assert reply['result']['doc'] is None
        assert reply['result']['captures'] == []

    async def test_journal_op_without_journal_errors(self, plain_server):
        # handle_connection(websocket) with no journal: a journal op
        # must get an ok=False reply, not reach the calc worker.
        ws = plain_server
        await ws.send(encode_frame({'id': 4, 'op': 'journal_set',
                                    'payload': {'doc': b'x'}}))
        reply = decode_frame(await recv_binary(ws))
        assert reply['ok'] is False
        assert 'journal' in reply['error']

    async def test_push_notify_reaches_client_as_text_frame(self, journal_server):
        ws, journal = journal_server
        journal.set_doc(b'DOC', notify=True)
        msg = json.loads(await recv_text(ws))
        assert msg == {'type': 'journal', 'event': 'updated'}
```

(The `journal_server` / `plain_server` fixtures and the
`recv_binary`/`recv_text` helpers follow the harness conventions
already in the file — write them against those, filtering the
`engine_ready` greeting the same way the existing tests do.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_engine_host.py -q -k Journal`
Expected: FAIL — `handle_connection() got an unexpected keyword
argument 'journal'` (or ok=False replies), per test.

- [ ] **Step 3: Implement in `engine_host.py`**

Signature: `async def handle_connection(websocket, journal=None):` —
document the new arg in its docstring ("`journal` is the serve
process's `pydvma.journal.SessionJournal`; None (e.g. a bare test
harness) declines journal ops with an error reply").

Immediately after the greeting `send` succeeds, register the notify
listener (and add the matching cleanup in the outer `finally`):

```python
    unsubscribe_journal = None
    if journal is not None:
        def _notify_journal_update():
            fut = asyncio.run_coroutine_threadsafe(
                websocket.send(json.dumps(
                    {'type': 'journal', 'event': 'updated'})), loop)
            fut.add_done_callback(lambda f: f.exception())
        unsubscribe_journal = journal.add_listener(_notify_journal_update)
```

In the frame loop, after `rid`/`op`/`payload` decode and BEFORE the
`worker.request` dispatch:

```python
            if op in ('journal_set', 'journal_get'):
                if journal is None:
                    reply = {'id': rid, 'ok': False,
                             'error': 'no session journal on this server'}
                elif op == 'journal_set':
                    doc = payload.get('doc')
                    if not isinstance(doc, (bytes, bytearray)):
                        reply = {'id': rid, 'ok': False,
                                 'error': 'journal_set needs doc bytes'}
                    else:
                        journal.set_doc(doc)
                        reply = {'id': rid, 'ok': True, 'result': {}}
                else:
                    doc, captures = journal.state()
                    reply = {'id': rid, 'ok': True,
                             'result': {'doc': doc, 'captures': captures}}
                try:
                    await websocket.send(encode_frame(reply))
                except ConnectionClosed:
                    break
                continue
```

In the outer `finally`, before the worker teardown:

```python
        if unsubscribe_journal is not None:
            unsubscribe_journal()
```

NOTE: `encode_frame` must accept `None` inside the result dict (doc
can be None) — it already passes non-array values through as JSON;
verify with the empty-journal test.

- [ ] **Step 4: Run the engine-host suite**

Run: `python -m pytest tests/test_engine_host.py -q`
Expected: all PASS (old tests untouched — `journal=None` default).

- [ ] **Step 5: Commit**

```bash
git add pydvma/engine_host.py tests/test_engine_host.py
git commit -m "feat(engine-host): journal_set/journal_get ops + journal-update notify frames"
```

### Task 3: Serve wiring — journal ownership, capture registration, capability

**Files:**
- Modify: `pydvma/serve.py`
- Modify: `tests/test_serve_protocol.py`

- [ ] **Step 1: Write the failing tests** (append to
  `tests/test_serve_protocol.py`, following its live-server patterns —
  `test_cancel_stops_monitor` at line 958 is the template for the
  end-to-end one)

```python
def test_build_capabilities_advertises_journal():
    caps = serve.build_capabilities()
    assert caps['engine']['journal'] is True


def test_log_registers_capture_in_journal():
    # Live mock-driver server; after a log completes, the server's
    # journal holds exactly one pending capture whose bytes load as a
    # one-TimeData .dvma (io.BytesIO + container.load).
    ...  # follow the file's spawn-server fixture; assert via a second
         # /engine connection's journal_get (the public read path).


def test_engine_connection_can_set_and_get_journal():
    # /engine round-trip against the REAL BridgeServer (not the bare
    # harness): journal_set then journal_get echoes the doc.
    ...
```

Write both `...` bodies fully, following the existing live-test
helpers in the file (`_send`, the async drain loops, the
spawned-server fixture). The capture assertion decodes
`result['captures'][0]` with `container.load(io.BytesIO(...))` and
checks `len(ds.time_data_list) == 1`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_serve_protocol.py -q -k journal`
Expected: FAIL — capabilities lack `journal`; journal_get errors.

- [ ] **Step 3: Implement in serve.py**

1. Import at top (with the existing `from . import engine_host`):
   `from . import journal as journal_mod`.
2. `BridgeServer.__init__` gains a journal (document it in the class
   docstring's Args):

```python
        import tempfile
        self.journal = journal_mod.SessionJournal(
            spill_path=Path(tempfile.gettempdir())
            / ('pydvma-session-%d.dvma' % os.getpid()))
```

3. `_handler`: `/engine` branch becomes
   `await engine_host.handle_connection(websocket, journal=self.journal)`;
   the `_Connection` construction becomes
   `conn = _Connection(websocket, journal=self.journal)`.
4. `_Connection.__init__(self, websocket, journal=None)` stores
   `self._journal = journal` (docstring: "captures register here at
   birth — stage 3").
5. In `_on_log`, at the point `_capture_to_dvma` has returned
   (serve.py:~1820–1830, just before `encode_container`):

```python
        if self._journal is not None:
            self._journal.add_capture(dvma_bytes)
```

6. In `build_capabilities`'s engine dict (serve.py:916–922) add
   `'journal': True,`.
7. In `main()`, after the server is constructed, print the spill path
   once: `print('session journal spill: %s' % server.journal._spill_path)`
   — expose a small `spill_path` property instead of reaching into the
   private attr:  add `@property def spill_path(self)` on
   `SessionJournal` returning `self._spill_path`, and print that.

- [ ] **Step 4: Run the serve suite**

Run: `python -m pytest tests/test_serve_protocol.py tests/test_engine_host.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pydvma/serve.py pydvma/journal.py tests/test_serve_protocol.py
git commit -m "feat(serve): BridgeServer owns a SessionJournal — captures at birth, journal capability"
```

### Task 4: App autosave gains the journal sink

**Files:**
- Modify: `webui/src/lib/files/autosave.ts`
- Modify: `webui/src/lib/files/autosave.test.ts` (or the vitest file
  covering autosave — locate with `rg -l "autosave" webui/src --glob '*.test.ts'`)

- [ ] **Step 1: Write the failing tests** (same fake-timer patterns as
  the file's existing tests)

```typescript
describe('journal sink', () => {
  it('persist() also posts to a registered journal sink', async () => {
    const posted: Uint8Array[] = [];
    setJournalSink((b) => posted.push(b));
    autosave(() => new Uint8Array([1, 2, 3]), null, true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(posted).toHaveLength(1);
    expect([...posted[0]]).toEqual([1, 2, 3]);
    setJournalSink(null);
  });

  it('sink errors never break the idb write', async () => {
    setJournalSink(() => { throw new Error('socket gone'); });
    autosave(() => new Uint8Array([9]), null, true);
    await vi.advanceTimersByTimeAsync(2000);
    // idb still received the bytes (assert via the fake idb store).
    setJournalSink(null);
  });

  it('no sink registered → unchanged behaviour', async () => {
    autosave(() => new Uint8Array([7]), null, true);
    await vi.advanceTimersByTimeAsync(2000);
    // fake idb store has the bytes; nothing thrown.
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `webui/`): `npx vitest run src/lib/files/autosave.test.ts`
Expected: FAIL — `setJournalSink` not exported.

- [ ] **Step 3: Implement in autosave.ts**

```typescript
/**
 * Optional second autosave target: the pydvma-serve session journal
 * (native-engine stage 3). When registered, every persisted autosave
 * is ALSO handed to the sink (which posts it over /engine as a
 * journal_set op). Best-effort and fire-and-forget, exactly like the
 * idb/folder write: a sink failure (socket closed mid-write) must
 * never break the local autosave. Registered by App.svelte when the
 * native engine + journal capability are live; cleared on fallback.
 */
export type JournalSink = (bytes: Uint8Array) => void;
let journalSink: JournalSink | null = null;
export function setJournalSink(next: JournalSink | null): void {
  journalSink = next;
}
```

and in `persist()`, before the try/catch (both branches must feed it):

```typescript
  if (journalSink) {
    try {
      journalSink(bytes);
    } catch (e) {
      console.warn('[autosave] journal sink failed:', e);
    }
  }
```

- [ ] **Step 4: Run vitest + check**

Run (from `webui/`): `npx vitest run src/lib/files && npm run check`
Expected: PASS / 0 errors.

- [ ] **Step 5: Commit**

```bash
git add webui/src/lib/files/autosave.ts webui/src/lib/files/*.test.ts
git commit -m "feat(webui): autosave journal sink — second target for the serve session journal"
```

### Task 5: App-side journal plumbing (socketClient event + engine-store helpers + App wiring)

**Files:**
- Modify: `webui/src/lib/worker/socketClient.ts` (+ its vitest — find
  with `rg -l "socketClient" webui/src --glob '*.test.ts'`)
- Modify: `webui/src/lib/stores/engine.ts`
- Modify: `webui/src/App.svelte`

**Read first:** `socketClient.ts` in full (the text-frame `onmessage`
dispatch), `engine.ts` in full (how the active client is held and how
`selectEngine.ts` resolves native), and App.svelte's
`bootFileRestore`. Adapt the names below to the store's actual client
handle — the SHAPES are specified here, the anchors are in those
files.

- [ ] **Step 1: socketClient — journal frames.** The text-frame
  handler currently dispatches `engine_ready` / `progress` / `error`.
  Add a `'journal'` case that fans out to subscribers, plus:

```typescript
/** Subscribers to server-initiated journal updates (Session.push). */
const journalSubs = new Set<() => void>();
export function onJournalUpdate(cb: () => void): () => void {
  journalSubs.add(cb);
  return () => journalSubs.delete(cb);
}
// in the text-frame dispatch:
//   case 'journal': for (const cb of journalSubs) cb(); break;
```

Vitest (fake-socket pattern already in the file's tests): a text frame
`{"type":"journal","event":"updated"}` invokes a registered callback;
unsubscribe stops it; an unknown text type stays ignored.

- [ ] **Step 2: engine-store helpers.** In `stores/engine.ts` export:

```typescript
/** True when the active engine is the native socket AND the serve
 *  capabilities advertised a session journal. */
export function journalAvailable(): boolean { ... }

/** Post the session doc to the serve journal (journal_set). */
export async function journalSet(doc: Uint8Array): Promise<void> { ... }

/** Fetch the serve journal (journal_get). */
export async function journalGet(): Promise<{
  doc: Uint8Array | null;
  captures: Uint8Array[];
}> { ... }
```

Implemented via the active `EngineClient`'s existing `call(op,
payload)` path (journal ops ride the same frames as calc ops) and the
capabilities snapshot the store already holds from engine resolution
(`engine: {v, pydvma, journal}` — thread the `journal` flag through
`selectEngine.ts`'s capability check the same way `v`/`pydvma` flow).
Fill the `...` bodies against the real store internals; each helper is
< 10 lines.

- [ ] **Step 3: App.svelte wiring.** Three additions:

1. When the native engine reaches `ready` and `journalAvailable()`:
   `setJournalSink((bytes) => void journalSet(bytes).catch(() => {}))`;
   clear the sink (`setJournalSink(null)`) on engine fallback/restart.
2. `bootFileRestore` grows a native-first branch: if
   `journalAvailable()` (await the engine resolution the same way the
   boot path awaits the engine store), call `journalGet()`; when
   `doc !== null || captures.length > 0` show the existing restore
   toast wired to a `restoreFromJournal(doc, captures)` helper:

```typescript
  function restoreFromJournal(doc: Uint8Array | null, captures: Uint8Array[]): void {
    if (doc) loadAndFocus(readDvma(doc));
    for (const c of captures) {
      actions.loadDataset(readDvma(c), { append: true });
    }
  }
```

   and SKIP the IndexedDB offer in that case (decision 2). The toast
   copy: `'Restore session from pydvma-serve?'` with
   Restore / Dismiss (Dismiss does nothing server-side — the journal
   stays authoritative).
3. Subscribe `onJournalUpdate` (when native): on fire, `journalGet()`
   and append ONLY the delta — implementation: `Session.push` replaces
   the whole doc, so the simple correct move is: if the local dataset
   is empty, load the doc; otherwise offer a toast
   `'pydvma session updated from notebook — reload?'` with a Reload
   action that calls `restoreFromJournal` after clearing the current
   dataset (`actions.loadDataset(readDvma(doc))` without append is
   exactly that). Never silently clobber local unsaved work.

- [ ] **Step 4: Suites**

Run (from `webui/`): `npx vitest run && npm run check`
Expected: PASS / 0 errors.

- [ ] **Step 5: Commit**

```bash
git add webui/src/lib/worker/socketClient.ts webui/src/lib/stores/engine.ts webui/src/App.svelte webui/src/lib/worker/*.test.ts
git commit -m "feat(webui): serve session journal — autosave posts, reconnect restore, push notify"
```

### Task 6: Session-restore e2e (also closes the real-app-over-socket gap)

**Files:**
- Create: `webui/e2e/session-journal.spec.ts`
- Modify: `webui/e2e/engine-native.spec.ts` (the port-claimants
  comment: add 8767)

- [ ] **Step 1: Write the spec.** BRIDGE_E2E-gated, mirroring
  `engine-native.spec.ts`'s arrangement (spawn
  `pydvma-serve --driver mock --port 8767` serving the built dist, so
  the native engine is the default). Flow:

```typescript
// 1. page A: open the served app; wait for the native engine
//    (console message '[engine-socket] native engine', same wait the
//    engine-native spec uses).
// 2. Log Data (mock driver) → wait for time-view lines.
// 3. Calc FFT → wait for freq-view lines.  ← the calc path through
//    /engine in the REAL app: closes the TODO coverage gap.
// 4. Wait >2.5 s (autosave debounce) so journal_set lands.
// 5. page A: close. Open page B (same URL, fresh context page —
//    NOT a fresh browser profile; IndexedDB isolation is not the
//    point, the JOURNAL restore is).
// 6. Expect the 'Restore session from pydvma-serve?' toast; click
//    Restore.
// 7. Assert the time AND freq views have the restored lines
//    (toBeAttached, not toBeVisible — SVG zero-height bbox gotcha).
```

Write the real Playwright code following `engine-native.spec.ts`'s
helpers (server spawn/teardown, console-message waits, line-count
assertions). Keep the round-7 standard where pixels are claimed:
line presence via attached SVG paths is enough here (no canvas).

- [ ] **Step 2: Run it**

Run (from `webui/`, after `npm run build` if the dist is stale):
`BRIDGE_E2E=1 npx playwright test e2e/session-journal.spec.ts --workers=1`
Expected: PASS.

- [ ] **Step 3: Run the neighbouring bridge specs (port hygiene)**

Run: `BRIDGE_E2E=1 npx playwright test e2e/bridge.spec.ts e2e/engine-native.spec.ts e2e/session-journal.spec.ts --workers=1`
Expected: PASS — no port collisions (8763/8766/8767).

- [ ] **Step 4: Commit**

```bash
git add webui/e2e/session-journal.spec.ts webui/e2e/engine-native.spec.ts
git commit -m "test(e2e): session-journal restore through a real serve — capture, FFT over /engine, close, reopen, restore"
```

---

## Stage 4 — `dvma.launch`

### Task 7: `container.save_bytes` / `load_bytes`

**Files:**
- Modify: `pydvma/container.py`
- Modify: `tests/test_container.py`

- [ ] **Step 1: Write the failing tests** (append to
  `tests/test_container.py`, reusing its dataset fixtures)

```python
class TestBytesRoundTrip:

    def test_save_bytes_load_bytes_round_trip(self, small_dataset):
        blob = container.save_bytes(small_dataset)
        ds = container.load_bytes(blob)
        assert len(ds.time_data_list) == len(small_dataset.time_data_list)

    def test_load_bytes_equals_load_file(self, small_dataset, tmp_path):
        p = tmp_path / 'x.dvma'
        container.save(small_dataset, p)
        assert container.load_bytes(p.read_bytes()) is not None

    def test_save_bytes_output_is_a_zip(self, small_dataset):
        assert container.save_bytes(small_dataset)[:2] == b'PK'
```

(`small_dataset` — use whatever fixture/builder the file already has;
if none is importable, build a one-TimeData DataSet inline the way the
file's other tests do.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_container.py -q -k Bytes`
Expected: FAIL — no attribute `save_bytes`.

- [ ] **Step 3: Implement.** Read `container.save` first. If its body
  is `zipfile.ZipFile(tmpname, 'w')` + member writes + rename, extract
  the member-writing middle into `_write_dataset(zf, dataset)` and:

```python
def save_bytes(dataset):
    """Serialise a DataSet to ``.dvma`` container bytes in memory.

    Byte-for-byte the same archive :func:`save` writes (same manifest,
    same members) without touching the filesystem — for the session
    journal and :meth:`pydvma.session.Session.push`, which move
    documents over sockets rather than into files.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        _write_dataset(zf, dataset)
    return buf.getvalue()


def load_bytes(data):
    """Load a DataSet from in-memory ``.dvma`` container bytes.

    The bytes-side twin of :func:`load` (which see for the
    schema/version rules — both share the reader).
    """
    return load(io.BytesIO(data))
```

Match `save`'s compression arguments exactly (read them off the
existing call). If `load` does anything filename-specific beyond
`ZipFile(filename)`, lift the shared part the same way.

- [ ] **Step 4: Run the container suite**

Run: `python -m pytest tests/test_container.py -q`
Expected: all PASS.

- [ ] **Step 5: DRY follow-up — `serve._capture_to_dvma` uses it.**
Replace its tempfile dance (serve.py:962–964) with
`dvma_bytes = container.save_bytes(dataset)`; delete the now-unused
tempfile plumbing in that function; update its docstring ("written
through container.save_bytes — the one save story").

Run: `python -m pytest tests/test_serve_protocol.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add pydvma/container.py pydvma/serve.py tests/test_container.py
git commit -m "feat(container): save_bytes/load_bytes — in-memory .dvma for journal + session push"
```

### Task 8: `pydvma/session.py` — `launch()` + `Session`

**Files:**
- Create: `pydvma/session.py`
- Create: `tests/test_session_launch.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_session_launch.py
"""dvma.launch / Session: background-thread server, pull/push, close.

Mock driver end to end — no hardware, no browser (open_browser=False
throughout). Ephemeral ports only (port=0), so the suite parallelises.
"""
import asyncio
import io
import threading

import numpy as np
import pytest

pytest.importorskip('websockets')

import pydvma as dvma
from pydvma import container, datastructure, options
from pydvma.session import launch, _settings_to_config_json


def _mock_settings():
    return options.MySettings(device_driver='mock', channels=2,
                              fs=8000, stored_time=0.1)


def _tiny_dataset(name='pushed'):
    td = datastructure.TimeData(
        time_axis=np.arange(80) / 8000.0,
        time_data=np.zeros((80, 1)),
        settings=_mock_settings(), test_name=name)
    return datastructure.DataSet(td)


class TestLaunchLifecycle:

    def test_launch_starts_and_closes(self):
        session = launch(_mock_settings(), open_browser=False, port=0)
        try:
            assert session.url.startswith('http://127.0.0.1:')
        finally:
            session.close()
        # close() joins the server thread
        assert not session._thread.is_alive()

    def test_launch_inside_running_loop(self):
        # The kernel-thread asyncio clash (design doc, risks): launch
        # must work when the CALLER already runs an asyncio loop
        # (Jupyter). It runs the server on its own thread + loop, so a
        # running caller loop must not matter.
        async def run():
            s = launch(_mock_settings(), open_browser=False, port=0)
            s.close()
            return True
        assert asyncio.run(run()) is True

    def test_context_manager(self):
        with launch(_mock_settings(), open_browser=False, port=0) as s:
            assert s.url
        assert not s._thread.is_alive()

    def test_config_prefill_served(self):
        import json
        import urllib.request
        with launch(_mock_settings(), open_browser=False, port=0) as s:
            cfg = json.loads(urllib.request.urlopen(
                s.url + 'config', timeout=5).read())
        assert cfg['device_driver'] == 'mock'
        assert cfg['fs'] == 8000


class TestSessionData:

    def test_empty_session_data(self):
        with launch(_mock_settings(), open_browser=False, port=0) as s:
            ds = s.data
        assert len(ds.time_data_list) == 0

    def test_push_then_data_round_trip(self):
        with launch(_mock_settings(), open_browser=False, port=0) as s:
            s.push(_tiny_dataset())
            ds = s.data
        assert len(ds.time_data_list) == 1
        assert ds.time_data_list[0].test_name == 'pushed'

    def test_push_timedata_wraps(self):
        with launch(_mock_settings(), open_browser=False, port=0) as s:
            s.push(_tiny_dataset().time_data_list[0])
            assert len(s.data.time_data_list) == 1

    def test_push_appends_to_existing_doc(self):
        with launch(_mock_settings(), open_browser=False, port=0) as s:
            s._server.journal.set_doc(container.save_bytes(_tiny_dataset('a')))
            s.push(_tiny_dataset('b'))
            names = [t.test_name for t in s.data.time_data_list]
        assert names == ['a', 'b']

    def test_data_includes_pending_captures(self):
        with launch(_mock_settings(), open_browser=False, port=0) as s:
            s._server.journal.add_capture(
                container.save_bytes(_tiny_dataset('cap')))
            names = [t.test_name for t in s.data.time_data_list]
        assert names == ['cap']


class TestSettingsToConfigJson:

    def test_json_safe_and_whitelisted(self):
        d = _settings_to_config_json(_mock_settings())
        import json
        json.dumps(d)                      # must be JSON-serialisable
        assert d['device_driver'] == 'mock'
        assert 'device_full_info' not in d  # non-JSON fields dropped

    def test_none_settings_gives_empty(self):
        assert _settings_to_config_json(None) == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_session_launch.py -q`
Expected: FAIL — `No module named 'pydvma.session'`.

- [ ] **Step 3: Implement `pydvma/session.py`**

```python
# -*- coding: utf-8 -*-
"""The notebook front door: ``dvma.launch(settings)`` (stage 4).

Successor to the removed ``dvma.Logger``. Starts the full
``pydvma-serve`` stack — acquisition bridge, native ``/engine``
compute host, session journal, embedded web UI — on a background
thread INSIDE the kernel process, opens the browser, and returns a
:class:`Session` handle:

>>> import pydvma as dvma
>>> session = dvma.launch(dvma.MySettings(device_driver='nidaq',
...                                       fs=3000, channels=2))
>>> session.data          # live view of the session document
>>> session.push(dataset)  # hand data back; the app reloads
>>> session.close()

Explicit handoff, not shared mutation: :attr:`Session.data`
materialises fresh pydvma objects from the journal under its lock, and
:meth:`Session.push` is the only write path — the kernel never holds
live references the engine is concurrently computing on.

The server runs on ITS OWN thread and event loop, so ``launch()``
works identically from a plain script and from inside Jupyter (whose
kernel already runs an asyncio loop — the clash the design doc calls
out). The thread is a daemon: an exiting kernel never hangs on it.

The notebook is optional — ``pydvma-serve --open`` from a terminal
starts the same server with no kernel anywhere; the only difference is
that no one holds a :class:`Session`.
"""
import asyncio
import threading
import webbrowser

from . import container
from . import datastructure
from . import options


def _merge_dataset(target, source):
    """Append every item of ``source`` (a DataSet) into ``target``.

    ``DataSet.add_to_dataset`` accepts one item or one HOMOGENEOUS
    list, so a whole-DataSet merge walks the per-kind list attributes
    (``DataSet._LIST_ATTRS``) and appends each non-empty list.
    """
    from .datastructure import DataSet
    for name in DataSet._LIST_ATTRS:
        items = list(getattr(source, name, []) or [])
        if items:
            target.add_to_dataset(items)


def _settings_to_config_json(settings):
    """MySettings → the JSON dict served at ``/config`` (UI prefill).

    Uses :data:`pydvma.serve._SETTINGS_WHITELIST` (derived from the
    ``MySettings.__init__`` signature) so the launch path and the
    ``--settings`` CLI path accept exactly the same keys, and keeps
    only JSON-representable values — resolved runtime baggage like
    ``device_full_info`` is dropped, matching what a hand-written
    settings JSON could contain.
    """
    if settings is None:
        return {}
    from . import serve
    out = {}
    for name in sorted(serve._SETTINGS_WHITELIST):
        value = getattr(settings, name, None)
        if isinstance(value, (list, tuple)):
            if all(isinstance(v, (int, float, str, bool)) for v in value):
                out[name] = list(value)
        elif isinstance(value, (int, float, str, bool)) or value is None:
            out[name] = value
    return out


class Session(object):
    """Handle onto a running :func:`launch` server.

    ``data`` and ``push`` speak to the session journal directly (same
    process); the connected browser app is notified over ``/engine``
    and offers to reload. ``close()`` shuts the server down and joins
    its thread. Also a context manager (``with launch(...) as s:``).
    """

    def __init__(self, server, thread, loop, url):
        self._server = server
        self._thread = thread
        self._loop = loop
        self.url = url

    @property
    def data(self):
        """The session document as a fresh :class:`DataSet`.

        Rebuilt on every access from the journal's current state (doc
        plus any captures pending since the last app autosave) — a
        snapshot, never a live reference.
        """
        doc, captures = self._server.journal.state()
        if doc is not None:
            ds = container.load_bytes(doc)
        else:
            ds = datastructure.DataSet()
        for blob in captures:
            _merge_dataset(ds, container.load_bytes(blob))
        return ds

    def push(self, data):
        """Merge ``data`` (a DataSet or a single data object) into the
        session and notify connected apps.

        Appends to the current document (never replaces existing
        items) and posts the result as the new authoritative doc; the
        app shows a reload offer rather than silently replacing
        anything unsaved.
        """
        ds = self.data
        if isinstance(data, datastructure.DataSet):
            _merge_dataset(ds, data)
        else:
            ds.add_to_dataset(data)
        self._server.journal.set_doc(container.save_bytes(ds),
                                     notify=True)

    def close(self):
        """Stop the server and join its thread (idempotent)."""
        if self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def launch(settings=None, open_browser=True, port=0, ui_dir=None):
    """Start the web logger from Python and return a :class:`Session`.

    Args:
        settings (MySettings or None): initial acquisition settings,
            served to the UI as the ``/config`` prefill (same effect as
            ``pydvma-serve --settings``); also selects the default
            device driver. ``None`` starts unconfigured (mock driver).
        open_browser (bool): open the system browser at the app URL.
        port (int): TCP port; ``0`` picks a free one.
        ui_dir (str or Path or None): override the built-UI directory
            (defaults to the packaged ``pydvma/_webui``, falling back
            to the repo's ``webui/dist`` in a checkout).

    Returns the :class:`Session`. Raises ``RuntimeError`` if the
    server fails to bind within 10 seconds.
    """
    from . import serve
    resolved_ui = None
    if ui_dir is not None:
        from pathlib import Path
        resolved_ui = Path(ui_dir)
    else:
        resolved_ui = serve._packaged_ui_dir() or serve._repo_default_ui_dir()

    driver = getattr(settings, 'device_driver', None) or 'mock'
    server = serve.BridgeServer(
        port=port, ui_dir=resolved_ui,
        settings_json=_settings_to_config_json(settings),
        default_driver=driver)

    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def _run():
        asyncio.set_event_loop(loop)
        task = loop.create_task(server.run())

        def _watch_bind():
            if server.sockets:
                ready.set()
            elif task.done():
                ready.set()          # failed — surfaced below
            else:
                loop.call_later(0.05, _watch_bind)
        loop.call_soon(_watch_bind)
        try:
            loop.run_forever()
        finally:
            task.cancel()
            try:
                loop.run_until_complete(task)
            except (asyncio.CancelledError, Exception):
                pass
            loop.close()

    thread = threading.Thread(target=_run, name='pydvma-serve',
                              daemon=True)
    thread.start()
    if not ready.wait(timeout=10) or not server.sockets:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        raise RuntimeError(
            'pydvma-serve failed to start (port %r in use?)' % (port,))

    real_port = server.sockets[0].getsockname()[1]
    url = 'http://127.0.0.1:%d/' % real_port
    session = Session(server, thread, loop, url)
    print('pydvma web logger: %s' % url)
    if open_browser:
        webbrowser.open(url)
    return session
```

(API verified at plan time: `DataSet.add_to_dataset` takes one item or
one homogeneous list; `DataSet._LIST_ATTRS` names the seven per-kind
lists; `DataSet()` constructs empty; `TimeData(time_axis, time_data,
settings, ..., test_name=...)` matches the test fixture.)

- [ ] **Step 4: Run the launch tests**

Run: `python -m pytest tests/test_session_launch.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pydvma/session.py tests/test_session_launch.py
git commit -m "feat(session): dvma.launch + Session — the notebook front door (stage 4)"
```

### Task 9: Package surface — lazy names + tombstone successor

**Files:**
- Modify: `pydvma/__init__.py`
- Modify: `tests/test_packaging.py` (or wherever the tombstone/lazy
  tests live — `rg -l "_REMOVED_NAMES" tests/`)

- [ ] **Step 1: Failing tests** (append next to the existing
  tombstone tests):

```python
def test_launch_is_importable_lazily():
    import pydvma as dvma
    assert callable(dvma.launch)
    from pydvma.session import Session
    assert dvma.Session is Session


def test_tombstone_names_launch():
    import pydvma as dvma
    with pytest.raises(AttributeError, match='dvma.launch'):
        dvma.Logger
```

- [ ] **Step 2: Implement.** In `_LAZY_NAMES` add (following the
  PlotData attribute-resolution pattern — the key differs from the
  module basename, so the attribute is returned):

```python
    # The notebook front door (stage 4). Deferred like `serve` (same
    # optional websockets dependency).
    'launch': '.session',
    'Session': '.session',
```

In `_LAZY_EXTRAS` add `'.session': ('websockets', 'serve'),`.
Replace `_REMOVED_MESSAGE` with:

```python
_REMOVED_MESSAGE = (
    "'pydvma.{name}' was removed. The Qt logger was retired after the "
    "web logger reached full parity. From a notebook, use the new "
    "front door:\n"
    "    session = dvma.launch(dvma.MySettings(...))\n"
    "(captures accumulate in the browser app; pull them back with "
    "session.data, hand data over with session.push).\n"
    "From a terminal: pip install pydvma[serve] && pydvma-serve --open\n"
    "(docs: https://torebutlin.github.io/pydvma/web-logger/).\n"
    "To run the old Qt GUI, check out the 'qt-final' git tag."
)
```

- [ ] **Step 3: Run the packaging/tombstone tests + full pytest**

Run: `python -m pytest tests/ -q --ignore=tests/test_acquisition_hardware.py`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add pydvma/__init__.py tests/
git commit -m "feat(api): dvma.launch/Session lazy exports; tombstones name the successor"
```

### Task 10: Docs + changelog

**Files:**
- Modify: `docs/web-logger/migration.md` — the `dvma.Logger` successor
  story becomes `dvma.launch` (code example as in the session.py
  docstring; note `session.data`/`push`; keep the qt-final tag note).
- Modify: `docs/web-logger/index.md` — the serving section gains the
  journal sentence: "when served locally, pydvma-serve keeps the
  session document — closing the tab loses nothing; reopening offers a
  restore" + a short `dvma.launch` subsection.
- Modify: `docs/examples/basic.md` — a notebook-flow example:
  `launch → capture in the app → session.data → analyse → push back`.
- Modify: `CHANGELOG.md` (Unreleased → Added): two entries, "Session
  journal — pydvma-serve owns the session document…" and
  "`dvma.launch(settings)` — the notebook front door replacing
  `dvma.Logger`…", written in the file's existing voice.

- [ ] **Step 1: Write all four.** Follow each file's current tone; the
  migration page is the one users land on from the tombstone — lead
  with the copy-pasteable `launch` example.

- [ ] **Step 2: Strict docs build**

Run: `python -m mkdocs build --strict`
Expected: clean. (Docstring discipline: one param per Args line,
returns in prose — griffe-strict fails otherwise.)

- [ ] **Step 3: Commit**

```bash
git add docs/ CHANGELOG.md
git commit -m "docs: session journal + dvma.launch — migration successor story, examples, changelog"
```

### Task 11: Close-out — full suites, round doc, trackers

- [ ] **Step 1: Full suite sweep**

```bash
python -m pytest tests/ -q --ignore=tests/test_acquisition_hardware.py
cd webui && npm run check && npx vitest run
npx playwright test --grep-invert @engine
npx playwright test --grep @engine --workers=1
BRIDGE_E2E=1 npx playwright test e2e/bridge.spec.ts e2e/bla.spec.ts e2e/engine-native.spec.ts e2e/session-journal.spec.ts --workers=1
cd .. && python -m mkdocs build --strict
```

Expected: all green. NOTE: `pydvma/engine.py` is untouched by this
arc, so NO engine-wheel rebuild is required — but if any task above
drifted into it, run `npm run vendor:wheels` and re-verify
byte-identity per CLAUDE.md's release notes.

- [ ] **Step 2: Round doc.** Create
  `dev/2026-08-XX-session-journal-round.md` (date of execution):
  what landed per stage, suite numbers, any deviations from this plan,
  and a live-verification checklist (real capture through a real
  device → close tab → reopen → restore; `dvma.launch` from a real
  Jupyter kernel with a hardware capture pushed/pulled).

- [ ] **Step 3: Trackers.** TODO.md: strike "Native engine, stages
  3–4" (point at the round doc) and strike the
  "real-app-over-socket e2e coverage gap" item (Task 6 closed it).
  CLAUDE.md current-focus: stages 3–4 landed; next arc TBD by Tore.

- [ ] **Step 4: Commit**

```bash
git add TODO.md CLAUDE.md dev/
git commit -m "docs: stages 3-4 close-out — round doc, TODO, focus"
```

---

## Self-review notes (done at plan time)

- **Spec coverage:** §4.4 autosave op → Tasks 2/4; captures at birth →
  Task 3; get_session/restore → Tasks 2/5/6; §4.5 launch/session API →
  Task 8; tombstone update → Task 9; docs/migration successor → Task
  10; §6 testing (journal e2e, headless push/pull via mock, kernel-
  loop clash) → Tasks 6/8; `dvma.attach` explicitly out of scope
  (design) — not planned.
- **Known soft spots the executor must resolve against the tree** (all
  flagged inline): the engine-host test harness fixture names (Task
  2), the engine store's client handle + capability threading (Task
  5), the autosave vitest filename (Task 4). Each is a
  read-the-file-first instruction with the target shape fully
  specified, not a design gap. (`DataSet`/`TimeData` APIs were
  verified at plan time — see Task 8's note.)
- **Type consistency:** journal ops are `journal_set`/`journal_get`
  everywhere; the notify frame is `{'type':'journal','event':'updated'}`
  in Task 2 (server) and Task 5 (client); `SessionJournal.state()`
  returns `(doc, captures)` in Tasks 1/2/3/8 alike; `save_bytes`/
  `load_bytes` (Task 7) are the only container additions and Task 8
  uses exactly those names.
