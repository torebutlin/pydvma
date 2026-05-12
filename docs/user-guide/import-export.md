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

## Save and Load a DataSet (native format)

```python
# Save dataset — opens a file-save dialog if filename is omitted
dvma.save_data(dataset, filename='dataset.npy')

# Load dataset — opens a file-open dialog if filename is omitted
dataset = dvma.load_data(filename='dataset.npy')
```

Internally this uses `numpy.save` / `numpy.load` on a one-element
object array wrapping the `DataSet`, so a saved file is a `.npy`. The
helpers handle overwrite prompts and dialog fallback; prefer them
over a raw `pickle`.

## Export Plots

```python
import matplotlib.pyplot as plt

# After creating a plot
plt.savefig('figure.png', dpi=300, bbox_inches='tight')
plt.savefig('figure.pdf', bbox_inches='tight')
```
