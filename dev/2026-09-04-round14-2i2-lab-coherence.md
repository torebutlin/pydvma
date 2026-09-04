# Round 14 — 2i2 coherence on the 3C6 rig: noise on the accelerometer channel, not acquisition

Date: 2026-09-04, afternoon, on the 3C6 lab PC itself (Claude desktop
app, `C:\Users\tb267\pydvma`, conda env `pydvma`, pydvma 2.4.2
installed). Bench: Scarlett 2i2 4th Gen (driver 4.150.0.432), noise
generator on input 1 (LEFT, `ch0`), accelerometer on input 2 (RIGHT,
`ch1`), driving the 3C6 rig. Tore's report: "really poor coherence
most of the time, occasionally the first test in a batch doing better,
true for fs = 3k, 48k…; the NI DAQ is better", plus "default device
lists the Focusrite but in practice I got the mock sine waves".

## Verdict

1. **The coherence loss is not an acquisition fault.** Every capture —
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

## What to check on the rig (in this order)

1. ~~Exchange the physical cables~~ — DONE 17:04, bursts stayed with
   the accel on input 2: cables exonerated.
2. ~~NI comparison with the same charge amp~~ — DONE 15:54/15:55,
   clean: accelerometer and charge amp exonerated.
3. **Channel swap proper**: charge-amp output into 2i2 input 1,
   generator into input 2, log again. Bursts move to ch0 → the
   charge-amp output does not get on with the 2i2's inputs (see 4).
   Bursts stay on ch1 → the 2i2's input 2 hardware.
4. **How the charge amp meets the 2i2**: is the 48 V button lit
   (phantom on the XLR pins into a charge-amp output stage), is the
   connection on the XLR or the TRS jack, is Inst (Hi-Z) lit, is Air
   lit? All should be off / line / TRS for a line-level source.
5. **USB**: move the 2i2 to a motherboard USB port with a known-good
   cable (no hub) and re-check with `dev/channel_noise_check.py` —
   the dropout count must go to zero.

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
