# Round 11 — first 3c6 lab round with the audio DAQs (2026-08-12)

Tore's first lab-testing round with the installed v2.3.0 wheel
(`pip install "pydvma[serve,soundcard]"`), bridge + soundcard driver,
ESI U24 XL and Scarlett 2i2. NI untested this round (audio-levels
session). No hardware attached during the fix session — everything
below is code-checked + suite-verified; items needing a live re-test
are flagged.

Status legend: ☐ open · ◐ in progress · ☑ fixed · ✎ recorded/no code.

## Confirmations (no action)

- ☑ Installed wheel works, connects to the audio DAQs.
- ☑ Workflow fine; notebook launch with `--settings` prefill is the
  intended lab path.
- ☑ Acquisition itself good; clipping indication fine.
- ✎ **2i2 tentatively chosen for 3c6** over the U24 XL (wider input
  range + gain control) — recorded in the device-survey doc + TODO.

Root causes for ALL bugs are established (evidence + decisions:
`dev/plans/2026-08-12-round11-design.md`). Highlights: the trigger
failure is THREE stacked defects (arming never set by Setup; threshold
volts-vs-FS mismatch armed by v2.3.0's VmaxSC auto-derivation;
soundcard trigger_detected actually meaning "capture complete" so
detection lags by stored_time and timeouts silently free-run); items
4+5 are ONE bug (fs really was 10000 — off-ladder fs renders the
select BLANK, so it was invisible and unchangeable; 10 kHz ⇒ TF axis
0–5000; engine metadata verified exact); CWT the sonogram works —
CWT DAMPING blows the 32-bit WASM allocation ceiling at lab sizes.

## Bugs

1. ☑ **Trigger never waits (soundcard).** Fixed in `2ce3770` (two-phase
   recorder, sample-exact alignment, timeout = wait only) + `404b1b0`
   (arming/threshold UX, volts default at 5 % FS). LIVE RE-TEST NEEDED
   (checklist below).
2. ☑ **Cancel mid-logging.** Fixed in `2ce3770` (background log task +
   cancel event) + `404b1b0` (client unwind).
3. ☑ **CWT damping over the WASM ceiling** (+ lin-axis default,
   w0-unaware band, masked errors, band boxes not reaching the fit).
   Fixed in `dc7e826`; progress + Stop added in `01a1f0b`.
4. ☑ **TF frequency axis ×10** = item 5 (fs was 10000 and
   undisplayable). Fixed by the typed fs combo (`404b1b0`) + the rates
   package (`e67348f`: sub-native targets incl. 3 kHz, stream restored
   after decimating logs, truthful configure fs).
5. ☑ **fs not settable under full settings.** Same root cause as 4 —
   the off-ladder value rendered the select blank. Typed combo.

## UX

6. ☑ Trigger essentials in Setup *basic* (`404b1b0`; the old group was
   machine-gated on NI presence, so on the lab PC it rendered beside a
   soundcard and silently did nothing).
7. ☑ "Default" device resolves to its physical name (`2ce3770`
   protocol + `404b1b0` UI). U24 S/PDIF endpoints receiving no signal
   is expected — they're digital inputs.
8. ☑ fs typed combo — "3000", "3k", "48 kHz" all accepted; feedback
   notes kept (`404b1b0`).
9. ☑ Full settings tidy: titled sections device/rates/levels/trigger/
   NI-DAQ (`404b1b0`).
10. ☑ Determinate progress bar; bridge clock capture-relative,
    holds while armed (`404b1b0`). Live time-domain preview DEFERRED
    (TODO). Long CWT calcs additionally got in-engine progress + a
    Stop (terminate + reboot) once past ~3 s (`01a1f0b`) — Tore's
    mid-round ask.
11. ☑ Prominent amber "armed — waiting for trigger" state naming the
    effective threshold (`404b1b0`) — the old one was a small grey
    note that never showed because of bug 1.
12. ☑ Sticky-auto axes (`22fecd3`): Auto X/Y restore the AUTO state
    (they used to freeze the extent — the click itself pinned the
    axis); new lines re-fit y (x too on an empty view); unit switches
    drop stale y; auto-y fits the visible x-window; x-only zooms keep
    y auto.
13. ☑ Nonlin redesign (`f7fc294`): linked Δf ↔ T inputs, total-time
    headline, M × n_exc progress grid + ETA, replace-vs-keep-both
    (replace undoes; kept runs suffixed #2), raw captures registered
    hidden atomically, `resp ch N` channel labels, σ key + explainer +
    docs link. Verified live against a mock bridge + real engine.

## For the next lab visit (live re-verification)

Code-checked this round, needs hardware truth:

- **Trigger end-to-end on the 2i2/U24**: arm in Setup basic, tap →
  the waiting banner should hold, the bar should start at the hit,
  and `record[pretrig_samples]` should be the hit. Try threshold up =
  no fire on ambient.
- **Cancel a 30 s log** mid-capture (should unwind in <1 s, no data).
- **fs = 3 kHz** (typed or picked): TF axis 0–1500, tray fs 3000,
  `captures at 8000/48000 Hz, resampled to 3000 Hz` note present
  (auto captures at 8 k on a real delta-sigma card; force
  `oversample='highest'` for a 48 k capture — delivered rate is 3000
  either way).
- **Scope after a decimating log** — axis must stay truthful (stream
  restore is new).
- **CWT damping on a real 6 s impulse** at 3 kHz — default band, no
  remedies needed; try the Q slider high + Stop mid-calc.
- **P4's live harness** (`scratchpad p4_hw_check.py` — copy into
  dev/ if useful): the full configure → decimating log → restored
  monitor run couldn't complete on the Mac (CoreAudio wedged by
  BlackHole's HAL proxy, unrelated pre-existing condition).
- 2i2 stated-gain workflow as the standard 3c6 ritual (survey/TODO).

## Suites at close

pytest **857 / 7 skipped**; vitest **939 / 1 skipped**; `npm run
check` **0/0**; mkdocs --strict green; Playwright **83 / 9 skipped**
plus the bridge specs under BRIDGE_E2E **12/12 against a real spawned
`pydvma-serve`** (incl. the new cancel-mid-BLA-run test). Engine wheel rebuilt (same 2.3.0 name — remember the
release traps in CLAUDE.md if this becomes 2.4.0). ~200 new tests
across the round. Session ran as 7 parallel read-only investigations
→ 7 implementation packages (P1–P7), each committed after coordinator
review.
