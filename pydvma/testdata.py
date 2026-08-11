# -*- coding: utf-8 -*-
"""
Created on Mon Aug 27 17:08:42 2018

@author: tb267
"""

from . import options
from . import datastructure

import numpy as np
import scipy.signal as signal
import datetime


    

#%% Create test data
def create_test_impulse_data(noise_level=0.0):
    '''
    Creates example time domain data simulating impulse hammer test
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
    
    test_freq = 100
    test_time_const = 0.1
    y = np.exp(-time_axis/test_time_const) * np.sin(2*np.pi*test_freq*time_axis)
    
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
    '''
    Creates ensemble of example time domain data simulating impulse hammer tests
    '''
    dataset = datastructure.DataSet()
    for n in range(N_ensemble):
        d = create_test_impulse_data(noise_level=noise_level)
        dataset.add_to_dataset(d.time_data_list)
    
    return dataset


def create_test_noise_data(added_noise_level=0.1):
    '''
    Creates example time domain data simulating noise input test
    '''
    settings = options.MySettings(fs=10000)
    N = int(10*1e4)
    time_axis = np.arange(N)/settings.fs
    
    time_data = np.zeros([N,2])
    x = np.random.rand(N) - 0.5
    test_freq = 100
    test_time_const = 0.1
    g = np.exp(-time_axis/test_time_const) * np.sin(2*np.pi*test_freq*time_axis)
    y = np.convolve(x,g)
    y = y[0:len(x)]
    
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
    '''
    Creates example time domain data simulating impulse hammer test
    with double exponential decay (two time constants)
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
    
    test_freq = 100
    test_time_const_1 = 0.05  # Fast decay component
    test_time_const_2 = 0.2   # Slow decay component
    amplitude_1 = 0.7         # Amplitude of fast component
    amplitude_2 = 0.3         # Amplitude of slow component
    
    # Double exponential decay with constant frequency
    y = (amplitude_1 * np.exp(-time_axis/test_time_const_1) + 
            amplitude_2 * np.exp(-time_axis/test_time_const_2)) * np.sin(2*np.pi*test_freq*time_axis)
    
    y += noise_level*2*(np.random.rand(len(y)) - 0.5)
    
    time_data[:,1] = y
    
    t = datetime.datetime.now()
    timestring = '_'+str(t.year)+'_'+str(t.month)+'_'+str(t.day)+'_at_'+str(t.hour)+'_'+str(t.minute)+'_'+str(t.second)
    
    timedata = datastructure.TimeData(time_axis,time_data,settings,timestamp=t, timestring=timestring, units=['N','m/s'], channel_cal_factors=[1,1], test_name='Synthesised nonlinear data v1')
    
    dataset = datastructure.DataSet()
    dataset.add_to_dataset(timedata)
    
    return dataset


def create_test_impulse_data_nonlinear_v2(noise_level=0):
    '''
    Creates example time domain data simulating impulse hammer test
    with exponential decay and frequency shifting from f2 to f1 using tanh transition
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
    '''
    Creates example time domain data simulating impulse hammer test
    with response containing harmonics at f1, 4f1, 9f1, 16f1 and f2, 4f2, 9f2, 16f2
    where f2 = 1.03 * f1
    '''
    settings = options.MySettings(fs=10000)
    N = int(1e4)
    time_axis = np.arange(N)/settings.fs
    
    time_data = np.zeros([N,2])
    pulse_width = 0.0005
    N_pulse = int(np.ceil(pulse_width*settings.fs))
    n = np.arange(N_pulse)
    pulse = 0.5*(1-np.cos(2*np.pi*n/N_pulse))
    time_data[n,0] = pulse
    time_data[:,0] += noise_level*2*(np.random.rand(N) - 0.5)
    
    f2 = 1.03 * f1
    test_time_const = 0.1
    
    # Create response with multiple harmonics
    y = np.zeros_like(time_axis)
    
    # First set of harmonics: f1, 4f1, 9f1, 16f1
    harmonics_1 = [1, 4, 9, 16]
    amplitudes_1 = [1.0, 0.5, 0.3, 0.2]  # Decreasing amplitudes
    
    for harmonic, amplitude in zip(harmonics_1, amplitudes_1):
        freq = harmonic * f1
        y += amplitude * np.exp(-time_axis/test_time_const) * np.sin(2*np.pi*freq*time_axis)
    
    # Second set of harmonics: f2, 4f2, 9f2, 16f2
    harmonics_2 = [1, 4, 9, 16]
    amplitudes_2 = [0.8, 0.4, 0.25, 0.15]  # Slightly different amplitudes
    
    for harmonic, amplitude in zip(harmonics_2, amplitudes_2):
        freq = harmonic * f2
        y += amplitude * np.exp(-time_axis/test_time_const) * np.sin(2*np.pi*freq*time_axis)
    
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

    Returns a list of ``n_exc`` lists of ``n_resp`` ``(b, a)`` digital
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

    Returns a tuple ``(time_data_list, run_spec, G_true)``: the list of
    ``M * n_exc`` `datastructure.TimeData` captures; the BlaRunSpec dict
    describing the run (measured-x mode, x channels ``0..n_exc-1``,
    response channels after them); and the exact frequency response of
    the reference filters at the excited bins, shape
    ``(n_k, n_resp, n_exc)`` complex, from `scipy.signal.freqz` of the
    same coefficients.
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