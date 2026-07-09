/**
 * Modal-fit state store (Wave-A Task A1; round-4 items 9-10).
 *
 * Holds ONE modal model per dataset — the browser analogue of Qt's
 * `dataset.modal_data_list[0]`. The engine (`glue.calc_fit`) is STATELESS
 * (spec §11): this store owns the accumulated modal matrix `M` and
 * re-sends it on every fit / reject / delete / refine, decoding each result
 * back into:
 *
 *   - `matrix`   — the marshalled `M` the store re-sends (opaque to the UI);
 *   - `modes`    — per-mode `{fn, zn, Q}` for the floating mode chip
 *                  (mockup `#fitChip`, round2-bench.html:1602-1606);
 *   - `local`    — the just-fitted modes' LOCAL reconstruction (dense over the
 *                  fit window; empty again after any non-'fit' recompute);
 *   - `global`   — the whole-model GLOBAL reconstruction (each set's own
 *                  measured axis), recomputed by the engine EXCLUDING muted
 *                  modes.
 *
 * Round-4 additions:
 *   - `muted`    — per-mode mute flags. A muted mode stays in `M` and in the
 *                  chip, but is excluded from the global overlay (the engine
 *                  reconstructs from a filtered `M`; recompute is driven by an
 *                  `action:'recon'` call carrying the mute indices). Preserved
 *                  across a mute-recompute / refine (mode COUNT unchanged),
 *                  reset whenever the mode set changes (fit / delete).
 *   - `reconMode` (round-7 item 6, superseding the round-4 `showLocal` /
 *                  `showGlobal` pair) — WHICH reconstruction the fit
 *                  pseudo-sets draw: 'local' or 'global'. Both were previously
 *                  drawable at once (local as an App-level pink overlay on the
 *                  primary set only), which read as "bold line for one channel
 *                  + dashed lines for all"; user feedback asked for local
 *                  lines for ALL sets/channels and an explicit either/or
 *                  toggle, so the actions layer now feeds the CHOSEN slice to
 *                  every target's pseudo-set (legend names carry the mode).
 *   - `mt`       — the current measurement type ('acc'|'vel'|'dsp'), mirrored
 *                  from the Fit card so per-mode deletes / mutes recompute the
 *                  overlays with the right `(iω)^p` power even though the chip
 *                  has no TF-type control of its own.
 *   - `undo`     — one level of undo (previous whole state) set before a
 *                  destructive/refine action; also the vehicle for refine
 *                  auto-revert. `null` when there is nothing to undo.
 *
 * `setId` records which set the model targets so a re-fit against a
 * DIFFERENT set starts fresh instead of accumulating incompatible modes.
 * `chIn` / `nChannels` map each reconstruction column back to its source
 * channel with the SAME out/in remap the measured TF uses (`tfColumn`).
 */
import { get, writable } from 'svelte/store';
import { decodeArray, type DecodedArray, type MarshalledArray } from '../plot/model';
import type { MeasurementType } from '../analysis/actions';

/**
 * One fitted mode's summary for the chip table (`Q = 1/(2ζ)`).
 * `phaseDevDeg` (round-7f, JW-logger parity): the WORST deviation, across
 * every fitted channel, of the mode's fitted modal phase from a REAL mode
 * (0° or 180°). A large value means the modal constant came out
 * significantly complex — the classic sign the TF type (acc/vel/dsp) is
 * wrong for the data, the old logger's "phase too significant" warning.
 */
export interface ModalMode { fn: number; zn: number; Q: number; phaseDevDeg: number; }

/**
 * Threshold (degrees) above which a mode's fitted phase counts as
 * SIGNIFICANT — i.e. too far from a real mode's 0°/180° to trust the
 * chosen TF type. 30° passes normal light-damping fits comfortably while
 * catching the ~90° swing of a mis-typed measurement.
 */
export const PHASE_DEV_WARN_DEG = 30;

/**
 * Per-mode worst phase deviation (degrees) from {0°, 180°}, computed from
 * the packed modal matrix (rows `[fn, zn, an*N, pn*N, rk*N, rm*N]` —
 * `modal.py`'s pack/unpack layout). Pure; tolerant of an empty matrix.
 */
export function phaseDevDegFromMatrix(matrix: MarshalledArray | null): number[] {
  if (!matrix || (matrix.shape[0] ?? 0) === 0) return [];
  const [rows, cols] = matrix.shape;
  if (!(cols >= 6)) return new Array(rows).fill(0);
  const nCh = Math.floor((cols - 2) / 4);
  const data = matrix.data instanceof Float64Array ? matrix.data : Float64Array.from(matrix.data);
  const out: number[] = [];
  for (let r = 0; r < rows; r++) {
    let worst = 0;
    for (let k = 0; k < nCh; k++) {
      const pn = data[r * cols + 2 + nCh + k];
      // Wrap to [0, π], then distance to the NEARER of {0, π}.
      let d = Math.abs(Math.atan2(Math.sin(pn), Math.cos(pn)));
      d = Math.min(d, Math.PI - d);
      if (d > worst) worst = d;
    }
    out.push((worst * 180) / Math.PI);
  }
  return out;
}

/**
 * Which reconstruction the modal-fit pseudo-sets draw (round-7 item 6):
 * `'local'` = the just-fitted modes over the fit window (empty until the next
 * Fit after any other recompute), `'global'` = the whole model over each set's
 * measured axis. An either/or choice, not two independent overlays.
 */
export type ReconMode = 'local' | 'global';

/** A reconstruction overlay: its own frequency axis + decoded complex TF. */
export interface ReconArrays { axis: Float64Array; data: DecodedArray; }

/**
 * One SET the shared-pole model spans (item 7). A shared-pole fit couples
 * several sets' TFs into ONE model (`matrix` / `modes` below): every set shares
 * the same `fn`/`zn` per mode, and each set contributes its OWN reconstruction
 * columns. Each `FitTarget` records that set's out/in geometry (`chIn` /
 * `nChannels` — `null` `chIn` for an orphan TF) plus its slice of the joint
 * `local` and `global` reconstruction (the fit pseudo-set draws whichever one
 * `reconMode` picks). `nCols` is the set's TF column count (used to size an
 * empty slice). A single-set fit has ONE target.
 */
export interface FitTarget {
  setId: number;
  chIn: number | null;
  nChannels: number;
  nCols: number;
  local: ReconArrays | null;
  global: ReconArrays | null;
}

/** The full modal-fit state for the current dataset. */
export interface ModalState {
  /** Set the model targets, or `null` when empty (no fit yet). */
  setId: number | null;
  /**
   * Input channel of the target set's TF (for the out/in overlay remap), or
   * `null` for an ORPHAN TF whose columns are the lines (round-5 item 3) —
   * `tfColumn` reads `null` as an identity mapping.
   */
  chIn: number | null;
  /** Source channel count of the target set (for the out/in overlay remap). */
  nChannels: number;
  /** Marshalled modal matrix `M` re-sent to the engine (`null` = empty). */
  matrix: MarshalledArray | null;
  /** Per-mode summaries for the floating chip. */
  modes: ModalMode[];
  /** Per-mode mute flags (same length/order as `modes`). */
  muted: boolean[];
  /** Measurement type mirrored from the Fit card (drives recon recompute). */
  mt: MeasurementType;
  /** Engine message from the last fit (poor-fit / phase warnings). */
  message: string;
  /**
   * LOCAL reconstruction (just-fitted modes, dense over the fit window) of the
   * PRIMARY target (`targets[0]`), or `null`. A convenience mirror — the
   * drawable per-set slices live on `targets`.
   */
  local: ReconArrays | null;
  /**
   * GLOBAL (whole-model) reconstruction of the PRIMARY target, or `null`.
   * Mirrors `targets[0].global`; also read as the "recon already computed"
   * flag by the deferred load-restore (`actions.maybeRestoreModalRecon`).
   */
  global: ReconArrays | null;
  /**
   * The sets this (possibly shared-pole) model spans, in reconstruction-column
   * order (item 7). A single-set fit has ONE entry; a shared-pole fit over
   * several sets has one per set, each with its own recon slice + geometry.
   * `setId`/`chIn`/`nChannels`/`local`/`global` above mirror `targets[0]`.
   */
  targets: FitTarget[];
  /**
   * Which reconstruction the fit pseudo-sets draw (round-7 item 6). Default
   * 'global' — the whole-model recon is the durable one (the local slice is
   * only non-empty straight after a Fit), so it is today's default look.
   */
  reconMode: ReconMode;
  /** One-level undo snapshot (state before the last destructive action). */
  undo: UndoSnapshot | null;
}

/** Everything undo restores — the whole state minus the undo slot itself. */
export type UndoSnapshot = Omit<ModalState, 'undo'>;

/** A worker array crosses either as a plain object or a `toJs` Map. */
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

/** A marshalled real 1-D axis's data as a fresh Float64Array. */
function axisData(v: unknown): Float64Array {
  const d = mval(v, 'data');
  return d instanceof Float64Array ? d : Float64Array.from((d as number[]) ?? []);
}

/** Decode a `{freq_axis, tf_data}` pair into a ReconArrays, or `null` if empty. */
function reconOf(axisRaw: unknown, dataRaw: unknown): ReconArrays | null {
  const axis = axisData(axisRaw);
  if (axis.length === 0) return null;
  return { axis, data: decodeArray(asMarshalled(dataRaw)) };
}

/** Fresh, empty modal state. */
function empty(): ModalState {
  return {
    setId: null, chIn: 0, nChannels: 0, matrix: null,
    modes: [], muted: [], mt: 'acc', message: '',
    local: null, global: null, targets: [], reconMode: 'global', undo: null,
  };
}

/** Snapshot the restorable part of `s` (everything but its own undo slot). */
function snapshot(s: ModalState): UndoSnapshot {
  const { undo: _drop, ...rest } = s;
  return rest;
}

/**
 * Create the modal-fit store. Actions read the current matrix/setId via
 * `get(store)` to decide whether to accumulate or start fresh, then push
 * the decoded engine result back through `applyResult`.
 */
export function createModalStore() {
  const store = writable<ModalState>(empty());

  /**
   * Context for one fitted set: which set's TF was fitted, its channel geometry
   * (`chIn === null` for an orphan TF — round-5 item 3), and how many TF
   * columns it contributed to the joint fit (`nCols`, for empty-slice sizing).
   * A shared-pole fit (item 7) passes ONE context per set, in column order.
   */
  interface FitContext { setId: number; chIn: number | null; nChannels: number; nCols: number; }

  /** Pull the engine's per-set `slices` list (or `[]`) as a plain array. */
  function sliceList(result: unknown): unknown[] {
    const raw = mval(result, 'slices');
    return raw ? Array.from(raw as ArrayLike<unknown>) : [];
  }

  /**
   * Decode a `calc_fit` engine result into the store, carrying one fit context
   * PER target set (`contexts`, in reconstruction-column order — a single-set
   * fit passes a length-1 array, a shared-pole fit one per set). The shared
   * model (`matrix` / `modes`) comes from the top-level result; each set's
   * recon slice comes from the matching `slices[i]`. `targets[0]` is mirrored
   * onto the top-level `setId`/`chIn`/`nChannels`/`local`/`global` fields.
   *
   * Preserves the `reconMode` choice and the `undo` slot across updates.
   * `muted` is preserved when the mode COUNT is unchanged (a
   * mute-recompute or a refine leaves indices meaningful) and reset to all-false
   * otherwise (fit / delete shift the rows).
   */
  function applyResult(result: unknown, contexts: FitContext[]): void {
    const fn = axisData(mval(result, 'fn'));
    const zn = axisData(mval(result, 'zn'));
    const matrixRaw = asMarshalled(mval(result, 'M'));
    const matrix = (matrixRaw.shape[0] ?? 0) > 0 ? matrixRaw : null;
    const pdev = phaseDevDegFromMatrix(matrix);
    const modes: ModalMode[] = [];
    for (let i = 0; i < fn.length; i++) {
      const z = zn[i];
      modes.push({ fn: fn[i], zn: z, Q: z > 0 ? 1 / (2 * z) : Infinity, phaseDevDeg: pdev[i] ?? 0 });
    }
    const slices = sliceList(result);
    const targets: FitTarget[] = contexts.map((ctx, i) => {
      const sl = slices[i];
      // Prefer the per-set slice; fall back (primary only) to the top-level
      // recon keys the engine also emits (single-set backward compatibility).
      const local = sl
        ? reconOf(mval(sl, 'recon_freq_axis'), mval(sl, 'recon_tf_data'))
        : (i === 0 ? reconOf(mval(result, 'recon_freq_axis'), mval(result, 'recon_tf_data')) : null);
      const global = sl
        ? reconOf(mval(sl, 'global_freq_axis'), mval(sl, 'global_tf_data'))
        : (i === 0 ? reconOf(mval(result, 'global_freq_axis'), mval(result, 'global_tf_data')) : null);
      return {
        setId: ctx.setId, chIn: ctx.chIn, nChannels: ctx.nChannels, nCols: ctx.nCols, local, global,
      };
    });
    const primary = targets[0];
    store.update((s) => {
      const keepMute = modes.length === s.modes.length && s.muted.length === modes.length;
      return {
        ...s,
        setId: matrix && primary ? primary.setId : null,
        chIn: primary ? primary.chIn : 0,
        nChannels: primary ? primary.nChannels : 0,
        matrix,
        modes,
        muted: keepMute ? s.muted : new Array(modes.length).fill(false),
        message: (mval(result, 'message') as string) ?? '',
        local: matrix && primary ? primary.local : null,
        global: matrix && primary ? primary.global : null,
        targets: matrix ? targets : [],
      };
    });
  }

  /**
   * Seed the model DIRECTLY from a marshalled matrix `M`, decoding the per-mode
   * summary from its rows (`[fn, zn, an*N, pn*N, rk*N, rm*N]`, so `fn` is column
   * 0 and `zn` column 1) WITHOUT an engine round-trip. Used to restore a loaded
   * `.dvma` ModalData item (round-5 item 13): the mode chip shows immediately;
   * the reconstruction overlays (`local`/`global`) stay `null` until a `'recon'`
   * `calc_fit` recomputes them once the target set's TF is present (the actions
   * layer fires that after load, or after the TF is first computed). `mt` is the
   * saved measurement type so that recompute uses the right `(iω)^p` power.
   *
   * `contexts` carries one geometry per target set the model spans (item 7): a
   * single-set model passes a length-1 array; a restored shared-pole model
   * passes one per set (in column order) so the deferred recon rebuilds every
   * set's slice.
   */
  function seedFromMatrix(matrix: MarshalledArray, contexts: FitContext[], mt: MeasurementType): void {
    const rows = matrix.shape[0] ?? 0;
    const cols = matrix.shape[1] ?? 0;
    const data = matrix.data instanceof Float64Array ? matrix.data : Float64Array.from(matrix.data);
    const pdev = phaseDevDegFromMatrix(matrix);
    const modes: ModalMode[] = [];
    for (let r = 0; r < rows; r++) {
      const fn = data[r * cols + 0];
      const zn = data[r * cols + 1];
      modes.push({ fn, zn, Q: zn > 0 ? 1 / (2 * zn) : Infinity, phaseDevDeg: pdev[r] ?? 0 });
    }
    // Recon slices stay null until a 'recon' calc recomputes them (deferred
    // until each target's TF is present — actions.maybeRestoreModalRecon).
    const targets: FitTarget[] = contexts.map((ctx) => ({
      setId: ctx.setId, chIn: ctx.chIn, nChannels: ctx.nChannels, nCols: ctx.nCols,
      local: null, global: null,
    }));
    const primary = targets[0];
    store.set({
      ...empty(),
      setId: rows > 0 && primary ? primary.setId : null,
      chIn: primary ? primary.chIn : 0, nChannels: primary ? primary.nChannels : 0,
      matrix: rows > 0 ? matrix : null,
      modes, muted: new Array(modes.length).fill(false), mt,
      targets: rows > 0 ? targets : [],
    });
  }

  return {
    subscribe: store.subscribe,
    /** Read the current state (for actions deciding accumulate vs fresh). */
    get: () => get(store),
    /** Push a decoded `calc_fit` result into the store. */
    applyResult,
    /** Seed the model from a saved matrix `M` (load-restore; see the fn doc). */
    seedFromMatrix,
    /**
     * Clear the whole model into the ONE-LEVEL undo slot (round-5 item 13):
     * empties matrix/modes/overlays but stashes the pre-clear state so a single
     * `undo()` brings the fit (and its cached recon overlays) back with no
     * engine call. Backs the fit tray card's delete-with-undo.
     */
    clearWithUndo: () => store.update((s) => ({ ...empty(), undo: snapshot(s) })),
    /**
     * Pick which reconstruction the fit pseudo-sets draw (round-7 item 6).
     * A store update, so the actions layer's `syncModal` subscription refeeds
     * every target's pseudo-set with the newly chosen slice — no extra wiring.
     */
    setReconMode: (mode: ReconMode) =>
      store.update((s) => (s.reconMode === mode ? s : { ...s, reconMode: mode })),
    /** Mirror the Fit card's measurement type (used by recon recompute). */
    setMt: (mt: MeasurementType) => store.update((s) => (s.mt === mt ? s : { ...s, mt })),
    /** Toggle mode `i`'s mute flag (the recompute is driven by the caller). */
    toggleMute: (i: number) => store.update((s) => {
      if (i < 0 || i >= s.muted.length) return s;
      const muted = s.muted.slice();
      muted[i] = !muted[i];
      return { ...s, muted };
    }),
    /** Indices of currently-muted modes (sent to the engine for recon). */
    mutedIndices: (): number[] => {
      const m = get(store).muted;
      const out: number[] = [];
      for (let i = 0; i < m.length; i++) if (m[i]) out.push(i);
      return out;
    },
    /** Capture the current state into the one-level undo slot. */
    pushUndo: () => store.update((s) => ({ ...s, undo: snapshot(s) })),
    /** Restore the undo snapshot (and clear the slot). No-op if none. */
    undo: () => store.update((s) => (s.undo ? { ...s.undo, undo: null } : s)),
    /** Drop the undo slot without restoring (e.g. after a clean success). */
    clearUndo: () => store.update((s) => (s.undo ? { ...s, undo: null } : s)),
    /** Reset to empty (new dataset, or the target set went away). */
    reset: () => store.set(empty()),
  };
}

/** The store object `createModalStore()` returns (for component props). */
export type ModalStore = ReturnType<typeof createModalStore>;
