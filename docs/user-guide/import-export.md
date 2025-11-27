# Import and Export

Guide for importing and exporting data in various formats.

## Export to Matlab

```python
# Export entire dataset
dvma.export_to_matlab(dataset)

# This creates a .mat file with all data structures
```

The Matlab file contains:
- Time data
- Frequency data
- Transfer function data
- Settings and metadata

## Export to CSV

```python
# Export time data
dvma.export_to_csv(dataset.time_data_list)

# Export frequency data
dvma.export_to_csv(dataset.freq_data_list)

# Export transfer function data
dvma.export_to_csv(dataset.tf_data_list)
```

## Import from Matlab

```python
# Import data from JW Logger format
dataset = dvma.import_from_matlab_jwlogger()
```

## Save Python Objects

```python
import pickle

# Save dataset
with open('dataset.pkl', 'wb') as f:
    pickle.dump(dataset, f)

# Load dataset
with open('dataset.pkl', 'rb') as f:
    dataset = pickle.load(f)
```

## Export Plots

```python
import matplotlib.pyplot as plt

# After creating a plot
plt.savefig('figure.png', dpi=300, bbox_inches='tight')
plt.savefig('figure.pdf', bbox_inches='tight')
```
