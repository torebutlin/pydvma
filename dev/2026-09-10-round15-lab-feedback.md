# Round 15 — 3C6 lab feedback on the PCI-6220 (2026-09-10)

Same afternoon as round 14d, on the lab PC, after Tore switched the rig
from the 2i2 to the lab's NI **PCI-6220** (Dev2, 16 AI, multiplexed):
good data at 3 kHz, better still with the digital low-pass on, and fine
at 50 kHz. File: `data/not-working-examples/pydvma_2026-09-10_1454.dvma`
(13 time sets: one single-channel 30 s set, three 30 s noise runs at
3 k / 3 k+LPF / 50 k, two 30 s pretriggered sets, six 6 s impulse taps
and a 10 s run; eight materialised TFs). Two screenshots of the TF view.

Written on the lab PC, which has **no node**: the Python changes are
tested here (443/1 on the touched suites); the web-UI changes are
written against a careful reading of the code and MUST be put through
`npm run check`, vitest and the Playwright `analysis.spec` Clean
Impulse test on the Mac before release.

## Items and dispositions

**1. "Compute failed: Transfer function needs at least one output
channel — set 14_35_26 has only one channel"** with All sets selected.
Root cause: the across-sets ensemble (item 6) — not the per-set path,
which already skips single-channel sets and reports them afterwards.
Fixed with 6.

**2. Two capture-rate dropdowns in Setup (full), the second showing
only "auto".** They answer different questions: the first is the
oversample STRATEGY (`MySettings.oversample`: auto / lowest / highest —
how far above fs the capture runs when the digital low-pass is on; auto
= lowest sufficient on a delta-sigma converter, highest on a multiplexed
SAR card like the 6220, which has no anti-alias filter), the second an
explicit HARDWARE RATE (`capture_fs`) chosen from the device's published
native ladder. An NI device publishes no ladder, so the second select
had one entry and read as broken. Now: labelled "strategy" and
"hardware rate", and the rate select is omitted when the device has no
ladder (`SetupCard.svelte`).

**3. "Mic access" and processing switches shown for nidaq.** The whole
"device" section of Setup-full (getCapabilities readout, the
getUserMedia echo/noise/AGC switches, the latency hint) is Web Audio
machinery; it is now rendered only off the bridge (`{#if !isBridge}`).

**4. Clean Impulse offered on non-impulse data.** New
`lib/analysis/impulse.ts`: `impulseTailFraction` = the fraction of the
input channel's energy in the second half of the record;
`looksLikeImpulse` passes at ≤ 25 % (`IMPULSE_TAIL_MAX`, conservative
as asked). The lab's 6 s taps score 0–1 %, its noise captures 46–55 %.
`actions.impulseEnergyTail(setId, ch)` reads the arrays in place; the
Time card shows the button only when the channel passes or the set is
already cleaned (so the toggle can come off), otherwise a one-line note
saying why (`clean-impulse-hidden`). Vitest:
`tests/analysis/impulse.test.ts`. NB the Playwright Clean Impulse test
uses `?fixture=1`, whose impulse is synthetic and front-loaded — it
should still find the button; confirm on the Mac.

**5. Impulse tests: "waiting for trigger" while recording; sometimes
triggered but not reported.** Two things. (a) The 14:46:46 set has 83 %
/ 99 % of its energy in the second half with the noise generator still
running on the trigger channel (ch0 max 2.1 V against a 0.05 V
threshold): it triggered instantly on the drive, so it WAS "recording
regardless" — that is the physics of the threshold, and the six 6 s
taps (0–1 % in the second half) triggered correctly. (b) The app never
said so because `Recorder_NI_nidaqmx` raised `trigger_detected` only
when the window was COMPLETE (the single-phase contract the soundcard
recorder left behind in round 11): `serve._poll_trigger` therefore saw
nothing during the capture and either caught the flag at the very end
("triggered", late) or lost it to `log_data`'s reset ("timeout") —
whichever won the race. Fixed: the NI recorder is two-phase like the
soundcard — `trigger_detected` at the crossing (newest chunk),
`capture_complete` when the crossing has rolled into the second-oldest
chunk, which is exactly where the old flag was raised, so the
hardware-verified window slicing is untouched (the stored ring now
freezes on `capture_complete`). `acquisition._reset_trigger_state`
lowers both without inventing the soundcard's `trigger_overshoot`
(the slicing route is chosen on that attribute now), and the
`_capture_finished` / poller docstrings say so. Tests:
`test_streams_ni_ring.py` (crossing flagged at once, completion from
the check window, unarmed never flags, reset shape) and
`test_streams_trigger.py` (NI-shaped duck typing). Hardware note for the
next lab visit: with the generator off, an impulse test on the 6220
should now show "triggered" within a poll tick of the tap.

**6. Across-sets TF: coherence 1 for five measurements, then would not
compute.** `analysis.calculate_tf_averaged` averaged cross-spectra bin
by bin with no compatibility check, and the app's 'across' ensemble
swept in EVERY time-bearing working set. The lab's 13 sets mix one and
two channels, 6 / 10 / 30 s, and two coerced rates — the 6220 answers a
3 kHz request with 3000.3 Hz (18002 samples per 6 s) or 2999.88 Hz
(18000) depending on the low-pass — so Python raised on a (2,2,9002)
vs (2,2,9001) shape mismatch and the app refused on the single-channel
first member; the "coherence = 1" lines were the stale per-set
single-frame results left on screen. Fixed on both sides: Python
truncates records to the shortest, requires one channel count and one
sample rate to 0.1 % (`TF_ENSEMBLE_FS_TOLERANCE`; the coercion jitter
is 0.014 %) and refuses the rest by name, stamping `n_samples` into the
provenance (`TestCalculateTfAveragedEnsembleGuards`); the app's
ensemble is the compatible working sets — two channels, the target's
rate — and the others are named in a note after the average is drawn
(`tfEnsembleLeftOutMessage`).

**7. x(iω)^p and the DC bin.** `iwFactor` collapses f = 0 to exactly 0
for any p ≠ 0 (Qt parity), and the dB transform floored `log10(0)` at a
finite −300 dB, which `dataExtent` then autoscaled to — the whole TF
flattened against one point. Per Tore's preference the data handling is
unchanged; the floor is now the named `DB_FLOOR` in `plot/build.ts`,
magnitude and PSD lines carry `dbY: true`, and `dataExtent` ignores
floored points on those lines. The DC point still draws (clipped at the
axis edge on a linear x; off-axis on a log x), nothing else moves.

**8. 'none' first in one list, last in the other.** The TF card's window
list now starts with 'none' like the averaging list.

## Also asked

- **USB NI vs PCI**: the PCI-6220 is clean at 50 kHz on the same
  host-loaded PC that corrupts the 2i2, so the trouble is specific to
  USB audio class: isochronous transfers with no retry, a small driver
  buffer, and a host that services them late. A USB NI device (6003 /
  6212 / cDAQ) moves data with bulk transfers that retry on error, and
  DAQmx buffers on the host (pydvma asks for 10 s) — a late host costs
  latency, not samples. Expect the USB NI to be fine here.

## For the Mac

1. `cd webui && npm run check && npx vitest run` — the new
   `tests/analysis/impulse.test.ts`, and everything touched:
   `lib/analysis/actions.ts` (across ensemble filter + note,
   `impulseEnergyTail`), `lib/plot/build.ts` / `model.ts` (`DB_FLOOR`,
   `dbY`), `components/cards/TFCard.svelte`, `SetupCard.svelte`,
   `TimeCard.svelte`, `lib/analysis/impulse.ts`.
2. Playwright `analysis.spec.ts` "Clean Impulse toggles" (fixture
   impulse must still show the button) and the Setup-full specs
   (device section now bridge-gated; capture-rate select conditional).
3. `python -m pytest` in full; then the engine wheel (`analysis.py`
   changed) before staging.
