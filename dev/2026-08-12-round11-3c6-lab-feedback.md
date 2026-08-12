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

1. ◐ **Trigger never waits (soundcard).** Fix in flight (P1 python +
   P3 UI).
2. ◐ **Cancel mid-logging does nothing.** Fix in flight (P1 server +
   P3 client).
3. ◐ **CWT damping over the WASM ceiling** (+ lin-axis default,
   w0-unaware band, unmasked errors). Fix in flight (P2).
4. ◐ **TF frequency axis ×10** = item 5 (fs was 10000 and
   undisplayable). Fix in flight (P3 fs combo); live re-verify next
   lab visit. Related fixes queued (P4): sub-8 kHz decimation
   targets, stream restored after decimating logs, truthful fs
   readback.
5. ◐ **fs not settable under full settings.** Same fix as 4 —
   typed fs combo (P3).

## UX

6. ◐ Basic trigger settings into Setup *basic* (P3; the old group was
   also machine-gated on NI presence, so on the lab PC it rendered
   beside a soundcard and silently did nothing).
7. ◐ "Default" device resolves to its physical name (P1 protocol +
   P3 UI). U24 S/PDIF endpoints receiving no signal is expected —
   they're digital inputs.
8. ◐ fs typed combo, "3k" accepted, feedback notes kept (P3).
9. ◐ Full settings tidy: titled sections instead of one 12–15-group
   wrapping row (P3).
10. ◐ Determinate progress bar; bridge clock made capture-relative
    (P3). Live time-domain preview DEFERRED to TODO.
11. ◐ Prominent "armed — waiting for trigger" state (P3) — it
    existed as one small grey note, and never showed because of
    bug 1.
12. ◐ Axes: Auto buttons currently FREEZE the extent instead of
    restoring the auto state — that plus unit-changing view switches
    keeping stale y-ranges is the root cause. Sticky-auto design in
    P5.
13. ◐ Nonlin redesign designed (P6): linked Δf ↔ period inputs,
    total-time headline, M × n_exc progress grid + ETA,
    replace-vs-keep-both run semantics (current behaviour appends
    silently and orphans the previous run's hidden raw sets), σ key +
    in-card explanation.

## Suites at close

TBD.
