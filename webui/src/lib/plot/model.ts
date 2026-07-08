/**
 * Pure plot-model assembly (Task 12). Turns the working dataset + the
 * selection's tri-state/colour state + the active view into a
 * `PlotModel` for `buildPlot`. This is the ONE place display transforms
 * (dB magnitude, phase, real/imag, Nyquist re/im) are applied — the
 * maths (FFT/PSD/TF/sono) always runs in the pyodide worker and crosses
 * as complex arrays; here we only reshape and re-express them for a
 * pane. Kept free of Svelte and worker imports so it is node-testable
 * (`tests/plot/model.test.ts`) — the heart of the integration, verified
 * fast, away from the slow @engine e2e.
 *
 * Marshalling convention (worker A8): every array arrives as
 * `{ shape, data (flat Float64Array, row-major), complex }`; complex is
 * INTERLEAVED `[re, im, re, im, …]`. `decodeArray` is the single decoder.
 */
import { dataExtent, type PlotLine, type PlotModel } from './build';
import type { TfPlotType } from '../stores/viewstate';
import { tfColumn } from './tfChannels';

/** The flat `{shape, data, complex}` dict every worker array crosses as. */
export interface MarshalledArray {
  shape: number[];
  data: Float64Array | number[];
  complex: boolean;
}

/** Decoded array: real part always present; imag present only for complex. */
export interface DecodedArray {
  shape: number[];
  re: Float64Array;
  im?: Float64Array;
}

/**
 * Decode a marshalled worker array into real (and, for complex, imag)
 * parts. Real arrays pass `data` straight through as `re`; complex
 * arrays de-interleave `[re, im, …]` into two half-length buffers. The
 * declared `shape` is row-major (`.ravel(order='C')`) regardless of the
 * source array's memory order, so it is carried through untouched.
 */
export function decodeArray(a: MarshalledArray): DecodedArray {
  const data = a.data instanceof Float64Array ? a.data : Float64Array.from(a.data);
  if (!a.complex) return { shape: a.shape, re: data };
  const n = data.length >> 1;
  const re = new Float64Array(n);
  const im = new Float64Array(n);
  for (let i = 0; i < n; i++) { re[i] = data[2 * i]; im[i] = data[2 * i + 1]; }
  return { shape: a.shape, re, im };
}

/** Tri-state → line opacity (off excluded upstream, never emitted). */
export type LineState = 'on' | 'fade';
const OPACITY: Record<LineState, number> = { on: 1.0, fade: 0.35 };

/** Which spectral quantity a frequency-view line represents. */
export type FreqMode = 'fft' | 'psd' | 'csd';

/**
 * One channel of one set, tagged with the render state the selection
 * store resolved for it. `state === 'off'` lines are dropped BEFORE
 * this list reaches `buildPlotModel`, so only `'on'`/`'fade'` appear.
 */
export interface VisibleLine { setId: number; ch: number; state: LineState; color: string; }

/**
 * A set's derived arrays, already decoded from the worker marshalling.
 * Only the arrays relevant to the active view need be present; a set
 * with no array for the active view contributes no lines (empty pane,
 * no throw). The `tf` slice's `data` is `(Nf, Nout)` where `Nout =
 * nChannels − 1` (the input channel is dropped) — see its field doc.
 */
export interface SetArrays {
  setId: number;
  time?: { axis: Float64Array; data: DecodedArray };          // TimeData: data (Ns, Nc)
  freq?: { axis: Float64Array; data: DecodedArray };          // FFT: freq_data (Nf, Nc) complex
  psd?: { axis: Float64Array; data: DecodedArray };           // PSD: psd (Nc, Nf) real
  /**
   * CSD slice (round-5 item 7). `data` is the COHERENCE matrix `Cxy (Nc, Nc,
   * Nf)` real; combined with the auto-power (`psd`) it reconstructs the
   * cross-spectrum MAGNITUDE for the selected pair `(i, j)` — the convention
   * is `S_xy = Pxy[i,j] = E[X_i* · X_j]` (pydvma's
   * `calculate_cross_spectrum_matrix`, `scipy.signal.csd(x_i, y_j)`), and
   * `|Pxy[i,j]|² = Cxy[i,j] · Pxx[i] · Pxx[j]`. `i`/`j` are the user-chosen
   * pair (defaults 0/1); the model draws ONE line per set — the pair line,
   * carried on the Y channel `j`. Absent `i`/`j` fall back to 0/1.
   */
  csd?: { axis: Float64Array; data: DecodedArray; i?: number; j?: number };
  /**
   * TF slice. `data` is `tf_data (Nf, Nout)`. `chIn` selects the geometry:
   *   - a NUMBER: `calculate_tf` DROPPED that input channel, so `Nout =
   *     nChannels − 1` OUTPUT columns in ascending order; the model remaps
   *     each visible source channel to its output column and skips the input
   *     line (Task R4). `nChannels` falls back to `Nout + 1` when absent.
   *   - `null`: an ORPHAN TF (a loaded TF-only file with no measured input,
   *     round-5 item 3) — nothing was dropped, so `Nout = nChannels` and each
   *     source channel maps to its OWN column (identity, via `tfColumn`).
   * `nChannels` is the source channel count either way.
   */
  tf?: {
    axis: Float64Array; data: DecodedArray; coherence?: DecodedArray;
    chIn?: number | null; nChannels?: number;
  };
  /** Sonogram magnitude image (Nf, Nt) plus its two axes (canvas heat layer). */
  sono?: { timeAxis: Float64Array; freqAxis: Float64Array; data: DecodedArray };
  /**
   * CALIBRATION SEAM (Wave-A; a calibration agent wires the UI/persistence).
   * Per-SOURCE-CHANNEL multiplier applied at DISPLAY time, mirroring Qt
   * (`plotting.py:267/271/299`): `value × calFactors[ch]`. Absent / `undefined`
   * ⇒ ALL-ONES ⇒ identity, so today's behaviour is unchanged. Semantics per
   * branch (see `calOf` / `calRatio`):
   *   - time / FFT: the signal / complex spectrum is scaled by `cal[ch]`
   *     (an AMPLITUDE factor) before the dB/linear/phase transform;
   *   - PSD: power, so the amplitude factor enters SQUARED — `× cal[ch]²`;
   *   - CSD (coherence): dimensionless, cal cancels — left untouched;
   *   - TF: each output column is scaled by the RATIO `cal[out]/cal[in]`
   *     (Qt stores this ratio on the TfData; the webui derives it from the
   *     source cal factors), applied to BOTH the measured line and its modal
   *     reconstruction overlay so they stay in engineering-unit lock-step.
   * Indexed by SOURCE channel (0..nChannels−1), same index space as `visible`.
   */
  calFactors?: number[];
  /**
   * Per-SOURCE-CHANNEL engineering unit string (round-4 item 6), used ONLY to
   * annotate plot axis labels — never to transform data. Indexed by source
   * channel like `calFactors`. Sourced from the `.dvma`/`.npy` `units` meta
   * (the same field the Calibrate dialog persists). Absent, empty, or the
   * uncalibrated default (`'V'`, see `DEFAULT_UNIT`) are treated as "no
   * meaningful unit" so the label keeps its plain fallback ('Amplitude',
   * 'Magnitude', '|H|'); a shared non-default unit across all VISIBLE channels
   * is surfaced in the axis label. See `commonUnit` / `tfRatioUnit`.
   */
  units?: string[];
}

/**
 * Units that carry NO engineering meaning for labelling: absent/empty, or the
 * uncalibrated default `'V'` (round-4 decision — "keep 'Amplitude' when units
 * are absent/all default"). Compared case-insensitively after trimming.
 */
const DEFAULT_UNITS = new Set(['', 'v']);

/** A channel's unit if it is meaningful (non-default), else `null`. */
function meaningfulUnit(u: string | undefined): string | null {
  if (typeof u !== 'string') return null;
  const t = u.trim();
  return DEFAULT_UNITS.has(t.toLowerCase()) ? null : t;
}

/**
 * Parenthesise a COMPOUND unit (one containing anything other than a letter or
 * digit, e.g. `m/s²`) so it composes unambiguously in a ratio or a square —
 * `(m/s²)/N`, `(m/s²)²/Hz` — while a simple unit is left bare (`Pa`, `N`).
 */
function wrapUnit(u: string): string {
  return /[^\p{L}\p{N}]/u.test(u) ? `(${u})` : u;
}

/**
 * The single engineering unit shared by ALL visible channels, or `null` when
 * the sets disagree or any visible channel has no meaningful unit. Drives the
 * time/frequency amplitude labels: `null` → the plain fallback (matching the
 * pre-item-6 behaviour), a value → e.g. `Amplitude (m/s²)`.
 */
function commonUnit(byId: Map<number, SetArrays>, visible: VisibleLine[]): string | null {
  let unit: string | null = null;
  for (const v of visible) {
    const u = meaningfulUnit(byId.get(v.setId)?.units?.[v.ch]);
    if (!u) return null;                 // absent/default on any line → no label unit
    if (unit === null) unit = u;
    else if (unit !== u) return null;    // mixed real units → plain fallback
  }
  return unit;
}

/**
 * The TF ratio unit `out/in` when determinable: all visible OUTPUT channels
 * share one meaningful unit AND all their input channels share one meaningful
 * unit. Otherwise `null` (label keeps `|H|`). e.g. an accel-over-force TF →
 * `(m/s²)/N`.
 */
function tfRatioUnit(byId: Map<number, SetArrays>, visible: VisibleLine[]): string | null {
  let outU: string | null = null, inU: string | null = null;
  for (const v of visible) {
    const set = byId.get(v.setId);
    const t = set?.tf;
    if (!t) continue;                    // no TF for this line → contributes nothing
    if (t.chIn === null) return null;    // orphan TF: no input channel → no ratio unit
    const o = meaningfulUnit(set?.units?.[v.ch]);
    const i = meaningfulUnit(set?.units?.[t.chIn ?? 0]);
    if (!o || !i) return null;
    if (outU === null) outU = o; else if (outU !== o) return null;
    if (inU === null) inU = i; else if (inU !== i) return null;
  }
  return outU && inU ? `${wrapUnit(outU)}/${wrapUnit(inU)}` : null;
}

/** Per-source-channel display cal factor for a set (default 1 = identity). */
function calOf(set: SetArrays | undefined, ch: number): number {
  const c = set?.calFactors?.[ch];
  return typeof c === 'number' && Number.isFinite(c) ? c : 1;
}

/**
 * TF display cal RATIO for output channel `out` against input `chIn`:
 * `cal[out]/cal[in]` (Qt's `TfData.channel_cal_factors` semantics). Default
 * 1 when either factor is absent. An ORPHAN TF (`chIn === null`) has no input
 * channel to normalise against, so the ratio is just `cal[out]` (divisor 1).
 * Applied to the complex TF column before the plot-type transform.
 */
function calRatio(set: SetArrays | undefined, out: number, chIn: number | null): number {
  return calOf(set, out) / (chIn === null ? 1 : calOf(set, chIn));
}

/** Everything `buildPlotModel` needs, kept plain for node testing. */
export interface PlotModelArgs {
  view: 'time' | 'frequency' | 'tf' | 'sono';
  /** Per-set decoded arrays for the active view (keyed by setId in `visible`). */
  sets: SetArrays[];
  /** Ordered visible (set,ch) lines with resolved state + colour. */
  visible: VisibleLine[];
  /** Frequency-view sub-mode (ignored outside `frequency`). */
  freqMode?: FreqMode;
  /** TF-view plot family (ignored outside `tf`). Bode is composed by the card. */
  tfPlotType?: TfPlotType;
  /** Coherence overlay flag (tf, mag/phase only). */
  coherence?: boolean;
  /**
   * Coherence right-axis mode (round-5 item 6). `false`/absent ⇒ the fixed
   * `[0,1]` axis; `true` ⇒ auto-fit the visible coherence data (padded). Only
   * consulted when the coherence overlay is shown (tf mag/phase).
   */
  coherenceAuto?: boolean;
  /** Shared frequency x-range for Nyquist windowing (`null` = full extent). */
  freqRange?: [number, number] | null;
  /**
   * Nyquist Real/Imag display window (round-5 item 4), the axes the toolbar's
   * x/y controls act on when plotType is `'nyquist'` — kept SEPARATE from the
   * frequency window (`range.x`). A null axis ⇒ auto-fit the windowed locus
   * (padded ~5%). `squareAspect` then equalises the two spans for a true 1:1
   * aspect, so an explicit box gets centred in a square (equal scale per unit).
   * Ignored outside the Nyquist projection.
   */
  nyquistRange?: { x: [number, number] | null; y: [number, number] | null } | null;
  /** Committed axis range for the active view (`null` axis = auto-fit). */
  range?: { x: [number, number] | null; y: [number, number] | null };
  /**
   * Per-view frequency x-axis scale (R3). `'log'` → the model carries
   * `xScale:'log'` so `buildPlot` maps the frequency axis through log10
   * with decade ticks. Applies to frequency/tf x-axes (which are
   * frequency); the TIME view's x is time and is always linear (log time
   * is nonsensical), so this is ignored there. Ignored on Nyquist (its x
   * is Real(H)). Default `'lin'`.
   */
  xScale?: 'lin' | 'log';
  /**
   * Per-view magnitude representation (R3), a MODEL change, not just an
   * axis scale. `'log'` (default) → dB: `20·log10|H|` (FFT/TF mag),
   * `10·log10` (PSD). `'lin'` → linear magnitude: `|H|` (FFT/TF), raw
   * PSD, with the y-label dropping "(dB)". Applies to MAGNITUDE views
   * only (FFT mag / TF mag / Bode-mag / PSD); ignored for TF
   * phase/real/imag/Nyquist and the time view.
   */
  yScale?: 'lin' | 'log';
  /**
   * Modal-reconstruction overlay (Task A1) — extra TF PlotLines drawn on top
   * of the measured TF, the coherence-overlay precedent (`plot/model.ts` TF
   * branch). `null`/absent ⇒ nothing drawn (the non-Fit stages). Present only
   * on the Fit stage. For each VISIBLE measured line whose set is `setId`, the
   * matching reconstruction column (same out/in remap via `tfColumn`, so plot
   * and legend never disagree — Task R4) is overlaid:
   *   - `local`  → pink solid (`#be185d`), the just-fitted modes over the fit
   *     window (mockup round2-bench.html:1588);
   *   - `global` → grey dashed (`#66708a`), the whole-model residual-free
   *     reconstruction, drawn only when `showGlobal` (the "Reconstruction"
   *     toggle) is on (mockup:1589).
   * `chIn`/`nChannels` are the target set's TF geometry (for `tfColumn`).
   */
  recon?: {
    setId: number; chIn: number | null; nChannels: number;
    local?: { axis: Float64Array; data: DecodedArray };
    global?: { axis: Float64Array; data: DecodedArray };
    showGlobal: boolean;
  } | null;
}

/** Recon overlay stroke colours (mockup round2-bench.html:1588-1590). */
const RECON_LOCAL = '#be185d';    // pink solid — the just-fitted modes
const RECON_GLOBAL = '#66708a';   // grey dashed — the whole-model reconstruction

const EMPTY: PlotModel = {
  lines: [], xLabel: '', yLabel: '', xRange: null, yRange: null,
};

/** nth column of a row-major (rows, cols) buffer as a fresh Float64Array. */
function column(buf: Float64Array, rows: number, cols: number, c: number): Float64Array {
  const out = new Float64Array(rows);
  for (let r = 0; r < rows; r++) out[r] = buf[r * cols + c];
  return out;
}

/** Pad a `[lo, hi]` extent outward by `frac` (default 5%); degenerate → ±1. */
function padExtent([lo, hi]: [number, number], frac = 0.05): [number, number] {
  const p = (hi - lo) * frac || 1;
  return [lo - p, hi + p];
}

/** 20·log10|z|, guarding log10(0) → a large-negative floor (−300 dB). */
function magDb(re: number, im: number): number {
  const m = Math.hypot(re, im);
  return m > 0 ? 20 * Math.log10(m) : -300;
}

/** 10·log10(x) for real power spectra, floored like `magDb`. */
function powDb(x: number): number {
  return x > 0 ? 10 * Math.log10(x) : -300;
}

/** Base PlotLine fields common to every left-axis, x-monotonic line. */
function baseLine(x: Float64Array, y: Float64Array, v: VisibleLine): PlotLine {
  return {
    x, y, color: v.color, opacity: OPACITY[v.state],
    width: 1.5, dashed: false, yAxis: 'left', xMonotonic: true,
  };
}

/** TF plot family excluding Bode (which degrades to 'mag'). */
type TfLineType = 'mag' | 'phase' | 'real' | 'imag' | 'nyquist';

/**
 * Transform one complex TF column into plotted `(x, y)` for a TF `type`,
 * shared by the measured lines AND the modal-reconstruction overlay so the
 * two are drawn identically. `reCol`/`imCol` are the column's real/imag
 * parts (already cal-scaled by the caller); `axis` its frequency axis.
 * Nyquist parametrises `x=Re, y=Im` and windows to `window` (the shared freq
 * band), returning `xMonotonic:false`; all other types map `x=axis` with the
 * per-type y (mag dB or linear, phase deg, real, imag) and `xMonotonic:true`.
 */
function tfXY(
  axis: Float64Array, reCol: Float64Array, imCol: Float64Array,
  type: TfLineType, linMag: boolean, window: [number, number] | null,
): { x: Float64Array; y: Float64Array; xMonotonic: boolean } {
  const nf = axis.length;
  if (type === 'nyquist') {
    if (window) {
      const [lo, hi] = window;
      const xs: number[] = [], ys: number[] = [];
      for (let i = 0; i < nf; i++) {
        if (axis[i] >= lo && axis[i] <= hi) { xs.push(reCol[i]); ys.push(imCol[i]); }
      }
      return { x: Float64Array.from(xs), y: Float64Array.from(ys), xMonotonic: false };
    }
    return { x: reCol, y: imCol, xMonotonic: false };
  }
  const y = new Float64Array(nf);
  for (let i = 0; i < nf; i++) {
    const re = reCol[i], im = imCol[i];
    if (type === 'mag') y[i] = linMag ? Math.hypot(re, im) : magDb(re, im);
    else if (type === 'phase') y[i] = (Math.atan2(im, re) * 180) / Math.PI;
    else if (type === 'real') y[i] = re;
    else y[i] = im;                                        // 'imag'
  }
  return { x: axis, y, xMonotonic: true };
}

/** A cal-scaled real/imag column pair of a complex `(Nf, nCols)` buffer. */
function calScaledColumn(data: DecodedArray, nf: number, cols: number, col: number, cal: number): { re: Float64Array; im: Float64Array } {
  const re = new Float64Array(nf), im = new Float64Array(nf);
  const hasIm = !!data.im;
  for (let i = 0; i < nf; i++) {
    const idx = i * cols + col;
    re[i] = data.re[idx] * cal;
    im[i] = hasIm ? data.im![idx] * cal : 0;
  }
  return { re, im };
}

/**
 * Assemble the `PlotModel` for the active view from decoded set arrays
 * and the visible-line list.
 *
 * - time: one line per visible (set,ch) from TimeData (x=time_axis,
 *   y=channel column), monotonic x.
 * - frequency: FFT → 20·log10|freq_data col ch| (dB); PSD → 10·log10(psd
 *   row ch); CSD → the cross-spectrum magnitude |S_xy| for the user-chosen
 *   pair (i, j), ONE line per set carried on the Y channel j (round-5 item 7:
 *   `|Pxy[i,j]|² = Cxy[i,j]·Pxx[i]·Pxx[j]`, convention `S_xy = E[X_i* X_j]`).
 *   Sub-mode via `freqMode`.
 * - tf: apply `tfPlotType` to complex tf_data columns — mag (dB), phase
 *   (degrees, atan2), real, imag; nyquist parametrises x=re/y=im with
 *   `squareAspect`, windows the locus to `freqRange` (the shared freq band),
 *   and takes its Real/Imag display window from `nyquistRange` (round-5 item
 *   4; null axis ⇒ auto-fit the windowed locus, padded ~5%). Each visible
 *   source channel is remapped to its OUTPUT column (tf_data drops the input
 *   channel, R4); the input channel draws no line. `bode` is NOT a single
 *   pane: the card builds a 'mag' model and a 'phase' model and stacks
 *   them, so `bode` here degrades to the 'mag' pane.
 * - coherence overlay: for tf mag/phase (never nyquist/real/imag), a
 *   dashed right-axis line per visible line from `coherence`, same
 *   colour, with a γ² label; the right axis is the fixed `[0,1]` by default
 *   or auto-fit to the visible coherence when `coherenceAuto` (round-5 item 6).
 * - sono: no lines (the heat layer is a canvas); returns axis labels
 *   and the committed range so PlotSurface draws empty axes beneath it.
 *
 * Calibration seam (Wave-A): each set may carry `calFactors` (per source
 * channel); the display value is scaled by it — amplitude for time/FFT, its
 * square for PSD (power), the `cal[out]/cal[in]` ratio for TF. Absent ⇒
 * all-ones ⇒ identity (today's behaviour). See `SetArrays.calFactors`.
 *
 * Modal reconstruction (Task A1): `args.recon` overlays the fitted model on
 * the TF pane — pink solid (local, just-fitted modes) and grey dashed
 * (global, when its toggle is on), one overlay per visible measured line of
 * the fit's target set, honouring the same out/in remap so plot and legend
 * agree. Non-TF views ignore it.
 *
 * Axis toggles (R3, per-view): `args.xScale='log'` threads onto the
 * frequency/tf models as `xScale:'log'` (decade log-x in `buildPlot`);
 * time/sono/Nyquist stay linear-x. `args.yScale='lin'` switches the
 * MAGNITUDE views (FFT mag / PSD / TF mag / Bode-mag) from dB to linear
 * `|H|`/raw-PSD and drops "(dB)" from the y-label; phase/real/imag/csd
 * and non-magnitude views ignore it.
 *
 * An empty/absent-array view yields an empty model — never throws.
 */
export function buildPlotModel(args: PlotModelArgs): PlotModel {
  const byId = new Map(args.sets.map(s => [s.setId, s]));
  const xr = args.range?.x ?? null;
  const yr = args.range?.y ?? null;

  if (args.view === 'time') {
    const lines: PlotLine[] = [];
    for (const v of args.visible) {
      const set = byId.get(v.setId);
      const s = set?.time;
      if (!s) continue;
      const cols = s.data.shape[1] ?? 1;
      if (v.ch >= cols) continue;
      const y = column(s.data.re, s.axis.length, cols, v.ch);
      const cal = calOf(set, v.ch);                        // display cal (default 1)
      if (cal !== 1) for (let i = 0; i < y.length; i++) y[i] *= cal;
      lines.push(baseLine(s.axis, y, v));
    }
    const unit = commonUnit(byId, args.visible);
    const yLabel = unit ? `Amplitude (${unit})` : 'Amplitude';
    return { ...EMPTY, lines, xLabel: 'Time (s)', yLabel, xRange: xr, yRange: yr };
  }

  if (args.view === 'frequency') {
    const mode = args.freqMode ?? 'fft';
    // yScale='lin' emits LINEAR magnitude (|H|, raw psd); 'log' (default)
    // emits dB. csd already plots linear |Cxy| and is unaffected.
    const linMag = args.yScale === 'lin';
    const lines: PlotLine[] = [];
    // Unit annotation (item 6): the shared engineering unit across visible
    // channels, if any. CSD is dimensionless (coherence) so it takes no unit.
    // FFT amplitude carries the channel unit; PSD is power → unit²/Hz.
    const unit = mode === 'csd' ? null : commonUnit(byId, args.visible);
    // PSD is power → unit²/Hz; parenthesise a compound unit so the square is
    // unambiguous ('m/s²' → '(m/s²)²/Hz', but 'Pa' → 'Pa²/Hz').
    const psdUnit = unit ? `${wrapUnit(unit)}²/Hz` : '';
    const yLabel = mode === 'psd'
      ? (unit ? (linMag ? `PSD (${psdUnit})` : `PSD (${psdUnit}, dB)`) : (linMag ? 'PSD' : 'PSD (dB)'))
      : mode === 'csd'
        // Cross-spectrum magnitude for the chosen pair (round-5 item 7). dB by
        // default (cross-spectra span orders of magnitude); linear honours the
        // frequency view's dB↔lin toggle if it is set.
        ? (linMag ? 'CSD |S_xy|' : 'CSD |S_xy| (dB)')
        : (unit ? (linMag ? `Magnitude (${unit})` : `Magnitude (${unit}, dB)`) : (linMag ? 'Magnitude' : 'Magnitude (dB)'));
    for (const v of args.visible) {
      const s = byId.get(v.setId);
      if (mode === 'fft') {
        const f = s?.freq; if (!f) continue;
        const cols = f.data.shape[1] ?? 1;
        if (v.ch >= cols) continue;
        const nf = f.axis.length;
        const cal = calOf(s, v.ch);                        // amplitude cal (default 1)
        const y = new Float64Array(nf);
        for (let i = 0; i < nf; i++) {
          const idx = i * cols + v.ch;
          const re = f.data.re[idx] * cal, im = (f.data.im ? f.data.im[idx] : 0) * cal;
          y[i] = linMag ? Math.hypot(re, im) : magDb(re, im);
        }
        lines.push(baseLine(f.axis, y, v));
      } else if (mode === 'psd') {
        const p = s?.psd; if (!p) continue;                  // psd shape (Nc, Nf)
        const nc = p.data.shape[0] ?? 1;
        if (v.ch >= nc) continue;
        const nf = p.axis.length;
        // PSD is POWER, so the amplitude cal enters squared (× cal²).
        const cal2 = calOf(s, v.ch) ** 2;
        const y = new Float64Array(nf);
        for (let i = 0; i < nf; i++) {
          const x = p.data.re[v.ch * nf + i] * cal2;
          y[i] = linMag ? x : powDb(x);
        }
        lines.push(baseLine(p.axis, y, v));
      } else {                                               // csd: cross-spectrum |S_xy| for the pair (i, j)
        const c = s?.csd; if (!c) continue;                  // Cxy (coherence) shape (Nc, Nc, Nf)
        const nc = c.data.shape[0] ?? 1;
        const nf = c.axis.length;
        // ONE line per set — the pair line, carried on the Y channel `j`
        // (round-5 item 7). App filters the legend to this same channel, so
        // plot + legend agree; the model still self-selects here so a direct
        // caller (or an unfiltered visible list) draws only the pair.
        const iCh = c.i ?? 0;
        const jCh = c.j ?? 1;
        if (v.ch !== jCh || iCh >= nc || jCh >= nc) continue;
        // |Pxy[i,j]|² = Cxy[i,j] · Pxx[i] · Pxx[j]. Cxy is the magnitude-squared
        // coherence; the auto-powers Pxx come from the sibling `psd` slice
        // (both are produced by the same calc_psd call). Without `psd` (e.g. a
        // bare loaded coherence matrix) fall back to the raw coherence.
        const pxx = s?.psd;
        const y = new Float64Array(nf);
        const baseIJ = (iCh * nc + jCh) * nf;                // Cxy[i, j, :]
        for (let f = 0; f < nf; f++) {
          const coh = Math.max(0, c.data.re[baseIJ + f]);    // magnitude-squared coherence ≥ 0
          let mag: number;
          if (pxx) {
            const pi = Math.abs(pxx.data.re[iCh * nf + f]);
            const pj = Math.abs(pxx.data.re[jCh * nf + f]);
            mag = Math.sqrt(coh * pi * pj);                  // |Pxy[i,j]|
          } else {
            mag = Math.sqrt(coh);                            // no auto-power → |coherence|
          }
          y[f] = linMag ? mag : (mag > 0 ? 20 * Math.log10(mag) : -300);
        }
        lines.push(baseLine(c.axis, y, v));
      }
    }
    return { ...EMPTY, lines, xLabel: 'Frequency (Hz)', yLabel, xScale: args.xScale, xRange: xr, yRange: yr };
  }

  if (args.view === 'tf') {
    const plotType = args.tfPlotType ?? 'mag';
    // Bode is composed by the card as two stacked single-pane models;
    // requesting it here yields the magnitude pane.
    const type = plotType === 'bode' ? 'mag' : plotType;
    const nyquist = type === 'nyquist';
    const window = nyquist ? (args.freqRange ?? null) : null;

    // Magnitude honours the y-toggle: 'lin' → |H| (linear), 'log' (default)
    // → dB. Phase/real/imag/nyquist ignore it.
    const linMag = args.yScale === 'lin';
    const lines: PlotLine[] = [];
    for (const v of args.visible) {
      const set = byId.get(v.setId);
      const t = set?.tf;
      if (!t) continue;
      const nout = t.data.shape[1] ?? 1;                     // tf_data (Nf, Nout)
      // R4: a MEASURED TF drops the INPUT channel, so a visible source
      // channel maps to its OUTPUT column (position within channels ∖ {chIn})
      // and the input channel has no column (skip — no line). An ORPHAN TF
      // (chIn === null, round-5 item 3) dropped nothing, so tfColumn maps each
      // channel to its own column (identity). `chIn ?? 0` would collapse the
      // orphan null to 0 and wrongly drop a line — preserve null explicitly.
      const chIn = t.chIn === undefined ? 0 : t.chIn;
      const nChannels = t.nChannels ?? nout + 1;
      const col = tfColumn(v.ch, chIn, nChannels);
      if (col === null || col >= nout) continue;             // input channel or out of range
      const nf = t.axis.length;
      // Apply the display cal RATIO cal[out]/cal[in] (default 1) before the
      // plot-type transform, matching Qt's per-output-column TF cal.
      const ratio = calRatio(set, v.ch, chIn);
      const { re, im } = calScaledColumn(t.data, nf, nout, col, ratio);
      const { x, y, xMonotonic } = tfXY(t.axis, re, im, type, linMag, window);
      lines.push({
        x, y, color: v.color, opacity: OPACITY[v.state],
        width: 1.5, dashed: false, yAxis: 'left', xMonotonic,
      });
    }

    // Modal-reconstruction overlay (Task A1) — extra PlotLines drawn over the
    // measured TF for the fit's target set. For each VISIBLE measured line of
    // that set, overlay the matching reconstruction column (same out/in remap
    // + cal ratio as the measured line, so plot and legend never disagree):
    // pink solid = local (just-fitted modes), grey dashed = global (shown only
    // when the "Reconstruction" toggle is on). Off lines are already dropped
    // from `args.visible`, so they get no overlay either.
    const recon = args.recon;
    if (recon) {
      for (const v of args.visible) {
        if (v.setId !== recon.setId) continue;
        const col = tfColumn(v.ch, recon.chIn, recon.nChannels);
        if (col === null) continue;
        const ratio = calRatio(byId.get(v.setId), v.ch, recon.chIn);
        const draw = (
          slice: { axis: Float64Array; data: DecodedArray },
          color: string, dashed: boolean, width: number,
        ) => {
          const nout = slice.data.shape[1] ?? 1;
          if (col >= nout) return;
          const nf = slice.axis.length;
          const { re, im } = calScaledColumn(slice.data, nf, nout, col, ratio);
          const { x, y, xMonotonic } = tfXY(slice.axis, re, im, type, linMag, window);
          lines.push({ x, y, color, opacity: 1, width, dashed, yAxis: 'left', xMonotonic });
        };
        // Widths bumped for legibility (round-4 item 9 — the dashed global
        // read as too subtle); mockup colours kept.
        if (recon.local) draw(recon.local, RECON_LOCAL, false, 2.8);
        if (recon.global && recon.showGlobal) draw(recon.global, RECON_GLOBAL, true, 2.2);
      }
    }

    if (nyquist) {
      // Nyquist axes are Real(H)/Imag(H). The FREQUENCY window (fmin/fmax, the
      // brush, Calc/Fit) lives on `range.x` and was applied above to WINDOW the
      // locus; it must NOT reach the Real/Imag axes (a frequency interval on
      // Real/Imag would collapse the plot under squareAspect). Instead the
      // toolbar's x/y controls drive `args.nyquistRange` (round-5 item 4): a
      // null axis auto-fits the windowed locus (padded ~5%), an explicit axis
      // pins it; squareAspect then equalises the spans for a true 1:1 aspect.
      const nx = args.nyquistRange?.x ?? padExtent(dataExtent(lines, 'x', 'any'));
      const ny = args.nyquistRange?.y ?? padExtent(dataExtent(lines, 'y', 'left'));
      return {
        ...EMPTY, lines, squareAspect: true,
        xLabel: 'Real', yLabel: 'Imag', xRange: nx, yRange: ny,
      };
    }

    // Unit annotation (item 6): a TF is a RATIO, so its unit is out/in when
    // both are determinable (e.g. (m/s²)/N). Phase is degrees regardless.
    const ratioUnit = tfRatioUnit(byId, args.visible);
    const yLabel = type === 'mag'
        ? (linMag ? (ratioUnit ? `|H| (${ratioUnit})` : '|H|')
                  : (ratioUnit ? `|H| (${ratioUnit}, dB)` : '|H| (dB)'))
      : type === 'phase' ? 'Phase (deg)'
      : type === 'real' ? (ratioUnit ? `Re(H) (${ratioUnit})` : 'Re(H)')
      : (ratioUnit ? `Im(H) (${ratioUnit})` : 'Im(H)');

    // Coherence overlay: mag/phase only (bode → mag), right axis, dashed.
    const cohShown = !!args.coherence && (type === 'mag' || type === 'phase');
    let cohLo = Infinity, cohHi = -Infinity;                 // for the auto right axis
    if (cohShown) {
      for (const v of args.visible) {
        const t = byId.get(v.setId)?.tf;
        if (!t?.coherence) continue;
        const nout = t.coherence.shape[1] ?? 1;              // coherence is (Nf, N_out) too
        // Same remap as the TF lines above (R4 measured / orphan identity).
        const chIn = t.chIn === undefined ? 0 : t.chIn;
        const nChannels = t.nChannels ?? nout + 1;
        const col = tfColumn(v.ch, chIn, nChannels);
        if (col === null || col >= nout) continue;
        const nf = t.axis.length;
        const y = column(t.coherence.re, nf, nout, col);
        for (let i = 0; i < y.length; i++) {
          const c = y[i];
          if (Number.isFinite(c)) { if (c < cohLo) cohLo = c; if (c > cohHi) cohHi = c; }
        }
        lines.push({
          x: t.axis, y, color: v.color, opacity: 0.7,
          width: 1, dashed: true, yAxis: 'right', xMonotonic: true,
        });
      }
    }

    // Right-axis range (round-5 item 6): fixed [0,1] by default; auto-fit the
    // visible coherence data (padded, clamped into [0,1]) when `coherenceAuto`.
    let y2Range: [number, number] | undefined;
    if (cohShown) {
      if (args.coherenceAuto && cohHi >= cohLo) {
        const pad = (cohHi - cohLo) * 0.05 || 0.02;
        y2Range = [Math.max(0, cohLo - pad), Math.min(1, cohHi + pad)];
      } else {
        y2Range = [0, 1];
      }
    }

    return {
      ...EMPTY, lines, xLabel: 'Frequency (Hz)', yLabel, xScale: args.xScale, xRange: xr, yRange: yr,
      ...(cohShown ? { y2Range, y2Label: 'coherence γ²' } : {}),
    };
  }

  // sono: heat layer is a separate canvas; PlotSurface renders empty axes.
  return { ...EMPTY, xLabel: 'Time (s)', yLabel: 'Frequency (Hz)', xRange: xr, yRange: yr };
}
