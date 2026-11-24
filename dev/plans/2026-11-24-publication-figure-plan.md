# Publication-quality Save Figure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save Figure (and the damping panel's chart saves) write a figure laid out for print at a chosen width (160 mm by default): STIX Two Text at 10 pt labels and 9 pt numbers and legend, per-type aspect (16:9, Bode 4:3, Nyquist 1:1), a 600 dpi PNG tagged 600 dpi and a vector PDF with the font embedded. The on-screen legend anchors inside the axes frame and the coherence label stops being cropped.

**Architecture:** A pure print renderer (`printFigure.ts`) lays a figure out again in quarter-point units from the same `PlotModel`s the screen draws, through the same `buildPlot`. It returns an SVG string plus its measured text boxes and frames, so node tests can check the layout. The legend layout is a pure sibling (`legendOverlay.ts`, rewritten). Browser-only writers turn the SVG into PNG (canvas + `pHYs`) or PDF (jsPDF + svg2pdf, embedded font). App and DampingPanel only assemble a `PrintFigureInput` and deliver bytes.

**Tech Stack:** TypeScript, Svelte 5, vitest (node env), Playwright (from `webui/`), jsPDF 4 + svg2pdf.js 2, fontTools 4.55 (Python, for the one-off font subset).

**Spec:** `dev/plans/2026-11-24-publication-figure-design.md` (approved 2026-11-24). Mockups and the throwaway reference renderer are in `dev/mockups/2026-11-24-publication-figure/`: `mockup_A4.pdf`, `aspects_A4.pdf`, `damping_A4.pdf`, `make_aspects.py`, `make_damping.py`. Read the spec first; this plan argues from it.

## Global Constraints

- Work on `master` in `/Users/tore/Documents/GitHub/pydvma`. Commit each task with `git add <exact paths>`: never `git add -A`, `git stash`, `git reset` or a branch switch. Another session in this checkout is changing the damping-fit engine. Never touch `pydvma/analysis.py`, `pydvma/engine.py`, their tests, or the damping-fit docs. Push only when Tore asks.
- Before editing `DampingPanel.svelte`, `stores/damping.ts` or anything under `docs/`, run `git status --short <path>`. If another session has uncommitted changes there, stop and ask Tore (or the session that started you) rather than editing around them.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Pure web-UI change. No Python package code changes, so no engine-wheel rebuild. The only Python is the font-subsetting script, run once.
- Damping charts consume the store's decoded results as they are today: `DampingPeaksResult` {`startTime`, `threshold`, `sliceFreq`, `sliceMag`, `peaksFreq`, `peaksMag`, `fits[{tFit, realFit, realData, fPeak, Qn}]`} and `DampingBandsResult.bandData[{fc, edcT, edcDb, fitT, fitDb}]`. Depend on no new field.
- Values pinned by the spec:
  - Default width 160 mm, range 40–300 mm, quick picks 90 / 140 / 160 / 190.
  - Type: 10 pt axis labels, 9 pt tick numbers, 9 pt legend. Never shrunk.
  - Aspects (`FIGURE_ASPECTS`): default 16/9, bode 4/3, nyquist 1. The sonogram and damping charts are `'default'`.
  - Bode: data height split 0.6 / 0.4 with a 9 pt gap; one shared left/right margin; the top pane has gridlines but no x tick labels and no x label.
  - Units: viewBox in quarter points (`UNITS_PER_PT = 4`); root `width`/`height` in pt. `buildPlot` is called with the data rect in units.
  - Print chrome: text `#1d2027`, frame `#3f4652` at 0.6 pt, gridlines `#dfe2e7` at 0.4 pt, legend card border `#c5cad3` at 0.5 pt, background `#ffffff`. No tick marks.
  - Line width = on-screen px × 2/3 pt; dashes `2.4 1.8` pt; opacity as on screen.
  - Markers: half-size 2.2 pt; × stroked 0.7 pt; ○ radius 2.6 pt stroked 0.9 pt; in the line's colour.
  - Legend: inset 0.6 × 9 pt = 5.4 pt from the frame; card fill white at 0.92 opacity, rx 2 pt; faded rows at 0.55 opacity.
  - Best-corner ties go se, ne, nw, sw. Go below when the best corner covers more than `max(2, 0.5 %)` of the points.
  - Tick labels print U+2212 for minus.
  - PNG at 600 dpi: pixel width = `round(widthMm / 25.4 × 600)` (160 mm → 3780). `pHYs` = 23622 px/m on both axes, unit 1.
  - PDF page = figure pt size, vector, font embedded.
  - Font: STIX Two Text Regular (variable, instanced at `wght=400`), subset, family renamed `Pydvma Figure Serif`, SIL OFL 1.1. CSS stack `'Pydvma Figure Serif', 'STIX Two Text', 'Times New Roman', Times, serif`.
- Copy pinned by the spec or this plan:
  - Width-field note: `Laid out for this printed width: labels print at 10 pt.`
  - Damping legends: `Start slice, t = {startTime 2 dp} s` · `Picked peaks ({n})` · `Threshold {3 s.f.}` · `{fPeak 1 dp} Hz, Qn = {Qn 0 dp}` · band `{fc} Hz` (1 dp when fc < 10, else 0 dp) · `T60 fit (dashed)` in `#6b7280`.
  - Damping print y labels: `Normalised |S|`, `Re log(S)`, `EDC (dB)`.
- SVG attribute order (the tests' regexes rely on it):
  - `<path d fill stroke stroke-width opacity stroke-dasharray>`
  - `<text data-role class font-family font-size fill text-anchor (x y | transform)>`
  - `<rect data-role class x y width height fill fill-opacity stroke stroke-width rx>`
  - `<circle cx cy r fill stroke stroke-width opacity>`
  - `<image x y width height preserveAspectRatio image-rendering href xlink:href>`

  Omit an attribute rather than writing it empty.
- Gate before each commit: `cd webui && npm run check` (never bare `svelte-check`), `npx vitest run`. Run Playwright only from `webui/`, and only the specs the task names. Task 10 runs the full gate and `python -m mkdocs build --strict` from the repo root.

## Review Focus

1. **Log axes**: log-x frequency plots and the sonogram's log-y. Expect the print to show `buildPlot`'s decade ticks, with no tick label clipped at either edge. (Test in Task 2.)
2. **Very long set names or labels in the legend**, longer than the frame or the canvas. Expect them kept whole when they fit the canvas, and shortened with `…` only when they can't. Never drawn off the canvas. (Test in Task 4.)
3. **Non-ASCII user text**: accented names (in the font), CJK or emoji (not). Expect the PDF still written, with one info toast naming the missing characters by code point, and the PNG fine. (Tests in Tasks 1 and 6.)
4. **Extreme widths** (40 mm, 300 mm). Expect a positive data rect, every text inside the canvas, and type unchanged; height grows if needed. (Test in Task 2.)
5. **Transparent and dark backgrounds on the print SVG**. Expect every print chrome hex on `data-role` elements recoloured or cleared, and data colours and markers untouched. (Test in Task 2.)

---

## File structure

| File | Responsibility |
|---|---|
| `webui/scripts/subset-figure-font.py` (new) | One-off: instance, subset, rename STIX Two Text; write the TTF, OFL text and metrics JSON. |
| `webui/src/lib/export/fonts/PydvmaFigureSerif.ttf`, `OFL.txt`, `figureFontMetrics.ts` (new, generated, committed) | The embedded face, its licence, its advance widths (a typed TS module: the app tsconfig has no `resolveJsonModule`). |
| `webui/src/lib/export/figureFont.ts` (new) | Family name and stack, `measureText`, ascent/descent, `missingGlyphs`, lazy base64 loader. |
| `webui/src/lib/plot/chrome.ts` | Adds `PRINT_CHROME`. |
| `webui/src/lib/plot/build.ts` | `PlotLine` gains optional `marker` / `markerOnly` (type only; `buildPlot` unchanged). |
| `webui/src/lib/export/printFigure.ts` (new) | The pure print renderer: types, constants, `printFigureSvg`, `printTick`. |
| `webui/src/lib/export/legendOverlay.ts` (rewritten) | Pure print legend layout: position / best / below, swatches, columns, truncation. |
| `webui/src/lib/export/pngDpi.ts` (new) | `withPngDpi`: insert or replace a `pHYs` chunk. |
| `webui/src/lib/export/figure.ts` | `DARK_MAP` gains the print hexes; new `withEmbeddedFont`, `exportPrintPng`, `exportPrintPdf`, `figureBytes`. The screen-SVG `exportPng`/`exportPdf`/`stampFonts` go in Task 10. |
| `webui/src/lib/export/figureSave.ts` | `widthMm` in `figureOptions`, width constants, `clampFigureWidth`, `figureNotes`. |
| `webui/src/lib/export/viewFigure.ts` (new) | Pure: the active view → `PrintFigureInput`; `LegendEntry` → print entries. |
| `webui/src/lib/export/dampingFigure.ts` (new) | Pure: damping results → `PrintFigureInput`; the panel's domain helpers, moved here. |
| `webui/src/components/cards/ExportCard.svelte` | Figure width field + quick picks + note. |
| `webui/src/App.svelte` | `saveFigure` on the print path; `getSvg`/`appendExportLegend` removed; frame binding for the legend; `notifyDamping` takes `'info'`. |
| `webui/src/components/DampingPanel.svelte` | Chart saves on the print path with `figureOptions`; domains from `dampingFigure.ts`. |
| `webui/src/components/PlotSurface.svelte` | Bindable `frame` insets; coherence label inside the SVG. |
| `webui/src/components/Legend.svelte` | Card placed inside a frame box at the PlotSurface's insets; inset 8 px. |
| `webui/src/lib/plot/legendPos.ts` | Exports the `FrameInsets` type. |

Order: Tasks 1→8 in sequence (each consumes the one before). Task 9 depends on nothing in 2–8 and may run alongside them. Task 10 is last.

---

### Task 1: The embedded font and its metrics

**Files:**
- Create: `webui/scripts/subset-figure-font.py`
- Create (generated, committed): `webui/src/lib/export/fonts/PydvmaFigureSerif.ttf`, `webui/src/lib/export/fonts/OFL.txt`, `webui/src/lib/export/fonts/figureFontMetrics.ts`
- Create: `webui/src/lib/export/figureFont.ts`
- Test: `webui/tests/export/figureFont.test.ts`

**Interfaces:**
- Produces:
  - `FIGURE_FONT_FAMILY = 'Pydvma Figure Serif'`
  - `FIGURE_FONT_STACK = "'Pydvma Figure Serif', 'STIX Two Text', 'Times New Roman', Times, serif"`
  - `measureText(text: string, sizePt: number): number` (pt)
  - `FONT_ASCENT: number`, `FONT_DESCENT: number` (em, both positive)
  - `missingGlyphs(texts: Iterable<string>): string[]`
  - `loadFigureFontBase64(): Promise<string>`
- Generated module: `export const FIGURE_FONT_METRICS: { family: string; unitsPerEm: number; ascender: number; descender: number; advances: Record<string, number> } = {…};`, with a do-not-edit header naming the script. `advances` keys are decimal code points; `descender` is positive (font units). It's a TS module rather than JSON because `tsconfig.app.json` has no `resolveJsonModule` and nothing in `src` imports JSON.

- [ ] **Step 1: Write `subset-figure-font.py`.** It takes no arguments and runs from the repo root. Steps:
  1. Source is `/System/Library/Fonts/Supplemental/STIXTwoText.ttf`. Exit 1 with a message naming https://github.com/stipub/stixfonts (release 2.13) if it's absent.
  2. `fontTools.varLib.instancer.instantiateVariableFont(font, {'wght': 400})`.
  3. `fontTools.subset` with `hinting=False`, to these ranges: U+0020–007E, U+00A0–00FF, U+0100–017F, U+0370–03FF, U+2000–206F, U+2070–209F, U+2100–214F, U+2190–2193, U+2200–22FF.
  4. Rename name IDs 1/16 to `Pydvma Figure Serif`, 2/17 to `Regular`, 4 to `Pydvma Figure Serif Regular`, 6 to `PydvmaFigureSerif-Regular`. Set ID 10 to `Subset of STIX Two Text 2.13 (Regular instance), renamed under the SIL OFL 1.1.` Keep IDs 0, 13 and 14.
  5. Write the TTF.
  6. Write `OFL.txt`: a one-paragraph header (what the file is, the source path, the upstream URL), then name ID 0 (the copyright), then the OFL 1.1 text. Copy the licence from `os.path.join(matplotlib.get_data_path(), 'fonts/ttf/LICENSE_STIX')`, starting at the line `SIL OPEN FONT LICENSE Version 1.1`.
  7. Write `figureFontMetrics.ts` from the subset: its cmap, `hmtx` advances, `head.unitsPerEm`, and `hhea.ascent`/`-hhea.descent` (JSON-serialise the object into the template).
  8. Print the TTF size.

- [ ] **Step 2: Run it.**
Run: `python webui/scripts/subset-figure-font.py`
Expected: three files written; TTF size printed, under 120 KB.

- [ ] **Step 3: Write the failing tests** in `tests/export/figureFont.test.ts`:

```ts
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
```

- [ ] **Step 4: Run them to verify they fail.**
Run: `cd webui && npx vitest run tests/export/figureFont.test.ts`
Expected: FAIL, cannot resolve `figureFont`.

- [ ] **Step 5: Implement `figureFont.ts`.**
  - Import `FIGURE_FONT_METRICS` statically (a few KB). `measureText` sums the advances (0.5 em for a code point not in the table) × size / unitsPerEm, iterating by code point (`for…of`).
  - `missingGlyphs` ignores whitespace and returns unique characters in first-seen order.
  - `loadFigureFontBase64` gets the TTF's URL by a **dynamic** `await import('./fonts/PydvmaFigureSerif.ttf?url')` inside the function, so node tests and app start never touch it. It fetches the file once, base64-encodes the bytes in chunks and caches the promise.
  - Every export gets a docstring. The module header says where the font came from and that `scripts/subset-figure-font.py` regenerates all three files.

- [ ] **Step 6: Run the tests.**
Run: `cd webui && npx vitest run tests/export/figureFont.test.ts && npm run check`
Expected: PASS; check 0 errors.

- [ ] **Step 7: Commit.**

```bash
git add webui/scripts/subset-figure-font.py webui/src/lib/export/fonts/PydvmaFigureSerif.ttf webui/src/lib/export/fonts/OFL.txt webui/src/lib/export/fonts/figureFontMetrics.ts webui/src/lib/export/figureFont.ts webui/tests/export/figureFont.test.ts
git commit -m "feat(webui): embedded figure font (STIX Two Text subset) and its metrics"
```

---

### Task 2: The print renderer — single pane

**Files:**
- Modify: `webui/src/lib/plot/chrome.ts` (add `PRINT_CHROME`)
- Modify: `webui/src/lib/plot/build.ts:30-46` (`PlotLine`: `marker?: 'x' | 'o'`, `markerOnly?: boolean`, with docstrings saying only the print renderer reads them)
- Modify: `webui/src/lib/export/figure.ts` (`DARK_MAP` gains the print hexes)
- Create: `webui/src/lib/export/printFigure.ts`
- Test: `webui/tests/export/printFigure.test.ts`; modify `webui/tests/export/figure.test.ts` (the dark-map guard)

**Interfaces:**
- Consumes: `measureText`, `FONT_ASCENT`, `FONT_DESCENT`, `FIGURE_FONT_STACK` (Task 1); `buildPlot`, `PlotModel`, `PlotLine` (build.ts); `fmtTick`, `scaleLinear`, `scaleLog` (scales.ts).
- Produces (all exported from `printFigure.ts`):

```ts
export type FigureKind = 'default' | 'bode' | 'nyquist';
export const FIGURE_ASPECTS: Readonly<Record<FigureKind, number>>;   // 16/9, 4/3, 1
export const PRINT_TYPE: { readonly labelPt: 10; readonly tickPt: 9; readonly legendPt: 9 };
export const UNITS_PER_PT = 4;
export interface PrintPane { model: PlotModel; image?: string }
export type LegendStyle = 'line' | 'dash' | 'x' | 'o' | 'xline';
export interface PrintLegendEntry { label: string; color: string; style: LegendStyle; faded: boolean }
export type LegendPlacement = { kind: 'position'; x: number; y: number } | { kind: 'best' };
export interface PrintLegend { entries: readonly PrintLegendEntry[]; placement: LegendPlacement }
export interface PrintFigureInput { panes: PrintPane[]; kind: FigureKind; widthMm: number; legend?: PrintLegend | null }
export interface PtBox { x: number; y: number; w: number; h: number }               // pt, origin top-left
export interface PrintText { text: string; role: 'tick' | 'label' | 'legend'; box: PtBox }
export interface PrintFigure {
  svg: string; widthPt: number; heightPt: number; grown: boolean;
  texts: PrintText[]; frames: PtBox[]; legendBox: (PtBox & { below: boolean }) | null;
}
export function printFigureSvg(input: PrintFigureInput): PrintFigure;
export function printTick(v: number, span: number): string;                         // fmtTick, '-' → '−'
```

  `chrome.ts`: `export const PRINT_CHROME = { bg: '#ffffff', ink: '#1d2027', frame: '#3f4652', grid: '#dfe2e7', card: '#c5cad3' } as const;`

  `DARK_MAP` additions: ink → `#e6e9ef`, frame → `#aab2c0`, grid → `#2a3346`, card → `#3a4356` (bg is already `CHROME.bg`).

  This task handles one pane (`'default'`, `'nyquist'`) and ignores `legend`; Task 3 adds Bode and Task 4 the legend.

- [ ] **Step 1: Write the failing tests** in `tests/export/printFigure.test.ts`. Use a `tfModel(over)` helper: 501 points over x 0..500, a red `#dc2626` 1.5 px left line, plus a 1 px dashed right-axis coherence line. Defaults: `xRange [0, 500]`, `yRange [-72, 6]`, `y2Range [0, 1]`, labels `Frequency (Hz)` / `|H| (V/V, dB)` / `coherence γ²`. Also an `inside(fig)` helper asserting every `texts[i].box` lies within `[0, widthPt] × [0, heightPt]` (±0.01). Tests:

```ts
it('a default figure is 160 mm wide at 16:9 and not grown', () => {
  const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 });
  expect(f.widthPt).toBeCloseTo(453.54, 2); expect(f.heightPt).toBeCloseTo(453.54 * 9 / 16, 2);
  expect(f.grown).toBe(false);
  expect(f.svg).toMatch(/^<svg[^>]* width="453\.54pt" height="255\.12pt" viewBox="0 0 1814\.2 1020\.5"/);
});
it('Nyquist is 1:1 with a square frame', () => {
  const f = printFigureSvg({ panes: [{ model: { ...tfModel({ y2Range: undefined, y2Label: undefined }), squareAspect: true } }], kind: 'nyquist', widthMm: 90 });
  expect(f.heightPt).toBeCloseTo(f.widthPt, 2);
  expect(f.frames[0].w).toBeCloseTo(f.frames[0].h, 2);
});
it('type is 10 pt labels and 9 pt numbers, in the embedded face', () => {
  const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 });
  for (const t of f.svg.match(/<text[^>]*class="tick"[^>]*>/g)!) expect(t).toContain('font-size="36"');
  for (const t of f.svg.match(/<text[^>]*class="label"[^>]*>/g)!) expect(t).toContain('font-size="40"');
  expect(f.svg).toContain(`font-family="${FIGURE_FONT_STACK}"`);
});
it("prints buildPlot's ticks with a true minus", () => {
  const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 });
  const ticks = f.texts.filter((t) => t.role === 'tick').map((t) => t.text);
  expect(ticks).toEqual(expect.arrayContaining(['−60', '−40', '−20', '0', '100', '500', '0.5', '1']));
  expect(ticks.some((t) => t.includes('-'))).toBe(false);
});
it('every text sits inside the canvas, with a right axis and a last tick on the right edge', () => {
  inside(printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 }));
  inside(printFigureSvg({ panes: [{ model: tfModel({ xRange: [0, 1500], y2Range: undefined, y2Label: undefined }) }], kind: 'default', widthMm: 160 }));
});
it('the right-axis label reads top-to-bottom inside the canvas', () => {
  const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 });
  expect(f.svg).toMatch(/rotate\(90\)[^>]*>coherence γ²</);
  const lab = f.texts.find((t) => t.text === 'coherence γ²')!;
  expect(lab.box.x + lab.box.w).toBeLessThanOrEqual(f.widthPt);
});
it('a label too long for the plot grows the height, never the type', () => {
  const long = 'Power spectrum ((m/s²)², A-weighted, dB) re 1 (m/s²)² per band, averaged';
  const f = printFigureSvg({ panes: [{ model: tfModel({ yLabel: long }) }], kind: 'default', widthMm: 90 });
  expect(f.grown).toBe(true);
  expect(f.heightPt).toBeGreaterThan(f.widthPt * 9 / 16);
  const lab = f.texts.find((t) => t.text === long)!;
  expect(lab.box.h).toBeLessThanOrEqual(f.frames[0].h + 0.01);
  expect(f.svg).toMatch(new RegExp(`font-size="40"[^>]*>${long.replace(/[()]/g, '\\$&')}<`));
});
it('a 40 mm and a 300 mm figure still lay out inside their canvas', () => {
  for (const widthMm of [40, 300]) {
    const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm });
    expect(f.frames[0].w).toBeGreaterThan(0); inside(f);
  }
});
it("log axes print buildPlot's decade ticks, none clipped", () => {
  const f = printFigureSvg({ panes: [{ model: tfModel({ xScale: 'log', xRange: [1, 1000] }) }], kind: 'default', widthMm: 160 });
  expect(f.texts.filter((t) => t.role === 'tick').map((t) => t.text)).toEqual(expect.arrayContaining(['1', '10', '100', '1000']));
  inside(f);
});
it('line weights and dashes are scaled for print', () => {
  const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 });
  expect(f.svg).toMatch(/<path[^>]*stroke="#dc2626"[^>]*stroke-width="4"/);            // 1.5 px → 1 pt → 4 units
  expect(f.svg).toMatch(/<path[^>]*stroke-width="2\.7"[^>]*stroke-dasharray="9\.6 7\.2"/); // 1 px dashed
});
it('markers draw in the line colour, and markerOnly lines draw no stroke', () => {
  const m = tfModel({ y2Range: undefined, y2Label: undefined });
  m.lines = [{ x: [100, 200, 300], y: [-10, -20, -30], color: '#123456', opacity: 1, width: 1.4, dashed: false,
    yAxis: 'left', marker: 'o', markerOnly: true }];
  const f = printFigureSvg({ panes: [{ model: m }], kind: 'default', widthMm: 160 });
  expect(f.svg.match(/<circle[^>]*stroke="#123456"[^>]*r="10\.4"|<circle[^>]*r="10\.4"[^>]*stroke="#123456"/g)).toHaveLength(3);
  expect(f.svg).not.toMatch(/<path[^>]*stroke="#123456"/);
});
it('a pane image fills the data rect and replaces the gridlines', () => {
  const f = printFigureSvg({ panes: [{ model: { ...tfModel(), lines: [] }, image: 'data:image/png;base64,AAAA' }], kind: 'default', widthMm: 160 });
  const fr = f.frames[0];
  expect(f.svg).toContain(`<image x="${(fr.x * 4).toFixed(1)}" y="${(fr.y * 4).toFixed(1)}" width="${(fr.w * 4).toFixed(1)}" height="${(fr.h * 4).toFixed(1)}"`);
  expect(f.svg).toContain('xlink:href="data:image/png;base64,AAAA"');
  expect(f.svg).not.toContain('class="grid"');
});
it('an empty model still draws its axes', () => {
  const f = printFigureSvg({ panes: [{ model: { lines: [], xLabel: 'Time (s)', yLabel: 'Amplitude', xRange: null, yRange: null } }], kind: 'default', widthMm: 160 });
  expect(f.frames).toHaveLength(1);
});
it('dark and transparent restyle every print chrome hex and keep data colours', () => {
  const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 });
  const dark = prepareSvg(f.svg, 'dark');
  for (const hex of [PRINT_CHROME.ink, PRINT_CHROME.frame, PRINT_CHROME.grid])
    expect(dark).not.toMatch(new RegExp(`data-role="(axis|plot-bg)"[^>]*"${hex}"`, 'i'));
  expect(dark).toContain('stroke="#dc2626"');
  expect(prepareSvg(f.svg, 'transparent')).toMatch(/data-role="plot-bg"[^>]*fill="none"/);
});
```

  In `figure.test.ts`, replace the `keys(DARK_MAP) === values(CHROME)` assertion with "equals the de-duplicated union of `values(CHROME)` and `values(PRINT_CHROME)`".

- [ ] **Step 2: Run them to verify they fail.**
Run: `cd webui && npx vitest run tests/export/printFigure.test.ts tests/export/figure.test.ts`
Expected: FAIL (`printFigure` missing; the guard fails on the new hexes once `PRINT_CHROME` exists).

- [ ] **Step 3: Add `PRINT_CHROME`, the `PlotLine` marker fields and the `DARK_MAP` entries.**

- [ ] **Step 4: Implement `printFigureSvg` for one pane.** Do the layout in pt; emit coordinates × `UNITS_PER_PT` with one decimal, and `width`/`height` in pt with two. Algorithm, taken from `make_aspects.py` `figure_svg`/`pane_svg` (read them):
  1. W = widthMm / 25.4 × 72; H0 = W / `FIGURE_ASPECTS[kind]`.
  2. **Gaps:** pad = 0.4 × tick, lpad = 0.35 × label, edge = 3 pt.
  3. **Left margin:** edge + label + lpad + widest y tick label + pad.
  4. **Right margin:** with a right axis, edge + label + lpad + widest y2 tick label + pad. Without one, 0.5 × tick + 2.
  5. Raise the right margin to at least half the last x tick label's width + 1 when that tick sits on the right edge. Do the same for the left margin and the first x tick label.
  6. **Top:** 0.6 × tick. **Bottom:** pad + tick + lpad + label + edge.
  7. **Grow:** if `measureText(yLabel or y2Label, 10) + 2 × tick` exceeds the data height, raise the data height to it and set `grown`.
  8. **Squares:** a `squareAspect` pane centres a square of side min(w, h).
  9. **Build:** `buildPlot(model, pw × 4, ph × 4)` gives the ticks and paths, already in units relative to the data rect. Wrap them in `<g transform="translate(ox oy)" clip-path>`.
  10. **Markers:** map the line's raw x/y through `scaleLinear`/`scaleLog` on `built.xDomain`/`yDomain` (log when `xScale === 'log'` / `yLogAxis`, never for `squareAspect`), skipping points outside the domain. Draw `<circle>`s or a single × `<path>`. A `markerOnly` line draws no path.
  11. **Strokes:** width × 2/3 × 4 units; dashes `9.6 7.2`.
  12. **Text:** every `<text>` carries `data-role="axis"`, `class="tick"` or `"label"`, `font-family`, `font-size` and `fill="#1d2027"`. Unrotated labels use `x`, `y` and `text-anchor`. The y label uses `transform="translate(x y) rotate(-90)"` at x = edge + 0.8 × label; the y2 label uses `rotate(90)` at W − edge − 0.8 × label.
  13. **Text boxes:** record each text's pt box from `measureText` and `FONT_ASCENT`/`FONT_DESCENT`, swapping w and h for rotated text.
  14. **Root and chrome:** the root carries `xmlns` and `xmlns:xlink`. First comes a full-canvas `<rect data-role="plot-bg" fill="#ffffff">`. Gridlines are `<line data-role="axis" class="grid" stroke="#dfe2e7" stroke-width="1.6">`, skipped when the pane has an `image`. The frame is `<rect data-role="axis" class="frame" fill="none" stroke="#3f4652" stroke-width="2.4">`. An image is `<image … preserveAspectRatio="none" image-rendering="pixelated">` with both `href` and `xlink:href`, drawn before the gridlines' place.
  15. **Return** `frames` and `texts`; `legendBox: null` for now.

  `printTick(v, span)` is `fmtTick(v, span).replace('-', '−')`.

- [ ] **Step 5: Run the tests.**
Run: `cd webui && npx vitest run tests/export && npm run check`
Expected: PASS; check 0 errors.

- [ ] **Step 6: Commit.**

```bash
git add webui/src/lib/plot/chrome.ts webui/src/lib/plot/build.ts webui/src/lib/export/figure.ts webui/src/lib/export/printFigure.ts webui/tests/export/printFigure.test.ts webui/tests/export/figure.test.ts
git commit -m "feat(webui): print renderer lays a plot out in points for publication"
```

---

### Task 3: Bode — two panes

**Files:**
- Modify: `webui/src/lib/export/printFigure.ts`
- Test: `webui/tests/export/printFigure.test.ts`

**Interfaces:**
- Consumes: Task 2's renderer.
- Produces: `export const BODE_SPLIT = [0.6, 0.4] as const; export const PANE_GAP_PT = 9;`. `printFigureSvg` accepts two panes for `kind: 'bode'` (first = magnitude, second = phase).

- [ ] **Step 1: Write the failing tests** (`phaseModel()` = the same x, a phase line, `Phase (deg)`, `yRange [-180, 180]`, no right axis):

```ts
it('Bode is 4:3 with a 60/40 split and a 9 pt gap', () => {
  const f = printFigureSvg({ panes: [{ model: tfModel() }, { model: phaseModel() }], kind: 'bode', widthMm: 160 });
  expect(f.heightPt).toBeCloseTo(f.widthPt * 3 / 4, 1); expect(f.grown).toBe(false);
  expect(f.frames[0].h / f.frames[1].h).toBeCloseTo(1.5, 3);
  expect(f.frames[1].y - (f.frames[0].y + f.frames[0].h)).toBeCloseTo(9, 3);
});
it('Bode frames share their left and right edges', () => {
  const f = printFigureSvg({ panes: [{ model: tfModel() }, { model: phaseModel() }], kind: 'bode', widthMm: 160 });
  expect(f.frames[1].x).toBeCloseTo(f.frames[0].x, 6); expect(f.frames[1].w).toBeCloseTo(f.frames[0].w, 6);
});
it("Bode's top pane keeps its gridlines but prints no x numbers or x label", () => {
  const f = printFigureSvg({ panes: [{ model: tfModel() }, { model: phaseModel() }], kind: 'bode', widthMm: 160 });
  expect(f.texts.filter((t) => t.text === 'Frequency (Hz)')).toHaveLength(1);
  // x tick labels are the ones horizontally over the frame (y ticks sit left of it, y2 ticks right)
  const fr = f.frames[0];
  const xTicks = f.texts.filter((t) => t.role === 'tick' && t.box.x + t.box.w > fr.x && t.box.x < fr.x + fr.w);
  expect(xTicks.map((t) => t.text)).toEqual(['0', '100', '200', '300', '400', '500']);
  for (const t of xTicks) expect(t.box.y).toBeGreaterThan(f.frames[1].y + f.frames[1].h);
  expect((f.svg.match(/class="grid"/g) ?? []).length).toBeGreaterThan(12);
  inside(f);
});
```

- [ ] **Step 2: Run them to verify they fail.**
Run: `cd webui && npx vitest run tests/export/printFigure.test.ts`
Expected: FAIL on the three Bode tests.

- [ ] **Step 3: Generalise the layout to a stack of panes.**
  - Margins are maxima over all panes.
  - The data height splits by `BODE_SPLIT` (one pane: 1) with `PANE_GAP_PT` between panes.
  - The grow rule applies per pane: need / share.
  - Every pane but the last skips its x tick labels and x label.

- [ ] **Step 4: Run the tests.**
Run: `cd webui && npx vitest run tests/export && npm run check`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add webui/src/lib/export/printFigure.ts webui/tests/export/printFigure.test.ts
git commit -m "feat(webui): print Bode as two aligned panes, 4:3, magnitude over phase"
```

---

### Task 4: The print legend

**Files:**
- Rewrite: `webui/src/lib/export/legendOverlay.ts`. The old `legendOverlaySvg` goes; its only caller, App's `appendExportLegend`, is removed in Task 7.
- Modify: `webui/src/lib/export/printFigure.ts` (collect points, lay out the legend, grow for a legend below)
- Rewrite test: `webui/tests/export/legendOverlay.test.ts`; extend `webui/tests/export/printFigure.test.ts`

**Interfaces:**
- Consumes: `PrintLegend`, `PtBox`, `PrintText` (Task 2); `measureText`, `FIGURE_FONT_STACK` (Task 1); `legendWrapColumns` (legendGrid.ts); `PRINT_CHROME`, `CHROME` (chrome.ts).
- Produces:

```ts
export const LEGEND_INSET_PT = 5.4;
export interface LegendLayoutArgs {
  legend: PrintLegend; frame: PtBox; canvas: { w: number; h: number };
  belowTopPt: number;                 // y where a below-axes block may start (under the x label)
  points: ReadonlyArray<readonly [number, number]>;  // plotted points in pt (first pane), for 'best'
}
export interface LegendLayout { svg: string; box: PtBox & { below: boolean }; extraHeightPt: number; texts: PrintText[] }
export function layoutPrintLegend(a: LegendLayoutArgs): LegendLayout | null;   // null when no entries
```

- [ ] **Step 1: Write the failing tests** in `legendOverlay.test.ts`, with `frame = { x: 40, y: 5, w: 400, h: 200 }`, `canvas = { w: 460, h: 250 }`, `belowTopPt = 240`, and `entry(label, style = 'line')`:

```ts
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
it('outside-right sits right of the frame and inside the canvas', () => {
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
  expect(svg).toMatch(/<rect data-role="plot-bg"[^>]*fill="#ffffff"[^>]*stroke="#c5cad3"/);
  expect(svg).toMatch(/<text data-role="axis"[^>]*font-size="36"[^>]*fill="#1d2027"/);
  expect(svg).toContain('a&lt;b &amp; c');
});
it('a legend taller than the frame adds columns, then goes below the axes', () => {
  const many = Array.from({ length: 40 }, (_, i) => entry(`set ${i} · ch_1/ch_0`));
  const l = layoutPrintLegend({ legend: { entries: many, placement: { kind: 'position', x: 0.98, y: 0.98 } }, frame: { ...frame, h: 80 }, canvas, belowTopPt: 240, points: [] })!;
  expect(l.box.below).toBe(true); expect(l.box.y).toBeGreaterThanOrEqual(240);
  expect(l.extraHeightPt).toBeGreaterThan(0); expect(l.svg).not.toContain('data-role="plot-bg"');
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
```

  And in `printFigure.test.ts`:

```ts
it('a legend below the axes grows the figure and stays on the canvas', () => {
  const entries = Array.from({ length: 30 }, (_, i) => ({ label: `mode ${i}, Qn = 100`, color: '#2563eb', style: 'xline' as const, faded: false }));
  const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 90, legend: { entries, placement: { kind: 'best' } } });
  expect(f.legendBox!.below).toBe(true); expect(f.grown).toBe(true); inside(f);
  expect(f.legendBox!.y + f.legendBox!.h).toBeLessThanOrEqual(f.heightPt + 0.01);
});
it('the Bode legend sits in the magnitude pane', () => {
  const f = printFigureSvg({ panes: [{ model: tfModel() }, { model: phaseModel() }], kind: 'bode', widthMm: 160,
    legend: { entries: [{ label: 'a', color: '#dc2626', style: 'line', faded: false }], placement: { kind: 'position', x: 0.98, y: 0.98 } } });
  expect(f.legendBox!.y + f.legendBox!.h).toBeLessThanOrEqual(f.frames[0].y + f.frames[0].h);
});
```

- [ ] **Step 2: Run them to verify they fail.**
Run: `cd webui && npx vitest run tests/export/legendOverlay.test.ts tests/export/printFigure.test.ts`
Expected: FAIL (`layoutPrintLegend` missing).

- [ ] **Step 3: Implement `layoutPrintLegend`** following `make_aspects.py`'s `legend_svg` / `legend_below`. Sizes are in em of the 9 pt legend type.
  - **Sizes:** swatch 1.6 em, swatch-to-text gap 0.5 em, card padding 0.45 em, row 1.25 em, column gap 1.2 em (card) or 1.6 em (below).
  - **Columns:** start at `legendWrapColumns(n)`. While the card is taller than `frame.h − 2 × inset` and one more column still fits `frame.w − 2 × inset`, add a column. If it's still too tall, or wider than `frame.w − 2 × inset` (long labels), go below (for `position` and `best` alike). Outside-right is the exception: it may be as wide as the canvas allows.
  - **Position:** the right edge is at `frame.x + x × frame.w` when x > 0.5, else the left edge is there; the same for y. Clamp into the frame at the inset when x ≤ 1. For x > 1 (outside-right), clamp into the canvas.
  - **Best:** try se, ne, nw, sw at the inset. Count `points` inside each box and take the fewest (ties in that order). Go below if the count exceeds `max(2, 0.005 × points.length)`.
  - **Below:** an unboxed block at `belowTopPt + 0.3 em` with as many equal columns as fit `frame.w`, centred on the frame, then clamped into `[edge, canvas.w − edge]`. `extraHeightPt` = rows × row + 0.6 em.
  - **Truncation:** a label wider than `canvas.w − 2 × edge − swatch − gap − 2 × padding` is shortened to fit, character by character, with a trailing `…`.
  - **Markup:** the card is `<rect data-role="plot-bg" fill="#ffffff" fill-opacity="0.92" stroke="#c5cad3" stroke-width="2" rx="8">`. Labels are `<text data-role="axis" class="legend" font-family font-size="36" fill="#1d2027">`. Swatches carry no data-role. A line-style swatch (`line`, `dash`, `xline`) is a `<line>` 1.6 em long, stroked 1.6 pt (6.4 units) in the entry's colour, as the mockup. A × is one `<path>` and a ○ a `<circle>`, at the marker sizes from Global Constraints, centred on the swatch.

  In `printFigureSvg`:
  1. Collect the first pane's points in pt: every vertex of each built path (parse `[ML](x),(y)` pairs, offset by the frame origin, ÷ 4) plus every marker centre.
  2. Call `layoutPrintLegend` with `belowTopPt` = the bottom of the last pane's x label + 0.3 em.
  3. Add `extraHeightPt` to the height, setting `grown` when it's > 0, and append the legend's svg and texts.

- [ ] **Step 4: Run the tests.**
Run: `cd webui && npx vitest run tests/export && npm run check`
Expected: PASS. `npm run check` will flag App's import of the removed `legendOverlaySvg`: keep a thin deprecated shim with the old signature, `legendOverlaySvg(entries: readonly LegendEntry[], pos: { x: number; y: number }, canvas: { w: number; h: number }): string`, returning `''`, with a comment saying Task 7 removes it and App's use with it. Until then a screen-path export simply has no legend. That keeps this commit green.

- [ ] **Step 5: Commit.**

```bash
git add webui/src/lib/export/legendOverlay.ts webui/src/lib/export/printFigure.ts webui/tests/export/legendOverlay.test.ts webui/tests/export/printFigure.test.ts
git commit -m "feat(webui): print legend inside the axes frame, best corner or below the axes"
```

---

### Task 5: PNG and PDF writers

**Files:**
- Create: `webui/src/lib/export/pngDpi.ts`
- Modify: `webui/src/lib/export/figure.ts`
- Test: `webui/tests/export/pngDpi.test.ts`; extend `webui/tests/export/figure.test.ts`

**Interfaces:**
- Consumes: `PrintFigure` (Task 2); `loadFigureFontBase64`, `FIGURE_FONT_FAMILY` (Task 1); `prepareSvg`, `DARK_BG` (figure.ts); `FigureFormat` (figureSave.ts, type import).
- Produces:

```ts
// pngDpi.ts
export function withPngDpi(png: Uint8Array, dpi: number): Uint8Array;   // insert or replace pHYs right after IHDR; throws on non-PNG
// figure.ts
export function withEmbeddedFont(svg: string, fontBase64: string): string;  // <style>@font-face …</style> right after the root tag
export async function exportPrintPng(fig: PrintFigure, mode: BackgroundMode, dpi?: number): Promise<Uint8Array>;  // dpi default 600
export async function exportPrintPdf(fig: PrintFigure, mode: BackgroundMode): Promise<Uint8Array>;
export async function figureBytes(fig: PrintFigure, format: FigureFormat, mode: BackgroundMode): Promise<Uint8Array>;
```

- [ ] **Step 1: Write the failing tests.** In `pngDpi.test.ts`, use the 1×1 PNG `iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=`:

```ts
it('inserts a 600 dpi pHYs chunk right after IHDR', () => {
  const out = withPngDpi(png, 600);
  const dv = new DataView(out.buffer, out.byteOffset);
  expect(dv.getUint32(33)).toBe(9);
  expect(new TextDecoder().decode(out.subarray(37, 41))).toBe('pHYs');
  expect(dv.getUint32(41)).toBe(23622); expect(dv.getUint32(45)).toBe(23622); expect(out[49]).toBe(1);
  expect(dv.getUint32(50)).toBe(0x14944341);                 // CRC-32 of 'pHYs' + data
  expect(out.length).toBe(png.length + 21);
});
it('replaces an existing pHYs instead of adding a second', () => {
  const twice = withPngDpi(withPngDpi(png, 300), 600);
  expect(new TextDecoder('latin1').decode(twice).split('pHYs')).toHaveLength(2);
  expect(new DataView(twice.buffer, twice.byteOffset).getUint32(41)).toBe(23622);
});
it('refuses bytes that are not a PNG', () => {
  expect(() => withPngDpi(new Uint8Array([1, 2, 3]), 600)).toThrow(/not a PNG/);
});
```

  In `figure.test.ts`:

```ts
it('withEmbeddedFont puts an @font-face for the figure family right after the root tag', () => {
  const out = withEmbeddedFont('<svg xmlns="http://www.w3.org/2000/svg" width="1pt"><rect/></svg>', 'QUJD');
  expect(out).toMatch(/^<svg[^>]*><style>@font-face\{font-family:'Pydvma Figure Serif';src:url\(data:font\/ttf;base64,QUJD\) format\('truetype'\)\}<\/style><rect\/>/);
});
```

- [ ] **Step 2: Run them to verify they fail.**
Run: `cd webui && npx vitest run tests/export/pngDpi.test.ts tests/export/figure.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement.**
  - **`withPngDpi`:** check the 8-byte signature; walk the chunks; drop any `pHYs`; write the new one after `IHDR`. Use a table-driven CRC-32 (a local function, no dependency).
  - **`exportPrintPng`:** `prepareSvg(fig.svg, mode)` → `withEmbeddedFont(…, await loadFigureFontBase64())` → Blob URL → `Image`. Await `img.decode()` after `onload`, so the embedded face is ready before drawing. Then a canvas of `round(widthPt / 72 × dpi)` × `round(heightPt / 72 × dpi)`, the white/dark pre-fill as today, `drawImage` to the full canvas, `toBlob('image/png')` → bytes → `withPngDpi(bytes, dpi)`.
  - **`exportPrintPdf`:** dynamic-import jsPDF and svg2pdf (as today). `new jsPDF({ unit: 'pt', format: [w, h], orientation: w >= h ? 'landscape' : 'portrait', compress: true })`, then `addFileToVFS('PydvmaFigureSerif.ttf', b64)` and `addFont('PydvmaFigureSerif.ttf', FIGURE_FONT_FAMILY, 'normal', 'Identity-H')`. Pre-fill the background as today; parse `prepareSvg(fig.svg, mode)` (no `<style>`: svg2pdf finds the family through jsPDF's font list); `doc.svg(node, { x: 0, y: 0, width: w, height: h })`; output an arraybuffer.
  - **`figureBytes`:** dispatch on the format.
  - Every new export gets a docstring stating the hardware-free facts (600 dpi = 23622 px/m; the PDF page is the figure's pt size).

- [ ] **Step 4: Run the tests.**
Run: `cd webui && npx vitest run tests/export && npm run check`
Expected: PASS. The browser paths are proven by Task 7's Playwright checks.

- [ ] **Step 5: Commit.**

```bash
git add webui/src/lib/export/pngDpi.ts webui/src/lib/export/figure.ts webui/tests/export/pngDpi.test.ts webui/tests/export/figure.test.ts
git commit -m "feat(webui): 600 dpi PNG and font-embedded PDF writers for print figures"
```

---

### Task 6: Figure width option, save notes, Export card

**Files:**
- Modify: `webui/src/lib/export/figureSave.ts`
- Modify: `webui/src/components/cards/ExportCard.svelte` (the figure group around L270–290)
- Test: `webui/tests/export/figureSave.test.ts`

**Interfaces:**
- Consumes: `missingGlyphs` (Task 1); `PrintFigure` (Task 2, type).
- Produces:

```ts
export interface FigureOptions { png: boolean; pdf: boolean; bg: BackgroundMode; widthMm: number }
export const DEFAULT_FIGURE_WIDTH_MM = 160;
export const FIGURE_WIDTH_PRESETS = [90, 140, 160, 190] as const;
export const FIGURE_WIDTH_RANGE = [40, 300] as const;
export function clampFigureWidth(v: unknown): number;
export function figureNotes(fig: Pick<PrintFigure, 'grown' | 'texts'>, formats: readonly FigureFormat[]):
  { grown: string | null; glyphs: string | null };
```

- [ ] **Step 1: Write the failing tests:**

```ts
it('figure options start PNG on white at 160 mm', () => {
  expect(get(figureOptions)).toEqual({ png: true, pdf: false, bg: 'white', widthMm: 160 });
});
it('clampFigureWidth keeps the width in 40–300 mm and falls back to 160', () => {
  expect(clampFigureWidth(90)).toBe(90); expect(clampFigureWidth('120')).toBe(120);
  expect(clampFigureWidth(20)).toBe(40); expect(clampFigureWidth(500)).toBe(300);
  expect(clampFigureWidth(NaN)).toBe(160); expect(clampFigureWidth('')).toBe(160); expect(clampFigureWidth(undefined)).toBe(160);
});
it('figureNotes says when a figure grew, and names glyphs the PDF lacks only when writing a PDF', () => {
  const t = (text: string) => ({ text, role: 'legend' as const, box: { x: 0, y: 0, w: 1, h: 1 } });
  expect(figureNotes({ grown: true, texts: [] }, ['png']).grown)
    .toBe('laid out taller than its usual shape so the labels fit at 10 pt');
  expect(figureNotes({ grown: false, texts: [t('漢 set')] }, ['png']).glyphs).toBeNull();
  expect(figureNotes({ grown: false, texts: [t('漢 set')] }, ['png', 'pdf']).glyphs)
    .toBe("The PDF can't draw 漢: those characters print as boxes there. The PNG shows them.");
  expect(figureNotes({ grown: false, texts: [t('ok')] }, ['pdf'])).toEqual({ grown: null, glyphs: null });
});
```

- [ ] **Step 2: Run them to verify they fail.**
Run: `cd webui && npx vitest run tests/export/figureSave.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement the constants and functions.** `figureNotes` joins several missing characters with a space, in `missingGlyphs` order. In `ExportCard.svelte`, add a `figure width` group beside format and background:
  - `<input type="number" min="40" max="300" step="1" data-testid="fig-width" aria-label="figure width (mm)">` bound to `$figureOptions.widthMm`, with ` mm` after it.
  - Four small buttons, `data-testid="fig-width-90"` … `"fig-width-190"`, labelled `90`, `140`, `160`, `190`, that set it.
  - A note line `Laid out for this printed width: labels print at 10 pt.`
  - Clamp on blur with `clampFigureWidth`.
  - Update the card's header docstring.

- [ ] **Step 4: Run the tests.**
Run: `cd webui && npx vitest run tests/export && npm run check`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add webui/src/lib/export/figureSave.ts webui/src/components/cards/ExportCard.svelte webui/tests/export/figureSave.test.ts
git commit -m "feat(webui): figure width option (160 mm default) and save notes"
```

---

### Task 7: Save Figure on the print path

**Files:**
- Create: `webui/src/lib/export/viewFigure.ts`
- Modify: `webui/src/App.svelte` (imports ~L58–62; `appendExportLegend`/`getSvg` ~L300–395 removed; `saveFigure` ~L1177)
- Modify: `webui/src/lib/export/legendOverlay.ts` (drop Task 4's shim)
- Test: `webui/tests/export/viewFigure.test.ts`; `webui/e2e/export.spec.ts`; `webui/e2e/analysis.spec.ts` (~L170, ~L215)

**Interfaces:**
- Consumes: `printFigureSvg`, types (Tasks 2–4); `figureBytes` (Task 5); `clampFigureWidth`, `figureNotes`, `figureFormats`, `figureTargets` (Task 6 / existing).
- Produces:

```ts
export function toPrintEntries(entries: readonly LegendEntry[], fitSetIds: ReadonlySet<number>): PrintLegendEntry[];
  // drops 'off'; style 'dash' for a fit pseudo-set's line (its recon draws dashed), else 'line'; faded = state === 'fade'
export interface ViewFigureArgs {
  view: ViewId; bode: boolean; nyquist: boolean;
  model: PlotModel; phaseModel: PlotModel; sonoAxisModel: PlotModel; sonoImage: string | null;
  legend: { visible: boolean; x: number; y: number };
  entries: readonly LegendEntry[]; fitSetIds: ReadonlySet<number>; widthMm: unknown;
}
export function viewFigureInput(a: ViewFigureArgs): PrintFigureInput;
```

- [ ] **Step 1: Write the failing vitest tests:**

```ts
it('kind and panes follow the view', () => {
  expect(viewFigureInput(args({ bode: true })).kind).toBe('bode');
  expect(viewFigureInput(args({ bode: true })).panes.map((p) => p.model)).toEqual([M, P]);
  expect(viewFigureInput(args({ nyquist: true })).kind).toBe('nyquist');
  expect(viewFigureInput(args({})).panes).toEqual([{ model: M }]);
});
it('the sonogram exports its heat image and no legend', () => {
  const i = viewFigureInput(args({ view: 'sono', sonoImage: 'data:image/png;base64,AA' }));
  expect(i.panes).toEqual([{ model: S, image: 'data:image/png;base64,AA' }]); expect(i.legend).toBeNull();
});
it('a hidden legend is left out; otherwise it carries the on-screen fractions', () => {
  expect(viewFigureInput(args({ legend: { visible: false, x: 0.98, y: 0.98 } })).legend).toBeNull();
  expect(viewFigureInput(args({})).legend!.placement).toEqual({ kind: 'position', x: 0.98, y: 0.98 });
});
it('toPrintEntries drops off rows, dashes fit lines and fades faded ones', () => {
  const e = (setId: number, state: TriState) => ({ setId, ch: 1, label: `s${setId}`, color: '#2563eb', state });
  expect(toPrintEntries([e(1, 'on'), e(2, 'off'), e(3, 'fade'), e(9, 'on')], new Set([9]))).toEqual([
    { label: 's1', color: '#2563eb', style: 'line', faded: false },
    { label: 's3', color: '#2563eb', style: 'line', faded: true },
    { label: 's9', color: '#2563eb', style: 'dash', faded: false },
  ]);
});
it('the width is clamped', () => { expect(viewFigureInput(args({ widthMm: 9999 })).widthMm).toBe(300); });
```

  (`M`, `P`, `S` are three distinct stub models; `args(over)` fills a default `ViewFigureArgs` with `view: 'tf'`, legend visible at 0.98/0.98, one 'on' entry, width 160.)

- [ ] **Step 2: Update the e2e specs (they fail until Step 4).**
  - `export.spec.ts`, "Export stage → PNG": read the downloaded bytes. Expect IHDR width (`readUInt32BE(16)`) 3780 and height within ±2 of 2126, a `pHYs` chunk right after IHDR with 23622 px/m, and a file under 1 000 000 bytes (the spec's "not a nuisance" bound).
  - `export.spec.ts`, "PDF only": expect the bytes (latin1) to contain `/FontFile2` and `PydvmaFigureSerif`.
  - New test `a 90 mm figure is 2126 px wide`: click `fig-width-90`, export a PNG, expect IHDR width 2126.
  - `analysis.spec.ts`, Bode test: replace the 0.85 height ratio with `mag = {w: 3780, h: 2126 ± 2}` and `bode = {w: 3780, h: 2835 ± 2}`. The comment should say why: 16:9 against 4:3 at 160 mm.
  - `analysis.spec.ts`, legend/coherence test: keep its structure. Run it once with the new figure, log the two measured fractions, set each threshold to half its measured value (leave `restored < 0.0005`), and update the comment with the measured numbers.

- [ ] **Step 3: Run vitest to verify it fails.**
Run: `cd webui && npx vitest run tests/export/viewFigure.test.ts`
Expected: FAIL.

- [ ] **Step 4: Implement `viewFigure.ts` and rewire App.**
  - `saveFigure` snapshots `viewFigureInput({...})` when pressed, from `view`, `bode`, `nyquist`, `model`, `phaseModel`, `sonoAxisModel`, `sonoCanvas?.toDataURL('image/png')` (sono only, `null` on failure), `get(currentSlice).legend`, `get(legendOverride ?? legendRows)`, `fitSetIds` and `get(figureOptions).widthMm`.
  - It then runs `printFigureSvg` before the name dialog, so a plot change while the dialog is open can't change the figure.
  - It loops `figureTargets` → `figureBytes(fig, format, opts.bg)`, writing as today.
  - The success toast is `Saved a and b`, plus `, ${notes.grown}` when grown. `notes.glyphs` goes in a separate `level: 'info'` toast.
  - Delete `appendExportLegend`, `getSvg`, the `legendOverlaySvg` / `exportPng` / `exportPdf` imports in App, and Task 4's shim.
  - Keep `plotRef`/`phaseRef` only if something else still uses them; grep, and delete if not.

- [ ] **Step 5: Run the tests.**
Run: `cd webui && npx vitest run && npm run check && npx playwright test e2e/export.spec.ts e2e/analysis.spec.ts e2e/server-files.spec.ts`
Expected: all PASS. The `@engine` tests in these specs need the vendored engine (as always); `server-files.spec.ts` needs BRIDGE_E2E if it is gated in this environment. Report which ran.

- [ ] **Step 6: Commit.**

```bash
git add webui/src/lib/export/viewFigure.ts webui/src/lib/export/legendOverlay.ts webui/src/App.svelte webui/tests/export/viewFigure.test.ts webui/e2e/export.spec.ts webui/e2e/analysis.spec.ts
git commit -m "feat(webui): Save Figure writes the print layout (160 mm, 600 dpi PNG, embedded-font PDF)"
```

---

### Task 8: Damping charts on the print path

**Files:**
- Create: `webui/src/lib/export/dampingFigure.ts`
- Modify: `webui/src/components/DampingPanel.svelte` (domains ~L97–166 use the new helpers; `saveChart` ~L195; `fmtThr` moves; the `notify` type)
- Modify: `webui/src/App.svelte` (`notifyDamping` ~L163 accepts `'info'`)
- Test: `webui/tests/export/dampingFigure.test.ts`; `webui/e2e/analysis.spec.ts` (~L570)

**Interfaces:**
- Consumes: the types from Task 2 (`PrintFigureInput`, etc.); `DampingPeaksResult`, `DampingBandsResult` (stores/damping.ts); `seriesExtent`, `padDomain`, `markerIndices`, `MiniDomain` (plot/miniplot.ts); `LINE_PALETTE` (stores/selection.ts); `printFigureSvg`, `figureBytes`, `figureFormats`, `figureNotes`, `clampFigureWidth`.
- Produces:

```ts
export function fmtThreshold(v: number): string;                         // String(Number(v.toPrecision(3)))
export function normaliseSlice(p: DampingPeaksResult): { freq: Float64Array; norm: Float64Array; lo: number; span: number } | null;
export function spectrumDomain(n: { freq: Float64Array }): MiniDomain;  // x padDomain 0.02, y [0, 1.06]
export function decayDomain(p: DampingPeaksResult): MiniDomain | null;   // x pad 0.03, y pad 0.08
export function edcDomain(b: DampingBandsResult): MiniDomain | null;     // x pad 0.02, y [-70, 3]
export function dampingSpectrumFigure(p: DampingPeaksResult, widthMm: number): PrintFigureInput | null;
export function dampingDecayFigure(p: DampingPeaksResult, widthMm: number): PrintFigureInput | null;
export function dampingEdcFigure(b: DampingBandsResult, widthMm: number): PrintFigureInput | null;
```

- [ ] **Step 1: Write the failing tests** with a fixed result. `F = Float64Array.from`. `peaks`: `startTime 0.1024`, `threshold 0.005566`, `sliceFreq F([0,100,200,300])`, `sliceMag F([1,5,2,3])`, `peaksFreq F([100,300])`, `peaksMag F([5,3])`, and two fits (`fPeak 249.04, Qn 273.6`; `fPeak 459.0, Qn 1394.9`) with 3-point `tFit`/`realFit`/`realData`. `bands`: `bandData` `[{fc: 1.953125, edcT, edcDb, fitT, fitDb}, {fc: 125, …, fitT: null, fitDb: null}]`.

```ts
it('spectrum: normalised slice, peaks as circles, dashed threshold, the panel domain', () => {
  const i = dampingSpectrumFigure(peaks, 160)!;
  const m = i.panes[0].model;
  expect([m.xLabel, m.yLabel]).toEqual(['Frequency (Hz)', 'Normalised |S|']);
  expect(m.xRange).toEqual([-6, 306]); expect(m.yRange).toEqual([0, 1.06]);
  expect(Array.from(m.lines[0].y)).toEqual([0, 1, 0.25, 0.5]);
  expect(m.lines[0]).toMatchObject({ color: '#4f46e5', width: 1.3, dashed: false });
  expect(m.lines[1]).toMatchObject({ color: '#dc2626', marker: 'o', markerOnly: true });
  expect(Array.from(m.lines[1].y)).toEqual([1, 0.5]);
  expect(m.lines[2]).toMatchObject({ color: '#dc2626', dashed: true, width: 1.2 });
  expect(Array.from(m.lines[2].x)).toEqual([-6, 306]); expect(Array.from(m.lines[2].y)).toEqual([0.005566, 0.005566]);
  expect(i.legend).toEqual({ placement: { kind: 'best' }, entries: [
    { label: 'Start slice, t = 0.10 s', color: '#4f46e5', style: 'line', faded: false },
    { label: 'Picked peaks (2)', color: '#dc2626', style: 'o', faded: false },
    { label: 'Threshold 0.00557', color: '#dc2626', style: 'dash', faded: false },
  ] });
  expect(i.kind).toBe('default'); expect(i.widthMm).toBe(160);
});
it('spectrum without a threshold or start time leaves them out', () => {
  const i = dampingSpectrumFigure({ ...peaks, threshold: null, startTime: null }, 160)!;
  expect(i.panes[0].model.lines).toHaveLength(2);
  expect(i.legend!.entries.map((e) => e.label)).toEqual(['Start slice', 'Picked peaks (2)']);
});
it('decay: x markers and a fit line per mode, palette colours, the panel domain', () => {
  const i = dampingDecayFigure(peaks, 160)!;
  const m = i.panes[0].model;
  expect([m.xLabel, m.yLabel]).toEqual(['Time (s)', 'Re log(S)']);
  expect(m.lines).toHaveLength(4);
  expect(m.lines[0]).toMatchObject({ color: LINE_PALETTE[0], marker: 'x', markerOnly: true, width: 1.1, opacity: 0.75 });
  expect(m.lines[1]).toMatchObject({ color: LINE_PALETTE[0], width: 2.4, dashed: false });
  expect([m.xRange, m.yRange]).toEqual([decayDomain(peaks)!.x, decayDomain(peaks)!.y]);
  expect(i.legend!.entries[0]).toEqual({ label: '249.0 Hz, Qn = 274', color: LINE_PALETTE[0], style: 'xline', faded: false });
});
it('EDC: a curve per band, a dashed fit only where there is one, then the fit key', () => {
  const i = dampingEdcFigure(bands, 160)!;
  const m = i.panes[0].model;
  expect([m.xLabel, m.yLabel, m.yRange]).toEqual(['Time (s)', 'EDC (dB)', [-70, 3]]);
  expect(m.lines.map((l) => l.dashed)).toEqual([false, true, false]);
  expect(m.lines[0]).toMatchObject({ width: 1.4, opacity: 0.9 }); expect(m.lines[1]).toMatchObject({ width: 2 });
  expect(i.legend!.entries.map((e) => [e.label, e.style])).toEqual([['2.0 Hz', 'line'], ['125 Hz', 'line'], ['T60 fit (dashed)', 'dash']]);
  expect(i.legend!.entries[2].color).toBe('#6b7280');
});
it('nothing to draw, no figure', () => {
  expect(dampingSpectrumFigure({ ...peaks, sliceFreq: F([]), sliceMag: F([]) }, 160)).toBeNull();
  expect(dampingDecayFigure({ ...peaks, fits: [] }, 160)).toBeNull();
  expect(dampingEdcFigure({ ...bands, bandData: [] }, 160)).toBeNull();
});
```

  In `analysis.spec.ts` ~L570, after the EDC PNG download, read its bytes and expect IHDR width 3780 (the default 160 mm).

- [ ] **Step 2: Run them to verify they fail.**
Run: `cd webui && npx vitest run tests/export/dampingFigure.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement `dampingFigure.ts`, then refactor DampingPanel.**
  - Swap its inline `specNorm`/`specDom`/`decayDom`/`edcDom`/`fmtThr` for the exported helpers (pure refactor: same values).
  - `saveChart(id)` drops its `svg` argument. It builds the chart's input with `clampFigureWidth(get(figureOptions).widthMm)` and runs `printFigureSvg`. For each format in `figureFormats(opts)`, it writes `damping-${id}_${stamp()}.${format}` through `onsavefile` with `figureBytes(fig, format, opts.bg)`.
  - No format ticked → `notify('Pick at least one figure format (PNG or PDF) in the Export stage.', 'info')`.
  - Success: `Saved …` plus `, ${notes.grown}` when grown; `notes.glyphs` as a separate info notice.
  - Widen the `notify` prop type and App's `notifyDamping` to `'success' | 'error' | 'info'`.
  - Update the panel header docstring's "Every chart is SAVEABLE" paragraph.
  - Remove the `exportPng` import.

- [ ] **Step 4: Run the tests.**
Run: `cd webui && npx vitest run && npm run check && npx playwright test e2e/analysis.spec.ts`
Expected: PASS (the damping e2e is `@engine`; run it with the engine vendored and say if it was skipped).

- [ ] **Step 5: Commit.**

```bash
git add webui/src/lib/export/dampingFigure.ts webui/src/components/DampingPanel.svelte webui/src/App.svelte webui/tests/export/dampingFigure.test.ts webui/e2e/analysis.spec.ts
git commit -m "feat(webui): damping charts save as print figures with their legends"
```

---

### Task 9: Screen legend inside the axes frame; coherence label uncropped

**Files:**
- Modify: `webui/src/lib/plot/legendPos.ts` (export `FrameInsets`)
- Modify: `webui/src/components/PlotSurface.svelte` (bindable `frame`; y2 label at ~L524)
- Modify: `webui/src/components/Legend.svelte` (`frame` prop, frame box, `INSET` 8, max-height)
- Modify: `webui/src/App.svelte` (`bind:frame` on the three PlotSurfaces with a Legend, ~L1937/1954/1974; pass `frame` to each Legend)
- Test: `webui/e2e/plot-gestures.spec.ts`

**Interfaces:**
- Produces: `export interface FrameInsets { left: number; top: number; right: number; bottom: number }` (px from the plot host's edges to the data frame). PlotSurface gets `frame = $bindable<FrameInsets | undefined>()`, set in an `$effect` from `ox`, `oy`, `pw`, `ph`, `width` and `height`. Legend gets `frame?: FrameInsets` (absent → all zero, today's behaviour).

- [ ] **Step 1: Write the failing e2e tests** in `plot-gestures.spec.ts` (inside the legend `describe`):

```ts
test('every corner preset keeps the legend inside the axes frame, clear of the tick labels', async ({ page }) => {
  await openFixture(page);
  const frame = (await page.getByTestId('plot-svg').locator('rect.frame').first().boundingBox())!;
  for (const p of ['NE', 'NW', 'SW', 'SE']) {
    await openPanel(page);
    await page.getByTitle(`Move legend: ${p}`).click();
    await page.mouse.move(6, 560);
    const card = (await page.getByTestId('legend').boundingBox())!;
    expect(card.x).toBeGreaterThanOrEqual(frame.x + 7);
    expect(card.y).toBeGreaterThanOrEqual(frame.y + 7);
    expect(card.x + card.width).toBeLessThanOrEqual(frame.x + frame.width - 7);
    expect(card.y + card.height).toBeLessThanOrEqual(frame.y + frame.height - 7);
    for (const t of await page.getByTestId('plot-svg').locator('text.tick').all()) {
      const b = (await t.boundingBox())!;
      const overlap = b.x < card.x + card.width && card.x < b.x + b.width && b.y < card.y + card.height && card.y < b.y + b.height;
      expect(overlap).toBe(false);
    }
  }
});
test('a dragged legend may sit over the margins but stays inside the plot', async ({ page }) => {
  await openFixture(page);
  const svg = (await page.getByTestId('plot-svg').boundingBox())!;
  const frame = (await page.getByTestId('plot-svg').locator('rect.frame').first().boundingBox())!;
  const card = page.getByTestId('legend');
  const b = (await card.boundingBox())!;
  await page.mouse.move(b.x + 12, b.y + 12); await page.mouse.down();
  await page.mouse.move(b.x + 20, b.y + 12, { steps: 2 });
  await page.mouse.move(b.x + 12 - (b.x - svg.x) - 200, b.y + 12, { steps: 8 });   // far past the left edge
  await page.mouse.up();
  const after = (await card.boundingBox())!;
  expect(after.x).toBeLessThan(frame.x);            // over the left margin
  expect(after.x).toBeGreaterThanOrEqual(svg.x);    // but not off the plot
});
test('the coherence label sits inside the plot', async ({ page }) => {
  await openFixture(page);
  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'TF' }).click();
  const svg = (await page.getByTestId('plot-svg').boundingBox())!;
  const lab = (await page.getByTestId('plot-svg').locator('text.axlab', { hasText: 'coherence' }).boundingBox())!;
  expect(lab.x + lab.width).toBeLessThanOrEqual(svg.x + svg.width);
});
```

  (Reuse the file's `openFixture`/`openPanel` helpers. Check the preset titles against `ZoomToolbar.svelte`; the existing test uses `Move legend: NE`.)

- [ ] **Step 2: Run them to verify they fail.**
Run: `cd webui && npx playwright test e2e/plot-gestures.spec.ts -g "inside the axes frame|over the margins|coherence label"`
Expected: the preset and coherence tests FAIL (SE overlaps the "500" tick today; the label overruns the edge). The margin-drag test may already pass, and must keep passing.

- [ ] **Step 3: Implement.**
  - **Legend:** wrap the card in `<div class="legend-frame" data-testid="legend-frame">`, absolutely positioned at the insets, with `pointer-events: none`. The card keeps `pointer-events: auto`, so `offsetParent`, `hostOf()`, `settledPos()` and the drag maths all resolve against the frame box unchanged.
  - Fractions now mean "fraction across the axes frame". The clamp in `placement` depends on where the position came from, so a preset lands inside the axes while a free drag may still use the margins (the spec's rule).
    - **Preset** (`legend.preset` set, including the default `se`): clamp inside the frame box, 8 px clear of its edges (`INSET = 8`). Outside-right keeps its `RIGHT_SLACK`.
    - **Dragged position** (`preset === null`): clamp inside the whole plot host, 4 px clear. In the frame box's coordinates the bounds are `4 − frame.left` px … `100% + frame.right − size − 4` px, and likewise per side.
  - `.legend { max-height: calc(100% - 16px) }` against the frame box.
  - **PlotSurface:** set the y2 label's x to `width - 13` (baseline inset by the 11.5 px ascent + 4), still `rotate(90)`, and say why in a comment. Document the `frame` prop.
  - **App:** one `let plotFrame = $state<FrameInsets | undefined>()`, bound on the three Legend-bearing PlotSurfaces (only one branch mounts at a time) and passed to each `<Legend frame={plotFrame} …>`.

- [ ] **Step 4: Run the tests.**
Run: `cd webui && npm run check && npx vitest run && npx playwright test e2e/plot-gestures.spec.ts e2e/analysis.spec.ts`
Expected: PASS, including the existing "presets snap the legend flush", "many lines in a short plot" and "a dragged legend stays where it is dropped" (they measure against `offsetParent`, now the frame box).

- [ ] **Step 5: Commit.**

```bash
git add webui/src/lib/plot/legendPos.ts webui/src/components/PlotSurface.svelte webui/src/components/Legend.svelte webui/src/App.svelte webui/e2e/plot-gestures.spec.ts
git commit -m "fix(webui): legend presets sit inside the axes frame; coherence label no longer cropped"
```

---

### Task 10: Remove the screen-SVG export, document, final checks

**Files:**
- Modify: `webui/src/lib/export/figure.ts` (remove `exportPng`, `exportPdf`, `stampFonts`, `EXPORT_FONTS`, `svgSize`, `withExplicitSize`, `loadImage` if unused, and the header text about serialising PlotSurface)
- Modify: `webui/tests/export/figure.test.ts` (drop the `stampFonts`/`EXPORT_FONTS` tests)
- Modify: `webui/src/components/PlotSurface.svelte`, `webui/src/components/DampingPanel.svelte` (comments that cite `exportPng`/the self-contained-SVG export, where now untrue)
- Modify: `docs/web-logger/export.md` (§ "Export figures", L215–238)
- Modify: `docs/web-logger/analysis.md` (L284–286 only, guarded: see Step 4)
- Modify: `CHANGELOG.md` (`## Unreleased`)

- [ ] **Step 1: Confirm nothing calls the screen path.**
Run: `cd webui && grep -rn "exportPng\|exportPdf\|stampFonts\|EXPORT_FONTS\|getSvgElement" src tests e2e`
Expected: only definitions in `figure.ts`/`PlotSurface.svelte`, and the PlotSurface `getSvgElement` export (keep it if any e2e uses it; else remove).

- [ ] **Step 2: Delete the dead code and its tests; run the suites.**
Run: `cd webui && npm run check && npx vitest run`
Expected: PASS.

- [ ] **Step 3: Rewrite `export.md` § Export figures.** Replace L217–238 with text covering these points, in the docs' existing voice:
  - **figure format:** PNG at 600 dpi, tagged 600 dpi so Word and LaTeX place it at its printed size; PDF vector with the font embedded.
  - **background:** unchanged.
  - **figure width:** 160 mm by default (A4 with 25 mm margins), with quick picks 90 / 140 / 160 / 190 mm (single column, 1.5 column, A4 text width, double column). The figure is laid out for that printed width, so its labels print at 10 pt and its numbers and legend at 9 pt. Set the width the paper uses rather than scaling the file.
  - **filename:** unchanged.
  - **The figure's shape follows the plot type:** 16:9, Bode 4:3 (magnitude over phase, sharing the frequency axis), Nyquist square. It grows taller only when a long axis label or a large legend needs the room, and the save message says so.
  - **What the figure shows:** the same as today's paragraph. Add: the legend sits where it does on screen, inside the axes, and a legend too big for the plot goes below it.
  - **Type and glyphs:** the type is STIX Two Text, a Times-style face, the same in PNG and PDF on every machine. A character it lacks (in a set name, say) prints as a box in the PDF and a message names it; the PNG shows it.

- [ ] **Step 4: Update `analysis.md` L284–286, guarded.** First run `git status --short docs/web-logger/analysis.md`.
  - If that file has uncommitted changes from the damping-engine session, do not edit it. Add this sentence to your final report for Tore instead.
  - Otherwise replace "writes a PNG styled like the main figures, delivered the same way as **Save Figure**" with "saves the chart with the Export stage's figure options (format, background and width), legend included, delivered the same way as **Save Figure**".

- [ ] **Step 5: CHANGELOG.** Under `## Unreleased`, add a `### Changed` bullet: **Save Figure writes publication figures.** Cover: laid out for a printed width (160 mm default, set in the Export stage), STIX Two Text at 10 pt labels and 9 pt numbers, shaped by plot type (16:9, Bode 4:3, Nyquist 1:1), PNG at 600 dpi tagged 600 dpi, PDF vector with the font embedded (so γ and superscripts print). Damping charts save the same way, with their legends. Add a `### Fixed` bullet: the legend's corner presets sit inside the axes, clear of the tick labels; the coherence axis label is no longer cut off.

- [ ] **Step 6: By-eye and cross-browser checks** (rendering claims need screenshots of real output; see CLAUDE.md, round 7).
  1. Run `npm run build` and `npx vite preview`.
  2. Load `p2_noise_30s.dvma` (path in the design's mockup notes). Export the TF magnitude with coherence as PNG and PDF.
  3. Place both at 160 mm on an A4 page, as `make_aspects.py` does, and compare with `aspects_A4.pdf` page 1.
  4. Export a time plot, PSD, phase, sonogram, Bode and a 90 mm Nyquist; compare each with its mockup page. Export one in transparent and one in dark.
  5. Export the three damping charts from `6modes done.dvma` set "2" and compare with `damping_A4.pdf`.
  6. Open a PDF in Preview and run `pdffonts` on it. Expect `PydvmaFigureSerif`, embedded, and γ drawn.
  7. Export a PNG once in Safari (`open -a Safari` on the preview URL) and once in Firefox if installed. Check the labels are the STIX face, not the fallback.
  8. Record what was checked, and anything that differed, in the final report.

- [ ] **Step 7: Full gate.**
Run: `cd webui && npm run check && npx vitest run && npx playwright test`, then `cd .. && python -m mkdocs build --strict`
Expected: check 0/0; vitest all pass; Playwright as before plus the new tests (report the `@engine`/BRIDGE_E2E skips honestly); mkdocs clean.

- [ ] **Step 8: Commit.**

```bash
git add webui/src/lib/export/figure.ts webui/tests/export/figure.test.ts webui/src/components/PlotSurface.svelte webui/src/components/DampingPanel.svelte docs/web-logger/export.md CHANGELOG.md
git add docs/web-logger/analysis.md   # only if Step 4 edited it
git commit -m "docs: publication figures; remove the screen-SVG export path"
```

---

## Self-review (done while writing; kept for the executor)

- **Spec coverage:**
  - Print renderer → Tasks 2–3. Legend in the export → Task 4. Legend on screen → Task 9. Font → Tasks 1 and 5.
  - PNG / PDF → Task 5. Export card width → Task 6. App wiring → Task 7. Damping charts → Task 8. Coherence label → Task 9.
  - Grown and glyph notes → Tasks 6–8. Tests and checks → every task, plus Task 10. Docs → Task 10.
  - Removing `stampFonts` and the screen path → Task 10.
- **Deliberate refinements of the spec:**
  - `measure` is imported from `figureFont.ts` rather than passed in the input (the same table either way, simpler).
  - `PrintFigure` also returns `texts` with boxes, plus `frames` and `legendBox`, so layout claims are node-testable.
  - The font metrics ship as a generated `.ts` module, not JSON (no `resolveJsonModule` in the app tsconfig).
  - On screen, the 8 px frame inset applies to presets. A dragged position is clamped to the plot host instead, so the spec's "may still be dragged over the margins" holds.
  - A legend too wide for the frame (long labels) also goes below the axes; the spec only named "too tall".
- **Type names used across tasks:** `PrintFigureInput`, `PrintFigure`, `PrintLegendEntry`, `LegendPlacement`, `PtBox`, `PrintText`, `FigureKind`, `FIGURE_ASPECTS`, `layoutPrintLegend`, `figureBytes`, `figureNotes`, `clampFigureWidth`, `viewFigureInput`, `toPrintEntries`, `FrameInsets`.
