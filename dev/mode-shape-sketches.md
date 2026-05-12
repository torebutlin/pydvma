# Mode-shape, MAC, ODS — feature sketches

Holding pen for code that *isn't shipped* as a pydvma API yet, but is
worth keeping when the corresponding feature is built (see TODO.md
entries: "Simple mode-shape plotter", "Modal Assurance Criterion
helper", "Operating Deflection Shape helper").

These sketches were previously published in
`docs/user-guide/modal-analysis.md` as user-side recipes. They're
removed from the user guide because they implied pydvma had built-in
mode-shape / MAC / ODS support; it doesn't. When implementing the
real APIs, they're a reasonable starting point — the maths and
matplotlib code are sound, they just need to be wrapped up as proper
helpers (e.g. `dvma.plot_mode_shape(...)`, `dvma.calculate_mac(...)`).

Not consumed by mkdocs — outside `docs/`.

---

## Mode-shape extraction from per-point FRFs

Given a list of `TfData` objects (one per measurement point), grab
the complex TF value at the mode's natural frequency and assemble a
mode-shape vector.

```python
import numpy as np
import pydvma as dvma

# Multi-point FRF measurements (impact hammer at fixed point,
# accelerometer moved between measurement_points)
tf_list = dvma.TfDataList()
for location in measurement_points:
    data = dvma.log_data(settings, test_name=f"point_{location}")
    tf = dvma.calculate_tf(data.time_data_list[0], ch_in=0)
    tf_list.append(tf)

# Extract mode shape at the chosen natural frequency
fn_mode = 150  # Hz
mode_shape = []
for tf_data in tf_list:
    idx = np.argmin(np.abs(tf_data.freq_axis - fn_mode))
    mode_shape.append(tf_data.tf_data[idx, 0])
mode_shape = np.array(mode_shape)
```

### 1D plot (beam-style)

```python
import matplotlib.pyplot as plt

x_positions = np.array([0, 0.1, 0.2, 0.3, 0.4, 0.5])  # m

plt.figure()
plt.plot(x_positions, np.abs(mode_shape), 'o-')
plt.xlabel('Position (m)')
plt.ylabel('Amplitude')
plt.title(f'Mode Shape at {fn_mode} Hz')
plt.grid(True)
plt.show()
```

### 2D plot (plate / surface)

```python
# Define 2D grid of measurement points
x_grid = np.array([...])              # x coordinates
y_grid = np.array([...])              # y coordinates
mode_shape_2d = np.array([...])       # complex amplitudes at each point

plt.figure(figsize=(10, 8))
plt.tricontourf(x_grid, y_grid, np.abs(mode_shape_2d), levels=20)
plt.colorbar(label='Amplitude')
plt.xlabel('X (m)')
plt.ylabel('Y (m)')
plt.title(f'Mode Shape at {fn_mode} Hz')
plt.axis('equal')
plt.show()
```

---

## Modal Assurance Criterion (MAC)

Compare two mode-shape vectors. MAC ≈ 1 means similar shapes; MAC ≈ 0
means uncorrelated.

```python
def calculate_mac(mode1, mode2):
    """Modal Assurance Criterion between two mode-shape vectors."""
    numerator = np.abs(np.dot(mode1.conj(), mode2)) ** 2
    denominator = np.dot(mode1.conj(), mode1) * np.dot(mode2.conj(), mode2)
    return numerator / denominator

mac_value = calculate_mac(mode_shape_1, mode_shape_2)
print(f"MAC: {mac_value:.4f}")
```

A real pydvma helper would likely take two iterables of shapes (or
two `ModalData` objects) and return a full MAC matrix.

---

## Operating Deflection Shape (ODS)

Visualise instantaneous shape at a chosen operating frequency. Same
shape-extraction as above, then animate by phase.

```python
# Build ODS vector at the operating frequency
f_operating = 120  # Hz
ods = []
for tf_data in tf_list:
    idx = np.argmin(np.abs(tf_data.freq_axis - f_operating))
    ods.append(tf_data.tf_data[idx, 0])
ods = np.array(ods)

# Animate by sweeping phase
plt.figure()
for phase in np.linspace(0, 2 * np.pi, 50):
    ods_instant = np.real(ods * np.exp(1j * phase))
    plt.clf()
    plt.plot(x_positions, ods_instant, 'o-')
    plt.ylim([-np.max(np.abs(ods)), np.max(np.abs(ods))])
    plt.pause(0.05)
```

A shipped helper would likely save out an MP4 / GIF rather than
relying on `plt.pause` (which only works in some matplotlib
backends).
