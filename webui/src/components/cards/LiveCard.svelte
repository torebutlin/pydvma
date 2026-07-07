<script lang="ts">
  /**
   * Live-stage context card (design spec §8; round-2/3 redesign). Controls
   * for the real-time oscilloscope monitor: Start / Stop / Pause, plus the
   * osc-specific display settings — stacked traces, autoscale Y, the viewed
   * time WINDOW (preset dropdown PLUS a typable custom value), FFT axis
   * scaling (dB↔linear magnitude, log↔linear frequency), a max-frequency
   * zoom (`fmax`, with a "full"/Nyquist default), and the FFT-pane spectrum
   * mode (instantaneous FFT vs averaged Welch PSD, with averaging + optional
   * temporal smoothing).  All drive the shared monitor store, so they stay
   * in sync with the persistent bottom-left mini monitor.
   *
   * The oscilloscope panes themselves (time trace, FFT, levels) render in
   * the plot region via `LiveScope` when `activeStage === 'live'`.
   */
  import type { MonitorStore } from '../../lib/stores/monitor';
  import { WINDOW_PRESETS_S, PSD_SEGMENT_CHOICES } from '../../lib/stores/monitor';

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
  const fftFMaxStore = $derived(monitor.fftFMax);
  const modeStore = $derived(monitor.spectrumMode);
  const segmentsStore = $derived(monitor.psdSegments);
  const smoothingStore = $derived(monitor.psdSmoothing);

  const isStreaming = $derived($status === 'streaming' || $status === 'paused');
  const isPaused = $derived($status === 'paused');
  const isPsd = $derived($modeStore === 'psd');
  // The window select shows the preset options plus a synthesised "custom"
  // entry when the current value isn't one of them (so it stays selectable).
  const isPresetWindow = $derived(
    (WINDOW_PRESETS_S as readonly number[]).includes($windowStore),
  );
  const fMaxValue = $derived($fftFMaxStore == null ? '' : $fftFMaxStore);

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
  function onWindowInput(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    if (isFinite(v) && v > 0) monitor.setWindow(v);
  }
  function onFMaxInput(e: Event) {
    const raw = (e.target as HTMLInputElement).value.trim();
    monitor.setFftFMax(raw === '' ? null : Number(raw));
  }
  function onSegments(e: Event) {
    monitor.setPsdSegments(Number((e.target as HTMLSelectElement).value));
  }
  function onSmoothing(e: Event) {
    monitor.setPsdSmoothing(Number((e.target as HTMLSelectElement).value));
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
        <span class="grp-lab">view time</span>
        <div class="grp-ctl">
          <select aria-label="viewed time window" value={$windowStore} onchange={onWindowChange} style="width:74px">
            {#each WINDOW_PRESETS_S as w (w)}
              <option value={w}>{fmtWindow(w)}</option>
            {/each}
            {#if !isPresetWindow}
              <option value={$windowStore}>{fmtWindow($windowStore)}</option>
            {/if}
          </select>
          <input
            type="number"
            aria-label="custom time window in seconds"
            data-testid="live-window-input"
            min="0.02"
            max="5"
            step="0.01"
            value={$windowStore}
            onchange={onWindowInput}
            title="Custom viewed window (0.02–5 s)"
            style="width:64px"
          />
          <span class="ml">s</span>
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
      <div class="grp">
        <span class="grp-lab">fft fmax</span>
        <div class="grp-ctl">
          <button
            class="btn sm"
            class:active={$fftFMaxStore == null}
            onclick={() => monitor.setFftFMax(null)}
            title="Show the full frequency span (Nyquist)"
          >Full</button>
          <input
            type="number"
            aria-label="fft max frequency in Hz"
            data-testid="live-fmax-input"
            min="10"
            step="10"
            value={fMaxValue}
            onchange={onFMaxInput}
            placeholder="Nyq"
            title="Zoom the FFT frequency axis to this max (Hz); blank = full"
            style="width:74px"
          />
          <span class="ml">Hz</span>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">spectrum</span>
        <div class="grp-ctl">
          <div class="seg" role="group" aria-label="spectrum mode">
            <button class:active={!isPsd} onclick={() => monitor.setSpectrumMode('instant')}
              data-testid="live-mode-fft" title="Instantaneous per-frame FFT (amplitude)">FFT</button>
            <button class:active={isPsd} onclick={() => monitor.setSpectrumMode('psd')}
              data-testid="live-mode-psd" title="Averaged Welch power spectral density (unit²/Hz)">PSD</button>
          </div>
        </div>
      </div>
      {#if isPsd}
        <div class="grp">
          <span class="grp-lab">averages</span>
          <div class="grp-ctl">
            <select aria-label="psd averages" data-testid="live-psd-avg" value={$segmentsStore} onchange={onSegments} style="width:56px">
              {#each PSD_SEGMENT_CHOICES as n (n)}
                <option value={n}>{n}×</option>
              {/each}
            </select>
          </div>
        </div>
        <div class="grp">
          <span class="grp-lab">smoothing</span>
          <div class="grp-ctl">
            <select aria-label="psd smoothing" value={$smoothingStore} onchange={onSmoothing} style="width:64px">
              <option value={0}>off</option>
              <option value={0.5}>low</option>
              <option value={0.8}>high</option>
            </select>
          </div>
        </div>
      {/if}
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
