/**
 * Interactive damping-fit state (round-7 items 3+4).
 *
 * One store shared by the Sono card (opens the panel, triggers fits), the
 * DampingPanel (plots + controls) and the sono plot host (the draggable
 * start-time line). It holds the DECODED results of the two damping modes —
 * the actions layer runs the engine ops (`calc_damping` /
 * `calc_damping_bands`) and pushes plain typed-array results in here; the
 * store itself never talks to the engine.
 *
 * The two knobs mirror the analysis-layer contract exactly:
 * - `startTime` (s): the free-decay start. `null` = let pydvma infer it from
 *   the pretrigger. Results echo the RESOLVED start, which seeds the panel
 *   field and the sono overlay line after an auto fit.
 * - `threshold` (peaks mode, 0..1): the normalised peak-picking threshold
 *   over the start-slice magnitude's min→max range (peakutils semantics).
 *   `null` = pydvma's automatic `10*median/max` choice; results echo the
 *   value actually used.
 */
import { writable, type Readable } from 'svelte/store';

/** One fitted mode's decay-line payload (the Qt DampingFitWindow lines). */
export interface DampingModeFit {
  tFit: Float64Array;
  realFit: Float64Array;
  realData: Float64Array;
  fPeak: number;
  Qn: number;
}

/** Decoded `calc_damping` result: fn/Qn plus the peak-picking context. */
export interface DampingPeaksResult {
  fn: Float64Array;
  Qn: Float64Array;
  fits: DampingModeFit[];
  /** Resolved decay start (s); null only on a pre-round-7 engine wheel. */
  startTime: number | null;
  /** Normalised threshold actually used; null only on an old wheel. */
  threshold: number | null;
  sliceFreq: Float64Array;
  sliceMag: Float64Array;
  peaksFreq: Float64Array;
  peaksMag: Float64Array;
}

/** One band's Schroeder EDC + T60 fit line (bands mode plotting payload). */
export interface DampingBand {
  fc: number;
  fLo: number;
  fHi: number;
  edcT: Float64Array;
  edcDb: Float64Array;
  fitT: Float64Array | null;
  fitDb: Float64Array | null;
  /** Where the curve stops: the decay meets the noise (s after the start);
   *  null from an engine older than 2026-11-24. */
  cutT: number | null;
}

/** A band metric that can be flagged as untrustworthy. */
export type BandMetric = 'EDT' | 'T20' | 'T30';

/** Decoded `calc_damping_bands` result (NaN metric = insufficient decay). */
export interface DampingBandsResult {
  bands: BandLadder;
  startTime: number;
  fc: Float64Array;
  fLo: Float64Array;
  fHi: Float64Array;
  EDT: Float64Array;
  T20: Float64Array;
  T30: Float64Array;
  T60: Float64Array;
  Qn: Float64Array;
  bandData: DampingBand[];
  /** Each band's loudest block above its noise floor (dB). Absent from an
   *  engine older than 2026-11-24, as are `cutTime` and `flags`. */
  rangeDb?: Float64Array;
  /** Where each band's curve stops, s after the start. */
  cutTime?: Float64Array;
  /** Why each metric is not trusted: comma-joined 'range' / 'short' /
   *  'bent', '' when it is (see `bandFlagReason`). */
  flags?: Record<BandMetric, string[]>;
}

/**
 * dB the decay must start above the noise for each band metric to be
 * trusted (ISO 3382). KEEP IN SYNC with pydvma's `analysis.DECAY_NEEDS_DB`.
 */
export const DECAY_NEEDS_DB: Record<BandMetric, number> = { EDT: 20, T20: 35, T30: 45 };

/**
 * A band metric's flag (`'range'`, `'short'`, `'bent'`, comma-joined; `''`
 * when trusted) in words, for the greyed cell's tooltip.
 */
export function bandFlagReason(flag: string, metric: BandMetric, rangeDb: number): string {
  const why: Record<string, string> = {
    range: `The decay starts only ${rangeDb.toFixed(1)} dB above the noise; `
      + `${metric} needs ${DECAY_NEEDS_DB[metric]} dB.`,
    short: "Shorter than the band filter's own ringing, so it measures the filter.",
    bent: "The fitted line doesn't follow the curve.",
  };
  return flag.split(',').filter(Boolean).map((f) => why[f] ?? f).join(' ');
}

/**
 * The band metrics as CSV, one row per band: NaN (and a column an older
 * engine did not send) is an empty cell, matching the table's em-dash.
 */
export function dampingBandsCsv(b: DampingBandsResult): string {
  const cell = (v: number | undefined) => (v !== undefined && Number.isFinite(v) ? String(v) : '');
  const rows = ['fc_Hz,f_lo_Hz,f_hi_Hz,EDT_s,T20_s,T30_s,T60_s,Qn,range_dB,cut_s,EDT_flag,T20_flag,T30_flag'];
  for (let i = 0; i < b.fc.length; i++) {
    rows.push([
      ...[b.fc[i], b.fLo[i], b.fHi[i], b.EDT[i], b.T20[i], b.T30[i], b.T60[i], b.Qn[i],
        b.rangeDb?.[i], b.cutTime?.[i]].map(cell),
      b.flags?.EDT[i] ?? '', b.flags?.T20[i] ?? '', b.flags?.T30[i] ?? '',
    ].join(','));
  }
  return rows.join('\n') + '\n';
}

export type BandLadder = 'all' | 'octave' | 'third-octave' | 'tenth-decade';
export type DampingMode = 'peaks' | 'bands';
/** The panel's chart identities (expand/save targets). */
export type DampingChart = 'spectrum' | 'decay' | 'edc';

export interface DampingState {
  /** Panel visible (the Sono card's Fit damping opens it). */
  open: boolean;
  /** A fit is in flight (controls disable, spinner shows). */
  busy: boolean;
  error: string | null;
  mode: DampingMode;
  /** The set/channel the open panel is fitting (frozen at open). */
  setId: number | null;
  ch: number;
  startTime: number | null;
  threshold: number | null;
  ladder: BandLadder;
  /**
   * Wide-mode chart expansion (round-7c): the named chart fills the whole
   * plot region (App hides the sonogram while set); null = normal layout.
   */
  expanded: DampingChart | null;
  peaks: DampingPeaksResult | null;
  bands: DampingBandsResult | null;
}

const FRESH: DampingState = {
  open: false, busy: false, error: null, mode: 'peaks',
  setId: null, ch: 0, startTime: null, threshold: null, ladder: 'octave',
  expanded: null,
  peaks: null, bands: null,
};

export interface DampingStore extends Readable<DampingState> {
  /** Open (or refocus) the panel for a set/channel; knobs reset to auto. */
  openFor(setId: number, ch: number): void;
  close(): void;
  setMode(mode: DampingMode): void;
  setStartTime(s: number | null): void;
  setThreshold(t: number | null): void;
  setLadder(l: BandLadder): void;
  setExpanded(chart: DampingChart | null): void;
  setBusy(busy: boolean): void;
  setError(message: string | null): void;
  /**
   * Land a peaks result. Auto knobs (null) adopt the engine's resolved
   * values so the panel fields and the sono start line show what was
   * actually fitted — an explicit user value is left untouched.
   */
  setPeaks(result: DampingPeaksResult): void;
  setBands(result: DampingBandsResult): void;
}

export function createDampingStore(): DampingStore {
  const { subscribe, update } = writable<DampingState>({ ...FRESH });
  return {
    subscribe,
    openFor(setId, ch) {
      update((s) => ({
        ...FRESH,
        open: true, setId, ch,
        // Mode/ladder survive re-opens (a user comparing sets keeps their
        // method); knobs and results reset — they belong to the old signal.
        mode: s.mode, ladder: s.ladder,
      }));
    },
    close: () => update((s) => ({ ...s, open: false, expanded: null })),
    // A mode flip collapses any expansion — the expanded chart belongs to
    // the OLD mode's family and would otherwise pin a stale full-screen plot.
    setMode: (mode) => update((s) => ({ ...s, mode, error: null, expanded: null })),
    setStartTime: (startTime) => update((s) => ({ ...s, startTime })),
    setThreshold: (threshold) => update((s) => ({ ...s, threshold })),
    setLadder: (ladder) => update((s) => ({ ...s, ladder })),
    setExpanded: (expanded) => update((s) => ({ ...s, expanded })),
    setBusy: (busy) => update((s) => ({ ...s, busy })),
    setError: (error) => update((s) => ({ ...s, error, busy: false })),
    setPeaks: (peaks) => update((s) => ({
      ...s, peaks, busy: false, error: null,
      startTime: s.startTime ?? peaks.startTime,
      threshold: s.threshold ?? peaks.threshold,
    })),
    setBands: (bands) => update((s) => ({
      ...s, bands, busy: false, error: null,
      startTime: s.startTime ?? bands.startTime,
    })),
  };
}
