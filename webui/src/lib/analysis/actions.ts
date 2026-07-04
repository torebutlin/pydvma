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
 * rejects, never hangs).
 *
 * Concurrency: live slider re-issues are debounced (150 ms) and each
 * action kind carries a PER-KIND stale seq (keyed 'fft'/'psd'/'tf'/
 * 'sono') so an out-of-order response of that SAME kind is dropped —
 * but a newer call of one kind NEVER cross-drops an in-flight result of
 * a DIFFERENT kind (that global-counter bug would let a debounced
 * sonogram slider silently blank an in-flight TF batch, and vice
 * versa). `busy` is REFERENCE-COUNTED so it stays true until the last
 * concurrent action settles, and `computeError` is cleared per-kind (a
 * concurrent action never erases another's error unseen).
 */
import { writable } from 'svelte/store';
import type { DvmaDataset, DvmaItem } from '../model/dataset';
import { itemChannels } from '../model/dataset';
import type { EngineStore } from '../stores/engine';
import type { Selection } from '../stores/selection';
import { decodeArray, type MarshalledArray, type SetArrays } from '../plot/model';
import { fromNFrames, fromNFft } from './resolution';

/** Compute-action kind, used as the per-kind stale-guard key. */
type Kind = 'fft' | 'psd' | 'tf' | 'sono' | 'clean';

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

  /**
   * Per-kind stale-guard counters. `bump(kind)` returns the token an
   * action captures BEFORE its worker call; `stale(kind, token)` is true
   * once a NEWER call of that SAME kind has bumped. Keying by kind is the
   * fix for the cross-kind clobber bug: a debounced sonogram slider must
   * not drop an in-flight TF result, and vice versa.
   */
  const seqs: Record<Kind, number> = { fft: 0, psd: 0, tf: 0, sono: 0, clean: 0 };
  const bump = (k: Kind): number => (seqs[k] = seqs[k] + 1);
  const stale = (k: Kind, token: number): boolean => token !== seqs[k];

  /**
   * Reference count of in-flight actions. `busy` reflects `busyN > 0`, so
   * two concurrent actions keep it true until BOTH settle — the first to
   * finish no longer re-enables the Calc buttons while the other runs.
   */
  let busyN = 0;

  /** Which action kind owns the currently-shown `computeError` (or null). */
  let errorKind: Kind | null = null;

  function setDerived(setId: number, patch: Partial<SetArrays>) {
    derived.update(m => ({ ...m, [setId]: { ...m[setId], ...patch, setId } }));
  }

  /**
   * Run `fn`, routing an engine rejection to `computeError` (never
   * hangs). `kind` scopes the error reset so a concurrent action of a
   * DIFFERENT kind never wipes this action's error before the user sees
   * it: entry clears the error only if it belongs to (was set by) this
   * same kind; a failure records the failing kind. `busy` is
   * reference-counted so it stays true until the last action settles.
   */
  async function guarded(kind: Kind, fn: () => Promise<void>): Promise<void> {
    if (errorKind === kind) computeError.set('');   // only clear our own prior error
    busyN += 1;
    busy.set(true);
    try {
      engine.boot();               // idempotent; lazily boots on first compute
      await fn();
      if (errorKind === kind) { computeError.set(''); errorKind = null; }  // our run succeeded
    } catch (e) {
      computeError.set(e instanceof Error ? e.message : String(e));
      errorKind = kind;
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
   */
  function loadDataset(ds: DvmaDataset) {
    dataset.set(ds);
    derived.set({});
    computeError.set('');
    errorKind = null;              // fresh dataset clears any lingering error owner
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
    const my = bump('fft');
    return guarded('fft', async () => {
      for (const ws of working) {
        const { axis, data, nCh } = timePayload(ws.time);
        const res = await engine.enqueue('calc_fft', {
          time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs, window,
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

  /** PSD (+ CSD coherence matrix) per set, at `n_frames` from `resolution`. */
  function calcPsd(window: string | null, nFrames: number) {
    const my = bump('psd');
    return guarded('psd', async () => {
      for (const ws of working) {
        const { axis, data, nCh } = timePayload(ws.time);
        const res = await engine.enqueue('calc_psd', {
          time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
          window: window ?? 'hann', n_frames: nFrames,
        });
        if (stale('psd', my)) return;                 // a newer PSD batch won
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
    const my = bump('tf');
    return guarded('tf', async () => {
      if (averaging === 'across') {
        const sets = working.map(ws => {
          const { axis, data, nCh } = timePayload(ws.time);
          return { time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs };
        });
        const res = await engine.enqueue('calc_tf_averaged', { sets, ch_in: chIn, window });
        if (stale('tf', my)) return;                    // a newer TF request won
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
          if (stale('tf', my)) return;                  // stale-drop the whole batch
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
    const my = bump('sono');
    return guarded('sono', async () => {
      const { axis, data, nCh } = timePayload(ws.time);
      const res = await engine.enqueue('calc_sono', {
        time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
        ch, nperseg: nFft, noverlap: nFft >> 1,
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

  /** Clean the impulse on `chImpulse` of set `setIdx`, replacing its TimeData. */
  function cleanImpulse(setIdx: number, chImpulse: number) {
    const ws = working[setIdx];
    if (!ws) return Promise.resolve();
    return guarded('clean', async () => {
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
