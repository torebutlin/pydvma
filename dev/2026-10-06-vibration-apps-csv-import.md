# Importing the Vibration Apps' transfer-function CSV (2026-10-06)

The **Transfer function** app on the course site
(https://torebutlin.github.io/vibration_apps/apps/frf/, 3C6 slides 3.2–3.6)
measures speaker → microphone in a browser (stepped sine, swept sine, band
noise or an audio file, with a chirp to find the loop delay) and saves every
measurement it holds as one CSV. Tore wants pydvma to import that file into a
DataSet, one `TfData` per measurement, so a phone or laptop measurement can
go straight into pydvma's plots and modal fits.

Nothing in pydvma has been changed. This note, the example file and a
working sketch (below; it runs against pydvma as it is) are all there is.

**Status (2026-10-06, later): implemented** as
`pydvma.file.import_from_vibration_apps_csv`, recognised by `load_data`
from the first line, and in the web app's Load Data through the engine op
`vibration_csv_to_dvma` (the same parser). Tore's choices: H1 only (H2 is a
TODO.md item, and this import changes when it lands); one-frame coherence
is None; the app's keys and notes go in `source_settings['vibration_apps']`.
Two departures from the sketch: the timestamp stays timezone-aware UTC (a
naive local time would be UTC under pyodide and so wrong in the browser),
with `timestring` rendered in local time; and a partly empty coherence
column keeps its NaN rather than being filled with 1.

- Example: `tests/data/vibration_apps_example.csv` (moved there from
  `dev/` as the test fixture)
  (the app's demo system, 5 measurements: noise in frames of 8192, a sweep
  ×4, a 20-point stepped sine, one frame of 2 s of noise, noise with the
  added mass, saved while hidden).
- The app's writer: `apps/frf/js/main.js` (`csv()`, `csvMeta()`); its own
  reader, for loading the file back into the app:
  `shared/js/dsp/tfcsv.js` (both in the vibration_apps repo).

## The format: `vibration-apps-tf-csv 1`

UTF-8 text. A block of `#` lines, a line of column names, then the rows.

```
# Vibration Apps transfer functions (vibration-apps-tf-csv 1)
# exported 2026-10-06T10:01:54.100Z from https://torebutlin.github.io/vibration_apps/apps/frf/ (3C6 slides 3.2-3.6)
# H1 = Sxy/Sxx, H2 = Syy/Syx, coherence = |Sxy|^2/(Sxx Syy): x what was played (or the reference channel where reference_channel=1), y the microphone
# units: H in microphone full scale per speaker full scale (uncalibrated, cal_factor 1); f in Hz; phase in degrees; time UTC
# measurements: 1,2,3,4,5
# columns: measurement,f_Hz,H1_re,H1_im,H1_dB,H1_phase_deg,coherence,H2_re,H2_im
# m1: test_name=…; timestamp=…; kind=noise; …        (one line of key=value pairs per measurement)
# m1 notes: … | … | …                                 (one line of notes in words per measurement)
…
measurement,f_Hz,H1_re,H1_im,H1_dB,H1_phase_deg,coherence,H2_re,H2_im
1,105.46875,…
```

- **First line** says the format and version: `(vibration-apps-tf-csv 1)`.
  Refuse anything else. A later version only adds keys or columns, so a
  reader should ignore what it does not know.
- **`# m<no>: `** then `key=value` pairs separated by `; `. Values never
  hold `;` or `=` (the app replaces them) and may be empty.
- **`# m<no> notes: `** then free text, items separated by ` | `: what was
  done about the loop delay, the frames, the audio devices, any flag.
- **Rows**: every measurement in the file, one after another, each row
  starting with its measurement number. Each has **its own frequencies**:
  a frame length's FFT bins within the band (a sweep's are its repeat's
  length), or a stepped sine's points (not a uniform grid, like a BLA set's
  excited bins). So one shared axis column, as in pydvma's own
  `export_to_csv`, cannot hold them.
- **Columns**: `f_Hz`; `H1_re`, `H1_im` (H₁ = S_xy/S_xx, x what was played
  or the reference channel, y the microphone); `H1_dB`, `H1_phase_deg`
  (redundant, for reading by eye); `coherence` (γ² = |S_xy|²/(S_xx S_yy),
  **empty for a result of one frame**, where it is 1 by definition);
  `H2_re`, `H2_im` (H₂ = S_yy/S_yx).
- **Units**: uncalibrated, microphone full scale per speaker full scale
  (`units=-`, `channel_cal_factors=1`). The loop delay the chirp found
  (`delay_s`) is already taken out of the phase.
- Measurement numbers are the app's card numbers: not necessarily 1…n
  (deleted ones are missing), listed in order on the `# measurements:` line.

Numpy note: `np.genfromtxt(..., names=True)` takes the first `#` line as
the names; skip the comment lines (`skip_header=`) as the sketch does.
`pandas.read_csv(f, comment='#')` reads it as it is.

### The keys, and where they go in pydvma

| key | meaning | pydvma |
|---|---|---|
| `test_name` | the card's name, e.g. `noise 10 s · 100 Hz–5 kHz` | `TfData.test_name` (prefixed `m<no>`) |
| `timestamp` | ISO 8601, UTC, when it was measured | `TfData.timestamp` |
| `fs` | sample rate, Hz | `settings.fs` |
| `channels`, `ch_in` | 1 output, input channel 0 | `settings.channels` (= outputs + 1), `settings.ch_in` |
| `device_name` | the microphone, as the browser named it | `settings.device_name` |
| `units`, `channel_cal_factors` | `-`, `1` (uncalibrated) | `TfData.units`, `TfData.channel_cal_factors` |
| `estimator` | `H1` (the `tf_data` columns) | — |
| `window` | `hann` (noise, file), `rect` (a sweep's repeats), empty (stepped sine) | `source_settings['window']` |
| `nperseg`, `frame` | FFT length used; `frame` as asked (`whole`, `sweep`) | `source_settings['nperseg']` |
| `N_frames` | averages (frames, sweep repeats, or a stepped sine's blocks per point) | `source_settings['N_frames']` |
| `overlap` | 0.5 for noise frames, 0 for sweep repeats | `source_settings['overlap']` |
| `kind` | `noise`, `sweep`, `sine` (stepped), `file` | `source_settings['calc']` |
| `source` | `mic`, or `demo` / `demo+mass` (the app's simulated system) | app's own |
| `f_lo_Hz`, `f_hi_Hz`, `level_dBFS`, `length_s`, `repeats`, `points`, `dwell_s`, `file` | the test signal | app's own |
| `reference_channel` | 1 if H used a second recorded channel as x | app's own |
| `delay_s`, `delay_fitted_s` | loop delay taken out; a pure delay still in the phase, if any | app's own |
| `coherence_median`, `snr_dB`, `peak_dBFS`, `flag` | quality: γ² median over the band, test signal over the room's noise in the band, microphone peak, `too loud` / `too quiet` / `γ² low (…)` | app's own |
| `output_latency_s` | the browser's output latency (about 2 s through AirPlay) | app's own |
| `view` | `shown`, `faded` or `hidden` in the app when saved (saving ignores it) | app's own |

The example's first measurement:

```
# m1: test_name=noise 10 s · 100 Hz–5 kHz; timestamp=2026-10-06T10:01:46.523Z; kind=noise; source=demo; fs=48000; channels=1; ch_in=0; units=-; channel_cal_factors=1; estimator=H1; window=hann; nperseg=8192; frame=8192; N_frames=120; overlap=0.5; f_lo_Hz=100; f_hi_Hz=5000; level_dBFS=-12; length_s=10; repeats=; points=; dwell_s=; file=; reference_channel=0; delay_s=0.04241788; delay_fitted_s=; coherence_median=0.999; snr_dB=34.5; peak_dBFS=; device_name=; output_latency_s=; flag=; view=shown
```

## Suggested API

`pydvma.file.import_from_vibration_apps_csv(filename) -> DataSet`, one
`TfData` per measurement in the file's order, and perhaps `load_data`
recognising a `.csv` whose first line names the format. Choices for Tore:

- **Coherence of a one-frame result**: the sketch passes `None` when the
  whole column is empty (as a BLA set does). A mix cannot happen: each
  measurement is one or the other.
- **H₂**: `TfData` has no field for it. The sketch keeps it as `tf.H2`
  beside the TfData; a second TfData, or a field, are the alternatives.
- **The app's own keys and notes**: the sketch puts them in
  `source_settings['vibration_apps']` (JSON-clean strings), so they
  round-trip through a `.dvma` file. `source_signature` is not set: there
  is no time data behind these.
- **Stepped sine** points are not a uniform grid; the modal fits should be
  fine with that (BLA sets already have only excited bins), the plots too.
- The web UI (`webui/`) could import the same file; the format is simple
  enough to parse in TypeScript as `shared/js/dsp/tfcsv.js` does.

Tests worth having: the example file's five sets (rows 836, 13380, 20,
13380, 836); measurement 4 has no coherence; measurement 5 was hidden
(`view=hidden`) and is imported all the same; a non-matching first line is
refused; unknown keys are ignored.

## The sketch (runs against pydvma 2.6 as it is)

```python
"""Sketch: import a Vibration Apps transfer-function CSV (vibration-apps-tf-csv 1) into a pydvma DataSet."""
import datetime
import re

import numpy as np

from pydvma import datastructure, options

FORMAT = 'vibration-apps-tf-csv 1'


def _num(s, default=None):
    try:
        return float(s) if s not in (None, '') else default
    except ValueError:
        return default


def read_vibration_apps_csv(filename):
    '''The header (title lines, per-measurement key=value pairs and notes) and the rows, grouped by measurement.'''
    meta, notes, head, n_comment = {}, {}, [], 0
    with open(filename, encoding='utf-8') as fh:
        for line in fh:
            if not line.startswith('#'):
                break
            n_comment += 1
            body = line[1:].strip()
            m = re.match(r'm(\d+)( notes)?: ?(.*)$', body)
            if m and m.group(2):
                notes[int(m.group(1))] = m.group(3).split(' | ')
            elif m:
                meta[int(m.group(1))] = dict(kv.split('=', 1) if '=' in kv else (kv, '') for kv in m.group(3).split('; '))
            else:
                head.append(body)
    if not head or FORMAT not in head[0]:
        raise ValueError('%s is not a %s file' % (filename, FORMAT))
    # names from the line after the comments: genfromtxt would otherwise take the first '#' line as the names
    data = np.atleast_1d(np.genfromtxt(filename, delimiter=',', skip_header=n_comment, names=True, encoding='utf-8'))
    out = []
    for no, md in meta.items():
        rows = data[data['measurement'] == no]
        out.append(dict(no=no, meta=md, notes=notes.get(no, []), f=rows['f_Hz'],
                        H1=rows['H1_re'] + 1j * rows['H1_im'], H2=rows['H2_re'] + 1j * rows['H2_im'],
                        coherence=rows['coherence']))
    return head, out


def import_from_vibration_apps_csv(filename):
    '''One TfData per measurement, in a new DataSet.'''
    head, ms = read_vibration_apps_csv(filename)
    dataset = datastructure.DataSet()
    for m in ms:
        md = m['meta']
        fs = _num(md.get('fs'), 48000.0)
        settings = options.MySettings(channels=int(_num(md.get('channels'), 1)) + 1, fs=int(round(fs)))
        settings.ch_in = int(_num(md.get('ch_in'), 0))
        if md.get('device_name'):
            settings.device_name = md['device_name']
        coh = m['coherence']
        coherence = None if np.all(np.isnan(coh)) else np.nan_to_num(coh, nan=1.0)[:, None]
        tf = datastructure.TfData(m['f'], m['H1'][:, None], coherence, settings,
                                  units=[md.get('units') or '-'],
                                  channel_cal_factors=np.array([_num(md.get('channel_cal_factors'), 1.0)]),
                                  test_name='m%d %s' % (m['no'], md.get('test_name', '')))
        if md.get('timestamp'):
            tf.timestamp = datetime.datetime.fromisoformat(md['timestamp'].replace('Z', '+00:00'))
        # what pydvma's own analysis records in source_settings, plus the app's own keys
        tf.source_settings = {
            'calc': 'vibration_apps_' + md.get('kind', ''),
            'window': md.get('window') or None,
            'N_frames': int(_num(md.get('N_frames'), 1)),
            'overlap': _num(md.get('overlap')),
            'nperseg': _num(md.get('nperseg')),
            'ch_in': settings.ch_in,
            'vibration_apps': dict(md, notes=m['notes']),
        }
        tf.H2 = m['H2'][:, None]   # not a TfData field: kept beside it for now
        dataset.add_to_dataset(tf)
    return dataset


if __name__ == '__main__':
    import sys
    ds = import_from_vibration_apps_csv(sys.argv[1])
    for tf in ds.tf_data_list:
        c = tf.tf_coherence
        print(tf.test_name, '| f', tf.freq_axis[0].round(1), '…', tf.freq_axis[-1].round(1), '| n', len(tf.freq_axis),
              '| |H| max dB', np.round(20 * np.log10(np.abs(tf.tf_data).max()), 1),
              '| coherence', 'none' if c is None else np.round(np.median(c), 3), '| fs', tf.settings.fs,
              '| N_frames', tf.source_settings['N_frames'], '| view', tf.source_settings['vibration_apps']['view'])
```

Its output on the example:

```
m1 noise 10 s · 100 Hz–5 kHz | f 105.5 … 4998.0 | n 836 | |H| max dB -0.3 | coherence 0.999 | fs 48000 | N_frames 120 | view shown
m2 sweep 1 s ×4 · 100 Hz–5 kHz | f 100.3 … 4999.9 | n 13380 | |H| max dB 0.1 | coherence 0.999 | fs 48000 | N_frames 4 | view shown
m3 sine 20 pts · 100 Hz–5 kHz | f 100.0 … 5000.7 | n 20 | |H| max dB -4.9 | coherence 1.0 | fs 48000 | N_frames 4 | view shown
m4 noise 2 s · 100 Hz–5 kHz | f 100.3 … 4999.9 | n 13380 | |H| max dB 0.1 | coherence none | fs 48000 | N_frames 1 | view shown
m5 noise 10 s · 100 Hz–5 kHz + mass | f 105.5 … 4998.0 | n 836 | |H| max dB -0.5 | coherence 0.999 | fs 48000 | N_frames 120 | view hidden
```

## Update from the app, 6 Oct afternoon (after 4936795)

Written from the vibration_apps side; nothing in pydvma's code was touched.
`import_from_vibration_apps_csv` as committed reads the new files unchanged
(checked: the five sets of the refreshed example, axes 836 / 13380 / 20 /
13380 / 836, coherence None for the one-frame set).

- **Each measurement has its own frequency axis.** Rows are grouped by
  `measurement` and each group's `f_Hz` is that TfData's `freq_axis`: noise
  in frames of N has the FFT bins k·fs/N in the band, a sweep its repeat's
  padded length, a whole-record frame that record's, and a stepped sine
  only its points (log-spaced, not a grid). Do not put them onto a common
  grid on import. The committed importer already does this; worth a test
  that says so (the first set starts at 105.47 Hz, the second at 100.34 Hz).
- **New column `H_power`** (last, after `H2_im`): |H| from the powers alone,
  √((S_yy − S_nn)/S_xx), with S_nn the room's noise per frame, heard before
  the chirp arrived, taken off. A magnitude with no phase. In the app it is
  the "power" option, the one to try where the loop delay is suspect
  (Bluetooth, AirPlay: a delay that wanders spoils H₁, by 10 dB or more in
  long frames, and leaves H_power alone). Empty for a stepped sine, and in
  a bin where the noise is all there is. If pydvma wants it: a second,
  magnitude-only TfData (zero phase, flagged so the phase plot and the
  modal fits leave it alone), or a field beside `tf_data`.
- **New key `file_start_s`**: for `kind=file`, where in the audio file the
  stretch played began, in seconds from its beginning (0: its first sound).
- The refreshed example, with both: `dev/2026-10-06-vibration-apps-example.csv`
  (`tests/data/vibration_apps_example.csv` is the earlier one, without them).

**pydvma side, after the update:** the refreshed example (with `H_power`
and `file_start_s`) is now the test fixture,
`tests/data/vibration_apps_example.csv`, replacing the earlier one; the
`dev/` copy was moved there. A test pins that each measurement keeps its
own axis (105.47 Hz and 100.34 Hz starts). `H_power` is not imported yet:
it sits in TODO.md beside H2 as a decision for Tore.

## Update 2 from the app, 6 Oct: time data (format 2) and the auto-spectra

Written from the vibration_apps side (its commit 81a8d39); nothing in
pydvma's code was touched. The committed importer reads every format-1 file
the app now writes (checked) and refuses format 2 with its clear message.

**In every file (still format 1):**

- Two more columns at the end of the transfer-function table, **`Gxx`** and
  **`Gyy`**: the auto-spectra of x and y as one-sided densities, full scale²
  per Hz, averaged over the frames as H₁ is (2·Σ|X|² / (frames · fs · Σw²);
  a Hann frame, a sweep's rectangular repeat, or the whole record). Checked
  against `scipy.signal.welch` on the exported time data: 0.000 dB. Empty
  for a stepped sine. With H₁ and γ² they give the whole cross-spectral
  matrix: G_xy = H₁·G_xx, so a `CrossSpecData` (P_xx, P_xy, P_yy, C_xy) per
  measurement is possible if pydvma wants one.
- A line `# section: tf` now comes just before the column names. It is a
  `#` line, so a reader that skips them (as the importer does) is unaffected.

**Format 2: `vibration-apps-tf-csv 2`**, written when the app's "time data"
box is ticked beside Save CSV. Everything in format 1, then a second table:

```
# section: time
measurement,t_s,x,y
1,0.000000,0.01093,0.0002101
…
```

- One block of rows per measurement that has time data: those with
  `time_rows=<n>` in their `# m<no>:` line. A stepped sine never has any
  (it comes in as its transfer function only).
- `t_s`: 0 where the test signal began as played, in steps of 1/fs.
- `x`: what was played (`time_x=played`), or the reference channel where
  there was one (`time_x=reference`). `y`: the microphone, moved earlier by
  the loop delay to the nearest sample, so x and y line up as the app
  analysed them. The fraction of a sample left in y is
  `time_delay_left_samples` (within ±0.5). H₁ in the file has it taken out
  of its phase; H₁ worked out from the time data carries an extra
  2π·f·left/fs (at most 19° at 5 kHz and 48 kHz).
- Checked: H₁ from the time data with scipy (Hann 8192, half overlap)
  matches the file's H₁ to 0.000 dB in magnitude, and in phase to the
  fraction above (median 1.7° there).
- Size: tens of MB (10 s of noise and four 1 s sweeps at 48 kHz: 26.7 MB),
  so read it line by line rather than with one `genfromtxt` over the file;
  split at the `# section: time` line.

**Mapping, for an importer of format 2**, beside each TfData:
`TimeData(time_axis=t_s, time_data=np.column_stack([x, y]), settings)` with
`settings.fs = fs`, `settings.channels = 2`, channel 0 the input (x) and
channel 1 the microphone (y), units `['-', '-']`, cal factors 1, the same
`test_name` and `timestamp`; and the TfData's `id_link` set to that
TimeData's `unique_id`, so pydvma's own `calculate_tf` / `calculate_tf_averaged`
on it (ch_in = 0) can be compared with the app's result.

Example: `dev/2026-10-06-vibration-apps-example-v2-time.csv` (5.5 MB: noise
1 s in frames of 4096, a sweep of 0.5 s ×2, a 20-point stepped sine; time
rows 67 200 and 86 400; the sine has none). Its first lines, cut at 160 characters here:

```
# Vibration Apps transfer functions (vibration-apps-tf-csv 2)
# exported 2026-10-06T10:44:40.293Z from https://torebutlin.github.io/vibration_apps/apps/frf/ (3C6 slides 3.2-3.6)
# H1 = Sxy/Sxx, H2 = Syy/Syx, coherence = |Sxy|^2/(Sxx Syy): x what was played (or the reference channel where reference_channel=1), y the microphone
# H_power = sqrt((Syy - Snn)/Sxx), |H| from the powers alone with the room noise Snn (heard before the chirp) taken off: no phase, so a wandering delay cannot s
# units: H in microphone full scale per speaker full scale (uncalibrated, cal_factor 1); f in Hz; phase in degrees; time UTC
# Gxx, Gyy: the auto-spectra of x and y as one-sided densities, full scale^2 per Hz (averaged over the frames as H1 is); empty for a stepped sine
# time data: after the transfer functions, a line "# section: time", its column names, then rows measurement,t_s,x,y for each measurement with time_rows in its 
# measurements: 1,2,3
# columns: measurement,f_Hz,H1_re,H1_im,H1_dB,H1_phase_deg,coherence,H2_re,H2_im,H_power,Gxx,Gyy
# m1: test_name=noise 1 s · 100 Hz–5 kHz; timestamp=2026-10-06T10:44:35.111Z; kind=noise; source=demo; fs=48000; channels=1; ch_in=0; units=-; channel_cal_fa
# m1 notes: delay through the measurement: steady to within 0.002 ms (2 of 2 pieces of 0.5 s found; played); 0.015 ms from the chirp's | frames: 23 of 24 found 
# m2: test_name=sweep 0.5 s ×2 · 100 Hz–5 kHz; timestamp=2026-10-06T10:44:36.079Z; kind=sweep; source=demo; fs=48000; channels=1; ch_in=0; units=-; channel_
```

**pydvma side, after update 2:** formats 1 and 2 both import. Format 2's
time data becomes a `TimeData` per measurement (x channel 0, y channel 1,
the axis rebuilt exactly from fs since `t_s` is rounded to the
microsecond), and `Gxx`/`Gyy` with H1 and γ² a `CrossSpecData` (pydvma's
convention: a one-sided power spectrum, the density times `enbw_hz` from
the stated window and `nperseg`; checked against `scipy.signal.welch` on
the imported time data). A measurement's items share one `id_link` (the
TimeData's id, or one minted for it), so the web app shows each
measurement as one card. An H1 with no phase anywhere is flagged
(`(|H| only, no phase)` in its name, `source_settings['magnitude_only']`,
a warning); a minimum-phase reconstruction is a TODO. The v2 example now
lives at `tests/data/vibration_apps_example_v2_time.csv`. NB `f_Hz` is
written to about 8 significant figures (1019.5313 for 1019.53125), so it
is not exactly the FFT bin; harmless, but a reader matching bins by value
must round.

