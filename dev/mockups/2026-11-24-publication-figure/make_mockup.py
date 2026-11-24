"""Mockup generator for the publication-quality Save Figure proposal.

Throwaway: writes three print-layout figure SVGs (laid out in POINTS at a
160 mm printed width) from a real .dvma TF, and an A4 HTML page per variant
with 10 pt body text around the figure, so the type sizes can be judged at
true scale. Run from the repo root:

    python dev/mockups/2026-11-24-publication-figure/make_mockup.py <file.dvma>
"""
import html
import sys
from pathlib import Path

import numpy as np

import pydvma as dvma

OUT = Path(__file__).parent

MM = 72 / 25.4                      # points per mm
W = 160 * MM                        # A4 with 25 mm margins: 160 mm text width
ASPECT = 2.08                       # the on-screen aspect of Tore's figure
H = W / ASPECT

RED = '#dc2626'                     # palette colour of the line in the app
INK = '#1d2027'                     # near-black text for print
FRAME = '#3f4652'
GRID = '#dfe2e7'
CARD_STROKE = '#c5cad3'


def text_w(s, size, serif):
    """Rough advance width (pt) of `s` at `size` pt, for margin sizing."""
    per = 0.50 if serif else 0.556   # digits are 0.5 em (Times) / 0.556 em (Arial)
    w = 0.0
    for ch in s:
        if ch.isdigit():
            w += per
        elif ch in '.,':
            w += 0.25 if serif else 0.278
        elif ch == '−':
            w += 0.564 if serif else 0.584
        else:
            w += 0.5
    return w * size


def fmt(v, d=0):
    s = f'{v:.{d}f}'
    return s.replace('-', '−')


def figure_svg(f, mag_db, coh, *, family, serif, lab, tick, legend_label):
    xr = (0.0, 500.0)
    yr = (-72.0, 6.0)
    xt = [0, 100, 200, 300, 400, 500]
    yt = [-60, -40, -20, 0]
    y2t = [(0.0, '0'), (0.5, '0.5'), (1.0, '1')]

    pad = 0.4 * tick                           # tick label to frame
    lpad = 0.35 * lab                          # axis label to tick labels
    yl_w = max(text_w(fmt(v), tick, serif) for v in yt)
    y2_w = max(text_w(s, tick, serif) for _, s in y2t)
    ml = 3 + lab + lpad + yl_w + pad
    mr = 3 + lab + lpad + y2_w + pad
    mt = 0.6 * tick
    mb = pad + tick + lpad + lab + 3
    pw, ph = W - ml - mr, H - mt - mb

    def sx(v):
        return ml + (v - xr[0]) / (xr[1] - xr[0]) * pw

    def sy(v):
        return mt + (yr[1] - v) / (yr[1] - yr[0]) * ph

    def sy2(v):
        return mt + (1 - v) * ph

    keep = (f >= xr[0]) & (f <= xr[1])
    fx, my, cy = f[keep], np.clip(mag_db[keep], yr[0] - 5, yr[1] + 5), coh[keep]
    d_mag = 'M' + ' L'.join(f'{sx(a):.2f} {sy(b):.2f}' for a, b in zip(fx, my))
    d_coh = 'M' + ' L'.join(f'{sx(a):.2f} {sy2(b):.2f}' for a, b in zip(fx, cy))

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.2f}pt" height="{H:.2f}pt" '
         f'viewBox="0 0 {W:.2f} {H:.2f}" font-family="{family}" fill="{INK}">',
         f'<rect width="{W:.2f}" height="{H:.2f}" fill="#fff"/>',
         f'<clipPath id="c"><rect x="{ml:.2f}" y="{mt:.2f}" width="{pw:.2f}" height="{ph:.2f}"/></clipPath>']
    for v in xt:
        p.append(f'<line x1="{sx(v):.2f}" x2="{sx(v):.2f}" y1="{mt:.2f}" y2="{mt + ph:.2f}" '
                 f'stroke="{GRID}" stroke-width="0.4"/>')
        p.append(f'<text x="{sx(v):.2f}" y="{mt + ph + pad + 0.8 * tick:.2f}" font-size="{tick}" '
                 f'text-anchor="middle">{fmt(v)}</text>')
    for v in yt:
        p.append(f'<line x1="{ml:.2f}" x2="{ml + pw:.2f}" y1="{sy(v):.2f}" y2="{sy(v):.2f}" '
                 f'stroke="{GRID}" stroke-width="0.4"/>')
        p.append(f'<text x="{ml - pad:.2f}" y="{sy(v) + 0.33 * tick:.2f}" font-size="{tick}" '
                 f'text-anchor="end">{fmt(v)}</text>')
    for v, s in y2t:
        p.append(f'<text x="{ml + pw + pad:.2f}" y="{sy2(v) + 0.33 * tick:.2f}" font-size="{tick}" '
                 f'text-anchor="start">{s}</text>')
    p.append(f'<g clip-path="url(#c)">'
             f'<path d="{d_coh}" fill="none" stroke="{RED}" stroke-width="0.6" '
             f'stroke-dasharray="2.4 1.6" opacity="0.75"/>'
             f'<path d="{d_mag}" fill="none" stroke="{RED}" stroke-width="1.0" '
             f'stroke-linejoin="round"/></g>')
    p.append(f'<rect x="{ml:.2f}" y="{mt:.2f}" width="{pw:.2f}" height="{ph:.2f}" fill="none" '
             f'stroke="{FRAME}" stroke-width="0.6"/>')
    # axis labels
    p.append(f'<text x="{ml + pw / 2:.2f}" y="{H - 3:.2f}" font-size="{lab}" '
             f'text-anchor="middle">Frequency (Hz)</text>')
    p.append(f'<text transform="translate({3 + 0.8 * lab:.2f} {mt + ph / 2:.2f}) rotate(-90)" '
             f'font-size="{lab}" text-anchor="middle">|<tspan font-style="italic">H</tspan>| (V/V, dB)</text>')
    p.append(f'<text transform="translate({W - 3 - 0.8 * lab:.2f} {mt + ph / 2:.2f}) rotate(90)" '
             f'font-size="{lab}" text-anchor="middle">Coherence <tspan font-style="italic">γ</tspan>²</text>')
    # legend: inside the axes, inset from the frame's bottom-right corner
    lsize = tick
    sw, gap, inset, cpad = 1.6 * lsize, 0.5 * lsize, 0.6 * lsize, 0.45 * lsize
    tw = len(legend_label) * (0.46 if serif else 0.5) * lsize
    bw, bh = cpad * 2 + sw + gap + tw, cpad * 2 + 1.2 * lsize
    bx, by = ml + pw - inset - bw, mt + ph - inset - bh
    p.append(f'<g transform="translate({bx:.2f} {by:.2f})">'
             f'<rect width="{bw:.2f}" height="{bh:.2f}" rx="2" fill="#fff" fill-opacity="0.92" '
             f'stroke="{CARD_STROKE}" stroke-width="0.5"/>'
             f'<line x1="{cpad:.2f}" x2="{cpad + sw:.2f}" y1="{bh / 2:.2f}" y2="{bh / 2:.2f}" '
             f'stroke="{RED}" stroke-width="1.6"/>'
             f'<text x="{cpad + sw + gap:.2f}" y="{bh / 2 + 0.34 * lsize:.2f}" font-size="{lsize}">'
             f'{html.escape(legend_label)}</text></g>')
    p.append('</svg>')
    return '\n'.join(p)


VARIANTS = [
    ('a', 'A: Times New Roman, 10 pt labels, 9 pt numbers',
     "'Times New Roman', Times, serif", True, 10, 9, 10),
    ('b', 'B: Arial (sans), 10 pt labels, 9 pt numbers',
     'Arial, Helvetica, sans-serif', False, 10, 9, 10),
    ('c', 'C: Times New Roman, 12 pt labels, 11 pt numbers (for a 12 pt manuscript)',
     "'Times New Roman', Times, serif", True, 12, 11, 12),
]

BODY = (
    'Placeholder body text, set at the size named on the tag above in Times '
    'New Roman, so that the type in the figure can be judged against the '
    'running text of a journal page. The figure is placed at the full text '
    'width of an A4 page with 25 mm margins, 160 mm, which is the width it is '
    'laid out for: printed at that width its labels are exactly the stated '
    'point size. Scaled to a single column (about 90 mm) the type would shrink '
    'to a little over half that size, so a single-column figure wants its own '
    'width setting rather than a reduction of this one.'
)


def page(title, svg_file, body_pt, caption):
    return f"""
<section class="page">
  <p class="tag">{html.escape(title)}</p>
  <p style="font-size:{body_pt}pt">{BODY}</p>
  <figure><img src="{svg_file}" style="width:160mm">
    <figcaption style="font-size:{body_pt - 1}pt"><b>Fig. 1.</b> {caption}</figcaption></figure>
  <p style="font-size:{body_pt}pt">{BODY}</p>
</section>"""


def main(path):
    ds = dvma.load_data(path)
    tf = ds.tf_data_list[0]
    f = np.asarray(tf.freq_axis)
    h = np.asarray(tf.tf_data)[:, 0]
    coh = np.asarray(tf.tf_coherence)[:, 0]
    mag_db = 20 * np.log10(np.maximum(np.abs(h), 1e-15))
    label = f'{tf.test_name} · ch_1/ch_0'

    pages = [page('Today: the saved PNG placed at the same 160 mm width',
                  'today.webp', 10,
                  'Transfer function and coherence (current Save Figure output).')]
    for key, title, family, serif, lab, tick, body in VARIANTS:
        svg = figure_svg(f, mag_db, coh, family=family, serif=serif, lab=lab,
                         tick=tick, legend_label=label)
        (OUT / f'figure_{key}.svg').write_text(svg, encoding='utf-8')
        pages.append(page(title, f'figure_{key}.svg', body,
                          'Transfer function |H| (solid) and coherence '
                          'γ² (dashed, right axis), from p2_noise_30s.dvma.'))

    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>pydvma publication figure mockup</title>
<style>
  @page {{ size: A4; margin: 0; }}
  body {{ margin: 0; font-family: 'Times New Roman', Times, serif; color: #111; }}
  .page {{ width: 210mm; height: 297mm; box-sizing: border-box; padding: 25mm;
           page-break-after: always; background: #fff; }}
  .tag {{ font: 600 9pt -apple-system, Helvetica, sans-serif; color: #b45309;
          border-bottom: 0.5pt solid #e5c9a0; padding-bottom: 2mm; margin: 0 0 6mm; }}
  p {{ text-align: justify; line-height: 1.25; margin: 0 0 4mm; }}
  figure {{ margin: 6mm 0; }}
  figure img {{ display: block; }}
  figcaption {{ margin-top: 2mm; line-height: 1.25; }}
</style></head><body>{''.join(pages)}</body></html>"""
    (OUT / 'mockup.html').write_text(doc, encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1])
