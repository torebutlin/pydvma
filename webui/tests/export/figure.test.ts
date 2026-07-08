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
  '<text data-role="axis" class="tick" fill="#66708a">1</text>' + // tick label (muted)
  '<text data-role="axis" class="axlab" fill="#66708a">Time (s)</text>' + // axis label (muted)
  '<rect data-role="axis" stroke="#e3e6eb" fill="none"/>' + // frame
  '<path data-testid="plot-line" stroke="#2563eb" d="M0,0L10,10"/></svg>'; // data line

test('white keeps white bg', () => {
  expect(prepareSvg(svg, 'white')).toContain('fill="#ffffff"');
});

test('white stamps explicit fonts but leaves every colour + the structure intact', () => {
  const o = prepareSvg(svg, 'white');
  // Colours untouched (fidelity change is fonts only).
  expect(o).toContain('fill="#ffffff"'); // plot-bg
  expect(o).toContain('fill="#66708a"'); // tick + axlab
  expect(o).toContain('stroke="#eef0f4"'); // gridline
  expect(o).toContain('stroke="#e3e6eb"'); // frame
  expect(o).toContain('stroke="#2563eb"'); // data line
  // Fonts now explicit (the self-contained-SVG font fix).
  expect(o).toContain('font-family="ui-monospace, Menlo, monospace"');
  expect(o).toContain('font-family="system-ui, sans-serif"');
});

// --- Font fidelity (Task A3): the exported SVG must carry explicit inline
// font-family/size so PNG rasterisation + svg2pdf don't fall back to a
// default (16px Times under svg2pdf). Stamped by class onto <text> nodes,
// for EVERY background. ---

test('fonts: tick text gets the monospace stack at 10.5px', () => {
  const o = prepareSvg(svg, 'white');
  expect(o).toMatch(
    /<text font-size="10\.5px" font-family="ui-monospace, Menlo, monospace"[^>]*class="tick"/,
  );
});

test('fonts: axis-label text gets the body stack at 11.5px', () => {
  const o = prepareSvg(svg, 'white');
  expect(o).toMatch(
    /<text font-size="11\.5px" font-family="system-ui, sans-serif"[^>]*class="axlab"/,
  );
});

test('fonts: each stack ends in a generic family so svg2pdf maps to a core font (not Times)', () => {
  // svg2pdf's fontAliases: monospace→courier, sans-serif→helvetica; a stack
  // that ends in a generic family never falls through to the Times default.
  const o = prepareSvg(svg, 'white');
  expect(o).toContain('monospace"'); // tick stack ends in monospace
  expect(o).toContain('sans-serif"'); // axlab stack ends in sans-serif
});

test('fonts: non-text elements (lines, rects, paths) are never stamped', () => {
  const o = prepareSvg(svg, 'white');
  // The gridline <line> and data <path> must not gain a font attribute.
  expect(o).not.toMatch(/<line[^>]*font-/);
  expect(o).not.toMatch(/<path[^>]*font-/);
});

test('fonts: stamping is idempotent (re-running white is stable)', () => {
  const once = prepareSvg(svg, 'white');
  expect(prepareSvg(once, 'white')).toBe(once);
});

test('fonts: dark stamps fonts AND still recolours the chrome', () => {
  const o = prepareSvg(svg, 'dark');
  expect(o).toContain('font-family="ui-monospace, Menlo, monospace"');
  expect(o).toMatch(/data-role="axis"[^>]*fill="#c7cede"/); // dark recolour intact
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
