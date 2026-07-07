<script lang="ts">
  /**
   * Acquire-stage context card (design spec §4). Shows a settings summary,
   * the prominent green **Log Data** button (the app's primary action), a
   * status line during recording, and a Cancel button.
   *
   * On completion the recorded set is pushed into the actions pipeline
   * (addRecordedSet) and the view switches to Time.
   *
   * Output signal and pretrigger rows are TODO placeholders for the next
   * iteration (design spec §4 inline-expand rows).
   */
  import type { AcquireStore } from '../../lib/stores/acquire';
  import { recordingToItem } from '../../lib/stores/acquire';
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

  const recording = $derived($status === 'recording');

  /** Format elapsed time as "0.0 / 2.0 s". */
  const progress = $derived(
    recording ? `${$elapsed.toFixed(1)} / ${$settings.durationS.toFixed(1)} s` : '',
  );

  /** Human name of the selected input device ('Default' when unset). */
  const deviceName = $derived.by(() => {
    const id = $settings.deviceId;
    if (!id) return 'Default input';
    const d = $devices.find((x) => x.deviceId === id);
    return d?.label ?? 'Selected device';
  });

  /**
   * Fuller settings summary (round-2 feedback): fs · channels · duration ·
   * device · pretrigger.  Pretrigger is shown honestly as "no pretrig"
   * since the capture path does not implement it yet.
   */
  const summary = $derived.by(() => {
    const s = $settings;
    const fs = s.sampleRate >= 1000 ? `${(s.sampleRate / 1000).toFixed(1)} kHz` : `${s.sampleRate} Hz`;
    return `${fs} · ${s.channelCount} ch · ${s.durationS.toFixed(1)} s · ${deviceName} · no pretrig`;
  });

  async function logData() {
    try {
      const rec = await acquire.record();
      // Convert to a DvmaItem and add to the dataset.
      const item = recordingToItem(rec);
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
    <span class="cn-s">record</span>
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
      {#if recording}
        <div class="grp">
          <span class="grp-lab">progress</span>
          <div class="grp-ctl">
            <span class="ml mono">{progress}</span>
          </div>
        </div>
      {/if}
    </div>
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
      <button class="btn log-btn" onclick={logData}>Log Data</button>
    {/if}
  </div>
</section>

<style>
  .sum-chip {
    background: #f8f9fb !important;
    border-radius: 13px !important;
    max-width: 420px;
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
  .cancel-btn {
    background: #fff !important;
    border-color: #ef4444 !important;
    color: #ef4444 !important;
    font-weight: 600 !important;
  }
  .cancel-btn:hover {
    background: #fef2f2 !important;
  }
</style>
