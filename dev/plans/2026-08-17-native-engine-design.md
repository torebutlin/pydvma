# Native engine — design

**Date:** 2026-08-17
**Status:** agreed in discussion with Tore (this doc is the write-up for
his review). No implementation yet.

## 1. Decision summary

The web logger's analysis engine becomes **host-agnostic**: the same
compute ops, answered either by the in-browser pyodide worker (today's
only implementation) or by the local `pydvma-serve` process running
ordinary CPython. When the app is served by `pydvma-serve`, analysis
runs natively — no wasm32 2 GB ceiling, full BLAS speed, real
progress/cancel, any installable package. The Pages app is unchanged
and keeps working with zero install.

On top of that, locally, the **serve process becomes the owner of the
session** (closing the tab loses nothing; reopening reconnects), and a
**notebook front door** — `dvma.launch(settings)` — starts the whole
thing from a kernel and gives the notebook pull/push access to the
session's data. `dvma.launch` is the successor to the removed
`dvma.Logger(settings)`.

Agreed invariants (Tore, 2026-08-17):

- **Usage is identical across modes.** Same UI, same maths, same
  results, same `.dvma` files. The only user-visible differences are
  performance and hardware reach (Pages: soundcard via Web Audio only;
  local install: NI + calibrated soundcard via the bridge — exactly as
  today).
- **Full power for those who install; full convenience for the
  webapp.** Neither mode is degraded to serve the other.
- **All detailed design work to date stands.** Device support,
  calibration model, capture semantics (round 11 trigger state machine,
  rate ladders, `VmaxSC` derivation), analysis behaviour, file format —
  none of it changes. This project moves *where* code runs, not *what*
  it does.
- **Done carefully.** Every stage lands with all suites green and the
  app fully working; native paths are capability-gated with pyodide as
  the always-available fallback, so nothing can break for a user whose
  serve/app versions mismatch.

Explicitly rejected alternatives:

- *Hybrid offload* (pyodide stays the engine, only heavy verbs go to
  the bridge): puts the dataset in two Pythons at once; mirror/cache
  coherence is the classic rot path.
- *Jupyter widget embedding*: wraps the bridge rather than removing it;
  heavy new embedding surface; doesn't address the wasm limits.
- *COOP/COEP headers from serve* (SharedArrayBuffer → interruptible
  pyodide): its benefit window closes when the native engine lands;
  Pages can't use it (GitHub Pages sends no custom headers — a
  service-worker workaround exists if Pages-mode Stop ever becomes a
  real complaint, noted in TODO, not built now).

## 2. Current architecture (as verified in-tree, 2026-08-17)

Three processes, with a clean seam already in place:

| Piece | Runs | Owns | Role |
|---|---|---|---|
| App (JS main thread) | browser tab | **the session**: dataset doc (`DvmaItem[]` of `NpyArray`s, `webui/src/lib/model/dataset.ts`), view state, undo snapshots, autosave (`files/autosave.ts`) | UI, plotting |
| Engine worker | browser tab (pyodide) | nothing — **stateless by design** | pure calculator |
| `pydvma-serve` | local CPython | hardware | acquisition only (`configure`/`log`/`monitor`/`cancel`) |

Facts the design leans on, verified in this session:

- **The engine protocol is already transport-shaped.** `worker/client.ts`
  correlates `{id, op, payload}` → `{id, ok, result|error}` plus
  unsolicited `{type:'progress', callId, done, total}` frames.
  `EngineClient` is an interface with an injectable transport; its own
  docstring anticipates "a future non-worker transport".
- **glue.py is stateless and CPython-clean.** Every op takes
  JSON-marshallable scalars plus flat float64 arrays and returns dicts
  of `{shape, data, complex}` arrays (the `codec/npy.ts` convention);
  "no PyProxy state survives between calls". The module header states
  it "imports and runs unchanged under CPython", and the JsProxy
  handling (`_get`, `_opt_float`, `_bla_run_spec`) is defensive input
  normalisation that passes plain dicts through untouched.
- **The dataset does NOT live in the engine.** Every calc call ships
  the needed arrays in; results come back as arrays. So swapping the
  calculator's host does not move the session — that is a separate,
  deliberate step (stage 3).
- **Captures are born native.** `serve.py` runs `acquisition.log_data`
  in CPython and serialises the result to a `.dvma` frame for the
  browser. In native-engine mode that object can simply stay home.
- The app already detects "served by pydvma-serve" (the `/config`
  fetch) and switches acquisition mode on it — the same signal gates
  the engine choice.

## 3. Target architecture

```
                    ┌───────────── browser tab ─────────────┐
                    │  app (UI, plots, view state)          │
                    │      │ EngineClient interface         │
                    │      ├── WorkerEngine (postMessage) ──┼─► pyodide worker   [Pages / fallback]
                    │      └── SocketEngine (ws /engine) ───┼─┐
                    └───────────────────────────────────────┘ │
                                                              ▼
   notebook kernel ──(launch: same process)──► pydvma-serve process
        session API                             ├─ bridge (acquisition)   [unchanged]
                                                ├─ engine host (glue ops in a worker process)
                                                └─ session journal (authoritative doc)
```

One protocol, two transports, one Python implementation of the ops.
Mode selection: the app uses the native engine **iff** the serve
capabilities advertise one it understands; otherwise it boots pyodide
exactly as today. Pages never sees any of this.

### 3.1 Ownership model (the careful version)

Full "server authoritative, browser mirrors" would rewrite every store
that touches the dataset doc (selection, undo, viewstate, autosave) —
maximal violence for marginal gain. Instead, ownership rides the
**existing autosave path**:

- In native mode the app's autosave target becomes the serve process
  (in addition to browser storage): the serve process always holds the
  current session document, `.dvma`-shaped.
- Captures register server-side at birth (they are already born there)
  and are pushed to the app as today.
- On connect, the app offers/loads the server's current document —
  reconnect-after-tab-close is "load the latest autosave", a flow the
  app already has (round-10 append semantics).
- Undo history and view state stay browser-side (they are UI state, and
  undo snapshots are exactly what we don't want to sync).

This achieves the user-visible property Tore approved — *local Python
owns the session; a closed tab loses nothing* — without re-architecting
the stores. The purist mirror model remains possible later; nothing
here forecloses it.

## 4. Components and changes

### 4.1 glue.py moves into the package (stage 0)

`webui/src/lib/worker/glue.py` becomes `pydvma/engine.py` (module name
final at implementation; `pydvma.engine` here). The worker imports it
from the installed wheel (it already installs the pydvma wheel; the
FS-write + `sys.path` dance goes away). The native host imports it
normally. One file, two hosts, version-locked to pydvma — which also
retires the `_accepts_kw` old-wheel probes over time (glue can no
longer be newer than the wheel it rides in).

Wasm-specific memory workarounds (`_spectrogram_complex_lowmem`,
CWT preflight) already live in pydvma behind environment checks and are
untouched.

### 4.2 Native engine host (stage 1)

New module `pydvma/engine_host.py`, wired into `BridgeServer`:

- **Endpoint:** a second websocket path, `/engine`, so the bridge
  protocol (`/ws`) is byte-for-byte untouched and monitor frames never
  interleave with engine traffic.
- **Wire format:** same `{id, op, payload}` / `{id, ok, result|error}`
  JSON as the worker protocol. Arrays cross as binary: the JSON carries
  `{__bin: n, shape, complex}` placeholders referencing the n-th
  following binary ws frame (the same JSON-then-binary pattern the
  bridge already uses for `log_result` → `.dvma` frame). Localhost
  bandwidth makes per-call array shipping a non-issue at lab scale
  (a 30 s × 2 ch × 48 kHz record ≈ 23 MB, well under a second).
- **Execution:** ops run in a **worker process pool** (spawned once,
  kept warm — Windows has no fork), not threads. Rationale: Python
  threads cannot be killed, but Stop must be reliable. Cooperative
  cancel goes first (the existing `progress_callback` hook doubles as a
  cancel checkpoint); hard Stop terminates the worker process and the
  pool respawns — the serve process and the session journal survive,
  which is strictly better than today's pyodide terminate-and-reboot.
- **Progress:** the pool worker reports through a pipe/queue; the host
  forwards `{type:'progress', callId, done, total}` frames — identical
  shape to the worker protocol, so `BusyChip`/progress UI needs no
  changes.
- **Trust model unchanged:** serve binds localhost; the engine endpoint
  accepts the same-origin app only, like `/ws`.

### 4.3 App-side SocketEngine (stage 1–2)

A second `EngineClient` implementation speaking the above over ws.
`client.ts`'s pending-map/`restart`/`observe` contract is reused;
`protocol.test.ts`'s fake-transport pattern extends to a fake socket.
The engine store (`stores/engine.ts`) gains host selection:
capabilities advertise `engine: {v: 1, pydvma: "<version>"}` → use
SocketEngine; absent/unknown → boot pyodide as today. A visible
indicator (Setup or the BusyChip tooltip) names the active engine —
"local Python" vs "browser" — so behaviour differences are never
mysterious.

Versioning rule: the app requires `engine.v` it knows and a pydvma
version ≥ its own expectations; any mismatch = silent fallback to
pyodide (today's behaviour, never a breakage).

### 4.4 Session journal (stage 3)

Serve gains a session document store (in-memory + spill to a session
file next to the autosave format):

- `autosave` op on `/engine`: the app posts the current doc (it already
  serialises for browser autosave).
- Captures append server-side at birth.
- `get_session` op: served on connect; the app offers "restore session"
  (or auto-restores when the doc is non-empty — UX decided at
  implementation with a Playwright-covered flow).

### 4.5 Notebook front door (stage 4)

```python
import pydvma as dvma
session = dvma.launch(dvma.MySettings(device_driver='nidaq', fs=3000,
                                      channels=2, stored_time=30))
# browser opens; captures accumulate. Later:
session.data          # live view of the session document (pydvma objects)
d = session.data[0]   # a TimeData — ordinary CPython object
session.push(d2)      # hand a (new/modified) dataset back; app appends
session.close()
```

- `launch(settings)` starts `BridgeServer` (bridge + engine + UI + the
  settings prefill, replacing the hand-written `--settings` JSON) on a
  **background thread** in the kernel process and opens the browser.
  The kernel is then the same process as the engine — pull is a local
  read of the journal, push is a local append plus a notify to the app.
- **Explicit handoff, not shared mutation:** `session.data` returns
  materialised pydvma objects (reconstructed from the journal under its
  lock); `push` is the only write path. The notebook never holds live
  references that the engine is concurrently computing on — this is the
  thread-safety answer to "editing the class while the GUI is live".
- **The notebook is optional.** `launch` and the CLI are two front
  doors onto the same `BridgeServer`: `pydvma-serve --driver nidaq
  --open` keeps working as a standalone-app launch with no notebook
  anywhere, and gets the native engine and session journal identically
  (they live in the serve process, not the launch path). The only
  difference is that the CLI route has no kernel holding a `session`
  handle.
- `dvma.attach(url)` (same session API against an externally started
  `pydvma-serve`, pull/push over `/engine` — the way to get notebook
  access to a CLI-launched session) is a natural follow-on and the API
  is designed not to preclude it, but it is **out of scope** for this
  project.
- The `Logger`/`Oscilloscope` tombstone messages update to name
  `dvma.launch`.

## 5. What explicitly does not change

- Pages app and JupyterLite: byte-identical behaviour, still pyodide,
  still zero-install. The pyodide engine is not deprecated — it is the
  permanent implementation for the no-install mode and the fallback
  everywhere.
- The bridge acquisition protocol (`/ws`), all round-11 capture
  semantics, device enumeration/calibration (`devices.py`, profiles,
  `VmaxSC`), rate ladders, `.dvma` format, the analysis maths.
- The app's stores/data model in Pages mode; in native mode only the
  engine client and the autosave target differ.
- `pydvma-serve` CLI surface (flags keep working; `--settings` remains
  for launch-script use).

## 6. Testing strategy

- **Stage 0** is proven by the existing suites (pure refactor; vitest
  worker tests + Playwright @engine unchanged) plus new **direct pytest
  coverage of glue ops under CPython** — cheap tests that were
  impossible while glue lived outside the package.
- **SocketEngine unit tests** via the fake-transport pattern
  (`protocol.test.ts` precedent).
- **Engine-host pytest**: ws round-trip per op family, binary framing,
  progress frames, cooperative + hard cancel, pool respawn.
- **Playwright grows an engine axis** for the flows that touch the
  engine (FFT/TF/sono/CWT/fit/BLA/resample): the existing BRIDGE_E2E
  harness (real spawned server) runs them against the native engine;
  Pages-mode runs stay as they are. Keep the round-7 standard:
  rendering claims verified on composited-pixel screenshots.
- **Parity**: by construction (same pydvma, same glue) — spot-checked
  by asserting a captured fixture through both engines agrees to
  tolerance in one e2e.
- **Session journal e2e**: capture → close tab → reopen → restore;
  notebook push/pull exercised headlessly (pytest driving `launch`
  with the mock driver).
- Regression floor: the 3c6 envelope (3 kHz / 30 s / 2 ch + 6 s CWT
  damping) must pass through the native engine, and must *still* pass
  through pyodide.

## 7. Staging

Each stage lands with pytest + vitest + check + Playwright + mkdocs
--strict green and the app fully working; no stage ships a half-mode.

- **Stage 0 — glue into the package.** Move + worker import change.
  Zero behaviour change.
- **Stage 1 — native engine behind a flag.** `/engine` host +
  SocketEngine + process pool + progress/cancel. Default engine remains
  pyodide even under serve; the flag is for testing and daring users.
- **Stage 2 — flip the default.** Served-by-pydvma-serve + capability
  match → native engine; indicator visible; fallback path e2e-tested.
- **Stage 3 — session journal.** Server-side autosave + restore flow.
- **Stage 4 — `dvma.launch`.** Session API, tombstone update, docs
  (migration.md gets its true successor story), labsheet example.

Stages 1–2 deliver the performance/limits win; 3 delivers ownership;
4 delivers the notebook. Later stages are independently shippable
releases.

## 8. Risks and mitigations

- **glue's FFI normalisation regressing pyodide mode** when inputs
  become plain JSON: the JsProxy helpers are pass-through for plain
  dicts (verified reading `_get`/`_opt_float`); existing @engine e2e
  guards them; helpers stay, they are harmless.
- **Process-pool cold spawn on Windows**: pool started warm at serve
  boot; first-calc latency e2e-asserted sane on the PC.
- **Large-array frames stalling the ws**: arrays chunked if needed;
  localhost measurements before optimising (suspected non-issue).
- **Version skew app↔serve**: capability gate + silent pyodide
  fallback; the mismatch is logged to console and shown in the engine
  indicator, never fatal.
- **Two-host drift**: forbidden structurally — ops live in one module
  in one package; anything host-specific lives in the thin transport
  adapters only. Code review rule: no compute logic in
  `engine_host.py` or the worker.
- **Kernel-thread asyncio clash in `launch`** (a second event loop in a
  thread inside Jupyter's loop): the bridge already runs
  `asyncio.run` standalone; in-thread it gets its own loop — the known
  pattern, covered by a pytest that launches inside a running loop.
- **Autoreload expectations**: as with the old Qt logger, editing
  pydvma acquisition/engine code does not affect a live session
  (background thread holds its references); documented in the
  `launch` docstring.

## 9. Out of scope

- `dvma.attach()` remote sessions (API shaped for it, not built).
- Pages-mode SharedArrayBuffer via service worker.
- Hybrid per-verb offload; Jupyter widget embedding.
- Non-localhost serving, auth, multi-client sessions (single app tab +
  single notebook assumed; the journal lock serialises them).
