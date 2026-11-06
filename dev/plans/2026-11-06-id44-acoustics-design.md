# Audient iD44 support and basic acoustics — design

2026-11-06, Mac session. Status: APPROVED by Tore (2026-11-06). Bench results from the same session are written up as `dev/2026-11-06-id44-bench.md` (to be written during the build).

## Intent

Tore wants pydvma to drive an **Audient iD44 MkII** with **Earthworks M23** measurement mics. The first use is long (1–5 min) recordings of **ambient sound in cars and rooms**: accurate PSDs and frequency content over time (pydvma's existing spectrogram), in **dB SPL**. Four mics now; more later through the iD44's optical (ADAT) inputs, up to 20 at 48 kHz.

This is pydvma's first acoustic use. Add only the standard pieces that are missing (dB SPL, A/C-weighting, octave/third-octave bands, a calibrator step) and make the hardware work properly. Statistics and further analysis are post-processing for now (Tore: "outputs from pydvma are fine for now... main thing now is to add functionality for this hardware").

## What the bench established (2026-11-06, Mac, iD44 + M23 + Bose speakers on the headphone jack)

- **Enumeration (macOS):** `Audient iD44`, 22 in / 24 out, one CoreAudio device. Inputs 1–4 analogue mic/line, 5–20 optical (ADAT, 16 at 44.1/48 kHz; manual: 8 at 88.2/96 kHz via SMUX), 21–22 loopback. The manual's spec table says 20 inputs; the extra 2 are the loopback.
- **Rates:** CoreAudio reports 44.1/48/88.2/96 kHz. The device was at 96 kHz; `_coreaudio.set_nominal_rate` moved it to 48 kHz. 24-bit capture. **No HAL input volume** on the iD44 (`input_volume_db` is empty), so no hidden digital gain to pin, unlike the U24 XL.
- **Loopback:** inputs 21/22 carry DAW 1+2 amplitude-exact (−70.00 dBFS in → −70.00 out). The source is selectable in the iD menu-bar app ("Set Loop-back Source"). Same cable-free self-test as the 2i2's inputs 3/4.
- **Gain is unreadable and unsettable from software.** The preamp gain knobs are analogue front-panel controls: CoreAudio exposes no input gain, and the manual lists no remote gain control (the iD mixer's faders affect monitoring only). The 48 V, −10 dB pad and 100 Hz HPF switches are also front-panel only. The knobs are continuous, so only the end stops are repeatable.
- **Measured gain at the top stop (channel 2):** with outputs 3+4 set to **DAW THRU** (bypasses all volume controls, rated +18 dBu = 0 dBFS) cabled into input 2's jack (line path), gain = **+50.46 dB** at 1 kHz. Identical to 0.01 dB at −80/−70/−60 dBFS and run to run. Round-trip response (DAC + ADC): −1.3 dB at 20 Hz, −0.10 at 100 Hz, −0.22 at 10 kHz, −0.84 at 20 kHz. Taking the line input as the mic preamp with a 10 dB pad in front (manual p16, spec p55), the **mic path is about +60.5 dB** at the top stop, matching the spec table's "0 to +60 dB" rather than the features page's "58 dB of clean gain". Accuracy rests on the rated converter references and the pad being exactly 10 dB: estimated ±0.5 dB until a calibrator confirms. Channels 1, 3, 4 not yet measured (pot tolerance may differ per channel).
- **Manual specs (iD44MKII Manual V4, p55):** mic max input +18 dBu at 0 dB gain (+28 with pad); 0 dBFS = +18 dBu at the converters; line gain −10 to +50 dB, line max +28 dBu; DI (front, ch 1–2 only) 0–60 dB, max +10 dBu; line outs +18 dBu = 0 dBFS; headphones +14 dBu = 0 dBFS; frequency response ±0.5 dB 10 Hz–Fs/2.
- **M23 serial 16332AA** (calibration chart, photo in session): sensitivity **33.5 mV/Pa at 1 kHz**; ±0.3 dB 10–790 Hz; reads about +1 dB at 10–15 kHz relative to 1 kHz. Earthworks supplied a ½-inch calibrator adaptor.
- **Full scale with the M23 at the top stop:** 0.174 Pa rms = 78.8 dB SPL (sine), pad off; 88.8 dB SPL pad on. Cars at speed can exceed 79 dB SPL, especially at low frequencies.
- **Stream quirk:** opening a second PortAudio stream on the iD44 while one is running fails with CoreAudio −10863 ("cannot do in current context"). One full-duplex `sd.Stream` works. pydvma's same-device stimulus path already uses a duplex stream (the 2i2 fix); the build must confirm it covers the iD44.
- **Rate switching restarts the iD mixer.** A loud speaker buzz happened during a run of rate switches and two failed stream opens. Avoid needless switches.
- **Rooms ring:** speaker→mic coherence was 0.69 with 0.17 s windows and 0.93 with 0.68 s windows. Acoustic TFs in rooms need long windows (a docs note, no code).
- **Yeti (USB mic, for comparison):** its own clock (~6.5 ppm against the iD44), 16-bit, both channels identical. Fine for spectra, unusable for TFs against the iD44's output. Out of scope.

## Goals

1. **iD44 device profile** in `pydvma/_soundcard_specs.PROFILES`, with the facts above cited to manual pages: match pattern for the macOS name, label, channel roles, per-mode full scale and gain ranges (mic, line incl. its −10 dB minimum, inst on channels 1–2 only), the pad, and output levels (DAW THRU line outs, headphones). `--list-devices` / Setup show it as **NEEDS GAIN**. The 16 optical inputs need a role distinct from both 'analogue' and 'loopback': they are real inputs, but their voltage scale belongs to whatever external preamp is attached, so the iD44 profile must not claim a full scale for them.
2. **Per-channel gain and pad.** Today pydvma holds one `input_gain_db` / `input_mode` / `VmaxSC` for the whole device (right for the 2i2 and U24 XL). The iD44 has four independent preamps, so the full-scale voltage must be per channel and stored data stay **volts per channel** (pydvma's existing convention). A scalar must keep meaning "all channels" so existing settings, files and devices behave exactly as now. Setup shows per-channel gain / mode / pad rows when the profile says the device has per-channel preamps, with one-click **top stop / bottom stop** values, because those are the only repeatable knob positions. *Claude's call:* the stops fill in the manual's figures (mic 0 / +60 dB, line −10 / +50 dB), not the bench's +60.5, which was one channel of one unit. The bench figure goes in the docs, and anyone can type a measured value instead. Clip detection and the live level meters judge each channel against its own full scale. Python (`MySettings`) and the web app get the same capability.
3. **Calibration to pascals,** two routes:
   - **Spec sheet:** the existing Calibrate dialog's sensitivity (V/Pa) + unit Pa already does this once the data are volts. The M23's 33.5 mV/Pa is entered as 0.0335.
   - **Calibrator step (new):** in the Calibrate dialog, per channel, derive the sensitivity from a recorded reference tone. Inputs: the set holding the tone, the reference level (default 94 dB SPL = 1 Pa rms when the unit is Pa; otherwise an rms value in the chosen unit, e.g. 10 m/s² for an accelerometer calibrator) and frequency (default 1 kHz). The level is the narrowband rms around that frequency. Warn when the strongest component is not near the stated frequency, when broadband level is well above the tone (noise or a loose fit), or when the channel clipped. Python function in `analysis` (source of truth), reached from the web app through an engine op. *Claude's call:* the step works at **any** gain, not just at the stops, since that is what a calibrator is for, and cars may need a gain between them. The derived sensitivity is in the channel's stored units: V/Pa when its gain is stated (data in volts), FS/Pa when it isn't (data in full-scale units, as the dialog already handles). A between-stops calibration is valid only until that knob moves, and the dialog says so.
   - **Carry forward to new recordings (Tore's decision, opt-in):** the Calibrate dialog gets a tick, "use for new recordings too". When ticked, each new capture on that channel arrives already calibrated (sensitivity, unit and provenance). If that channel's stated gain or pad changes, or the device changes, pydvma warns that the carried calibration may no longer hold; it cannot read the knob, so a stated change is all it can notice. Nothing changes for anyone who doesn't tick it (the 3C6 labs keep today's behaviour). Already-recorded sets are still edited per set, as now.
   - **Provenance saved with the data:** how each channel's calibration was obtained (spec sheet or reference tone; date; reference level and frequency) and the stated gain/pad, plus a free-text note (e.g. "pad off, HPF off"). A file must say how its pascals were obtained.
4. **dB SPL.** When every visible line shares the unit Pa, the frequency view's dB axes use the 20 µPa reference: "dB re 20 µPa" for FFT magnitude and power spectrum, "dB re (20 µPa)²/Hz" for PSD. Any other unit keeps today's labels.
5. **A- and C-weighting** (C is Claude's addition: it's the standard partner and the one used for low-frequency noise such as cars). A frequency-view selector **Z (none) / A / C** for the FFT, power spectrum and PSD modes. Analytic IEC 61672-1 curves, 0 dB at 1 kHz. A display transform only, like x(iω): never written into stored data or used by calculations. Labels say dB(A)/dB(C).
6. **Octave and third-octave band levels.** A frequency-view option **Off / Octave / Third-octave** for the power spectrum and PSD modes: band power summed from the spectrum within each band, base-10 IEC 61260 nominal centres (reuse the band ladder in `analysis.py` that `calculate_damping_by_band` already uses). Drawn as stepped bands over the spectrum. Combines with weighting. Bands too narrow for the frequency resolution are left out rather than drawn from one or two bins.
7. **Long recordings work.** 1–5 min × 4 channels at 48 kHz (about 460 MB as float64) must capture, display, compute PSD and spectrogram, save, reload, and survive tab-close restore through `pydvma-serve` with the native engine, without data loss or a silent fallback. Known limits in the path, all at or below that size: the `/engine` socket's 256 MiB inbound frame cap (`serve.py`), the session journal's 256 MB pending-capture budget (`journal.py`), the web app's 192 MiB autosave guard, and browser memory. Measure first, then fix what breaks. State the resulting ceiling for 20 channels in the docs. *Claude's calls:* the target rate is 48 kHz (at 96 kHz the data double; state that ceiling rather than push every limit for it). "Spectrogram" means the STFT; a CWT of minutes of audio is far past the 8 GiB native ceiling, and its existing preflight refusal with a reason is the right behaviour.
8. **Sample rates.** Setup lists 44.1/48/88.2/96 kHz as hardware rates for the iD44, default 48 kHz. Lower rates use the existing route: capture at a hardware rate (the iD44's own anti-alias filter only follows its clock, and it has no rate below 44.1 kHz), then pydvma's decimation (`lpf_on`, `resample_to_fs`). Verify end to end: 48 kHz, 8 kHz (exact 6:1) and 96 kHz, including how many inputs CoreAudio reports at 96 kHz.
9. **Hardware notes, harness and docs.**
   - Bench write-up `dev/2026-11-06-id44-bench.md` and new entries in `dev/hardware-lessons-learnt.md`.
   - A reusable headless harness `dev/id44_hw_check.py`, like `u24xl_hw_check.py`: loopback exactness, rate pinning, and the DAW THRU gain check on whichever channel is cabled.
   - A docs page on acoustic measurements with the iD44: cabling, phantom, the gain stops and pad, calibration by spec sheet or calibrator, dB SPL, weighting, bands, long recordings.
   - TODO.md entries for everything deferred (below).
10. **The `id44/` folder.** Claude's call, which Tore can overrule:
    - Facts move into the profile docstring and the bench doc, with manual page references.
    - **The PDFs are not committed.** The manual is Audient's copyrighted document (12 MB) and the repo is public; the docs link to audient.com instead. No other device manual is in the repo either.
    - `measure.py` and the "Quick acoustic measurements" note are someone else's draft and are not committed. Their useful ideas are folded in here: calibrator sanity checks, a gain/pad note stored with each calibration, and normalising a mic response file to 0 dB at the calibrator frequency (for the TODO).
    - The driver installers are not needed.
    - After the build Claude asks before deleting the folder.

## Non-goals

- Noise statistics (Leq, percentiles, histograms, stationarity). TODO.
- Mic frequency-response correction from the calibration chart. TODO.
- Time-weighted SPL (fast/slow) and a dB SPL readout on the live scope. TODO.
- Recording two devices at once (e.g. iD44 + Yeti), and using the loopback as a TF reference channel.
- Windows: the iD44 has not been on the PC. Its Windows device name and behaviour are a TODO.
- Matplotlib plotting parity for weighting/bands. Python gets the computations, not new plots.

## Anti-goals (failure even if it technically works)

- A dB SPL label on anything not truly in pascals: full-scale units or volts must never read as dB SPL.
- Assuming a gain silently. The iD44's gain cannot be read, so an uncalibrated channel must look uncalibrated.
- Changing behaviour, settings or file reading for the existing single-gain devices (2i2, U24 XL) or NI.
- Weighting or band transforms leaking into stored data or calculations.
- Needless sample-rate switching on the iD44 (it restarts the mixer, and coincided with a speaker buzz).

## Constraints

- Repo conventions (CLAUDE.md):
  - Python is the source of truth and JS twins are pinned by shared known-answer vectors (the `_signature` / unit-wrap precedent).
  - Rebuild the engine wheel after an engine-op or `pydvma/*.py` change.
  - Docstrings on everything public.
  - Tests on both sides.
  - CHANGELOG under `## Unreleased`, no version bump.
  - Small commits to master, no push unless asked.
- Never let bulk numbers cross into pyodide one by one (the Safari JIT lesson): use the packed payload path.
- Hardware-touching code is verified on the real iD44 before handing back, headlessly where possible.

## Hardware access during the build

- The iD44 stays on this Mac with the M23 on input 1 (48 V on) and output 3 (DAW THRU) cabled into input 2's jack. Both gain knobs are at the top stop, pad and HPF off.
- No calibrator yet. The calibrator step is tested with a synthetic tone, with the speakers playing a 1 kHz tone into the M23 (relative check only), and through the loopback.
- Knob and cable changes (other channels' stops, bottom stops) need Tore at the front panel. Plan them as short sessions with him, not as blockers.

## Left to the builder

- How per-channel full scale is represented and carried through capture, serve, the web app and the saved file.
- UI layout and wording for the per-channel rows, the calibrator step, the weighting and band selectors.
- Band-summation details (partial bins at edges, the too-narrow threshold) and the band drawing style.
- How each long-recording limit is fixed once measured.
- Where provenance lives in the saved document, as long as Python can read it.
