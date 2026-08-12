# Audio-as-DAQ device survey (2026-08-11)

Context: the Scarlett 2i2 4th Gen's input gain cannot be set in
software (FC2's AES70 API is pairing-gated; macOS `usbaudiod` owns the
USB interface — see `dev/plans/2026-08-10-focusrite-scarlett-design.md`
and TODO's "gain control is a dead end"). Survey of alternatives with
software-settable gain, then of the inverse concept: fixed-gain
line-level capture ("nothing to mis-set"). Three web-research rounds,
2026-08-11; prices are that day's UK retail, verify before purchase.

## Software-settable gain — verified options

| Family | Entry | Control path | Notes |
|---|---|---|---|
| **RME** (Babyface Pro FS £629 → UCX II £1,079 → UFX III/12Mic) | 2-in | TotalMix FX **OSC** (RME-published chart; third-party plugins confirm settable Gain 0–65 dB) — `python-osc`; TotalMix must run on the host | Fully digital preamps, no pots anywhere in the line; best converters/drivers; the buy-once option |
| **MOTU AVB** (8A ~£900?, 16A 2025 £1,525) | 8-in | Device-hosted **HTTP/JSON Datastore API** (`POST /datastore/ext/ibank/0/ch/0/trim`) — `requests`, no vendor app at runtime, OS-independent | TRAP: UltraLite-mk5 does NOT have the API (AVB generation only). Has front-panel knobs (API-writable) |
| **Behringer XR18 £315–349 / Midas MR18 ~£586** | 16 preamps, 18×18 USB | Device-hosted **OSC** over WiFi/Ethernet; maintained `xair-api` PyPI package exposes HeadAmp gain (−12..+60 dB) | ZERO physical controls (stagebox format — reads as instrumentation, not audio gear); 48 kHz ceiling; 114 dB A/D; line ins +16 dBu (+23 dBu combo); gain-by-script ≈ fixed-by-policy. £315 Andertons price may be EOL clearance — check |
| **Behringer Flow 8 £144** | 10-in/2-out USB | Documented **MIDI CC** with dB formula (CC=(dB+20)·127/80, −20..+60 dB) — `mido`, class-compliant | Has physical faders (looks like a tiny mixing desk — wrong affordance for a lab bench) |

Ruled out: **Audient EVO** (perfect shape — £91 2i2o, dial-free, family
to 16ch — but control is reverse-engineered vendor-USB needing kernel-
driver detach; Linux-only in practice, no macOS route, Windows needs
Zadig surgery: same disease as Focusrite); **Behringer UMC** (analogue
knobs only, no software path — fine as dumb capture boxes); PreSonus /
Tascam / Zoom / Steinberg sub-£400 (no documented APIs).

## Fixed-gain line-level capture (nothing to mis-set)

- **Behringer UCA202/UCA222 (£17)** — 16-bit/48 kHz, clip 2 dBV
  ≈ 1.26 V rms, 27 kΩ in, RCA. Genuinely zero gain anywhere. ADC-side
  quality NEVER publicly measured (NwAvGuy did the DAC only; expect
  ~14–15 effective bits). External conditioning must size signals to
  the 1.26 V rms window (resistive divider in the cable keeps the
  no-settings property).
- **ESI U24 XL (£63)** — the 24-bit sibling concept, still 48 kHz,
  TRS/RCA line I/O, **no knobs (confirmed first-hand — Tore owns one)**.
  Best-fit 2-channel fixed-gain station box. **Bench-characterised
  2026-08-11** (`dev/2026-08-11-u24xl-bench.md`): +4.7 dBu fixed full
  scale confirmed to 0.07 dB, native 8k–48k ladder with the anti-alias
  filter tracking fs (69–76 dB rejection), ~12.8 effective bits
  wideband / ~15.3 at 8 kHz, clocks at −0.3 ppm. Its ONE settable
  hazard (a hidden ±dB *digital* input volume, plus macOS parking it
  at 16-bit) is now pinned by pydvma per capture; profile +
  `dev/u24xl_hw_check.py` landed same day, 13/13.
- **Above 2 channels the fixed-gain category is NEARLY empty** (≤£300)
  — revised by the ESI family sweep below: everything multichannel
  grows adjustable gain, is output-only (Gigaport HD+/eX), or needs a
  £700+ ADAT converter with its own gain menus. Multiple stereo boxes
  canNOT be stacked **over USB**: independent clocks drift — stereo
  per box is a physics ceiling *for that bus*. Dante/AoIP boxes are
  the exception (shared PTP leader clock across the network — see
  planet 22c below). Multichannel fixed-gain ⇒ the XR18 with gain
  pinned by script, stacked planet 22c units, or (with old-converter
  caveats) the Maya 44 USB+.

## ESI family sweep (2026-08-11, Thomann UK prices)

Prompted by Thomann's ESI category page; specs from ESI product pages
and manuals. Vendor DR figures are dB(A) — only the U24 XL numbers are
our own unweighted measurements.

| Model | £ | Analog in | Gain architecture | DAQ verdict |
|---|---|---|---|---|
| **U24 XL** | 63 | 2× TS line | none (digital vol, pinned by pydvma) | characterised incumbent |
| **planet 22c** | 159 | 2× bal TRS | **no knob** — 2-position range switch (−10 dBV/+4 dBu; max +6 dBV/+20 dBu) | **the sleeper** — Dante+PoE, 110 dB(A) in; ESI's manual: "ideal for audio measurement purposes" |
| Maya 44 USB+ | 81 | 4× RCA line | **none at all** | single-box 4-ch fixed-gain — but USB 1.1, 48 k, 18-bit-era ADC; bench before trusting |
| Juli@ eX | 166 | 2× line (−10 dBV RCA / +4 dBu TRS by physical PCB swap) | no pots | 125 dB(A) ADC, measurement-grade — but PCIe + Windows-only |
| MAYA44 eX | ~103 | 4× fixed line + mic/inst | line fixed, mic preamp adjustable | PCIe, Windows-only |
| UGM192 | 40 | 1 mic (stepped) + 1 inst (fixed) | inst fixed but FS −8.4 dBu ≈ 0.29 Vrms | oddball; tiny full scale |
| Neva Uno/Duo/OTG, Amber i1/i2/i4, planet 22x | 47–245 | various | physical gain knobs | out of category |
| Gigaport eX | 122 | none (8× RCA OUT) | n/a | possible 8-ch stimulus fan-out |

**planet 22c is the notable find**: fixed-gain in each of two
documented range positions, balanced, PoE-powered, and because it is
Dante, N boxes share one network clock — 2N phase-coherent channels at
~£80/channel with nothing to mis-set.

planet 22c practicalities (plain-language, discussed with Tore
2026-08-11):

- **It is NOT a USB device** — Thomann's category lumps it in, but its
  only data connection is Ethernet. Dante = audio-over-Ethernet with
  network-distributed clock sync (PTP, same family as IEEE 1588 in
  distributed NI/PXI systems). The computer joins via Dante Virtual
  Soundcard (~£40 one-off per machine), which presents an ordinary
  CoreAudio/WASAPI multichannel device — pydvma would see it as a
  normal soundcard.
- **The 2-position switch is a RANGE switch, not a gain knob**: max
  +6 dBV ≈ ±2.8 Vpk (sensitive) or +20 dBu ≈ ±11 Vpk (high-level).
  Two discrete documented states map straight onto the profile
  schema's per-mode `max_input_dbu`, fixed-gain in each — the 2i2
  line/inst machinery without the unknowable knob.
- **Power/connectivity**: a USB→Ethernet adapter on a laptop carries
  DATA only — PoE power comes from a PoE switch or a ~£12 inline
  injector, or use the box's 12 V DC jack. Single-box bench trial =
  laptop + USB-C→Ethernet adapter + direct cable + 12 V supply.
  Multi-box = one small PoE gigabit switch (~£40) powers and connects
  everything.
- **The USB stereo-per-box ceiling does not apply**: USB boxes drift
  on independent crystals (meaningless cross-box phase); Dante boxes
  slave to one elected leader clock, so channels on different boxes
  stay sample-locked. Microsecond-class alignment (a fraction of a
  degree at 1 kHz) is inferred from Dante's sync spec, NOT
  vendor-promised for this box — a two-box cross-spectrum bench is
  the decision gate before any 3C6-scale commitment, alongside a
  noise-floor/absolute-scale session like the U24 XL's.
- **Two deployment shapes, same hardware** (clarified with Tore
  2026-08-11): *Shape A, six independent stations* — one box per PC,
  DIRECT Ethernet cable (no switch anywhere), 12 V supply or £12
  injector; rigs fully isolated, each PC sees its own 2-ch device.
  Tore: Shape A is the 3C6 shape. *Shape B, pooled multichannel* —
  several boxes + ONE PC on one PoE switch when a single measurement
  needs >2 coherent channels; of interest for RESEARCH rigs, not 3C6.
  The same six station boxes can be pooled into a 12-ch coherent rig
  for the price of one switch — six U24 XLs can never do that. Cost
  honesty: DVS is licensed per PC, so Shape A costs ~£210/station
  (£159 + ~£40 licence + ~£12 adapter) vs the U24 XL's £63 all-in;
  the premium buys balanced inputs, two documented ranges, the better
  converter path, and the pooling option.
- **Campus-network coexistence (Shape A)**: station PCs are already
  on the university LAN — do NOT put the Dante boxes there. Give each
  PC a second, dedicated "DAQ port" (a ~£12 USB→gigabit-Ethernet
  adapter), one cable straight to the box; the built-in port stays on
  campus. No IP setup — a DHCP-less direct link falls back to
  link-local addressing, which Dante is designed for. Pin DVS to that
  interface (it has a picker); route the box's channels once in the
  free Dante Controller (config persists in the device). Rationale:
  managed campus networks block/jitter the multicast+PTP Dante needs,
  and six boxes on one LAN would DISCOVER each other, elect a single
  shared leader clock and let any station re-patch any other —
  isolation comes from each box living on its own two-node link.
  (Same pattern as private point-to-point links for Ethernet NI cDAQ
  chassis.)
- PCIe options (Juli@ eX, MAYA44 eX) dropped from consideration —
  the point is escaping the old NI PCI estate, not adding new
  internal cards (Tore, 2026-08-11).

## AoIP endpoint class sweep (2026-08-12)

Question from Tore: does Dante open another device class worth
looking at? Answer: the class exists ("AoIP endpoints") but **the
planet 22c is its value outlier** — nothing certified comes close at
lab prices. The class is priced for the commercial-install/broadcast
market. Web-researched 2026-08-12; prices are that day's snapshot.

| Tier | Examples | 2i2o cost | Gain architecture |
|---|---|---|---|
| Value outlier | **ESI planet 22c** | **£159 single box** | fixed 2-position range switch |
| Audinate own-brand | AVIO analog in + out adapter pair | ~£430/pair | **software-stepped ranges** via Dante Controller (+24/+4/0 dBu, 0 dBV, −10 dBV) — DAQ-like, but 2.7× the 22c |
| Certified pro | Neutrik NA-2I2O-DLINE (~£310–370), Shure ANI22 (~£540), Radial DAN-TX2/RX2 (~£920/pair), Attero unDIO2x2 (POA, est. £450+) | £310–920 | software (browser/Dante Controller) |
| Grey-market OEM | ToVi/OREI DXA-A2 pair (~£220), J-Tech DA2EX/DX pair (~£260), MAXSQUARE (~£377) | £220–380 | physical DIP/level switches; claim Dante Ultimo silicon but NOT in Audinate's certified device catalogue |

Cross-ecosystem: **AES67-only budget hardware is a dead end** (one
€99 hobbyist unit with reported dropout bugs); **AVB never grew a
budget tier** (MOTU AVB line from ~$850). At lab prices it is Dante
or nothing.

Host-side precision (corrects the ~£40 estimates above): **DVS is
£45**/machine perpetual non-transferable (£85 transferable), rates
44.1–192 k with channel count dropping at high rates. TRAP: the
cheaper "Dante Via" product is locked to 48 kHz — avoid. Sample rate
is genuinely software-settable per device (Dante Controller); devices
must share a rate to route to the same capture. Potentially
interesting FREE host route: Dante devices have an AES67 mode and
PipeWire ≥ 1.1 claims verified Dante interop on Linux — UNVERIFIED by
us, but would delete the per-PC licence if stations were ever Linux
boxes; one bench afternoon would settle it.

Sweep verdict: the only things money buys above the 22c are
software range-switching (AVIO pair, +£270) or preamp-grade remote
gain (Shure/RedNet tier, £500+/box). Below it, only grey-market boxes
with physical switches and unverified certification (~£60 saved).
The 22c + £45 DVS stands as the deal in the certified class.

## Multichannel tier: Dante vs USB at 8/16/32 ch (2026-08-12)

Tore's question: does Dante earn its keep at research channel counts
(8/16/32), hundreds-not-thousands budget? **Verdict: never on
£/channel — only when the GEOMETRY earns it** (distributed sensors, or
multi-box/multi-PC phase-coherent scaling). Researched Thomann UK
prices, snapshot 2026-08-12:

| ch | Best USB (co-located) | Best Dante route |
|---|---|---|
| 8 | XR18 £315 | 4× planet 22c ≈ £710 all-in (£89/ch) |
| 16 | **XR18 £315 (£20/ch)** | 8× 22c ≈ £1,360; cheapest certified single box = Yamaha Tio1608-D2 £1,525 (£95/ch) |
| 32 | **full-size X32 £1,299 (£41/ch)** — 32 XLR in, software gain, 32×32 USB standard | X32 + X-Dante card £1,567, or 16× 22c £2,640 |

Findings: (a) purpose-built multichannel Dante is absurd vs stacking —
cheapest certified 8-in box is £1,181 (Sonifex AVN-AIO8, gain arch
unverified); grey-market OEM Dante caps at 4 ch, uncertified; one £45
DVS licence covers 64×64 so stacking never needs the Pro tier.
(b) CORRECTIONS: X32 Rack (£666) / Producer (£799) have only 16
physical XLR ins — the 32-in unit is the full-size X32 console; X32
Core is discontinued; XR18/MR18 have NO Dante or AES50 path (Dante Via
over USB is not a network node); KT DN9630 is AES50→USB not Dante
("DN9632" doesn't exist; the real bridge, DN9650 + KT-DANTE64, is
quote-only broadcast kit). Behringer SD/DL stageboxes are AES50-only.
(c) Midas variants cost ~£440 more for the same channel counts (M32R
Live £1,739 + DN32-Dante £295). WING Rack £1,169 + WING-DANTE £439 —
input count unverified.
(d) When Dante DOES earn it: sensors spread over a large structure
(digitise at the sensor, one Cat5/PoE run each, 100 m/hop, no long
analogue cables) and incremental growth/pooling (2 ch at a time,
Shape A stations ↔ Shape B array). At 8 ch that costs ~£710 (within
"hundreds"); at 16 ch the distribution argument must be real to
justify £1,360 vs £315.

## Input-range comparison (2026-08-12)

Tore: if the U24 XL's dealbreaker is its input voltage range (fixed
±1.9 Vpk), what are the options? By maximum line input:

| Option | Max line input | Range mechanism | Cost |
|---|---|---|---|
| U24 XL as-is | ±1.9 Vpk | none | owned |
| U24 XL + 10:1 passive divider | ±19 Vpk | fixed, in-cable, absorbed as `cal_factor` | pennies + a bench session |
| 2i2 4th gen @ min gain | ±13.8 Vpk (+22 dBu) | knob END STOP — the one repeatable dial position; stated-gain workflow for other ranges (9 dB ≈ ±4.9 V, NI-like, hw-confirmed 0.10 dB) | owned |
| planet 22c | ±2.8 / ±11 Vpk | 2-position physical switch | £159 + £45 DVS |
| XR18 | ±6.9 Vpk line (±15.5 combo) | software gain, 1 dB steps, script-pinnable | £315, 16 ch |

Notes: (a) the 2i2 has NO attenuation — gain is 0..+69 dB, but its
minimum-gain baseline is already ±13.8 V; (b) **no budget USB
interface with a pot-free physical range switch appears to exist** —
the market splits into knobless consumer boxes (small fixed ranges)
and continuous-pot music interfaces (pads only ever accompany pots);
the discrete-range pattern lives in AoIP/install gear and
instrumentation; (c) the divider trick (already noted for the UCA222)
applies to any fixed-range box: trades switchability and input
impedance for zero settings.

**Off-the-shelf divider = the inline attenuator pad** (2026-08-12, to
save technician time): passive resistive XLR-barrel pads, many with a
discrete −10/−20/−30 dB switch — Hosa ATT-448 (~£17, −20/−30/−40),
Audio-Technica AT8202 (~£30, −10/−20/−30), Shure A15AS (~£50,
−15/−20/−25), fixed Sescom/Whirlwind barrels (~£15–25). Plus an
XLR→TS adapter per channel for the U24 XL. Caveats: the labelled dB
assumes pro-audio impedances — the realised ratio into a ~10 kΩ
unbalanced input differs, so characterise in situ once (fixed
resistors: it then never moves) and store as `cal_factor`; stay
RESISTIVE — transformer DI/iso boxes roll off and distort at low
frequency, exactly where vibration lives; size the step to the signal
(±5 V conditioner → U24 wants −10 dB ⇒ ≈±6 V full scale; −20 dB
donates ~2 bits of range). U24 XL + −10 dB pad ≈ a ±6 V fixed-gain
station for ~£80 all-in with nothing continuously adjustable in the
chain.

Worked example of the impedance caveat (2026-08-12, Tore's find —
CPC Pro Signal PSG02971 "−10 dB" XLR barrel, ~£6): its datasheet
publishes the network (312 Ω per leg, 422 Ω shunt; −10 dB assumes
BALANCED 600 Ω both ends). In the real chain — unbalanced adapters
short one leg, U24 XL load ≈10 kΩ — it realises 312 Ω into
(422∥10k) ≈ 0.56 = **−5 dB only**: FS ≈ ±3.4 Vpk, still clipped by
±5 V conditioners. Verdict: right category, wrong step — buy the
−20 dB sibling **PSG02973 (CPC AV17579)**, expected ≈ −13..−15 dB
realised ⇒ FS ≈ ±8–11 Vpk; measure the actual ratio in situ →
`cal_factor`. Per channel: pad + XLR-male source cable +
XLR-female→TS adapter, <£15, no fabrication.

## Conclusions (as discussed with Tore)

- **3C6-scale (2-in/2-out stations):** the owned ESI U24 XL is the
  candidate; UCA222 the £17 fallback. Characterise on the bench first —
  `dvma.verify_input_scaling` with the Rigol DG1022Z as known source
  (absolute scaling + clip), plus a noise-floor capture for effective
  bits. Both tools exist as of v2.1.0+.
- **Higher channel counts:** XR18 (or MR18) — software-settable
  (`xair-api`), no physical controls, instrumentation-looking.
- **No-compromise:** RME (OSC), if budget ever ceases to be the point.
- All of these are per-channel delta-sigma with inherent anti-alias
  filtering, same mechanism as the 2i2/9234.

## Recommended lineup (agreed with Tore, 2026-08-11)

Ladder: **ESI U24 XL** (owned; fixed-gain 3C6-scale stations, pending
bench characterisation — likely better than UCA222 on its 24-bit
dynamic range; both ADCs publicly unmeasured) → **Scarlett 2i2 4th gen**
(adjustable bench box: best fs/converters of the cheap tier; gain NOT
software-settable — FC2 pairing-gated, confirmed on macOS AND Windows —
but pydvma's stated-gain workflow, Setup level check and
verify_input_scaling manage the knob risk) → **Behringer XR18** (16
synced channels, £315–349, zero physical controls, gain pinned by
script via the maintained `xair-api` package). **UCA222** (£17,
16-bit) as disposable spares where dynamic range doesn't matter.
**Flow 8** ranked below the 2i2 for labs despite its documented MIDI-CC
gain: physical faders are exactly the wrong affordance. **RME Babyface
Pro FS / MOTU 8A** remain the buy-once tier.

Cross-cutting: everything but the 2i2/RME/MOTU is capped at 48 kHz
(planet 22c reaches 96 k); channel counts never stack across USB boxes
(unsynchronised clocks) — past 2 synced channels the budget routes are
the XR18 or stacked Dante boxes (planet 22c, shared PTP clock — see
the ESI family sweep section).
