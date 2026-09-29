# Plotting and Visualization

There are two ways to plot from Python. The `DataSet.plot_*` methods give
quick figures with calibration applied. Matplotlib recipes give figures
you control completely. For interactive analysis in the browser, use the
[web logger](../web-logger/index.md).

The examples on this page start from a synthetic impulse test (channel 0
is the force, channel 1 the response):

```python
import matplotlib.pyplot as plt
import numpy as np
import pydvma as dvma

data = dvma.create_test_impulse_data(noise_level=0.01)
data.calculate_fft_set(window='hann')
data.calculate_tf_set(ch_in=0, window='hann', N_frames=4)
data.calculate_sono_set()

time_data = data.time_data_list[0]
```

## Built-in plots

Each `DataSet` has one plot method per kind of data:

```python
data.plot_time_data()
data.plot_freq_data()       # needs calculate_fft_set() first
data.plot_tf_data()         # needs calculate_tf_set() first
data.plot_sono_data(n_set=0, n_chan=1, db_range=60)   # needs calculate_sono_set()
```

Each opens a matplotlib figure and returns a `PlotData` object. The
figures apply `channel_cal_factors`, so they read in engineering units
when you have set sensitivities. The frequency and transfer function
plots show magnitude in dB. The transfer function plot adds coherence on
a right-hand axis, which stays hidden while the coherence is exactly 1
everywhere (as it is when `N_frames=1`).

Pass `sets=[...]` and `channels=[...]` to emphasise some lines. The
others stay on the plot, faded. To change what is plotted, call `update`
on the returned object and give it the data list again:

```python
plot = data.plot_tf_data(sets=[0], channels=[0])
plot.update(data.tf_data_list, plot_type='Phase', xlinlog='log')
```

| `update` argument | Values |
| ----------------- | ------ |
| `plot_type` | `'Amplitude (dB)'` (default), `'Amplitude (linear)'`, `'Real Part'`, `'Imag Part'`, `'Phase'`, `'Nyquist'` |
| `xlinlog` | `'linear'` (default) or `'log'` |
| `show_coherence` | `True` (default) or `False`, for transfer functions |
| `freq_range` | `[f_min, f_max]`, used by `'Nyquist'` |

An interactive matplotlib backend gives you zoom and pan: `%matplotlib qt`
in a desktop session, or `%matplotlib widget` in Jupyter (which needs the
`ipympl` package).

## Matplotlib recipes

The arrays inside each object are the raw stored values. Multiply by
`channel_cal_factors` to get engineering units, as the built-in plots do.

### Time domain

```python
t = time_data.time_axis
y = time_data.time_data * time_data.channel_cal_factors   # (samples, channels)

plt.figure(figsize=(10, 5))
plt.plot(t, y[:, 0], label='Channel 0')
plt.plot(t, y[:, 1], label='Channel 1')
plt.xlabel('Time (s)')
plt.ylabel('Amplitude')
plt.legend()
plt.grid(True)
plt.show()
```

### FFT

```python
freq_data = data.freq_data_list[0]
f = freq_data.freq_axis
Y = freq_data.freq_data * freq_data.channel_cal_factors

plt.figure(figsize=(10, 5))
plt.semilogy(f, np.abs(Y[:, 1]))
plt.xlabel('Frequency (Hz)')
plt.ylabel('FFT magnitude')
plt.xlim([0, 1000])
plt.grid(True)
plt.show()
```

`calculate_fft` returns the raw FFT of the windowed record: it is not
divided by the record length and not corrected for the window, so the
level depends on both. For a level you can compare between records, use a
power spectrum or PSD (below).

### Transfer function

```python
tf = data.tf_data_list[0]
f = tf.freq_axis
H = tf.tf_data[:, 0] * tf.channel_cal_factors[0]
coherence = tf.tf_coherence[:, 0]

fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
ax1.loglog(f[1:], np.abs(H[1:]))
ax1.set_ylabel('|H|')
ax2.semilogx(f[1:], np.angle(H[1:], deg=True))
ax2.set_ylabel('Phase (deg)')
ax3.semilogx(f[1:], coherence[1:])
ax3.set_ylabel('Coherence')
ax3.set_xlabel('Frequency (Hz)')
ax3.set_ylim([0, 1])
for ax in (ax1, ax2, ax3):
    ax.grid(True, which='both')
plt.show()
```

Coherence is only meaningful when the transfer function averages at least
a few frames (`N_frames=4` above). With `N_frames=1` it is exactly 1.

### Power spectrum, PSD and CSD

```python
cs = dvma.calculate_cross_spectrum_matrix(time_data, window='hann', N_frames=8)
f = cs.freq_axis

power0 = cs.Pxy[0, 0].real               # power spectrum of channel 0, unit²
psd1 = cs.Pxy[1, 1].real / cs.enbw_hz    # PSD of channel 1, unit²/Hz
csd01 = cs.Pxy[0, 1]                     # cross-spectrum, complex
coh01 = cs.Cxy[0, 1]                     # coherence

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
ax1.semilogy(f[1:], power0[1:], label='power spectrum, ch 0')
ax1.semilogy(f[1:], psd1[1:], label='PSD, ch 1')
ax1.semilogy(f[1:], np.abs(csd01[1:]), '--', label='|cross-spectrum| 0-1')
ax1.legend()
ax2.plot(f[1:], coh01[1:])
ax2.set_ylabel('Coherence')
ax2.set_xlabel('Frequency (Hz)')
ax2.set_ylim([0, 1])
plt.show()
```

Read a discrete tone from the power spectrum and a noise floor from the
PSD. [Data Analysis](analysis.md#cross-spectrum-analysis) explains why.

### Sonogram

```python
sono = data.sono_data_list[0]
S = sono.sono_data[:, :, 1]              # (frequencies, times), complex
level_db = 20 * np.log10(np.abs(S) + 1e-12)

plt.figure(figsize=(10, 5))
plt.pcolormesh(sono.time_axis, sono.freq_axis, level_db,
               shading='gouraud', cmap='viridis')
plt.colorbar(label='Magnitude (dB)')
plt.xlabel('Time (s)')
plt.ylabel('Frequency (Hz)')
plt.ylim([0, 2000])
plt.show()
```

## Saving figures

`dvma.save_fig` writes a PNG and a PDF of a `PlotData` object or a
matplotlib figure:

```python
plot = data.plot_tf_data()
dvma.save_fig(plot, filename='tf_plot', overwrite_without_prompt=True)
# writes tf_plot.png and tf_plot.pdf, both at 300 dpi
```

For a matplotlib figure of your own, `plt.savefig` works as usual:

```python
plt.savefig('recipe.pdf', bbox_inches='tight')     # vector
plt.savefig('recipe.png', dpi=300, bbox_inches='tight')
```
