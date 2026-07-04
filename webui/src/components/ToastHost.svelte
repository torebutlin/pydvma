<script lang="ts">
  /**
   * Bottom-right toast stack (Task 13). Renders the `toasts` store as a
   * fixed column of cards: plain toasts auto-dismiss (handled by the
   * store), actionable ones show labelled buttons (Restore / Dismiss,
   * Set folder, …) and stay until the user acts. `level` tints the left
   * accent bar (info / error / success). Each toast exposes a testid so
   * the e2e can target the restore banner and its buttons.
   */
  import type { Toasts } from '../lib/stores/toast';

  let { toasts: store }: { toasts: Toasts } = $props();
  const toasts = $derived(store.toasts);
</script>

<div class="toast-host" data-testid="toast-host" aria-live="polite">
  {#each $toasts as t (t.id)}
    <div class="toast {t.level}" data-testid="toast" role="status">
      <span class="msg">{t.message}</span>
      {#if t.actions}
        <div class="actions">
          {#each t.actions as a (a.label)}
            <button class="action" onclick={a.run}>{a.label}</button>
          {/each}
        </div>
      {:else}
        <button class="close" aria-label="Dismiss" onclick={() => store.dismiss(t.id)}>×</button>
      {/if}
    </div>
  {/each}
</div>

<style>
  .toast-host {
    position: fixed;
    right: 16px;
    bottom: 16px;
    z-index: 50;
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-width: 360px;
  }
  .toast {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 3px solid var(--muted);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    font-size: 12.5px;
    color: var(--text);
  }
  .toast.error {
    border-left-color: #dc2626;
  }
  .toast.success {
    border-left-color: var(--green);
  }
  .toast.info {
    border-left-color: #2563eb;
  }
  .msg {
    flex: 1 1 auto;
  }
  .actions {
    display: flex;
    gap: 6px;
    flex: 0 0 auto;
  }
  .action {
    height: 26px;
    padding: 0 10px;
    border-radius: 6px;
    border: 1px solid #93c5fd;
    background: #eff6ff;
    color: #2563eb;
    font-weight: 600;
    font-size: 12px;
    cursor: pointer;
    font-family: inherit;
  }
  .action:hover {
    background: #dbeafe;
  }
  .close {
    flex: 0 0 auto;
    width: 20px;
    height: 20px;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--muted);
    font-size: 16px;
    line-height: 1;
    cursor: pointer;
  }
  .close:hover {
    color: var(--text);
  }
</style>
