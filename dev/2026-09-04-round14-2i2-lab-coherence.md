# Round 14 — 2i2 coherence on the 3C6 rig: noise on the accelerometer channel, not acquisition

Date: 2026-09-04, afternoon, on the 3C6 lab PC itself (Claude desktop
app, `C:\Users\tb267\pydvma`, conda env `pydvma`, pydvma 2.4.2
installed). Bench: Scarlett 2i2 4th Gen (driver 4.150.0.432), noise
generator on input 1 (LEFT, `ch0`), accelerometer on input 2 (RIGHT,
`ch1`), driving the 3C6 rig. Tore's report: "really poor coherence
most of the time, occasionally the first test in a batch doing better,
true for fs = 3k, 48k…; the NI DAQ is better", plus "default device
lists the Focusrite but in practice I got the mock sine waves".

## Verdict (revised the same evening — see "Revision" below)

1. **The coherence loss is not an acquisition fault, and — revising
   the afternoon's reading — it is not an analogue fault on input 2
   either: it is frame-level corruption of BOTH channels in the 2i2's
   digital path** (device, its USB link to this PC, or its power),
   visible only on the accelerometer because that signal is 15 dB
   weaker in-band and lives at a few modal peaks. Evidence in the
   Revision section; the afternoon's evidence below stands as
   evidence, its interpretation is superseded.
   ~~The coherence loss is not an acquisition fault.~~ Every capture —
   the lab's own `.dvma` files and 7 live captures made here — had
   zero PortAudio input overflows, and the accelerometer channel's
   coherence collapses exactly where **its own broadband noise floor
   rises 10–15 dB**, while the noise-source channel in the very same
   USB frames stays flat. The identical bursts appear in a raw
   `sounddevice.InputStream` capture that never touches pydvma. Both
   channels share one stream, one callback and one ring buffer, so no
   timing or buffer bug can touch one channel and not the other. The
   noise enters upstream of the converter on input 2: accelerometer,
   its cable/connector, its conditioning/IEPE supply, or the 2i2's
   second input.
2. **"Default device → mock sines" is a real bug, fixed.**
   `dvma.launch()` with no settings started the bridge with
   `default_driver='mock'`, while the handshake labelled the UI's
   Default row with the OS default input (the Focusrite). A configure
   that named no device fell back to mock. Now `'auto'` resolves
   "Default" to the OS default input soundcard on its recommended
   backend (`serve.resolve_default_device`), else mock.

## Evidence — the lab's files (`data/not-working-examples/wetransfer_…/`)

Three `.dvma` files (14:55, 14:57, 15:00), nine captures, all from the
same session:

| set | time | fs | driver / device | 1 s-block coherence (20–1000 Hz) |
|---|---|---|---|---|
| TD0, TD1 | 14:49 | 44.1k | **mock** | pure 100 Hz / 200 Hz sines — the "mock sine waves" |
| TD2 | 14:50 | 44.1k (capt. 48k) | soundcard 12 (WASAPI) | 0.61 (2 s) |
| TD3 | 14:50 | 44.1k | WASAPI | ~0.68 throughout |
| TD4 | 14:52 | 44.1k | WASAPI | 0.37–0.68, dips at every ch1 spike |
| TD5 | 14:53 | 3k (capt. 48k) | WASAPI | 0.80 typical, dips 0.62–0.69 |
| TD6 | 14:55 | 3k | WASAPI | 0.80 → **0.10–0.24 from 23 s** |
| TD7 | 14:57 | 3k | WASAPI | 0.80 → **0.09–0.14 from 9 s** |
| TD8 | 14:59 | 3k | WASAPI | 0.80 with dips |

What the bad stretches look like (TD6, 23–30 s vs 5–20 s):

- `ch0` (noise source) PSD unchanged to within 1 dB at every frequency.
- `ch1` (accel) PSD **+10 to +13 dB off-resonance** (−70.7 → −59.0 dB
  at 100 Hz, −84.9 → −71.5 dB at 700 Hz), only +3 dB on the 310 Hz
  mode: an added broadband floor, not extra structural excitation.
- The coherent part survives underneath: |H| at 300 Hz 0.31 → 0.24,
  group delay 1.5 ms both times; the inter-channel lag in good seconds
  is a steady 24 samples at 3 kHz (8 ms) and in bad seconds the only
  correlation left is a weak instantaneous one (lag 1).
- No exact-zero runs, no leading zeros, no time-warp signature; the
  collapse onsets fall at arbitrary sample offsets, not chunk
  boundaries.
- Besides the sustained bursts, every capture carries isolated 50 ms
  spikes of ~+10 dB on `ch1`, each costing a coherence dip in its
  1 s block (TD4 has a dozen).

`dev/screenshots/2026-09-04-round14-lab-captures-envelopes.png` shows
all of this: 420–700 Hz band envelopes of both channels with the
per-second coherence overlaid.

## Evidence — live on the bench (16:30–17:10)

Rig on, same cabling, Tore's notebook session (`dvma.launch()`, PID
5124) still holding a WASAPI shared session on the endpoint.

| capture | overflows | 1 s coherence | ch1 noisy 50 ms windows (>+6 dB) | ch0 noisy windows |
|---|---|---|---|---|
| raw `sd.InputStream`, WASAPI shared, 48 k, 60 s | 0 | 0.5–0.7 for 33 s, then **0.05–0.24** | 320 | 0 |
| pydvma `log_data` fs=3000, rep 0 | 0 | 0.8 → 0.11–0.2 | 173 | 0 |
| pydvma fs=3000, rep 1 | 0 | 0.2–0.8 | 53 | 0 |
| pydvma fs=3000, rep 2 | 0 | 0.2–0.8 | 42 | 0 |
| pydvma fs=48000, rep 0 | 0 | ~0.68, collapse at 29 s | 24 | 0 |
| pydvma fs=48000, rep 1 | 0 | **0.07–0.18 for all 30 s** (ch1 floor −44 dB vs −54.5 normal) | 21 | 0 |

`dev/screenshots/2026-09-04-round14-raw-2i2-accel-noise-bursts.png` is
the raw capture: envelope + coherence, ch1 spectrum quiet vs noisy
(broadband, non-modal, no 50 Hz harmonics), ch0 spectrum identical in
both, and the waveform at a burst onset. High-band (2–8 kHz) kurtosis
on `ch1` is >100 even in "quiet" windows — the channel crackles.

Callback timing was also clean on every run: PortAudio's
`inputBufferAdcTime` is jittery on WASAPI shared (a known timestamp
artefact) but wall-clock gaps never exceeded three chunks and the
overflow flag never fired. The round-12/13 integrity machinery is
doing its job — it reports nothing because nothing was dropped.

## Evidence — the 15:56 / 16:02 / 17:04 files (NI comparison, cable exchange, dropouts)

Tore's own comparison run, same afternoon, same rig, same charge-mode
accelerometer through the same charge amplifier (its voltage output is
what both acquisition boxes see):

| time | driver | fs | accel channel (ch1) noisy 50 ms windows | 1 s coherence |
|---|---|---|---|---|
| 15:51 | 2i2 WASAPI | 44.1k (capt. 48k) | 99 / 600 (16 %) | median 0.13, 18 of 30 s < 0.3 |
| 15:53 | 2i2 | 3k | 56 / 600 (9 %) | median 0.14, 27 of 30 s < 0.3 |
| **15:54** | **NI (RSE, no IEPE)** | 3k | **0 / 600** | **0.77–0.81 every second** |
| **15:55** | **NI** | 3k | **0 / 600** | **0.77–0.80 every second** |
| 15:57 | 2i2 | 3k | 56 / 600 (9 %) | median 0.13 |
| 15:58 | 2i2 | 48k | 2 / 600 | 0.62–0.70 every second (a clean 30 s) |
| 15:59 | 2i2 | 48k | 37 / 600 (6 %) | median 0.11 |
| 16:01 | 2i2 | 48k | 30 / 600 (5 %) + 191 zero runs | median 0.55 |

The charge-amp output is clean for 60 s straight on the NI and noisy
on the 2i2 immediately before and after, so the accelerometer and the
charge amp are exonerated; the noise is added where that output meets
the 2i2. (NI's ch1 also resolves three more modes — 762, 1143,
1360 Hz — that the 2i2's floor buries.)

17:04 file, after Tore **exchanged the two physical cables** (each
signal now travels on the other cable but still arrives at the same
2i2 input — the accel is still channel index 1: RMS 0.04, lag +8 ms
behind the drive, modal spectrum): the bursts stayed on the accel
channel (22 % / 9 % / 14 % noisy windows in the three 2-ch sets). The
cables between the bench and the 2i2 are exonerated too. Remaining
suspects, in order: the 2i2's input 2 itself, and the way the charge
amp's output is presented to it (48 V phantom on the XLR pins into a
charge amp output stage; Inst/Hi-Z mode; Air). The channel swap proper
(charge amp into input 1, generator into input 2) decides between
them.

**Dropouts, a second and separate fault.** The 17:01:48 set has a
188 ms stretch of exact zeros on BOTH channels at 26.5 s (plus runs of
8–184 frames), the 17:02:51 set 278 runs of 2–34+ frames totalling
815 ms, the 16:01:54 set 191 runs. Both channels zero at once, run
lengths arbitrary (not chunk-sized, not multiples of anything), the
signal spliced across the gap — this is the Focusrite driver
zero-filling lost USB packets, and PortAudio's overflow flag never
fires for it, so the round-12 integrity toast stayed silent. Now
detected: `acquisition.exact_zero_dropouts` scans every capture for
all-channel exact-zero runs of ≥ `DROPOUT_MIN_RUN` (8) frames after
the first sample (a live analogue input never produces one; a silent
16-bit record is exempted), `log_data` parks `(count, seconds)` in
`LAST_CAPTURE_DROPOUTS` and warns, serve pins the same toast. Applied
to the afternoon's files it flags exactly the sets above and nothing
else. Remedy is on the USB side: another port (motherboard, not a
hub) or cable.

`dev/channel_noise_check.py` is the per-capture report used for all
of the above (which channel's floor jumps, per-second coherence,
inter-channel lag, dropouts) — run it on any `.dvma` before arguing
about acquisition.

## Revision (evening, Tore remote, 2i2 unplugged): it is the 2i2's data path, on both channels

Tore's later facts: the accelerometer is charge-mode into a charge
amp whose voltage output is what both boxes see; the 2i2 path is
charge amp → BNC termination → BNC extension → 2i2 on each channel,
the NI path has no extensions; "swapping the cables" exchanged the two
extensions, and Safe/Inst/Air were off throughout (one run with Inst
on: no change). So the extensions were exonerated as well, and the
"which input" question needed a better instrument than the band
envelope. Three further looks at the 48 kHz captures, comparing the
bad sets (17:01:48, 15:59:57) with the one clean set (15:58:17):

1. **Residual analysis** (accel minus the drive filtered through the
   H1 estimate): the residual does not scale with signal level
   (corr −0.12 / +0.14 within noisy windows — no distortion, and
   peaks are 0.15–0.18 FS, no clipping); its 2–15 kHz kurtosis is
   150–350 against 3 (Gaussian) in the clean set — sparse impulses,
   present even in the bad sets' "quiet" windows; and the largest
   sample-to-sample step on the accel channel is 0.22–0.24 FS against
   0.035 in the clean set, twenty times a channel whose RMS is 0.04.
2. **The drive channel is not clean either** — it only looked clean
   because its own white-noise signal is 15 dB above the added noise
   in-band. Above 5 kHz, where the generator rolls off, the drive
   channel's floor in the bad sets is 9–13 dB above the clean set (at
   10 kHz: −93.7 / −91.2 dB vs −102.8; at 20 kHz: −98.7 / −95.5 vs
   −108.1), and it rises a further 3–4 dB in the accel's noisy
   windows. The biggest spikes on the two channels sit in the SAME
   frames (samples 878306, 878360, 425473, 1319336 head both lists),
   as one- or two-sample outliers with no filter ringing — which an
   analogue event cannot produce through a delta-sigma decimation
   filter.
3. **Common-cause test** (`dev/channel_noise_check.py
   common_cause_test`): band-pass both channels above 6 kHz, rectify,
   cross-correlate the envelopes. Lag-0 correlation **0.63–0.64 in
   every bad capture — Tore's three and both of my raw-sounddevice
   controls — against 0.19 in the clean capture and ~0.01 at any
   other lag**, while the waveform coherence between the residual and
   the drive stays at 0.02: noise arriving on both channels at the
   same instants, independent in value. That is frame-level
   corruption — samples wrong on every channel of the same frames —
   somewhere between the 2i2's converter and the Windows audio engine.
   The exact-zero dropouts (packets the driver zero-filled) are the
   same link in its worst moments.

Everything else lines up: NI clean (a different box), extensions and
cables exchanged with no effect (they carry the signal before the
corruption), Inst irrelevant, any fs (the corruption is at the 48 kHz
capture rate whatever pydvma decimates to), "first test in a batch
better" (a marginal device or link degrading as it warms), and my
earlier sighting of the Focusrite delivering nothing to any new stream
for ten minutes (the same link in a bad state). The PC is not short of
anything — i7-8700, 16 GB, DPC time 0.1–0.6 %, no USB or PnP events
logged today — but its USB port, cable and 5 V supply to a bus-powered
interface are inside the suspect boundary. (Housekeeping noticed on
the way: `NI Device Monitor 17.0` has burnt 25 CPU-hours on a core
since boot and McAfee's `mcshield` 4.7 — neither touches audio timing,
but the NI one is worth disabling.)

## What to check next (in this order)

1. ~~Exchange the physical cables / extensions~~ — DONE 17:04, no
   effect: cables and extensions exonerated.
2. ~~NI comparison with the same charge amp~~ — DONE 15:54/15:55,
   clean: accelerometer and charge amp exonerated.
3. ~~Inst / Air / Safe~~ — off throughout; Inst on once, no change.
4. **USB first, no rig needed**: the 2i2 on a rear motherboard USB
   port with the Focusrite-supplied cable (no hub, no front-panel
   port), then a 60 s capture of the generator alone on both inputs
   (or any signal) at 48 kHz and `dev/channel_noise_check.py` on it:
   the common-cause lag-0 correlation must drop to the clean value
   (~0.2) and the dropout count to zero. If it does, the port/cable
   was the fault.
5. **Loopback discriminator, no rig needed**: play noise out of the
   2i2 into its own inputs via a cable, and record all four MME/WDM-KS
   channels (3/4 are the digital loopback of the output mix). If the
   loopback channels carry the same impulses/floor as the analogue
   inputs, the corruption is on the USB link or in the driver (digital
   domain); if the loopback is pristine while the analogue inputs
   corrupt, it is the 2i2's converter/power section.
6. **Same 2i2 on another computer** (a laptop, same rig or the
   loopback above): corruption persists → the unit (check/update its
   firmware in Focusrite Control 2, then RMA); vanishes → this PC's
   USB.
7. The channel swap proper is no longer diagnostic — both channels are
   affected — but a **stronger accelerometer signal** (more charge-amp
   gain: the accel peaks at 0.18 FS, 15 dB of headroom) would raise
   its coherence against a corruption floor that is fixed in absolute
   terms, as a stop-gap only.

## Side observations (not root-caused, logged for the next visit)

- **The Focusrite delivered no samples to any new stream** (MME,
  DirectSound, WDM-KS and WASAPI shared all opened and started, zero
  callbacks in 60 s) for ~10 minutes while the notebook session held
  its shared session. A WASAPI-exclusive open (which succeeded and
  streamed) followed by a close un-wedged it; after that every host
  API streamed normally, even with the notebook session still open.
  Oddly, MME at 44.1 kHz delivered (through the engine's resampler)
  while MME at 48 kHz did not. Looks like a driver/engine state, not
  pydvma; noted in case a "capture starts with zeros / stream delivered
  fewer samples" report comes in from this PC.
- **Mid-record exact-zero stretches on both channels** (0.1–0.2 s, at
  3 kHz: runs of 172/215/327/309/623 samples) in 2 of 5 pydvma runs;
  none in the 60 s raw run, none in the lab's files, and not
  reproduced in two further 3 kHz runs that recorded every 48 kHz
  chunk the callback received (only the 3 startup priming chunks were
  zero). Cheap hardening if it recurs: count all-zero chunks AFTER the
  first signal in `Recorder.callback` and report them with the overflow
  count. Left as TODO.
- `dev/soundcard_drop_check.py` needs a sine generator; on this rig
  the noise source made the inter-channel-lag and band-envelope
  method above the practical drop/noise detector. Worth folding into
  a `dev/` harness next time.

## Code changes this round

- `pydvma/serve.py`: `_preferred_twin`, `resolve_default_device`;
  `configure` resolves a missing `device_driver` through it and
  reports the choice in `deviceNote`; `--driver` gains `auto` and
  defaults to it (e2e spawns pass `--driver mock` explicitly and are
  unaffected).
- `pydvma/session.py`: `launch()` defaults the driver to `'auto'` and
  prints what it resolved to.
- `tests/test_serve_protocol.py`: 8 tests for the resolver and the
  configure paths (auto with a soundcard, auto without, explicit mock).
- `CHANGELOG.md` Unreleased entry.

Not touched: the webui (it already sends nothing for "Default", which
is exactly the case the server now resolves; the row's label is the
OS default's name, and the reply's note names the backend actually
used).

## Round 14b — the office bench, same evening: a KNOWN source into the 2i2 is clean

Office PC (i7 desktop, RDP session, Claude desktop app), bench cDAQ-9174
+ the office Scarlett 2i2 4th Gen (driver 4.150.0.432 — the same
version as the lab PC; Focusrite Control 2 had just updated and the PC
rebooted), 2i2 gain 15 dB on both channels, **cDAQ 9260 ao0 → 2i2 input
1, ao1 → input 2** through the same BNC extensions the lab used (front
combo jacks; the old ao0→ai0 loopback is gone, so the cDAQ's own AI
cannot be used as a reference for now). Harness:
`dev/twoi2_known_source_check.py` — brick-wall 20–3000 Hz Gaussian
noise, 0.5 Vpk, identical on both outputs, regenerating; the 2i2
recorded through raw `sounddevice` AND `pydvma.log_data` (WDM-KS: RDP
hides the WASAPI/MME endpoints), then the round-14 checker plus
identical-signal metrics.

| run | seconds with coherence < 0.99 (20–3000 Hz) | per-second lag | L − g·R residual | dropouts / overflows | one-sample step / rms | bits |
|---|---|---|---|---|---|---|
| raw sounddevice, 48 k, 60 s | **0 / 60** (min 1.0000) | 0 in every second | 65.7 dB below signal, kurtosis 3.0 | 0 / 0 | 1.2 | 24.0 |
| pydvma `log_data`, 48 k, 60 s | **0 / 60** | 0 | 65.7 dB, Gaussian | 0 / 0 | 1.2 | 24.1 |
| raw, 48 k, **300 s** | **0 / 300** | 0 | 65.7 dB | 0 / 0 | 1.2 | 24.0 |
| pydvma, **fs = 3000** (the lab setting; captured at 48 k, decimated), 60 s | **0 / 60** | 0 | 68.2 dB | 0 / 0 | — | — |
| raw, ao1 delayed 10 AO samples (9.4 capture samples), 30 s | 0 / 30 (0.9999) | **−9 in 30 of 30 s** | — | 0 / 0 | — | — |

Amplitude linearity, 1 kHz sine 0.05 → 1.0 Vpk: 0.4107 FS/V at every
level (four digits), third harmonic 0.000, L/R within 0.5 % — i.e. full
scale **2.435 V**, against the profile's 2.452 V at 15 dB line gain
(0.06 dB). The checker's ">6 kHz envelope" test reads lag-0 0.95 vs
off-lag 0.88 here — shared CONTENT (the two channels carry the same
signal above 6 kHz too), not the lab's peak (0.63 vs 0.25); the verdict
now judges the peak against its own off-lag yardstick (ratio > 1.5,
lab 2.2–2.8, bench and clean-lab 1.1).

So on this PC, this USB port and cable, this 2i2 unit, over WDM-KS:
**no corruption of any kind, raw or through pydvma, at 48 k or
decimated to 3 k, for five minutes**. That exonerates, for the lab
problem: pydvma's soundcard chain (raw = pydvma, sample for sample),
the 2i2 model and its 4.150 driver in general, WDM-KS capture, the
line-input path at 15 dB, and the BNC extensions (they carried the
cDAQ's signal here to 0.06 dB). What is left is exactly what differs
between the two benches: **the lab PC's USB port / cable / 5 V, the lab
2i2 unit, and the host API — the lab captured through WASAPI shared
(device 12 in its files), this bench through kernel streaming**.

Two lessons that cost an hour: (1) PortAudio **renumbers devices
inside a process that imports pydvma** (its rate probes re-initialise
PortAudio) — index 5 was the 2i2 in one process and the Realtek Stereo
Mix in the next, so the first "no signal, only ground noise when the
AO task runs" results, the amplitude sweep that showed a constant 11 mV
"square wave", and a suspicion that the extensions were in the 2i2's
rear OUTPUTS were all measurements of the wrong device. Resolve by
name, every time (the harness now does). (2) The WDM-KS pin refuses
4 channels in every format over RDP, so the loopback-channel
discriminator (checklist item 5) needs a console login (WASAPI/MME).

Two bugs found on the way, both fixed and committed:

- **`setup_output_NI_nidaqmx` wrote a non-contiguous array** — the
  round-13 resample hands `task.write` a fresh C-order (N, 2) array
  whose transpose nidaqmx's ctypes layer refuses. Any two-channel NI
  stimulus at a coerced rate died with `array must have flags
  ['C_CONTIGUOUS']`. **This is in the 2.4.2 cut**, caught before the
  upload; the cut must be re-taken from HEAD (`78fabcb`).
- **The intermittent "set “set” has only one channel"**: `calcTf('all')`
  (and `calcFft`/`calcPsd`) iterated every working set including
  TF-only ones — an orphan TfData, or the Nonlin stage's BLA result
  set, which with one response column has "one channel" — and
  `nameOf` fell back to the literal "set". Compute over "all" now
  considers only time-bearing sets; an explicit TF-only target is
  refused with a clear message (`81d9088`).

### What to check next in the lab (revised order)

1. **Host API, no rig needed** (new, cheapest, most likely): in
   Setup pick the 2i2's **WDM-KS** row, not the WASAPI one, and repeat
   a 60 s capture of anything at 48 kHz; run
   `dev/channel_noise_check.py` on it. If the lag-0 peak ratio drops to
   ~1 and the dropouts to zero, the fault is the Windows audio engine's
   shared-mode path on that PC (the same engine that "wedged" the
   endpoint for ten minutes), and the fix is the backend default — the
   `--driver auto` resolver already prefers WDM-KS.
2. USB port (rear, motherboard) and the Focusrite cable, no hub.
3. `dev/twoi2_known_source_check.py` on the lab PC with the office
   cDAQ (or any generator into both inputs) — the numbers above are
   the reference.
4. Same 2i2 on another PC / another 2i2 on the lab PC → unit vs host.
