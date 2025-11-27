# Basic Examples

Collection of basic examples for common tasks.

## Example 1: Simple Measurement and FFT

```python
import pydvma as dvma
import numpy as np
import matplotlib.pyplot as plt

# Setup
settings = dvma.MySettings()
settings.fs = 10000
settings.stored_time = 2.0
settings.channels = 1

# Record
dataset = dvma.log_data(settings, test_name="example_01")
time_data = dataset.time_data_list[0]

# Calculate FFT
freq_data = dvma.calculate_fft(time_data, window='hann')

# Plot
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

ax1.plot(time_data.time_axis, time_data.time_data[:, 0])
ax1.set_xlabel('Time (s)')
ax1.set_ylabel('Amplitude')
ax1.set_title('Time Domain')
ax1.grid(True)

ax2.semilogy(freq_data.freq_axis, np.abs(freq_data.freq_data[:, 0]))
ax2.set_xlabel('Frequency (Hz)')
ax2.set_ylabel('Magnitude')
ax2.set_title('Frequency Domain')
ax2.set_xlim([0, 2000])
ax2.grid(True)

plt.tight_layout()
plt.show()
```

## Example 2: Transfer Function Measurement

```python
import pydvma as dvma
import numpy as np
import matplotlib.pyplot as plt

# Setup for 2-channel measurement
settings = dvma.MySettings()
settings.fs = 10000
settings.stored_time = 2.0
settings.channels = 2  # Channel 0: input, Channel 1: output

# Record
dataset = dvma.log_data(settings, test_name="tf_measurement")
time_data = dataset.time_data_list[0]

# Calculate transfer function
tf_data = dvma.calculate_tf(time_data, ch_in=0, window='hann',
                             N_frames=4, overlap=0.5)

# Plot
f = tf_data.freq_axis
H = tf_data.tf_data[:, 0]
coh = tf_data.tf_coherence[:, 0]

fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 10))

# Magnitude
ax1.loglog(f, np.abs(H))
ax1.set_ylabel('|H(f)|')
ax1.set_title('FRF Magnitude')
ax1.grid(True, which='both')

# Phase
ax2.semilogx(f, np.angle(H, deg=True))
ax2.set_ylabel('Phase (deg)')
ax2.set_title('FRF Phase')
ax2.grid(True)

# Coherence
ax3.semilogx(f, coh)
ax3.set_xlabel('Frequency (Hz)')
ax3.set_ylabel('Coherence')
ax3.set_ylim([0, 1])
ax3.set_title('Coherence')
ax3.grid(True)

plt.tight_layout()
plt.show()
```

## Example 3: Impact Test with Averaging

```python
import pydvma as dvma
import numpy as np

# Setup
settings = dvma.MySettings()
settings.fs = 10000
settings.stored_time = 1.0
settings.channels = 2
settings.pretrig_samples = 1000

# Collect multiple impacts
time_data_list = dvma.TimeDataList()
n_impacts = 5

for i in range(n_impacts):
    input(f"Press Enter for impact {i+1}/{n_impacts}...")
    data = dvma.log_data(settings, test_name=f"impact_{i}")
    time_data_list.append(data.time_data_list[0])

# Calculate averaged transfer function
tf_data = dvma.calculate_tf_averaged(time_data_list, ch_in=0)

# Results
print(f"Averaged {len(time_data_list)} measurements")
print(f"Average coherence: {np.mean(tf_data.tf_coherence):.3f}")
```

## Example 4: Sonogram Analysis

```python
import pydvma as dvma
import numpy as np
import matplotlib.pyplot as plt

# Record data
settings = dvma.MySettings()
settings.fs = 10000
settings.stored_time = 5.0
dataset = dvma.log_data(settings, test_name="sono_test")
time_data = dataset.time_data_list[0]

# Calculate sonogram
sono_data = dvma.calculate_sonogram(time_data, nperseg=512, noverlap=256)

# Plot
plt.figure(figsize=(12, 6))
plt.pcolormesh(sono_data.time_axis,
               sono_data.freq_axis,
               20*np.log10(np.abs(sono_data.sono_data[:, :, 0])),
               shading='gouraud',
               cmap='viridis')
plt.ylabel('Frequency (Hz)')
plt.xlabel('Time (s)')
plt.colorbar(label='Magnitude (dB)')
plt.ylim([0, 2000])
plt.title('Sonogram')
plt.show()
```

## Example 5: Modal Analysis from Impact

```python
import pydvma as dvma
import numpy as np

# Record impact response
settings = dvma.MySettings()
settings.fs = 10000
settings.stored_time = 2.0
settings.channels = 2
settings.pretrig_samples = 1000

dataset = dvma.log_data(settings, test_name="modal_test")
time_data = dataset.time_data_list[0]

# Extract damping from free decay
fn, Qn, fit_data = dvma.calculate_damping_from_sono(
    time_data,
    n_chan=1,
    nperseg=512
)

# Display results
print("Modal Analysis Results:")
print("-" * 40)
for i, (f, Q) in enumerate(zip(fn, Qn)):
    zeta = 1 / (2 * Q)
    print(f"Mode {i+1}:")
    print(f"  Natural frequency: {f:.2f} Hz")
    print(f"  Damping ratio: {zeta:.4f}")
    print(f"  Q factor: {Q:.1f}")
    print()
```
