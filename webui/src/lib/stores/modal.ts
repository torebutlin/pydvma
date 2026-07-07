/**
 * Modal-fit state store (Wave-A Task A1).
 *
 * Holds ONE modal model per dataset — the browser analogue of Qt's
 * `dataset.modal_data_list[0]`. The engine (`glue.calc_fit`) is STATELESS
 * (spec §11): this store owns the accumulated modal matrix `M` and
 * re-sends it on every fit / reject, decoding each result back into:
 *
 *   - `matrix`   — the marshalled `M` the store re-sends (opaque to the UI);
 *   - `modes`    — per-mode `{fn, zn, Q}` for the floating mode chip
 *                  (mockup `#fitChip`, round2-bench.html:1602-1606);
 *   - `local`    — the just-fitted modes' LOCAL reconstruction (pink solid
 *                  overlay, dense over the fit window);
 *   - `global`   — the whole-model GLOBAL reconstruction (grey dashed overlay,
 *                  shown when `showGlobal` is on — the "Reconstruction" toggle).
 *
 * `setId` records which set the model targets so a re-fit against a
 * DIFFERENT set (with a possibly different channel count) starts fresh
 * instead of trying to accumulate incompatible modes. `chIn` / `nChannels`
 * are carried so the recon overlay maps each reconstruction column back to
 * its source channel with the SAME out/in remap the measured TF uses
 * (`tfColumn`), keeping plot and legend in lock-step (Task R4 precedent).
 *
 * A single modal model across MULTIPLE sets' TFs (Qt fits the whole
 * `tf_data_list` jointly) is deferred — the webui fits one target set's TF,
 * which is deterministic and robust. Flagged for Tore.
 */
import { get, writable } from 'svelte/store';
import { decodeArray, type DecodedArray, type MarshalledArray } from '../plot/model';

/** One fitted mode's summary for the chip table (`Q = 1/(2ζ)`). */
export interface ModalMode { fn: number; zn: number; Q: number; }

/** A reconstruction overlay: its own frequency axis + decoded complex TF. */
export interface ReconArrays { axis: Float64Array; data: DecodedArray; }

/** The full modal-fit state for the current dataset. */
export interface ModalState {
  /** Set the model targets, or `null` when empty (no fit yet). */
  setId: number | null;
  /** Input channel of the target set's TF (for the out/in overlay remap). */
  chIn: number;
  /** Source channel count of the target set (for the out/in overlay remap). */
  nChannels: number;
  /** Marshalled modal matrix `M` re-sent to the engine (`null` = empty). */
  matrix: MarshalledArray | null;
  /** Per-mode summaries for the floating chip. */
  modes: ModalMode[];
  /** Engine message from the last fit (poor-fit / phase warnings). */
  message: string;
  /** Local (pink) reconstruction of the just-fitted modes, or `null`. */
  local: ReconArrays | null;
  /** Global (grey dashed) reconstruction of the whole model, or `null`. */
  global: ReconArrays | null;
  /** Whether the global reconstruction overlay is shown ("Reconstruction"). */
  showGlobal: boolean;
}

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
    modes: [], message: '', local: null, global: null, showGlobal: false,
  };
}

/**
 * Create the modal-fit store. Actions read the current matrix/setId via
 * `get(store)` to decide whether to accumulate or start fresh, then push
 * the decoded engine result back through `applyResult`.
 */
export function createModalStore() {
  const store = writable<ModalState>(empty());

  /** Context for a fit: which set's TF was fitted and its channel geometry. */
  interface FitContext { setId: number; chIn: number; nChannels: number; }

  /**
   * Decode a `calc_fit` engine result into the store, carrying the fit
   * context. Preserves the current `showGlobal` toggle across updates so a
   * fresh fit does not silently hide/show the global overlay.
   */
  function applyResult(result: unknown, ctx: FitContext): void {
    const fn = axisData(mval(result, 'fn'));
    const zn = axisData(mval(result, 'zn'));
    const modes: ModalMode[] = [];
    for (let i = 0; i < fn.length; i++) {
      const z = zn[i];
      modes.push({ fn: fn[i], zn: z, Q: z > 0 ? 1 / (2 * z) : Infinity });
    }
    const matrixRaw = asMarshalled(mval(result, 'M'));
    const matrix = (matrixRaw.shape[0] ?? 0) > 0 ? matrixRaw : null;
    store.update((s) => ({
      ...s,
      setId: matrix ? ctx.setId : null,
      chIn: ctx.chIn,
      nChannels: ctx.nChannels,
      matrix,
      modes,
      message: (mval(result, 'message') as string) ?? '',
      local: reconOf(mval(result, 'recon_freq_axis'), mval(result, 'recon_tf_data')),
      global: reconOf(mval(result, 'global_freq_axis'), mval(result, 'global_tf_data')),
    }));
  }

  return {
    subscribe: store.subscribe,
    /** Read the current state (for actions deciding accumulate vs fresh). */
    get: () => get(store),
    /** Push a decoded `calc_fit` result into the store. */
    applyResult,
    /** Show/hide the global reconstruction overlay. */
    setShowGlobal: (b: boolean) => store.update((s) => ({ ...s, showGlobal: b })),
    /** Toggle the global reconstruction overlay. */
    toggleGlobal: () => store.update((s) => ({ ...s, showGlobal: !s.showGlobal })),
    /** Reset to empty (new dataset, or the target set went away). */
    reset: () => store.set(empty()),
  };
}

/** The store object `createModalStore()` returns (for component props). */
export type ModalStore = ReturnType<typeof createModalStore>;
