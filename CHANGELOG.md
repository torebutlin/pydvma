# Changelog

All notable changes to pydvma are documented here. This project
follows [semantic versioning](https://semver.org/).

## 2.3.0 — 2026-08-12

Makes the sound card a device you can *name* rather than index, and
says plainly whether its readings are volts. Adds the first fixed-gain
interface profile (ESI U24 XL), characterised on both macOS and
Windows.

### Added

- **Device discovery** — `dvma.list_available_devices()` and
  `pydvma-serve --list-devices`. One block per *physical* device rather
  than one line per enumeration slot: backends ranked with the
  recommended one marked, the hardware's rate ladder shown separately
  from what each backend actually **delivers**, and an explicit
  calibration status — **CHARACTERISED** (full scale known, `VmaxSC`
  derived, readings are volts), **NEEDS GAIN** (model known, analogue
  gain must be stated), or **uncalibrated** (`VmaxSC=1.0` is a
  placeholder and readings are full-scale units). An assumed voltage
  scale can no longer pass for a measured one.
- **Select a device by name** — `MySettings(device='U24XL')` resolves a
  name substring and picks the backend that can deliver the requested
  sample rate, reporting the reason. It refuses to guess between two
  real devices. Resolution falls back to the device table's profile
  label when the raw driver name misses, so `device='ESI U24 XL'`
  works on macOS *and* Windows even though the same box enumerates as
  `U24XL with SPDIF I/O` on one and `Line (U24XL with SPDIF I/O)` on
  the other.
- **ESI U24 XL profile** — the first *fixed-gain* interface in the
  device table. Full scale is constant, so `VmaxSC` is derived with no
  gain to state and Setup drops the gain field. Characterised against a
  calibrated generator: measured full scale agrees with the published
  +4.7 dBu to 0.1 dB.
- **Windows endpoint-volume pinning** (`_win_audio.py`) — the
  counterpart to `_coreaudio.py`, so a stray OS-level input volume
  cannot silently rescale a capture.

### Changed

- **Device identity is (name, host API), not an enumeration index.**
  Indices reorder on Windows as backends appear and disappear — the
  same U24 XL moved from 36 to 27 with no hardware change. The Python
  and CLI paths now get the same protection the bridge had.
- `native_input_rates` answers on Windows as well as macOS, and the
  device's true maximum rate propagates to the Setup sample-rate list.
- Setup shows one row per device with an "all backends" control and the
  calibration line; the input dropdown lists only capture endpoints
  (38 rows → 11 on the Windows test bench).

### Fixed

- **macOS silently parked the U24 XL at 16 bits** and reset that on
  every rate change, and its "input gain" is a hidden digital volume.
  Both are now pinned per capture and restored on close, as the clock
  already was.

## 2.2.0 — 2026-08-11

Supersedes 2.1.0 on PyPI (2.1.0 was tagged but never uploaded): adds
the input-scaling verification tool and the Windows/NI hardware-
verification round's fixes.

### Added

- **`verify_input_scaling`** — absolute input-chain verification
  against a source of known level: `source='loopback'` plays a known
  tone through the device's own AO (absolute on NI's calibrated AO→AI
  path; chain-consistency on a sound card), or pass a
  **`RigolDG1022Z`** instance (new SCPI wrapper, pyvisa) to command an
  external calibrated generator — the only way to verify a sound card
  whose loopback is digital. Robust windowed-periodogram tone
  estimation; per-channel PASS/FAIL table.

### Changed

- **BLA commanded-drive mode is disabled on all paths.** Hardware
  measurement (USB-6212, routed AI sample clock) showed the AO start
  offset is random per capture even on shared-clock devices, so an
  analytic commanded reference would corrupt the noise/nonlinearity
  separation. Measured-x — the default, and the method's own
  recommendation — is the sole mode; the UI explains why.
- The 9234's oversample default ('lowest') is hardware-confirmed:
  alias rejection holds and the in-band noise cost is +3.0 dB.

### Fixed

- Scarlett 2i2 device-profile resolution on Windows (WDM-KS sibling
  naming), so the loopback-channel warning, gain-derived calibrated
  volts and serve capabilities now work there too (calibration
  re-confirmed on Windows to −0.108 dB).

## 2.1.0 — 2026-08-11

A month of lab-testing feedback rounds plus two feature arcs: sound-
card capture-rate correctness (Focusrite Scarlett class) and the
headline **noise/nonlinearity separation (Schoukens BLA)** workflow.
No breaking changes.

### Added

- **Nonlin stage (web logger): Schoukens BLA noise/nonlinearity
  separation.** Design a seeded random-phase multisine (band, Δf shown
  as samples *and* seconds, RMS level, M realisations × P periods +
  transient periods), run M×n orthogonal experiments on any
  acquisition path (browser audio, `pydvma-serve` soundcard or NI),
  and get one Best-Linear-Approximation FRF per excitation with
  `bla_sigma_nl` / `bla_sigma_n` overlays on the TF view and per-band
  verdict lines. SISO and MISO share one n×n solve (non-square
  response counts are first-class); the drive is a measured input
  channel by default, with commanded-drive mode on provably
  shared-clock NI devices. Python API: `multisine_generator`,
  `calculate_bla`, `create_test_bla_captures`; everything round-trips
  `.dvma`. Docs: *Web Logger → Noise & nonlinearity separation*.
- **Frequency navigator** on all frequency-axis views: progressive
  scope ribbon, client-side peak stepping ‹ ›, fitted-mode ticks.
- **Logging digital low-pass** (Setup full): capture oversampled at
  the device max and resample down with a zero-phase Kaiser FIR;
  **Time-view Resample tool** (anti-alias down / band-limited up).
- **Interactive damping panel**: restored Qt decay-fit plot with
  draggable threshold/start lines, plus band decay analysis
  (Butterworth ladder + Schroeder EDC → EDT/T20/T30/T60/band-Q).
- **CWT wavelet-Q slider** with voices/octave auto ladder; sonogram
  log-y and dB|lin heat toggles.
- **Setup gain-derived volts + level check** (soundcard): state the
  interface gain (`input_gain_db`, `input_mode`) and captures scale to
  real volts (verified to 0.1 dB on a Scarlett 2i2); the live monitor
  reports per-channel peak/RMS in volts and says which way to turn the
  knob.
- **Load Data appends** to an existing dataset (the old logger's "Add
  on load"); error toasts pin open until dismissed.
- Modal-fit upgrades: variable-projection **Refine**, linear re-solve
  of global constants, per-mode phase-significance ⚠, divergence
  warning with Undo; fits follow the visible line selection.

### Changed

- **Soundcard captures run at rates the hardware can actually
  produce**: pydvma reads the device's real rate ladder (CoreAudio),
  pins the hardware clock, and captures at a native rate before its
  own anti-alias decimation — `check_input_settings` optimism no
  longer silently varies the alias rejection. Delta-sigma devices
  (9234, audio interfaces) default to the lowest adequate native rate;
  unfiltered NI multiplexers (6003/6212) keep capturing at the device
  max.
- Devices are followed **by name, not enumeration index**, when
  PortAudio re-orders the device list mid-session (the bridge
  re-resolves and reports; a vanished device refuses rather than
  recording the wrong input).
- Legends and coherence export with figures per their toggles; every
  damping chart saves as its own PNG; Bode exports composite both
  panes.

### Fixed

- JW-logger V2.9a `.mat` time-file import (no-`npts` layout) and
  coherence columns importing as fake TF channels.
- Multiplexed NI aggregate-rate division (`max_input_fs`), AO
  shared-clock mis-rating with `lpf_on`, `resample_to_fs` missing
  exact ratios for coerced capture rates, bridge output defaults
  sending a DC pulse, a soundcard stream leak on reconfigure, and an
  AO-rate clamp for AO-limited devices (6003).
- Security: dompurify and postcss/nanoid lockfile bumps (Dependabot);
  `npm audit` clean.

## 2.0.0 — 2026-07-08

First release since the browser-based **web logger** replaced the
removed Qt desktop GUI. Because the desktop `Logger`/`Oscilloscope`
API is gone, this is a breaking change and warrants the major bump.
PyPI remains the package channel (`pip install pydvma`); GitHub Pages
serves only the hosted app and documentation.

### Breaking

- **The Qt desktop GUI has been removed.** `pydvma/gui.py` and the
  orphaned `oscilloscope.py` / `logger_tester.py` are deleted along
  with the Qt-only tests.
- **The `[qt]` extra is gone.** `pip install pydvma[qt]` now errors on
  an unknown extra — the honest signal that the desktop GUI is retired.
  Use `pip install pydvma[serve]` + `pydvma-serve` instead.
- **`dvma.Logger` and `dvma.Oscilloscope` now raise an actionable
  tombstone** on access, pointing at the web logger and the migration
  docs.
- The last version that shipped the Qt GUI is the **`qt-final`** git
  tag — revert there if the desktop logger is ever needed.

### Added — the web logger

- **Three ways to run it:**
  - **Pages app** (no install) — analysis + Web Audio soundcard
    acquisition in the browser, at
    <https://torebutlin.github.io/pydvma/app/>.
  - **`pydvma-serve` local bridge** — `pip install pydvma[serve]`
    then `pydvma-serve` serves the wheel-embedded UI and bridges to
    local hardware. Drivers: `mock`, `soundcard`, `nidaqmx`.
    NI acquisition is hardware-verified (multi-channel capture,
    sample-exact pretrigger, output stimulus sweep).
  - **JupyterLite** — the analysis core running under Pyodide.
- **Acquisition:** basic/full Setup, capability-clamped NI options
  (IEPE, terminal config, sample-rate ladders, voltage rails),
  armed pretrigger with editable sample count (browser and bridge),
  output stimulus generator (`signal_generator` parity), persistent
  mini-oscilloscope and a Live scope (FFT / Welch PSD).
- **Analysis:** FFT, PSD, cross-spectrum pair (E[X*Y]),
  transfer function + coherence, Clean Impulse; sonogram via STFT
  **and CWT** (dependency-free Morlet) with damping fits;
  unit-aware axes and live recompute.
- **Modal fitting:** Fit 1/2/3, **multi-set shared poles**
  (joint `TfDataList` fit), Reject, **Refine** (auto-revert),
  per-mode mute/delete/undo; fits render as tray cards and persist in
  `.dvma` as Python-readable `ModalData`.
- **Scaling:** **Best Match** (via calibration factors) plus a
  non-destructive **x(iω)^p display transform**; calibration dialog
  (sensitivity + units).
- **Export:** `.dvma`, MATLAB `.mat`, CSV (parity with the file API),
  and theme-invariant PNG/PDF figures.
- **UI:** hover-expand axis toolbar with undo/redo history,
  draggable Nyquist/Bode/coherence axis navigation, and a no-flash
  **dark theme** toggle.
- Legacy files continue to load (2019 pre-list pickles are
  normalised; derived kinds seed views; orphan-TF convention).

### Documentation

- A full **Web Logger** section is published on the docs site,
  including a migration guide from the retired Qt GUI:
  <https://torebutlin.github.io/pydvma/web-logger/>

## 1.5.0 and earlier

Pre-2.0.0 history (the notebook + Qt-GUI era) is not itemised here.
See the git log and the `v1.5.0`, `v1.4.0`, … release tags, and the
`qt-final` tag for the last Qt-GUI commit.
