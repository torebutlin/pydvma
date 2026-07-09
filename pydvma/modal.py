# -*- coding: utf-8 -*-
"""
Created on Mon Aug 19 17:29:30 2019

@author: tb267
"""


from . import datastructure
from . import options

import numpy as np
from scipy import signal
from scipy import optimize
import copy

MESSAGE = ''

#%% single peak fit

def f_3dB(f,G0):
    
    ff = np.linspace(f[0],f[-1],np.max([len(f),1000]))
    GG = np.interp(ff,f,np.squeeze(G0))
    
    f=ff
    G0=GG
    
    
    fn0i = np.argmax(np.abs(G0))
    fn0 = f[fn0i]
    
    halfpower = np.max(np.abs(G0)) / np.sqrt(2)
    
    xi = np.where(np.squeeze(np.abs(G0)) > halfpower)[0]

    
    f1 = f[xi[0]]
    f2 = f[xi[-1]]

    
    df = f2-f1
    zn0 = df/2/fn0
    
    return fn0,zn0



def modal_fit_single_channel(tf_data,freq_range=None,channel=0,measurement_type='acc'):
    '''
    Fit modal parameters for a single mode to data within specified freq_range
    '''
    
    if freq_range is None:
        freq_range = tf_data.freq_axis[[0,-1]]
    
    
    f = tf_data.freq_axis
    selected_range = np.where((f > freq_range[0]) & (f < freq_range[1]))
    
    f = f[selected_range]
    
    #NEED GOOD INITIAL GUESS!
    G0 = tf_data.tf_data[selected_range,channel]
    
    fn0,zn0 = f_3dB(f,G0)
    
    
    
    an0 = np.max(np.abs(G0))*(2*np.pi*fn0)**2 * 2*zn0
    pn0 = 0
    Rk0 = np.max(np.abs(G0))/1e3
    Rm0 = np.max(np.abs(G0))*((2*np.pi*fn0)**2)/1e3
    
    
    #x0 = np.array([fn0,zn0,an0,pn0,Rk0,Rm0])
    x0 = np.concatenate(([fn0],[zn0],an0,pn0,Rk0,Rm0))
    
    bounds = ([freq_range[0],0,-np.inf,-np.pi/2,0,0],[freq_range[1],1,np.inf,np.pi/2,np.inf,np.inf])
#    bounds = ((-np.inf,np.inf),(freq_range[0],freq_range[1]),(0,np.inf),(-np.pi/2,np.pi/2),(-np.inf,np.inf),(-np.inf,np.inf))
    
    r = optimize.least_squares(f_residual,x0, bounds=bounds, max_nfev=1000, args=(f,G0,measurement_type))
#    r = optimize.minimize(f_residual,x0, bounds=bounds, method='SLSQP', args=(f,G0,measurement_type))
    print('')
    print('fn={:.4g} (Hz), zn={:.4g}, an={:.4g}, phase={:.4g} (deg)'.format(r.x[0],r.x[1],r.x[2],r.x[3]*180/np.pi))
    print('')
    if (np.abs(r.x[3])*180/np.pi > 60):
        print('Phase is significant, check ''measurement_type'' setting is correct')
    return r
    
    

def f_TF(x,f,measurement_type):

    fn = x[0]
    zn = x[1]
    an = x[2]
    pn = x[3]
#    R  = x[4] + 1j*x[5]
    R1 = x[4]
    R2 = x[5]
    
    wn = 2*np.pi*fn
    w = 2*np.pi*f
    
    
    if measurement_type == 'acc':
        p = 2
    elif measurement_type == 'vel':
        p = 1
    elif measurement_type == 'dsp':
        p = 0
    
    G = an*np.exp(1j*pn)/(wn**2 + 2j*wn*zn*w - w**2) + R1 - R2/(w**2)
    G = G*((1j*w)**p)
    
    return G



def f_residual(x,f,G0,measurement_type):
    
    G0 = np.squeeze(G0)
    G = f_TF(x,f,measurement_type)
        
    e = (G-G0)
    #e = np.abs(e)
    e = np.concatenate((np.real(e),np.imag(e)))
    
    
    return e



#%%
def f_TF_all_channels(x,f,measurement_type):

    N_tfs = int((len(x)-2)/4)
    
    fn = x[0]
    zn = x[1]
    an = x[2:2+N_tfs].reshape(1,N_tfs)
    pn = x[2+N_tfs:2+2*N_tfs].reshape(1,N_tfs)
#    R  = x[4] + 1j*x[5]
    R1 = x[2+2*N_tfs:2+3*N_tfs].reshape(1,N_tfs)
    R2 = x[2+3*N_tfs:2+4*N_tfs].reshape(1,N_tfs)
    
    wn = 2*np.pi*fn
    w = 2*np.pi*f
    w = w.reshape(len(w),1)
    
    
    if measurement_type == 'acc':
        p = 2
    elif measurement_type == 'vel':
        p = 1
    elif measurement_type == 'dsp':
        p = 0

    if w[0]==0:
        # avoid singularity at w=0
        w[0] = w[1]
    G = an*np.exp(1j*pn)/(wn**2 + 2j*wn*zn*w - w**2) + R1 - R2/(w**2)
    G = G*((1j*w)**p)
    
    return G


def f_residual_all_channels(x,f,G0,measurement_type):
    
    G = f_TF_all_channels(x,f,measurement_type)
        
    e = (G-G0)
    #e = np.abs(e)
    e = np.concatenate((np.real(e),np.imag(e)))
    e = e.reshape(np.size(e))
    
    return e

#%% MULTI-CHANNEL MODAL FIT
def modal_fit_all_channels(tf_data_list,freq_range=None,measurement_type='acc'):
    '''
    Fit modal parameters for a single mode to data within specified freq_range.
    
    Assumes all tf_data in tf_data_list have same frequency axes
    '''
    global MESSAGE
    
    if measurement_type == 'acc':
        p = 2
    elif measurement_type == 'vel':
        p = 1
    elif measurement_type == 'dsp':
        p = 0
    
    # Find out how many TFs in dataset
    N_tfs = 0
    for tf_data in tf_data_list:
        if tf_data.flag_modal_TF == False:
            N_tfs += len(tf_data.tf_data[0,:])

    if N_tfs == 0:
        raise ValueError(
            'modal_fit_all_channels needs at least one TfData that is '
            'not a modal reconstruction (flag_modal_TF == False); got '
            '{} item(s), none usable.'.format(len(tf_data_list))
        )

    if freq_range is None:
        freq_range = tf_data_list[0].freq_axis[[0,-1]]
    
    # get selected frequency axis
    f = tf_data_list[0].freq_axis
    selected_range = np.where((f > freq_range[0]) & (f < freq_range[1]))
    
    f = f[selected_range]
    
    # compile transfer functions into single array, and get initial guesses
    G0 = np.zeros((len(f),N_tfs),dtype=complex)
    fn0 = np.zeros(N_tfs)
    zn0 = np.zeros(N_tfs)
    counter = -1
    for tf_data in tf_data_list:
        if tf_data.flag_modal_TF == False:
            for n_chan in range(len(tf_data.tf_data[0,:])):
                counter += 1
                G0[:,counter] = tf_data.tf_data[selected_range,n_chan] * tf_data.channel_cal_factors[n_chan]
                fn0[counter],zn0[counter] = f_3dB(f,G0[:,counter])
            

    # initial global guess for fn0,zn0 discarding any outliers
    fn0 = np.median(fn0)
    zn0 = np.median(zn0)
    fn0i = np.argmin(np.abs(f - fn0))
    
    
    # initial guesses for each channel
    an0 = np.zeros(N_tfs)
    pn0 = np.zeros(N_tfs)
    Rk0 = np.zeros(N_tfs)
    Rm0 = np.zeros(N_tfs)
    id_link = []
    counter = -1
    for tf_data in tf_data_list:
        if tf_data.flag_modal_TF == False:
            id_link += [tf_data.id_link]
            for n_chan in range(len(tf_data.tf_data[0,:])):
                counter += 1
                an0[counter] = np.max(np.abs(G0[:,counter]))*(2*np.pi*fn0)**(2-p) * 2*zn0
    #            an0[counter] = an0[counter] * np.sign(np.real(G0[fn0i,counter] / ((2j*np.pi*fn0)**p)))
                an0[counter] = an0[counter] * np.sign(-np.imag(G0[fn0i,counter] / ((1j)**p)))
                
                pn0[counter] = 0
                Rk0[counter] = np.max(np.abs(G0[:,counter]))/1e6
                Rm0[counter] = np.max(np.abs(G0[:,counter]))*((2*np.pi*fn0)**2)/1e6
    
    x0 = np.concatenate(([fn0],[zn0],an0,pn0,Rk0,Rm0))
    
    
    # bounds
    B_fn = freq_range
    B_zn = [0,1]
    B_an = np.zeros((N_tfs,2))
    B_an[:,0] = -np.inf
    B_an[:,1] =  np.inf
    B_pn = np.zeros((N_tfs,2))
    B_pn[:,0] = -np.pi/2
    B_pn[:,1] =  np.pi/2
    B_rk = np.zeros((N_tfs,2))
    B_rk[:,0] = 0
    B_rk[:,1] = np.inf
    B_rm = np.copy(B_rk)
    
    lower_bounds = np.concatenate(([B_fn[0]],[B_zn[0]],B_an[:,0],B_pn[:,0],B_rk[:,0],B_rm[:,0]))
    upper_bounds = np.concatenate(([B_fn[1]],[B_zn[1]],B_an[:,1],B_pn[:,1],B_rk[:,1],B_rm[:,1]))
    
    bounds = (lower_bounds,upper_bounds)
    
    r = optimize.least_squares(f_residual_all_channels,x0, bounds=bounds, max_nfev=1000, args=(f,G0,measurement_type))
    
    settings = tf_data_list[0].settings
    test_name = tf_data_list[0].test_name
    m = datastructure.ModalData(r.x, settings=settings, id_link=id_link, test_name=test_name)

    fn,zn,an,pn,rk,rm = unpack(r.x)

#    with np.printoptions(precision=3, suppress=True):
    MESSAGE = 'fn={:.2f} (Hz), zn={:.3g}, Qn = 1/(2 zn) = {:.1f}\n\n'.format(fn,zn,1/2/zn)
    MESSAGE += 'an={}\n\n'.format(np.array2string(an,precision=3))
    MESSAGE += 'pn={} deg\n\n'.format(np.array2string(pn*180/np.pi,precision=2))
    print(MESSAGE)
    if np.any(np.abs(pn)*180/np.pi > 60):
        MESSAGE += '\nPhase is significant, check ''TF type'' setting is correct.\n'
        print(MESSAGE)
        
    # Check quality of fit
    e = f_residual_all_channels(r.x,f,G0,measurement_type)
    G0rms = np.mean(np.abs(G0)**2)
    erms = np.mean(np.abs(e)**2)
    e_rel = erms/G0rms
    if e_rel > 0.1:
        MESSAGE += '\nPoor quality fit: try adjusting frequency range.\n'
        print(MESSAGE)

    return m
    
#%%% Reconstruction
def unpack(x):
    # unpacks modal parameters into set of variables
    N_tfs = int((len(x)-2)/4)
    
    fn = x[0]
    zn = x[1]
    an = x[2:2+N_tfs]
    pn = x[2+N_tfs:2+2*N_tfs]
    rk = x[2+2*N_tfs:2+3*N_tfs]
    rm = x[2+3*N_tfs:2+4*N_tfs]
    
    return fn,zn,an,pn,rk,rm

def unpack_matrix(X):
    '''
    Unpack a stacked modal matrix ``X`` (one packed mode per row,
    ``[fn, zn, an*N, pn*N, rk*N, rm*N]``) into per-parameter arrays.

    Robust to an EMPTY model: a ``(0, 2+4*N)`` matrix (every mode deleted)
    returns zero-length ``fn``/``zn`` and ``(0, N)`` ``an``/``pn``/``rk``/``rm``
    instead of raising. The channel count is read from the column count
    (``X.shape[1]``), NOT by indexing row 0 — indexing ``X[0, :]`` on an
    emptied ``(0, 6)`` matrix is exactly what crashed
    ``ModalData.delete_mode`` when the last mode was removed (the round-4
    "Fit -> Reject" IndexError, also on Qt's Reject path).
    '''
    X = np.atleast_2d(X)
    N_tfs = int((X.shape[1]-2)/4)

    fn = X[:,0]
    zn = X[:,1]
    an = X[:,2:2+N_tfs]
    pn = X[:,2+N_tfs:2+2*N_tfs]
    rk = X[:,2+2*N_tfs:2+3*N_tfs]
    rm = X[:,2+3*N_tfs:2+4*N_tfs]

    return fn,zn,an,pn,rk,rm
    
def pack(fn,zn,an,pn,rk,rm):
    # packs modal parameters into single variable for optimisation
    x = np.concatenate(([fn],[zn],an,pn,rk,rm))
    return x
    

def reconstruct_transfer_function(modal_data,f,measurement_type='acc'):
    '''
    Reconstructs transfer functions from modal_data and returns TfData object.
    Includes the per-channel local residual terms (rk, rm). Does not modify
    modal_data.
    '''
    G = 0
    for n_row in range(len(modal_data.M[:,0])):
        xn = modal_data.M[n_row,:]
        G += f_TF_all_channels(xn,f,measurement_type=measurement_type)

    # own copy: the returned TfData must not share (or mutate) the
    # ModalData's settings object
    settings = copy.copy(modal_data.settings)
    settings.channels = modal_data.channels
    tf_data = datastructure.TfData(f,G,None,settings,units=modal_data.units,channel_cal_factors=None,id_link=modal_data.id_link,test_name=modal_data.test_name)
    tf_data.flag_modal_TF = True
    return tf_data

#%% GLOBAL LINEAR RE-ESTIMATION (round-7g)

def _measurement_power(measurement_type):
    '''The `(jw)^p` exponent for 'dsp' (0) / 'vel' (1) / 'acc' (2).'''
    return {'dsp': 0, 'vel': 1, 'acc': 2}[measurement_type]


def _modes_band(M, f_axis):
    '''Default estimation/refinement band: the modes' fn span padded so each
    peak's half-power skirts are included (the `modal_refine` convention),
    clamped to the measured axis. Returns ``[lo, hi]`` in Hz.'''
    fn_fit = M[:, 0]
    zn_fit = M[:, 1]
    lo_fn, hi_fn = float(np.min(fn_fit)), float(np.max(fn_fit))
    span = hi_fn - lo_fn
    bw = float(np.max(fn_fit * np.clip(zn_fit, 0.0, None))) if fn_fit.size else 0.0
    pad = max(0.25 * span, 5.0 * bw, 0.05 * max(hi_fn, 1.0))
    return [max(float(f_axis[0]), lo_fn - pad),
            min(float(f_axis[-1]), hi_fn + pad)]


def _measured_columns(tf_data_list, sel):
    '''Stack every measured (non-reconstruction) TF column over the ``sel``
    frequency indices, cal-scaled — the `modal_fit_all_channels` /
    `modal_refine` G0 assembly, shared. Returns ``(len(sel), n_cols)``.

    NB the shared-pole machinery assumes every set shares ONE frequency axis
    (``tf_data_list[0].freq_axis``) — the same assumption the fitters make.'''
    cols = []
    for tf_data in tf_data_list:
        if getattr(tf_data, 'flag_modal_TF', False):
            continue
        for n_chan in range(tf_data.tf_data.shape[1]):
            cols.append(tf_data.tf_data[sel, n_chan] * tf_data.channel_cal_factors[n_chan])
    if len(cols) == 0:
        raise ValueError('needs at least one measured (non-reconstruction) TF.')
    return np.array(cols, dtype=complex).T


def estimate_global_constants(fn, zn, f, G0, measurement_type='acc'):
    '''
    Re-estimate the COMPLEX modal constants and per-channel GLOBAL residual
    terms for FIXED poles — the linear half of the global fit (round-7g).

    With the poles ``{fn, zn}`` held fixed, the modal model is LINEAR in the
    remaining parameters, so they solve in one least-squares with no
    convergence risk. In receptance space (measured columns divided by
    ``(jw)^p``):

        ``G0_c/(jw)^p  ~=  sum_n A_nc * phi_n(w)  +  RH_c  -  RL_c/w^2``

    with ``phi_n = 1/(wn^2 + 2j*wn*zn*w - w^2)``. ``RH`` (stiffness-like
    constant) and ``RL/w^2`` (mass-like) are ONE pair of GLOBAL residues per
    channel, standing for above-band and below-band modes respectively —
    unlike the local fits' per-mode ``rk``/``rm``, which are mutually
    redundant in a joint model (each mode's residues can impersonate a
    neighbour's tail: flat cost directions that let refinement drag poles
    without penalty). The constants that emerge are the GLOBALLY consistent
    ones: neighbour interaction is explained by the neighbours themselves,
    so any remaining phase in ``A`` is genuine mode complexity, not
    circle-rotation leakage from nearby modes.

    Args:
        fn (array_like): pole natural frequencies (Hz), length N — held
            fixed during the solve
        zn (array_like): pole damping ratios, length N — held fixed
        f (np.ndarray): frequency axis (Hz); rows with ``f <= 0`` are
            excluded (the ``1/w^2`` term and the ``(jw)^p`` division are
            singular at DC)
        G0 (np.ndarray): measured complex columns, shape
            ``(len(f), n_cols)``, cal-scaled
        measurement_type (str): 'acc' | 'vel' | 'dsp' (the ``(jw)^p``
            convention)

    Returns ``(A, RH, RL, cost)``: ``A`` complex ``(N, n_cols)``, ``RH`` and
    ``RL`` complex ``(n_cols,)``, and ``cost = 0.5*sum(|model - G0|^2)`` over
    the used rows in MEASURED space (identical to the stacked real/imag
    least-squares cost convention used by ``modal_refine``).
    '''
    fn = np.atleast_1d(np.asarray(fn, dtype=np.float64))
    zn = np.atleast_1d(np.asarray(zn, dtype=np.float64))
    f = np.asarray(f, dtype=np.float64)
    G0 = np.atleast_2d(np.asarray(G0, dtype=complex))
    p = _measurement_power(measurement_type)

    mask = f > 0
    w = (2.0 * np.pi * f[mask]).reshape(-1, 1)
    y = G0[mask, :] / ((1j * w) ** p)

    wn = (2.0 * np.pi * fn).reshape(1, -1)
    phi = 1.0 / (wn ** 2 + 2j * wn * zn.reshape(1, -1) * w - w ** 2)
    B = np.hstack([phi, np.ones_like(w, dtype=complex), -1.0 / w ** 2])

    x, *_ = np.linalg.lstsq(B, y, rcond=None)
    A = x[:len(fn), :]
    RH = x[len(fn), :]
    RL = x[len(fn) + 1, :]

    model = (B @ x) * ((1j * w) ** p)
    cost = 0.5 * float(np.sum(np.abs(model - G0[mask, :]) ** 2))
    return A, RH, RL, cost


def _evaluate_global_model(fn, zn, A, RH, RL, f, measurement_type='acc'):
    '''Evaluate the re-estimated global model on axis ``f`` (any axis — the
    reconstruction axis need not match the estimation axis). Guards the
    ``w = 0`` singularity the way ``f_TF_all_channels`` does (first bin
    borrows the second bin's frequency).'''
    fn = np.atleast_1d(np.asarray(fn, dtype=np.float64))
    zn = np.atleast_1d(np.asarray(zn, dtype=np.float64))
    p = _measurement_power(measurement_type)
    w = (2.0 * np.pi * np.asarray(f, dtype=np.float64)).reshape(-1, 1).copy()
    if w.size and w[0] == 0:
        w[0] = w[1] if w.size > 1 else 1.0
    wn = (2.0 * np.pi * fn).reshape(1, -1)
    phi = 1.0 / (wn ** 2 + 2j * wn * zn.reshape(1, -1) * w - w ** 2)
    G = phi @ np.atleast_2d(A) + RH.reshape(1, -1) - RL.reshape(1, -1) / w ** 2
    return G * ((1j * w) ** p)


def reconstruct_transfer_function_global(modal_data,f,measurement_type='acc',
                                         tf_data_list=None):
    '''
    Reconstructs the GLOBAL (whole-model) transfer functions from modal_data
    and returns a TfData object. Does not modify modal_data.

    With ``tf_data_list`` (the measured TFs) the reconstruction uses the
    round-7g GLOBAL RE-ESTIMATION: the modal constants (amplitude AND phase,
    per channel) plus one pair of global residues per channel (``RH`` const +
    ``RL/w^2``) are re-solved linearly against the measured data over the
    modes' padded band, with the stored poles held fixed (see
    `estimate_global_constants` — this removes the double-counting of
    neighbour interactions that each mode's LOCALLY-fitted phase absorbs).

    Without ``tf_data_list`` (e.g. a ModalData loaded on its own) the legacy
    behaviour is kept: the stored per-mode rows are summed with their local
    residual terms (rk, rm) zeroed.
    '''
    M = np.atleast_2d(modal_data.M)
    N_tfs = int((M.shape[1]-2)/4)

    if tf_data_list is not None:
        f_axis = np.asarray(tf_data_list[0].freq_axis, dtype=np.float64)
        band = _modes_band(M, f_axis)
        sel = np.where((f_axis > band[0]) & (f_axis < band[1]))[0]
        if sel.size < max(4, M.shape[0] + 2):
            sel = np.arange(f_axis.size)
        G0 = _measured_columns(tf_data_list, sel)
        if G0.shape[1] == N_tfs:
            A, RH, RL, _ = estimate_global_constants(
                M[:, 0], M[:, 1], f_axis[sel], G0, measurement_type)
            G = _evaluate_global_model(M[:, 0], M[:, 1], A, RH, RL, f,
                                       measurement_type)
            settings = copy.copy(modal_data.settings)
            settings.channels = modal_data.channels
            tf_data = datastructure.TfData(f,G,None,settings,units=modal_data.units,channel_cal_factors=None,id_link=modal_data.id_link,test_name=modal_data.test_name)
            tf_data.flag_modal_TF = True
            return tf_data
        # channel mismatch (defensive): fall through to the legacy sum

    G = 0
    for n_row in range(M.shape[0]):
        # copy: zeroing through a view would permanently wipe the stored
        # residual columns of modal_data.M
        xn = M[n_row,:].copy()
        xn[2+2*N_tfs:] = 0 #don't want local residual fits for global fits - i.e. rk and rm
        G += f_TF_all_channels(xn,f,measurement_type=measurement_type)

    settings = copy.copy(modal_data.settings)
    settings.channels = modal_data.channels
    tf_data = datastructure.TfData(f,G,None,settings,units=modal_data.units,channel_cal_factors=None,id_link=modal_data.id_link,test_name=modal_data.test_name)
    tf_data.flag_modal_TF = True
    return tf_data


#%% SIMULTANEOUS MULTI-MODE REFINEMENT
# (The pre-round-7g whole-parameter-set residual `_f_residual_refine` is gone:
# refinement now projects the linear parameters out — see `modal_refine`.)


def modal_refine(modal_data, tf_data_list, freq_range=None, measurement_type='acc'):
    '''
    Simultaneously refine ALL modes in ``modal_data`` against the measured
    transfer functions, seeded from the current fit.

    Round-7g VARIABLE-PROJECTION rebuild: the nonlinear search runs over the
    POLES ONLY (``[fn, zn]`` per mode — 2N parameters), and at every candidate
    pole set the modal constants + per-channel GLOBAL residues are re-solved
    linearly (`estimate_global_constants`). The previous refine optimised the
    whole packed parameter set including every mode's LOCAL residual terms
    (rk, rm) — which are mutually redundant in a joint model (one mode's
    residues can impersonate a neighbour's tail), creating flat directions in
    the cost surface along which a pole could drift far while the residues
    compensated, "improving" the residual as it went. Projecting the linear
    parameters out removes those flat directions and makes the pole search
    far stiffer on overlapping-mode data (e.g. instrument bodies).

    Like ``modal_fit_all_channels``, the measured TFs are cal-scaled when
    building the target ``G0``, so the seed and the refined result live in
    the SAME parameter space. ``freq_range`` defaults to the modes' padded
    band (see `_modes_band`), clamped to the measured axis.

    The refined ``M`` rows carry the poles plus the GLOBALLY re-estimated
    constants (``an = |A|``, ``pn = arg A``) with the per-mode local residues
    ZEROED — after a joint refine the local-window residues are meaningless,
    and the global reconstruction re-estimates its own residues from the
    measured data anyway (`reconstruct_transfer_function_global`).

    Convergence / non-convergence is REPORTED, never enforced. Returns
    ``(ModalData, info)`` with
    ``info = {'converged': bool, 'cost_before': float, 'cost_after': float}``;
    both costs are the SAME projected-model cost (linear solve at the seed
    poles vs at the refined poles), so directly comparable. The refined model
    and info are returned even when not converged — the CALLER decides
    whether to keep or revert (the webui auto-reverts on
    ``converged == False``). On a pathological failure the seed model is
    handed back unchanged with ``converged == False``.

    Mac-runnable, no hardware. Mirrors ``modal_fit_all_channels`` for
    ``settings`` / ``id_link`` / ``test_name`` provenance.
    '''
    if modal_data is None or np.size(np.atleast_2d(modal_data.M)) == 0:
        raise ValueError('modal_refine needs a ModalData with at least one mode.')

    M = np.atleast_2d(modal_data.M).astype(np.float64)
    n_modes, row_len = M.shape
    N_tfs = int((row_len - 2) / 4)

    f_axis = np.asarray(tf_data_list[0].freq_axis, dtype=np.float64)

    # default window: the modes' band, padded by the widest half-power skirt
    if freq_range is None:
        freq_range = _modes_band(M, f_axis)
    freq_range = [max(float(f_axis[0]), float(freq_range[0])),
                  min(float(f_axis[-1]), float(freq_range[1]))]

    sel = np.where((f_axis > freq_range[0]) & (f_axis < freq_range[1]))[0]
    if sel.size < max(4, 2 * n_modes + 2):
        # too narrow to constrain the parameters — refine over the full axis
        sel = np.arange(f_axis.size)
    f = f_axis[sel]

    # compile the measured TFs (cal-scaled) into G0, as modal_fit_all_channels does
    try:
        G0 = _measured_columns(tf_data_list, sel)
    except ValueError:
        raise ValueError('modal_refine needs at least one measured (non-reconstruction) TF.')
    if G0.shape[1] != N_tfs:
        raise ValueError(
            'modal_refine: measured TF channel count ({}) does not match the '
            'modal model channel count ({}).'.format(G0.shape[1], N_tfs))

    # ---- variable projection: poles nonlinear, constants/residues linear ----
    def residual(x):
        fn = x[0::2]
        zn = x[1::2]
        A, RH, RL, _ = estimate_global_constants(fn, zn, f, G0, measurement_type)
        model = _evaluate_global_model(fn, zn, A, RH, RL, f, measurement_type)
        e = model - G0
        return np.concatenate((np.real(e), np.imag(e))).reshape(-1)

    x0 = np.empty(2 * n_modes)
    x0[0::2] = M[:, 0]
    x0[1::2] = M[:, 1]
    lower = np.empty_like(x0)
    upper = np.empty_like(x0)
    lower[0::2] = f_axis[0]
    upper[0::2] = f_axis[-1]
    lower[1::2] = 0.0
    upper[1::2] = 1.0
    x0 = np.clip(x0, lower, upper)

    # Pathological measured data (e.g. a NaN sample) makes the inner linear
    # solve raise rather than merely returning a non-finite residual — treat
    # both the same way: report non-convergence, never raise.
    try:
        cost_before = 0.5 * float(np.sum(residual(x0) ** 2))
    except Exception:
        cost_before = float('nan')

    if not np.isfinite(cost_before):
        x_ref = x0
        cost_after = cost_before
        success = False
    else:
        try:
            r = optimize.least_squares(residual, x0, bounds=(lower, upper),
                                       max_nfev=2000)
            x_ref = r.x
            cost_after = float(r.cost)
            success = bool(r.success)
        except Exception:
            # pathological input — hand back the seed unchanged, not converged
            x_ref = x0
            cost_after = cost_before
            success = False

    converged = bool(success and np.isfinite(cost_after)
                     and cost_after <= cost_before * (1.0 + 1e-9))

    # Rebuild M rows: refined poles + globally re-estimated constants; local
    # residues zeroed (see docstring). On failure this reproduces the seed
    # poles with re-projected constants — still a valid, comparable model,
    # and the caller reverts anyway when converged is False.
    fn_ref = x_ref[0::2]
    zn_ref = x_ref[1::2]
    try:
        A, RH, RL, _ = estimate_global_constants(fn_ref, zn_ref, f, G0, measurement_type)
    except Exception:
        A = (M[:, 2:2 + N_tfs] * np.exp(1j * M[:, 2 + N_tfs:2 + 2 * N_tfs]))

    settings = tf_data_list[0].settings
    test_name = tf_data_list[0].test_name
    id_link = [tf.id_link for tf in tf_data_list
               if not getattr(tf, 'flag_modal_TF', False)]
    m_ref = datastructure.ModalData(settings=settings, id_link=id_link, test_name=test_name)
    A = np.atleast_2d(A)
    for i in range(n_modes):
        row = pack(fn_ref[i], zn_ref[i],
                   np.abs(A[i, :]), np.angle(A[i, :]),
                   np.zeros(N_tfs), np.zeros(N_tfs))
        m_ref.add_mode(row)

    info = {'converged': converged,
            'cost_before': float(cost_before),
            'cost_after': float(cost_after)}
    return m_ref, info