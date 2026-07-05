<script lang="ts">
  /**
   * Canvas-rendered real-time oscilloscope (design spec §8).
   *
   * Draws the monitor store's ring buffer as time-domain traces using
   * requestAnimationFrame.  Two modes: **overlaid** (all channels share
   * one vertical axis, like a typical scope) and **stacked** (each
   * channel gets its own vertical lane, the Qt many-channel idiom so
   * 10 channels remain readable).
   *
   * The canvas fills the `.plot-host` container (sized by CSS flex)
   * and redraws whenever:
   * - The ring revision changes (new audio data arrived), or
   * - The `stacked` or `autoscaleY` toggles flip.
   *
   * Performance target: stable 30 fps for up to 16 channels at 48 kHz.
   * The ring buffer is small (~100 ms = ~4800 samples), so iteration
   * cost is negligible compared to `putImageData` overhead. Line
   * decimation is applied when sample count exceeds pixel width.
   */
  import { onMount, onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import type { MonitorStore } from '../lib/stores/monitor';

  // Plot palette — shared with the SVG analysis plots.
  const PALETTE = [
    '#6366f1', '#f97316', '#10b981', '#f43f5e', '#8b5cf6',
    '#06b6d4', '#eab308', '#ec4899', '#14b8a6', '#a855f7',
  ];

  let {
    monitor,
  }: {
    monitor: MonitorStore;
  } = $props();

  let canvasEl: HTMLCanvasElement | undefined = $state();
  let raf = 0;
  let lastRev = -1;
  let mounted = true;

  // Layout constants.
  const MARGIN = { top: 12, right: 12, bottom: 28, left: 50 };

  onMount(() => {
    mounted = true;
    raf = requestAnimationFrame(draw);
  });

  onDestroy(() => {
    mounted = false;
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
    // Add 10% headroom; clamp to avoid a zero-height range.
    const margin = Math.max(0.001, (max - min) * 0.1);
    return [min - margin, max + margin];
  }

  function draw() {
    if (!mounted) return;
    raf = requestAnimationFrame(draw);
    if (!canvasEl) return;

    const snap = monitor.snapshot();
    if (snap.channels.length === 0) {
      // No data — draw an empty "waiting" state.
      const ctx2d = canvasEl.getContext('2d');
      if (!ctx2d) return;
      const dpr = window.devicePixelRatio || 1;
      const w = canvasEl.clientWidth;
      const h = canvasEl.clientHeight;
      canvasEl.width = w * dpr;
      canvasEl.height = h * dpr;
      ctx2d.scale(dpr, dpr);
      ctx2d.fillStyle = 'var(--surface, #fff)';
      ctx2d.fillRect(0, 0, w, h);
      ctx2d.fillStyle = '#9ca3af';
      ctx2d.font = '13px system-ui, sans-serif';
      ctx2d.textAlign = 'center';
      ctx2d.fillText('Start the monitor to see live traces', w / 2, h / 2);
      return;
    }

    // Skip redraw if nothing changed (saves CPU while paused).
    if (snap.rev === lastRev) return;
    lastRev = snap.rev;

    const stacked = get(monitor.stacked);
    const autoY = get(monitor.autoscaleY);
    const nCh = snap.channels.length;
    const nSamples = snap.channels[0].length;

    const ctx2d = canvasEl.getContext('2d');
    if (!ctx2d) return;

    // Resize canvas buffer to match CSS size × devicePixelRatio.
    const dpr = window.devicePixelRatio || 1;
    const w = canvasEl.clientWidth;
    const h = canvasEl.clientHeight;
    canvasEl.width = w * dpr;
    canvasEl.height = h * dpr;
    ctx2d.scale(dpr, dpr);

    // Clear.
    ctx2d.fillStyle = '#fff';
    ctx2d.fillRect(0, 0, w, h);

    const plotW = w - MARGIN.left - MARGIN.right;
    const plotH = h - MARGIN.top - MARGIN.bottom;

    if (plotW <= 0 || plotH <= 0) return;

    // Draw a border around the plot area.
    ctx2d.strokeStyle = '#d1d5db';
    ctx2d.lineWidth = 1;
    ctx2d.strokeRect(MARGIN.left, MARGIN.top, plotW, plotH);

    // X axis: time scale from 0 to window duration.
    const duration = nSamples / snap.fs;
    ctx2d.fillStyle = '#6b7280';
    ctx2d.font = '10px system-ui, sans-serif';
    ctx2d.textAlign = 'center';
    // A few tick labels.
    const xTicks = 5;
    for (let i = 0; i <= xTicks; i++) {
      const t = (i / xTicks) * duration;
      const x = MARGIN.left + (i / xTicks) * plotW;
      ctx2d.fillText(`${(t * 1000).toFixed(0)}`, x, h - MARGIN.bottom + 14);
      // Tick mark.
      ctx2d.strokeStyle = '#e5e7eb';
      ctx2d.beginPath();
      ctx2d.moveTo(x, MARGIN.top);
      ctx2d.lineTo(x, MARGIN.top + plotH);
      ctx2d.stroke();
    }
    ctx2d.fillStyle = '#6b7280';
    ctx2d.fillText('ms', w - MARGIN.right + 4, h - MARGIN.bottom + 14);

    // Draw each channel.
    if (stacked) {
      // Stacked: each channel gets an equal vertical lane.
      const laneH = plotH / nCh;
      for (let ch = 0; ch < nCh; ch++) {
        const laneTop = MARGIN.top + ch * laneH;
        const samples = snap.channels[ch];
        const [yMin, yMax] = yRange(samples, autoY);

        // Lane separator.
        if (ch > 0) {
          ctx2d.strokeStyle = '#e5e7eb';
          ctx2d.beginPath();
          ctx2d.moveTo(MARGIN.left, laneTop);
          ctx2d.lineTo(MARGIN.left + plotW, laneTop);
          ctx2d.stroke();
        }

        // Channel label.
        ctx2d.fillStyle = PALETTE[ch % PALETTE.length];
        ctx2d.font = '10px system-ui, sans-serif';
        ctx2d.textAlign = 'left';
        ctx2d.fillText(`ch${ch}`, MARGIN.left + 4, laneTop + 12);

        // Y axis labels for this lane.
        ctx2d.fillStyle = '#9ca3af';
        ctx2d.textAlign = 'right';
        ctx2d.fillText(yMax.toFixed(2), MARGIN.left - 4, laneTop + 10);
        ctx2d.fillText(yMin.toFixed(2), MARGIN.left - 4, laneTop + laneH - 2);

        // Trace.
        drawTrace(ctx2d, samples, MARGIN.left, laneTop, plotW, laneH, yMin, yMax, PALETTE[ch % PALETTE.length]);
      }
    } else {
      // Overlaid: all channels share one Y range.
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

      // Y axis labels.
      ctx2d.fillStyle = '#9ca3af';
      ctx2d.font = '10px system-ui, sans-serif';
      ctx2d.textAlign = 'right';
      ctx2d.fillText(globalMax.toFixed(2), MARGIN.left - 4, MARGIN.top + 10);
      ctx2d.fillText(globalMin.toFixed(2), MARGIN.left - 4, MARGIN.top + plotH - 2);
      const mid = (globalMin + globalMax) / 2;
      ctx2d.fillText(mid.toFixed(2), MARGIN.left - 4, MARGIN.top + plotH / 2 + 4);

      // Zero line.
      if (globalMin < 0 && globalMax > 0) {
        const zeroY = MARGIN.top + plotH * (1 - (0 - globalMin) / (globalMax - globalMin));
        ctx2d.strokeStyle = '#d1d5db';
        ctx2d.setLineDash([4, 4]);
        ctx2d.beginPath();
        ctx2d.moveTo(MARGIN.left, zeroY);
        ctx2d.lineTo(MARGIN.left + plotW, zeroY);
        ctx2d.stroke();
        ctx2d.setLineDash([]);
      }

      for (let ch = 0; ch < nCh; ch++) {
        drawTrace(ctx2d, snap.channels[ch], MARGIN.left, MARGIN.top, plotW, plotH, globalMin, globalMax, PALETTE[ch % PALETTE.length]);
      }

      // Channel legend.
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
   * Draw a single channel trace.  Decimates when nSamples > plotW to
   * keep the line count bounded at one segment per pixel.
   */
  function drawTrace(
    ctx: CanvasRenderingContext2D,
    samples: Float32Array,
    x0: number, y0: number, w: number, h: number,
    yMin: number, yMax: number,
    color: string,
  ) {
    const n = samples.length;
    if (n === 0 || h <= 0) return;
    const ySpan = yMax - yMin || 1;

    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    ctx.beginPath();

    if (n <= w) {
      // No decimation needed — draw each sample as a point.
      for (let i = 0; i < n; i++) {
        const px = x0 + (i / (n - 1)) * w;
        const py = y0 + h * (1 - (samples[i] - yMin) / ySpan);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
    } else {
      // Decimate: for each pixel column, draw the min–max vertical span
      // to preserve peaks (LTTB-like but simpler).
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
