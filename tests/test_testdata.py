"""The synthetic test measurements follow the physics of a real impact test.

The response channel is the VELOCITY of a linear oscillator driven by the
force channel: the analytic velocity impulse response convolved with the
sampled force pulse. So the response starts with the hammer pulse, and the
transfer function velocity/force is the textbook velocity FRF — fitted with
``measurement_type='vel'`` its modal constant comes out real (phase ~0),
with no spurious delay. (Before: a displacement-shaped ``exp*sin`` that
started at t = 0, while the pulse centre was at 1 ms, labelled ``m/s``.)
Mac-runnable, no hardware.
"""

import numpy as np
import pytest

from pydvma import analysis, datastructure, modal, testdata

FN, TAU, A = 100.0, 0.1, 1000.0          # the documented test mode


def _velocity_frf(f, modes):
    """Analytic velocity FRF, sum of i*w*A / (wn^2 - w^2 + 2i*zeta*wn*w)."""
    w = 2 * np.pi * f
    H = np.zeros_like(w, dtype=complex)
    for fn, tau, a in modes:
        wn = 2 * np.pi * fn
        H += 1j * w * a / (wn ** 2 - w ** 2 + 2j * (1 / tau) * w)
    return H


def _tf(dataset):
    return analysis.calculate_tf(dataset.time_data_list[0], ch_in=0, window=None)


def test_the_response_starts_with_the_force():
    td = testdata.create_test_impulse_data().time_data_list[0]
    force, vel = td.time_data[:, 0], td.time_data[:, 1]
    assert force[0] == 0 and vel[0] == 0                 # at rest before the tap
    first = int(np.argmax(np.abs(vel) > 1e-6 * np.max(np.abs(vel))))
    assert first <= 1                                    # moves as the pulse starts
    assert np.max(np.abs(vel)) == pytest.approx(1.0, rel=0.1)   # ~1 m/s peak
    # During the 2 ms pulse the spring has barely acted, so the velocity is
    # the impulse delivered so far over the mass: A * integral of force.
    from scipy.integrate import cumulative_trapezoid
    fs = td.settings.fs
    during = slice(1, 10)                                # the first 1 ms
    impulse_so_far = cumulative_trapezoid(force, dx=1 / fs, initial=0)[during]
    np.testing.assert_allclose(vel[during], A * impulse_so_far, rtol=0.05)


# The raised-cosine pulse's own spectrum has zeros from 2/width (1 kHz for
# the 2 ms pulse, 4 kHz for the 0.5 ms one), where velocity/force is 0/0;
# check below them.
@pytest.mark.parametrize('make,modes,f_max', [
    (testdata.create_test_impulse_data, [(FN, TAU, A)], 800),
    (testdata.create_test_impulse_data_nonlinear_v1,
     [(FN, 0.05, 700.0), (FN, 0.2, 300.0)], 800),
    (lambda: testdata.create_test_impulse_data_multi_harmonics(noise_level=0),
     [(k * 100.0, 0.1, a / 2.5e-4) for k, a in zip([1, 4, 9, 16], [1.0, 0.5, 0.3, 0.2])]
     + [(k * 103.0, 0.1, a / 2.5e-4) for k, a in zip([1, 4, 9, 16], [0.8, 0.4, 0.25, 0.15])],
     2000),
])
def test_the_tf_is_the_analytic_velocity_frf(make, modes, f_max):
    tf = _tf(make())
    f = tf.freq_axis
    band = (f > 20) & (f < f_max)
    H = _velocity_frf(f[band], modes)
    err = np.abs(tf.tf_data[band, 0] - H) / np.max(np.abs(H))
    assert np.max(err) < 5e-3


def test_a_vel_fit_recovers_the_mode_with_a_real_modal_constant():
    tf = _tf(testdata.create_test_impulse_data())
    md = modal.modal_fit_all_channels(datastructure.TfDataList([tf]),
                                      freq_range=[80, 120], measurement_type='vel')
    assert md.fn[0] == pytest.approx(FN, rel=1e-3)
    assert md.zn[0] == pytest.approx(1 / (TAU * 2 * np.pi * FN), rel=0.02)
    assert md.an[0, 0] == pytest.approx(A, rel=0.02)
    assert abs(md.pn[0, 0]) < np.deg2rad(2)              # no spurious delay


def test_noise_data_tf_is_the_same_system():
    td = testdata.create_test_noise_data(added_noise_level=0).time_data_list[0]
    tf = analysis.calculate_tf(td, ch_in=0, window='hann', N_frames=8)
    f = tf.freq_axis
    near = (f > 80) & (f < 120)
    H = _velocity_frf(f[near], [(FN, TAU, A)])
    rel = np.abs(tf.tf_data[near, 0] - H) / np.abs(H)
    assert np.median(rel) < 0.05
    assert tf.tf_coherence[near, 0].mean() > 0.95


def test_the_ensemble_is_repeated_impulse_tests():
    ens = testdata.create_test_impulse_ensemble(N_ensemble=2, noise_level=0)
    a, b = (td.time_data for td in ens.time_data_list)
    np.testing.assert_array_equal(a, b)
    np.testing.assert_array_equal(a, testdata.create_test_impulse_data().time_data_list[0].time_data)
