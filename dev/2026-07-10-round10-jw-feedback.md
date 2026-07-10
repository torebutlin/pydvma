# Round 10 — Jim Woodhouse's first hands-on feedback (2026-07-10)

JW tried the web logger on his own archives (email via Tore; his test
files live in `dev/example_data/`, left deliberately untracked — real
measurement data, ~40 MB). Three issues, all reproduced and fixed.

## 1. "Could only ever see the most recent file" → append-on-load

`actions.loadDataset` reset every store on each call, so the second
Load REPLACED the first — JW's old logger composited files ("Add on
load", which its save path explicitly supported and his archives rely
on). Now `loadDataset(ds, { append: true })`: with data already
present, the file's items merge into the existing dataset object (one
doc for autosave/Save Dataset), its sets register alongside the
current ones (orphan-TF pseudo-sets included), derived seeds merge,
and NOTHING resets — the live modal fit survives, and a ModalData
carried by an APPENDED file is deliberately ignored (one live model
per session). With nothing loaded, append degrades to the full load
(so Load Data always passes append:true). The toast says "Added
<file> alongside the loaded data." Focus follows the appended file's
first populated view. Replace-from-scratch = tray × per set or page
reload; documented in export.md.

## 2. KeyError on JW's time-data .mat → time files have no `npts`

`guitar_string4_5mar_1.mat` (dev/example_data): V2.9a TIME captures
save `indata, buflen, freq, dt2, tsmax` — NO `npts`, no `tfun` — but
the importer's time branch built its axis from `d['npts']` →
KeyError. (Every spectral file in JW's set has npts; only time files
differ. `tsmax` is a scale marker — indata is already physical units
(his file: ±4.44), so no rescale.) Fix: the time axis comes from
indata's own row count at fs=freq; row-vector indata transposes to a
column; `freq`/`npts` MATLAB (1,1) scalars unwrapped once. His real
file now imports (200000×1 @ 40 kHz) and round-trips the exact glue
path (import → container.save → load). New pytest class
(synthesized time-file fixtures, single + multichannel) and a
synthetic `jw_time.mat` e2e fixture through the full browser path.

## 3. "Error vanished before I could copy it" → sticky error toasts

Error-level toasts auto-dismissed after 4 s like everything else. Now
they pin open until the user closes them (the × was already there);
info/success keep the 4 s auto-dismiss, actionable toasts unchanged,
and an explicit `timeout` can still make an error transient. New
toast.test.ts covers all four behaviours.

## Suites at close

pytest 347/3 (+2 time-import tests; base grew on the PC day). vitest
660/1 (+7: 4 toast + 3 append). check 0/0. Playwright 81/7 (+2:
time-mat import, second-file append; both through the real engine).
mkdocs --strict green. Engine wheel rebuilt (file.py runs in pyodide).

Committed locally — NOT pushed (no push instruction this round).
