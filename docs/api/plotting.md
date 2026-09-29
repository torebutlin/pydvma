# Plotting Module

Matplotlib plotting for datasets.

`PlotData` is the object returned by `DataSet.plot_time_data`,
`plot_freq_data`, `plot_tf_data` and `plot_sono_data`. It wraps a
matplotlib figure (`fig`, `ax`, and `ax2` for coherence), so anything
matplotlib can do to a figure you can do to it.

A `PlotData` can also stand in for a time range. Pass it as
`time_range=` to `calculate_fft` or `calculate_cross_spectrum_matrix`,
and the range is read from the current x-axis limits of the plot: zoom
the plot, then analyse what you see. Elsewhere, pass the range as a list
such as `[0.5, 1.5]`: a transfer function computed with a `PlotData`
range can't be saved afterwards.

For custom figures, use matplotlib directly, as shown in the
[Plotting Guide](../user-guide/plotting.md).

::: pydvma.plotting.PlotData

::: pydvma.plotting.PlotSonoData
