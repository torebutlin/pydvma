# Working with Claude on pydvma

## Current focus (update when it changes)

As of 2026-07-10 PM (round 9 **hardware-verified on the PC**, commits
local): bridge_hw_check 44/44 incl. new check E on all three devices;
the multiplexed `max_input_fs` division confirmed live (6003 2ch
captures at exactly 100k/2 = 50 kHz — DAQmx accepts running AT the
aggregate limit; 6212 400k/2; DSA 9234 keeps 51.2k per-channel) and
regression-guarded (`test_lpf_log_respects_per_channel_max_rate` +
a 6212 anti-alias proof: an unfiltered 2 kHz log folds a 1300 Hz tone
in-band at ~0.5 V, lpf_on crushes it >40 dB). The day's testing found
and FIXED four real bugs: (1) **AO shared-clock mis-rating** — the
6212 routed the AI sample clock as AO source even when output_fs ≠
the AI stream rate, so lpf_on + stimulus played the drive 100x fast
(now rate-gated; hardware-verified); (2) **resample_to_fs missed
exact ratios for coerced capture rates** — the 6003's 80 MHz timebase
coerces 48 kHz→48019.2077 Hz, whose 833/5000 back-ratio is past
limit_denominator(1024), landing "8 kHz" lpf logs at 8003.2 Hz (now a
Stern–Brocot simplest-in-tolerance fallback with a 2^19-tap FIR cap;
also un-no-ops resample-to-match between near-identical rates);
(3) **webui bridge output defaults** — an enabled-but-untouched
output group sent amp 0 / f1 0 / f2 0 (a windowed DC pulse) while the
chip claimed "sweep 0.3V 10-500Hz" (bridge.ts now uses the card
defaults); (4) **soundcard stream leak** — start_stream overwrote
REC_SC without closing the old InputStream (fatal on single-handle
MME under RDP, where it blocked every bridge log after configure;
plus the documented lpf unfiltered fallback now also covers an
oversampled OPEN being refused — PortAudio check_input_settings
approves rates InputStream then rejects). Windows-PC infra unlocked:
Playwright ran here for the FIRST time — 86/86 incl. all 7 bridge
e2e (needed `npx playwright install`, hand-started webServers — the
config commands are POSIX-only — and the new PYDVMA_PYTHON override
in bridge.spec.ts; bare `python3` is the MS-Store stub on Windows);
webui/public/pyodide vendored (never fetched here — engine boot
failed from the served dist until `bash scripts/fetch-pyodide.sh`).
Soundcard under RDP: paths work but capture is digital silence, only
44.1k opens, no default input — see the rdp-audio-quirks memory.
Suites at close: pytest 407/19 (hardware live), vitest 653/1, check
0/0, Playwright 86/86, mkdocs --strict green. Engine wheel + dist
rebuilt at HEAD.

Earlier that day (round 9 as landed on the Mac): third feedback batch
(`dev/2026-07-10-round9-feedback.md`): **CWT wavelet Q is a slider**
(4–64 + exact box to 128, nFFT feel) with **voices/octave AUTO by
default** (`autoVoicesForW0` = ladder ≥ max(16, 0.6·w0) — Morlet tiling
bound, default CWT unchanged; explicit pick pins it, legacy files with
hand-picked voices load pinned); **logging digital low-pass toggle**
(Setup full, off by default): fs keeps its meaning, `lpf_on` makes the
capture oversample at the device max (`streams.max_input_fs` — NB
multiplexed NI devices: ai_max_rate is AGGREGATE, divided by channels)
and resample down behind `analysis.resample_to_fs` (rational polyphase
Kaiser FIR, 96 dB stopband, zero-phase; DSA-coercion-safe; clip check
on the RAW peak; `lpf_capture_fs` recorded; web-audio path records at
native rate + engine-resamples); and a **Time-view Resample tool**
(match-a-set dropdown with fs values + custom fs; down = anti-alias
decimation, up = band-limited interp — NOT linear, which images; toast
Undo one level; derived results recompute). NI hardware verification
was pending — now DONE, see above. Engine wheel rebuilt (same 2.0.0
name). Suites at the Mac close: pytest 340/3, check 0/0, vitest
652/1, Playwright 79/7, mkdocs --strict green.

Earlier (2026-07-09, round 8):
Tore's second feedback batch landed
(`dev/2026-07-09-round8-feedback.md`): the **fit summary chip is
draggable + minimisable** (module-scope UI state survives re-mounts;
re-clamps on expand so an edge-parked chip never clips its buttons;
z-index above the legend so it can't park ungrabbably under it);
**‹ › shift a selected line subset** as a group
(`selection.shiftLines` — per-SET circular rotation so a ch+fit pair
cycles together and a one-line fit set stays put; all-on and
clean-set-solo keep the old stepping); a **header computing chip**
(`BusyChip` — actions.busy OR damping.busy OR engine 'loading' →
"starting engine…"; 300 ms delay-in so fast calcs never flash it;
indeterminate by design, the worker has no progress frames); and a
**docs audit** (stale "Nyquist brush in flight" fixed; all-hidden Fit
refusal, Best-match-ignores-visibility, multi-set compose rule, and
the round-8 features documented; mkdocs --strict green). Suites:
check 0/0, vitest 648/1, Playwright 78/7.

Earlier that day: **rounds 7 through 7h — the whole first
lab-testing feedback day — are fully landed, PUSHED, and DEPLOYED (CI
green; the live app carries 4c92545).** The 7d–7h additions on top of
what's described below: legends + coherence now EXPORT with figures per
their toggles (SVG legend overlay follows the restyle contract;
e2e pixel-diff round-trip); the **JW-logger .mat import** was fixed
twice over — coherence columns attach as `tf_coherence` instead of
poisoning fits as fake TF channels (guitar file: fit railed at the
window edge before, fn=182.13 ζ=0.0085 after), then the layout was
matched to Tore's RECOVERED original MATLAB source (V2.9a: `freq`=fs,
`dt2`=[n_time, n_spec_cols, n_son], yspec interleaves [H,coh] pairs) —
survey of that source produced the "Old-logger feature review list" in
TODO.md; **fit self-awareness**: per-mode phase-significance ⚠ (>30°
from 0/180° → check TF type) + Refine divergence warning (>10% fn move
→ toast with Undo); **the modal fit got a structural upgrade** —
`estimate_global_constants` (linear re-solve of complex constants +
per-channel global RH/RL·ω⁻² residues at fixed poles) now powers the
global reconstruction, and `modal_refine` is VARIABLE PROJECTION
(poles-only nonlinear; rescued a railed seed to a physical 234 Hz mode
on the real guitar file); and **fits follow visible lines** — the
legend/tray tri-state selects exactly which line(s) are fitted (solo =
fit one), with the Fit card showing "N of M lines". Suites at close:
pytest 328/3, vitest 642/1, `npm run check` 0/0, Playwright 77/7.
Gotchas that bit: griffe-strict docstrings fail the docs CI (one param
per Args line, returns in prose; gate with `python -m mkdocs build
--strict`); Playwright ONLY from webui/.

Earlier that day — round 7b:
Clean Impulse is an on/off TOGGLE (raw stashed + cleaned cached, never
re-cleans its own output; save writes the applied copy); legend
defaults SE. Round 7c: CWT ladders widened (w0 + voices/octave to 64);
the damping panel sits in a RIGHT-hand column on wide screens (charts
stacked, click-to-expand fills the plot region and pops back; narrow
keeps the below-dock); every damping chart saves as its own PNG via the
Save Figure delivery + restyle contract (charts follow the
self-contained-SVG rules: xmlns + data-role + CHROME hexes) and the
band table saves CSV; the export audit's one correctness gap — Bode
exporting ONLY its magnitude pane — is fixed (getSvg composites both
panes, flattened; e2e-guarded). CI gotcha learned: gate on `npm run
check` (app tsconfig, ~172 files), NOT bare svelte-check (~104) — the
bare form missed a real rune-shadowing error that failed CI.

All nine round-7 items are done (dispositions:
`dev/2026-07-09-round7-feedback.md`): sono axis controls actually work
now (the toolbar was fed [0,1] extents and setRange('sono') was never
read — e2e-guarded end-to-end since); the zoom toolbar docks in a
`.plot-nav` strip above the plot instead of floating over the data;
**the interactive damping panel** replaces the inline fn/Qn box
(peaks mode: the restored Qt decay-fit plot + draggable threshold line
+ draggable start-time line over the sonogram, `peak_threshold`
promoted to a real analysis parameter; bands mode: NEW
`calculate_damping_by_band` — Butterworth ladder ('all'/oct/1-3rd/
1-10th-dec) + Schroeder EDC → EDT/T20/T30/T60/band-Qn); CWT wavelet-Q
(`w0`) exposed in the Sono card; Clean Impulse now auto-recomputes
existing derived results; modal fit lines got a local|global toggle
(all sets/chans, first-class pseudo-sets, pink overlay retired);
legend wraps to columns >10 entries + compact dot-grid mode. Engine
wheel rebuilt (same 2.0.0 filename). Latent bug fixed on the way:
damping as a session's FIRST compute parked forever (no engine.boot()
kick — see the calcDamping comment). Suites on this Mac: pytest 319/3
skipped, vitest 623/1, svelte-check 0, Playwright 72/8 (hardware +
capability tests only run on the Windows PC).

Round-1..6 context (2026-07-05..08): six feedback/build rounds
delivered the whole `dev/plans/2026-07-07-full-gui-replacement-plan.md`
roadmap; live at torebutlin.github.io/pydvma/app/ (+ /lite/, + docs
with a full Web Logger section).

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
SVG: scoped CSS BEATS inline presentation attributes — an opaque
.plot-bg { fill: var(--surface) } silently covered the sono heat
canvas for weeks while fill="transparent" sat ignored; canvas-pixel
and attribute assertions stayed green throughout. Rendering claims
must be verified on SCREENSHOTS of visible composited pixels (the
sono e2e now does; keep that standard for any layered-canvas work).
The engine wheel (public/pypi, gitignored) rebuilds via
webui/scripts/build-wheels.sh — keep ENGINE_WHEELS
(webui/src/lib/stores/engine.ts) in sync on version bumps: the
hard-coded `pydvma-<version>-py3-none-any.whl` filename must match the
rebuilt engine wheel or the app breaks at boot (as of v2.0.0).

**Suites at close:** pytest 352 / 15 capability-skipped (Windows PC,
all NI hardware live); vitest 592; svelte-check 0/0; Playwright 69 +
bridge e2e 7/7 (BRIDGE_E2E=1 vs a real spawned server).

**The Windows NI recheck is DONE** (2026-07-08, this PC — full
write-up in `dev/2026-07-08-windows-ni-recheck.md`): full pytest
green with hardware live; the standing multi-channel gap is closed
(real 4-ch bridge capture on the 9234 + 4-ch live scope and Log in
the built UI); pretrigger + output sweep verified through the bridge
on all three devices (`dev/bridge_hw_check.py`, 38/38 — a reusable
headless harness, run it against `pydvma-serve --driver nidaq` after
any acquisition-path change); both round-D notes eyeballed in the
real UI with real caps ("output clamped to device rail ±4.24 V";
"device runs at 8533.3 Hz (requested 8000)"). The recheck's NEW
finding is FIXED (task_01e8edaf): the webui acquire store's
`reclampOutputFs` now stages `output_fs` from the effective output
device's `device_caps.ao_max_rate` whenever the input fs exceeds it
(MySettings otherwise defaults output_fs = fs and the 6003 rejects
the log), and Setup shows "output runs at 5000 Hz (device AO
limit)" — verified end-to-end on the real Dev3 (bridge-payload
check + a real UI log through vite + `pydvma-serve --driver
nidaq`).  The NEWER finding from that verification is ALSO FIXED
(its spawned session, merged same day): an unset NI/mock
`output_device_index` now follows the resolved input device when
the output driver matches the input driver (options.py), instead of
silently defaulting to device 0 — previously a Dev3 input drove AO
on the cDAQ (mis-routed stimulus / rail errors on multi-NI
benches). Hardware-verified: Dev2-input + unset output routes the
sweep out of Dev2's own AO.

**v2.0.0 IS RELEASED** (2026-07-08 evening): PyPI carries the fat
wheel + sdist (`pip install "pydvma[serve]"` works cold), the
`v2.0.0` tag is pushed, and the GitHub release (CHANGELOG body +
artifacts) is published. The sustainability surface is live
(CITATION.cff with Tore's ORCID, docs/about/support.md, FUNDING.yml
Sponsor-button link — NO payment routes by design until the Cambridge
Enterprise conversation). The JOSS paper draft moved OUT of the repo
to Tore's OneDrive (Work Research/Projects/2026_pydvma_paper/paper) —
he authors it personally. **The Qt GUI was REMOVED** (Tore's final
confirmation after the round-6 parity audit): `dvma.Logger` /
`dvma.Oscilloscope` raise actionable tombstones (`_REMOVED_NAMES` in
`pydvma/__init__.py`); the last Qt version is the **`qt-final`** git
tag.

**NEXT SESSIONS: Tore is lab-testing solo over days/weeks — expect
FEEDBACK-driven work, not feature waves. `TODO.md` is the single
canonical pickup list** (web-logger follow-ups, hardware ideas,
housekeeping, deferred items, and Tore's release/sustainability admin
threads — Zenodo DOI, CE, JOSS). Feedback trail:
dev/2026-07-08-round6-feedback.md and earlier; full history in git.
IEPE with a live accelerometer is verified (accel on cDAQ1Mod1/ai1;
`dev/iepe_accel_check.py`); `dev/bridge_hw_check.py` is the reusable
headless NI harness for after any acquisition-path change.


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
physically present to tap a hammer or similar. **An IEPE
accelerometer (~100 mV/g class) is plugged into cDAQ1Mod1/ai1** (as
of 2026-07-08) — it sits motionless on the bench, so expect only a
noise floor (~30 µV rms) plus the cold-start bias transient, but it
lets IEPE excitation be exercised against a real sensor chain
headlessly (`dev/iepe_accel_check.py`). Stimulus-dependent
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
