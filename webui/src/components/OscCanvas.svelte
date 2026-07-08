<script lang="ts">
  /**
   * Canvas-rendered real-time oscilloscope TIME trace (design spec §8).
   *
   * Draws the monitor store's ring buffer as time-domain traces using
   * requestAnimationFrame.  Shared by the persistent MiniMonitor and the
   * expanded Live scope's time pane, so it takes a `variant`:
   *
   * - **full** (default): axes, margins, tick labels, per-channel Y
   *   labels, and — with `stacked` — one vertical lane per channel (the
   *   Qt many-channel idiom).  This is the Live tab's big time pane.
   * - **compact**: no chrome at all — just the overlaid traces filling
   *   the canvas on white, for the bottom-left mini monitor.  Autoscale
   *   is forced on and a faint mid-line is drawn.
   *
   * The canvas fills its container (sized by CSS) and redraws whenever
   * the ring revision changes (new audio) or a display toggle flips.
   * When `active` is false (e.g. the mini body is collapsed) the rAF loop
   * keeps ticking but skips all drawing so a hidden scope costs nothing.
   *
   * Line decimation (min–max per pixel column) is applied when the sample
   * count exceeds the pixel width, preserving peaks at any window length.
   */
  import { onMount, onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import type { MonitorStore } from '../lib/stores/monitor';
  import { canvasColors } from '../lib/plot/canvasTheme';
  import { theme } from '../lib/stores/theme';

  // Plot palette — shared with the SVG analysis plots.
  const PALETTE = [
    '#6366f1', '#f97316', '#10b981', '#f43f5e', '#8b5cf6',
    '#06b6d4', '#eab308', '#ec4899', '#14b8a6', '#a855f7',
  ];

  let {
    monitor,
    variant = 'full',
    active = true,
  }: {
    monitor: MonitorStore;
    variant?: 'full' | 'compact';
    active?: boolean;
  } = $props();

  let canvasEl: HTMLCanvasElement | undefined = $state();
  let raf = 0;
  let lastRev = -1;
  let lastActive = true;
  let mounted = true;

  // Layout constants for the full variant.
  const MARGIN = { top: 12, right: 12, bottom: 28, left: 50 };

  onMount(() => {
    mounted = true;
    raf = requestAnimationFrame(draw);
  });

  // Force a repaint when the theme flips (canvas colours are read at draw
  // time; the rev-skip guard would otherwise keep the stale-theme frame).
  const unsubTheme = theme.subscribe(() => { lastRev = -1; });

  onDestroy(() => {
    mounted = false;
    unsubTheme();
    if (raf) cancelAnimationFrame(raf);
  });

  /** Compute Y range per channel with autoscale or fixed ±1. */
  function yRange(samples: Float32Array, auto: boolean): [number, number] {
    if (!auto) return [-1, 1];
    let min = Infinity, max = -Infinity;
    for (let i = 0; i < samples.length; i++) {
      if (samples[i] < min) min = samples[i];
      if (samples[i] > max) max = samples[i];
    }
    if (!isFinite(min) || !isFinite(max)) return [-1, 1];
    // Add 10% headroom; clamp to avoid a zero-height range.
    const margin = Math.max(0.001, (max - min) * 0.1);
    return [min - margin, max + margin];
  }

  /** Resize the canvas backing store to CSS size × devicePixelRatio. */
  function fitCanvas(cv: HTMLCanvasElement, ctx: CanvasRenderingContext2D): [number, number] {
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth;
    const h = cv.clientHeight;
    cv.width = Math.max(1, Math.round(w * dpr));
    cv.height = Math.max(1, Math.round(h * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return [w, h];
  }

  function draw() {
    if (!mounted) return;
    raf = requestAnimationFrame(draw);
    if (!canvasEl) return;

    // When inactive (collapsed mini) don't draw — but note the transition so
    // we force one redraw when it becomes active again.
    if (!active) { lastActive = false; return; }
    const becameActive = !lastActive;
    lastActive = true;

    const snap = monitor.snapshot();
    if (snap.channels.length === 0) {
      drawEmpty();
      lastRev = -1;
      return;
    }

    // Skip redraw if nothing changed (saves CPU while paused) — unless we
    // just became visible or the variant needs a first paint.
    if (snap.rev === lastRev && !becameActive) return;
    lastRev = snap.rev;

    if (variant === 'compact') drawCompact(snap);
    else drawFull(snap);
  }

  /** Empty "waiting" state. */
  function drawEmpty() {
    if (!canvasEl) return;
    const ctx = canvasEl.getContext('2d');
    if (!ctx) return;
    const C = canvasColors();
    const [w, h] = fitCanvas(canvasEl, ctx);
    // Compact (mini) clears transparent so the container bg shows; full fills.
    if (variant === 'full') {
      ctx.fillStyle = C.bg;
      ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = C.muted;
      ctx.font = '13px system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Start the monitor to see live traces', w / 2, h / 2);
    } else {
      ctx.clearRect(0, 0, w, h);
    }
  }

  /** Compact variant: overlaid autoscaled traces, no chrome (mini monitor). */
  function drawCompact(snap: { channels: Float32Array[]; fs: number; rev: number }) {
    if (!canvasEl) return;
    const ctx = canvasEl.getContext('2d');
    if (!ctx) return;
    const C = canvasColors();
    const [w, h] = fitCanvas(canvasEl, ctx);
    ctx.clearRect(0, 0, w, h);

    const nCh = snap.channels.length;
    // Shared autoscaled Y range across channels.
    let lo = Infinity, hi = -Infinity;
    for (let ch = 0; ch < nCh; ch++) {
      const [a, b] = yRange(snap.channels[ch], true);
      if (a < lo) lo = a;
      if (b > hi) hi = b;
    }
    if (!isFinite(lo) || !isFinite(hi)) { lo = -1; hi = 1; }

    // Faint mid-line.
    if (lo < 0 && hi > 0) {
      const zeroY = h * (1 - (0 - lo) / (hi - lo));
      ctx.strokeStyle = C.grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, zeroY);
      ctx.lineTo(w, zeroY);
      ctx.stroke();
    }

    for (let ch = 0; ch < nCh; ch++) {
      drawTrace(ctx, snap.channels[ch], 1, 1, w - 2, h - 2, lo, hi, PALETTE[ch % PALETTE.length], 1.3);
    }
  }

  /** Full variant: axes, ticks, stacked/overlaid lanes (Live time pane). */
  function drawFull(snap: { channels: Float32Array[]; fs: number; rev: number }) {
    if (!canvasEl) return;
    const stacked = get(monitor.stacked);
    const autoY = get(monitor.autoscaleY);
    const nCh = snap.channels.length;
    const nSamples = snap.channels[0].length;

    const ctx2d = canvasEl.getContext('2d');
    if (!ctx2d) return;
    const C = canvasColors();
    const [w, h] = fitCanvas(canvasEl, ctx2d);

    // Clear.
    ctx2d.fillStyle = C.bg;
    ctx2d.fillRect(0, 0, w, h);

    const plotW = w - MARGIN.left - MARGIN.right;
    const plotH = h - MARGIN.top - MARGIN.bottom;
    if (plotW <= 0 || plotH <= 0) return;

    // Border around the plot area.
    ctx2d.strokeStyle = C.frame;
    ctx2d.lineWidth = 1;
    ctx2d.strokeRect(MARGIN.left, MARGIN.top, plotW, plotH);

    // X axis: time in ms.
    const duration = nSamples / snap.fs;
    ctx2d.fillStyle = C.axis;
    ctx2d.font = '10px system-ui, sans-serif';
    ctx2d.textAlign = 'center';
    const xTicks = 5;
    for (let i = 0; i <= xTicks; i++) {
      const t = (i / xTicks) * duration;
      const x = MARGIN.left + (i / xTicks) * plotW;
      ctx2d.fillText(`${(t * 1000).toFixed(0)}`, x, h - MARGIN.bottom + 14);
      ctx2d.strokeStyle = C.grid;
      ctx2d.beginPath();
      ctx2d.moveTo(x, MARGIN.top);
      ctx2d.lineTo(x, MARGIN.top + plotH);
      ctx2d.stroke();
    }
    ctx2d.fillStyle = C.axis;
    ctx2d.fillText('ms', w - MARGIN.right + 4, h - MARGIN.bottom + 14);

    if (stacked) {
      const laneH = plotH / nCh;
      for (let ch = 0; ch < nCh; ch++) {
        const laneTop = MARGIN.top + ch * laneH;
        const samples = snap.channels[ch];
        const [yMin, yMax] = yRange(samples, autoY);
        if (ch > 0) {
          ctx2d.strokeStyle = C.grid;
          ctx2d.beginPath();
          ctx2d.moveTo(MARGIN.left, laneTop);
          ctx2d.lineTo(MARGIN.left + plotW, laneTop);
          ctx2d.stroke();
        }
        ctx2d.fillStyle = PALETTE[ch % PALETTE.length];
        ctx2d.font = '10px system-ui, sans-serif';
        ctx2d.textAlign = 'left';
        ctx2d.fillText(`ch${ch}`, MARGIN.left + 4, laneTop + 12);
        ctx2d.fillStyle = C.muted;
        ctx2d.textAlign = 'right';
        ctx2d.fillText(yMax.toFixed(2), MARGIN.left - 4, laneTop + 10);
        ctx2d.fillText(yMin.toFixed(2), MARGIN.left - 4, laneTop + laneH - 2);
        drawTrace(ctx2d, samples, MARGIN.left, laneTop, plotW, laneH, yMin, yMax, PALETTE[ch % PALETTE.length], 1.2);
      }
    } else {
      let globalMin = Infinity, globalMax = -Infinity;
      if (autoY) {
        for (let ch = 0; ch < nCh; ch++) {
          const [lo, hi] = yRange(snap.channels[ch], true);
          if (lo < globalMin) globalMin = lo;
          if (hi > globalMax) globalMax = hi;
        }
      } else {
        globalMin = -1; globalMax = 1;
      }
      if (!isFinite(globalMin) || !isFinite(globalMax)) { globalMin = -1; globalMax = 1; }

      ctx2d.fillStyle = C.muted;
      ctx2d.font = '10px system-ui, sans-serif';
      ctx2d.textAlign = 'right';
      ctx2d.fillText(globalMax.toFixed(2), MARGIN.left - 4, MARGIN.top + 10);
      ctx2d.fillText(globalMin.toFixed(2), MARGIN.left - 4, MARGIN.top + plotH - 2);
      const mid = (globalMin + globalMax) / 2;
      ctx2d.fillText(mid.toFixed(2), MARGIN.left - 4, MARGIN.top + plotH / 2 + 4);

      if (globalMin < 0 && globalMax > 0) {
        const zeroY = MARGIN.top + plotH * (1 - (0 - globalMin) / (globalMax - globalMin));
        ctx2d.strokeStyle = C.zero;
        ctx2d.setLineDash([4, 4]);
        ctx2d.beginPath();
        ctx2d.moveTo(MARGIN.left, zeroY);
        ctx2d.lineTo(MARGIN.left + plotW, zeroY);
        ctx2d.stroke();
        ctx2d.setLineDash([]);
      }

      for (let ch = 0; ch < nCh; ch++) {
        drawTrace(ctx2d, snap.channels[ch], MARGIN.left, MARGIN.top, plotW, plotH, globalMin, globalMax, PALETTE[ch % PALETTE.length], 1.2);
      }

      if (nCh > 1) {
        for (let ch = 0; ch < nCh; ch++) {
          const lx = MARGIN.left + 6 + ch * 50;
          ctx2d.fillStyle = PALETTE[ch % PALETTE.length];
          ctx2d.fillRect(lx, MARGIN.top + 4, 12, 3);
          ctx2d.fillText(`ch${ch}`, lx + 16, MARGIN.top + 10);
        }
      }
    }
  }

  /**
   * Draw a single channel trace.  Decimates (min–max per pixel column)
   * when nSamples > plotW to keep the line count bounded and preserve
   * peaks at long windows.
   */
  function drawTrace(
    ctx: CanvasRenderingContext2D,
    samples: Float32Array,
    x0: number, y0: number, w: number, h: number,
    yMin: number, yMax: number,
    color: string,
    lineWidth: number,
  ) {
    const n = samples.length;
    if (n === 0 || h <= 0 || w <= 0) return;
    const ySpan = yMax - yMin || 1;

    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.beginPath();

    if (n <= w) {
      for (let i = 0; i < n; i++) {
        const px = x0 + (i / (n - 1)) * w;
        const py = y0 + h * (1 - (samples[i] - yMin) / ySpan);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
    } else {
      const step = n / w;
      for (let px = 0; px < w; px++) {
        const i0 = Math.floor(px * step);
        const i1 = Math.min(n, Math.floor((px + 1) * step));
        let lo = Infinity, hi = -Infinity;
        for (let i = i0; i < i1; i++) {
          if (samples[i] < lo) lo = samples[i];
          if (samples[i] > hi) hi = samples[i];
        }
        const xPx = x0 + px;
        const yLo = y0 + h * (1 - (lo - yMin) / ySpan);
        const yHi = y0 + h * (1 - (hi - yMin) / ySpan);
        if (px === 0) ctx.moveTo(xPx, yHi);
        else ctx.lineTo(xPx, yHi);
        ctx.lineTo(xPx, yLo);
      }
    }
    ctx.stroke();
  }
</script>

<canvas bind:this={canvasEl} class="osc-canvas" data-testid="osc-canvas"></canvas>

<style>
  .osc-canvas {
    width: 100%;
    height: 100%;
    display: block;
  }
</style>
