// chrome.ts — the plot's chrome (background + axis) colours, in ONE place.
//
// These are the inline presentation-attribute hexes PlotSurface stamps on its
// plot-bg and axis elements so a serialised export SVG is self-contained
// (figure.ts restyles by them). They are the resolved values of the app.css
// design tokens the on-screen scoped CSS uses — keep them in sync by hand:
//
//   bg    = --surface        (#ffffff)
//   grid  = the .grid literal (#eef0f4)   ← not a token; a literal in app.css
//   frame = --border         (#e3e6eb)
//   axis  = --muted          (#66708a)
//
// That app.css link is the ONE manual coupling that remains. Everything
// downstream (PlotSurface's markup, figure.ts's DARK_MAP) derives from CHROME,
// so a colour change here propagates — and figure.test.ts asserts DARK_MAP's
// keys are exactly CHROME's and PRINT_CHROME's values, so forgetting to update
// one fails RED.
export const CHROME = {
  bg: '#ffffff',
  grid: '#eef0f4',
  frame: '#e3e6eb',
  axis: '#66708a',
} as const;

export type ChromeKey = keyof typeof CHROME;

/**
 * The print figure's chrome colours (light mode), which the print renderer
 * (`lib/export/printFigure.ts`) stamps inline on its `data-role` elements:
 *
 * - `bg` `#ffffff`: the canvas background (the same hex as `CHROME.bg`).
 * - `ink` `#1d2027`: tick numbers, axis labels and legend text.
 * - `frame` `#3f4652`: the axes frame, drawn 0.6 pt wide.
 * - `grid` `#dfe2e7`: the gridlines, drawn 0.4 pt wide.
 * - `card` `#c5cad3`: the legend card's border, drawn 0.5 pt wide.
 *
 * Darker than `CHROME`, because a printed figure is read on paper, not beside
 * the app's light-grey UI. `figure.ts`'s `DARK_MAP` maps each of them for the
 * dark background.
 */
export const PRINT_CHROME = {
  bg: '#ffffff',
  ink: '#1d2027',
  frame: '#3f4652',
  grid: '#dfe2e7',
  card: '#c5cad3',
} as const;
