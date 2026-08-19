# Changelog

All notable changes to pydvma are documented here. This project
follows [semantic versioning](https://semver.org/).

## Unreleased

The first 3c6 lab round's fixes (round 11): every bug found in the
field, plus the acquisition UX it showed was missing.

### Fixed

- **A bridge capture now carries the server's `unique_id`.** The webui's
  capture path dropped it, so `pydvma-serve`'s journal could never prove
  a posted document contained that capture: reopening restored the
  document *and* re-appended the capture beside its own copy. The
  session-journal e2e was checking only that a card was visible, so it
  passed with two — it now asserts the set count.
- **The journal's size guard is no longer silent.** An over-size session
  fell back to local-only autosave with a `console.warn`, so every
  server-side feature (tab-close restore, crash recovery, `session.data`)
  quietly stopped tracking the session while the app looked healthy. It
  now raises a one-shot toast saying exactly that.
- **`onsave` no longer receives a `MouseEvent` as its subset pick.** The
  header and Export-card buttons call `onsave()` explicitly; a bare
  `onclick={onsave}` would have handed the click event to the new
  optional `setIds` parameter.
- **Soundcard stimulus output no longer plays on the wrong device — or
  silences the capture.** Two stacked defects on the bridge/Python
  soundcard path: an unset output device resolved to the SYSTEM
  DEFAULT output (laptop speakers) instead of the interface being
  measured, and explicitly routing the output to the capture device
  opened a second CoreAudio stream that killed the running input
  stream — the capture came back all-zero (measured on raw
  sounddevice: macOS stops the input callback permanently the moment
  the second stream opens). Now an unset output follows the capture
  device whenever it can play (a microphone-only input still falls
  back to the default output), and a same-device capture+stimulus runs
  as ONE full-duplex stream — the capture stream plays the stimulus
  itself. A bridge **cancel now also stops a soundcard stimulus
  mid-play** (the playback wait polls the cancel event; previously it
  was uninterruptible). Live-verified on a Scarlett 2i2 4th Gen:
  direct path, /ws bridge path incl. mid-stimulus cancel, and the BLA
  loopback identity harness (G ≡ 1 to 4e-17 through the duplex
  stream).
- **The soundcard trigger now actually triggers.** Three stacked
  defects fixed: Setup's trigger fields never armed anything (and the
  group only rendered when NI was installed); the threshold compared
  volts against a full-scale-era default — 0.05 V is noise on a
  13.8 V-full-scale 2i2, so armed captures fired instantly; and
  `trigger_detected` in the soundcard recorder really meant "capture
  finished", so detection lagged by the whole record and timeouts
  silently fell through to free-run. Triggering is now two-phase
  (detection at the crossing, sample-exact pretrigger alignment), the
  threshold field knows its units (volts with a live % FS hint on a
  calibrated interface) and defaults to 5 % of full scale, and the
  timeout bounds only the wait.
- **Cancel works mid-log** on the bridge: the server answers control
  messages during a capture, the capture polls a cancel event
  everywhere it waits (stimulus stopped cleanly), and the client
  unwinds without touching the dataset.
- **CWT damping no longer dies on lab-length records.** The transform
  pre-flights its allocation against a 768 MiB ceiling and refuses
  with the numbers and remedies instead of numpy's bare "array is too
  big"; the fitted band's top now sets a time decimation; the band
  boxes reach the fit; the default band's low end tracks the wavelet
  Q; CWT sonograms default to the log frequency axis their native
  grid needs.
- **fs can no longer be invisible.** An off-ladder sample rate
  rendered the Setup dropdown blank while staying in force — the root
  cause of both "couldn't set fs anywhere" and a transfer function
  whose axis read 0–5000 where 0–500 was expected. The control is now
  a typed combo (accepts `3000`, `3k`, `48 kHz`) with the device
  ladder as suggestions, and it always shows the value in force.
- **The live scope stays truthful**: after a decimating log the stream
  is restored to the configured rate (it used to stay at the capture
  rate, scaling the scope's axis by up to 12×), and the configure
  reply reports the genuinely delivered rate.
- **Axes re-fit when they should.** Auto X/Y now *restore automatic
  fitting* instead of freezing the current extent; new data landing in
  a view re-fits y (and x if the view was empty); unit-changing view
  switches drop the stale range; an automatic y fits what is inside
  the current x window; an x-only zoom no longer silently pins y.
- **A Python round trip no longer strips app-authored `.dvma` state.**
  The web app stores per-item document state the Python reader does not
  interpret (channel labels, per-set analysis settings, a modal fit's
  measurement type and source mapping). `container.load` used to drop
  those manifest keys and `save` never wrote them back, so opening and
  re-saving a file in Python quietly discarded them — and, with the new
  session journal, so did every `session.push`, permanently, because the
  app reloads and autosaves the stripped document. Unknown per-item keys
  now survive verbatim; the reader's own fields still win on collision.

### Added

- **Acquisition progress**: a determinate bar against the capture
  duration, a capture-relative clock that holds while armed, and an
  unmissable "armed — waiting for trigger" state.
- **Long-calculation progress + Stop**: CWT computations report
  determinate progress from inside the engine; past ~3 s the Sono card
  shows a bar with a **Stop** that terminates and reboots the engine
  (the only reliable interrupt on the WASM worker).
- **Trigger essentials in Setup basic** (arm, threshold, channel),
  capability-gated per device; advanced fields under Full, which is
  now organised into titled sections instead of one wrapping row.
- **Sub-native rate targets** (500 Hz–5 kHz, including 3c6's 3 kHz) in
  the soundcard ladder — delivered by native capture + decimation,
  which the U24 XL's 8 kHz-floor ladder previously made unreachable.
- **The Default device names itself** — `Default — ESI U24 XL` — via a
  new `default_input` capability.
- **Nonlin stage redesign**: Δf and period are linked inputs with
  visible units, total experiment time is the card's headline, an
  M × n_exc progress grid with ETA runs during capture, re-runs ask
  replace-or-keep (replace undoes; kept runs get `#2` suffixes), BLA
  result channels read `resp ch N`, and the σ overlay finally has a
  key and a one-line explanation.
- **Native compute engine.** When the app is served by `pydvma-serve`,
  analysis ops now run in ordinary CPython on the serving machine (a
  new `/engine` websocket + `pydvma.engine_host`: per-connection worker
  subprocess, binary frame protocol) instead of the in-browser pyodide
  engine — no wasm32 2 GB address-space ceiling (the CWT image budget
  rises from 0.75 GiB to 8 GiB on 64-bit hosts), full-speed BLAS,
  engine-ready in about a second instead of a pyodide boot, and Stop
  terminates just the worker subprocess (measured: the in-flight calc
  settles in under a millisecond client-side and the compute child is
  dead within tens of milliseconds). The Pages app is unchanged: the
  browser engine remains the zero-install path and the automatic
  fallback whenever the native host is absent, version-mismatched, or
  unreachable (a toast reports the fallback when serve was detected).
  Force a host with `?enginehost=` (`native`, `pyodide`, or an explicit
  `ws://` URL). The BusyChip tooltip names the active engine.
- **Session journal — `pydvma-serve` owns the session.** Served locally,
  the authoritative session document now lives in the serve process, not
  only in the browser: the app's existing debounced autosave also posts
  to the server, and every capture is registered server-side the moment
  it is taken (so a tab closing inside the two-second autosave window
  still loses nothing). A registered capture is held until a posted
  document is shown to contain it — matched by `unique_id` — so one
  taken while the app was already serialising its document, or one
  belonging to another tab, is never dropped by that post. A session
  too large to cross the `/engine` socket in one frame (192 MiB guard,
  under serve's 256 MiB cap) falls back to browser-local autosave rather
  than repeatedly severing the connection, and **says so once** — a
  toast explaining that the server-side copy is stale from here while
  the local autosave is still current (a limit that stops being
  theoretical as soon as sonograms are included on Save).
  Closing the tab therefore costs nothing —
  reopening offers *"Restore session from pydvma-serve?"*. If the serve
  process itself died, the next start finds the session file it left
  behind and the app offers *"Recover session from a previous
  pydvma-serve run?"*, with **Dismiss** deleting the file; it lives in
  the system temp dir unless `pydvma-serve --session-dir DIR` says
  otherwise. Both are offers, never an automatic load. The browser-side
  IndexedDB autosave is unchanged and the Pages app is untouched; when
  both hold a session, the server's copy is the one offered. Restoring
  brings back the **data** — captures, loaded sets, calibration, units,
  channel labels, any saved modal fit — plus whatever analysis is
  already part of the document (see derived-data save below: pressing
  Save materialises the FFT and TF views into it, and they ride the
  journal from then on). Analysis computed but never saved is not in the
  document: re-run it (fast on the native engine).
- **`dvma.launch(settings)` — the notebook front door**, successor to the
  removed `dvma.Logger`. Starts the whole serve stack — acquisition
  bridge, native `/engine` compute host, session journal, embedded UI —
  on a background thread with its own event loop inside the kernel
  process, opens the browser, prints the URL and returns a `Session`. So
  it works identically from a plain script and from inside Jupyter, whose
  kernel already runs a loop of its own. `session.data` materialises a
  fresh `DataSet` from the session on every access, captures included;
  `session.push(data)` hands data back and connected apps offer to reload
  rather than silently replacing what is on screen; `session.close()`
  stops the server (context-manager supported, and `session.url` is the
  address). Push **merges by id** instead of replacing: an item carrying
  a `unique_id` replaces the stored copy *in place*, so pull → modify →
  push updates data where it sits, while a newly built item appends.
  Every kind mints one (see the derived-data entry below), so pushing an
  unmodified pull is a no-op. `MySettings` prefills Setup exactly as
  `--settings` does.
  `pydvma-serve --open` remains the same server without a kernel handle,
  and the `dvma.Logger` / `dvma.Oscilloscope` tombstones now point here.
- **Save Dataset stores data *with* its processing.** Saving now
  materialises the analysis you computed into the document itself: every
  FFT becomes a real `FreqData` and every transfer function a real
  `TfData` (coherence included), linked to the measurement it came from
  and readable straight back in Python — `data.freq_data_list` is
  populated by a file the app saved. Each stored result records the
  analysis settings that produced it (`source_settings`) and a signature
  of the **source samples** it was computed from (`source_signature`: an
  FNV-1a-64 hash of the samples plus the rate, computed identically in
  Python and in the browser and pinned by shared known-answer vectors).
  Re-saving replaces by lineage, so a measurement owns one FFT and one
  TF however many times you save; a session that has been saved carries
  its results through the journal and through `session.data` too.
  Saving also posts the updated session to `pydvma-serve` immediately, so
  the results are in the journal from the moment the file is written — a
  tab-close restore brings them back, and `session.data` in a notebook
  sees them. Deliberately narrow for now: PSD/cross-spectra are not
  materialised, and neither is an ensemble ("across sets") transfer
  function — it has many sources, and a single-source stamp could not
  honestly report staleness.
- **Every item carries its own `unique_id`.** `FreqData`, `TfData`,
  `CrossSpecData`, `SonoData`, `ModalData` and `MetaData` all mint one at
  construction, exactly as `TimeData` always has, and the app stamps one
  on every item it materialises *and* on the modal fit it persists
  (stable across re-saves, and preserved when it adopts an item written
  by python). `Session.push` merges by id, so this is what makes a
  notebook pull → push-back of an unchanged session a genuine no-op
  instead of appending a second copy of every spectrum — and of the modal
  fit. Optional in the container, so files written before this load
  unchanged — with no id, and therefore still duplicating on a repeated
  push; recompute or re-Save to give them one.
- **Broken compute chains are flagged, not silently trusted.** If a
  measurement's time data changed after a result was stored — a
  resample, a Clean Impulse, or an edit pushed back from a notebook —
  loading the file shows a **⚠ source changed** badge on that
  measurement's tray card; clicking it rederives exactly the affected
  views and the badge clears. Files with no signature (anything saved by
  an earlier pydvma) are never flagged.
- **"Include sonogram data?" on Save.** A sonogram is stored only when
  you say so, because the view is one channel's picture while the file
  wants the full complex sonogram — an extra transform and a bigger
  file. The prompt appears only when a sonogram was actually computed
  this session (never in a session that did not open the Sonogram
  stage, and never on autosave or the journal), offers **This channel**
  (the default; stores just that channel, so the cost matches the
  picture), **All channels** or **Don't include**, and does not ask
  again while the stored sonogram is still current. A refusal from the
  memory preflight reports itself and the save completes without it.
- **"Choose sets…" — save or export a subset.** Save Dataset, Export
  Matlab and Export CSV are now split controls: the button still means
  everything, and the ▾ opens a tick list of measurements. A subset save
  writes the chosen measurements plus everything derived from them
  (spectra, transfer functions, a modal fit spanning them) and nothing
  else. The pick is per-invocation, starts all-ticked every time, and is
  deliberately independent of what is shown or hidden on the plot.
- **Python subset parity**: `DataSet.subset(sets)` returns a new dataset
  holding the chosen measurements and every item derived from them
  (items are shared, not copied), and `save_data(..., sets=[…])` writes
  that subset — the notebook counterpart of Choose sets….

### Changed

- **Engine ops live in the package.** The compute glue the browser
  worker used to bundle privately is now `pydvma.engine`, shipped in
  the wheel and shared verbatim by both engine hosts (dev note:
  engine-op edits need `npm run vendor:wheels` before the browser sees
  them).
- **`legacy_to_dvma` / `mat_to_dvma` use real temp dirs** instead of
  fixed `/tmp` paths (Windows-safe, collision-safe under the native
  host).

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
- **Install docs named the wrong extra for sound cards.** The bridge is
  advertised as driving "soundcard or NI-DAQ", but `pydvma[serve]`
  installs only `websockets` — an acquisition backend that is absent is
  skipped *silently*, so a soundcard user following the headline command
  got a bridge that listed no audio devices and said nothing about why.
  The documented command is now `pydvma[serve,soundcard]`.

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
