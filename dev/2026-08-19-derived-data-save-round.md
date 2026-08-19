# Derived-data save — round writeup

**Date:** 2026-08-19 (Mac session). **Status:** landed, committed
locally (**NOT pushed**), full suite gate green. **No live verification
yet** — everything here has met the mock driver and the native engine on
this Mac, nothing has met real hardware or a real notebook round trip;
that is Tore's next step via the checklist at the end.

Plan: `dev/plans/2026-08-19-derived-data-save-plan.md` (Tasks 1–7; this
doc closes Task 7). Predecessor round (stages 3–4):
`dev/2026-08-18-session-journal-round.md` — this round sits directly on
top of it and answers the limitation that round left open ("restore
brings back DATA, not computed analysis views").

Commits `ee24ba0..561832f` on master (Tasks 1–7), plus this close-out's
docs commit and the final whole-round review's two (`554551b` + this
doc's amendment) — see "Final whole-round review" below.

> **Reading the plan against the tree:** several tasks deviated under
> review, one of them in the cross-language contract itself, and Task 5b
> did not exist when the plan was written (it replaced a deferral,
> `cfc7a6a`). The plan is the intent; this doc and `git log` are what
> exists.

## The idea in one paragraph

Tore's ask was "data with its processing": a `.dvma` that carries the
analysis you did, not only the samples you took. Saving now materialises
the computed FFT and TF views into real document items, each stamped
with the settings that produced it and a hash of the **source samples**
it was computed from. That hash is the whole trick — it lets a loaded
file distinguish a result that still belongs to the data beside it from
one whose source has since been edited, so a broken chain is **flagged**
(⚠ source changed, one click from a recompute) rather than silently
trusted or silently recomputed.

## What landed

**Task 1 — the signature** (`ee24ba0`, `5b627ac`, `2a23d07`).
`pydvma/_signature.py`: FNV-1a-64 over a defined byte stream, 16 hex
chars, no dependencies. `analysis.calculate_fft` /
`calculate_tf` / `calculate_tf_averaged` stamp `source_signature` +
`source_settings` (the call's ACTUAL knobs, JSON-safe scalars) via
`_stamp_source`; `container._OPTIONAL_META` carries both for
`FreqData`/`TfData`, so absence survives the round trip and an older file
makes no claim about its chain. Display state (cal factors, units, x(iω)
power) is deliberately NOT hashed: it does not change the samples.

**Task 2 — the twin** (`059681b`). `webui/src/lib/codec/signature.ts`:
the same contract in TypeScript (BigInt FNV), pinned by **eleven frozen
known-answer vectors** that appear literal-for-literal in both
`tests/test_signature.py` and `webui/tests/codec/signature.test.ts`.

**Task 3 — materialise on Save** (`4629bb8`, `52618cc`, `ed60479`).
`actions.materializeDerived()` builds a `FreqData` per computed FFT and a
`TfData` (coherence included) per computed TF, `id_link`ed to the
measurement, named as the set is named at save time, stamped. Called from
the Save handler only; autosave never materialises — but once
materialised, items are ordinary document items and ride later autosaves,
which is the intended behaviour. (Reaching the serve JOURNAL needed one
more thing, found in the final review below: the save handler posts the
live document itself, because materialisation deliberately emits no store
change.) **Replace-by-lineage** (a per-(set,
kind) map, seeded both by materialisation and by `loadDataset` pass 2)
keeps re-saves idempotent and adopts a loaded file's own items instead of
duplicating them. Four deliberate narrowings, all documented at the
function: FFT + TF only; only slices computed THIS SESSION; only sets
whose source is a real `TimeData`; not an ensemble TF (see deviations).

**Task 4 — the stale badge** (`5fdb6f1`). Load-time detection: pass 2
rehashes the source's current samples against each adopted item's stamped
signature and records mismatches in a kind-generic `actions.staleChains`
store. `TrayCard` shows **⚠ source changed**; clicking reruns exactly the
flagged calc(s), which clears the flag through `markComputed`. Wired
through both tray layouts.

**Task 5 — Choose sets…** (`44e8548`, `4d73167`). Save Dataset / Export
Matlab / Export CSV become split controls: the primary button is
unchanged (everything, no dialog), the ▾ opens `ChooseSetsPopover`. The
pick is per-invocation, all-ticked on every open, never persisted and
never read from view/solo/fade state. `subsetDataset(setIds?)` builds a
filtered document (a new items array over the same item references);
`exportArrays`/`exportMat`/`buildCsvFiles` thread the same pick.

**Task 5b — the sonogram prompt** (`cfc7a6a` plan amendment, `56a03b8`,
`e61aee7`). Tore's design, replacing the original "defer sonograms"
decision. The sono view is one channel's magnitude image while `SonoData`
wants the whole complex cube, so an honest item needs a save-time
recompute — real seconds and a much bigger file. So Save **asks**, and
only when a sonogram was actually computed this session on a set this
save will contain (a 3c6 session never sees it; autosave and the journal
never raise it). Three answers: **This channel** (default), **All
channels**, **Don't include** — the last declining the recompute, never
stripping a sonogram the document already holds. New engine op
`calc_sono_full` beside the unchanged `calc_sono`, sharing one
`_sono_data` so the STFT/CWT dispatch and the memory guards are written
once.

**Task 6 — Python parity** (`a433298`, `dd84f93`). `DataSet.subset(sets)`
returns a new `DataSet` holding the chosen `TimeData` items plus every
derived item whose `id_link` resolves into the pick (a scalar link
matches directly; a LIST link — `calculate_tf_averaged`,
`calculate_cross_spectra_averaged`, `calculate_bla` — matches on **ANY**
member) and any `ModalData` whose own link or browser-authored
`source_targets` lands in the lineage. Items are shared, not copied.
`file.save_data(..., sets=…)` and `DataSet.save_data(..., sets=…)` apply
it before writing.

**Task 7 — this close-out** (`561832f`, plus the docs/round commit).
`webui/e2e/derived-save.spec.ts` (BRIDGE_E2E, port 8768, its own
`--session-dir`) drives all four behaviours through a real
`pydvma-serve`; docs and CHANGELOG; this doc; trackers.

## The cost tables (measured, not estimated)

**The signature's reduction rule.** A naive per-byte FNV over a 30 s ×
4 ch × 51.2 kHz record (49 MB) takes **2.33 s** in CPython — far too slow
for a save click. The stream is therefore reduced: heads (`n_rows`,
`n_cols`, `fs` as float64-LE) then selected whole ROWS, cap 65536 hashed
*values*, `row_stride = ceil(n_rows / max(1, 65536 // n_cols))`, final
row appended unconditionally. Same record: **~25 ms Python, ~11 ms JS.**

**Including a sonogram.** Same 30 s × 51.2 kHz × 4 ch record:

| | file | CWT recompute |
| --- | --- | --- |
| save without the sonogram | 47.8 MB | — |
| save with all 4 channels | 138.7 MB | 20.54 s |
| save with "This channel" (after the fix) | — | **4.91 s** |

The 4× was a real bug found in review: `calc_sono_full` sliced the
requested columns out of the time payload *before* transforming instead
of transforming and `np.take`-ing after, so "This channel" on a 4-channel
record paid for four. Fixed, with one honest consequence pinned in tests:
the STFT batches over the channel axis, so a single-channel cube differs
from the all-channel display plane by ~1 ULP of the image peak (~2e-16
relative); the CWT stays bit-identical.

## Bugs found in review (fixed before landing)

Every task ran design-review → implement → review. The findings worth
remembering:

- **The signature hashed ONE CHANNEL on multi-channel records**
  (`5b627ac`) — and this was caught *before* the TypeScript twin froze
  the contract, which is the only reason it was cheap. The first cut
  strided over FLAT bytes, so within each channel the sampled flat
  indices were congruent to 0 mod `gcd(stride, n_cols)`: a 4 ch × 48 kHz
  × 30 s record (stride 88, gcd 4) hashed channel 0 only, and
  `clean_impulse(td, ch_impulse=1)` changed nothing hashed — a broken
  chain reading as intact, i.e. the feature silently not working. The
  stream now hashes whole ROWS, so every channel of a sampled time
  instant is covered and the blind spot is purely temporal (an edit
  confined to fewer than `row_stride` consecutive unsampled rows —
  documented, and pinned as a known limitation).
- **An ensemble TF would have carried single-source provenance**
  (`52618cc`). `calc_tf_averaged` derives one curve from every working
  set but hangs it on `working[0]`, so materialising it would stamp the
  first set's `id_link` and the first set's signature — an edit to any
  *other* member would leave the chain looking intact, exactly the
  failure the signature exists to catch. Deferred whole rather than
  half-stamped.
- **Removal orphaned derived items; undo duplicated them** (`ed60479`).
  `removeBlaRun` dropped only the source `TimeData`, leaving materialised
  items pointing at a source that no longer existed (a phantom orphan set
  on the next reload); undo then re-registered under a NEW selection id,
  so the next Save pushed a duplicate beside the restored item. Removal
  now takes the materialised items with it (stashed with their
  positions), undo splices them back and re-keys the lineage.
- **Adoption replaced `metaRaw` wholesale** (`ed60479`), amputating
  manifest keys this builder does not re-emit (`flag_modal_TF`,
  `iw_power_counter`, anything a newer writer adds) — contradicting the
  container passthrough contract the previous round had just established.
  Now merged, not replaced.
- **Bridge captures dropped the server's `unique_id`** (`ed60479`) —
  pre-existing, and this round's problem. The journal clears a pending
  capture only when a posted document provably contains its ids, so a
  bridge capture could NEVER be cleared: reopening restored the document
  AND re-appended the capture beside its own copy. The session-journal
  e2e was **masking** it (`tray-card-0` is visible whether one card or
  two came back), so both restore tests now assert the SET COUNT.
- **The subset picker carried its ticks between targets** (`4d73167`).
  Hopping Save ▾ → untick → Matlab ▾ without closing left `pick` truthy
  throughout, so the `{#if}` reused the instance — contradicting the
  popover's own all-ticked-per-open guarantee. Fixed with `{#key pick}`.
  No vitest can pin it without a component harness, so the assertion
  lives in this round's e2e.
- **The sono include cost 4× on a single channel**, and the cube had no
  memory preflight (`e61aee7`). `calc_sono_full` now predicts
  `(n_freq, n_frames)` from the parameters alone — reading
  `max_time_columns` off `calculate_cwt`'s own signature rather than
  duplicating it — and refuses over-ceiling requests before any
  transform, checked against the WHOLE cube because marshalling peaks at
  ~3× its size. It is the first shipped op whose result is user-sized, so
  `engine_host`'s "nothing returns >2 GiB" decision comment was updated.
- **Escape did nothing on the sono dialog** (`e61aee7`): the handler sat
  on the overlay element, which never has focus when the dialog is raised
  from a header button. Moved to `<svelte:window>` (as
  `ChooseSetsPopover` already did) with an explicit focus on the default
  button.

Two traps the e2e itself shook out (`561832f`), both recorded in the
spec because they will bite the next spec too: the **mock capture is MONO
by default** (a TF needs `channel count` = 2 — the failure reads as "no
plot line" rather than "no response channel"), and **`sono-canvas` mounts
with the view, not with the result** — waiting on its visibility raced
the calc and left nothing for Save to offer, so the wait reads the canvas
backing store instead.

### Final whole-round review

Reviewing the round as a whole — after every task had passed its own
review — found three more, all of them at the seam between the new
document items and the machinery from the PREVIOUS round (the journal,
`Session.push`), which is exactly where a per-task review does not look.

- **CRITICAL: materialised items never reached the journal.**
  `materializeDerived` emits no store change (deliberately — a re-emit
  would schedule a debounced autosave that fires just after the explicit
  Save cleared the pending one), and the journal is fed ONLY by the
  autosave subscription. So the server kept the pre-Save session:
  `session.data` after a Save had no TF, a tab closed after a Save
  restored without one, and a notebook push replaced the document so the
  materialised item vanished — with no stale badge, because it was gone
  rather than stale. Fixed by posting from the save flow DIRECTLY
  (`journalPost` in `App.svelte`'s `onsave`, right after the file write),
  which keeps the no-emit choice and its race protection intact. The
  journal always gets the FULL live document, so a subset save pays one
  extra serialise. Pinned in the e2e: test 1 now TAKES the journal
  restore offer and asserts both views draw — with the post removed it
  fails on exactly that assertion (verified).
- **IMPORTANT: a notebook pull → push duplicated derived items.** They
  carried no `unique_id`, and `_merge_dataset` appends anything without
  one — so pushing back an UNMODIFIED pull doubled every spectrum, every
  time. Fixed on both sides: `FreqData`/`TfData`/`CrossSpecData`/
  `SonoData` mint one at construction like `TimeData`, the app mints one
  per materialised item and preserves it across re-saves and reloads, and
  `container` round-trips it as OPTIONAL meta so older files load
  unchanged. Caveat kept honest rather than papered over: derived items
  inside a PRE-round file have no id and still append on a repeated push
  — a composite-key fallback was considered and rejected; recompute or
  re-Save to give them ids.
- **IMPORTANT: the 192 MiB journal guard was console-only.** Fine while
  only a pathological session could reach it; including one all-channel
  sonogram on Save (139 MB on the bench case) makes two measurements
  enough. The whole server-side surface then went stale in silence.
  `setJournalOverflowNotice` now raises a one-shot toast, fired from both
  the autosave sink and the new direct post.

`container.manifest_ids` picked up a consequence worth recording: it now
returns derived ids too. The journal only ever asks whether a capture's
ids are a SUBSET of a document's, and a capture blob still holds just its
`TimeData`, so a larger document set cannot make that test wrongly true —
docstring and test updated to say so rather than to keep claiming only
captures carry ids.

A re-verification pass then closed the same hole one kind wider:

- **`ModalData` (and `MetaData`) still duplicated on every push.** The
  identity fix above covered the four derived kinds and stopped there,
  which left the one item Tore actually pushes back — a modal fit —
  appending a fresh copy on every `session.push`. Both kinds now mint a
  `unique_id` at construction, both ride `_OPTIONAL_META` (so pre-round
  files load unchanged), and `upsertModalItem` mints/preserves one. That
  last one carried the SAME defect `upsertDerivedItem` had already been
  fixed for — it replaced `meta`/`metaRaw` WHOLESALE, so an adopted
  python-written fit lost the id python minted *and* every foreign
  manifest key, on the first app-side re-fit. Merged now, not replaced.
  Pinned by three vitest cases (all three fail against the wholesale
  version) and by the no-op-push fixture, which now carries a real
  `modal_fit_all_channels` result and a `MetaData` — with the
  ModalData mint disabled its `modal_data_list` count goes 1 → 2.
  This is what makes the broad claims in `migration.md` and the
  CHANGELOG (*"every item carries a `unique_id`"*, *"pushing an
  unmodified pull is a no-op"*) true as written.

## Deviations from the plan (honest list)

1. **The reduction rule is ROW-STRIDED, not flat-byte-strided.** The
   plan sketched a flat byte stride; review found it channel-aliasing
   (above) and the contract was rewritten before the twin existed. The
   authority is `pydvma/_signature.py`'s module docstring; the frozen
   vector table lives in `tests/test_signature.py` and is mirrored
   literal-for-literal in `webui/tests/codec/signature.test.ts`, with an
   independent JS implementation written from the contract text checked
   in as `dev/prototypes/signature_prototype.mjs` so the
   "verified against JavaScript" claim is falsifiable — run it, the table
   must match row for row.
2. **Provenance dialects differ by writer.** App-materialised items carry
   the webui's camelCase setting names (`nFft`, `voicesPerOctave`,
   `fMin`); `pydvma.analysis`'s own stamps are snake_case (`nperseg`,
   `voices_per_octave`). `calc` — and, for sonograms, `method` — are
   spelled the same by both, so a reader keys off those and accepts
   either. One consistent dialect per writer was judged better than a
   split spelling inside one document; normalising them is a follow-up.
   Documented in `docs/web-logger/dvma-format.md` and at the write site.
3. **Python's `subset` never live-returns.** The webui's `subsetDataset`
   short-circuits an all-sets pick to the live document, so "everything"
   keeps meaning everything including unattributable orphans.
   `DataSet.subset` always builds a fresh DataSet, so an item nothing can
   attribute stays excluded even from a full-index pick. Deliberate
   (Python has no live document to preserve) and documented.
4. **`source_targets[].id_link` is a PLAIN STRING in a real round trip**
   (`dd84f93`), not the `{'__uuid__': …}` tagged form: the browser never
   applies pydvma's JSON tag scheme and `container.py` stashes unknown
   keys verbatim/undecoded. The subset test uses the shape that actually
   occurs, verified against `tests/test_container.py`'s passthrough
   fixture and `actions.ts`'s `upsertModalItem` before being written.
5. **Task 5b did not exist at plan time.** The plan deferred sonograms
   entirely; Tore's design replaced that with the include-prompt
   mid-round (`cfc7a6a` amends the plan in place).
6. **The cross-language pin took a different route.** The plan wanted the
   signature threaded through `codec/crosscheck.test.ts` and
   `tests/test_container.py`'s fixture pipeline. It is instead pinned by
   the eleven shared known-answer vectors (Tasks 1–2) plus, in this
   round's e2e, a **rehash of a real browser-written file**: the python
   probe recomputes `_signature.source_signature` from the stored samples
   and it must equal the digits the browser stamped. Stronger than the
   fixture route on the thing that matters (a real file, both languages)
   and it costs no new fixture plumbing.
7. **Still deferred:** PSD/cross-spectra materialisation, ensemble
   ("across sets") TF materialisation. Both are in TODO.md with their
   reasons.

## Suites at close (this Mac, 2026-08-19)

- `python -m pytest tests/ -q --ignore=tests/test_acquisition_hardware.py`:
  **1117 passed, 6 skipped** (1033/6 at the previous
  round's close; +84 this round, the last 6 from the final review)
- `python -m mkdocs build --strict`: **clean** (exit 0)
- `npm run check`: **188 files, 0 errors, 0 warnings**
- `npx vitest run`: **1145 passed, 1 skipped** (1069/1 before; the last 12 from the final review
  and its re-verification)
- `npx playwright test --grep-invert @engine`: **69 passed, 23 skipped** (19 skipped
  before — the four new BRIDGE_E2E tests are gated off here)
- `npx playwright test --grep @engine --workers=1`: **19 passed**
- `BRIDGE_E2E=1 npx playwright test e2e/bridge.spec.ts e2e/bla.spec.ts
  e2e/engine-native.spec.ts e2e/session-journal.spec.ts
  e2e/derived-save.spec.ts --workers=1`: **26 passed** (22 before; five real spawned
  `pydvma-serve` processes across ports 8763–8768). The new spec was
  additionally run twice on its own, green both times, and re-run green
  after the final-review fixes.
- **Engine wheel** (`npm run vendor:wheels`, still
  `pydvma-2.3.0-py3-none-any.whl`, matching `ENGINE_WHEELS`): rebuilt
  **five times** this round — twice inside Task 5b (`56a03b8`,
  `e61aee7`, both for `pydvma/engine.py`), once at close-out (Task 6
  changed `pydvma/datastructure.py` and `pydvma/file.py` after the last
  rebuild, and both ship in the wheel), and twice more as the final
  review and its re-verification touched `datastructure.py` +
  `container.py`. Final state verified: all **24** `pydvma/*.py` modules
  byte-identical to the tree, `dist/pypi/` carrying that same wheel, and
  @engine re-run 19/19 after it.

## Next-lab-visit checklist (live verification — none of this is done)

This round's items. The previous round's checklist
(`dev/2026-08-18-session-journal-round.md`) is still outstanding and
should be run in the same visit — the two arcs share the serve stack.

- [ ] **Save with a computed TF → reload → the views seed.** A real 2i2
      capture, Calc TF, Save Dataset, reopen the file: the TF draws with
      no Calc pressed. This is the headline claim and has only met the
      mock driver.
- [ ] **Edit time data in a notebook → push → the app flags it.**
      `session.data`, scale or filter a capture, `session.push`, and
      confirm the measurement comes back with **⚠ source changed** and
      that clicking it rederives.
- [ ] **Pull → push an UNMODIFIED session** after a Save and confirm
      nothing doubles (the derived-`unique_id` fix, live rather than
      against the mock).
- [ ] **Save with an all-channel sonogram on a long record** and watch
      for the over-size journal toast — the 192 MiB guard is now
      reachable, and its message has never been seen outside a unit test.
- [ ] **Subset save of one measurement** out of a multi-capture session;
      reopen and confirm exactly that measurement plus its own results.
- [ ] **Sonogram include on a real capture**: compute a sonogram, Save,
      choose **This channel**, note how long the save takes and how big
      the file is, reopen and confirm the sono view seeds. Then Save
      again and confirm it does NOT ask.
- [ ] **The 3c6 envelope shows no prompt**: 3 kHz / 30 s / 2 ch with no
      sonogram computed — Save must go straight through.
- [ ] **Windows PC:** the five BRIDGE_E2E specs together (first Windows
      run of `derived-save.spec.ts`). Rebuild the gitignored artifacts
      first (`npm run vendor:wheels` + `npm run build`) — that machine
      has been caught with a stale wheel before.
