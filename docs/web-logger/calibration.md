# Calibration and units

Captures are always stored in **volts**. To read results in engineering
units (g, m/s², N, Pa, …) you attach a per-channel **sensitivity** and
**unit**; the web logger then scales plots, spectra, transfer functions
and fits at display time. (What makes the stored samples volts in the
first place is the input's full-scale voltage, fixed at capture time —
see [Soundcard input gain](#soundcard-input-gain-and-full-scale) for the
audio-interface case.) Because the stored samples stay in volts,
calibration is **non-destructive** — you can set or correct it after
recording without losing anything, and clip detection still works against
the true voltage.

This is the same model as the Python interface
([Calibration and scaling](../user-guide/acquisition.md#calibration-and-scaling));
the browser dialog just writes the same `channel_cal_factors` and
`units` that the file format stores.

## The calibration dialog

Open it from the **cal** button on a dataset's card in the tray (it
appears on hover). The dialog shows **one row per channel**:

- the channel's **label**;
- a **sensitivity** value; and
- a **unit** dropdown — **V**, **m/s²**, **N**, **Pa** (any existing
  non-standard unit on the channel is preserved as an option).

Enter the sensitivity in **volts per unit** (V/eu). The label next to
the box reflects the chosen unit (e.g. `V / (m/s²)`). Click **Apply** to
scale the data, or **Cancel** (or Esc) to dismiss.

On a device whose voltage scale pydvma does **not** know, the stored
samples are not volts but full-scale fractions, and the dialog says so:
the label reads `FS / (m/s²)` and a note appears above the rows. Enter
the sensitivity against full scale there, or state the full scale in
Setup first (below) and work in volts as usual.

!!! tip "Reading sensitivity off the cal sheet"
    Manufacturers usually print sensitivity in **mV per unit** — divide
    by 1000 for the V/unit value here. A 100 mV/g accelerometer is
    `0.1`; a 10 mV/g one is `0.01`; a 2.3 mV/N force transducer is
    `0.0023`. A common slip is entering `100` instead of `0.1`, which
    would scale results by 1000×.

## How it is applied and stored

Internally the logger stores a **cal factor** = `1 / sensitivity` per
channel (engineering-units per volt — the multiplier applied to the
stored volts). A sensitivity of 1 leaves the channel unscaled; a zero or
non-finite entry falls back to a factor of 1 (no calibration).

The factor and unit propagate the way they do in pydvma:

- **time and FFT** plots multiply each channel by its factor, so axes
  read in engineering units;
- the **power spectrum** is a power, so the amplitude factor enters
  squared (`× factor²`) and the axis reads in `unit²`;
- the **cross-spectrum** `|S_xy|` of a channel pair carries
  `unit_i · unit_j`, so it is scaled by `factor_i × factor_j`.
  **Coherence is not** — it is a normalised ratio, dimensionless, and
  stays exactly the same however the channels are calibrated;
- a **transfer function** inherits the calibration *ratio* — its unit is
  built as `output-unit / input-unit` (e.g. a `g/N` accelerance) — and so
  do the BLA uncertainty bands drawn with it;
- the **sonogram** is drawn relative to its own peak, so a constant
  per-channel factor cancels and the image is unchanged; and
- a **modal fit** is run on the calibrated transfer function, so its
  modal constants come back in engineering units and its reconstruction
  overlays the measured curve at the same level. Natural frequencies,
  damping ratios and Q are scale-invariant either way.

!!! warning "Re-calibrating under an existing fit"
    Because the fit reads the *calibrated* transfer function, its stored
    modal constants are in the units that were in force when it ran.
    Change the calibration afterwards and they are quietly in the old
    ones — so the logger raises a toast naming the set. Re-fit to bring
    the constants up to date; the frequencies, damping ratios and Q
    values are unaffected and need nothing. The fit is never re-run
    automatically, because that would silently discard rejected modes and
    refinements you may have made by hand.

All of this is saved in the [`.dvma` file](dvma-format.md) as the
`channel_cal_factors` and `units` fields, so calibrated data reopens
calibrated — in the web logger, in Python, or in the JupyterLite
notebook.

## Calibration and the data exports

**Save Dataset** (`.dvma`) and **figure exports** are calibrated: the
file carries the factors and units, and a saved figure carries whatever
its axes showed.

**Export CSV** and **Export Matlab** are different by design — they write
the **raw stored arrays, in volts, with no calibration applied**, so that
what you get is the measurement rather than a view of it. To keep that
honest rather than silent, both now carry the calibration as metadata:

- the **CSV** begins with a commented header naming the per-column
  factors and units. It is prefixed `#`, so `np.loadtxt`,
  `np.genfromtxt` and `pandas.read_csv(..., comment='#')` skip it and
  the numeric rows are unchanged:

    ```
    # pydvma export: RAW data, calibration NOT applied.
    # Column 1 is the shared axis (s); the rest are data columns.
    # Multiply data column k by cal_factors[k] for engineering units.
    # cal_factors: 10,0.5
    # units: m/s2,N
    ```

- the **Matlab** file gains `time_cal_factors` / `time_units` (and the
  `freq_` and `tf_` equivalents) alongside the arrays it always wrote.
  Nothing existing changed, so older scripts keep working.

!!! note "Compound units are parenthesised"
    A transfer function's unit is built as `output/input`, which is
    ambiguous when the numerator is itself a ratio: `m/s2/N` reads
    equally as `(m/s2)/N` (what it means) and `m/(s2·N)` (what it does
    not). pydvma therefore wraps a compound unit before composing it, so
    an accelerance comes out as `(m/s2)/N`. Files written before this
    change keep the string they were written with — it cannot be split
    back into numerator and denominator without guessing, so it is left
    alone rather than rewritten.

## Best match replaces the calibration

The TF stage's **Best match** rescales every transfer function onto a
reference channel — and it stores the result in the *same*
`channel_cal_factors` slot this dialog writes, because a per-channel
display multiplier is the only place pydvma has for it. On an
uncalibrated dataset that is exactly what you want. On a **calibrated**
one it replaces the transducer calibration with a relative scale, while
the engineering units stay as they were: the axis goes on saying `m/s²`
over numbers that have become relative.

So Best match asks first, naming the measurements whose calibration
would be replaced, and the toast it leaves carries an **Undo** that puts
the previous factors and units back.

## Soundcard input gain and full scale

Per-channel sensitivity turns **volts** into engineering units. What
turns the raw ±1 samples an audio interface delivers into volts in the
first place is `VmaxSC` — the jack voltage that reads full scale — and
on an interface that depends on the preamp gain. No audio API exposes
that gain (it is a front-panel knob), so pydvma cannot read it; you
state it instead, at capture time:

```python
settings = dvma.MySettings(
    device_driver='soundcard',
    input_gain_db=9,        # what the front panel / Focusrite Control says
    input_mode='line',      # 'line' | 'inst' | 'mic'
)
```

`VmaxSC` is then derived from the interface's published maximum input
level `L` (in dBu at minimum gain) and the stated gain `G`:

    V_fullscale_peak = sqrt(2) * 0.7746 * 10 ** ((L - G) / 20)

On a Scarlett 2i2 4th Gen `L` is 22 dBu on **line**, 12 on **inst** and
16 on **mic**; the formula was confirmed against hardware to 0.10 dB. A
stated gain takes precedence over an explicit `VmaxSC`, and only applies
to interfaces characterised in `pydvma._soundcard_specs` — any other
device keeps whatever `VmaxSC` you gave it. Note `output_VmaxSC`
defaults to `VmaxSC`, so a derived value moves the output scaling with
it (though the Scarlett's front-panel Output knob is an analogue
control, so output voltage is only repeatable at a marked knob
position).

This is not a second calibration layer — it *derives* the setting that
was always there. The chain stays: raw ±1 → ×`VmaxSC` → volts →
×cal factor (= 1 / sensitivity) → engineering units. The first stage is
fixed when you record; the second is the per-channel sensitivity above,
which you can set or correct at any time. Changing the gain on the
hardware invalidates the first stage, so re-state it when you do.

### Setting it from the app

Open **Setup → full**, section **levels**. What appears depends on what
pydvma knows about the selected interface:

- a **characterised** interface with a preamp shows **input gain (for
  calibrated volts)** plus its input mode, and previews the full scale
  the pair implies;
- a **fixed-gain** interface (e.g. the ESI U24 XL) has nothing to state,
  so it shows its constant full scale as a note;
- an **uncharacterised** interface — no profile, so no published input
  level to derive from — shows **full scale (for calibrated volts)**,
  where you enter the measured volts-peak directly. Leave it blank and
  captures stay in full-scale units; fill it in and the device's
  calibration line in Setup changes to say so.

Measure that number once with a known source —
`dvma.verify_input_scaling()` does it against a signal generator — or
take it from the maker's spec. It can also be set outside the app as
`VmaxSC` in `MySettings`, or in the JSON you hand to
`pydvma-serve --settings` (see
[From the Qt logger](migration.md#pre-seeding-settings-with-settings)).

## Best Match scaling writes here too

The TF card's **[Best match](analysis.md#scaling-xi-and-best-match)**
button (relative TF scaling, the Qt `best_match` tool) does not keep its
own separate factors — it writes the computed scale factors straight into
these per-channel `channel_cal_factors`. So after a Best Match the factors
are visible and editable in this dialog, they persist in the `.dvma` file,
and the scaling is undone by reopening Calibrate and resetting the
affected channels' sensitivities to 1.

## NI IEPE/ICP sensors

When acquiring IEPE/ICP accelerometers through the bridge, enable the
excitation in Setup's [NI-DAQ group](acquisition.md#ni-daq-options-bridge-only)
and set each sensor's sensitivity here (or in `MySettings` at capture
time). See the worked cDAQ recipe in the
[Python acquisition guide](../user-guide/acquisition.md#worked-example-iepe-accelerometers-on-a-cdaq).

!!! note "Guided (known-input) calibration"
    A **known-input calibration** helper (calibrate against a reference
    signal of known level) is stubbed in the dialog but **not yet
    enabled** — it is on the roadmap. It is not the only route to a
    calibrated result, though: enter sensitivities from the sensor's
    calibration sheet, and on a characterised audio interface state the
    preamp gain rather than measuring the input full scale
    ([above](#soundcard-input-gain-and-full-scale)).
