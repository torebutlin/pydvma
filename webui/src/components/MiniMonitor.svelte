<script lang="ts">
  /**
   * Persistent bottom-left mini-oscilloscope (round-2 redesign; visuals
   * ported from the `.monitor-mini` block of round2-bench.html).
   *
   * Docked at the FOOT of the data tray, below `<Tray>`, so it is visible
   * on EVERY stage — that persistent presence is how the user knows the
   * mic is live.  It has its OWN start/stop (independent of the Live
   * stage): when idle it shows a compact Start affordance so the monitor
   * is discoverable; once streaming it shows a live time trace + input
   * level bars + a latching CLIP pill.
   *
   * Two affordances open the expanded scope (the Live stage): the ⤢
   * button and clicking the mini trace.  The ▾ button collapses just the
   * body (keeping the header), and while collapsed the trace stops
   * drawing (`active=false`) so a hidden mini costs nothing.
   *
   * NO FFT here — the mini is time trace + levels + clip only; the FFT
   * lives in the expanded Live scope.
   */
  import type { MonitorStore } from '../lib/stores/monitor';
  import { activeStage } from '../lib/stores/stages';
  import OscCanvas from './OscCanvas.svelte';
  import LevelBars from './LevelBars.svelte';

  let {
    monitor,
  }: {
    monitor: MonitorStore;
  } = $props();

  const status = $derived(monitor.status);
  const errorMsg = $derived(monitor.errorMsg);

  const isStreaming = $derived($status === 'streaming' || $status === 'paused');
  const isStarting = $derived($status === 'starting');

  // Body collapse is local UI state (the header stays, the trace hides).
  let collapsed = $state(false);

  function expand() {
    activeStage.set('live');
  }
  function toggleCollapse() {
    collapsed = !collapsed;
  }
  function startMonitor() {
    void monitor.start();
  }
  function stopMonitor() {
    monitor.stop();
  }
</script>

<section class="monitor-mini" data-testid="mini-monitor" aria-label="Live input monitor">
  <div class="mon-head">
    <span class="mon-dot" class:live={isStreaming}></span>
    <span class="sec-label">Monitor</span>
    {#if isStreaming}
      <span class="mon-live">live</span>
    {:else if isStarting}
      <span class="mon-off">opening…</span>
    {:else}
      <span class="mon-off">off</span>
    {/if}
    <span class="spacer"></span>
    {#if isStreaming}
      <button class="mini-ib" title="Expand the oscilloscope (Live stage)" aria-label="Expand oscilloscope" onclick={expand}>⤢</button>
      <button class="mini-ib" title={collapsed ? 'Show the monitor' : 'Hide the monitor'} aria-label="Toggle monitor body" onclick={toggleCollapse}>{collapsed ? '▸' : '▾'}</button>
    {/if}
  </div>

  {#if !collapsed}
    <div class="mon-body">
      {#if isStreaming}
        <button
          class="mon-canvas-wrap"
          title="Open the expanded oscilloscope"
          aria-label="Open expanded oscilloscope"
          onclick={expand}
        >
          <OscCanvas {monitor} variant="compact" active={!collapsed} />
        </button>
        <LevelBars {monitor} variant="mini" />
      {:else if isStarting}
        <div class="mon-idle"><span class="note">Opening microphone…</span></div>
      {:else}
        <div class="mon-idle">
          <span class="note">Monitor is off</span>
          <button class="mini-start" onclick={startMonitor} data-testid="mini-start">▶ Start</button>
        </div>
      {/if}
    </div>
    {#if isStreaming}
      <div class="mon-foot">
        <button class="mini-stop" onclick={stopMonitor} data-testid="mini-stop">Stop</button>
      </div>
    {/if}
    {#if $errorMsg && !isStreaming}
      <div class="mon-err" role="alert">{$errorMsg}</div>
    {/if}
  {/if}
</section>

<style>
  .monitor-mini {
    flex: 0 0 auto;
    border-top: 1px solid var(--border);
    background: #fbfcfe;
    padding: 7px 12px 10px;
  }
  .mon-head {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-bottom: 5px;
  }
  .sec-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
  }
  .mon-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #c7ccd8;
    flex: 0 0 auto;
  }
  .mon-dot.live {
    background: var(--green);
    box-shadow: 0 0 0 3px rgba(22, 163, 74, 0.15);
    animation: mon-pulse 1.6s ease-in-out infinite;
  }
  @keyframes mon-pulse {
    0%, 100% { box-shadow: 0 0 0 3px rgba(22, 163, 74, 0.15); }
    50% { box-shadow: 0 0 0 5px rgba(22, 163, 74, 0.05); }
  }
  @media (prefers-reduced-motion: reduce) {
    .mon-dot.live { animation: none; }
  }
  .mon-live {
    font: 600 10px var(--font-mono);
    color: var(--green);
  }
  .mon-off {
    font: 600 10px var(--font-mono);
    color: #a3aabc;
  }
  .spacer {
    flex: 1;
  }
  .mini-ib {
    width: 22px;
    height: 22px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: #fff;
    cursor: pointer;
    color: var(--muted);
    font-size: 11px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
  }
  .mini-ib:hover {
    color: var(--text);
    border-color: #c6cbd6;
  }
  .mon-body {
    display: flex;
    gap: 8px;
    align-items: stretch;
  }
  .mon-canvas-wrap {
    flex: 1;
    min-width: 0;
    height: 52px;
    padding: 0;
    background: #fff;
    border: 1px solid var(--border);
    border-radius: 7px;
    overflow: hidden;
    cursor: pointer;
    display: block;
  }
  .mon-canvas-wrap:hover {
    border-color: #c6cbd6;
  }
  .mon-idle {
    flex: 1;
    height: 52px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 0 4px;
  }
  .note {
    font-size: 11px;
    color: var(--muted);
  }
  .mini-start {
    height: 24px;
    padding: 0 10px;
    border-radius: 6px;
    border: 1px solid var(--indigo);
    background: var(--indigo);
    color: #fff;
    font: 600 11.5px var(--font-body);
    cursor: pointer;
  }
  .mini-start:hover {
    filter: brightness(0.92);
  }
  .mon-foot {
    display: flex;
    justify-content: flex-end;
    margin-top: 6px;
  }
  .mini-stop {
    height: 22px;
    padding: 0 9px;
    border-radius: 6px;
    border: 1px solid #ef4444;
    background: #fff;
    color: #ef4444;
    font: 600 11px var(--font-body);
    cursor: pointer;
  }
  .mini-stop:hover {
    background: #fef2f2;
  }
  .mon-err {
    margin-top: 6px;
    font-size: 10.5px;
    color: #b91c1c;
  }
</style>
