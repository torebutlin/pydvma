"""Regression tests for the webui glue's sonogram ops (Task 5b).

The browser/native engine imports ``pydvma.engine`` and drives it with plain
dicts / flat float64 arrays. These tests import that same module directly under
CPython and exercise the two sonogram ops the way the JS side does:

- ``calc_sono`` — one channel, real MAGNITUDE image, what the heat display
  draws (unchanged behaviour, pinned here because Task 5b refactored its guts
  into the shared ``_sono_data`` helper);
- ``calc_sono_full`` — the same transform as the COMPLEX ``(Nf, Nt, Nc)`` cube a
  stored ``SonoData`` holds, for the "Include sonogram?" save prompt.

The pairing is the point: whatever the user saw on screen must be the modulus
of what lands in the file.
"""

import numpy as np
import pytest

from pydvma import engine as glue

FS = 2000
N = 4096


def _payload(n_channels=3):
    """Multi-channel time payload exactly as JS ``timePayload`` marshals it."""
    t = np.arange(N) / FS
    cols = [np.sin(2 * np.pi * f * t) for f in (100.0, 250.0, 400.0)[:n_channels]]
    y = np.stack(cols, axis=1)
    return {
        'time_axis': t.astype(np.float64),
        'time_data': y.astype(np.float64).ravel(),
        'n_channels': n_channels,
        'fs': FS,
    }


def _marsh(a):
    """Rebuild a numpy array from a glue ``_arr`` marshal."""
    data = np.asarray(a['data'], dtype=np.float64)
    if a['complex']:
        data = data[0::2] + 1j * data[1::2]
    return data.reshape(a['shape'])


def _full(p, channels, **kw):
    return glue.calc_sono_full(p['time_axis'], p['time_data'], p['n_channels'],
                               p['fs'], channels=channels, nperseg=256,
                               noverlap=128, **kw)


class TestCalcSonoFull:

    def test_returns_the_complex_cube_for_the_chosen_channels(self):
        p = _payload()
        out = _full(p, [0, 2])
        cube = _marsh(out['sono_data'])
        assert out['sono_data']['complex'] is True
        n_f = len(_marsh(out['freq_axis']))
        n_t = len(_marsh(out['time_axis']))
        assert cube.shape == (n_f, n_t, 2)
        assert np.iscomplexobj(cube)
        # not all-real: a windowed STFT of a sine has genuine phase
        assert np.abs(cube.imag).max() > 0

    def test_cube_plane_order_follows_the_requested_channel_list(self):
        p = _payload()
        forward = _marsh(_full(p, [0, 2])['sono_data'])
        reversed_ = _marsh(_full(p, [2, 0])['sono_data'])
        np.testing.assert_allclose(forward[:, :, 0], reversed_[:, :, 1])
        np.testing.assert_allclose(forward[:, :, 1], reversed_[:, :, 0])

    def test_single_channel_matches_what_the_display_op_showed(self):
        # The contract behind the save prompt: |saved cube| == the image the
        # user was looking at when they chose to include it.
        p = _payload()
        shown = glue.calc_sono(p['time_axis'], p['time_data'], p['n_channels'],
                               p['fs'], ch=1, nperseg=256, noverlap=128)
        saved = _full(p, [1])
        np.testing.assert_allclose(
            np.abs(_marsh(saved['sono_data'])[:, :, 0]),
            _marsh(shown['sono_data']))
        np.testing.assert_allclose(_marsh(saved['freq_axis']),
                                   _marsh(shown['freq_axis']))
        np.testing.assert_allclose(_marsh(saved['time_axis']),
                                   _marsh(shown['time_axis']))

    def test_cwt_method_also_yields_a_complex_cube(self):
        p = _payload(n_channels=1)
        out = _full(p, [0], method='cwt', voices_per_octave=4)
        cube = _marsh(out['sono_data'])
        assert cube.shape[2] == 1
        assert np.iscomplexobj(cube)
        # CWT keeps its NATIVE log grid here, as calc_sono does
        f = _marsh(out['freq_axis'])
        assert f[0] < f[-1] and len(f) == cube.shape[0]

    def test_cwt_matches_the_display_op_channel_for_channel(self):
        p = _payload(n_channels=2)
        shown = glue.calc_sono(p['time_axis'], p['time_data'], p['n_channels'],
                               p['fs'], ch=1, nperseg=256, noverlap=128,
                               method='cwt', voices_per_octave=4)
        saved = _full(p, [0, 1], method='cwt', voices_per_octave=4)
        np.testing.assert_allclose(
            np.abs(_marsh(saved['sono_data'])[:, :, 1]),
            _marsh(shown['sono_data']))

    def test_out_of_range_channel_is_refused_not_clamped(self):
        p = _payload(n_channels=2)
        with pytest.raises(ValueError, match='out of range'):
            _full(p, [0, 5])

    def test_empty_channel_list_is_refused(self):
        p = _payload()
        with pytest.raises(ValueError, match='No channels'):
            _full(p, [])
