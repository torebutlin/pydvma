import { expect, test } from 'vitest';
import { prepareSvg, DARK_MAP } from '../../src/lib/export/figure';
import { CHROME } from '../../src/lib/plot/chrome';

// A miniature of the SVG PlotSurface.getSvgElement() serialises AFTER the
// Step-0 inline-attribute change: plot-bg + every axis element carry inline
// presentation attrs with the EXACT hexes PlotSurface emits
//   plot-bg fill   #ffffff   (--surface)
//   gridline stroke #eef0f4  (.grid literal)
//   tick/axlab fill #66708a  (--muted)
//   frame stroke   #e3e6eb   (--border)
// and the data line carries an inline stroke from the line palette (#2563eb),
// which the exporter must NEVER touch.
const svg =
  '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400">' +
  '<rect data-role="plot-bg" width="800" height="400" fill="#ffffff"/>' +
  '<line data-role="axis" stroke="#eef0f4"/>' + // gridline
  '<text data-role="axis" fill="#66708a">1</text>' + // tick label (muted)
  '<text data-role="axis" fill="#66708a">Time (s)</text>' + // axis label (muted)
  '<rect data-role="axis" stroke="#e3e6eb" fill="none"/>' + // frame
  '<path data-testid="plot-line" stroke="#2563eb" d="M0,0L10,10"/></svg>'; // data line

test('white keeps white bg', () => {
  expect(prepareSvg(svg, 'white')).toContain('fill="#ffffff"');
});

test('white leaves the SVG otherwise unchanged', () => {
  expect(prepareSvg(svg, 'white')).toBe(svg);
});

test('transparent strips bg fill only', () => {
  const o = prepareSvg(svg, 'transparent');
  expect(o).toMatch(/data-role="plot-bg"[^>]*fill="none"/);
  expect(o).toContain('stroke="#2563eb"'); // data line untouched
  expect(o).toContain('stroke="#eef0f4"'); // axis chrome untouched in transparent
  expect(o).toContain('fill="#66708a"'); // tick colour untouched in transparent
});

test('dark swaps bg AND recolours EVERY axis colour, not the data line', () => {
  const o = prepareSvg(svg, 'dark');
  expect(o).toMatch(/data-role="plot-bg"[^>]*fill="#1b2130"/);
  expect(o).not.toContain('fill="#ffffff"');
  expect(o).not.toContain('#eef0f4'); // gridline recoloured for dark
  expect(o).not.toContain('#e3e6eb'); // frame recoloured for dark
  expect(o).not.toContain('#66708a'); // tick/axis label recoloured for dark
  expect(o).toContain('stroke="#2563eb"'); // data line colour PRESERVED
});

test('dark recolours the tick/axis-label muted fill to a light colour', () => {
  const o = prepareSvg(svg, 'dark');
  // Every data-role="axis" text fill must move to the dark-mode light hex.
  expect(o).toMatch(/data-role="axis"[^>]*fill="#c7cede"/);
});

test('dark recolours the gridline stroke and frame stroke distinctly', () => {
  const o = prepareSvg(svg, 'dark');
  expect(o).toContain('stroke="#2a3346"'); // gridline dark
  expect(o).toContain('stroke="#3a4356"'); // frame dark
});

test('dark does not touch a data-role="plot-bg" that is already transparent-safe (idempotent hexes)', () => {
  // Running dark twice should be stable (no cascading replacement).
  const once = prepareSvg(svg, 'dark');
  const twice = prepareSvg(once, 'dark');
  expect(twice).toBe(once);
});

test('DARK_MAP keys are EXACTLY the CHROME values (single-source guard)', () => {
  // The chrome hexes live in one place (lib/plot/chrome). PlotSurface stamps
  // them inline; DARK_MAP is keyed off them. If someone changes a CHROME
  // colour but forgets to add its DARK_MAP entry, the dark export would ship
  // an un-recoloured (light) chrome element with NO error — this fails RED
  // instead. Compare as sets so ordering never matters.
  expect(new Set(Object.keys(DARK_MAP))).toEqual(new Set(Object.values(CHROME)));
});
