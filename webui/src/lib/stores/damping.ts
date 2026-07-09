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
}

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
}

export type BandLadder = 'all' | 'octave' | 'third-octave' | 'tenth-decade';
export type DampingMode = 'peaks' | 'bands';

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
  peaks: DampingPeaksResult | null;
  bands: DampingBandsResult | null;
}

const FRESH: DampingState = {
  open: false, busy: false, error: null, mode: 'peaks',
  setId: null, ch: 0, startTime: null, threshold: null, ladder: 'octave',
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
    close: () => update((s) => ({ ...s, open: false })),
    setMode: (mode) => update((s) => ({ ...s, mode, error: null })),
    setStartTime: (startTime) => update((s) => ({ ...s, startTime })),
    setThreshold: (threshold) => update((s) => ({ ...s, threshold })),
    setLadder: (ladder) => update((s) => ({ ...s, ladder })),
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
