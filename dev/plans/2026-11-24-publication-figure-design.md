# Publication-quality Save Figure — design

2026-11-24. Tore's ask. Mockups are in `dev/mockups/2026-11-24-publication-figure/`:
`mockup_A4.pdf` (type; Tore picked variant **A**, Times-style 10 pt) and
`aspects_A4.pdf` (one figure per type at its aspect; Tore approved the set
"16:9 default, Bode 4:3, Nyquist 1:1"), and `damping_A4.pdf` (the damping
panel's three charts; Tore: "yes, as mocked"). `make_aspects.py` (plus
`make_damping.py`) there is the throwaway layout prototype. Its margin and
legend arithmetic, including the best-corner and below-axes legend, is a
useful reference for the real renderer.

## Intent

Save Figure (header button and the Export stage, both App's `saveFigure`)
should produce a figure that can go straight into a journal paper (JSV-style,
A4) at full text width: legible type at a stated point size, print
resolution, no clipped labels, no garbled glyphs. Today the export is a
scaled copy of the on-screen SVG. Its viewBox is the plot's pixel size on
screen (~1300 px wide), so its 10.5/11.5 px text prints at ~4 pt at 160 mm,
and the result depends on the browser window's width.

Second ask: the legend's default corner (and the other corner presets) must
not cover the axes' corner tick labels, on screen and in the export. Tore's
second screenshot shows the wanted place: inside the axes frame, a little
clear of the corner.

## Findings that shape the design

1. **Size**: the export can't be fixed by enlarging text. The margins
   (PlotSurface L58/T16/B42, R18 or 56) and label positions are fixed screen
   pixels, so larger text overlaps and clips. The figure must be laid out
   again at a physical size.
2. **Cropped coherence label** (screen too): PlotSurface draws the y2 label
   with `translate(width-8, …) rotate(90)`. With rotate(90) the glyphs'
   ascent points to +x, so they run past the right edge.
3. **PDF can't draw γ**: jsPDF's built-in fonts are WinAnsi only. A label
   with γ (`coherence γ²`) is written as UTF-16 into a WinAnsi font and
   renders as garbage. This was reproduced in jsPDF directly; an exported
   PDF has not been opened. An embedded TrueType font fixes it.
4. **Legend anchoring**: on screen, `Legend.svelte` positions the card as
   fractions of its offsetParent, which is the whole plot host *including
   margins*, with a 4 px inset. The SE preset (0.98, 0.98) therefore sits
   on the bottom-right tick labels ("500", the right-axis "0"). The export
   overlay (`legendOverlay.ts`) copies the same rule over the whole canvas.

## Goals

- A figure laid out for a stated printed width, **160 mm by default** (A4
  with 25 mm margins), so its type is true to size at that width.
- **Type**: a Times-style serif, **10 pt axis labels, 9 pt tick numbers,
  9 pt legend** (variant A), near-black. Same face in PNG and PDF on every
  machine.
- **PNG at 600 dpi** of the chosen width (160 mm → 3780 px wide, ~400 KB for
  the mockup figure), tagged 600 dpi so Word and LaTeX place it at its
  printed size.
- **PDF** vector at exactly the chosen width × height, fonts embedded.
- **Aspect ratio by figure type**, not the on-screen shape (Tore: "the aim
  isn't to match on-screen aspect ratio"). Approved set, width : height of
  the whole figure:

  | Figure type | Aspect |
  |---|---|
  | default: time; spectra (FFT, Power, PSD, CSD); TF magnitude (± coherence, fit lines, BLA σ), phase, real, imag; sonogram | **16:9** |
  | Bode (magnitude over phase) | **4:3**, magnitude 60 % / phase 40 % of the data height |
  | Nyquist | **1:1** (square data rect) |

- **Fixed type wins over aspect**: when a rotated axis label is longer than
  its plot is tall (narrow widths, Bode panes, long PSD labels), the figure
  grows taller just enough to fit. The type never shrinks. The save toast
  then says it was laid out taller than its usual shape to fit the labels.
  *(Tore chose growing the height; the wording is my call.)*
- **Nothing clipped**: margins sized from the actual label and tick text.
- **Legend inside the axes frame**, clear of tick labels, at all four corner
  presets, on screen and in the export.
- The coherence (right-axis) label fixed on screen too.

## Non-goals

- Italic math symbols. The mockup set *H* and γ in italic by hand. The app's
  labels are plain strings (`|H| (V/V, dB)`) and print upright as written.
  *(My call: parsing labels for symbols is out of scope.)*
- A colour bar for the sonogram, or any element the screen plot lacks.
- Changing what the damping fits compute, or what the damping charts plot
  (their data, domains and colours stay as on screen). The band-metrics
  table still saves as CSV only.
- Persisting the figure width across sessions: `figureOptions` is
  session-only today and stays so.
- Changing the on-screen plot's look, beyond the legend anchoring and the
  coherence label position.

## Anti-goals (a failure even if it works)

- An export that shows *different data* from the screen: other lines, other
  ranges, other legend entries, other tick values. Only layout, type, line
  weights and size may differ. One exception: Bode's top pane omits the
  frequency tick labels and axis label it shares with the pane below. Its
  gridlines stay at the same ticks.
- Breaking the white / transparent / dark background modes, Bode's two
  panes, the sonogram heat image, or Nyquist's square aspect.
- Any glyph rendering as a box or garbage in either format.
- A PNG so large it's a nuisance (aim: under ~1 MB for a typical figure at
  160 mm).

## Approaches

1. **A print renderer (chosen).** A new pure module builds the export SVG
   string from the same `PlotModel`(s) the screen renders, through the same
   `buildPlot`, at the print size, with print typography and margins sized
   from the text. Same data, ranges, ticks and decimation logic; node-testable.
2. *Enlarge the text in the serialised screen SVG.* Rejected: margins and
   label positions are screen pixels, so larger type overlaps and clips (the
   coherence crop is this failure already).
3. *Mount a hidden PlotSurface in a "print" mode and serialise it.* Rejected:
   it mixes print styling into the interactive component, needs a DOM and an
   async mount, and can't be unit-tested in node.

Tore handed over the how; approach 1 is the builder's brief.

## Design

### Print renderer — `webui/src/lib/export/printFigure.ts` (new)

A pure function (no DOM) that returns a self-contained SVG string and its
size:

```
printFigureSvg(input: PrintFigureInput): PrintFigure
// PrintFigure = { svg, widthPt, heightPt, grown, texts }
// texts: every string drawn, for the PDF missing-glyph check
```

`PrintFigureInput` carries:
- `panes`: one or two panes, top to bottom. Each pane has its `PlotModel`
  (exactly what App passes to that PlotSurface) and an optional raster
  `image` (the sonogram heat as a PNG data URL) drawn into the pane's data
  rect, as `getSvg` composites it today.
- `kind`: `'default' | 'bode' | 'nyquist'`, which picks the aspect from the
  table in Goals (one exported constant, `FIGURE_ASPECTS`, so the docs and
  tests read the same numbers). The sonogram is `'default'`.
- `widthMm` (default 160).
- `legend`: entries ('off' rows excluded, as now) and a placement, drawn
  in the **first** pane (as on screen for Bode). None for the sonogram, as
  now. Each entry is `{ label, color, style, faded }`, where `style` is
  `'line' | 'dash' | 'x' | 'o' | 'xline'` and picks the swatch. Placement
  is `{ kind: 'position', x, y }` (the on-screen legend's fractions) or
  `{ kind: 'best' }` (the damping charts, see Damping charts).
- Lines may carry **markers**: `PlotLine` gains optional `marker?: 'x' |
  'o'` and `markerOnly?: boolean` (draw the markers, no stroke). Only the
  print renderer reads them; PlotSurface ignores them, since no on-screen
  model sets them. Markers are 2.2 pt half-size, stroked in the line's
  colour (× 0.7 pt, ○ 0.9 pt, r 2.6 pt).
- `fonts`: a text-measuring function `measure(text, sizePt) → widthPt`. In
  the browser it comes from the embedded font's advance widths (a generated
  table, see Font); node tests can use the same table.

Geometry:
- **Units**: the root `<svg>` has `width="…pt" height="…pt"` and a viewBox
  in **quarter points** (4 units per pt). `buildPlot` is called with the data
  rect in those units, so `minMaxDecimate` keeps 4 columns per pt (~150 per
  inch). This is enough for 600 dpi (one column is about 4 px) and much
  finer than calling it at the pt size. All type sizes and stroke widths
  are given ×4.
- **Height** = width ÷ the kind's aspect. Then, if any rotated y or y2 label
  (plus a tick's height of clearance) is longer than its pane's data
  height, the data height grows until it fits, and the function reports
  `grown: true` so the toast can say so. Return `{ svg, widthPt, heightPt,
  grown }`.
- **Bode**: the data height splits 60 % magnitude / 40 % phase, with a 9 pt
  gap between the panes. Both panes share one left and right margin, so
  their frames line up. The top pane draws its x gridlines but no x tick
  labels and no x label. The right axis (coherence) belongs to the pane
  that carries it.
- **Margins** come from the text. Left = widest y tick label (over all
  panes) + gap + rotated label line. Right = the y2 tick width + gap +
  rotated y2 label line when there's a right axis, else a small pad, but
  never less than half the last x tick label's width when that tick sits on
  the right edge. The mockup clipped "1500" before this rule. Bottom = tick
  line + gap + x label line. Top = a little over half a tick line, so the
  top tick label isn't clipped. Gaps scale with the font size (the mockup
  used 0.4 × tick size label-to-frame and 0.35 × label size between tick
  labels and axis label; tune by eye).
- **Squares**: a `squareAspect` (Nyquist) pane centres a square data rect,
  as PlotSurface does.
- **Ticks**: `buildPlot`'s ticks unchanged. Labels go through `fmtTick`,
  then hyphen-minus → U+2212 (true minus) for print only.
- **Right-axis label** reads top-to-bottom (rotate 90). It is positioned so
  its glyphs sit *inside* the canvas: baseline inset by the ascent from the
  right edge.

Print styling (light mode values; the restyle maps cover the other modes):
- text `#1d2027`; frame `#3f4652` at 0.6 pt; gridlines `#dfe2e7` at 0.4 pt;
  no tick marks (the gridlines do that job, as on screen).
- data line widths = on-screen px width × 2/3 pt (1.5 px → 1.0 pt, coherence
  1 px → 0.67 pt; band overlay 2.5 px → 1.67 pt); dashes scaled by 0.6
  (`4 3` px → `2.4 1.8` pt). Opacity as on screen.
- The `data-role="axis"` / `"plot-bg"` tags and inline hexes follow the
  existing self-contained-SVG contract in `figure.ts`, so `prepareSvg`'s
  transparent and dark modes keep working. Add the print chrome hexes to
  the dark map, or give the print path its own map; either way keep the
  `figure.test.ts` "every chrome hex has a dark mapping" guard true for the
  print colours.

### Legend in the export

`legendOverlay.ts` places the card relative to the **axes frame** (the first
pane's data rect), not the canvas:
- fractions `(x, y)` map across the frame; right/bottom anchoring past 0.5
  stays as now;
- corner presets sit **inset 0.6 × legend font size** from the frame's
  edges (≈5.4 pt) — inside the axes, clear of every tick label;
- 9 pt type, swatch ≈1.6 em, card fill white at 0.92 opacity, 0.5 pt border
  `#c5cad3`, as in the mockup;
- box size from the same `measure` function (not the current `CHAR_W`
  guess);
- clamp the box inside the frame; `outside-right` (x > 1) may sit in the
  right margin and is clamped inside the canvas.
- **A legend too big for the frame**: wrap into columns like the screen
  (`legendWrapColumns`), then add columns while the box is wider than it is
  tall and still fits the frame width. If it is still taller than the
  frame, place it **below the axes**, full width, in as many columns as
  fit, and grow the figure by its height. It always writes full rows (line
  + label). The screen's compact dot grid is never exported: a printed
  legend must name its lines. *(My call.)*
- **Below the axes** means an unboxed block under the x label, centred on
  the frame, with as many equal columns as fit the frame width, filled
  top-to-bottom then across. The figure grows by its height
  (`grown: true`). The mockup's decay chart shows it (90 → 108 mm).
- **Best placement** (`{ kind: 'best' }`): try the four corners at the
  preset inset. Count the plotted points (every built path vertex, and
  every marker) inside each candidate box, and take the corner with the
  fewest; ties go se, ne, nw, sw. If even that corner covers more than
  `max(2, 0.5 %)` of the points, put the legend below the axes.

### Legend on screen — `Legend.svelte`

Same rule on screen. The card's fractions and presets refer to the
PlotSurface's **data frame** (`ox, oy, pw, ph`; L58/T16/B42, R18 or 56;
Nyquist's centred square), with an 8 px inset at the presets. Today they
refer to the whole host with a 4 px inset.
- PlotSurface exposes its frame rect, e.g. a bindable `frame` prop or a
  callback. App hands it to Legend; Bode uses the magnitude pane's.
- Stored fractions keep their meaning as "fraction across the axes"; the
  preset table in `legendPos.ts` keeps its values. A saved view lands
  slightly further in than before. *(My call: no migration; it is a
  view nicety.)*
- Dragging computes the drop fraction against the frame; the "stays inside
  the plot" clamp becomes "stays inside the host" (the card may still be
  dragged over the margins if the user wants).
- `outside-right` keeps working: right of the frame, clamped inside the host.

### Font

- Face: **STIX Two Text** Regular (Times-style; SIL OFL 1.1; v2.13 is on
  macOS at `/System/Library/Fonts/Supplemental/STIXTwoText.ttf`, upstream
  github.com/stipub/stixfonts). *(Settled after the builder check: the
  matplotlib STIX General copy first chosen has only ¹ ² ³ ⁿ, and the app
  makes "m/s⁴" from m/s² with x(iω)^+2. STIX Two Text has U+2070–209F,
  Greek, − · µ Ω °; it lacks ≤ and ∞, which no app label uses.)* It is a
  variable font: instance it at `wght=400` with
  `fontTools.varLib.instancer` before subsetting.
- Subset with fontTools (installed with matplotlib) to Basic Latin,
  Latin-1, Latin Extended-A (accented names), Greek, General Punctuation,
  super/subscripts, letterlike symbols (Ω, ℃) and the operators the app's
  units use (− · × ÷ √ ∂). Expect ~50–70 KB. **Rename the family** in the
  subset's name table (e.g. "Pydvma Figure Serif"): OFL forbids a modified
  font from using a Reserved Font Name. Commit the subsetting script
  (`webui/scripts/subset-figure-font.py`, which names its source path and
  the upstream release), the `.ttf`, and the OFL licence text next to it.
  Also commit an advance-width table (JSON, codepoint → advance in em),
  generated from the same font for `measure`. Only regenerating the font
  needs the source; nobody else does.
- **Text the subset can't draw** (users type set names, channel labels
  and units): the PDF would show boxes. When writing a PDF, check every
  string against the subset's cmap. If any character is missing, still
  write the file, and raise one info toast naming those characters and
  saying the PNG shows them. *(My call.)*
- Loaded only when a figure is exported (dynamic import / asset URL), so
  the main bundle doesn't grow.
- **PNG**: the SVG carries `@font-face { src: url(data:font/ttf;base64,…) }`
  in a `<style>`. Verified working in Chromium for an SVG drawn through
  `<img>` (scratch test, 2026-11-24). Safari and Firefox are **unverified**:
  check both. The `font-family` stack ends `'Times New Roman', Times,
  serif`, so a browser that ignores the embedded face still gets a Times.
- **PDF**: register the TTF with jsPDF (`addFileToVFS` + `addFont`,
  Identity-H) under the same family name, so svg2pdf's font lookup finds it
  for the `font-family` attribute. Verify the γ renders and the font is
  embedded (`pdffonts`, or inspect the PDF).

### PNG

- Pixel width = round(widthMm / 25.4 × 600); height from the laid-out
  height (the aspect, or taller when grown).
- Insert a `pHYs` chunk (23622 px/m both axes = 600 dpi) after `IHDR`; a
  pure, unit-tested function on the PNG bytes (chunk CRC included).
- The white/dark canvas pre-fill stays as now.

### PDF

- Page = the SVG's pt width × height; vector; embedded font. Today's
  background pre-fill stays.

### Export card — figure width

- A **Figure width** field in mm next to the format/background choices,
  default 160, with quick picks **90 / 140 / 160 / 190** (Elsevier single
  column, 1.5 column, A4 text width, double column). Range 40–300 mm. Stored
  in `figureOptions`, session-only like the rest. *(My call on the presets
  and range.)*
- Type sizes stay 10/9 pt at any width: the layout adapts, so a 90 mm figure
  is laid out for 90 mm instead of shrinking the 160 mm one.
- A one-line note under the field: "Laid out for this printed width: labels
  print at 10 pt."

### App wiring

- `saveFigure` builds a `PrintFigureInput` from the active view's model(s)
  (the same `$derived` models the plot branches render), the figure kind
  (Bode / Nyquist / default from the current view), the sonogram heat
  (`sonoCanvas.toDataURL`), and the legend state.
  It then calls `printFigureSvg`, and passes the result to the print PNG /
  PDF writers. The print SVG stamps `font-family` and `font-size` on every
  `<text>` itself, so `prepareSvg`'s `stampFonts` leaves it alone. Once the
  damping charts move to the print path, nothing serialises a screen SVG,
  so remove `stampFonts`, `EXPORT_FONTS` and the screen-SVG `exportPng` /
  `exportPdf` if nothing else calls them.
- `getSvg` stays for anything else that uses it (the Bode e2e reads it);
  remove it if nothing does.
- Snapshot the inputs when Save Figure is pressed, as today's "serialise
  NOW" does, so a plot change while the dialog is open doesn't change the
  figure.

### Damping charts — `DampingPanel.svelte`

The panel's three saveable charts go through the same print renderer
(mockup `damping_A4.pdf`). Each card's save button writes the chart with
the Export stage's `figureOptions`: formats, background and width. It
keeps its automatic name `damping-<chart>_<stamp>.<ext>`, writing both
files when both formats are ticked, through the same `onsavefile`
delivery. Kind `'default'` (16:9). Legend placement `{ kind: 'best' }`.

A pure module `webui/src/lib/export/dampingFigure.ts` builds each chart's
`PrintFigureInput` from the damping store's results, with explicit
`xRange`/`yRange` equal to the panel's own domains (so the printed chart
plots what the card plots):

- **Start-slice spectrum** (peaks mode): x `Frequency (Hz)`, y
  `Normalised |S|` (the card says `norm |S|`; print only). Lines: the
  normalised slice in `#4f46e5` at 1.3 px; the picked peaks as `'o'`
  markers only, in `#dc2626`; the threshold as a dashed `#dc2626` line
  across the x range. Domains: x = the slice's extent padded 2 %,
  y = [0, 1.06]. Legend: `Start slice, t = {start_time, 2 dp} s` (line),
  `Picked peaks ({n})` (o), `Threshold {fmtThr}` (dash, the panel's
  3-significant-figure format).
- **Decay fits** (peaks mode): x `Time (s)`, y `Re log(S)`. Per mode `i`,
  in `LINE_PALETTE[i]`: the data as `'x'` markers only (at the panel's
  `markerIndices`, 1.1 px, opacity 0.75), and the fitted line at 2.4 px.
  Domains as the panel's `decayDom`. Legend per mode:
  `{fPeak, 1 dp} Hz, Qn = {Qn, 0 dp}` (xline).
- **Schroeder EDC** (bands mode): x `Time (s)`, y `EDC (dB)`. Per band `i`,
  in `LINE_PALETTE[i]`: the EDC at 1.4 px, opacity 0.9, and the T60 fit
  dashed at 2 px. Domains as the panel's `edcDom` (y [−70, 3]). Legend per
  band: `{fc} Hz` (fc < 10 → 1 dp, else 0 dp) (line), then
  `T60 fit (dashed)` in `#6b7280` (dash).

The card's own on-screen look and its HTML legend chips don't change.

### Screen fix — coherence label

PlotSurface's y2 label moves so its glyphs sit inside the SVG: baseline
x = `width − 4 − ascent` (≈ `width − 13` at 11.5 px), still rotate(90).
Check it clears the y2 tick labels (`ox + pw + 7`, ~20 px wide) with the
56 px right margin.

## Tests and checks

- **vitest** (`tests/export/printFigure.test.ts`, new):
  - root width/height in pt match `widthMm` and the kind's aspect
    (16:9, Bode 4:3, Nyquist 1:1), and `grown` is false for ordinary
    labels at 160 mm;
  - a label too long for the plot grows the height (never the type), with
    `grown: true`;
  - Bode's top pane has no x tick labels or x label, its split is
    60/40, and both frames share left/right edges;
  - a right-edge last tick label ("1500") lies inside the canvas;
  - a legend taller than the frame goes below the axes and grows the figure;
  - `{ kind: 'best' }` picks the emptiest corner, and goes below the axes
    when every corner covers more than `max(2, 0.5 %)` of the points;
  - legend swatches follow `style` (dash, x, o, xline), and markers draw
    with no stroke for `markerOnly` lines;
  - `dampingFigure.ts`: each builder's labels, domains, line styles and
    legend text for a small fixed result (the formats in the design);
  - every text element's box lies inside the canvas (margins fit the
    labels, including a long y label and a right axis);
  - font sizes are 10/9/9 pt (×4 units);
  - the tick values match `buildPlot`'s for the same model;
  - minus signs are U+2212;
  - the legend box lies inside the frame for all four presets and doesn't
    overlap any tick label;
  - Bode two panes with the legend in the top one; the Nyquist square;
  - the sonogram image fills the data rect.
- **vitest**: the pHYs writer (chunk order, CRC, 600 dpi value); the
  legend overlay's new frame anchoring (update `legendOverlay.test.ts`);
  the restyle-map guard covering the print colours.
- **Playwright**:
  - `export.spec.ts`'s PDF size floor and anything else asserting
    today's dimensions;
  - `analysis.spec.ts`'s legend/coherence pixel-diff export test and its
    Bode both-panes test (re-baseline thresholds against the new figure);
  - `plot-gestures.spec.ts`'s legend preset/drag tests for the
    frame-anchored screen legend;
  - a new check that an exported PNG is 3780 px wide at 160 mm with a
    600 dpi pHYs.
- **By eye** (the round-7 lesson: rendering claims need screenshots of the
  real output): export the mockup's file (`p2_noise_30s.dvma`, TF + coherence)
  as PNG and PDF, place both at 160 mm on an A4 page as the mockup does, and
  compare with `aspects_A4.pdf` page 1 (16:9). Also export the other pages'
  types (time, PSD, phase, sonogram, Bode, a Nyquist at 90 mm) and a
  multi-line legend, compare each with its mockup page, and check them in
  white, transparent and dark.
  Open the PDF in Preview *and* check fonts are embedded.
- **Safari and Firefox**: the PNG's embedded font.
- Gate: `npm run check`, vitest, the Playwright specs above (from `webui/`),
  and `mkdocs build --strict` after the docs edit.

## Docs

`docs/web-logger/export.md` "Export figures": the width setting and what
it means, 600 dpi PNG, vector PDF with embedded font, type sizes, and that
the figure is laid out for print rather than copied from the screen. The
damping docs (wherever the card's save button is described) say the
charts save with the Export stage's figure options and carry their
legends. The CHANGELOG `## Unreleased` gets an entry.

## Left to the builder

- Exact gap constants, tuned by eye against the mockup.
- Whether the print dark map is merged into `DARK_MAP` or separate.
- How PlotSurface exposes its frame rect to Legend.
- The advance-width table's format, and kerning (ignore; Times-style
  figures and labels don't need it).
- Whether `getSvg` survives.
