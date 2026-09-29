# Acquisition Module

Data acquisition functions for logging data from soundcards and National Instruments DAQ devices.

## Acquisition Settings

`MySettings` is the object you pass to every acquisition call — it holds
the device, channel, sampling, trigger, voltage-range, IEPE excitation
and per-channel calibration configuration. Every constructor argument is
keyword-only with a default, and the attributes are plain and mutable.
The full per-attribute reference is below; for worked end-to-end recipes
(IEPE on a cDAQ, calibration at logging time) see the
[Data Acquisition user guide](../user-guide/acquisition.md).

::: pydvma.options.MySettings
    options:
      members: false

::: pydvma.options.MySettings.input_vmax

::: pydvma.options.MySettings.output_vmax

## Main Acquisition Function

::: pydvma.acquisition.log_data

## Output Signals

::: pydvma.acquisition.output_signal

::: pydvma.acquisition.signal_generator

::: pydvma.acquisition.multisine_generator

## Stream Monitoring

::: pydvma.acquisition.stream_snapshot

## Cancelled Captures and Dropouts

::: pydvma.acquisition.CaptureCancelled

::: pydvma.acquisition.exact_zero_dropouts

## Devices

Run `list_available_devices()` before writing a `MySettings` to see what
is plugged in, which backend to drive each device through, and whether
its readings will be in volts or only in full-scale units. Pass
`MySettings(device='name')` to select a device by name rather than by
index; `resolve`, also exported as `dvma.resolve_device_spec`, does the
matching.

::: pydvma.list_available_devices

::: pydvma.devices.resolve

::: pydvma.devices.inventory

::: pydvma.devices.format_inventory

::: pydvma.devices.calibration_status

::: pydvma.devices.preferred_backend

### National Instruments devices

::: pydvma.suggest_ni_settings

::: pydvma.get_device_info

## Unused Settings Class

`Output_Signal_Settings` is not used by pydvma. It is kept so that old
code which constructs it still imports. To define a stimulus, use
`signal_generator` with `log_data(output=...)`, or the output group in the
web logger's Acquire stage.

::: pydvma.options.Output_Signal_Settings
    options:
      members: false
