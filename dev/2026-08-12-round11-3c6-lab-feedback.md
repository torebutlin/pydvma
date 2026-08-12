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

## Bugs

1. ☐ **Trigger never waits (soundcard).** Trigger on → Log → starts
   immediately, at any threshold. Root cause TBD.
2. ☐ **Cancel mid-logging does nothing.** Root cause TBD.
3. ☐ **CWT sonogram "not working".** Root cause TBD.
4. ☐ **TF frequency axis ×10 too large** (0–5000 shown where 0–500
   expected; U24, possibly 2i2 too). Code check this round — root
   cause TBD, live re-verify next lab visit.
5. ☐ **Full settings: decimation (lpf) offered but fs not settable
   anywhere.** Root cause TBD.

## UX

6. ☐ Basic trigger settings belong in Setup *basic*, not only full.
7. ☐ "Default" device should say which physical device it resolves
   to (U24 S/PDIF endpoints receiving no signal is expected — they're
   digital inputs — but the default's identity was invisible).
8. ☐ fs should accept a typed value as well as the dropdown ("fs=3k"
   feel), keeping the actual-fs / lpf-decimation feedback.
9. ☐ Full settings cluttered — tidy + clarity pass.
10. ☐ Acquisition progress indication (30 s logs show nothing —
    progress bar and/or live incoming time preview).
11. ☐ Obvious "waiting for trigger" state (may partially exist;
    unverifiable by Tore because of bug 1).
12. ☐ Axes not re-autoscaled when data added/processed/view changed —
    principle: data added to a view ⇒ re-auto (at least y), with care
    not to fight deliberate zooms.
13. ☐ **Nonlin tab needs a redesign for legibility**: what's
    happening during a run (progress grid), what the plots/new
    channels are, Δf ↔ period coupling made explicit (time-variable
    slider?), a clear total-experiment-time readout, and defined
    append-vs-replace semantics on re-run.

## Suites at close

TBD.
