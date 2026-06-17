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
      show_source: false
      heading_level: 3
      members: false

::: pydvma.options.Output_Signal_Settings
    options:
      show_source: false
      heading_level: 3
      members: false

## Main Acquisition Function

::: pydvma.acquisition.log_data
    options:
      show_source: false
      heading_level: 3

## Signal Generation

::: pydvma.acquisition.output_signal
    options:
      show_source: false
      heading_level: 3

::: pydvma.acquisition.signal_generator
    options:
      show_source: false
      heading_level: 3

## Stream Monitoring

::: pydvma.acquisition.stream_snapshot
    options:
      show_source: false
      heading_level: 3
