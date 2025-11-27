# Plotting and Visualization

Brief guide for plotting with pydvma's built-in tools and matplotlib.

## GUI Plotting

The Logger GUI provides interactive plotting:

```python
logger = dvma.Logger(settings, dataset=dataset)
```

Features:
- Switch between Time, FFT, TF, and Sonogram views
- Interactive zoom and pan
- Channel selection
- Export plots

## Custom Plotting with Matplotlib

### Time Domain Plots

```python
import matplotlib.pyplot as plt
import numpy as np

time_data = dataset.time_data_list[0]
t = time_data.time_axis
y = time_data.time_data

plt.figure(figsize=(10, 6))
plt.plot(t, y[:, 0], label='Channel 0')
plt.plot(t, y[:, 1], label='Channel 1')
plt.xlabel('Time (s)')
plt.ylabel('Amplitude')
plt.title('Time Domain Signal')
plt.legend()
plt.grid(True)
plt.show()
```

### Frequency Domain Plots

```python
freq_data = dvma.calculate_fft(time_data)
f = freq_data.freq_axis
Y = freq_data.freq_data

plt.figure(figsize=(10, 6))
plt.semilogy(f, np.abs(Y[:, 0]))
plt.xlabel('Frequency (Hz)')
plt.ylabel('Magnitude')
plt.title('FFT Magnitude')
plt.grid(True)
plt.xlim([0, 1000])
plt.show()
```

### FRF Plots

```python
tf_data = dvma.calculate_tf(time_data, ch_in=0)
f = tf_data.freq_axis
H = tf_data.tf_data
coh = tf_data.tf_coherence

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

# Magnitude
ax1.loglog(f, np.abs(H[:, 0]))
ax1.set_ylabel('|H(f)|')
ax1.set_title('FRF Magnitude')
ax1.grid(True, which='both')

# Coherence
ax2.semilogx(f, coh[:, 0])
ax2.set_xlabel('Frequency (Hz)')
ax2.set_ylabel('Coherence')
ax2.set_ylim([0, 1])
ax2.grid(True)

plt.tight_layout()
plt.show()
```

### Sonogram Plots

```python
sono_data = dvma.calculate_sonogram(time_data)
t = sono_data.time_axis
f = sono_data.freq_axis
S = sono_data.sono_data

plt.figure(figsize=(12, 6))
plt.pcolormesh(t, f, 20*np.log10(np.abs(S[:, :, 0])),
               shading='gouraud', cmap='viridis')
plt.ylabel('Frequency (Hz)')
plt.xlabel('Time (s)')
plt.colorbar(label='Magnitude (dB)')
plt.ylim([0, 2000])
plt.title('Sonogram')
plt.show()
```

## Export Plots

```python
# Save figure
plt.savefig('plot.png', dpi=300, bbox_inches='tight')
plt.savefig('plot.pdf', bbox_inches='tight')  # Vector format
```
