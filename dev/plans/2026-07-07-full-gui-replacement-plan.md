# Full GUI replacement — execution plan (2026-07-07)

Tore's directive (2026-07-07): continue development to a **fully
replaced GUI** — the webui becomes THE pydvma interface — with **full
NI-DAQ support** and the **three modes of use** from the Stage-2
decision record (`dev/2026-07-01-web-ui-design.md`): Pages/pyodide
analysis, Pages/Web-Audio soundcard, and local `pydvma serve`
(nidaqmx + websocket bridge, serves the UI itself). The **Qt GUI stays
in place, frozen bugfix-only, until Tore's final confirmation** of the
tidy-up. **Pushing is now authorized** — commit AND push at sensible
checkpoints; CI (webui.yml quality gate) + Pages deploy (docs.yml →
`/app/`) activate on the first push.

Orchestration model (per this session): Fable coordinates; Opus
subagents implement scoped, disjoint-file tasks with no-commit rule;
Fable reviews every diff, runs full suites (pytest root + vitest +
two-pass Playwright + `npm run check`), commits coherent chunks,
pushes checkpoints, and watches CI (`gh run list/watch`).

Baselines at plan time: pytest 205 passed / 4 skipped; vitest 307;
Playwright 38 + growing; `npm run check` 0/0.

## Checkpoint 0 — round-3 wave + FIRST PUSH (in flight)

Three agents working `dev/2026-07-07-round3-feedback.md`: (1) PSD
mixed-fs crash root-cause + per-kind compute errors + live slider
drag; (2) tray whole-card tri-state; (3) osc view-time combo + fmax +
Welch-PSD averaging mode + Setup-full grouped device options
(nidaq-ready structure). Integrate, verify, commit → **push #1**
(everything since v1.4.0: Stages 0–1, Plan 1, redesign, Plan 2 chunks,
rounds 2–3). Watch both workflows; fix red. Verify Pages serves
`/pydvma/app/` and the JupyterLite site still builds.

## Wave A — Plan-2 remainder (browser-mode features, Mac-runnable)

From TODO.md Phase B item 6 backlog, in priority order:

- **A1 Fit stage** (modal fitting + reconstruction): pydvma
  `modal.py` via the pyodide worker (`glue.py` wrappers); Fit stage
  card (freq-range select, N modes / auto, fit, reconstruction
  overlay on the TF plot, mode table with fn/ζn, delete-mode);
  enables the last gated stage (`fitEngine` capability). Sonogram
  damping-fit interactivity folds in here if cheap.
- **A2 Calibration**: calibration flow + `channel_sensitivities`
  write-through to `.dvma` (units live in the manifest already);
  per-channel cal factor UI (tray or Setup), applied on
  display/compute like the Qt logger's dialog.
- **A3 Figures/export tab**: export-preview (the R-round layout
  polish anticipated it), browser MATLAB `.mat` / CSV export
  (pyodide scipy.io.savemat; CSV in TS), figure-export font fidelity.
- **A4 Acquisition depth (browser/Web Audio)**: pretrigger
  (threshold-armed capture reusing the monitor ring), output/stimulus
  signals (Web Audio output: sweep/white/gaussian + OUT badge +
  log-with-output), CSD off-diagonals view, header/tab level meters.
- **A5 polish (any wave)**: dark theme, AudioWorklet migration,
  narrow-rail mini strip, minors M1/M2.

Each A-task: design vs the round-2 mockups first (they contain Fit +
output-signal treatments), then implement. Push checkpoint after each
coherent group lands.

## Wave B — `pydvma serve` bridge (Plan 3 core, Mac-runnable)

- **B1 `pydvma/serve.py`** + `pydvma[serve]` extra: local process
  wrapping existing `streams`/`acquisition`, streaming chunks over
  websocket, serving the built UI statically (no internet needed in
  the lab). Protocol: JSON control (enumerate/configure/start/stop/
  log) + binary sample frames; versioned. `MockRecorder` powers
  hardware-free protocol tests; `sounddevice` backend verifiable on
  this Mac end-to-end.
- **B2 webui `BridgeSource`**: the third data source behind the
  existing source interface (WebAudio / File / Bridge); capability
  negotiation (bridge advertises backends: soundcard/NI, device
  lists, fs ladders, IEPE, pretrigger, AO); Setup grows the "nidaq"
  group slot when the bridge reports NI. Mode detection: bridge
  present (served by `pydvma serve` or localhost probe) vs Pages.
- **B3 launch-config + scenarios**: settings/config injectable at
  launch (from a notebook / CLI flags / URL params) the way the old
  Qt logger took `MySettings`; document the three modes; PWA
  manifest if cheap. Wheel/dist packaging so `pip install
  pydvma[serve]` ships the built UI.

## Wave C — NI support through the bridge (Mac = mocks only)

NI-DAQmx does not run on macOS: ALL NI work here is desk work +
mocked tests (`_ni_backend` enumeration/channel-string logic is
already Mac-tested); **hardware verification happens in a Windows
session on Tore's machine** (three devices + ao0→ai0 loopbacks per
CLAUDE.md; `tests/test_acquisition_hardware.py` conventions).

- **C1 NI backend over the bridge**: enumeration (device/product
  category/AI-AO counts), channel config (fs ladders incl. DSA
  9234 constraints, IEPE 0/2 mA, terminal config), pretrigger via
  the nidaqmx path, AO stimulus + shared-clock AI/AO sync options,
  `VmaxNI` scaling (TODO Phase C item 14).
- **C2 Windows hardware-session checklist**: a runnable doc of
  exactly what to verify per device (6003 multiplexed-skew, 6212
  sync, cDAQ DSA/IEPE), mapping to auto-skipping hardware tests.

## Wave D — replacement finish (needs Tore)

- Round-N hands-on cycles on each wave's output (established rhythm).
- Qt GUI: stays untouched; final tidy-up (removal/deprecation of
  `gui.py`/pyqtgraph deps) ONLY after Tore's explicit confirmation.
- Docs: MkDocs pages for the webui modes; labsheet migration notes;
  October-readiness check.

## Standing constraints

- Old Qt GUI is never edited except bugfixes (compat contract #1:
  `import pydvma as dvma` API unchanged; legacy `.npy` loads forever).
- Every behaviour change tested at the right layer (pytest / vitest /
  Playwright); hardware-touching code carries Mac-runnable mocked
  tests + a Windows verification note.
- Design-first for user-facing surfaces: check the round-2 mockups
  before building; queue design questions for Tore's hands-ons rather
  than blocking.
