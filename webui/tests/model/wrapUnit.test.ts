import { expect, test } from 'vitest';
import { wrapUnit } from '../../src/lib/model/calibration';

// Known-answer vectors mirrored VERBATIM from
// `pydvma.analysis.UNIT_WRAP_VECTORS`. Python builds the STORED TfData unit
// strings and the browser builds the same strings for its own TF axis labels,
// so the rule is pinned rather than trusted. A change on either side must
// change both. (Moved here from tests/export/data.test.ts when the app's CSV
// writer went to the engine.)
const UNIT_WRAP_VECTORS: [string, string][] = [
  ['', ''],
  ['N', 'N'],
  ['Pa', 'Pa'],
  ['V', 'V'],
  ['g', 'g'],
  ['m', 'm'],
  ['s2', 's2'],
  ['m/s2', '(m/s2)'],
  ['m/s²', '(m/s²)'],
  ['m/s', '(m/s)'],
  ['N·m', '(N·m)'],
  ['-', '(-)'],
  ['(m/s2)', '(m/s2)'],
  ['(m/s2)/N', '((m/s2)/N)'],
  ['(a)/(b)', '((a)/(b))'],
];

test('wrapUnit matches python wrap_unit on every shared vector', () => {
  for (const [value, expected] of UNIT_WRAP_VECTORS) {
    expect(`${value} → ${wrapUnit(value)}`).toBe(`${value} → ${expected}`);
  }
});

test('wrapUnit is idempotent', () => {
  for (const [value] of UNIT_WRAP_VECTORS) {
    expect(wrapUnit(wrapUnit(value))).toBe(wrapUnit(value));
  }
});
