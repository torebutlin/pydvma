<script lang="ts">
  /**
   * Setup-stage context card (design spec §4). The single settings home
   * for audio acquisition: device select, sample rate, channels, and
   * duration.  Apply restarts the stream when settings change.
   *
   * Follows the shared `.ctx-card.card-controls` layout pattern
   * (ctx-name / ctx-body with ctx-row+grp / ctx-primary).
   */
  import type { AcquireStore } from '../../lib/stores/acquire';

  let {
    acquire,
  }: {
    acquire: AcquireStore;
  } = $props();

  const devices = $derived(acquire.devices);
  const settings = $derived(acquire.settings);

  // Common sample rates for the dropdown.
  const SAMPLE_RATES = [8000, 16000, 22050, 44100, 48000, 96000];
  // Duration presets.
  const DURATIONS = [0.5, 1, 2, 5, 10, 30, 60];

  function onDeviceChange(e: Event) {
    acquire.patch({ deviceId: (e.target as HTMLSelectElement).value });
  }
  function onFsChange(e: Event) {
    acquire.patch({ sampleRate: Number((e.target as HTMLSelectElement).value) });
  }
  function onChannelsChange(e: Event) {
    const v = Math.max(1, Math.min(32, Number((e.target as HTMLInputElement).value) || 1));
    acquire.patch({ channelCount: v });
  }
  function onDurationChange(e: Event) {
    acquire.patch({ durationS: Number((e.target as HTMLSelectElement).value) });
  }

  /** Kick a fresh device enumeration (helps after granting permission). */
  function refreshDevices() {
    void acquire.refreshDevices();
  }
</script>

<section class="ctx-card card-controls" aria-label="Setup stage controls">
  <div class="ctx-name">
    <span class="cn-t">Setup</span>
    <span class="cn-s">configure</span>
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
              <option value={fs}>{fs >= 1000 ? `${fs / 1000}k` : fs}</option>
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
            max="32"
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
    </div>
  </div>
</section>
