<script lang="ts">
  /**
   * Thin SVG plot renderer. Measures its own box with a
   * ResizeObserver, delegates ALL geometry to `buildPlot`
   * (src/lib/plot/build.ts) and renders the result verbatim — no plot
   * logic lives here. Zoom/pan interaction arrives in a later task.
   *
   * Export hooks: the root <svg> carries `data-testid="plot-svg"`,
   * each line `data-testid="plot-line"` (Playwright), the background
   * rect `data-role="plot-bg"` and every piece of axis chrome
   * `data-role="axis"` (the figure exporter restyles by these tags).
   *
   * Visual treatment ported from dev/mockups/round2-bench.html:
   * margins L58/T16/B42, R18 (56 with a right axis), #eef0f4
   * gridlines, mono tick labels and muted axis labels.
   */
  import { buildPlot, type PlotModel } from '../lib/plot/build';
  import { fmtTick } from '../lib/plot/scales';

  let { model }: { model: PlotModel } = $props();

  const uid = $props.id();
  const clipId = `plot-clip-${uid}`;

  let host: HTMLDivElement | undefined = $state();
  let svgEl: SVGSVGElement | undefined = $state();
  let width = $state(0);
  let height = $state(0);

  /** Root <svg> element, serialised by the figure exporter (Task 14). */
  export function getSvgElement(): SVGSVGElement | undefined {
    return svgEl;
  }

  $effect(() => {
    if (!host) return;
    const ro = new ResizeObserver((entries) => {
      const r = entries[entries.length - 1].contentRect;
      width = r.width;
      height = r.height;
    });
    ro.observe(host);
    return () => ro.disconnect();
  });

  // Margins from the mockup's plot engine (L=58, T=16, B=42; R widens
  // to make room for right-axis tick labels when coherence is shown).
  const ML = 58, MT = 16, MB = 42;
  const MR = $derived(model.y2Range ? 56 : 18);

  const iw = $derived(Math.max(50, width - ML - MR));
  const ih = $derived(Math.max(50, height - MT - MB));
  // squareAspect: drawing area is a centred square of side min(iw, ih).
  const side = $derived(Math.min(iw, ih));
  const pw = $derived(model.squareAspect ? side : iw);
  const ph = $derived(model.squareAspect ? side : ih);
  const ox = $derived(ML + (model.squareAspect ? (iw - side) / 2 : 0));
  const oy = $derived(MT + (model.squareAspect ? (ih - side) / 2 : 0));

  const built = $derived(width > 0 && height > 0 ? buildPlot(model, pw, ph) : null);
  const xSpan = $derived(built ? built.xDomain[1] - built.xDomain[0] : 1);
  const ySpan = $derived(built ? built.yDomain[1] - built.yDomain[0] : 1);
  const y2Span = $derived(model.y2Range ? model.y2Range[1] - model.y2Range[0] : 1);
</script>

<div class="plot-surface" bind:this={host}>
  {#if built}
    <svg
      bind:this={svgEl}
      data-testid="plot-svg"
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 {width} {height}"
    >
      <rect data-role="plot-bg" class="plot-bg" x="0" y="0" width={width} height={height} />
      <defs>
        <clipPath id={clipId}><rect x="0" y="0" width={pw} height={ph} /></clipPath>
      </defs>

      {#each built.xTicks as t (t.v)}
        <line data-role="axis" class="grid" x1={ox + t.px} y1={oy} x2={ox + t.px} y2={oy + ph} />
        <text data-role="axis" class="tick" x={ox + t.px} y={oy + ph + 15} text-anchor="middle"
          >{fmtTick(t.v, xSpan)}</text>
      {/each}
      {#each built.yTicks as t (t.v)}
        <line data-role="axis" class="grid" x1={ox} y1={oy + t.px} x2={ox + pw} y2={oy + t.px} />
        <text data-role="axis" class="tick" x={ox - 7} y={oy + t.px + 3.5} text-anchor="end"
          >{fmtTick(t.v, ySpan)}</text>
      {/each}
      {#each built.y2Ticks as t (t.v)}
        <text data-role="axis" class="tick" x={ox + pw + 7} y={oy + t.px + 3.5} text-anchor="start"
          >{fmtTick(t.v, y2Span)}</text>
      {/each}

      <rect data-role="axis" class="frame" x={ox} y={oy} width={pw} height={ph} />

      <text data-role="axis" class="axlab" x={ox + pw / 2} y={height - 6} text-anchor="middle"
        >{model.xLabel}</text>
      <text data-role="axis" class="axlab" transform="translate(14 {oy + ph / 2}) rotate(-90)"
        text-anchor="middle">{model.yLabel}</text>
      {#if model.y2Label && built.y2Ticks.length > 0}
        <text data-role="axis" class="axlab" transform="translate({width - 8} {oy + ph / 2}) rotate(90)"
          text-anchor="middle">{model.y2Label}</text>
      {/if}

      <g transform="translate({ox} {oy})">
        <g clip-path="url(#{clipId})">
          {#each built.paths as p, i (i)}
            {#if p.d}
              <path
                data-testid="plot-line"
                d={p.d}
                fill="none"
                stroke={p.color}
                stroke-width={p.width}
                opacity={p.opacity}
                stroke-dasharray={p.dashed ? '4 3' : undefined}
              />
            {/if}
          {/each}
        </g>
      </g>
    </svg>
  {/if}
</div>

<style>
  .plot-surface {
    position: relative;
    width: 100%;
    height: 100%;
    min-height: 220px;
  }
  svg {
    display: block;
    width: 100%;
    height: 100%;
  }
  .plot-bg {
    fill: var(--surface, #ffffff);
  }
  .frame {
    fill: none;
    stroke: var(--border, #e3e6eb);
  }
  .grid {
    stroke: #eef0f4;
  }
  .tick {
    fill: var(--muted, #66708a);
    font: 10.5px var(--font-mono, ui-monospace, Menlo, monospace);
  }
  .axlab {
    fill: var(--muted, #66708a);
    font-size: 11.5px;
    font-family: var(--font-body, system-ui, sans-serif);
  }
</style>
