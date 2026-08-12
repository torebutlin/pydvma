# Noise & nonlinearity separation (Nonlin stage)

The **Nonlin** stage runs a **Schoukens random-phase multisine**
measurement: instead of one ordinary transfer function, it takes a
structured set of captures designed so the result splits cleanly into
three numbers per frequency line — the **best linear approximation**
(BLA) of your system's frequency response, how much of the scatter
around it is **measurement noise**, and how much is **nonlinear
distortion**. An ordinary TF or coherence measurement cannot tell you
that split; coherence drops for noise, a bad reference *and*
nonlinearity alike, with no way to tell which. This stage answers "is
my structure behaving linearly at this excitation level, and if not,
where?"

## What the method measures

The excitation is a **multisine**: a periodic signal built from many
sinusoids at once, at random phases, covering your chosen band. A run
plays **M realisations** (fresh random phases each) and, within every
realisation, captures **P repeated periods** of the same steady-state
signal:

- **Period-to-period scatter** (within one realisation) is pure
  **measurement noise** — the system's response to an *identical*
  repeated input can only differ because of noise in the chain.
- **Realisation-to-realisation scatter** (across the M draws) is
  **noise + nonlinear distortion** — a new random phase draw applies a
  different amplitude/phase combination to the input harmonics, and a
  nonlinear system responds differently to different combinations of
  the same lines. A perfectly linear system would show no extra
  scatter here beyond the noise already seen period-to-period.

Subtracting the (period-averaged) noise variance from the realisation
variance isolates the nonlinear-distortion variance. The result is
reported as two extra lines alongside the ordinary transfer function:
**σ_NL** (nonlinear-distortion level) and **σ_n** (noise level), both
standard deviations in the same linear units as the transfer function
itself. See [Reading the results](#reading-the-results) for how to use
them.

SISO and MISO measurements share one code path: **n_exc** driven
outputs (excitations) against any number of measured responses,
including non-square systems (e.g. 1 output driving 3 response
channels).

## Getting to the Nonlin stage

Nonlin is a **measurement** stage, not just an analysis view — like
Acquire, it drives an output and runs its own captures, so it needs a
live source (a soundcard or NI device, in the browser or through the
bridge) and stays disabled when you have only loaded a saved file with
no live device attached. See [the three modes](index.md) for what each
mode can reach.

## Design: setting up a run

The **Design** group mirrors the Acquire card's shape, but every field
here also drives the excitation itself.

### Band and resolution

- **band (Hz)** — the frequency range to excite, `f1` to `f2`.
- **resolution / period** — **Δf** (Hz) and **T** (s) are two boxes for
  **one** quantity, and you can type into either. They are linked
  through the multisine's period length in samples, which is what the
  excitation is really defined in: typing a resolution gives
  `N = round(fs / Δf)` samples, typing a period gives
  `N = round(T · fs)`, and the resolved `N` and excited-line count are
  shown underneath (`N = 4096 samples · 993 lines`). A typed period is
  quantised to whole samples first, so the Δf box comes back with the
  resolution you can actually have rather than the one you asked for.

    The reason both are on the card: they trade off directly, and the
    period is the one that costs you time. A **finer Δf** (better
    frequency resolution, closer-spaced excited lines) means a
    **longer period**, and every realisation/experiment captures
    several whole periods of it, so halving Δf doubles the whole run.
    Pick the coarsest Δf that still resolves the features you care
    about, and watch the [total time](#total-time) as you do.

### Level

**level** sets the **RMS amplitude per excitation** — volts on an NI
bridge output (clamped to the device's output rail), or a normalised
fraction of full scale (rail ±1) on the soundcard/browser path, which
has no calibrated DAC. There is no simple peak limit to enforce on this
field directly: a random-phase multisine's **crest factor** (peak /
RMS) is not fixed the way a single sine's `√2` is — it varies from one
random phase draw to the next, and is typically several times higher
for a many-line multisine. So pydvma cannot just cap the RMS field
against a fixed ratio. Instead, **Start** generates every one of the
run's `M × n_exc` actual waveforms up front and checks each one's real
peak against the output rail before playing a single sample; if any
realisation would clip, the run refuses with a message telling you to
lower the level.

### Averaging: M, P, transient

- **M** (default **6**) — realisations. Raise it for a less noisy
  σ_NL/σ_n split (more realisation-scatter samples), and because the
  BLA itself keeps improving as `1/√M` — the reported σ values are
  *per-realisation* levels, not the uncertainty on the plotted line
  (see [below](#reading-the-results)).
- **P** (default **4**) — steady-state periods captured per experiment.
  Raise it to buy a lower noise floor (σ_n): P periods average down
  the same way an ordinary spectral average does, at the cost of a
  longer capture.
- **transient** (default **2**) — periods played and discarded before
  the analysis window starts, so the structure's response has time to
  settle into steady state after each fresh phase draw. Raise it for
  heavily-damped or low-frequency structures that need longer than two
  periods to settle, and see the [browser-path
  note](#browser-path-output-latency) below for another reason to raise
  it there.

### Total time {#total-time}

The card's headline number — top left, beside the stage title — is the
run's **whole wall-clock cost**, live as you edit anything:

```
≈ 12.4 s
12 captures × 1.03 s
```

The design row spells out where it comes from (`6 realisations × 2
excitations × 6 periods (2 transient + 4 steady)`), so if a run is
going to take longer than you want, you can see which factor to cut.

Note that **the run sets its own capture length** — one whole
`(transient + P)`-period window per capture — and says so under the
responses readout. Your standing **duration** in the Acquire card is
overridden for the run and restored afterwards; you do not need to set
it, and you should not be surprised to see it move.

### Excitations and responses

The **excitations** table has one row per output channel your device
can drive (up to a handful of rows — a much larger AO device would need
a wider UI than a context card comfortably offers). For each row you
enable:

- turn the output **on** to drive it during the run, and
- pick where the analysis reads that excitation's actual drive signal
  from — its **x-source**.

**Every driven output needs its drive measured on an input channel**
(a loopback wire, or a force gauge on a hammer/shaker rig) — pick
**measure on ch N** and wire that output's signal into input channel
`N`. The alternative, **commanded drive**, is described next; it is
only offered where it is actually valid.

Every input channel that is *not* carrying a measured drive becomes a
**response** automatically — the responses readout (`responses: ch 1,
ch 2`) always reflects the remaining channels, so you don't assign
those explicitly.

#### x-source: measured vs. commanded drive

**Measured** (the default, and the only choice that works everywhere)
reads the excitation from an input channel wired to the drive. It works
because the excitation and every response share the **same ADC clock**:
whatever moment the output happens to start playing at, the unknown
delay rotates the excitation and the response spectra by the identical
phase factor, which cancels out in the analysis. A per-capture restart
of the output is therefore harmless.

**Commanded drive** skips measuring the excitation at all — the
analysis regenerates the exact waveform it *told the hardware to play*,
from the same random-phase seed, and uses that directly. This frees up
an input channel, but it is only offered — the option is disabled
otherwise, with the reason shown — when the path can **prove** the
output started at a known sample relative to the input: a **non-chassis
NI device**, with the input's own AI sample clock routed as the AO
clock, running both at one matched rate. A cDAQ chassis does **not**
qualify even though its modules share a chassis timebase: that keeps
AI and AO **phase-coherent** but not **sample-accurate** — there is no
routed AI clock to prove a zero start offset. Software-timed-AO NI
devices (the USB-6003 family) don't qualify either.

Why this matters: unlike measured-x, the commanded branch assumes **no**
per-capture start-time jitter. On any path that cannot prove that, real
jitter in when the output actually starts would show up as extra
realisation-to-realisation scatter — indistinguishable, in the maths,
from genuine nonlinear distortion. Measuring the drive sidesteps the
whole problem, which is why it is the default and the only option on
the browser and soundcard paths.

## What the run enforces

Nonlin runs a stricter capture than an ordinary log, and checks (or
adjusts) three things before Start will proceed:

- **Output rate = sample rate.** The multisine is defined as an exact
  integer number of samples per period; any mismatch between the drive
  rate and the capture rate would break that exact periodicity, so
  unlike an ordinary output stimulus (which pydvma silently reclamps to
  fit an AO-rate limit) a BLA run refuses outright rather than
  reclamping quietly.
- **Digital low-pass off.** In that mode the capture runs oversampled
  and is resampled down afterwards — which means the recorded period is
  no longer a whole number of samples, and the resulting leakage would
  land in the realisation scatter and be misread as nonlinear
  distortion.
- **Pretrigger auto-disarmed.** A BLA capture is a fixed-length
  free-run window — the analysis assumes a known number of transient
  periods followed by exactly P steady periods, an assumption a
  threshold-triggered start would break. The run disarms pretrigger for
  you automatically and notes that it did so; your standing pretrigger
  setting is restored afterwards.

## Browser-path: output latency {#browser-path-output-latency}

On the browser (Web Audio) path there is no hardware-synchronised
start the way an NI shared clock gives you — scheduling the output
buffer and the audio graph's own output latency both eat into the
window the run treats as "transient". Keep the **transient** period
count at its default (2) or higher on this path, so the discarded
window reliably clears both the structure's own settling time and the
browser's timing slop before the analysis starts counting steady-state
periods.

## Running the measurement

**Start** runs the whole thing: `M × n_exc` ordinary one-shot captures,
in sequence. When Start is disabled, the reason is shown next to
whichever control it applies to (an out-of-range band, a duplicated
measured-x channel, no response channels left, and so on).

### Watching it run

Progress is a **grid**: one row per realisation, one cell per
excitation, so the shape of the grid is the shape of the run. Cells are
outlines until they run, fill left-to-right while their capture is in
flight, and go solid when it lands. Beside it, `capture 3/12 · ~9 s
left` counts captures rather than asking you to multiply realisation
and experiment indices together.

**stop after this capture** does exactly that: the capture in flight
completes (a half-played multisine is a useless set) and the run stops
before the next one. Whatever landed is kept as ordinary time sets, and
the grid stays on screen so you can see which captures you came away
with.

The individual captures land as ordinary `TimeData` sets, named
`<test name> r<m>e<e>` — but **hidden by default** in the tray and
legend, since a typical run's `M × n_exc` captures would otherwise flood
both. A **show raw captures** button in the results group reveals them
(and hides them again); they are perfectly normal time sets you can
inspect, plot or delete like any other.

Once the run finishes, the analysis runs once (`computing BLA…` — there
is no progress for this phase, it is a single call) and the view jumps
to **TF**, now showing one BLA line per excitation. Each result line is
named after the **response channel** it came from (`resp ch 1`), not a
bare `ch_1`: a BLA set's columns are only the response channels, so
their numbering is not the capture's.

### Running again: replace, or keep both {#replace-or-keep}

Once a run has landed, Start grows a **previous run** choice:

- **replace previous** (the default) removes the last run's raw
  captures and BLA sets before the new one begins, so iterating on a
  design does not silently pile up sets you will never look at again.
  A toast offers a one-click **Undo** that puts them all back —
  visibility, channel labels and all — if you did not mean it.
- **keep both** leaves the last run alone and names the new one apart:
  `bla#2 r1e1`, `bla#2 BLA q1 (via ch0)`, then `bla#3`, and so on. This
  is what you want for a [level sweep](#level-sweeps), where the whole
  point is comparing runs. Renaming the **test** field between runs
  does the same job and needs no suffix.

**new run** clears the run state without deleting anything: the landed
sets stay in the tray and the raw captures are un-hidden as the card
lets go of them, so nothing is ever left hidden with no control to
reveal it.

## Reading the results

Because a BLA result is an ordinary `TfData` object under the hood,
every other TF-consuming view already works on it with no
special-casing — Bode, Nyquist, phase, real/imag, figure export, and
[modal fitting](modal-fitting.md) all apply exactly as they do to any
other transfer function.

### The σ overlay

On the **magnitude** view (including the magnitude pane of Bode), each
BLA line draws with two extra thin dashed lines on the **same dB
axis**:

- **σ_NL**, in the line's own colour (dimmer) — the nonlinear-distortion
  level, and
- **σ_n**, in neutral grey — the measurement-noise level.

A **σ lines** toggle (on the TF card, and mirrored on the Nonlin card
itself, since results appear over the TF view while the Nonlin stage
stays active) hides both. The σ lines carry no entry in the plot legend
— they annotate a channel rather than being channels of their own — so
the Nonlin card shows a small **key** beside that toggle with the two
dash swatches in their real colours, plus a one-line reminder of what
they are and the `√M` step to the BLA's own error bar.

A **gap** in the σ_NL line at some frequency does not mean "no
distortion was measured there" — it means the estimator's floor
(`max(scatter − noise, 0)`) landed at exactly zero, i.e. **no
distortion above what this run can resolve at that line**. A run with
more realisations (M) or periods (P), or a higher excitation level, can
push that resolution further and reveal distortion a coarser run
missed.

Both σ values are **per-realisation** standard deviations — the
distortion/noise level present in *one* realisation, not the
uncertainty on the plotted BLA line itself, which is `√M` better
(`σ_BLA = σ_tot / √M`). That is the classic Schoukens presentation: the
σ lines answer "how nonlinear is this system at this excitation level",
and you divide by `√M` yourself to get the BLA's own error bar.

### Verdict lines

Each excitation gets a one-line, plain-English verdict, e.g. *"linear
below 800 Hz; nonlinearity dominates 800–5000 Hz — level-dependent,
repeat at 2–3 amplitudes"*. Under the hood this splits the excited band
into a few log-spaced sub-bands and compares the median σ²_NL against
the median σ²_n in each; a band reads as nonlinearity-dominated once the
ratio clears a small safety margin above 1 (so the verdict does not
flip on the estimator's own scatter at low M), and the sentence merges
neighbouring bands that agree. The verdict for a multi-response
excitation is judged on its **worst** response channel — a distortion
that shows on any one response channel is a real distortion.

### Level sweeps

Nonlinearity is level-dependent, so one run at one amplitude only tells
you about that amplitude. Repeat the run at **2–3 different levels**
(the verdict text says so whenever a band reads nonlinear), switching
the previous-run choice to **keep both** (or renaming the test field)
so the runs [coexist](#replace-or-keep) instead of replacing each
other. Their sets then overlay in the TF view through the ordinary
tray/legend controls, showing where the distortion grows with level.
Automated level sweeps are not built yet — see `TODO.md`.

## Saving and re-analysing in Python

A `.dvma` save carries **everything** the run produced — the (normally
hidden) raw captures and the BLA result sets alike — so reopening the
file, in the web logger or in Python, restores the full picture. Each
BLA `TfData` also carries the exact run specification it was computed
from (band, Δf, M, P, transient periods, seed, x-mode, channel roles)
in its `.bla` attribute, which is exactly the `run_spec` argument
[`calculate_bla`](../api/analysis.md) takes — so a saved run can be
recomputed (after an analysis-code change, say, or just to verify) with
no need to remember or re-enter the design:

```python
import pydvma as dvma

data = dvma.load_data('bench_run.dvma')
raw = [d for d in data.time_data_list if d.test_name.startswith('bla r')]  # (m, e) order, as recorded
run_spec = data.tf_data_list[0].bla        # the run spec the web logger saved alongside the result
tf_list = dvma.calculate_bla(raw, run_spec)
```

The excitation waveforms themselves come from `multisine_generator` —
the same function the web logger's bridge path calls per capture — so a
fully scripted (no-UI) BLA run is also possible: build a `run_spec`,
loop `multisine_generator` + `log_data(settings, output=y)` over
`(m, e)`, and hand the resulting capture list to `calculate_bla` exactly
as above. See the [Acquisition](../api/acquisition.md) and
[Analysis](../api/analysis.md) API references for both functions.

Next: [Modal fitting](modal-fitting.md), or
[saving and exporting](export.md).
