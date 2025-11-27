# Advanced Examples

More advanced usage examples and workflows.

## Complete Experimental Modal Analysis

See the [Modal Analysis](../user-guide/modal-analysis.md#experimental-modal-analysis-workflow) page for a complete EMA workflow example.

## Custom Signal Processing

```python
import pydvma as dvma
import numpy as np
from scipy import signal

# Record data
settings = dvma.MySettings()
dataset = dvma.log_data(settings)
time_data = dataset.time_data_list[0]

# Design custom filter
sos = signal.butter(4, [50, 500], 'bandpass',
                    fs=settings.fs, output='sos')

# Apply filter
filtered = signal.sosfiltfilt(sos, time_data.time_data, axis=0)

# Analyze filtered data
import copy
time_data_filtered = copy.copy(time_data)
time_data_filtered.time_data = filtered

freq_data = dvma.calculate_fft(time_data_filtered)
```

## Batch Processing Multiple Files

```python
import pydvma as dvma
import os

# Process all measurements in a directory
data_dir = 'measurements'
files = [f for f in os.listdir(data_dir) if f.endswith('.pkl')]

results = []
for filename in files:
    # Load data
    with open(os.path.join(data_dir, filename), 'rb') as f:
        time_data = pickle.load(f)

    # Analyze
    freq_data = dvma.calculate_fft(time_data)
    tf_data = dvma.calculate_tf(time_data, ch_in=0)

    # Store results
    results.append({
        'filename': filename,
        'freq_data': freq_data,
        'tf_data': tf_data
    })
```

## Integration with Other Tools

```python
import pydvma as dvma
import pandas as pd

# Convert to pandas DataFrame for analysis
time_data = dataset.time_data_list[0]
df = pd.DataFrame(
    time_data.time_data,
    index=time_data.time_axis,
    columns=[f'Channel_{i}' for i in range(time_data.time_data.shape[1])]
)

# Use pandas tools
print(df.describe())
df.plot()
```
