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
dvma.save_data(dataset, filename='dataset')

# Load dataset — opens a file-open dialog if filename is omitted
dataset = dvma.load_data(filename='dataset.dvma')
```

`.dvma` has been the native format since 1.5: a zip container of
`manifest.json` plus pickle-free `.npy` arrays. Loading a `.dvma`
file executes no code, so it's safe to share with others. If
`filename` doesn't already end in `.dvma` or `.npy`, `save_data`
appends `.dvma` for you. Format detection on load is by content (zip
magic bytes), not extension, so a renamed file still loads correctly.

Legacy `.npy` pickle files from pydvma <= 1.4.0 still load forever.
To keep writing that legacy pickle format, pass an explicit filename
ending in `.npy` — an escape hatch for workflows that still need it,
but note that unpickling can execute arbitrary code, so only load
legacy `.npy` files you or your lab created. The helpers handle
overwrite prompts and dialog fallback either way.

## Export Plots

```python
import matplotlib.pyplot as plt

# After creating a plot
plt.savefig('figure.png', dpi=300, bbox_inches='tight')
plt.savefig('figure.pdf', bbox_inches='tight')
```
