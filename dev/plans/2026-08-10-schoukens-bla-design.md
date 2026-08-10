# Schoukens BLA — noise/nonlinearity separation (design)

**Date:** 2026-08-10 · **Status:** approved by Tore (chat), implementation on
branch `worktree-schoukens-bla` · **Method references:** Tore's notes
`schoukens_bla_method_basic.html` + `schoukens_bla_method_miso.html`
(OneDrive, BOSE/2024_Matt_Bryan/methods — not in repo).

## Goal

Implement the Schoukens random-phase multisine method for separating
measurement noise from nonlinear distortion, as a whole-workflow feature of
the web logger: design excitation → run M realisations × n experiments × P
periods → per-period DFT analysis → best linear approximation (BLA) FRFs
with σ²_noise and σ²_NL, plus interpretation. SISO and MISO in one code
path (SISO = n_exc = 1). Scriptable from Python too.

## Terminology (used consistently everywhere)

- **n_exc** — number of driven excitation channels (AO). Experiments per
  realisation = n_exc (that's what makes the input matrix square).
- **n_resp** — number of response channels. Independent of n_exc:
  **non-square systems are first-class** (G is n_resp × n_exc; the n×n
  solve happens per response channel with the same X⁻¹).
- **x_q** — the q-th excitation *as seen by the analysis*: either a
  **measured** input channel (default; required on unsynced paths) or the
  **commanded** drive (NI shared-clock only; regenerated analytically from
  the seed — never recorded as a channel).
- **M** realisations (fresh random phases), **P** steady-state periods,
  **n_trans** discarded transient periods.

## UX — a new "Nonlin" stage

New stage after **tf** in the strip (id `bla`, label "Nonlin"), gated on an
audio/bridge source like Acquire. Setup and Acquire untouched; the stage
reads device/fs/channels from the acquire store. Card phases top-to-bottom:

1. **Design** — band f1–f2; frequency resolution Δf with the derived period
   length shown as **N samples = T seconds** (both labels always visible;
   N = round(fs/Δf), T = N/fs); amplitude per output; M (default 6), P
   (default 4), n_trans (default 2); outputs table: each driven AO channel ×
   its x-source (measured input channel dropdown, or "commanded drive" —
   enabled only when the path is sample-synced, see Validity); remaining
   input channels are responses. Live total-run-time readout:
   M × n_exc × (n_trans + P) × N / fs.
2. **Run** — one button; progress "realisation m/M · experiment e/n";
   cancel stops after the in-flight capture. Captures land as ordinary
   TimeData sets named `<test> · r<m>e<e>`, **hidden by default** in the
   tray/legend so M×n sets don't flood the UI.
3. **Results** — one TfData per (excitation q) with all responses as
   channels; the view jumps to TF with σ_NL and σ_n dashed overlays; a
   verdict chip summarises interpretation per band.

## Excitation — `'multisine'` signal type

Defined **in samples, not seconds**: one period = N samples exciting
integer DFT bins k ∈ [k1, k2] (from f1/f2 via k = round(f·N/fs)), flat
amplitude, phases U[0,2π) from a **seed** recorded in metadata. Rationale:
exact periodicity by construction regardless of clock coercion (the 6003's
48000 → 48019.2 Hz case); frequencies reported as k·fs_actual/N.

- Python: new branch in `signal_generator` (`pydvma/acquisition.py`) that
  **skips the raised-cosine fade and the silent peak rescale** — returns
  exact integer periods; peak > rail is a **hard error**, not a rescale.
  Buffer = (n_trans + P) periods, gapless, shape (samples, n_exc).
- TS twin: `generateStimulus` in `webui/src/lib/audio/signal.ts` (seeded
  PRNG — mulberry32 or similar; TS and Python phases need NOT match, since
  one path generates all captures of a run and analysis reads measured x).
- MISO rotation: base phases drawn once per realisation from the seed;
  experiment e multiplies excitation q's spectrum by
  T_qe = exp(−j2π(q−1)(e−1)/n_exc) (DFT-matrix column). Spec `{seed, m, e,
  n_exc}` → fully deterministic and reproducible from saved metadata.

## Acquisition — TS orchestration over ordinary captures

Sequencing lives in the webui (new `bla` store looping `acquire.record()`),
the only seam shared by bridge-NI, bridge-soundcard, and browser web-audio.
Each capture = one (m, e): a normal one-shot log, duration
(n_trans + P)·N/fs, pretrigger unarmed, with the multisine stimulus spec.
Bridge: `serve.py _build_output_signal` whitelist gains the multisine keys.
Browser: same spec through the existing `AudioBufferSourceNode` graph
(multi-channel buffer for n_exc ≥ 2).

**Why per-capture AO restart is safe (measured x):** x and y share the ADC
clock; in steady state, any whole-period slice is valid — the unknown AO
start offset rotates X and Y by the same e^(−jωτ) which cancels in the
solve. The restart costs only the discarded transient periods.

**Validity rules (enforced, with clear messages):**
- `output_fs == fs` — the run refuses to start otherwise (no silent
  reclamp; the AO-limit clamp path must hard-error in this mode).
- Commanded-x allowed **only** when AO/AI are hardware-synced (NI
  shared-clock conditions as in `setup_output_NI_nidaqmx`); on soundcard/
  browser the option is disabled with "measure the drive on an input
  channel" guidance. (Unsynced commanded-x would let per-realisation start
  jitter leak into realisation scatter and corrupt σ²_NL.)
- Pretrigger must be unarmed for the run (auto, with a note).

## Analysis — `calculate_bla` in `pydvma/analysis.py`

Input: the M×n_exc TimeData list + run spec (N, P, n_trans, excited bins,
channel roles, seed, x-mode). Steps (per Tore's notes, MISO doc governs):

1. Slice off transients; slice P exact N-sample periods per capture.
2. Per-period rFFT at excited bins only — no window, no detrend.
3. Period-average X̄_q^[m,e], Ȳ_r^[m,e]; noise variance σ²_Y from period
   scatter (1/(P−1) form).
4. Per realisation, per response r: solve Ĝ_r^[m] = Y_r^[m]·[X^[m]]⁻¹
   (n_exc × n_exc; n_exc = 1 degenerates to division). Noise propagated
   through the inverse: σ²_{n,G_qr} = (1/P)·Σ_e σ²_{Y,me,r}·|[X⁻¹]_eq|².
5. BLA = mean over m; σ²_tot from realisation scatter (1/(M−1));
   σ²_NL = σ²_tot − σ²_n (the 1/P already folded in at step 4).
6. Commanded-x mode: X regenerated analytically from the seed (noiseless);
   identical formulas, σ²_X terms vanish.

WASM constraints respected: `as_strided`-to-final-shape for period
slicing, MemoryError catch with a human message (patterns at
`analysis.py` calculate_cross_spectrum_matrix). Exposed as a `calc_bla`
glue op (`webui/src/lib/worker/glue.py`); **engine wheel rebuild
required** (`npm run vendor:wheels`, ENGINE_WHEELS name check).

## Data model — extend TfData, no new kind

One `TfData` per excitation q, with optional additions:
- `bla_sigma_nl`, `bla_sigma_n` — real arrays, shape = `tf_data` (like
  `tf_coherence`), stored in **FRF-magnitude² units** (variances); plotted
  as √ on the dB axis.
- `bla` metadata dict: {M, P, n_trans, n_exc, N, seed, excited_bins,
  amplitude(s), x_mode, x_channels, level_label}.

Registration: `container.py` `_ARRAY_FIELDS`/`_OPTIONAL_META` entries +
codec `dvma.ts` optional arrays. Old files load unchanged; `.dvma`
round-trips raw time sets + BLA sets, so Python re-analysis always works.
Rationale over a new `BlaData` kind: a BLA *is* a TF — every view (Bode,
Nyquist, phase, export, **modal fit**) works immediately.

## Results view & interpretation

TF plot: |G_BLA| normal line + two thin dashed lines on the **same dB
axis** (classic Schoukens presentation): σ_NL and σ_n. Uses existing
dashed/opacity primitives; TF-card toggle to hide σ lines. Verdict chip
applies the step-10 logic per band: σ²_tot ≈ σ²_n/P → "linear at this
level (or distortion below noise floor) — averaging helps"; σ²_tot ≫
σ²_n/P → "nonlinearity dominates [band] — level-dependent; repeat at 2–3
amplitudes". Level sweeps stay manual in V1: runs at different amplitudes
coexist as separate sets and overlay in the TF view.

## Testing

- **pytest** — synthetic end-to-end: known linear filters + weak cubic +
  additive noise (extending `testdata.py`), n_exc ∈ {1,2} × n_resp ∈
  {1,2,3} incl. non-square; assert G_BLA ≈ true linear part, σ_NL/σ_NL=0
  separation with cubic on/off; unit tests for multisine periodicity,
  flatness, rotation orthogonality/unit-amplitude, solver conditioning,
  slicing exactness under coerced fs.
- **vitest** — TS multisine twin (periodicity, rotation), bla store
  sequencing/cancel/progress, spec plumbing.
- **Playwright (from webui/)** — mock-bridge full run + browser-audio run;
  σ-overlay assertions on screenshots (composited-pixels standard).
- **Mac hardware smoke** — Scarlett 2i2 digital loopback (inputs 3/4 =
  outputs 1/2, no cables, Rigol off): G ≈ 1 flat on loopback pairs, σ_NL
  near noise floor. Windows-PC NI verification queued for a PC session:
  `bridge_hw_check` extension (BNC loopback ⇒ y = x, G ≈ 1).

## Out of scope (V1)

- Automated amplitude-level sweeps (manual re-runs; overlay comparison).
- Odd-multisine / detection-line designs (even/odd NL discrimination).
- Webui exposure of `use_output_as_ch0` (verified working, multi-channel
  correct, alignment assumed-not-measured → TODO.md item instead).

## Session-collision plan

All work in worktree `.claude/worktrees/schoukens-bla` (branch
`worktree-schoukens-bla`); main checkout untouched. Merge to master after
the concurrent hardware session's milestone (already pushed) — expect
trivial or no conflicts.
