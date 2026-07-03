# Stage 2 handoff — design session agenda (written 2026-07-03)

For the next working session on the web UI. Context documents, in
reading order: `dev/2026-07-01-web-ui-design.md` (decision record +
staged architecture), `dev/plans/2026-07-02-web-ui-stages-0-1.md`
(what landed in Stages 0–1 and how), `TODO.md` Phase B item 6.

## Where things stand

Stages 0, 0.5 and 1 are **live**: pyproject packaging split
(`pydvma[full]` etc., v1.5.0), `.dvma` container format (default save,
legacy `.npy` loads forever), JupyterLite no-install analysis site
deployed at https://torebutlin.github.io/pydvma/lite/ via
workflow-based Pages CI. Suite ~205 passed / 4 hardware-skipped.
Qt GUI is frozen (bugfix-only) pending replacement by Stage 2.

## Stage 2 = the actual GUI replacement

One web app (Svelte/TS candidate — NOT yet decided), served from
Pages, pyodide in a worker as the maths engine only, three data
sources behind one interface: WebAudio (soundcard), websocket bridge
(`pydvma serve`, NI in the lab), files. The app shell must never gate
on pyodide boot.

### Piece 1 — the gate prototype (built, needs judging)

`dev/prototypes/scope.html` — self-contained Web Audio oscilloscope
(worklet chunk stream → ring buffer → rAF canvas), T/F/L/P keys
matching the Qt scope, synthetic-signal mode, fps instrumentation
(`window.__scopeStats`). Run:

    python3 -m http.server -d dev/prototypes 8905
    # open http://localhost:8905/scope.html  (mic needs localhost, not file://)

**Gate criterion (from the spec): smooth ≥30 fps live trace in a real
browser.**

**VERDICT (Tore, 2026-07-03): PASSED — "stable 30 fps, feels live,
seems like a go."** Stage 2 detailed design is approved to proceed.
One small curiosity for the Stage 2 rendering work: the fps sat at a
stable 30 rather than the expected 60 in a real browser (headless
evidence showed zero jitter/drops at that cadence, so it's a cap
somewhere — display refresh, browser throttling, or the prototype's
render loop — not a struggle). Understand it before choosing the
production rendering approach; not a blocker.

### Piece 2 — the design session (the main event, needs Tore)

Interactive session (~30–60 min, brainstorming skill, visual mockups
to react to). This is the "review the GUI, make it slick" conversation
— Tore's words. Scope:

- Overall layout: how scope / logger controls / analysis actions /
  figure area relate (today: 3,177-line `gui.py` with left/centre/right
  panels — see the 3C6 labsheet cell "Familiarise yourself with the
  logger window" for how it's taught).
- Data navigation: sets/channels selection, comparing datasets,
  what replaces the clickable-legend idiom ("like the mix of manual
  and zoom and clickable line controls, but not slick" — Tore).
- Workflow parity: Log Data / pretrigger / Calc FFT / Calc TF (with
  window + N_frames + averaging) / Best Match / save-load — see the
  3C6 labsheet for the exact teaching flow that must stay recognisable
  (on Tore's Mac: `~/Documents/GitHub/divc_labs/3C6/3C6_Notebook.ipynb`;
  its "Familiarise yourself with the logger window" cell describes the
  current panel layout as taught).
- Session mechanics decided 2026-07-03: design happens IN Claude Code,
  iteratively, with clickable HTML mockups in `dev/mockups/` served
  locally (same pattern as the scope prototype) or via Artifact pages.
  claude.ai/design (DesignSync) is deferred until a component library
  exists worth syncing. Ask Tore early for: 2–3 screenshots of the Qt
  logger in real use, any admired interfaces, and his top GUI
  irritations beyond those already recorded.
- Plot interactivity expectations (zoom/pan/legend) — the lite-site
  ipympl experience is informative but the app will own its plots
  (Plotly.js candidate for static, custom canvas for realtime).
- Deliverables: Stage 2 detailed design spec (new dev/ doc), then an
  implementation plan like Stages 0–1, executed with subagent flow.

## Loose ends (not blockers, don't lose them)

- **PyPI 1.5.0 publish** — README/docs already point at
  `pip install "pydvma[full]"`; publish when ready (offer: trusted
  publishing via Actions).
- **ipympl interactivity fix** (commit c594b21) — pushed; deployment
  was rate-limited on 2026-07-03, auto-retries were running. Verify
  https://torebutlin.github.io/pydvma/lite/extensions/jupyter-matplotlib/package.json
  returns 200, then Tore deletes his browser-local copy of the
  notebook so the updated install cell (ipympl==0.9.7) is picked up,
  re-tests zoom/pan.
- **Pages deploys are rate-limited** (~10/hr) — batch pushes; a failed
  "Deployment failed, try again later" usually just needs a spaced
  `gh run rerun <id> --failed`.
- AutoRegN hardware verify (next Windows/NI session, TODO Phase A6);
  labsheet `.dvma` wording before October; CE conversation for the
  supporter tier (TODO "Sustainability & impact").
