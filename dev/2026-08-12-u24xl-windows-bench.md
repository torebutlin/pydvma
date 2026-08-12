# ESI U24 XL on Windows (2026-08-12)

Companion to `dev/2026-08-11-u24xl-bench.md` (the Mac round). Same box,
this time on the Windows PC with a **Rigol DG1022Z as an independent
calibrated source** — 1 kHz sine, 3.000 Vpp, high-Z load, into the LEFT
input only (RIGHT left unconnected, which turns it into a free
noise-floor channel). ESI's own Windows driver is installed; the machine
was on the physical console, not RDP.

This round closes three of the four U24 XL follow-ups queued in
`TODO.md` and opens four Windows-specific ones.

## 1. Absolute scale — confirmed against a real instrument

The Mac round's 0.07 dB agreement rested on an *assumption*: that
Apple's line-level output mode is exactly 1.000 Vrms. The Rigol removes
it.

| | value |
|---|---|
| Source (Rigol, 3.000 Vpp high-Z) | 1.06066 Vrms |
| Captured peak (WDM-KS, 48 kHz, 24-bit, 10 s) | 0.78800 FS |
| ⇒ full scale from peak | **1.9036 Vpk** |
| ⇒ full scale from tone RMS | 1.9063 Vpk |
| ESI spec, +4.7 dBu | 1.8819 Vpk |
| **Error vs spec** | **+0.10 dB** |
| Implied clip point | **3.81 Vpp** |

Tore's bench observation — 3 Vpp clean, the clip LED on by 4 Vpp —
independently brackets that 3.81 Vpp figure, and also confirms the Rigol
was genuinely set to a high-Z load (a 50 Ω setting would put the real
clip point at 7.6 Vpp).

Through the **whole pydvma path** with `VmaxSC` auto-derived from the
fixed-gain profile (1.8819 V, no stated gain):

```
pydvma capture       1.04679 Vrms vs 1.06066 commanded  -0.114 dB   @1 kHz
verify_input_scaling 1.0428 Vrms  vs 1.0607  expected   -0.15 dB    @1 kHz  PASS
verify_input_scaling 1.0459 Vrms  vs 1.0607  expected   -0.12 dB    @5 kHz  PASS
```

The 1 kHz and 5 kHz results agree to 0.01 dB, so the response is flat
across that span as well as correctly scaled.

Both are the same fact from the other end: pydvma scales by ESI's spec
(1.8819 V) while the box's true full scale is 1.9036 V, so it reads
0.10 dB low. **Well inside any sane tolerance — the profile is right.**

## 2. The Windows "input gain" is DIGITAL — measured, not assumed

Windows exposes the same control CoreAudio does, via
`IAudioEndpointVolume` on the *Line (U24XL with SPDIF I/O)* capture
endpoint: **−40 .. +12 dB, 0.5 dB step**, and it reports
`QueryHardwareSupport = 0x3` (volume + mute).

That flag is not a lie, but it is not the answer either, which is
exactly why this needed measuring: it means the *endpoint device* has a
volume register rather than the Windows engine doing the scaling — it
says nothing about whether that register sits before or after the
converter. Here it is in the codec (ESI's manual calls it the "I2S
input gain"), operating on samples that have already been digitised.
It is a hardware control and a digital one at the same time. The
consequence is what matters: it cannot buy SNR. The pin applies to
every host API including WDM-KS, confirming it lives in the driver
below the audio engine.

Fixed analogue tone, endpoint volume swept, WDM-KS 48 kHz:

| setting | tone dBFS | noise dBFS | **SNR** | ch1 (open) noise |
|---|---|---|---|---|
| 0 dB | −5.09 | −73.78 | **68.7** | −96.71 |
| −6 dB | −11.10 | −79.75 | **68.7** | −102.70 |
| −20 dB | −25.13 | −93.79 | **68.7** | −116.98 |
| −40 dB | −45.30 | −112.96 | **67.7** | −138.48 |
| +6 dB | −1.57 | −39.21 | 37.6 (clipped) | −90.72 |
| +12 dB | −1.06 | −32.99 | 31.9 (clipped) | −84.66 |
| 0 dB (return) | −5.09 | −73.86 | **68.8** | −96.73 |

**Signal and noise move together to within 0.03 dB over 20 dB of
attenuation — SNR is flat.** The gain is applied *after* the converter:
it is a pure multiply on captured data. The open-input channel settles
it beyond argument — ch1 has no source at all, yet its floor tracks the
setting exactly in *both* directions (−5.99, −20.27, +5.99, +12.05 dB).
An analogue gain ahead of the ADC could not move an unconnected
channel's converter noise at all.

So: **no, the software gain cannot buy SNR.** Turning it up only costs
headroom. Two practical consequences:

- The +6 and +12 dB rows are clipped *digitally* — the analogue signal
  was never near the rails (0.79 FS), but the post-ADC multiply pushed
  the samples past 1.0. THD goes −73.7 → −9.9 dB. Boost destroys data
  it cannot recover.
- **Slider trap:** scalar 0.6296 = 0 dB, scalar 1.0 = **+12 dB**. A user
  dragging the Windows recording slider to 100% adds 12 dB of digital
  boost and clips anything above −12 dBFS. 0 dB sits at 63% of travel.

The 1 dB SNR dip at −40 dB is the 24-bit floor appearing, not the gain
misbehaving (noise at −113 dBFS is closing on the LSB).

### The over-range test: it cannot pull a hot signal back into range

The sharpest form of the question — Tore's, mid-session: raise the
source above full scale and see whether the "gain" can rescue it. Rigol
to **5.000 Vpp** (2.5 Vpk = 1.31× full scale, 2.35 dB over):

| gain | peak FS | crest factor | THD | samples at peak |
|---|---|---|---|---|
| 0 dB | 1.00011 | **1.238** | **−19.4** | **45.1 %** |
| −3 dB | 0.70710 | **1.238** | **−19.4** | **45.1 %** |
| −6 dB | 0.50103 | **1.238** | **−19.4** | **45.2 %** |
| −12 dB | 0.25100 | **1.238** | **−19.3** | **45.4 %** |
| −20 dB | 0.09962 | **1.238** | **−19.3** | **45.4 %** |
| *(clean 3 Vpp)* | *0.788* | *1.414* | *−73.7* | *4.5 %* |

The level obeys the setting exactly; the **shape never changes**. Crest
factor is pinned at 1.238 against a sine's 1.414, 45 % of samples are
flat-topped, THD sits at −19.4 dB throughout. The waveform was
destroyed at the converter and the gain only shrinks the wreckage.

**The lab hazard:** at −20 dB it peaks at 10 % of full scale — which
reads as comfortably safe on any level meter — while still being 45 %
flat-topped. *Digital attenuation hides clipping from exactly the
indicator an operator would use to check for it.* Another reason to pin
the control at 0 dB rather than leave it to a slider.

### So what IS the input range? Two clip points, only one of them moves

Tore's follow-up, and the question that ties the section together:
does the gain change the acceptable input voltage? Rigol at 3.000 Vpp
(1.500 Vpk), endpoint gain swept across its whole range, WDM-KS 24-bit:

| gain | peak FS | predicted FS | crest | THD | |
|---|---|---|---|---|---|
| −20 dB | 0.07842 | 0.07880 | 1.416 | −74.0 | clean |
| −12 dB | 0.19768 | 0.19793 | 1.416 | −74.0 | clean |
| −6 dB | 0.39450 | 0.39493 | 1.416 | −74.0 | clean |
| 0 dB | 0.78771 | 0.78798 | 1.416 | −74.0 | clean |
| +2 dB | 0.99119 | 0.99201 | 1.416 | −74.0 | clean |
| +2.5 dB | 0.99159 | — | 1.416 | −74.0 | clean |
| **+3 dB** | 1.00000 | 1.11305 | **1.321** | **−29.7** | **CLIPPED** |
| +6 dB | 1.00002 | 1.57223 | 1.181 | −15.7 | CLIPPED |
| +12 dB | 1.00003 | 3.13701 | 1.077 | −10.8 | CLIPPED |

Level tracks the prediction to better than 0.05 % everywhere it is
clean, crest factor sits on √2 = 1.414 throughout, and clipping starts
between +2.5 and +3 dB against a predicted +2.07 dB from the measured
full scale. So:

- **The ANALOGUE clip point is FIXED at 3.81 Vpp (±1.9036 Vpk) and no
  software setting moves it.** That is the device's input range, full
  stop.
- **The DIGITAL clip point moves with the gain**: 3.81 Vpp × 10^(−G/20).
- **At 0 dB the two coincide** — the unique setting where digital full
  scale equals analogue full scale, which is exactly why pinning there
  is right. Above 0 dB the digital limit bites first and you LOSE usable
  range (at +12 dB you clip at ~0.96 Vpp, a quarter of the device's
  capability). Below 0 dB the range is unchanged but the meter
  under-reads, so hitting the analogue limit becomes invisible.

The gain therefore never *increases* the input range: at best it leaves
it alone, at worst it shrinks it, and below unity it hides the fact that
you have hit it. Which also settles the 5 Vpp case above from the other
direction — 2.5 Vpk is past the fixed analogue limit, so it is clipped
at EVERY setting, and the sweep that could not un-clip it was not going
to succeed at any gain.

Two footnotes. The claimed 0.5 dB step is not exactly honoured: +2.0 and
+2.5 dB both produced ~+2.00 dB of actual gain (0.99119 and 0.99159 FS).
And band-limited interpolation of the captured samples overshoots the
true peak by ~6 % here (5 kHz at 48 kHz is only 9.6 samples/cycle), so
the plain sample peak — which over ~5000 cycles of drifting sample phase
lands on the real peak anyway — is the trustworthy figure. The
interpolated column was dropped for that reason.

The one silver lining of the over-range case: because the shape
survives, the clipping is quantifiable. Inverting the crest factor of a symmetrically clipped
sine gives clip-level/amplitude = 0.7628, hence a source peak of
**2.496 Vpk = 4.99 Vpp** against the 5.00 Vpp commanded — 0.2 %. A
possible future "how over-range were you?" diagnostic, and here a
fourth independent confirmation of the 1.9036 Vpk full scale.

**Gap: pydvma does not pin this on Windows.** `Recorder.init_stream`
calls `_pin_hardware_clock` / `_pin_hardware_format` /
`_pin_input_volume`, but all three are `pydvma._coreaudio` and
`_coreaudio.available()` is `False` here. The macOS build protects the
fixed-gain `VmaxSC` derivation by forcing the volume to 0 dB per
capture; **on Windows nothing does**, so a stray slider silently
rescales every capture while `VmaxSC` keeps asserting 1.8819 V. See
TODO.

## 3. Sample rate — what is actually adjustable here

The four host APIs disagree, and each one disagrees usefully:

| host API | rates accepted | word delivered (float32 path) |
|---|---|---|
| **WASAPI exclusive** | **8000, 16000, 32000, 44100, 48000** | 16 bit (PortAudio negotiation) |
| WDM-KS | 44100, 48000 only | **24 bit** |
| WASAPI shared | 44100 only (the endpoint's Default Format) | 24 bit |
| MME / DirectSound | 8000 … 192000 — **all accepted, most fake** | **16 bit** |

**WASAPI exclusive reproduces the Mac's CoreAudio ladder exactly** —
8/16/32/44.1/48 kHz, the same five rates, including the low ones the
manual does not admit to. Exclusive mode does not resample (a format
the device cannot clock fails at `IAudioClient::Initialize`), so those
low rates are real here too. **WDM-KS refuses them outright**, which is
what an earlier probe in this session saw before WASAPI was tried —
hence a wrong note in the first draft of this document claiming the low
rates were macOS-only. They are not; they are *host-API*-only.

**The anti-alias filter tracks the rate here too** — confirmed with the
Rigol moved to 5 kHz, which is the test a 1 kHz tone cannot do (at
fs = 8000 every harmonic of 1 kHz aliases exactly onto another
harmonic, so folding is invisible):

| capture | 5 kHz vs Nyquist | content at the fold frequency |
|---|---|---|
| fs = 8000 (Nyquist 4 k) | out of band | 3 kHz is **75 dB down** — rejected |
| fs = 16000 (Nyquist 8 k) | in band | 5 kHz present at −0.1 dB |

75 dB is a floor, not a ceiling: the chain already carries −82.6 dB of
3 kHz distortion residue at full bandwidth, so the measurement is
limited by the source, not the filter. Either way nothing folded.

The awkward consequence: **no single Windows host API is best at
everything.** WASAPI exclusive has the rate ladder, WDM-KS has the
24-bit word. Both refuse to lie, which is the property that matters
most.

Also: **Windows shared mode fixes the converter rate**, not pydvma. The
endpoint's Default Format is currently 44100 Hz / 24-bit (registry
`PKEY_AudioEngine_DeviceFormat`). Change it in Sound → Recording →
Line (U24XL) → Advanced, or bypass it with an exclusive host API.

### The MME/DirectSound rates are fiction, and here is the proof

Asking MME for a rate the hardware cannot run returns data anyway.
Open-input noise, per 2 kHz band, dBFS:

```
MME  96000:  ... 18k:-102.6  20k:-105.4  22k:-110.1  24k:-110.1 ... 46k:-110.1
MME 192000:  ... 18k:-103.0  20k:-106.1  22k:-113.1  24k:-113.2 ... 94k:-113.1
WDM-KS 48000: ... 18k:-108.8  20k:-108.7  22k:-109.8            (flat to Nyquist)
```

Everything above **22 kHz** — the 44.1 kHz endpoint's Nyquist — is a
*perfectly constant* floor: −110.1 dB in every single band to 48 kHz,
−113.1 dB in every single band to 96 kHz. Real converter noise is never
that flat. And the two levels differ by exactly **−3.0 dB for 2× the
rate**, which is the signature of a fixed dither power spread over a
wider band. There is no information up there at all.

The same step appears at 48 kHz (`20k:-104.2  22k:-107.0` against a
−101.8 plateau), so **even a plain `fs=48000` MME capture is resampled
from 44.1 kHz.**

**Bug: `streams.max_input_fs` reports 192000 for the MME and
DirectSound endpoints** (48000 for WASAPI/WDM-KS, correctly). This is
the exact trap `native_input_rates` was written to close on macOS —
`sd.check_input_settings` is not a capability probe — but that function
returns `[]` on Windows, so nothing catches it. It matters because
**pydvma's default input device on this machine IS the MME endpoint**
(`sd.default.device[0]` = 1), so the digital-LPF oversample path would
ask for a 192 kHz capture and get 44.1 kHz of signal in a 192 kHz
wrapper. See TODO.

## 4. Noise floor — the box alone, at last

The Mac round could only offer −79 dBFS *including the Mac's headphone
amp*. Here the unconnected right channel gives the box on its own
(WDM-KS, 24-bit, gain 0 dB, 6 s):

| | 20 Hz–20 kHz | 10–3800 Hz |
|---|---|---|
| 48 kHz | **−96.1 dBFS** | −98.7 dBFS |
| 44.1 kHz | −92.4 dBFS | −97.0 dBFS |

So the U24 XL is roughly **16–17 dB quieter than the Mac bench could
see** — about 15.5–16 effective bits of dynamic range, not the ~12.8
that round reported. That figure was the Mac's amp, not the ADC.

Two incidental findings:

- **48 kHz is ~3.7 dB quieter in-band than 44.1 kHz** (−96.1 vs
  −92.4 dBFS). Prefer 48 k.
- **The Rigol dominates when connected**: the driven channel floors at
  −73.8 dBFS against the open channel's −96.7 dBFS — the generator's own
  output noise is 23 dB above the converter's. Any THD/SNR number taken
  through the DG1022Z at 3 Vpp is a *lower bound* on the U24 XL.

Mains pickup is negligible: 50 Hz at −97 dBc, worst harmonic 150 Hz at
−86 dBc, on an unbalanced RCA/TS run to a mains-powered generator. No
ground-loop problem on this bench.

## 5. Device identity

- **The Windows enumeration name carries the model**:
  `Line (U24XL with SPDIF I/O)`. The existing profile match
  (`'u24xl'`/`'u24 xl'`) resolves **directly** on all four host APIs —
  no WDM-KS product-id token needed, unlike the Scarlett 2i2. MME
  truncates the S/PDIF endpoint to `SPDIF Interface (U24XL with SPD`,
  which still matches. `fixed_gain` → `True`, `VmaxSC` → 1.8819 V
  everywhere.
- **`device_index` is NOT stable on Windows.** The WDM-KS block
  reordered between two enumerations minutes apart with no hardware
  change and no change in device count (38 both times): the U24 XL Line
  input moved from index 36 to index 27, and an earlier resolution of
  index 23 returned a Realtek endpoint. Anything that stores a device
  index — `MySettings`, a saved `.dvma`, a `--settings` file — can point
  at the wrong hardware on the next run, and with profile-derived
  `VmaxSC` that means the wrong voltage scale too. Resolve by name.

## Verdict

The U24 XL works correctly through pydvma on Windows, to 0.15 dB
absolute against an independent source, with the profile and fixed-gain
`VmaxSC` derivation resolving unaided. It is a better converter than the
Mac round could measure. The Windows-specific risks are all in the
platform layer, not the box: an unpinned digital gain, a lying rate
probe on the default host API, a 16-bit default path, and unstable
device indices.
