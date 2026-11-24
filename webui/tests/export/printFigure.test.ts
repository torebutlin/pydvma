import { describe, expect, it } from 'vitest';
import { printFigureSvg, printTick, BODE_SPLIT, PANE_GAP_PT, FIGURE_ASPECTS, PRINT_TYPE, UNITS_PER_PT, type PrintFigure }
  from '../../src/lib/export/printFigure';
import { prepareSvg } from '../../src/lib/export/figure';
import { FIGURE_FONT_STACK } from '../../src/lib/export/figureFont';
import { PRINT_CHROME } from '../../src/lib/plot/chrome';
import type { PlotModel } from '../../src/lib/plot/build';

/** A TF magnitude (red, 1.5 px) with a dashed 1 px coherence line on the right axis. */
function tfModel(over: Partial<PlotModel> = {}): PlotModel {
  const x = Array.from({ length: 501 }, (_, i) => i);
  const mag = x.map((f) => -30 + 20 * Math.sin(f / 40));
  const coh = x.map((f) => 0.5 + 0.4 * Math.cos(f / 30));
  return {
    lines: [
      { x, y: mag, color: '#dc2626', opacity: 1, width: 1.5, dashed: false, yAxis: 'left', xMonotonic: true },
      { x, y: coh, color: '#dc2626', opacity: 0.75, width: 1, dashed: true, yAxis: 'right', xMonotonic: true },
    ],
    xLabel: 'Frequency (Hz)', yLabel: '|H| (V/V, dB)', y2Label: 'coherence γ²',
    xRange: [0, 500], yRange: [-72, 6], y2Range: [0, 1],
    ...over,
  };
}

/** A phase pane for a Bode figure: the same x, a phase line, no right axis. */
function phaseModel(): PlotModel {
  const x = Array.from({ length: 501 }, (_, i) => i);
  return {
    lines: [{ x, y: x.map((f) => 150 * Math.sin(f / 50)), color: '#dc2626', opacity: 1, width: 1.5, dashed: false, yAxis: 'left', xMonotonic: true }],
    xLabel: 'Frequency (Hz)', yLabel: 'Phase (deg)', xRange: [0, 500], yRange: [-180, 180],
  };
}

/** Every drawn text's box lies on the canvas. */
function inside(f: PrintFigure): void {
  for (const t of f.texts) {
    expect(t.box.x, t.text).toBeGreaterThanOrEqual(-0.01);
    expect(t.box.y, t.text).toBeGreaterThanOrEqual(-0.01);
    expect(t.box.x + t.box.w, t.text).toBeLessThanOrEqual(f.widthPt + 0.01);
    expect(t.box.y + t.box.h, t.text).toBeLessThanOrEqual(f.heightPt + 0.01);
  }
}

describe('printFigureSvg, one pane', () => {
  it('exports the pinned constants', () => {
    expect(FIGURE_ASPECTS).toEqual({ default: 16 / 9, bode: 4 / 3, nyquist: 1 });
    expect(PRINT_TYPE).toEqual({ labelPt: 10, tickPt: 9, legendPt: 9 });
    expect(UNITS_PER_PT).toBe(4);
    expect(printTick(-60, 78)).toBe('−60');
  });
  it('a default figure is 160 mm wide at 16:9 and not grown', () => {
    const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 });
    expect(f.widthPt).toBeCloseTo(453.54, 2); expect(f.heightPt).toBeCloseTo(453.54 * 9 / 16, 2);
    expect(f.grown).toBe(false); expect(f.grownFor).toEqual({ labels: false, legend: false });
    expect(f.svg).toMatch(/^<svg[^>]* width="453\.54pt" height="255\.12pt" viewBox="0 0 1814\.2 1020\.5"/);
  });
  it('Nyquist is 1:1 with a square frame', () => {
    const f = printFigureSvg({ panes: [{ model: { ...tfModel({ y2Range: undefined, y2Label: undefined }), squareAspect: true } }], kind: 'nyquist', widthMm: 90 });
    expect(f.heightPt).toBeCloseTo(f.widthPt, 2);
    expect(f.frames[0].w).toBeCloseTo(f.frames[0].h, 2);
  });
  it('type is 10 pt labels and 9 pt numbers, in the embedded face', () => {
    const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 });
    for (const t of f.svg.match(/<text[^>]*class="tick"[^>]*>/g)!) expect(t).toContain('font-size="36"');
    for (const t of f.svg.match(/<text[^>]*class="label"[^>]*>/g)!) expect(t).toContain('font-size="40"');
    expect(f.svg).toContain(`font-family="${FIGURE_FONT_STACK}"`);
  });
  it("prints buildPlot's ticks with a true minus", () => {
    const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 });
    const ticks = f.texts.filter((t) => t.role === 'tick').map((t) => t.text);
    expect(ticks).toEqual(expect.arrayContaining(['−60', '−40', '−20', '0', '100', '500', '0.5', '1']));
    expect(ticks.some((t) => t.includes('-'))).toBe(false);
  });
  it('every text sits inside the canvas, with a right axis and a last tick on the right edge', () => {
    inside(printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 }));
    inside(printFigureSvg({ panes: [{ model: tfModel({ xRange: [0, 1500], y2Range: undefined, y2Label: undefined }) }], kind: 'default', widthMm: 160 }));
  });
  it('the right-axis label reads top-to-bottom inside the canvas', () => {
    const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 });
    expect(f.svg).toMatch(/rotate\(90\)[^>]*>coherence γ²</);
    const lab = f.texts.find((t) => t.text === 'coherence γ²')!;
    expect(lab.box.x + lab.box.w).toBeLessThanOrEqual(f.widthPt);
  });
  it('a label too long for the plot grows the height, never the type', () => {
    const long = 'Power spectrum ((m/s²)², A-weighted, dB) re 1 (m/s²)² per band, averaged';
    const f = printFigureSvg({ panes: [{ model: tfModel({ yLabel: long }) }], kind: 'default', widthMm: 90 });
    expect(f.grown).toBe(true); expect(f.grownFor).toEqual({ labels: true, legend: false });
    expect(f.heightPt).toBeGreaterThan(f.widthPt * 9 / 16);
    const lab = f.texts.find((t) => t.text === long)!;
    expect(lab.box.h).toBeLessThanOrEqual(f.frames[0].h + 0.01);
    expect(f.svg).toMatch(new RegExp(`font-size="40"[^>]*>${long.replace(/[()]/g, '\\$&')}<`));
  });
  it('a 40 mm and a 300 mm figure still lay out inside their canvas', () => {
    for (const widthMm of [40, 300]) {
      const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm });
      expect(f.frames[0].w).toBeGreaterThan(0); inside(f);
    }
  });
  it("log axes print buildPlot's decade ticks, none clipped", () => {
    const f = printFigureSvg({ panes: [{ model: tfModel({ xScale: 'log', xRange: [1, 1000] }) }], kind: 'default', widthMm: 160 });
    expect(f.texts.filter((t) => t.role === 'tick').map((t) => t.text)).toEqual(expect.arrayContaining(['1', '10', '100', '1000']));
    inside(f);
  });
  it('line weights and dashes are scaled for print', () => {
    const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 });
    expect(f.svg).toMatch(/<path[^>]*stroke="#dc2626"[^>]*stroke-width="4"/);            // 1.5 px → 1 pt → 4 units
    expect(f.svg).toMatch(/<path[^>]*stroke-width="2\.7"[^>]*stroke-dasharray="9\.6 7\.2"/); // 1 px dashed
  });
  it('markers draw in the line colour, and markerOnly lines draw no stroke', () => {
    const m = tfModel({ y2Range: undefined, y2Label: undefined });
    m.lines = [{ x: [100, 200, 300], y: [-10, -20, -30], color: '#123456', opacity: 1, width: 1.4, dashed: false,
      yAxis: 'left', marker: 'o', markerOnly: true }];
    const f = printFigureSvg({ panes: [{ model: m }], kind: 'default', widthMm: 160 });
    expect(f.svg.match(/<circle[^>]*stroke="#123456"[^>]*r="10\.4"|<circle[^>]*r="10\.4"[^>]*stroke="#123456"/g)).toHaveLength(3);
    expect(f.svg).not.toMatch(/<path[^>]*stroke="#123456"/);
  });
  it('a pane image fills the data rect and replaces the gridlines', () => {
    const f = printFigureSvg({ panes: [{ model: { ...tfModel(), lines: [] }, image: 'data:image/png;base64,AAAA' }], kind: 'default', widthMm: 160 });
    const fr = f.frames[0];
    expect(f.svg).toContain(`<image x="${(fr.x * 4).toFixed(1)}" y="${(fr.y * 4).toFixed(1)}" width="${(fr.w * 4).toFixed(1)}" height="${(fr.h * 4).toFixed(1)}"`);
    expect(f.svg).toContain('xlink:href="data:image/png;base64,AAAA"');
    expect(f.svg).not.toContain('class="grid"');
  });
  it('an empty model still draws its axes', () => {
    const f = printFigureSvg({ panes: [{ model: { lines: [], xLabel: 'Time (s)', yLabel: 'Amplitude', xRange: null, yRange: null } }], kind: 'default', widthMm: 160 });
    expect(f.frames).toHaveLength(1);
  });
  it('dark and transparent restyle every print chrome hex and keep data colours', () => {
    const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 });
    const dark = prepareSvg(f.svg, 'dark');
    for (const hex of [PRINT_CHROME.ink, PRINT_CHROME.frame, PRINT_CHROME.grid])
      expect(dark).not.toMatch(new RegExp(`data-role="(axis|plot-bg)"[^>]*"${hex}"`, 'i'));
    expect(dark).toContain('stroke="#dc2626"');
    expect(prepareSvg(f.svg, 'transparent')).toMatch(/data-role="plot-bg"[^>]*fill="none"/);
  });
});

describe('printFigureSvg, Bode', () => {
  it('exports the split and gap', () => {
    expect(BODE_SPLIT).toEqual([0.6, 0.4]); expect(PANE_GAP_PT).toBe(9);
  });
  it('Bode is 4:3 with a 60/40 split and a 9 pt gap', () => {
    const f = printFigureSvg({ panes: [{ model: tfModel() }, { model: phaseModel() }], kind: 'bode', widthMm: 160 });
    expect(f.heightPt).toBeCloseTo(f.widthPt * 3 / 4, 1); expect(f.grown).toBe(false);
    expect(f.frames[0].h / f.frames[1].h).toBeCloseTo(1.5, 3);
    expect(f.frames[1].y - (f.frames[0].y + f.frames[0].h)).toBeCloseTo(9, 3);
  });
  it('Bode frames share their left and right edges', () => {
    const f = printFigureSvg({ panes: [{ model: tfModel() }, { model: phaseModel() }], kind: 'bode', widthMm: 160 });
    expect(f.frames[1].x).toBeCloseTo(f.frames[0].x, 6); expect(f.frames[1].w).toBeCloseTo(f.frames[0].w, 6);
  });
  it("Bode's top pane keeps its gridlines but prints no x numbers or x label", () => {
    const f = printFigureSvg({ panes: [{ model: tfModel() }, { model: phaseModel() }], kind: 'bode', widthMm: 160 });
    expect(f.texts.filter((t) => t.text === 'Frequency (Hz)')).toHaveLength(1);
    // x tick labels are the ones horizontally over the frame (y ticks sit left of it, y2 ticks right)
    const fr = f.frames[0];
    const xTicks = f.texts.filter((t) => t.role === 'tick' && t.box.x + t.box.w > fr.x && t.box.x < fr.x + fr.w);
    expect(xTicks.map((t) => t.text)).toEqual(['0', '100', '200', '300', '400', '500']);
    for (const t of xTicks) expect(t.box.y).toBeGreaterThan(f.frames[1].y + f.frames[1].h);
    expect((f.svg.match(/class="grid"/g) ?? []).length).toBeGreaterThan(12);
    inside(f);
  });
  it('clip ids are distinct per pane, and a pane count that does not match the kind throws', () => {
    const f = printFigureSvg({ panes: [{ model: tfModel() }, { model: phaseModel() }], kind: 'bode', widthMm: 160 });
    expect(f.svg).toContain('id="pf-clip-0"'); expect(f.svg).toContain('id="pf-clip-1"');
    expect(() => printFigureSvg({ panes: [{ model: tfModel() }], kind: 'bode', widthMm: 160 })).toThrow(/bode/);
    expect(() => printFigureSvg({ panes: [{ model: tfModel() }, { model: phaseModel() }], kind: 'default', widthMm: 160 })).toThrow(/one pane/);
  });
  it('a long label grows the Bode height per pane share', () => {
    const long = 'Phase of the transfer function between the two measured channels (deg), unwrapped';
    const f = printFigureSvg({ panes: [{ model: tfModel() }, { model: { ...phaseModel(), yLabel: long } }], kind: 'bode', widthMm: 90 });
    expect(f.grown).toBe(true);
    expect(f.frames[0].h / f.frames[1].h).toBeCloseTo(1.5, 3);
    inside(f);
  });
});

describe('printFigureSvg, data line joins', () => {
  it('data lines end with a round linejoin, markers do not', () => {
    const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 });
    expect(f.svg).toMatch(/<path d="[^"]*" fill="none" stroke="#dc2626" stroke-width="4" opacity="1" stroke-linejoin="round"\/>/);
    expect(f.svg).toMatch(/stroke-dasharray="9\.6 7\.2" stroke-linejoin="round"\/>/);
    const m = tfModel({ y2Range: undefined, y2Label: undefined });
    m.lines = [{ x: [100, 200], y: [-10, -20], color: '#123456', opacity: 1, width: 1.4, dashed: false, yAxis: 'left', marker: 'x', markerOnly: true }];
    expect(printFigureSvg({ panes: [{ model: m }], kind: 'default', widthMm: 160 }).svg).not.toContain('linejoin');
  });
});

describe('printFigureSvg, legend', () => {
  it('a legend below the axes grows the figure and stays on the canvas', () => {
    const entries = Array.from({ length: 30 }, (_, i) => ({ label: `mode ${i}, Qn = 100`, color: '#2563eb', style: 'xline' as const, faded: false }));
    const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 90, legend: { entries, placement: { kind: 'best' } } });
    expect(f.legendBox!.below).toBe(true); expect(f.grown).toBe(true); inside(f);
    expect(f.grownFor).toEqual({ labels: false, legend: true });
    expect(f.legendBox!.y + f.legendBox!.h).toBeLessThanOrEqual(f.heightPt + 0.01);
  });
  it('a long label and a legend below the axes set both reasons', () => {
    const long = 'Power spectrum ((m/s²)², A-weighted, dB) re 1 (m/s²)² per band, averaged';
    const entries = Array.from({ length: 30 }, (_, i) => ({ label: `mode ${i}, Qn = 100`, color: '#2563eb', style: 'xline' as const, faded: false }));
    const f = printFigureSvg({ panes: [{ model: tfModel({ yLabel: long }) }], kind: 'default', widthMm: 90, legend: { entries, placement: { kind: 'best' } } });
    expect(f.grownFor).toEqual({ labels: true, legend: true }); expect(f.grown).toBe(true);
  });
  it('the Bode legend sits in the magnitude pane', () => {
    const f = printFigureSvg({ panes: [{ model: tfModel() }, { model: phaseModel() }], kind: 'bode', widthMm: 160,
      legend: { entries: [{ label: 'a', color: '#dc2626', style: 'line', faded: false }], placement: { kind: 'position', x: 0.98, y: 0.98 } } });
    expect(f.legendBox!.y + f.legendBox!.h).toBeLessThanOrEqual(f.frames[0].y + f.frames[0].h);
  });
  it('a legend card lists its texts, keeps the aspect, and is drawn last', () => {
    const f = printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160,
      legend: { entries: [{ label: 'noise · ch_1/ch_0', color: '#dc2626', style: 'line', faded: false }], placement: { kind: 'position', x: 0.98, y: 0.98 } } });
    expect(f.grown).toBe(false); expect(f.heightPt).toBeCloseTo(f.widthPt * 9 / 16, 6);
    expect(f.texts.filter((t) => t.role === 'legend').map((t) => t.text)).toEqual(['noise · ch_1/ch_0']);
    expect(f.legendBox!.below).toBe(false);
    expect(f.svg.lastIndexOf('class="legend"')).toBeGreaterThan(f.svg.lastIndexOf('class="frame"'));
    expect(printFigureSvg({ panes: [{ model: tfModel() }], kind: 'default', widthMm: 160 }).legendBox).toBeNull();
  });
  it("'best' avoids the corner the data runs through", () => {
    // A line along the bottom-right: se and sw are covered, the top corners are empty.
    const m = tfModel({ y2Range: undefined, y2Label: undefined });
    const x = Array.from({ length: 501 }, (_, i) => i);
    m.lines = [{ x, y: x.map(() => -65), color: '#dc2626', opacity: 1, width: 1.5, dashed: false, yAxis: 'left', xMonotonic: true }];
    const f = printFigureSvg({ panes: [{ model: m }], kind: 'default', widthMm: 160,
      legend: { entries: [{ label: 'a', color: '#dc2626', style: 'line', faded: false }], placement: { kind: 'best' } } });
    const fr = f.frames[0];
    expect(f.legendBox!.below).toBe(false);
    expect(f.legendBox!.y).toBeLessThan(fr.y + fr.h / 2);           // ne, the first empty corner
    expect(f.legendBox!.x).toBeGreaterThan(fr.x + fr.w / 2);
  });
});
