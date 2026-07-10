# Round 9 — lab-testing feedback (2026-07-10)

Three asks: CWT wavelet-Q ergonomics, a principled digital low-pass for
logging, and (mid-round re-scope by Tore) a general resample tool. All
landed; pushed to master per Tore's instruction.

## 1. Wavelet Q: higher range, slider feel, auto-matched voices

- **w0 is now a slider (4–64) + exact box (accepts up to 128)** in the
  nFFT idiom — linear value, no log2 snapping. The engine never had a
  w0 ceiling; the old dropdown (max 32→64 in 7c) was the only limit.
- **voices/octave defaults to AUTO**: `autoVoicesForW0(w0)` =
  smallest ladder value ≥ max(16, 0.6·w0). The 0.6·w0 bound is the
  Morlet tiling condition (fractional -3 dB bandwidth ≈ 2.36/w0 vs
  voice spacing ≈ 0.69/V); the floor of 16 keeps the DEFAULT CWT
  byte-identical to round-8 behaviour (auto(6)=16). Picking an explicit
  number pins it (voicesAuto=false) until 'auto' is re-chosen. The w0
  box clamps at 128 because the 64-voice ladder top starts
  undersampling past w0 ≈ 107.
- Persistence: `voicesAuto` stamps into `ui.analysis.sono`; pre-round-9
  files with a saved voicesPerOctave ≠ auto-resolution load as PINNED
  so a later w0 tweak can't clobber a hand-picked density.

## 2. Logging digital low-pass — ON/OFF, fs stays the control

Tore's re-scope (mid-implementation, replacing a cutoff-field design):
fs keeps its meaning; the toggle changes HOW fs is achieved.

- **Core: `analysis.resample_to_fs(y, fs, fs_new)`** — rational
  polyphase resampling (`Fraction.limit_denominator(1024)` →
  `scipy.signal.resample_poly` with a Kaiser FIR). Down: stopband
  96 dB at the NEW Nyquist, passband to fs_new/2.56 (DSA guard-band
  convention) — the noise-reducing anti-alias direction. Up: stopband
  at the ORIGINAL Nyquist (band-limited/sinc interpolation — linear
  interp was rejected: its triangular kernel is a sinc² filter that
  droops the passband AND leaks imaging above the original band),
  passband to 0.92× the original Nyquist. Zero-phase (delay
  compensated); sample 0 → sample 0, so pretrigger alignment maps
  exactly. Rational handling means a DSA-coerced 8533.33 Hz capture
  still lands exactly on a 2000 Hz target (up/down = 15/64).
  Gotcha found by test: scipy scales an ARRAY window by `up`
  internally — pre-scaling the kernel came out 20·log10(up) dB hot.
- **`MySettings(lpf_on=True)`** (auto-whitelisted through serve's
  signature-derived kwargs; round-trips .dvma via vars()). `log_data`
  swaps in a CAPTURE settings copy — fs×M, chunk_size×M,
  pretrig_samples×M, where M = floor(max_input_fs/fs) — runs the
  existing capture path unmodified, then resamples the assembled
  window from the rate the stream ACTUALLY ran at (DSA coercion safe)
  down to the target. TimeData carries target-rate settings +
  `lpf_capture_fs`. No headroom (M<2) → unfiltered log + printed note.
  Clip check now uses the RAW peak taken before filtering (the FIR
  would smear rail hits under the threshold), and the
  use_output_as_ch0 injection moved AFTER the resample (the drive is
  generated at output_fs = target rate — placing it on the capture
  grid would have compressed it by M).
- **`streams.max_input_fs(settings)`**: nidaq via entry_capabilities
  ai_max_rate — DIVIDED by channel count on multiplexed devices
  (ai_max_multi_chan_rate is AGGREGATE for one scanning ADC; caught
  while writing the hw-check, would have over-asked a 2-ch 6003);
  soundcard probes the rate ladder with check_input_settings; mock
  gets MOCK_MAX_FS = 1 MS/s for test headroom.
- **Webui**: Setup full gains the off-by-default "digital low-pass —
  oversample + decimate" switch. Bridge: one `lpf_on` kwarg (server
  does the chain). Web Audio: `lpfOn` skips the AudioContext rate pin
  (records at the context's NATIVE rate — also avoids the browser's
  own opaque resampler) and AcquireCard resamples to the requested fs
  via the engine post-capture (skipped for bridge captures, which
  arrive at the target rate already).
- **Hardware verification is PENDING (PC)**: bridge_hw_check.py grew
  check E (lpf_on log on all three NI devices); see TODO.md. All
  Mac-runnable coverage is green (mock-driver pytest incl. pretrigger
  timeout path, amplitude preservation of the mock sines).

## 3. Time-view Resample + "resample to match"

- `actions.resampleTime(setId, fsNew)` → engine op `resample_time`
  (same core). Swaps arrays/axis/settings.fs in place, drops the
  clean-impulse stash (raw arrays at the old rate would corrupt a
  later toggle), re-emits the dataset (autosave), recomputes existing
  derived results only, and offers ONE-level Undo via the success
  toast (`undoResample`).
- TimeCard "resample — now X kHz" group: dropdown of other
  time-bearing sets with their fs ("match <set> (fs)") + custom…
  entry with an fs box; stale selections fall back to custom via an
  effect. Apply disabled when the target already runs at that rate.

## Suites at close

pytest 340 passed / 3 skipped (+12: resample_to_fs unit DSP asserts —
passband unity / −80 dB alias floor / 147/160 rational / zero-phase
impulse mapping / noise process gain; mock lpf_on log family). vitest
652 passed / 1 skipped (+5 incl. autoVoicesForW0 rule + resampleTime
swap/undo/no-op). `npm run check` 0/0. Playwright 79 passed / 7
hardware-skipped (one new Time-Resample engine test; the Setup-full and
CWT tests grew the LPF-toggle and w0-slider/auto-voices assertions).
`python -m mkdocs build --strict` green. Engine wheel rebuilt (same
2.0.0 filename; CI rebuilds on deploy).
