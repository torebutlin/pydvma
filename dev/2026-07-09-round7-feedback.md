# Round 7 feedback — 2026-07-09 (first lab-testing round after v2.0.0)

Raw feedback from Tore, verbatim in intent, lightly reformatted.
Dispositions filled in as the round proceeded.

## 1. Floating axis-control box placement
> The axis control floating box does look a bit awkward covering part of
> the top right of the plot all the time. Is there a natural alternative?

**DONE (b599876).** The toolbar is docked in a slim `.plot-nav` strip
above the plot frame on every host (sono / nyquist / bode / default) —
it never covers data now. The expander popover still drops over the
plot's top-right corner while open (transient, as before). Note for a
future round: the legend's default corner is still `nw` (chosen when
the toolbar occupied `ne`); `ne` is available again if preferred.

## 2. Sono axis controls broken + messy bar
> Sono axis controls seem to be x and y go from 0 to 1 and don't do
> anything. And the whole bar there with 'y log lin / colour dB lin' is
> just a bit messy.

**DONE (b599876).** Root cause: the toolbar was fed extents from the
sono view's EMPTY-lines model ([0,1] fallback) and `setRange('sono')`
was written but never read by the heat painter or axis model. Now both
consume one shared committed window (`sonoWindow`, log-DC-guarded), the
painter crops value→pixel on both axes (out-of-data renders transparent
rather than smearing edge bins), PlotSurface gained log-y gesture space
+ an extent override, so limit fields / Auto X/Y / box-zoom / pan /
undo all work on the sonogram. e2e guards the loop end-to-end now (the
missing guard is why d02dd00 shipped broken). The bar itself is less
"floating clutter" after item 1's dock; the y/colour toggles stayed in
the bar for one-click access — shout if they should fold into the
popover instead.

## 3. Fit damping UI — no interactive plot
> Fit damping brings up a weirdly placed box of fn and zn, but no
> interactive plot with peak threshold control or line for choosing
> where (in time) to find those peaks. I provided a prototype in the
> prev code, there should still be a screenshot for the kind of fit
> line, and the methods should all still exist.

**DONE.** Confirmed: both analysis methods survive intact and always
computed the plot arrays; the glue layer DISCARDED them (only fn/Qn
crossed to JS) — that is why the web UI lost the Qt `DampingFitWindow`
plot (screenshot: `dev/screenshots/Untitled 23.png`). Rebuilt as an
interactive panel docked below the sonogram: the decay-fit chart
(× data markers + fitted lines + `f Hz, Qn=…` legend — the Qt plot),
the start-slice spectrum with a DRAGGABLE threshold line + candidate
peaks, a draggable start-time line over the sonogram itself, and
number fields for both knobs (blank = auto; the engine echoes its
resolved values back). Every control re-fits live; a Refit button
covers card-side changes (the fit follows the STFT|CWT method toggle).
Notes: the Qt prototype hard-coded the threshold (`10*median/max`) and
never had a time line — both controls are NEW capability on top of the
restored plot; `peak_threshold` was promoted to a real analysis
parameter (d3145e9). Fixing the panel also flushed out a LATENT
pre-panel bug: damping as the session's FIRST compute parked forever
because `calcDamping` never kicked `engine.boot()` (every other calc
does, via guarded()) — now fixed and e2e-guarded.

## 4. Fit damping modes: by peaks / by band
> Include a fit damping toggle (by peaks, and by band). Peaks: find
> peaks, fit according to the decay line, accurate freq estimation from
> the phase. By band: apply a series of Band Pass filters to extract
> bands (options: all, oct, third-oct, 10th-dec), then use the Schroeder
> decay integral and fit method to estimate the band-centred Q factors,
> or the band acoustic decay metrics (ET, T20/30, RT60) etc.

**DONE.** "Peaks" is the existing pair of sonogram/CWT fits
(freq-from-phase included). New `calculate_damping_by_band` (d3145e9):
zero-phase Butterworth bank ('all' | octave | third-octave |
tenth-decade, 1 kHz-anchored, whole-band-inside-range), Schroeder EDC
per band, EDT / T20 / T30 / T60 (T30-preferred, NaN when decay range
insufficient) and band-centred `Qn = pi*fc*T60/(3 ln10)`; exported at
top level for notebooks too. The damping panel's **peaks | bands**
toggle drives it: bands mode shows the per-band EDC curves with dashed
T60 fit lines and the metrics table (fc / EDT / T20 / T30 / T60 / Qn,
`—` = insufficient decay range). Glue op `calc_damping_bands`.

## 5. CWT resolution control + does fit use CWT?
> Does CWT provide more refined control of its freq resolution (via its
> Q factor of the wavelets? or...?) And does fit damping pick up the CWT
> data if available rather than the STFT, or always use STFT?

**ANSWERED + w0 EXPOSED (f169fa2).** Yes: `w0`, the non-dimensional
Morlet frequency, IS the wavelet-Q knob — higher w0 = more cycles under
the envelope = finer frequency resolution, coarser time resolution. It
was plumbed end-to-end (default 6) but had no UI; the Sono card now has
a "wavelet Q (w0)" select (4/6/8/12/16/24) next to voices/octave (which
is grid DENSITY, not bandwidth). And fit damping follows the card's
method toggle: CWT mode fits the CWT image, STFT mode the STFT — it is
never "always STFT" (but it also doesn't auto-prefer CWT when the
toggle is on STFT).

## 6. Fit lines local vs global
> In Fit mode, clicking a fit shows a bold fit line for one chan and
> global fit lines for all, but no local fit line selection options. I'd
> want all local lines for all sets/chans, and also global. Maybe
> local/global should be a toggle choice (reflected in the legend and
> lines), not an option for both?

**IN PROGRESS (toggle design, as suggested).** The per-set/channel
local reconstructions were ALWAYS stored (modal store keeps local +
global per target); only the presentation limited local to a pink
primary-set overlay outside the legend. Being rebuilt as: fit
pseudo-sets carry either family, a `local | global` toggle in the Fit
card picks which, legend names reflect it (`Modal fit local (set)` /
`Modal fit global (set)`), pink overlay retired.

## 7. Do TF/PSD see cleaned impulse data?
> Does the TF and PSD calcs pick up the cleaned impulse data, i.e. do
> they see the change, or do they always use the raw?

**ANSWERED + IMPROVED (b3cb82e).** Clean Impulse mutates the source
TimeData in place — there is no retained raw copy — so any recompute
already used cleaned data. But existing results did NOT auto-refresh
(only the time view updated; FFT/PSD/TF/sono stayed stale until a
manual Calc). Now cleaning re-dispatches the calcs for whatever results
already exist on that set (including a participating across-ensemble
TF), so every view reflects the clean immediately.

## 8. Legend with many lines
> Legends with many lines: maybe fitted lines should be in a second
> column?

**DONE (39eb0bb).** Above 10 entries the legend wraps into 2 (cap 3)
balanced columns; entries flow top-to-bottom then across, so the
modal-fit rows (last) naturally land in the later column.

## 9. Legend compact view
> Option for a compact view so it condenses to a selectable grid of dots
> with sensible arrangement and colour coding?

**DONE (39eb0bb).** Hover-revealed toggle on the legend card switches
to a dot grid: one row per set, one column per channel, dots in the
line colour (off = hollow ring, fade = translucent), click cycles the
line exactly like a legend row, full label as tooltip. Persists per
view.

## Round 7b (same day, on reviewing the summary)

> Clean impulse should be something that works once; even better, an
> on/off toggle (doubles storage requirements but not usually
> significant). Legend: let's default SE and see how that goes.

**BOTH DONE.** Clean Impulse is now a toggle: the first clean stashes
the raw arrays and caches the cleaned result; toggling swaps by
reference (the clean never re-runs on its own output — idempotent), a
different impulse channel re-cleans from the raw stash, and each swap
re-runs the existing-results recompute. Save/autosave write whichever
copy is APPLIED; the other copy is session-only. Legend default corner
is `se` (history: `nw` was chosen when the toolbar floated over `ne`).
Master pushed at Tore's request — the deployed site had still been
showing the pre-round-7 build.

## Round 7c (same day, after using the panel)

> Sono CWT: make the two res options wider range (Q up to something
> higher, and per-oct to match). Wide mode: arrange the two subplots to
> the right-hand side, one above the other; narrow mode as-is. The star
> plot when fitting is the decay plot — make the fit plots expand to
> fill when clicked (and pop back in), and saveable as their own plots.
> Might be worth a review that all plots are save/exportable with
> consistent styles.

**ALL DONE.**
- CWT ladders: `w0` now 4..64, voices/octave 8..64 (matched top ends —
  a high-Q wavelet needs a comparably dense grid). At the extremes a
  very long record can hit the engine's 32-bit array ceiling; that
  surfaces as the clear "array is too big" error, not a crash.
- Damping layout: wide screens put the panel in a right-hand column
  beside the sonogram, controls on top, charts stacked; each chart
  expands to fill the whole plot region (click the chart or its ⤢; the
  sonogram tucks away) and pops back. Narrow keeps the round-7
  below-dock. A mode flip collapses any expansion.
- Chart saves: every damping chart saves as its own PNG through the
  same workdir-or-download path as Save Figure, restyled by the same
  exporter (the charts now follow PlotSurface's self-contained-SVG
  contract: data-role plot-bg/axis + inline CHROME hexes + tick-class
  text — theme-invariant like the main figures). The band table saves
  CSV.
- Export audit (full table in the session log; agent-audited): the ONE
  correctness gap was **Bode exporting only its magnitude pane** — the
  phase pane was a second, unbound PlotSurface. Fixed: `getSvg` now
  composites both panes into one flattened SVG (raster + PDF safe).
  Remaining, deliberate or deferred: Nyquist's brush strip is a nav
  control and stays out of the export; the legend is still absent from
  every figure (pre-existing TODO); live scopes are real-time-only by
  design.

## Round 7d (same day)

> Legends should be in the exported figs (as per whether it has been
> turned on or off). Similarly coherence should be in exported figs
> when it's turned on, but not when toggled off.

**DONE.** Exports now append an SVG legend to the figure clone whenever
the on-screen legend is visible — same fractional position (SE default
pins flush; outside-right clamps inside the canvas), listing the DRAWN
lines only ('off' rows exist on screen purely to be clicked back on),
faded lines faded, columns wrapping past 10 entries like the card. The
legend card follows the exporter's white/transparent/dark restyle
contract (plot-bg card, axis-grey labels, untouched data-colour
swatches). Bode exports place it in the magnitude pane; sono exports
carry none (no legend mounts there). Coherence was VERIFIED already
correct — the overlay + right axis live inside the plot SVG, so they
export exactly per the toggle — and is now e2e-guarded alongside the
legend (export pixel-diff on/off/restored round-trip).

## Round 7e (same day) — JW-logger .mat import

> When imported I don't think the lines are quite right… some lines are
> actually coherence lines that should be marked as such. And when
> fitting, weird freq shifts making the fits not converge — I suspect
> the data import, not the fitting algorithm.

**Diagnosed on the four sample files; Tore's suspicion confirmed.**
- The frequency axis was CORRECT all along: JW's `freq` is the sample
  rate (the format's own time branch uses it as fs), and the importer's
  `rfftfreq(npts, 1/freq)` matches the row count exactly. Sanity: the
  violin file's strongest peak lands at 524 Hz (B1 territory), the
  flamenco guitar's at 182 Hz (top mode) — physical.
- The REAL bug: `import_from_matlab_jwlogger` imported EVERY `yspec`
  column as a TF channel and never set `tf_coherence`. JW admittance
  files store coherence as an extra column (guitar file: [H, coh]) —
  imported as a channel it poisons the multi-channel modal fit.
  Measured on the guitar file, 150–220 Hz window: TF-only fit gives
  fn=182.13 Hz ζ=0.0085; with the coherence-as-channel the fit RAILS to
  fn=150 (window edge), ζ=1.0. That is the "weird freq shifts / no
  convergence".
- Fix (careful/additive): coherence columns detected (real-valued AND
  within [0,1] — no measured complex FRF satisfies both) and attached
  as `tf_coherence` paired in column order, ONLY when the split is
  clean (equal counts); ambiguous mixes keep the historic all-TF import
  so nothing is dropped. Verified on all four samples: guitar → 1 TF +
  coherence; violin/clav/Deering unchanged (all-complex columns).
- Engine wheel rebuilt; the previously-fixme'd webui mat-import e2e now
  runs against a checked-in synthetic JW fixture (one TF line in the
  legend, coherence arriving as the overlay).
- Usage note for these files: they are admittances (velocity/force) —
  pick **Velocity** as the TF type when fitting (docs updated).

## Round 7f (same day) — original-logger source recovered

> Revamp the JW import per the original MATLAB logger source docs. Also
> survey it for old features worth porting. The fit struggles with
> these examples; Refine sometimes goes well off without warning — add
> a self-awareness flag. Future: auto-identify disp/vel/acc. And: are
> we fitting phase (my original logger did, and flagged significant
> phase)?

**All addressed:**
- **Import revamped from source.** The V2.9a source confirms every
  convention: saves are `yspec, dt2, npts, freq, tfun` (+`indata`);
  `freq` IS the sample rate; `dt2` = saved `dtype` = column counts
  `[n_time, n_spec_cols, n_son]`; the averaged-TF writer interleaves
  `[H1, coh1, H2, coh2, …]` (avtflogpars.m: `thing(:,2k-1)=cross/
  autoin; thing(:,2k)=|cross|²/(autoin·autoout)`); the save menu also
  writes arbitrary column subsets, and the Add-on-load path composites
  files (hence the 3/4-column all-H instrument collections). The
  importer now recognises the documented interleaved layout as the
  primary rule (order-pairing + all-TF fallbacks kept); docstring cites
  the source. 7 pytest cases.
- **Feature survey done** → prioritised review list in TODO.md
  ("Old-logger (V2.9a) feature review list"): grid/roving-hammer
  logging (→ mode shapes), md_param legacy modal-file import, manual
  add/edit-mode authoring, time-delay compensation, per-mode digital
  filters, RFP fitting. The big extras menus are PhD-era bowed-string
  research code — low porting value.
- **Phase IS fitted** — pydvma's modal model is `an·e^{jpn}/(…)`, a
  per-mode per-channel phase, same as the old logger's circle fit
  (`sdof.m` `exp(i·var(3))`). Historical correction: the old logger
  PRINTED each fitted phase but had NO automated "too significant"
  warning (searched the source; reconstruction deliberately dropped
  phase). The new build adds the flag the original implied: each mode's
  worst phase deviation from a REAL mode (0/180°) is computed
  (`phaseDevDegFromMatrix`), the fit chip marks offenders ⚠ (tooltip
  explains + names the TF type), and a toast fires when a fresh fit
  exceeds 30°.
- **Refine divergence flag**: refine already auto-reverts on a WORSE
  residual; the new check catches the "improved cost, mode flew away"
  case — any mode moved >10% (and >2 Hz) from its pre-refine frequency
  warns with an Undo action on the toast. 5 vitest cases cover both
  flags.
- **Auto-identify disp/vel/acc** → TODO item 7 (suggest the TF type
  that minimises the fitted-phase deviation — the flag's data makes
  this a natural follow-on).

## Incidental findings (not in Tore's list)

- **Exported figures never include the legend.** PNG/PDF export
  serialises only the PlotSurface SVG; the legend is a separate HTML
  div. Nobody has complained, but it is worth an explicit decision —
  draw a legend into the export SVG, or document it as-is. → TODO.md.
- The vitest count grew 592 → 630+ across this round; Playwright 69 →
  70+ (sono axis-range guard added to the big sono spec).
