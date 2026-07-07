<script lang="ts">
  /**
   * Expanded Live oscilloscope — the Live stage's figure content (design
   * spec §8; ported from the `#monOverlay .mon-panel` block of
   * round2-bench.html, but rendered INLINE in the plot area, not as a
   * modal).  This is the "expanded" form of the bottom-left mini monitor:
   * clicking the mini's ⤢ (or its trace) switches to the Live stage,
   * which shows this.
   *
   * Three panes on the mockup's `.mon-grid`:
   * - time (top-left)  — the full OscCanvas time trace
   * - fft  (bottom-left) — the live FFT pane
   * - levels (right, spanning both rows) — input level bars + CLIP pill
   *
   * A toolbar of chip toggles T / F / L / P (active = indigo) shows/hides
   * panes and pauses; hidden panes free their grid space.  Pane state,
   * pause and the latching clip all live on the monitor store so the mini
   * and the expanded scope stay in lock-step.
   */
  import type { MonitorStore } from '../lib/stores/monitor';
  import OscCanvas from './OscCanvas.svelte';
  import FftCanvas from './FftCanvas.svelte';
  import LevelBars from './LevelBars.svelte';

  let {
    monitor,
  }: {
    monitor: MonitorStore;
  } = $props();

  const status = $derived(monitor.status);
  const panes = $derived(monitor.panes);
  const isPaused = $derived($status === 'paused');
  const isRunning = $derived($status === 'streaming' || $status === 'paused');

  const timeOn = $derived($panes.time);
  const freqOn = $derived($panes.freq);
  const levelsOn = $derived($panes.levels);

  // Grid template: right levels column only when levels are shown; two
  // rows only when both time and freq panes are visible.
  const gridStyle = $derived.by(() => {
    const cols = levelsOn ? '1fr 220px' : '1fr';
    const rows = timeOn && freqOn ? '1fr 1fr' : '1fr';
    return `grid-template-columns:${cols};grid-template-rows:${rows}`;
  });
  const timeRow = $derived(freqOn ? '1' : '1 / -1');
  const freqRow = $derived(timeOn ? '2' : '1 / -1');

  function togglePause() {
    monitor.togglePause();
  }
</script>

<div class="live-scope" data-testid="live-scope">
  <div class="scope-bar">
    <span class="sec-label">Oscilloscope — live monitor</span>
    <div class="chips">
      <button class="chip" class:on={timeOn} onclick={() => monitor.togglePane('time')} title="Toggle the time trace pane">T time</button>
      <button class="chip" class:on={freqOn} onclick={() => monitor.togglePane('freq')} title="Toggle the FFT pane">F freq</button>
      <button class="chip" class:on={levelsOn} onclick={() => monitor.togglePane('levels')} title="Toggle the levels pane">L levels</button>
      <button class="chip" class:on={isPaused} disabled={!isRunning} onclick={togglePause} title="Freeze / resume the trace">P pause</button>
    </div>
  </div>

  <div class="mon-grid" style={gridStyle}>
    {#if timeOn}
      <div class="mon-cell" style="grid-column:1;grid-row:{timeRow}">
        <span class="cell-lab">time</span>
        <OscCanvas {monitor} variant="full" />
      </div>
    {/if}
    {#if freqOn}
      <div class="mon-cell" style="grid-column:1;grid-row:{freqRow}">
        <span class="cell-lab">fft</span>
        <FftCanvas {monitor} active={freqOn} />
      </div>
    {/if}
    {#if levelsOn}
      <div class="mon-cell levels-cell" style="grid-column:2;grid-row:1 / -1">
        <span class="cell-lab">levels</span>
        <LevelBars {monitor} variant="big" />
      </div>
    {/if}
  </div>
</div>

<style>
  .live-scope {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    padding: 10px 12px 12px;
    gap: 8px;
    min-height: 0;
  }
  .scope-bar {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .sec-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
  }
  .chips {
    display: flex;
    gap: 5px;
    margin-left: auto;
  }
  .chip {
    height: 25px;
    padding: 0 9px;
    border-radius: 7px;
    border: 1px solid var(--border);
    background: #fff;
    color: var(--muted);
    font: 600 11.5px var(--font-mono);
    cursor: pointer;
  }
  .chip:hover {
    border-color: #c6cbd6;
    color: var(--text);
  }
  .chip.on {
    background: #eef0ff;
    border-color: #c7d2fe;
    color: var(--indigo);
  }
  .chip[disabled] {
    opacity: 0.45;
    pointer-events: none;
  }
  .mon-grid {
    flex: 1;
    min-height: 0;
    display: grid;
    gap: 10px;
  }
  .mon-cell {
    background: #fff;
    border: 1px solid var(--border);
    border-radius: 9px;
    position: relative;
    overflow: hidden;
    min-height: 0;
  }
  .cell-lab {
    position: absolute;
    top: 5px;
    left: 9px;
    z-index: 2;
    font: 600 10px var(--font-mono);
    letter-spacing: 0.07em;
    color: #a3aabc;
    text-transform: uppercase;
    pointer-events: none;
  }
  .levels-cell {
    display: flex;
    align-items: flex-end;
    justify-content: center;
    gap: 18px;
    padding: 30px 12px 22px;
  }
  /* The levels component fills the cell height so its bars scale. */
  .levels-cell :global(.levelbars) {
    height: 100%;
    align-items: stretch;
  }
</style>
