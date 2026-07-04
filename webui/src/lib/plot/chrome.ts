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
// keys are exactly CHROME's values, so forgetting to update one fails RED.
export const CHROME = {
  bg: '#ffffff',
  grid: '#eef0f4',
  frame: '#e3e6eb',
  axis: '#66708a',
} as const;

export type ChromeKey = keyof typeof CHROME;
