<script lang="ts">
  /**
   * Acquire-stage context card (design spec §4; round-2 mockup
   * `dev/mockups/round2-bench.html` Acquire card).  Shows a settings
   * summary chip, an optional output (stimulus) group, an optional
   * pretrigger arm switch, the prominent green **Log Data** button (the
   * app's primary action, gaining an OUT badge when output is armed), a
   * status line (progress + pretrigger lifecycle), and a Cancel button.
   *
   * On completion the recorded set is pushed into the actions pipeline
   * (addRecordedSet) — carrying the bridge container's provenance metadata
   * when bridged — and the view switches to Time.
   *
   * The output + pretrigger groups are capability-gated: for a bridge, on the
   * advertised analog output (`outputCapable`) / pretrigger; for the Web Audio
   * path (round-5 #10), both are always available — the browser drives the
   * output stimulus + armed pretrigger itself (see `source.ts`).
   */
  import type { AcquireStore } from '../../lib/stores/acquire';
  import { recordingToItem } from '../../lib/stores/acquire';
  import {
    outputCapable,
    deviceCapsFor,
    clampVoltage,
    outputDevices,
    BARE_ARM_PRETRIG_SAMPLES,
  } from '../../lib/audio/provider';
  import type { Actions } from '../../lib/analysis/actions';
  import type { Toasts } from '../../lib/stores/toast';
  import { activeStage } from '../../lib/stores/stages';

  let {
    acquire,
    actions,
    toasts,
  }: {
    acquire: AcquireStore;
    actions: Actions;
    toasts: Toasts;
  } = $props();

  const settings = $derived(acquire.settings);
  const devices = $derived(acquire.devices);
  const status = $derived(acquire.status);
  const statusText = $derived(acquire.statusText);
  const errorMsg = $derived(acquire.errorMsg);
  const elapsed = $derived(acquire.elapsed);
  const bridgeCaps = $derived(acquire.bridgeCaps);
  const bridgeConfig = $derived(acquire.bridgeConfig);
  const pretrigStatus = $derived(acquire.pretrigStatus);
  const coercedFs = $derived(acquire.coercedFs);
  // Web Audio (round-5 #10) supports the output stimulus + pretrigger too,
  // surfaced via the store's reactive `kind` + enumerated output devices —
  // kept OUT of bridgeCaps so SetupCard's `bridgeCaps != null` bridge detection
  // is unaffected.
  const kind = $derived(acquire.kind);
  const webOutputDevices = $derived(acquire.webOutputDevices);
  const isWebAudio = $derived($kind === 'webaudio');

  const recording = $derived($status === 'recording');

  // ---- capability gates ----
  // Output (stimulus) group: the bridge advertises AO for the selected device;
  // the Web Audio path always supports a browser output stimulus.
  const showOutput = $derived(isWebAudio ? true : outputCapable($bridgeCaps, $settings.deviceId));
  // The selected device's output voltage rail (ao_vmax) clamps the amplitude.
  // Web Audio has no calibrated volts, so there is no rail to clamp against.
  const aoVmaxCap = $derived(isWebAudio ? undefined : deviceCapsFor($bridgeCaps, $settings.deviceId)?.ao_vmax);
  // Pretrigger arm: the bridge advertises pretrigger; Web Audio always supports it.
  const showPretrig = $derived(isWebAudio ? true : ($bridgeCaps?.pretrigger ?? false));

  // ---- output group state (backed by bridgeConfig, mockup defaults) ----
  const outputOn = $derived($bridgeConfig.outputEnabled ?? false);
  const outputType = $derived($bridgeConfig.outputType ?? 'sweep');
  const outputAmp = $derived($bridgeConfig.outputAmp ?? 0.3);
  const outputF1 = $derived($bridgeConfig.outputF1 ?? 10);
  const outputF2 = $derived($bridgeConfig.outputF2 ?? 500);
  // Fuller output controls (round-4 item 12): duration + output device/channels.
  const outputDuration = $derived($bridgeConfig.outputDuration);
  const outputDeviceId = $derived($bridgeConfig.outputDeviceId ?? '');
  const outputChannels = $derived($bridgeConfig.outputChannels ?? 1);
  // AO-capable devices: the bridge's advertised list, or (Web Audio) the
  // enumerated browser outputs. Empty → the device select hides (default output).
  const outDevices = $derived(isWebAudio ? $webOutputDevices : outputDevices($bridgeCaps));
  const outMaxChannels = $derived(
    outDevices.find((d) => d.deviceId === outputDeviceId)?.maxChannels,
  );

  // ---- pretrigger arm state ----
  const armed = $derived($bridgeConfig.pretrigArmed ?? false);
  const pretrigTimeout = $derived($bridgeConfig.pretrigTimeout ?? 1.0);
  // Editable-on-arm sample count (round-4 item 11): the SAME store value Setup
  // shows, defaulting to BARE_ARM_PRETRIG_SAMPLES (100) when unset.
  const pretrigSamples = $derived($bridgeConfig.pretrigSamples ?? BARE_ARM_PRETRIG_SAMPLES);

  /** UI label for a signal_generator token ('uniform' shows as "white"). */
  function typeLabel(t: string): string {
    return t === 'uniform' ? 'white' : t;
  }

  /** Format a sample rate: integer as-is, else 1 d.p. (8533.3). */
  function fmtHz(hz: number): string {
    return Number.isInteger(hz) ? String(hz) : hz.toFixed(1);
  }

  /** Whether the OUT badge shows on the Log button (output armed). */
  const outActive = $derived(showOutput && outputOn);

  /** Human name of the selected input device ('Default' when unset). */
  const deviceName = $derived.by(() => {
    const id = $settings.deviceId;
    if (!id) return 'Default input';
    const d = $devices.find((x) => x.deviceId === id);
    return d?.label ?? 'Selected device';
  });

  /**
   * Fuller settings summary (round-2 feedback): fs · channels · duration ·
   * device · pretrigger · output.  Pretrigger reads "armed" / "no pretrig";
   * the output clause (e.g. "out: sweep 0.3V 10-500") appears only when the
   * stimulus is armed.
   */
  const summary = $derived.by(() => {
    const s = $settings;
    const fs = s.sampleRate >= 1000 ? `${(s.sampleRate / 1000).toFixed(1)} kHz` : `${s.sampleRate} Hz`;
    // Pretrigger now shows its (editable) sample count when armed.
    const pre = showPretrig && armed ? `armed ${pretrigSamples}` : 'no pretrig';
    let out = '';
    if (outActive) {
      // Fuller output description (round-4 item 3): type · amp · band ·
      // duration, then the chosen output device + channel count when set.
      const durTxt = (outputDuration ?? s.durationS).toFixed(1);
      const dev = outDevices.find((d) => d.deviceId === outputDeviceId);
      const devTxt = dev ? ` → ${dev.label}` : '';
      const chTxt = outputChannels > 1 ? ` ${outputChannels}ch` : '';
      out = ` · out: ${typeLabel(outputType)} ${outputAmp}V ${outputF1}-${outputF2}Hz ${durTxt}s${devTxt}${chTxt}`;
    }
    return `${fs} · ${s.channelCount} ch · ${s.durationS.toFixed(1)} s · ${deviceName} · ${pre}${out}`;
  });

  /** Format elapsed time as "0.0 / 2.0 s". */
  const progress = $derived(
    recording ? `${$elapsed.toFixed(1)} / ${$settings.durationS.toFixed(1)} s` : '',
  );

  /**
   * Pretrigger status line during a recording: armed → triggered / timeout.
   * Empty unless the arm switch is on. A timeout is not a failure — the
   * buffered set is still captured.
   */
  const pretrigLine = $derived.by(() => {
    if (!recording || !armed) return '';
    switch ($pretrigStatus) {
      case 'triggered': return 'triggered — capturing';
      case 'timeout': return 'trigger timeout — capturing buffered data';
      case 'armed':
      default: return 'armed — waiting for trigger…';
    }
  });

  // ---- output handlers ----
  function onOutputToggle(e: Event) {
    acquire.patchBridge({ outputEnabled: (e.target as HTMLInputElement).checked });
  }
  function onOutputType(e: Event) {
    acquire.patchBridge({
      outputType: (e.target as HTMLSelectElement).value as 'sweep' | 'uniform' | 'gaussian',
    });
  }
  function onOutputAmp(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    // Clamp to the device's output rail (ao_vmax) so the drive never exceeds
    // the hardware — the 9260 rail (±4.24 V) is below the pydvma 5 V default.
    if (isFinite(v)) acquire.patchBridge({ outputAmp: clampVoltage(v, aoVmaxCap) });
  }
  function onOutputF1(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    if (isFinite(v)) acquire.patchBridge({ outputF1: v });
  }
  function onOutputF2(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    if (isFinite(v)) acquire.patchBridge({ outputF2: v });
  }
  /** Output duration (s); blank / non-positive clears it (server = capture dur). */
  function onOutputDuration(e: Event) {
    const raw = (e.target as HTMLInputElement).value.trim();
    const v = raw === '' ? undefined : Number(raw);
    acquire.patchBridge({ outputDuration: v != null && isFinite(v) && v > 0 ? v : undefined });
  }
  /** Output device (AO); blank = same as input device / server default. */
  function onOutputDevice(e: Event) {
    const v = (e.target as HTMLSelectElement).value;
    acquire.patchBridge({ outputDeviceId: v || undefined });
  }
  /** Output channel count, capped to the selected device's AO channel count. */
  function onOutputChannels(e: Event) {
    const v = Math.max(1, Math.round(Number((e.target as HTMLInputElement).value)) || 1);
    acquire.patchBridge({ outputChannels: outMaxChannels != null ? Math.min(v, outMaxChannels) : v });
  }

  // ---- pretrigger handlers ----
  function onArmToggle(e: Event) {
    acquire.patchBridge({ pretrigArmed: (e.target as HTMLInputElement).checked });
  }
  function onTimeout(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    if (isFinite(v) && v > 0) acquire.patchBridge({ pretrigTimeout: v });
  }
  /**
   * Edit the pretrigger sample count directly on the arm control — writes the
   * SAME `bridgeConfig.pretrigSamples` Setup's NI-group field edits (single
   * source of truth, so the two never fight).  Blank clears it (the bridge
   * then falls back to BARE_ARM_PRETRIG_SAMPLES); else a positive integer.
   */
  function onArmSamples(e: Event) {
    const raw = (e.target as HTMLInputElement).value.trim();
    acquire.patchBridge({
      pretrigSamples: raw === '' ? null : Math.max(1, Math.round(Number(raw)) || BARE_ARM_PRETRIG_SAMPLES),
    });
  }

  async function logData() {
    try {
      const rec = await acquire.record();
      // Convert to a DvmaItem, preserving bridge container provenance
      // (real device driver / calibration / name) when present.
      const item = recordingToItem(rec, undefined, acquire.lastRecordingMeta);
      actions.addRecordedSet(item);
      // Switch to Time view to show the new recording.
      activeStage.set('time');
      toasts.push('Recording captured.', { level: 'success' });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg !== 'cancelled') {
        toasts.push(`Recording failed: ${msg}`, { level: 'error' });
      }
    }
  }

  function cancel() {
    acquire.cancel();
  }
</script>

<section class="ctx-card card-controls" aria-label="Acquire stage controls">
  <div class="ctx-name">
    <span class="cn-t">Acquire</span>
    <span class="cn-s">capture</span>
  </div>
  <div class="ctx-body">
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">settings</span>
        <div class="grp-ctl">
          <button
            class="btn sm sum-chip mono"
            onclick={() => activeStage.set('setup')}
            title="Jump to Setup to edit these"
            data-testid="acquire-summary"
          >{summary}</button>
          <button class="btn sm" onclick={() => activeStage.set('setup')}>Edit</button>
        </div>
      </div>

      <!--
        Output (stimulus) group — renders for a bridge with advertised AO OR
        the Web Audio path (round-5 #10: the browser plays the stimulus through
        an AudioBufferSourceNode during the capture).
      -->
      {#if showOutput}
        <div class="grp" data-testid="acquire-output">
          <span class="grp-lab">output</span>
          <div class="grp-ctl">
            <label class="switch" title="Drive the output channel during logging">
              <input
                type="checkbox"
                checked={outputOn}
                onchange={onOutputToggle}
                aria-label="output signal on"
                data-testid="output-on"
              />
            </label>
            <select
              title="Output signal type"
              aria-label="output signal type"
              value={outputType}
              onchange={onOutputType}
              disabled={!outputOn}
            >
              <option value="sweep">sweep</option>
              <option value="uniform">white</option>
              <option value="gaussian">gaussian</option>
            </select>
            <span class="ml">amp (V)</span>
            <input
              type="number" step="0.1" style="width:54px"
              max={aoVmaxCap ?? undefined}
              title={aoVmaxCap != null ? `Output amplitude (V); device rail ±${aoVmaxCap.toFixed(2)} V` : 'Output amplitude (V)'}
              aria-label="output amplitude"
              value={outputAmp} onchange={onOutputAmp} disabled={!outputOn}
            />
            <span class="ml">f1</span>
            <input
              type="number" style="width:54px"
              aria-label="output f1"
              value={outputF1} onchange={onOutputF1} disabled={!outputOn}
            />
            <span class="ml">f2</span>
            <input
              type="number" style="width:60px"
              aria-label="output f2"
              value={outputF2} onchange={onOutputF2} disabled={!outputOn}
            />
            <span class="ml">dur (s)</span>
            <input
              type="number" step="0.1" min="0" style="width:56px"
              placeholder={$settings.durationS.toFixed(1)}
              title="Output duration (s); blank = match capture duration"
              aria-label="output duration"
              data-testid="output-duration"
              value={outputDuration ?? ''} onchange={onOutputDuration} disabled={!outputOn}
            />
            {#if outDevices.length}
              <span class="ml">device</span>
              <select
                title="Output (AO) device; 'same as input' uses the input device"
                aria-label="output device"
                data-testid="output-device"
                value={outputDeviceId} onchange={onOutputDevice} disabled={!outputOn}
              >
                <option value="">same as input</option>
                {#each outDevices as d (d.deviceId)}
                  <option value={d.deviceId}>{d.label}</option>
                {/each}
              </select>
              <span class="ml">out ch</span>
              <input
                type="number" min="1" max={outMaxChannels ?? undefined} style="width:48px"
                title={outMaxChannels != null ? `Output channels (device max ${outMaxChannels})` : 'Output channels'}
                aria-label="output channels"
                data-testid="output-channels"
                value={outputChannels} onchange={onOutputChannels} disabled={!outputOn}
              />
            {/if}
          </div>
        </div>
      {/if}

      <!-- Pretrigger arm — bridge (advertised pretrigger) or Web Audio (round-5 #10). -->
      {#if showPretrig}
        <div class="grp" data-testid="acquire-pretrigger">
          <span class="grp-lab">pretrigger</span>
          <div class="grp-ctl">
            <label class="switch" title="Arm the pretrigger — capture waits for the threshold crossing">
              <input
                type="checkbox"
                checked={armed}
                onchange={onArmToggle}
                aria-label="arm pretrigger"
                data-testid="pretrig-arm"
              />
              arm
            </label>
            {#if armed}
              <span class="ml">samples</span>
              <input
                type="number" step="1" min="1" style="width:64px"
                title="Pretrigger sample count (defaults to 100; same value as Setup)"
                aria-label="pretrigger samples"
                data-testid="pretrig-samples-arm"
                value={pretrigSamples} onchange={onArmSamples}
              />
              <span class="ml">timeout (s)</span>
              <input
                type="number" step="0.1" min="0" style="width:56px"
                aria-label="pretrigger timeout"
                data-testid="pretrig-timeout"
                value={pretrigTimeout} onchange={onTimeout}
              />
            {/if}
          </div>
        </div>
      {/if}

      {#if recording}
        <div class="grp">
          <span class="grp-lab">progress</span>
          <div class="grp-ctl">
            <span class="ml mono">{progress}</span>
          </div>
        </div>
      {/if}
    </div>
    {#if $coercedFs}
      <!-- DSA coerced-fs note: the device runs at a different rate than
           requested (off-ladder snap). Shown so axes are read at the true rate. -->
      <div class="ctx-row">
        <span class="note coerce-note" data-testid="acquire-coerced-fs">
          device runs at {fmtHz($coercedFs.configured)} Hz (requested {fmtHz($coercedFs.requested)})
        </span>
      </div>
    {/if}
    {#if pretrigLine}
      <div class="ctx-row">
        <span class="note" data-testid="pretrig-status">{pretrigLine}</span>
      </div>
    {/if}
    {#if $statusText && !recording}
      <div class="ctx-row">
        <span class="note">{$statusText}</span>
      </div>
    {/if}
    {#if $errorMsg}
      <div class="ctx-err" role="alert">{$errorMsg}</div>
    {/if}
  </div>
  <div class="ctx-primary">
    {#if recording}
      <button class="btn cancel-btn" onclick={cancel}>Cancel</button>
    {:else}
      <button class="btn log-btn" onclick={logData} data-testid="log-btn">
        Log Data{#if outActive}&nbsp;<span class="out-badge" data-testid="out-badge">OUT</span>{/if}
      </button>
    {/if}
  </div>
</section>

<style>
  .sum-chip {
    background: var(--surface-2) !important;
    border-radius: 13px !important;
    max-width: 520px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sum-chip:hover {
    background: var(--control-bg) !important;
  }
  .log-btn {
    background: var(--green) !important;
    border-color: var(--green) !important;
    color: #fff !important;
    font-weight: 600 !important;
  }
  .log-btn:hover {
    background: var(--green-hover) !important;
  }
  .out-badge {
    display: inline-block;
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 0.04em;
    padding: 1px 4px;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.25);
    vertical-align: middle;
  }
  .cancel-btn {
    background: var(--control-bg) !important;
    border-color: var(--danger-strong) !important;
    color: var(--danger-strong) !important;
    font-weight: 600 !important;
  }
  .cancel-btn:hover {
    background: var(--danger-soft) !important;
  }
  /* DSA coerced-fs advisory — visible but not an error. */
  .coerce-note {
    color: var(--amber, #b45309);
    font-weight: 500;
  }
</style>
