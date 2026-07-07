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
import { writable, get } from 'svelte/store';
import type { DvmaDataset, DvmaItem, DvmaItemUi } from '../model/dataset';
import { itemChannels, setItemMeta } from '../model/dataset';
import type { EngineStore } from '../stores/engine';
import type { Selection } from '../stores/selection';
import type { AnalysisSettings, AnalysisTarget } from '../stores/analysisSettings';
import { defaults, type PerSetSettings } from '../stores/analysisSettings';
import { decodeArray, type MarshalledArray, type SetArrays } from '../plot/model';
import type { ModalStore } from '../stores/modal';
import { normalizeFactors, normalizeUnits } from '../model/calibration';
import { calibrationController } from '../stores/calibrationController';
import { fromNFrames, fromNFft } from './resolution';

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
export function createActions(engine: EngineStore, selection: Selection, settings?: AnalysisSettings, modal?: ModalStore) {
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
    return settings?.get(setId, 'freq') ?? { window: 'hann', mode: 'fft' as const, nFrames: 10 };
  }
  function tfSettings(setId: number) {
    return settings?.get(setId, 'tf') ?? { chIn: 0, window: 'hann', averaging: 'within' as const, nFrames: 10 };
  }
  function sonoSettings(setId: number) {
    return settings?.get(setId, 'sono') ?? { nFft: 512, dynRangeDb: 60 };
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
  function loadDataset(ds: DvmaDataset) {
    dataset.set(ds);
    derived.set({});
    computeErrors.set(emptyErrors());   // fresh dataset clears every kind's error
    modal?.reset();                     // drop any prior dataset's modal fit
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
        // Thread stored per-channel calibration into the display seam so plots
        // read in engineering units immediately on load (Task A2). Absent /
        // all-ones ⇒ identity — the plot model treats it as no-op.
        calFactors: normalizeFactors(item.meta.channel_cal_factors, nCh),
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
    derived.set(seed);
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
        const sonoChanged = sono.nFft !== d.sono.nFft || sono.dynRangeDb !== d.sono.dynRangeDb;
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
          setDerived(ws.setId, {
            psd: { axis: freqAxis, data: decodeArray(asMarshalled(mval(res, 'psd'))) },
            csd: { axis: freqAxis, data: decodeArray(asMarshalled(mval(res, 'Cxy'))) },
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
   * `target` names the set by id ('all' uses the first working set); the
   * set's `nFft` comes from `settings`. `ch` is passed explicitly (the
   * sonogram channel is a card control, not a per-set stored setting).
   */
  function calcSono(target: AnalysisTarget, ch: number) {
    const ws = target === 'all' ? working[0] : working.find((w) => w.setId === target);
    if (!ws) return Promise.resolve();
    const { nFft } = sonoSettings(ws.setId);
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

  /**
   * Clean the impulse on `chImpulse` of the set named by `target`
   * (setId; 'all' uses the first working set), replacing its TimeData.
   */
  function cleanImpulse(target: AnalysisTarget, chImpulse: number) {
    const ws = target === 'all' ? working[0] : working.find((w) => w.setId === target);
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
      // The cleaned arrays were mutated in place on the item that lives inside
      // the `dataset` store, so `derived` (the plot) already updated via
      // setDerived — but the store itself never re-emitted, and autosave is
      // driven by a `dataset` subscription (App.svelte). Re-emit the same
      // object so the cleaned impulse is autosaved; otherwise a clean followed
      // by a tab-close silently loses the cleanup (explicit Save is unaffected).
      dataset.update((d) => d);
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
    setDerived(setId, { calFactors: norm });
    dataset.update((d) => d);            // re-emit so autosave persists the edit
  }

  // Publish the calibration API so the tray's Calibrate dialog can reach it
  // without a prop thread through App.svelte (see `calibrationController`).
  calibrationController.set({ getCalibration, setCalFactors });

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

  /**
   * Modal fit / reject / reconstruction over one set's TF (Task A1). The
   * engine (`calc_fit`) is STATELESS — the modal store holds the accumulated
   * matrix `M` and this re-sends it, so add/replace/delete all round-trip
   * through the store. `action`:
   *
   * - `'fit'`   — fit `nModes` mode(s) over `freqRange` (the CURRENT visible
   *   TF window, `viewState.sharedFreqRange`) and add/replace into the model.
   * - `'reject'`— delete modes whose fn lies in `freqRange`.
   * - `'recon'` — recompute the overlays from the current model (no fit).
   *
   * The fit scopes to ONE target set (deterministic; Qt's joint multi-set fit
   * is deferred). The store's matrix is only re-sent when it targets the SAME
   * set, so switching sets starts a fresh model rather than mixing geometries.
   */
  function calcFit(
    target: AnalysisTarget = 'all',
    freqRange: [number, number] | null = null,
    mt: MeasurementType = 'acc',
    action: 'fit' | 'reject' | 'recon' = 'fit',
    nModes = 1,
  ) {
    if (!modal) return Promise.resolve();
    const ws = fitSet(target);
    if (!ws) return Promise.resolve();                  // no TF to fit
    const slice = get(derived)[ws.setId]!.tf!;
    const nTf = slice.data.shape[1] ?? 0;
    const chIn = slice.chIn ?? 0;
    const nChannels = slice.nChannels ?? nTf + 1;
    const my = bump('fit');
    return guarded('fit', async () => {
      // Interleave the decoded complex tf_data back to [re, im, …] for the
      // worker (the glue de-interleaves into a complex matrix).
      const re = slice.data.re, im = slice.data.im;
      const n = slice.axis.length * nTf;
      const flat = new Float64Array(n * 2);
      for (let i = 0; i < n; i++) { flat[2 * i] = re[i]; flat[2 * i + 1] = im ? im[i] : 0; }
      // Accumulate only when the stored model already targets THIS set.
      const cur = modal.get();
      const M = cur.setId === ws.setId ? cur.matrix : null;
      // OMIT null optionals — pyodide passes a JS `null` as a falsy `JsNull`
      // proxy (not Python `None`), so sending them would break the engine's
      // `is None` defaults; leaving the keys off lets the Python defaults apply.
      const payload: Record<string, unknown> = {
        freq_axis: slice.axis, tf_data: flat, n_tf: nTf, ch_in: chIn,
        n_channels: nChannels, fs: ws.fs, measurement_type: mt, action, n_modes: nModes,
      };
      if (M) payload.M = M;
      if (freqRange) payload.freq_range = freqRange;
      const res = await engine.enqueue('calc_fit', payload);
      if (stale('fit', my)) return;                     // a newer fit won
      modal.applyResult(res, { setId: ws.setId, chIn, nChannels });
    });
  }

  /**
   * Sonogram-derived modal damping for one channel of the target set (Task
   * A1; Sono card "Fit damping"). Returns the raw `{fn, Qn}` arrays for the
   * card's chip table — nothing is stored in `derived` (it is a one-shot
   * readout, not a plotted slice). `'all'` uses the first working set.
   */
  async function calcDamping(target: AnalysisTarget, ch: number, nFft: number): Promise<{ fn: Float64Array; Qn: Float64Array }> {
    const ws = target === 'all' ? working[0] : working.find((w) => w.setId === target);
    if (!ws) return { fn: new Float64Array(0), Qn: new Float64Array(0) };
    const { axis, data, nCh } = timePayload(ws.time);
    // `start_time` is omitted (not sent as JS null — see calcFit note) so the
    // engine infers the free-decay start.
    const res = await engine.enqueue('calc_damping', {
      time_axis: axis, time_data: data, n_channels: nCh, fs: ws.fs,
      ch, nperseg: nFft,
    });
    return { fn: axisData(mval(res, 'fn')), Qn: axisData(mval(res, 'Qn')) };
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
    calcFft, calcPsd, calcTf, calcSono, cleanImpulse, hasComputed,
    calcFit, calcDamping, exportArrays, exportMat,
    getCalibration, setCalFactors,
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
