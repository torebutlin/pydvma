# -*- coding: utf-8 -*-
"""Synthetic measurements for trying pydvma without hardware."""

from . import options
from . import datastructure

import numpy as np
import scipy.signal as signal
import datetime


    

#%% Create test data
def _sdof_velocity_ir(t, fn, tau):
    """Velocity impulse response of one mode, per unit modal constant.

    A mode with undamped natural frequency ``fn`` (Hz) whose free decay has
    time constant ``tau`` (s), so ``zeta * wn = 1/tau``. For a unit impulse
    of force at t = 0 the velocity is ``exp(-t/tau) * (cos(wd*t) -
    sin(wd*t) / (tau*wd))`` times the modal constant ``A`` (``1/m`` for a
    single mass), whose Fourier transform is the velocity FRF ``i*w*A /
    (wn**2 - w**2 + 2i*zeta*wn*w)``: the form `modal_fit_all_channels`
    fits with ``measurement_type='vel'``.
    """
    sigma = 1.0 / tau
    wn = 2 * np.pi * fn
    wd = np.sqrt(wn ** 2 - sigma ** 2)
    return np.exp(-sigma * t) * (np.cos(wd * t) - (sigma / wd) * np.sin(wd * t))


def _velocity_response(force, fs, modes):
    """Velocity of a linear structure driven by ``force`` (N, sampled at fs).

    ``modes`` is a list of ``(fn, tau, A)``: natural frequency (Hz), decay
    time constant (s) and modal constant (1/kg). The response is the
    convolution of the force with the summed velocity impulse responses,
    so it starts with the force and a TF of velocity over force is the
    analytic velocity FRF, with no delay between the two channels. The
    first impulse-response sample is halved (the trapezoid rule): the plain
    sampled sum adds ``h(0)*dt/2`` to the FRF at every frequency, 30 % of
    it at 1 kHz for the default test mode.
    """
    t = np.arange(len(force)) / fs
    h = np.zeros_like(t)
    for fn, tau, A in modes:
        h += A * _sdof_velocity_ir(t, fn, tau)
    h[0] *= 0.5
    return np.convolve(force, h)[:len(force)] / fs


def _raised_cosine_pulse(N, fs, width):
    """A unit-height raised-cosine force pulse ``width`` s long at t = 0.

    Returns the length-N force channel and its impulse (N s), the area
    under the pulse.
    """
    force = np.zeros(N)
    N_pulse = int(np.ceil(width * fs))
    n = np.arange(N_pulse)
    force[n] = 0.5 * (1 - np.cos(2 * np.pi * n / N_pulse))
    return force, np.sum(force) / fs


def create_test_impulse_data(noise_level=0.0):
    '''Simulate one impulse-hammer test of a single 100 Hz mode.

    The DataSet holds one `TimeData` of 1 s at 10 kHz (10000 samples,
    two channels, units ``['N', 'm/s']``). Channel 0 is the hammer
    force: a unit-height raised-cosine pulse, 2 ms long, at the start of
    the record (an impulse of 1 mN s). Channel 1 is the VELOCITY it
    drives: one mode at 100 Hz whose free decay has a 0.1 s time
    constant (damping ratio 0.0159), with modal constant 1000 /kg (a
    1 g mass), so the tap sets it moving at about 1 m/s. The response is
    the force convolved with the mode's velocity impulse response, so it
    starts with the pulse, and a TF of channel 1 over channel 0 is the
    velocity FRF: fit it with ``measurement_type='vel'``.

    Args:
        noise_level (float): Half-width of uniform random noise added to
            channel 1 (default 0, no noise).

    Returns:
        dataset (DataSet): The simulated measurement, with test name
            ``'Synthesised data'``.
    '''
    settings = options.MySettings(fs=10000)
    N = int(1e4)
    time_axis = np.arange(N)/settings.fs
    
    time_data = np.zeros([N,2])
    force, _impulse = _raised_cosine_pulse(N, settings.fs, 0.002)
    time_data[:,0] = force
    
    y = _velocity_response(force, settings.fs, [(100.0, 0.1, 1000.0)])
    
    y += noise_level*2*(np.random.rand(len(y)) - 0.5)
    
    time_data[:,1] = y
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    timedata = datastructure.TimeData(time_axis,time_data,settings,timestamp=t, timestring=timestring, units=['N','m/s'], channel_cal_factors=[1,1], test_name='Synthesised data')
    #metadata = MetaData(, tf_cal_factors=1)
    
    dataset = datastructure.DataSet()
    dataset.add_to_dataset(timedata)
    
    return dataset

def create_test_impulse_ensemble(N_ensemble=5, noise_level=0.1):
    '''Simulate repeated impulse-hammer tests, for ensemble averaging.

    Calls `create_test_impulse_data` ``N_ensemble`` times, so every
    measurement is the same 100 Hz mode with fresh random noise on the
    response channel.

    Args:
        N_ensemble (int): Number of measurements (default 5).
        noise_level (float): Half-width of the uniform noise added to
            each response (default 0.1).

    Returns:
        dataset (DataSet): ``N_ensemble`` `TimeData` measurements.
    '''
    dataset = datastructure.DataSet()
    for n in range(N_ensemble):
        d = create_test_impulse_data(noise_level=noise_level)
        dataset.add_to_dataset(d.time_data_list)
    
    return dataset


def create_test_noise_data(added_noise_level=0.1):
    '''Simulate a random-excitation test of a single 100 Hz mode.

    The DataSet holds one `TimeData` of 10 s at 10 kHz (100000 samples,
    two channels, units ``['N', 'm/s']``). Channel 0 is the input force:
    uniform white noise between -0.5 and 0.5 N. Channel 1 is the
    velocity it drives in the same structure as
    `create_test_impulse_data` (one mode at 100 Hz, 0.1 s decay time
    constant, modal constant 1000 /kg), plus uniform measurement noise.

    Args:
        added_noise_level (float): Half-width of the uniform noise added
            to channel 1 (default 0.1).

    Returns:
        dataset (DataSet): The simulated measurement, with test name
            ``'Synthesised data'``.
    '''
    settings = options.MySettings(fs=10000)
    N = int(10*1e4)
    time_axis = np.arange(N)/settings.fs
    
    time_data = np.zeros([N,2])
    x = np.random.rand(N) - 0.5
    y = _velocity_response(x, settings.fs, [(100.0, 0.1, 1000.0)])
    
    added_noise = added_noise_level*2*(np.random.rand(N)-0.5)
    time_data[:,0] = x
    time_data[:,1] = y + added_noise
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    timedata = datastructure.TimeData(time_axis,time_data,settings,timestamp=t, timestring=timestring, units=['N','m/s'], channel_cal_factors=[1,1], test_name='Synthesised data')
    
    dataset = datastructure.DataSet()
    dataset.add_to_dataset(timedata)
    
    return dataset
    

def create_test_impulse_data_nonlinear_v1(noise_level=0):
    '''Simulate an impulse test whose decay has two time constants.

    The DataSet holds one `TimeData` of 1 s at 10 kHz (10000 samples,
    two channels, units ``['N', 'm/s']``). Channel 0 is the hammer
    force: a unit-height raised-cosine pulse, 2 ms long, at the start of
    the record. Channel 1 is the velocity of two coincident 100 Hz modes
    with decay time constants 0.05 s and 0.2 s (modal constants 700 and
    300 /kg), so its envelope is close to ``0.7*exp(-t/0.05) +
    0.3*exp(-t/0.2)`` m/s: a decay that a single damping ratio cannot
    describe. The system is linear despite the name; the response is
    the force convolved with the modes' velocity impulse responses.

    Args:
        noise_level (float): Half-width of uniform random noise added to
            channel 1 (default 0, no noise).

    Returns:
        dataset (DataSet): The simulated measurement, with test name
            ``'Synthesised nonlinear data v1'``.
    '''
    settings = options.MySettings(fs=10000)
    N = int(1e4)
    time_axis = np.arange(N)/settings.fs
    
    time_data = np.zeros([N,2])
    force, impulse = _raised_cosine_pulse(N, settings.fs, 0.002)
    time_data[:,0] = force
    
    # Two coincident 100 Hz modes, fast and slow decays; the modal
    # constants make their free-decay amplitudes 0.7 and 0.3 m/s.
    y = _velocity_response(force, settings.fs,
                           [(100.0, 0.05, 0.7 / impulse), (100.0, 0.2, 0.3 / impulse)])
    
    y += noise_level*2*(np.random.rand(len(y)) - 0.5)
    
    time_data[:,1] = y
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    timedata = datastructure.TimeData(time_axis,time_data,settings,timestamp=t, timestring=timestring, units=['N','m/s'], channel_cal_factors=[1,1], test_name='Synthesised nonlinear data v1')
    
    dataset = datastructure.DataSet()
    dataset.add_to_dataset(timedata)
    
    return dataset


def create_test_impulse_data_nonlinear_v2(noise_level=0):
    '''Simulate an impulse test whose frequency falls as it decays.

    The DataSet holds one `TimeData` of 1 s at 10 kHz (10000 samples,
    two channels, units ``['N', 'm/s']``). Channel 0 is the hammer
    force: a unit-height raised-cosine pulse, 2 ms long, at the start of
    the record. Channel 1 decays as ``exp(-t/0.1)`` while
    its frequency glides from 200 Hz to 100 Hz along a tanh curve
    centred at 0.2 s with a 0.4 s time scale. This one is genuinely
    nonlinear, so it has no impulse response to drive with the pulse:
    channel 1 is that free decay written down directly, starting at
    t = 0. Use it for decay and sonogram analysis, not a TF fit.

    Args:
        noise_level (float): Half-width of uniform random noise added to
            channel 1 (default 0, no noise).

    Returns:
        dataset (DataSet): The simulated measurement, with test name
            ``'Synthesised nonlinear data v2'``.
    '''
    settings = options.MySettings(fs=10000)
    N = int(1e4)
    time_axis = np.arange(N)/settings.fs
    
    time_data = np.zeros([N,2])
    pulse_width = 0.002
    N_pulse = int(np.ceil(pulse_width*settings.fs))
    n = np.arange(N_pulse)
    pulse = 0.5*(1-np.cos(2*np.pi*n/N_pulse))
    time_data[n,0] = pulse
    
    f1 = 100   # Final frequency (Hz)
    f2 = 200  # Initial frequency (Hz)
    test_time_const = 0.1
    transition_time = 0.4  # Time scale for frequency transition
    transition_center = 0.2  # Center time of transition
    
    # Frequency varies from f2 to f1 using tanh transition
    freq_transition = 0.5 * (np.tanh((time_axis - transition_center) / transition_time) + 1)
    instantaneous_freq = f2 - (f2 - f1) * freq_transition
    
    # Calculate instantaneous phase
    phase = 2 * np.pi * np.cumsum(instantaneous_freq) / settings.fs
    
    # Response with exponential decay and frequency shift
    y = np.exp(-time_axis/test_time_const) * np.sin(phase)
    
    y += noise_level*2*(np.random.rand(len(y)) - 0.5)
    
    time_data[:,1] = y
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    timedata = datastructure.TimeData(time_axis,time_data,settings,timestamp=t, timestring=timestring, units=['N','m/s'], channel_cal_factors=[1,1], test_name='Synthesised nonlinear data v2')
    
    dataset = datastructure.DataSet()
    dataset.add_to_dataset(timedata)
    
    return dataset

def create_test_impulse_data_multi_harmonics(f1=100, noise_level=0.001):
    '''Simulate an impulse test with two families of closely spaced modes.

    The DataSet holds one `TimeData` of 1 s at 10 kHz (10000 samples,
    two channels, units ``['N', 'm/s']``). Channel 0 is a raised-cosine
    force pulse 0.5 ms long (unit height) at the start of the record.
    Channel 1 is the velocity of modes (decay time constant 0.1 s) at
    ``f1``, ``4*f1``, ``9*f1`` and ``16*f1`` (free-decay amplitudes 1,
    0.5, 0.3, 0.2 m/s) and at the same multiples of ``f2 = 1.03*f1``
    (0.8, 0.4, 0.25, 0.15 m/s), so each pair of modes is 3 % apart:
    the force convolved with their velocity impulse responses. Uniform
    noise is added to both channels.

    Args:
        f1 (float): Lowest frequency in Hz (default 100).
        noise_level (float): Half-width of the uniform noise added to
            both channels (default 0.001).

    Returns:
        dataset (DataSet): The simulated measurement, with test name
            ``'Synthesised multi-harmonic data'``.
    '''
    settings = options.MySettings(fs=10000)
    N = int(1e4)
    time_axis = np.arange(N)/settings.fs
    
    time_data = np.zeros([N,2])
    force, impulse = _raised_cosine_pulse(N, settings.fs, 0.0005)
    
    f2 = 1.03 * f1
    test_time_const = 0.1
    harmonics = [1, 4, 9, 16]
    amplitudes_1 = [1.0, 0.5, 0.3, 0.2]     # free-decay velocity, m/s
    amplitudes_2 = [0.8, 0.4, 0.25, 0.15]
    modes = ([(k * f1, test_time_const, a / impulse) for k, a in zip(harmonics, amplitudes_1)]
             + [(k * f2, test_time_const, a / impulse) for k, a in zip(harmonics, amplitudes_2)])
    y = _velocity_response(force, settings.fs, modes)
    
    # The noise is added after the response, so it is measurement noise on
    # the force channel, not force the structure felt.
    time_data[:,0] = force + noise_level*2*(np.random.rand(N) - 0.5)
    
    y += noise_level*2*(np.random.rand(len(y)) - 0.5)
    
    time_data[:,1] = y
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    timedata = datastructure.TimeData(time_axis,time_data,settings,timestamp=t, timestring=timestring, units=['N','m/s'], channel_cal_factors=[1,1], test_name='Synthesised multi-harmonic data')

    dataset = datastructure.DataSet()
    dataset.add_to_dataset(timedata)

    return dataset


#%% BLA (best linear approximation) test captures
def _bla_reference_filters(n_exc, n_resp, fs, f_lo, f_hi):
    """Build one distinct, well-conditioned digital filter per
    (excitation, response) pair for `create_test_bla_captures`.

    Each is a peaking biquad — a resonance at ``f0`` with a zero pair of
    the same natural frequency but heavier damping — so the magnitude
    tends to a finite gain at both ends of the excited band instead of
    rolling off. That keeps the dynamic range across the band to about
    15 dB, which is what makes a *relative* error tolerance meaningful
    at every excited bin (a plain resonance would fall 40 dB at the band
    edges and let output noise dominate the relative error there). The
    resonances are spread over the middle half of ``f_lo..f_hi`` and the
    pole damping varies per pair, so no two paths are alike and the
    frequency dependence is real rather than flat.

    Args:
        n_exc (int): Number of excitation (input) channels.
        n_resp (int): Number of response (output) channels.
        fs (float): Sample rate in Hz.
        f_lo (float): Lowest excited frequency in Hz.
        f_hi (float): Highest excited frequency in Hz.

    Returns:
        filters (list): ``n_exc`` lists of ``n_resp`` ``(b, a)`` digital
            filter coefficient tuples, indexed ``filters[q][r]``.
    """
    n_pairs = n_exc * n_resp
    filters = []
    for q in range(n_exc):
        row = []
        for r in range(n_resp):
            i = q * n_resp + r
            frac = 0.25 if n_pairs == 1 else 0.25 + 0.5 * i / (n_pairs - 1)
            f0 = f_lo + (f_hi - f_lo) * frac
            w0 = 2 * np.pi * f0
            zeta_p = 0.10 + 0.03 * (i % 4)      # pole damping (the peak)
            zeta_z = 0.5                        # zero damping (the floor)
            gain = 1.0 + 0.2 * i
            b, a = signal.bilinear([gain, gain * 2 * zeta_z * w0, gain * w0 ** 2],
                                   [1.0, 2 * zeta_p * w0, w0 ** 2], fs=fs)
            row.append((b, a))
        filters.append(row)
    return filters


def create_test_bla_captures(M=6, n_exc=2, n_resp=2, N=2048, P=4, t_periods=2,
                             fs=8192.0, k1=8, k2=200, seed=42, amp_rms=0.1,
                             cubic=0.0, noise_rms=1e-4):
    """Synthesise a complete BLA run against a known MISO system.

    Produces the ``M * n_exc`` captures of a Schoukens best-linear-
    approximation run in the canonical order
    ``[(m, e) for m in range(M) for e in range(n_exc)]``, ready to hand
    straight to `analysis.calculate_bla`. Every capture is a real
    `datastructure.TimeData` holding the excitation channels first
    (indices ``0 .. n_exc-1``) then the responses (``n_exc ..
    n_exc+n_resp-1``).

    The system is

    ``y_r[n] = sum_q (h_qr * x_q)[n] + cubic * (sum_q x_q[n])**3 + e_r[n]``

    where ``h_qr`` is a stable digital peaking biquad (see
    `_bla_reference_filters`), the cubic term is instantaneous — so it
    is exactly periodic like the excitation and therefore invisible to
    the period-to-period noise estimate, exactly as a real nonlinearity
    is — and ``e_r`` is white Gaussian output noise of rms
    ``noise_rms``, drawn independently for every capture. Excitations
    come from `acquisition.multisine_generator`, so the phase and
    scaling law here is the same one `analysis.calculate_bla`
    regenerates in commanded-x mode. The recorded excitation channels
    are NOISELESS: the method's noise model is output noise, and a
    clean x makes the measured-x and commanded-x paths comparable bit
    for bit.

    Filtering runs over the whole buffer including the ``t_periods``
    transient periods, which the analysis then discards — with the
    default geometry the slowest filter has decayed by more than 250 dB
    before the first kept period, so the kept data is periodic steady
    state to far below the noise floor.

    Args:
        M (int): Number of realisations (independent phase draws).
        n_exc (int): Number of excitation channels; also the number of
            experiments per realisation.
        n_resp (int): Number of response channels; independent of
            `n_exc` (non-square systems are supported).
        N (int): Samples in one multisine period.
        P (int): Steady-state periods kept per capture.
        t_periods (int): Transient periods discarded per capture.
        fs (float): Sample rate in Hz.
        k1 (int): First excited DFT bin.
        k2 (int): Last excited DFT bin.
        seed (int): Master seed for the phase draws and the noise.
        amp_rms (float): Per-channel excitation rms in volts.
        cubic (float): Coefficient of the instantaneous cubic
            distortion; 0 gives an exactly linear system.
        noise_rms (float): Standard deviation of the additive white
            output noise in volts.

    Returns:
        time_data_list (TimeDataList): The ``M * n_exc`` captures, each
            ``(t_periods + P) * N`` samples long, with units ``'V'`` for
            the excitations and ``'m/s/s'`` for the responses.
        run_spec (dict): The BlaRunSpec describing the run (measured-x
            mode, x channels ``0..n_exc-1``, response channels after
            them), ready for `analysis.calculate_bla`.
        G_true (np.ndarray): The exact frequency response of the
            reference filters at the excited bins, complex, shape
            ``(n_k, n_resp, n_exc)`` with ``n_k = k2 - k1 + 1``, from
            `scipy.signal.freqz` of the same coefficients.
    """
    from . import acquisition            # lazy: keeps import order simple

    fs = float(fs)
    k_bins = np.arange(int(k1), int(k2) + 1)
    filters = _bla_reference_filters(n_exc, n_resp, fs,
                                      k1 * fs / N, k2 * fs / N)

    # Exact truth: the DFT ratio of a periodic steady-state response is
    # the filter's frequency response at that bin, so freqz on the same
    # coefficients (worN in rad/sample: bin k <-> 2*pi*k/N) is the value
    # calculate_bla must return.
    w = 2 * np.pi * k_bins / N
    G_true = np.zeros((len(k_bins), n_resp, n_exc), dtype=complex)
    for q in range(n_exc):
        for r in range(n_resp):
            b, a = filters[q][r]
            G_true[:, r, q] = signal.freqz(b, a, worN=w)[1]

    settings = options.MySettings(
        device_driver='mock', fs=fs, channels=n_exc + n_resp,
        stored_time=(t_periods + P) * N / fs,
        output_device_driver='mock', output_channels=n_exc,
        output_fs=fs, output_VmaxSC=10.0)

    n_samples = (t_periods + P) * N
    time_axis = np.arange(n_samples) / fs
    units = ['V'] * n_exc + ['m/s/s'] * n_resp

    time_data_list = datastructure.TimeDataList()
    for m in range(M):
        for e in range(n_exc):
            spec = dict(n_samples=N, k1=int(k1), k2=int(k2), p_periods=P,
                        t_periods=t_periods, seed=int(seed), m=m, e=e,
                        n_exc=n_exc, amp_rms=amp_rms)
            _, x = acquisition.multisine_generator(settings, spec)

            block = np.zeros((n_samples, n_exc + n_resp))
            block[:, :n_exc] = x
            x_sum = x.sum(axis=1)
            # 9973 is an arbitrary fixed offset that keeps the noise
            # stream disjoint from the excitation's [seed, m] draw.
            rng = np.random.default_rng([int(seed), 9973, m, e])
            for r in range(n_resp):
                y = np.zeros(n_samples)
                for q in range(n_exc):
                    b, a = filters[q][r]
                    y += signal.lfilter(b, a, x[:, q])
                if cubic:
                    y += cubic * x_sum ** 3
                if noise_rms:
                    y += rng.normal(0.0, noise_rms, n_samples)
                block[:, n_exc + r] = y

            t = datetime.datetime.now()
            timestring = ('_' + str(t.year) + '_' + str(t.month) + '_'
                          + str(t.day) + '_at_' + str(t.hour) + '_'
                          + str(t.minute) + '_' + str(t.second))
            time_data_list += [datastructure.TimeData(
                time_axis, block, settings, timestamp=t,
                timestring=timestring, units=units,
                test_name='bla_test r{}e{}'.format(m, e))]

    run_spec = {
        'multisine': {'n_samples': int(N), 'k1': int(k1), 'k2': int(k2),
                      'p_periods': int(P), 't_periods': int(t_periods),
                      'seed': int(seed), 'amp_rms': float(amp_rms),
                      'n_exc': int(n_exc), 'M': int(M)},
        'x_mode': 'measured',
        'x_channels': list(range(n_exc)),
        'resp_channels': list(range(n_exc, n_exc + n_resp)),
        'fs': fs,
    }
    return time_data_list, run_spec, G_true