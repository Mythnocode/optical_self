import numpy as np


class NumPyBackend:
    array = staticmethod(np.asarray)
    fft2 = staticmethod(np.fft.fft2)
    ifft2 = staticmethod(np.fft.ifft2)
