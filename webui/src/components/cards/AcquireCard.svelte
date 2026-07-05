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
  const status = $derived(acquire.status);
  const statusText = $derived(acquire.statusText);
  const errorMsg = $derived(acquire.errorMsg);
  const elapsed = $derived(acquire.elapsed);

  const recording = $derived($status === 'recording');

  /** Format elapsed time as "0.0 / 2.0 s". */
  const progress = $derived(
    recording ? `${$elapsed.toFixed(1)} / ${$settings.durationS.toFixed(1)} s` : '',
  );

  /** Settings summary chip: "44.1 kHz · 1 ch · 2.0 s". */
  const summary = $derived.by(() => {
    const s = $settings;
    const fs = s.sampleRate >= 1000 ? `${(s.sampleRate / 1000).toFixed(1)} kHz` : `${s.sampleRate} Hz`;
    return `${fs} · ${s.channelCount} ch · ${s.durationS.toFixed(1)} s`;
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
          <span class="ml">{summary}</span>
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
