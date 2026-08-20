# Working with Claude on pydvma

## Current focus (update when it changes)

As of 2026-08-20 (office Windows PC, 2i2 + Rigol DG1022Z on the bench,
over RDP): **ROUND 12 — Tore's same-morning lab report that the 2i2
was unusable — is root-caused, fixed, live-verified on real hardware,
and committed (NOT pushed).** The two acquisition bugs were: (1)
**coherence collapse** — `Recorder.callback` shifted the WHOLE stored
buffer per chunk (23 MB memmove vs a 2 ms budget at 48 kHz/chunk 100;
measured 3.4 ms), so PortAudio dropped input and every drop time-warped
the capture; worse for longer captures, intermittent at 3 kHz (33 ms
budget survives standalone, dies under the v2.4 serve journal's GIL
load — the "broke since v2.3" delta), NI immune (DAQmx buffers in C).
Fixed: both buffers are circular rings (O(chunk) callback;
`osc_time_data`/`stored_time_data` became copy-returning PROPERTIES —
zero via `zero_stored()`, assignment is a silent no-op), streams open
`latency='high'`, and dropped input is now COUNTED
(`Recorder.input_overflows` → `acquisition.LAST_CAPTURE_OVERFLOWS` →
a pinned "capture integrity" toast via a serve error frame). (2)
**zero-start** — every log rebuilt the stream and the 2-chunk settle
sleep lost to startup latency (172 zeros at 3 kHz exactly, reproduced
to the sample; 100–110 ms variable at 48 kHz), PLUS WDM-KS delivers a
burst of exact-zero PRIMING chunks a sample-count wait can't see
through. Fixed three ways: `start_stream` REUSES a live matching
soundcard stream (signature FROZEN at open — `_open_signature` — since
serve mutates the settings object the recorder may hold; the NI reuse
has the same latent aliasing, TODO'd), `log_data` tops the dwell up
until the ring truly holds the window (`_wait_for_buffer_fill`), and
the callback skips leading all-zero chunks bounded to ~1 s. Also
fixed: WDM-KS refuses sub-native rates with **-9994** (not -9997) —
`_is_unsupported_rate_error` now accepts it, so configure steps the
monitor up instead of dying; the fs dropdown (a Chromium datalist that
PREFIX-FILTERS by the typed text — ladder collapsed to one entry shown
twice) is now a typed input + arrow-only `<select>` (`setup-fs-pick`)
listing the full ladder unfiltered; and TF-view tray cards label rows
`ch_1/ch_0` + `ch_0 (ref)` via the legend's own `tfLineLabel`
(App threads `tfChInFor` through Tray). Evidence & verification: Rigol
sines phase-tracked (a drop = a phase step) — before: 5–11 events +
~1700 rad resid per 30 s capture; after: **0 events, 0 leading zeros,
~0.001 rad** across fresh/reused/3 kHz/48 kHz, plus a real spawned
serve with the ws monitor streaming through a 30 s log (clean), plus
Playwright against the built dist + real bridge for both webui fixes.
Round doc: `dev/2026-08-20-round12-2i2-lab-feedback.md`; reusable
harness `dev/soundcard_drop_check.py`. Suites: pytest 1163/14 (new
`tests/test_streams_ring.py`, 24 tests; serve gained -9994 + the
overflow-toast test), vitest 1145/1, check 0/0; engine wheel rebuilt
(same 2.4.0 name — remember `PYTHON=<anaconda>` or build-wheels.sh
hits the MS-Store python stub and my `| tail` masked its failure) and
verified byte-identical; webui dist rebuilt. NB this RDP session's
audio stack CHURNED mid-bench (enumeration reordered twice, WASAPI
endpoints vanished, probes went -9998) — deferred a
`select_capture_fs` probe fallback for ladder-less machines to
TODO.md rather than build against a moving target. **Next: Tore's
lab re-verification** (checklist at the top of TODO.md) alongside the
two still-unticked next-lab-visit checklists from stages 3–4 and the
derived-data round; the v2.4.0 PyPI upload remains his.

Previous (2026-08-19, Mac session, second half): **the derived-data save
round is LANDED on top of stages 3–4 — committed locally, NOT pushed
(Tore hasn't asked), full suite gate green, and NEITHER round is
live-verified yet.** Save Dataset now materialises the app's computed
**FFT and TF** into the `.dvma` as real `FreqData`/`TfData` items
(coherence included, `id_link`ed to their measurement,
replace-by-lineage so re-saves are idempotent) — Tore's "data with its
processing". Every stamped item carries `source_settings` plus a
**`source_signature`**: an FNV-1a-64 hash of the SOURCE samples + rate,
written once in `pydvma/_signature.py` and mirrored in
`webui/src/lib/codec/signature.ts`, pinned by eleven shared
known-answer vectors and a checked-in JS prototype
(`dev/prototypes/signature_prototype.mjs`). A file whose time data
changed after stamping loads with a **⚠ source changed** tray badge and
click-to-rederive — never a silent recompute, never silent trust.
Sonograms are stored only behind an explicit save-time prompt (Tore's
design: only when computed this session, This channel / All channels /
Don't include, not re-asked while the stored one is fresh; "This
channel" costs ONE channel, not all — a 4× bug caught in review, 20.54 s
→ 4.91 s on the 30 s × 51.2 kHz × 4 ch CWT bench, and the file goes
47.8 → 138.7 MB if you include all four). **Choose sets…** turns
Save/Export Matlab/Export CSV into all-by-default split buttons with a
per-measurement subset picker, and Python got the parity
(`DataSet.subset`, `save_data(sets=…)`). Save also POSTS the full live
document to the serve journal itself (`journalPost` in App's `onsave`) —
materialisation deliberately emits no store change, so without that post
the server kept the pre-Save session; thereafter the items are ordinary
document items and ride autosaves like any other. Between them that
closes the "restore brings back DATA only" limitation stages 3–4 left
open: a restore, and `session.data` in a notebook, now carry the saved
analysis. Round doc:
`dev/2026-08-19-derived-data-save-round.md` (what landed per task, the
measured cost tables, seven deviations, and the review-loop finds — the
signature originally hashed ONE CHANNEL of a multi-channel record;
ensemble-TF provenance deferred; remove/undo orphaning materialised
items; metaRaw merge-not-replace; the bridge capture that never carried
its server `unique_id`, duplicating on restore and MASKED by a too-weak
e2e assertion; the picker keeping ticks across split-button targets; the
sono cube preflight; a dead Escape handler — plus the FINAL whole-round
review's three: Save never posted the materialised items to the journal
at all; derived items (and the modal fit) carried no `unique_id`, so a
notebook pull→push duplicated them every time; and the 192 MiB journal
guard failed silently). Suites at close: pytest
**1117/6**, vitest **1145/1**, check **0/0** (188 files), Playwright
**69/23skip** + @engine **19/19** + BRIDGE_E2E **26/26** (five
specs, ports 8763–8768), mkdocs --strict clean; engine
wheel rebuilt FIVE times this round (twice in Task 5b, once at
close-out because Task 6 touched `datastructure.py`/`file.py`, twice more
for the final review and its re-verification — all ship in the wheel),
all **24** `pydvma/*.py` byte-identical to the tree.
Still deferred, in TODO.md: ensemble-TF and CSD materialisation,
provenance-dialect normalisation (app camelCase vs Python snake_case),
pre-round files whose derived items still have no id (so a repeated
notebook push duplicates those), `dvma.attach(url)`. The journal
sink-overflow toast is DONE, landed in this round's final review.
Everything is PUSHED, and **v2.4.0 is CUT and pushed** (five version
sites bumped; engine wheel reborn as 2.4.0 and re-verified through
@engine + engine-native; UI staged; sdist + fat wheel built and proven
from a CLEAN venv — `dvma.launch` from the installed wheel served the
embedded UI referencing its own 2.4.0 engine wheel, /engine greeting
`{v:1, pydvma:'2.4.0', journal:true}`). **Next: Tore's twine upload to
PyPI** (`twine upload dist/pydvma-2.4.0*`), then his live verification
on the lab PC via BOTH rounds' next-lab-visit checklists; the GitHub
release + tag stay HELD until after the PyPI upload per the v2.3.0
precedent (Zenodo auto-archives on release — no DOI for a
not-yet-installable version).

Previous (2026-08-19, Mac session, overnight): **stages 3–4 of the
native-engine arc — the session journal and `dvma.launch` — are LANDED
and committed locally (NOT pushed; Tore hasn't asked), with the full
suite gate green but NO live verification yet.** `pydvma-serve` now
owns the session document: a `SessionJournal` (atomic spill, generation
counter, 256 MB pending-capture budget) fed by the app's debounced
autosave over new `/engine` journal ops AND by the serve log path
registering every capture **at birth**, so closing the tab inside the
autosave debounce still loses nothing; reopening offers the session
back, and a `kill -9`'d previous run is offered as a crash recovery
(liveness-probed, PK-gated, 7-day pruned, `--session-dir` injectable).
`dvma.launch(settings)` is the notebook front door replacing the removed
`dvma.Logger` — the whole serve stack on a daemon thread inside the
kernel, returning a `Session` with `.data` / `.push` (generation-checked,
smart-merged by `unique_id`) / `.close`; `container.save_bytes`/
`load_bytes` gave the journal, the capture path and `engine.py`'s import
ops **one shared writer**. Round doc:
`dev/2026-08-18-session-journal-round.md` (what landed, six honest
deviations from the plan, and the review-loop findings — non-atomic
spill, journal writes on the event loop, a destructive test suite
pruning REAL session files, a capture-loss window in push, e2e teardown
holes). A FINAL whole-arc review then caught three cross-task seams no
per-task review could see, all fixed before handover (`ff1baab`):
`Session.push` stripped webui-authored document state (channel labels,
ModalData fit-source keys — container now passes unknown manifest keys
through, making Python round-trips lossless); a >256 MiB autosave frame
would kill the /engine socket in a loop (sink guarded at 192 MiB,
falls back to local-only with a console warning — a one-shot toast is
TODO'd); and clears-pending had a capture-loss window (now id-matched:
a doc post clears only captures it actually contains, two-tab safe).
Suites at close: pytest **1033/6**, vitest **1069/1**, check
**0/0**, Playwright **69/19skip** + @engine **19/19** + BRIDGE_E2E
**22/22** (bridge+bla+engine-native+session-journal, ports
8763/8765/8766/8767), mkdocs --strict clean; engine wheel rebuilt
TWICE (still 2.3.0; second rebuild after `container.py` changed) and
verified byte-identical to the tree. Two known
limitations went to TODO.md: **restore brings back DATA, not computed
analysis views** (derived store sits outside the document — pre-existing,
newly user-visible, docs say so; **now CLOSED by the derived-data round
above**) and `dvma.attach(url)` for an externally started serve.
Its live-verification checklist (real 2i2 capture → close → reopen →
Restore; launch from a real Jupyter kernel; kill -9 recovery; two
concurrent serves; the Windows bridge-spec run) is **still unticked** and
should be run alongside the derived-data one.

Previous (2026-08-18 evening, Mac session, 2i2 + loopback cable back on
the bench): **the bridge soundcard-OUTPUT bug is FIXED and the
native-engine round's checklist is now fully ticked** (committed
locally, NOT pushed — Tore hasn't asked). Root cause of the
zeroed-capture half was confirmed ENVIRONMENTAL with raw sounddevice —
the running input stream's callback now stops permanently the moment a
second stream opens on the same device (PaMacCore err=-50; worked
2026-08-10, broken by 2026-08-17 — tracks the Focusrite Control 2
install 10 Aug + self-update 12 Aug, Tore-confirmed, likely flashed
2i2 firmware: no OS update/reboot in the window, persists with FC2
quit) — so the fix is structural:
an unset soundcard output now follows the capture device whenever it
can play (options.py; mic-only inputs keep the default-output
fallback), and a same-device capture+stimulus runs as ONE full-duplex
`sd.Stream` (Recorder.init_stream opens duplex when
`output_shares_input_clock`; `setup_output_soundcard` returns an
adapter that plays through the capture stream's own output side, and
refuses actionably if the live stream is input-only). Bonus: bridge
cancel now stops a soundcard stimulus MID-PLAY — the adapter's wait
polls the cancel event (a release-once call raced a cancel arriving
before the stimulus was queued; measured 1.91 s → 0.49 s over /ws).
Evidence: 20 mocked-sd unit tests (`tests/test_soundcard_duplex_output.py`),
direct live 6/6 (BlackHole pinned "nothing at the system default"),
/ws live 10/10, BLA identity G ≡ 1 to 4e-17 through the duplex stream.
Also closed: the "2i2 cable −27 dB" mystery was just the output volume
knob (−3 dB at full). NB the device indices REORDERED mid-session when
an iPhone continuity mic left (2i2 1→0) — name-based re-resolution
absorbed it on the bridge; pin bench scripts by name. Suites: pytest
907/6, mkdocs --strict green (webui untouched). (That session closed by
drafting the stages 3–4 plan,
`dev/plans/2026-08-18-session-journal-launch-plan.md`, which Tore
approved and which is now implemented — see the top block.)

Earlier (2026-08-18, Windows PC session, via RDP): **the native-engine
arc is verified on the PC too, and everything is PUSHED.** The
round-doc checklist's four PC items are all ticked live against the
cDAQ-9174 (native-engine default flip on Windows; a real 4-ch NI
capture FFT/TF'd through `/engine`; a 30 s × 51.2 kHz CWT damping fit
whose 6.34 GiB image sails through the 8 GiB native ceiling with the
sizing error firing correctly at 64 voices; Stop mid-CWT killing the
worker subprocess within seconds) — only the soundcard-output item
remains, blocked on its fix landing (and RDP has no audio endpoints).
Suites on the PC: pytest 927/18 with hardware live, vitest 1030/1,
check 0/0, Playwright 69 + @engine 19/19 + BRIDGE_E2E 18/18 (first
Windows run of the spawned engine host), bridge_hw_check 58/58,
mkdocs --strict green. **One real bug found and fixed (`8cc9f48`)**:
serve restored the post-capture stream rate AFTER `log_result`, a
race only real NI hardware loses (refusal or DAQmx property-conflict
on a prompt follow-up; regression-pinned mock-side). Two notes went
to TODO.md: the real-app-over-socket e2e coverage gap, and calc
completion parking in a HIDDEN page (rAF suspended — engine
round-trip completes, the action then waits for an animation frame;
bit this session's browser-pane automation, harmless for visible
tabs). Remember the gitignored-artifact trap when switching machines:
this PC still had a v2.0.0 engine wheel + July dist until rebuilt.

As of 2026-08-17 evening (Mac session): **the native compute engine —
stages 0–2 of `dev/plans/2026-08-17-native-engine-design.md` — is
landed, pushed, and live-verified on real
hardware.** When the app is opened through `pydvma-serve`, analysis now
runs in ordinary CPython on the serving machine over a new `/engine`
websocket (`pydvma.engine_host`: per-connection worker subprocess,
binary frame protocol) instead of the in-browser pyodide worker —
lifting the wasm32 CWT/sonogram memory ceiling from 0.75 GiB to 8 GiB,
running at full BLAS speed, and making Stop kill a subprocess in
milliseconds instead of rebooting the whole engine; the compute glue
itself moved into the package as `pydvma.engine`, shipped in the wheel
and shared verbatim by both hosts. It is the default whenever serve
detects itself served locally (`?enginehost=` overrides; the browser
engine is the automatic, silently-toasted fallback on any absence or
version mismatch) — Pages and JupyterLite are untouched, still pyodide,
still zero-install. Review passes across the arc caught and fixed real
bugs before anything shipped: non-finite scalars breaking the wire
JSON, a too-permissive frame-truncation guard, Stop not actually
observing a client-side close, a stranded `init()` orphaning worker
subprocesses on retry, and a genuine Playwright port collision (this
arc's own port pick for `engine-native.spec.ts` landed on 8765, already
owned by `bla.spec.ts`'s `BLA_BRIDGE_PORT` — moved to 8766, every
claimant now named in one comment). Live-verified this evening on this
Mac + a Scarlett 2i2 4th Gen (48 kHz, 4-ch bridge captures): served
with no `?enginehost=` param, the app resolved the native engine by
default (console-confirmed), and FFT/CWT-sonogram/TF-with-coherence all
ran correctly through the `/engine` socket end-to-end. That session also
found (and logged to TODO, NOT fixed — pre-existing, not from this arc)
a two-part bridge **soundcard OUTPUT** bug: an unset output device plays
the stimulus on the system default output instead of the capture
device, and an explicitly-matched output device zeroes the capture on
macOS (a second CoreAudio stream breaking the running input stream) —
likely fix is one duplex `sd.playrec`-style stream. Round doc:
`dev/2026-08-17-native-engine-round.md`. Suites at close: pytest 886/7,
vitest 1030/1, check 0/0, Playwright 69/15skip + @engine 19/19 +
BRIDGE_E2E 18/18, mkdocs --strict green; engine wheel rebuilt (still
2.3.0) and verified byte-identical to the tree. **Stages 3–4 — the
session journal (serve owns the session doc; tab-close/reopen restores
it) and `dvma.launch` (the notebook front door replacing the removed
`dvma.Logger`)** are the next arc and need their own fresh plan before
implementation starts (design §4.4–4.5 already sketches the shape).

As of 2026-08-12/13 (overnight Mac session): **ROUND 11 — the first
3c6 lab round's feedback — is fully fixed and committed LOCALLY (NOT
pushed; Tore hasn't asked).** Sixteen items, five real bugs, all
root-caused before any fix (`dev/2026-08-12-round11-3c6-lab-feedback.md`
+ `dev/plans/2026-08-12-round11-design.md`): the soundcard trigger was
broken THREE ways at once (Setup never armed + the group was gated on
machine-has-NI; threshold in volts vs a full-scale-era 0.05 default —
noise-fires on a 13.8 V-FS 2i2, armed by v2.3.0's own VmaxSC
auto-derivation; `trigger_detected` actually meant capture-COMPLETE,
so detection lagged stored_time and timeouts silently free-ran — the
recorder is now a two-phase state machine, sample-exact, NI untouched);
bridge cancel was dead four ways (now: background log task + cancel
event, `status/cancelled` INSTEAD of `log_result`); "CWT not working" =
CWT DAMPING blowing the fixed ~2 GB wasm32 ceiling (now: 768 MiB
preflight naming remedies, band→fit plumbing, w0-aware f_min, log-axis
default for CWT); and **"fs unsettable" + "TF axis ×10" were ONE bug** —
fs really was 10000 (docs-canonical prefill) and an off-ladder fs
rendered the Setup select BLANK (now a typed combo accepting "3k";
sub-native targets 500–5000 incl. 3c6's 3 kHz offered; stream restored
to configured rate after decimating logs; configure fs truthful). UX:
trigger essentials in Setup basic (unit-aware threshold defaulting to
5 % FS), Default device names itself (`default_input` capability), full
tier in titled sections, determinate progress bar + capture-relative
clock + unmissable armed-waiting banner, **sticky-auto axes** (Auto X/Y
restore null — they used to FREEZE the extent; new lines re-fit y;
unit switches drop y; auto-y fits the visible x-window), the **Nonlin
redesign** (linked Δf↔T, total-time headline, M×n_exc progress grid,
replace-vs-keep-both with Undo, `resp ch N` labels, σ key), and
**in-engine progress + Stop** for long CWT calcs (worker posts frames;
Stop = terminate + reboot — SharedArrayBuffer needs COOP/COEP that
Pages won't send). **3c6 envelope pinned as regression floor**: 3 kHz /
30 s / 2 ch (+ 6 s damping) — Tore's stated lab usage; NB auto
oversample captures 3 kHz lpf logs at 8 k on real delta-sigma cards
('lowest'), 48 k needs `oversample='highest'`, delivered rate 3000
either way. Suites: pytest 857/7, vitest 939/1, check 0/0, Playwright
83/9 + bridge e2e green (see round doc), mkdocs --strict green; engine
wheel rebuilt (same 2.3.0 name). **Next lab visit checklist** (live
re-verification of trigger/cancel/3 kHz/scope-restore/CWT) is in the
round doc. Ran as 7 parallel read-only investigations → 7 review-gated
implementation packages; NB two agents ran `git stash` in the shared
tree mid-session (recovered; prompts must forbid it — see auto-memory).
2i2 is Tore's TENTATIVE 3c6 pick (survey + TODO updated). v2.3.0 PyPI
upload + GitHub release remain Tore's (unchanged below).

Previous session (2026-08-12 late, Mac): **v2.3.0 is cut and pushed for
Tore's 3c6 lab round — PyPI upload is his (twine), and the GitHub
release is deliberately held until after it** so the Zenodo auto-archive
does not mint a DOI for a version that is not yet installable. Minor,
not patch: `pydvma.devices`, `list_available_devices()`,
`MySettings(device=...)` and `pydvma-serve --list-devices` are all new
public API. **The lab install is
`pip install "pydvma[serve,soundcard]"`** — the audio DAQ needs the
BRIDGE, because everything that turns the U24 XL into volts (profile →
`VmaxSC`, the macOS bit-depth/volume pins, the Windows endpoint-volume
pin, honest rate ladders) is Python-side; the browser-only Pages app
captures in FS units with a rate CoreAudio may lie about.

Cutting it surfaced two silent-failure traps, now written up under
"Releasing" below and worth reading before any future release: the fat
wheel had embedded a **v2.0.0-era UI** (staging step skipped — and it
boots fine, so nothing complains), and the documented `pydvma[serve]`
never installed `sounddevice`, with a missing backend vanishing from
`--list-devices` without a word. Docs corrected repo-wide. Verified by
installing the built wheel into a clean venv and driving the bundled UI
end-to-end, not from the editable checkout. Suites: pytest 705/7, check
0/0, vitest 810/1, mkdocs --strict green.

Earlier that day (Windows PC session): **the U24 XL is characterised on
Windows too, and the three platform gaps that round exposed are FIXED.**
Bench: `dev/2026-08-12-u24xl-windows-bench.md`; harness
`dev/u24xl_win_check.py` (18/18, source-free by design so it runs with
nothing plugged in; `--source-vpp` adds the absolute check). Measured
against a Rigol DG1022Z (3.000 Vpp, high-Z, confirmed on the
instrument): true full scale **1.9036 Vpk = +0.10 dB vs ESI's +4.7 dBu
spec**, implied clip 3.81 Vpp (bracketed by Tore's LED observation);
pydvma reads −0.114 dB at 1 kHz and −0.12 dB at 5 kHz. The Mac round's
Apple-1.000-Vrms assumption is now corroborated, not load-bearing. The
box is also **~16 dB quieter than the Mac could see** (open-channel
floor −96.1 dBFS, 20 Hz–20 kHz at 48 k — that −79 dBFS / 12.8 ENOB was
the Mac's headphone amp). Anti-alias tracks fs here too (5 kHz rejected
75 dB at fs = 8000). Windows exposes the SAME −40..+12 dB gain and it is
digital — SNR flat to 0.03 dB over 20 dB, the UNCONNECTED channel's
floor tracks the setting, and at 5 Vpp in, attenuating cannot un-clip
(crest 1.238 and THD −19.4 dB at every setting) but DOES hide the
clipping from the level meter. Landed: `pydvma/_win_audio.py` (raw
ctypes COM endpoint-volume pin, `_coreaudio`'s twin);
`native_input_rates` answers on Windows (`max_input_fs` 192000 → 48000,
and this propagates to the Setup fs dropdown); device identity is
**(name, host API)** via `streams.resolve_device_index`, lifted out of
`serve.py` so the Python/CLI paths get the bridge's protection —
`device_index` really does reorder on Windows (WDM-KS block moved, U24
XL 36 → 27, no hardware change). Suites: pytest 698/17, mkdocs --strict
green.

**The device/fs UX work then landed in the same session** —
`pydvma/devices.py`. `dvma.list_available_devices()` and
`pydvma-serve --list-devices` are the pre-choice step: one block per
PHYSICAL device (not one line per enumeration slot), backends ranked
with the recommended one marked, the hardware's rate ladder shown
separately from what each backend actually **delivers**, and an explicit
calibration status so an assumed voltage scale can never pass for a
known one — **CHARACTERISED** (in `_soundcard_specs`, `VmaxSC` derived,
readings are volts) / **NEEDS GAIN** (model known, analogue knob must be
stated) / **uncalibrated** (`VmaxSC=1.0` is a PLACEHOLDER, readings are
FS units, fix with `verify_input_scaling`). `MySettings(device='U24XL')`
selects by name and picks the backend for the requested fs — 48 kHz →
WDM-KS index 27, 8 kHz → WASAPI index 23 with the reason printed —
refusing to guess between two real devices, with one reported tie-break
(auxiliary S/PDIF and Stereo Mix endpoints lose to the analogue input,
judged on the endpoint ROLE before the bracket, never the model name:
the U24 XL's own name contains "SPDIF I/O"). Setup shows one row per
device with an "all backends" tick and the calibration line; verified
live. **Cross-OS portability**: `devices.resolve` falls back to the
`_soundcard_specs` PROFILE LABEL when the raw name misses, so
`device='ESI U24 XL'` resolves on Mac AND PC (the same box is `U24XL
with SPDIF I/O` to CoreAudio, `Line (U24XL with SPDIF I/O)` to
Windows, and a 2i2 is generic `Analogue 1 + 2 (Focusrite USB Audio)`
on Windows) — case/punctuation-insensitive, reported in the note,
tried only after a name miss. The input dropdown also stopped listing
playback-only endpoints: **38 rows → 11**.

Recommended default backend on Windows is **WDM-KS** (24-bit + honest
rates), NOT WASAPI (exclusive = full rate ladder but PortAudio
negotiates 16-bit; shared = 24-bit but locked to the control-panel
rate).

Suites at close: pytest 747/17, vitest 810/1, check 0/0, mkdocs
--strict green. Everything above is PUSHED to master.


As of 2026-08-11 (late evening, Mac session): **the ESI U24 XL is
characterised AND landed** — the survey's flagged Tore-action closed
same-day using the Mac jack as reference source (its line-level output
mode measured as 1.000 Vrms full-scale; wiring: jack → U24 L+R, still
connected). Bench (`dev/2026-08-11-u24xl-bench.md`): +4.7 dBu fixed
full scale confirmed to 0.07 dB, native 8k–48k ladder with fs-tracking
anti-alias (69–76 dB), ~12.8 ENOB wideband / ~15.3 at 8 kHz (floor
includes the Mac amp), clocks −0.3 ppm. Two macOS traps found and now
PINNED per-capture by `streams.Recorder` (restore-on-close, like the
clock): macOS parks the box at 16-bit AND resets that on every rate
change; the "input gain" is a hidden ±dB DIGITAL volume (vold write
silently fails — the setter bisects the volm scalar). Landed:
`esi_u24xl` PROFILES entry (first FIXED-GAIN profile), VmaxSC
auto-derivation with NO stated gain (`fixed_gain` flag through serve
caps to a gainless Setup UI), `dev/u24xl_hw_check.py` (13/13 live,
incl. ABSOLUTE volts at −0.00 dB with the volume deliberately
mis-set). Follow-ups queued in TODO.md: Windows enumeration name +
endpoint-volume equivalent, Rigol absolute check (needs a BNC→RCA/TS
cable), unplugged-input noise floor, output-side calibration, S/PDIF
self-test idea. Suites: pytest 619/3, vitest 807/1, check 0/0, mkdocs
--strict green; engine wheel rebuilt (same 2.2.0 name).

Next morning (2026-08-12): the survey doc grew four researched
sections (ESI family sweep → **planet 22c** found: £159 Dante
fixed-range 2i2o, "a real option of interest" per Tore — bench trial
= decision gate, incl. two-box cross-spectrum sync check; AoIP class
sweep — 22c is the class's value outlier, DVS £45/PC, Dante Via is
48k-locked, unverified free Linux route via AES67+PipeWire;
multichannel tier — Dante NEVER wins co-located, XR18/X32 stay the
answer, stacked 22c only for distributed/poolable; input-range
options — inline attenuator pads solve the U24's ±1.9 Vpk ceiling,
buy −20 dB PSG02973 not the −10 dB whose 312/422 network realises
only −5 dB into 10 kΩ). Survey conclusions + lineup rewritten current
(U24 characterised; 22c inserted second in the ladder). All pushed;
CI green.

Earlier (2026-08-11 evening): **v2.2.0 is RELEASED end-to-end** — PyPI
(2.0.0 → 2.2.0; 2.1.0 was tagged+GH-released but deliberately never
uploaded: its embedded UI still offered the since-refuted BLA
commanded-x), GitHub release, Zenodo auto-archive (concept DOI
10.5281/zenodo.21888383 in CITATION.cff; the GitHub–Zenodo toggle is ON
so every release self-archives), and Pages app+docs current. The BLA
branch AND the PC hardware round (`pc-bench-2026-08-11`) are both
merged: BLA verified live on NI (measured-x exact incl. at coerced
rates; **commanded-x REFUTED — AO start offset random per capture even
on a routed-clock 6212 — gate closed everywhere**), 9234 oversample
'lowest' confirmed (+3.0 dB), WASAPI answered (refuses wrong rates —
no Windows _coreaudio twin needed), 2i2 Windows profile fixed BUT its
render path is dead at the driver level (FC2/driver reinstall pending —
blocks the Windows loopback BLA check). Also landed:
`verify_input_scaling` + `RigolDG1022Z` (pydvma/verify.py; live
hardware run still pending — Rigol has no USB cable), the
audio-as-DAQ device survey with agreed lineup
(`dev/2026-08-11-audio-daq-device-survey.md`: ESI U24 XL → 2i2 → XR18),
and TODO.md consolidated into one list. JOSS is now unblocked (DOI
exists; paper is Tore's, in his OneDrive). Suites: pytest 594/3,
vitest 802/1, check 0/0, Playwright 87/9 + BRIDGE_E2E 96/96, mkdocs
--strict green.

Earlier (2026-08-10): the Schoukens BLA noise/nonlinearity-separation
feature was built COMPLETE on branch `worktree-schoukens-bla` (~25
commits; since merged, see above).
Design + plan: `dev/plans/2026-08-10-schoukens-bla-*`.
What shipped: a **Nonlin stage** (design→run→results card) that runs
M realisations × n_exc orthogonal experiments × P periods of seeded
random-phase multisine (defined in SAMPLES — coercion-proof; equal-A
lines, RMS level, hard peak guard, no fade), per-capture via
`acquire.record({outputOverride})` on ALL paths (bridge-NI, bridge-
soundcard, browser web-audio — no sample-sync needed because x is a
MEASURED channel and the common phase offset cancels in the solve;
commanded-x is analytic-from-seed and gated to non-chassis routed-clock
NI only), then `analysis.calculate_bla` (unified n×n solve, SISO =
n_exc=1, non-square n_resp×n_exc first-class) → one TfData per
excitation with `bla_sigma_nl`/`bla_sigma_n` (LINEAR-unit stds, plot
directly — no sqrt) + `.bla` run-spec meta; TF-view dashed σ overlay
(zero-floored bins → NaN gaps, NOT −300 dB — autofit protection),
verdict banding, `.dvma` round-trip incl. reload. Hard preflight:
output_fs==fs, lpf OFF (resample kills periodicity), pretrigger
auto-disarm, all-waveform peak sweep (crest varies per (m,e)), rail =
output_VmaxNI default 5 V not ao_vmax; enabled AO rows must be
ao0..ao(n−1) (buffer columns map positionally). Suites at close: pytest
538/3, vitest 777/1, check 0/0, Playwright 87/9 + BRIDGE_E2E 96/96 (full
pyodide run vs real mock server; wheel re-vendored — same 2.0.0 name),
mkdocs --strict green. **Hardware-verified live on the Scarlett 2i2
digital loopback** (`dev/bla_soundcard_check.py`, 8/8: 2×2 identity to
1e-17 with both outputs driving — the orthogonal solve works through
the physical path). Docs: `docs/web-logger/nonlin.md`. TODO.md gained
an 11-item BLA follow-ups section (PC/NI verification queued for a
Windows session; use_output_as_ch0 webui exposure; calc_tf_averaged
latent JsProxy indexing; worker-offload for low-Δf generation).

Earlier (2026-08-03): two Dependabot security bumps merged (PRs #9, #10 —
both lockfile-only, `webui/package-lock.json`): dompurify 3.4.11→3.4.12
(transitive via jspdf; GHSA-c2j3-45gr-mqc4) and postcss 8.5.16→8.5.25
+ nanoid 3.3.15→3.3.16 (dev, transitive via vite; GHSA-r28c-9q8g-f849,
high — source-map path traversal). `npm audit` now 0 vulnerabilities.
Verified before merge: registry integrity hashes checked independently,
check 0/0 + vitest 681/1, and the built CSS is BYTE-IDENTICAL across the
postcss bump; dompurify is bundled but unreachable (nothing calls
jspdf's `doc.html()` — figure.ts uses jsPDF + svg2pdf.js only). NB
there is no `.github/dependabot.yml`, and that is DELIBERATE: repo
setting `dependabot_security_updates` is enabled, which scans the whole
dependency graph (npm AND pip/pyproject) and raises a PR only for a
real advisory. A dependabot.yml would additionally opt into ROUTINE
version-bump PRs — unwanted churn during lab testing. 0 open alerts as
of 2026-08-03.

As of 2026-07-11 (freq-navigator arc — PUSHED; deployed at HEAD):
**The frequency navigator shipped end-to-end** (design
`dev/plans/2026-07-11-freq-navigator-design.md`, plan
`…-plan.md`; Tore's ask: kill the zoom-fit-home-zoom loop in modal
fitting). NyquistBrush is GENERALISED into `FreqNavigator` on all
freq-x views (frequency + every tf type incl. Bode; toolbar toggle,
auto-open in the Fit stage + on Nyquist, per-view `navigator`
override): a **progressive scope ribbon** (⤢ scopes the strip to the
window; the thin full-extent ribbon appears only when scoped; scope =
`viewState.freqScope`, NAVIGATIONAL only — never feeds calcs, not in
undo history, and NOT persisted: `viewState.serialize()/restore()`
turn out to have no app callers, now a TODO.md item), **client-side
peak-step ‹ ›** (`lib/plot/peaks.ts` — prominence-gated max-envelope
detection + keep-width targeting, span/10 first step from wide-open,
log = ratio semantics) and **fitted-mode ticks** (strip = mode map;
fit → › → fit). Pure webui — no engine/wheel rebuild. Suites: check
0/0, vitest 681/1, Playwright 85/7 (fit @engine incl. tick asserts),
pytest 347/3, mkdocs --strict green.

Earlier (2026-07-10 evening, round 10 — PUSHED):
**Jim Woodhouse's first hands-on feedback**
(`dev/2026-07-10-round10-jw-feedback.md`; his test archives in
`dev/example_data/`, deliberately untracked). Three fixes: **Load Data
now APPENDS** when data is already loaded (`loadDataset(ds,
{append:true})` — merges into the existing dataset doc, keeps the live
modal fit, ignores an appended file's ModalData; the old logger's
"Add on load"); **JW time-file .mat import fixed** — V2.9a TIME
captures save `indata/buflen/freq/dt2/tsmax` with NO `npts`, the
importer's time branch KeyError'd on `npts` (guitar_string4_5mar_1.mat
now imports 200000×1 @ 40 kHz; axis from indata's own length; tsmax is
a scale marker, data already physical — no rescale); **error toasts
pin open** until × (JW couldn't copy one before it vanished; explicit
timeout still overrides). Suites: pytest 347/3, check 0/0, vitest
660/1, Playwright 81/7, mkdocs --strict green; wheel rebuilt. Round 10
is PUSHED + DEPLOYED; **round-10b addendum** (also pushed):
`selection.shiftLines` is FAMILY-aware — data sets and fit pseudo-sets
shift independently, a whole-set solo advances to its family's next
set (lockstep when both families solo) — fixing "‹ › drop the fit line
when a soloed/1-channel data set is selected" (the old clean-solo
exception judged via trayFocus, which filters fit sets; the Tray
exception is deleted, shiftMode = any line subset).

Earlier that day (round 9 **hardware-verified on the PC**): bridge_hw_check 44/44 incl. new check E on all three devices;
the multiplexed `max_input_fs` division confirmed live (6003 2ch
captures at exactly 100k/2 = 50 kHz — DAQmx accepts running AT the
aggregate limit; 6212 400k/2; DSA 9234 keeps 51.2k per-channel) and
regression-guarded (`test_lpf_log_respects_per_channel_max_rate` +
a 6212 anti-alias proof: an unfiltered 2 kHz log folds a 1300 Hz tone
in-band at ~0.5 V, lpf_on crushes it >40 dB). The day's testing found
and FIXED four real bugs: (1) **AO shared-clock mis-rating** — the
6212 routed the AI sample clock as AO source even when output_fs ≠
the AI stream rate, so lpf_on + stimulus played the drive 100x fast
(now rate-gated; hardware-verified); (2) **resample_to_fs missed
exact ratios for coerced capture rates** — the 6003's 80 MHz timebase
coerces 48 kHz→48019.2077 Hz, whose 833/5000 back-ratio is past
limit_denominator(1024), landing "8 kHz" lpf logs at 8003.2 Hz (now a
Stern–Brocot simplest-in-tolerance fallback with a 2^19-tap FIR cap;
also un-no-ops resample-to-match between near-identical rates);
(3) **webui bridge output defaults** — an enabled-but-untouched
output group sent amp 0 / f1 0 / f2 0 (a windowed DC pulse) while the
chip claimed "sweep 0.3V 10-500Hz" (bridge.ts now uses the card
defaults); (4) **soundcard stream leak** — start_stream overwrote
REC_SC without closing the old InputStream (fatal on single-handle
MME under RDP, where it blocked every bridge log after configure;
plus the documented lpf unfiltered fallback now also covers an
oversampled OPEN being refused — PortAudio check_input_settings
approves rates InputStream then rejects). Windows-PC infra unlocked:
Playwright ran here for the FIRST time — 86/86 incl. all 7 bridge
e2e (needed `npx playwright install`, hand-started webServers — the
config commands are POSIX-only — and the new PYDVMA_PYTHON override
in bridge.spec.ts; bare `python3` is the MS-Store stub on Windows);
webui/public/pyodide vendored (never fetched here — engine boot
failed from the served dist until `bash scripts/fetch-pyodide.sh`).
Soundcard under RDP: paths work but capture is digital silence, only
44.1k opens, no default input — see the rdp-audio-quirks memory.
Suites at close: pytest 407/19 (hardware live), vitest 653/1, check
0/0, Playwright 86/86, mkdocs --strict green. Engine wheel + dist
rebuilt at HEAD.

Earlier that day (round 9 as landed on the Mac): third feedback batch
(`dev/2026-07-10-round9-feedback.md`): **CWT wavelet Q is a slider**
(4–64 + exact box to 128, nFFT feel) with **voices/octave AUTO by
default** (`autoVoicesForW0` = ladder ≥ max(16, 0.6·w0) — Morlet tiling
bound, default CWT unchanged; explicit pick pins it, legacy files with
hand-picked voices load pinned); **logging digital low-pass toggle**
(Setup full, off by default): fs keeps its meaning, `lpf_on` makes the
capture oversample at the device max (`streams.max_input_fs` — NB
multiplexed NI devices: ai_max_rate is AGGREGATE, divided by channels)
and resample down behind `analysis.resample_to_fs` (rational polyphase
Kaiser FIR, 96 dB stopband, zero-phase; DSA-coercion-safe; clip check
on the RAW peak; `lpf_capture_fs` recorded; web-audio path records at
native rate + engine-resamples); and a **Time-view Resample tool**
(match-a-set dropdown with fs values + custom fs; down = anti-alias
decimation, up = band-limited interp — NOT linear, which images; toast
Undo one level; derived results recompute). NI hardware verification
was pending — now DONE, see above. Engine wheel rebuilt (same 2.0.0
name). Suites at the Mac close: pytest 340/3, check 0/0, vitest
652/1, Playwright 79/7, mkdocs --strict green.

Earlier (2026-07-09, round 8):
Tore's second feedback batch landed
(`dev/2026-07-09-round8-feedback.md`): the **fit summary chip is
draggable + minimisable** (module-scope UI state survives re-mounts;
re-clamps on expand so an edge-parked chip never clips its buttons;
z-index above the legend so it can't park ungrabbably under it);
**‹ › shift a selected line subset** as a group
(`selection.shiftLines` — per-SET circular rotation so a ch+fit pair
cycles together and a one-line fit set stays put; all-on and
clean-set-solo keep the old stepping); a **header computing chip**
(`BusyChip` — actions.busy OR damping.busy OR engine 'loading' →
"starting engine…"; 300 ms delay-in so fast calcs never flash it;
indeterminate by design, the worker has no progress frames); and a
**docs audit** (stale "Nyquist brush in flight" fixed; all-hidden Fit
refusal, Best-match-ignores-visibility, multi-set compose rule, and
the round-8 features documented; mkdocs --strict green). Suites:
check 0/0, vitest 648/1, Playwright 78/7.

Earlier that day: **rounds 7 through 7h — the whole first
lab-testing feedback day — are fully landed, PUSHED, and DEPLOYED (CI
green; the live app carries 4c92545).** The 7d–7h additions on top of
what's described below: legends + coherence now EXPORT with figures per
their toggles (SVG legend overlay follows the restyle contract;
e2e pixel-diff round-trip); the **JW-logger .mat import** was fixed
twice over — coherence columns attach as `tf_coherence` instead of
poisoning fits as fake TF channels (guitar file: fit railed at the
window edge before, fn=182.13 ζ=0.0085 after), then the layout was
matched to Tore's RECOVERED original MATLAB source (V2.9a: `freq`=fs,
`dt2`=[n_time, n_spec_cols, n_son], yspec interleaves [H,coh] pairs) —
survey of that source produced the "Old-logger feature review list" in
TODO.md; **fit self-awareness**: per-mode phase-significance ⚠ (>30°
from 0/180° → check TF type) + Refine divergence warning (>10% fn move
→ toast with Undo); **the modal fit got a structural upgrade** —
`estimate_global_constants` (linear re-solve of complex constants +
per-channel global RH/RL·ω⁻² residues at fixed poles) now powers the
global reconstruction, and `modal_refine` is VARIABLE PROJECTION
(poles-only nonlinear; rescued a railed seed to a physical 234 Hz mode
on the real guitar file); and **fits follow visible lines** — the
legend/tray tri-state selects exactly which line(s) are fitted (solo =
fit one), with the Fit card showing "N of M lines". Suites at close:
pytest 328/3, vitest 642/1, `npm run check` 0/0, Playwright 77/7.
Gotchas that bit: griffe-strict docstrings fail the docs CI (one param
per Args line, returns in prose; gate with `python -m mkdocs build
--strict`); Playwright ONLY from webui/.

Earlier that day — round 7b:
Clean Impulse is an on/off TOGGLE (raw stashed + cleaned cached, never
re-cleans its own output; save writes the applied copy); legend
defaults SE. Round 7c: CWT ladders widened (w0 + voices/octave to 64);
the damping panel sits in a RIGHT-hand column on wide screens (charts
stacked, click-to-expand fills the plot region and pops back; narrow
keeps the below-dock); every damping chart saves as its own PNG via the
Save Figure delivery + restyle contract (charts follow the
self-contained-SVG rules: xmlns + data-role + CHROME hexes) and the
band table saves CSV; the export audit's one correctness gap — Bode
exporting ONLY its magnitude pane — is fixed (getSvg composites both
panes, flattened; e2e-guarded). CI gotcha learned: gate on `npm run
check` (app tsconfig, ~172 files), NOT bare svelte-check (~104) — the
bare form missed a real rune-shadowing error that failed CI.

All nine round-7 items are done (dispositions:
`dev/2026-07-09-round7-feedback.md`): sono axis controls actually work
now (the toolbar was fed [0,1] extents and setRange('sono') was never
read — e2e-guarded end-to-end since); the zoom toolbar docks in a
`.plot-nav` strip above the plot instead of floating over the data;
**the interactive damping panel** replaces the inline fn/Qn box
(peaks mode: the restored Qt decay-fit plot + draggable threshold line
+ draggable start-time line over the sonogram, `peak_threshold`
promoted to a real analysis parameter; bands mode: NEW
`calculate_damping_by_band` — Butterworth ladder ('all'/oct/1-3rd/
1-10th-dec) + Schroeder EDC → EDT/T20/T30/T60/band-Qn); CWT wavelet-Q
(`w0`) exposed in the Sono card; Clean Impulse now auto-recomputes
existing derived results; modal fit lines got a local|global toggle
(all sets/chans, first-class pseudo-sets, pink overlay retired);
legend wraps to columns >10 entries + compact dot-grid mode. Engine
wheel rebuilt (same 2.0.0 filename). Latent bug fixed on the way:
damping as a session's FIRST compute parked forever (no engine.boot()
kick — see the calcDamping comment). Suites on this Mac: pytest 319/3
skipped, vitest 623/1, svelte-check 0, Playwright 72/8 (hardware +
capability tests only run on the Windows PC).

Round-1..6 context (2026-07-05..08): six feedback/build rounds
delivered the whole `dev/plans/2026-07-07-full-gui-replacement-plan.md`
roadmap; live at torebutlin.github.io/pydvma/app/ (+ /lite/, + docs
with a full Web Logger section).

**What ships:** the three modes (Pages analysis + Web Audio soundcard,
no install; `pip install pydvma[serve]` -> `pydvma-serve` local bridge
with mock/soundcard/nidaq drivers + wheel-embedded UI + `--settings`
-> /config Setup prefill; JupyterLite). Acquisition: Setup basic/full
(processing-off defaults, NI group: IEPE/terminal/fs ladders/voltage
rails capability-clamped), pretrigger (armed, editable samples,
status events; browser AND bridge; hardware-verified sample-exact on
NI), output stimulus (signal_generator parity, browser + bridge),
persistent mini-oscilloscope + Live scope (FFT/Welch-PSD, narrow-rail
strip). Analysis: FFT/PSD/CSD-pair (E[X*Y]) /TF+coherence/Clean
Impulse, sonogram STFT|**CWT** (dependency-free Morlet) + damping
fits (both methods), unit-aware axes, Δf-intent resolution, live
recompute. Modal fit: Fit 1/2/3, **multi-set shared poles**
(TfDataList joint fit), Reject, **Refine** (auto-revert), per-mode
mute/delete/undo, fit-as-tray-card (dashed recon lines, normal line
controls), ModalData persists in .dvma (Python-readable). Scaling:
**Best Match** (via calibration factors) + **x(iω)^p display
transform** (non-destructive by design — divergence from Qt
documented). Calibration dialog (sensitivity+units). Export: .dvma /
MATLAB / CSV (file.py parity), PNG/PDF figures (theme-invariant).
Axis-nav: hover-expand toolbar, curl undo/redo (snapshot history),
Nyquist real/imag + draggable freq brush (live, 1 undo/gesture),
Bode per-pane y, coherence axis. Dark theme (no-flash, toggle).
Legacy files load forever (2019 pre-list pickles normalised; derived
kinds seed views; orphan TF convention chIn=null).

**Engineering notes that keep biting:** 32-bit WASM rejects big
NOMINAL strided views ('array is too big') — fixed via direct
as_strided in calculate_cross_spectrum_matrix AND the sonogram
(_spectrogram_complex_lowmem, byte-identical, scipy-pinned); CWT was
memory-bounded by design. Nested FFI payloads are JsProxy/JsNull —
glue uses .get/getattr/`not x`, JS omits null keys. The deployed
subpath (/pydvma/app/) is e2e-guarded (engine base-URL bug class).
SVG: scoped CSS BEATS inline presentation attributes — an opaque
.plot-bg { fill: var(--surface) } silently covered the sono heat
canvas for weeks while fill="transparent" sat ignored; canvas-pixel
and attribute assertions stayed green throughout. Rendering claims
must be verified on SCREENSHOTS of visible composited pixels (the
sono e2e now does; keep that standard for any layered-canvas work).
The engine wheel (public/pypi, gitignored) rebuilds via
webui/scripts/build-wheels.sh — keep ENGINE_WHEELS
(webui/src/lib/stores/engine.ts) in sync on version bumps: the
hard-coded `pydvma-<version>-py3-none-any.whl` filename must match the
rebuilt engine wheel or the app breaks at boot (as of v2.0.0). As of the
native-engine work (2026-08-17), this same wheel also carries the
compute-ops module `pydvma/engine.py` — so an engine-op edit is invisible
to the browser (vite no longer bundles it) until `npm run vendor:wheels`
rebuilds the wheel.

**Suites at close:** pytest 352 / 15 capability-skipped (Windows PC,
all NI hardware live); vitest 592; svelte-check 0/0; Playwright 69 +
bridge e2e 7/7 (BRIDGE_E2E=1 vs a real spawned server).

**The Windows NI recheck is DONE** (2026-07-08, this PC — full
write-up in `dev/2026-07-08-windows-ni-recheck.md`): full pytest
green with hardware live; the standing multi-channel gap is closed
(real 4-ch bridge capture on the 9234 + 4-ch live scope and Log in
the built UI); pretrigger + output sweep verified through the bridge
on all three devices (`dev/bridge_hw_check.py`, 38/38 — a reusable
headless harness, run it against `pydvma-serve --driver nidaq` after
any acquisition-path change); both round-D notes eyeballed in the
real UI with real caps ("output clamped to device rail ±4.24 V";
"device runs at 8533.3 Hz (requested 8000)"). The recheck's NEW
finding is FIXED (task_01e8edaf): the webui acquire store's
`reclampOutputFs` now stages `output_fs` from the effective output
device's `device_caps.ao_max_rate` whenever the input fs exceeds it
(MySettings otherwise defaults output_fs = fs and the 6003 rejects
the log), and Setup shows "output runs at 5000 Hz (device AO
limit)" — verified end-to-end on the real Dev3 (bridge-payload
check + a real UI log through vite + `pydvma-serve --driver
nidaq`).  The NEWER finding from that verification is ALSO FIXED
(its spawned session, merged same day): an unset NI/mock
`output_device_index` now follows the resolved input device when
the output driver matches the input driver (options.py), instead of
silently defaulting to device 0 — previously a Dev3 input drove AO
on the cDAQ (mis-routed stimulus / rail errors on multi-NI
benches). Hardware-verified: Dev2-input + unset output routes the
sweep out of Dev2's own AO.

**v2.0.0 IS RELEASED** (2026-07-08 evening): PyPI carries the fat
wheel + sdist (`pip install "pydvma[serve]"` works cold), the
`v2.0.0` tag is pushed, and the GitHub release (CHANGELOG body +
artifacts) is published. The sustainability surface is live
(CITATION.cff with Tore's ORCID, docs/about/support.md, FUNDING.yml
Sponsor-button link — NO payment routes by design until the Cambridge
Enterprise conversation). The JOSS paper draft moved OUT of the repo
to Tore's OneDrive (Work Research/Projects/2026_pydvma_paper/paper) —
he authors it personally. **The Qt GUI was REMOVED** (Tore's final
confirmation after the round-6 parity audit): `dvma.Logger` /
`dvma.Oscilloscope` raise actionable tombstones (`_REMOVED_NAMES` in
`pydvma/__init__.py`); the last Qt version is the **`qt-final`** git
tag.

**NEXT SESSIONS: Tore is lab-testing solo over days/weeks — expect
FEEDBACK-driven work, not feature waves. `TODO.md` is the single
canonical pickup list** (web-logger follow-ups, hardware ideas,
housekeeping, deferred items, and Tore's release/sustainability admin
threads — Zenodo DOI, CE, JOSS). Feedback trail:
dev/2026-07-08-round6-feedback.md and earlier; full history in git.
IEPE with a live accelerometer is verified (accel on cDAQ1Mod1/ai1;
`dev/iepe_accel_check.py`); `dev/bridge_hw_check.py` is the reusable
headless NI harness for after any acquisition-path change.


Auto-loaded by Claude Code at the start of every session. Contributors
and collaborators: the concrete filesystem paths below are for the
**maintainer's Windows development machine** (``C:\Users\tb267\...``)
and don't apply on Mac/Linux — translate them to your own paths or
put personal overrides in ``CLAUDE.local.md`` (which stays
gitignored). The rules themselves (edit master directly, verify
hardware-touching code before handing back, docstring discipline,
etc.) are repo-wide conventions worth following regardless of OS.

## Workflow (solo developer)

- **Edit directly on `master`** in the main repo folder
  (`C:\Users\tb267\Documents\GitHub\pydvma`). Don't create feature
  branches for isolation — the sole developer uses `git revert` or
  `git reset` as the undo button.
- Exception: genuinely risky or multi-file refactors can still use a
  branch; ask before creating one.
- Commit small, coherent changes to `master` as you go. Don't batch a
  session's worth of edits into one commit. Push only when the user
  explicitly asks.
- Worktrees under `.claude/worktrees/` are for Claude's isolated
  exploration only; prefer not to use them for iterative development
  against real hardware.

## Iteration mechanics

- The main repo is installed editably (`pip install -e .`), so saved
  file changes are immediately live in the notebook kernel.
- Recommend `%load_ext autoreload` + `%autoreload 2` in the first
  notebook cell so no kernel restart is needed.

## Environment

- Windows 11, Python via `C:\Users\tb267\anaconda3\python.exe` (base
  conda env). No per-project env.
- `pytest` available from base; tests live in `tests/`.

## Hardware (for NI acquisition work)

Three NI devices are connected on this Windows machine:

- **USB-6003** — low-cost; AO is software-timed (no hardware AI/AO
  sync possible). **Multiplexed AI**: single ADC scanning the
  channel list, so samples across channels are skewed by the inter-
  channel convert time, not simultaneous.
- **USB-6212** — M-series; hardware-timed AO, supports shared-clock
  AI/AO sync. **Multiplexed AI**: single ADC scanning the channel
  list (same sample skew caveat as the 6003).
- **cDAQ-9174 chassis** with module `cDAQ1Mod1` = NI 9234 (4-ch AI)
  and `cDAQ1Mod2` = NI 9260 BNC (2-ch AO). Shared-clock sync via
  chassis timebase. **Simultaneous sampling**: both modules are DSA
  (delta-sigma) with per-channel ADCs/DACs, so all channels are
  sampled (and output) at the same instant — no inter-channel skew.
  **IEPE/ICP excitation** is supported on the 9234 (not the 6003 or
  6212); discrete legal currents are `0.0` or `0.002` A. Anti-alias
  LPF is automatic and locked to the sample rate (delta-sigma
  inherent — not user-configurable).

**BNC loopback is wired ao0 → ai0 on each device** — that's the
standard test stimulus. Self-contained: the user does not need to be
physically present to tap a hammer or similar. **An IEPE
accelerometer (~100 mV/g class) is plugged into cDAQ1Mod1/ai1** (as
of 2026-07-08) — it sits motionless on the bench, so expect only a
noise floor (~30 µV rms) plus the cold-start bias transient, but it
lets IEPE excitation be exercised against a real sensor chain
headlessly (`dev/iepe_accel_check.py`). Stimulus-dependent
tests (e.g. `test_pretrigger_with_stimulus`) run an AC-stimulus
preflight (`_has_ao_to_ai_loopback` in
`tests/test_acquisition_hardware.py`) and auto-skip on any device
whose loopback isn't producing signal, so adding or removing cables
just changes which tests run — nothing breaks CI.

- **Caveat (this specific USB-6003 only):** the loopback sits on a
  breakout box and there is some evidence the `ao0` / `ao1` screw-
  terminal labels on this unit may not match the silicon channels
  reported to nidaqmx (i.e. the label says `ao0` but it might be
  wired to `ao1`, or vice versa). If AO→AI tests on Dev3 start
  failing after a re-wire, physically swap the wire between the two
  AO terminals as a first sanity check before suspecting a hardware
  fault. Not believed to affect other 6003 units — just this one.
  The wire is currently left in place so tests stay runnable.

## Verify, don't assume

Before writing code against an external library (esp. `nidaqmx`,
`sounddevice`), verify the real API up front:

- `python -c "import nidaqmx.constants as c; print([x.name for x in c.ProductCategory])"`
- Inspect `dir(obj)` on a live object, or check the upstream source.

A unit test with a fake object only proves the code matches the fake —
it does not prove the fake matches reality. The 2025 `C_DAQ_CHASSIS`
vs `COMPACT_DAQ_CHASSIS` bug came from exactly this gap.

## Tests — build them as you go

Every behaviour-changing edit should either have a test (new or
updated) or a reason not to. Split by where they can run:

- **Mac-runnable (no hardware):** pure-Python logic — `_ni_backend`
  enumeration + channel-string construction, signal generation, FFT /
  TF maths, datastructure round-trips. Use mocks for nidaqmx.
- **PC-only (NI hardware plugged in):** live acquisition, pretrigger
  timing, AO loopback, clock routing. These live in
  `tests/test_acquisition_hardware.py` and auto-skip on Mac via a
  module-level `nidaqmx` detection check.
- **Parametrize over whatever is plugged in.** Don't hard-code
  `device_index=0` in tests — discover devices at collection time and
  iterate. Hardware varies (USB-6003, USB-6212, cDAQ chassis with
  different modules) and tests should keep working as devices are
  swapped in and out.
- **Cover with AND without pretrigger.** Pretrigger changes the call
  path significantly (buffer re-init, callback interaction, timeout
  fallback). Both must be exercised. The "with" variant should drive
  the AO → BNC loopback to produce a real trigger event.

## Run hardware checks yourself before handing code back

Since this Windows machine has all three NI devices connected and
Python + nidaqmx work from the shell, verify NI-touching code by
running it headlessly from the terminal (`python -c` or a small
inline script) before asking the user to try it in the notebook.
GUI is not required for driver / callback / trigger logic. Catch
hardware-surfaced bugs at write time, not at notebook time.

## Docstrings

- Write a docstring for every new public function, method, or class.
- When reading or editing an existing function, check its docstring
  against current behaviour and update any inaccuracy you notice —
  even if the edit itself was unrelated. The published MkDocs site
  (`docs/`) is generated from these, so drift becomes user-visible.
- Include hardware constraints and conventions you discover
  (voltage ranges, terminal-config requirements, clock routing
  limits, sample-rate ladders on DSA modules) in the docstring of
  the function that enforces or depends on them. Don't bury them in
  `# comments` — the rendered docs won't pick those up.

## Releasing — the two silent traps

Both of these produce a *working* artifact that is quietly wrong, so
neither shows up as an error. Check them explicitly.

**1. Stage the UI before building the wheel.** `pydvma/_webui` is a
gitignored staged copy that the build backend simply zips — it does
**not** read `webui/dist`. Skip the staging step and the fat wheel
ships whatever UI was staged last time, *together with its matching
engine wheel*, so it is internally consistent and boots happily while
serving a months-old app. Order:

```bash
python scripts/stage_webui.py          # runs npm run build, mirrors dist -> pydvma/_webui
python -m build --sdist --wheel        # both flags: the bare form yields a LEAN wheel
```

Verify by listing the wheel: `pydvma/_webui/pypi/` must contain the
engine wheel for *this* version, and the embedded `assets/index-*.js`
must reference that same filename.

**2. Version bump touches five places, not one.** `pyproject.toml`,
`pydvma/datastructure.py`, `CITATION.cff`, `CHANGELOG.md`, and
`ENGINE_WHEELS` in `webui/src/lib/stores/engine.ts`. Only the first two
are test-enforced. A stale `ENGINE_WHEELS` does **not** 404 under vite —
the SPA fallback hands micropip `index.html` and it fails deep in the
install. Prove it by booting the app, not by checking a status code.

Extras are separable: `[serve]` is the bridge alone (`websockets`), and
an absent acquisition backend is skipped **silently** — no error, the
driver's whole section just vanishes from `--list-devices`. Test a
release by installing the built wheel into a clean venv, never from the
editable checkout, which already has the backends present.

## Scope discipline

See `TODO.md` for the roadmap; it's organised by phase. Don't
freelance Phase D items when doing Phase A work.
