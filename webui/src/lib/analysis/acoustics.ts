// Basic acoustics maths: IEC 61672-1 A/C weighting and IEC 61260 base-10
// octave / third-octave band levels. Twin of pydvma/acoustics.py, pinned by
// ACOUSTICS_VECTORS in tests/analysis/acoustics.test.ts.

/** Reference sound pressure, 20 micropascals. */
export const P_REF = 20e-6;

export type Weighting = 'Z' | 'A' | 'C';
export type BandKind = 'octave' | 'third-octave';
export type BandRow = { centre: number; nominal: number; lower: number; upper: number };

const POLES = [20.6, 107.7, 737.9, 12194];
const NOMINAL_PATTERN = [1, 1.25, 1.6, 2, 2.5, 3.15, 4, 5, 6.3, 8];

function raw(f: number, w: 'A' | 'C'): number {
  const f2 = f * f;
  const [p1, p2, p3, p4] = POLES.map((p) => p * p);
  const num = w === 'A' ? p4 * f2 * f2 : p4 * f2;
  const den = w === 'A' ? (f2 + p1) * (f2 + p4) * Math.sqrt((f2 + p2) * (f2 + p3)) : (f2 + p1) * (f2 + p4);
  return 20 * Math.log10(num / den);
}

/** Weighting in dB, 0 at 1 kHz; 'Z' is 0; f <= 0 is -Infinity for A and C. */
export function weightingDb(f: number, w: Weighting): number {
  if (w === 'Z') return 0;
  if (!(f > 0)) return -Infinity;
  return raw(f, w) - raw(1000, w);
}

function nominal(n: number): number {
  const d = Math.floor(n / 10);
  const r = n - d * 10;
  return Number((NOMINAL_PATTERN[r] * 1000 * 10 ** d).toPrecision(4));
}

/** Base-10 bands whose edges lie inside [fLo, fHi]. */
export function bandTable(kind: BandKind, fLo: number, fHi: number): BandRow[] {
  const b = kind === 'octave' ? 1 : 3;
  const step = kind === 'octave' ? 3 : 1;
  const rows: BandRow[] = [];
  for (let x = -30 * b; x <= 30 * b; x++) {
    const centre = 1000 * 10 ** ((0.3 * x) / b);
    const lower = centre * 10 ** (-0.15 / b);
    const upper = centre * 10 ** (0.15 / b);
    if (lower >= fLo && upper <= fHi) rows.push({ centre, nominal: nominal(step * x), lower, upper });
  }
  return rows;
}

/**
 * Band powers from a power spectral DENSITY (unit^2/Hz): sum of
 * density * 10^(W/10) * df over bins with lower <= f < upper. Bands with fewer
 * than `minBins` bins are dropped. The 0 Hz bin has zero weight under A/C.
 */
export function bandLevels(
  f: ArrayLike<number>,
  density: ArrayLike<number>,
  kind: BandKind,
  w: Weighting = 'Z',
  minBins = 3,
): (BandRow & { power: number; nBins: number })[] {
  const n = f.length;
  if (n < 2) return [];
  const df = f[1] - f[0];
  const gain = new Float64Array(n);
  for (let i = 0; i < n; i++) gain[i] = f[i] > 0 ? 10 ** (weightingDb(f[i], w) / 10) : 0;
  const out: (BandRow & { power: number; nBins: number })[] = [];
  for (const row of bandTable(kind, Math.max(f[0], 0), f[n - 1] + df)) {
    let sum = 0;
    let nBins = 0;
    for (let i = 0; i < n; i++) {
      if (f[i] >= row.lower && f[i] < row.upper) {
        sum += density[i] * gain[i];
        nBins++;
      }
    }
    if (nBins >= minBins) out.push({ ...row, power: sum * df, nBins });
  }
  return out;
}
