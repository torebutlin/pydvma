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

- ~~**Native engine, stages 3–4**~~ — **DONE** 2026-08-18/19
  (`dev/2026-08-18-session-journal-round.md`; plan
  `dev/plans/2026-08-18-session-journal-launch-plan.md`). The session
  journal (`pydvma/journal.py`, serve ownership with captures
  registered at birth, crash-recovery adoption, `/engine` journal ops)
  and `dvma.launch` / `Session` (`pydvma/session.py`) both landed with
  full suites green. Committed locally, **not pushed**, and **not yet
  live-verified** — the round doc's next-lab-visit checklist is
  unticked. NB one deliberate asymmetry recorded there: the app's
  autosave `journal_set` is **not** generation-checked (the app owns
  the whole document, so it has no partial-write race to lose); only
  `Session.push`, a partial writer merging into what it read, carries
  the check, and a notebook push racing an autosave serialises through
  push's bounded retry loop. NB the journal has a **frame ceiling**:
  each autosave posts the WHOLE document in one `/engine` frame, so the
  sink is guarded at 192 MiB against serve's 256 MiB `max_size` — a
  session past that keeps its browser-local autosave and drops only the
  server copy (an unguarded over-cap frame closed the socket with 1009
  and re-killed the engine on every autosave). The refusal is no longer
  silent: `setJournalOverflowNotice` raises a ONE-SHOT toast saying the
  server-side copy is stale from here while the local autosave is still
  current — landed in the derived-data round, once including a sonogram
  on Save made the limit reachable in ordinary use (one all-channel
  sonogram of the 30 s × 51.2 kHz × 4 ch bench case is ~139 MB, so two
  measurements cross it). If real sessions routinely approach it, the
  fix is chunked or delta posts, not a bigger number.
- ~~**Real-app-over-socket e2e coverage gap**~~ — **CLOSED** by
  `webui/e2e/session-journal.spec.ts` test 1, which drives the REAL
  app against a spawned `pydvma-serve`: Log Data (mock driver) → Calc
  FFT → plot lines, all through the native `/engine` socket, before it
  goes on to test the restore. (`engine-native.spec.ts` still uses the
  `?engine=1` probe page for its own low-level checks; that is now
  supplementary rather than the only socket coverage.)
- ~~**Derived analysis views are not part of the session document**~~ —
  **DONE (2026-08-19), not yet live-verified.** Round doc:
  `dev/2026-08-19-derived-data-save-round.md`; plan:
  `dev/plans/2026-08-19-derived-data-save-plan.md`. Save now
  materialises the computed FFT and TF into the document as real
  `FreqData`/`TfData` items, each stamped with `source_signature` (an
  FNV-1a-64 hash of the SOURCE samples + rate, computed identically in
  `pydvma/_signature.py` and `webui/src/lib/codec/signature.ts`) and
  `source_settings`; a broken chain is flagged **⚠ source changed** on
  the tray card with click-to-rederive, never silently trusted or
  silently recomputed. Re-saves replace by lineage. Once materialised
  the items are ordinary document items, so they ride the autosave, the
  journal and `Session.data` — which is what closes the
  restore-brings-back-data-only gap this item was raised for.
  Sonograms are stored behind an explicit save-time prompt (Tore's
  design: only when computed, This channel / All channels / Don't
  include). Subset save/export landed as the "Choose sets…"
  split-button, with `DataSet.subset` / `save_data(sets=…)` for parity.
  **Deferred remainder, still live:**
  - **Ensemble ("across sets") TF materialisation.**
    `calc_tf_averaged` derives one curve from every working set but
    hangs it on the first, so a single-source stamp would name one
    member's `id_link` and hash one member's samples — an edit to any
    other member would read as an intact chain, exactly the failure the
    signature exists to catch. Needs the JS multi-source signature
    (python's `source_signature` already accepts a list) AND
    list-valued-`id_link` load seeding, since a list link reloads as an
    orphan set today and the flag could not attach to it.
  - **CSD / PSD (`CrossSpecData`) materialisation** — deferred whole
    this round; the slices live outside the freq/tf shapes the
    materialiser handles.
  - **Provenance-dialect normalisation** — app-written
    `source_settings` use the webui's camelCase knob names, python's own
    stamps use snake_case. Both agree on `calc` (and `method` for
    sonograms), and a reader keys off those; documented in
    `docs/web-logger/dvma-format.md`. Worth unifying if anything ever
    needs to read the settings generically.
  - ~~**Sink-overflow toast**~~ — **DONE** in the same round's final
    review (see the journal item above); the 192 MiB guard now tells the
    user once instead of only the console.
  - **Pre-round files still duplicate derived items on a repeated
    notebook push.** Every derived item minted from now on carries a
    `unique_id`, but one loaded from an older file has none and so has
    no identity to merge on. A composite-key fallback (kind + `id_link`
    + settings) was deliberately NOT built — recomputing or re-Saving in
    the app gives the item an id, which is the honest repair.
- **`dvma.attach(url)` — session API against an externally started
  serve** — `launch()` owns the server it returns a handle to, so a
  notebook cannot currently get `session.data` / `session.push` against
  a `pydvma-serve` someone started from a terminal (or a second kernel
  wanting to read a colleague's running session). The design doc names
  this as the natural follow-on; it needs the journal ops driven as a
  *client* over `/engine` rather than reached in-process, so `Session`
  would grow a second backing implementation. Deliberately out of
  scope for the stages 3–4 arc.
- **Calc completion parks in a hidden page (rAF)** — with the page
  `document.hidden` (background tab, or an embedded/hidden webview)
  a calc's engine round-trip completes — request sent, reply decoded,
  the socket client's pending entry resolved (verified to that depth,
  2026-08-18) — but the action then parks awaiting an animation frame:
  "computing…" forever, no lines, no error, until the page is visible
  again. Applies to mock and nidaq alike; a visible or Playwright
  browser completes instantly. Real-user impact is only "finishes when
  you return to the tab", but it blocks hidden-webview automation and
  the exact await-rAF site is still unlocated — worth finding and
  making visibility-independent.
- **Serve HTTP HEAD requests log noisy websockets tracebacks** — an
  external health probe (or a browser's favicon/preflight-style
  request) sending `HEAD` instead of `GET` produces an "unsupported
  HTTP method; expected GET; got HEAD" traceback on stderr for every
  hit. Consider answering `HEAD` explicitly in
  `BridgeServer._process_request` instead of letting it fall through to
  the websocket handshake rejection.
- **DampingPanel doesn't format NaN consistently** (pre-existing on
  pyodide; now equally reachable through the native engine) — the
  per-mode chip's `Qn={f.Qn.toFixed(0)}` renders the literal text "NaN"
  when a fit produces one (`webui/src/components/DampingPanel.svelte`
  ~429), and the start-time/threshold inputs render `NaN` as their
  value text too (`String(dmp.startTime)` etc, ~306–313) — both should
  get the same `fmt1`-style em-dash treatment the metrics table already
  uses.
- **`pydvma/engine.py` MemoryError remedy messages are stale** — the
  PSD/STFT sizing-error text ("too large an internal buffer for the
  browser engine…", ~205 and ~295) predates the native engine and is
  now wrong when a native-hosted calc hits its own (much higher) 8 GiB
  ceiling. Reword to be host-aware, or drop the "browser engine" phrase
  and just name the ceiling that was actually hit.
- **Vestigial `_accepts_kw` old-wheel probes in `pydvma/engine.py`**
  (~74–97) — these existed to guard against the browser running a
  cached engine wheel older than the glue calling it. Now that glue
  ships *inside* the wheel it rides in (Task 1 of the native-engine
  arc), glue can no longer be newer than its own wheel, so the probe is
  dead weight. Safe to simplify once confirmed there's no equivalent
  skew risk on the native path (a stale installed `pydvma` vs. a newer
  one only in `webui`'s vendored copy) — check before deleting.
- **Round-11 deferred (2026-08-12,
  `dev/2026-08-12-round11-3c6-lab-feedback.md`):**
  - Live incoming time-domain preview during a log — the monitor
    stream already flows during a capture on both paths, so the data
    exists; round 11 shipped the determinate progress bar + waiting
    banner instead. Revisit if Tore still wants to *see* the signal
    mid-log.
  - σ_NL/σ_n overlay entries in the REAL plot legend (round 11 added
    an in-card key beside the σ toggle; the legend model builds from
    viewEntries only, `plot/model.ts` ~794).
  - Web Audio pretrigger THRESHOLD control — the bridge path got the
    unit-aware field; the browser path keeps its 0.05 FS default
    (`provider.ts` documented follow-up).
  - Manual axis-limits popover commits BOTH axes on a single field
    edit — typing an x limit pins y at the shown extent (same family
    as the round-11 sticky-auto fixes; `ZoomToolbar.svelte` fields).
  - CWT damping over a NARROW band (< ~1.5 octaves): the historic
    auto peak threshold (`10·median/max`) picks nothing — a user who
    narrows hard must also drop the threshold slider. Changing the
    auto rule would move existing numbers; decide deliberately.

- **Webui exposure of `use_output_as_ch0`** — verified working and
  multi-channel-correct (prepends ALL commanded AO columns, cal factor
  1.0; `pydvma/acquisition.py` ~423). **Round-11 investigation found a
  REAL rate bug on this path**: on an lpf (decimating) log the output
  is resampled UP to the capture rate (`acquisition.py` ~236-248) but
  prepended to data already decimated to the target with no matching
  down-resample (~423-438) — the prepended column is wrong by exactly
  capture/target. Python-API-only (unreachable from the webui). Fix
  before any UI exposure. Alignment is assumed-not-measured
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
  (`pydvma/engine.py` ~301-319, `s['time_axis']` etc.) — by
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

- **3c6 station device: 2i2 is the TENTATIVE pick (round 11,
  2026-08-12)** — first lab round found it worked better than the
  U24 XL (wider input range + gain knob; the U24's ±1.9 Vpk ceiling bit
  exactly as the survey predicted, pads not in hand). Firm up after
  the round-11 fixes are re-tested in the lab; if it sticks, the
  stated-gain workflow (NEEDS GAIN calibration status) becomes the
  standard 3c6 flow — consider making `verify_input_scaling` +
  level-check the documented first-day-of-term ritual. Feedback doc:
  `dev/2026-08-12-round11-3c6-lab-feedback.md`.

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
- **`_soundcard_specs.PROFILES` has two entries** (Scarlett 2i2 4th
  Gen; ESI U24 XL, first FIXED-GAIN profile, 2026-08-11) — add
  interfaces as they are characterised. XR18 next per the agreed
  lineup.
- **U24 XL follow-ups** (bench + landing 2026-08-11,
  `dev/2026-08-11-u24xl-bench.md`; Windows round 2026-08-12,
  `dev/2026-08-12-u24xl-windows-bench.md`):
  - ~~**Windows enumeration name unknown**~~ — DONE 2026-08-12. It
    carries the model: `Line (U24XL with SPDIF I/O)`, matching the
    existing profile DIRECTLY on all four host APIs (no product-id
    token needed, unlike the 2i2). `fixed_gain` True, `VmaxSC` 1.8819 V.
  - ~~**Absolute calibration against an independent source**~~ — DONE
    2026-08-12 against the Rigol DG1022Z (1 kHz, 3.000 Vpp, high-Z):
    true full scale 1.9036 Vpk, i.e. **+0.10 dB vs ESI's +4.7 dBu
    spec**; implied clip 3.81 Vpp, bracketed by Tore's LED observation
    (3 V clean, 4 V clipped). Through pydvma: −0.114 dB;
    `verify_input_scaling` PASS at −0.15 dB. Apple's 1.000 Vrms
    assumption is now corroborated, not load-bearing.
  - ~~**U24 XL-alone noise floor**~~ — DONE 2026-08-12 via the
    unconnected right channel (WDM-KS, 24-bit, gain 0): **−96.1 dBFS**
    (20 Hz–20 kHz, 48 k) / −92.4 dBFS (44.1 k) — the box is ~16 dB
    quieter than the Mac round could see, so its ~12.8 ENOB figure was
    the Mac's headphone amp, not the ADC (≈15.5–16 bits really). NB
    48 k is 3.7 dB quieter in-band than 44.1 k; and the Rigol at 3 Vpp
    floors at −73.8 dBFS, dominating the converter by 23 dB.
  - **PIN THE WINDOWS ENDPOINT VOLUME** (new, 2026-08-12 — the one real
    gap this round found). Windows exposes the SAME digital gain via
    `IAudioEndpointVolume` on the Line endpoint: **−40..+12 dB**,
    0.5 dB step. Measured digital beyond doubt — SNR flat to 0.03 dB
    over 20 dB of attenuation, and the UNCONNECTED channel's floor
    tracks the setting in both directions. (`QueryHardwareSupport =
    0x3` is not a contradiction: it means the endpoint owns the
    register rather than the Windows engine scaling in software, and
    says nothing about which side of the converter it sits on.)
    ~~DONE 2026-08-12~~ — new `pydvma/_win_audio.py` (raw ctypes COM,
    no pycaw/comtypes, mirroring `_coreaudio`'s interface) plus
    `streams._volume_backend()`, so `Recorder._pin_input_volume` takes
    either platform module. Hardware-verified: −12 dB, +6 dB and a
    mismatched {−3.0, +7.5} each pinned to 0 dB for the capture and
    restored exactly on `end_stream`.
    STILL OPEN: surface the slider trap in the UI — scalar 1.0 is
    **+12 dB** and 0 dB sits at 63% of travel, so "turned up" is the
    resting state; and because the gain is post-ADC, attenuating a
    clipped capture HIDES the clipping from the level meter (10% FS
    peak, still 45% flat-topped).
  - ~~**`max_input_fs` lies on Windows MME/DirectSound**~~ — DONE
    2026-08-12. Reported **192000** for the U24 XL's MME and
    DirectSound endpoints; the MME endpoint is `sd.default.device[0]`
    here, so the digital-LPF oversample path would have requested
    192 kHz. PROVEN fake: above 22 kHz (the 44.1 kHz endpoint Nyquist)
    every 2 kHz band reads an identical −110.1 dBFS at 96 k / −113.1 at
    192 k — exactly −3 dB for 2× the rate, i.e. one fixed dither power
    spread wider, not converter noise. Even plain `fs=48000` on MME is
    resampled from 44.1 k. Fixed by giving `native_input_rates` a
    Windows answer (`_windows_native_rates` probes a WASAPI-exclusive
    or WDM-KS twin — host APIs that refuse rather than convert);
    `max_input_fs` now reports 48000 on all four.
  - **No Windows host API is best at everything** (new, 2026-08-12) —
    **WASAPI exclusive** reproduces the Mac's full CoreAudio ladder
    (8/16/32/44.1/48 k — exclusive mode cannot resample, so the low
    rates are real) but PortAudio negotiates it to **16 bit**;
    **WDM-KS** delivers a **24-bit** word but refuses everything below
    44.1 k; WASAPI shared is 24-bit locked to the control-panel rate;
    MME/DirectSound are 16-bit AND fabricate rates — and MME is what
    pydvma defaults to. Worth deciding a documented preference order,
    and whether to expose the host API in Setup at all.
  - ~~**Anti-alias tracking unverified on Windows**~~ — DONE
    2026-08-12 with the Rigol at 5 kHz (a 1 kHz tone is degenerate for
    this test at fs = 8000: every harmonic aliases onto another
    harmonic). At fs = 8000 the out-of-band 5 kHz is **75 dB down** at
    the 3 kHz fold frequency — rejected, not folded — and at
    fs = 16000 it is present in band at −0.1 dB. The 75 dB is
    source-limited (−82.6 dB of 3 kHz distortion residue exists at full
    bandwidth), so it is a lower bound. Absolute scaling at 5 kHz also
    came out at −0.12 dB, matching the 1 kHz result to 0.01 dB.
  - ~~**`device_index` is not stable on Windows**~~ — DONE
    2026-08-12. The WDM-KS block reordered between two enumerations
    minutes apart with no hardware change and the same device count
    (U24 XL Line 36 → 27; an index-23 lookup returned a Realtek
    endpoint). The bridge had re-resolved by name since 2026-08-10 but
    the Python/CLI paths had nothing. Lifted to
    `streams.resolve_device_index`, applied in `start_stream`, with
    `serve.py` delegating. Name alone is NOT enough on Windows —
    PortAudio lists one box once per host API with the SAME name, so a
    name-only match found four candidates and gave up — hence the
    identity is (name, host API); `MySettings` gained `device_name` and
    `device_hostapi`, both self-populating after the first capture.
    The user-facing SELECTOR landed too — see the item below.
  - ~~**Cross-platform device + fs UX**~~ — DONE 2026-08-12, in
    `pydvma/devices.py`. `list_available_devices()` and
    `pydvma-serve --list-devices` are the pre-choice step: one block per
    PHYSICAL device, backends ranked with the recommended one marked,
    the hardware's rate ladder shown separately from what each backend
    actually delivers, and an explicit calibration status
    (CHARACTERISED / NEEDS GAIN / uncalibrated) so an assumed voltage
    scale can never pass for a known one. `MySettings(device='U24XL')`
    selects by name, picks the backend for the requested fs (fs=8000
    moves off WDM-KS onto WASAPI and says why), and refuses to guess
    between two real devices — with one reported tie-break, auxiliary
    endpoints (S/PDIF, Stereo Mix) losing to the analogue input. Setup
    shows one row per device with an "all backends" escape hatch, plus
    the calibration line. Docs in `docs/user-guide/acquisition.md`.
    Cross-OS name portability landed too: the same box has a DIFFERENT
    name on each OS (U24 XL is `U24XL with SPDIF I/O` on macOS vs `Line
    (U24XL with SPDIF I/O)` on Windows; the 2i2 is generic `Analogue 1 +
    2 (Focusrite USB Audio)` on Windows, which does not contain the
    model at all), so `devices.resolve` now falls back to matching the
    `_soundcard_specs` PROFILE LABEL — `device='ESI U24 XL'` resolves on
    either machine, ignoring case and punctuation, reported in the note,
    and only tried when the raw name misses.
  - ~~**Input dropdown lists output-only devices**~~ — DONE
    2026-08-12. `enumerateInputDevices` now skips endpoints whose
    `max_input_channels` is 0 (and only when the server actually sent
    the counts, so an older bridge keeps the flat list). Setup's input
    selector went 38 rows -> 11 on this bench.
  - **Output-side calibration not attempted** — output volume
    (−55..0 dB digital) is not pinned and `output_VmaxSC` is not
    derived from `max_output_dbu` (+6.9 dBu); worth doing if the U24
    is ever the stimulus source, and would make the loopback
    `verify_input_scaling` an absolute check.
  - **S/PDIF input source selector** is software-settable — a TOSLINK
    loop would give the U24 a cable-free digital self-test like the
    2i2's loopback channels (`'ssrc'` CoreAudio property, not used by
    pydvma yet).
- **IEPE auto-detect via bias-voltage probe** — enable 2 mA excitation
  and read the DC bias before AC coupling to classify what is
  connected (~24 V open / 8–14 V IEPE / ~0 V low-Z) so
  `iepe_excit_current_A='auto'` can configure each 9234 channel.
  Sensitivity still has to be entered manually.
- ~~**TEST THE ESI U24 XL**~~ — DONE 2026-08-11 (same day), via the
  Mac-jack loopback instead of the Rigol: +4.7 dBu fixed full scale
  confirmed to 0.07 dB, profile + fixed-gain VmaxSC auto-derivation +
  bit-depth/volume pinning landed, `dev/u24xl_hw_check.py` 13/13.
  Decision: the U24 XL IS the 3C6 station-box candidate — see
  `dev/2026-08-11-u24xl-bench.md` and the follow-ups item above (the
  Rigol absolute check remains queued there).
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
- ~~**Bridge soundcard OUTPUT path is broken two ways**~~ — FIXED
  2026-08-18 (Mac + 2i2 4th Gen live). (a) An unset
  `output_device_index` now follows the capture device whenever it can
  play (`options.py`; microphone-only inputs keep the default-output
  fallback), and (b) a same-device capture+stimulus runs as **one
  full-duplex `sd.Stream`** (`streams.Recorder.init_stream` +
  `setup_output_soundcard` routing playback through the capture
  stream's own output side). Root cause of (b) was confirmed
  environmental, not a pydvma regression: raw sounddevice shows the
  running input stream's callback now dies permanently the moment a
  second stream opens on the same device (PaMacCore err=-50) — worked
  2026-08-10, broken by 2026-08-17, and the change tracks the
  **Focusrite Control 2 install (10 Aug) + self-update (12 Aug,
  confirmed by Tore)**, not the OS (no macOS update since 30 Jun, no
  reboot since 26 Jul, sounddevice unchanged since Oct 2025; persists
  with FC2 quit → likely a flashed 2i2 firmware change, possibly
  device-specific). Bonus from the duplex
  path: bridge **cancel stops a soundcard stimulus mid-play** (the
  playback wait polls the cancel event; measured 0.49 s release
  through /ws). Unit-tested with a mocked sd
  (`tests/test_soundcard_duplex_output.py`, 20 cases) and
  live-verified: direct path 6/6, /ws bridge 10/10 (incl.
  mid-stimulus cancel + monitor restore after capture),
  `bla_soundcard_check.py` identity G ≡ 1 to 4e-17 through the duplex
  stream.
- ~~**2i2 4th Gen physical loopback cable is ~-27 dB down**~~ —
  ANSWERED 2026-08-18: it was the **output volume knob**, not the
  cable. With the knob at full the Out L → In 1 cable delivers −3.0 dB
  relative to the played level (digital loopback = 0.0 dB exactly).
  The analogue loopback is now a usable second self-test path;
  the digital loopback (channels 3/4) remains the knob-independent
  one. NB `dev/bla_soundcard_check.py`'s "open-input response" check
  now reads the cable's signal on ch1 and reports one expected FAIL
  while the cable stays plugged in.
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
