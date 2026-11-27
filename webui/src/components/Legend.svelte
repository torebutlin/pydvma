<script lang="ts">
  /**
   * Draggable plot legend (design spec §6). An absolutely-positioned
   * card floating over the plot, mounted inside the plot host next to
   * `PlotSurface` / `ZoomToolbar`.
   *
   * Wiring contract (documented design choice): like `ZoomToolbar`,
   * this takes the WHOLE `selection` and `viewState` store objects
   * rather than narrow callbacks. It reads `selection.legendRows` (a
   * derived store that lists EVERY line, off ones included, each tagged
   * with its tri-state), mirrors the data-tray's tri-state by calling
   * `selection.clickLine` / `dblclickLine`, and persists placement via
   * `viewState.setLegend(active, …)` while reading the current legend
   * slice from `viewState.current`. Callbacks would just re-implement
   * this surface, and the stores' identities are stable for the
   * component's lifetime (created once at app startup).
   *
   * Placement is FRACTIONAL (`legend.x` / `legend.y`, spec convention, see
   * `lib/plot/legendPos`) ACROSS THE AXES FRAME, as in the printed figure:
   * nominally in `[0, 1]`, but the `outside-right` preset stores
   * `x = 1.02` and a drag over the plot's margins stores values a little
   * below 0 or past 1. The card sits in a box laid at PlotSurface's `frame`
   * insets (`legend-frame`, pointer-events none so the plot underneath
   * still takes gestures), which is the card's offsetParent, so every
   * fraction, measure and drag below resolves against the frame. The card
   * anchors to the right edge when `x > 0.5` and to the bottom when
   * `y > 0.5` so a corner preset pins the nearest corner of the card to
   * that corner of the axes (matplotlib feel). The whole card is hidden
   * when `legend.visible === false`.
   *
   * TWO DISPLAY MODES (post-release feedback: "many lines" legends):
   *
   * - FULL (default): one labelled row per line, mirroring the tray —
   *   a colour swatch + label per entry; a `fade` entry renders the
   *   whole row at 40% opacity, an `off` entry is dimmed and
   *   struck-through (still listed, so it can be re-enabled). With
   *   more than 10 entries the rows wrap automatically into 2 (>10)
   *   or 3 (>20) balanced columns (`legendWrapColumns`), reading
   *   top-to-bottom then across, so late-listed modal-fit rows flow
   *   into the later column; the card widens from its single-column
   *   46% cap to 60%/72% to make room. One column behaves exactly
   *   like the classic legend.
   *
   * - COMPACT: a dot grid — one ~11 px coloured dot per line, one
   *   grid ROW per set and one COLUMN per channel (`legendGrid`), so
   *   fit pseudo-sets form their own trailing row(s). Off lines are
   *   hollow + faded, fade lines 40% opacity; each dot's tooltip is
   *   the full row label. Toggled by a small corner button (shown on
   *   card hover, title "Compact legend") and persisted per view via
   *   `legend.compact` in the viewState legend slice.
   *
   * Clicking a row OR a dot cycles that line (on → fade → off → on);
   * double-clicking shows or hides it outright, judged from its state
   * before the first click (`selection.clickLine` / `dblclickLine`), so
   * lines can be flashed on and off without passing through fade. The
   * store update flows back through `legendRows` and re-renders in place.
   *
   * Free drag: pointer-drag the card → `clampLegend(newFractionalPos, the
   * host's bounds as frame fractions)` → `setLegend(active, { …legend, x, y,
   * preset: null })`. Dragging ALWAYS clears the preset and NEVER snaps
   * (spec §6). Moves update
   * live (legend position is not history-tracked) but are rAF-coalesced
   * for smoothness. On pointerup the card commits WHERE IT SITS, as the
   * fraction of its nearer edges (`settledPos`), so the anchor flip below
   * leaves it in place instead of moving it by its own size.
   *
   * NEVER OUTGROWS THE PLOT (4C6 lab, 2026-11: a file with 23 sets and
   * their fit pseudo-sets gave ~69 rows, and in a short plot the card grew
   * up past the plot over the frequency navigator and hid its controls;
   * the zoom toolbar's strip stacks above it). The card is a flex column
   * capped at the axes frame's height less 2 × INSET (its offsetParent);
   * its rows or dots scroll inside it, the list taking touch pans only
   * when it actually scrolls. Its measured size clamps its placement (CSS
   * `clamp()` against the frame box's own %, the size re-measured by a
   * ResizeObserver on the card, its list and the frame box), so a plot
   * resize, more lines or a mode switch pull it back into view. WHERE it is
   * clamped depends on where the position came from (publication figures,
   * 2026-11-24: the SE preset used to sit on the corner tick labels):
   * - a PRESET (`legend.preset` set, the default `se` included) stays inside
   *   the axes frame, INSET px clear of its edges, so it never covers a tick
   *   label; `outside-right` may overhang the frame's right edge by up to
   *   RIGHT_SLACK (5 %, `clampLegend`'s slack) but stays inside the plot;
   * - a DRAGGED position (`preset === null`) may sit over the margins but
   *   stays inside the whole plot host, DRAG_INSET px clear of its edges.
   * The fraction stored in viewState is left as placed: the clamp is
   * visual, so growing the plot back restores it.
   */
  import type { LegendEntry, Selection } from '../lib/stores/selection';
  import { LINE_WEIGHT_PX } from '../lib/stores/selection';
  import type { ViewState } from '../lib/stores/viewstate';
  import { clampLegend, type FrameInsets } from '../lib/plot/legendPos';
  import { legendGrid, legendWrapColumns } from '../lib/plot/legendGrid';
  import { get, type Readable } from 'svelte/store';
  import { flushSync } from 'svelte';

  let {
    selection,
    viewState,
    entriesOverride,
    frame,
  }: {
    selection: Selection;
    viewState: ViewState;
    /**
     * Optional view-aware entry list (Task R4). When present the legend
     * renders THESE rows instead of `selection.legendRows` — the TF view
     * passes its out/in-labelled, input-dropped entries so the legend
     * matches exactly what the plot draws. Clicking a row still cycles the
     * underlying (setId, ch) line, so the tri-state behaviour is
     * unchanged. Omitted (undefined) → the off-inclusive legend rows.
     */
    entriesOverride?: Readable<LegendEntry[]> | undefined;
    /**
     * Where the axes frame sits in the plot host (PlotSurface's bound
     * `frame`, px from the host's edges). PlotSurface measures it against
     * its parent element, and this legend is mounted in that same element,
     * which is the frame box's offsetParent: the box is laid at these
     * insets there, so the card's fractions and presets refer to the
     * frame's visible part. Omitted → all zero: the box is the whole host.
     */
    frame?: FrameInsets;
  } = $props();

  const NO_FRAME: FrameInsets = { left: 0, top: 0, right: 0, bottom: 0 };
  /** The frame insets in use (absent → the whole host). */
  const fr = $derived(frame ?? NO_FRAME);

  // Derived (not destructured) so the component tracks reassigned props.
  // An override store wins; otherwise the off-inclusive per-channel rows
  // (off lines stay listed, struck-through, so they can be re-enabled).
  const entries = $derived(entriesOverride ?? selection.legendRows);
  const current = $derived(viewState.current);

  const legend = $derived($current.legend);

  // Full mode: automatic column wrapping past 10 entries (see the
  // header comment). `wrapRows` balances the columns; the card's
  // max-width widens with the column count (single column keeps the
  // stylesheet's 46% via `undefined`, i.e. no inline override).
  const wrapCols = $derived(legendWrapColumns($entries.length));
  const wrapRows = $derived(Math.max(1, Math.ceil($entries.length / wrapCols)));
  const cardMaxWidth = $derived(
    legend.compact || wrapCols === 1 ? undefined : wrapCols === 2 ? '60%' : '72%');

  // Compact mode: the set-rows × channel-columns dot grid.
  const grid = $derived(legendGrid($entries));

  /** Toggle compact (dot-grid) mode, persisted per view like placement. */
  function toggleCompact() {
    if (justDragged) return;   // a drag that ended on the button is not a click
    viewState.setLegend(get(viewState.active), { ...legend, compact: !legend.compact });
  }

  // The card's own measured box, so anchoring pins the correct edge.
  let card: HTMLDivElement | undefined = $state();

  /**
   * CSS placement for the card. Fractional x/y position the anchor
   * point inside the host.
   *
   * For PRESET / committed (non-drag) placement: when x>0.5 we anchor
   * the card's RIGHT edge (so it grows leftward and its right corner
   * tracks the point) and when y>0.5 its BOTTOM edge — this keeps
   * corner presets (NE, SE, outside-right, …) flush to the matching
   * plot corner rather than overflowing it.
   *
   * WHILE DRAGGING, however, `legend.x`/`legend.y` ARE the card's
   * top-left fraction (that is what `commit` writes from the pointer),
   * so we must ALWAYS left/top-anchor during a drag. Applying the
   * edge-flip mid-drag would reinterpret the same x as a right-edge
   * offset the instant the left edge crossed 0.5, snapping the card
   * left by ~its own width under the cursor. So the flip is gated on
   * `!dragging`. (Drag/click/anchor behaviours are e2e-covered in
   * Task 9 Playwright.)
   */
  const placement = $derived.by(() => {
    const anchorRight = !dragging && legend.x > 0.5;
    const anchorBottom = !dragging && legend.y > 0.5;
    return {
      left: anchorRight ? 'auto' : offset('left', legend.x, cardW),
      right: anchorRight ? offset('right', 1 - legend.x, cardW) : 'auto',
      top: anchorBottom ? 'auto' : offset('top', legend.y, cardH),
      bottom: anchorBottom ? offset('bottom', 1 - legend.y, cardH) : 'auto',
    };
  });

  const OPPOSITE = { left: 'right', right: 'left', top: 'bottom', bottom: 'top' } as const;

  /**
   * One CSS offset for the card's `side` edge: the fraction `pct` of the
   * frame box, clamped so the card's MEASURED `size` stays inside its bounds
   * (see the header), between `lo` and `hi` (`max()` keeps `hi` at or above
   * `lo`; the max-height/max-width caps make the card fit anyway).
   * - A preset: inside the frame box, INSET px clear (`lo` = INSET,
   *   `hi` = 100% − size − INSET); `outside-right`'s right edge may go up to
   *   RIGHT_SLACK past the frame's right edge, but not past the host's.
   * - A dragged position (or a drag in progress): inside the whole host,
   *   DRAG_INSET px clear. In the frame box's coordinates the host's edge on
   *   `side` is `−fr[side]` px away and the far one `100% + fr[opposite]`.
   * The card's width is max-content (see .legend), so an overhang past the
   * frame box never narrows it, which would move the bound, and so on.
   */
  function offset(side: keyof typeof OPPOSITE, pct: number, size: number): string {
    let lo: string, hi: string;
    if (!legend.preset || dragging) {
      lo = `${DRAG_INSET - fr[side]}px`;
      hi = `calc(100% + ${fr[OPPOSITE[side]] - size - DRAG_INSET}px)`;
    } else {
      lo = side === 'right' && legend.preset === 'outside-right'
        ? `max(${-RIGHT_SLACK * 100}%, ${DRAG_INSET - fr.right}px)` : `${INSET}px`;
      hi = `calc(100% - ${size + INSET}px)`;
    }
    return `clamp(${lo}, ${pct * 100}%, max(${lo}, ${hi}))`;
  }

  /** How far past the frame's right edge the outside-right preset may sit
   *  (fraction of the frame width): `clampLegend`'s slack. */
  const RIGHT_SLACK = 0.05;
  /** A preset's gap to the axes frame's edges, px: keep in lockstep with
   *  the .legend max-height. Presets (2 %) sit further in on frames over
   *  400 px. */
  const INSET = 8;
  /** A dragged card's gap to the plot host's edges, px. */
  const DRAG_INSET = 4;

  // ---- In-plot cap and clamp (see the header) ----
  let bodyEl: HTMLDivElement | undefined = $state();
  let listEl: HTMLDivElement | undefined = $state();
  /** The card's measured border box, for the placement clamp. */
  let cardW = $state(0);
  let cardH = $state(0);
  /** The capped card's list overflows: it scrolls, and takes touch pans. */
  let scrolls = $state(false);

  /** Re-measure the card (sub-pixel: it carries no transform) and whether
   *  its list scrolls. */
  function measure() {
    if (!card) return;
    const r = card.getBoundingClientRect();
    if (r.width !== cardW) cardW = r.width;
    if (r.height !== cardH) cardH = r.height;
    scrolls = !!bodyEl && bodyEl.scrollHeight > bodyEl.clientHeight + 1;
  }

  // Re-measure whenever the card, its list or the plot changes size: lines
  // coming and going, compact ↔ full, a plot resize. The list is observed
  // as well as the card because a capped card keeps its size while its
  // list grows underneath; the host because a resize that leaves the card
  // its size still changes whether the list fits.
  $effect(() => {
    const el = card;
    if (!el) return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    if (listEl) ro.observe(listEl);
    if (el.offsetParent) ro.observe(el.offsetParent);
    return () => ro.disconnect();
  });

  /**
   * The card's committed position as it sits now: per axis, the fraction of
   * its LEFT/TOP edge when its centre is in the first half of the plot, else
   * of its RIGHT/BOTTOM edge. That is the edge `placement` anchors for that
   * fraction (x > 0.5 → right), so committing it leaves the card in place.
   */
  function settledPos(): { x: number; y: number } | null {
    const host = hostOf();
    if (!card || !host) return null;
    // Rects, not the integer offset* values, so the card lands to the
    // sub-pixel. The host's padding box is what the % offsets resolve on.
    const hr = host.getBoundingClientRect();
    const cr = card.getBoundingClientRect();
    const W = hr.width - (host.offsetWidth - host.clientWidth);
    const H = hr.height - (host.offsetHeight - host.clientHeight);
    if (W <= 0 || H <= 0) return null;
    const l = cr.left - hr.left - host.clientLeft, t = cr.top - hr.top - host.clientTop;
    const w = cr.width, h = cr.height;
    return {
      x: l + w / 2 > W / 2 ? (l + w) / W : l / W,
      y: t + h / 2 > H / 2 ? (t + h) / H : t / H,
    };
  }

  /** Whether a press is on the scrolling list's scrollbar (the list itself,
   *  not a row, in its right gutter), which must scroll, not drag. */
  function onScrollbar(e: PointerEvent): boolean {
    if (!scrolls || !bodyEl || e.target !== bodyEl) return false;
    const r = bodyEl.getBoundingClientRect();
    const bar = Math.max(bodyEl.offsetWidth - bodyEl.clientWidth, 12);
    return e.clientX >= r.right - bar;
  }

  // ---- Free drag (pointer capture + rAF coalescing) ----
  //
  // A pointerdown only ARMS a potential drag; we defer pointer capture
  // (and the `dragging` state) until the pointer actually moves past a
  // few pixels. That keeps a plain tap/click on a row from being
  // captured by the card — capture would retarget the pointer sequence
  // and swallow the button's native `click`, breaking the tri-state
  // cycle. So: small movement = click the row; real movement = drag.

  /** Pixels of pointer travel before an armed press becomes a drag. */
  const DRAG_THRESHOLD_PX = 3;

  let armed = false;                 // pointerdown seen, not yet a drag
  let dragging = $state(false);      // a real drag is in progress
  // Set the instant a press promotes to a drag; cleared on the next
  // microtask after pointerup. The row's onclick early-returns while
  // it is set, so a drag that STARTED on a row never spurious-cycles
  // that row on release (belt-and-braces alongside pointer capture,
  // which already retargets the synthetic click away from the row).
  let justDragged = false;
  let activePointer = 0;
  let downClientX = 0, downClientY = 0;  // pointerdown origin (client px)
  // Pointer→fraction needs the host rect; capture it at pointerdown.
  let hostRect: DOMRect | null = null;
  // Offset from the pointer to the card's top-left, in host fractions,
  // so the card doesn't jump under the cursor when the drag begins.
  let grabFx = 0, grabFy = 0;
  let rafId = 0;
  let pendingPos: { x: number; y: number } | null = null;

  /** Host element = the card's positioned ancestor: the frame box (the
   *  axes frame inside the plot host). */
  function hostOf(): HTMLElement | null {
    return card?.offsetParent as HTMLElement | null;
  }

  /** Commit a fractional position, clearing any preset. It is clamped to the
   *  whole plot host (the frame plus its margins, as fractions of the frame);
   *  the px-exact clamp is `offset`'s. */
  function commit(pos: { x: number; y: number }) {
    const r = hostRect ?? hostOf()?.getBoundingClientRect();
    const W = r && r.width > 0 ? r.width : 1, H = r && r.height > 0 ? r.height : 1;
    const c = clampLegend(pos, {
      x: [-fr.left / W, 1 + fr.right / W],
      y: [-fr.top / H, 1 + fr.bottom / H],
    });
    viewState.setLegend(get(viewState.active), { ...legend, x: c.x, y: c.y, preset: null });
  }

  function onPointerDown(e: PointerEvent) {
    if (e.button !== 0 || !card || onScrollbar(e)) return;
    const host = hostOf();
    if (!host) return;
    hostRect = host.getBoundingClientRect();
    if (hostRect.width === 0 || hostRect.height === 0) return;
    // ARM only — no capture yet, so a plain click still reaches the row.
    armed = true;
    activePointer = e.pointerId;
    downClientX = e.clientX; downClientY = e.clientY;
    // Fraction of the pointer within the host, and the card's current
    // top-left as a fraction, so we can keep the grab offset constant.
    const cardRect = card.getBoundingClientRect();
    const px = (e.clientX - hostRect.left) / hostRect.width;
    const py = (e.clientY - hostRect.top) / hostRect.height;
    grabFx = px - (cardRect.left - hostRect.left) / hostRect.width;
    grabFy = py - (cardRect.top - hostRect.top) / hostRect.height;
  }

  function onPointerMove(e: PointerEvent) {
    if ((!armed && !dragging) || e.pointerId !== activePointer || !hostRect) return;
    // Safety: if we're still only ARMED (not yet captured) and the primary
    // button is no longer held, the pointerup happened off-card before the
    // drag threshold and we never saw it — so `armed` is stale. Clear it and
    // bail, otherwise a later hover-move would spuriously promote to a drag
    // ("the legend picks itself up without a click").
    if (!dragging && (e.buttons & 1) === 0) { armed = false; return; }
    // Promote an armed press to a drag once it travels past the threshold.
    if (!dragging) {
      const moved = Math.hypot(e.clientX - downClientX, e.clientY - downClientY);
      if (moved < DRAG_THRESHOLD_PX) return;
      dragging = true;
      justDragged = true;                        // suppress the release-click on a row
      card?.setPointerCapture(e.pointerId);
    }
    const px = (e.clientX - hostRect.left) / hostRect.width;
    const py = (e.clientY - hostRect.top) / hostRect.height;
    // Position is the card's top-left; subtract the grab offset.
    pendingPos = { x: px - grabFx, y: py - grabFy };
    if (!rafId) {
      rafId = requestAnimationFrame(() => {
        rafId = 0;
        if (pendingPos) commit(pendingPos);
      });
    }
  }

  /** Release capture, cancel any pending rAF, and reset drag state. */
  function endGesture(pointerId: number) {
    try { card?.releasePointerCapture(pointerId); } catch { /* already released */ }
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
    armed = false;
    dragging = false;
    pendingPos = null;
    hostRect = null;
    // Clear the release-click guard AFTER this event loop tick, so the
    // click synthesised by the browser right after pointerup (which is
    // what would spurious-cycle a row) still sees justDragged === true.
    if (justDragged) queueMicrotask(() => { justDragged = false; });
  }

  function onPointerUp(e: PointerEvent) {
    if (e.pointerId !== activePointer) return;
    // A press that never crossed the threshold was a click: let the
    // row button's own onclick fire; we do nothing but disarm.
    if (dragging) {
      // Apply the last move, then commit where the (clamped) card sits as
      // the fraction of its nearer edges, so ending the drag (which turns
      // the anchor flip back on) does not move it.
      if (pendingPos) commit(pendingPos);
      flushSync();
      const settled = settledPos();
      if (settled) commit(settled);
    }
    endGesture(e.pointerId);
  }

  /** Aborted gesture (e.g. touch cancelled by the OS): reset, no commit. */
  function onPointerCancel(e: PointerEvent) {
    if (e.pointerId !== activePointer) return;
    endGesture(e.pointerId);
  }

  // Cancel any pending rAF if the component unmounts mid-drag.
  $effect(() => () => { if (rafId) cancelAnimationFrame(rafId); });
</script>

{#if legend.visible}
  <!-- The frame box: laid at the axes frame's insets, it is the card's
       offsetParent, so the card's fractions and clamps refer to the frame.
       It takes no pointer events, so the plot underneath keeps its
       gestures; the card takes them back. -->
  <div
    class="legend-frame"
    data-testid="legend-frame"
    style:left={`${fr.left}px`}
    style:top={`${fr.top}px`}
    style:right={`${fr.right}px`}
    style:bottom={`${fr.bottom}px`}
  >
    <div
      bind:this={card}
      class="legend"
      class:dragging
      class:compact={legend.compact}
      class:scrolls
      data-testid="legend"
      style:left={placement.left}
      style:right={placement.right}
      style:top={placement.top}
      style:bottom={placement.bottom}
      style:max-width={cardMaxWidth}
      role="group"
      aria-label="Plot legend — drag to reposition"
      onpointerdown={onPointerDown}
      onpointermove={onPointerMove}
      onpointerup={onPointerUp}
      onpointercancel={onPointerCancel}
    >
      <!-- Mode toggle: hover-revealed corner button; absolute, so it sits
           outside the row/dot flow. `pointer-events` gates with opacity so
           the invisible button never swallows a click meant for a row. -->
      <button
        type="button"
        class="mode-toggle"
        data-testid="legend-compact-toggle"
        title="Compact legend"
        aria-pressed={legend.compact}
        onclick={toggleCompact}
      >
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <circle cx="3" cy="3" r="1.6" fill="currentColor" />
          <circle cx="7" cy="3" r="1.6" fill="currentColor" />
          <circle cx="3" cy="7" r="1.6" fill="currentColor" />
          <circle cx="7" cy="7" r="1.6" fill="currentColor" />
        </svg>
      </button>
      <!-- The list scrolls inside the capped card (see the header). -->
      <div class="legend-body" class:scrolls bind:this={bodyEl} data-testid="legend-body">
      {#if legend.compact}
        <!-- Compact: one dot per line; row = set, column = channel. -->
        <div
          bind:this={listEl}
          class="dots"
          data-testid="legend-dots"
          style:grid-template-rows={`repeat(${Math.max(1, grid.nRows)}, auto)`}
          style:grid-template-columns={`repeat(${Math.max(1, grid.nCols)}, auto)`}
        >
          {#each grid.cells as c (`${c.setId}:${c.ch}`)}
            <button
              type="button"
              class="dot"
              class:fade={c.state === 'fade'}
              class:off={c.state === 'off'}
              style:grid-row={c.row + 1}
              style:grid-column={c.col + 1}
              data-testid="legend-dot"
              title={c.label}
              aria-label={c.label}
              onclick={(ev) => { if (!justDragged) selection.clickLine(c.setId, c.ch, ev.detail); }}
              ondblclick={() => { if (!justDragged) selection.dblclickLine(c.setId, c.ch); }}
            >
              <span
                class="dot-fill"
                style:border-color={c.color}
                style:background={c.state === 'off' ? 'transparent' : c.color}
              ></span>
            </button>
          {/each}
        </div>
      {:else}
        <!-- Full: labelled rows; >10 entries wrap into balanced columns
             reading top-to-bottom then across (grid-auto-flow: column). -->
        <div
          bind:this={listEl}
          class="rows"
          class:multi={wrapCols > 1}
          style:grid-template-rows={wrapCols > 1 ? `repeat(${wrapRows}, auto)` : undefined}
        >
          {#each $entries as e (`${e.setId}:${e.ch}`)}
            <button
              type="button"
              class="row"
              class:fade={e.state === 'fade'}
              class:off={e.state === 'off'}
              data-testid="legend-entry"
              title="Click: on → fade → off. Double-click: show / hide"
              onclick={(ev) => { if (!justDragged) selection.clickLine(e.setId, e.ch, ev.detail); }}
              ondblclick={() => { if (!justDragged) selection.dblclickLine(e.setId, e.ch); }}
            >
              <!-- The key line follows the line's weight (2 × its px: normal 3 px). -->
              <span class="swatch" style:background={e.color}
                style:height="{2 * LINE_WEIGHT_PX[e.weight ?? 'normal']}px"></span>
              <span class="label">{e.label}</span>
            </button>
          {/each}
        </div>
      {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  /* The axes frame's box (see the template); positioned inline. */
  .legend-frame {
    position: absolute;
    pointer-events: none;
  }
  .legend {
    position: absolute;
    z-index: 5;
    pointer-events: auto;
    /* Its own content's width, capped by max-width, NOT shrink-to-fit: a
       dragged card may overhang the frame box into the plot's margins, and
       a shrink-to-fit width would narrow as it did (see `offset`). */
    width: max-content;
    max-width: 46%;
    /* Never taller than the axes frame (its offsetParent), 8 px (INSET)
       clear of each edge: the rows scroll in .legend-body instead (see the
       header). */
    max-height: calc(100% - 16px);
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: 6px 8px;
    background: var(--overlay-bg);
    border: 1px solid var(--border, #e3e6eb);
    border-radius: 8px;
    box-shadow: var(--shadow, 0 1px 3px rgba(16, 24, 40, 0.12));
    cursor: grab;
    touch-action: none;
    user-select: none;
  }
  .legend.dragging {
    cursor: grabbing;
    box-shadow: 0 6px 20px rgba(16, 24, 40, 0.22);
  }
  /* Compact cards are small; reserve a right gutter so the corner
     toggle never covers the first row's last dot. A scrolling list gets
     the same gutter, so the toggle never covers its scrollbar. */
  .legend.compact,
  .legend.scrolls {
    padding-right: 24px;
  }
  /* The entry list: it fills the capped card and scrolls when the entries
     do not fit. A touch pan scrolls it only when it scrolls: otherwise a
     touch drag anywhere on the card moves the card (the card's own
     touch-action stops at this scroll container, hence the explicit none). */
  .legend-body {
    flex: 1 1 auto;
    min-height: 0;
    overflow-x: hidden;
    overflow-y: auto;
    overscroll-behavior: contain;
    touch-action: none;
  }
  .legend-body.scrolls {
    touch-action: pan-y;
  }
  /* Hover-revealed mode toggle pinned to the card's top-right corner.
     `pointer-events: none` while hidden so it can never intercept a
     click aimed at the row beneath it. */
  .mode-toggle {
    position: absolute;
    top: 3px;
    right: 3px;
    width: 16px;
    height: 16px;
    padding: 0;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--muted, #6b7280);
    cursor: pointer;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.12s ease;
  }
  .legend:hover .mode-toggle,
  .mode-toggle:focus-visible {
    opacity: 1;
    pointer-events: auto;
  }
  .mode-toggle:hover {
    background: var(--hover-bg);
    color: var(--text, #1b2437);
  }
  .mode-toggle[aria-pressed='true'] {
    color: var(--text, #1b2437);
  }
  /* Full-mode row list. Single column by default — identical to the
     classic legend. `.multi` (>10 entries) switches to a grid flowing
     top-to-bottom then across; equal minmax(0,1fr) columns keep the
     nowrap labels ellipsizing instead of blowing past max-width. */
  .rows {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }
  .rows.multi {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: minmax(0, 1fr);
    column-gap: 12px;
    row-gap: 1px;
  }
  /* Compact mode: the set-rows × channel-columns dot grid. */
  .dots {
    display: grid;
    gap: 3px;
    padding: 1px;
  }
  .dot {
    width: 16px;
    height: 16px;
    padding: 0;
    display: grid;
    place-items: center;
    border: none;
    border-radius: 50%;
    background: transparent;
    cursor: pointer;
  }
  .dot:hover {
    background: var(--hover-bg);
  }
  .dot-fill {
    width: 11px;
    height: 11px;
    box-sizing: border-box;
    border-radius: 50%;
    border: 2px solid;   /* border-color = the line colour (inline) */
  }
  .dot.fade .dot-fill {
    opacity: 0.4;
  }
  /* Off dots are hollow (transparent fill set inline) AND faded. */
  .dot.off .dot-fill {
    opacity: 0.35;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 7px;
    border: none;
    background: transparent;
    border-radius: 4px;
    padding: 2px 4px;
    cursor: pointer;
    text-align: left;
    color: var(--text, #1b2437);
    font: 500 11.5px var(--font-body, system-ui, sans-serif);
  }
  .row:hover {
    background: var(--hover-bg);
  }
  .row.fade {
    opacity: 0.4;
  }
  /* Off lines stay listed but read as "disabled": dimmed row, faded
     swatch and a struck-through label (mirrors the tray's off style). */
  .row.off {
    opacity: 0.5;
  }
  .row.off .swatch {
    opacity: 0.25;
  }
  .row.off .label {
    text-decoration: line-through;
    color: var(--muted, #6b7280);
  }
  .swatch {
    flex: 0 0 auto;
    width: 14px;
    height: 3px;
    border-radius: 2px;
  }
  .label {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
