# Native engine — round writeup (stages 0–2)

**Date:** 2026-08-17 (Mac session, day + evening). **Status:** stages
0–2 landed, committed locally (NOT pushed), full suite gate green,
live-verified on real hardware (Scarlett 2i2 4th Gen). Stages 3–4
(session journal, `dvma.launch`) deliberately deferred — see the
checklist at the end. Design: `dev/plans/2026-08-17-native-engine-design.md`;
plan: `dev/plans/2026-08-17-native-engine-plan.md` (Tasks 1–11; this
doc closes Task 11).

## What landed

**Stage 0 — glue into the package.** `webui/src/lib/worker/glue.py`
moved verbatim into the installed package as `pydvma.engine`, importable
by both the pyodide worker and the (then-future) native host; the
worker now imports it from the wheel it already installs instead of
writing it into pyodide's virtual FS by hand. Zero behaviour change,
proven by the existing suites staying green untouched. One incidental
fix rode along: `legacy_to_dvma`/`mat_to_dvma` now use real `tempfile`
dirs instead of a fixed `/tmp` path (Windows-safe, collision-safe).

**Stage 1 — native engine behind a flag.** New `pydvma/engine_host.py`:
a binary frame codec (`[u32 LE header_len][header JSON][blobs...]`,
arrays lifted out of the JSON tree into trailing blobs) specified
byte-for-byte for both the Python codec and a JS mirror
(`worker/frames.ts`); a persistent spawn-context `EngineWorker`
subprocess (serial op execution, progress via the hook that doubles as
the cooperative-cancel checkpoint, hard kill + transparent respawn); a
second websocket route, `/engine`, alongside the untouched `/ws` bridge
protocol. App-side, `SocketEngineClient` implements the existing
`EngineClient` interface over that socket, reusing `client.ts`'s
pending-map/restart contract. Selectable only via `?enginehost=` at
this stage — the shipped default stayed pyodide even under serve.

**Stage 2 — flip the default.** `decideEnginePolicy` in
`stores/engine.ts`: explicit `?enginehost=` always wins; absent that, a
`/config` probe (`probeServeConfig`, not the pre-existing
`fetchServeConfig` — see bugs below) detects "served by pydvma-serve"
and resolves the native engine, gated on a greeting protocol-version
match, falling back to pyodide silently on any absence/mismatch/failure
(console-logged, plus a one-shot toast when a successful auto-detection
still ends in fallback). The native worker child raises
`analysis.CWT_MAX_IMAGE_BYTES` from the pyodide-only 768 MiB default to
8 GiB, since that ceiling exists solely to protect the 32-bit wasm heap
and would otherwise throw away the engine's headline memory win for
CWT/sonogram work specifically. `BusyChip`/`EngineProbe` surface the
active host and the answering `pydvma` version.

## Bugs found in review (fixed before shipping)

- **Non-finite scalars broke the wire JSON** — `NaN`/`Infinity` aren't
  valid JSON tokens; an early codec draft let them leak through. Fixed
  by sanitising non-finite scalars to `null` (mirrors JS
  `JSON.stringify(NaN)`) and running `json.dumps(..., allow_nan=False)`
  so any missed path fails loudly. Array *values* are unaffected — an
  `"f8"` blob is raw bytes, never JSON.
- **A too-permissive frame-truncation guard** — the first cut only
  rejected `pos > len(data)`, so a frame corrupt in a way that still
  satisfied that inequality (short by less than one blob, or carrying
  extra trailing bytes) decoded anyway. Tightened to require an exact
  fit (`pos == len(data)`) — the format has no padding by design.
- **Stop wasn't actually observing the close** — the handler awaited
  the in-flight op to finish *before* checking whether the client had
  gone away, so closing the socket didn't interrupt anything: the
  worker kept computing, a reconnect spun up a second worker alongside
  the abandoned one. Fixed by racing the op against
  `websocket.wait_closed()`; losing that race kills the worker promptly.
- **A stranded `init()`** — stage 2 calls `SocketEngineClient.init()`
  twice in the ordinary case (native-host probe, then the store's own
  boot); the first cut opened a second socket, and therefore a second
  server-side worker subprocess, on the second call. Fixed with a
  `connectPromise` reused for as long as a connection attempt is in
  flight or connected, cleared only when it genuinely ends.
- **Port collisions, including the plan's own pick** —
  `engine-native.spec.ts` moved off 8764 (a collision with the bridge
  settings server) to 8765, which turned out to already be
  `bla.spec.ts`'s `BLA_BRIDGE_PORT`. Silent collision: a mock
  `pydvma-serve` answers both `/ws` and `/engine`, so the loser ran its
  tests against the winner's server instead of failing to bind. Moved
  to 8766, every claimant (8763/8764/8765/8766) named in one comment.
- **`fetchServeConfig`'s `{}`-collapse** — a `pydvma-serve` session
  started without `--settings` (the ordinary case) publishes an empty
  `/config`, which the pre-existing `fetchServeConfig` collapses to
  `null` for its own unrelated purpose. Using that as the served-ness
  signal would have kept every unset-settings session on pyodide,
  defeating stage 2 entirely — caught by a served-mode e2e spawning the
  mock driver with no `--settings`. Fixed with a dedicated
  `probeServeConfig`.

## Live-verification session (2026-08-17 evening, this Mac)

Hardware: Scarlett 2i2 4th Gen, gain 9 dB, Focusrite Control 2 pinned at
48 kHz. Served the built app through a real `pydvma-serve` (no
`--settings`, no `?enginehost=`) and drove it by hand.

**Proven working:** with no override the app resolved the native engine
by default (console: `[engine-socket] native engine: pydvma 2.3.0`);
real 48 kHz 4-channel bridge captures; FFT on 12 real channels, a CWT
sonogram (log-frequency axis, heat canvas verified on composited
pixels), and a TF with coherence ≈ 1 on the digital-loopback pair
(identical-signal channels → unity TF) — all through the `/engine`
socket.

**Found, pre-existing, NOT from this arc — logged to `TODO.md`, not
fixed here:**

1. Bridge soundcard **output** path is broken two ways: with
   `output_device_index` unset, `sd.OutputStream(device=None)` plays on
   the **system default output** (Mac speakers, audibly confirmed)
   instead of the capture device (the round-9 "unset output follows
   input" fix in `options.py` covers NI/mock only); with
   `output_device_index` set explicitly to the *same* device as the
   input, the capture comes back **all-zero** (a second CoreAudio
   stream on a device with a running input stream appears to break it,
   macOS-specific). Repro'd headlessly over `/ws` both ways; a direct
   `sd.playrec` duplex stream on the same device works fine — likely
   the fix shape.
2. The physical out-L→in-1 loopback cable on this 2i2 passes signal
   ~27 dB down (RMS 0.009 vs 0.204 on the digital loopback for the same
   tone) — cable/gain suspect, not chased further. Digital loopback
   (channels 3/4) remains the reliable cable-free self-test path.
3. Minor: HTTP `HEAD` requests to serve (health probes) log noisy
   `websockets` tracebacks ("unsupported HTTP method; expected GET; got
   HEAD") — cosmetic, worth a quiet answer in `_process_request`.

## Suites at close

- `pytest -q -m "not hardware"`: **886 passed, 7 skipped** (no flake —
  the acquisition-cancel test's known rare timing flake did not
  reproduce).
- `npx vitest run`: **1030 passed, 1 skipped.**
- `npm run check`: **0 errors, 0 warnings.**
- `npx playwright test --grep-invert @engine`: **69 passed, 15
  skipped** (the `@engine` specs, run separately below).
- `npx playwright test --grep @engine --workers=1`: **19 passed.**
- `BRIDGE_E2E=1 npx playwright test e2e/bridge.spec.ts e2e/bla.spec.ts
  e2e/engine-native.spec.ts --workers=1`: **18 passed** (three real
  spawned `pydvma-serve` processes on ports 8763/8765/8766).
- `python -m mkdocs build --strict`: clean.
- Engine wheel rebuilt (`npm run vendor:wheels`, still `2.3.0`) and
  verified byte-identical to `pydvma/engine.py` in the tree (SHA-256
  match).

## Next-lab-visit checklist (live re-verification)

- [ ] **Native-engine default flip on the lab PC** — serve with no
      param, confirm the console reports the native engine on Windows.
- [ ] **A real NI capture analysed natively** — configure/log through
      an actual NI device (6003 / 6212 / cDAQ-9234), FFT/TF end to end
      (today's verification used soundcard captures only).
- [ ] **CWT damping on a 30 s capture, exercising the 8 GiB ceiling** —
      confirm a record that would refuse under pyodide's 768 MiB cap
      now succeeds natively, and the sizing error still fires correctly
      when actually exceeded.
- [ ] **Stop mid-CWT in the real UI** — not just the e2e harness:
      trigger a long CWT calc, click Stop, confirm the server-side
      worker subprocess is actually gone.
- [ ] **Soundcard-output bug fix, once it lands** — re-run a stimulus
      log on the 2i2 (and ideally the U24 XL), confirming both the
      unset-device and same-device cases play from the right output and
      the capture is no longer zeroed.
