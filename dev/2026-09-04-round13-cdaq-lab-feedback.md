# Round 13 — the cDAQ lab round on v2.4.1 (2026-09-04)

Tore's lab report, same morning, against a cDAQ-class device with five
channels on a "1/2-year-old laptop", with `pydvma_2026-09-04_1057.dvma`
(5 captures, 12.8 kHz and 8533 Hz, 10–60 s) in
`data/not-working-examples/`:

1. Coherence "sometimes OK, sometimes a strong lobing pattern with big
   dips at regular frequency intervals".
2. Long captures (~60 s at fs = 12500 or 8000, coerced to 12800 /
   8533) come back with "10, 20, 30 s silent gaps with drifting channel
   voltages" — while the shaker audibly keeps driving throughout.
3. Full settings don't expose chunk/buffer sizes ("may be part of the
   issue above?").
4. "FS" for full scale reads oddly next to *fs* the sample rate.
5. Duration is a dropdown with no typing: a `--settings` prefill of
   40 s showed a blank select that could not be typed back in; and the
   output duration is a separate typed number that should default to
   the capture length.
6. (mid-session) A saved TF carries no settings; the time data's own
   settings are four keys.

Everything below was root-caused on this PC against the bench
cDAQ-9174 (9234 + 9260, ao0→ai0 loopback, IEPE accelerometer on ai1)
before any fix, then fixed, then re-verified on the same hardware.

## What the file says

Envelope + raw-sample forensics of the five captures
(`dev/` scratch analysis, not checked in; the numbers are exact):

| capture | fs | T | signature |
| --- | --- | --- | --- |
| 0 | 12800 | 10 s | clean; drive stops at **9.77 s** (= 10·12500/12800) |
| 1 | 12800 | 60 s | first **30.06 s exactly zero** on every channel (sample 384800 = 3848 whole chunks); data then begins with a fresh-task first chunk (four channels read 0.0 for exactly one chunk); the drive appears ~1 s later |
| 2 | 12800 | 60 s | **22.5 s stretch** (14.31 → 36.88 s, start chunk-aligned) with ch0 at its −0.5 mV noise floor, ch3 at noise, ch1/ch2 wandering ±0.5 V through zero over seconds; ch1's DC continues SMOOTHLY across the end of the gap with the drive superimposed |
| 3 | 12800 | 30 s | clean; drive stops at **29.3 s** (= 30·12500/12800) |
| 4 | 8533.3 | 30 s | clean; drive stops at **28.16 s** (= 30·8000/8533.3) |

Two mechanisms, both reproduced live below:

**A. The NI recorder could not keep up, and lost samples silently.**
`Recorder_NI_nidaqmx._process_chunk` shifted the WHOLE stored buffer by
one chunk per callback, per channel, in a Python loop — the exact
O(buffer) memmove round-12 replaced with ring buffers on the soundcard
side, but left in place on NI ("NI immune, DAQmx buffers in C" — wrong;
the DAQmx buffer only absorbs ~7.8 s of lag). The lab geometry is
12.8 kHz × 60 s × 5 ch = 30.7 MB of strided memmove per 7.8 ms chunk:

| geometry | buffer | shift / chunk | budget | ratio |
| --- | --- | --- | --- | --- |
| 12800 × 60 s × 5 ch (lab) | 30.7 MB | 7.73 ms | 7.81 ms | **0.99×** on this desktop, standalone |
| 12800 × 10 s × 5 ch | 5.1 MB | 0.68 ms | 7.81 ms | 0.09× (the clean 10 s capture) |
| 8533 × 60 s × 5 ch | 20.5 MB | 4.00 ms | 11.72 ms | 0.34× |
| 51200 × 30 s × 4 ch | 49.2 MB | 11.20 ms | 1.95 ms | 5.74× |

A laptop with the serve loop, the monitor feed and the journal all
contending for the GIL is over budget at the lab geometry, and that is
exactly the "long captures at 12500 or 8000" pattern. What DAQmx does
then is the interesting part, measured with the callback instrumented
(`dev/ni_drop_check.py`, T = 150 s to push this desktop over budget):
the backlog climbs linearly to the buffer depth (7.8 s at 18 s in),
then the driver **keeps the task running** and ~45 % of reads fail
with -200279 while the rest succeed — the overwritten samples are
simply gone. The stored buffer, a shift register of the last 60 s of
*processed* samples, then holds a **time-compressed** history spanning
~2× its length of wall-clock: the T = 150 run came back with 66 s of
leading zeros, the sweep at 1.9× its rate, and a frequency jump every
~10 s. Map that onto the lab file: capture 1's 30 s of zeros + a
fresh-task first chunk + the drive 1 s later is the task start (the
log rebuilt the task for the new duration) seen through a reader
running at half speed; capture 2's "silent gap with drifting voltages"
is the **pre-/post-stimulus quiet spliced into the window** — the
shaker was driving, but the recorded 60 s covered two minutes of the
bench, including the accelerometers settling after the previous
stimulus. And a time-warped record is what round-12 already showed
turns coherence into a lobed comb.

**B. The stimulus played at the requested rate's sample count on the
coerced clock.** `MySettings` defaults `output_fs = fs` — the rate the
user *asked* for. The 9260 coerces onto the 9234's own 51200/n ladder
(check H of `dev/bridge_hw_check.py`), so a 60 s sweep generated at
12500 Hz played at 12800 Hz: 2.4 % fast, ending 1.4 s early; at 8000 →
8533.33 that is 6.7 % and 1.9 s. The early stops in captures 0, 3, 4
match to the sample. The console warning about it never reached the
browser, and `use_output_as_ch0` was not in play.

## What landed

Python (`pydvma/streams.py`, `acquisition.py`, `serve.py`):

- **NI ring buffers.** `_alloc_buffers` allocates circular rings;
  `osc_time_data` / `stored_time_data` are copy-returning properties
  (no setter — assignment raises, as on the soundcard); `zero_stored`
  clears the ring; `_process_chunk` does two O(chunk) ring writes and
  reads the trigger-check window (the second-oldest chunk) straight
  from the ring, so the hardware-verified pretrigger contract is
  unchanged. `chunks_seen` is counted, so `_wait_for_buffer_fill` now
  covers NI as a safety net.
- **DAQmx overflows are counted, not printed once per failed read.**
  `-200279` increments `input_overflows` (printed once per task);
  `log_data` diffs it around the dwell exactly as for PortAudio, so
  `LAST_CAPTURE_OVERFLOWS` and serve's pinned "capture integrity"
  toast now fire on NI. Wording is "acquisition host" rather than
  "audio host". The DAQmx input buffer floor is 10 s of samples (was
  5 s, which the driver default already exceeded at these rates).
- **Frozen NI reuse signature** (`_open_signature`, stamped after the
  rate coercion) — the TODO'd twin of the soundcard fix: a settings
  object that IS the recorder's own, mutated in place, now rebuilds
  the task instead of comparing itself to itself.
- **AO coercion → resample.** `setup_output_NI_nidaqmx` reads the
  task's real `samp_clk_rate` and, when it differs from `output_fs`
  (and the AO is on its own timebase), resamples the waveform onto
  it (`analysis.resample_to_fs`) and re-times the task for the new
  sample count — the shared-clock soundcard path's rule, so the
  stimulus keeps its physical frequencies and duration. Message left
  in `acquisition.MESSAGE`.

Web UI:

- **Duration is typed + picked**, the fs-picker pattern: a text field
  accepting `40`, `2.5`, `500ms`, `1m`, and an arrow-only preset
  select (`setup-duration` / `setup-duration-pick`). A prefill of 40 s
  shows 40.
- **Output duration defaults to "match capture"** (a ticked switch;
  the number box shows the capture length, greyed). Unticking seeds
  it with the capture length for editing.
- **"FS" → "full scale"** everywhere it was a unit (`× full scale`,
  `% of full scale`, BLA amplitude `× full scale rms`).
- **Settings provenance.** `recordingMetaFromDvma` carries the
  container's whole `settings` dict verbatim (tags included) and
  `recordingToItem` merges it under the four keys the app has always
  written, so a saved set records device, index, IEPE, terminal
  config, rails, output and trigger settings. Materialised
  `FreqData`/`TfData` are stamped with their source set's settings, as
  python's `calculate_fft`/`calculate_tf` stamp theirs.

Not done, deliberately: exposing `chunk_size`/`num_chunks` in Full
settings. With O(chunk) rings the chunk size no longer bears on
capture integrity at all; it sets the monitor's granularity (7.8 ms at
12.8 kHz) and the pretrigger context ceiling, both fine as they are.
Integrity is now *observable* instead (the toast), which is the
control that was actually missing.

## Verification

- Unit: `tests/test_streams_ni_ring.py` (new, 16 tests: ring order
  across the wrap, copy semantics, no setter, O(chunk) write count
  independent of `stored_time`, pretrigger window after wrap + freeze,
  overflow counting/printing, `log_data` reporting, frozen-signature
  reuse/rebuild/coerced-rate reuse, buffer-fill wait); the NI callback
  fakes moved onto `_alloc_buffers`. pytest **1182 passed, 13
  skipped, 1 failed** — the failure is
  `test_acquisition_cancel.py::TestTwoPhaseArmedWait::test_trigger_state_is_cleared_and_the_buffer_unfrozen_after`,
  a SOUNDCARD two-phase test whose final all-zero assertion races its
  own feeder thread (it keeps appending after `zero_stored`); it
  passes alone and the soundcard path was not touched. Load-sensitive
  test, noted in TODO.
- Hardware (cDAQ-9174): `tests/test_acquisition_hardware.py` **17
  passed, 4 skipped** incl. two new tests —
  `test_long_capture_loses_no_samples` (51.2 kHz × 4 ch × 15 s, the
  5.7×-over-budget geometry: 0 overflows, 0 leading zeros, sweep a
  straight line at the generated rate) and
  `test_ao_coerced_rate_keeps_stimulus_frequencies_and_duration`
  (fs 8000 → 8533.33: driven to the end, slope exact).
- Instrumented bench, before → after, same machine, same rig:

  | run | overflows | leading zeros | sweep rate | per-chunk (median) |
  | --- | --- | --- | --- | --- |
  | T = 90 s, 12.5 k × 4 ch (before) | 0 | 0 | 1.024× (AO coercion) — stopped at 88 s | 7.21 ms / 7.81 |
  | T = 150 s (before) | ~5000 | **66.4 s** | **1.88×**, jumps every ~10 s | 15 ms / 7.81 |
  | T = 150 s (after) | 0 | 0 | 1.000× | 0.46 ms / 7.81 |
  | T = 60 s lab geometry (after, `dev/ni_drop_check.py`) | 0 | 0 | 1.000× | 0.29 ms / 7.81 |

- Bridge: `dev/bridge_hw_check.py` against a spawned
  `pydvma-serve --driver nidaq` — **42/42**.
- Web: `npm run check` 0/0 (188 files), vitest **1148/1**, Playwright
  `bridge.spec.ts` 7/7 + `derived-save.spec.ts` + `session-journal.spec.ts`
  8/8 (BRIDGE_E2E, real spawned mock serve, built dist), mkdocs
  `--strict` clean. Engine wheel rebuilt (still 2.4.1) and verified
  byte-identical to the tree; dist rebuilt.

## Next lab visit (Tore)

- [ ] Repeat the failing geometry on the lab laptop: 5 ch, fs 12500,
      60 s, sweep on. Expect: no zeros, no silent stretches, the
      drive through to the last sample, coherence back to the 2 s /
      10 s levels. If the laptop is *still* too slow for something,
      the toast now says so — a capture with an integrity toast is a
      capture to repeat, not to analyse.
- [ ] `python dev/ni_drop_check.py --T=60 --fs=12500 --ch=5` on the
      laptop for the numbers (per-chunk cost, backlog, overflows).
- [ ] Type 40 in duration; untick "match capture" and set a shorter
      output; confirm the AO stops when the box says.
- [ ] Save a dataset with a TF; reload in python: `tf.settings.fs`,
      `time_data.settings.device_index` / `iepe_excit_current_A` present.

## Release note

These fixes need a release the same way round-12's did (the lab
installs from PyPI). Version bump and the five-site ritual are
untouched here — Tore's call whether this is 2.4.2 or 2.5.0.
