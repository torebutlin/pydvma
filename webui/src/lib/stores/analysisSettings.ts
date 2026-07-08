/**
 * Per-set analysis settings store (Stage-2 Plan 1.5, Task R1).
 *
 * Moves analysis settings from GLOBAL (one setting applied to every set)
 * to PER-SET: each loaded set carries its own FFT / TF / sonogram
 * settings, keyed by the selection store's stable `setId`. A shared
 * `analysisTarget: 'all' | setId` drives every analysis card's
 * "Dataset ▾" dropdown; the card's other controls edit the FOCUSED
 * set's settings (or, for `'all'`, every set at once).
 *
 * DROPDOWN-FOLLOWS-TRAY (confirmed design decision): `analysisTarget`
 * is two-way-coupled with the tray focus (`selection.trayFocus`):
 *   - picking a set as target ⇒ `selection.solo(setId)` (so you SEE the
 *     set you configure);
 *   - picking `'all'` ⇒ `selection.all()` (show every set);
 *   - the tray soloing one set ⇒ target follows to that set;
 *   - the tray showing all sets ⇒ target follows to `'all'`.
 * The coupling is guarded against feedback loops with a re-entrancy flag
 * (`syncing`): a change we push INTO the tray must not bounce back and
 * re-drive the target. See `setTarget` / the `trayFocus` subscription.
 *
 * IN-SESSION ONLY: these settings are NOT persisted to `.dvma` in v1
 * (deferred; see TODO). The store is seeded with `defaults()` whenever a
 * set appears in `selection.setsView` and pruned when a set is removed,
 * so it never leaks records for gone sets.
 */
import { get, writable, type Readable } from 'svelte/store';
import type { Selection } from './selection';

/** The three analysis "views" that own per-set settings. */
export type SettingsView = 'freq' | 'tf' | 'sono';

/**
 * Frequency-card settings: spectral quantity + window + averaging frames, plus
 * the CSD channel pair (round-5 item 7). `csdX`/`csdY` are the two channels of
 * the cross-spectrum `S_xy = E[X_csdX* · X_csdY]`; they are display-only (the
 * full coherence matrix is computed once, so changing the pair re-plots without
 * a recompute) and ignored outside CSD mode. Defaults 0/1.
 */
export interface FreqSettings {
  window: string; mode: 'fft' | 'psd' | 'csd'; nFrames: number;
  csdX: number; csdY: number;
}
/** TF-card settings: input channel, window, averaging mode, averaging frames. */
export interface TfSettings { chIn: number; window: string; averaging: 'none' | 'within' | 'across'; nFrames: number; }
/**
 * Sonogram-card settings. `method` chooses the time-frequency transform:
 * `'stft'` (default, unchanged behaviour) uses the STFT window `nFft`;
 * `'cwt'` uses a complex Morlet continuous wavelet transform whose
 * `voicesPerOctave` (log-frequency density) and `w0` (non-dimensional Morlet
 * frequency) replace `nFft` — the CWT has no fixed window, so `nFft` is
 * ignored in that mode. `fMin`/`fMax` (Hz) optionally override the CWT's
 * auto band (`null` = auto `4/T .. 0.4*fs`). `dynRangeDb` is the heat-map
 * dynamic range, shared by both methods.
 */
export interface SonoSettings {
  nFft: number; dynRangeDb: number;
  method: 'stft' | 'cwt'; voicesPerOctave: number; w0: number;
  fMin: number | null; fMax: number | null;
}

/** All per-set settings for one set (one record per selection setId). */
export interface PerSetSettings { freq: FreqSettings; tf: TfSettings; sono: SonoSettings; }

/** Map a view name to its settings shape (used by the typed accessors). */
export interface ViewSettings { freq: FreqSettings; tf: TfSettings; sono: SonoSettings; }

/**
 * Default per-set settings. Values match each card's prior local
 * defaults (FrequencyCard: window 'hann', mode 'fft', 10 frames;
 * TFCard: chIn 0, window 'hann', averaging 'within', 10 frames;
 * SonoCard: nFft 512 = 2^9, dynRangeDb 60, method 'stft' — CWT off by
 * default so today's behaviour is preserved). A fresh object each call so
 * seeded records never alias.
 */
export function defaults(): PerSetSettings {
  return {
    freq: { window: 'hann', mode: 'fft', nFrames: 10, csdX: 0, csdY: 1 },
    tf: { chIn: 0, window: 'hann', averaging: 'within', nFrames: 10 },
    sono: { nFft: 512, dynRangeDb: 60, method: 'stft', voicesPerOctave: 16, w0: 6, fMin: null, fMax: null },
  };
}

/** `analysisTarget` value: every set, or one specific set by id. */
export type AnalysisTarget = 'all' | number;

/**
 * Create the per-set analysis-settings store bound to a selection store.
 * Returns the settings map, the `analysisTarget` writable, and typed
 * accessors (`get` / `settingFor` / `patch` / `isMixed`). Seeds/prunes
 * records off `selection.setsView` and keeps `analysisTarget` in sync
 * with `selection.trayFocus` (see the module docstring for the coupling
 * and its loop guard).
 */
export function createAnalysisSettings(selection: Selection) {
  /** Per-set settings keyed by stable selection setId. */
  const map = writable<Record<number, PerSetSettings>>({});
  /** Shared focus: which set(s) the analysis cards target. Default 'all'. */
  const analysisTarget = writable<AnalysisTarget>('all');
  /**
   * Explicit SINGLE-set target for the SONOGRAM (round-6 item 3). The sonogram
   * is a per-set, per-channel view with NO 'all' aggregate and no orphan/fit
   * target, so it targets ONE time-bearing set independently of the shared
   * `analysisTarget` (which the FFT/TF cards share and may leave at 'all').
   * `null` = none chosen yet, or no time-bearing set exists. SonoCard keeps it
   * pointing at a valid time-bearing set; App's heat renderer reads it to pick
   * which set's image to paint. Pruned to `null` when its set is removed.
   */
  const sonoTarget = writable<number | null>(null);

  /**
   * Re-entrancy guard for the target↔tray coupling. When we deliberately
   * drive the tray (solo/all) in response to a target change, the tray's
   * `trayFocus` will emit — this flag makes that echo a no-op so the two
   * subscriptions never ping-pong.
   */
  let syncing = false;

  // Seed defaults for new sets; prune records for removed sets. Keyed by
  // setId so surviving sets keep their exact settings across add/remove.
  // DATA sets only (round-5 item 13): the modal-fit pseudo-set is never an
  // analysis target, so it must not get a settings record (nor perturb the
  // `'all'` representative / mixed detection).
  const setsView = selection.dataSetsView as Readable<{ id: number }[]>;
  setsView.subscribe(($sets) => {
    const present = new Set($sets.map((s) => s.id));
    map.update((m) => {
      let changed = false;
      const next = { ...m };
      for (const s of $sets) {
        if (!(s.id in next)) { next[s.id] = defaults(); changed = true; }
      }
      for (const idKey of Object.keys(next)) {
        if (!present.has(Number(idKey))) { delete next[Number(idKey)]; changed = true; }
      }
      return changed ? next : m;
    });
    // Prune the explicit sonogram target if its set is gone (round-6 item 3) —
    // SonoCard then re-defaults to a valid time-bearing set (or disables Calc).
    const st = get(sonoTarget);
    if (st !== null && !present.has(st)) sonoTarget.set(null);
  });

  // Tray → target: when the tray settles on one soloed set, follow it;
  // when it shows all sets, read 'all'. Guarded so our own solo/all
  // pushes (below) don't bounce back.
  selection.trayFocus.subscribe((focus) => {
    if (syncing) return;
    const cur = get(analysisTarget);
    if (cur !== focus) analysisTarget.set(focus);
  });

  /**
   * Set the analysis target and drive the tray to match (target → tray):
   * a set id solos that set; `'all'` shows every set. The `syncing` flag
   * suppresses the resulting `trayFocus` echo so this never loops.
   */
  function setTarget(target: AnalysisTarget) {
    analysisTarget.set(target);
    syncing = true;
    try {
      if (target === 'all') selection.all();
      else selection.solo(target);
    } finally {
      syncing = false;
    }
  }

  /** Read one set's settings for `view`, seeding defaults if absent. */
  function getFor<V extends SettingsView>(setId: number, view: V): ViewSettings[V] {
    const rec = get(map)[setId] ?? defaults();
    return rec[view];
  }

  /** Every setId currently in the map, in ascending id order. */
  function ids(): number[] {
    return Object.keys(get(map)).map(Number).sort((a, b) => a - b);
  }

  /**
   * Representative settings for the current target. For a set id, its
   * own settings. For `'all'`, the FIRST set's settings as the display
   * representative (mixed keys are flagged separately via `isMixed`).
   * Returns `defaults()[view]` when no sets exist.
   */
  function settingFor<V extends SettingsView>(target: AnalysisTarget, view: V): ViewSettings[V] {
    if (target !== 'all') return getFor(target, view);
    const first = ids()[0];
    return first === undefined ? defaults()[view] : getFor(first, view);
  }

  /**
   * Whether the sets DISAGREE on `key` of `view` — true only in the
   * `'all'` case with 2+ sets whose values differ. Drives the "–mixed–"
   * display: a mixed key shows a placeholder until the first edit (which,
   * being an `'all'` patch, writes every set and clears the disagreement).
   */
  function isMixed<V extends SettingsView, K extends keyof ViewSettings[V]>(view: V, key: K): boolean {
    const list = ids();
    if (list.length < 2) return false;
    const m = get(map);
    const first = (m[list[0]][view] as ViewSettings[V])[key];
    return list.some((id) => (m[id][view] as ViewSettings[V])[key] !== first);
  }

  /**
   * Patch `view` settings for the target: a set id writes only that set;
   * `'all'` writes the partial to EVERY set (so the first edit after a
   * "–mixed–" display makes them agree). No-op for an unknown set id.
   */
  function patch<V extends SettingsView>(target: AnalysisTarget, view: V, partial: Partial<ViewSettings[V]>) {
    map.update((m) => {
      const next = { ...m };
      const apply = (id: number) => {
        const rec = next[id];
        if (!rec) return;
        next[id] = { ...rec, [view]: { ...rec[view], ...partial } };
      };
      if (target === 'all') Object.keys(next).forEach((k) => apply(Number(k)));
      else apply(target);
      return next;
    });
  }

  return {
    /** Read-only settings map (subscribe to react to patches). */
    map: { subscribe: map.subscribe },
    /** Shared analysis target: read to bind the "Dataset ▾" dropdown. */
    analysisTarget,
    /**
     * Explicit single-set sonogram target (round-6 item 3): the setId the Sono
     * card + heat renderer use, or `null` when no time-bearing set is chosen.
     */
    sonoTarget,
    /** Set the target AND drive the tray to match (use from the dropdown). */
    setTarget,
    /** One set's settings for a view. */
    get: getFor,
    /** Representative settings for the current target (see `isMixed`). */
    settingFor,
    /** True when sets disagree on a key (the "–mixed–" flag). */
    isMixed,
    /** Write a partial: one set, or every set when target is 'all'. */
    patch,
  };
}

/** The store object `createAnalysisSettings()` returns (for component props). */
export type AnalysisSettings = ReturnType<typeof createAnalysisSettings>;
