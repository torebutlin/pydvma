"""Mockup round 3: the damping panel's three saveable charts at print size.

Throwaway, like make_aspects.py (whose renderer it reuses). Runs pydvma's own
engine ops (`engine.calc_damping`, `engine.calc_damping_bands`, the app's
defaults) on one 4C6 hammer record and lays out the start-slice spectrum,
the decay fits and the Schroeder EDC at 16:9, 160 mm, with their legends
drawn INSIDE the figure (on screen they are HTML chips the PNG never had).

    python dev/mockups/2026-11-24-publication-figure/make_damping.py "data/4c6_examples_problems/6modes done.dvma"
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import make_aspects as A  # noqa: E402

import pydvma as dvma  # noqa: E402
from pydvma import engine  # noqa: E402

PALETTE = ['#2563eb', '#dc2626', '#059669', '#d97706', '#7c3aed', '#0891b2',
           '#be185d', '#4d7c0f', '#9333ea', '#0e7490', '#b91c1c', '#15803d']
INDIGO, RED, GREY = '#4f46e5', '#dc2626', '#6b7280'


def arr(p):
    """Engine payload {'shape', 'data'} -> ndarray."""
    return np.asarray(p['data'], dtype=float).reshape(p['shape'])


def pad(lo, hi, f):
    s = (hi - lo) or 1.0
    return lo - f * s, hi + f * s


def every(n, k=60):
    """The app's markerIndices: at most k evenly spread indices."""
    if n <= k:
        return np.arange(n)
    return np.round(np.arange(k) * (n - 1) / (k - 1)).astype(int)


def main(path):
    ds = dvma.load_data(path)
    td = ds.time_data_list[0]
    t, x = np.asarray(td.time_axis), np.asarray(td.time_data)
    fs = td.settings.fs
    r = engine.calc_damping(t, x, 2, fs, 1, 2048)
    b = engine.calc_damping_bands(t, x, 2, fs, 1, bands='octave')

    # 1. start-slice spectrum, normalised, peaks + threshold
    sf, sm = arr(r['slice_freq']), arr(r['slice_mag'])
    lo, span = sm.min(), (sm.max() - sm.min()) or 1.0
    norm = (sm - lo) / span
    pf, pm = arr(r['peaks_freq']), (arr(r['peaks_mag']) - lo) / span
    thr = float(r['threshold'])
    xl = pad(sf.min(), sf.max(), 0.02)
    spec = A.Pane('Frequency (Hz)', 'Normalised |S|', xl, (0, 1.06), [
        (sf, norm, INDIGO, 1.3, False, 1, 'left'),
        (pf, pm, RED, 1.4, False, 1, 'left', 'o', False),
        (np.array(xl), np.array([thr, thr]), RED, 1.2, True, 1, 'left'),
    ])
    spec_leg = [(f'Start slice, t = {float(r["start_time"]):.2f} s', INDIGO, 'line'),
                (f'Picked peaks ({len(pf)})', RED, 'o'),
                (f'Threshold {thr:.2g}', RED, 'dash')]

    # 2. decay fits: Re log(S) data (sparse x) + fitted line per mode
    lines, leg = [], []
    allx, ally = [], []
    for i, f in enumerate(r['fits']):
        tf_, rd, rf = arr(f['t_fit']), arr(f['real_data']), arr(f['real_fit'])
        c = PALETTE[i % len(PALETTE)]
        k = every(len(tf_))
        lines.append((tf_[k], rd[k], c, 1.1, False, 0.75, 'left', 'x', False))
        lines.append((tf_, rf, c, 2.4, False, 1, 'left'))
        leg.append((f'{float(f["f_peak"]):.1f} Hz, Qn = {float(f["Qn"]):.0f}', c, 'xline'))
        allx += [tf_.min(), tf_.max()]
        ally += [rd.min(), rd.max(), rf.min(), rf.max()]
    decay = A.Pane('Time (s)', 'Re log(S)', pad(min(allx), max(allx), 0.03),
                   pad(min(ally), max(ally), 0.08), lines)

    # 3. Schroeder EDC per octave band + dashed T60 fits
    lines, eleg, tmax = [], [], 0.0
    for i, bd in enumerate(b['band_data']):
        c = PALETTE[i % len(PALETTE)]
        et, ed = arr(bd['edc_t']), arr(bd['edc_db'])
        lines.append((et, ed, c, 1.4, False, 0.9, 'left'))
        if 'fit_t' in bd:
            lines.append((arr(bd['fit_t']), arr(bd['fit_db']), c, 2.0, True, 1, 'left'))
        fc = float(bd['fc'])
        eleg.append((f'{fc:.1f} Hz' if fc < 10 else f'{fc:.0f} Hz', c, 'line'))
        tmax = max(tmax, et.max())
    eleg.append(('T60 fit (dashed)', GREY, 'dash'))
    edc = A.Pane('Time (s)', 'EDC (dB)', pad(0, tmax, 0.02), (-70, 3), lines)

    figs = [
        ('spectrum', 'Damping, peaks mode: start-slice spectrum', spec, spec_leg),
        ('decay', 'Damping, peaks mode: decay fits', decay, leg),
        ('edc', 'Damping, bands mode: Schroeder EDC, octave bands', edc, eleg),
    ]
    blocks = []
    for key, title, pane, lg in figs:
        svg, hmm, grown = A.figure_svg([pane], 160, 16 / 9, lg, corner='best')
        (A.OUT / f'damping_{key}.svg').write_text(svg, encoding='utf-8')
        blocks.append(f'<figure><img src="damping_{key}.svg" style="width:160mm">'
                      f'<figcaption><b>{A.esc(title)}.</b> 16:9, 160 × {hmm:.0f} mm; '
                      f'legend in the emptiest corner, or below the axes when every corner would cover data.</figcaption></figure>')

    para = ('<p>Placeholder body text in 10 pt Times-style type, for scale. Record: '
            f'{A.esc(Path(path).name)}, set &ldquo;{A.esc(str(td.test_name))}&rdquo;, response '
            'channel, the app’s default fits (STFT 2048, automatic start and threshold; '
            'octave bands).</p>')
    pages = [blocks[:2], blocks[2:]]
    body = ''.join(f'<section class="page"><p class="tag">Damping charts ({i + 1} of 2)</p>{para}'
                   + ''.join(p) + '</section>' for i, p in enumerate(pages))
    html_doc = (A.OUT / 'aspects.html').read_text(encoding='utf-8')
    head = html_doc.split('<body>')[0].replace('aspect mockups', 'damping chart mockups')
    (A.OUT / 'damping.html').write_text(f'{head}<body>{body}</body></html>', encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1])
