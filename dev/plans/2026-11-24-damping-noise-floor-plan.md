# Damping fits stop at the noise floor — implementation plan

> Executed natively in the session that wrote the design (Tore asked for the
> fix directly). Steps use checkbox syntax for tracking.

**Goal:** pydvma's damping fits (bands and peaks) measure the noise floor, fit
only the decay above it, and say when a value isn't supported, as
vibration_apps' `decay.js` does.

**Architecture:** One private helper finds the floor and the decay stretch above
it on a power series. Bands mode applies it to block powers, then cuts the
Schroeder integral at the crossover and adds the tail. Peaks mode applies it
per picked bin to `|S|²`, then fits a line to `ln|S|`. The engine passes the
new fields through, and the app greys untrusted band metrics.

**Tech stack:** numpy/scipy (`pydvma/analysis.py`), `pydvma/engine.py`,
Svelte/TS (`webui/src/lib/stores/damping.ts`, `lib/analysis/actions.ts`,
`components/DampingPanel.svelte`).

**Spec:** `dev/plans/2026-11-24-damping-noise-floor-design.md` (approved).

## Global constraints

- Margin above the floor: 10 dB. Floor: mean power of the last tenth (bands:
  at least one block of samples; peaks: at least 2 frames). Block length
  `max(10 ms, 2/fc)`.
- Trust: `range_db` ≥ 20 (EDT) / 35 (T20) / 45 (T30); T ≥ `16/(f_hi − f_lo)`;
  line drop within 0.6–1/0.6 of the window's drop. Flags `range`, `short`,
  `bent`, comma-joined; `''` when trusted or when the value is NaN.
- T60 = first trusted of T30, T20, EDT, else NaN.
- Peaks: at least 3 frames above floor + 10 dB, else the mode is skipped.
- Onset (bands, no pretrigger, no start_time): loudest sample +
  `round(100/44100·fs)` samples.
- Shared checkout: another session writes `dev/plans/2026-11-24-publication-
  figure-plan.md` and may later edit `DampingPanel.svelte` and the export code.
  Commit only named paths, never stash or reset, and commit each task
  promptly.

## Review focus

1. A record with no noise at all (synthetic): the floor is the decay's own
   tail; results match today's within 1 %.
2. A decay still well above the noise at the record's end: the cut stays at
   the record's end, and the tail energy is added.
3. `|S| = 0` or `P = 0` stretches (silence, zero padding): no log-of-zero
   crash, and no division by a zero floor.
4. A band with only filter ringing (no mode): no trusted T60 (`short` or
   `range`).
5. A mode with < 3 frames above the floor: absent from `fits`, but still in
   `peaks_freq`.

---

### Task 1: Bands mode

**Files:** `pydvma/analysis.py` (`calculate_damping_by_band`, new helpers),
`tests/test_analysis.py` (`TestDampingByBand`).

- [ ] Tests (fail first):
  - `test_t60_unbiased_when_decay_ends_early`: one mode per octave (250 Hz
    Q 300, 1 kHz Q 300, 2 kHz Q 600) + noise rms 1e-2, fs 10 kHz, 5 s. The
    single-mode bands' T60 is within 5 % of `3ln10/(ζω)`. `cut_time` is
    between 0.2 and 0.8 of the record for 1 kHz and 2 kHz.
  - `test_band_without_a_mode_has_no_trusted_t60`: in the same record, the
    62.5 Hz octave has T60 NaN and a non-empty T30/T20 flag.
  - `test_new_outputs_shapes`: `noise_db`, `range_db`, `cut_time`, and
    `EDT_flag`/`T20_flag`/`T30_flag` have one entry per band;
    `band_data[i]['cut_t']` is a float.
  - `test_default_start_is_the_onset`: a decay after 0.3 s of near-silence,
    no `start_time`, gives `start_time` ≈ the onset (± 1 ms) and T60 within
    10 %.
  - The existing `TestDampingByBand` tests still pass.
- [ ] Implement `_decay_floor_stretch(P, i0, margin_db, tail_count)`, plus
  `_band_decay_cut(yb, fs, block_s) -> (L, end, noise_db, range_db)` and
  `_decay_onset(y, fs) -> int`, and the flags and T60 rule.
- [ ] Update the docstrings (`calculate_damping_by_band` Returns, the
  module constants).
- [ ] pytest `tests/test_analysis.py -k Damping`, commit.

### Task 2: Peaks mode

**Files:** `pydvma/analysis.py` (`_fit_modes_from_image`, the
`calculate_damping_from_sono`/`_cwt` docstrings), `tests/test_analysis.py`.

- [ ] Tests:
  - `test_noisy_fast_modes_q_within_5pc`: modes (1630 Hz Q 900, 1950 Hz
    Q 1200) + noise rms 1e-2, fs 10 kHz, 5 s, nperseg 2048. Each Q is
    within 5 %.
  - `test_mode_with_too_little_decay_is_dropped`: a weak mode only ~2
    frames above floor + 10 dB is in `peaks_freq` but not in `fits`.
  - `test_fit_reports_floor_and_crossover`: each fit has `noise`,
    `t_cross` and `range_db`; `t_fit[-1] <= t_cross`.
  - Existing `TestDampingBothMethods` and `TestDampingPeakThresholdAndFitContext`
    pass.
- [ ] Implement: replace the `func_real` fit with the stretch + line, and run
  the phase fit over the same stretch.
- [ ] pytest, commit.

### Task 3: Engine

**Files:** `pydvma/engine.py` (`calc_damping`, `calc_damping_bands`),
`tests/test_webui_glue_damping.py`.

- [ ] Tests: `calc_damping_bands` returns `noise_db`/`range_db`/`cut_time`
  (marshalled arrays), and `EDT_flag`/`T20_flag`/`T30_flag` (lists of str),
  and `band_data[i]['cut_t']`. Each `calc_damping` fit carries `t_cross`
  and `range_db`.
- [ ] Implement, pytest, commit. Rebuild the engine wheel
  (`cd webui && npm run vendor:wheels`) and check `pydvma/*.py` are
  byte-identical inside it.

### Task 4: App

**Files:** `webui/src/lib/stores/damping.ts` (`DampingBandsResult`),
`webui/src/lib/analysis/actions.ts` (decode),
`webui/src/components/DampingPanel.svelte` (table, CSV, EDC tick), and
vitest beside the existing damping tests.

- [ ] Types: `rangeDb`, `noiseDb`, `cutTime: number[]`, `edtFlag`/`t20Flag`/
  `t30Flag: string[]`, `bandData[i].cutT?: number`.
- [ ] Table: a flagged EDT/T20/T30 cell gets class `dp-untrusted` (greyed)
  and a `title` built by `flagReason(flag, metric, rangeDb)`, a pure
  function in `lib/stores/damping.ts`:
  - `range` → "decay only {r} dB above the noise; {M} needs {n}";
  - `short` → "shorter than the band filter's own ringing";
  - `bent` → "the fitted line doesn't follow the curve".
- [ ] CSV header:
  `fc_Hz,f_lo_Hz,f_hi_Hz,EDT_s,T20_s,T30_s,T60_s,Qn,range_dB,cut_s,EDT_flag,T20_flag,T30_flag`.
- [ ] EDC chart: a 6 px vertical tick in the band's colour at `(cutT, EDC
  at cutT)`.
- [ ] vitest for `flagReason` and the CSV row, `npm run check`, commit.

### Task 5: Docs and gate

- [ ] `docs/web-logger/analysis.md` damping section and
  `docs/user-guide/modal-analysis.md` where they describe the fits:
  the floor, the cut, the flags.
- [ ] CHANGELOG `## Unreleased`: numbers change (see the design).
- [ ] Full gate: pytest, vitest, `npm run check`, the damping Playwright
  specs (from `webui/`, @engine), `mkdocs build --strict`. Commit.
