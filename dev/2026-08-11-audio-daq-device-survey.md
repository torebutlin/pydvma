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
  Best-fit 2-channel fixed-gain station box, pending bench
  characterisation (no published ADC measurements either).
- **Above 2 channels the fixed-gain category is EMPTY** (≤£300):
  everything multichannel grows adjustable gain, is output-only
  (Gigaport HD+), or needs a £700+ ADAT converter with its own gain
  menus. Multiple stereo boxes canNOT be stacked: independent USB
  clocks drift — stereo per box is a physics ceiling. Multichannel
  fixed-gain ⇒ the XR18 with gain pinned by script.

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
