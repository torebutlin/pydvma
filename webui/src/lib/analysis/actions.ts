/**
 * Analysis orchestration (Task 12). The bridge between the loaded
 * dataset, the selection/view stores, and the pyodide worker: load a
 * dataset → populate the selection tray, then run FFT / PSD / TF / sono
 * / clean-impulse ops by marshalling each source TimeData set to the
 * worker and decoding the result into per-set `SetArrays` for
 * `buildPlotModel`.
 *
 * MATHS NEVER RUNS HERE — every numeric op is a worker call into glue.py
 * (spec §11); this module only reshapes flat JS buffers in and
 * `decodeArray`s the marshalled result out. Every action awaits the
 * engine (`enqueue` / `whenReady`) and, on REJECTION (boot failure),
 * records the failure in `computeErrors` rather than hanging (engine
 * store A8b: enqueue rejects, never hangs).
 *
 * Errors are PER-KIND (Round-3 item 2): `computeErrors` is a keyed store
 * `{ fft, psd, tf, sono, clean, fit }` so each card banner shows only its
 * own kind's error, App's under-plot banner shows the ACTIVE view's kind, and
 * starting a calc clears ONLY that kind. A failed TF therefore can no
 * longer poison the Sonogram card (the old single `computeError` + owner
 * flag left one kind's error stuck on every card until a same-kind run).
 *
 * Modal fit (Task A1): `calcFit` runs the STATELESS `calc_fit` engine op and
 * pushes the decoded result into the injected `modal` store (which owns the
 * accumulated modal matrix and re-sends it). `exportMat` / `exportArrays` are
 * shared-spine accessors the Export card (a sibling agent) consumes.
 *
 * Concurrency: live slider re-issues are debounced (150 ms) and each
 * action kind carries a PER-KIND stale seq (keyed 'fft'/'psd'/'tf'/
 * 'sono') so an out-of-order response of that SAME kind is dropped —
 * but a newer call of one kind NEVER cross-drops an in-flight result of
 * a DIFFERENT kind (that global-counter bug would let a debounced
 * sonogram slider silently blank an in-flight TF batch, and vice
 * versa). `busy` is REFERENCE-COUNTED so it stays true until the last
 * concurrent action settles.
 */
import { writable, derived as svelteDerived, get } from 'svelte/store';
import type { DvmaDataset, DvmaItem, DvmaItemUi } from '../model/dataset';
import { itemChannels, setItemMeta } from '../model/dataset';
import type { NpyArray } from '../codec/npy';
import type { EngineStore } from '../stores/engine';
import type { Selection } from '../stores/selection';
import type { AnalysisSettings, AnalysisTarget } from '../stores/analysisSettings';
import { defaults, type PerSetSettings } from '../stores/analysisSettings';
import { decodeArray, type DecodedArray, type MarshalledArray, type SetArrays } from '../plot/model';
import type { ViewId } from '../stores/viewstate';
import { PHASE_DEV_WARN_DEG } from '../stores/modal';
import type { ModalStore, ModalState, ReconArrays, ReconMode } from '../stores/modal';
import type {
  BandLadder, DampingBand, DampingBandsResult, DampingModeFit, DampingPeaksResult,
} from '../stores/damping';
import type { Toasts } from '../stores/toast';
import { normalizeFactors, normalizeUnits } from '../model/calibration';
import { calibrationController } from '../stores/calibrationController';
import { tfColumn } from '../plot/tfChannels';
import { fromNFrames, fromNFft } from './resolution';

/** Clamp an x(iω) display power to an integer in [-2, +2] (0 = identity). */
function normalizeIwPower(v: unknown): number {
  const n = Math.round(Number(v));
  return Number.isFinite(n) ? Math.max(-2, Math.min(2, n)) : 0;
}

/**
 * SOURCE channel that TF output column `col` came from — the inverse of
 * {@link tfColumn}. A measured TF dropped the input channel `chIn`, so
 * `col` maps back to `col < chIn ? col : col + 1`; an ORPHAN TF (`chIn`
 * null) is identity (columns are the channels). Used by Best Match to fold a
 * per-column scale factor into the right source channel's calibration.
 */
function sourceOfColumn(col: number, chIn: number | null, nChannels: number): number {
  void nChannels;
  if (chIn === null) return col;
  return col < chIn ? col : col + 1;
}

/** Compute-action kind, used as the per-kind stale-guard + error key. */
type Kind = 'fft' | 'psd' | 'tf' | 'sono' | 'clean' | 'fit';

/** A fresh, all-clear per-kind error record. */
const emptyErrors = (): Record<Kind, string> =>
  ({ fft: '', psd: '', tf: '', sono: '', clean: '', fit: '' });

/** Measurement type for the modal fit (Qt's "TF type" combo). */
export type MeasurementType = 'acc' | 'vel' | 'dsp';

/** A per-set export accessor slice (raw decoded columns for the CSV builder). */
export interface ExportSetArrays {
  setId: number;
  axis: Float64Array;
  columns: Float64Array[] | { re: Float64Array; im: Float64Array }[];
}

/** A worker array crosses either as a plain object or a toJs Map. */
function mval(v: unknown, k: string): unknown {
  return v instanceof Map ? v.get(k) : (v as Record<string, unknown>)[k];
}

/** Coerce a worker return value (object or Map) into a MarshalledArray. */
function asMarshalled(v: unknown): MarshalledArray {
  return {
    shape: (mval(v, 'shape') as number[]) ?? [],
    data: mval(v, 'data') as Float64Array,
    complex: !!mval(v, 'complex'),
  };
}

/** A source set: its TimeData item, stable selection id, and cached time arrays. */
interface WorkingSet {
  setId: number;
  time: DvmaItem;                 // the source TimeData
  fs: number;
  durationS: number;
  nChannels: number;
}

/** Per-set derived arrays, keyed by selection setId (fed to buildPlotModel). */
type DerivedMap = Record<number, SetArrays>;

/** fs from a TimeData item: prefer settings.fs, else infer from the axis. */
function sampleRate(item: DvmaItem): number {
  const fromSettings = item.settings?.fs;
  if (typeof fromSettings === 'number' && fromSettings > 0) return fromSettings;
  const axis = item.arrays.time_axis?.data;
  if (axis && axis.length > 1) return 1 / (axis[1] - axis[0]);
  return 1;
}

/** Flat row-major time_data buffer + its channel column count for the worker. */
function timePayload(item: DvmaItem): { axis: Float64Array; data: Float64Array; nCh: number } {
  const axis = Float64Array.from(item.arrays.time_axis.data);
  const data = Float64Array.from(item.arrays.time_data.data);
  return { axis, data, nCh: itemChannels(item) };
}

/**
 * Whether a working set carries the time-domain arrays a sonogram / damping
 * fit needs. Round-5's orphan-TF sets (a TF-only `.mat`/`.dvma` load) enter
 * `working` with a DERIVED item as their source (TfData/FreqData/
 * CrossSpecData) and therefore have NO `time_axis`/`time_data`. A sonogram or
 * damping fit on such a set must be REFUSED with a clear message (round-6 item
 * 2) rather than dereferencing the missing array — which threw an opaque
 * "Cannot read properties of undefined (reading 'data')" and left the heat
 * canvas white/silent. `workingSets()` exposes this so the Sono card can list
 * only time-bearing sets as targets (round-6 item 3).
 */
function hasTimeData(item: DvmaItem): boolean {
  const a = item.arrays;
  return !!(a && a.time_axis && a.time_axis.data && a.time_data && a.time_data.data);
}

/** Decode a loaded-file `NpyArray` into the plot model's `DecodedArray`. */
function decodeNpy(a: NpyArray): DecodedArray {
  return decodeArray({ shape: a.shape, data: a.data as Float64Array, complex: a.isComplex });
}

/**
 * Derived-view slice(s) a loaded non-TimeData item contributes, so its view
 * shows on load WITHOUT a recompute (round-4 bug 3: a legacy `.npy` that
 * already carried a TF loaded the time series but never the TF). Returns a
 * partial `SetArrays` to merge onto the item's source set, or `null` for
 * kinds we don't restore. `srcChannels` is the source set's channel count.
 *
 * Restored: `FreqData → freq` (Frequency/FFT view); `TfData → tf` (TF view,
 * with the out/in remap fields); `CrossSpecData → csd` (coherence). NOT
 * restored as a slice: stored `SonoData` is a 3-D complex `(Nf, Nt, Nc)`
 * cube whereas the webui's sono slice is a 2-D per-channel magnitude image,
 * and PSD is derivable from the stored `Pxy` — both are left to an on-demand
 * Calc (the FFT still shows). `ModalData`/`MetaData` carry no plottable slice.
 *
 * chIn CONVENTION (two cases):
 *   - LINKED TF (a source `TimeData` IS in the file): its input channel was
 *     dropped when the TF was computed, but pydvma's `TfData` carries NO
 *     input-channel field, so it is UNKNOWABLE from the file. We restore
 *     `chIn = 0` — pydvma's default and overwhelmingly common case (Qt's
 *     `calculate_tf_set(ch_in=0)`); the out/in remap then drops source
 *     channel 0 and maps the survivors to the TF columns.
 *   - ORPHAN TF (`orphan = true`; no source `TimeData`, e.g. a JW-logger
 *     `.mat` whose `yspec` is a bare TF matrix): there is NO measured input
 *     to drop, so the columns ARE the lines. We restore `chIn = null` and
 *     `nChannels = Nout`, and the model maps each channel to its own column
 *     (identity) — 11 columns ⇒ 11 distinct lines/chips (round-5 item 3).
 */
function sliceForLoadedItem(
  item: DvmaItem, srcChannels: number, orphan = false,
): Partial<SetArrays> | null {
  const A = item.arrays;
  switch (item.kind) {
    case 'FreqData':
      if (!A.freq_axis || !A.freq_data) return null;
      return { freq: { axis: Float64Array.from(A.freq_axis.data), data: decodeNpy(A.freq_data) } };
    case 'TfData':
      if (!A.freq_axis || !A.tf_data) return null;
      return {
        tf: {
          axis: Float64Array.from(A.freq_axis.data),
          data: decodeNpy(A.tf_data),
          coherence: A.tf_coherence ? decodeNpy(A.tf_coherence) : undefined,
          chIn: orphan ? null : 0, nChannels: srcChannels,
        },
      };
    case 'CrossSpecData':
      if (!A.freq_axis || !A.Cxy) return null;
      return { csd: { axis: Float64Array.from(A.freq_axis.data), data: decodeNpy(A.Cxy) } };
    default:
      return null;
  }
}

/**
 * Source-channel count for a set created for an ORPHAN derived item — one
 * whose source `TimeData` is absent from the file (e.g. a TF-only export).
 * An orphan `TfData` restores as `Nout` source channels — its columns ARE
 * the lines (chIn = null convention, round-5 item 3), so an 11-column ruler-
 * grid TF yields 11 channels/chips/lines, NOT 12. `FreqData` uses its own
 * column count; `CrossSpecData` its matrix dimension; anything else → 1.
 */
function orphanChannels(item: DvmaItem): number {
  const A = item.arrays;
  if (item.kind === 'TfData' && A.tf_data) return A.tf_data.shape[1] ?? 1;
  if (item.kind === 'FreqData' && A.freq_data) return A.freq_data.shape[1] ?? 1;
  if (item.kind === 'CrossSpecData' && A.Cxy) return A.Cxy.shape[0] ?? 1;
  return 1;
}

/**
 * First populated view in the priority order time → frequency → tf → sono
 * (round-4 bug 4). `frequency` counts as populated when ANY of FFT / PSD /
 * coherence is present. Returns the ordered list of populated views so the
 * caller can both pick a jump target (`[0]`) and test whether the current
 * view is among them. Empty when the dataset has nothing plottable.
 */
function populatedViews(seed: DerivedMap): ViewId[] {
  const sets = Object.values(seed);
  const any = (pred: (s: SetArrays) => boolean) => sets.some(pred);
  const out: ViewId[] = [];
  if (any((s) => !!s.time)) out.push('time');
  if (any((s) => !!s.freq || !!s.psd || !!s.csd)) out.push('frequency');
  if (any((s) => !!s.tf)) out.push('tf');
  if (any((s) => !!s.sono)) out.push('sono');
  return out;
}

/**
 * Create the analysis actions bound to an engine + selection store, plus
 * the per-set `analysisSettings` store. Exposes the working `dataset`
 * store, the decoded `derived` store the plot model consumes, and a
 * per-kind `computeErrors` store the cards show on engine failure. Actions
 * are thin: marshal → enqueue → decode.
 *
 * PER-SET TARGETING (Task R1): `calcFft` / `calcPsd` / `calcTf` take a
 * `target: 'all' | setId` and read EACH targeted set's settings from
 * `settings` (window / mode / nFrames / chIn / averaging), so different
 * sets can be processed with different settings. `target === 'all'` runs
 * every working set; a setId runs just that one. `settings` is optional
 * so the actions stay unit-testable in isolation; when omitted the calc
 * functions fall back to per-set `defaults()`.
 */
export function createActions(engine: EngineStore, selection: Selection, settings?: AnalysisSettings, modal?: ModalStore, toasts?: Toasts) {
  const dataset = writable<DvmaDataset | null>(null);
  const derived = writable<DerivedMap>({});
  /**
   * Per-kind compute errors (Round-3 item 2): one slot per action kind so a
   * card banner shows only its own kind's failure and one kind's failure
   * never surfaces on another card. `''` means "no error for this kind".
   */
  const computeErrors = writable<Record<Kind, string>>(emptyErrors());
  const busy = writable<boolean>(false);

  /** Set/clear one kind's error (no-op emit when unchanged). */
  const setError = (kind: Kind, msg: string) =>
    computeErrors.update((e) => (e[kind] === msg ? e : { ...e, [kind]: msg }));

  /** Source sets in load order (one per TimeData item), with cached meta. */
  let working: WorkingSet[] = [];

  /** The working sets a target names: one set, or all of them. */
  function targeted(target: AnalysisTarget): WorkingSet[] {
    if (target === 'all') return working;
    const ws = working.find((w) => w.setId === target);
    return ws ? [ws] : [];
  }

  /** Display name of a set (for user-facing messages), from the selection. */
  function nameOf(setId: number): string {
    return get(selection.sets).find((s) => s.id === setId)?.name ?? 'set';
  }

  /**
   * Whether `target` already has a computed result for `view` — the gate
   * for the analysis cards' LIVE recompute (round-2 feedback). A setting
   * change recomputes only once a first result exists, so a stray tweak
   * before the first explicit Calc never boots the engine (the Calc button
   * stays the first-compute trigger). `target === 'all'` is true when ANY
   * working set has the view; a setId checks just that set.
   */
  function hasComputed(
    target: AnalysisTarget,
    view: 'time' | 'freq' | 'psd' | 'csd' | 'tf' | 'sono',
  ): boolean {
    const d = get(derived);
    const ids = target === 'all' ? working.map((w) => w.setId) : [target];
    return ids.some((id) => d[id]?.[view] !== undefined);
  }

  /** Per-set settings for `view`, from the store or per-set defaults. */
  function freqSettings(setId: number) {
    return settings?.get(setId, 'freq') ?? { window: 'hann', mode: 'fft' as const, nFrames: 10, csdX: 0, csdY: 1 };
  }
  function tfSettings(setId: number) {
    return settings?.get(setId, 'tf') ?? { chIn: 0, window: 'hann', averaging: 'within' as const, nFrames: 10 };
  }
  function sonoSettings(setId: number) {
    return settings?.get(setId, 'sono')
      ?? { nFft: 512, dynRangeDb: 60, method: 'stft' as const, voicesPerOctave: 16, w0: 6, fMin: null, fMax: null };
  }

  /**
   * Per-kind stale-guard counters. `bump(kind)` returns the token an
   * action captures BEFORE its worker call; `stale(kind, token)` is true
   * once a NEWER call of that SAME kind has bumped. Keying by kind is the
   * fix for the cross-kind clobber bug: a debounced sonogram slider must
   * not drop an in-flight TF result, and vice versa.
   */
  const seqs: Record<Kind, number> = { fft: 0, psd: 0, tf: 0, sono: 0, clean: 0, fit: 0 };
  const bump = (k: Kind): number => (seqs[k] = seqs[k] + 1);
  const stale = (k: Kind, token: number): boolean => token !== seqs[k];

  /**
   * Reference count of in-flight actions. `busy` reflects `busyN > 0`, so
   * two concurrent actions keep it true until BOTH settle — the first to
   * finish no longer re-enables the Calc buttons while the other runs.
   */
  let busyN = 0;

  function setDerived(setId: number, patch: Partial<SetArrays>) {
    derived.update(m => ({ ...m, [setId]: { ...m[setId], ...patch, setId } }));
  }

  /**
   * Run `fn`, routing an engine rejection to THIS kind's slot in
   * `computeErrors` (never hangs). Errors are per-kind, so a concurrent
   * action of a DIFFERENT kind never touches this kind's error: entry
   * clears only this kind, success clears only this kind, failure records
   * only this kind. `busy` is reference-counted so it stays true until the
   * last action settles.
   */
  async function guarded(kind: Kind, fn: () => Promise<void>): Promise<void> {
    setError(kind, '');            // clear only THIS kind's prior error
    busyN += 1;
    busy.set(true);
    try {
      engine.boot();               // idempotent; lazily boots on first compute
      await fn();
      setError(kind, '');          // our run succeeded — clear this kind
    } catch (e) {
      setError(kind, e instanceof Error ? e.message : String(e));
    } finally {
      busyN -= 1;
      busy.set(busyN > 0);
    }
  }

  /**
   * Load a dataset: reset stores, register every TimeData item with the
   * selection tray (name / channel count / duration / timestamp from
   * item meta), and seed the derived map with the time arrays so the
   * time view plots immediately (no compute needed).
   *
   * Plan 2 persistence: after seeding, restore persisted UI state from
   * each item's `ui` field — custom channel labels flow to the selection
   * store, per-set analysis settings flow to the analysisSettings store.
   * Missing `ui` (older files) leaves both at their defaults.
   */
  function loadDataset(ds: DvmaDataset): ViewId[] {
    dataset.set(ds);
    derived.set({});
    computeErrors.set(emptyErrors());   // fresh dataset clears every kind's error
    modal?.reset();                     // drop any prior dataset's modal fit
    cleanCache.clear();                 // raw/cleaned stashes belong to the old sets
    cleanedSets.set({});
    working = [];
    // Selection store has no reset; it is created fresh per app load. We
    // simply addSet for each item in this dataset.
    const seed: DerivedMap = {};
    // Map a source TimeData's `unique_id` → its setId so DERIVED items
    // (FreqData/TfData/CrossSpecData, linked by `id_link`) attach to the
    // right set (round-4 bug 3).
    const linkToSet = new Map<string, number>();

    // ---- Pass 1: TimeData items → selection sets + seeded time slice ----
    ds.items.forEach(item => {
      if (item.kind !== 'TimeData') return;
      const nCh = itemChannels(item);
      const axis = item.arrays.time_axis?.data;
      const durationS = axis && axis.length ? axis[axis.length - 1] - axis[0] : 0;
      const name = (item.meta.test_name as string) || 'set';
      const timestamp = (item.meta.timestring as string) || '';
      const setId = selection.addSet({ name, nChannels: nCh, durationS, timestamp });
      working.push({ setId, time: item, fs: sampleRate(item), durationS, nChannels: nCh });
      const uid = item.meta.unique_id;
      if (typeof uid === 'string') linkToSet.set(uid, setId);
      seed[setId] = {
        setId,
        time: {
          axis: Float64Array.from(item.arrays.time_axis.data),
          data: decodeArray({
            shape: item.arrays.time_data.shape,
            data: item.arrays.time_data.data as Float64Array,
            complex: item.arrays.time_data.isComplex,
          }),
        },
        // Thread stored per-channel calibration into the display seam so plots
        // read in engineering units immediately on load (Task A2). Absent /
        // all-ones ⇒ identity — the plot model treats it as no-op.
        calFactors: normalizeFactors(item.meta.channel_cal_factors, nCh),
        // Per-channel engineering units for axis labels (round-4): 'V'/absent
        // reads as unlabelled, so uncalibrated sets keep the plain 'Amplitude'.
        units: normalizeUnits(item.meta.units, nCh),
        // x(iω) display power (round-6 Qt-parity Scaling tool), persisted in ui.
        iwPower: normalizeIwPower(item.ui?.iw_power),
      };

      // Restore persisted UI state (Plan 2 persistence).
      const ui = item.ui;
      if (ui) {
        // Channel labels — sparse map keyed by stringified channel index.
        if (ui.channel_labels) {
          for (const [chStr, label] of Object.entries(ui.channel_labels)) {
            const ch = Number(chStr);
            if (Number.isFinite(ch) && ch >= 0 && ch < nCh && typeof label === 'string') {
              selection.renameChannel(setId, ch, label);
            }
          }
        }
        // Per-set analysis settings — merge saved partials over defaults.
        if (ui.analysis && settings) {
          if (ui.analysis.freq) settings.patch(setId, 'freq', ui.analysis.freq);
          if (ui.analysis.tf) settings.patch(setId, 'tf', ui.analysis.tf);
          if (ui.analysis.sono) settings.patch(setId, 'sono', ui.analysis.sono);
        }
      }
    });

    // ---- Pass 2: DERIVED items (Freq/Tf/CrossSpec) → seeded view slices ----
    // A file that carries a TF/FFT/coherence should show those views on load,
    // not just the time series (round-4 bug 3). Each derived item links to its
    // source TimeData via `id_link`; an ORPHAN one (source absent, e.g. a
    // TF-only export) gets its OWN display set so its view still shows.
    ds.items.forEach(item => {
      if (item.kind === 'TimeData') return;
      const link = item.meta.id_link;
      const linkedSet = typeof link === 'string' ? linkToSet.get(link) : undefined;

      if (linkedSet !== undefined) {
        // Source TimeData present: seed the view slice onto its set.
        const srcChannels = working.find((w) => w.setId === linkedSet)!.nChannels;
        const slice = sliceForLoadedItem(item, srcChannels);
        if (slice) seed[linkedSet] = { ...seed[linkedSet], ...slice, setId: linkedSet };
        return;
      }

      // Orphan (source TimeData absent). Only worth a standalone display set
      // if the item yields a plottable slice — an orphan SonoData / ModalData
      // has nothing to show, so it is skipped rather than left as an empty set.
      // `orphan = true` restores an orphan TF with chIn = null (columns are
      // the lines) instead of the linked chIn = 0 convention (round-5 item 3).
      const nCh = orphanChannels(item);
      const slice = sliceForLoadedItem(item, nCh, true);
      if (!slice) return;
      const name = (item.meta.test_name as string) || item.kind;
      const timestamp = (item.meta.timestring as string) || '';
      const newId = selection.addSet({ name, nChannels: nCh, durationS: 0, timestamp });
      // Kept in `working` (with the derived item as its source) so the set is
      // targetable — a loaded TF is fittable; a recompute would fail through
      // the normal guarded path (no time series), not crash.
      working.push({ setId: newId, time: item, fs: sampleRate(item), durationS: 0, nChannels: nCh });
      if (typeof link === 'string') linkToSet.set(link, newId);
      seed[newId] = {
        setId: newId,
        calFactors: normalizeFactors(item.meta.channel_cal_factors, nCh),
        units: normalizeUnits(item.meta.units, nCh),
        iwPower: normalizeIwPower(item.ui?.iw_power),
        ...slice,
      };
    });

    derived.set(seed);

    // ---- Pass 3: ModalData → restore the modal store + fit tray card(s) ----
    // (round-5 item 13; item 7 multi-set). A saved `.dvma` may carry the fitted
    // modal model as a `ModalData` item. Seed the modal store from `M` (the mode
    // chip shows immediately), adopt the item for in-place persistence, and —
    // when EVERY spanned set's TF is present (typical: the TFs are saved
    // alongside) — recompute the reconstruction so the pseudo-set(s)' recon lines
    // appear. Otherwise the recon is DEFERRED until the TFs are computed (see
    // `maybeRestoreModalRecon`). A shared-pole model spanning several sets is
    // restored from the `source_targets` mapping (each set by its own id_link);
    // a legacy single-set save (no `source_targets`) uses the single id_link.
    if (modal) {
      const modalEntry = ds.items.find((it) => it.kind === 'ModalData' && !!it.arrays.M);
      if (modalEntry) {
        const Marr = modalEntry.arrays.M;
        const matrix: MarshalledArray = {
          shape: Marr.shape.slice(),
          data: Marr.data instanceof Float64Array ? Marr.data : Float64Array.from(Marr.data as ArrayLike<number>),
          complex: false,
        };
        const mt = (modalEntry.meta.measurement_type as MeasurementType) ?? 'acc';
        const rawTargets = modalEntry.meta.source_targets as
          | { id_link?: string; ch_in?: number | null; n_channels?: number; n_cols?: number }[]
          | undefined;
        const contexts: { setId: number; chIn: number | null; nChannels: number; nCols: number }[] = [];
        let ok = true;
        if (Array.isArray(rawTargets) && rawTargets.length > 0) {
          for (const rt of rawTargets) {
            const sid = typeof rt.id_link === 'string' ? linkToSet.get(rt.id_link) : undefined;
            if (sid === undefined) { ok = false; break; }
            const tf = seed[sid]?.tf;
            contexts.push({
              setId: sid,
              chIn: tf ? (tf.chIn ?? null) : ((rt.ch_in ?? null) as number | null),
              nChannels: tf ? (tf.nChannels ?? 1) : (rt.n_channels ?? 1),
              nCols: tf ? (tf.data.shape[1] ?? 1) : (rt.n_cols ?? 1),
            });
          }
        } else {
          const link = modalEntry.meta.id_link;
          const sid = typeof link === 'string' ? linkToSet.get(link) : undefined;
          if (sid === undefined) ok = false;
          else {
            const tf = seed[sid]?.tf;
            contexts.push({
              setId: sid,
              chIn: tf ? (tf.chIn ?? null) : ((modalEntry.meta.source_ch_in as number | null) ?? 0),
              nChannels: tf ? (tf.nChannels ?? 1) : ((modalEntry.meta.source_n_channels as number) ?? 1),
              nCols: tf ? (tf.data.shape[1] ?? 1)
                : Math.max(0, Math.round(((matrix.shape[1] ?? 2) - 2) / 4)),
            });
          }
        }
        if (ok && contexts.length > 0) {
          modalItem = modalEntry;                        // adopt for in-place upsert
          lastMatrix = matrix;                           // adopted item already in items
          modal.seedFromMatrix(matrix, contexts, mt);
          const allReady = contexts.every((c) => (seed[c.setId]?.tf?.data.shape[1] ?? 0) > 0);
          if (allReady) void calcFit(contexts[0].setId, null, mt, 'recon');
        }
      }
    }

    return populatedViews(seed);
  }

  /**
   * Write the current channel labels and per-set analysis settings onto
   * each working set's DvmaItem.ui so the next `writeDvma` persists them
   * in the manifest. Called from the save / autosave path BEFORE
   * serialization (Plan 2 persistence).
   *
   * Mutates items in place (they live inside the `dataset` store by
   * reference); no store emission is needed — the caller serializes
   * immediately after.
   */
  function stampUiState(): void {
    for (const ws of working) {
      const ui: DvmaItemUi = {};

      // Channel labels (sparse).
      const labels = selection.getLabelsForSet(ws.setId);
      if (labels) ui.channel_labels = labels;

      // x(iω) display power (round-6): persist only when non-identity.
      const iwP = get(derived)[ws.setId]?.iwPower ?? 0;
      if (iwP) ui.iw_power = iwP;

      // Per-set analysis settings (full snapshot per view).
      if (settings) {
        const freq = settings.get(ws.setId, 'freq');
        const tf = settings.get(ws.setId, 'tf');
        const sono = settings.get(ws.setId, 'sono');
        const d = defaults();
        // Only include views that differ from defaults (keep files lean),
        // but always include all if ANY field was customised.
        const freqChanged = freq.window !== d.freq.window || freq.mode !== d.freq.mode || freq.nFrames !== d.freq.nFrames;
        const tfChanged = tf.chIn !== d.tf.chIn || tf.window !== d.tf.window || tf.averaging !== d.tf.averaging || tf.nFrames !== d.tf.nFrames;
        const sonoChanged = sono.nFft !== d.sono.nFft || sono.dynRangeDb !== d.sono.dynRangeDb
          || sono.method !== d.sono.method || sono.voicesPerOctave !== d.sono.voicesPerOctave
          || sono.w0 !== d.sono.w0 || sono.fMin !== d.sono.fMin || sono.fMax !== d.sono.fMax;
        if (freqChanged || tfChanged || sonoChanged) {
          ui.analysis = {};
          if (freqChanged) ui.analysis.freq = { ...freq };
          if (tfChanged) ui.analysis.tf = { ...tf };
          if (sonoChanged) ui.analysis.sono = { ...sono };
        }
      }

      // Only set `ui` when there's something to persist (avoids empty
      // objects in the manifest for sets with all-default state).
      ws.time.ui = Object.keys(ui).length > 0 ? ui : undefined;
    }
  }

  /**
   * FFT of the targeted set(s), each with ITS OWN window from `settings`,
   * writing decoded freq arrays into `derived`. `target === 'all'` runs
   * every set; a setId runs just that one.
   */
  function calcFft(target: AnalysisTarget = 'all') {
    const my = bump('fft');
    return guarded('fft', async () => {
      for (const ws of targeted(target)) {
        const { window } = freqSettings(ws.setId);
        const { axis, data, nCh } = timePayload(ws.time);
        const res = await engine.enqueue('calc_fft', {
          time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
          window: window === 'none' ? null : window,
        });
        if (stale('fft', my)) return;                 // a newer FFT batch won
        setDerived(ws.setId, {
          freq: {
            axis: axisData(mval(res, 'freq_axis')),
            data: decodeArray(asMarshalled(mval(res, 'freq_data'))),
          },
        });
      }
    });
  }

  /**
   * PSD (+ CSD coherence matrix) of the targeted set(s), each at ITS OWN
   * window + n_frames from `settings`. `target === 'all'` runs every set.
   *
   * PARTIAL FAILURE (Round-3 item 1): each set is computed independently in
   * its own try/catch, so a set the engine CAN'T handle (e.g. a resolution
   * too fine for the 32-bit browser engine → glue.py raises a clear message)
   * does not stop the others. Sets that succeed render; the failing sets are
   * collected into ONE named `psd` error naming each set and its reason.
   */
  function calcPsd(target: AnalysisTarget = 'all') {
    const my = bump('psd');
    return guarded('psd', async () => {
      const failed: string[] = [];
      for (const ws of targeted(target)) {
        const s = freqSettings(ws.setId);
        const window = s.window === 'none' ? null : s.window;
        const { axis, data, nCh } = timePayload(ws.time);
        try {
          const res = await engine.enqueue('calc_psd', {
            time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
            window: window ?? 'hann', n_frames: s.nFrames,
          });
          if (stale('psd', my)) return;               // a newer PSD batch won
          const freqAxis = axisData(mval(res, 'freq_axis'));
          // Stamp the CSD pair (round-5 item 7) from the set's freq settings so
          // the cross-spectrum plots the chosen (X, Y) pair immediately.
          setDerived(ws.setId, {
            psd: { axis: freqAxis, data: decodeArray(asMarshalled(mval(res, 'psd'))) },
            csd: {
              axis: freqAxis, data: decodeArray(asMarshalled(mval(res, 'Cxy'))),
              i: s.csdX, j: s.csdY,
            },
          });
        } catch (e) {
          // One set failing must not abort the batch — record which set and
          // why, keep going, and surface the collected message at the end.
          failed.push(`${nameOf(ws.setId)}: ${e instanceof Error ? e.message : String(e)}`);
        }
      }
      if (stale('psd', my)) return;                   // a newer batch superseded us
      if (failed.length) throw new Error(psdFailedMessage(failed));
    });
  }

  /**
   * Re-stamp the CSD pair (X, Y) on the targeted set(s)' already-computed
   * coherence slice from their freq settings (round-5 item 7). The FULL
   * coherence + auto-power matrices are already present, so switching the pair
   * is a pure DISPLAY change — no recompute, no engine boot. A set with no CSD
   * slice yet is skipped (the pair is picked up at the next Calc). The caller
   * (FrequencyCard) patches the settings first, then calls this.
   */
  function setCsdPair(target: AnalysisTarget = 'all') {
    for (const ws of targeted(target)) {
      const cur = get(derived)[ws.setId]?.csd;
      if (!cur) continue;
      const { csdX, csdY } = freqSettings(ws.setId);
      if (cur.i === csdX && cur.j === csdY) continue;
      setDerived(ws.setId, { csd: { ...cur, i: csdX, j: csdY } });
    }
  }

  /**
   * Transfer function of the targeted set(s), each reading ITS OWN
   * chIn / window / averaging / nFrames from `settings`. Per set:
   * - 'none'   → calc_tf with n_frames = 1
   * - 'within' → calc_tf with the set's n_frames
   * - 'across' → one calc_tf_averaged over ALL working sets' time_data
   *   (an ensemble op — inherently multi-set; it uses the target set's
   *   chIn/window, attaches the single averaged curve to the first set,
   *   and ignores the per-set loop). `target === 'all'` runs every set.
   */
  function calcTf(target: AnalysisTarget = 'all') {
    const my = bump('tf');
    return guarded('tf', async () => {
      const sets = targeted(target);
      // A transfer function maps ONE input channel to the remaining OUTPUT
      // channels, so `calculate_tf` returns tf_data of shape (Nf, N−1). A
      // single-channel set therefore has ZERO output columns (tf_data is
      // (Nf, 0)) and the post-R4 model correctly draws NOTHING — which read
      // as a crash/broken TF to the user (round-2 feedback). Guard here:
      // skip any set that can't produce an output line and surface a clear
      // message via `computeErrors.tf` instead of issuing a meaningless worker
      // call. `< 2` channels ⇒ no output.
      const acrossSet = sets.find((ws) => tfSettings(ws.setId).averaging === 'across');
      if (acrossSet) {
        // 'across' is an ensemble over ALL sets; the target set names the
        // chIn/window to use. The averaged curve attaches to the FIRST set,
        // so that set must have an output channel too.
        const first = working[0];
        if (!first || first.nChannels < 2) {
          throw new Error(tfNoOutputMessage(first ? [nameOf(first.setId)] : []));
        }
        const { chIn, window } = tfSettings(acrossSet.setId);
        const ensemble = working.map(ws => {
          const { axis, data, nCh } = timePayload(ws.time);
          return { time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs };
        });
        const res = await engine.enqueue('calc_tf_averaged', {
          sets: ensemble, ch_in: chIn, window: window === 'none' ? null : window,
        });
        if (stale('tf', my)) return;                    // a newer TF request won
        const axis = axisData(mval(res, 'freq_axis'));
        // Carry the chIn it was computed with (and that set's channel count)
        // so the model remaps out/in against the same input channel (R4).
        const tf = tfFromResult(res, axis, chIn, first.nChannels);
        setDerived(first.setId, { tf });
        maybeRestoreModalRecon([first.setId]);          // deferred modal recon
        return;
      }
      // Per-set: run only the sets that HAVE an output channel; collect the
      // single-channel ones so we can explain why they produced no TF.
      const runnable = sets.filter((ws) => ws.nChannels >= 2);
      const skipped = sets.filter((ws) => ws.nChannels < 2);
      for (const ws of runnable) {
        const { chIn, window, averaging, nFrames } = tfSettings(ws.setId);
        const frames = averaging === 'none' ? 1 : nFrames;
        const { axis, data, nCh } = timePayload(ws.time);
        const res = await engine.enqueue('calc_tf', {
          time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
          ch_in: chIn, window: window === 'none' ? null : window, n_frames: frames,
        });
        if (stale('tf', my)) return;                  // stale-drop the whole batch
        const fAxis = axisData(mval(res, 'freq_axis'));
        // Carry this set's chIn + channel count onto the slice so the plot
        // model remaps its out/in columns/labels correctly (R4).
        setDerived(ws.setId, { tf: tfFromResult(res, fAxis, chIn, ws.nChannels) });
      }
      if (stale('tf', my)) return;                    // a newer batch superseded us
      // A newly-computed TF may satisfy a deferred modal restore (round-5 item 13).
      maybeRestoreModalRecon(runnable.map((ws) => ws.setId));
      // Any valid sets are now drawn; if we skipped single-channel sets,
      // tell the user why (routes to `computeErrors.tf` via `guarded`, shown
      // on the TF card + under the plot). A pure single-channel target
      // computes nothing and shows only this message.
      if (skipped.length > 0) {
        throw new Error(tfNoOutputMessage(skipped.map((ws) => nameOf(ws.setId))));
      }
    });
  }

  /**
   * Sonogram of one channel of one set (nperseg=nFft, noverlap=nFft/2).
   * `target` names the set by id; the set's `nFft` comes from `settings`.
   * `ch` is passed explicitly (the sonogram channel is a card control, not a
   * per-set stored setting).
   *
   * The sonogram is a single-set, single-channel view, so the SonoCard always
   * passes a concrete time-bearing setId (round-6 item 3). `'all'` is accepted
   * for API symmetry but resolves to the FIRST TIME-BEARING set — never a
   * leading orphan-TF set, which has no time series and would blank the plot.
   * A time-less target is refused with a clear `computeErrors.sono` message
   * rather than the opaque deref error it used to throw (round-6 item 2).
   */
  /**
   * Sonogram channel each set LAST computed with (post-clamp). The channel
   * is card-local UI state — not part of the per-set sono settings — so a
   * recompute of an existing sonogram (e.g. after Clean Impulse, see
   * `recomputeExisting`) records it here to re-run the SAME channel the
   * user is looking at rather than resetting to channel 0.
   */
  const lastSonoCh = new Map<number, number>();

  function calcSono(target: AnalysisTarget, ch: number) {
    const ws = target === 'all'
      ? working.find((w) => hasTimeData(w.time))
      : working.find((w) => w.setId === target);
    if (!ws) return Promise.resolve();
    const { nFft, method, voicesPerOctave, w0, fMin, fMax } = sonoSettings(ws.setId);
    const my = bump('sono');
    return guarded('sono', async () => {
      // Refuse a time-less set with a CLEAR message (round-6 item 2): an orphan
      // TF/spectrum set has no time series to transform, so proceeding would
      // deref a missing array and blank the heat canvas with an opaque error.
      if (!hasTimeData(ws.time)) throw new Error(sonoNoTimeMessage(nameOf(ws.setId)));
      const { axis, data, nCh } = timePayload(ws.time);
      // Clamp the requested channel to the set's channel range (round-4 bug
      // 1). The sono channel select (`ch`) is card-local state that is NOT
      // reset when the analysis target switches to a set with FEWER channels
      // (e.g. selecting ch_1 on a 2-channel set, then logging a mono take):
      // an out-of-range `ch` makes the engine's `sono_data[:, :, ch]` raise
      // `IndexError`, so the sonogram silently renders NOTHING while PSD/FFT
      // (which process every channel) still work. Clamping keeps a stale
      // select from blanking the plot; SonoCard also resets the select.
      const safeCh = Math.min(Math.max(0, Math.floor(ch)), Math.max(0, nCh - 1));
      lastSonoCh.set(ws.setId, safeCh);   // remembered for existence-gated recomputes
      const res = await engine.enqueue('calc_sono', {
        time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
        ch: safeCh, nperseg: nFft, noverlap: nFft >> 1,
        // CWT passthrough (ignored by the engine when method === 'stft').
        method, voices_per_octave: voicesPerOctave, w0,
        f_min: fMin ?? undefined, f_max: fMax ?? undefined,
      });
      if (stale('sono', my)) return;                    // a newer sonogram won
      setDerived(ws.setId, {
        sono: {
          timeAxis: axisData(mval(res, 'time_axis')),
          freqAxis: axisData(mval(res, 'freq_axis')),
          data: decodeArray(asMarshalled(mval(res, 'sono_data'))),
        },
      });
    });
  }

  /**
   * Recompute every derived result that ALREADY exists and reads `ws`'s
   * time data — the post-Clean-Impulse refresh. This is the cards' live-
   * recompute pattern (an existence gate on `hasComputed` followed by a
   * re-dispatch of the normal calc action with each set's CURRENT
   * settings): a kind the user never computed is never created, and each
   * recompute routes any failure to its own `computeErrors` slot.
   *
   * Covered kinds: FFT (`freq`), PSD + coherence (`psd`; the CSD pair is
   * re-stamped exactly as at calc time), the set's own per-set TF, an
   * 'across'-ensemble TF, and the sonogram (re-run on the channel it last
   * computed — see `lastSonoCh`). A csd-only slice with no psd (possible
   * only via a loaded `CrossSpecData`) is left alone: recomputing it would
   * fabricate a PSD the user never asked for.
   *
   * TF ensemble nuance: an 'across' TF is computed from ALL working sets'
   * time data (so the cleaned set ALWAYS feeds it) and attaches to the
   * FIRST working set. It is detected the same way `calcTf` resolves the
   * mode — some set's tf settings say 'across' — combined with the first
   * set carrying a TF slice; the recompute dispatches via the across-
   * owning set (whose chIn/window drive the ensemble). The cleaned set's
   * own TF dispatch is then skipped when it would just re-run that same
   * ensemble (its slice IS the ensemble result, or its own settings
   * resolve to the ensemble op).
   */
  async function recomputeExisting(ws: WorkingSet): Promise<void> {
    if (hasComputed(ws.setId, 'freq')) await calcFft(ws.setId);
    if (hasComputed(ws.setId, 'psd')) await calcPsd(ws.setId);

    const first = working[0];
    const acrossOwner = working.find((w) => tfSettings(w.setId).averaging === 'across');
    let ensembleRecomputed = false;
    if (acrossOwner && first && hasComputed(first.setId, 'tf')) {
      await calcTf(acrossOwner.setId);
      ensembleRecomputed = true;
    }
    const resolvesToEnsemble = ensembleRecomputed
      && (ws.setId === first.setId || tfSettings(ws.setId).averaging === 'across');
    if (hasComputed(ws.setId, 'tf') && !resolvesToEnsemble) await calcTf(ws.setId);

    if (hasComputed(ws.setId, 'sono')) {
      await calcSono(ws.setId, lastSonoCh.get(ws.setId) ?? 0);
    }
  }

  /**
   * Clean Impulse toggle cache (round-7b): per-set raw/cleaned array PAIRS
   * plus which one is applied. The first clean stashes the raw arrays and
   * caches the engine's cleaned result, so the toggle then swaps by
   * reference — the clean NEVER re-runs on its own output (idempotent) —
   * at the cost of holding both copies (~2x that set's time data; Tore's
   * explicit call: "doubles storage requirements but not usually
   * significant"). Session-local: Save/autosave write whichever copy is
   * APPLIED, and the other copy does not survive a reload.
   */
  interface CleanPair { td: NpyArray; ax: NpyArray; }
  const cleanCache = new Map<number, {
    raw: CleanPair; cleaned: CleanPair; chImpulse: number; active: boolean;
  }>();
  /** Reactive per-set cleaned flags — the Time card's toggle button state. */
  const cleanedSets = writable<Record<number, boolean>>({});

  /** Swap one raw/cleaned array pair onto the set + refresh its time slice. */
  function applyTimeArrays(ws: WorkingSet, pair: CleanPair): void {
    ws.time.arrays.time_data = pair.td;
    ws.time.arrays.time_axis = pair.ax;
    // The RAW stash can carry a loaded file's original dtype — normalise to
    // f64 for the plot slice exactly like the load-time seeding does.
    const f64 = (d: NpyArray['data']): Float64Array =>
      d instanceof Float64Array ? d : Float64Array.from(d as ArrayLike<number>);
    setDerived(ws.setId, {
      time: {
        axis: f64(pair.ax.data),
        data: decodeArray({ shape: pair.td.shape, data: f64(pair.td.data), complex: false }),
      },
    });
  }

  /**
   * TOGGLE the impulse clean on the set named by `target` (setId; 'all'
   * uses the first working set):
   *
   * - not cleaned → runs the engine clean on `chImpulse` and applies it,
   *   stashing the raw arrays (first time) or reusing the cached cleaned
   *   arrays (same channel — no engine op, never re-cleans cleaned data);
   * - cleaned → restores the stashed RAW arrays (no engine op).
   *
   * A different `chImpulse` re-cleans from the raw stash. Either direction
   * recomputes every derived result that ALREADY exists for the affected
   * set — FFT / PSD / TF / sonogram, including a live 'across'-ensemble TF
   * the set feeds (see `recomputeExisting`); kinds the user never computed
   * are not created. `cleanedSets` reflects the applied state per set.
   */
  function cleanImpulse(target: AnalysisTarget, chImpulse: number) {
    const ws = target === 'all' ? working[0] : working.find((w) => w.setId === target);
    if (!ws) return Promise.resolve();
    return guarded('clean', async () => {
      const entry = cleanCache.get(ws.setId);
      if (entry?.active) {
        // Toggle OFF: back to the stashed raw arrays.
        applyTimeArrays(ws, entry.raw);
        entry.active = false;
        cleanedSets.update((m) => ({ ...m, [ws.setId]: false }));
      } else if (entry && entry.chImpulse === chImpulse) {
        // Toggle back ON, same impulse channel: reuse the cached clean.
        applyTimeArrays(ws, entry.cleaned);
        entry.active = true;
        cleanedSets.update((m) => ({ ...m, [ws.setId]: true }));
      } else {
        // First clean (or a new impulse channel): the CURRENT arrays are the
        // raw ones (any prior clean is inactive here) — stash them, clean
        // from them, cache both copies.
        const raw: CleanPair = { td: ws.time.arrays.time_data, ax: ws.time.arrays.time_axis };
        const { axis, data, nCh } = timePayload(ws.time);
        const res = await engine.enqueue('clean_impulse', {
          time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs, ch_impulse: chImpulse,
        });
        const cleaned = asMarshalled(mval(res, 'time_data'));
        const newAxis = axisData(mval(res, 'time_axis'));
        const cleanedPair: CleanPair = {
          td: {
            shape: cleaned.shape, isComplex: false,
            data: cleaned.data instanceof Float64Array ? cleaned.data : Float64Array.from(cleaned.data),
          },
          ax: { shape: [newAxis.length], isComplex: false, data: newAxis },
        };
        cleanCache.set(ws.setId, { raw, cleaned: cleanedPair, chImpulse, active: true });
        applyTimeArrays(ws, cleanedPair);
        cleanedSets.update((m) => ({ ...m, [ws.setId]: true }));
      }
      // The arrays were swapped in place on the item that lives inside the
      // `dataset` store, so `derived` (the plot) already updated via
      // setDerived — but the store itself never re-emitted, and autosave is
      // driven by a `dataset` subscription (App.svelte). Re-emit the same
      // object so the applied state is autosaved; otherwise a toggle followed
      // by a tab-close silently loses it (explicit Save is unaffected).
      dataset.update((d) => d);
      // Refresh the already-computed derived results from the applied data so
      // the FFT/PSD/TF/sono views never show a stale copy's spectra.
      await recomputeExisting(ws);
    });
  }

  /**
   * Add a recorded TimeData item to the existing dataset (or create one
   * if empty).  The item is appended, registered with the selection
   * tray, and seeded into the derived map so the time view shows it
   * immediately.  Returns the new set's `setId`.
   *
   * Plan 2 acquisition: called by the AcquireCard after a successful
   * recording — the item comes from `recordingToItem` in acquire.ts.
   */
  function addRecordedSet(item: DvmaItem): number {
    // Ensure a dataset exists.
    let ds = get(dataset);
    if (!ds) {
      ds = { formatVersion: 2, pydvmaVersion: 'webui', items: [] };
    }
    ds.items.push(item);
    dataset.set(ds);

    const nCh = itemChannels(item);
    const axis = item.arrays.time_axis?.data;
    const dur = axis && axis.length ? axis[axis.length - 1] - axis[0] : 0;
    const name = (item.meta.test_name as string) || 'set';
    const timestamp = (item.meta.timestring as string) || '';
    const setId = selection.addSet({ name, nChannels: nCh, durationS: dur, timestamp });
    const ws: WorkingSet = { setId, time: item, fs: sampleRate(item), durationS: dur, nChannels: nCh };
    working.push(ws);

    // Seed the time arrays so the time view draws immediately, plus any
    // calibration the recorder attached (channel_sensitivities → cal factors).
    setDerived(setId, {
      time: {
        axis: Float64Array.from(item.arrays.time_axis.data),
        data: decodeArray({
          shape: item.arrays.time_data.shape,
          data: item.arrays.time_data.data as Float64Array,
          complex: item.arrays.time_data.isComplex,
        }),
      },
      calFactors: normalizeFactors(item.meta.channel_cal_factors, nCh),
      units: normalizeUnits(item.meta.units, nCh),
    });

    return setId;
  }

  /**
   * Read a set's persisted calibration for the Calibrate dialog (Task A2):
   * the per-channel `channel_cal_factors` multipliers and engineering `units`,
   * both normalised to the set's channel count (defaults: factor `1`, unit
   * `'V'`). Reads from the source `DvmaItem` meta — the authoritative store
   * that `.dvma` persists — not the derived slice. Unknown set ⇒ empty arrays.
   */
  function getCalibration(setId: number): { factors: number[]; units: string[] } {
    const ws = working.find((w) => w.setId === setId);
    if (!ws) return { factors: [], units: [] };
    return {
      factors: normalizeFactors(ws.time.meta.channel_cal_factors, ws.nChannels),
      units: normalizeUnits(ws.time.meta.units, ws.nChannels),
    };
  }

  /**
   * Persist a set's calibration and reflect it in the live plot (Task A2).
   *
   * `factors` are pydvma's plain `channel_cal_factors` multipliers (the dialog
   * converts the user's sensitivity via `1/sensitivity` before calling this).
   * Both `factors` and the optional per-channel `units` are padded/truncated to
   * the set's channel count so the stored arrays never desync from the data.
   *
   * Writes through `setItemMeta` (keeping the decoded `meta` and tagged
   * `metaRaw` views consistent, the real `channel_cal_factors` / `units`
   * manifest fields both codecs round-trip — NOT the `ui` blob), patches the
   * derived `calFactors` slice so `buildPlotModel` re-scales at once, and
   * re-emits the `dataset` store so the autosave subscription captures it.
   */
  function setCalFactors(setId: number, factors: number[], units?: readonly string[]): void {
    const ws = working.find((w) => w.setId === setId);
    if (!ws) return;
    const norm = normalizeFactors(factors, ws.nChannels);
    setItemMeta(ws.time, 'channel_cal_factors', norm);
    if (units !== undefined) {
      setItemMeta(ws.time, 'units', normalizeUnits(units, ws.nChannels));
    }
    setDerived(setId, {
      calFactors: norm,
      units: normalizeUnits(units !== undefined ? units : ws.time.meta.units, ws.nChannels),
    });
    dataset.update((d) => d);            // re-emit so autosave persists the edit
  }

  // Publish the calibration API so the tray's Calibrate dialog can reach it
  // without a prop thread through App.svelte (see `calibrationController`).
  calibrationController.set({ getCalibration, setCalFactors });

  // --------------------------------------------------------------------- //
  // Scaling tools (round-6 Qt-parity): x(iω) display power + Best Match
  // --------------------------------------------------------------------- //

  /** Read a set's x(iω) display power (0 = identity). */
  function getIwPower(setId: number): number {
    return get(derived)[setId]?.iwPower ?? 0;
  }

  /**
   * Set a set's x(iω) DISPLAY power (round-6 Qt-parity Scaling tool, the
   * NON-DESTRUCTIVE analogue of Qt's `multiply_by_power_of_iw`). `power` is an
   * integer in [-2, +2]; the FFT/TF views multiply the complex value by
   * `(iω)^p` at DISPLAY time (see `model.ts`), so `+1` differentiates and `-1`
   * integrates — the stored arrays are NEVER mutated, so a set that recomputes
   * stays correct. Persisted per-set in `.dvma` UI state (`iw_power`, via
   * `stampUiState`) and autosaved. Any modal-fit pseudo-set overlaying the set
   * inherits the same power so its reconstruction stays visually locked to the
   * (transformed) measured line. The display power does NOT feed the modal fit
   * (that reads the raw TF + its own measurement_type).
   */
  function setIwPower(setId: number, power: number): void {
    const ws = working.find((w) => w.setId === setId);
    if (!ws) return;
    const p = normalizeIwPower(power);
    setDerived(setId, { iwPower: p });
    // Keep an overlaying fit pseudo-set locked to the same display power.
    const fit = fitSets.get(setId);
    if (fit && get(derived)[fit.id]) setDerived(fit.id, { iwPower: p });
    dataset.update((d) => d);            // re-emit so autosave persists the change
  }

  /**
   * Best Match relative scaling (round-6 Qt-parity — Qt's `analysis.best_match`
   * + `set_calibration_factors_all`). Rescales EVERY TF-bearing set's output
   * columns to best match ONE reference column of set `refSetId` over
   * `freqRange` (the committed shared frequency window; `null` = each set's full
   * band), then folds the resulting factor into the SOURCE channel's
   * `channel_cal_factors` through the EXISTING calibration path — so the scaling
   * is display-time, `.dvma`-persisted, Undo-able (re-open Calibrate + reset),
   * and visible/editable in the Calibrate dialog afterwards.
   *
   * `refChannel` is a SOURCE channel of the reference set; it maps to its TF
   * output column (falling back to column 0 if it names the input channel). The
   * reference column gets factor ~1 (matches itself, times its current cal
   * factor); every other set/column is scaled relative to it. Toasts the applied
   * per-set factors; no-ops (with a toast) when no TF exists yet.
   */
  async function calcBestMatch(
    refSetId: number, refChannel: number, freqRange: [number, number] | null = null,
  ): Promise<void> {
    const specs = working.map((w) => tfSpecOf(w)).filter((s): s is FitSpec => s !== null);
    if (specs.length === 0) {
      toasts?.push('Best match needs a transfer function — Calc TF first.', { level: 'info' });
      return;
    }
    const found = specs.findIndex((s) => s.ws.setId === refSetId);
    const refIdx = found >= 0 ? found : 0;
    const refSpec = specs[refIdx];
    // Reference OUTPUT column from the chosen source channel (input → column 0).
    const refCol = tfColumn(refChannel, refSpec.chIn, refSpec.nChannels) ?? 0;
    const refCal = getCalibration(refSpec.ws.setId).factors[refChannel] ?? 1;

    engine.boot();
    busyN += 1;
    busy.set(true);
    try {
      const payload: Record<string, unknown> = {
        sets: specs.map((s) => ({
          freq_axis: s.slice.axis, tf_data: interleaveTf(s.slice, s.cols), n_tf: s.nCols,
        })),
        set_ref: refIdx,
        ch_ref: refCol,
      };
      // Omit freq_range when null: a JS null crosses the FFI as a truthy JsNull
      // proxy, so leaving the key off lets the engine's full-band default apply.
      if (freqRange) payload.freq_range = freqRange;
      const res = await engine.enqueue('calc_best_match', payload);
      const raw = mval(res, 'factors');
      const factorList: Float64Array[] = Array.isArray(raw)
        ? (raw as unknown[]).map((a) => axisData(a))
        : [];
      const summary: string[] = [];
      specs.forEach((s, i) => {
        const facs = factorList[i];
        if (!facs) return;
        const cur = getCalibration(s.ws.setId);
        const next = cur.factors.slice();
        for (let c = 0; c < s.nCols; c++) {
          const sc = sourceOfColumn(c, s.chIn, s.nChannels);
          const f = facs[c];
          if (sc >= 0 && sc < next.length && Number.isFinite(f) && f !== 0) {
            next[sc] = refCal * f;
          }
        }
        setCalFactors(s.ws.setId, next, cur.units);
        // Report the reference column's factor per set as the headline number.
        const head = facs[Math.min(refCol, facs.length - 1)];
        summary.push(`${nameOf(s.ws.setId)} ×${Number.isFinite(head) ? head.toPrecision(3) : '1'}`);
      });
      toasts?.push(
        `Best match → ${nameOf(refSpec.ws.setId)}: ${summary.join(', ')}`,
        { level: 'success' },
      );
    } catch (e) {
      toasts?.push(`Best match failed: ${e instanceof Error ? e.message : String(e)}`, { level: 'error' });
    } finally {
      busyN -= 1;
      busy.set(busyN > 0);
    }
  }

  // --------------------------------------------------------------------- //
  // Modal-fit pseudo-set + persistence (round-5 item 13)
  // --------------------------------------------------------------------- //
  //
  // The modal model becomes a first-class TRAY CARD: its reconstruction
  // registers as a `role:'fit'` selection set whose lines flow through the
  // normal visible-line pipeline (so tri-state / solo / legend "just work"),
  // and it PERSISTS as a `ModalData` item inside the dataset so Save / autosave
  // / Load round-trip it. `syncModal` reconciles BOTH from the modal store on
  // every change (driven by a store subscription).
  //
  // WHICH reconstruction the card draws is the store's `reconMode` (round-7
  // item 6): 'global' (default) = the whole model on each set's measured axis;
  // 'local' = the just-fitted modes dense over the fit window. Previously the
  // local recon was an App-level pink overlay on the PRIMARY set only, drawn
  // alongside the global pseudo-sets — feedback asked for local lines on ALL
  // sets/channels and an explicit either/or toggle, so both slices now flow
  // through the same pseudo-set pipeline and the mode names the legend rows.
  //
  // GUARD RAILS (one predicate — `role === 'fit'`): the pseudo-set is excluded
  // from `dataSetsView` (so the analysis "Dataset ▾" dropdowns + calc targets
  // never see it), NEVER enters `working` (so MAT/CSV export + save-as-TimeData
  // skip it), and is only ever serialized as `ModalData` (below), never as a
  // TimeData.

  /** Fallback recon colour when the target set's colour is unavailable. */
  const FIT_FALLBACK_COLOR = '#66708a';   // mockup grey (round2-bench.html)

  /**
   * Modal-fit pseudo-sets, keyed by the SOURCE setId they overlay (item 7:
   * a shared-pole model spanning several sets registers ONE pseudo-set per
   * set — the cleanest option, "one card per set fed from one M", so each
   * set's recon lines keep the same `tfColumn` remap, legend and per-line
   * tri-state as the measured lines, and the `role === 'fit'` exclusion
   * predicate is unchanged). `nChannels` is cached so a set whose channel
   * count changes rebuilds its card; `mode` so a reconMode flip renames the
   * card in place (per-line tri-state survives the flip). A single-set fit
   * has ONE entry. */
  const fitSets = new Map<number, { id: number; nChannels: number; mode: ReconMode; chansKey: string }>();
  /** Reactive list of the live pseudo-set selection ids (drives the exposed
   *  `fitSetId` prop). */
  const fitSetIdsW = writable<number[]>([]);
  /** The `ModalData` item kept inside `dataset.items` (persistence), or null. */
  let modalItem: DvmaItem | null = null;
  /** Last CHOSEN recon slice synced per source setId (by reference) so
   *  `syncModal` skips no-op derived emits — a reconMode flip changes the
   *  reference, so it refeeds; and the last matrix synced for persistence. */
  const lastSliceBySet = new Map<number, ReconArrays | null>();
  let lastMatrix: MarshalledArray | null = null;

  /** id_link for a source set = its TimeData `unique_id` (or `id_link`). */
  function idLinkOf(setId: number): string | null {
    const ws = working.find((w) => w.setId === setId);
    const uid = ws?.time.meta.unique_id;
    if (typeof uid === 'string' && uid) return uid;
    const link = ws?.time.meta.id_link;
    return typeof link === 'string' && link ? link : null;
  }

  /**
   * Insert or update the persisted `ModalData` item from the current model.
   *
   * Mirrors pydvma `container.py`'s ModalData schema so python's
   * `container.load` reads it back: array `M` (the modal matrix, row-major
   * `[fn, zn, an*C, pn*C, rk*C, rm*C]` — `C` = TOTAL columns across every set
   * the model spans, exactly as Qt stores a shared-pole fit), meta `units /
   * test_name / timestamp / timestring / id_link / channels`. For a shared-pole
   * model `id_link` is the LIST of the spanned sets' unique_ids (the native
   * pydvma representation — `modal_fit_all_channels` sets a list). Extra
   * webui-only meta keys let the LOADER rebuild the geometry + recompute the
   * recon: `measurement_type`, `source_ch_in` / `source_n_channels` (the FIRST
   * target, backward compatible with the single-set loader), and `source_targets`
   * — a JSON list of `{id_link, ch_in, n_channels, n_cols}` per spanned set, in
   * reconstruction-column order. pydvma ignores manifest keys it does not know,
   * so they are harmless to the python reader. `timestamp` carries a
   * `{__datetime__}` tag in `metaRaw` so python decodes a real datetime.
   */
  function upsertModalItem(m: ModalState): void {
    const ds = get(dataset);
    if (!ds || !m.matrix || m.targets.length === 0) return;
    const matrix = m.matrix;
    const channels = Math.max(0, Math.round(((matrix.shape[1] ?? 2) - 2) / 4));
    const primary = m.targets[0];
    const units = (working.find((w) => w.setId === primary.setId)?.time.meta.units as unknown) ?? null;
    const links = m.targets.map((t) => idLinkOf(t.setId)).filter((l): l is string => !!l);
    const sourceTargets = m.targets.map((t) => ({
      id_link: idLinkOf(t.setId), ch_in: t.chIn, n_channels: t.nChannels, n_cols: t.nCols,
    }));
    const iso = new Date().toISOString();
    const meta: Record<string, unknown> = {
      units, test_name: `modal_${nameOf(primary.setId)}`,
      timestamp: iso, timestring: iso,
      // Single link for a single-set model (unchanged), else the list of links.
      id_link: links.length <= 1 ? (links[0] ?? null) : links,
      channels,
      measurement_type: m.mt, source_ch_in: primary.chIn, source_n_channels: primary.nChannels,
      source_targets: sourceTargets,
    };
    const metaRaw: Record<string, unknown> = { ...meta, timestamp: { __datetime__: iso } };
    const M: NpyArray = {
      shape: matrix.shape.slice(),
      data: matrix.data instanceof Float64Array ? matrix.data : Float64Array.from(matrix.data),
      isComplex: false,
    };
    if (modalItem) {
      modalItem.arrays = { M }; modalItem.meta = meta; modalItem.metaRaw = metaRaw;
    } else {
      modalItem = { kind: 'ModalData', arrays: { M }, meta, metaRaw, settings: null };
      ds.items.push(modalItem);
    }
  }

  /** Remove ONE source set's fit pseudo-set from selection + derived. */
  function removeFitSetFor(srcId: number): void {
    const rec = fitSets.get(srcId);
    if (!rec) return;
    fitSets.delete(srcId);
    lastSliceBySet.delete(srcId);
    selection.removeSet(rec.id);
    derived.update((d) => { const n = { ...d }; delete n[rec.id]; return n; });
  }

  /** Remove every fit pseudo-set (model cleared / retargeted). */
  function removeAllFitSets(): void {
    for (const srcId of Array.from(fitSets.keys())) removeFitSetFor(srcId);
    fitSetIdsW.set([]);
  }

  /** Drop the persisted ModalData item from the dataset (model cleared). */
  function removeModalItem(): void {
    const ds = get(dataset);
    if (ds && modalItem) {
      const i = ds.items.indexOf(modalItem);
      if (i >= 0) ds.items.splice(i, 1);
    }
    modalItem = null;
  }

  /** The recon slice `reconMode` picks from a target (round-7 item 6). */
  function chosenSlice(t: ModalState['targets'][number], mode: ReconMode): ReconArrays | null {
    return mode === 'local' ? t.local : t.global;
  }

  /** Legend/tray name for a target's fit pseudo-set — carries the reconMode
   *  so the legend says WHICH reconstruction the lines are (round-7 item 6). */
  function fitSetName(srcId: number, mode: ReconMode): string {
    return `Modal fit ${mode} (${nameOf(srcId)})`;
  }

  /**
   * Reconcile the fit pseudo-set(s) + the ModalData item with the modal store.
   * Called on every modal-store change (subscription below). Reference checks
   * keep idempotent emits (mt / pushUndo) cheap — the set/derived/dataset only
   * change when the chosen recon or matrix reference actually changes.
   *
   * - ONE pseudo-set per target set the shared-pole model spans (item 7), each
   *   existing only while that set has a non-empty slice OF THE KIND `reconMode`
   *   picks (round-7 item 6: 'local' or 'global' — its lines ARE that slice).
   *   In 'local' mode that means lines exist only straight after a Fit (the
   *   engine returns an empty local slice for recon/refine/mute recomputes,
   *   matching the old transient pink overlay's lifetime). The `tf` slice
   *   carries the set's own out/in geometry so the same `tfColumn` remap +
   *   legend as the measured lines apply. A reconMode flip renames each card
   *   in place and refeeds its slice, so per-line tri-state survives the flip.
   * - The ModalData item persists whenever a model exists (even before the
   *   recon lands — e.g. a loaded model whose TFs are not yet computed).
   */
  function syncModal(): void {
    if (!modal) return;
    const m = modal.get();
    const hasModel = !!m.matrix && m.modes.length > 0 && m.setId !== null;
    const mode = m.reconMode;

    // ---- Pseudo-sets (visible recon lines), one per drawable target ----
    const drawable = hasModel
      ? m.targets.filter((t) => {
          const s = chosenSlice(t, mode);
          return s && ((s.data.shape[1] ?? 0) > 0);
        })
      : [];
    const wantIds = new Set(drawable.map((t) => t.setId));
    // Drop pseudo-sets whose source set no longer has a drawable slice.
    for (const srcId of Array.from(fitSets.keys())) {
      if (!wantIds.has(srcId)) removeFitSetFor(srcId);
    }
    for (const t of drawable) {
      // Round-7h: a fit can span a SUBSET of the set's channels (the lines
      // left visible at fit time). Subset pseudo-sets carry one line per
      // FITTED channel (orphan-style 1:1 columns, chIn null) with the source
      // line's colour and label; full-set fits keep the legacy chIn remap.
      const subset = t.chans !== null;
      const lineCount = subset ? t.chans!.length : t.nChannels;
      const chansKey = subset ? t.chans!.join(',') : 'all';
      let rec = fitSets.get(t.setId);
      // A changed channel geometry needs a fresh card (colours/labels/remap).
      if (rec && (rec.nChannels !== lineCount || rec.chansKey !== chansKey)) {
        removeFitSetFor(t.setId);
        rec = undefined;
      }
      if (!rec) {
        // Mirror the SOURCE lines' colours so each recon line reads as the fit
        // of the measured line it overlays; dashing (model.ts) is the fit
        // signature.
        const srcCh = (c: number) => (subset ? t.chans![c] : c);
        const colors = Array.from({ length: lineCount },
          (_, c) => selection.lineColor(t.setId, srcCh(c)) ?? FIT_FALLBACK_COLOR);
        const id = selection.addSet({
          name: fitSetName(t.setId, mode),
          nChannels: lineCount, durationS: 0, timestamp: '', role: 'fit', colors,
        });
        if (subset) {
          // Label each pseudo line with its SOURCE channel's display label so
          // the legend reads e.g. "Modal fit global (set) · ch_2".
          const labelOf = get(selection.channelLabel);
          for (let c = 0; c < lineCount; c++) {
            selection.renameChannel(id, c, labelOf(t.setId, t.chans![c]));
          }
        }
        rec = { id, nChannels: lineCount, mode, chansKey };
        fitSets.set(t.setId, rec);
      } else if (rec.mode !== mode) {
        // Mode flipped: rename in place (legend reflects the mode) rather than
        // rebuilding, so per-line tri-state / custom labels survive.
        selection.rename(rec.id, fitSetName(t.setId, mode));
        rec.mode = mode;
      }
      const s = chosenSlice(t, mode)!;
      if (lastSliceBySet.get(t.setId) !== s) {
        setDerived(rec.id, {
          tf: subset
            ? { axis: s.axis, data: s.data, chIn: null, nChannels: lineCount }
            : { axis: s.axis, data: s.data, chIn: t.chIn, nChannels: t.nChannels },
        });
        lastSliceBySet.set(t.setId, s);
      }
    }
    fitSetIdsW.set(Array.from(fitSets.values()).map((r) => r.id));

    // ---- Persisted ModalData item ----
    if (hasModel) {
      if (m.matrix !== lastMatrix) {
        upsertModalItem(m);
        lastMatrix = m.matrix;
        dataset.update((d) => d);       // re-emit → autosave persists the edit
      }
    } else if (modalItem) {
      removeModalItem();
      lastMatrix = null;
      dataset.update((d) => d);
    }
  }

  // Drive `syncModal` off every modal-store change: fit / reject / delete /
  // refine / mute-recon / undo / clear / reset / reconMode flip all flow
  // through here, so the tray card + persistence stay consistent with the
  // model with no per-action wiring. Fires once at construction (empty model
  // → no-op).
  if (modal) modal.subscribe(() => syncModal());

  /** Primary (first) pseudo-set id, exposed for App as a single-store prop. */
  const fitSetIdW = svelteDerived(fitSetIdsW, ($ids) => ($ids.length ? $ids[0] : null));

  /**
   * Clear the modal model from the tray-card delete (round-5 item 13). Empties
   * the model into the one-level undo slot (so `syncModal` removes the card + the
   * ModalData item) and offers a toast Undo — one click restores the fit and its
   * cached recon overlays with no engine call.
   */
  function clearFit(): void {
    if (!modal) return;
    modal.clearWithUndo();
    toasts?.push('Modal fit cleared.', { level: 'info', actions: [{ label: 'Undo', run: () => modal.undo() }] });
  }

  /**
   * Restore a DEFERRED modal recon (round-5 item 13; item 7 multi-set): after a
   * TF is first computed for a set, if a loaded model is waiting (matrix seeded,
   * no pseudo-sets built yet) and ALL the sets it spans now have a computed TF,
   * recompute its (shared-pole) reconstruction so the fit card(s) + recon lines
   * appear. No-op unless exactly that condition holds — a shared-pole model
   * needs every spanned set's TF present before it can be reconstructed.
   */
  function maybeRestoreModalRecon(setIds: number[]): void {
    if (!modal) return;
    const m = modal.get();
    if (!m.matrix || m.targets.length === 0 || m.global || fitSets.size > 0) return;
    if (!m.targets.some((t) => setIds.includes(t.setId))) return;
    const d = get(derived);
    const ready = m.targets.every((t) => (d[t.setId]?.tf?.data.shape[1] ?? 0) > 0);
    if (ready) void calcFit(m.targets[0].setId, null, m.mt, 'recon');
  }

  /**
   * Resolve the working set a fit `target` names AND that has a computed TF.
   * A setId picks that set (if it has a TF); `'all'` picks the FIRST set with
   * a TF. `undefined` when nothing fittable exists — `calcFit` no-ops.
   */
  function fitSet(target: AnalysisTarget): WorkingSet | undefined {
    const d = get(derived);
    const pool = target === 'all' ? working : working.filter((w) => w.setId === target);
    return pool.find((w) => d[w.setId]?.tf && (d[w.setId]!.tf!.data.shape[1] ?? 0) > 0);
  }

  /** A resolved per-set fit spec: the working set, its TF slice, and geometry. */
  interface FitSpec {
    ws: WorkingSet;
    slice: NonNullable<SetArrays['tf']>;
    chIn: number | null;
    nChannels: number;
    /** FITTED column count (a visibility subset when `visibleOnly`). */
    nCols: number;
    /** Fitted TF column indices within the slice (ascending). */
    cols: number[];
    /** Fitted source CHANNEL per column (same length as `cols`). */
    chans: number[];
    /** True when every TF column of the slice is fitted. */
    allCols: boolean;
  }

  /** Build a FitSpec from a working set IF it has a non-empty TF, else null.
   *  Preserves an orphan TF's null chIn (columns are the lines — round-5 item 3);
   *  `chIn === undefined` (no chIn recorded) collapses to 0 as before.
   *
   *  `visibleOnly` (round-7h — the modal fit): keep only the columns whose
   *  LINE is left visible in the legend/tray (tri-state on/fade; 'off' lines
   *  are excluded) — the legend is the fit's line selector, so a multi-
   *  instrument set (e.g. a composited JW file) can fit one line at a time
   *  by hiding or soloing. A set with every line hidden returns null (it
   *  drops out of the fit entirely). Best match and other non-fit consumers
   *  pass false and keep every column. */
  function tfSpecOf(ws: WorkingSet, visibleOnly = false): FitSpec | null {
    const slice = get(derived)[ws.setId]?.tf;
    const totalCols = slice?.data.shape[1] ?? 0;
    if (!slice || totalCols === 0) return null;
    const chIn = slice.chIn === undefined ? 0 : slice.chIn;
    const nChannels = slice.nChannels ?? totalCols + 1;
    const visible = visibleOnly
      ? new Set(get(selection.legendEntries).filter((e) => e.setId === ws.setId).map((e) => e.ch))
      : null;
    const cols: number[] = [];
    const chans: number[] = [];
    for (let col = 0; col < totalCols; col++) {
      // Column -> source channel: orphan TFs (chIn null) map 1:1; otherwise
      // the input channel is skipped (the tfColumn convention).
      const ch = chIn === null ? col : (col < chIn ? col : col + 1);
      if (visible && !visible.has(ch)) continue;
      cols.push(col);
      chans.push(ch);
    }
    if (cols.length === 0) return null;
    return { ws, slice, chIn, nChannels, nCols: cols.length, cols, chans,
             allCols: cols.length === totalCols };
  }

  /** Interleave a TF slice's chosen complex columns to [re,im,…] row-major. */
  function interleaveTf(slice: NonNullable<SetArrays['tf']>, cols: number[]): Float64Array {
    const re = slice.data.re, im = slice.data.im;
    const rows = slice.axis.length;
    const total = slice.data.shape[1];
    const flat = new Float64Array(rows * cols.length * 2);
    let o = 0;
    for (let r = 0; r < rows; r++) {
      for (const c of cols) {
        const i = r * total + c;
        flat[o++] = re[i];
        flat[o++] = im ? im[i] : 0;
      }
    }
    return flat;
  }

  /** Actions that change the mode set (get a one-level undo snapshot). */
  type FitAction = 'fit' | 'reject' | 'recon' | 'refine' | 'delete_one';
  const DESTRUCTIVE: ReadonlySet<FitAction> = new Set(['reject', 'delete_one', 'refine']);
  /**
   * Fit target: `'shared'` = a JOINT shared-pole fit over EVERY TF-bearing set
   * (item 7 — Qt's `fit_mode`, one fn/zn per mode with per-set/-channel
   * amplitudes); `'all'` = the first TF-bearing set (legacy single-set default);
   * a setId = that one set. The Fit-card control owns this choice LOCALLY rather
   * than reusing `analysisSettings.analysisTarget`, because for the other cards
   * `analysisTarget='all'` means "each set INDEPENDENTLY", whereas here the
   * multi-set option means "all sets JOINTLY (shared poles)" — a different
   * semantic that would be confusing to overload onto the shared target.
   */
  type FitTargetSel = AnalysisTarget | 'shared';

  /**
   * Modal fit / reject / delete-one / refine / reconstruction over ONE set's TF
   * or, with SHARED POLES, several sets' TFs jointly (Task A1; round-4 items
   * 9-10; round-6 item 7). The engine (`calc_fit`) is STATELESS — the modal
   * store holds the accumulated matrix `M` and this re-sends it, so
   * add/replace/delete/refine all round-trip through the store. `action`:
   *
   * - `'fit'`        — fit `nModes` mode(s) over `freqRange` (the CURRENT
   *   visible TF window) and add/replace into the model.
   * - `'reject'`     — delete modes whose fn lies in `freqRange`.
   * - `'delete_one'` — delete the single mode at `index` (the chip's × button).
   * - `'refine'`     — simultaneously refine ALL modes (seeded from `M`, over
   *   the modes' band; `freqRange` is ignored). Auto-reverts (via the store's
   *   undo slot) when the engine reports the refinement did not improve.
   * - `'recon'`      — recompute the overlays from the current model (no fit);
   *   used when the mute set changes.
   *
   * TARGET (`'fit'` only): `'shared'` jointly fits every TF-bearing set with one
   * fn/zn per mode (per-set amplitudes); a setId (or `'all'`) fits ONE set. Any
   * action OTHER than `'fit'` operates on the EXISTING model and reuses its
   * exact spanned-set composition (so a shared-pole model stays coherent across
   * follow-ups) — it no-ops if any spanned set's TF is missing.
   *
   * Destructive actions push a one-level undo snapshot BEFORE the round-trip.
   * The mute list is sent for `'recon'` only (after fit/delete the mode rows
   * shift, so the muted set is reset by the store and irrelevant here).
   *
   * The store's matrix is re-sent only when THIS call's set composition matches
   * the stored model's (same sets, same order), so switching target sets starts
   * a fresh model rather than mixing incompatible column geometries.
   */
  function calcFit(
    target: FitTargetSel = 'all',
    freqRange: [number, number] | null = null,
    mt: MeasurementType = 'acc',
    action: FitAction = 'fit',
    nModes = 1,
    index?: number,
  ) {
    if (!modal) return Promise.resolve();
    // Record the measurement type this fit uses so the persisted ModalData
    // carries the type the model was fitted with — making calcFit authoritative
    // keeps it consistent regardless of caller wiring.
    modal.setMt(mt);
    const cur = modal.get();

    // Subset an all-columns spec to a target's STORED fitted channels (null =
    // the full set). Returns null when a stored channel's column is gone.
    const specForTarget = (ws: WorkingSet, want: number[] | null): FitSpec | null => {
      const s = tfSpecOf(ws);
      if (!s || !want) return s;
      const cols: number[] = [];
      const chans: number[] = [];
      for (let k = 0; k < s.chans.length; k++) {
        if (want.includes(s.chans[k])) { cols.push(s.cols[k]); chans.push(s.chans[k]); }
      }
      if (chans.length !== want.length) return null;
      return { ...s, cols, chans, nCols: cols.length, allCols: cols.length === s.cols.length };
    };

    // Resolve the ordered set list this call operates on.
    let specs: FitSpec[];
    if (action !== 'fit' && cur.targets.length > 0) {
      // Reuse the model's EXACT composition — sets AND fitted channels — so
      // the shared-pole model stays coherent across reject / delete / refine
      // / recon (the model's columns are fixed; visibility changes since the
      // fit must NOT reshuffle them). No-op (rather than a partial/
      // mismatched model) if any spanned set's TF or channel is missing.
      specs = [];
      for (const t of cur.targets) {
        const ws = working.find((w) => w.setId === t.setId);
        const spec = ws ? specForTarget(ws, t.chans ?? null) : null;
        if (spec) specs.push(spec);
      }
      if (specs.length !== cur.targets.length) return Promise.resolve();
    } else if (target === 'shared') {
      // Round-7h: a FIT uses the lines left VISIBLE (legend/tray) — the
      // legend is the fit's line selector. Hidden-line sets drop out.
      specs = working.map((w) => tfSpecOf(w, true)).filter((s): s is FitSpec => s !== null);
    } else {
      const ws = fitSet(target);
      const spec = ws ? tfSpecOf(ws, true) : null;
      specs = spec ? [spec] : [];
    }
    if (specs.length === 0) {
      if (action === 'fit') {
        toasts?.push('Nothing to fit — every TF line is hidden. Re-enable lines in the legend or tray.',
          { level: 'info' });
      }
      return Promise.resolve();
    }

    const contexts = specs.map((s) => ({
      setId: s.ws.setId, chIn: s.chIn, nChannels: s.nChannels, nCols: s.nCols,
      // null = the full set (the compact legacy representation, and what a
      // restored-from-file model reports).
      chans: s.allCols ? null : s.chans,
    }));
    // Accumulate the stored M only when THIS call's composition matches the
    // stored model's (same sets, same order, same fitted channels); else
    // start a fresh model — mixed column geometries cannot be merged.
    const chansMatch = (t: { chans?: number[] | null }, s: FitSpec): boolean => {
      const stored = t.chans ?? null;
      if (stored === null) return s.allCols;
      return stored.length === s.chans.length && stored.every((c, k) => c === s.chans[k]);
    };
    const sameComposition = cur.targets.length === specs.length
      && cur.targets.every((t, i) => t.setId === specs[i].ws.setId && chansMatch(t, specs[i]));

    const my = bump('fit');
    if (DESTRUCTIVE.has(action)) modal.pushUndo();       // undo / auto-revert snapshot
    return guarded('fit', async () => {
      const payload: Record<string, unknown> = {
        measurement_type: mt, action, n_modes: nModes,
      };
      if (specs.length === 1) {
        // Single set: top-level payload (backward-compatible shape).
        const s = specs[0];
        payload.freq_axis = s.slice.axis;
        payload.tf_data = interleaveTf(s.slice, s.cols);
        payload.n_tf = s.nCols;
        payload.n_channels = s.nChannels;
        payload.fs = s.ws.fs;
        // Omit ch_in for an orphan TF (chIn null): a JS null marshals as a
        // truthy JsNull proxy, breaking the engine's `is None` default; leaving
        // the key off lets Python's ch_in=None default apply (round-6 bug 1).
        if (s.chIn !== null) payload.ch_in = s.chIn;
      } else {
        // Shared-pole joint fit: a LIST of per-set TF payloads (item 7). ch_in
        // is bookkeeping only (the glue never re-drops an input) so a null is
        // harmless inside the nested object — the glue ignores it.
        payload.sets = specs.map((s) => ({
          freq_axis: s.slice.axis, tf_data: interleaveTf(s.slice, s.cols),
          n_tf: s.nCols, ch_in: s.chIn, n_channels: s.nChannels, fs: s.ws.fs,
        }));
      }
      const M = sameComposition ? modal.get().matrix : null;
      if (M) payload.M = M;
      if (freqRange && action !== 'refine') payload.freq_range = freqRange;
      if (action === 'delete_one' && index !== undefined) payload.index = index;
      if (action === 'recon') payload.mute = modal.mutedIndices();
      // Pre-refine poles for the divergence flag (round-7f): the auto-revert
      // below only catches a WORSE residual — a refine can "improve" the
      // cost while a mode flies far from its fitted peak (seen on the JW
      // instrument files). Snapshot BEFORE the engine call.
      const preFn = action === 'refine' ? modal.get().modes.map((m) => m.fn) : [];
      const res = await engine.enqueue('calc_fit', payload);
      if (stale('fit', my)) return;                      // a newer fit won
      modal.applyResult(res, contexts);
      // Phase-significance flag (round-7f; JW-logger heritage — the original
      // printed every fitted mode's phase): a fresh fit whose modal phase
      // lands far from a REAL mode's 0/180° usually means the TF type
      // (acc/vel/dsp) is wrong for the data. The chip marks the mode ⚠; this
      // toast explains it once per fit.
      if (action === 'fit') {
        const worst = modal.get().modes.reduce((a, m) => Math.max(a, m.phaseDevDeg), 0);
        if (worst > PHASE_DEV_WARN_DEG) {
          toasts?.push(
            `Fitted modal phase is ${Math.round(worst)}° from real (0/180°) — check the TF type (Acceleration / Velocity / Displacement).`,
            { level: 'info' });
        }
      }
      // Refine auto-revert: if the engine reports it did not improve / converge,
      // restore the pre-refine model and explain (round-4 item 10).
      if (action === 'refine') {
        const converged = mval(res, 'converged');
        if (converged === false) {
          modal.undo();
          toasts?.push('Refine did not improve the fit — reverted to the previous modes.',
            { level: 'info' });
        } else {
          const before = Number(mval(res, 'cost_before'));
          const after = Number(mval(res, 'cost_after'));
          if (Number.isFinite(before) && Number.isFinite(after) && before > 0) {
            const pct = Math.max(0, Math.round((1 - after / before) * 100));
            toasts?.push(`Refined modes — residual down ${pct}%.`, { level: 'success' });
          }
          // Divergence flag (round-7f): a numerically-improved refine that
          // dragged a mode >10% (and >2 Hz) from its pre-refine frequency is
          // suspect — warn and offer the one-level Undo, don't silently trust.
          const moved = modal.get().modes
            .map((m, i) => ({ from: preFn[i], to: m.fn }))
            .filter((p) => Number.isFinite(p.from)
              && Math.abs(p.to - p.from) > Math.max(2, 0.1 * p.from));
          if (moved.length > 0) {
            const eg = moved[0];
            toasts?.push(
              `Refine moved ${moved.length} mode(s) far from their fitted peaks `
              + `(e.g. ${eg.from.toFixed(1)} → ${eg.to.toFixed(1)} Hz) — inspect the fit lines before trusting it.`,
              { level: 'info', actions: [{ label: 'Undo', run: () => modal.undo() }] });
          }
        }
      }
    });
  }

  /**
   * What a Fit would use RIGHT NOW for `target` (round-7h): visible
   * (fittable) TF lines vs total TF lines across the spanned set(s). Pure
   * read for the Fit card's "N of M lines" hint; recompute on legend/tray
   * tri-state changes (the caller subscribes to `selection.legendEntries`).
   */
  function fitLineSummary(target: FitTargetSel): { fitted: number; total: number } {
    let pool: WorkingSet[];
    if (target === 'shared') pool = working;
    else {
      const ws = fitSet(target);
      pool = ws ? [ws] : [];
    }
    let fitted = 0;
    let total = 0;
    for (const ws of pool) {
      const all = tfSpecOf(ws);
      if (!all) continue;
      total += all.nCols;
      const vis = tfSpecOf(ws, true);
      fitted += vis ? vis.nCols : 0;
    }
    return { fitted, total };
  }

  /** Resolve the damping target set (both damping ops share this). */
  function dampingWs(target: AnalysisTarget): WorkingSet | undefined {
    const ws = target === 'all'
      ? working.find((w) => hasTimeData(w.time))
      : working.find((w) => w.setId === target);
    // Same time-less guard as the sonogram (round-6 item 2): damping is read
    // from the decay of the time signal, so a time-less set cannot fit.
    if (ws && !hasTimeData(ws.time)) throw new Error(sonoNoTimeMessage(nameOf(ws.setId)));
    return ws;
  }

  /**
   * Sonogram-derived modal damping for one channel of the target set (Task
   * A1; round-7 interactive rebuild). Returns fn/Qn PLUS the decoded
   * peak-picking context and per-mode decay-fit arrays the DampingPanel
   * draws (`DampingPeaksResult`) — nothing is stored in `derived` (a
   * one-shot readout, not a plotted slice). `'all'` uses the first working
   * set. `opts.startTime` (s) and `opts.threshold` (normalised 0..1) are the
   * panel's knobs; null/omitted = the engine's automatic choices (which the
   * result echoes back as `startTime`/`threshold`).
   */
  async function calcDamping(
    target: AnalysisTarget, ch: number, nFft: number,
    opts: { startTime?: number | null; threshold?: number | null } = {},
  ): Promise<DampingPeaksResult> {
    // Idempotent lazy boot (mirrors guarded()): damping can be the FIRST
    // compute of a session, and enqueue() from 'idle' only QUEUES — without
    // this kick the op would park forever (EngineProbe's boot is ?engine=1
    // e2e-gated, so nothing else starts the engine).
    engine.boot();
    const empty = new Float64Array(0);
    const ws = dampingWs(target);
    if (!ws) {
      return {
        fn: empty, Qn: empty, fits: [], startTime: null, threshold: null,
        sliceFreq: empty, sliceMag: empty, peaksFreq: empty, peaksMag: empty,
      };
    }
    const { axis, data, nCh } = timePayload(ws.time);
    const { method, voicesPerOctave, w0 } = sonoSettings(ws.setId);
    // Auto knobs are OMITTED (not sent as JS null — see calcFit note) so the
    // engine infers the free-decay start / uses its automatic threshold.
    // `method` selects the STFT or CWT damping path; the CWT params are
    // ignored by the engine for 'stft'.
    const payload: Record<string, unknown> = {
      time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
      ch, nperseg: nFft,
      method, voices_per_octave: voicesPerOctave, w0,
    };
    if (opts.startTime !== null && opts.startTime !== undefined) payload.start_time = opts.startTime;
    if (opts.threshold !== null && opts.threshold !== undefined) payload.peak_threshold = opts.threshold;
    const res = await engine.enqueue('calc_damping', payload);
    const fitsRaw = mval(res, 'fits');
    const fits: DampingModeFit[] = (fitsRaw ? Array.from(fitsRaw as ArrayLike<unknown>) : [])
      .map((m) => ({
        tFit: axisData(mval(m, 't_fit')),
        realFit: axisData(mval(m, 'real_fit')),
        realData: axisData(mval(m, 'real_data')),
        fPeak: Number(mval(m, 'f_peak')),
        Qn: Number(mval(m, 'Qn')),
      }));
    // The picking context is absent only on a pre-round-7 engine wheel (the
    // panel then shows its stale-engine note instead of the spectrum).
    const thr = mval(res, 'threshold');
    return {
      fn: axisData(mval(res, 'fn')), Qn: axisData(mval(res, 'Qn')), fits,
      startTime: thr === undefined ? null : Number(mval(res, 'start_time')),
      threshold: thr === undefined ? null : Number(thr),
      sliceFreq: thr === undefined ? empty : axisData(mval(res, 'slice_freq')),
      sliceMag: thr === undefined ? empty : axisData(mval(res, 'slice_mag')),
      peaksFreq: thr === undefined ? empty : axisData(mval(res, 'peaks_freq')),
      peaksMag: thr === undefined ? empty : axisData(mval(res, 'peaks_mag')),
    };
  }

  /**
   * Band-centred decay metrics via the Schroeder integral (round-7 'bands'
   * damping mode): zero-phase band-pass ladder → per-band EDC → EDT / T20 /
   * T30 / T60 (NaN = insufficient decay range) + band-centred Qn. One-shot
   * readout like `calcDamping`; nothing lands in `derived`.
   */
  async function calcDampingBands(
    target: AnalysisTarget, ch: number,
    opts: { ladder: BandLadder; startTime?: number | null } = { ladder: 'octave' },
  ): Promise<DampingBandsResult | null> {
    engine.boot();               // idempotent; see calcDamping
    const ws = dampingWs(target);
    if (!ws) return null;
    const { axis, data, nCh } = timePayload(ws.time);
    const payload: Record<string, unknown> = {
      time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
      ch, bands: opts.ladder,
    };
    if (opts.startTime !== null && opts.startTime !== undefined) payload.start_time = opts.startTime;
    const res = await engine.enqueue('calc_damping_bands', payload);
    const bandsRaw = mval(res, 'band_data');
    const bandData: DampingBand[] = (bandsRaw ? Array.from(bandsRaw as ArrayLike<unknown>) : [])
      .map((b) => {
        const fitT = mval(b, 'fit_t');
        return {
          fc: Number(mval(b, 'fc')), fLo: Number(mval(b, 'f_lo')), fHi: Number(mval(b, 'f_hi')),
          edcT: axisData(mval(b, 'edc_t')), edcDb: axisData(mval(b, 'edc_db')),
          fitT: fitT === undefined ? null : axisData(fitT),
          fitDb: fitT === undefined ? null : axisData(mval(b, 'fit_db')),
        };
      });
    return {
      bands: String(mval(res, 'bands')) as BandLadder,
      startTime: Number(mval(res, 'start_time')),
      fc: axisData(mval(res, 'fc')),
      fLo: axisData(mval(res, 'f_lo')), fHi: axisData(mval(res, 'f_hi')),
      EDT: axisData(mval(res, 'EDT')), T20: axisData(mval(res, 'T20')),
      T30: axisData(mval(res, 'T30')), T60: axisData(mval(res, 'T60')),
      Qn: axisData(mval(res, 'Qn')),
      bandData,
    };
  }

  /**
   * Raw decoded per-set arrays for the CSV builder (Wave-A shared spine —
   * Agent 2 owns the CSV/preview UI). PURE accessor, no engine call: reads
   * the decoded `derived` slices and splits each into per-channel columns.
   * `'time'` returns real `Float64Array` columns; `'freq'`/`'tf'` return
   * complex `{re, im}` columns. Sets without the requested kind are skipped.
   */
  function exportArrays(kind: 'time' | 'freq' | 'tf'): ExportSetArrays[] {
    const d = get(derived);
    const out: ExportSetArrays[] = [];
    for (const ws of working) {
      const slice = kind === 'time' ? d[ws.setId]?.time
        : kind === 'freq' ? d[ws.setId]?.freq
          : d[ws.setId]?.tf;
      if (!slice) continue;
      const { axis, data } = slice;
      const rows = axis.length;
      const cols = data.shape[1] ?? 1;
      if (kind === 'time') {
        const columns: Float64Array[] = [];
        for (let c = 0; c < cols; c++) {
          const col = new Float64Array(rows);
          for (let r = 0; r < rows; r++) col[r] = data.re[r * cols + c];
          columns.push(col);
        }
        out.push({ setId: ws.setId, axis, columns });
      } else {
        const columns: { re: Float64Array; im: Float64Array }[] = [];
        for (let c = 0; c < cols; c++) {
          const cre = new Float64Array(rows), cim = new Float64Array(rows);
          for (let r = 0; r < rows; r++) {
            const idx = r * cols + c;
            cre[r] = data.re[idx]; cim[r] = data.im ? data.im[idx] : 0;
          }
          columns.push({ re: cre, im: cim });
        }
        out.push({ setId: ws.setId, axis, columns });
      }
    }
    return out;
  }

  /**
   * Build a MATLAB `.mat` of every computed kind and return its bytes
   * (Wave-A shared spine — Agent 2's Export card calls this). Sends each
   * set's raw decoded row-major buffers (the `DecodedArray.re`/`im` are
   * already row-major (rows, cols)) to the `export_mat` glue op, which
   * interpolates onto a per-kind common axis, column-concatenates, and
   * `scipy.io.savemat`s. RAW values (no cal factors); no coherence.
   */
  async function exportMat(): Promise<Uint8Array> {
    const d = get(derived);
    const time_sets: unknown[] = [];
    const freq_sets: unknown[] = [];
    const tf_sets: unknown[] = [];
    for (const ws of working) {
      const t = d[ws.setId]?.time;
      if (t) time_sets.push({ axis: t.axis, data: t.data.re, cols: t.data.shape[1] ?? 1 });
      // Complex kinds always carry `im`; include it only when present (never
      // send a JS null — the engine treats a missing key as zero imag).
      const f = d[ws.setId]?.freq;
      if (f) freq_sets.push({ axis: f.axis, re: f.data.re, ...(f.data.im ? { im: f.data.im } : {}), cols: f.data.shape[1] ?? 1 });
      const tf = d[ws.setId]?.tf;
      if (tf) tf_sets.push({ axis: tf.axis, re: tf.data.re, ...(tf.data.im ? { im: tf.data.im } : {}), cols: tf.data.shape[1] ?? 1 });
    }
    engine.boot();
    const res = await engine.enqueue('export_mat', { time_sets, freq_sets, tf_sets });
    const mat = mval(res, 'mat');
    return mat instanceof Uint8Array ? mat : Uint8Array.from(mat as ArrayLike<number>);
  }

  return {
    dataset, derived, computeErrors, busy, modal,
    loadDataset, addRecordedSet, stampUiState,
    calcFft, calcPsd, calcTf, calcSono, cleanImpulse, cleanedSets, hasComputed,
    calcFit, fitLineSummary, calcDamping, calcDampingBands, exportArrays, exportMat, setCsdPair,
    getCalibration, setCalFactors,
    /** Scaling tools (round-6 Qt-parity): x(iω) display power + Best Match. */
    getIwPower, setIwPower, calcBestMatch,
    /** Modal-fit pseudo-set (round-5 item 13): tray-card delete-with-undo.
     *  (Line visibility is the normal legend/tray tri-state; WHICH recon the
     *  lines draw is the modal store's `reconMode` — round-7 item 6.) */
    clearFit,
    /** The modal-fit pseudo-set's selection id store (null when none), for App. */
    fitSetId: { subscribe: fitSetIdW.subscribe },
    /**
     * Source-set metadata for cards (setId → fs / duration / channels /
     * whether it carries time data). `hasTime` is false for round-5's orphan
     * TF/spectrum sets (no `time_data`), so the Sono card lists only
     * time-bearing sets as sonogram targets (round-6 items 2/3).
     */
    workingSets: () => working.map(w => ({
      setId: w.setId, fs: w.fs, durationS: w.durationS, nChannels: w.nChannels,
      hasTime: hasTimeData(w.time),
    })),
  };
}

/** Extract a marshalled 1-D axis's data as a fresh Float64Array. */
function axisData(v: unknown): Float64Array {
  const d = mval(v, 'data');
  return d instanceof Float64Array ? d : Float64Array.from((d as number[]) ?? []);
}

/**
 * Build a SetArrays.tf slice from a calc_tf-shaped worker result. `chIn`
 * (the input channel the TF was computed with) and `nChannels` (the
 * source channel count) are carried onto the slice so `buildPlotModel`
 * can remap each visible source channel to its output column — `tf_data`
 * drops the input channel, so it is `(Nf, nChannels − 1)` (Task R4).
 */
function tfFromResult(
  res: unknown, axis: Float64Array, chIn: number, nChannels?: number,
): NonNullable<SetArrays['tf']> {
  const coh = mval(res, 'coherence');
  return {
    axis,
    data: decodeArray(asMarshalled(mval(res, 'tf_data'))),
    coherence: coh == null ? undefined : decodeArray(asMarshalled(coh)),
    chIn, nChannels,
  };
}

/**
 * User-facing message for a TF requested on a set with no output channel.
 * A transfer function maps one INPUT channel to the remaining OUTPUT
 * channels, so a single-channel set has nothing to estimate. Surfaced via
 * `computeErrors.tf` (the TF card + plot error banners) rather than crashing
 * or drawing a silent, empty TF (round-2 feedback).
 */
function tfNoOutputMessage(names: string[]): string {
  const base = 'Transfer function needs at least one output channel besides the input';
  if (names.length === 0) return `${base}.`;
  if (names.length === 1) return `${base} — set “${names[0]}” has only one channel.`;
  return `${base} — single-channel sets: ${names.join(', ')}.`;
}

/**
 * User-facing message for a sonogram / damping fit requested on a set with no
 * time-domain signal (round-6 item 2). Orphan TF / spectrum sets (a TF-only
 * `.mat`/`.dvma` load) carry no `time_data`, so there is nothing to transform.
 * Surfaced via `computeErrors.sono` (SonoCard + the under-plot banner) instead
 * of the opaque "Cannot read properties of undefined" the missing array threw.
 */
function sonoNoTimeMessage(name: string): string {
  return `Sonogram needs a time signal — “${name}” has no time data `
    + '(it is a loaded spectrum or transfer function). Choose a recorded or time-bearing set.';
}

/**
 * User-facing message for one or more sets whose PSD could not be computed
 * (Round-3 item 1). Each `entry` is already `"<set name>: <reason>"`; the
 * successful sets have already rendered, so this names only the failures.
 * Surfaced via `computeErrors.psd`.
 */
function psdFailedMessage(entries: string[]): string {
  if (entries.length === 1) return `PSD could not be computed — ${entries[0]}`;
  return `PSD could not be computed for some sets — ${entries.join('; ')}`;
}

export type Actions = ReturnType<typeof createActions>;

/** Re-export resolution helpers so cards import from one analysis module. */
export { fromNFrames, fromNFft };
