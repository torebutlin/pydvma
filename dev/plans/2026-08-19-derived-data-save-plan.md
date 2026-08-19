# Derived-Data Save Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development. Steps use checkbox syntax.
> House rules: edit master directly, commit per task, NEVER `git stash`
> or `git reset`, Playwright ONLY from `webui/`, docstrings
> griffe-strict, `pydvma/engine.py` edits require a wheel rebuild note.

**Goal:** Save Dataset materialises the app's computed analysis views
into real items inside the `.dvma` document (Tore's data-with-processing
concept end-to-end), each stamped with a compute-chain signature so a
broken chain is flagged rather than silently trusted; Save/Export gain
a per-measurement subset picker; Python gets subset parity.

**Decisions (agreed with Tore, 2026-08-19 chat — recorded in TODO.md):**
materialise on Save; items stand until recomputed with a
"source changed — rederive?" flag on broken chains; replace-by-lineage
keeps re-saves idempotent; subset via an explicit "Choose sets…"
split-button (all-by-default), never driven by view/fade state;
journal/autosave do NOT auto-materialise (explicit Save only — though
once materialised, items are simply part of the document and ride
subsequent autosaves like any other item, which is correct and
intended).

**Scope decisions taken in this plan (Tore can veto):**
1. **Round 1 materialises FFT (FreqData) and TF (TfData incl.
   coherence).** SonoData is EXCLUDED: the app's derived sono slice is
   a single-channel magnitude image (the container schema wants the
   full multi-channel complex cube), so an honest SonoData would need
   a full recompute at save time. Deferred with a TODO note. CSD
   matrices likewise deferred. BLA TfData and ModalData are ALREADY
   real items — untouched.
2. **The signature covers SOURCE SAMPLES only** (+ fs), not settings:
   staleness means "the time data changed since this was computed"
   (Tore's scaled/edited case). The analysis settings used are stored
   ALONGSIDE as provenance (`source_settings`) — a settings change
   does not invalidate a stored result, it is still a valid TF *of its
   settings*.
3. **Signature algorithm is FNV-1a 64-bit over the little-endian
   float64 sample bytes**, hex-encoded — ~20 lines in each language,
   no dependencies, pinned cross-language by a shared known-answer
   vector AND the existing JS↔Python round-trip fixture pipeline.

**Verified facts (explored 2026-08-19; file:line anchors current at
plan time):**
- Save path: `App.svelte:470` (autosave thunk) and `:801-802` (Save
  button) both do `actions.stampUiState()` → `writeDvma(ds)`.
  `stampUiState` (`actions.ts:700-738`) stamps `ui` onto source
  TimeData items — the natural sibling seam for materialisation.
- JS-authored derived items have precedent: `addBlaSets`
  (`actions.ts:1319-1388`) builds `TfData` `DvmaItem`s from raw
  Float64Arrays (NpyArray construction, `metaRaw` with
  `{__datetime__}` timestamp); `upsertModalItem` (`:1770-1803`) is the
  upsert precedent but is a SINGLE reference — per-set/per-kind
  lineage needs a `Map` keyed `${setId}:${kind}`.
- Derived store: `DerivedMap` (`actions.ts:146`, store at `:346`),
  slice shapes in `plot/model.ts:81-131` (`freq` complex; `tf` with
  `coherence`/`chIn`/`sigmaNl`/`sigmaN`; `DecodedArray` = split
  re/im). Per-set settings: `analysisSettings.ts` `PerSetSettings`
  (`:91`).
- Set model: `working: WorkingSet[]` (`actions.ts:137-143`);
  `idLinkOf(setId)` (`:1744-1750`) recovers the source `unique_id`;
  load-side `linkToSet` map (`:509-522`); Pass 2 derived-item seeding
  (`:575-616`). Set display names: `selection.ts` `SetRecord.name`,
  rendered/renamed in `TrayCard.svelte` (~260-284); badge precedent
  `.dur-badge`/`.fit-badge` (`TrayCard.svelte:287-292`, `475-487`).
- Export: `exportArrays(kind)` (`actions.ts:2434-2467`) and
  `exportMat()` (`:2477-2496`) loop `working` unfiltered;
  `buildCsvFiles` (`export/data.ts:155-163`) via the `Exporter`
  interface (`:49-54`). Sono/CSD are NOT in the export surface today.
  Figure export is separate — out of scope.
- Popover precedent: `ZoomToolbar.svelte` `.ax-pop` (~479+, absolute,
  `data-testid="axis-popover"`); no shared popover component exists.
  `ExportCard.svelte:200-219` is flat button rows.
- Python: `analysis.py` stamps `id_link=time_data.unique_id` at every
  calc creation site (67, 353, 466, 1203, 1535); `_OPTIONAL_META`
  (`container.py:123-127`) is the extensibility seam (hasattr-gated
  write `:393-396`, presence-gated read `:527-531`) — the
  `impulse_cleaned`/`iw_power_counter` precedent; unknown keys survive
  via `_container_extra` regardless. `file.py::save_data` (`:72`) has
  no sets filter; `DataSet` has no subset helper. NO hashing utility
  exists on either side.
- Tests: `webui/tests/codec/dvma.test.ts`, `analysis/actions.test.ts`
  (round-trip suites at 1193-1330), `analysis/addBlaSets.test.ts`
  (JS-authored TfData round-trip — the direct template),
  `codec/crosscheck.test.ts` → `tests/test_container.py::
  test_real_webui_fixture_round_trips_losslessly` (the cross-language
  pipeline any new manifest field must keep green);
  `test_container.py:326/349` are the `_OPTIONAL_META` test template.
  Playwright: `e2e/export.spec.ts` (CSV/Matlab flows),
  `e2e/files.spec.ts` (load/autosave), `e2e/tray.spec.ts`.
- Naming caution: `selection.ts` already uses "family" for
  data-vs-fit Tab-cycling (:199-256). This plan says **measurement /
  set** throughout; do not introduce "family" into code.

**File map:**
- Create: `pydvma/_signature.py` (+ `tests/test_signature.py`)
- Modify: `pydvma/analysis.py` (stamp at calc sites),
  `pydvma/container.py` (`_OPTIONAL_META`), `pydvma/datastructure.py`
  (`DataSet.subset`), `pydvma/file.py` (`save_data(sets=…)`)
- Create: `webui/src/lib/codec/signature.ts` (+ vitest)
- Modify: `webui/src/lib/analysis/actions.ts` (materialise + lineage
  map + staleness on load + export filters), `webui/src/components/
  TrayCard.svelte` (stale badge), `webui/src/components/cards/
  ExportCard.svelte` + new `webui/src/components/ChooseSetsPopover.svelte`,
  `webui/src/lib/export/data.ts` (filter threading)
- Create: `webui/e2e/derived-save.spec.ts`
- Docs: `docs/web-logger/export.md`, `docs/web-logger/index.md`,
  `docs/web-logger/migration.md`, `docs/examples/basic.md`,
  `CHANGELOG.md`, TODO/round close-out.

---

### Task 1: The signature, Python side

**Files:** Create `pydvma/_signature.py`, `tests/test_signature.py`;
modify `pydvma/analysis.py`, `pydvma/container.py`.

- [ ] **Step 1 — failing tests** (`tests/test_signature.py`):

```python
"""Compute-chain signature: FNV-1a 64-bit over little-endian float64
sample bytes, hex-encoded. The SAME algorithm is implemented in
webui/src/lib/codec/signature.ts — the known-answer vectors here and
there MUST agree; change one and you must change both (the
cross-language fixture round-trip pins it end-to-end).
"""
import numpy as np

from pydvma import _signature


class TestFnv1a64:

    def test_known_answer_empty(self):
        assert _signature.fnv1a64(b'') == 'cbf29ce484222325'

    def test_known_answer_abc(self):
        assert _signature.fnv1a64(b'abc') == 'e71fa2190541574b'

    def test_known_answer_float_vector(self):
        # THE cross-language vector: [0.0, 1.0, -1.5] as '<f8' bytes.
        data = np.array([0.0, 1.0, -1.5]).astype('<f8').tobytes()
        expected = _signature.fnv1a64(data)
        # Computed once at implementation time and FROZEN here and in
        # signature.test.ts — fill the literal in during Step 3 and
        # record it in both files.
        assert expected == _signature.fnv1a64(data)  # replace with literal


class TestSourceSignature:

    def test_signature_of_time_data(self):
        from pydvma import datastructure, options
        s = options.MySettings(device_driver='mock', channels=2, fs=8000)
        td = datastructure.TimeData(
            time_axis=np.arange(16) / 8000.0,
            time_data=np.arange(32, dtype=float).reshape(16, 2),
            settings=s)
        sig = _signature.source_signature(td)
        assert isinstance(sig, str) and len(sig) == 16
        # deterministic
        assert sig == _signature.source_signature(td)

    def test_signature_changes_when_samples_change(self):
        ...  # same TimeData, mutate one sample, signature differs

    def test_signature_ignores_display_state(self):
        ...  # channel_cal_factors / units changes do NOT change it

    def test_signature_includes_fs(self):
        ...  # same samples, different settings.fs → differs
```

Fill every `...` body. Run; watch fail.

- [ ] **Step 2 — implement `pydvma/_signature.py`:**

```python
# -*- coding: utf-8 -*-
"""Compute-chain signatures (derived-data save round, 2026-08-19).

A derived item (FFT, TF) records a short signature of the SOURCE
samples it was computed from, so a loaded file can tell whether the
chain is intact ("this TF really is the TF of that time data") or
broken (the time data was edited/scaled/resampled after the compute) —
shown in the app as a "source changed — rederive?" flag, never a
silent recompute. Display-side state (calibration factors, units,
x(iw) power) is deliberately NOT hashed: it never changes the samples.

The algorithm is FNV-1a 64-bit over the little-endian float64 sample
bytes plus the sample rate, hex-encoded — chosen because it is ~15
identical lines in Python and TypeScript with no dependencies. The
TypeScript twin is ``webui/src/lib/codec/signature.ts``; the two are
pinned to each other by shared known-answer vectors and the
JS<->Python fixture round-trip. This is an integrity check against
accidental edits, not a cryptographic guarantee.
"""
import numpy as np

_FNV_OFFSET = 0xcbf29ce484222325
_FNV_PRIME = 0x100000001b3
_MASK = 0xFFFFFFFFFFFFFFFF


def fnv1a64(data):
    """FNV-1a 64-bit hash of ``data`` (bytes), as 16 hex characters."""
    h = _FNV_OFFSET
    for b in data:
        h = ((h ^ b) * _FNV_PRIME) & _MASK
    return '%016x' % h


def source_signature(time_data):
    """Signature of a TimeData's samples + rate.

    Hashes the little-endian float64 bytes of ``time_data.time_data``
    followed by ``settings.fs`` as one little-endian float64 — the
    exact bytes the TypeScript twin hashes, so signatures written by
    either side verify on the other.
    """
    samples = np.ascontiguousarray(time_data.time_data, dtype='<f8')
    fs = np.float64(time_data.settings.fs).astype('<f8')
    return fnv1a64(samples.tobytes() + fs.tobytes())
```

NOTE: `for b in data` over large arrays is slow in pure Python
(~seconds for 10 MB). Implement the hot loop with
`np.frombuffer(data, dtype=np.uint8)` and a vectorised or
chunked-int approach ONLY IF a direct timing check shows >100 ms on a
30 s × 4 ch × 51.2 kHz array; otherwise keep the simple loop.
Actually: measure FIRST (Step 3a below) — a 47 MB buffer at ~50 ns/byte
is ~2.4 s, which IS too slow for a save click. Expected outcome: you
will need the chunked implementation. A clean approach that stays
identical cross-language: hash a REDUCED byte stream — every sample of
arrays up to 1 M samples; for larger arrays, a deterministic stride
that samples ≤1 M values PLUS the array shape and the first/last 4096
bytes. If you take this route the EXACT reduction rule must be
specified in both implementations' docstrings and covered by the
shared vectors (add a >1 M-sample vector). Choose, implement
identically in Task 2, and record the choice in the plan-deviation
notes.

- [ ] **Step 3 — stamp at the Python calc sites.** In
`pydvma/analysis.py`, at each derived-item creation site that sets
`id_link=time_data.unique_id` for FFT and TF results
(`calculate_fft`, `calculate_tf`, `calculate_tf_averaged` — lines ~67,
~353, ~466; read each site), set post-construction:

```python
    freq_data.source_signature = _signature.source_signature(time_data)
    freq_data.source_settings = {'window': str(window), ...}  # the
    # ACTUAL parameters that call used — read each function's
    # signature and record its real knobs (window, N_frames, overlap,
    # time_range) as plain JSON-safe scalars.
```

Import `_signature` at module top. CrossSpec/sono sites: NOT stamped
this round (out of scope — leave them).

- [ ] **Step 4 — container round-trip.** `container.py`
`_OPTIONAL_META`: add `'source_signature'` and `'source_settings'` to
the `FreqData` and `TfData` lists. Tests: clone the
`test_v2_optional_analysis_attrs_roundtrip` / `absent_stay_absent`
pattern (`test_container.py:326/349`) for the two new fields.

- [ ] **Step 5:** `python -m pytest tests/test_signature.py
tests/test_container.py tests/test_analysis.py -q` green; full sweep;
mkdocs strict. Commit:
`feat(signature): compute-chain signatures — FNV-1a-64 source hashes stamped on FFT/TF results`

### Task 2: The signature, TypeScript side

**Files:** Create `webui/src/lib/codec/signature.ts`,
`webui/tests/codec/signature.test.ts`.

- [ ] Implement `fnv1a64(bytes: Uint8Array): string` with BigInt
arithmetic (mask to 64 bits) and
`sourceSignature(samples: Float64Array, fs: number): string` hashing
EXACTLY the bytes Task 1 defined (little-endian float64 samples + fs;
JS typed arrays are little-endian on every supported platform — assert
via DataView if you want belt-and-braces; if Task 1 adopted the
large-array reduction rule, implement the identical rule). Vitest:
the SAME known-answer vectors as `tests/test_signature.py` (empty,
'abc', the float vector, the large-array vector if applicable) with a
comment naming the Python twin. `npm run check` + vitest green.
Commit: `feat(webui): signature.ts — the FNV-1a-64 twin of pydvma._signature`

### Task 3: Materialise on Save (webui)

**Files:** Modify `webui/src/lib/analysis/actions.ts`; extend
`webui/tests/analysis/actions.test.ts`.

**Read first:** `stampUiState`, `addBlaSets` (the item-construction
template), `upsertModalItem`, loadDataset Pass 2, the `derived` store
shapes, `idLinkOf`.

- [ ] **Step 1 — failing tests** (extend the round-trip suite at
`actions.test.ts:1193+`, following its harness): after a mock
capture + `calcFft` + `calcTf`, calling the new
`actions.materializeDerived()` then `writeDvma(ds)` →
`readDvma` → fresh `loadDataset` yields: a FreqData item and a TfData
item linked to the source set (`id_link` matches), coherence intact
on the TfData, `source_signature` present and equal to
`sourceSignature(source samples, fs)`, `source_settings` carrying the
settings used; calling materialise+save TWICE yields exactly ONE
FreqData + ONE TfData (replace-by-lineage); loading a file that
already carries materialised items and re-saving does NOT duplicate
them (lineage map seeded from load); a set with no computed views
materialises nothing; BLA sets and the modal item are untouched.

- [ ] **Step 2 — implement `materializeDerived()`** in
`createActions`:
- module-scope `const materializedItems = new Map<string, DvmaItem>()`
  keyed `` `${setId}:${kind}` `` (kind ∈ 'freq' | 'tf');
- seeded during `loadDataset` Pass 2: a loaded FreqData/TfData item
  that resolves to a set registers itself in the map (so re-saves
  replace);
- `materializeDerived()` walks `working`; for each set with a
  `derived[setId].freq` slice builds/updates a FreqData item (
  `freq_axis` + complex `freq_data` re-interleaved from the
  DecodedArray — follow `addBlaSets`' NpyArray/metaRaw construction
  exactly), likewise `tf` → TfData (`tf_data` + `tf_coherence` when
  the slice has `coherence`); stamps `id_link` via `idLinkOf(setId)`,
  `source_signature` via `sourceSignature(...)` over the SOURCE
  TimeData item's samples + fs, `source_settings` from the per-set
  `analysisSettings` snapshot (same diff-from-defaults shape
  `stampUiState` uses), `test_name` from the set name; upserts via
  the map (mutate arrays/meta in place when present, else push +
  register);
- deleted/removed sets: if the map holds an item whose set no longer
  exists, leave the item alone (it is document data; removal is the
  user's Remove action, unchanged this round).
- [ ] **Step 3 — call it on Save.** In `App.svelte`, the Save handler
(`onsave`, ~:801) calls `actions.materializeDerived()` before
`stampUiState()`. The AUTOSAVE thunk does NOT call it (agreed:
explicit Save only; materialised items naturally ride later autosaves
once they exist — add exactly this sentence as a comment).
- [ ] **Step 4:** vitest + `npm run check` green. Commit:
`feat(webui): Save materialises computed FFT/TF into the document — replace-by-lineage, signature-stamped`

### Task 4: Staleness flag on load (webui)

**Files:** Modify `actions.ts` (Pass 2), `TrayCard.svelte`,
`selection.ts` ONLY if a per-set flag store is genuinely needed (read
first — prefer a small store in actions or a field on the tray's
view-model, following how `fit-badge` gets its data).

- [ ] Pass 2: when a loaded FreqData/TfData item carries
`source_signature` AND its source TimeData is present, recompute the
source's signature; on mismatch mark that set+kind stale (store:
`staleChains: Record<setId, kinds[]>` or similar). Items without a
signature (older files): no flag, no assumption.
- [ ] TrayCard: a small badge beside `.dur-badge` when the set has any
stale chain — text `⚠ source changed`, `title` explaining ("this
set's saved TF/FFT was computed from earlier time data — rederive to
refresh"), `data-testid="stale-chain-badge"`. Clicking it triggers the
relevant recompute(s) via the existing calc actions (which overwrites
the derived view; the flag clears when a later Save re-materialises —
ALSO clear the in-memory flag immediately on recompute).
- [ ] Tests: vitest for the Pass-2 detection (build a file where the
source samples were mutated after stamping — construct via the codec
in-test); a component-level assertion is NOT required (no component
test precedent) — cover the badge in Task 7's e2e instead.
- [ ] Commit: `feat(webui): broken compute chains flagged on load — stale badge with click-to-rederive`

### Task 5: Subset picker (webui Save/Export)

**Files:** Create `webui/src/components/ChooseSetsPopover.svelte`;
modify `ExportCard.svelte`, `actions.ts` (`exportArrays`/`exportMat`
gain `setIds?: readonly number[]`), `export/data.ts` (thread the
filter through `Exporter`), `App.svelte` (save path accepts a subset).

- [ ] Popover: checkbox list of sets (name + kind badges built from
`derived[setId]`: time · fft · tf · fit), all ticked initially,
OK/Cancel, absolutely positioned following the `.ax-pop` pattern
(`data-testid="choose-sets-popover"`). Selection state is LOCAL to
the popover per invocation — deliberately not persisted and never
read from view/fade state.
- [ ] ExportCard: each of Save Dataset / Export Matlab / Export CSV
becomes a split control — the primary button unchanged
(everything, no dialog), a narrow `▾`/`Choose sets…` secondary
opening the popover; OK runs the same action with the chosen
`setIds`. Save-with-subset builds a FILTERED document: the chosen
sets' TimeData + every item id_linked to them + the modal item when
any of its links resolve into the chosen sets (read how ModalData
id_link lists work in Pass 3 first); materialisation still runs
first, so a subset save carries the chosen sets' derived items.
- [ ] Export filters: `exportArrays(kind, setIds?)` /
`exportMat(setIds?)` filter `working`; `buildCsvFiles` threads it.
- [ ] Vitest: filtered exportArrays; filtered save document contents
(subset .dvma round-trip contains exactly the chosen measurement +
its derived items and nothing else); all-ticked path byte-equivalent
to today's. `npm run check` green.
- [ ] Commit: `feat(webui): Choose sets… — subset Save/Export per measurement, all-by-default split-buttons`

### Task 6: Python subset parity

**Files:** Modify `pydvma/datastructure.py`, `pydvma/file.py`; tests
in `tests/test_datastructure.py` + `tests/test_file.py` (follow their
existing class layout).

- [ ] `DataSet.subset(sets)` — new method: `sets` is an int or
iterable of ints indexing `time_data_list`; returns a NEW DataSet
containing those TimeData items plus every derived item whose
`id_link` matches one of their `unique_id`s (ModalData included when
any linked TF's own `id_link` resolves into the subset — read the
id_link-list convention in the modal code first), lists in original
order, items SHARED (not copied — document that mutation affects
both, consistent with the rest of the API). Griffe-clean docstring
with the semantics spelled out.
- [ ] `file.py::save_data(..., sets=None)` — `None` = everything
(unchanged); otherwise `dataset = dataset.subset(sets)` before
writing.
- [ ] Tests: subset picks the right derived items; orphan derived
items excluded unless their source is chosen; ModalData inclusion
rule; `save_data(sets=[1])` file contains exactly measurement 1's
family; `subset` shares objects (mutation visible both sides).
- [ ] Full pytest + mkdocs strict. Commit:
`feat(datastructure): DataSet.subset + save_data(sets=…) — notebook parity for subset saving`

### Task 7: E2E + cross-language pin + docs + close-out

- [ ] **E2E** (`webui/e2e/derived-save.spec.ts`, BRIDGE_E2E, its own
port — claim the next free one in the engine-native register and use
`--session-dir`): capture (mock) → Calc FFT + TF → Save Dataset into
the page's download/fsaccess path (read how files.spec handles saves)
→ reload the app fresh → Load the saved file → FFT and TF views show
WITHOUT recomputing (assert lines attached before any calc click);
then a stale-chain case: load a fixture whose source was edited after
stamping (build the fixture bytes in-spec via page.evaluate or
check one in) → `stale-chain-badge` visible → click → view recomputes
→ badge gone. And a subset case: two captures → Choose sets… → save
only set 2 → reload → exactly one measurement present.
- [ ] **Cross-language pin:** extend `codec/crosscheck.test.ts` to
stamp a signature JS-side into the round-trip fixture, and
`tests/test_container.py`'s fixture test to verify that signature
Python-side with `_signature.source_signature` (and vice versa: a
Python-stamped file verified in a vitest via the checked-in fixture
pipeline — follow how the fixture flows between the suites today).
- [ ] **Docs:** `export.md` (split-buttons, Choose sets…, what Save
now contains), `index.md` + `migration.md` restore/`session.data`
notes updated (restored sessions and pulled data now INCLUDE saved
FFT/TF results once you have Saved; the journal itself still doesn't
auto-materialise), `examples/basic.md` (subset + signature notes),
CHANGELOG (Added: derived-data save + signatures + subset picker;
one honest note: sonograms/CSD not yet materialised). TODO.md:
strike the decided item's "decide deliberately" framing → point at
this plan/round; add the sono/CSD deferral note.
- [ ] **Suites:** full pytest, vitest, check, Playwright non-engine +
@engine + BRIDGE_E2E (all five bridge specs now), mkdocs strict.
`pydvma/analysis.py` changed → it ships in the engine wheel → `npm
run vendor:wheels` + byte-identity + `npm run build`, and re-run the
@engine suite after (the browser engine now stamps signatures too —
this is DESIRED: pyodide-computed TFs saved from Pages carry
signatures as well; note it in the round doc).
- [ ] **Round doc** `dev/2026-08-19-derived-data-save-round.md` (house
shape): what landed, the sono/CSD deferral, the signature reduction
rule if one was needed, deviations, suite numbers, and a
next-lab-visit checklist (save with TFs → load in notebook →
`session.data` has TfData; edit time data in Python → push → app
flags the stale chain; subset save of measurement 4). CLAUDE.md
focus updated.
- [ ] Commits per the natural grouping above.

---

## Self-review notes (plan time)
- Every agreed decision from TODO.md maps to a task (materialise→3,
  signature/staleness→1/2/4, replace-by-lineage→3, subset picker→5,
  Python parity→6, journal exclusion→3 step 3 comment).
- Known soft spots flagged inline as read-first: the analysis.py call
  sites' real parameter names (Task 1), ModalData id_link-list
  semantics (Tasks 5/6), files.spec save-path mechanics (Task 7), the
  possible large-array hash reduction (Task 1 — the one genuinely
  open implementation decision, with the decision procedure given).
- Cross-language consistency: signature bytes defined once (Task 1),
  twin pinned by shared vectors (Task 2) and the fixture pipeline
  (Task 7).
