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
  import Segmented from '../Segmented.svelte';

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
  const fftFMinStore = $derived(monitor.fftFMin);
  const fftFreqModeStore = $derived(monitor.fftFreqMode);
  const modeStore = $derived(monitor.spectrumMode);
  const segmentsStore = $derived(monitor.psdSegments);
  const smoothingStore = $derived(monitor.psdSmoothing);

  const isStreaming = $derived($status === 'streaming' || $status === 'paused');
  const isPaused = $derived($status === 'paused');
  const isPsd = $derived($modeStore === 'psd');

  // ── View-time combo (item 5): a preset dropdown PLUS a 'custom…' entry.
  // Picking 'custom' reveals a typebox (pre-filled with the current value);
  // a loaded/typed non-preset value auto-selects custom so it stays editable.
  let showCustomWindow = $state(false);
  const isPresetWindow = $derived(
    (WINDOW_PRESETS_S as readonly number[]).includes($windowStore),
  );
  const customWindowActive = $derived(showCustomWindow || !isPresetWindow);
  const windowSelectValue = $derived(customWindowActive ? 'custom' : String($windowStore));
  // Memory-safe upper bound for the custom window (round-5 item 8): recomputed
  // on stream-state / window change (fs·channels drive it). setWindow enforces
  // the real clamp; this only bounds the input hint.
  const windowMax = $derived.by(() => { void $status; void $windowStore; return monitor.maxWindowS(); });
  const windowMaxLabel = $derived(windowMax >= 1 ? `${Math.round(windowMax)}` : windowMax.toFixed(2));

  const isRangeFreq = $derived($fftFreqModeStore === 'range');
  const fMaxValue = $derived($fftFMaxStore == null ? '' : $fftFMaxStore);
  const fMinValue = $derived($fftFMinStore == null ? '' : $fftFMinStore);

  function startMonitor() {
    void monitor.start();
  }
  function stopMonitor() {
    monitor.stop();
  }
  function togglePause() {
    monitor.togglePause();
  }
  function onWindowSelect(e: Event) {
    const v = (e.target as HTMLSelectElement).value;
    if (v === 'custom') { showCustomWindow = true; return; }
    showCustomWindow = false;
    monitor.setWindow(Number(v));
  }
  function onWindowInput(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    if (isFinite(v) && v > 0) monitor.setWindow(v);
  }
  function onFMaxInput(e: Event) {
    const raw = (e.target as HTMLInputElement).value.trim();
    monitor.setFftFMax(raw === '' ? null : Number(raw));
  }
  function onFMinInput(e: Event) {
    const raw = (e.target as HTMLInputElement).value.trim();
    monitor.setFftFMin(raw === '' ? null : Number(raw));
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
          <select aria-label="viewed time window" value={windowSelectValue} onchange={onWindowSelect} style="width:82px">
            {#each WINDOW_PRESETS_S as w (w)}
              <option value={String(w)}>{fmtWindow(w)}</option>
            {/each}
            <option value="custom">custom…</option>
          </select>
          {#if customWindowActive}
            <input
              type="number"
              aria-label="custom time window in seconds"
              data-testid="live-window-input"
              min="0.02"
              max={windowMax}
              step="0.01"
              value={$windowStore}
              onchange={onWindowInput}
              title={`Custom viewed window (0.02–${windowMaxLabel} s; capped by memory at high fs/channels)`}
              style="width:64px"
            />
            <span class="ml">s</span>
          {/if}
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">fft axes</span>
        <div class="grp-ctl">
          <Segmented
            ariaLabel="FFT magnitude scale"
            value={$fftYLogStore}
            onchange={(v) => monitor.fftYLog.set(v)}
            options={[
              { value: true, label: 'dB', title: 'FFT magnitude in dB (log)' },
              { value: false, label: 'lin', title: 'Linear FFT magnitude' },
            ]}
          />
          <Segmented
            ariaLabel="FFT frequency axis scale"
            value={$fftXLogStore}
            onchange={(v) => monitor.fftXLog.set(v)}
            options={[
              { value: false, label: 'lin f', title: 'Linear frequency axis' },
              { value: true, label: 'log f', title: 'Log frequency axis' },
            ]}
          />
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">fft freq</span>
        <div class="grp-ctl">
          <Segmented
            ariaLabel="FFT frequency range mode"
            value={$fftFreqModeStore}
            onchange={(m) => monitor.setFftFreqMode(m)}
            options={[
              { value: 'full' as const, label: 'Full', title: 'Show the full frequency span (Nyquist)' },
              { value: 'range' as const, label: 'Range', title: 'Zoom the FFT to a min–max frequency band' },
            ]}
          />
          {#if isRangeFreq}
            <input
              type="number"
              aria-label="fft min frequency in Hz"
              data-testid="live-fmin-input"
              min="0"
              step="10"
              value={fMinValue}
              onchange={onFMinInput}
              placeholder="0"
              title="Band start (Hz); blank = 0 / DC"
              style="width:60px"
            />
            <span class="ml">–</span>
            <input
              type="number"
              aria-label="fft max frequency in Hz"
              data-testid="live-fmax-input"
              min="10"
              step="10"
              value={fMaxValue}
              onchange={onFMaxInput}
              placeholder="Nyq"
              title="Band end (Hz); blank = Nyquist"
              style="width:66px"
            />
            <span class="ml">Hz</span>
          {/if}
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">spectrum</span>
        <div class="grp-ctl">
          <Segmented
            ariaLabel="spectrum mode"
            value={$modeStore}
            onchange={(m) => monitor.setSpectrumMode(m)}
            options={[
              { value: 'instant' as const, label: 'FFT', title: 'Instantaneous per-frame FFT (amplitude)', testid: 'live-mode-fft' },
              { value: 'psd' as const, label: 'PSD', title: 'Averaged Welch power spectral density (unit²/Hz)', testid: 'live-mode-psd' },
            ]}
          />
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
    background: var(--control-bg) !important;
    border-color: var(--danger-strong) !important;
    color: var(--danger-strong) !important;
    font-weight: 600 !important;
  }
  .stop-btn:hover {
    background: var(--danger-soft) !important;
  }
  .pause-btn {
    background: var(--control-bg) !important;
    border-color: var(--indigo) !important;
    color: var(--indigo) !important;
    font-weight: 600 !important;
  }
  .pause-btn:hover {
    background: var(--accent-soft) !important;
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
