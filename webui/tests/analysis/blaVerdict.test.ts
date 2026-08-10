/**
 * BLA verdict banding (`lib/analysis/blaVerdict.ts`) — the pure logic behind
 * the Nonlin card's per-excitation summary line. The σ arrays are LINEAR
 * standard deviations, so every comparison here is against SQUARED medians.
 */
import { expect, test, describe } from 'vitest';
import {
  blaVerdicts,
  summariseBlaVerdicts,
  worstBlaChannel,
  fmtVerdictHz,
  BLA_LINEAR_TEXT,
  BLA_NONLINEAR_TEXT,
} from '../../src/lib/analysis/blaVerdict';

/** Log-spaced excited axis, 20 Hz → 5 kHz, `n` lines. */
function logAxis(n: number, f1 = 20, f2 = 5000): Float64Array {
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) out[i] = f1 * Math.pow(f2 / f1, i / (n - 1));
  return out;
}

/** σ array from a per-frequency function. */
function sigmaFrom(axis: Float64Array, f: (hz: number, i: number) => number): Float64Array {
  return Float64Array.from(axis, (hz, i) => f(hz, i));
}

describe('blaVerdicts', () => {
  test('pure-noise σ arrays read as linear in every band', () => {
    const axis = logAxis(400);
    // Distortion an order of magnitude BELOW the noise everywhere.
    const sigmaN = sigmaFrom(axis, () => 1e-3);
    const sigmaNl = sigmaFrom(axis, () => 1e-4);

    const bands = blaVerdicts(axis, sigmaNl, sigmaN);
    expect(bands).toHaveLength(4);
    expect(bands.every((b) => !b.nonlinear)).toBe(true);
    expect(bands.every((b) => b.verdict === BLA_LINEAR_TEXT)).toBe(true);
    // Ratio is a VARIANCE ratio: (1e-4/1e-3)² = 0.01.
    for (const b of bands) expect(b.ratio).toBeCloseTo(0.01, 6);
    expect(summariseBlaVerdicts(bands)).toBe(BLA_LINEAR_TEXT);
  });

  test('σ_NL rising above a corner splits the verdict at the right bands', () => {
    const axis = logAxis(400);
    const corner = 800;
    const sigmaN = sigmaFrom(axis, () => 1e-3);
    // Below the corner distortion is 10x under the noise; above it, 10x over.
    const sigmaNl = sigmaFrom(axis, (hz) => (hz < corner ? 1e-4 : 1e-2));

    const bands = blaVerdicts(axis, sigmaNl, sigmaN);
    expect(bands.length).toBe(4);
    // The log split of 20 Hz–5 kHz puts the 800 Hz corner in the last third:
    // whatever the exact edges, the low bands are clean and the top band is not.
    expect(bands[0].nonlinear).toBe(false);
    expect(bands[bands.length - 1].nonlinear).toBe(true);
    expect(bands[bands.length - 1].verdict).toBe(BLA_NONLINEAR_TEXT);
    // Every band is either fully below or fully above the corner, so the
    // clean→dirty transition happens exactly once (no interleaving).
    const flags = bands.map((b) => b.nonlinear);
    expect(flags.indexOf(true)).toBe(flags.lastIndexOf(false) + 1);

    const text = summariseBlaVerdicts(bands);
    expect(text).toMatch(/^linear below \d+ Hz; nonlinearity dominates \d+–\d+ Hz/);
    expect(text).toContain('level-dependent, repeat at 2–3 amplitudes');
    // The named crossover is a BAND EDGE, not the true corner: a band whose
    // lines straddle 800 Hz is judged by its median, so the reported edge is
    // the edge of the last clean band (here ~1.25 kHz — the log split of
    // 20 Hz–5 kHz into 4 puts an edge at 316 Hz and the next at 1257 Hz, and
    // the 316–1257 band is mostly below the corner in log terms).
    const belowHz = Number(text.match(/linear below (\d+) Hz/)![1]);
    expect(belowHz).toBeGreaterThan(300);
    expect(belowHz).toBeLessThan(1300);
    expect(flags).toEqual([false, false, false, true]);
    // The dirty run ends at the top of the excited band.
    expect(text).toContain('5000 Hz');
  });

  test('distortion dominating everywhere names the whole band once', () => {
    const axis = logAxis(200);
    const bands = blaVerdicts(axis, sigmaFrom(axis, () => 1), sigmaFrom(axis, () => 1e-3));
    expect(bands.every((b) => b.nonlinear)).toBe(true);
    const text = summariseBlaVerdicts(bands);
    expect(text).toBe('nonlinearity dominates 20–5000 Hz — level-dependent, repeat at 2–3 amplitudes');
  });

  test('a clean top band above a dirty low band reads "linear above"', () => {
    const axis = logAxis(400);
    const sigmaN = sigmaFrom(axis, () => 1e-3);
    const sigmaNl = sigmaFrom(axis, (hz) => (hz < 800 ? 1e-2 : 1e-4));
    const text = summariseBlaVerdicts(blaVerdicts(axis, sigmaNl, sigmaN));
    expect(text).toMatch(/^nonlinearity dominates \d+–\d+ Hz; linear above \d+ Hz/);
  });

  test('the 2x variance threshold is what flips a band', () => {
    const axis = logAxis(40);
    const sigmaN = sigmaFrom(axis, () => 1);
    // ratio = 1.9 (below) then 2.1 (above) — bracketing BLA_NL_RATIO = 2.
    const below = blaVerdicts(axis, sigmaFrom(axis, () => Math.sqrt(1.9)), sigmaN, 1);
    const above = blaVerdicts(axis, sigmaFrom(axis, () => Math.sqrt(2.1)), sigmaN, 1);
    expect(below[0].nonlinear).toBe(false);
    expect(above[0].nonlinear).toBe(true);
  });

  test('medians ignore a single outlier line inside a band', () => {
    const axis = logAxis(101);
    const sigmaN = sigmaFrom(axis, () => 1e-3);
    // One huge distortion line (a resonance artefact) must not flip its band.
    const sigmaNl = sigmaFrom(axis, (_hz, i) => (i === 50 ? 10 : 1e-4));
    const bands = blaVerdicts(axis, sigmaNl, sigmaN);
    expect(bands.every((b) => !b.nonlinear)).toBe(true);
  });

  test('degenerate inputs do not crash', () => {
    expect(blaVerdicts(new Float64Array(0), new Float64Array(0), new Float64Array(0))).toEqual([]);
    // One line: one band, still judged.
    const one = blaVerdicts([100], [1e-2], [1e-3]);
    expect(one).toHaveLength(1);
    expect(one[0].f1).toBe(100);
    expect(one[0].f2).toBe(100);
    expect(one[0].nonlinear).toBe(true);
    // Two lines never yield four empty-ish bands.
    expect(blaVerdicts([100, 200], [1e-4, 1e-4], [1e-3, 1e-3])).toHaveLength(2);
    // All lines at one frequency (degenerate log span).
    expect(blaVerdicts([50, 50, 50], [1, 1, 1], [1, 1, 1])).toHaveLength(1);
    // Non-finite / non-positive entries are dropped, not propagated.
    const withJunk = blaVerdicts(
      [0, NaN, 100, 200], [1, 1, 1e-4, 1e-4], [1, 1, 1e-3, 1e-3],
    );
    expect(withJunk.length).toBeGreaterThan(0);
    expect(withJunk.every((b) => Number.isFinite(b.sigmaNl) && !b.nonlinear)).toBe(true);
    // Zero noise with zero distortion is linear; zero noise with distortion is not.
    expect(blaVerdicts([100], [0], [0], 1)[0].nonlinear).toBe(false);
    expect(blaVerdicts([100], [1], [0], 1)[0].ratio).toBe(Infinity);
    // Mismatched lengths read only the common prefix.
    expect(blaVerdicts([100, 200, 300], [1e-4], [1e-3], 1)).toHaveLength(1);
    expect(summariseBlaVerdicts([])).toBe('no usable σ data');
  });

  test('nBands is honoured and clamped to the line count', () => {
    const axis = logAxis(60);
    const nl = sigmaFrom(axis, () => 1e-4);
    const n = sigmaFrom(axis, () => 1e-3);
    expect(blaVerdicts(axis, nl, n, 6)).toHaveLength(6);
    expect(blaVerdicts(axis, nl, n, 1)).toHaveLength(1);
    expect(blaVerdicts([100, 200], [1e-4, 1e-4], [1e-3, 1e-3], 9)).toHaveLength(2);
    expect(blaVerdicts(axis, nl, n, 0)).toHaveLength(1);
  });
});

describe('worstBlaChannel', () => {
  test('picks the worst distortion-to-noise column, pairing σ from that column', () => {
    // 3 frequencies × 2 response channels, row-major.
    const nl = [
      1e-4, 1e-2,   // f0: channel 1 is the dirty one
      1e-2, 1e-4,   // f1: channel 0
      1e-4, 1e-4,   // f2: tie → first wins
    ];
    const nz = [
      1e-3, 2e-3,
      3e-3, 1e-3,
      1e-3, 1e-3,
    ];
    const out = worstBlaChannel(nl, nz, 2);
    expect(Array.from(out.sigmaNl)).toEqual([1e-2, 1e-2, 1e-4]);
    // The noise value comes from the SAME column as the chosen distortion.
    expect(Array.from(out.sigmaN)).toEqual([2e-3, 3e-3, 1e-3]);
  });

  test('single-column input passes straight through', () => {
    const out = worstBlaChannel([1, 2, 3], [4, 5, 6], 1);
    expect(Array.from(out.sigmaNl)).toEqual([1, 2, 3]);
    expect(Array.from(out.sigmaN)).toEqual([4, 5, 6]);
  });

  test('degenerate shapes yield an empty pair rather than throwing', () => {
    expect(worstBlaChannel([], [], 2).sigmaNl).toHaveLength(0);
    expect(worstBlaChannel([1], [1], 0).sigmaNl).toHaveLength(0);
    // NaN columns are skipped; a fully-NaN row reports NaN (dropped downstream).
    const out = worstBlaChannel([NaN, 1e-3], [NaN, 1e-3], 2);
    expect(out.sigmaNl[0]).toBe(1e-3);
    const allNaN = worstBlaChannel([NaN, NaN], [NaN, NaN], 2);
    expect(Number.isNaN(allNaN.sigmaNl[0])).toBe(true);
    expect(blaVerdicts([100], allNaN.sigmaNl, allNaN.sigmaN)).toEqual([]);
  });

  test('feeding the reduction into blaVerdicts flags a nonlinearity on ONE channel', () => {
    const axis = logAxis(200);
    const nl: number[] = [];
    const nz: number[] = [];
    for (const hz of axis) {
      nl.push(1e-4, hz > 800 ? 1e-2 : 1e-4);  // channel 1 misbehaves up top
      nz.push(1e-3, 1e-3);
    }
    const pair = worstBlaChannel(nl, nz, 2);
    const text = summariseBlaVerdicts(blaVerdicts(axis, pair.sigmaNl, pair.sigmaN));
    expect(text).toContain(BLA_NONLINEAR_TEXT);
    expect(text).toContain('linear below');
  });
});

describe('fmtVerdictHz', () => {
  test('rounds by magnitude', () => {
    expect(fmtVerdictHz(813.4)).toBe('813');
    expect(fmtVerdictHz(5000)).toBe('5000');
    expect(fmtVerdictHz(20)).toBe('20');
    expect(fmtVerdictHz(12.34)).toBe('12.3');
    expect(fmtVerdictHz(2.5)).toBe('2.5');
    expect(fmtVerdictHz(NaN)).toBe('?');
  });
});
