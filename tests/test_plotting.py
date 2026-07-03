"""Headless tests for `pydvma.plotting.PlotData`.

Forces the matplotlib Agg backend so no Qt/display is needed: PlotData
with canvas=None is plain matplotlib. Covers the June 2026 review
fixes: the `channels='all'` sentinel locking to the first set's channel
count, and the coherence log-plot recomputing 20·log10 on zeros after
the zero-safe branch (RuntimeWarning + dead code).
"""

import matplotlib
matplotlib.use('Agg', force=True)

import warnings

import numpy as np
import pytest

from pydvma import analysis, datastructure, options
from pydvma import plotting


def _make_time_data(n_chans, fs=1000, n_samples=512, seed=0):
    rng = np.random.default_rng(seed)
    settings = options.MySettings(fs=fs, channels=n_chans)
    time_axis = np.arange(n_samples) / fs
    return datastructure.TimeData(
        time_axis,
        rng.standard_normal((n_samples, n_chans)),
        settings,
        channel_cal_factors=np.ones(n_chans),
        test_name='test',
    )


class TestChannelsAllAcrossSets:

    def test_all_channels_selected_when_sets_have_different_counts(self):
        """channels='all' must select every channel of every set; it was
        being narrowed to range(N_chans of set 0) on the first loop
        iteration, dimming the extra channels of later sets."""
        tdl = datastructure.TimeDataList([
            _make_time_data(n_chans=1, seed=1),
            _make_time_data(n_chans=3, seed=2),
        ])
        p = plotting.PlotData()
        p.update(tdl, channels='all', auto_xy='')

        alphas = [line.get_alpha()
                  for set_lines in p.line_listbyset
                  for line in set_lines]
        assert len(alphas) == 4
        # all selected → full LINE_ALPHA (0.9 for <=12 channels)
        assert all(a == pytest.approx(0.9) for a in alphas)

    def test_explicit_channel_selection_still_dims_others(self):
        tdl = datastructure.TimeDataList([_make_time_data(n_chans=3, seed=3)])
        p = plotting.PlotData()
        p.update(tdl, channels=[0], auto_xy='')

        alphas = [line.get_alpha() for line in p.line_listbyset[0]]
        assert alphas[0] == pytest.approx(0.9)
        assert alphas[1] == pytest.approx(0.1)
        assert alphas[2] == pytest.approx(0.1)


class TestCoherenceLogPlot:

    def test_zero_coherence_log_plot_is_warning_free(self):
        """The zero-safe dB conversion was immediately overwritten by a
        plain 20·log10(|yc|), reintroducing divide-by-zero warnings on
        zero-coherence bins (e.g. the DC bin)."""
        td = _make_time_data(n_chans=2, n_samples=2048, seed=4)
        tf = analysis.calculate_tf(td, ch_in=0, N_frames=4, window='hann')
        tf.tf_coherence[0, :] = 0.0  # force a zero bin

        p = plotting.PlotData()
        with warnings.catch_warnings():
            warnings.simplefilter('error', category=RuntimeWarning)
            p.update(datastructure.TfDataList([tf]),
                     coherence_plot_type='log', auto_xy='')

        yc = p.line2_listbyset[0][0].get_data()[1]
        assert yc[0] == -np.inf  # zero coherence → -inf dB, silently


class TestAutoYSmoke:

    def test_auto_y_runs_for_tf_default_and_nyquist(self):
        """auto_y contained an acknowledged-dead TfData/Nyquist branch;
        pin that both plot types still autoscale without error."""
        td = _make_time_data(n_chans=2, n_samples=2048, seed=5)
        tf = analysis.calculate_tf(td, ch_in=0, N_frames=4, window='hann')
        tfl = datastructure.TfDataList([tf])

        p = plotting.PlotData()
        p.update(tfl, plot_type=None, auto_xy='xy')
        p.update(tfl, plot_type='Nyquist', auto_xy='xy')


class TestFigShowGating:
    """PlotData.__init__ used to call self.fig.show() unconditionally,
    which (a) is meaningless under non-interactive backends like the
    Agg backend forced in this file and just emits a UserWarning, and
    (b) under notebook-style backends (ipympl, inline, matplotlib-pyodide's
    wasm/html5-canvas backends used by JupyterLite) double-displays a
    spurious empty figure before the populated one, since those backends
    already show the figure via their own repr/widget machinery."""

    def test_no_warning_under_agg(self, recwarn):
        """Agg is non-interactive; show() should be skipped, not just
        attempted-and-warned."""
        plotting.PlotData()
        show_warnings = [w for w in recwarn.list
                          if 'cannot be shown' in str(w.message)]
        assert not show_warnings

    @pytest.mark.parametrize('backend_name', [
        'module://ipympl.backend_nbagg',
        'nbagg',
        'module://matplotlib_inline.backend_inline',
        'module://matplotlib_pyodide.wasm_backend',
        'module://matplotlib_pyodide.html5_canvas_backend',
        'webagg',
        'agg',
        'svg',
        'pdf',
    ])
    def test_notebook_and_non_interactive_backends_skip_show(self, backend_name, monkeypatch):
        """fig.show() must not be invoked for notebook-style backends
        (would double-display) or non-interactive backends (would warn
        for no benefit)."""
        monkeypatch.setattr(plotting.matplotlib, 'get_backend', lambda: backend_name)
        calls = []
        p = plotting.PlotData.__new__(plotting.PlotData)
        fig, ax = plotting.plt.subplots(1, 1)
        fig.show = lambda: calls.append(True)
        monkeypatch.setattr(plotting.plt, 'subplots', lambda *a, **k: (fig, ax))
        plotting.PlotData.__init__(p)
        assert calls == []
