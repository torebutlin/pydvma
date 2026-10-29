"""`acquisition.signal_generator` warns when it rescales to the output rail,
and makes ``ceil(T * output_fs)`` samples (the last two tests).

When the finished waveform's peak exceeds ``settings.output_vmax()`` the
whole waveform is scaled down so its peak sits on the rail. That used to
happen silently (the only trace was ``acquisition.MESSAGE``), so a stimulus
could leave at a fraction of the requested level with nothing said.
Mac-runnable, no hardware.
"""

import warnings

import numpy as np
import pytest

from pydvma import acquisition, options


def _settings():
    s = options.MySettings(fs=2000, output_fs=2000, output_channels=1)
    assert s.output_vmax() > 0
    return s


def test_sweep_above_the_rail_warns_and_sits_on_the_rail():
    s = _settings()
    rail = s.output_vmax()
    with pytest.warns(acquisition.OutputRescaledWarning) as rec:
        _t, y = acquisition.signal_generator(
            s, sig='sweep', T=0.5, amplitude=3 * rail, f=[10, 200])
    assert len(rec) == 1
    msg = str(rec[0].message)
    assert 'rail' in msg and 'amplitude' in msg
    assert np.max(np.abs(y)) == pytest.approx(rail)


def test_banded_gaussian_above_the_rail_warns_once():
    s = _settings()
    rail = s.output_vmax()
    with pytest.warns(acquisition.OutputRescaledWarning) as rec:
        _t, y = acquisition.signal_generator(
            s, sig='gaussian', T=0.5, amplitude=rail, f=[10, 200])
    assert len(rec) == 1
    assert np.max(np.abs(y)) <= rail * (1 + 1e-12)


@pytest.mark.parametrize('sig,f', [('sweep', [10, 200]),
                                   ('gaussian', [10, 200]),
                                   ('gaussian', None),
                                   ('uniform', None)])
def test_within_the_rail_is_silent(sig, f):
    s = _settings()
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        acquisition.signal_generator(s, sig=sig, T=0.5,
                                     amplitude=0.05 * s.output_vmax(), f=f)


def test_unbanded_gaussian_is_truncated_not_rescaled():
    """Plain Gaussian noise is a truncated normal: samples beyond the rail
    are redrawn, the level is not scaled, so there is nothing to warn of."""
    s = _settings()
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        _t, y = acquisition.signal_generator(
            s, sig='gaussian', T=0.5, amplitude=2 * s.output_vmax())
    assert np.max(np.abs(y)) <= s.output_vmax()


def test_the_warning_is_a_userwarning():
    assert issubclass(acquisition.OutputRescaledWarning, UserWarning)


@pytest.mark.parametrize('fs,T,n', [
    (1000, 8.05, 8050),           # arange(0, T, 1/fs) made 8051
    (1000, 16.01, 16010),         # ... and 16011
    (8000, 1.0, 8000),            # exact T*fs stays exact
    (8000, 0.05, 400),
    (44100, 2.0, 88200),
    (20e6 / 6667, 1.0, 3000),     # an NI-coerced rate rounds up
])
def test_sample_count_is_ceil_of_T_times_fs(fs, T, n):
    # The browser generator's `stimulusLength` counts the same way
    # (webui/tests/audio/signal.test.ts pins the last three).
    s = options.MySettings(fs=int(fs), output_fs=int(fs), output_channels=1)
    s.output_fs = fs   # MySettings stores an int; a coerced rate is assigned
    t, y = acquisition.signal_generator(s, sig='sweep', T=T,
                                        amplitude=0.1, f=[10, 200])
    assert y.shape == (n, 1)
    assert len(t) == n
    assert t[-1] < T
    np.testing.assert_allclose(t, np.arange(n) / fs)


def test_old_float_step_did_overshoot():
    # Guards the first case above: it is a real arange overshoot.
    assert len(np.arange(0, 8.05, 1 / 1000)) == 8051
