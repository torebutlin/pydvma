# Calibration and units

Calibration turns the numbers you recorded into engineering units. You
give each channel a **sensitivity** and a **unit**, and the plots,
spectra, transfer functions and fits all read in those units (m/s², N,
Pa, …). When you know a transfer function's true level but not the
sensors', you can instead
[calibrate the transfer function directly](#calibrate-a-transfer-function-directly).

Your recorded samples are never changed. Calibration is a multiplier
applied when data is displayed or fitted, so you can set it, or correct
it, after recording. Clip detection still works against the true input
voltage.

## What your samples are

Before calibration, a capture is in volts or in fractions of full
scale, depending on the input:

| Input | Samples are |
| ----- | ----------- |
| An NI-DAQ device | volts, read directly from the device |
| A soundcard or audio interface whose full scale is known ([below](#soundcard-input-gain-and-full-scale)) | volts |
| Any other soundcard, or recording in the browser | fractions of full scale, between -1 and 1 |

## Calibrate a channel

1. In the tray, hover a dataset's card and press **cal**.
2. In the dialog, each channel has a **sensitivity** box and a unit
   menu. Enter the sensitivity in **volts per unit**, from the sensor's
   calibration sheet, and pick the unit: **V**, **m**, **m/s**,
   **m/s²**, **N** or **Pa**. A different unit already on the channel
   stays in the menu.
3. Press **Apply**. **Cancel**, or Esc, closes the dialog with no
   change.

The label beside each box shows what it means, for example
`V / (m/s²)`. The dialog also shows a disabled **known-input
calibration…** button, which is not available.

To remove a calibration, set the sensitivity to 1 and the unit to
**V**. A sensitivity of zero, or one that isn't a number, counts as 1.

If the label reads `FS / (m/s²)` and a note appears above the rows, the
samples are fractions of full scale. Either enter each sensitivity as
full scale per unit, or [state the full scale](#soundcard-input-gain-and-full-scale)
first and work in volts.

!!! tip "Reading the sensitivity off the calibration sheet"
    Sheets usually give **millivolts** per unit, so divide by 1000: a
    2.3 mV/N force transducer is `0.0023`. A common slip is entering
    `100` for a 100 mV/unit sensor instead of `0.1`, which scales
    results by 1000.

    Accelerometers are usually rated in mV/g, and the menu offers m/s²,
    not g, so divide by 9.81 as well: 100 mV/g is `0.0102` V/(m/s²). To
    read in g instead, give the channel the unit `g` from Python. The
    dialog keeps it, and `0.1` is then right for 100 mV/g.

## Calibrate a transfer function directly

Sometimes the transfer function's true level is known when neither
sensor's sensitivity is. A mass on a soft spring is the classic case:
above its bounce frequency it behaves as a free mass, so its accelerance
(acceleration over force) is exactly `1/m`. Measuring it gives the one
factor that calibrates the whole measurement chain, and every transfer
function measured with the same sensors and settings can then be
multiplied by it.

The calibrate dialog takes this factor directly:

1. Record the measurement and press **Calc TF**.
2. Hover the dataset's card in the tray and press **cal**. Below the
   channel rows, a **Transfer function** section has one row per line,
   labelled like the legend (`ch_1/ch_0`).
3. Type the **factor** to multiply the measured transfer function by, and
   pick its unit as response over reference, for example **m/s** over
   **N**.
4. Press **Apply**.

The factor is a plain multiplier, not a sensitivity: it is the number
the measured transfer function must be multiplied by to give the actual
values. Enter the unit of the transfer function as measured, before any
[x(iω)](analysis.md#scaling-xi-and-best-match) scaling, because the
axis moves the response unit along `m`, `m/s`, `m/s²` by itself as you
change the power.

A blank factor follows the channel calibration. The box then shows, in
grey, the factor the channels give, and the unit menus show the
channels' units. **↺** clears a factor you set. If the set has no
transfer function yet, the dialog says to calculate one first.

!!! example "Working out the factor from a free mass"
    Measure the mass's transfer function and view it as acceleration over
    force. If you measured velocity, set **x(iω)^** to `1`. Above the
    bounce frequency the magnitude is a near-flat line. Read its level,
    say −28 dB, and convert it back to linear: 10^(−28/20) = 0.0398.
    For a 0.3 kg mass the true value is 1/0.3 = 3.33 kg⁻¹, so the factor
    is 3.33 / 0.0398 = 83.7.

    The factor is the true value divided by the measured one, not the
    level of the flat line itself.

A transfer function factor changes the **transfer function view**, the
[modal fit](modal-fitting.md) and [Best match](#best-match-sets-the-transfer-function-calibration).
The time, FFT, power, PSD and CSD views keep using the channel
calibration, because the factor calibrates the ratio, not either sensor.
A factor is tied to the transfer function's input channel: if you change
**in** on the TF card, it no longer applies until you change it back.

To calibrate other measurements with the same factor, open each one's
dialog and enter it there.

!!! note "A transfer function averaged across sets"
    An **across sets** transfer function is drawn on the first set that
    qualifies, so set its factor on that set's card. Transfer functions
    averaged across sets are not stored in the `.dvma` file, so Python
    does not see this one.

A dataset that holds only a transfer function, with no time data, has
no channel calibration underneath. Its dialog shows only the
**Transfer function** section, and every line always has a factor.

## How it is stored

Each channel keeps a **cal factor**, the reciprocal of the sensitivity
(a 0.1 V/unit sensor has a factor of 10). The
[`.dvma` file](dvma-format.md) stores the factors and units, so
calibrated data reopens calibrated, in the browser, served locally, in
Python and in JupyterLite. CSV and MATLAB exports, from the app or from
Python, write the values as recorded and the factors and units beside
them; see [What each output holds](export.md#what-each-output-holds).

A transfer function factor is saved with the set, and is written into
the saved transfer function's own factors and units, which is where
Python keeps them. `data.tf_data_list` therefore comes out calibrated in
a notebook, and so do the CSV and MATLAB exports.

**From Python**, pass `channel_sensitivities` in `MySettings` when you
record with `dvma.log_data`, or set the factors afterwards. See
[Setting or correcting calibration after logging](../user-guide/acquisition.md#setting-or-correcting-calibration-after-logging).
A transfer function factor set in Python with
`data.tf_data_list.set_calibration_factor` shows in the dialog when the
file is opened in the web logger.

## What calibration changes

- **Time and FFT** plots multiply each channel by its factor, so axes
  read in the channel's unit.
- **Power** carries the factor squared, and reads in `unit²`.
- **PSD** is the same power divided by the analysis window's effective
  noise bandwidth, and reads in `unit²/Hz`.
- **CSD** shows the cross-spectrum magnitude of a channel pair, scaled
  by both channels' factors, and reads in `unit_i·unit_j`.
  **Coherence** is a ratio and never changes with calibration.
- **Transfer functions** use the ratio of the output and input factors,
  and read in output unit over input unit, with a compound unit in
  brackets: `(m/s²)/N`. A
  [transfer function factor](#calibrate-a-transfer-function-directly)
  replaces that ratio, with its own unit. The BLA uncertainty bands
  drawn with a transfer function scale the same way.
- **Sonograms** are drawn relative to their own peak, so calibration
  leaves them unchanged.
- **Modal fits** run on the calibrated transfer function, so the modal
  constants come out in engineering units. Natural frequencies, damping
  ratios and Q do not depend on the scale.

Axes only show `(V)` where the samples really are volts. For fractions
of full scale an uncalibrated axis reads just `Amplitude`.

!!! warning "Changing a calibration under an existing fit"
    A fit's modal constants stay in the units that were in force when
    you fitted. If you change the calibration afterwards, the app names
    the set in a message. Fit again to update the constants; the
    frequencies, damping ratios and Q are unaffected. The fit is never
    re-run for you, because that would discard modes you rejected or
    refined by hand.

## Best match sets the transfer function calibration

The **TF** stage's **Best match** rescales every transfer function onto
a reference channel (see
[Scaling: x(iω) and Best Match](analysis.md#scaling-xi-and-best-match)).
It matches the reference as displayed, including any transfer function
factor, so other measurements land on a calibrated reference's level.
Calibrate one measurement directly, choose it as the reference, and Best
match brings the rest onto it.

The results are stored as each line's
[transfer function factor](#calibrate-a-transfer-function-directly), so
they show in this dialog afterwards, and each rescaled line takes the
reference's unit. Channel calibrations are never changed, so time and
spectrum views stay as they were.

A transfer function that already reads at a calibrated level, from a
factor or from its channels, has that level replaced. So Best match
asks first, naming those measurements, and its result message has an
**Undo** that puts the previous factors back.

## Soundcard input gain and full scale

An audio interface delivers samples between -1 and 1. To read them as
volts, pydvma needs the input's **full scale**: the voltage that reads
as 1. On an interface with a preamp that depends on the gain knob, and
no software can read the knob. So you state the gain, and pydvma works
out the full scale from the interface's published maximum input level.

Served locally, open **Setup**, press **Full ▾** and find **levels**.
What you see depends on the interface:

- **An interface pydvma has a profile for, with a preamp** (a Scarlett
  2i2 4th Gen, for example): **input gain (for calibrated volts)** in
  dB, and an input mode (**line**, **inst** or **mic**). Setup shows the
  full scale that follows as `full scale ≈ … V pk`.
- **A fixed-gain interface** (the ESI U24 XL): nothing to enter. Setup
  shows its constant full scale.
- **Any other interface**: **full scale (for calibrated volts)**, in
  volts peak. Measure it once with a known source, or take it from the
  maker's specification. Left blank, captures stay in fractions of full
  scale.

Setup also shows a note under the device saying whether its full scale
is known, for example `calibrated: full scale 1.882 V peak`. Full scale
is fixed when you record, so state it first, and state the new gain if
you change the gain on the interface. Sensitivities can be changed at
any time.

Recording in the browser has no gain or full-scale field, because a
browser can't know the interface's gain. Its captures are fractions of
full scale, so calibrate them against full scale in the dialog, or
record locally.

**From Python**, when you record with `dvma.log_data`, give `MySettings`
the gain. For an interface pydvma has no profile for, give the full
scale instead, as `VmaxSC=` in volts peak.

```python
settings = dvma.MySettings(
    device_driver='soundcard',
    input_gain_db=9,        # what the front panel says
    input_mode='line',      # 'line', 'inst' or 'mic'
)
```

A stated gain overrides an explicit `VmaxSC`. `dvma.verify_input_scaling()`
measures the full scale against a signal generator, and
`pydvma-serve --list-devices` shows what pydvma knows about each
interface. The formula, and the interface levels it uses, are in
[Deriving VmaxSC from the preamp gain](../user-guide/acquisition.md#deriving-vmaxsc-from-the-preamp-gain).
`dvma.launch` and `pydvma-serve --settings` don't carry these two
settings into the app, and they don't carry `channel_sensitivities`
either. Enter the gain or full scale in Setup as above, and the
sensitivities in the calibration dialog.
[Pre-filling Setup](running-locally.md#pre-filling-setup) lists what a
launch does fill in.

## IEPE accelerometers on NI hardware

Switch on the excitation in Setup (see
[IEPE excitation](ni-hardware.md#iepe-excitation)), then enter each
sensor's sensitivity here.
