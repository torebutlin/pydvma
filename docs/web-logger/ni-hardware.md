# National Instruments Hardware

A browser can't reach NI hardware. The web logger drives it through
pydvma running on the lab PC, where `pydvma-serve` (or `dvma.launch`)
serves the app and talks to the NI-DAQmx driver for it. The same
recording code runs when you record from Python, so this page applies to
both.

## Getting started

1. Install the NI-DAQmx driver and pydvma's NI support. NI-DAQmx runs on
   Windows and Linux only. See
   [Installation](../getting-started/installation.md#national-instruments-hardware).
2. Start the app on the lab PC with `pydvma-serve --open`, or
   `dvma.launch()` from a notebook. See [Running locally](running-locally.md).
3. In **Setup**, pick your NI device from **input device**. NI devices
   are listed with any soundcards. Press **Full ▾** to reveal the
   **NI-DAQ** section, described [below](#ni-daq-controls-in-setup).

`pydvma-serve --list-devices` shows the NI devices pydvma can see, and
`pydvma-serve --driver nidaq --open` makes an NI device the app's
**Default**. From Python, `dvma.list_available_devices()` lists the
devices, and `dvma.suggest_ni_settings(index)` returns safe settings for
one.

## Devices and how they differ

| Device | Sampling | Analogue output | IEPE | Notes |
| ------ | -------- | --------------- | ---- | ----- |
| **USB-6003** | multiplexed | software-timed, up to about 5 kS/s | no | Low cost. One converter scans the channels. No anti-alias filter. |
| **USB-6212** | multiplexed | hardware-timed | no | One converter scans the channels. No anti-alias filter. |
| **cDAQ-9174 chassis** | simultaneous | hardware-timed | yes, on the 9234 | Delta-sigma (DSA) modules with a converter for each channel. Examples: the NI 9234 (4 inputs, IEPE, pseudo-differential only, AC coupled with a high-pass near 0.5 Hz) and the NI 9260 (2 BNC outputs, up to ±4.24 V). |

**Multiplexed or simultaneous** matters for phase-sensitive work such as
transfer functions and mode shapes. On the multiplexed USB devices the
channels are sampled one after another, which leaves a small fixed time
offset between them, and the maximum sample rate is shared between the
channels you record. A DSA module samples every channel at the same
instant. It also filters against aliasing in the converter itself, at a
setting tied to the sample rate, while the USB-6003 and USB-6212 have no
such filter. The [digital low-pass](acquisition.md#digital-low-pass)
gives them one.

A cDAQ chassis appears as a single device. Your channel count runs
across its input modules in slot order, and output-only modules are
skipped, so 8 channels on a chassis with two 4-channel input modules
spans both. The
[Python guide](../user-guide/acquisition.md#cdaq-chassis-with-multiple-modules)
has the channel table.

## Sample rate ladders and coercion

Measurement hardware often runs only a fixed set of sample rates. A DSA
module such as the 9234 runs at 51.2 kHz divided by a whole number from
1 to 31, so you can ask for a rate it doesn't have. The USB-6003 and
USB-6212 divide their clocks finely enough to count as continuous, but
still round a little: the 6003 runs a 48 kHz request at 48019.2 Hz.

A DSA module moves an off-ladder request to the nearest rate it has. On
a 9234, 8000 Hz runs at 8533.33 Hz and 5000 Hz at 5120 Hz. pydvma reads
back the rate the hardware is really running and uses it for every time
and frequency axis, so your data is scaled correctly. Setup and Acquire
show a note such as `device runs at 8533.3 Hz (requested 8000)`.

The **sample rate** field in Setup takes any rate you type. The arrow
beside it lists common rates within the device's limits; on a DSA module
not every one is a rate it runs.

The output side works the same way. A DSA output module such as the
9260 also rounds its rate onto its own ladder, so pydvma resamples your
stimulus onto the rate the module really runs. A 30 s sweep therefore
still lasts 30 s.

!!! tip
    Pick a rate the module runs and nothing is rounded. If you need an
    exact arbitrary rate, a USB-6212 or USB-6003 gets closest.

A soundcard is handled the other way round: pydvma captures at a rate
the hardware runs and resamples to yours. See
[Capture rate and delivered rate](acquisition.md#capture-rate-and-delivered-rate).

## NI-DAQ controls in Setup

Setup shows these in its **NI-DAQ** section, under **Full ▾**, whenever
NI hardware is available.

- **terminal configuration** offers **default**, **RSE**, **NRSE** and
  **diff**. **default** is RSE. If the device can't do the mode you
  choose, pydvma uses one it can and prints a note in the terminal where
  `pydvma-serve` is running; the app does not show it. A 9234 supports
  only pseudo-differential, which pydvma then uses, so leave it at
  **default**.
- **NI voltage range (±V)** sets the **in** range and the **out** range,
  both 5 V to start with. Each is limited to the device's real range,
  shown beside the fields as `rail in ±… out ±… V`. The 9260 tops out at
  ±4.24 V, below the 5 V start, so its output range is set to that, with
  a note.
- **IEPE off** or **IEPE 2 mA**, described [below](#iepe-excitation).

The input range is the full scale of the input, and a smaller range
gives finer resolution. The hardware only has certain ranges, though,
and rounds your request up to one it has: a 9234 is fixed at ±5 V
whatever you enter, and a USB-6212 asked for ±1 V runs at ±2 V. pydvma
reads back the range the device is really using, and the level meters
and the clip warning judge against it.

## IEPE excitation

A DSA module with built-in excitation, the 9234, can power IEPE/ICP
accelerometers directly. Choose **IEPE 2 mA** for the sensors, or **IEPE
off**. Those are the only two currents a 9234 accepts. Switching it on
puts the inputs into AC coupling and adds about 2 seconds to the first
capture while the sensors' DC bias settles.

!!! warning "The app's IEPE switch applies to every channel"
    **IEPE 2 mA** powers all the channels you record. Forcing excitation
    current into a channel that has no IEPE/ICP sensor, such as a
    charge amplifier's output, a signal generator or a loopback from an
    output, can damage what is connected. The app has no per-channel switch, and a list given to
    `dvma.launch` or `pydvma-serve --settings` is cut to its first
    entry, which then applies to every channel.

    If some channels carry IEPE sensors and others don't, record from
    Python with one current for each channel, here IEPE on channels 0
    and 1 only:

    ```python
    settings = dvma.MySettings(
        device_driver='nidaq', channels=3,
        iepe_excit_current_A=[0.002, 0.002, 0.0],
    )
    ```

    Then save the result with `dvma.save_data` and open the file in the
    app. The
    [worked example](../user-guide/acquisition.md#worked-example-iepe-accelerometers-on-a-cdaq)
    goes through a complete recording with calibration.

## Output and trigger

An output stimulus plays from the device's analogue outputs during the
capture, and is limited to the output range above. A pretrigger catches
transients. See [Output stimulus](acquisition.md#output-stimulus) and
[Pretrigger](acquisition.md#pretrigger).

## If a capture has gaps

If the computer falls behind the hardware, the app pins a **capture
integrity** message after the capture. The data has gaps, and transfer
functions and coherence computed from it can't be trusted, so record it
again. See [Capture integrity](../user-guide/acquisition.md#capture-integrity).
