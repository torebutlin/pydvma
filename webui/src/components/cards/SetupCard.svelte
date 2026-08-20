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
  import { parseFs, fsOptionsFor } from '../../lib/stores/acquire';
  import {
    deviceCapsFor,
    clampVoltage,
    defaultPretrigThreshold,
    effectiveFullScaleVolts,
    BARE_ARM_PRETRIG_SAMPLES,
    DEFAULT_PRETRIG_TIMEOUT_S,
    PYDVMA_DEFAULT_VMAX,
  } from '../../lib/audio/provider';
  import type { MonitorStore } from '../../lib/stores/monitor';
  import { reportLevels, worstVerdict, verdictAdvice } from '../../lib/model/levelCheck';

  let {
    acquire,
    monitor,
  }: {
    acquire: AcquireStore;
    monitor: MonitorStore;
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
  const deviceNote = $derived(acquire.deviceNote);
  const isBridge = $derived($bridgeCaps != null);
  const hasNidaq = $derived($bridgeCaps?.backends.includes('nidaq') ?? false);

  // Permission is granted once ANY device reports a real label.
  const permissionGranted = $derived($devices.some((d) => d.hasLabel));

  // ---- one interface, several backends ------------------------------
  // Windows publishes a single piece of hardware once per host API, so
  // an ESI U24 XL fills seven rows of a 38-row dropdown and nothing
  // says which to pick — though they differ in word length (24-bit on
  // WDM-KS, 16 on MME) and in whether an unsupported sample rate is
  // refused or silently resampled to. The server marks the backend it
  // recommends; by default show only that one, with an escape hatch for
  // anyone who needs a specific host API. The CURRENT selection is
  // always kept, so switching to "all" and back cannot strand it.
  let allBackends = $state(false);
  const hasHiddenBackends = $derived(
    $devices.some((d) => (d.backendCount ?? 1) > 1),
  );
  const visibleDevices = $derived(
    allBackends
      ? $devices
      : $devices.filter(
          (d) =>
            d.recommended !== false ||
            d.deviceId === $settings.deviceId,
        ),
  );
  /** Device label, qualified by host API only when that is a real choice. */
  function deviceLabel(d: (typeof $devices)[number]): string {
    if (!allBackends || (d.backendCount ?? 1) <= 1 || !d.hostapi) return d.label;
    return `${d.label} — ${d.hostapi}`;
  }
  /**
   * What "Default" actually resolves to.  Leaving the device unset is the
   * common case, and until the server started reporting `default_input` the
   * row was a blank cheque: no way to tell whether the capture would come
   * from the interface on the bench or the laptop's own microphone.  Host API
   * is appended under the same condition {@link deviceLabel} uses, since that
   * is when a host API is a real distinction rather than noise.
   */
  const defaultDeviceLabel = $derived.by(() => {
    const d = $bridgeCaps?.default_input;
    if (!d?.name) return 'Default';
    return allBackends && d.hostapi ? `Default — ${d.name} — ${d.hostapi}` : `Default — ${d.name}`;
  });
  const selectedDevice = $derived(
    $devices.find((d) => d.deviceId === $settings.deviceId),
  );
  /** Is the selected device's VOLTAGE scale known, or standing in for a
   *  measurement nobody made? Sample rates and channel counts come from
   *  the driver and are equally reliable either way; volts do not. */
  const calibrationNote = $derived.by(() => {
    const d = selectedDevice;
    if (!d?.calibration) return null;
    if (d.calibration === 'characterised') {
      return d.fullScaleVolts
        ? `calibrated: full scale ${d.fullScaleVolts.toFixed(3)} V peak`
        : null;
    }
    return d.calibrationAdvice ?? null;
  });
  const calibrationWarn = $derived(
    !!selectedDevice?.calibration && selectedDevice.calibration !== 'characterised',
  );

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
  const srMax = $derived($deviceCaps?.sampleRate?.max);
  // Suggestions for the fs combo — the ladder PLUS whatever is currently set,
  // so an off-ladder rate is always visible (see `fsOptionsFor`).
  const fsSuggestions = $derived(fsOptionsFor(fsOptions, $settings.sampleRate));
  // The fs field's text. A plain `value={...}` binding cannot revert itself
  // after invalid input (the store never changed, so nothing re-renders), so
  // the text is local state mirrored from the store — commit parses it, and
  // anything unparseable simply re-shows the stored rate.
  let fsText = $state('');
  $effect(() => { fsText = fmtHz($settings.sampleRate); });
  // A rate ABOVE what the device can run is worth saying — but not worth
  // blocking: the request is still meaningful (the server coerces, or the
  // decimating capture path handles it) and blocking it was how an
  // unreachable rate became an unchangeable one.
  const fsAboveMax = $derived.by(() => {
    const maxFs = bridgeSelCaps?.max_fs ?? srMax;
    return maxFs != null && $settings.sampleRate > maxFs ? maxFs : null;
  });
  // The rate the converter will really run at, when the device publishes a
  // hardware ladder and the chosen fs is not on it. A sound card cannot
  // sample at 3 kHz; pydvma captures at the lowest native rate above it and
  // decimates behind its own anti-alias filter. Say so, rather than letting
  // the fs select imply the hardware runs there.
  const captureFs = $derived.by(() => {
    const native = bridgeSelCaps?.native_rates;
    if (!native || !native.length) return null;
    const fs = $settings.sampleRate;
    if (native.includes(fs)) return null;
    return native.find((r) => r > fs) ?? native[native.length - 1];
  });
  // Loopback warning: some interfaces present digital loopback channels
  // alongside their real inputs. A Scarlett 2i2 reports four inputs but
  // 3-4 are a tap of its own output mix, so a student who raises the
  // channel count to 4 records the playback, not the structure.
  const loopbackFrom = $derived.by(() => {
    const roles = bridgeSelCaps?.channel_roles;
    if (!roles || !roles.length) return null;
    const first = roles.findIndex((r) => r === 'loopback');
    if (first < 0 || $settings.channelCount <= first) return null;
    return first + 1; // 1-based for display
  });
  // Rates offerable as an explicit capture rate: the hardware's own ladder,
  // at or above the delivered rate (capturing below it would mean upsampling,
  // which the server rejects).
  const nativeRateOptions = $derived(
    (bridgeSelCaps?.native_rates ?? []).filter((r) => r >= $settings.sampleRate),
  );
  // Input modes this interface offers, or null when it is not characterised
  // — without a published maximum input level there is no way to turn a
  // stated gain into volts, so the whole group is hidden rather than shown
  // inert.
  const inputModeOptions = $derived(
    bridgeSelCaps?.input_modes && bridgeSelCaps.input_modes.length
      ? bridgeSelCaps.input_modes
      : null,
  );
  // FIXED-GAIN interface (e.g. the ESI U24 XL): there is no analogue gain
  // anywhere in the input path, so full scale is a hardware constant —
  // `sqrt(2) * 0.7746 * 10 ** (dBu / 20)` at gain 0 — rather than something
  // the operator states. Such a device carries exactly one input mode, so
  // the sole/first key of `max_input_dbu` is authoritative.
  const fixedGain = $derived(bridgeSelCaps?.fixed_gain === true);
  const fixedGainInfo = $derived.by(() => {
    if (!fixedGain) return null;
    const levels = bridgeSelCaps?.max_input_dbu;
    if (!levels) return null;
    const mode = Object.keys(levels)[0];
    if (mode === undefined) return null;
    const dbu = levels[mode];
    if (dbu == null) return null;
    const volts = Math.SQRT2 * 0.7746 * Math.pow(10, dbu / 20);
    return { mode, dbu, volts };
  });
  // Preview of what the stated gain means, so a wrong entry is obvious
  // before it silently scales a whole dataset. A fixed-gain device has no
  // gain TO state, so its full scale comes straight from fixedGainInfo.
  const fullScaleVolts = $derived.by(() => {
    if (fixedGain) return fixedGainInfo?.volts ?? null;
    const gain = $bridgeConfig.inputGainDb;
    const levels = bridgeSelCaps?.max_input_dbu;
    if (gain == null || !levels) return null;
    const dbu = levels[$bridgeConfig.inputMode ?? 'line'];
    if (dbu == null) return null;
    return Math.SQRT2 * 0.7746 * Math.pow(10, (dbu - gain) / 20);
  });

  // ---- trigger (pretrigger) ----
  // Gated on the CAPABILITY, not on the machine having NI-DAQ installed. The
  // old `hasNidaq` gate is why the trigger controls rendered beside a
  // soundcard on the lab PC and did nothing: the machine had NI drivers, the
  // capture path did not. A bridge advertises `pretrigger`; the Web Audio
  // recorder implements its own armed capture, so it always has one.
  const showTrigger = $derived(isBridge ? ($bridgeCaps?.pretrigger ?? false) : true);
  const armed = $derived($bridgeConfig.pretrigArmed ?? false);
  /**
   * Full scale in volts for the selected input, or null when the volt scale
   * is unknown.  Non-null is exactly the condition under which the threshold
   * is a VOLTAGE — the server compares it against VmaxSC-scaled data.
   */
  const triggerFullScale = $derived(
    effectiveFullScaleVolts($bridgeCaps, $settings.deviceId, $bridgeConfig),
  );
  const thresholdInVolts = $derived(triggerFullScale != null);
  /** The threshold that will actually be used when the field is left blank. */
  const thresholdDefault = $derived(defaultPretrigThreshold(triggerFullScale));
  /** The threshold in force right now (explicit value, else the default). */
  const thresholdEffective = $derived($bridgeConfig.pretrigThreshold ?? thresholdDefault);
  /**
   * The same threshold as a percentage of full scale.  A bare "0.05 V" tells
   * nobody whether that is a firm tap or the noise floor; on a 2i2 at high
   * gain it is 0.36 % FS and fires on nothing at all.
   */
  const thresholdPctFs = $derived.by(() => {
    if (triggerFullScale == null || triggerFullScale <= 0) return null;
    const pct = (thresholdEffective / triggerFullScale) * 100;
    return pct >= 10 ? pct.toFixed(0) : pct.toFixed(pct >= 1 ? 1 : 2);
  });
  const pretrigTimeout = $derived($bridgeConfig.pretrigTimeout ?? DEFAULT_PRETRIG_TIMEOUT_S);
  const pretrigSamples = $derived($bridgeConfig.pretrigSamples);

  /** Whether any advisory note has something to say (else the strip is skipped). */
  const hasNotes = $derived(
    $coercedFs != null || fsAboveMax != null || calibrationNote != null
    || $deviceNote != null || loopbackFrom != null || captureFs != null
    || $bridgeConfig.outputFs != null,
  );

  // Level check. The monitor already computes per-channel peak/RMS from the
  // live stream, so this is a reading of it rather than a second capture
  // path. Volts appear only once a gain has been stated — that is the only
  // thing that fixes the normalised-to-volts scale.
  const monitorLevels = $derived(monitor.levels);
  const monitorStatus = $derived(monitor.status);
  const levelReports = $derived(reportLevels($monitorLevels ?? [], fullScaleVolts));
  const levelVerdict = $derived(worstVerdict(levelReports));
  const levelsLive = $derived($monitorStatus === 'streaming' || $monitorStatus === 'paused');

  function fmtDbfs(db: number): string {
    return db === -Infinity ? '−∞' : db.toFixed(1);
  }

  function onOversampleChange(e: Event) {
    const v = (e.target as HTMLSelectElement).value as 'auto' | 'lowest' | 'highest';
    acquire.patchBridge({ oversample: v });
  }
  function onCaptureFsChange(e: Event) {
    const raw = (e.target as HTMLSelectElement).value;
    acquire.patchBridge({ captureFs: raw === '' ? undefined : Number(raw) });
  }
  function onInputGainChange(e: Event) {
    const raw = (e.target as HTMLInputElement).value.trim();
    acquire.patchBridge({ inputGainDb: raw === '' ? undefined : Number(raw) });
  }
  function onInputModeChange(e: Event) {
    const v = (e.target as HTMLSelectElement).value as 'line' | 'inst' | 'mic';
    acquire.patchBridge({ inputMode: v });
  }
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
  /**
   * Commit the typed sample rate.  Accepts plain hertz or k-notation
   * (`3k`, `3.2k`); anything unparseable reverts the field to the stored
   * rate rather than recording at NaN.  Off-ladder values are ACCEPTED — the
   * notes below say what the hardware will really do with them.
   */
  function onFsCommit(e: Event) {
    const raw = (e.target as HTMLInputElement).value;
    const fs = parseFs(raw);
    if (fs == null) { fsText = fmtHz($settings.sampleRate); return; }
    if (fs !== $settings.sampleRate) acquire.patch({ sampleRate: fs });
    else fsText = fmtHz(fs);          // normalise "3k" → "3000" with no change
  }
  /** Enter commits without waiting for blur. */
  function onFsKey(e: KeyboardEvent) {
    if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
  }
  /**
   * Commit a rate picked from the ladder select.  The select's own value
   * is pinned back to the empty placeholder (it is an arrow-only picker,
   * not the display — the input shows the stored rate), so re-picking
   * the same entry later still fires a change event.
   */
  function onFsPick(e: Event) {
    const el = e.target as HTMLSelectElement;
    const fs = Number(el.value);
    el.value = '';
    if (Number.isFinite(fs) && fs > 0 && fs !== $settings.sampleRate) {
      acquire.patch({ sampleRate: fs });
    }
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

  // ---- trigger handlers ----
  /**
   * Arm / disarm from Setup.  Writes the SAME `bridgeConfig.pretrigArmed` the
   * Acquire card's switch writes — this used to be the missing link: Setup's
   * pretrigger fields set samples/threshold/channel but never ARMED anything,
   * and a log with no pretrigger block actively clears the server's settings,
   * so a carefully filled-in Setup produced a free-run capture.
   */
  function onArmToggle(e: Event) {
    acquire.patchBridge({ pretrigArmed: (e.target as HTMLInputElement).checked });
  }
  /** Blank pretrigger-samples clears it (free-run capture); else an integer. */
  function onPretrigSamples(e: Event) {
    const raw = (e.target as HTMLInputElement).value.trim();
    acquire.patchBridge({ pretrigSamples: raw === '' ? null : Math.max(0, Math.round(Number(raw)) || 0) });
  }
  /**
   * Trigger level.  Blank CLEARS it back to the effective default rather than
   * setting zero — `Number('')` is 0, and a zero threshold triggers on the
   * first sample, which is indistinguishable from no trigger at all.
   */
  function onPretrigThreshold(e: Event) {
    const raw = (e.target as HTMLInputElement).value.trim();
    if (raw === '') { acquire.patchBridge({ pretrigThreshold: undefined }); return; }
    const v = Number(raw);
    if (isFinite(v) && v >= 0) acquire.patchBridge({ pretrigThreshold: v });
  }
  function onPretrigChannel(e: Event) {
    const raw = (e.target as HTMLInputElement).value.trim();
    if (raw === '') { acquire.patchBridge({ pretrigChannel: undefined }); return; }
    const v = Math.max(0, Math.round(Number(raw)) || 0);
    acquire.patchBridge({ pretrigChannel: Math.min(v, Math.max(0, $settings.channelCount - 1)) });
  }
  /** Seconds to wait for a crossing before capturing anyway. */
  function onPretrigTimeout(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    if (isFinite(v) && v > 0) acquire.patchBridge({ pretrigTimeout: v });
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
            <option value="">{defaultDeviceLabel}</option>
            {#each visibleDevices as d (d.deviceId)}
              <option value={d.deviceId}>{deviceLabel(d)}</option>
            {/each}
          </select>
          <button class="btn sm" onclick={refreshDevices} title="Refresh device list">↻</button>
          {#if hasHiddenBackends}
            <label class="chk" title="This machine exposes some interfaces through several host APIs. They are the same hardware but not equivalent: WDM-KS gives a 24-bit word and refuses sample rates the device cannot clock, while MME and DirectSound truncate to 16 bits and resample silently. Only the recommended backend is shown unless you tick this.">
              <input
                type="checkbox"
                bind:checked={allBackends}
                data-testid="setup-all-backends"
              />
              <span>all backends</span>
            </label>
          {/if}
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">sample rate</span>
        <div class="grp-ctl">
          <!-- A typed input PLUS an arrow-only select, not a bare select and
               not a datalist. A select can only show a value it has an
               option for: an off-ladder fs (a `--settings` prefill of
               10000, say) rendered BLANK, so the rate could be neither read
               nor changed — the root cause of two lab reports. A datalist
               (the first replacement) was no better as a browser: Chromium
               PREFIX-FILTERS its suggestions by the current text, so with
               "44100" in the field the whole ladder collapsed to one
               entry, shown twice (value + label) — the round-12 "odd
               dropdown" lab report. The input always shows the stored
               value and accepts any rate; the select beside it always
               lists the full ladder, unfiltered. -->
          <input
            type="text"
            inputmode="decimal"
            aria-label="sample rate"
            data-testid="setup-fs"
            title="Sample rate in Hz. Type any rate — 3000, 3k, 48k — or pick one from the list."
            style="width:84px"
            bind:value={fsText}
            onchange={onFsCommit}
            onblur={onFsCommit}
            onkeydown={onFsKey}
          />
          <select
            class="fs-pick"
            aria-label="sample rate options"
            data-testid="setup-fs-pick"
            title="Rates this device runs (plus targets pydvma delivers by capturing high and decimating)."
            value=""
            onchange={onFsPick}
          >
            <option value="" disabled hidden></option>
            {#each fsSuggestions as fs (fs)}
              <option value={String(fs)}>{fmtHz(fs)} Hz</option>
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
      <!--
        TRIGGER — basic tier, capability-gated (bridge `pretrigger` / always
        on Web Audio), NOT gated on the machine having NI drivers installed.
        Arming lives here as well as on the Acquire card because this is where
        the level and channel are set, and setting them without arming did
        nothing at all.  Both controls write the SAME store fields.
      -->
      {#if showTrigger}
        <div class="grp" data-testid="setup-trigger">
          <span class="grp-lab">trigger</span>
          <div class="grp-ctl">
            <label class="switch" title="Wait for the signal to cross the threshold before capturing (the samples before the crossing are kept).">
              <input
                type="checkbox"
                checked={armed}
                onchange={onArmToggle}
                aria-label="arm trigger"
                data-testid="setup-pretrig-arm"
              />
              arm
            </label>
            <input
              type="number"
              step="any"
              min="0"
              style="width:72px"
              value={$bridgeConfig.pretrigThreshold ?? ''}
              placeholder={String(thresholdDefault)}
              onchange={onPretrigThreshold}
              aria-label="trigger threshold"
              data-testid="setup-pretrig-threshold"
              title={thresholdInVolts
                ? 'Trigger level in VOLTS — the server compares it against calibrated data. Blank uses 5 % of full scale.'
                : 'Trigger level as a fraction of full scale (this input is not calibrated, so there are no volts to compare against). Blank uses 0.05.'}
            />
            <span class="ml">{thresholdInVolts ? 'V' : '×FS'}</span>
            {#if thresholdPctFs != null}
              <span class="note" data-testid="setup-threshold-pct">= {thresholdPctFs} % FS</span>
            {/if}
            {#if $settings.channelCount > 1}
              <span class="ml">on ch</span>
              <input
                type="number"
                min="0"
                max={Math.max(0, $settings.channelCount - 1)}
                step="1"
                style="width:52px"
                value={$bridgeConfig.pretrigChannel ?? ''}
                placeholder="0"
                onchange={onPretrigChannel}
                aria-label="trigger channel"
                data-testid="setup-pretrig-channel"
                title="Which channel is watched for the crossing (0-based)."
              />
            {/if}
          </div>
        </div>
      {/if}
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

    <!--
      ADVISORY NOTES — one wrapping strip rather than six full-width rows
      stacked above the settings.  Each note is still its own span (and keeps
      its testid); they simply flow instead of pushing the controls down the
      card one line at a time.  None of these is an error: every one says what
      the hardware will really do with a request it could not take literally.
    -->
    {#if hasNotes}
      <div class="ctx-row notes-row" data-testid="setup-notes">
        {#if $coercedFs}
          <!-- DSA coerced-fs: the device snapped an off-ladder request to a
               legal step (e.g. 8000 → 8533.3 Hz on the 9234). Axes read at
               the TRUE rate — never silently at the requested one. -->
          <span class="note coerce-note" data-testid="setup-coerced-fs">
            device runs at {fmtHz($coercedFs.configured)} Hz (requested {fmtHz($coercedFs.requested)})
          </span>
        {/if}
        {#if fsAboveMax != null}
          <!-- Above the device's own ceiling. Said, not blocked: refusing the
               value is how an unreachable rate became an unchangeable one. -->
          <span class="note coerce-note" data-testid="setup-fs-above-max">
            above this device's maximum {fmtHz(fsAboveMax)} Hz — it will run slower
          </span>
        {/if}
        {#if calibrationNote}
          <!-- Whether "volts" are really volts. For a characterised model the
               full-scale voltage is known and VmaxSC is derived; for anything
               else VmaxSC=1.0 is a PLACEHOLDER, so readings are full-scale
               units wearing a unit they have not earned. Say which. -->
          <span
            class="note {calibrationWarn ? 'warn-note' : 'coerce-note'}"
            data-testid="setup-calibration-note"
          >
            {calibrationNote}
          </span>
        {/if}
        {#if $deviceNote}
          <!-- The index the UI held had gone stale and the server re-pointed
               it at the device we actually named. The capture is right; the
               user should still know their device list moved. -->
          <span class="note coerce-note" data-testid="setup-device-note">
            {$deviceNote}
          </span>
        {/if}
        {#if loopbackFrom}
          <!-- Loopback channels are a digital tap of the interface's own
               output, not inputs. Silent unless something is playing, and
               actively misleading when it is. -->
          <span class="note coerce-note" data-testid="setup-loopback-note">
            channels {loopbackFrom}+ are the device's digital loopback, not inputs
          </span>
        {/if}
        {#if captureFs}
          <!-- Hardware-ladder note: the chosen fs is not a rate this device
               can run, so the capture happens at a native rate and is
               resampled down by pydvma (96 dB stopband) rather than by the
               OS, whose alias rejection was measured as poor as 12 dB. -->
          <span class="note coerce-note" data-testid="setup-capture-fs">
            captures at {fmtHz(captureFs)} Hz, resampled to {fmtHz($settings.sampleRate)} Hz
          </span>
        {/if}
        {#if $bridgeConfig.outputFs != null}
          <!-- AO rate clamp: the effective output device's analog output tops
               out below the requested input fs (USB-6003: AO 5 kS/s vs AI
               100 kS/s), so the store pins output_fs to the cap — unclamped,
               MySettings defaults output_fs = fs and a stimulus-enabled log
               fails server-side. -->
          <span class="note coerce-note" data-testid="output-fs-clamp-note">
            output runs at {fmtHz($bridgeConfig.outputFs)} Hz (device AO limit)
          </span>
        {/if}
      </div>
    {/if}

    {#if full}
      <!--
        FULL option set, in TITLED SECTIONS rather than one wrapping row of
        a dozen-plus groups.  The sections are the questions an operator
        actually asks in order — what is this device / what rate does it
        really run / are the levels right / how does it trigger / and the
        NI-only extras — and each is its own sub-row so a wide group cannot
        drag an unrelated one onto the next line.  Read-only readouts
        (capabilities, live levels) render as info lines, visibly not
        controls.  Basic mode above is untouched.
      -->
      <div class="full-block" data-testid="setup-full">
        <!-- ── device ─────────────────────────────────────────────── -->
        <div class="full-sec">
          <span class="sec-head">device</span>
          <div class="ctx-row sec-row">
            <!-- Reported capability ranges (getCapabilities) — a READING,
                 not a setting. -->
            <div class="info">
              <span class="info-lab">device capabilities</span>
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
            <!-- getUserMedia DSP flags (all default OFF). -->
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
            <!-- Input latency hint (best-effort). -->
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
          </div>
        </div>

        <!-- ── rates ──────────────────────────────────────────────── -->
        <div class="full-sec">
          <span class="sec-head">rates</span>
          <div class="ctx-row sec-row">
            <!-- Digital low-pass (round-9) — fs keeps its meaning; ON means
                 the capture oversamples at the device max and comes down to
                 fs behind a linear-phase anti-alias FIR (noise-reducing
                 decimation). Bridge: MySettings.lpf_on (server-side chain);
                 Web Audio: native-rate capture + engine resample. -->
            <div class="grp">
              <span class="grp-lab">digital low-pass</span>
              <div class="grp-ctl">
                <label class="switch"
                  title="Sample at the device's maximum rate, then decimate to your fs behind an anti-alias filter (reduces noise and aliasing). Off = sample at fs directly.">
                  <input type="checkbox" checked={$settings.lpfOn}
                    data-testid="setup-lpf"
                    onchange={(e) => acquire.patch({ lpfOn: (e.target as HTMLInputElement).checked })} />
                  oversample&nbsp;+&nbsp;decimate
                </label>
                {#if $settings.lpfOn}
                  <span class="note">logs at fs = {($settings.sampleRate / 1000).toFixed(3).replace(/\.?0+$/, '')} kHz via a higher capture rate</span>
                {/if}
              </div>
            </div>
            <!-- fs is the DELIVERED rate; these decide what the converter
                 actually runs at before pydvma decimates. Bridge-only: the
                 Web Audio path has no hardware clock to pin. -->
            {#if isBridge}
              <div class="grp" data-testid="setup-capture-rate">
                <span class="grp-lab">capture rate</span>
                <div class="grp-ctl">
                  <select
                    aria-label="oversample strategy"
                    title="How far above fs to capture when oversampling. Auto follows the device: the lowest sufficient rate on a delta-sigma converter (already anti-aliased in silicon), the highest available on one with no anti-alias filter."
                    value={$bridgeConfig.oversample ?? 'auto'}
                    onchange={onOversampleChange}
                    style="width:110px"
                  >
                    <option value="auto">auto</option>
                    <option value="lowest">lowest</option>
                    <option value="highest">highest</option>
                  </select>
                  <select
                    aria-label="capture sample rate"
                    title="Force the rate the hardware samples at. Auto picks it from the device's own ladder."
                    value={$bridgeConfig.captureFs == null ? '' : String($bridgeConfig.captureFs)}
                    onchange={onCaptureFsChange}
                    style="width:96px"
                  >
                    <option value="">auto</option>
                    {#each nativeRateOptions as r}
                      <option value={String(r)}>{fmtHz(r)} Hz</option>
                    {/each}
                  </select>
                  <span class="ml note">hardware rate</span>
                </div>
              </div>
            {/if}
          </div>
        </div>

        <!-- ── levels ─────────────────────────────────────────────── -->
        <div class="full-sec">
          <span class="sec-head">levels</span>
          <div class="ctx-row sec-row">
            <!-- Soundcard input gain — no audio API can READ the preamp
                 gain, so stating it is the only route to calibrated volts.
                 The server derives VmaxSC from the device's published
                 maximum input level. A FIXED-GAIN interface (e.g. the ESI
                 U24 XL) has no gain to state at all — full scale is a
                 hardware constant — so it gets a static line instead of the
                 gain input + mode select (mode is single anyway). -->
            {#if isBridge && inputModeOptions}
              {#if fixedGain}
                <div class="info" data-testid="setup-input-gain">
                  <span class="info-lab">input level (fixed gain)</span>
                  <span
                    class="note"
                    data-testid="setup-fixed-gain-note"
                    title="This interface has no analogue gain anywhere in the input path — full scale is a hardware constant, so calibrated volts need no operator input."
                  >
                    full scale ±{fixedGainInfo?.volts.toFixed(2)} V
                    ({fixedGainInfo && fixedGainInfo.dbu >= 0 ? '+' : ''}{fixedGainInfo?.dbu} dBu {fixedGainInfo?.mode})
                  </span>
                </div>
              {:else}
                <div class="grp" data-testid="setup-input-gain">
                  <span class="grp-lab">input gain (for calibrated volts)</span>
                  <div class="grp-ctl">
                    <input
                      type="number"
                      min="0"
                      step="1"
                      value={$bridgeConfig.inputGainDb ?? ''}
                      onchange={onInputGainChange}
                      placeholder="not set"
                      title="The preamp gain currently set on the interface, in dB. pydvma cannot read it, so state it here and full scale in volts follows from the device's published maximum input level."
                      aria-label="input gain in dB"
                      style="width:72px"
                    />
                    <span class="ml">dB</span>
                    <select
                      aria-label="input mode"
                      title="Which input the signal is on — sets the maximum input level used with the gain."
                      value={$bridgeConfig.inputMode ?? 'line'}
                      onchange={onInputModeChange}
                      style="width:84px"
                    >
                      {#each inputModeOptions as m}
                        <option value={m}>{m}</option>
                      {/each}
                    </select>
                    {#if fullScaleVolts != null}
                      <span class="note" data-testid="setup-full-scale">
                        full scale ≈ {fullScaleVolts.toFixed(3)} V pk
                      </span>
                    {/if}
                  </div>
                </div>
              {/if}
            {/if}
            <!-- Read off the live monitor, so no second capture path.
                 Getting the gain wrong is silent in both directions: too
                 high clips, too low buries the signal in converter noise
                 while still drawing a plausible trace. -->
            <div class="info" data-testid="setup-levels">
              <span class="info-lab">input level</span>
              {#if !levelsLive}
                <span class="note">start the monitor to check levels</span>
              {:else if !levelReports.length}
                <span class="note">waiting for the first block…</span>
              {:else}
                <span class="mono note" data-testid="setup-levels-readout">
                  {#each levelReports as r}
                    ch{r.channel}
                    {#if r.peakVolts != null}
                      {r.peakVolts.toFixed(r.peakVolts < 1 ? 4 : 3)} V pk
                    {:else}
                      {fmtDbfs(r.peakDbfs)} dBFS pk
                    {/if}
                    {#if r.channel < levelReports.length - 1}·{/if}
                  {/each}
                </span>
                {#if levelVerdict && levelVerdict !== 'ok'}
                  <span class="note coerce-note" data-testid="setup-levels-verdict">
                    {verdictAdvice(levelVerdict)}
                  </span>
                {:else if levelVerdict === 'ok'}
                  <span class="note" data-testid="setup-levels-verdict">
                    {verdictAdvice('ok')}
                  </span>
                {/if}
              {/if}
            </div>
          </div>
        </div>

        <!-- ── trigger ────────────────────────────────────────────── -->
        <!-- The advanced half of the trigger group above: how much context
             to keep before the crossing, and how long to wait for one.
             Capability-gated like the basic tier — these used to sit behind
             `hasNidaq`, which is why they rendered next to a soundcard on a
             machine that merely HAD NI drivers, and never rendered on a
             machine that did not. -->
        {#if showTrigger}
          <div class="full-sec">
            <span class="sec-head">trigger</span>
            <div class="ctx-row sec-row">
              <div class="grp" data-testid="setup-pretrigger">
                <span class="grp-lab">pretrigger context</span>
                <div class="grp-ctl">
                  <input
                    type="number"
                    min="0"
                    step="1"
                    placeholder={String(BARE_ARM_PRETRIG_SAMPLES)}
                    value={pretrigSamples ?? ''}
                    onchange={onPretrigSamples}
                    title="How many samples BEFORE the crossing to keep. Blank uses 100, which fits the default context buffer."
                    aria-label="pretrigger samples"
                    data-testid="setup-pretrig-samples"
                    style="width:76px"
                  />
                  <span class="ml">samples before trigger</span>
                </div>
              </div>
              <div class="grp">
                <span class="grp-lab">timeout</span>
                <div class="grp-ctl">
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={pretrigTimeout}
                    onchange={onPretrigTimeout}
                    title="Seconds to wait for a crossing. On timeout the capture runs anyway — the set still lands, it is simply not trigger-aligned."
                    aria-label="pretrigger timeout"
                    data-testid="setup-pretrig-timeout"
                    style="width:64px"
                  />
                  <span class="ml">s to wait</span>
                </div>
              </div>
            </div>
          </div>
        {/if}

        <!-- ── NI-DAQ ─────────────────────────────────────────────── -->
        <!-- Rendered ONLY when the bridge reports the 'nidaq' backend (no
             dead controls elsewhere). Everything here sends through the
             acquire store's bridge config → the next `configure` message's
             MySettings kwargs. -->
        {#if hasNidaq}
          <div class="full-sec">
            <span class="sec-head">NI-DAQ</span>
            <div class="ctx-row sec-row">
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
              <!-- NI voltage rails: input (VmaxNI) + output (output_VmaxNI),
                   each clamped to the selected device's reported range so a
                   requested range never exceeds the hardware. The 9260's
                   ±4.24 V output rail is BELOW the pydvma 5 V default; the
                   store clamps the default down and this note says why. -->
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
            </div>
          </div>
        {/if}
      </div>
    {/if}
  </div>
</section>

<style>
  /* Arrow-only ladder picker beside the fs input: wide enough for the
     native dropdown arrow, with the (placeholder) value area collapsed. */
  .fs-pick {
    width: 26px;
    min-width: 26px;
    padding-left: 2px;
    padding-right: 2px;
  }
  .perm-btn {
    color: var(--indigo);
    border-color: var(--accent-soft-border);
    background: var(--accent-soft);
    white-space: normal;
    text-align: left;
    height: auto;
    padding: 4px 8px;
  }
  /* The advanced panel: titled sections stacked, each its own sub-row, so a
     wide group can never drag an unrelated one onto the next line. */
  .full-block {
    display: flex;
    flex-direction: column;
    gap: 7px;
    border-top: 1px dashed var(--border);
    padding-top: 7px;
    margin-top: 2px;
    min-width: 0;
  }
  .full-sec {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    min-width: 0;
  }
  .sec-head {
    flex: 0 0 62px;
    padding-top: 4px;
    font-size: 9.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted-2);
    white-space: nowrap;
  }
  .sec-row {
    flex: 1;
    min-width: 0;
  }
  /* A READ-ONLY line. Deliberately unlike .grp: no control-height row, a
     lighter label, so a readout is not mistaken for something to edit. */
  .info {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  .info-lab {
    font-size: 9.5px;
    font-weight: 500;
    font-style: italic;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted-2);
    white-space: nowrap;
  }
  /* Advisory strip — the notes flow instead of stacking one row each. */
  .notes-row {
    align-items: center;
    gap: 12px;
    row-gap: 3px;
  }
  /* Coerced-fs / voltage-clamp advisories — visible but not an error. */
  .coerce-note {
    color: var(--amber, #b45309);
    font-weight: 500;
  }
  /* An UNCALIBRATED device is not an error either — it just means the
     numbers are full-scale units, not volts. Same weight as the other
     advisories, muted so a characterised bench does not look alarming. */
  .warn-note {
    color: var(--muted, #6b7280);
    font-weight: 500;
  }
  /* Inline "all backends" toggle beside the device dropdown. */
  .chk {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.85em;
    color: var(--muted, #6b7280);
    white-space: nowrap;
    cursor: pointer;
  }
  .chk input {
    margin: 0;
  }
</style>
