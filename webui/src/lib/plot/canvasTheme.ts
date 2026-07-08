// canvasTheme.ts — resolve the live-canvas chrome colours from the app's CSS
// custom properties at draw time (round-5 item 11, dark theme).
//
// The <canvas> renderers (OscCanvas, FftCanvas, LevelBars) paint with the 2D
// context, so — unlike CSS-styled SVG — they cannot inherit `var(--…)`. They
// call `canvasColors()` when they actually repaint (infrequent: the rev-skip
// guards mean this runs only on new audio or a display/theme change) and read
// the `--canvas-*` tokens off <html>, which carry the light or dark values per
// the active `data-theme`. Subscribing to the `theme` store forces a repaint
// on a theme flip.
//
// The exported SVG figure is deliberately NOT theme-driven (figure.ts keys off
// the fixed CHROME constants), so these live-canvas colours never touch export.

export interface CanvasColors {
  /** Plot-area background fill. */
  bg: string;
  /** Gridlines / faint mid-lines. */
  grid: string;
  /** Plot frame / border stroke. */
  frame: string;
  /** Axis tick + unit label text. */
  axis: string;
  /** Muted secondary text (min/max readouts, empty-state prompt). */
  muted: string;
  /** Zero-reference dashed line. */
  zero: string;
}

const FALLBACK: CanvasColors = {
  bg: '#ffffff',
  grid: '#eef0f4',
  frame: '#d1d5db',
  axis: '#6b7280',
  muted: '#9ca3af',
  zero: '#d1d5db',
};

/**
 * Read the current `--canvas-*` design tokens off the document root. Falls
 * back to the light defaults when there is no DOM (SSR / tests) or a token is
 * unset, so a renderer always gets a usable colour.
 */
export function canvasColors(): CanvasColors {
  if (typeof document === 'undefined' || typeof getComputedStyle !== 'function') {
    return { ...FALLBACK };
  }
  const s = getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string): string => {
    const v = s.getPropertyValue(name).trim();
    return v || fallback;
  };
  return {
    bg: read('--canvas-bg', FALLBACK.bg),
    grid: read('--canvas-grid', FALLBACK.grid),
    frame: read('--canvas-frame', FALLBACK.frame),
    axis: read('--canvas-axis', FALLBACK.axis),
    muted: read('--canvas-muted', FALLBACK.muted),
    zero: read('--canvas-zero', FALLBACK.zero),
  };
}
