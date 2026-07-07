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
   * The output + pretrigger groups are BRIDGE-only and capability-gated:
   * the output group renders only when the bridge advertises analog output
   * (`outputCapable`), and the arm switch only when it advertises
   * pretrigger.  On the Web Audio path both are hidden — a browser output
   * stimulus is a later item (see the web-audio output slot comment below).
   */
  import type { AcquireStore } from '../../lib/stores/acquire';
  import { recordingToItem } from '../../lib/stores/acquire';
  import { outputCapable, deviceCapsFor, clampVoltage } from '../../lib/audio/provider';
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

  const recording = $derived($status === 'recording');

  // ---- capability gates (bridge only) ----
  // Output (stimulus) group: only when the bridge advertises AO for the
  // selected device. The Web Audio path (null caps) is always hidden.
  const showOutput = $derived(outputCapable($bridgeCaps, $settings.deviceId));
  // The selected device's output voltage rail (ao_vmax); clamps the amplitude.
  const aoVmaxCap = $derived(deviceCapsFor($bridgeCaps, $settings.deviceId)?.ao_vmax);
  // Pretrigger arm: only when the bridge advertises pretrigger.
  const showPretrig = $derived($bridgeCaps?.pretrigger ?? false);

  // ---- output group state (backed by bridgeConfig, mockup defaults) ----
  const outputOn = $derived($bridgeConfig.outputEnabled ?? false);
  const outputType = $derived($bridgeConfig.outputType ?? 'sweep');
  const outputAmp = $derived($bridgeConfig.outputAmp ?? 0.3);
  const outputF1 = $derived($bridgeConfig.outputF1 ?? 10);
  const outputF2 = $derived($bridgeConfig.outputF2 ?? 500);

  // ---- pretrigger arm state ----
  const armed = $derived($bridgeConfig.pretrigArmed ?? false);
  const pretrigTimeout = $derived($bridgeConfig.pretrigTimeout ?? 1.0);

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
    const pre = showPretrig && armed ? 'armed' : 'no pretrig';
    let out = '';
    if (outActive) {
      out = ` · out: ${typeLabel(outputType)} ${outputAmp}V ${outputF1}-${outputF2}`;
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

  // ---- pretrigger handlers ----
  function onArmToggle(e: Event) {
    acquire.patchBridge({ pretrigArmed: (e.target as HTMLInputElement).checked });
  }
  function onTimeout(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    if (isFinite(v) && v > 0) acquire.patchBridge({ pretrigTimeout: v });
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
        Output (stimulus) group — BRIDGE-only, gated on advertised AO.
        Web-audio output slot: a browser output stimulus (Web Audio
        OscillatorNode / buffer) is a later item; when added, render an
        equivalent group here for the Web Audio path instead of hiding it.
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
          </div>
        </div>
      {/if}

      <!-- Pretrigger arm — BRIDGE-only, gated on advertised pretrigger. -->
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
    background: #f8f9fb !important;
    border-radius: 13px !important;
    max-width: 520px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sum-chip:hover {
    background: #fff !important;
  }
  .log-btn {
    background: var(--green) !important;
    border-color: var(--green) !important;
    color: #fff !important;
    font-weight: 600 !important;
  }
  .log-btn:hover {
    background: #15803d !important;
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
    background: #fff !important;
    border-color: #ef4444 !important;
    color: #ef4444 !important;
    font-weight: 600 !important;
  }
  .cancel-btn:hover {
    background: #fef2f2 !important;
  }
  /* DSA coerced-fs advisory — visible but not an error. */
  .coerce-note {
    color: var(--amber, #b45309);
    font-weight: 500;
  }
</style>
