# Test Data

Synthetic measurements for trying the analysis and plotting functions
without hardware. Each `create_test_*` function returns a `DataSet`
holding simulated time data (channel 0 is the input, the rest are
responses at 10 kHz), except `create_test_bla_captures`, which builds the
captures of a Nonlin-stage run.

```python
import pydvma as dvma

data = dvma.create_test_impulse_data()
data.calculate_tf_set(ch_in=0, window=None)
data.plot_tf_data()
```

## Impulse and Noise Tests

::: pydvma.testdata.create_test_impulse_data

::: pydvma.testdata.create_test_impulse_ensemble

::: pydvma.testdata.create_test_noise_data

## Nonlinear and Multi-Harmonic Responses

::: pydvma.testdata.create_test_impulse_data_nonlinear_v1

::: pydvma.testdata.create_test_impulse_data_nonlinear_v2

::: pydvma.testdata.create_test_impulse_data_multi_harmonics

## Best Linear Approximation

::: pydvma.testdata.create_test_bla_captures
