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
 * sets `computeError` rather than hanging (engine store A8b: enqueue
 * rejects, never hangs). Live slider re-issues are debounced (150 ms)
 * and guarded by `latestOnly` so an out-of-order response never
 * clobbers a newer one.
 */
import { get, writable } from 'svelte/store';
import type { DvmaDataset, DvmaItem } from '../model/dataset';
import { itemChannels } from '../model/dataset';
import type { EngineStore } from '../stores/engine';
import type { Selection } from '../stores/selection';
import { decodeArray, type MarshalledArray, type SetArrays } from '../plot/model';
import { fromNFrames, fromNFft } from './resolution';

/**
 * Wrap an async action so only the LATEST invocation's continuation
 * runs to completion: each call bumps a shared counter, and after the
 * inner promise settles the wrapper returns early if a newer call has
 * since started. Used for live slider re-issues (TF n-frames, sonogram
 * resolution) where out-of-order worker responses must not clobber the
 * newest one. (The action bodies ALSO guard their commit with the same
 * seq for finer-grained per-batch dropping.)
 */
let latestSeq = 0;
export function latestOnly<T extends unknown[]>(fn: (...a: T) => Promise<void>) {
  return async (...a: T): Promise<void> => {
    const my = ++latestSeq;
    await fn(...a);
    if (my !== latestSeq) return;
  };
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
 * Create the analysis actions bound to an engine + selection store.
 * Exposes the working `dataset` store, the decoded `derived` store the
 * plot model consumes, and a `computeError` string store the cards show
 * on engine failure. Actions are thin: marshal → enqueue → decode.
 */
export function createActions(engine: EngineStore, selection: Selection) {
  const dataset = writable<DvmaDataset | null>(null);
  const derived = writable<DerivedMap>({});
  const computeError = writable<string>('');
  const busy = writable<boolean>(false);

  /** Source sets in load order (one per TimeData item), with cached meta. */
  let working: WorkingSet[] = [];

  /** Stale-guard: each action captures the seq before its worker call. */
  let seq = 0;

  function setDerived(setId: number, patch: Partial<SetArrays>) {
    derived.update(m => ({ ...m, [setId]: { ...m[setId], ...patch, setId } }));
  }

  /** Run `fn`, routing an engine rejection to `computeError` (never hangs). */
  async function guarded(fn: () => Promise<void>): Promise<void> {
    computeError.set('');
    busy.set(true);
    try {
      engine.boot();               // idempotent; lazily boots on first compute
      await fn();
    } catch (e) {
      computeError.set(e instanceof Error ? e.message : String(e));
    } finally {
      busy.set(false);
    }
  }

  /**
   * Load a dataset: reset stores, register every TimeData item with the
   * selection tray (name / channel count / duration / timestamp from
   * item meta), and seed the derived map with the time arrays so the
   * time view plots immediately (no compute needed).
   */
  function loadDataset(ds: DvmaDataset) {
    dataset.set(ds);
    derived.set({});
    computeError.set('');
    working = [];
    // Selection store has no reset; it is created fresh per app load. We
    // simply addSet for each TimeData item in this dataset.
    const seed: DerivedMap = {};
    ds.items.forEach(item => {
      if (item.kind !== 'TimeData') return;
      const nCh = itemChannels(item);
      const axis = item.arrays.time_axis?.data;
      const durationS = axis && axis.length ? axis[axis.length - 1] - axis[0] : 0;
      const name = (item.meta.test_name as string) || 'set';
      const timestamp = (item.meta.timestring as string) || '';
      const setId = selection.addSet({ name, nChannels: nCh, durationS, timestamp });
      working.push({ setId, time: item, fs: sampleRate(item), durationS, nChannels: nCh });
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
      };
    });
    derived.set(seed);
  }

  /** FFT of every set, writing decoded freq arrays into `derived`. */
  function calcFft(window: string | null) {
    return guarded(async () => {
      for (const ws of working) {
        const { axis, data, nCh } = timePayload(ws.time);
        const res = await engine.enqueue('calc_fft', {
          time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs, window,
        });
        setDerived(ws.setId, {
          freq: {
            axis: axisData(mval(res, 'freq_axis')),
            data: decodeArray(asMarshalled(mval(res, 'freq_data'))),
          },
        });
      }
    });
  }

  /** PSD (+ CSD coherence matrix) per set, at `n_frames` from `resolution`. */
  function calcPsd(window: string | null, nFrames: number) {
    return guarded(async () => {
      for (const ws of working) {
        const { axis, data, nCh } = timePayload(ws.time);
        const res = await engine.enqueue('calc_psd', {
          time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
          window: window ?? 'hann', n_frames: nFrames,
        });
        const freqAxis = axisData(mval(res, 'freq_axis'));
        setDerived(ws.setId, {
          psd: { axis: freqAxis, data: decodeArray(asMarshalled(mval(res, 'psd'))) },
          csd: { axis: freqAxis, data: decodeArray(asMarshalled(mval(res, 'Cxy'))) },
        });
      }
    });
  }

  /**
   * Transfer function. `averaging`:
   * - 'none'   → calc_tf per set with n_frames = 1
   * - 'within' → calc_tf per set with n_frames from `resolution`
   * - 'across' → one calc_tf_averaged over ALL sets' time_data (ensemble)
   */
  function calcTf(
    chIn: number,
    window: string | null,
    averaging: 'none' | 'within' | 'across',
    nFrames: number,
  ) {
    const my = ++seq;
    return guarded(async () => {
      if (averaging === 'across') {
        const sets = working.map(ws => {
          const { axis, data, nCh } = timePayload(ws.time);
          return { time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs };
        });
        const res = await engine.enqueue('calc_tf_averaged', { sets, ch_in: chIn, window });
        if (my !== seq) return;                         // stale: a newer TF request won
        const axis = axisData(mval(res, 'freq_axis'));
        const tf = tfFromResult(res, axis);
        // Ensemble result attaches to the first set (single averaged curve).
        if (working.length) setDerived(working[0].setId, { tf });
      } else {
        const frames = averaging === 'none' ? 1 : nFrames;
        for (const ws of working) {
          const { axis, data, nCh } = timePayload(ws.time);
          const res = await engine.enqueue('calc_tf', {
            time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
            ch_in: chIn, window, n_frames: frames,
          });
          if (my !== seq) return;                       // stale-drop the whole batch
          const fAxis = axisData(mval(res, 'freq_axis'));
          setDerived(ws.setId, { tf: tfFromResult(res, fAxis) });
        }
      }
    });
  }

  /** Sonogram of one channel of one set (nperseg=nFft, noverlap=nFft/2). */
  function calcSono(setIdx: number, ch: number, nFft: number) {
    const ws = working[setIdx];
    if (!ws) return Promise.resolve();
    const my = ++seq;
    return guarded(async () => {
      const { axis, data, nCh } = timePayload(ws.time);
      const res = await engine.enqueue('calc_sono', {
        time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
        ch, nperseg: nFft, noverlap: nFft >> 1,
      });
      if (my !== seq) return;
      setDerived(ws.setId, {
        sono: {
          timeAxis: axisData(mval(res, 'time_axis')),
          freqAxis: axisData(mval(res, 'freq_axis')),
          data: decodeArray(asMarshalled(mval(res, 'sono_data'))),
        },
      });
    });
  }

  /** Clean the impulse on `chImpulse` of set `setIdx`, replacing its TimeData. */
  function cleanImpulse(setIdx: number, chImpulse: number) {
    const ws = working[setIdx];
    if (!ws) return Promise.resolve();
    return guarded(async () => {
      const { axis, data, nCh } = timePayload(ws.time);
      const res = await engine.enqueue('clean_impulse', {
        time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs, ch_impulse: chImpulse,
      });
      const cleaned = asMarshalled(mval(res, 'time_data'));
      const newAxis = axisData(mval(res, 'time_axis'));
      // Replace the source item's arrays so re-analysis uses the cleaned data.
      ws.time.arrays.time_data = {
        shape: cleaned.shape, isComplex: false,
        data: cleaned.data instanceof Float64Array ? cleaned.data : Float64Array.from(cleaned.data),
      };
      ws.time.arrays.time_axis = { shape: [newAxis.length], isComplex: false, data: newAxis };
      setDerived(ws.setId, {
        time: { axis: newAxis, data: decodeArray({ ...cleaned }) },
      });
    });
  }

  return {
    dataset, derived, computeError, busy,
    loadDataset, calcFft, calcPsd, calcTf, calcSono, cleanImpulse,
    /** Source-set metadata for cards (set index → fs / duration / channels). */
    workingSets: () => working.map(w => ({
      setId: w.setId, fs: w.fs, durationS: w.durationS, nChannels: w.nChannels,
    })),
  };
}

/** Extract a marshalled 1-D axis's data as a fresh Float64Array. */
function axisData(v: unknown): Float64Array {
  const d = mval(v, 'data');
  return d instanceof Float64Array ? d : Float64Array.from((d as number[]) ?? []);
}

/** Build a SetArrays.tf slice from a calc_tf-shaped worker result. */
function tfFromResult(res: unknown, axis: Float64Array): NonNullable<SetArrays['tf']> {
  const coh = mval(res, 'coherence');
  return {
    axis,
    data: decodeArray(asMarshalled(mval(res, 'tf_data'))),
    coherence: coh == null ? undefined : decodeArray(asMarshalled(coh)),
  };
}

export type Actions = ReturnType<typeof createActions>;

/** Re-export resolution helpers so cards import from one analysis module. */
export { fromNFrames, fromNFft };
