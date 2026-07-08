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
  import { deviceCapsFor, clampVoltage, PYDVMA_DEFAULT_VMAX } from '../../lib/audio/provider';

  let {
    acquire,
  }: {
    acquire: AcquireStore;
  } = $props();

  const devices = $derived(acquire.devices);
  const settings = $derived(acquire.settings);
  const deviceCaps = $derived(acquire.deviceCaps);
  // Bridge state (Wave B): non-null caps means the app is driving a
  // `pydvma serve` bridge instead of the browser soundcard. The NI-DAQ
  // group renders only when the bridge reports the 'nidaq' backend (no
  // dead controls), and the mic-permission hint is suppressed (bridge
  // devices always carry real labels).
  const bridgeCaps = $derived(acquire.bridgeCaps);
  const bridgeConfig = $derived(acquire.bridgeConfig);
  const coercedFs = $derived(acquire.coercedFs);
  const isBridge = $derived($bridgeCaps != null);
  const hasNidaq = $derived($bridgeCaps?.backends.includes('nidaq') ?? false);

  // Permission is granted once ANY device reports a real label.
  const permissionGranted = $derived($devices.some((d) => d.hasLabel));

  // Basic (default) vs full settings view. Local UI state.
  let full = $state(false);

  // Common sample rates for the dropdown.
  const SAMPLE_RATES = [8000, 16000, 22050, 44100, 48000, 96000];
  // Duration presets.
  const DURATIONS = [0.5, 1, 2, 5, 10, 30, 60];

  // ---- capability-derived constraints ----
  // Bridge per-device caps (Wave C): when bridged and the selected device
  // carries caps (an fs ladder / max rate / max channels), they constrain
  // the fs select + channels input, taking precedence over the Web Audio
  // getCapabilities() values. Absent → the Web Audio behaviour below.
  const bridgeSelCaps = $derived(deviceCapsFor($bridgeCaps, $settings.deviceId));
  // fs options: a bridge device's discrete DSA ladder replaces the standard
  // soundcard list; otherwise the standard list (constrained by ranges).
  const fsOptions = $derived(
    bridgeSelCaps?.fs_ladder && bridgeSelCaps.fs_ladder.length
      ? bridgeSelCaps.fs_ladder
      : SAMPLE_RATES,
  );
  // Max channels the device supports (caps the channel input); 32 fallback.
  const maxChannels = $derived(
    bridgeSelCaps?.max_channels ?? $deviceCaps?.channelCount?.max ?? 32,
  );
  const srMin = $derived($deviceCaps?.sampleRate?.min);
  const srMax = $derived($deviceCaps?.sampleRate?.max);
  // A sample rate the selected device actually supports. On a bridge ladder
  // every rendered rate IS the ladder, so all are allowed; otherwise honour
  // the bridge max_fs / the Web Audio min–max range.
  const rateAllowed = (fs: number): boolean => {
    if (bridgeSelCaps?.fs_ladder && bridgeSelCaps.fs_ladder.length) {
      return bridgeSelCaps.fs_ladder.includes(fs);
    }
    const maxFs = bridgeSelCaps?.max_fs ?? srMax;
    return (srMin == null || fs >= srMin) && (maxFs == null || fs <= maxFs);
  };
  // Current input latency hint, shown in the timing group (ms in the UI).
  const latencyMs = $derived(
    $settings.latency && $settings.latency > 0 ? Math.round($settings.latency * 1000) : '',
  );

  // ---- NI voltage rails (bridge caps) ----
  // Largest symmetric input/output ranges the selected NI device reports;
  // undefined when unknown (mock/soundcard, or a device that didn't report).
  const aiVmaxCap = $derived(bridgeSelCaps?.ai_vmax);
  const aoVmaxCap = $derived(bridgeSelCaps?.ao_vmax);
  // Effective values shown in the fields: the explicit config or the pydvma
  // default (5 V) the server would otherwise use. The store proactively
  // clamps these to the device rail on device select, so a field showing
  // e.g. 4.24 V after picking the 9260-fed chassis IS the clamped default.
  const vmaxNIValue = $derived($bridgeConfig.vmaxNI ?? PYDVMA_DEFAULT_VMAX);
  const outputVmaxNIValue = $derived($bridgeConfig.outputVmaxNI ?? PYDVMA_DEFAULT_VMAX);
  // True when the AO rail sits below the pydvma default — the field was (or
  // will be) clamped down and we explain why (the motivating 9260 bug).
  const aoRailBelowDefault = $derived(aoVmaxCap != null && aoVmaxCap < PYDVMA_DEFAULT_VMAX);

  /** Format a sample rate: integer as-is, else 1 d.p. (8533.3). */
  function fmtHz(hz: number): string {
    return Number.isInteger(hz) ? String(hz) : hz.toFixed(1);
  }
  /** Trim a voltage to a short, human-readable string (4.2426 → "4.24"). */
  function fmtVolts(v: number): string {
    return Number.isInteger(v) ? String(v) : v.toFixed(2);
  }

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

  // ---- NI-DAQ group handlers (bridge only) ----
  // Each sends through the acquire store's bridge config, which the bridge
  // merges into the next `configure` message as MySettings kwargs.
  function onIepeChange(e: Event) {
    acquire.patchBridge({ iepeExcitCurrentA: Number((e.target as HTMLSelectElement).value) });
  }
  function onTermChange(e: Event) {
    const v = (e.target as HTMLSelectElement).value;
    acquire.patchBridge({ niMode: v || undefined });
  }
  /** Blank pretrigger-samples clears it (free-run capture); else an integer. */
  function onPretrigSamples(e: Event) {
    const raw = (e.target as HTMLInputElement).value.trim();
    acquire.patchBridge({ pretrigSamples: raw === '' ? null : Math.max(0, Math.round(Number(raw)) || 0) });
  }
  function onPretrigThreshold(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    if (isFinite(v)) acquire.patchBridge({ pretrigThreshold: v });
  }
  function onPretrigChannel(e: Event) {
    const v = Math.max(0, Math.round(Number((e.target as HTMLInputElement).value)) || 0);
    acquire.patchBridge({ pretrigChannel: v });
  }
  /** NI input range (VmaxNI), clamped to the device's ai_vmax rail. */
  function onVmaxNI(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    if (!isFinite(v) || v <= 0) return;
    acquire.patchBridge({ vmaxNI: clampVoltage(v, aiVmaxCap) });
  }
  /** NI output range (output_VmaxNI), clamped to the device's ao_vmax rail. */
  function onOutputVmaxNI(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    if (!isFinite(v) || v <= 0) return;
    acquire.patchBridge({ outputVmaxNI: clampVoltage(v, aoVmaxCap) });
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
            {#each fsOptions as fs (fs)}
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
      {#if !permissionGranted && !isBridge}
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

    {#if $coercedFs}
      <!-- DSA coerced-fs note: the device snapped an off-ladder request to a
           legal step (e.g. 8000 → 8533.3 Hz on the 9234). Axes read at the
           TRUE rate — never silently at the requested one. -->
      <div class="ctx-row">
        <span class="note coerce-note" data-testid="setup-coerced-fs">
          device runs at {fmtHz($coercedFs.configured)} Hz (requested {fmtHz($coercedFs.requested)})
        </span>
      </div>
    {/if}

    {#if $bridgeConfig.outputFs != null}
      <!-- AO rate clamp note: the effective output device's analog output
           tops out below the requested input fs (USB-6003: AO 5 kS/s vs AI
           100 kS/s), so the store pins output_fs to the cap — unclamped,
           MySettings defaults output_fs = fs and a stimulus-enabled log
           fails server-side. -->
      <div class="ctx-row">
        <span class="note coerce-note" data-testid="output-fs-clamp-note">
          output runs at {fmtHz($bridgeConfig.outputFs)} Hz (device AO limit)
        </span>
      </div>
    {/if}

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
        <!-- nidaq slot (Wave B): rendered ONLY when the bridge reports the
             'nidaq' backend (no dead controls on the Web-Audio path).
             IEPE excitation, terminal configuration, and pretrigger all
             send through the acquire store's bridge config → the next
             `configure` message's MySettings kwargs. -->
        {#if hasNidaq}
          <div class="grp" data-testid="setup-nidaq">
            <span class="grp-lab">NI-DAQ input</span>
            <div class="grp-ctl">
              <select
                aria-label="IEPE excitation current"
                title="IEPE/ICP constant-current excitation (NI 9234 only)"
                value={String($bridgeConfig.iepeExcitCurrentA ?? 0)}
                onchange={onIepeChange}
                style="width:96px"
              >
                <option value="0">IEPE off</option>
                <option value="0.002">IEPE 2 mA</option>
              </select>
              <select
                aria-label="terminal configuration"
                title="Analog-input terminal configuration"
                value={$bridgeConfig.niMode ?? ''}
                onchange={onTermChange}
                style="width:96px"
              >
                <option value="">default</option>
                <option value="DAQmx_Val_RSE">RSE</option>
                <option value="DAQmx_Val_NRSE">NRSE</option>
                <option value="DAQmx_Val_Diff">diff</option>
              </select>
            </div>
          </div>
          <div class="grp" data-testid="setup-pretrigger">
            <span class="grp-lab">pretrigger</span>
            <div class="grp-ctl">
              <input
                type="number"
                min="0"
                step="1"
                placeholder="off"
                value={$bridgeConfig.pretrigSamples ?? ''}
                onchange={onPretrigSamples}
                title="Pretrigger samples (blank = free-run, no trigger)"
                aria-label="pretrigger samples"
                style="width:76px"
              />
              <span class="ml">samples</span>
              <input
                type="number"
                step="0.01"
                value={$bridgeConfig.pretrigThreshold ?? ''}
                onchange={onPretrigThreshold}
                placeholder="thresh"
                title="Trigger amplitude threshold"
                aria-label="pretrigger threshold"
                style="width:64px"
              />
              <input
                type="number"
                min="0"
                step="1"
                value={$bridgeConfig.pretrigChannel ?? ''}
                onchange={onPretrigChannel}
                placeholder="ch"
                title="Trigger channel index"
                aria-label="pretrigger channel"
                style="width:52px"
              />
            </div>
          </div>
          <!-- NI voltage rails: input (VmaxNI) + output (output_VmaxNI),
               each clamped to the selected device's reported range so a
               requested range never exceeds the hardware. The 9260's ±4.24 V
               output rail is BELOW the pydvma 5 V default; the store clamps
               the default down and this note explains why. -->
          <div class="grp" data-testid="setup-vmax">
            <span class="grp-lab">NI voltage range (±V)</span>
            <div class="grp-ctl">
              <span class="ml">in</span>
              <input
                type="number"
                min="0"
                step="0.1"
                max={aiVmaxCap ?? undefined}
                value={vmaxNIValue}
                onchange={onVmaxNI}
                title={aiVmaxCap != null
                  ? `Input full-scale (VmaxNI); device rail ±${fmtVolts(aiVmaxCap)} V`
                  : 'Input full-scale (VmaxNI)'}
                aria-label="NI input voltage range"
                data-testid="vmax-ni"
                style="width:64px"
              />
              <span class="ml">out</span>
              <input
                type="number"
                min="0"
                step="0.1"
                max={aoVmaxCap ?? undefined}
                value={outputVmaxNIValue}
                onchange={onOutputVmaxNI}
                title={aoVmaxCap != null
                  ? `Output full-scale (output_VmaxNI); device rail ±${fmtVolts(aoVmaxCap)} V`
                  : 'Output full-scale (output_VmaxNI)'}
                aria-label="NI output voltage range"
                data-testid="output-vmax-ni"
                style="width:64px"
              />
              {#if aiVmaxCap != null || aoVmaxCap != null}
                <span class="note" data-testid="vmax-hint">
                  rail{aiVmaxCap != null ? ` in ±${fmtVolts(aiVmaxCap)}` : ''}{aoVmaxCap != null ? ` out ±${fmtVolts(aoVmaxCap)}` : ''} V
                </span>
              {/if}
            </div>
            {#if aoRailBelowDefault}
              <span class="note coerce-note" data-testid="vmax-clamp-note">
                output clamped to device rail ±{fmtVolts(aoVmaxCap!)} V (default {PYDVMA_DEFAULT_VMAX} V would saturate)
              </span>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
  </div>
</section>

<style>
  .perm-btn {
    color: var(--indigo);
    border-color: var(--accent-soft-border);
    background: var(--accent-soft);
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
  /* Coerced-fs / voltage-clamp advisories — visible but not an error. */
  .coerce-note {
    color: var(--amber, #b45309);
    font-weight: 500;
  }
</style>
