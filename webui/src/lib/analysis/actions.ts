/**
 * Analysis orchestration (Task 12). The bridge between the loaded
 * dataset, the selection/view stores, and the pyodide worker: load a
 * dataset → populate the selection tray, then run FFT / PSD / TF / sono
 * / clean-impulse ops by marshalling each source TimeData set to the
 * worker and decoding the result into per-set `SetArrays` for
 * `buildPlotModel`.
 *
 * MATHS NEVER RUNS HERE — every numeric op is a worker call into
 * pydvma.engine (spec §11); this module only reshapes flat JS buffers in and
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
 * Save (derived-data round): `materializeDerived` turns the computed FFT / TF
 * views into real `FreqData` / `TfData` items inside the document, linked and
 * compute-chain-signed, replaced by lineage on a re-save. Explicit Save only —
 * see its doc for what is deliberately NOT materialised.
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
import type { DataKind, DvmaDataset, DvmaItem, DvmaItemUi } from '../model/dataset';
import { itemChannels, setItemMeta } from '../model/dataset';
import type { NpyArray } from '../codec/npy';
import { signatureOfSamples } from '../codec/signature';
import type { EngineStore } from '../stores/engine';
import { isEngineStopped, ENGINE_STOPPED_MESSAGE, consumeEngineStopNotice } from '../stores/engine';
import type { Selection, SetRecord, TriState } from '../stores/selection';
import type { AnalysisSettings, AnalysisTarget } from '../stores/analysisSettings';
import { autoVoicesForW0, defaults, type PerSetSettings } from '../stores/analysisSettings';
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
type Kind = 'fft' | 'psd' | 'tf' | 'sono' | 'clean' | 'resample' | 'fit';

/** A fresh, all-clear per-kind error record. */
const emptyErrors = (): Record<Kind, string> =>
  ({ fft: '', psd: '', tf: '', sono: '', clean: '', resample: '', fit: '' });

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

/**
 * A marshalled SCALAR as a number — `null`/`undefined` decode to NaN, never 0.
 *
 * The native `/engine` host's codec cannot put NaN/±Infinity in JSON, so a
 * non-finite scalar crosses the wire as `null` (`pydvma/engine_host.py`
 * `encode_frame`; array VALUES are unaffected, being raw IEEE-754 blobs).
 * `Number(null)` is 0, so a bare `Number(mval(…))` would render a degenerate
 * mode as a plausible-looking `Qn = 0` on the native host where pyodide shows
 * NaN — a wrong NUMBER rather than a visible failure. Use this at EVERY
 * scalar decode site.
 *
 * What that buys is agreement on NOT-FINITE, not on the value: the wire maps
 * NaN and ±Infinity alike to `null`, so a scalar that is `Infinity` under
 * pyodide arrives as NaN from the native host. Every consumer here already
 * treats these as "no usable number" (`Number.isFinite` guards, NaN-gapped
 * plot lines), so the distinction does not reach the user — but do not read a
 * decoded NaN as proof the engine produced one.
 */
function num(v: unknown): number {
  return v == null ? NaN : Number(v);
}

/** Coerce a worker return value (object or Map) into a MarshalledArray. */
function asMarshalled(v: unknown): MarshalledArray {
  return {
    shape: (mval(v, 'shape') as number[]) ?? [],
    data: mval(v, 'data') as Float64Array,
    complex: !!mval(v, 'complex'),
  };
}

/** A marshalled array's buffer as a Float64Array (copied only when needed). */
function toF64(d: Float64Array | number[]): Float64Array {
  return d instanceof Float64Array ? d : Float64Array.from(d);
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
 * Re-interleave a decoded array into the stored complex `NpyArray`
 * convention (`[re, im, re, im, …]`, `isComplex: true`) — the exact inverse
 * of {@link decodeArray}, and the form `addBlaSets` already writes. A decoded
 * REAL array (no `im`) contributes zero imaginary parts, so the stored kind
 * is complex either way: `container.py` reads `freq_data` / `tf_data` back
 * into complex numpy arrays. The buffer is always freshly allocated, so the
 * item owns it and a later recompute of the derived slice cannot alias it.
 */
function complexNpy(a: DecodedArray): NpyArray {
  const n = a.re.length;
  const data = new Float64Array(n * 2);
  for (let i = 0; i < n; i++) {
    data[2 * i] = a.re[i];
    data[2 * i + 1] = a.im ? a.im[i] : 0;
  }
  return { shape: a.shape.slice(), data, isComplex: true };
}

/** A decoded REAL array as a stored `NpyArray` (copied — the item owns it). */
function realNpy(a: DecodedArray): NpyArray {
  return { shape: a.shape.slice(), data: Float64Array.from(a.re), isComplex: false };
}

/** A 1-D axis as a stored `NpyArray` (copied — the item owns it). */
function axisNpy(axis: Float64Array): NpyArray {
  return { shape: [axis.length], data: Float64Array.from(axis), isComplex: false };
}

/**
 * pydvma's `timestring` spelling of a moment — `YYYY-MM-DD HH:MM:SS` in
 * LOCAL time, matching what the acquisition paths write and the tray shows.
 */
function timestringOf(now: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} `
    + `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

/**
 * A fresh RFC-4122 v4 id string, for minting the `unique_id` a browser
 * capture never had (pydvma's Python side sets one in every `TimeData`
 * constructor; `recordingToItem` does not). Written untagged, which
 * `container.py`'s reader accepts as a plain string — and the derived items'
 * `id_link` then matches it exactly, which is what makes the lineage
 * survive a save/reload.
 *
 * `crypto.randomUUID` is unavailable outside a secure context (a serve
 * reached over plain http at a LAN address, say), so a `getRandomValues`
 * fallback formats the same v4 shape; the last resort is `Math.random`,
 * which is fine here — this is a document-local key, never a secret.
 */
function newUniqueId(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c && typeof c.getRandomValues === 'function') c.getRandomValues(bytes);
  else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;               // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80;               // variant 1
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-`
    + `${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * Derived-view slice(s) a loaded non-TimeData item contributes, so its view
 * shows on load WITHOUT a recompute (round-4 bug 3: a legacy `.npy` that
 * already carried a TF loaded the time series but never the TF). Returns a
 * partial `SetArrays` to merge onto the item's source set, or `null` for
 * kinds we don't restore. `srcChannels` is the source set's channel count.
 *
 * Restored: `FreqData → freq` (Frequency/FFT view); `TfData → tf` (TF view,
 * with the out/in remap fields, PLUS the Schoukens BLA σ_NL/σ_n pair when the
 * item carries `bla_sigma_nl`/`bla_sigma_n` — a saved-then-reopened BLA set
 * is a plain `TfData`, see `addBlaSets`, so its σ overlay must round-trip
 * the same way `coherence` does); `CrossSpecData → csd` (coherence). NOT
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
          // Schoukens BLA σ pair (Task 9 reload gap): a BLA set IS a TfData
          // (see `addBlaSets`), so a saved-then-reopened one carries
          // `bla_sigma_nl`/`bla_sigma_n` beside `tf_data` — restore them the
          // same way as every other optional array here (`coherence` above)
          // so the σ overlay survives a save/reload round-trip.
          sigmaNl: A.bla_sigma_nl ? decodeNpy(A.bla_sigma_nl) : undefined,
          sigmaN: A.bla_sigma_n ? decodeNpy(A.bla_sigma_n) : undefined,
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
 * Whether `view` currently has anything plottable in `map` — the "was this
 * view empty before?" test behind the P5 auto-scaling rules. Shares
 * `populatedViews`' definition of populated (frequency counts FFT / PSD /
 * coherence alike) so the two can never drift apart.
 */
function viewPopulated(map: DerivedMap, view: ViewId): boolean {
  return populatedViews(map).includes(view);
}

/**
 * How the actions layer tells the VIEW layer that a plot's contents changed
 * underneath it, so the axes can re-fit (round-11 P5: "when data is added to a
 * view then the view — at least the y-range — should be auto-ed").
 *
 * Injected rather than imported: actions has no view-state dependency by
 * design (it is unit-tested with a bare selection + engine), and App owns the
 * single `viewState` instance. Both callbacks are advisory — an actions
 * instance created without a notifier behaves exactly as before.
 */
export interface ViewNotifier {
  /**
   * New LINES landed in `view`. `viewWasEmpty` is true when the view held
   * nothing plottable before the operation, which is what licenses resetting
   * the x window too (any x range on an empty view is a leftover); otherwise
   * only y should relax, so the user's navigation survives.
   *
   * Fired for genuinely NEW lines only — a capture, a load/append, a set's
   * FIRST result for that view, a BLA run. A recompute in place (Clean
   * Impulse, a settings change, a resample) deliberately does NOT fire: the
   * user is looking at a window they chose, and the numbers only moved a
   * little.
   */
  linesAdded(view: ViewId, info: { viewWasEmpty: boolean }): void;
  /**
   * The UNITS (or the quantity) plotted on these views changed — a
   * calibration, an x(iω) display power, an FFT↔PSD↔CSD switch. The data are
   * the same lines at a different scale, so only y should relax; the x window
   * still means what it did.
   */
  unitsChanged(views: ViewId[]): void;
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
 *
 * `notify` (round-11 P5, optional) receives the axis-relevant events — new
 * lines in a view, a units change — so App can relax those views' axes back
 * to auto. See `ViewNotifier`.
 */
export function createActions(engine: EngineStore, selection: Selection, settings?: AnalysisSettings, modal?: ModalStore, toasts?: Toasts, notify?: ViewNotifier) {
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

  /** The two derived kinds `materializeDerived` writes into the document. */
  type DerivedKind = 'freq' | 'tf';
  /** Lineage key for one set's derived item of one kind. */
  const lineageKey = (setId: number, kind: DerivedKind) => `${setId}:${kind}`;
  /**
   * REPLACE-BY-LINEAGE index: the `FreqData` / `TfData` item in the document
   * that stands for one set's view of one kind, so a second Save updates the
   * item it wrote last time instead of piling up a duplicate. Populated both
   * by `materializeDerived` (items it authors) and by `loadDataset` pass 2
   * (items a file already carried — a loaded-then-recomputed-then-saved
   * result therefore REPLACES the file's own item rather than joining it).
   *
   * Per ACTIONS INSTANCE, not per module: two instances (the app's and a
   * test's) own different documents, and a shared map would cross-link them.
   * Cleared by a fresh (non-append) load; an append keeps what is there and
   * registers the incoming file's items on top. A file carrying SEVERAL
   * derived items of one kind for one source (Python can write three FFTs of
   * one measurement) keeps the LAST — the same one whose slice the view
   * shows, so what a re-save replaces is always what is on screen.
   */
  const materializedItems = new Map<string, DvmaItem>();
  /**
   * Which `${setId}:${kind}` slices THIS SESSION computed. Materialisation
   * writes only these: a slice that merely came off disk is already backed by
   * its own item, whose stored provenance (the settings that really produced
   * it, and its signature — possibly a BROKEN one this app is meant to flag)
   * must not be overwritten with this session's settings on a Save the user
   * made for some unrelated reason.
   */
  const computedThisSession = new Set<string>();
  /** Record that a calc produced `kind` for `setId` (see the set's doc). */
  const markComputed = (setId: number, kind: DerivedKind) =>
    computedThisSession.add(lineageKey(setId, kind));

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
  const seqs: Record<Kind, number> = { fft: 0, psd: 0, tf: 0, sono: 0, clean: 0, resample: 0, fit: 0 };
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
      if (isEngineStopped(e)) {
        // The user pressed Stop: every queued calc rejects with this, so the
        // cards' quiet notes (keyed on the exact message) do the talking and
        // the notice gate keeps it to ONE info toast, not one per calc.
        setError(kind, ENGINE_STOPPED_MESSAGE);
        if (consumeEngineStopNotice()) {
          toasts?.push('Calculation stopped — restarting the engine.', {
            level: 'info', timeout: 4000,
          });
        }
      } else {
        setError(kind, e instanceof Error ? e.message : String(e));
      }
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
   *
   * `opts.append` (round-10, JW's feedback — the old logger's
   * "Add on load"): when data is ALREADY loaded, merge this file's items
   * into the existing dataset instead of replacing it — the new sets
   * appear alongside the current ones in the tray/legend, and Save
   * Dataset writes the composite. Nothing is reset; the current modal
   * fit survives, and any ModalData carried BY the appended file is
   * deliberately ignored (one live model per session — an appended
   * file's fit must not clobber it). With nothing loaded yet, append
   * degrades to the normal full load.
   */
  function loadDataset(ds: DvmaDataset, opts: { append?: boolean } = {}): ViewId[] {
    const append = !!opts.append && get(dataset) !== null && working.length > 0;
    // Which views already held something, BEFORE the merge — a fresh (non-
    // append) load clears everything, so every view it fills counts as
    // previously empty and gets both axes back to auto (P5).
    const before = append ? get(derived) : {};
    if (append) {
      // Merge into the EXISTING dataset object so autosave/save see one doc.
      const base = get(dataset)!;
      base.items.push(...ds.items);
      dataset.set(base);
    } else {
      dataset.set(ds);
      derived.set({});
      computeErrors.set(emptyErrors());   // fresh dataset clears every kind's error
      modal?.reset();                     // drop any prior dataset's modal fit
      cleanCache.clear();                 // raw/cleaned stashes belong to the old sets
      cleanedSets.set({});
      resampleUndo.clear();               // stashes belong to the old sets
      working = [];
      materializedItems.clear();          // fresh document ⇒ fresh lineage
      computedThisSession.clear();
    }
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
          if (ui.analysis.sono) {
            const s = ui.analysis.sono;
            // Pre-round-9 files carry voicesPerOctave with no voicesAuto
            // flag: a saved density that ISN'T what auto would resolve was a
            // hand-picked value — pin it, so the next w0 tweak can't clobber
            // it with the auto-follow.
            const legacyPinned = s.voicesAuto === undefined
              && s.voicesPerOctave !== undefined
              && s.voicesPerOctave !== autoVoicesForW0(s.w0 ?? defaults().sono.w0);
            settings.patch(setId, 'sono', legacyPinned ? { ...s, voicesAuto: false } : s);
          }
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
        // Adopt the item for replace-by-lineage: a later Save that
        // re-materialises this set's FFT/TF updates THIS item rather than
        // adding a second one beside it (see `materializedItems`).
        if (item.kind === 'FreqData') materializedItems.set(lineageKey(linkedSet, 'freq'), item);
        else if (item.kind === 'TfData') materializedItems.set(lineageKey(linkedSet, 'tf'), item);
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

    if (append) derived.update((d) => ({ ...d, ...seed }));
    else derived.set(seed);

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
    if (modal && !append) {
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

    // The incoming file's lines are now in these views: re-fit each one's y
    // (and x where the view was empty until now) — P5's data-add rule.
    const filled = populatedViews(seed);
    for (const v of filled) notify?.linesAdded(v, { viewWasEmpty: !viewPopulated(before, v) });
    return filled;
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
          || sono.voicesAuto !== d.sono.voicesAuto
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
   * The lineage id of a set's source measurement, minting one if it has
   * none. pydvma's Python `TimeData` always carries a `unique_id`, but the
   * browser capture path (`recordingToItem`) writes none — so a derived
   * item built from a fresh capture would have nothing to link to and would
   * reload as an ORPHAN set beside its own source. Minting one here (through
   * `setItemMeta`, so the tagged write view stays consistent) is what makes
   * `id_link` mean something for browser-acquired data.
   */
  function ensureIdLink(ws: WorkingSet): string {
    const uid = ws.time.meta.unique_id;
    if (typeof uid === 'string' && uid) return uid;
    const minted = newUniqueId();
    setItemMeta(ws.time, 'unique_id', minted);
    return minted;
  }

  /** Compute-chain signature of a set's SOURCE samples (+ its rate). */
  function sourceSignatureOf(ws: WorkingSet): string {
    const td = ws.time.arrays.time_data;
    const flat = td.data instanceof Float64Array
      ? td.data : Float64Array.from(td.data as ArrayLike<number>);
    const nCols = td.shape.length > 1 ? (td.shape[1] ?? 1) : 1;
    return signatureOfSamples(flat, nCols, ws.fs);
  }

  /** `[t_first, t_last]` of a set's time axis — the calc's effective range. */
  function timeRangeOf(ws: WorkingSet): number[] {
    const ax = ws.time.arrays.time_axis?.data;
    return ax && ax.length ? [ax[0], ax[ax.length - 1]] : [0, 0];
  }

  /**
   * Per-output-channel calibration + units for a materialised TF, following
   * `analysis.calculate_tf`'s convention: the OUTPUT channels are every
   * source channel except `chIn`, in ascending order, each carrying the cal
   * RATIO `cal[out]/cal[in]` and the unit `"<out>/<in>"`. Returns `null`s
   * when the geometry does not line up with the stored columns (an
   * 'across' ensemble whose column count came from a different set, say) —
   * an absent field is honest, a mis-indexed one is not.
   */
  function tfCalibration(
    setId: number, chIn: number, nChannels: number, nCols: number,
  ): { factors: number[] | null; units: string[] | null } {
    const cal = getCalibration(setId);
    const outs: number[] = [];
    for (let c = 0; c < nChannels; c++) if (c !== chIn) outs.push(c);
    if (outs.length !== nCols || chIn < 0 || chIn >= cal.factors.length
      || outs.some((c) => c >= cal.factors.length)) {
      return { factors: null, units: null };
    }
    return {
      factors: outs.map((c) => cal.factors[c] / cal.factors[chIn]),
      units: outs.map((c) => `${cal.units[c]}/${cal.units[chIn]}`),
    };
  }

  /**
   * Insert or update the document item that stands for `setId`'s view of
   * `kind` — the replace-by-lineage upsert (see `materializedItems`). An
   * adopted item is mutated IN PLACE (it may already sit anywhere in
   * `ds.items`, and the file's item order should not shuffle on a re-save);
   * a new one is appended and registered. `arrays` is REPLACED wholesale,
   * which is safe only because a σ-bearing BLA `TfData` is never adopted:
   * `analysis.calculate_bla` writes a LIST `id_link` and `addBlaSets` writes
   * `null`, so both land in `loadDataset`'s ORPHAN branch and never enter the
   * lineage map. If that link ever became scalar, a TF recompute + Save would
   * silently delete `bla_sigma_nl` / `bla_sigma_n`. `rawLink` is the source's id_link
   * in its ORIGINAL manifest form — a `{__uuid__}` tag for a python-written
   * source, so python reads a `uuid.UUID` back and it still equals the
   * source's own `unique_id`; a plain string for a browser-minted one.
   */
  function upsertDerivedItem(
    ds: DvmaDataset, setId: number, kind: DerivedKind,
    build: { kind: DataKind; arrays: Record<string, NpyArray>; meta: Record<string, unknown> },
    rawLink: unknown, iso: string,
  ): void {
    const meta = { ...build.meta, timestamp: iso };
    // `timestamp` carries the datetime tag so python decodes a real datetime
    // on load, and `id_link` its original tag (same convention as
    // `upsertModalItem` / `addBlaSets`).
    const metaRaw = { ...meta, timestamp: { __datetime__: iso }, id_link: rawLink };
    const existing = materializedItems.get(lineageKey(setId, kind));
    if (existing && ds.items.includes(existing)) {
      // MERGE the metadata, never replace it: an adopted item may carry
      // manifest keys this builder does not re-emit — python's
      // `flag_modal_TF` / `iw_power_counter`, or any key a newer writer added
      // — and the container round-trip contract is that browser-authored
      // state and unknown keys both SURVIVE a foreign writer.
      existing.arrays = build.arrays;
      existing.meta = { ...existing.meta, ...meta };
      existing.metaRaw = { ...existing.metaRaw, ...metaRaw };
      return;
    }
    const item: DvmaItem = {
      kind: build.kind, arrays: build.arrays, meta, metaRaw, settings: null,
    };
    ds.items.push(item);
    materializedItems.set(lineageKey(setId, kind), item);
  }

  /**
   * Turn this session's COMPUTED analysis views into real items inside the
   * document — Tore's "data with its processing", written on an explicit
   * Save. An FFT becomes a `FreqData`, a transfer function a `TfData` (with
   * its coherence), each `id_link`ed to the measurement it came from, named
   * after the set as it is named right now, and stamped with a
   * `source_signature` (a hash of the SOURCE samples + rate — so a loaded
   * file can tell a chain that is still intact from one whose time data has
   * since been edited) plus `source_settings` (the analysis knobs in force,
   * with a `calc` discriminator mirroring `pydvma.analysis._stamp_source`).
   * Both fields round-trip through `container.py`'s `_OPTIONAL_META`.
   *
   * WHAT IS MATERIALISED — deliberately narrow:
   *   - only the `freq` slice, which is the FFT: `psd` / `csd` live in their
   *     own slices and are a `CrossSpecData`-shaped job, deferred with the
   *     sonogram (the app's sono slice is a single-channel magnitude image,
   *     while `SonoData` wants the full complex cube — an honest one needs a
   *     recompute at save time);
   *   - NOT an 'across'-averaged (ensemble) TF. `calc_tf_averaged` derives one
   *     curve from EVERY working set but hangs it on the first, so the
   *     single-source stamp this function writes would name one member's
   *     id_link and hash one member's samples: an edit to any other member
   *     would leave the chain looking intact, which is precisely the failure
   *     the signature exists to catch. Doing it properly needs the
   *     multi-source signature (python's `source_signature` already accepts a
   *     list) plus a LIST-valued `id_link` — and a list id_link does not seed
   *     onto a set at all today (`loadDataset` pass 2 keys on a single link,
   *     so such a TF reloads as an orphan set the flag could not attach to).
   *     Deferred whole rather than half-stamped;
   *   - only slices THIS SESSION computed. A view that merely came off disk
   *     is already backed by its own item, whose stored provenance is the
   *     truth about how it was made — re-stamping it with this session's
   *     settings would fabricate provenance, and would silently "repair" a
   *     broken chain the app is supposed to be flagging;
   *   - only sets whose source is a real `TimeData`. A BLA result set and an
   *     orphan TF/spectrum load both sit in `working` with a DERIVED item as
   *     their source: their views ARE that item, so materialising them would
   *     clone it. The modal fit persists through `upsertModalItem` and is
   *     untouched here.
   *
   * Re-running is idempotent: each (set, kind) owns ONE item, updated in
   * place. `removeBlaRun` takes a removed set's materialised items out with
   * it (and its undo puts them back under the new set id), so the document
   * never keeps a derived item whose source has gone.
   *
   * A destructive edit — a resample, a Clean Impulse toggle — changes the
   * source samples, so the item already in the document legitimately becomes
   * STALE until the next Save re-materialises it. Task 4's badge firing there
   * is the intended behaviour, not a bug: it is exactly the "the chain no
   * longer holds" state the signature exists to show.
   *
   * Called from the Save handler only. Autosave deliberately does not: once
   * materialised, the items are part of the document and ride subsequent
   * autosaves like any other item.
   */
  function materializeDerived(): void {
    const ds = get(dataset);
    if (!ds) return;
    const d = get(derived);
    const now = new Date();
    const iso = now.toISOString();
    const timestring = timestringOf(now);

    for (const ws of working) {
      if (ws.time.kind !== 'TimeData' || !hasTimeData(ws.time)) continue;
      const slice = d[ws.setId];
      if (!slice) continue;
      const freq = computedThisSession.has(lineageKey(ws.setId, 'freq')) ? slice.freq : undefined;
      const tf = computedThisSession.has(lineageKey(ws.setId, 'tf')) ? slice.tf : undefined;
      if (!freq && !tf) continue;

      const link = ensureIdLink(ws);
      const rawLink = ws.time.metaRaw?.unique_id ?? link;
      const signature = sourceSignatureOf(ws);
      const testName = nameOf(ws.setId);          // read fresh: sets get renamed
      const timeRange = timeRangeOf(ws);

      if (freq) {
        const cal = getCalibration(ws.setId);
        upsertDerivedItem(ds, ws.setId, 'freq', {
          kind: 'FreqData',
          arrays: { freq_axis: axisNpy(freq.axis), freq_data: complexNpy(freq.data) },
          meta: {
            units: cal.units, channel_cal_factors: cal.factors,
            test_name: testName, timestring, id_link: link,
            source_signature: signature,
            source_settings: { calc: 'fft', time_range: timeRange, ...freqSettings(ws.setId) },
          },
        }, rawLink, iso);
      }

      if (tf) {
        const chIn = tf.chIn ?? 0;
        const nCols = tf.data.shape[1] ?? 0;
        const cal = tfCalibration(ws.setId, chIn, tf.nChannels ?? ws.nChannels, nCols);
        const arrays: Record<string, NpyArray> = {
          freq_axis: axisNpy(tf.axis), tf_data: complexNpy(tf.data),
        };
        if (tf.coherence) arrays.tf_coherence = realNpy(tf.coherence);
        upsertDerivedItem(ds, ws.setId, 'tf', {
          kind: 'TfData',
          arrays,
          meta: {
            units: cal.units, channel_cal_factors: cal.factors,
            test_name: testName, timestring, id_link: link,
            source_signature: signature,
            source_settings: { calc: 'tf', time_range: timeRange, ...tfSettings(ws.setId) },
          },
        }, rawLink, iso);
      }
    }
    // No store emission, exactly as `stampUiState`: the items were pushed
    // into the live document object by reference and the caller serializes
    // immediately after. Re-emitting here would schedule an autosave that
    // fires just after the explicit Save cleared the pending one. The
    // consequence is cosmetic and deliberate: the autosave/journal copy lags
    // the materialised items until the NEXT dataset mutation re-emits, while
    // the file the user just saved is complete and correct.
  }

  /**
   * FFT of the targeted set(s), each with ITS OWN window from `settings`,
   * writing decoded freq arrays into `derived`. `target === 'all'` runs
   * every set; a setId runs just that one.
   */
  function calcFft(target: AnalysisTarget = 'all') {
    const my = bump('fft');
    return guarded('fft', async () => {
      // P5 data-add rule: a set's FIRST spectrum is a NEW line in the
      // frequency view (re-fit y); a recompute of one that already exists
      // keeps the range the user is looking at. Emptiness is judged for the
      // whole batch, before any of it lands.
      const wasEmpty = !viewPopulated(get(derived), 'frequency');
      let added = false;
      for (const ws of targeted(target)) {
        const { window } = freqSettings(ws.setId);
        const { axis, data, nCh } = timePayload(ws.time);
        const res = await engine.enqueue('calc_fft', {
          time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
          window: window === 'none' ? null : window,
        });
        if (stale('fft', my)) return;                 // a newer FFT batch won
        if (get(derived)[ws.setId]?.freq === undefined) added = true;
        setDerived(ws.setId, {
          freq: {
            axis: axisData(mval(res, 'freq_axis')),
            data: decodeArray(asMarshalled(mval(res, 'freq_data'))),
          },
        });
        markComputed(ws.setId, 'freq');   // Save may materialise this result
      }
      if (added) notify?.linesAdded('frequency', { viewWasEmpty: wasEmpty });
    });
  }

  /**
   * PSD (+ CSD coherence matrix) of the targeted set(s), each at ITS OWN
   * window + n_frames from `settings`. `target === 'all'` runs every set.
   *
   * PARTIAL FAILURE (Round-3 item 1): each set is computed independently in
   * its own try/catch, so a set the engine CAN'T handle (e.g. a resolution
   * too fine for the 32-bit browser engine → pydvma.engine raises a clear message)
   * does not stop the others. Sets that succeed render; the failing sets are
   * collected into ONE named `psd` error naming each set and its reason.
   */
  function calcPsd(target: AnalysisTarget = 'all') {
    const my = bump('psd');
    return guarded('psd', async () => {
      const failed: string[] = [];
      // P5 data-add rule — see `calcFft` (PSD and CSD both land in the
      // frequency view, and one op fills both slices).
      const wasEmpty = !viewPopulated(get(derived), 'frequency');
      let added = false;
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
          if (get(derived)[ws.setId]?.psd === undefined) added = true;
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
      if (added) notify?.linesAdded('frequency', { viewWasEmpty: wasEmpty });
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
      // P5 data-add rule — see `calcFft`.
      const wasEmpty = !viewPopulated(get(derived), 'tf');
      let added = false;
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
        if (get(derived)[first.setId]?.tf === undefined) added = true;
        setDerived(first.setId, { tf });
        // NOT `markComputed`: an ensemble result has MANY sources but hangs on
        // the first set, so materialising it would stamp single-source
        // provenance and an edit to any other member would never flip the
        // staleness flag. Deferred — see `materializeDerived`'s doc.
        maybeRestoreModalRecon([first.setId]);          // deferred modal recon
        if (added) notify?.linesAdded('tf', { viewWasEmpty: wasEmpty });
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
        if (get(derived)[ws.setId]?.tf === undefined) added = true;
        // Carry this set's chIn + channel count onto the slice so the plot
        // model remaps its out/in columns/labels correctly (R4).
        setDerived(ws.setId, { tf: tfFromResult(res, fAxis, chIn, ws.nChannels) });
        markComputed(ws.setId, 'tf');                 // Save may materialise it
      }
      if (stale('tf', my)) return;                    // a newer batch superseded us
      if (added) notify?.linesAdded('tf', { viewWasEmpty: wasEmpty });
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
      // P5 data-add rule — see `calcFft`. A re-run at a new nFft / channel /
      // wavelet Q keeps the user's window; the FIRST sonogram re-fits.
      const wasEmpty = !viewPopulated(get(derived), 'sono');
      const added = get(derived)[ws.setId]?.sono === undefined;
      setDerived(ws.setId, {
        sono: {
          timeAxis: axisData(mval(res, 'time_axis')),
          freqAxis: axisData(mval(res, 'freq_axis')),
          data: decodeArray(asMarshalled(mval(res, 'sono_data'))),
        },
      });
      if (added) notify?.linesAdded('sono', { viewWasEmpty: wasEmpty });
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

  /** One-level resample undo stash per set (round-9). */
  const resampleUndo = new Map<number, { td: NpyArray; ax: NpyArray; fs: number }>();

  /**
   * Resample the set named by `target` to `fsNew` (round-9): the Time
   * view's Resample tool, "resample to match", and the web-audio side of
   * the logging digital low-pass. Band-limited rational polyphase via the
   * engine's `resample_time` op — noise-reducing anti-alias decimation
   * when `fsNew < fs` (96 dB stopband at the new Nyquist), band-limited
   * (sinc) interpolation when `fsNew > fs` (stopband at the ORIGINAL
   * Nyquist — no invented high-frequency content), zero-phase either way.
   *
   * Replaces the set's stored TimeData in place — arrays, time axis, and
   * `settings.fs` — then recomputes every derived result that already
   * exists for the set (like Clean Impulse). Stashes the previous arrays
   * so `undoResample` can revert one step. Returns the ACHIEVED fs
   * (rational approximation of `fsNew`; equal for representable ratios),
   * or null when the target is unknown / has no time data / the rate is
   * already `fsNew`.
   */
  async function resampleTime(
    target: AnalysisTarget,
    fsNew: number,
    opts: { notify?: boolean } = {},
  ): Promise<number | null> {
    const ws = target === 'all' ? working[0] : working.find((w) => w.setId === target);
    if (!ws || !ws.time.arrays.time_data || !(fsNew > 0)) return null;
    if (Math.abs(fsNew - ws.fs) / ws.fs < 1e-9) return null;
    let achieved: number | null = null;
    await guarded('resample', async () => {
      const prev = { td: ws.time.arrays.time_data, ax: ws.time.arrays.time_axis, fs: ws.fs };
      const { data, nCh } = timePayload(ws.time);
      const res = await engine.enqueue('resample_time', {
        time_data: data, n_channels: nCh, fs: ws.fs, fs_new: fsNew,
      });
      const out = asMarshalled(mval(res, 'time_data'));
      const fsOut = num(mval(res, 'fs_out'));
      const n = out.shape[0];
      const axis = Float64Array.from({ length: n }, (_, i) => i / fsOut);
      applyTimeArrays(ws, {
        td: {
          shape: out.shape, isComplex: false,
          data: out.data instanceof Float64Array ? out.data : Float64Array.from(out.data),
        },
        ax: { shape: [n], isComplex: false, data: axis },
      });
      resampleUndo.set(ws.setId, prev);
      // A resample invalidates the clean-impulse stash (raw arrays at the
      // OLD rate would corrupt a later toggle) — drop it for this set.
      cleanCache.delete(ws.setId);
      cleanedSets.update((m) => ({ ...m, [ws.setId]: false }));
      ws.fs = fsOut;
      if (ws.time.settings) ws.time.settings.fs = fsOut;
      else ws.time.settings = { fs: fsOut };
      dataset.update((d) => d);          // re-emit for autosave (see cleanImpulse)
      await recomputeExisting(ws);
      achieved = fsOut;
      if (opts.notify) {
        const fromTxt = prev.fs >= 1000 ? `${(prev.fs / 1000).toFixed(3).replace(/\.?0+$/, '')} kHz` : `${prev.fs.toFixed(6).replace(/\.?0+$/, '')} Hz`;
        const toTxt = fsOut >= 1000 ? `${(fsOut / 1000).toFixed(3).replace(/\.?0+$/, '')} kHz` : `${fsOut.toFixed(6).replace(/\.?0+$/, '')} Hz`;
        toasts?.push(`Resampled ${fromTxt} → ${toTxt}. Saved data will carry the new rate.`, {
          level: 'success',
          actions: [{ label: '↶ Undo', run: () => void undoResample(ws.setId) }],
        });
      }
    });
    return achieved;
  }

  /**
   * Revert the last `resampleTime` on a set (one level). Restores the
   * stashed arrays + fs and recomputes existing derived results. Returns
   * true when a stash existed.
   */
  async function undoResample(setId: number): Promise<boolean> {
    const prev = resampleUndo.get(setId);
    const ws = working.find((w) => w.setId === setId);
    if (!prev || !ws) return false;
    await guarded('resample', async () => {
      resampleUndo.delete(setId);
      applyTimeArrays(ws, { td: prev.td, ax: prev.ax });
      ws.fs = prev.fs;
      if (ws.time.settings) ws.time.settings.fs = prev.fs;
      cleanCache.delete(ws.setId);
      cleanedSets.update((m) => ({ ...m, [ws.setId]: false }));
      dataset.update((d) => d);
      await recomputeExisting(ws);
    });
    return true;
  }

  /**
   * Add a recorded TimeData item to the existing dataset (or create one
   * if empty).  The item is appended, registered with the selection
   * tray, and seeded into the derived map so the time view shows it
   * immediately.  Returns the new set's `setId`.
   *
   * Plan 2 acquisition: called by the AcquireCard after a successful
   * recording — the item comes from `recordingToItem` in acquire.ts.
   *
   * `opts.hidden` (round-11 P6) registers the set with every line already
   * 'off' and SKIPS the `linesAdded` notification. Both halves matter for the
   * BLA run's `M × n_exc` raw captures: the set must never be emitted visible
   * (see `selection.addSet`'s `hidden` option), and a hidden capture is not a
   * new line in the time view, so announcing it would re-autoscale that view
   * once per capture for data nobody can see.
   */
  function addRecordedSet(item: DvmaItem, opts: { hidden?: boolean } = {}): number {
    // P5: a capture is always a NEW line in the time view. Judged before the
    // seeding below (an empty time view also releases the x window — the
    // first capture of a session must not inherit a leftover zoom).
    const wasEmpty = !viewPopulated(get(derived), 'time');
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
    const setId = selection.addSet(
      { name, nChannels: nCh, durationS: dur, timestamp },
      { hidden: !!opts.hidden },
    );
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

    if (!opts.hidden) notify?.linesAdded('time', { viewWasEmpty: wasEmpty });
    return setId;
  }

  /**
   * Land the `calc_bla` results (Schoukens BLA, the "Nonlin" stage) as
   * FIRST-CLASS TF sets — one per excitation `q`, each carrying every
   * response channel as a column.  Returns the new sets' ids in the same
   * order as `results`.
   *
   * The sets are built exactly like an ORPHAN TF loaded from a file (the
   * `loadDataset` pass-2 branch): a `TfData` item appended to the dataset, its
   * own tray set with `chIn = null` (nothing was dropped — the columns ARE the
   * lines, `tfColumn` identity), and an entry in `working` so the set is
   * targetable, fittable and exportable like any other. That is what makes a
   * BLA a normal TF everywhere — Bode / Nyquist / phase / export / modal fit
   * all work with no special case, which is the whole reason the design
   * extends `TfData` rather than adding a new data kind. A `'fit'`-style
   * pseudo-set was the alternative and was rejected: pseudo-sets are excluded
   * from the analysis-target and export paths by design.
   *
   * The σ pair rides the derived `tf` slice (`sigmaNl` / `sigmaN`) beside the
   * curve it annotates, mirroring `coherence`; the arrays ALSO go onto the
   * item so `.dvma` round-trips them (`container.py` registers
   * `bla_sigma_nl` / `bla_sigma_n` on `TfData`), and the engine's `bla` run-spec
   * dict is stored verbatim as item meta (a registered optional `TfData` meta
   * field, already JSON-clean).
   *
   * `opts.names` supplies one display name per excitation (the caller knows
   * the x-channel geometry); `opts.channelLabels` optionally names the lines
   * after their SOURCE response channels so the legend stays readable.
   */
  function addBlaSets(
    results: unknown[],
    opts: { names?: string[]; channelLabels?: string[]; timestring?: string } = {},
  ): number[] {
    let ds = get(dataset);
    if (!ds) ds = { formatVersion: 2, pydvmaVersion: 'webui', items: [] };
    const now = new Date();
    const timestring = opts.timestring ?? timestringOf(now);
    const iso = now.toISOString();
    const ids: number[] = [];
    // P5: BLA results are new TF lines (see `linesAdded`), judged before any
    // of them land.
    const wasEmpty = !viewPopulated(get(derived), 'tf');

    results.forEach((res, q) => {
      const axis = axisData(mval(res, 'freq_axis'));
      const tfM = asMarshalled(mval(res, 'tf_data'));
      const nOut = tfM.shape[1] ?? 1;
      const sigNl = mval(res, 'bla_sigma_nl');
      const sigN = mval(res, 'bla_sigma_n');
      const sigNlM = sigNl == null ? null : asMarshalled(sigNl);
      const sigNM = sigN == null ? null : asMarshalled(sigN);
      const name = opts.names?.[q] ?? `BLA q${q + 1}`;
      // The engine's `bla` dict is already JSON-clean (numpy scalars stripped);
      // a Map only ever appears in tests, so normalise both shapes.
      const blaRaw = mval(res, 'bla');
      const bla = blaRaw instanceof Map ? Object.fromEntries(blaRaw) : blaRaw ?? null;

      const arrays: Record<string, NpyArray> = {
        freq_axis: { shape: [axis.length], data: axis, isComplex: false },
        tf_data: { shape: tfM.shape.slice(), data: toF64(tfM.data), isComplex: true },
      };
      if (sigNlM) arrays.bla_sigma_nl = { shape: sigNlM.shape.slice(), data: toF64(sigNlM.data), isComplex: false };
      if (sigNM) arrays.bla_sigma_n = { shape: sigNM.shape.slice(), data: toF64(sigNM.data), isComplex: false };

      const meta: Record<string, unknown> = {
        units: null, test_name: name, timestamp: iso, timestring,
        id_link: null, channels: nOut, bla,
      };
      const item: DvmaItem = {
        kind: 'TfData', arrays, meta,
        // `timestamp` carries the datetime tag so python decodes a real
        // datetime on load (same convention as `upsertModalItem`).
        metaRaw: { ...meta, timestamp: { __datetime__: iso } },
        settings: null,
      };
      ds!.items.push(item);

      const setId = selection.addSet({ name, nChannels: nOut, durationS: 0, timestamp: timestring });
      working.push({ setId, time: item, fs: sampleRate(item), durationS: 0, nChannels: nOut });
      setDerived(setId, {
        tf: {
          axis, data: decodeArray(tfM), chIn: null, nChannels: nOut,
          sigmaNl: sigNlM ? decodeArray(sigNlM) : undefined,
          sigmaN: sigNM ? decodeArray(sigNM) : undefined,
        },
      });
      opts.channelLabels?.slice(0, nOut).forEach((label, c) => {
        if (label) selection.renameChannel(setId, c, label);
      });
      ids.push(setId);
    });

    dataset.set(ds);
    if (ids.length) notify?.linesAdded('tf', { viewWasEmpty: wasEmpty });
    return ids;
  }

  /**
   * One-level undo slot for {@link removeBlaRun} — everything needed to put a
   * removed set back exactly as it was: its dataset item (and the index it sat
   * at, so the file's item order survives), its selection record minus the id
   * (ids are never reused, so the restored set gets a fresh one), its per-line
   * tri-states and custom labels, its `working` entry and its derived slice.
   */
  interface RemovedSet {
    item: DvmaItem | null;
    index: number;
    record: SetRecord;
    states: TriState[];
    labels: Record<string, string> | undefined;
    ws: WorkingSet | null;
    slice: SetArrays | undefined;
    /**
     * The set's MATERIALISED derived items (see `materializeDerived`) with
     * their original positions, pulled out of the document alongside the
     * source they were derived from. Without this a removed set's saved FFT/TF
     * would stay in `ds.items` with an `id_link` to a source that is gone —
     * reloading the file as a phantom orphan tray set.
     */
    derivedItems: { kind: DerivedKind; item: DvmaItem; index: number }[];
    /** Which kinds were marked computed-this-session, so undo can re-mark. */
    computedKinds: DerivedKind[];
  }
  let blaRunUndo: RemovedSet[] = [];

  /**
   * Remove a previous BLA run's sets — raw captures AND result sets — from the
   * dataset, the tray and the derived map, and offer a one-level Undo toast
   * (round-11 P6, the "replace previous run" half of the Nonlin run
   * semantics).
   *
   * Why this lives here rather than in the BLA store: a set spans four places
   * (dataset items, `working`, `derived`, the selection tray) and only this
   * module holds three of them. `stores/bla.ts` calls it with the ids it
   * tracked and stays thin.
   *
   * Undo re-registers each set in its original dataset position with its
   * visibility, labels and derived slice intact — so a replaced run's raw
   * captures come back HIDDEN (which is how they landed) and its BLA lines
   * come back drawn. The restored sets carry NEW selection ids (ids are
   * monotonic and never reused), so the BLA store no longer tracks them; they
   * are ordinary tray cards from then on, which is exactly what a
   * previous-run set is.
   *
   * @param ids Selection ids to remove; unknown ids are skipped.
   * @param opts.label Noun for the toast ("previous BLA run" by default).
   * @returns How many sets were actually removed (`0` ⇒ no toast was raised).
   */
  function removeBlaRun(ids: readonly number[], opts: { label?: string } = {}): number {
    const ds = get(dataset);
    const stateOf = get(selection.state);
    const removed: RemovedSet[] = [];
    // Indices are read against the PRISTINE item list and the items dropped in
    // one pass at the end. Splicing per set would renumber the list under the
    // remaining lookups, and every subsequent set would stash index 0 — which
    // restores the run backwards.
    const drop = new Set<DvmaItem>();
    for (const id of ids) {
      const record = get(selection.sets).find((s) => s.id === id);
      if (!record) continue;
      const ws = working.find((w) => w.setId === id) ?? null;
      const item = ws?.time ?? null;
      // This set's materialised FFT/TF leave WITH it — they are derived from
      // the very item being removed, and the lineage/computed keys would
      // otherwise linger and be re-used by a future set (see `RemovedSet`).
      const derivedItems: RemovedSet['derivedItems'] = [];
      const computedKinds: DerivedKind[] = [];
      for (const kind of ['freq', 'tf'] as const) {
        const key = lineageKey(id, kind);
        const mat = materializedItems.get(key);
        const at = mat && ds ? ds.items.indexOf(mat) : -1;
        if (mat && at >= 0) { derivedItems.push({ kind, item: mat, index: at }); drop.add(mat); }
        materializedItems.delete(key);
        if (computedThisSession.delete(key)) computedKinds.push(kind);
      }
      removed.push({
        item,
        index: ds && item ? ds.items.indexOf(item) : -1,
        record: { ...record, colors: record.colors.slice() },
        states: Array.from({ length: record.nChannels }, (_, c) => stateOf(id, c)),
        labels: selection.getLabelsForSet(id),
        ws,
        slice: get(derived)[id],
        derivedItems,
        computedKinds,
      });
      if (item) drop.add(item);
      working = working.filter((w) => w.setId !== id);
      derived.update((d) => { const n = { ...d }; delete n[id]; return n; });
      // Per-set caches are keyed by the id that is going away.
      cleanCache.delete(id);
      cleanedSets.update((m) => { const n = { ...m }; delete n[id]; return n; });
      resampleUndo.delete(id);
      // `analysisSettings` prunes itself off `selection.setsView`, so removing
      // the tray set is enough to drop its per-set settings record.
      selection.removeSet(id);
    }
    if (!removed.length) return 0;
    if (ds) {
      if (drop.size) ds.items = ds.items.filter((i) => !drop.has(i));
      dataset.set(ds);
    }
    blaRunUndo = removed;
    const n = removed.length;
    const what = opts.label ?? 'previous BLA run';
    toasts?.push(`Replaced the ${what} — ${n} set${n === 1 ? '' : 's'} removed.`, {
      level: 'info',
      actions: [{ label: '↶ Undo', run: () => void undoRemoveBlaRun() }],
    });
    return n;
  }

  /**
   * Restore the sets {@link removeBlaRun} last removed (the toast's Undo).
   * Sets go back in their original dataset order, so the restored `.dvma`
   * matches what a save before the replace would have written. Returns false
   * when the slot is empty (already undone, or nothing was removed).
   *
   * ONE deliberate departure from a literal undo: by the time the user takes
   * it, the replacement run has usually already landed under the SAME names
   * (that is why the old ones were removed), so restoring verbatim would hand
   * them two indistinguishable groups of tray cards — precisely the confusion
   * the run-suffix scheme exists to prevent. On a name collision the whole
   * restored batch is marked `… (restored)`, on the tray card AND on the
   * item's `test_name`, so the distinction survives a save.
   */
  function undoRemoveBlaRun(): boolean {
    if (!blaRunUndo.length) return false;
    const batch = blaRunUndo;
    blaRunUndo = [];
    let ds = get(dataset);
    if (!ds) ds = { formatVersion: 2, pydvmaVersion: 'webui', items: [] };
    const taken = new Set(get(selection.sets).map((s) => s.name));
    // Marked as a BATCH, not per set: half a run renamed would read as two
    // different runs.
    const mark = batch.some((r) => taken.has(r.record.name)) ? ' (restored)' : '';
    // Ascending original index, so each splice lands where the item was.
    const ordered = [...batch].sort((a, b) => a.index - b.index);
    for (const r of ordered) {
      const name = r.record.name + mark;
      if (r.item) {
        if (mark) setItemMeta(r.item, 'test_name', name);
        const at = r.index >= 0 && r.index <= ds.items.length ? r.index : ds.items.length;
        ds.items.splice(at, 0, r.item);
      }
      const { nChannels, durationS, timestamp, role, colors } = r.record;
      const id = selection.addSet({ name, nChannels, durationS, timestamp, role, colors });
      selection.setLineStates(id, r.states);
      if (r.labels) {
        for (const [c, label] of Object.entries(r.labels)) selection.renameChannel(id, Number(c), label);
      }
      if (r.ws) working.push({ ...r.ws, setId: id });
      if (r.slice) setDerived(id, { ...r.slice, setId: id });
      // Put the materialised FFT/TF back and re-key their lineage under the
      // NEW selection id — otherwise the next Save would push a SECOND copy
      // beside the restored one. Positions are best-effort (the same
      // original-index convention as the source item above).
      for (const dItem of r.derivedItems) {
        const at = dItem.index >= 0 && dItem.index <= ds.items.length ? dItem.index : ds.items.length;
        ds.items.splice(at, 0, dItem.item);
        materializedItems.set(lineageKey(id, dItem.kind), dItem.item);
      }
      for (const kind of r.computedKinds) computedThisSession.add(lineageKey(id, kind));
    }
    dataset.set(ds);
    return true;
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
    // P5: a calibration rescales every derived view of this set (a 100 mV/g
    // sensitivity moves the y decades), so relax their y axes back to auto.
    notify?.unitsChanged(['time', 'frequency', 'tf']);
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
    // P5: (iω)^p changes the plotted QUANTITY (and its decades) on the
    // spectral views — relax their y axes back to auto.
    notify?.unitsChanged(['frequency', 'tf']);
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
          const before = num(mval(res, 'cost_before'));
          const after = num(mval(res, 'cost_after'));
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
    const { method, voicesPerOctave, w0, fMin, fMax } = sonoSettings(ws.setId);
    // Auto knobs are OMITTED (not sent as JS null — see calcFit note) so the
    // engine infers the free-decay start / uses its automatic threshold.
    // `method` selects the STFT or CWT damping path; the CWT params are
    // ignored by the engine for 'stft'.
    // The CWT band goes with them (the same boxes `calcSono` sends): it is not
    // cosmetic here — the wavelet fit's image is n_freqs × n_columns complex,
    // so a lab-length record over the whole default band exceeds the engine's
    // memory ceiling and the fit fails outright. Narrowing the band is the
    // remedy, and it only works if the band reaches the fit.
    const payload: Record<string, unknown> = {
      time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
      ch, nperseg: nFft,
      method, voices_per_octave: voicesPerOctave, w0,
      f_min: fMin ?? undefined, f_max: fMax ?? undefined,
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
        fPeak: num(mval(m, 'f_peak')),
        Qn: num(mval(m, 'Qn')),
      }));
    // The picking context is absent only on a pre-round-7 engine wheel (the
    // panel then shows its stale-engine note instead of the spectrum).
    const thr = mval(res, 'threshold');
    return {
      fn: axisData(mval(res, 'fn')), Qn: axisData(mval(res, 'Qn')), fits,
      // `thr === undefined` is the STALE-ENGINE sentinel (a pre-round-7 wheel
      // omits the picking context entirely); a present-but-non-finite value
      // arrives as null on the native host and decodes to NaN, not 0.
      startTime: thr === undefined ? null : num(mval(res, 'start_time')),
      threshold: thr === undefined ? null : num(thr),
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
          fc: num(mval(b, 'fc')), fLo: num(mval(b, 'f_lo')), fHi: num(mval(b, 'f_hi')),
          edcT: axisData(mval(b, 'edc_t')), edcDb: axisData(mval(b, 'edc_db')),
          fitT: fitT === undefined ? null : axisData(fitT),
          fitDb: fitT === undefined ? null : axisData(mval(b, 'fit_db')),
        };
      });
    return {
      bands: String(mval(res, 'bands')) as BandLadder,
      startTime: num(mval(res, 'start_time')),
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
    loadDataset, addRecordedSet, addBlaSets, removeBlaRun, undoRemoveBlaRun, stampUiState,
    materializeDerived,
    calcFft, calcPsd, calcTf, calcSono, cleanImpulse, cleanedSets, hasComputed,
    resampleTime, undoResample,
    calcFit, fitLineSummary, calcDamping, calcDampingBands, exportArrays, exportMat, setCsdPair,
    getCalibration, setCalFactors,
    /**
     * Report a UNITS/quantity change on `views` to the injected
     * `ViewNotifier` (round-11 P5) — for the cards that change what a view
     * PLOTS without going through an action here, i.e. the Frequency card's
     * FFT↔PSD↔CSD switch. Threading the view store into those cards instead
     * would mean a prop through every intervening component; they already
     * hold `actions`. No-op when no notifier was injected.
     */
    notifyUnitsChanged: (views: ViewId[]) => notify?.unitsChanged(views),
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
