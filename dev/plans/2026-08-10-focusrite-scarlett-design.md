# Focusrite Scarlett 2i2 4th Gen support — investigation and design

Date: 2026-08-10
Hardware under test: Scarlett 2i2 4th Gen, serial S2J525A573389F, USB
VID 0x1235 / PID 0x8219 (33305), firmware bcdDevice 2417, on macOS
(Apple silicon), Focusrite Control 2 running. Rigol generator on input 1.

Status: **design, not yet approved or implemented.**

---

## 1. What was measured

All numbers below are from live measurements on this device, not from
datasheets. Test scripts are in the session scratchpad; the ones worth
keeping are listed in §7.

### 1.1 The device offers six native sample rates

CoreAudio reports `kAudioDevicePropertyAvailableNominalSampleRates` as
six discrete values — there is no continuous range:

```
44100, 48000, 88200, 96000, 176400, 192000
```

This matches the user guide ("Supported Sample Rates: 44.1 kHz, 48 kHz,
88.2 kHz, 96 kHz, 176.4 kHz, 192 kHz", p43). **44.1 kHz is the floor.**

### 1.2 `sounddevice` claims every rate works. It is lying.

`sd.check_input_settings()` returns success for *every* rate tried,
including 3000 Hz:

```
3000 OK   8000 OK   11025 OK   16000 OK   22050 OK   32000 OK
44100 OK  48000 OK  88200 OK   96000 OK  176400 OK  192000 OK
```

The hardware cannot run at any of these except the six native rates.
CoreAudio silently sample-rate-converts. Confirmed by reading the HAL
nominal rate *while a stream is open*:

| requested fs | hardware clock while streaming | what actually happens |
|---|---|---|
| 44100 | 192000 | OS resampled |
| 48000 | 192000 | OS resampled |
| 96000 | 192000 | OS resampled |
| 192000 | 192000 | true hardware rate |
| 8000 | 192000 | OS resampled |
| 3000 | 192000 | OS resampled |

PortAudio **never changes the hardware clock**. The device stays at
whatever rate Focusrite Control (or the last app, or the system) left it
at — here, 192 kHz — and everything else is converted behind our back.

### 1.3 The OS resampler's quality depends on the ratio, and at some ratios it is unusable

Measured through the device's own digital loopback, with the test tone
generated at the hardware rate so it is genuine (an earlier version of
this test generated the tone inside the low-rate stream, where it was
already aliased — that result was discarded).

Capture requested at 8000 Hz (Nyquist 4000 Hz):

| | hw clock 192000 | hw clock 44100 |
|---|---|---|
| in-band 1000 Hz | **−1.19 dB** | −0.00 dB |
| in-band 3000 Hz | **−4.33 dB** | −1.00 dB |
| alias: 5000 Hz → 3000 Hz | **−11.7 dB** | −64.7 dB |
| alias: 6000 Hz → 2000 Hz | **−17.5 dB** | −113.8 dB |
| alias: 9000 Hz → 1000 Hz | −48.9 dB | −126.6 dB |

At the 24:1 ratio the converter is close to useless for measurement:
4 dB of passband droop and only 12 dB of alias rejection. At 5.5:1 it is
respectable. **The user cannot see which case they are in**, and the
answer depends on the state another application left the device in.

When the requested rate equals the hardware clock, capture is exact
(−0.00 dB at 1 k, 5 k and 15 kHz).

### 1.4 The hardware clock *is* settable, from pure Python

`kAudioDevicePropertyNominalSampleRate` reports `settable = true`, and a
~150-line `ctypes` binding against the CoreAudio framework sets it
reliably with no new dependency:

```
available rates: [44100, 48000, 88200, 96000, 176400, 192000]
set 44100:  OK -> now 44100.0
set 48000:  OK -> now 48000.0
set 192000: OK -> now 192000.0
```

### 1.5 Gain cannot be set or read on macOS

Three routes were investigated, all closed:

- **CoreAudio HAL.** A probe of `VolumeScalar`, `VolumeDecibels`,
  `Gain`, `Mute` and phantom-power selectors across every input element
  (master + channels 1–4) found **no controllable properties at all** on
  the input scope. The device exposes no HAL gain control.
- **Focusrite Control 2's local server.** FC2 advertises
  `_ocaws._tcp` on Bonjour (`fc2-<mac>`, port 58323 plain / 58322
  secure, with a `publicKey` in the TXT record) and speaks **AES70/OCA
  over WebSocket**. It is reachable and answers, but the object tree is
  hidden behind an `OcaFocusriteAuthenticationAgent` at object number
  4096; every other object number returns `BadONo`. Binary strings
  confirm a `RequestApproval` / `SendQRData` pairing flow backed by
  x25519 + libsodium `secretstream` — i.e. the phone-app pairing
  handshake, which requires a human to approve the client inside FC2 and
  then encrypts the session. This is an undocumented, authenticated,
  encrypted, vendor-private protocol. Reverse-engineering it would be
  fragile and would break on FC2 updates. **Out of scope.**
- **USB vendor protocol.** The Linux kernel driver
  (`snd-usb-audio` / alsa-scarlett-gui) does control Gen 4 gain over a
  USB vendor protocol, so the protocol is known in principle. On macOS
  the USB Audio Class interfaces are held exclusively by the system:
  `UsbExclusiveOwner = "pid 94450, usbaudiod"`. A userspace libusb
  client cannot claim them; doing this properly would need a DriverKit
  extension. **Out of scope.**

So: **gain is neither settable nor readable in software on macOS.** It
is a front-panel knob plus Focusrite Control 2, and pydvma cannot see
it. This is the single biggest obstacle to the "student-lab-proof"
goal, and the design below works around it rather than solving it.

The same applies to 48V, Inst/Line, Air, Auto Gain, Clip Safe, and the
front-panel **Output** knob — the last of which is an *analogue* control
on outputs 1/2, so playback voltage is not repeatable either.

### 1.6 Inputs 3 and 4 are a digital loopback, not analogue inputs

The device presents **4 input channels**. Per the user guide (p44),
inputs 1–2 are the analogue Mic/Line/Inst inputs and inputs 3–4 are
**Loopback 1–2**, a digital tap of the output mix.

Verified: playing 0.05 FS at 1000 Hz to outputs 1/2 returns exactly
0.0500 FS at 1000.0 Hz on input 3. Amplitude-exact and cable-free.

Two consequences:

- **Risk.** pydvma currently reads `max_input_channels` and will happily
  offer a student 4 channels, two of which are not connected to the
  outside world at all. Silent, confusing, and easy to record by
  accident.
- **Opportunity.** This is a free, always-available, end-to-end
  acquisition self-test — the equivalent of the NI BNC loopback but
  digital and needing no cable. It exercises output stimulus → device →
  capture → analysis in one shot, and belongs in the test suite and in a
  `dev/` harness.

### 1.7 Input voltage calibration is a closed-form function of gain

From the user guide (p43), max input level at minimum gain, and gain
range 69 dB (62 dB for Inst):

| input mode | max input at min gain | full-scale peak volts at gain G |
|---|---|---|
| Line | 22 dBu | `√2 · 0.7746 · 10^((22−G)/20)` |
| Instrument | 12 dBu | `√2 · 0.7746 · 10^((12−G)/20)` |
| Mic | 16 dBu | `√2 · 0.7746 · 10^((16−G)/20)` |

Line examples: **13.79 V pk** at 0 dB, 3.46 V at 12 dB, **0.870 V at
24 dB**, 0.219 V at 36 dB.

This maps directly onto pydvma's existing `MySettings.VmaxSC` ("the jack
voltage corresponding to a normalised reading of 1.0",
`pydvma/options.py:127`), applied at `pydvma/streams.py:526`. So
calibrated volts are achievable **provided the user tells pydvma the
gain and input mode** — which is the unavoidable manual step created
by §1.5.

Output side: line outputs are 16 dBu max = 6.91 V peak, but the analogue
Output knob sits in that path, so `output_VmaxSC` is only meaningful at a
marked knob position.

### 1.7a The calibration model, confirmed on hardware

Measured later the same day with a 5.000 Vpp sine (Rigol CH1, 215 Hz)
into the Line input at a Focusrite-Control-reported **9 dB** gain:

- fundamental **0.505072 FS peak**, crest factor 1.4166 (theory
  1.4142), THD 0.13 %, no clipped samples, 5.9 dB headroom — a clean
  sine, so the reading is trustworthy;
- implied **`VmaxSC` = 4.9498 V peak** at full scale (3.500 V rms,
  13.10 dBu);
- the §1.7 model predicts 4.8932 V pk at 9 dB — agreement to
  **0.10 dB**, i.e. an implied gain of 8.90 dB against the 9 dB set.

So the manual's max-input table *and* Focusrite Control's gain readout
are both accurate to ~0.1 dB. Calibrated volts therefore need only the
gain and input mode the operator states — no per-device calibration
run.

An earlier attempt at 24 dB gain clipped hard (78 % of samples at the
rail, THD 30 %, crest 1.10 — a square wave); a 5 Vpp sine needs the gain
below ~15 dB on the Line input. Worth remembering that the useful
by-product of a clipped capture is still a bound: back-solving the
clipped duty cycle gave ~0.845 V pk full scale, within 3 % of the model.

### 1.8 What is actually on input 1 right now

Captured 5 s at a pinned 44.1 kHz clock:

- rms 0.0279 FS, peak 0.1390 FS, crest factor 4.98 (Gaussian noise),
  17.1 dB of headroom — not clipping.
- **The noise is flat to 20 kHz**, not band-limited to 1 kHz: mean PSD
  is −74.5 ± 0.2 dB in every band from 20 Hz to 20 kHz. There is no
  roll-off anywhere below Nyquist.
- Implied physical level, if the input is Line at 24 dB gain:
  **24.3 mV rms / 121 mV pk**.

Two things worth flagging to the operator: the source is **broadband,
not 1 kHz-limited** (so it is an excellent anti-aliasing test signal,
and a nasty one if the anti-aliasing is wrong); and 24 mV rms is roughly
30–40 dB below what a 5 Vpp setting would imply, so either the generator
is set differently than believed, there is an attenuator in line, or the
gain is not 24 dB. This is precisely the ambiguity calibrated volts is
meant to remove.

---

## 2. Answers to the questions asked

**Can we add the device via the sounddevice driver?** Yes — it already
enumerates and captures. But shipping it as-is would silently hand
students resampled data, so the work below is not optional polish.

**Are device-specific additions needed?** Yes, two: the macOS
hardware-clock pin (§1.2–1.4), and a device profile covering the native
rate ladder, the loopback channels, and the input calibration model.

**Can we set the gain in software?** No. Not by any route that is
appropriate to ship. See §1.5.

**Can we at least read it?** No — same barrier.

**Can we specify the sample rate?** Not through `sounddevice` alone —
that only chooses a resampling target. Through CoreAudio directly, yes,
and pydvma should do this.

**Can we document accepted fs values?** Yes: the six native rates,
queried from the device rather than hard-coded.

**Voltage as the output unit?** Yes, via the existing `VmaxSC`, computed
from gain + input mode. It cannot be automatic, because gain is not
readable.

**Highest-fs-then-software-LPF, or lowest-native-fs-then-software-LPF?**
**Your instinct is right, and the measurements back it.** Capture at the
lowest *native* rate that covers the bandwidth (44.1 kHz for essentially
all vibration work), then decimate with pydvma's own polyphase Kaiser
filter. Two reasons beyond the obvious data-volume one:

- The 2i2's converters are delta-sigma with an anti-alias filter locked
  to the converter rate. At 44.1 kHz everything above ~22 kHz is already
  gone *in hardware*, so capturing at 192 kHz buys no alias protection
  for a 1.5 kHz measurement — it only adds 4.35× the data.
- pydvma's `analysis.resample_to_fs` has a 96 dB stopband and is
  characterised and tested. CoreAudio's converter, as measured, ranges
  from 12 dB to 114 dB of rejection depending on a ratio nobody chose
  deliberately.

So for a 1.5 kHz bandwidth lab: pin the clock to 44.1 kHz, capture at
44.1 kHz, decimate in software to 3 kHz. The only correction to the plan
as you stated it is that the clock must be pinned explicitly — otherwise
"log at 44.1 kHz" may quietly mean "resample from 192 kHz".

---

## 3. Design

Five pieces, in dependency order. Each is independently useful.

### A. `pydvma/_coreaudio.py` — macOS hardware clock control

A small `ctypes` module, no new dependency, importable everywhere and
inert off macOS (`available()` returns False; every entry point no-ops
or raises a typed error).

```
available()                     -> bool
find_device(name_substring)     -> (device_id, name) | (None, None)
native_rates(device_id)         -> [44100.0, ...]      # queried, not hard-coded
get_nominal_rate(device_id)     -> float
set_nominal_rate(device_id, fs) -> bool                # verifies, with timeout
```

Already prototyped and working against the real device.

**Design decision to confirm:** the nominal rate is a *system-wide*
device property. Setting it affects other applications using the same
interface. The proposal is to pin on capture start and **restore the
previous rate on stop**, so pydvma leaves the machine as it found it.

### B. Honest sample-rate ladders

- `streams.max_input_fs` (`streams.py:164-217`): for the soundcard
  driver on macOS, return the highest **native** rate, and add a
  `native_input_rates(settings)` helper returning the full ladder.
  Today it derives the answer from `check_input_settings`, which §1.2
  shows accepts everything.
- `serve._soundcard_candidate_rates` (`serve.py:472-502`): same fix —
  the advertised `fs_ladder` in `device_caps` must be the native list,
  so the web UI dropdown stops offering rates the hardware cannot run.
- `SetupCard.svelte:63` currently hard-codes
  `SAMPLE_RATES = [8000, 16000, 22050, 44100, 48000, 96000]` for the
  browser path; the bridge ladder already overrides it when present.

Off macOS, behaviour is unchanged pending the equivalent check on
Windows (see §6).

### C. Capture at a native rate, decimate in software

Extend the existing `lpf_on` machinery (`acquisition.py:119-147`) so
that for the soundcard driver the oversample target is **the lowest
native rate ≥ 2.56 × target fs**, not `max_input_fs`. For a 3 kHz
target that selects 44.1 kHz rather than 192 kHz — same alias
protection, 4.35× less data.

Additionally: when the user picks a **non-native** fs with `lpf_on`
off, do not hand them an OS-resampled capture. Either refuse with an
actionable message, or transparently capture-and-decimate. This is the
main open question in §5.

`lpf_capture_fs` already records the true capture rate; nothing new is
needed to keep the provenance.

### D. Device profile and channel labelling

A small table mirroring `pydvma/_ni_device_specs.py`, keyed on device
name:

- native rate ladder (fallback if the CoreAudio query is unavailable);
- **channel roles** — 1–2 analogue, 3–4 `loopback` — surfaced in
  `device_caps` so the UI can label or hide them. This closes the
  §1.6 trap.
- input calibration model — the max-input-level table from §1.7,
  so `VmaxSC` can be *computed* from a gain + input-mode the user
  states, rather than typed as a raw voltage.

### E. Gain provenance, since gain cannot be read

Given §1.5, the goal shifts from control to **provenance and
verification**:

1. New settings fields — `input_gain_db` and `input_mode`
   (`line` / `inst` / `mic`) — which drive `VmaxSC` through the §1.7
   formula. Recorded in the saved dataset, so a `.dvma` file says what
   the front panel was set to.
2. A **level check** in Setup that reports measured rms/peak in volts
   and flags both clipping and gross under-range — which would have
   caught the §1.8 discrepancy immediately.
3. Documentation stating plainly that changing the front-panel gain
   invalidates the calibration, with the loopback self-test (§1.6) as
   the way to confirm the digital chain independently.

---

## 4. Testing

- **Mac-runnable, no hardware:** the `_coreaudio` ctypes layer against a
  fake CoreAudio (`available()` false path, rate verification, restore
  on stop); native-ladder selection in `max_input_fs` and
  `_soundcard_candidate_rates`; the §1.7 voltage formula; the
  lowest-native-rate-≥-2.56× selection rule.
- **Hardware, this Mac:** a `dev/scarlett_hw_check.py` harness in the
  style of `dev/bridge_hw_check.py` — native ladder query, clock pin and
  restore, bit-exactness at a pinned rate, and the loopback round-trip.
  All of it runs headless with no cable, thanks to §1.6.
- **webui:** vitest for the ladder plumbing and channel-role labelling;
  the existing Playwright bridge spec covers the path.

Existing gaps this touches, from the codebase survey: `max_input_fs` has
no direct unit test at all, and nothing asserts that `lpfOn` reaches
`buildSettings` as `lpf_on: true`.

---

## 5. Open questions for approval

1. **Non-native fs with `lpf_on` off** — refuse with a clear message, or
   silently capture-and-decimate? Refusing is honest and teaches the
   constraint; auto-decimating is friendlier for students. A third
   option is to restrict the dropdown to native rates and let `lpf_on`
   be the only route to anything lower.
2. **Clock restore** — restore the previous rate on capture stop
   (proposed), or leave it pinned so successive runs are identical?
   Restoring is polite; leaving it pinned is more reproducible.
3. **Scope now** — A+B+C (the correctness fix) is the part that stops
   bad data reaching students. D and E are the lab-proofing layer. Both
   in one go, or land the correctness fix first?

---

## 6. Deferred / needs the Windows PC

**ANSWERED (2026-08-11, measured on the PC, 2i2 4th Gen, console
session, Rigol 1 kHz 5 Vpp on input 1):**

- **WASAPI does NOT lie.** Shared-mode WASAPI (and WDM-KS) accept
  ONLY the endpoint mix rate (48 kHz here) via
  `sd.check_input_settings` — every other rate is rejected with
  `PaErrorCode -9997`. There is no silent WASAPI resample on the
  default path, so no WASAPI twin of `_coreaudio.py` is needed.
- **MME and DirectSound accept EVERYTHING (1.6–192 kHz) — but their
  resampler is measurement-grade**, unlike CoreAudio's. Measured on
  the 2i2 with the Rigol tone: requesting fs = 1600 (Nyquist 800 Hz
  below the 1 kHz tone) folds NOTHING measurable — rejection ≈
  −100 dB (MME), −94 dB (DS), both at the local noise floor — and
  passband droop at 0.91×Nyquist is −0.30 dB. Compare CoreAudio's
  measured −11.7 dB rejection / −4.3 dB droop (§1.2). PortAudio's
  WASAPI `auto_convert` escape hatch (non-default) measures the same
  ≈ −97 dB. So the Windows `'unknown'` capture-rate path is SAFE in
  practice: an off-ladder request lands on the Windows mixer
  resampler, which does not corrupt measurements. Provenance is the
  only cost (data passed through a resampler pydvma didn't choose).
- **One real Windows trap found instead: mono capture is a downmix.**
  `channels=1` on a shared-mode endpoint delivers (ch1+ch2)/2 — a
  single-input calibrated measurement silently loses 6 dB (measured
  −6.13 dB, exactly the ½ + the 0.1 dB calibration residual).
  Capture ≥ 2 channels and select, or document. Tracked in TODO.md.
- The measurement harness is `dev/windows_resampler_check.py`
  (method notes inside — including the probe-vs-Rigol frequency
  separation rule that produced a false reading on the first attempt).
- ASIO remains unnecessary for correctness on this evidence.

## 6a. Implementation status (2026-08-10)

Scope A+B+C — the correctness fix — is **implemented, tested and
hardware-verified**. D (device profile, loopback channel labelling,
calibration model) and E (gain provenance) are **not started**.

Landed:

- `pydvma/_coreaudio.py` — native rate query + clock pin/restore.
- `streams.native_input_rates` / `select_capture_fs` /
  `soundcard_device_name`; `max_input_fs` prefers the native ladder.
- `Recorder._pin_hardware_clock` / `_restore_hardware_clock`.
- `acquisition._capture_settings` / `_capture_rate_message`, and the
  capture-vs-deliver split in `log_data`.
- `MySettings.capture_fs` — the manual override.
- `serve._soundcard_native_rates`, honest `candidate_rates`, and a new
  `device_caps[...].native_rates`.
- webui: `DeviceCapsEntry.native_rates`, and the Setup note
  "captures at 44100 Hz, resampled to 8000 Hz".

Verified: `dev/scarlett_hw_check.py` 11/11 on the real device; pytest
393/3 skipped; vitest 683/1 skipped; `npm run check` 0/0; mkdocs
--strict green. End-to-end through `pydvma-serve --driver soundcard` in
the built UI: fs = 8 kHz on the Scarlett records real signal whose
amplitude drops from ~0.139 to ~0.045 FS — the out-of-band noise power
is REMOVED, where naive decimation would have folded it in and left the
amplitude unchanged.

Two behaviours worth knowing:

- **Clock lifetime.** The clock is pinned while pydvma holds the stream
  and restored by `end_stream()`, not at the end of each `log_data` —
  pydvma owns the device for the session. A hard kill (SIGKILL) leaves
  it pinned; nothing can be done about that.
- **Output stimulus shares the clock.** The device has ONE clock, so an
  output stream running at a different rate while the clock moves takes
  both streams down (PaMacCore -50, then silence). `MySettings` defaults
  `output_fs = fs`, so a stimulus-enabled log at a non-native fs will
  hit this. Not addressed here — see below.

### Follow-ups this created

1. **Output stimulus at a non-native fs** (above). The fix is to stage
   `output_fs` onto the capture rate for soundcard devices, mirroring
   what `reclampOutputFs` already does for the NI AO rate cap.
2. **Windows/WASAPI** — does `check_input_settings` lie there too?
   Must be measured on the PC before any claim; non-macOS behaviour is
   deliberately unchanged for now.
3. **`max_input_fs` still has no direct unit test** (pre-existing gap;
   the new `select_capture_fs` tests cover the adjacent logic).
4. All of the above are now tracked in `TODO.md` under "Soundcard /
   Focusrite Scarlett follow-ups", alongside the loopback labelling and
   calibrated-volts items from §3 D/E.

## 7. Artefacts worth keeping

- `coreaudio_rate.py` — the working ctypes prototype, the basis for
  `pydvma/_coreaudio.py`.
- The loopback alias-rejection measurement, which should become the core
  of `dev/scarlett_hw_check.py`.

Both currently live in the session scratchpad and are not yet in the
repo.
