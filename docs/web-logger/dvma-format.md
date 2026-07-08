# The `.dvma` file format

`.dvma` is pydvma's native save format (the default since version 1.5).
Everything the web logger and the Python interface save — time series,
spectra, transfer functions, sonograms, modal fits, calibration and
units — round-trips through it. It is a small, documented, language-
neutral container, which is exactly why the browser app can open and
write your data without waking the Python engine.

## Why not the old `.npy` pickle?

Files saved by pydvma ≤ 1.4.0 were a NumPy pickle of the live Python
objects (`np.save(..., allow_pickle=True)`). That format is:

- **single-language** — only Python can read it;
- **unversioned** — no way to detect or migrate a schema change;
- **a code-execution risk** — unpickling can run arbitrary code, so a
  file is only safe to open if you trust whoever made it; and
- **coupled to the code layout** — the pickle stores class module
  paths, so renaming a module breaks every old file.

`.dvma` fixes all four. Loading a `.dvma` file executes no code, so it
is safe to share and to open in the browser.

!!! success "Legacy files still load — forever"
    pydvma still reads legacy `.npy` pickle files saved by version
    1.4.0 and earlier. Both the Python `load_data()` and the browser
    app's file loader detect the format automatically. In the browser,
    a legacy `.npy` is decoded by the pyodide engine (which understands
    the pickle); a modern `.dvma` is read directly in JavaScript. See
    [Saving and exporting](export.md) and
    [From the Qt logger](migration.md).

## What is inside a `.dvma` file

A `.dvma` file is an ordinary **zip archive** containing a
`manifest.json` plus one plain `.npy` array file (written with
`allow_pickle=False`) per array attribute:

```text
manifest.json                    # the schema (below)
arrays/0000_time_axis.npy        # one member per array attribute
arrays/0000_time_data.npy
arrays/0001_freq_axis.npy
arrays/0001_freq_data.npy
...
```

You can unzip it with any zip tool and read the arrays with any NumPy
`.npy` parser — no pydvma required. The zip members use DEFLATE
compression transparently.

## The manifest schema (format version 1)

`manifest.json` — not the Python object graph — is the contract. Its
top level is:

```json
{
  "format": "dvma-dataset",
  "format_version": 1,
  "pydvma_version": "<version that wrote the file>",
  "storage": "npy",
  "items": [ ... ]
}
```

- `format` / `format_version` — identify the container; a reader
  refuses a `format_version` newer than it understands rather than
  silently misreading it.
- `pydvma_version` — the version that **wrote** the file (resaving an
  old file records the new writer).
- `storage` — `"npy"` today; a versioned extension point reserved for
  a future chunked/HDF5 backend for very large captures.

Each entry in `items` is one data object:

```json
{
  "kind": "TimeData",
  "arrays": { "time_axis": "arrays/0000_time_axis.npy",
              "time_data": "arrays/0000_time_data.npy" },
  "meta":   { "units": ["g", "N"], "channel_cal_factors": {"__array__": [10.0, 434.78]},
              "test_name": "impact_01", "timestamp": {"__datetime__": "..."}, ... },
  "settings": { ... }
}
```

- **`kind`** is the class name in `pydvma.datastructure`: one of
  `TimeData`, `FreqData`, `CrossSpecData`, `TfData`, `SonoData`,
  `ModalData`, `MetaData`.
- **`arrays`** maps each array attribute to its zip member. Absent
  arrays (e.g. a `TfData` with no coherence, or a fresh `ModalData`
  whose model list is empty) are simply omitted.
- **`meta`** holds the scalar metadata — including **`units`** and
  **`channel_cal_factors`**, the calibration state described in
  [Calibration and units](calibration.md), plus `test_name`,
  `timestamp`/`timestring`, and traceability ids (`unique_id`,
  `id_link`).
- **`settings`** is the item's `MySettings` as a plain dict (or
  `null`).

### Lossless JSON encoding

So the manifest stays strict, parseable JSON (it is written with
`allow_nan=False`, so `JSON.parse` in a browser never chokes), scalar
values that JSON cannot represent natively are wrapped in small type
tags:

| Tag | Meaning |
| --- | ------- |
| `{"__uuid__": "..."}` | a UUID (traceability ids) |
| `{"__datetime__": "<isoformat>"}` | a timestamp |
| `{"__array__": [...]}` | a small array embedded in the manifest |
| `{"__float__": "inf" \| "-inf" \| "nan"}` | a non-finite float |

Type tags are applied recursively (including inside embedded arrays and
nested dicts), and the larger arrays keep their exact dtype in their
`.npy` members. A reader ignores manifest keys it does not recognise,
so newer files degrade gracefully in older readers where the schema
allows.

## Reading and writing from Python

```python
import pydvma as dvma

# Save — appends .dvma if the name has no recognised extension
dvma.save_data(dataset, filename='my_measurement')

# Load — format detected from the file's content (zip magic bytes),
# not its extension, so a renamed file still loads correctly
dataset = dvma.load_data(filename='my_measurement.dvma')
```

The write is **atomic**: data goes to a temporary file in the same
directory and is renamed over the target only on success, so a crash
mid-save can never destroy a pre-existing good file.

To deliberately write the legacy pickle format instead, pass a filename
ending in `.npy` — an escape hatch for workflows that still need it.

See also: [Saving and exporting](export.md) for the browser app's Save,
autosave and export options, and the API reference for
[`container`](../api/file.md) and the
[data structures](../api/datastructure.md).
