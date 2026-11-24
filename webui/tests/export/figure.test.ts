import { expect, test } from 'vitest';
import { prepareSvg, DARK_MAP } from '../../src/lib/export/figure';
import { CHROME, PRINT_CHROME } from '../../src/lib/plot/chrome';

// A miniature figure SVG: the plot-bg and every axis element carry inline
// presentation attrs with chrome hexes (here the screen CHROME ones, which
// DARK_MAP also covers; the print chrome is checked in printFigure.test.ts)
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
  '<text data-role="axis" class="tick" fill="#66708a">1</text>' + // tick label (muted)
  '<text data-role="axis" class="axlab" fill="#66708a">Time (s)</text>' + // axis label (muted)
  '<rect data-role="axis" stroke="#e3e6eb" fill="none"/>' + // frame
  '<path data-testid="plot-line" stroke="#2563eb" d="M0,0L10,10"/></svg>'; // data line

test('white keeps white bg', () => {
  expect(prepareSvg(svg, 'white')).toContain('fill="#ffffff"');
});

test('white returns the SVG unchanged (its fonts and colours are already inline)', () => {
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

test('DARK_MAP keys are EXACTLY the CHROME and PRINT_CHROME values (single-source guard)', () => {
  // The chrome hexes live in one place (lib/plot/chrome). PlotSurface and the
  // print renderer stamp them inline; DARK_MAP is keyed off them. If someone
  // changes a chrome colour but forgets to add its DARK_MAP entry, the dark
  // export would ship an un-recoloured (light) chrome element with NO error —
  // this fails RED instead. Compare as sets so ordering never matters (the two
  // share #ffffff, the background).
  expect(new Set(Object.keys(DARK_MAP)))
    .toEqual(new Set([...Object.values(CHROME), ...Object.values(PRINT_CHROME)]));
});

// --- Export is theme-INDEPENDENT (round-5 item 11, dark theme). ---
// The app's on-screen dark theme swaps CSS custom properties; PlotSurface's
// on-screen chrome follows them (so the plot goes dark on screen). But the
// SERIALISED figure carries FIXED inline CHROME hexes (never CSS variables),
// and prepareSvg is a pure string transform that reads no DOM. So the exported
// PNG/PDF/SVG is byte-identical no matter which theme the app is showing — the
// export background (white/transparent/dark) is chosen in the Export card, not
// inherited from the app theme. These tests pin that contract.

test('export is byte-identical regardless of the active app theme', () => {
  // Simulate the app being in dark theme by stamping data-theme on a fake
  // document root, then in light. prepareSvg must produce the same output for
  // the same input in both — proving no hidden theme coupling.
  const g = globalThis as Record<string, unknown>;
  const doc = { documentElement: { getAttribute: (_n: string) => 'dark', style: {} } };
  const saved = g.document;
  try {
    g.document = doc;
    const darkThemeWhite = prepareSvg(svg, 'white');
    const darkThemeDark = prepareSvg(svg, 'dark');
    (doc.documentElement as { getAttribute: (n: string) => string }).getAttribute = () => 'light';
    const lightThemeWhite = prepareSvg(svg, 'white');
    const lightThemeDark = prepareSvg(svg, 'dark');
    expect(lightThemeWhite).toBe(darkThemeWhite);
    expect(lightThemeDark).toBe(darkThemeDark);
  } finally {
    g.document = saved;
  }
});

test('the serialised chrome PlotSurface emits is pinned to the fixed light hexes', () => {
  // The exporter input carries CHROME.* inline (not app-theme tokens): a white
  // export returns exactly those light hexes, so a dark app theme can never
  // leak dark chrome into an exported figure.
  const white = prepareSvg(svg, 'white');
  expect(white).toContain(`fill="${CHROME.bg}"`); // #ffffff, not the dark --surface
  expect(white).toContain(`stroke="${CHROME.grid}"`); // #eef0f4
  expect(white).toContain(`stroke="${CHROME.frame}"`); // #e3e6eb
  expect(white).toContain(`fill="${CHROME.axis}"`); // #66708a
});

import { withEmbeddedFont, figureBytes } from '../../src/lib/export/figure';

test('withEmbeddedFont puts an @font-face for the figure family right after the root tag', () => {
  const out = withEmbeddedFont('<svg xmlns="http://www.w3.org/2000/svg" width="1pt"><rect/></svg>', 'QUJD');
  expect(out).toMatch(/^<svg[^>]*><style>@font-face\{font-family:'Pydvma Figure Serif';src:url\(data:font\/ttf;base64,QUJD\) format\('truetype'\)\}<\/style><rect\/>/);
});

test('figureBytes refuses an unknown format', async () => {
  await expect(figureBytes({} as never, 'gif' as never, 'white')).rejects.toThrow(/format/);
});

test('the legend card keeps its white fill when the canvas is transparent, and is recoloured in dark', () => {
  const card = '<rect data-role="legend-bg" x="1" y="1" width="50" height="20" fill="#ffffff" fill-opacity="0.92" stroke="#c5cad3"/>';
  const fig = svg.replace('</svg>', `${card}</svg>`);
  const t = prepareSvg(fig, 'transparent');
  expect(t).toMatch(/data-role="plot-bg"[^>]*fill="none"/);
  expect(t).toMatch(/data-role="legend-bg"[^>]*fill="#ffffff"/);
  const d = prepareSvg(fig, 'dark');
  expect(d).toMatch(/data-role="legend-bg"[^>]*fill="#1b2130"/);
  expect(d).not.toMatch(/data-role="legend-bg"[^>]*"#c5cad3"/i);
});
