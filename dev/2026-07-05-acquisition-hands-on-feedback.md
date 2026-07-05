# Acquisition + follow-ups — hands-on feedback (round 2, 2026-07-05)

Tore's hands-on with the **acquisition/Live first-cut** (the rescued dispatch
work) plus more of the analysis app. **Recorded for the NEXT session — do not
implement in this one.** Everything below is committed to `master`; nothing
pushed. The earlier round-1 triage is `dev/2026-07-05-hands-on-feedback.md`.

## Big-picture takeaway

The **acquisition + Live** chunk needs a proper **design pass against the
round-2 mockups** before more building — the mockup's mini-oscilloscope (live
time trace + FFT + levels, a compact bottom-left widget that expands to fill the
figure area) is the target and is currently missing. Treat acquisition as
**design-first** next time; reference `dev/mockups/round2-bench.html` (and the
other round-1/2 mockups) — "that was great." The persistence half (per-set
settings + channel labels → `.dvma`) is solid and needs no rework.

---

## Setup
- **Trigger device lookup as soon as the Setup page loads** — currently it
  doesn't even try to enumerate devices until you press "Log data".
- Devices expose **many more settings**; keep the simple list but add a
  **basic ↔ full toggle**. "Full" needs more room than the context bar.
  Tore's preferred approach: an **extended-area mode** — the bar has its
  current compact size, plus an expanded mode that grows and **squashes the
  plot area downwards** for a fuller set of options (rather than taking over
  the whole figure region). [design]
- Allow **specifying the settings/config from OUTSIDE at launch** — e.g. from
  the JupyterLite notebook, the way the old Qt logger could. (Believed already
  in the Plan-2/3 scope — the `pydvma serve` / launch-config path.)

## Acquire
- Give a **more fulsome settings summary** (not every detail): **fs, channels,
  T (duration), selected device, pretrigger**.

## Live — bring back the mockup's oscilloscope
- The mockup's lovely **mini-oscilloscope** (based on the old Qt logger) has
  disappeared. It should show a **live time trace, live FFT, and levels**, all
  nicely designed.
- **Compact mode** sits **bottom-left** and **expands on click** up to fill the
  figure area — that **expanded** view is what the **Live tab** shows (two ways
  to reach the scope, per round-1 feedback).
- **Oscilloscope settings**: shared with Acquire, plus **osc-specific** ones —
  how much **time** is viewed, **frequency-view controls**, **log/lin**, etc.

## Time
- Rename **"Impulse channel" → "Input channel"** on the Time card. (The
  **"Clean Impulse"** button label stays — it is impulse-specific.) NB the TF
  card already says "input channel"; this is the Time/Clean-Impulse control.
- The tray card's **logged-time badge** shows e.g. `1.999977 s` on default
  settings → round to a **sensible number of sig figs (3 s.f.)**.

## Legend
- **Off lines disappearing is confusing** — once an item drops out of the
  legend you can't turn it back on from there. **Revert to struck-through /
  crossed-out when off** (keep it visible in the legend, like the tray),
  so it can be cycled back on. [conflicts with the current `legendEntries`,
  which drops fully-off lines — needs the legend to show off entries too.]

## Compute should be LIVE (not button-gated)
- **PSD / TF / Sono should recompute as soon as settings or sliders change**,
  not only when the Calc button is pressed. In particular **PSD averaging
  should be a live slider** (and live number entries). (Debounce sensibly; the
  per-kind stale-guard already handles rapid re-issue.)

## Bug to fix
- **TF with a single channel CRASHED.** Investigate + fix. Likely cause: the R4
  out/in remap drops the input channel, so a 1-channel set has **zero output
  channels** → the TF branch may index an empty `tf_data` or produce no lines /
  an error. Repro with a 1-channel `.dvma`; handle the "no output channel"
  case gracefully (clear message, no crash).

## Monitor lifecycle — REVISIT the C1 leak fix
- The C1 fix just applied (stop the monitor when leaving the Live stage)
  **conflicts** with the desired design: the monitor should **persist as the
  bottom-left mini view across tabs**. Instead, give the **mini-monitor its own
  start/stop** so the user is in control — and knows it's running because it's
  visibly there bottom-left. Replace "auto-stop on leaving Live" with
  **explicit start/stop + stop on whole-app teardown** (and still guard the C2
  setup-throw + I2/I3 races, which stay valid). [revisit `App.svelte`'s
  `$effect(() => { if ($activeStage !== 'live') monitor.stop() })`]
