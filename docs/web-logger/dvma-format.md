# The `.dvma` file format

`.dvma` is pydvma's own save format. Everything the web logger and the
Python interface save (time series, spectra, transfer functions,
sonograms, modal fits, calibration and units) goes into it, and it
reopens in either.

It is a plain zip archive that any language can read. Opening one never
runs code, so `.dvma` files are safe to share and to open in the browser.

## What is inside

A `.dvma` file is an ordinary zip archive with one `manifest.json` and
one plain NumPy `.npy` file for each array. The members are compressed
with DEFLATE.

```text
manifest.json
arrays/0000_time_axis.npy
arrays/0000_time_data.npy
arrays/0001_freq_axis.npy
arrays/0001_freq_data.npy
...
```

Unzip it with any zip tool and read the arrays with any `.npy` reader.
No pydvma is needed:

```python
import io, json, zipfile
import numpy as np

with zipfile.ZipFile('session.dvma') as z:
    manifest = json.loads(z.read('manifest.json'))
    member = manifest['items'][0]['arrays']['time_data']
    time_data = np.load(io.BytesIO(z.read(member)))
```

## The manifest

`manifest.json` describes the file. Its top level is:

```json
{
  "format": "dvma-dataset",
  "format_version": 1,
  "pydvma_version": "2.5.0",
  "storage": "npy",
  "items": [ ... ]
}
```

- `format` and `format_version` identify the file. A reader refuses a
  `format_version` newer than it understands rather than misreading it.
- `pydvma_version` is the version that wrote the file. Saving an old
  file again records the newer version.
- `storage` is `"npy"`: the arrays are `.npy` members.

Each entry in `items` is one data object:

```json
{
  "kind": "TimeData",
  "arrays": { "time_axis": "arrays/0000_time_axis.npy",
              "time_data": "arrays/0000_time_data.npy" },
  "meta":   { "units": ["m/s2", "N"],
              "channel_cal_factors": {"__array__": [10.0, 434.78]},
              "test_name": "impact_01", ... },
  "settings": { ... },
  "ui": { ... }
}
```

- **`kind`** says what the item is (table below).
- **`arrays`** maps each array to its zip member. An array an item does
  not have, such as the coherence of a transfer function, is left out.
- **`meta`** holds the scalar details: `units`, `channel_cal_factors`
  (see [Calibration and units](calibration.md)), `test_name`,
  `timestamp` and `timestring`, and the ids that link a result to the
  measurement it came from (`unique_id`, `id_link`).
- **`settings`** is the capture's `MySettings` as a plain dictionary, or
  `null`. The web logger reads `device_driver` and `VmaxSC` from it to
  tell whether a capture is in volts.
- **`ui`** is written only by the web logger: the channel labels
  (`channel_labels`), the x(iω) display power (`iw_power`), and the
  window, averaging and other settings of each calculation
  (`analysis`). Other readers can ignore it. Python keeps it, and any
  other key it doesn't recognise, when it loads and saves a file, so a
  round trip through a notebook loses nothing.

### Kinds of item

| `kind` | Arrays | What they hold |
| ------ | ------ | -------------- |
| `TimeData` | `time_axis`, `time_data` | time in seconds; the samples, one column per channel |
| `FreqData` | `freq_axis`, `freq_data` | frequency in Hz; the complex spectrum, one column per channel |
| `CrossSpecData` | `freq_axis`, `Pxy`, `Cxy` | the complex cross-spectrum matrix and the real coherence matrix, both channels × channels × frequencies |
| `TfData` | `freq_axis`, `tf_data`, `tf_coherence`, `bla_sigma_nl`, `bla_sigma_n` | the complex transfer function, one column per output channel (the input channel has none); its coherence; and the uncertainty of a best linear approximation |
| `SonoData` | `time_axis`, `freq_axis`, `sono_data` | frame times and frequencies; the complex sonogram, frequencies × frames × channels |
| `ModalData` | `M` | the fitted modes, one row per mode |
| `MetaData` | none | units, calibration factors and timestamps only |

Some kinds add to `meta`: `CrossSpecData` has `enbw_hz`, the window's
effective noise bandwidth in Hz (`Pxy / enbw_hz` is a spectral density);
`TfData` has `flag_modal_TF` and `bla`, the settings of a best linear
approximation run; and `ModalData` has `channels`, plus
`measurement_type` and `source_targets` when the web logger wrote it.
The [data structures](../api/datastructure.md) describe each field.

Two points about calibration in these items:

- On a `TfData`, `channel_cal_factors` has one entry for each output
  column: the ratio of that channel's factor to the input channel's.
  Its `units` entry is `output/input`, with a compound unit in
  brackets, such as `(m/s2)/N`.
- A `SonoData` saved by the web logger holds only the channels you chose
  at the save prompt. Its `units` and `channel_cal_factors` follow those
  planes, and `source_settings['channels']` names the measured channel
  each plane came from.

### Provenance: `source_signature` and `source_settings`

A `FreqData`, `TfData` or `SonoData` item can carry two optional `meta`
fields that say how it was made:

- **`source_signature`** is 16 hex characters: a hash of the samples the
  result was computed from, and their sample rate. Recompute it from the
  file's `TimeData` and compare, and you know whether the result still
  belongs to those samples. That is what raises the app's **⚠ source
  changed** badge (see [Saving and exporting](export.md#source-changed)).
  Settings are not in the hash, because a result computed with a
  different window is still a valid result of those settings. For a long
  record only evenly spaced rows are hashed (up to 65,536 values), so
  an edit to a few neighbouring rows can go unnoticed.
- **`source_settings`** holds the settings behind the result, with a
  `calc` key naming the calculation (`'fft'`, `'tf'`, `'sonogram'`, …).
  The web logger writes its own names (`nFft`, `voicesPerOctave`) and
  Python writes snake_case (`nperseg`, `voices_per_octave`). `calc`, and
  `method` for sonograms, are the same in both, so read those first.

The hashing algorithm is written out in `pydvma/_signature.py`.

## How values are encoded

The manifest is strict JSON, with no bare `NaN` or `Infinity`, so
`JSON.parse` in a browser always works. Values JSON can't hold are
wrapped in small tags:

| Tag | Meaning |
| --- | ------- |
| `{"__uuid__": "..."}` | a UUID (the ids that link items) |
| `{"__datetime__": "<isoformat>"}` | a timestamp |
| `{"__array__": [...]}` | a small array held in the manifest |
| `{"__float__": "inf" \| "-inf" \| "nan"}` | a non-finite number |

Tags apply at any depth. The large arrays keep their exact dtype in
their `.npy` members. A reader skips manifest keys it does not
recognise, so a file from a newer version still opens where the format
allows.

## Reading and writing from Python

```python
import pydvma as dvma

dvma.save_data(dataset, filename='my_measurement')       # adds .dvma
dataset = dvma.load_data(filename='my_measurement.dvma')
```

`load_data` recognises the format from the file's content, not its
extension, so a renamed file still loads. A save writes to a temporary
file first and renames it over the target only when it has finished, so
a crash mid-save can't damage an existing file. See
[Import and export](../user-guide/import-export.md#save-and-load-a-dataset-native-format)
and the [file functions](../api/file.md).

## Older `.npy` files

pydvma 1.4.0 and earlier saved a NumPy pickle of the live Python
objects. `.dvma` replaced it in 1.5 because the pickle could be read
only from Python, carried no version, could run arbitrary code when
opened, and broke whenever pydvma's code was reorganised.

Those files still open. `dvma.load_data()` recognises them from their
content, and the web logger converts them when you press **Load Data**.
Only open a `.npy` file from someone you trust, because unpickling can
run code. To write the old format anyway, give `save_data` a filename
ending in `.npy`.
