<script lang="ts">
  /**
   * Live-stage context card (design spec §8; round-2 redesign). Controls
   * for the real-time oscilloscope monitor: Start / Stop / Pause, plus the
   * osc-specific display settings — stacked traces, autoscale Y, the viewed
   * time WINDOW, and the FFT axis scaling (dB↔linear magnitude, log↔linear
   * frequency).  All drive the shared monitor store, so they stay in sync
   * with the persistent bottom-left mini monitor.
   *
   * The oscilloscope panes themselves (time trace, FFT, levels) render in
   * the plot region via `LiveScope` when `activeStage === 'live'`.
   */
  import type { MonitorStore } from '../../lib/stores/monitor';
  import { WINDOW_PRESETS_S } from '../../lib/stores/monitor';

  let {
    monitor,
  }: {
    monitor: MonitorStore;
  } = $props();

  const status = $derived(monitor.status);
  const errorMsg = $derived(monitor.errorMsg);
  const stackedStore = $derived(monitor.stacked);
  const autoscaleStore = $derived(monitor.autoscaleY);
  const windowStore = $derived(monitor.windowS);
  const fftYLogStore = $derived(monitor.fftYLog);
  const fftXLogStore = $derived(monitor.fftXLog);

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
  function onWindowChange(e: Event) {
    monitor.setWindow(Number((e.target as HTMLSelectElement).value));
  }
  function fmtWindow(s: number): string {
    return s < 1 ? `${(s * 1000).toFixed(0)} ms` : `${s} s`;
  }
</script>

<section class="ctx-card card-controls" aria-label="Live stage controls">
  <div class="ctx-name">
    <span class="cn-t">Live</span>
    <span class="cn-s">monitor</span>
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
  <div class="ctx-body">
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">display</span>
        <div class="grp-ctl">
          <label class="toggle" title="Separate channels vertically">
            <input type="checkbox" checked={$stackedStore} onchange={() => monitor.stacked.update((v) => !v)} />
            Stacked
          </label>
          <label class="toggle" title="Auto-fit amplitude range">
            <input type="checkbox" checked={$autoscaleStore} onchange={() => monitor.autoscaleY.update((v) => !v)} />
            Auto Y
          </label>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">window</span>
        <div class="grp-ctl">
          <select aria-label="viewed time window" value={$windowStore} onchange={onWindowChange} style="width:78px">
            {#each WINDOW_PRESETS_S as w (w)}
              <option value={w}>{fmtWindow(w)}</option>
            {/each}
          </select>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">fft axes</span>
        <div class="grp-ctl">
          <button class="btn sm" class:active={$fftYLogStore} onclick={() => monitor.fftYLog.update((v) => !v)}
            title="FFT magnitude: dB (log) or linear">{$fftYLogStore ? 'dB' : 'lin'}</button>
          <button class="btn sm" class:active={$fftXLogStore} onclick={() => monitor.fftXLog.update((v) => !v)}
            title="FFT frequency axis: log or linear">{$fftXLogStore ? 'log f' : 'lin f'}</button>
        </div>
      </div>
    </div>
    {#if $status === 'starting'}
      <div class="ctx-row"><span class="note">Opening microphone…</span></div>
    {/if}
    {#if $errorMsg}
      <div class="ctx-err" role="alert">{$errorMsg}</div>
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
</style>
