"""Mockup round 2: one figure per figure type, each at its proposed aspect.

Throwaway, like make_mockup.py. Lays every figure type the web app can save
(time, spectrum, TF magnitude + coherence, TF phase, Bode, Nyquist,
sonogram) out in POINTS at a printed width, in STIX Two Text (10 pt labels,
9 pt numbers and legend), measuring text with the font's own advance widths
so margins fit the labels, and growing the height only when a rotated y label
would not fit the plot. Writes aspects.html; print it with print.cjs's twin.

    python dev/mockups/2026-11-24-publication-figure/make_aspects.py <file.dvma>
"""
import base64
import html
import io
import math
import sys
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from scipy import signal

import pydvma as dvma

OUT = Path(__file__).parent
MM = 72 / 25.4
FONT = 'STIX Two Text'
FONT_PATH = '/System/Library/Fonts/Supplemental/STIXTwoText.ttf'
LAB, TICK, LEG = 10.0, 9.0, 9.0
INK, FRAME, GRID, CARD = '#1d2027', '#3f4652', '#dfe2e7', '#c5cad3'
BLUE, RED = '#2563eb', '#dc2626'

_tt = TTFont(FONT_PATH)
_cmap, _hmtx, _upm = _tt.getBestCmap(), _tt['hmtx'], _tt['head'].unitsPerEm


def tw(s, size):
    """Advance width of `s` in pt at `size` pt (STIX Two Text Regular)."""
    w = 0
    for ch in s:
        g = _cmap.get(ord(ch))
        w += _hmtx[g][0] if g else 0.5 * _upm
    return w / _upm * size


def nice_ticks(lo, hi, target=6):
    """The app's niceTicks (scales.ts)."""
    span = hi - lo
    step0 = span / target
    mag = 10 ** math.floor(math.log10(step0))
    n = step0 / mag
    step = (1 if n <= 1 else 2 if n <= 2 else 5 if n <= 5 else 10) * mag
    v, out = math.ceil(lo / step) * step, []
    while v <= hi + step * 1e-9:
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        v += step
    return out


def fmt(v, span):
    d = max(0, min(8, 2 - math.floor(math.log10(span))))
    s = f'{round(v, d):.{d}f}'.rstrip('0').rstrip('.') if d else f'{v:.0f}'
    return s.replace('-', '−')


def esc(s):
    return html.escape(s, quote=False)


class Pane:
    """One axes: lines (x, y, colour, px width, dashed, opacity, side)."""

    def __init__(self, xlabel, ylabel, xlim, ylim, lines, y2label=None, y2lim=None,
                 image=None, square=False, xticklabels=True, yticks=None):
        self.xlabel, self.ylabel, self.xlim, self.ylim = xlabel, ylabel, xlim, ylim
        self.lines, self.y2label, self.y2lim = lines, y2label, y2lim
        self.image, self.square, self.xticklabels = image, square, xticklabels
        self.xt = nice_ticks(*xlim)
        self.yt = yticks or nice_ticks(*ylim)
        self.y2t = nice_ticks(*y2lim, 4) if y2lim else []


def figure_svg(panes, width_mm, aspect, legend=None, shares=None):
    """Lay out `panes` stacked, `width_mm` wide at `aspect` (w:h)."""
    W = width_mm * MM
    H0 = W / aspect
    pad, lpad, gap = 0.4 * TICK, 0.35 * LAB, 9.0
    # One left/right margin for every pane, so stacked frames line up.
    yw = max(tw(fmt(v, p.ylim[1] - p.ylim[0]), TICK) for p in panes for v in p.yt)
    y2w = max([tw(fmt(v, 1), TICK) for p in panes for v in p.y2t] or [0])
    ml = 3 + LAB + lpad + yw + pad
    mr = (3 + LAB + lpad + y2w + pad) if any(p.y2label for p in panes) else 0.5 * TICK + 2
    # The last x tick label is centred on the right edge: leave room for its half.
    at_edge = [p for p in panes if p.xt and abs(p.xt[-1] - p.xlim[1]) < 1e-9 * (p.xlim[1] - p.xlim[0])]
    half_last = max([tw(fmt(p.xt[-1], p.xlim[1] - p.xlim[0]), TICK) / 2 + 1 for p in at_edge] or [0])
    mr = max(mr, half_last)
    mt = 0.6 * TICK
    mb = pad + TICK + lpad + LAB + 3
    shares = shares or [1 / len(panes)] * len(panes)
    # Grow the height only if a rotated y label is longer than its plot.
    data_h = H0 - mt - mb - gap * (len(panes) - 1)
    need = max(max(tw(p.ylabel, LAB), tw(p.y2label or '', LAB)) / s + 2 * TICK
               for p, s in zip(panes, shares))
    grown = need > data_h
    if grown:
        data_h = need
    H = data_h + mt + mb + gap * (len(panes) - 1)
    pw = W - ml - mr

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.2f}pt" height="{H:.2f}pt" '
           f'viewBox="0 0 {W:.2f} {H:.2f}" font-family="{FONT}" fill="{INK}">',
           f'<rect width="{W:.2f}" height="{H:.2f}" fill="#fff"/>']
    y0 = mt
    first_frame = None
    for k, (p, s) in enumerate(zip(panes, shares)):
        ph = data_h * s
        ox, oy, fw, fh = ml, y0, pw, ph
        if p.square:
            side = min(pw, ph)
            ox, fw, fh = ml + (pw - side) / 2, side, side
            oy = y0 + (ph - side) / 2
        first_frame = first_frame or (ox, oy, fw, fh)
        out.append(pane_svg(p, ox, oy, fw, fh, pad, lpad, W, H, k))
        y0 += ph + gap
    if legend:
        out.append(legend_svg(legend, *first_frame))
    out.append('</svg>')
    return '\n'.join(out), H / MM, grown


def pane_svg(p, ox, oy, pw, ph, pad, lpad, W, H, k):
    (x0, x1), (y0, y1) = p.xlim, p.ylim
    sx = lambda v: ox + (v - x0) / (x1 - x0) * pw
    sy = lambda v: oy + (y1 - v) / (y1 - y0) * ph
    sy2 = (lambda v: oy + (p.y2lim[1] - v) / (p.y2lim[1] - p.y2lim[0]) * ph) if p.y2lim else None
    o = [f'<clipPath id="c{k}"><rect x="{ox:.2f}" y="{oy:.2f}" width="{pw:.2f}" height="{ph:.2f}"/></clipPath>']
    if p.image:
        o.append(f'<image x="{ox:.2f}" y="{oy:.2f}" width="{pw:.2f}" height="{ph:.2f}" '
                 f'preserveAspectRatio="none" href="{p.image}"/>')
    xs, ys = x1 - x0, y1 - y0
    for v in p.xt:
        if not p.image:
            o.append(f'<line x1="{sx(v):.2f}" x2="{sx(v):.2f}" y1="{oy:.2f}" y2="{oy + ph:.2f}" stroke="{GRID}" stroke-width="0.4"/>')
        if p.xticklabels:
            o.append(f'<text x="{sx(v):.2f}" y="{oy + ph + pad + 0.8 * TICK:.2f}" font-size="{TICK}" '
                     f'text-anchor="middle">{fmt(v, xs)}</text>')
    for v in p.yt:
        if not p.image:
            o.append(f'<line x1="{ox:.2f}" x2="{ox + pw:.2f}" y1="{sy(v):.2f}" y2="{sy(v):.2f}" stroke="{GRID}" stroke-width="0.4"/>')
        o.append(f'<text x="{ox - pad:.2f}" y="{sy(v) + 0.33 * TICK:.2f}" font-size="{TICK}" '
                 f'text-anchor="end">{fmt(v, ys)}</text>')
    for v in p.y2t:
        o.append(f'<text x="{ox + pw + pad:.2f}" y="{sy2(v) + 0.33 * TICK:.2f}" font-size="{TICK}">{fmt(v, 1)}</text>')
    o.append(f'<g clip-path="url(#c{k})">')
    for (x, y, col, wpx, dashed, op, side) in p.lines:
        f = sy2 if side == 'right' else sy
        d = 'M' + ' L'.join(f'{sx(a):.2f} {f(b):.2f}' for a, b in zip(x, y))
        dash = ' stroke-dasharray="2.4 1.8"' if dashed else ''
        o.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{wpx * 2 / 3:.2f}" '
                 f'opacity="{op}" stroke-linejoin="round"{dash}/>')
    o.append('</g>')
    o.append(f'<rect x="{ox:.2f}" y="{oy:.2f}" width="{pw:.2f}" height="{ph:.2f}" fill="none" stroke="{FRAME}" stroke-width="0.6"/>')
    if p.xticklabels:
        o.append(f'<text x="{ox + pw / 2:.2f}" y="{oy + ph + pad + TICK + lpad + 0.8 * LAB:.2f}" '
                 f'font-size="{LAB}" text-anchor="middle">{esc(p.xlabel)}</text>')
    o.append(f'<text transform="translate({3 + 0.8 * LAB:.2f} {oy + ph / 2:.2f}) rotate(-90)" '
             f'font-size="{LAB}" text-anchor="middle">{esc(p.ylabel)}</text>')
    if p.y2label:
        o.append(f'<text transform="translate({W - 3 - 0.8 * LAB:.2f} {oy + ph / 2:.2f}) rotate(90)" '
                 f'font-size="{LAB}" text-anchor="middle">{esc(p.y2label)}</text>')
    return '\n'.join(o)


def legend_svg(entries, ox, oy, pw, ph, corner='se'):
    sw, gap, inset, cp, row = 1.6 * LEG, 0.5 * LEG, 0.6 * LEG, 0.45 * LEG, 1.25 * LEG
    bw = 2 * cp + sw + gap + max(tw(t, LEG) for t, _ in entries)
    bh = 2 * cp + row * len(entries)
    bx = ox + pw - inset - bw if corner[1] == 'e' else ox + inset
    by = oy + ph - inset - bh if corner[0] == 's' else oy + inset
    o = [f'<g transform="translate({bx:.2f} {by:.2f})"><rect width="{bw:.2f}" height="{bh:.2f}" rx="2" '
         f'fill="#fff" fill-opacity="0.92" stroke="{CARD}" stroke-width="0.5"/>']
    for i, (t, col) in enumerate(entries):
        cy = cp + row * (i + 0.5)
        o.append(f'<line x1="{cp:.2f}" x2="{cp + sw:.2f}" y1="{cy:.2f}" y2="{cy:.2f}" stroke="{col}" stroke-width="1.6"/>'
                 f'<text x="{cp + sw + gap:.2f}" y="{cy + 0.34 * LEG:.2f}" font-size="{LEG}">{esc(t)}</text>')
    o.append('</g>')
    return ''.join(o)


def viridis_png(z):
    """dB image (rows = freq ascending) → viridis PNG data URL, top row = high f."""
    import matplotlib
    rgba = matplotlib.colormaps['viridis'](z[::-1])
    from PIL import Image
    im = Image.fromarray((rgba[..., :3] * 255).astype(np.uint8))
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def main(path):
    ds = dvma.load_data(path)
    td, tf = ds.time_data_list[0], ds.tf_data_list[0]
    name = tf.test_name
    t, x = np.asarray(td.time_axis), np.asarray(td.time_data)
    fs = td.settings.fs
    f = np.asarray(tf.freq_axis)
    h = np.asarray(tf.tf_data)[:, 0]
    coh = np.asarray(tf.tf_coherence)[:, 0]
    band = f <= 500
    fb, hb, cb = f[band], h[band], coh[band]
    mag = 20 * np.log10(np.maximum(np.abs(hb), 1e-15))
    ph = np.degrees(np.angle(hb))

    leg_tf = [(f'{name} · ch_1/ch_0', RED)]
    leg_t = [(f'{name} · ch_0', BLUE), (f'{name} · ch_1', RED)]
    tf_mag = lambda **kw: Pane('Frequency (Hz)', '|H| (V/V, dB)', (0, 500), (-72, 6),
                               [(fb, mag, RED, 1.5, False, 1, 'left'),
                                (fb, cb, RED, 1, True, 0.75, 'right')],
                               y2label='coherence γ²', y2lim=(0, 1), **kw)

    # time: first second of both channels
    k = t <= 1.0
    p_time = Pane('Time (s)', 'Amplitude (V)', (0, 1),
                  (-1.05 * np.abs(x[k]).max(), 1.05 * np.abs(x[k]).max()),
                  [(t[k], x[k, 0], BLUE, 1.5, False, 1, 'left'),
                   (t[k], x[k, 1], RED, 1.5, False, 1, 'left')])
    # spectrum: Welch PSD of both channels
    fw, pxx = signal.welch(x, fs=fs, nperseg=8192, axis=0)
    pdb = 10 * np.log10(pxx)
    lo, hi = np.floor(pdb[fw > 2].min() / 10) * 10, np.ceil(pdb.max() / 10) * 10
    p_psd = Pane('Frequency (Hz)', 'PSD (V²/Hz, dB)', (0, 1500), (lo, hi),
                 [(fw, pdb[:, 0], BLUE, 1.5, False, 1, 'left'),
                  (fw, pdb[:, 1], RED, 1.5, False, 1, 'left')])
    # phase
    p_phase = Pane('Frequency (Hz)', 'Phase (deg)', (0, 500), (-180, 180),
                   [(fb, ph, RED, 1.5, False, 1, 'left')], yticks=[-180, -90, 0, 90, 180])
    # Bode: magnitude (no x labels; shared x) over phase
    p_bmag = tf_mag(xticklabels=False)
    # Nyquist: the 77 Hz mode
    nb = (f >= 70) & (f <= 85)
    re, im = h[nb].real, h[nb].imag
    r = 1.1 * max(np.abs(re).max(), np.abs(im).max())
    cx, cy = (re.max() + re.min()) / 2, (im.max() + im.min()) / 2
    p_nyq = Pane('Real', 'Imag', (cx - r, cx + r), (cy - r, cy + r),
                 [(re, im, RED, 1.5, False, 1, 'left')], square=True)
    # sonogram: STFT of ch_1, 0-500 Hz, 60 dB range
    fs_, ts_, S = signal.spectrogram(x[:, 1], fs=fs, nperseg=1024, noverlap=768)
    S = S[fs_ <= 500]
    z = 10 * np.log10(S + 1e-30)
    z = np.clip((z - (z.max() - 60)) / 60, 0, 1)
    p_sono = Pane('Time (s)', 'Frequency (Hz)', (0, ts_[-1]), (0, 500), [], image=viridis_png(z))

    figs = [
        ('main', 'Main default 16:9: TF magnitude + coherence', [tf_mag()], 160, 16 / 9, leg_tf, None),
        ('main32', 'For comparison, 3:2: the same TF', [tf_mag()], 160, 3 / 2, leg_tf, None),
        ('time', 'Time history, 16:9 (default)', [p_time], 160, 16 / 9, leg_t, None),
        ('psd', 'Spectrum (PSD), 16:9 (default)', [p_psd], 160, 16 / 9, leg_t, None),
        ('phase', 'TF phase, 16:9 (default)', [p_phase], 160, 16 / 9, leg_tf, None),
        ('sono', 'Sonogram, 16:9 (default)', [p_sono], 160, 16 / 9, None, None),
        ('bode', 'Bode, 4:3 (exception): magnitude 60 %, phase 40 %, shared x labels',
         [p_bmag, p_phase], 160, 4 / 3, leg_tf, [0.6, 0.4]),
        ('nyq', 'Nyquist, 1:1 (exception), saved at 90 mm width: 70–85 Hz band',
         [p_nyq], 90, 1.0, leg_tf, None),
    ]
    blocks = {}
    for key, title, panes, wmm, asp, leg, shares in figs:
        svg, hmm, grown = figure_svg(panes, wmm, asp, leg, shares)
        (OUT / f'aspect_{key}.svg').write_text(svg, encoding='utf-8')
        note = f'{wmm:.0f} × {hmm:.0f} mm' + (' (grown to fit its labels)' if grown else '')
        blocks[key] = (f'<figure><img src="aspect_{key}.svg" style="width:{wmm}mm">'
                       f'<figcaption><b>{esc(title)}.</b> {note}.</figcaption></figure>')

    para = ('<p>Placeholder body text in 10 pt Times-style type, for scale. Each figure is '
            'laid out for the width it is shown at, so its labels print at 10 pt and its '
            'numbers and legend at 9 pt.</p>')
    pages = [
        ('1. The main default: 16:9 (top) against 3:2 (below)', ['main', 'main32']),
        ('2. The default on other single-pane plots', ['time', 'psd']),
        ('3. The default on other single-pane plots', ['phase', 'sono']),
        ('4. Exception: Bode', ['bode']),
        ('5. Exception: Nyquist', ['nyq']),
    ]
    body = ''.join(f'<section class="page"><p class="tag">{esc(t)}</p>{para}'
                   + ''.join(blocks[k] for k in keys) + '</section>' for t, keys in pages)
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>aspect mockups</title>
<style>
  @page {{ size: A4; margin: 0; }}
  body {{ margin: 0; font-family: 'STIX Two Text', 'Times New Roman', serif; color: #111; }}
  .page {{ width: 210mm; height: 297mm; box-sizing: border-box; padding: 25mm;
           page-break-after: always; background: #fff; }}
  .tag {{ font: 600 9pt -apple-system, Helvetica, sans-serif; color: #b45309;
          border-bottom: 0.5pt solid #e5c9a0; padding-bottom: 2mm; margin: 0 0 5mm; }}
  p {{ font-size: 10pt; line-height: 1.25; margin: 0 0 4mm; text-align: justify; }}
  figure {{ margin: 4mm 0 7mm; }} figure img {{ display: block; }}
  figcaption {{ font-size: 9pt; margin-top: 2mm; }}
</style></head><body>{body}</body></html>"""
    (OUT / 'aspects.html').write_text(doc, encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1])
