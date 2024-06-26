#%% 
import pydvma as ma
import matplotlib.pyplot as plt
import numpy as np
import peakutils as pu
from scipy.optimize import curve_fit, least_squares

# %%
%matplotlib qt

#%%
d = ma.load_data(filename='/Users/tore/Dropbox (Cambridge University)/Work Teaching/3C6/2021/LAB/LAB VIDEO/p3_impulse_with_TF.npy')
# %%
d.calculate_sono_set(nperseg=200)
n_chan = 1
d.plot_sono_data(n_chan=n_chan)
# %%
sd = d.sono_data_list[0]
# %%
t = sd.time_axis
f = sd.freq_axis
S = sd.sono_data
# %%
# find t index closest to t0
t0 = 2*sd.settings.pretrig_samples/sd.settings.fs
print(t0)
time_slice = np.argmin(np.abs(t - t0))
print(time_slice)
print(t[time_slice])

time_slice_data = np.abs(S[:, time_slice, n_chan])
threshold = 10 * np.median(time_slice_data)/np.max(time_slice_data)
print(threshold)
peaks = pu.indexes(time_slice_data, thres=threshold, min_dist=1)
print(peaks)
print(threshold * np.max(time_slice_data))
# %%
plt.plot(time_slice_data)
# horizontal line at threshold
plt.axhline(threshold * np.max(time_slice_data), color='r')
# %%
plt.hist(time_slice_data)
# %%
zeta_n = []
wn_n = []
# define a custom two-param function for fitting
def func_real(t, A,B,N):
    #ensure exp(A) and exp(N) are positive
    f = np.log(np.exp(A)*np.exp(-B*t) + 1j*np.exp(N))
    f = np.real(f)
    return f

def func_imag(t, W, C):
    f = W*t + C
    return f

for peak in peaks:

    # Extract the real and imaginary parts of S at the peak frequency
    real_part = np.real(np.log(S[peak, :, n_chan]))
    imag_part = np.unwrap(np.imag(np.log(S[peak, :, n_chan])))
    
    # Fit linear best fits to the real and imaginary parts separately
    # real_fit = np.polyfit(t, real_part, 1)
    # imag_fit = np.polyfit(t, imag_part, 1)

    # Fit the real part to a custom function
    popt_real, _ = curve_fit(func_real, t[time_slice:], real_part[time_slice:])
    real_fit = func_real(t, *popt_real)
    A = popt_real[0]
    B = popt_real[1]
    N = popt_real[2]
    
    # plt.plot(t, real_part)
    # plt.plot(t, real_fit)

    # Identify crossover time when noise starts to dominate
    t_cross = (A - N)/B
    # nearest time index
    time_cross = np.argmin(np.abs(t - t_cross))

    t0 = time_slice
    dt = int(np.ceil(0.9*(time_cross - time_slice)))
    dt = np.max([2,dt])
    t1 = t0 + dt

    # Fit the imaginary part to a linear function for clean part of the signal
    # Use constrained least squares to fit the imaginary part
    W_bins = np.fft.rfftfreq(len(t), d=t[1]-t[0])
    dw = 2*np.pi*(f[1] - f[0])
    # w_full = np.arange(0, fs/2, dw)
    # result = least_squares(lambda p: func_imag(t[t0:t1], *p) - imag_part[t0:t1], [0, 0], bounds=([-dw, -np.inf], [dw, np.inf]))
    # imag_fit = func_imag(t, *result.x)
    # popt_imag = result.x

    popt_imag,_ = curve_fit(func_imag, t[t0:t1], imag_part[t0:t1])
    imag_fit = func_imag(t, *popt_imag)


    W = popt_imag[0]
    print(W/2/np.pi)
    W0 = 2*np.pi*f[peak] + W # corrected for the bin frequency
    # print(W0/2/np.pi+f[peak])
    C = popt_imag[1]
    print(C/2/np.pi)
    
    # plt.plot(t, real_fit)
    # plt.plot(t[t0:t1], real_fit[t0:t1], linewidth=3)
    # plt.plot(t, real_part,'x')
    # plt.plot(t, imag_fit)
    plt.plot(t[t0:t1], imag_part[t0:t1], linewidth=3)
    # plt.plot(t, np.imag(np.log(S[peak, :, n_chan])),'x')
    # plt.plot(t, imag_part,'.')

    

    # Calculate the damping factor and frequency from the fit coefficients
    zeta = B / np.sqrt(W0**2 + B**2)
    wn = W0 / np.sqrt(1 - zeta**2)
    
    # check quality of fit for real part in the clean part of the signal
    # calculate normalised MSE
    residual = (real_part[t0:t1] - real_fit[t0:t1])**2
    mse = np.sum(residual) / len(residual)

    threshold = 1e-3
    if mse > threshold:
        print('Fit not good enough')
        

    # Store the results in numpy arrays
    zeta_n.append(zeta)
    wn_n.append(wn)
    
zeta_n = np.array(zeta_n)
Qn = 1/(2*zeta_n)
wn_n = np.array(wn_n)
fn_n = wn_n / (2*np.pi)
print(fn_n)
print(Qn)


# %%
