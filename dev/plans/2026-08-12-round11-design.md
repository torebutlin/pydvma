# Round 11 design — 3c6 lab feedback fixes (2026-08-12)

Feedback: `dev/2026-08-12-round11-3c6-lab-feedback.md`. Seven read-only
investigations established root causes before any fix (evidence with
file:line in the session record); this doc fixes the DECISIONS. Work is
split into packages with disjoint file ownership so implementation
agents can run in parallel.

## Root causes (summary)

1. **Trigger never waits** — three independent layers, every one of
   which alone produces "it just logged":
   (a) Setup's pretrig fields never set `pretrigArmed` (only the
   Acquire switch does), and a log without a pretrigger block actively
   clears the server's pretrig settings; the Setup group is also gated
   on `hasNidaq` — machine-has-NI — so it renders next to a soundcard
   and does nothing.
   (b) Threshold units: soundcard data is VmaxSC-scaled volts, the
   0.05 default is a full-scale-era number → 0.36 % FS on a 2i2 —
   fires on the noise floor (simulated: −60 dBFS noise triggers).
   v2.3.0's VmaxSC auto-derivation armed this without any user input.
   (c) The soundcard recorder's `trigger_detected` actually means
   "post-trigger capture complete" (it checks the second-oldest chunk
   of a capture-length ring), so detection lags by ~stored_time,
   `pretrig_timeout` races event+capture, and timeout silently returns
   the buffer tail — indistinguishable from free-run.
2. **Cancel mid-log dead** — serve.py dispatches inline in the
   websocket receive loop (cancel frame not even read until the log
   ends); executor thread uncancellable; zero cancel polling in
   acquisition; client promise never rejects. (Web Audio path cancels
   fine — why it slipped.)
3. **CWT "not working"** = CWT *damping* blows the 32-bit WASM
   allocation ceiling at lab sizes (n_freqs × N × 16 bytes; 6.4 GB at
   30 s/48 kHz), raw numpy error shown verbatim; plus lin-axis default
   fighting CWT's log grid, w0-unaware f_min, band boxes not reaching
   the fit, TypeError masking. Sonogram CWT itself is correct.
4. **fs unsettable + TF axis ×10 = ONE bug** — fs really was 10000
   (docs-canonical prefill value); an off-ladder fs renders the select
   BLANK (Svelte selectedIndex −1), so it could be neither seen nor
   changed; 10 kHz ⇒ TF axis 0–5000. Engine metadata verified exact
   end-to-end. Related: U24 ladder floor = standard-rate floor, so lpf
   decimation had nothing to offer; after a decimating log the live
   stream stays at the capture rate (monitor axis wrong).
5. **Axes** — "auto" is `range=null` and re-fits on data-add by
   itself; the failure is stale EXPLICIT ranges, chiefly because the
   toolbar Auto buttons freeze the current extent instead of restoring
   null, gestures clobber both axes, and unit-changing view switches
   keep the old y.

## Package P1 — Python trigger + cancel (pydvma/streams, acquisition, serve, options)

- Soundcard recorder → two-phase: `trigger_detected` fires AT the
  crossing (serve's existing `status/triggered` poller then reports
  truthfully); new `capture_complete` when pretrig_samples before +
  (stored_time·fs − pretrig_samples) after are in the buffer;
  sample-exact slicing (record[pretrig_samples] = first crossing
  sample). `pretrig_timeout` = wait-for-trigger only; phase 2 bounded
  by stored_time + 5 s. NI recorder byte-identical (duck-typed
  `getattr(REC,'capture_complete', trigger_detected)`).
- Threshold stays VOLTS (VmaxSC-scaled data) — documented; UI carries
  the units (P3).
- Cancel: `log` dispatched as a background task (other messages stay
  inline); cooperative `cancel_event` threaded into the capture
  (chunked sleeps + both wait phases, output stimulus stopped
  cleanly); contract: cancel-during-log ⇒ `status/cancelled` INSTEAD
  of `log_result`+container; cancel with no log in flight keeps old
  monitor-stop behaviour.
- Capabilities gain `default_input`/`default_output`
  ({driver,index,name,hostapi}|null) for the UI.

## Package P2 — CWT (pydvma/analysis, webui glue/SonoCard/actions)

Per investigation §7: bound damping CWT (time_step from fitted-band
Nyquist ×4 oversample; f_range through glue + actions), pre-flight
allocation guard with a remedy-naming error, w0-aware f_min
(4·max(1,w0/6)/T), onBand single-bound/order validation, CWT ⇒ log
freq-scale default on method toggle, unmask TypeErrors.

## Package P3 — webui acquisition UX (SetupCard, AcquireCard, bridge.ts, acquire.ts, serveConfig)

- **Setup basic tier**: device (Default shows resolved name from
  `default_input`), fs as typed combo (input + datalist of the ladder,
  accepts `3k`, off-ladder value always visible; feedback via the
  existing coerced/captures-at notes), channels, duration, and a NEW
  trigger group — arm + threshold + channel — gated on
  `bridgeCaps.pretrigger`/Web Audio (NOT hasNidaq). Threshold field is
  unit-aware: volts + "= N % FS" hint when full_scale_volts known,
  ×FS otherwise; effective default 5 % of full scale (client sends
  volts explicitly when armed).
- **Setup full tier**: reorganised into titled sections — device /
  rates / levels / trigger (samples, timeout) / NI-DAQ — instead of
  one 12–15-group wrapping row; notes consolidated visually; fs labels
  via fmtHz. pretrig samples no longer able to break configure
  (chunk-size raise keyed on samples present, not armed).
- **Acquire**: determinate progress bar (elapsed/duration; bridge
  clock starts at log-send, HOLDS during `armed`, runs from
  `triggered`); prominent "armed — waiting for trigger" banner state
  (replaces the small grey note while waiting); timeout default
  matches server (20 s); statusText no longer suppressed while
  recording. Cancel: client races `log_result` vs `status/cancelled`
  → clean unwind + toast.

## Package P4 — rates (serve.py/streams.py, AFTER P1 lands — same files)

- Sub-8 kHz decimation targets (500/1000/2000/4000/5000) in
  `_soundcard_candidate_rates` so lpf has something to deliver on
  8 k-floor devices.
- Restore the configured stream after a decimating log (or stamp
  monitor frames with the configured fs) — live scope axis stays
  truthful.
- Soundcard `status.fs` reads back the opened stream rate instead of
  echoing the request.

## Package P5 — axes auto (viewstate, ZoomToolbar, PlotSurface, build, actions, App)

1. Auto X/Y restore `null` (sticky auto), as the Nyquist branch does.
2. Unit-changing switches (plot type, y-scale, freq mode, sono scale)
   drop the stale y-range (no history entry).
3. New lines landing in a view (capture, load/append, first calc for a
   set, BLA results) re-auto y via the no-history path; x too when the
   view was empty. Recompute-in-place keeps the user's range.
4. y-auto fits the data INSIDE the current x-window (dataExtent gains
   an x-window; binary-search bounds already exist in build.ts).
5. Gestures stop clobbering the untouched axis: an effectively-x-only
   box zoom preserves a null y.

## Package P6 — Nonlin legibility (BlaCard, bla.ts, actions bla region)

- **Coupling made explicit**: Δf and period T become LINKED inputs
  (single resolver, ResolutionControl pattern; N = round(fs/Δf),
  T = N/fs; editing either updates both). Units on every field.
- **Total time is the headline**: the primary slot shows
  "≈ 12.4 s total · 12 captures × 1.03 s" live, not buried mono text.
- **Progress**: an M × n_exc capture grid (done/running/pending
  cells; running cell fills from acquire.elapsed / captureS) + "capture
  3/12 · ~8 s left" ETA; `computing BLA…` stays for the analyse phase;
  cancel button labelled "finish current capture + stop".
- **Run semantics**: starting a run with previous results present asks
  replace (default) vs keep-both via a Segmented choice near Start;
  replace removes the previous run's raw+result sets (one-level Undo
  toast, resample-undo pattern); keep-both suffixes run names (bla#2)
  so tray entries stay distinguishable; the silent-orphan path (state
  reset dropping hidden rawSetIds) is closed either way.
- **Explanation**: one short in-card line naming σ_NL/σ_n (with an
  in-card dashed-line key beside the σ toggle — legend model stays
  untouched) + docs link.

## Sequencing

P1, P2, P3 in parallel (disjoint files) → P4 after P1 → P5 after P2
(actions.ts/viewstate.ts overlap) → P6 after P5 (actions.ts bla
region). Integration (me): suites, engine wheel rebuild, docs pass,
CHANGELOG, round-doc closure.

## Deferred to TODO (recorded there)

- Live incoming-time-domain preview during a log (monitor stream
  already flows; progress bar + waiting banner judged sufficient for
  this round).
- `use_output_as_ch0` prepends the stimulus at the CAPTURE rate on
  lpf logs (Python-API-only path; wrong by capture/target).
- σ overlay entries in the real plot legend (in-card key this round).
- Web Audio pretrigger threshold control (bridge path got it; browser
  keeps the 0.05 FS default until its own control lands).
