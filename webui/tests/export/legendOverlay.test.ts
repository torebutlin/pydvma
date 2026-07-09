import { describe, expect, it } from 'vitest';
import { legendOverlaySvg } from '../../src/lib/export/legendOverlay';
import { CHROME } from '../../src/lib/plot/chrome';
import type { LegendEntry } from '../../src/lib/stores/selection';

const entry = (over: Partial<LegendEntry> = {}): LegendEntry => ({
  setId: 0, ch: 0, label: 'set · ch_0', color: '#2563eb', state: 'on', ...over,
});

describe('legendOverlaySvg (round-7d: legends in exported figures)', () => {
  it('follows the figure.ts restyle contract: plot-bg card, axis labels, roleless swatches', () => {
    const svg = legendOverlaySvg([entry()], { x: 0.02, y: 0.02 }, { w: 800, h: 400 });
    expect(svg).toContain(`data-role="plot-bg"`);
    expect(svg).toContain(`fill="${CHROME.bg}"`);
    expect(svg).toContain(`stroke="${CHROME.frame}"`);
    expect(svg).toContain(`data-role="axis"`);
    expect(svg).toContain(`fill="${CHROME.axis}"`);
    // The swatch keeps the DATA colour and carries no data-role.
    expect(svg).toMatch(/<line [^>]*stroke="#2563eb"/);
    expect(svg).not.toMatch(/<line [^>]*data-role/);
  });

  it("excludes 'off' rows (they exist on screen only to be clicked back on)", () => {
    const svg = legendOverlaySvg(
      [entry({ label: 'shown' }), entry({ ch: 1, label: 'hidden', state: 'off' })],
      { x: 0.02, y: 0.02 }, { w: 800, h: 400 },
    );
    expect(svg).toContain('shown');
    expect(svg).not.toContain('hidden');
    // All lines off → nothing at all.
    expect(legendOverlaySvg([entry({ state: 'off' })], { x: 0, y: 0 }, { w: 800, h: 400 })).toBe('');
  });

  it('fades faded rows and escapes XML in labels', () => {
    const svg = legendOverlaySvg(
      [entry({ state: 'fade', label: 'a<b & c>' })],
      { x: 0.02, y: 0.02 }, { w: 800, h: 400 },
    );
    expect(svg).toContain('opacity="0.55"');
    expect(svg).toContain('a&lt;b &amp; c&gt;');
    expect(svg).not.toContain('a<b');
  });

  it('anchors right/bottom past 0.5 (SE default pins flush) and clamps into the canvas', () => {
    const se = legendOverlaySvg([entry()], { x: 0.98, y: 0.98 }, { w: 800, h: 400 });
    const [, tx, ty] = se.match(/translate\(([\d.]+) ([\d.]+)\)/)!.map(Number);
    // The box's right/bottom edge sits near (but inside) the SE corner.
    expect(tx).toBeGreaterThan(800 * 0.6);
    expect(ty).toBeGreaterThan(400 * 0.6);
    const [, w, h] = se.match(/width="([\d.]+)" height="([\d.]+)"/)!.map(Number);
    expect(tx + w).toBeLessThanOrEqual(800);
    expect(ty + h).toBeLessThanOrEqual(400);
    // outside-right (x=1.02) clamps fully inside rather than clipping.
    const outside = legendOverlaySvg([entry()], { x: 1.02, y: 0.02 }, { w: 800, h: 400 });
    const [, ox] = outside.match(/translate\(([\d.]+) /)!.map(Number);
    const [, ow] = outside.match(/width="([\d.]+)"/)!.map(Number);
    expect(ox + ow).toBeLessThanOrEqual(800);
  });

  it('wraps into columns beyond 10 entries, like the on-screen card', () => {
    const many = Array.from({ length: 12 }, (_, i) => entry({ ch: i, label: `line_${i}` }));
    const svg = legendOverlaySvg(many, { x: 0.02, y: 0.02 }, { w: 800, h: 400 });
    const [, , h] = svg.match(/width="([\d.]+)" height="([\d.]+)"/)!.map(Number);
    // Two balanced columns: 6 rows tall, not 12.
    expect(h).toBeLessThan(12 * 15);
    expect(h).toBeGreaterThanOrEqual(6 * 15);
    // Both columns' x offsets appear.
    const xs = new Set([...svg.matchAll(/<line x1="([\d.]+)"/g)].map((m) => m[1]));
    expect(xs.size).toBe(2);
  });
});
