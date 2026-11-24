# Damping fits stop where the decay meets the noise — design

2026-11-24. Tore's ask: "the damping fitting engine needs improving to end the
transient at a sensible place to stop noise overwhelming the fit. I think the
logic in vibration apps repo for reverb measurement is good here." Reference:
`vibration_apps/shared/js/dsp/decay.js` (`noiseFloor`, `reverbTimes`,
`bandMinT`, `NEEDS`, `DROP`, `onset`), used by `apps/reverb`. Prototype and
numbers: the scratch script quoted below (synthetic decays with known Q/T60
plus `data/4c6_examples_problems/6modes done.dvma` set "2", response channel).

## What is wrong today

**Bands mode** (`analysis.calculate_damping_by_band`): each band's Schroeder
integral runs to the end of the record. The noise after the decay counts as
decay energy, which holds the curve up, and then the curve dives to −∞ at the
record's end. Nothing measures the noise, and nothing says a value is
untrustworthy. When the decay ends well before the record does, the result is
wrong by up to an order of magnitude:

| Band | Truth | Today | Cut at the floor |
|---|---|---|---|
| synthetic 2 kHz (noise rms 1e-2) | 1.2–1.35 s | 20.2 s | 1.32 s |
| synthetic 1 kHz (mix) | ~2–5 s | 15.6 s | 2.72 s |
| 4C6 record 1 kHz | ~2–4.6 s (its modes) | 18.4 s | 2.70 s |
| 4C6 record 2 kHz | ~1.2–1.7 s (its modes) | 13.7 s | 1.40 s |
| synthetic 250 Hz (one mode) | 2.64 s | 2.64 / 2.75 s | 2.64 / 2.66 s |

Bands with no mode in them (the default ladder starts at 4/T, so 2–125 Hz
here) report T60s of 5–30 s from noise and the filter's own ringing.

**Peaks mode** (`_fit_modes_from_image`, shared by the STFT and CWT fits):
it fits `ln|S| = ½ln(e^{2(A−Bt)} + e^{2N})` over the whole record from the
start frame. The noise level `N` is free, and the STFT gives few frames
(nperseg 2048 at 10 kHz, no overlap: 24 frames in 5 s). When `N` lands well
below the real floor, the noise tail is fitted as decay. On the 4C6 record at
810.5 Hz, `N` = −21.9 against a measured tail of −12.2: Qn 1901, against 1670
from the decay alone. At 952.1 Hz only one frame is more than 10 dB above the
floor, yet today reports Qn 2146 from five noise-dominated frames. On clean
synthetic decays today's fit is good; with more noise it drifts on the fast
modes (1950 Hz, Q 1200: 986 today, 1188 cut).

**Start**: the app's engine never passes the pretrigger, so every app fit
uses the fallback start: t = 0 for bands, frame 0 for the STFT, 5 % in for
the CWT.

## Approaches

1. **Adopt decay.js's logic (chosen).** Measure the floor, find where the
   decay meets it, fit only above it, add the tail energy (bands), and flag
   values the decay doesn't support. Proven in the reverb app, and it gave
   the right answers above.
2. *Keep the decay+noise model but fix `N` at the measured floor* (peaks
   mode). Tried: biased low on long decays (Q 1400 → 1343), because a tail
   still holding decay overstates the floor.
3. *Full Lundeby iteration.* More robust when a decay wiggles, but more code
   than the evidence asks for. Left as a follow-up.

## Design

### Bands mode — `calculate_damping_by_band`

Per band, on the band-filtered decay from the start (filter unchanged:
`sosfiltfilt`, order 4):

- **Floor**: mean square of the last tenth of the decay (at least one block).
- **Blocks**: mean square in blocks of `max(10 ms, 2/fc)`; levels in dB re
  the loudest block. `range_db` = loudest block over the floor.
- **Crossover**: a straight line through the block levels, from the loudest
  block until the level first comes within 10 dB of the floor (at least 3
  blocks). Where that line meets the floor is the crossover, clamped to the
  record. If there's no usable line, the crossover is the record's end.
- **Cut + tail**: the Schroeder integral stops at the crossover, and the
  line's own energy beyond it is added (`P(t_end)·fs/k`, k = −slope·ln10/10).
  This is decay.js `reverbTimes(cut=True)`.
- **Metrics**: EDT, T20 and T30 as now (0/−10, −5/−25, −5/−35, one stretch
  each). Each is marked untrustworthy when the band doesn't support it:
  - **range**: `range_db` below 20 (EDT) / 35 (T20) / 45 (T30), as ISO 3382;
  - **short**: T below `16/B`, the band filter's own ringing (Jacobsen and
    Rindel; B = f_hi − f_lo);
  - **bent**: the fitted line falls outside 0.6–1/0.6 of the window's drop.
- **T60**: T30 if trustworthy, else T20 if trustworthy, else EDT if
  trustworthy, else NaN. Qn follows T60. EDT, T20 and T30 keep their values
  either way. *(decay.js falls back to an untrusted value; pydvma's table
  already shows NaN as "not enough decay", so NaN is the honest equivalent.
  My call.)*
- **New per-band outputs** (arrays like `fc`): `noise_db` (the floor re the
  loudest block), `range_db`, `cut_time` (s after the start), and a reason
  string per metric (`''` when trustworthy, else `range`, `short` or `bent`,
  joined) as `EDT_flag` / `T20_flag` / `T30_flag`. `band_data` gains
  `cut_t` for the plot.

### Peaks mode — `_fit_modes_from_image` (STFT and CWT)

Per picked peak, on `P(t) = |S(f_k, t)|²` from the start frame:

- **Floor**: mean power of the last tenth of the frames (at least 2).
- **Stretch**: from the loudest frame at or after the start until the level
  first comes within 10 dB of the floor.
- **Fit**: a straight line through `ln|S|` over that stretch gives `B`. It
  replaces the free-floor model fit (`func_real` is kept as public API but
  no longer used). The phase-slope fit runs over the same stretch. It used to
  run over 90 % of the model's crossover.
- **Too little decay**: fewer than 3 frames in the stretch skips the mode,
  as a failed fit is skipped today. `peaks_freq` still lists it as a
  candidate.
- Each fit dict gains `noise` (the floor, as `ln|S|`), `t_cross` (where the
  line meets the floor) and `range_db`. `t_fit` / `real_fit` / `real_data`
  cover the stretch.

### Start

When there's no pretrigger and no `start_time`, bands mode starts at the
**onset**: the loudest sample plus 2.3 ms (decay.js `onset`, `100/44100·fs`
samples). Today it's t = 0. The STFT and CWT start-frame rules are
unchanged: their fit now starts at each mode's loudest frame anyway.

### Engine and app

- `engine.calc_damping_bands` passes the new arrays through: `noise_db`,
  `range_db`, `cut_time`, the `*_flag` lists, and `band_data[].cut_t`.
  `calc_damping` passes `t_cross` / `range_db` per fit.
- **Band metrics table**: an untrustworthy EDT/T20/T30 shows greyed, with
  its reason as a tooltip ("decay only 28 dB above the noise; T30 needs
  45"). T60 is already NaN, shown as an em-dash, when nothing is
  trustworthy.
- **Band metrics CSV**: gains `range_dB` and `cut_s` columns and one
  `*_flag` per metric.
- **EDC chart**: a small tick on each curve at its cut. The decay chart
  doesn't change: its data markers now stop where the noise begins.
- Engine wheel rebuilt (`npm run vendor:wheels`).

## Tests

pytest (`tests/test_damping*.py`, next to the existing damping tests):

- **Bands, synthetic decay with known T60 and a floor**: one mode per
  octave, white noise. T60 within 5 % in a band whose decay ends at 1/3 of
  the record (today: many times too long). `cut_time` near the
  line-meets-floor time. A band with no mode gets no T60 (NaN) and a
  `short` or `range` flag.
- **Bands, no noise**: results unchanged from today within 1 % (the cut
  lands at the record's end and the tail is negligible).
- **Peaks, synthetic modes with known Q, noise rms 1e-2**: Q within 5 % for
  the fast modes (today's 986 for Q 1200 fails). A mode with fewer than 3
  frames above floor + 10 dB is not in `fits`.
- **Start**: with no pretrigger, bands mode starts at the onset (loudest
  sample + 2.3 ms).
- **Engine**: the new keys are present with the right shapes.
- **vitest/Playwright**: the table's greyed cells, and the CSV columns.

## Docs and CHANGELOG

Update the damping docs (the web-logger damping section and the
`calculate_damping_*` docstrings): what the floor is, where the cut falls,
what each flag means. CHANGELOG `## Unreleased`: **numbers change**. Band
T60s for decays that end before the record shrink to their true values.
Bands with too little decay now read NaN. Peaks-mode Qs for noisy modes
move. Modes with under 3 frames above the noise are dropped.

## Not in this change

- Chu noise subtraction (decay.js `subtract`) and full Lundeby iteration.
- A pre-impact noise measurement: most captures have only ~100 pretrigger
  samples.
- STFT overlap for more frames. Today's phase-to-frequency mapping relies
  on `noverlap=0`, so overlap needs its own change.
- The default band ladder's low edge (4/T). The flags now mark its empty
  low bands instead.
