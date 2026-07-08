# Calibration and units

Captures are always stored in **volts**. To read results in engineering
units (g, m/s², N, Pa, …) you attach a per-channel **sensitivity** and
**unit**; the web logger then scales plots, spectra, transfer functions
and fits at display time. Because the stored samples stay in volts,
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

Enter the sensitivity in **volts per unit** (V/eu). The denominator
label next to the box reflects the chosen unit (e.g. `V / (m/s²)`).
Click **Apply** to scale the data, or **Cancel** (or Esc) to dismiss.

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

- **plots** multiply each channel by its factor, so axes read in
  engineering units;
- **FFT / PSD / sonogram** copy the factors and units onto the derived
  spectra; and
- a **transfer function** inherits the calibration *ratio* — its unit is
  built as `output-unit / input-unit` (e.g. a `g/N` accelerance).

All of this is saved in the [`.dvma` file](dvma-format.md) as the
`channel_cal_factors` and `units` fields, so calibrated data reopens
calibrated — in the web logger, in Python, or in the JupyterLite
notebook.

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
    enabled** — it is on the roadmap. For now, enter sensitivities from
    the sensor's calibration sheet.
