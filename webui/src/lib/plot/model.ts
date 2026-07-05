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
import type { PlotLine, PlotModel } from './build';
import type { TfPlotType } from '../stores/viewstate';

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
 * no throw). `nOut` (TF) is the output-channel count of `tf`.
 */
export interface SetArrays {
  setId: number;
  time?: { axis: Float64Array; data: DecodedArray };          // TimeData: data (Ns, Nc)
  freq?: { axis: Float64Array; data: DecodedArray };          // FFT: freq_data (Nf, Nc) complex
  psd?: { axis: Float64Array; data: DecodedArray };           // PSD: psd (Nc, Nf) real
  csd?: { axis: Float64Array; data: DecodedArray };           // CSD: |Cxy| pairs (Nc, Nc, Nf)
  tf?: { axis: Float64Array; data: DecodedArray; coherence?: DecodedArray }; // tf_data (Nf, Nout)
  /** Sonogram magnitude image (Nf, Nt) plus its two axes (canvas heat layer). */
  sono?: { timeAxis: Float64Array; freqAxis: Float64Array; data: DecodedArray };
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
  /** Shared frequency x-range for Nyquist windowing (`null` = full extent). */
  freqRange?: [number, number] | null;
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
}

const EMPTY: PlotModel = {
  lines: [], xLabel: '', yLabel: '', xRange: null, yRange: null,
};

/** nth column of a row-major (rows, cols) buffer as a fresh Float64Array. */
function column(buf: Float64Array, rows: number, cols: number, c: number): Float64Array {
  const out = new Float64Array(rows);
  for (let r = 0; r < rows; r++) out[r] = buf[r * cols + c];
  return out;
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

/**
 * Assemble the `PlotModel` for the active view from decoded set arrays
 * and the visible-line list.
 *
 * - time: one line per visible (set,ch) from TimeData (x=time_axis,
 *   y=channel column), monotonic x.
 * - frequency: FFT → 20·log10|freq_data col ch| (dB); PSD → 10·log10(psd
 *   row ch); CSD → 20·log10|Cxy[ch,ch]| honestly labelled (off-diagonal
 *   pairs deferred). Sub-mode via `freqMode`.
 * - tf: apply `tfPlotType` to complex tf_data columns — mag (dB), phase
 *   (degrees, atan2), real, imag; nyquist parametrises x=re/y=im with
 *   `squareAspect` and windows to `freqRange`. `bode` is NOT a single
 *   pane: the card builds a 'mag' model and a 'phase' model and stacks
 *   them, so `bode` here degrades to the 'mag' pane.
 * - coherence overlay: for tf mag/phase (never nyquist/real/imag), a
 *   dashed right-axis line per visible line from `coherence`, same
 *   colour, with `y2Range:[0,1]` and a γ² label.
 * - sono: no lines (the heat layer is a canvas); returns axis labels
 *   and the committed range so PlotSurface draws empty axes beneath it.
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
      const s = byId.get(v.setId)?.time;
      if (!s) continue;
      const cols = s.data.shape[1] ?? 1;
      if (v.ch >= cols) continue;
      const y = column(s.data.re, s.axis.length, cols, v.ch);
      lines.push(baseLine(s.axis, y, v));
    }
    return { ...EMPTY, lines, xLabel: 'Time (s)', yLabel: 'Amplitude', xRange: xr, yRange: yr };
  }

  if (args.view === 'frequency') {
    const mode = args.freqMode ?? 'fft';
    // yScale='lin' emits LINEAR magnitude (|H|, raw psd); 'log' (default)
    // emits dB. csd already plots linear |Cxy| and is unaffected.
    const linMag = args.yScale === 'lin';
    const lines: PlotLine[] = [];
    let yLabel = linMag ? 'Magnitude' : 'Magnitude (dB)';
    for (const v of args.visible) {
      const s = byId.get(v.setId);
      if (mode === 'fft') {
        const f = s?.freq; if (!f) continue;
        const cols = f.data.shape[1] ?? 1;
        if (v.ch >= cols) continue;
        const nf = f.axis.length;
        const y = new Float64Array(nf);
        for (let i = 0; i < nf; i++) {
          const idx = i * cols + v.ch;
          const re = f.data.re[idx], im = f.data.im ? f.data.im[idx] : 0;
          y[i] = linMag ? Math.hypot(re, im) : magDb(re, im);
        }
        lines.push(baseLine(f.axis, y, v));
      } else if (mode === 'psd') {
        const p = s?.psd; if (!p) continue;                  // psd shape (Nc, Nf)
        const nc = p.data.shape[0] ?? 1;
        if (v.ch >= nc) continue;
        const nf = p.axis.length;
        const y = new Float64Array(nf);
        for (let i = 0; i < nf; i++) {
          const x = p.data.re[v.ch * nf + i];
          y[i] = linMag ? x : powDb(x);
        }
        lines.push(baseLine(p.axis, y, v));
        yLabel = linMag ? 'PSD' : 'PSD (dB)';
      } else {                                               // csd: |Cxy[ch,ch]| (coherence diagonal)
        const c = s?.csd; if (!c) continue;                  // Cxy shape (Nc, Nc, Nf)
        const nc = c.data.shape[0] ?? 1;
        const nf = c.axis.length;
        if (v.ch >= nc) continue;
        const y = new Float64Array(nf);
        const base = (v.ch * nc + v.ch) * nf;                // diagonal [ch,ch,:]
        for (let i = 0; i < nf; i++) {
          const re = c.data.re[base + i];
          const im = c.data.im ? c.data.im[base + i] : 0;
          y[i] = Math.hypot(re, im);
        }
        lines.push(baseLine(c.axis, y, v));
        yLabel = 'CSD (coherence)';
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

    const lines: PlotLine[] = [];
    for (const v of args.visible) {
      const t = byId.get(v.setId)?.tf;
      if (!t) continue;
      const nout = t.data.shape[1] ?? 1;                     // tf_data (Nf, Nout)
      if (v.ch >= nout) continue;
      const nf = t.axis.length;
      const reCol = column(t.data.re, nf, nout, v.ch);
      const imCol = t.data.im ? column(t.data.im, nf, nout, v.ch) : new Float64Array(nf);

      if (nyquist) {
        // Parametric curve: x=re, y=im, sliced to the shared freq window.
        let x = reCol, y = imCol;
        if (window) {
          const [lo, hi] = window;
          const xs: number[] = [], ys: number[] = [];
          for (let i = 0; i < nf; i++) {
            if (t.axis[i] >= lo && t.axis[i] <= hi) { xs.push(reCol[i]); ys.push(imCol[i]); }
          }
          x = Float64Array.from(xs); y = Float64Array.from(ys);
        }
        lines.push({
          x, y, color: v.color, opacity: OPACITY[v.state],
          width: 1.5, dashed: false, yAxis: 'left', xMonotonic: false,
        });
        continue;
      }

      // Magnitude honours the y-toggle: 'lin' → |H| (linear), 'log'
      // (default) → dB. Phase/real/imag are untouched by yScale.
      const linMag = args.yScale === 'lin';
      const y = new Float64Array(nf);
      for (let i = 0; i < nf; i++) {
        const re = reCol[i], im = imCol[i];
        if (type === 'mag') y[i] = linMag ? Math.hypot(re, im) : magDb(re, im);
        else if (type === 'phase') y[i] = (Math.atan2(im, re) * 180) / Math.PI;
        else if (type === 'real') y[i] = re;
        else y[i] = im;                                      // 'imag'
      }
      lines.push(baseLine(t.axis, y, v));
    }

    if (nyquist) {
      // Nyquist axes are Real(H)/Imag(H), navigated by fmin/fmax (the shared
      // freq window applied above) — NOT by the committed view range, whose
      // `.x` is a FREQUENCY band (it doubles as `freqRange`, see
      // viewstate.sharedFreqRange). Passing that band through as xr/yr would
      // apply a frequency interval to the Real/Imag axes and squareAspect
      // would then collapse the locus. Return null so the windowed locus
      // auto-fits and squares ("fits data, stays square" — design §5).
      return {
        ...EMPTY, lines, squareAspect: true,
        xLabel: 'Real', yLabel: 'Imag', xRange: null, yRange: null,
      };
    }

    const yLabel = type === 'mag' ? (args.yScale === 'lin' ? '|H|' : '|H| (dB)')
      : type === 'phase' ? 'Phase (deg)'
      : type === 'real' ? 'Re(H)' : 'Im(H)';

    // Coherence overlay: mag/phase only (bode → mag), right axis, dashed.
    const cohShown = !!args.coherence && (type === 'mag' || type === 'phase');
    if (cohShown) {
      for (const v of args.visible) {
        const t = byId.get(v.setId)?.tf;
        if (!t?.coherence) continue;
        const nout = t.coherence.shape[1] ?? 1;
        if (v.ch >= nout) continue;
        const nf = t.axis.length;
        const y = column(t.coherence.re, nf, nout, v.ch);
        lines.push({
          x: t.axis, y, color: v.color, opacity: 0.7,
          width: 1, dashed: true, yAxis: 'right', xMonotonic: true,
        });
      }
    }

    return {
      ...EMPTY, lines, xLabel: 'Frequency (Hz)', yLabel, xScale: args.xScale, xRange: xr, yRange: yr,
      ...(cohShown ? { y2Range: [0, 1] as [number, number], y2Label: 'coherence γ²' } : {}),
    };
  }

  // sono: heat layer is a separate canvas; PlotSurface renders empty axes.
  return { ...EMPTY, xLabel: 'Time (s)', yLabel: 'Frequency (Hz)', xRange: xr, yRange: yr };
}
