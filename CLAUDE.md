# Working with Claude on pydvma

## Current focus (update when it changes)

As of 2026-07-08: **the web logger has full functional parity with the
(now-removed) Qt GUI, plus substantial new capability.** Six orchestrated
feedback/build rounds (2026-07-05..08) delivered the whole
`dev/plans/2026-07-07-full-gui-replacement-plan.md` roadmap. Master is
pushed (b54b5a4); CI green; live at torebutlin.github.io/pydvma/app/
(+ /lite/, + docs with a full Web Logger section).

**What ships:** the three modes (Pages analysis + Web Audio soundcard,
no install; `pip install pydvma[serve]` -> `pydvma-serve` local bridge
with mock/soundcard/nidaq drivers + wheel-embedded UI + `--settings`
-> /config Setup prefill; JupyterLite). Acquisition: Setup basic/full
(processing-off defaults, NI group: IEPE/terminal/fs ladders/voltage
rails capability-clamped), pretrigger (armed, editable samples,
status events; browser AND bridge; hardware-verified sample-exact on
NI), output stimulus (signal_generator parity, browser + bridge),
persistent mini-oscilloscope + Live scope (FFT/Welch-PSD, narrow-rail
strip). Analysis: FFT/PSD/CSD-pair (E[X*Y]) /TF+coherence/Clean
Impulse, sonogram STFT|**CWT** (dependency-free Morlet) + damping
fits (both methods), unit-aware axes, Δf-intent resolution, live
recompute. Modal fit: Fit 1/2/3, **multi-set shared poles**
(TfDataList joint fit), Reject, **Refine** (auto-revert), per-mode
mute/delete/undo, fit-as-tray-card (dashed recon lines, normal line
controls), ModalData persists in .dvma (Python-readable). Scaling:
**Best Match** (via calibration factors) + **x(iω)^p display
transform** (non-destructive by design — divergence from Qt
documented). Calibration dialog (sensitivity+units). Export: .dvma /
MATLAB / CSV (file.py parity), PNG/PDF figures (theme-invariant).
Axis-nav: hover-expand toolbar, curl undo/redo (snapshot history),
Nyquist real/imag + draggable freq brush (live, 1 undo/gesture),
Bode per-pane y, coherence axis. Dark theme (no-flash, toggle).
Legacy files load forever (2019 pre-list pickles normalised; derived
kinds seed views; orphan TF convention chIn=null).

**Engineering notes that keep biting:** 32-bit WASM rejects big
NOMINAL strided views ('array is too big') — fixed via direct
as_strided in calculate_cross_spectrum_matrix AND the sonogram
(_spectrogram_complex_lowmem, byte-identical, scipy-pinned); CWT was
memory-bounded by design. Nested FFI payloads are JsProxy/JsNull —
glue uses .get/getattr/`not x`, JS omits null keys. The deployed
subpath (/pydvma/app/) is e2e-guarded (engine base-URL bug class).
The engine wheel (public/pypi, gitignored) rebuilds via
webui/scripts/build-wheels.sh — version must stay 1.5.0 (ENGINE_WHEELS).

**Suites at close:** pytest 311 / 4 hardware-skipped; vitest 592;
svelte-check 0/0; Playwright 69 + bridge e2e 7/7 (BRIDGE_E2E=1 vs a
real spawned server).

**START THE NEXT SESSION HERE — it will be on the WINDOWS PC** (Tore
is switching machines; this Mac session ends after the Qt teardown):
(1) `git pull`, then `pip install -e .[serve,ni,soundcard]` (NB the
`[qt]` extra no longer exists — do not install it). (2) **NI recheck
session**: run the full pytest (hardware tests auto-run there;
expect the pre-teardown hardware set incl.
tests/test_streams_ni_callback.py + test_acquisition_hardware.py);
then `pydvma-serve --driver nidaq --open` and hands-on the webui
against real devices — MULTI-CHANNEL capture recheck (the standing
gap: everything since round 5 was verified single-ch on Mac +
mock/protocol only), pretrigger + output sweep on each device, and
EYEBALL the two round-D notes on real hardware: the 9260
`output clamped to device rail ±4.24 V` note in Setup-full's NI
group, and the DSA coerced-fs note (request 8000 on the 9234 → note
should read 8533.3). `data/examples/` has real files for the
analysis-side checks (see its README). (3) After that session, Tore
tests solo over days/weeks — sessions should expect FEEDBACK-driven
work, not new feature waves. Round-7 hands-on surface: shared-pole
fitting, Best match / x(iω) scaling group, /config prefill, sono
single-targeting, brush v2, dark mode. (4) Small flagged follow-ups: CSD
PHASE (glue must return complex Pxy), browser pretrig threshold
control, log-y CWT heat rendering, CSD pair auto-enable on hidden
channel, orphan-fit browser e2e (task_c158292c), PWA manifest
(installability — manifest-first, offline later). (3) October
readiness: labsheets live in the OTHER repo (parked). (4) **The Qt GUI
was REMOVED** (2026-07-08, Tore's final confirmation after the round-6
parity audit closed): `pydvma/gui.py` + the orphan `oscilloscope.py` /
`logger_tester.py` and the Qt-only tests are deleted, the `[qt]` extra
is dropped from `pyproject.toml`, and `dvma.Logger` / `dvma.Oscilloscope`
now raise an actionable tombstone (see `pydvma/__init__.py`
`_REMOVED_NAMES`) pointing at the web logger. The last version that
shipped the Qt GUI is the **`qt-final`** git tag — revert there if the
desktop logger is ever needed. Feedback trail:
dev/2026-07-08-round6-feedback.md and earlier; full history in git.


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
