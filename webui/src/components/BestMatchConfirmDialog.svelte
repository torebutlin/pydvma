<script lang="ts">
  /**
   * "Best match onto <reference>" — the confirm prompt in front of
   * `actions.calcBestMatch`.
   *
   * WHY IT EXISTS. Best Match is relative scaling: it stores, per rescaled TF
   * line, the factor that brings that line onto the reference's displayed
   * level, as its TRANSFER-FUNCTION calibration (Calibrate's "Transfer
   * function" section). The reference line and every sensor calibration are
   * untouched, but whatever factor a RESCALED line showed before — a
   * free-mass calibration, an earlier Best Match, or the ratio its channel
   * calibration implied — is replaced. Nothing in the toolbar button suggests
   * that, hence this.
   *
   * IT IS ONLY RAISED WHEN SOMETHING IS AT STAKE: `calcBestMatch` asks only
   * when a rescaled line shows a factor other than 1 today, so `calibrated`
   * is normally non-empty. The prompt names the reference and says it stays as
   * it is (before 2026-11 it read as if the reference's own factor would be
   * replaced), names the cards that are rescaled, and says which of them lose
   * a calibrated level. The action is Undo-able from the result toast — the
   * text says so, because a reversible action people know is reversible is one
   * they can try.
   *
   * DISMISSAL IS CANCEL (unlike `SonoIncludeDialog`, where dismissal means
   * "don't include" and the save proceeds): nothing has been committed at this
   * point, so Escape and a backdrop click both mean "don't do it".
   *
   * DUMB component: it renders the names it is given and reports yes/no.
   */
  let {
    reference,
    names,
    calibrated,
    onchoose,
  }: {
    /** The reference TF line, named as the "ref TF" picker names it. */
    reference: string;
    /** Display names of every card Best Match would rescale. */
    names: string[];
    /** Those with a calibrated level today — what stands to be replaced. */
    calibrated: string[];
    /** The answer; dismissal reports `false`. */
    onchoose: (ok: boolean) => void;
  } = $props();

  const many = $derived(calibrated.length > 1);

  /** The default button, focused on mount so Enter confirms. */
  let defaultBtn = $state<HTMLButtonElement>();

  $effect(() => { defaultBtn?.focus(); });

  /**
   * Escape cancels — bound on the WINDOW, not the overlay, because a dialog
   * raised from a card button leaves focus on that button and an
   * overlay-scoped handler never sees the key. Same reasoning as
   * `SonoIncludeDialog` / `ChooseSetsPopover`.
   */
  function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'Escape') onchoose(false);
  }
</script>

<svelte:window on:keydown={onKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div
  class="overlay"
  data-testid="best-match-confirm-overlay"
  role="dialog"
  aria-modal="true"
  aria-label="Best match onto {reference}"
  tabindex="-1"
  onclick={(e) => { if (e.target === e.currentTarget) onchoose(false); }}
>
  <div class="modal">
    <div class="modal-title">Best match onto <span class="names">{reference}</span></div>

    <p class="body" data-testid="best-match-confirm-reference">
      The reference, <span class="names">{reference}</span>, stays as it is.
      Best match rescales <span class="names">{names.join(', ')}</span> onto
      it, and stores each result <em>as that transfer function's calibration
      factor</em>, the one in Calibrate's Transfer function section. Sensor
      calibrations are not changed.
    </p>

    {#if calibrated.length > 0}
      <p class="body warn" data-testid="best-match-confirm-risk">
        <span class="names">{calibrated.join(', ')}</span>
        {many ? 'show' : 'shows'} a calibrated level now, which will be
        replaced. The rescaled lines take the reference's units.
      </p>
    {/if}

    <p class="note">
      You can put the old values back with Undo on the result message, or by
      editing the transfer function in Calibrate.
    </p>

    <div class="mrow end">
      <button class="btn" data-testid="best-match-confirm-cancel" onclick={() => onchoose(false)}>
        Cancel
      </button>
      <button
        class="btn indigo"
        data-testid="best-match-confirm-ok"
        bind:this={defaultBtn}
        onclick={() => onchoose(true)}
      >Rescale</button>
    </div>
  </div>
</div>

<style>
  /* Same overlay/modal surface as CalibrateDialog (the house modal). */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 330;
    background: var(--scrim);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .modal {
    width: 400px;
    background: var(--surface);
    border-radius: 12px;
    padding: 16px 18px 14px;
    box-shadow: 0 24px 70px rgba(16, 24, 40, 0.35);
  }
  .modal-title {
    font-weight: 700;
    font-size: 14px;
    margin-bottom: 10px;
  }
  .body {
    font-size: 12.5px;
    line-height: 1.45;
    color: var(--text);
    margin: 0 0 8px;
  }
  .body.warn {
    color: var(--text);
    background: var(--warn-bg, rgba(217, 119, 6, 0.1));
    border-left: 3px solid var(--warn, #d97706);
    border-radius: 0 6px 6px 0;
    padding: 8px 10px;
  }
  .names {
    font-family: var(--font-mono);
    font-size: 11.5px;
    overflow-wrap: anywhere;
  }
  .modal-title .names {
    font-size: 13px;
  }
  .note {
    font-size: 11.5px;
    line-height: 1.4;
    color: var(--muted);
    margin: 8px 0 0;
  }
  .mrow {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .mrow.end {
    justify-content: flex-end;
    margin-top: 16px;
  }
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 28px;
    padding: 0 12px;
    border: 1px solid var(--border);
    border-radius: 7px;
    background: var(--control-bg);
    color: var(--text);
    font-family: inherit;
    font-size: 12.5px;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
  }
  .btn:hover {
    border-color: var(--border-strong);
    background: var(--hover-bg);
  }
  .btn.indigo {
    background: var(--indigo, #4f46e5);
    border-color: var(--indigo, #4f46e5);
    color: #fff;
    font-weight: 600;
  }
  .btn.indigo:hover {
    background: var(--indigo-hover);
  }
</style>
