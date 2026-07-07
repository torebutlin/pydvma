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

def reconstruct_transfer_function_global(modal_data,f,measurement_type='acc'):
    '''
    Reconstructs transfer functions from modal_data and returns TfData object.
    Excludes the per-channel local residual terms (rk, rm) — only the modal
    contributions are summed, as wanted for global fits. Does not modify
    modal_data.
    '''
    G = 0
    N_tfs = int((len(modal_data.M[0,:])-2)/4)
    for n_row in range(len(modal_data.M[:,0])):
        # copy: zeroing through a view would permanently wipe the stored
        # residual columns of modal_data.M
        xn = modal_data.M[n_row,:].copy()
        xn[2+2*N_tfs:] = 0 #don't want local residual fits for global fits - i.e. rk and rm
        G += f_TF_all_channels(xn,f,measurement_type=measurement_type)

    settings = copy.copy(modal_data.settings)
    settings.channels = modal_data.channels
    tf_data = datastructure.TfData(f,G,None,settings,units=modal_data.units,channel_cal_factors=None,id_link=modal_data.id_link,test_name=modal_data.test_name)
    tf_data.flag_modal_TF = True
    return tf_data


#%% SIMULTANEOUS MULTI-MODE REFINEMENT
def _f_residual_refine(x_flat, n_modes, row_len, f, G0, measurement_type):
    '''
    Least-squares residual for simultaneous multi-mode refinement.

    ``x_flat`` is the ``n_modes`` packed mode rows (each of length
    ``row_len = 2 + 4*N_tfs``) concatenated row-major (i.e. ``M.ravel()``).
    The model TF is the SUM over modes of ``f_TF_all_channels`` — each mode's
    modal contribution PLUS its per-channel local residual terms (rk, rm) —
    matching ``reconstruct_transfer_function``. Returns the real-then-imag
    flattened error ``model - G0`` (length ``2*len(f)*N_tfs``).
    '''
    rows = x_flat.reshape(n_modes, row_len)
    G = np.zeros_like(G0)
    for r in range(n_modes):
        G = G + f_TF_all_channels(rows[r], f, measurement_type)
    e = G - G0
    e = np.concatenate((np.real(e), np.imag(e)))
    return e.reshape(np.size(e))


def modal_refine(modal_data, tf_data_list, freq_range=None, measurement_type='acc'):
    '''
    Simultaneously refine ALL modes in ``modal_data`` against the measured
    transfer functions, seeded from the current fit.

    Individual modes are typically fitted in isolation or in small peak-split
    groups (``modal_fit_all_channels`` / the webui Fit 1/2/3 flow), so
    neighbouring modes' skirts bias each other. This runs a single
    ``scipy.optimize.least_squares`` over the WHOLE packed parameter set
    (every mode's ``[fn, zn, an*N, pn*N, rk*N, rm*N]`` row, seeded from
    ``modal_data.M``), letting all modes move together against the summed
    reconstruction model (``_f_residual_refine``).

    Like ``modal_fit_all_channels``, the measured TFs are scaled by their
    ``channel_cal_factors`` when building the target ``G0``, so the seed
    ``modal_data.M`` (produced by that fitter) and the refined result live in
    the SAME cal-scaled parameter space and remain directly comparable.

    ``freq_range`` (``[lo, hi]`` Hz) defaults to the span of the fitted natural
    frequencies padded so each peak's half-power skirts are included
    (``max(0.25*span, 5*max(fn*zn), 5% of the top fn)``), clamped to the
    measured axis. Narrowing to the modes' band converges more reliably than
    the full axis (out-of-band data the N-mode model cannot represent would
    otherwise dominate the cost).

    Convergence / non-convergence is REPORTED, never enforced here. Returns
    ``(ModalData, info)`` where ``info`` is
    ``{'converged': bool, 'cost_before': float, 'cost_after': float}``.
    ``converged`` is ``least_squares`` success AND the refined cost not worse
    than the seed cost (both are ``0.5*sum(residual**2)`` of the same
    residual, so directly comparable). Per the contract, the refined
    ModalData and info are returned EVEN WHEN the fit did not improve or did
    not converge — the CALLER decides whether to keep or revert (the webui
    auto-reverts to the pre-refine model on ``converged == False``). On a
    pathological ``least_squares`` failure the seed model is returned unchanged
    with ``converged == False``.

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
        fn_fit = M[:, 0]
        zn_fit = M[:, 1]
        lo_fn, hi_fn = float(np.min(fn_fit)), float(np.max(fn_fit))
        span = hi_fn - lo_fn
        bw = float(np.max(fn_fit * np.clip(zn_fit, 0.0, None))) if fn_fit.size else 0.0
        pad = max(0.25 * span, 5.0 * bw, 0.05 * max(hi_fn, 1.0))
        freq_range = [lo_fn - pad, hi_fn + pad]
    freq_range = [max(float(f_axis[0]), float(freq_range[0])),
                  min(float(f_axis[-1]), float(freq_range[1]))]

    sel = np.where((f_axis > freq_range[0]) & (f_axis < freq_range[1]))[0]
    if sel.size < max(4, row_len):
        # too narrow to constrain the parameters — refine over the full axis
        sel = np.arange(f_axis.size)
    f = f_axis[sel]

    # compile the measured TFs (cal-scaled) into G0, as modal_fit_all_channels does
    cols = []
    for tf_data in tf_data_list:
        if getattr(tf_data, 'flag_modal_TF', False):
            continue
        for n_chan in range(tf_data.tf_data.shape[1]):
            cols.append(tf_data.tf_data[sel, n_chan] * tf_data.channel_cal_factors[n_chan])
    if len(cols) == 0:
        raise ValueError('modal_refine needs at least one measured (non-reconstruction) TF.')
    if len(cols) != N_tfs:
        raise ValueError(
            'modal_refine: measured TF channel count ({}) does not match the '
            'modal model channel count ({}).'.format(len(cols), N_tfs))
    G0 = np.array(cols, dtype=complex).T  # (len(f), N_tfs)

    # seed + bounds (mirrors modal_fit_all_channels, tiled across modes)
    x0 = M.ravel().astype(np.float64)
    lo_row = np.concatenate(([f_axis[0]], [0.0],
                             np.full(N_tfs, -np.inf), np.full(N_tfs, -np.pi/2),
                             np.zeros(N_tfs), np.zeros(N_tfs)))
    hi_row = np.concatenate(([f_axis[-1]], [1.0],
                             np.full(N_tfs, np.inf), np.full(N_tfs, np.pi/2),
                             np.full(N_tfs, np.inf), np.full(N_tfs, np.inf)))
    lower = np.tile(lo_row, n_modes)
    upper = np.tile(hi_row, n_modes)
    x0 = np.clip(x0, lower, upper)

    args = (n_modes, row_len, f, G0, measurement_type)
    cost_before = 0.5 * float(np.sum(_f_residual_refine(x0, *args) ** 2))

    try:
        r = optimize.least_squares(_f_residual_refine, x0, bounds=(lower, upper),
                                   max_nfev=2000, args=args)
        x_ref = r.x
        cost_after = float(r.cost)
        success = bool(r.success)
    except Exception:
        # pathological input — hand back the seed unchanged, flagged not converged
        x_ref = x0
        cost_after = cost_before
        success = False

    converged = bool(success and np.isfinite(cost_after)
                     and cost_after <= cost_before * (1.0 + 1e-9))

    settings = tf_data_list[0].settings
    test_name = tf_data_list[0].test_name
    id_link = [tf.id_link for tf in tf_data_list
               if not getattr(tf, 'flag_modal_TF', False)]
    m_ref = datastructure.ModalData(settings=settings, id_link=id_link, test_name=test_name)
    for row in x_ref.reshape(n_modes, row_len):
        m_ref.add_mode(row)

    info = {'converged': converged,
            'cost_before': float(cost_before),
            'cost_after': float(cost_after)}
    return m_ref, info