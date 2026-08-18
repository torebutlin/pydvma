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

Run 2026-08-18 on the Windows PC (RDP session; cDAQ-9174 + USB-6212
connected, 6003 absent). The stale gitignored artifacts were rebuilt
first — this PC's `webui/public/pypi` still held a **v2.0.0** engine
wheel from July and a July-era `dist/`, exactly the silent trap
CLAUDE.md's release notes describe (`npm run vendor:wheels` + `npm run
build`, wheel verified byte-identical to the tree's `engine.py`). The
UI was driven by Playwright scripts against a real
`pydvma-serve --driver nidaq` because the in-app browser pane turned
out to be `document.hidden` with rAF suspended — see "PC verification
notes" below.

- [x] **Native-engine default flip on the lab PC** — 2026-08-18:
      served with no param on Windows, console reports
      `[engine-socket] native engine: pydvma 2.3.0`.
- [x] **A real NI capture analysed natively** — 2026-08-18: 2 s
      4-channel 9234 capture at 51.2 kHz with a 9260 sweep on the
      loopback, FFT and TF both rendered through the `/engine` socket.
- [x] **CWT damping on a 30 s capture, exercising the 8 GiB ceiling** —
      2026-08-18: 30 s × 51.2 kHz capture; default-band CWT damping is
      a **6.34 GiB** image (8.4× over pyodide's 768 MiB cap) and
      completed natively in ~35 s (worker RSS peaked 6.88 GB, decay
      fits + mode chip rendered); at 64 voices/octave the sizing error
      fired correctly — "25.27 GB, over the **8.00 GB** limit" with
      the full remedies text, proving the raised native ceiling (not
      pyodide's 0.75) is the one enforced end-to-end.
- [x] **Stop mid-CWT in the real UI** — 2026-08-18: Stop clicked ~15 s
      into the transform; the worker subprocess (2.7 GB RSS,
      mid-compute) was gone within one 5 s process poll, a replacement
      connected (second engine greeting in the console), and the next
      Fit damping ran to completion cleanly.
- [x] **Soundcard-output bug fix, once it lands** — DONE 2026-08-18
      (Mac session, 2i2 4th Gen + physical loopback cable, output knob
      at full): the fix landed same-day (unset output follows the
      capture device; same-device capture+stimulus is ONE full-duplex
      `sd.Stream` — root cause confirmed environmental with raw
      sounddevice: on this bench a running input stream's callback now
      stops permanently when a second stream opens on the same device,
      PaMacCore err=-50. Attribution, checked 2026-08-18 evening with
      Tore: NOT an OS change — no macOS update since 30 Jun, no reboot
      since 26 Jul, sounddevice/PortAudio unchanged since Oct 2025 —
      but **Focusrite Control 2 was installed 10 Aug (after that day's
      passing BLA run) and self-updated 12 Aug** (Tore confirms the
      update), and FC2 updates carry 2i2 firmware; the breakage
      persists with FC2 quit, so a flashed firmware change is the
      prime suspect. Possibly 2i2-specific rather than macOS-wide —
      the duplex arrangement is the correct one regardless). Live
      evidence: direct path 6/6 (unset output
      resolves to the 2i2 and the tone lands on cable ch1 at −3 dB +
      digital loopback ch3/4, with NOTHING at the system default
      output, pinned measurably via BlackHole; explicit same-device
      identical); real `pydvma-serve` over `/ws` 10/10 (sweep in the
      returned .dvma both ways, `status/cancelled` releasing a
      mid-stimulus cancel in 0.49 s, monitor stream flowing after the
      capture); `bla_soundcard_check.py` identity **G ≡ 1 to 4e-17
      through the duplex stream** (its "open-input" check now reads
      the plugged cable on ch1 — expected while the cable stays in).
      The U24 XL half remains untested (box not on this bench) but
      exercises the same code path. (2i2 cable mystery closed too: the
      −27 dB was the output volume knob, −3 dB at full.)

## PC verification notes (2026-08-18, Windows session)

Suites on the PC at the same tree: pytest **927/18** with cDAQ + 6212
live (first hardware run of the native-engine era), vitest **1030/1**,
check **0/0**, Playwright main **69 passing** (two live-monitor specs
flaked once under CPU contention with the concurrently-running pytest
and passed clean on re-run), `--grep @engine` **19/19**, BRIDGE_E2E
bridge+bla+engine-native **18/18** (first Windows run of the spawned
`/engine` host — spawn-context worker, large frames, Stop, default
flip all green), mkdocs --strict clean.

**Real bug found and fixed (commit `8cc9f48`):** running
`dev/bridge_hw_check.py` (58/58 after the fix) exposed a round-11
race — serve restored the post-capture stream rate AFTER delivering
`log_result`, so a client reacting promptly hit either "a log is
already in flight" or a DAQmx property-conflict error from the
restore racing the next `configure`. Mock reopen is instant, which is
why every Mac/mock run had passed. The restore now runs before the
result goes out; regression-pinned in `test_serve_protocol.py`.

**Not a bug, but a trap for automation:** the served app driven in a
HIDDEN page (`document.hidden`, rAF suspended — e.g. the Claude
browser pane, potentially any background tab) never completes a calc:
the engine round-trip finishes (request sent, reply received and
resolved — verified down to the client's pending map) but the action
then parks awaiting an animation frame, "computing…" forever, no
error. Perfectly reproducible with mock and nidaq drivers alike;
completes instantly in a visible/Playwright browser. For a real user
this is at worst "calc finishes when you come back to the tab". The
exact rAF-await site was not located; noted in TODO.md alongside the
related e2e coverage gap (no test drives the real app's calc path
over the socket engine — the e2e uses the `?engine=1` probe page).
