import numpy as np


def fft2_centered(values):
    return np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(values)))


def ifft2_centered(values):
    return np.fft.fftshift(np.fft.ifft2(np.fft.ifftshift(values)))
