# File Operations Module

Functions for importing, exporting, and saving data in various formats.

## Load and Save

::: pydvma.file.load_data

::: pydvma.file.save_data

::: pydvma.file.save_fig

## Export Functions

The CSV and MATLAB exports write the stored values with no calibration
applied: volts, or full-scale units on an uncalibrated soundcard. They
record the calibration next to the data so that it is not lost. A CSV file starts with a `#`-commented header
listing `cal_factors` and `units` per data column (`numpy.loadtxt` and
`pandas.read_csv(..., comment='#')` skip it). A MATLAB file gains
`time_cal_factors` and `time_units`, and the `freq_` and `tf_` pairs
for those data. Multiply each data column by its factor to get
engineering units. The web logger's exports are described in
[Saving & Exporting](../web-logger/export.md).

::: pydvma.file.export_to_matlab

::: pydvma.file.export_to_matlab_jwlogger

::: pydvma.file.export_to_csv

::: pydvma.file.format_cal_factor

## Import Functions

::: pydvma.file.import_from_matlab_jwlogger

::: pydvma.file.import_from_vibration_apps_csv
