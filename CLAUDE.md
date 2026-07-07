# Working with Claude on pydvma

## Current focus (update when it changes)

As of 2026-07-07: web-UI Stages 0–1, **Stage 2 Plan 1** (the no-install
browser **analysis** app in `webui/`), the analysis-card redesign
(R1–R5), `.dvma` UI-state persistence, and now the **full round-2
feedback round** are ALL implemented and committed on master.
The round-2 work (orchestrated session, 2026-07-07; ten commits
`888f710..1624320`) landed every item in
`dev/2026-07-05-acquisition-hands-on-feedback.md`:

- **Analysis fixes:** TF on a single-channel set no longer goes blank
  (named-set message via `computeError`; root cause was the R4 out/in
  remap leaving zero output columns); legend off-lines stay listed
  struck-through and cycle back on (`selection.legendRows`; the TF
  view's App-level override included); PSD/TF/Sono **recompute live**
  (debounced `lib/analysis/liveCalc.ts`, gated so the FIRST compute is
  still the Calc button); Time card "input channel" rename + tray
  duration badge at 3 s.f.
- **Acquisition design pass** (design-first, from
  `dev/mockups/round2-bench.html` distilled by a scout agent): the
  **persistent mini-oscilloscope** (`MiniMonitor.svelte`) docks at the
  tray foot on every stage with its OWN start/stop (C1 auto-stop
  removed — teardown release via onDestroy + pagehide/beforeunload;
  I2/I3/C2 guards intact); ⤢ expands into the **Live tab** =
  `LiveScope.svelte` (time + live **FFT** (`lib/audio/fft.ts`, tested
  TS radix-2/Hann) + levels grid, T/F/L/P chips); monitor store gained
  windowS presets (clamped — M3 fixed), dB/lin + log/lin f, latching
  CLIP; **Setup** enumerates devices on mount + basic↔full
  extended-area mode; **Acquire** summary shows fs·ch·T·device·pretrig.
- **Bonus measurement fix:** getUserMedia echoCancellation /
  noiseSuppression / autoGainControl now default **OFF** (browser
  defaults silently filter measurement audio); toggles in Setup full.

Verified: 307 vitest + 38 Playwright e2e green (incl. a fake-mic
`live.spec.ts`), svelte-check 0 errors, visual check against the
mockup. **Still NOTHING pushed** — CI/Pages activate on next `git push`.

**Round-3 feedback also landed (2026-07-07)**: PSD mixed-fs crash
root-caused to the 32-bit WASM nominal-size limit in
`sliding_window_view` (fixed in `pydvma/analysis.py` via direct
`as_strided`, byte-identical, + glue-side guard for stale wheels);
per-kind `computeErrors` (a failed TF no longer poisons Sonogram);
Δf-intent distribution for mixed-fs "All sets" targets; live slider
drag; tray title cycles the whole set; Live scope custom view-time +
fmax + Welch-PSD averaging mode; Setup-full grouped device options
with a marked nidaq slot. Tore's directive: **pushing authorized at
checkpoints; goal = fully replaced GUI** (Qt stays until his final
confirmation) with full NI-DAQ + the three modes —
`dev/plans/2026-07-07-full-gui-replacement-plan.md` is the roadmap.

**Waves A + B LANDED (2026-07-07, checkpoint 2):** the webui now has
the **modal Fit stage** (Fit 1/2/3 via peak-split, Reject,
Reconstruction overlays, fn/ζ/Q chip, gated until a TF exists),
**sonogram damping fit**, **per-channel calibration** (mockup dialog;
stores real `channel_cal_factors` + `units` manifest fields;
display-time scaling incl. TF ratio), **browser MATLAB/CSV export**
(file.py schema parity) + figure font fidelity, AND the full
**`pydvma serve` bridge**: `pydvma/serve.py` (websockets, protocol
v1, mock/soundcard/nidaq drivers, serves webui/dist + /config) with
the webui `SourceProvider` seam + `BridgeProvider`
(`window.__pydvma_bridge` / `?bridge=` / `/config` probe), Setup
showing bridge devices + an NI group when the bridge reports nidaq.
Bridge e2e (BRIDGE_E2E=1) passes against a real mock-driver server.
Suites: pytest 225, vitest 396, svelte-check 0/0, Playwright 46.

**Wave C LANDED too (checkpoint 3):** serve reports real per-device
capabilities (fs ladders / max channels / device_caps, keyed
driver:index; NI via additive `_ni_backend.device_capabilities`
helpers — property names verified against nidaqmx-python source,
mock-tested only on Mac); `log` takes an output-stimulus object
(sweep/gaussian/uniform via `signal_generator`, as Qt's
LogDataThread) and streams armed→triggered/timeout pretrigger status
events. Acquire has the mockup's output group (OUT badge) +
pretrigger arm, both capability-gated; Setup fs/channels constrain to
the selected device's ladder; bridged sets keep their container
metadata. Suites: pytest 247, vitest 410, svelte-check 0/0,
Playwright 46 + bridge e2e 3/3 vs a real mock-driver server.

**Windows NI hardware session DONE (2026-07-07, checkpoint 4):** the
full Wave-C checklist (`dev/plans/2026-07-07-waveC-windows-checklist.md`
— results block at the top) passed on all three real devices; §3+§4
verified end-to-end over the ws protocol (39 headless checks, 0 fail;
pretrigger crossing at exactly `pretrig_samples` through the whole
bridge stack on every device; IEPE capture off the real accel now
wired on **cDAQ1Mod1/ai1**). Five real defects found+fixed with tests:
(1) pretrigger missed under host load — NI callback now **drains the
read backlog** + ~5 s DAQmx input buffer (multiple of chunk_size,
else -200877) + timeout clock starts at stimulus start + `_closing`
teardown flag; (2) **DSA fs coercion** (9234: request 8000 → get
8533.33!) — recorder adopts the true `samp_clk_rate` into
settings.fs, resizes buffers, stream-reuse still matches via
`_requested_fs`, AO warns; (3) default RSE crashed cDAQ configure —
`resolve_terminal_config_for_entry` falls back to the module's
supported config; (4) out-of-range `output_fs` → clear preflight;
caps now report `ai_vmax`/`ao_vmax` (9260 rail 4.2426 V < default
output_VmaxNI 5.0 — webui should clamp, not yet wired); (5) stale
re-trigger between captures — stored buffer zeroed before unfreezing.
Full pytest green on the hardware machine (hardware + mock, incl. new
`tests/test_streams_ni_callback.py`). No Node.js on the Windows box —
browser UI itself still mock-e2e only.

**START THE NEXT SESSION HERE:** (1) **Tore hands-on round 4** — new
surface: Fit, calibration, exports, Live PSD mode, Setup full, and
the bridge — NI path now real-hardware-verified (`pip install -e
.[serve,ni,soundcard]` then `pydvma-serve --driver nidaq --open`, or
`--driver soundcard` on Mac). Queued decisions: Fit-N/Global
optimise, CSV all-kinds vs current-view, unit axis labels, implicit
1000-sample bare-arm default, output UI shape. (2) **Webui follow-ups
from the hardware session**: clamp `output_VmaxNI` to the new
`ao_vmax` cap in Setup; surface the coerced-fs note (BridgeProvider
already adopts `configured.fs`); consider `ai_vmax` for the VmaxNI
picker. (3) **Wave D polish**: narrow-rail mini, AudioWorklet, dark
theme, wheel-embedding webui/dist (pyproject TODO), M1/M2,
browser-side (Web Audio) output stimulus + pretrigger. (4) Qt
teardown ONLY after Tore's explicit confirmation. Roadmap:
`dev/plans/2026-07-07-full-gui-replacement-plan.md`. Run: `cd webui
&& npm run dev`, `http://localhost:5173/?fixture=1` (or `?fixture=3ch`);
feedback trail: `dev/2026-07-07-round3-feedback.md` and earlier.

Auto-loaded by Claude Code at the start of every session. Contributors
and collaborators: the concrete filesystem paths below are for the
**maintainer's Windows development machine** (``C:\Users\tb267\...``)
and don't apply on Mac/Linux — translate them to your own paths or
put personal overrides in ``CLAUDE.local.md`` (which stays
gitignored). The rules themselves (edit master directly, verify
hardware-touching code before handing back, docstring discipline,
etc.) are repo-wide conventions worth following regardless of OS.

## Workflow (solo developer)

- **Edit directly on `master`** in the main repo folder
  (`C:\Users\tb267\Documents\GitHub\pydvma`). Don't create feature
  branches for isolation — the sole developer uses `git revert` or
  `git reset` as the undo button.
- Exception: genuinely risky or multi-file refactors can still use a
  branch; ask before creating one.
- Commit small, coherent changes to `master` as you go. Don't batch a
  session's worth of edits into one commit. Push only when the user
  explicitly asks.
- Worktrees under `.claude/worktrees/` are for Claude's isolated
  exploration only; prefer not to use them for iterative development
  against real hardware.

## Iteration mechanics

- The main repo is installed editably (`pip install -e .`), so saved
  file changes are immediately live in the notebook kernel.
- Recommend `%load_ext autoreload` + `%autoreload 2` in the first
  notebook cell so no kernel restart is needed.

## Environment

- Windows 11, Python via `C:\Users\tb267\anaconda3\python.exe` (base
  conda env). No per-project env.
- `pytest` available from base; tests live in `tests/`.

## Hardware (for NI acquisition work)

Three NI devices are connected on this Windows machine:

- **USB-6003** — low-cost; AO is software-timed (no hardware AI/AO
  sync possible). **Multiplexed AI**: single ADC scanning the
  channel list, so samples across channels are skewed by the inter-
  channel convert time, not simultaneous.
- **USB-6212** — M-series; hardware-timed AO, supports shared-clock
  AI/AO sync. **Multiplexed AI**: single ADC scanning the channel
  list (same sample skew caveat as the 6003).
- **cDAQ-9174 chassis** with module `cDAQ1Mod1` = NI 9234 (4-ch AI)
  and `cDAQ1Mod2` = NI 9260 BNC (2-ch AO). Shared-clock sync via
  chassis timebase. **Simultaneous sampling**: both modules are DSA
  (delta-sigma) with per-channel ADCs/DACs, so all channels are
  sampled (and output) at the same instant — no inter-channel skew.
  **IEPE/ICP excitation** is supported on the 9234 (not the 6003 or
  6212); discrete legal currents are `0.0` or `0.002` A. Anti-alias
  LPF is automatic and locked to the sample rate (delta-sigma
  inherent — not user-configurable).

**BNC loopback is wired ao0 → ai0 on each device** — that's the
standard test stimulus. Self-contained: the user does not need to be
physically present to tap a hammer or similar. Stimulus-dependent
tests (e.g. `test_pretrigger_with_stimulus`) run an AC-stimulus
preflight (`_has_ao_to_ai_loopback` in
`tests/test_acquisition_hardware.py`) and auto-skip on any device
whose loopback isn't producing signal, so adding or removing cables
just changes which tests run — nothing breaks CI.

- **Caveat (this specific USB-6003 only):** the loopback sits on a
  breakout box and there is some evidence the `ao0` / `ao1` screw-
  terminal labels on this unit may not match the silicon channels
  reported to nidaqmx (i.e. the label says `ao0` but it might be
  wired to `ao1`, or vice versa). If AO→AI tests on Dev3 start
  failing after a re-wire, physically swap the wire between the two
  AO terminals as a first sanity check before suspecting a hardware
  fault. Not believed to affect other 6003 units — just this one.
  The wire is currently left in place so tests stay runnable.

## Verify, don't assume

Before writing code against an external library (esp. `nidaqmx`,
`sounddevice`), verify the real API up front:

- `python -c "import nidaqmx.constants as c; print([x.name for x in c.ProductCategory])"`
- Inspect `dir(obj)` on a live object, or check the upstream source.

A unit test with a fake object only proves the code matches the fake —
it does not prove the fake matches reality. The 2025 `C_DAQ_CHASSIS`
vs `COMPACT_DAQ_CHASSIS` bug came from exactly this gap.

## Tests — build them as you go

Every behaviour-changing edit should either have a test (new or
updated) or a reason not to. Split by where they can run:

- **Mac-runnable (no hardware):** pure-Python logic — `_ni_backend`
  enumeration + channel-string construction, signal generation, FFT /
  TF maths, datastructure round-trips. Use mocks for nidaqmx.
- **PC-only (NI hardware plugged in):** live acquisition, pretrigger
  timing, AO loopback, clock routing. These live in
  `tests/test_acquisition_hardware.py` and auto-skip on Mac via a
  module-level `nidaqmx` detection check.
- **Parametrize over whatever is plugged in.** Don't hard-code
  `device_index=0` in tests — discover devices at collection time and
  iterate. Hardware varies (USB-6003, USB-6212, cDAQ chassis with
  different modules) and tests should keep working as devices are
  swapped in and out.
- **Cover with AND without pretrigger.** Pretrigger changes the call
  path significantly (buffer re-init, callback interaction, timeout
  fallback). Both must be exercised. The "with" variant should drive
  the AO → BNC loopback to produce a real trigger event.

## Run hardware checks yourself before handing code back

Since this Windows machine has all three NI devices connected and
Python + nidaqmx work from the shell, verify NI-touching code by
running it headlessly from the terminal (`python -c` or a small
inline script) before asking the user to try it in the notebook.
GUI is not required for driver / callback / trigger logic. Catch
hardware-surfaced bugs at write time, not at notebook time.

## Docstrings

- Write a docstring for every new public function, method, or class.
- When reading or editing an existing function, check its docstring
  against current behaviour and update any inaccuracy you notice —
  even if the edit itself was unrelated. The published MkDocs site
  (`docs/`) is generated from these, so drift becomes user-visible.
- Include hardware constraints and conventions you discover
  (voltage ranges, terminal-config requirements, clock routing
  limits, sample-rate ladders on DSA modules) in the docstring of
  the function that enforces or depends on them. Don't bury them in
  `# comments` — the rendered docs won't pick those up.

## Scope discipline

See `TODO.md` for the roadmap; it's organised by phase. Don't
freelance Phase D items when doing Phase A work.
