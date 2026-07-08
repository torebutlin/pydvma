# Example measurement data

Real measurement files for hands-on testing and manual regression of
the web logger (and the Python API). Both have caught genuine bugs —
they exercise paths synthetic fixtures miss.

| File | What it is | Why it's useful |
| ---- | ---------- | --------------- |
| `grid_data.npy` | 4C6 teaching-lab grid measurement (2019, legacy pickle format): **12 sets**, each 2-channel TimeData (fs 3000, 3 s) with linked FreqData + TfData | Legacy pre-`modal_data_list` pickle (exercises `DataSet.__setstate__` normalisation); multi-set loading; derived-kind seeding; **multi-set shared-pole fitting** |
| `ruler_grid_acc_3.mat` | Ruler-grid accelerometer transfer functions (Jim Woodhouse): a bare 10-column TF matrix, **no time data** | MATLAB import; **orphan-TF** convention (chIn = null, columns are lines); time-less sets must be excluded from sonogram targeting; orphan fitting |

Try them: open the app (live Pages URL or `pydvma-serve --open`) →
**Load Data** → pick a file. `grid_data.npy` lands 12 tray sets and
should jump to the Time view; `ruler_grid_acc_3.mat` lands one orphan
TfData set and should jump to the TF view.

These are real teaching/research data — kept for testing, not as
documentation examples. Automated tests use small synthetic fixtures
in `webui/tests/fixtures/` instead; keep it that way (these files are
large and not versioned per-test).
