<script lang="ts">
  /**
   * Setup-stage context card (design spec §4; round-2 redesign). The
   * settings home for audio acquisition.
   *
   * Round-2 changes:
   * - Enumerate devices as soon as the Setup stage MOUNTS (not only when
   *   logging), so the device dropdown is populated on arrival.  Browsers
   *   hide device labels until mic permission is granted, so when labels
   *   are still blank we surface an "Allow microphone access" hint that
   *   requests permission (via a throwaway stream) and re-enumerates —
   *   we never force a permission prompt on app load, only here.
   * - A basic ↔ full toggle.  "Full" reveals the FULL soundcard option set
   *   (round-3), grouped BY DOMAIN so a future NI-DAQ group can slot in
   *   without a redesign:
   *     · device     — the granted track's reported capability RANGES
   *                     (channel count, sample-rate, latency) from
   *                     `getCapabilities()`, which also constrain the basic
   *                     fs/channel inputs where known.
   *     · processing — the echo-cancellation / noise-suppression / auto-gain
   *                     getUserMedia constraints (all default OFF; the browser
   *                     turns them on by default, which corrupts measurement
   *                     data).
   *     · timing     — an optional input-latency hint.
   *   The context zone grows to fit the taller card, squashing the plot
   *   downwards (the maintainer's "extended-area mode").
   *
   * NO pretrigger / output-signal / NI-DAQ UI here yet — those capture-path
   * features are not implemented, so no dead controls (see the nidaq slot
   * comment in the full row).
   */
  import { onMount } from 'svelte';
  import type { AcquireStore } from '../../lib/stores/acquire';

  let {
    acquire,
  }: {
    acquire: AcquireStore;
  } = $props();

  const devices = $derived(acquire.devices);
  const settings = $derived(acquire.settings);
  const deviceCaps = $derived(acquire.deviceCaps);

  // Permission is granted once ANY device reports a real label.
  const permissionGranted = $derived($devices.some((d) => d.hasLabel));

  // Basic (default) vs full settings view. Local UI state.
  let full = $state(false);

  // Common sample rates for the dropdown.
  const SAMPLE_RATES = [8000, 16000, 22050, 44100, 48000, 96000];
  // Duration presets.
  const DURATIONS = [0.5, 1, 2, 5, 10, 30, 60];

  // ---- capability-derived constraints (populated after mic permission) ----
  // Max channels the device supports (caps the channel input); 32 fallback.
  const maxChannels = $derived($deviceCaps?.channelCount?.max ?? 32);
  const srMin = $derived($deviceCaps?.sampleRate?.min);
  const srMax = $derived($deviceCaps?.sampleRate?.max);
  // A sample rate the granted device actually supports.
  const rateAllowed = (fs: number): boolean =>
    (srMin == null || fs >= srMin) && (srMax == null || fs <= srMax);
  // Current input latency hint, shown in the timing group (ms in the UI).
  const latencyMs = $derived(
    $settings.latency && $settings.latency > 0 ? Math.round($settings.latency * 1000) : '',
  );

  onMount(() => {
    // Enumerate on arrival (round-2: don't wait for "Log data").
    void acquire.refreshDevices();
  });

  function onDeviceChange(e: Event) {
    acquire.patch({ deviceId: (e.target as HTMLSelectElement).value });
  }
  function onFsChange(e: Event) {
    acquire.patch({ sampleRate: Number((e.target as HTMLSelectElement).value) });
  }
  function onChannelsChange(e: Event) {
    const v = Math.max(1, Math.min(maxChannels, Number((e.target as HTMLInputElement).value) || 1));
    acquire.patch({ channelCount: v });
  }
  function onDurationChange(e: Event) {
    acquire.patch({ durationS: Number((e.target as HTMLSelectElement).value) });
  }
  function onLatencyChange(e: Event) {
    const raw = (e.target as HTMLInputElement).value.trim();
    // UI is in ms; store is in seconds. Blank / non-positive clears the hint.
    const ms = raw === '' ? 0 : Number(raw);
    acquire.patch({ latency: isFinite(ms) && ms > 0 ? ms / 1000 : undefined });
  }
  function refreshDevices() {
    void acquire.refreshDevices();
  }
  function requestPermission() {
    void acquire.requestPermission();
  }
  /** Format a capability range like "1–2" / "≤ 96 kHz", or "—" when unknown. */
  function fmtRange(r: { min?: number; max?: number } | undefined, unit = '', k = 1): string {
    if (!r || (r.min == null && r.max == null)) return '—';
    const f = (v: number) => (k !== 1 ? `${(v / k).toFixed(v / k >= 10 ? 0 : 1)}` : `${v}`);
    if (r.min != null && r.max != null) return `${f(r.min)}–${f(r.max)}${unit}`;
    if (r.max != null) return `≤ ${f(r.max)}${unit}`;
    return `≥ ${f(r.min!)}${unit}`;
  }
</script>

<section class="ctx-card card-controls" aria-label="Setup stage controls">
  <div class="ctx-name">
    <span class="cn-t">Setup</span>
    <span class="cn-s">configure</span>
  </div>
  <div class="ctx-primary">
    <button
      class="btn sm"
      class:active={full}
      onclick={() => (full = !full)}
      aria-pressed={full}
      title="Show advanced input settings"
    >{full ? 'Basic' : 'Full ▾'}</button>
  </div>
  <div class="ctx-body">
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">input device</span>
        <div class="grp-ctl">
          <select style="width:200px" aria-label="input device" value={$settings.deviceId} onchange={onDeviceChange}>
            <option value="">Default</option>
            {#each $devices as d (d.deviceId)}
              <option value={d.deviceId}>{d.label}</option>
            {/each}
          </select>
          <button class="btn sm" onclick={refreshDevices} title="Refresh device list">↻</button>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">sample rate</span>
        <div class="grp-ctl">
          <select style="width:84px" aria-label="sample rate" value={$settings.sampleRate} onchange={onFsChange}>
            {#each SAMPLE_RATES as fs (fs)}
              <option value={fs} disabled={!rateAllowed(fs)}>{fs >= 1000 ? `${fs / 1000}k` : fs}</option>
            {/each}
          </select>
          <span class="ml">Hz</span>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">channels</span>
        <div class="grp-ctl">
          <input
            type="number"
            min="1"
            max={maxChannels}
            value={$settings.channelCount}
            onchange={onChannelsChange}
            style="width:52px"
            aria-label="channel count"
          />
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">duration</span>
        <div class="grp-ctl">
          <select style="width:68px" aria-label="duration" value={$settings.durationS} onchange={onDurationChange}>
            {#each DURATIONS as d (d)}
              <option value={d}>{d < 1 ? `${d * 1000}ms` : `${d}s`}</option>
            {/each}
          </select>
        </div>
      </div>
      {#if !permissionGranted}
        <div class="grp">
          <span class="grp-lab">microphone</span>
          <div class="grp-ctl">
            <button class="btn sm perm-btn" onclick={requestPermission} data-testid="allow-mic">
              Allow microphone access to see device names
            </button>
          </div>
        </div>
      {/if}
    </div>

    {#if full}
      <!--
        FULL soundcard option set, grouped by domain (device / processing /
        timing).  Structured so a future NI-DAQ group (IEPE excitation,
        terminal config, pretrigger) can slot in as another <div class="grp">
        block right here — see the "nidaq slot" marker below — without
        redesigning the row.  Basic mode above is untouched.
      -->
      <div class="ctx-row full-row" data-testid="setup-full">
        <!-- domain: device — reported capability ranges (getCapabilities). -->
        <div class="grp">
          <span class="grp-lab">device capabilities</span>
          <div class="grp-ctl">
            {#if $deviceCaps}
              <span class="mono note" data-testid="setup-caps">
                {fmtRange($deviceCaps.channelCount)} ch ·
                {fmtRange($deviceCaps.sampleRate, ' kHz', 1000)} ·
                lat {fmtRange($deviceCaps.latency, ' ms', 0.001)}
                {#if $deviceCaps.current?.sampleRate}
                  <br />now {($deviceCaps.current.sampleRate / 1000).toFixed(1)} kHz{#if $deviceCaps.current.channelCount} · {$deviceCaps.current.channelCount} ch{/if}
                {/if}
              </span>
            {:else}
              <span class="note">allow mic access to read capabilities</span>
            {/if}
          </div>
        </div>
        <!-- domain: processing — getUserMedia DSP flags (all default OFF). -->
        <div class="grp">
          <span class="grp-lab">processing (off = raw measurement)</span>
          <div class="grp-ctl">
            <label class="switch" title="Browser echo cancellation — leave OFF for measurement">
              <input type="checkbox" checked={$settings.echoCancellation}
                onchange={(e) => acquire.patch({ echoCancellation: (e.target as HTMLInputElement).checked })} />
              echo&nbsp;cancel
            </label>
            <label class="switch" title="Browser noise suppression — leave OFF for measurement">
              <input type="checkbox" checked={$settings.noiseSuppression}
                onchange={(e) => acquire.patch({ noiseSuppression: (e.target as HTMLInputElement).checked })} />
              noise&nbsp;suppress
            </label>
            <label class="switch" title="Browser auto gain control — leave OFF for measurement">
              <input type="checkbox" checked={$settings.autoGainControl}
                onchange={(e) => acquire.patch({ autoGainControl: (e.target as HTMLInputElement).checked })} />
              auto&nbsp;gain
            </label>
          </div>
        </div>
        <!-- domain: timing — input latency hint (best-effort). -->
        <div class="grp">
          <span class="grp-lab">timing</span>
          <div class="grp-ctl">
            <input
              type="number"
              min="0"
              step="1"
              value={latencyMs}
              onchange={onLatencyChange}
              placeholder="auto"
              title="Preferred input latency hint (ms); blank = browser default"
              data-testid="setup-latency"
              aria-label="input latency hint in milliseconds"
              style="width:64px"
            />
            <span class="ml">ms latency</span>
          </div>
        </div>
        <!-- nidaq slot: a future NI-DAQ group (IEPE, terminal config,
             pretrigger) drops in here as another <div class="grp"> block. -->
      </div>
    {/if}
  </div>
</section>

<style>
  .perm-btn {
    color: var(--indigo);
    border-color: #c7d2fe;
    background: #eef0ff;
    white-space: normal;
    text-align: left;
    height: auto;
    padding: 4px 8px;
  }
  .full-row {
    border-top: 1px dashed var(--border);
    padding-top: 7px;
    margin-top: 2px;
  }
</style>
