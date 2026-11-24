import { readFileSync, statSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { FIGURE_FONT_METRICS as metrics } from '../../src/lib/export/fonts/figureFontMetrics';
import { FIGURE_FONT_FAMILY, FIGURE_FONT_STACK, measureText, missingGlyphs, FONT_ASCENT, FONT_DESCENT }
  from '../../src/lib/export/figureFont';

describe('figure font', () => {
  it('is the renamed subset, first in the stack', () => {
    expect(FIGURE_FONT_FAMILY).toBe('Pydvma Figure Serif');
    expect(metrics.family).toBe('Pydvma Figure Serif');
    expect(FIGURE_FONT_STACK.startsWith("'Pydvma Figure Serif'")).toBe(true);
    expect(FIGURE_FONT_STACK.endsWith('serif')).toBe(true);
  });
  it("covers every character the app's labels use", () => {
    const chars = 'γ²³⁴⁻−·µΩ°×é|()/,.%[]' + '0123456789' + 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ';
    expect(missingGlyphs([chars])).toEqual([]);
  });
  it('names unsupported characters once each, by code point', () => {
    expect(missingGlyphs(['漢字 漢', 'ok 😀'])).toEqual(['漢', '字', '😀']);
  });
  it('measures additively and in proportion to size', () => {
    expect(measureText('', 9)).toBe(0);
    expect(measureText('ab', 10)).toBeCloseTo(measureText('a', 10) + measureText('b', 10), 9);
    expect(measureText('x', 20)).toBeCloseTo(2 * measureText('x', 10), 9);
    expect(measureText('漢', 10)).toBeCloseTo(5, 9); // missing glyph: 0.5 em
  });
  it('has sane vertical metrics and a small file', () => {
    expect(FONT_ASCENT).toBeGreaterThan(0.6); expect(FONT_ASCENT).toBeLessThan(1.2);
    expect(FONT_DESCENT).toBeGreaterThan(0.1); expect(FONT_DESCENT).toBeLessThan(0.5);
    expect(statSync('src/lib/export/fonts/PydvmaFigureSerif.ttf').size).toBeLessThan(120_000);
    expect(readFileSync('src/lib/export/fonts/OFL.txt', 'utf8')).toContain('SIL OPEN FONT LICENSE Version 1.1');
  });
});
