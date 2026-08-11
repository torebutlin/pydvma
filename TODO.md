# pydvma — TODO / Backlog

The big pre-web-UI backlog is **done**. Across 2026-06 → 2026-07 the
package gained a real test suite, a vectorised analysis core, the
`nidaqmx` NI migration (USB-6003 / USB-6212 / cDAQ-9174, hardware-
verified), and — the headline — a complete **browser web logger**
(`webui/` + `pydvma-serve`) that reached full parity with the old Qt
GUI, which has now been **removed** (last Qt version: the `qt-final`
git tag). 2026-08 added Scarlett/soundcard capture-rate correctness and
the Schoukens BLA **Nonlin** stage. The decision trail and per-round
detail live in `dev/` and the git history; this file tracks only what
is still open, as one consolidated list.

## Backlog — web logger & analysis

- **Webui exposure of `use_output_as_ch0`** — verified working and
  multi-channel-correct (prepends ALL commanded AO columns, cal factor
  1.0; `pydvma/acquisition.py` ~423). Alignment is assumed-not-measured
  — and NB the 2026-08-11 commanded-x measurement (the "NI commanded-x
  start-sync gap" tracker below) showed the AO-vs-capture offset is
  RANDOM per capture even on a routed-clock 6212, so the prepended
  column's time alignment is decorative on every current path; any UI
  exposure should say so. No UI control for it since the Qt removal.
- **Setup controls for the new capture settings** — `capture_fs`,
  `oversample`, `input_gain_db` and `input_mode` are all accepted over
  the bridge wire (the `configure` whitelist is derived from the
  `MySettings` signature) but Setup exposes none of them. The Setup
  "full" panel is where they belong, next to the NI voltage rails.
- **`calc_tf_averaged` indexes nested payloads directly**
  (`webui/src/lib/worker/glue.py` ~195-213, `s['time_axis']` etc.) — by
  the module's own JsProxy convention (documented in `calc_bla`'s own
  docstring) this is a latent bug on the real browser path. Verify the
  'across' ensemble TF path from a real browser session and switch it
  to `_get()`.
- **Multisine generation runs on the main thread** — an `O(N · lines)`
  cosine sum per capture (the preflight peak guard and each real
  capture in `webui/src/lib/stores/bla.ts` `start()`); at a fine Δf
  (large N) this freezes the UI for seconds per capture. Consider
  worker offload, or reusing the preflight-generated buffers instead of
  regenerating them.
- **Automated amplitude-level sweeps (BLA)** — V1 is manual re-runs at
  each level; the overlay (separate sets in the TF view) already works.
- **Odd multisines / detection lines** for even-vs-odd nonlinearity
  discrimination — out of scope for BLA V1 (design doc, "Out of
  scope").
- **Coherence overlay ignores line fade state.** The σ_NL/σ_n overlay
  applies `OPACITY[v.state]` (`webui/src/lib/plot/model.ts` ~830), but
  the coherence line a little above it (~765) still hardcodes
  `opacity: 0.7` regardless of the line's tri-state fade. Apply the
  same multiplier there.
- **Nonlin card's first impression on a 1-channel setup** blocks with
  "no response channels" as soon as an excitation is enabled (its one
  captured channel becomes the measured drive, leaving none for a
  response). Consider nudging the channel count up automatically on
  entering the stage.
- **DSA first-run coercion (BLA)** — the coerced sample rate is only
  known after a configure round-trip, so the first BLA run on a
  coercing device (e.g. the 9234) can abort mid-design with "start the
  run again" (`webui/src/lib/stores/bla.ts` `start()`). Consider
  forcing an automatic configure round-trip in preflight so the first
  run already knows the true rate.
- **Outputs table caps at `MAX_OUTPUT_ROWS = 8`**
  (`webui/src/components/cards/BlaCard.svelte` ~96) — fine for the
  hardware in the lab today; revisit for a larger AO device.
- **CSD phase** — the glue must return the complex `Pxy` so the CSD
  pair view can show phase (currently magnitude only).
- **Browser pretrigger threshold control** — expose the trigger
  threshold in the browser Acquire UI (the bridge already has it;
  browser uses a fixed 0.05).
- **CSD pair auto-enable on a hidden channel** — selecting a CSD pair
  should re-enable a channel that is currently hidden.
- **Orphan-fit browser e2e** — Playwright cover for the round-6
  orphan-TF fit crash (task_c158292c; was running in its own session
  in the `claude/determined-haslett-6448df` worktree — check whether
  it finished and merge or redo).
- **PWA manifest** — installability (manifest first; offline caching
  later, and only wired to deploy hashes — a stale service worker
  serving an old build is the failure mode to design against).
- **Narrow-band CWT damping memory optimisation** — a prototype was
  reverted because the `10·median/max` peak-detection heuristic
  misbehaves on narrow bands. Round-7 made the threshold a real
  user-controllable parameter (interactive panel), which removes the
  heuristic-dependence blocker — revisit on its own now.
- **Dark-mode contrast verdicts (Tore)** — deliberately shipped as-is
  and awaiting his call: the green Save Dataset button is white-on-
  green ≈2.7:1 and solid-indigo buttons ≈3.6:1 in dark. Bump if they
  bother him in use.
- **View-state persistence** — `viewState.serialize()/restore()` exist
  (round-trip ranges, legend, navigator scope — vitest-covered) but
  nothing calls them in the app; wire into autosave/restore so axis
  ranges, legend placement and the navigator scope survive a reload.
- **Round-7 leftovers (small):** sono `y lin|log` + `colour dB|lin`
  toggles stayed in the toolbar for one-click access — fold into the
  popover if Tore still finds the bar busy. LOCAL fit lines only exist
  right after a full Fit (the engine returns empty local slices on
  recon/refine/mute recomputes); return local slices from those ops if
  the toggle should survive a mute.

## Backlog — hardware, acquisition & the next PC session

- **Next Windows/PC sitting — one umbrella, three briefs:**
  1. **Run `dev/2026-08-10-windows-checklist.md`** — NI regression
     DONE 2026-08-11 (PC, 6003 unplugged): `bridge_hw_check.py` 35/35
     (now discovery-driven) + pytest 599/14/0 with hardware live. The
     9234 oversample change is verified (`dev/cdaq_oversample_check.py`
     7/7): alias rejection holds under `'lowest'` (FIR −113 dB at
     1500 Hz, 9234 hardware filter −107 dB at 5900 Hz), and the noise
     cost is only **+3.0 dB in-band PSD** (not the naive 9 dB — the
     delta-sigma floor isn't flat). **Tore confirmed `'lowest'` as the
     DSA default (2026-08-11)** — 3 dB is a small price for 8× less
     capture/decimation work; override per-log with
     `oversample='highest'` for an unusually quiet measurement. Noted:
     a bridge lpf log delivers the DSA-coerced target (2048) where the
     direct path delivers the requested 2000 exactly — self-consistent
     each way, but the paths differ. The checklist's **WASAPI question
     is unresolved and now needs a console session** — see the
     dedicated brief below.
  2. ~~**BLA on NI hardware**~~ — DONE (2026-08-11, console session):
     `bridge_hw_check.py` gained checks F/G/H, **58/58** live on the
     cDAQ-9174 + USB-6212. Measured-x BLA through the bridge is exact
     (G ≡ 1 to 1.1e-16, σ_NL = 0 on the x channel, at a native rate
     AND at the DSA-coerced 8533.33 — the samples-based spec is
     coercion-proof; 9234's second channel at the noise floor).
     **Commanded-x was REFUTED, not verified** — see the "NI
     commanded-x start-sync gap" tracker below; the webui gate is now
     closed everywhere. Optional harness upgrade: wiring 9260 ao1 →
     9234 ai2 would let check F auto-run a true 2-excitation MISO on
     analogue NI hardware (today's MISO evidence is the 2i2 digital
     loopback only).
  3. ~~**Two silent rate paths**~~ — both answered (2026-08-11):
     (a) On Windows a real 2i2 run reports `'unknown'` (no ladder
     published off macOS) at the 48 kHz mix rate — and the measured
     Windows resampler behaviour (design doc §6) makes even a
     genuinely off-ladder request safe there; `bla_soundcard_check.py`
     now prints/checks the `select_capture_fs` reason. macOS keeps
     `'exact'` via native-rate advertising. No preflight change
     needed on this evidence.
     (b) The 9260 coerces AO onto exactly the 9234's own 51200/n
     ladder (8000 → 8533.33; exact at 8533.33 — `bridge_hw_check`
     check H pins it), so a BLA run at the AI-coerced rate keeps
     output_fs == fs physically. STILL OPEN in the general case: an
     ordinary stimulus log at a coercing fs plays the drive at
     shifted frequencies with only a server-console warning — routing
     that into the bridge status channel remains worth doing.

- ~~**NEXT CONSOLE (non-RDP) SESSION**~~ — RUN (2026-08-11, console
  login; the 2i2 surfaced on every host API as predicted). Results:
  1. ~~**WASAPI-lie measurement**~~ — ANSWERED, and better than
     feared: **WASAPI/WDM-KS refuse every rate but the 48 kHz mix
     rate** (no silent resample), while **MME/DirectSound accept
     everything but resample well** — fold rejection ≈ −100 dB (at
     the noise floor), droop −0.30 dB at 0.91×Nyquist. No WASAPI twin
     of `_coreaudio.py` is needed; the Windows `'unknown'` path is
     safe in practice. Full numbers + method lessons in the design
     doc §6; reusable harness `dev/windows_resampler_check.py` (9/9).
  2. ~~**Soundcard BLA capture-rate reason**~~ — reports `'unknown'`
     at the 48 kHz native mix rate on Windows (checked in
     `bla_soundcard_check.py`); safe per the resampler measurement.
     **The 2i2 BLA identity run itself is still PENDING on Windows:**
     capture channels 3/4 are SILENT here — the digital loopback tap
     that "just works" on macOS is not wired into the Windows capture
     endpoint. Eliminated by measurement (2026-08-11): endpoint
     volume/mute; the FC2 "Send Direct Monitor mix to Loopback"
     preference (channels 3/4 stay silent ticked or unticked, and
     carry neither playback nor the DM mix — NB if that tickbox ever
     does take effect it is the WRONG source for an identity run,
     since a DM-sourced loopback mixes the analogue inputs into the
     tap; leave it off); a separate loopback endpoint appearing on
     enable (none does); the WDM-KS input pins directly (they refuse
     every PortAudio sample format). SHARPENED by the physical
     loopback test (Output R → Input 1 cable, same sitting): **the
     2i2's Windows RENDER path is dead entirely** — MME and WDM-KS
     play into silence at the jack, WASAPI shared fails to start
     (PaErrorCode −9999), WASAPI exclusive refuses to open (−9996) —
     while every Windows layer above reports healthy (session active
     at 100%, endpoint unmuted, 48 kHz matched in FC2 and Windows)
     and the CAPTURE side is calibrated to 0.1 dB. Survives a USB
     replug and FC2 being closed. So the silent loopback was never a
     routing question: nothing renders at all. Verdict: broken
     Focusrite driver install (render half) → reinstall FC2/driver
     from Focusrite (after one full PC reboot for luck), then run
     `dev/bla_soundcard_check.py` (identity via the tap, if it
     appears) and the Output-R→Input-1 knob calibration + analogue
     SISO BLA (`scratchpad` scripts from 2026-08-11 are the
     template). NB Output R = Output 2 = playback channel index 1;
     L = Output 1. The output knob's effect is uncharacterised until
     playback works (published ceiling: 16 dBu ⇒ 6.91 V pk at max).
  3. ~~**2i2 calibrated-volts re-confirm**~~ — CONFIRMED on Windows
     to **−0.108 dB** (2.4692 V measured vs 2.500 V, Rigol 1 kHz
     5 Vpp, 9 dB Line), identical on MME and WASAPI — matches the
     Mac's 0.10 dB. NB the Rigol is NOT USB-connected, so the SCPI
     route for `verify_input_scaling` stays untested; the manual
     known-level flow is exactly what this session exercised.
  4. ~~**`_soundcard_specs` profile match on Windows**~~ — FIXED:
     `device_profile()` takes a `neighbours` list; the generic
     Windows endpoint names resolve through the WDM-KS twin
     (`wc4800_8219` embeds USB productId 0x8219, the stable key),
     vendor-gated and single-candidate-only. Loopback warning +
     calibrated volts + serve capabilities all fire on Windows now.
  5. ~~**Windows sanity (checklist §5)**~~ — all pass.
  **New Windows finding — mono capture is a downmix:** `channels=1`
  on any shared-mode endpoint delivers (ch1+ch2)/2, silently −6 dB
  on a single-input calibrated measurement (pinned in
  `windows_resampler_check.py`). pydvma defaults channels=2, but a
  deliberate 1-channel soundcard log on Windows hits it — consider
  capturing ≥ 2 and slicing, or a warning, on the Windows soundcard
  path.

- **NI commanded-x start-sync gap (was: "cDAQ commanded-x is refused,
  conservatively" — now measured, and it is not just the cDAQ).**
  2026-08-11 hardware run (`bridge_hw_check.py` check G): a routed AI
  sample clock locks the RATE but each capture is a window of the
  free-running AI stream, so the AO start lands on an arbitrary tick
  — the per-capture phase is RANDOM on the 6212 exactly as on the
  cDAQ (commanded-x |G| collapses to ~1/√M ≈ 0.43 at M=4 with
  σ_NL ≈ 2.4·|G|, through a loop measured-x resolves to 1 to 1e-16).
  The webui commanded-x gate is now closed on EVERY path
  (`BLA_COMMANDED_X_START_SYNC_PROVEN` in
  `webui/src/lib/stores/bla.ts`). Reopening it — and lifting the cDAQ
  exclusion — is the same piece of work: start AO and AI off one
  shared start trigger (or restart the AI task armed on the AO start)
  and prove a fixed offset with check G's measurement, which is
  purpose-built to flip when this lands. Measured-x is unaffected and
  remains the (only) NI BLA mode.
- **Input-scaling verification tool ("calibration against a known
  source")** — the Python helper is **DONE**: `dvma.verify_input_scaling`
  (`pydvma/verify.py`) plays/commands a known-RMS tone and compares the
  measured volts against it, via a robust windowed-periodogram tone
  estimator (immune to broadband noise / other tones); `source='loopback'`
  plays the tone itself (absolute on NI's calibrated AO→AI path, chain-
  consistency-only on a sound card — prints a warning, doesn't refuse);
  `source=RigolDG1022Z(...)` commands an external SCPI generator instead
  (`pydvma.verify.RigolDG1022Z`, pyvisa-based, VRMS unit mode) — the only
  way to verify a sound card whose loopback is DIGITAL (e.g. the 2i2's
  inputs 3/4, which copy the output stream pre-preamp and so can't see
  the analogue input gain at all). Idea from the 3C6 lab's `check_setup`
  level meter (divc_labs repo), which checks levels against a target
  band but cannot verify absolute scaling without a known source.
  Remaining, all webui/GUI follow-ups (YAGNI'd this round — no hardware
  on the Mac to test them against):
  (a) a Setup "Verify input scaling" button for the NI-loopback path
  (the webui can already drive AO, so this needs no new bridge op —
  just wiring the existing capabilities together in the UI);
  (b) a bridge-gated Rigol variant — the browser cannot reach VISA/USB
  instruments, so this needs a `pydvma-serve`-side op plus capability
  gating (only offer it when the server process can import `pyvisa`
  and finds a DG1xxx).
  **Live-verification status (2026-08-11 PC session):** the underlying
  NI loopback path is proven (bridge_hw_check F/G/H, 58/58) but
  `verify_input_scaling` itself hasn't been run against hardware; the
  Rigol SCPI route is UNTESTED because the bench Rigol has no USB
  cable connected (the manual known-level flow it automates was
  exercised instead — 2i2 calibrated volts confirmed to −0.108 dB);
  the 2i2 absolute check waits on the Windows driver reinstall.
- **Device identity on the Python path** — the webui now re-resolves
  devices by NAME when PortAudio indices shift mid-session, but
  `MySettings(device_index=…)` in a notebook is still positional;
  consider accepting a device name there too. Same gap for the 2i2
  loopback-channel warning (Setup shows it; the Python path has no
  equivalent).
- **`_soundcard_specs.PROFILES` has exactly one entry** (Scarlett 2i2
  4th Gen) — add interfaces as they are characterised.
- **IEPE auto-detect via bias-voltage probe** — enable 2 mA excitation
  and read the DC bias before AC coupling to classify what is
  connected (~24 V open / 8–14 V IEPE / ~0 V low-Z) so
  `iepe_excit_current_A='auto'` can configure each 9234 channel.
  Sensitivity still has to be entered manually.
- **TEST THE ESI U24 XL (Tore — action item, 2026-08-11).** Find the
  unit, then a bench session: `dvma.verify_input_scaling` with the
  Rigol as known source (needs the Rigol on USB for the SCPI route —
  or drive it manually and read the PASS/FAIL table) for absolute
  scaling + clip point, plus a noise-floor capture for effective bits.
  This is the decision gate for the 3C6 station-box choice (agreed
  lineup: `dev/2026-08-11-audio-daq-device-survey.md`).
- **`streams.max_input_fs` still has no direct unit test** — the
  `select_capture_fs` tests cover the adjacent logic but not this.
- **Scarlett gain control is a dead end — do not re-investigate.** No
  CoreAudio HAL properties on the input scope; Focusrite Control 2's
  AES70/OCA server gates its object tree behind an authenticated
  x25519 pairing agent needing a human in FC2; the USB interfaces are
  exclusively owned by `usbaudiod`. `Mathieu2301/Focusrite-Control-API`
  targets FC1 (3rd gen) and exposes Air/Inst/LED but not gain.
  **Windows confirmation (2026-08-11, 2i2 4th Gen on the PC):** FC2's
  OCA server IS connectable here — OCP.1 binary over a plain WebSocket
  on `127.0.0.1:58323` (port 58322 is a sibling HTTP server that 404s),
  no TLS/auth to open the socket. But the tree is gated identically:
  RootBlock (ONo 0x64) has a single member, an `AuthenticationAgent`
  block (ONo 0x1000, proprietary Focusrite class 1.2.65535.0.4878.1);
  `GetMembersRecursive` and the agent's `GetMembers` both return
  `NotImplemented`, and every standard AES70 manager except
  SubscriptionManager (ONo 4) answers `BadONo`. So no gain/Air/Inst/48V
  object is addressable without completing the agent's pairing (human
  approve-in-FC2), exactly as macOS. The Windows-native audio route is
  also closed: the 2i2 inputs surface only via WDM-KS, and Core Audio's
  MMDevice enumerator returns **0 capture endpoints** under RDP, so
  there is no `IAudioEndpointVolume` hardware slider to read/write — and
  this is why the §3 WASAPI-lie question cannot be measured from an RDP
  session (no shared-mode WASAPI endpoint for the 2i2; needs a console
  login). Only pairing-free readable facts: serial `S2J525A573389F`,
  productId 33305 (0x8219). Probe script: not kept — one-off.
- **Lab-testing period (Tore, days/weeks)** — real structures, real
  measurements; expect feedback-driven fix rounds. Newest surfaces to
  exercise: the Nonlin/BLA stage, Setup level check + gain-derived
  volts, shared-pole fitting, Best-match / x(iω) scaling,
  freq-navigator. `data/examples/` has the two real regression files;
  `dev/bridge_hw_check.py` is the reusable headless NI harness to run
  after any acquisition-path change.

## Old-logger (V2.9a) feature review list (round-7f survey)

The recovered MATLAB source of the original JW/Tore logger was surveyed
on 2026-07-09 (Tore's OneDrive, "…Pen Drive History IV/Data logger
V2.9a"; full inventory in `dev/2026-07-09-round7-feedback.md`). Worth
considering, in rough priority:

1. **Grid / roving-hammer TF logging** (`gridlog*.m`) — measurement
   grids with next-point prompting and per-point re-log; the
   acquisition side that feeds **mode shapes** (ties into the parked
   mode-shape plotter thread).
2. **Legacy modal-parameter file import** — the old logger saved
   `md_param` (n×4: f, Q, |A|, arg A) `.mat` files; a ~30-line importer
   maps them onto `ModalData`. Valuable if archived `_param.mat` files
   still matter.
3. **"Add/edit a mode by hand" reconstruction authoring** (`reconpar`
   family) — type f, Q, amplitude-in-dB to add or tweak a mode without
   refitting; a nice manual authoring loop on top of the fits.
4. **Compensate time delay** — multiply a channel by `exp(-i·2πf·τ)`
   (vibrometer / instrumentation phase cleanup). Tiny and useful.
5. **Digital filtering from fitted modes** — per-mode filter
   coefficients to isolate one mode's time-domain contribution.
6. **RFP (rational-fraction-polynomial) fitting** — an alternative
   fitter family; useful cross-check for overlapping modes.
7. **Auto-identify TF measurement type** — infer disp/vel/acc from the
   fitted-phase deviation (the ⚠ flag's data) and suggest the type
   that minimises it. Natural extension of the phase-significance flag.

Covered already: measurement-type exponent (Fit card's TF type =
`ipower`), (iω)^p display transform, sweep logging, impulse cleaning
(`hammerclean`), decay fits. Low value (research-specific): cepstrum
sonogram, Signal Wizard export, bowed-string/musical-acoustics extras.

## Release & sustainability admin (Tore's threads)

v2.0.0 shipped 2026-07-08 (PyPI + tag + GitHub release); v2.1.0 is in
flight (see CHANGELOG.md). Remaining admin, no deadlines:

- ~~**Zenodo DOI**~~ — DONE (2026-08-11): the GitHub–Zenodo integration
  is enabled (future releases archive automatically), v2.1.0 is
  archived, and the concept DOI **10.5281/zenodo.21888383** is in
  `CITATION.cff`, `.zenodo.json` metadata, and the support page. This
  unblocks the JOSS submission.
- **Cambridge Enterprise conversation** — required before any payment
  route for the institutional-supporter tier; until then the support
  page's contact-email route stands. When a route exists, add it to
  the support page (and optionally `.github/FUNDING.yml`, which today
  only links the Sponsor button to that page — no payment links).
- **JOSS paper** — Tore is authoring it personally; the draft +
  submission checklist live in his OneDrive
  (`…/Projects/2026_pydvma_paper/paper`; ORCID already applied).
  Outstanding: Zenodo DOI, word-count check, submit at joss.theoj.org.
- **Release artifacts note** — `dist/` (gitignored) holds local build
  artifacts; pre-2.0 builds were moved to a scratchpad and are
  recoverable from PyPI if ever needed.

## Housekeeping (smaller open items)

- **Finish the docs accuracy audit** — the Qt pages were corrected
  when the GUI was removed; the rest of `docs/` still deserves a
  page-by-page cross-check against real behaviour (several pages were
  originally Claude-generated).
- **Test-suite tail** — beyond the bug-pin cases already landed:
  broader `modal.py` multi-mode synthetic fits, `datastructure.py`
  save/load and list ops, and `file.py` `.npy` / CSV / MATLAB import
  round-trips.
- **Import-time / structure cleanup (remainder)** — cache lazy imports
  in `pydvma/__init__.py.__getattr__` (`globals()[name] = ...`);
  silence the `DeprecationWarning: __package__ != __spec__.parent`
  from `_ni_device_specs.py:227`; fix the copy-paste docstrings on
  `DataSet.calculate_tf_set` / `calculate_cross_spectrum_matrix_set` /
  `calculate_tf_averaged` (all three still say "Calls calculate_fft").
- **`streams.py` singletons** — the module-level recorder globals
  (`REC` / `REC_SC` / `REC_NI` / `REC_MOCK`) and `start_stream`
  re-`__init__` are fragile; pass recorder instances explicitly. (The
  mocked harness now guards the behaviour.)
- **Centralise optional hardware imports** — a small `_hardware.py`
  that does the `sounddevice` / `nidaqmx` try-imports once and exposes
  flags + handles, instead of the scattered try/except in `streams.py`
  / `options.py`.
- **Better output-signal control** — offset, ramp, and save/reload of
  signal definitions (the web logger covers type / amplitude / band /
  sweep; the BLA multisine spec is save/reload-able via `.bla` meta).
- **Repo-root cleanup** — the six tracked docs-about-docs files
  (`DOCS_SETUP_SUMMARY.md`, `MKDOCSTRINGS_INTEGRATION.md`,
  `DOCUMENTATION.md`, `README_DOCS.md`, `.mkdocs_quickref.md`,
  `CODE_STRUCTURE.md`) and the personal `logger.yml` conda export —
  fold anything still true into `docs/` or `CLAUDE.md` and delete the
  rest.

## Deferred / low-urgency (no blockers)

- **Mode-shape plotter, MAC helper, ODS plotter** — teaching-useful,
  not urgent. Starter recipes in `dev/mode-shape-sketches.md`.
- **Large-data / streaming acquisition + big-file storage** —
  `scipy.fft` `workers=-1`, optional `pyfftw`, and a chunked/streaming
  cross-spectrum path for recordings that don't fit in RAM; the
  `.dvma` manifest already reserves a `storage` field as the versioned
  hook for an HDF5/Parquet backend. Pick up when a real "too big"
  workload appears.
- **BLAS thread-pinning for small-matrix workloads** — mostly
  user-side; scope `threadpoolctl.threadpool_limits(1)` around the
  modal-fitting loops if batch fitting ever shows jitter. Diagnosis in
  `dev/python_blas_threading_note.md`.
- **Review `multiply_by_power_of_iw` initialisation** (`analysis.py`
  ~63–91) — correct today but fragile if `channel_list` semantics
  change.
- **ML plugin as a separate repo** — keep the core dependency-light;
  the natural open-core seam.

## Parked (other repo)

- **Teaching notebooks / labsheets for the `.dvma` era** — the 4C6
  labsheets live in a separate repository; update the "you should have
  a `*.npy` file" wording there before October.

---

Everything checked off across the June–August 2026 work — the analysis
speedups, the `nidaqmx` migration, the whole web-logger build, the
`.dvma` format, the Qt removal, the Scarlett capture-rate arc, and the
Schoukens BLA arc — is recorded in the git history and in `dev/`. This
file deliberately no longer duplicates it.
