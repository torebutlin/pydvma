import { describe, expect, it } from 'vitest';
import { layoutPrintLegend, LEGEND_INSET_PT } from '../../src/lib/export/legendOverlay';
import { measureText } from '../../src/lib/export/figureFont';
import type { LegendStyle, PrintLegendEntry } from '../../src/lib/export/printFigure';

const frame = { x: 40, y: 5, w: 400, h: 200 };
const canvas = { w: 460, h: 250 };
const entry = (label: string, style: LegendStyle = 'line'): PrintLegendEntry => ({ label, color: '#2563eb', style, faded: false });

describe('layoutPrintLegend', () => {
  it('exports the 5.4 pt inset and sizes a one-entry card from the em sizes', () => {
    expect(LEGEND_INSET_PT).toBe(5.4);
    const l = layoutPrintLegend({ legend: { entries: [entry('a')], placement: { kind: 'position', x: 0.98, y: 0.98 } }, frame, canvas, belowTopPt: 240, points: [] })!;
    // padding 0.45 em each side, swatch 1.6 em, gap 0.5 em, the label; one 1.25 em row (9 pt type)
    expect(l.box.w).toBeCloseTo(2 * 0.45 * 9 + 1.6 * 9 + 0.5 * 9 + measureText('a', 9), 6);
    expect(l.box.h).toBeCloseTo(2 * 0.45 * 9 + 1.25 * 9, 6);
    expect(l.extraHeightPt).toBe(0);
    expect(l.texts).toEqual([expect.objectContaining({ text: 'a', role: 'legend' })]);
  });
  it('each corner preset sits inside the frame, at least 5.4 pt in', () => {
    for (const [x, y] of [[0.98, 0.98], [0.98, 0.02], [0.02, 0.02], [0.02, 0.98]]) {
      const l = layoutPrintLegend({ legend: { entries: [entry('noise 30s · ch_1/ch_0')], placement: { kind: 'position', x, y } }, frame, canvas, belowTopPt: 240, points: [] })!;
      expect(l.box.x).toBeGreaterThanOrEqual(frame.x + 5.4 - 1e-9);
      expect(l.box.y).toBeGreaterThanOrEqual(frame.y + 5.4 - 1e-9);
      expect(l.box.x + l.box.w).toBeLessThanOrEqual(frame.x + frame.w - 5.4 + 1e-9);
      expect(l.box.y + l.box.h).toBeLessThanOrEqual(frame.y + frame.h - 5.4 + 1e-9);
      expect(l.box.below).toBe(false);
    }
  });
  it('outside-right overhangs the right edge of the frame and stays inside the canvas', () => {
    const l = layoutPrintLegend({ legend: { entries: [entry('a')], placement: { kind: 'position', x: 1.02, y: 0.02 } }, frame, canvas, belowTopPt: 240, points: [] })!;
    expect(l.box.x + l.box.w).toBeGreaterThan(frame.x + frame.w);
    expect(l.box.x + l.box.w).toBeLessThanOrEqual(canvas.w);
  });
  it('swatches follow their style and faded rows fade', () => {
    const svg = layoutPrintLegend({ legend: { entries: [entry('l'), entry('d', 'dash'), entry('x', 'x'), entry('o', 'o'), entry('xl', 'xline'), { ...entry('f'), faded: true }], placement: { kind: 'position', x: 0.98, y: 0.98 } }, frame, canvas, belowTopPt: 240, points: [] })!.svg;
    expect(svg).toMatch(/stroke-dasharray="9\.6 7\.2"/);
    expect(svg).toMatch(/<circle/);
    expect((svg.match(/<path/g) ?? []).length).toBe(2);   // the × of 'x' and of 'xline'
    expect(svg).toContain('opacity="0.55"');
  });
  it('follows the restyle contract and escapes labels', () => {
    const svg = layoutPrintLegend({ legend: { entries: [entry('a<b & c')], placement: { kind: 'position', x: 0.98, y: 0.98 } }, frame, canvas, belowTopPt: 240, points: [] })!.svg;
    expect(svg).toMatch(/<rect data-role="legend-bg"[^>]*fill="#ffffff"[^>]*stroke="#c5cad3"/);
    expect(svg).toMatch(/<text data-role="axis"[^>]*font-size="36"[^>]*fill="#1d2027"/);
    expect(svg).toContain('a&lt;b &amp; c');
  });
  it('a legend taller than the frame adds columns, then goes below the axes', () => {
    const many = Array.from({ length: 40 }, (_, i) => entry(`set ${i} · ch_1/ch_0`));
    const l = layoutPrintLegend({ legend: { entries: many, placement: { kind: 'position', x: 0.98, y: 0.98 } }, frame: { ...frame, h: 80 }, canvas, belowTopPt: 240, points: [] })!;
    expect(l.box.below).toBe(true); expect(l.box.y).toBeGreaterThanOrEqual(240);
    expect(l.extraHeightPt).toBeGreaterThan(0); expect(l.svg).not.toContain('data-role="legend-bg"');
  });
  it('a card too wide in its wrap columns steps down to fewer columns before going below', () => {
    const ents = Array.from({ length: 12 }, (_, i) => entry(`run ${i} · a long descriptive name for this measurement · ch_1/ch_0`));
    const ws = ents.map((e) => measureText(e.label, 9));
    const maxW = frame.w - 2 * 5.4;
    // legendWrapColumns(12) is 2: two columns are too wide even with the shortest label; one column fits.
    expect(2 * 0.45 * 9 + 2 * (2.1 * 9 + Math.min(...ws)) + 1.2 * 9).toBeGreaterThan(maxW);
    expect(2 * 0.45 * 9 + 2.1 * 9 + Math.max(...ws)).toBeLessThanOrEqual(maxW);
    const l = layoutPrintLegend({ legend: { entries: ents, placement: { kind: 'position', x: 0.98, y: 0.98 } }, frame, canvas, belowTopPt: 240, points: [] })!;
    expect(l.box.below).toBe(false);
    expect(l.box.h).toBeCloseTo(2 * 0.45 * 9 + 12 * 1.25 * 9, 6);    // one column of 12 rows
    expect(l.box.w).toBeLessThanOrEqual(maxW);
    expect(l.svg).toContain('data-role="legend-bg"');
  });
  it('a card too wide and too tall at every column count still goes below', () => {
    const ents = Array.from({ length: 12 }, (_, i) => entry(`run ${i} · a long descriptive name for this measurement · ch_1/ch_0`));
    const l = layoutPrintLegend({ legend: { entries: ents, placement: { kind: 'position', x: 0.98, y: 0.98 } }, frame: { ...frame, h: 120 }, canvas, belowTopPt: 240, points: [] })!;
    expect(l.box.below).toBe(true);
  });
  it("'best' takes the emptiest corner, ties going se, ne, nw, sw", () => {
    const best = (points: [number, number][]) => layoutPrintLegend({ legend: { entries: [entry('a')], placement: { kind: 'best' } }, frame, canvas, belowTopPt: 240, points })!.box;
    const se = best([]);                                              // no points: se
    expect(se.x + se.w).toBeGreaterThan(frame.x + frame.w / 2); expect(se.y).toBeGreaterThan(frame.y + frame.h / 2);
    // inside the se card (~31 x 16 pt for 'a', 5.4 pt in from the corner)
    const crowdedSe = Array.from({ length: 50 }, (_, i) => [frame.x + frame.w - 10 - i * 0.5, frame.y + frame.h - 12] as [number, number]);
    const ne = best(crowdedSe);
    expect(ne.y).toBeLessThan(frame.y + frame.h / 2); expect(ne.x).toBeGreaterThan(frame.x + frame.w / 2);
  });
  it("'best' goes below when every corner covers data", () => {
    const grid: [number, number][] = [];
    for (let i = 0; i <= 100; i++) for (let j = 0; j <= 50; j++) grid.push([frame.x + i * 4, frame.y + j * 4]);
    const l = layoutPrintLegend({ legend: { entries: [entry('a'), entry('b')], placement: { kind: 'best' } }, frame, canvas, belowTopPt: 240, points: grid })!;
    expect(l.box.below).toBe(true);
  });
  it('a label wider than the canvas is shortened with an ellipsis, never drawn off it', () => {
    const long = 'x'.repeat(400);
    const l = layoutPrintLegend({ legend: { entries: [entry(long)], placement: { kind: 'position', x: 0.98, y: 0.98 } }, frame, canvas, belowTopPt: 240, points: [] })!;
    expect(l.box.x).toBeGreaterThanOrEqual(0); expect(l.box.x + l.box.w).toBeLessThanOrEqual(canvas.w);
    expect(l.texts[0].text.endsWith('…')).toBe(true);
  });
  it('no entries, no legend', () => {
    expect(layoutPrintLegend({ legend: { entries: [], placement: { kind: 'best' } }, frame, canvas, belowTopPt: 240, points: [] })).toBeNull();
  });
});
