# Hardware lessons learnt — sound cards and DAQs as measurement front ends

Internal record, consolidated 2026-09-10 from rounds 12–15
(`dev/2026-08-20-round12-2i2-lab-feedback.md`,
`dev/2026-09-04-round13-cdaq-lab-feedback.md`,
`dev/2026-09-04-round14-2i2-lab-coherence.md`,
`dev/2026-09-10-round15-lab-feedback.md`). Those carry the evidence and
the numbers; this page keeps what we would want to know before the next
bench, lab or purchase. Not user documentation — the user-facing
distillate is one paragraph in `docs/user-guide/acquisition.md`
("Capture integrity").

**Read section 5 first.** The 2i2 coherence hunt that prompted this
page closed on 2026-09-14: the interface is fine, the lab PCs were the
limit, and sections 1–4 are why.

## 1. A USB audio interface needs a quieter host than a DAQ does

**The mechanism.** USB audio class streams isochronously: packets are
scheduled, not retried, and the driver has a small buffer. If the host
services the stream late, packets are lost — the Focusrite driver
zero-fills them (exact zeros on every channel, 8 frames to 188 ms,
invisible to PortAudio's overflow flag) — and frames get garbled
(one-sample outliers on BOTH channels of the same frames, no filter
ringing, uncorrelated in value but simultaneous). A DAQ over USB uses
bulk transfers that retry on error, and DAQmx buffers on the host
(pydvma asks for 10 s), so a late host costs latency, not samples; a
PCI card (the 3C6 PCI-6220) never sees the USB stack at all. Measured
on the same host-loaded PC on the same afternoon: the 2i2 corrupted,
the PCI-6220 clean even at 50 kHz.

**What "host load" meant in the lab.** Not CPU throughput — a 2-channel
48 kHz stream is 384 kB/s and the callback budget is never the issue
since round 12's ring buffers. It was MEMORY: a 16 GB PC at 22 of 24.5 GB
commit with 4.5 % disk free (the pagefile could not grow), paging at
6 000 pages/s with the disk at 100 % during a routine counter sample,
McAfee + Tanium + Dell agents + a browser + the Claude app resident,
15 days of uptime with a 1.27 GB nonpaged kernel pool. Reproduced three
times out of three: four processes churning 100 MB arrays (what a
notebook does as captures accumulate) gave 12 / 14 / 480 zero-fill
dropouts in 30 s and lifted the accelerometer floor 10–25 dB; disk load
alone and playback through the interface did not. The one pristine 30 s
capture on that PC (−83 dB floor, coherence 0.97 by the app's
estimator) proves the chain can be clean there.

**How it looked from the measurement.** Coherence collapsing on the
WEAKER channel only — the accelerometer at 0.04 FS with its energy at a
few modal peaks — while the drive channel 15 dB stronger looked
untouched; episodes of seconds; the first test in a batch the best (the
kernel grows ~50–75 MB per 30 s × 48 kHz capture, plus the engine
worker and journal copies); every USB port the same; a different unit
of the same model clean on a different PC. Every one of those facts
pointed at the wrong thing first (input 2, the cable, the extension,
the charge amp) until the drive channel's own >5 kHz floor and the
frame-synchronous impulse envelopes were looked at.

**User-space buffering does not help — measured (2026-09-11, lab PC,
rig off so the inputs carry only their noise floor, which is never
exactly zero).** Raw `sounddevice` captures on the 2i2's WASAPI entry
at 44.1 kHz, 30 s each, under the same four-process 100 MB array churn
that reproduced the fault the day before, with PortAudio asked for
progressively deeper buffering:

| condition | PortAudio host buffer | zero-fill runs | frames lost (of 1.32 M) | PortAudio overflows |
|---|---|---|---|---|
| quiet, block 1600, latency high | 73 ms | 0 | 0 | 0 |
| churn, block 100, high | 22 ms | 13 | 51 848 (1.2 s) | 0 |
| churn, block 1600, high | 73 ms | 23 | 88 012 (2.0 s) | 0 |
| churn, block 9600, high | 435 ms | 38 | 84 908 (1.9 s) | 0 |
| churn, block 1600, 0.5 s | 536 ms | 131 | 53 512 (1.2 s) | 0 |
| churn, block 9600, 1.0 s | 1 218 ms | 272 | 57 171 (1.3 s) | 0 |
| quiet again | 73 ms | 0 | 0 | 0 |

Four to seven per cent of every capture gone whatever the buffering,
and PortAudio never once fell behind: the loss happens before the
samples reach any buffer a user-space program owns — in the audio
engine, the Focusrite driver or the USB link. So larger chunks, larger
rings, deeper PortAudio latency or pre-allocation in pydvma cannot fix
it (the rings are pre-allocated already); the levers are the driver's
own buffer setting (Focusrite Control 2, untested), the host's memory
headroom, and not generating the churn in the first place. The one
thing pydvma can do on its own side is keep its footprint down — the
kernel's growth per capture, the engine worker's 0.8 GB, the journal's
copies — so that the logger is not the process that tips a marginal
machine into paging.

**Host requirements we would state for USB audio capture now.**
Several GB of free RAM and NO paging during the capture; the notebook
kernel restarted between batches (or the session saved and cleared);
browsers and other memory-heavy apps closed while logging; a reboot
after long uptime; the interface on a motherboard port with its own
cable, hub power management and USB selective suspend off; and the
PC's security/management agents accepted as a fixed cost — 16 GB is
tight with them. A dedicated measurement PC, or more RAM, is the
structural fix. None of this applies to the NI path.

## 2. The Scarlett 2i2 4th Gen on Windows

- Four capture channels on MME/DirectSound/WDM-KS (3/4 are a digital
  loopback of the output mix), two on WASAPI. The loopback pair is
  SILENT unless Focusrite Control 2 routes a source to it — with
  nothing routed it carries only 16-bit dither on MME — so the loopback
  discriminator (`dev/twoi2_loopback_check.py`) needs that set first.
- Bit depth by host API: WDM-KS and WASAPI shared 24-bit; WASAPI
  exclusive, MME and DirectSound 16-bit. MME/DirectSound accept ANY
  rate and let the audio engine resample (the "3 kHz" request that
  silently ran at 48 k); WASAPI shared is locked to the control-panel
  rate; WDM-KS refuses sub-native rates with -9994 (not -9997).
  pydvma captures at the lowest native rate above fs and decimates
  itself (`select_capture_fs`).
- Devices RENUMBER between enumerations, and inside one process after
  a re-enumeration — resolve by name (`streams.resolve_device_index`),
  and pin bench scripts by name.
- **The endpoint wedge**: after some stream churn (a session holding a
  shared stream while others open and close; a re-enumeration), every
  NEW stream on the device opens and starts but never delivers a
  callback, on every host API, for as long as ten minutes. An
  exclusive-mode WASAPI open, a moment of streaming and a close restores
  delivery to all of them. Seen three times; pydvma now does this
  itself (`Recorder._unwedge_silent_stream`, 1 s grace).
- Windows applies no audio-processing objects to its capture endpoint
  (checked in the registry), so "enhancements" are not a suspect; nor
  were Inst, Air, Safe or phantom for the corruption above.
- On macOS, Focusrite Control 2's install/self-update in August 2026
  changed the device's behaviour (a second CoreAudio stream on the
  device stopped the running input stream's callback) — the duplex
  stream design came from that.
- Its analogue side is excellent when the host behaves: a −92.7 dB
  >6 kHz floor on a live accelerometer channel, 24-bit through WDM-KS.

## 3. NI DAQs

- DAQmx does not stop on input-buffer overflow: it overwrites unread
  samples, keeps the task running and fails reads with -200279, so a
  slow host got a time-compressed patchwork back (round 13). Ring
  buffers, a 10 s DAQmx buffer and overflow counting fixed it.
- DSA modules coerce both AI and AO rates (12500 → 12800, 8000 → 8533);
  a stimulus generated at the requested rate played fast and stopped
  early until it was resampled onto the AO's real rate.
- A multiplexed card's advertised maximum rate is AGGREGATE (divide by
  channels); the 6003 has no hardware AI/AO sync; the 6220 has no AO.
- The PCI-6220 coerces one nominal 3 kHz two ways (3000.3 / 2999.88 Hz,
  with the digital low-pass off / on), so repeated captures come back a
  few samples apart — ensemble averaging now truncates to the shortest
  and tolerates 0.1 % of rate jitter.
- IEPE excitation exists on the 9234 only (0 or 2 mA); a charge-mode
  accelerometer goes through its charge amplifier's voltage output on
  any front end.
- NI pretrigger reporting was single-phase until 2026-09-10 (the flag
  rose only on completion); both hardware recorders are now two-phase.
  An impulse test needs the drive OFF on the trigger channel — a 0.05 V
  threshold against a 0.9 V RMS noise drive fires on the first chunk.
- Expected but not yet verified: the USB NI devices are immune to the
  host-load problem of §1 (bulk transfers, 10 s buffer).

## 4. How to tell acquisition from rig from interface (the method)

1. `dev/channel_noise_check.py <file.dvma>`: per-second coherence
   against each channel's OWN band-limited noise floor, exact-zero
   runs, inter-channel lag in the good seconds, and the common-cause
   test (correlate the two channels' >6 kHz noise envelopes at lag 0:
   ~0.6 means frame-synchronous corruption in the interface's digital
   path, ~0.2 means per-channel analogue or nothing). A capture rate
   ≥ 20 kHz is needed for the last one.
2. A raw `sounddevice` capture with nothing of pydvma in the loop, run
   through the same report — the control that separates pydvma from
   the host.
3. Swap tests, and what each exonerates: exchanging two cables (or
   extensions) between channels exonerates the CABLES only if the
   symptom stays with the signal; moving a signal to the other input
   exonerates the INPUT; the same sensor chain on another front end
   (the NI) exonerates the sensor and conditioning. None of them
   touches a corruption that sits on both channels.
4. A load A/B on the live interface: `dev/soundcard_load_check.py`
   (quiet / CPU + memory churn / disk, and `--buffering` for the
   block-size and latency sweep under churn; raw `sounddevice`, no
   pydvma in the loop, no signal needed). It produced the §1 tables.
5. The app's coherence estimator and the checker's per-second one have
   different ceilings (0.97 vs 0.69 at 48 k with 2048-point segments);
   compare like with like, and against an NI reference of the same rig.

## 5. VERDICT (2026-09-14): it was the host, and the 2i2 is fine

Tore's own cross-checks close the question, and they line up exactly
with section 1:

| What was run | Result |
|---|---|
| 2i2 + the lab rig, captured on a **Mac** | good data |
| 2i2 on the **lab PC**, **shorter** captures | good data |
| **USB NI** on the lab PC | good data |
| USB NI on the lab PC, **decimation + high fs + long capture** | occasional corruption — as MISSING DATA, not low coherence |

No fundamental software fault, and no fault in the 2i2. The failure is
the lab PCs not sustaining a long high-rate stream, and the NI row is
the same ceiling seen from the other side: the bulk-transfer path does
not garble frames the way isochronous audio does, so when the host
finally cannot keep up it shows as a gap, not as noise. That is the
signature to expect on each transport, and it is a useful diagnostic in
its own right — **corruption that reads as noise points at USB audio;
corruption that reads as a hole points at the host.**

Practical envelope for the 3C6 lab as it stands: keep captures short at
high rates on the lab PCs, or move to a machine with memory and disk
headroom. Both drivers now report what they lost — the dropout scan
(2.4.3) and the NI overflow count (2.4.2) pin the toast — so a capture
that hits the ceiling says so rather than passing quietly.

## 6. Open items (2026-09-14)

- Lab PC housekeeping is now the actionable item, not a hardware swap:
  free C:, disable NI Device Monitor 17 (25 CPU-h since boot), consider
  a McAfee exclusion for the working folder; more RAM.
- Characterise where the NI "long + decimated + high fs" ceiling
  actually sits on the lab PC (which of rate, duration and decimation
  dominates), so the envelope can be stated as numbers rather than as
  "shorter".
- Retired with the verdict above: the 2i2 unit swap, and the
  `dev/twoi2_loopback_check.py` converter-vs-link discriminator. Both
  were discriminators for a fault that is not in the interface. The
  harnesses stay for any future interface.
- Ship 2.4.4 — the lab install is still 2.4.3.
