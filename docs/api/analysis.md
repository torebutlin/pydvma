# Analysis Module

Analysis functions for spectra, transfer functions, sonograms and
damping estimates. The `calculate_*` functions take a `TimeData` (or a
`TimeDataList` for ensemble averages) and return a new result without
changing their input. Modal fitting is in the
[Modal Analysis](modal.md) module.

## FFT Analysis

::: pydvma.analysis.calculate_fft

## Transfer Functions

::: pydvma.analysis.calculate_tf

::: pydvma.analysis.calculate_tf_averaged

::: pydvma.analysis.calculate_bla

## Cross-Spectrum Analysis

::: pydvma.analysis.calculate_cross_spectrum_matrix

::: pydvma.analysis.calculate_cross_spectra_averaged

## Time-Frequency Analysis

::: pydvma.analysis.calculate_sonogram

::: pydvma.analysis.calculate_cwt

## Damping

::: pydvma.analysis.calculate_damping_from_sono

::: pydvma.analysis.calculate_damping_from_cwt

::: pydvma.analysis.calculate_damping_by_band

## Signal Processing

::: pydvma.analysis.resample_to_fs

::: pydvma.analysis.multiply_by_power_of_iw

::: pydvma.analysis.clean_impulse

::: pydvma.analysis.best_match

## Units

::: pydvma.analysis.wrap_unit

## Acoustics

Sound pressure level, frequency weighting, band levels and calibration
from a reference tone. The web app's frequency view draws the same
curves and bands from a TypeScript twin pinned to these by shared
known-answer vectors.

::: pydvma.acoustics.P_REF

::: pydvma.acoustics.weighting_db

::: pydvma.acoustics.band_table

::: pydvma.acoustics.band_levels

::: pydvma.acoustics.tone_rms

::: pydvma.acoustics.reference_tone_calibration
