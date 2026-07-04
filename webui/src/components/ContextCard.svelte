<script lang="ts">
  /**
   * Fixed-height context-card frame (design spec §3; visuals ported
   * from dev/mockups/round2-bench.html `.ctx-zone` / `.ctx-card`).
   *
   * In WIDE mode the zone is a fixed 118px tall — every stage's card is
   * the SAME height so the frame never jumps as stages switch (a
   * Playwright test may assert this). In NARROW mode (the `narrow`
   * prop) it may grow, so the height contract relaxes to a min-height.
   *
   * The real per-stage cards are Task 12; this is a placeholder that
   * shows the active stage's label plus a muted "controls arrive in
   * Task 12" note, holding the fixed-height contract in the meantime.
   */
  import { activeStage, STAGES } from '../lib/stores/stages';

  let { narrow = false }: { narrow?: boolean } = $props();

  const labelOf = (id: string): string => STAGES.find(s => s.id === id)?.label ?? '';
</script>

<div class="ctx-zone" class:narrow>
  <section class="ctx-card" aria-label="stage controls">
    <div class="ctx-name">
      <span class="cn-t">{labelOf($activeStage)}</span>
      <span class="cn-s">stage</span>
    </div>
    <div class="ctx-body">
      <span class="ctx-note">controls arrive in Task 12</span>
    </div>
  </section>
</div>

<style>
  .ctx-zone {
    flex: 0 0 auto;
    height: 118px;
    padding: 9px 16px;
    background: var(--bg);
  }
  .ctx-card {
    display: flex;
    align-items: stretch;
    height: 100%;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    padding: 8px 12px;
    position: relative;
  }
  .ctx-name {
    flex: 0 0 92px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 2px;
    border-right: 1px solid var(--border);
    padding-right: 10px;
    margin-right: 12px;
  }
  .cn-t {
    font-weight: 700;
    font-size: 13px;
  }
  .cn-s {
    font-size: 9.5px;
    color: #98a1b5;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .ctx-body {
    flex: 1;
    display: flex;
    align-items: center;
    min-width: 0;
  }
  .ctx-note {
    font-size: 12px;
    color: var(--muted);
    font-style: italic;
  }

  /* Narrow mode: card may grow, so relax the fixed height to a floor. */
  .ctx-zone.narrow {
    height: auto;
    min-height: 118px;
  }
  .ctx-zone.narrow .ctx-card {
    height: auto;
    min-height: 100px;
  }
</style>
