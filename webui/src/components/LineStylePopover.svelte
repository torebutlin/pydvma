<script lang="ts">
  /**
   * The tray card's ⋯ pop-up: each line's colour and thickness (2026-11-27,
   * 4C6 lab — two lines from two sets came out the same colour).
   *
   * Deliberately small (Tore: "keep simple"): per line, the FIXED 12-colour
   * `LINE_PALETTE` as swatches (the current one ringed) and thin / normal /
   * bold; one **Reset to automatic** for the set. No dash style, since dashes
   * already mean coherence and modal-fit lines, and no free colour picker.
   *
   * MOUNTED ON `document.body` (the `portal` action), at the ⋯ button's
   * position and clamped inside the window: the tray scrolls and clips its
   * cards, and the narrow layout's drawer is a scroller too, so a pop-up
   * kept inside the card could be cut off or hard to find. It opens below the
   * button (above when there is no room), right-aligned to it, and closes on
   * Escape, Done, a press outside it and the button, and a scroll or resize
   * that moves the button away from it.
   *
   * DUMB: it shows the set it is given and reports picks; the caller applies
   * them (`actions.setLineStyle` / `actions.resetLineStyles`).
   */
  import { onMount, tick } from 'svelte';
  import Segmented from './Segmented.svelte';
  import { LINE_PALETTE, type LineWeight, type SetView } from '../lib/stores/selection';

  /** Plain names for the palette, for each swatch's tooltip and label. */
  const COLOR_NAMES = ['blue', 'red', 'green', 'amber', 'violet', 'cyan',
    'pink', 'olive', 'purple', 'teal', 'dark red', 'dark green'];
  const WEIGHTS: { value: LineWeight; label: string; title: string }[] = [
    { value: 'thin', label: 'thin', title: 'Thin line (1 px)' },
    { value: 'normal', label: 'normal', title: 'Normal line (1.5 px)' },
    { value: 'bold', label: 'bold', title: 'Bold line (2.5 px)' },
  ];
  /** Gap between the button and the pop-up, and the pop-up and the window edge, px. */
  const GAP = 6;

  let {
    set,
    labelOf,
    anchor,
    onpick,
    onreset,
    onclose,
  }: {
    /** The set whose lines are shown (its live `colors` / `widths`). */
    set: SetView;
    /** Display label of line `ch`, as its tray row shows it. */
    labelOf: (ch: number) => string;
    /** The ⋯ button: where the pop-up sits, and a press on it is not "outside". */
    anchor: HTMLElement;
    onpick: (ch: number, style: { color?: string; weight?: LineWeight }) => void;
    onreset: () => void;
    onclose: () => void;
  } = $props();

  let root = $state<HTMLDivElement>();
  let left = $state(0);
  let top = $state(0);

  /** Move `node` to the end of `document.body`; Svelte still removes it. */
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy() { node.remove(); } };
  }

  /** Place the pop-up at the anchor, inside the window. */
  function place(): void {
    if (!root) return;
    const a = anchor.getBoundingClientRect();
    const w = root.offsetWidth, h = root.offsetHeight;
    const vw = window.innerWidth, vh = window.innerHeight;
    let x = a.right - w;
    let y = a.bottom + GAP;
    if (y + h > vh - GAP && a.top - GAP - h >= GAP) y = a.top - GAP - h;   // no room below
    x = Math.min(Math.max(x, GAP), Math.max(GAP, vw - GAP - w));
    y = Math.min(Math.max(y, GAP), Math.max(GAP, vh - GAP - h));
    left = x;
    top = y;
  }

  onMount(() => {
    void tick().then(() => {
      place();
      root?.querySelector<HTMLElement>('[aria-pressed="true"]')?.focus({ preventScroll: true });
    });
  });

  function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'Escape') { e.stopPropagation(); onclose(); }
  }
  function onPointerDown(e: PointerEvent): void {
    const t = e.target as Node | null;
    if (!t || root?.contains(t) || anchor.contains(t)) return;
    onclose();
  }
  /** A scroll of anything but the pop-up itself (the tray, the page) leaves
   *  it detached from its button, so it closes. */
  function onScroll(e: Event): void {
    const t = e.target as Node | null;
    if (t && root?.contains(t)) return;
    onclose();
  }
</script>

<svelte:window onkeydown={onKeydown} onpointerdown={onPointerDown} onresize={place}
  onscrollcapture={onScroll} />

<div
  bind:this={root}
  use:portal
  class="ls-pop"
  role="dialog"
  aria-label={`Line colour and thickness — ${set.name}`}
  data-testid="line-style-panel"
  style:left="{left}px"
  style:top="{top}px"
>
  <div class="ls-head">
    <span class="ls-title">Lines</span>
    <span class="ls-set" title={set.name}>{set.name}</span>
  </div>
  <div class="ls-body">
    {#each set.colors as color, ch (ch)}
      <div class="ls-line" data-testid={`line-style-row-${ch}`}>
        <div class="ls-line-head">
          <span class="ls-sample" style:background={color} style:height="{set.widths[ch] === 'bold' ? 4 : set.widths[ch] === 'thin' ? 1.5 : 2.5}px"></span>
          <span class="ls-lab">{labelOf(ch)}</span>
          <Segmented
            options={WEIGHTS.map((w) => ({ ...w, testid: `line-weight-${ch}-${w.value}` }))}
            value={set.widths[ch]}
            onchange={(weight) => onpick(ch, { weight })}
            ariaLabel={`Thickness of ${labelOf(ch)}`}
          />
        </div>
        <div class="ls-swatches" role="group" aria-label={`Colour of ${labelOf(ch)}`}>
          {#each LINE_PALETTE as c, i (c)}
            <button
              type="button"
              class="ls-swatch"
              class:on={c === color.toLowerCase()}
              style:background={c}
              title={COLOR_NAMES[i]}
              aria-label={COLOR_NAMES[i]}
              aria-pressed={c === color.toLowerCase()}
              data-testid={`line-swatch-${ch}-${i}`}
              onclick={() => onpick(ch, { color: c })}
            ></button>
          {/each}
        </div>
      </div>
    {/each}
  </div>
  <div class="ls-foot">
    <button type="button" class="ls-btn" data-testid="line-style-reset" onclick={onreset}
      title="Give every line of this set its automatic colour and normal thickness">Reset to automatic</button>
    <button type="button" class="ls-btn primary" data-testid="line-style-done" onclick={onclose}>Done</button>
  </div>
</div>

<style>
  .ls-pop {
    position: fixed;
    z-index: 60;
    width: 268px;
    max-height: min(70vh, 520px);
    display: flex;
    flex-direction: column;
    background: var(--surface, #ffffff);
    color: var(--text);
    border: 1px solid var(--border, #e3e6eb);
    border-radius: var(--radius, 10px);
    box-shadow: var(--shadow-lg, 0 8px 28px rgba(16, 24, 40, 0.16));
    font-size: 11.5px;
  }
  .ls-head {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 9px 12px 6px;
    border-bottom: 1px solid var(--border);
  }
  .ls-title {
    font-size: 10.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
  }
  .ls-set {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 600;
  }
  .ls-body {
    overflow-y: auto;
    padding: 4px 12px;
  }
  .ls-line {
    padding: 7px 0;
  }
  .ls-line + .ls-line {
    border-top: 1px solid var(--border);
  }
  .ls-line-head {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-bottom: 6px;
  }
  .ls-sample {
    width: 18px;
    border-radius: 2px;
    flex: 0 0 auto;
  }
  .ls-lab {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--font-mono);
    font-size: 11px;
  }
  .ls-swatches {
    display: grid;
    grid-template-columns: repeat(12, 1fr);
    gap: 3px;
  }
  .ls-swatch {
    aspect-ratio: 1;
    width: 100%;
    padding: 0;
    border: 2px solid transparent;
    border-radius: 50%;
    cursor: pointer;
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.12);
  }
  .ls-swatch:hover {
    transform: scale(1.12);
  }
  .ls-swatch.on {
    outline: 2px solid var(--text);
    outline-offset: 1px;
  }
  .ls-swatch:focus-visible {
    outline: 2px solid var(--indigo);
    outline-offset: 1px;
  }
  .ls-foot {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 12px 10px;
    border-top: 1px solid var(--border);
  }
  .ls-btn {
    height: 24px;
    padding: 0 9px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--control-bg);
    color: var(--text);
    font: inherit;
    font-size: 11.5px;
    cursor: pointer;
  }
  .ls-btn:hover {
    border-color: var(--border-strong);
    background: var(--hover-bg);
  }
  .ls-btn.primary {
    border-color: var(--indigo);
    color: var(--indigo);
  }
</style>
