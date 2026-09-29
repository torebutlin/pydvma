# Noise & nonlinearity separation (Nonlin stage)

The **Nonlin** stage measures how linear your structure is. It runs a
**Schoukens random-phase multisine** measurement: a structured set of
captures that gives three things at every frequency line: the **best
linear approximation** (BLA) of the frequency response, the level of the
**measurement noise**, and the level of the **nonlinear distortion**.

An ordinary transfer function cannot give you that split. Coherence drops
for noise, for a poor reference and for nonlinearity alike, with no way to
tell which. The Nonlin stage answers "is my structure behaving linearly at
this excitation level, and if not, where?"

## What the method measures

The excitation is a **multisine**: a periodic signal built from many
sinusoids at random phases across your band. A run plays **M
realisations**, each with fresh random phases, and captures **P repeated
periods** of the steady-state signal in each.

- The scatter **between periods** of one realisation is measurement
  **noise**, because an identical repeated input can only give different
  outputs through noise.
- The scatter **between realisations** is noise plus **nonlinear
  distortion**. A nonlinear system responds differently to different
  combinations of the same lines; a linear one adds nothing beyond the
  noise.

Subtracting the noise variance from the realisation variance leaves the
distortion. The result is a transfer function with two extra lines,
**σ_NL** (nonlinear distortion) and **σ_n** (noise), both standard
deviations in the same linear units as the transfer function. See
[Reading the results](#reading-the-results).

The method handles one or several driven outputs against any number of
measured responses, including non-square systems such as one output
driving three response channels.

## Run a measurement

1. Wire each output you will drive into an input channel: a loopback
   cable, or a force gauge on a hammer or shaker rig. This input measures
   the drive.
2. Open **Nonlin**. Set the **band (Hz)** to excite and the resolution
   **Δf**.
3. Set the **level**, then **M**, **P** and **transient** (see
   [Design](#design-setting-up-a-run)).
4. In **excitations**, tick each output to drive, and for each choose
   **measure on ch N**: the input channel wired to it.
5. Check the run time shown beside the card's title, then press **Start**.
6. The view moves to **TF**, showing one BLA line per excitation with
   dashed σ lines. Read the verdict on the Nonlin card.

## Getting to the Nonlin stage

Nonlin drives an output and makes its own captures, like **Acquire**, so
it needs a live input. It is disabled when you have only loaded a saved
file. It works in the browser or [served locally](running-locally.md).

## Design: setting up a run

The first row of the Nonlin card holds the design. The card starts with a
band of 20 to 2000 Hz, Δf of 5 Hz, level 0.1, **M** 6, **P** 4 and
**transient** 2. The **test** box sets the base name for the run's sets
(`bla` to start with).

### Band and resolution

- **band (Hz)**: the range to excite, from a start to an end frequency.
- **resolution / period**: **Δf** in hertz and **T** in seconds are two
  boxes for one quantity, and you can type into either. The multisine's
  period is a whole number of samples, `N`. Typing a resolution gives
  `N = round(fs / Δf)`; typing a period gives `N = round(T · fs)`. The
  card shows the result beneath (`N = 4096 samples · 993 lines`). A typed
  period is rounded to whole samples, so the Δf box comes back showing the
  resolution you can actually have.

A finer Δf needs a longer period, and every realisation captures several
whole periods, so halving Δf doubles the run. Choose the coarsest Δf that
still resolves what you care about, and watch the
[total time](#total-time).

### Level

**level** is the RMS amplitude of each excitation. It is in volts on an NI
output (up to the output rail), and a fraction of full scale (rail ±1) on
a soundcard or in the browser.

A random-phase multisine's peak is several times its RMS and varies from
one phase draw to the next. So **Start** generates every one of the
`M × n_exc` waveforms first and checks each peak against the output rail
before playing anything. If any would clip, the run refuses and asks you
to lower the level.

### Averaging: M, P, transient

- **M** (realisations, at least 2): raise it for a cleaner split of σ_NL
  and σ_n. The BLA itself also improves as `1/√M`.
- **P** (steady-state periods per capture, at least 2): raise it for a
  lower noise floor σ_n, at the cost of longer captures.
- **transient**: periods played and discarded before the analysis window
  starts, so the structure settles after each new phase draw. Raise it for
  heavily damped or low-frequency structures. In the browser, keep it at
  2 or more (see [below](#browser-path-output-latency)).

### Total time {#total-time}

The headline beside the card's title is the run's whole duration, updated
as you edit:

```
≈ 12.4 s
12 captures × 1.03 s
```

In the **responses · run length** group, the readout `6 realisations × 2
excitations × 6 periods (2 transient + 4 steady)` shows where it comes
from, so you can see which factor to cut.

The run sets its own capture length, one whole window of
`transient + P` periods per capture, and says so on the card. It
overrides the **duration** on Acquire while the run is going and restores
it afterwards.

### Excitations and responses

The **excitations** table has a row for each output channel the device
can drive, up to eight, labelled `ao0`, `ao1` and so on. For each row:

- tick it to drive that output during the run; and
- choose its **x source**, where the analysis reads that excitation's
  actual drive.

The rows you tick must start at `ao0` with no gaps. Every input channel
that is not carrying a measured drive becomes a **response**. The
`responses:` readout lists them, so you don't assign them yourself.

#### Measuring the drive

Every driven output needs its drive measured on an input channel. Choose
**measure on ch N** and wire that output into input `N`. This works on
every device because the drive and the responses share one ADC clock: the
unknown moment at which the output starts rotates all their spectra by
the same phase, and that cancels in the analysis.

A **commanded drive** option is listed, but it is disabled on every
device. The output starts at an arbitrary point relative to the capture
each time, and without measuring the drive that random offset would show
up as extra scatter, indistinguishable from nonlinear distortion.

## What the run sets for you

A Nonlin run is stricter than an ordinary log. **Start** checks these
before it proceeds:

- **Output rate equals sample rate.** The multisine is an exact whole
  number of samples per period, so a different drive rate would break it.
  When served locally, a device that limits its output rate below your
  sample rate blocks the run: lower the sample rate.
- **Digital low-pass off.** That mode resamples the capture, which makes
  the period a non-integer number of samples. The leakage would look like
  distortion.
- **Pretrigger disarmed.** A run is a fixed-length free-running window, so
  pretrigger is switched off for it, a note says so, and your setting is
  restored afterwards.

If **Start** is disabled, the reason appears beside the control it
concerns: for example a band above the Nyquist frequency, the same input
channel used as the drive for two excitations, or no response channels
left.

## Browser: output latency {#browser-path-output-latency}

In the browser there is no hardware-synchronised start. Scheduling the
output and the browser's own output latency eat into the window that the
run treats as transient. Keep **transient** at 2 or more so that the
discarded window clears both the structure's settling and the browser's
timing slop.

## Running the measurement

**Start** runs `M × n_exc` ordinary one-shot captures in sequence.

### Watching it run

Progress is a grid with a row for each realisation and a cell for each
excitation. Cells are outlines until they run, fill while their capture is
in flight, and go solid when it lands. Beside it, `capture 3/12 · ~9 s
left` counts captures.

**stop after this capture** lets the capture in flight finish, since a
half-played multisine is useless, and stops before the next. Whatever
landed is kept, and the grid stays so you can see what you have.

The captures land as ordinary time sets named `<test> r<m>e<e>`
(`bla r1e1`), **hidden** in the tray and legend because there can be many.
**show raw captures** reveals them, and **hide raw captures** hides them
again. They are normal sets you can inspect, plot or delete.

When the captures are done, the analysis runs (**computing BLA…**) and the
view moves to **TF** with one BLA line per excitation. Each is named after
the response channel it came from, such as `resp ch 1`.

### Running again: replace, or keep both {#replace-or-keep}

Once a run has landed, a **previous run** choice appears before **Start**.

- **replace previous** (the default) removes the last run's raw captures
  and BLA sets when the new run starts, so iterating on a design doesn't
  pile up sets. A message offers **Undo** to bring them all back.
- **keep both** leaves the last run alone and names the new one apart:
  `bla#2 r1e1`, `bla#2 BLA q1 (via ch0)`, then `bla#3`, and so on. Use it
  for a [level sweep](#level-sweeps). Changing the **test** name between
  runs has the same effect.

**new run** forgets the run state without deleting anything. The landed
sets stay in the tray, and the raw captures are shown again.

## Reading the results

A BLA result is an ordinary transfer function, so everything that works on
one works on it: Bode, Nyquist, phase, real and imaginary, figure export
and [modal fitting](modal-fitting.md).

### The σ overlay

On the magnitude view (and the magnitude pane of Bode), each BLA line has
two thin dashed lines on the same dB axis:

- **σ_NL**, in the line's colour but dimmer: the nonlinear-distortion
  level.
- **σ_n**, in grey: the measurement-noise level.

The **σ lines** switch, on the TF card and on the Nonlin card, hides both.
They have no legend entry; the Nonlin card shows a small key beside the
switch.

A **gap** in σ_NL does not mean "no distortion". It means the distortion
was too small for this run to resolve at that line. More realisations,
more periods or a higher level can reveal distortion that a coarser run
missed.

Both σ values are **per realisation**: the distortion or noise level in
one realisation, not the uncertainty of the plotted line. That is `√M`
smaller, `σ_BLA = σ_tot / √M`. So σ shows how nonlinear the system is at
this level, and you divide by `√M` yourself to get the error bar on the
BLA.

### Verdict lines

Each excitation gets a plain-English verdict, for example *"linear below
800 Hz; nonlinearity dominates 800–5000 Hz — level-dependent, repeat at
2–3 amplitudes"*. It summarises which parts of the band have more
distortion than noise. With several responses it reports the worst one.

### Level sweeps

Nonlinearity depends on level, so one run tells you about one amplitude.
Repeat the run at two or three levels, with **keep both** (or a different
**test** name) so the runs [coexist](#replace-or-keep). Their sets then
overlay on the TF view through the tray and legend, showing where the
distortion grows with level. Each level is a separate run; there is no
automatic sweep.

## Saving and re-analysing in Python

**Save Dataset** stores everything the run produced: the raw captures and
the BLA sets. Each BLA set also carries the run specification it was
computed from in its `bla` attribute, which is the `run_spec` argument of
[`calculate_bla`](../api/analysis.md). It holds the multisine settings
(`n_samples`, `k1`, `k2`, `p_periods`, `t_periods`, `seed`, `amp_rms`,
`n_exc`, `M`), the x mode, the input channels that carry the drive and the
response channels, and the sample rate. You can recompute a saved run
without re-entering the design:

```python
import pydvma as dvma

data = dvma.load_data(filename='bench_run.dvma')
raw = [d for d in data.time_data_list if d.test_name.startswith('bla r')]
run_spec = data.tf_data_list[0].bla     # saved with the result
tf_list = dvma.calculate_bla(raw, run_spec)
```

`raw` must be in run order: realisation, then excitation. Runs kept with
**keep both** have names such as `bla#2 r1e1`, so filter on that prefix
for them.

You can also run a measurement without the app. Build a `run_spec`, then
for each realisation and excitation generate the waveform with
`dvma.multisine_generator(settings, spec)` and record it with
`dvma.log_data(settings, output=y)`. Pass the list of captures to
`calculate_bla`. See the [Acquisition](../api/acquisition.md) and
[Analysis](../api/analysis.md) references.

Next: [Modal fitting](modal-fitting.md), or
[saving and exporting](export.md).
