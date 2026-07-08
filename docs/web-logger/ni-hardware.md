# National Instruments hardware over the bridge

National Instruments DAQ hardware cannot be reached from a web browser
directly — there is no browser API for it. The web logger drives NI
hardware through the local **`pydvma serve` bridge**: a small Python
process on the lab PC that owns the `nidaqmx` driver and streams data
to the browser over a WebSocket. See
[Acquisition and setup](acquisition.md) for how to start it, and
[Installation](../getting-started/installation.md) for the extras.

This page collects the practical NI details you need when acquiring
through the bridge. It applies equally to the desktop Python interface
(the same recorder code runs underneath) — see
[Data acquisition](../user-guide/acquisition.md) for the scripting API.

## Requirements

- Windows or Linux (NI-DAQmx has **no macOS driver**).
- The **NI-DAQmx driver** installed from National Instruments.
- The Python bindings: `pip install "pydvma[ni,serve]"` (or
  `pydvma[full]`).

Start the bridge with the NI driver and open the app:

```bash
pydvma-serve --driver nidaq --open
```

When the bridge reports NI hardware, the app's **Setup** stage shows an
extra **NI** group with the controls below, and the device picker lists
your NI devices alongside any soundcards.

## Devices and how they differ

pydvma has been verified end-to-end (over the bridge, on real hardware)
with three representative devices. They behave differently in ways that
affect your measurements:

| Device | Sampling | AO timing | IEPE | Notes |
| ------ | -------- | --------- | ---- | ----- |
| **USB-6003** | Multiplexed (inter-channel skew) | Software-timed | No | Low-cost; single ADC scans the channel list, so channels are sampled slightly staggered. AO max ~5 kS/s. |
| **USB-6212** | Multiplexed (inter-channel skew) | Hardware-timed | No | M-series; supports shared-clock AI/AO sync. |
| **cDAQ-9174 chassis** | **Simultaneous** (DSA) | Hardware-timed | **Yes** (9234) | Delta-sigma modules with per-channel ADCs/DACs: every channel is sampled at the same instant, no skew. Example modules: NI 9234 (4-ch AI, IEPE), NI 9260 (2-ch BNC AO). |

**Multiplexed vs simultaneous** matters for phase-sensitive work
(transfer functions, mode shapes): on the multiplexed USB devices there
is a small, fixed inter-channel time skew; on the DSA chassis there is
none.

### Addressing a cDAQ chassis

A CompactDAQ chassis is addressed as a **single device**, not one per
module. The requested channel count is consumed across the chassis's AI
modules in slot order, and AO-only modules in the middle are skipped
when counting AI channels. So on a chassis with two 4-channel AI
modules, asking for 8 channels spans both modules automatically, and an
accelerometer on the second module's `ai1` lands at capture **column 5**
— the same index used for its IEPE current, sensitivity and units. Full
details and the channel-mapping table are in the
[Python acquisition guide](../user-guide/acquisition.md#cdaq-chassis-with-multiple-modules).

## DSA modules: sample-rate coercion

Delta-sigma modules (like the NI 9234) only run at rates on their
internal divider ladder. If you request a rate that is not on the
ladder, the driver **coerces it to the nearest legal value** — for
example, requesting 8000 Hz on a 9234 can yield 8533.33 Hz, and 5000 Hz
can yield 5120 Hz.

pydvma adopts the *true* hardware rate: the recorder reads back the
actual sample-clock rate and uses it for every time and frequency axis,
so your data is correctly scaled even when it differs from what you
asked for. In the app, **Setup** and **Acquire** show a note when the
rate has been coerced, and the fs picker constrains to the selected
device's ladder to reduce surprises.

!!! tip
    Pick a rate from the device's ladder in the first place and the
    coercion never happens. If you must hit an exact rate, choose a
    multiplexed device (USB-6212/6003), whose rates are continuous.

## Terminal configuration

The **NI** group exposes the input terminal configuration. The legal
options depend on the module:

- Multiplexed devices support **RSE** (referenced single-ended,
  default), **NRSE** and **differential**.
- **DSA modules (9234) are pseudo-differential only.** If a
  configuration a module cannot support is requested, pydvma falls back
  to the module's supported configuration (with a note) rather than
  crashing — the app surfaces the effective mode.

## Voltage ranges and output rails

- **Input range** (`VmaxNI`, default ±5 V) is the AI full-scale. Pick
  the smallest range that covers your signal for the best resolution;
  DAQmx rejects samples outside the range.
- **Output rail** (`output_VmaxNI`) is the AO full-scale. Some modules
  have a hard rail **below** the default — the NI 9260, for instance,
  is limited to ±4.24 V, which is less than the default 5 V. The bridge
  reports each device's real `ai_vmax` / `ao_vmax`, and the app clamps
  the input-range and output-amplitude controls to those rails, so you
  cannot ask for a voltage the hardware will refuse.

## IEPE / ICP excitation (DSA only)

DSA modules with built-in excitation (the 9234) can power IEPE/ICP
accelerometers directly. In the **NI** group you enable IEPE per
channel; the 9234 accepts exactly **0 mA (off)** or **2 mA**.

!!! warning "Only enable IEPE where an ICP/IEPE sensor is wired"
    Forcing excitation current into a voltage/charge input (a force
    hammer, a signal generator, or a loopback to an AO output) can
    damage it. Leave every non-ICP channel **off**. Enabling a channel
    switches it to AC coupling and adds a ~2 s bias-settle on the first
    capture while the sensor's DC bias stabilises.

The scripting equivalent and a full worked recipe (IEPE accelerometers
plus a force hammer on a cDAQ, with per-channel calibration) are in the
[Python acquisition guide](../user-guide/acquisition.md#iepe-icp-excitation-ni-dsa-modules).

## Output stimulus and pretrigger

Through the bridge the app can play an **output stimulus** (sine sweep,
white/uniform noise, or Gaussian noise) during a capture and can **arm
a pretrigger** to catch transients — see
[Acquisition and setup](acquisition.md). On the DSA chassis the sweep
plays from the 9260 AO into the structure while the 9234 captures the
response; a requested stimulus frequency above Nyquist (`fs/2`) is
rejected with a clear message. Pretrigger crossings land at exactly the
requested pre-trigger sample count on all verified devices.

## What runs where

Everything on this page needs the **`pydvma serve` bridge**, because it
needs the native NI driver. The no-install browser modes (the Pages app
and JupyterLite) can analyse NI data you have already saved, but they
cannot acquire from NI hardware — only a local Python process can. See
[the three modes](index.md) for the full picture.
