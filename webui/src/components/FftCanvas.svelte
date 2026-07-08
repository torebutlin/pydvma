<script lang="ts">
  /**
   * Canvas-rendered live FFT / PSD pane for the expanded Live scope
   * (design spec §8; visuals ported from `drawFFT` in round2-bench.html,
   * extended in round-3).
   *
   * Two spectrum modes, driven by the monitor store's `spectrumMode`:
   * - **instant** — the per-frame one-sided amplitude spectrum from the
   *   small in-browser radix-2 FFT (`lib/audio/fft.ts`, Hann-windowed);
   *   the y axis is amplitude (dB = 20·log₁₀, or linear).
   * - **psd** — an averaged Welch power spectral density over the ring
   *   buffer (`welchPsd`): the window is split into `psdSegments`
   *   50 %-overlap Hann segments and the periodograms averaged, giving a
   *   low-variance estimate in unit²/Hz (dB = 10·log₁₀, or linear).  An
   *   optional exponential temporal smoothing (`psdSmoothing`) blends the
   *   PSD across frames for an even steadier noise floor.
   *
   * Axis scaling follows the store: `fftYLog` picks dB vs linear, `fftXLog`
   * picks a log vs linear frequency axis, and `fftFMax` zooms the frequency
   * axis to a band (`null` = full / Nyquist).  A rev-skip guard means a
   * paused/idle scope costs nothing, drawing is skipped while `active` is
   * false, and the spectra are only recomputed when the ring data or a
   * display setting actually changes.
   */
  import { onMount, onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import type { MonitorStore } from '../lib/stores/monitor';
  import { magnitudeSpectrum, welchPsd } from '../lib/audio/fft';
  import { canvasColors } from '../lib/plot/canvasTheme';
  import { theme } from '../lib/stores/theme';

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
  const DYN_RANGE_DB = 100; // decades of log-axis dynamic range below the peak

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

  // Rev-skip state (mirror OscCanvas): only recompute the spectra when the
  // ring data or a display setting changes, or the pane just became active.
  let lastRev = -1;
  let lastSig = '';
  let lastActive = true;

  // Persistent exponentially-smoothed PSD, one array per channel (PSD mode
  // only). Reset whenever the channel count or bin count changes.
  let smoothed: Float64Array[] | null = null;

  onMount(() => { mounted = true; raf = requestAnimationFrame(draw); });
  // Repaint on a theme flip (colours are read at draw time; rev-skip would
  // otherwise hold the stale-theme frame).
  const unsubTheme = theme.subscribe(() => { lastRev = -1; });
  onDestroy(() => { mounted = false; unsubTheme(); if (raf) cancelAnimationFrame(raf); });

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
    if (!canvasEl || !active) { if (!active) lastActive = false; return; }
    const becameActive = !lastActive;
    lastActive = true;

    const ctx = canvasEl.getContext('2d');
    if (!ctx) return;

    const snap = monitor.snapshot();
    const yLog = get(monitor.fftYLog);
    const xLog = get(monitor.fftXLog);
    const mode = get(monitor.spectrumMode);
    const fMaxCfg = get(monitor.fftFMax);
    const fMinCfg = get(monitor.fftFMin);
    const segments = get(monitor.psdSegments);
    const smoothing = get(monitor.psdSmoothing);

    // Rev-skip: nothing changed and we're not re-entering → don't repaint.
    const sig = `${yLog}|${xLog}|${mode}|${fMinCfg}|${fMaxCfg}|${segments}|${smoothing}`;
    if (snap.rev === lastRev && sig === lastSig && !becameActive) return;
    lastRev = snap.rev;
    lastSig = sig;

    const C = canvasColors();
    const [w, h] = fitCanvas(canvasEl, ctx);
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, w, h);

    const plotW = w - MARGIN.left - MARGIN.right;
    const plotH = h - MARGIN.top - MARGIN.bottom;
    if (plotW <= 0 || plotH <= 0) return;

    const nCh = snap.channels.length;
    const fs = snap.fs;
    const nyquist = fs / 2;
    const isPsd = mode === 'psd';

    // Border.
    ctx.strokeStyle = C.frame;
    ctx.lineWidth = 1;
    ctx.strokeRect(MARGIN.left, MARGIN.top, plotW, plotH);

    // Per-channel spectra: freqs[] + vals[] (amplitude or PSD power).
    const freqsByCh: Float64Array[] = [];
    const valsByCh: Float64Array[] = [];
    for (let ch = 0; ch < nCh; ch++) {
      if (isPsd) {
        const r = welchPsd(snap.channels[ch], { fs, segments, applyHann: true });
        freqsByCh.push(r.freqs);
        valsByCh.push(r.psd);
      } else {
        const s = magnitudeSpectrum(snap.channels[ch], true);
        const nBins = s.mag.length;
        const binHz = s.size > 0 ? fs / s.size : 0;
        const f = new Float64Array(nBins);
        for (let k = 0; k < nBins; k++) f[k] = k * binHz;
        freqsByCh.push(f);
        valsByCh.push(s.mag);
      }
    }

    const nBins = valsByCh[0]?.length ?? 0;
    if (nCh === 0 || nBins < 2 || !(fs > 0)) {
      smoothed = null;
      ctx.fillStyle = C.muted;
      ctx.font = '12px system-ui, sans-serif';
      ctx.textAlign = 'center';
      const msg = isPsd ? 'PSD — start the monitor' : 'FFT — start the monitor';
      ctx.fillText(msg, MARGIN.left + plotW / 2, MARGIN.top + plotH / 2);
      return;
    }

    // Exponential temporal smoothing (PSD mode only).
    let plotVals = valsByCh;
    if (isPsd && smoothing > 0) {
      if (!smoothed || smoothed.length !== nCh || smoothed[0].length !== nBins) {
        smoothed = valsByCh.map((v) => Float64Array.from(v));
      } else {
        for (let ch = 0; ch < nCh; ch++) {
          const s = smoothed[ch], v = valsByCh[ch];
          for (let k = 0; k < nBins; k++) s[k] = smoothing * s[k] + (1 - smoothing) * v[k];
        }
      }
      plotVals = smoothed;
    } else {
      smoothed = null;
    }

    // Display frequency span: clamp the configured max to Nyquist.
    let fMaxDisplay = fMaxCfg == null ? nyquist : Math.min(fMaxCfg, nyquist);
    if (!(fMaxDisplay > 0)) fMaxDisplay = nyquist;
    // Low edge of the display band: DC (linear) / first bin (log), raised to a
    // configured `fMinCfg` when set. Guard against an inverted/degenerate band.
    const df0 = freqsByCh[0][1] - freqsByCh[0][0] || nyquist;
    const naturalLow = xLog ? Math.max(df0, 1) : 0;
    let fMinDisplay = fMinCfg == null ? naturalLow : Math.max(naturalLow, fMinCfg);
    if (!(fMinDisplay < fMaxDisplay)) fMinDisplay = naturalLow;

    // Value → display transform (dB uses 20·log for amplitude, 10·log for power).
    const dbFactor = isPsd ? 10 : 20;
    const toDisp = (v: number): number =>
      yLog ? (v > 0 ? dbFactor * Math.log10(v) : -Infinity) : v;

    // Y range over the DISPLAYED band only ([fMinDisplay, fMaxDisplay]).
    let vMax = -Infinity;
    for (let ch = 0; ch < nCh; ch++) {
      const f = freqsByCh[ch], vv = plotVals[ch];
      for (let k = 0; k < vv.length; k++) {
        if (f[k] > fMaxDisplay) break;
        if (f[k] < fMinDisplay) continue;
        const d = toDisp(vv[k]);
        if (isFinite(d) && d > vMax) vMax = d;
      }
    }
    if (!isFinite(vMax)) vMax = yLog ? 0 : 1;
    const yTop = yLog ? vMax + 6 : Math.max(vMax * 1.1, 1e-12);
    const yBot = yLog ? yTop - DYN_RANGE_DB : 0;
    const floorDisp = yLog ? yBot : 0;
    const mapY = (v: number): number => {
      const d = toDisp(v);
      const dv = isFinite(d) ? d : floorDisp;
      const t = (dv - yBot) / (yTop - yBot || 1);
      return MARGIN.top + plotH * (1 - Math.max(0, Math.min(1, t)));
    };

    // X mapping: frequency → pixel over [fMinDisplay, fMaxDisplay].
    const logMin = Math.log10(Math.max(fMinDisplay, 1e-6));
    const logMax = Math.log10(Math.max(fMaxDisplay, fMinDisplay + 1));
    const mapX = (f: number): number => {
      const t = xLog
        ? (Math.log10(Math.max(f, fMinDisplay)) - logMin) / (logMax - logMin || 1)
        : (f - fMinDisplay) / ((fMaxDisplay - fMinDisplay) || 1);
      return MARGIN.left + plotW * Math.max(0, Math.min(1, t));
    };

    // Horizontal gridlines.
    ctx.strokeStyle = C.grid;
    ctx.lineWidth = 1;
    for (let i = 1; i < 4; i++) {
      const gy = MARGIN.top + (plotH * i) / 4;
      ctx.beginPath();
      ctx.moveTo(MARGIN.left, gy);
      ctx.lineTo(MARGIN.left + plotW, gy);
      ctx.stroke();
    }

    // Traces (filled area + stroke), one per channel, over the display band.
    for (let ch = 0; ch < nCh; ch++) {
      const f = freqsByCh[ch], vv = plotVals[ch];
      let startBin = xLog ? 1 : 0; // skip DC on a log axis
      // Advance to the first bin inside the display band's low edge.
      while (startBin < vv.length && f[startBin] < fMinDisplay) startBin++;
      // Find the last bin within the display band.
      let endBin = startBin;
      for (let k = startBin; k < vv.length; k++) {
        if (f[k] > fMaxDisplay) break;
        endBin = k;
      }
      if (endBin <= startBin) continue;
      const baseline = MARGIN.top + plotH;

      ctx.beginPath();
      ctx.moveTo(mapX(f[startBin]), baseline);
      for (let k = startBin; k <= endBin; k++) ctx.lineTo(mapX(f[k]), mapY(vv[k]));
      ctx.lineTo(mapX(f[endBin]), baseline);
      ctx.closePath();
      ctx.fillStyle = FILL[ch % FILL.length];
      ctx.fill();

      ctx.beginPath();
      for (let k = startBin; k <= endBin; k++) {
        const px = mapX(f[k]), py = mapY(vv[k]);
        if (k === startBin) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.strokeStyle = PALETTE[ch % PALETTE.length];
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }

    // Axis labels.
    ctx.fillStyle = C.axis;
    ctx.font = '10px system-ui, sans-serif';
    const fmtHz = (v: number): string => v >= 1000
      ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)} kHz`
      : `${Math.round(v)} Hz`;
    ctx.textAlign = 'right';
    ctx.fillText(fmtHz(fMaxDisplay), MARGIN.left + plotW, h - MARGIN.bottom + 14);
    ctx.textAlign = 'left';
    // Left edge shows the band start when a min is set; else the axis origin.
    const leftLabel = xLog ? 'log f' : (fMinDisplay > 0 ? fmtHz(fMinDisplay) : '0');
    ctx.fillText(leftLabel, MARGIN.left, h - MARGIN.bottom + 14);
    // Y-axis unit label (amplitude vs power density).
    ctx.textAlign = 'right';
    const yLabel = isPsd ? (yLog ? 'dB/Hz' : 'u²/Hz') : (yLog ? 'dB' : 'lin');
    ctx.fillText(yLabel, MARGIN.left - 4, MARGIN.top + 9);
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
