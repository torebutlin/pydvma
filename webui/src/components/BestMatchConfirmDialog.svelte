<script lang="ts">
  /**
   * "Best match will replace calibration factors" — the confirm prompt in
   * front of `actions.calcBestMatch`.
   *
   * WHY IT EXISTS. Best Match is relative scaling: it stores, per channel, the
   * factor that brings each TF onto the reference's level. pydvma has exactly
   * one place to put a per-channel display multiplier — `channel_cal_factors`
   * — and that is the same slot the Calibrate dialog fills with a transducer
   * sensitivity. So a Best Match over a calibrated set REPLACES a physical
   * calibration with a relative one, while the engineering `units` stay as
   * they were: the axis goes on saying `m/s²` over numbers that no longer are.
   * Nothing in the toolbar button suggests that, hence this.
   *
   * The wording adapts to what is actually at stake. With `calibrated` empty
   * every set is still raw, nothing is lost and this reads as a plain
   * confirmation; with sets listed it names them and says what will happen to
   * them. Either way the action is Undo-able from the result toast — the text
   * says so, because a reversible action people know is reversible is one they
   * can try.
   *
   * DISMISSAL IS CANCEL (unlike `SonoIncludeDialog`, where dismissal means
   * "don't include" and the save proceeds): nothing has been committed at this
   * point, so Escape and a backdrop click both mean "don't do it".
   *
   * DUMB component: it renders the names it is given and reports yes/no.
   */
  let {
    names,
    calibrated,
    onchoose,
  }: {
    /** Display names of every set Best Match would rescale. */
    names: string[];
    /** Those with a non-identity calibration today — what stands to be lost. */
    calibrated: string[];
    /** The answer; dismissal reports `false`. */
    onchoose: (ok: boolean) => void;
  } = $props();

  const atRisk = $derived(calibrated.length > 0);
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
  aria-label="Best match will change calibration factors"
  tabindex="-1"
  onclick={(e) => { if (e.target === e.currentTarget) onchoose(false); }}
>
  <div class="modal">
    <div class="modal-title">Best match changes calibration factors</div>

    <p class="body">
      Best match rescales {names.length === 1 ? 'this measurement' : `these ${names.length} measurements`}
      onto the reference, and stores the result <em>as the calibration
      factors</em> — the same values the Calibrate dialog sets.
    </p>

    {#if atRisk}
      <p class="body warn" data-testid="best-match-confirm-risk">
        {many ? 'These are' : 'This is'} calibrated now, so {many ? 'their' : 'its'}
        current calibration will be replaced:
        <span class="names">{calibrated.join(', ')}</span>.
        The engineering units stay as they are, so the axis will keep its unit
        label over numbers that have become relative.
      </p>
    {:else}
      <p class="note" data-testid="best-match-confirm-norisk">
        Nothing here is calibrated yet, so there is no transducer calibration
        to lose.
      </p>
    {/if}

    <p class="note">
      You can put {atRisk ? 'the old values' : 'this'} back with Undo on the
      toast, or by editing the factors in Calibrate.
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
