<script lang="ts">
  /**
   * Live-stage context card (design spec §8). Controls for the real-time
   * oscilloscope monitor: Start / Stop / Pause, stacked traces toggle,
   * autoscale toggle, and per-channel level meters.
   *
   * The LiveCard does NOT contain the oscilloscope canvas — that lives
   * in OscCanvas.svelte and is rendered in the plot region (App.svelte)
   * when `activeStage === 'live'`.
   */
  import type { MonitorStore } from '../../lib/stores/monitor';

  let {
    monitor,
  }: {
    monitor: MonitorStore;
  } = $props();

  const status = $derived(monitor.status);
  const errorMsg = $derived(monitor.errorMsg);
  const levels = $derived(monitor.levels);
  const stackedStore = $derived(monitor.stacked);
  const autoscaleStore = $derived(monitor.autoscaleY);

  const isStreaming = $derived($status === 'streaming' || $status === 'paused');
  const isPaused = $derived($status === 'paused');

  function startMonitor() {
    void monitor.start();
  }
  function stopMonitor() {
    monitor.stop();
  }
  function togglePause() {
    monitor.togglePause();
  }
  function toggleStacked() {
    monitor.stacked.update((v: boolean) => !v);
  }
  function toggleAutoscale() {
    monitor.autoscaleY.update((v: boolean) => !v);
  }

  /**
   * Format a level value (0..1) as a dB string for the meter tooltip.
   * Clamps to -60 dB at the bottom.
   */
  function toDb(v: number): string {
    if (v <= 0) return '-∞';
    const db = 20 * Math.log10(v);
    return db < -60 ? '<-60' : db.toFixed(0);
  }
</script>

<section class="ctx-card card-controls" aria-label="Live stage controls">
  <div class="ctx-name">
    <span class="cn-t">Live</span>
    <span class="cn-s">monitor</span>
  </div>
  <div class="ctx-body">
    <div class="ctx-row">
      {#if isStreaming}
        <div class="grp">
          <span class="grp-lab">display</span>
          <div class="grp-ctl">
            <label class="toggle" title="Separate channels vertically">
              <input type="checkbox" checked={$stackedStore} onchange={toggleStacked} />
              Stacked
            </label>
            <label class="toggle" title="Auto-fit amplitude range">
              <input type="checkbox" checked={$autoscaleStore} onchange={toggleAutoscale} />
              Auto Y
            </label>
          </div>
        </div>
        <div class="grp">
          <span class="grp-lab">levels</span>
          <div class="grp-ctl levels-row">
            {#each $levels as lv, ch}
              <div class="level-bar" title="ch{ch}: peak {toDb(lv.peak)} dB, RMS {toDb(lv.rms)} dB">
                <div class="level-fill" style="height:{Math.min(100, lv.peak * 100)}%"
                     class:clip={lv.peak >= 0.95}></div>
              </div>
            {/each}
          </div>
        </div>
      {:else if $status === 'starting'}
        <div class="grp">
          <span class="grp-lab">status</span>
          <div class="grp-ctl"><span class="note">Opening microphone…</span></div>
        </div>
      {/if}
    </div>
    {#if $errorMsg}
      <div class="ctx-err" role="alert">{$errorMsg}</div>
    {/if}
  </div>
  <div class="ctx-primary">
    {#if isStreaming}
      <button class="btn pause-btn" onclick={togglePause}>
        {isPaused ? '▶ Resume' : '⏸ Pause'}
      </button>
      <button class="btn stop-btn" onclick={stopMonitor}>Stop</button>
    {:else if $status === 'starting'}
      <button class="btn stop-btn" onclick={stopMonitor}>Cancel</button>
    {:else}
      <button class="btn start-btn" onclick={startMonitor}>Start Monitor</button>
    {/if}
  </div>
</section>

<style>
  .start-btn {
    background: var(--indigo) !important;
    border-color: var(--indigo) !important;
    color: #fff !important;
    font-weight: 600 !important;
  }
  .start-btn:hover {
    filter: brightness(0.9);
  }
  .stop-btn {
    background: #fff !important;
    border-color: #ef4444 !important;
    color: #ef4444 !important;
    font-weight: 600 !important;
  }
  .stop-btn:hover {
    background: #fef2f2 !important;
  }
  .pause-btn {
    background: #fff !important;
    border-color: var(--indigo) !important;
    color: var(--indigo) !important;
    font-weight: 600 !important;
  }
  .pause-btn:hover {
    background: #eef0ff !important;
  }
  .toggle {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    color: var(--text);
    cursor: pointer;
    user-select: none;
  }
  .toggle input {
    margin: 0;
  }
  .levels-row {
    display: flex;
    gap: 3px;
    align-items: flex-end;
    height: 24px;
  }
  .level-bar {
    width: 8px;
    height: 100%;
    background: #e5e7eb;
    border-radius: 2px;
    position: relative;
    overflow: hidden;
  }
  .level-fill {
    position: absolute;
    bottom: 0;
    left: 0;
    width: 100%;
    background: var(--green);
    border-radius: 2px;
    transition: height 60ms linear;
  }
  .level-fill.clip {
    background: #ef4444;
  }
</style>
