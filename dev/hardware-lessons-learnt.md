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
4. A load A/B on the live interface (quiet / disk / CPU + memory churn
   / playback) — the round-14d scripts are in that session's
   scratchpad description; ten lines of `sounddevice` each.
5. The app's coherence estimator and the checker's per-second one have
   different ceilings (0.97 vs 0.69 at 48 k with 2048-point segments);
   compare like with like, and against an NI reference of the same rig.

## 5. Open items (2026-09-10)

- Re-measure the 2i2 on the lab PC after a reboot on a quiet machine;
  only if still corrupt, swap the unit (this 2i2 on another PC, or the
  office 2i2 here).
- Route the loopback source in Focusrite Control 2 and run
  `dev/twoi2_loopback_check.py` — the last discriminator between the
  converter and the link.
- Verify a USB NI device under the same host load.
- Lab PC housekeeping: free C:, disable NI Device Monitor 17 (25 CPU-h
  since boot), consider a McAfee exclusion for the working folder;
  more RAM.
- Ship 2.4.4 (the round-14d/15 fixes are Unreleased) — the lab install
  is still 2.4.3.
