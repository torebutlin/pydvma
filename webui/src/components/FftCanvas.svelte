<script lang="ts">
  /**
   * Canvas-rendered live FFT pane for the expanded Live scope (design
   * spec §8; visuals ported from `drawFFT` in round2-bench.html).
   *
   * Each animation frame it takes the monitor ring-buffer snapshot,
   * computes a one-sided amplitude spectrum per channel with the small
   * in-browser radix-2 FFT (`lib/audio/fft.ts`, Hann-windowed), and draws
   * each channel as a filled area at low alpha plus a 1.2 px stroke in the
   * shared trace palette.
   *
   * Axis scaling follows the monitor store: `fftYLog` picks dB vs linear
   * magnitude, `fftXLog` picks a log vs linear frequency axis.  The
   * rev-skip guard means a paused/idle scope costs nothing, and drawing is
   * skipped entirely while `active` is false.
   */
  import { onMount, onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import type { MonitorStore } from '../lib/stores/monitor';
  import { magnitudeSpectrum } from '../lib/audio/fft';

  const PALETTE = [
    '#6366f1', '#f97316', '#10b981', '#f43f5e', '#8b5cf6',
    '#06b6d4', '#eab308', '#ec4899', '#14b8a6', '#a855f7',
  ];
  const FILL = [
    'rgba(99,102,241,.12)', 'rgba(249,115,22,.12)', 'rgba(16,185,129,.12)',
    'rgba(244,63,94,.12)', 'rgba(139,92,246,.12)', 'rgba(6,182,212,.12)',
    'rgba(234,179,8,.12)', 'rgba(236,72,153,.12)', 'rgba(20,184,166,.12)',
    'rgba(168,85,247,.12)',
  ];

  const MARGIN = { top: 10, right: 12, bottom: 22, left: 44 };
  const DB_FLOOR = -100; // dB floor for the log magnitude axis

  let {
    monitor,
    active = true,
  }: {
    monitor: MonitorStore;
    active?: boolean;
  } = $props();

  let canvasEl: HTMLCanvasElement | undefined = $state();
  let raf = 0;
  let mounted = true;

  onMount(() => { mounted = true; raf = requestAnimationFrame(draw); });
  onDestroy(() => { mounted = false; if (raf) cancelAnimationFrame(raf); });

  function fitCanvas(cv: HTMLCanvasElement, ctx: CanvasRenderingContext2D): [number, number] {
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth, h = cv.clientHeight;
    cv.width = Math.max(1, Math.round(w * dpr));
    cv.height = Math.max(1, Math.round(h * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return [w, h];
  }

  function draw() {
    if (!mounted) return;
    raf = requestAnimationFrame(draw);
    if (!canvasEl || !active) return;

    const ctx = canvasEl.getContext('2d');
    if (!ctx) return;
    const [w, h] = fitCanvas(canvasEl, ctx);
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, w, h);

    const plotW = w - MARGIN.left - MARGIN.right;
    const plotH = h - MARGIN.top - MARGIN.bottom;
    if (plotW <= 0 || plotH <= 0) return;

    const snap = monitor.snapshot();
    const nCh = snap.channels.length;
    const fs = snap.fs;
    const yLog = get(monitor.fftYLog);
    const xLog = get(monitor.fftXLog);

    // Per-channel spectra.
    const specs = snap.channels.map((c) => magnitudeSpectrum(c, true));
    const size = specs[0]?.size ?? 0;
    const nBins = specs[0]?.mag.length ?? 0;
    const fMax = fs / 2;

    // Border.
    ctx.strokeStyle = '#d1d5db';
    ctx.lineWidth = 1;
    ctx.strokeRect(MARGIN.left, MARGIN.top, plotW, plotH);

    if (nCh === 0 || nBins < 2 || size < 2) {
      ctx.fillStyle = '#9ca3af';
      ctx.font = '12px system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('FFT — start the monitor', MARGIN.left + plotW / 2, MARGIN.top + plotH / 2);
      return;
    }

    // Y mapping.
    let yMax = 0;
    for (const s of specs) for (const m of s.mag) if (m > yMax) yMax = m;
    if (yMax <= 0) yMax = 1;
    const yTop = yLog ? 20 * Math.log10(yMax) + 6 : yMax * 1.1;
    const yBot = yLog ? DB_FLOOR : 0;
    const mapY = (m: number): number => {
      const v = yLog ? (m > 0 ? 20 * Math.log10(m) : DB_FLOOR) : m;
      const t = (v - yBot) / (yTop - yBot || 1);
      return MARGIN.top + plotH * (1 - Math.max(0, Math.min(1, t)));
    };

    // X mapping: bin index → frequency → pixel.
    const binHz = fMax / (nBins - 1);
    const fMin = xLog ? Math.max(binHz, 1) : 0;
    const logMin = Math.log10(Math.max(fMin, 1e-6));
    const logMax = Math.log10(Math.max(fMax, fMin + 1));
    const mapX = (bin: number): number => {
      const f = bin * binHz;
      const t = xLog
        ? (Math.log10(Math.max(f, fMin)) - logMin) / (logMax - logMin || 1)
        : f / (fMax || 1);
      return MARGIN.left + plotW * Math.max(0, Math.min(1, t));
    };

    // Gridlines (horizontal).
    ctx.strokeStyle = '#eef0f4';
    ctx.lineWidth = 1;
    for (let i = 1; i < 4; i++) {
      const gy = MARGIN.top + (plotH * i) / 4;
      ctx.beginPath();
      ctx.moveTo(MARGIN.left, gy);
      ctx.lineTo(MARGIN.left + plotW, gy);
      ctx.stroke();
    }

    // Traces (filled area + stroke), one per channel.
    const startBin = xLog ? 1 : 0; // skip DC on a log axis
    for (let ch = 0; ch < nCh; ch++) {
      const mag = specs[ch].mag;
      ctx.beginPath();
      ctx.moveTo(mapX(startBin), MARGIN.top + plotH);
      for (let b = startBin; b < mag.length; b++) {
        ctx.lineTo(mapX(b), mapY(mag[b]));
      }
      ctx.lineTo(mapX(mag.length - 1), MARGIN.top + plotH);
      ctx.closePath();
      ctx.fillStyle = FILL[ch % FILL.length];
      ctx.fill();

      ctx.beginPath();
      for (let b = startBin; b < mag.length; b++) {
        const px = mapX(b), py = mapY(mag[b]);
        if (b === startBin) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.strokeStyle = PALETTE[ch % PALETTE.length];
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }

    // Axis labels.
    ctx.fillStyle = '#6b7280';
    ctx.font = '10px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(`${(fMax / 1000).toFixed(1)} kHz`, MARGIN.left + plotW, h - MARGIN.bottom + 14);
    ctx.textAlign = 'left';
    ctx.fillText(xLog ? 'log f' : '0', MARGIN.left, h - MARGIN.bottom + 14);
    ctx.textAlign = 'right';
    ctx.fillText(yLog ? 'dB' : 'lin', MARGIN.left - 4, MARGIN.top + 9);
  }
</script>

<canvas bind:this={canvasEl} class="fft-canvas" data-testid="fft-canvas"></canvas>

<style>
  .fft-canvas {
    width: 100%;
    height: 100%;
    display: block;
  }
</style>
