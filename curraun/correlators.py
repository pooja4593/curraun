from curraun.numba_target import myjit, my_parallel_loop, use_cuda
import numpy as np
import curraun.lattice as l
import curraun.su as su
if use_cuda:
    import numba.cuda as cuda

"""
    A module for computing E_z and B_z correlation functions
"""

@myjit
def compute_Bz(xi, n, u0, u1, aeta0, aeta1, pt0, pt1, peta0, peta1):
    bz = su.zero()

    # quadratically accurate +Bz
    b1 = l.plaq(u0, xi, 0, 1, 1, 1, n)
    b2 = su.ah(b1)
    bz = l.add_mul(bz, b2, -0.25)

    b1 = l.plaq(u0, xi, 0, 1, 1, -1, n)
    b2 = su.ah(b1)
    bz = l.add_mul(bz, b2, +0.25)

    b1 = l.plaq(u0, xi, 1, 0, 1, -1, n)
    b2 = su.ah(b1)
    bz = l.add_mul(bz, b2, -0.25)

    b1 = l.plaq(u0, xi, 1, 0, -1, -1, n)
    b2 = su.ah(b1)
    bz = l.add_mul(bz, b2, +0.25)

    return bz


@myjit
def compute_Ez(xi, n, u0, u1, aeta0, aeta1, pt0, pt1, peta0, peta1):
    ez = su.zero()

    # quadratically accurate +E_z
    ez = l.add_mul(ez, peta1[xi], 0.5)
    ez = l.add_mul(ez, peta0[xi], 0.5)

    return ez


class Correlators:
    def __init__(self, s):
        self.s = s

        self.corr = np.zeros(s.n // 2,  dtype=np.double)
        self.d_corr = self.corr

        if use_cuda:
            self.copy_to_device()

    def copy_to_device(self):
        self.d_corr = cuda.to_device(self.corr)

    def copy_to_host(self):
        self.d_corr.copy_to_host(self.corr)

    def compute(self, mode):
        s = self.s
        self.corr = np.zeros(s.n // 2,  dtype=np.double)
        if use_cuda:
            self.copy_to_device()

        if mode == 'Ez':
            my_parallel_loop(compute_correlation_kernel, s.n * s.n, s.n,
                             s.d_u0, s.d_u1, s.d_aeta0, s.d_aeta1, s.d_pt0, s.d_pt1, s.d_peta0, s.d_peta1,
                             self.d_corr, 0)
        elif mode == 'Bz':
            my_parallel_loop(compute_correlation_kernel, s.n * s.n, s.n,
                             s.d_u0, s.d_u1, s.d_aeta0, s.d_aeta1, s.d_pt0, s.d_pt1, s.d_peta0, s.d_peta1,
                             self.d_corr, 1)
        else:
            print("Correlators: mode '{}' is not implemented.".format(mode))

        if use_cuda:
            self.copy_to_host()

        # normalize, 2 * n ** 2 contributions per distance r
        self.corr /= 2 * s.n ** 2

@myjit
def compute_correlation_kernel(xi, n, u0, u1, aeta0, aeta1, pt1, pt0, peta1, peta0, corr, mode):
    Ux = su.unit()
    Uy = su.unit()

    if mode == 0:
        F = compute_Ez(xi, n, u0, u1, aeta0, aeta1, pt1, pt0, peta1, peta0)
    else:
        F = compute_Bz(xi, n, u0, u1, aeta0, aeta1, pt1, pt0, peta1, peta0)

    for r in range(n // 2):
        # x shifts
        xs_x = l.shift(xi, 0, r, n)

        if mode == 0:
            Fs_x = compute_Ez(xs_x, n, u0, u1, aeta0, aeta1, pt1, pt0, peta1, peta0)
        else:
            Fs_x = compute_Bz(xs_x, n, u0, u1, aeta0, aeta1, pt1, pt0, peta1, peta0)

        Fs_x = l.act(Ux, Fs_x)
        correlation = su.tr(su.mul(F, su.dagger(Fs_x))).real

        cuda.atomic.add(corr, r, correlation)

        # y shifts
        xs_y = l.shift(xi, 1, r, n)

        if mode == 0:
            Fs_y = compute_Ez(xs_y, n, u0, u1, aeta0, aeta1, pt1, pt0, peta1, peta0)
        else:
            Fs_y = compute_Bz(xs_y, n, u0, u1, aeta0, aeta1, pt1, pt0, peta1, peta0)

        Fs_y = l.act(Uy, Fs_y)
        correlation = su.tr(su.mul(F, su.dagger(Fs_y))).real

        cuda.atomic.add(corr, r, correlation)

        # update Ux, Uy
        Ux = su.mul(Ux, u0[xs_x, 0])
        Uy = su.mul(Uy, u0[xs_y, 1])