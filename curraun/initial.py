from curraun.numba_target import myjit, my_parallel_loop, prange, use_python
import numpy as np
import curraun.lattice as l
import curraun.su as su

def init(s, w1, w2):
    u0 = s.u0
    u1 = s.u1
    pt1 = s.pt1
    pt0 = s.pt0
    aeta0 = s.aeta0
    aeta1 = s.aeta1
    peta1 = s.peta1
    peta0 = s.peta0
    v1 = w1
    v2 = w2
    n = s.n
    dt = s.dt
    dth = s.dt / 2.0

    # temporary transverse gauge links for each nucleus
    ua = np.zeros_like(u0)
    ub = np.zeros_like(u0)

    en_EL = np.zeros(n ** 2, dtype=np.double)  # TODO: Think about alternative implementation that reduces on GPU?
    en_BL = np.zeros(n ** 2, dtype=np.double)

    # TODO: keep arrays on GPU device during execution of these kernels
    my_parallel_loop(init_kernel_1, n ** 2, v1, v2, n, ua, ub)
    if su.N_C == 2:
        my_parallel_loop(init_kernel_2, n ** 2, u0, u1, ua, ub)
    elif su.N_C == 3:
        print("WARNING: initial.py: proper SU(3) code not implemented")
        # TODO: Implement SU(3) initialization code.
        # So far, this only works with TEST_SU2_SUBGROUP = True in mv.py
        my_parallel_loop(init_kernel_2_TEST4, n ** 2, u0, u1, ua, ub)
    else:
        print("initial.py: SU(N) code not implemented")
    my_parallel_loop(init_kernel_3, n ** 2, u0, peta1, n, ua, ub)
    my_parallel_loop(init_kernel_4, n ** 2, u0, pt1, n, dt)
    my_parallel_loop(init_kernel_5, n ** 2, u0, u1, pt1, aeta0, aeta1, peta1, dt, dth)
    my_parallel_loop(init_kernel_6, n ** 2, u0, u1, peta1, n, en_EL, en_BL)

    peta0[:,:] = peta1[:,:]
    pt0[:,:] = pt1[:,:]

    en_EL_sum = np.sum(en_EL)
    en_BL_sum = np.sum(en_BL)

    print("e_EL = {}".format(en_EL_sum))
    print("e_BL = {}".format(en_BL_sum))


@myjit
def init_kernel_1(xi, v1, v2, n, ua, ub):
    # temporary transverse gauge fields
    for d in range(2):
        xs = l.shift(xi, d, 1, n)
        buffer1 = su.mul(v1[xi], su.dagger(v1[xs]))
        su.store(ua[xi, d], buffer1)
        buffer2 = su.mul(v2[xi], su.dagger(v2[xs]))
        su.store(ub[xi, d], buffer2)


@myjit
def init_kernel_2(xi, u0, u1, ua, ub):
    # initialize transverse gauge links (longitudinal magnetic field)
    # (see PhD thesis eq.(2.135))  # TODO: add proper link or reference
    for d in range(2):
        b1 = su.load(ua[xi, d])
        b1 = su.add(b1, ub[xi, d])
        b2 = su.dagger(b1)
        b2 = su.inv(b2)
        b3 = su.mul(b1, b2)
        su.store(u0[xi, d], b3)
        su.store(u1[xi, d], b3)

ITERATION_FACTOR_1 = 0.5 #0.25 # 0.5
ITERATION_FACTOR_2 = 0.25 # 0.5 # 0.25 # 0.5
ITERATION_BOUND_1 = 1e-8 #20 #su.EXP_ACCURACY_SQUARED
ITERATION_BOUND_2 = 1e-8 #20 #su.EXP_ACCURACY_SQUARED
ITERATION_MAX = 30 # 25000 # 30 # 250

# Iterative solution
@myjit
def init_kernel_2_TEST(xi, u0, u1, ua, ub):
    # initialize transverse gauge links (longitudinal magnetic field)
    # (see PhD thesis eq.(2.135))  # TODO: add proper link or reference
    for d in range(2):
        b1 = su.load(ua[xi, d])
        b1 = su.add(b1, ub[xi, d])  # A
        b2 = su.dagger(b1)
        b2 = su.inv(b2)  # (A.H)^(-1)
        b3 = su.mul(b1, b2) # A (A.H)^(-1)

        check = su.det(b3)

        # Make solution consistently unitary
        unit = su.unit()
        c1 = su.add(b3, su.mul_s(unit, -1)) # A (A.H)^(-1) - 1
        f1 = ITERATION_FACTOR_1
        f2 = ITERATION_FACTOR_2
        for i in range(ITERATION_MAX):
            b3old = b3

            # Check result
            e1 = su.mul(b1, su.dagger(su.add(unit, b3)))
            e2 = su.ah(e1)
            check1 = su.sq(e2)

            # Check unitarity:
            check2 = su.check_unitary(b3)

            # Adapt iteration factors
            # f1 = ITERATION_FACTOR_1 / (1 + check1 + check2)  # more careful if we are very off
            # f2 = ITERATION_FACTOR_2 / (1 + check1 + check2)  # more careful if we are very off

            # New guess for unitarity
            # B = (B.H)^(-1)
            e1 = su.dagger(b3)
            b3new = su.inv(e1)
            b3 = su.add(su.mul_s(b3, 1 - f1), su.mul_s(b3new, f1))

            # New guess for unitarity
            # B = (B.H)^(-1)
            #      e1 = su.dagger(b3)
            #      e2 = su.inv(e1) # (B.H)^(-1)
            #      e3 = su.mul(su.mul(b3, e1), b3)  # B B.H B
            #      b3new = su.add(su.add(e3, e2), su.mul_s(b3, -1))
            #      b3 = su.add(su.mul_s(b3, 1 - f1), su.mul_s(b3new, f1))

            # Check result
            e1 = su.mul(b1, su.dagger(su.add(unit, b3)))
            e2 = su.ah(e1)
            check3 = su.sq(e2)

            # Check unitarity:
            check4 = su.check_unitary(b3)

            # if check3 + check4 > check1 + check2:
            if check4 > check2:
         #       print("Iteration f1 step too big? i = {}".format(i))
         #       print("  {} + {} > {} + {}".format(check3, check4, check1, check2))
                b3 = b3old # Keep old solution
                f1 = f1 * 0.5 # Reduce step size
                # f2 = f2 * 0.5
                check3 = check1
                check4 = check2
         #       print("  f1: {}, f2: {}".format(f1, f2))
     #       elif i % 4 == 0 and f1 < 0.5:
     #           f1 = f1 * 2

            b3old = b3

    #        # New guess
    #        # B = A B.H (A.H)^(-1) + A (A.H)^(-1) - 1
    #        c2 = su.dagger(b3)
    #        #c2 = su.inv(b3)  # Alternative
    #        c3 = su.mul(b1, c2)
    #        c4 = su.mul(c3, b2)
    #        b3new = su.add(c4, c1)
    #        b3 = su.add(su.mul_s(b3, 1 - f2), su.mul_s(b3new, f2))

            # New guess
            # X = A (1 + B).H
            # X_new = X_old - [X_old]_ah
            # B_new = X_new (A.H)^(-1) - 1
            X = su.mul(b1, su.dagger(su.add(unit, b3)))
            Xnew = su.add(X, su.ah(X))
            c2 = su.inv(su.dagger(b1))
            c3 = su.mul(Xnew, c2)
            b3new = su.add(c3, su.mul_s(unit, -1))
            b3 = su.add(su.mul_s(b3, 1 - f2), su.mul_s(b3new, f2))

            # Check result
            e1 = su.mul(b1, su.dagger(su.add(unit, b3)))
            e2 = su.ah(e1)
            check5 = su.sq(e2)

            # check also trace:
            e3 = su.add(e1, su.mul_s(su.dagger(e1), -1)) # X - X.H
            check5b = su.tr(e3)

            # Check unitarity:
            check6 = su.check_unitary(b3)

            # check also determinant
            check6b = su.det(b3)

            #if check5 + check6 > check3 + check4:
            if check5 > check3:
        #        print("Iteration f2 step too big? i = {}".format(i))
        #        print("  {} + {} > {} + {}".format(check5, check6, check3, check4))
                b3 = b3old # Keep old solution
                #f1 = f1 * 0.5 # Reduce step size
                f2 = f2 * 0.5
        #        print("  f1: {}, f2: {}".format(f1, f2))
    #        elif i % 4 == 0 and f2 < 0.25:
    #            f2 = f2 * 2

            if check5 + check6 > check1 + check2:
                #       print("Iteration f1 step too big? i = {}".format(i))
                #       print("  {} + {} > {} + {}".format(check3, check4, check1, check2))
                #b3 = b3old  # Keep old solution
                f1 = f1 * 0.5  # Reduce step size
                f2 = f2 * 0.5
                check3 = check1
                check4 = check2
                #       print("  f1: {}, f2: {}".format(f1, f2))

            if check1 < ITERATION_BOUND_1 and check2 < ITERATION_BOUND_2:
                print("Kernel 2: {} iterations: {}, ·{}".format(i, check1, check2))
                break
        else: # no break
            print("Kernel 2: max iterations reached. bounds: {}, {}".format(check1, check2))
            print("xi: {}, d: {}".format(xi, d))
            print("  f1: {}, f2: {}".format(f1, f2))

        check = su.det(b3)

        su.store(u0[xi, d], b3)
        su.store(u1[xi, d], b3)

# Gradient descent
@myjit
def init_kernel_2_TEST2(xi, u0, u1, ua, ub):
    # initialize transverse gauge links (longitudinal magnetic field)
    # (see PhD thesis eq.(2.135))  # TODO: add proper link or reference
    for d in range(2):
        b1 = su.load(ua[xi, d])
        b1 = su.add(b1, ub[xi, d])  # A
        b2 = su.dagger(b1)
        b2 = su.inv(b2)  # (A.H)^(-1)
        b3 = su.mul(b1, b2) # A (A.H)^(-1)

        check = su.det(b3)

        b3 = su.unit()

        # Make solution consistently unitary
        epsilon2 = 0.125
        for i in range(ITERATION_MAX):
            b3old = b3

            # Calculate Loss:

            loss1, check1, check2, check3 = loss(b1, b3)

            b3new = b3
            b3new2 = b3
            b3new3 = b3

            epsilon1 = epsilon2 # * 0.125 # smaller
            for a in range(9):
                for b in range(2):
                    jj = 1
                    if b == 1:
                        jj = 1j
                    b3test = su.add(b3, su.mul_s(su.slist[a], epsilon1 * jj))
                    loss2 = loss(b1, b3test)[0]
                    dloss = (loss2 - loss1) / epsilon1
                    b3new = su.add(b3new, su.mul_s(su.slist[a], -dloss * epsilon2 * jj))
                    b3new2 = su.add(b3new2, su.mul_s(su.slist[a], -dloss * epsilon2 * jj * 0.5))
                    b3new3 = su.add(b3new3, su.mul_s(su.slist[a], -dloss * epsilon2 * jj * 0.25))

            loss3, check4, check5, check6 = loss(b1, b3new)
            loss4 = loss(b1, b3new2)[0]
            loss5 = loss(b1, b3new3)[0]

            onesmaller = False
            if loss5 < loss1:
                b3 = b3new3
                onesmaller = True
            if loss4 < loss5:
                b3 = b3new2
                onesmaller = True
            if loss3 < loss4:
                b3 = b3new
                onesmaller = True
                if i % 4 == 0:
                    epsilon2 = epsilon2 * 2
            if not onesmaller:
                epsilon2 = epsilon2 * 0.5

            if loss3 < ITERATION_BOUND_1:
     #           print("Kernel 2: {} iterations: {}".format(i, loss3))
                print("Kernel 2: " + str(i) + " iterations: " + str(loss3))
                break
        else: # no break
            print("Kernel 2: max iterations reached. Bounds: " + str(loss3))
            pass
     #       print("Kernel 2: max iterations reached. bounds: {}".format(loss3))
     #       print("xi: {}, d: {}".format(xi, d))

        check = su.det(b3)

        su.store(u0[xi, d], b3)
        su.store(u1[xi, d], b3)

# debug = True # use_python

GRADIENT_ITERATION_MAX = 2500 # 50 # 2500000 # 30  # 25000 # 30 # 250
GRADIENT_ITERATION_BOUND = 1e-8 #20 #su.EXP_ACCURACY_SQUARED

# Gradient descent on algebra element
@myjit
def init_kernel_2_TEST3(xi, u0, u1, ua, ub):
    # initialize transverse gauge links (longitudinal magnetic field)
    # (see PhD thesis eq.(2.135))  # TODO: add proper link or reference
    for d in range(2):
        b1 = su.load(ua[xi, d])
        b1 = su.add(b1, ub[xi, d])  # A

        m1 = zero_algebra # real values

        # Make solution consistently unitary
        epsilon2 = 0.125
        for i in range(GRADIENT_ITERATION_MAX):
            # Calculate Loss:
            b3 = su.mexp(su.get_algebra_element(m1))
            loss1, check1, check2, check3 = loss(b1, b3)

            m2new = m1
            m2new2 = m1
            m2new3 = m1

            epsilon1 = epsilon2 # * 0.125 # smaller
            for a in range(8):
                mdelta = unit_algebra[a]
                m2 = add_algebra(m1, mul_algebra(mdelta, epsilon1))
                m3 = su.get_algebra_element(m2)
                b3test = su.mexp(m3)

                loss2 = loss(b1, b3test)[0]
                dloss_first_order = (loss2 - loss1) / epsilon1

                # Calculate derivative to second order accuracy:
                m2 = add_algebra(m1, mul_algebra(mdelta, -epsilon1))
                m3 = su.get_algebra_element(m2)
                b3test = su.mexp(m3)

                loss3 = loss(b1, b3test)[0]
                dloss = (loss2 - loss3) / (2 * epsilon1)

                m2new = add_algebra(m2new, mul_algebra(mdelta, -dloss * epsilon2))
                b3new = su.mexp(su.get_algebra_element(m2new))

                m2new2 = add_algebra(m2new2, mul_algebra(mdelta, -dloss * epsilon2 * 0.5))
                b3new2 = su.mexp(su.get_algebra_element(m2new2))

                m2new3 = add_algebra(m2new3, mul_algebra(mdelta, -dloss * epsilon2 * 0.25))
                b3new3 = su.mexp(su.get_algebra_element(m2new3))

            loss3, check4, check5, check6 = loss(b1, b3new)
            loss4 = loss(b1, b3new2)[0]
            loss5 = loss(b1, b3new3)[0]

            onesmaller = False
            if loss5 < loss1:
                m1 = m2new3
                # onesmaller = True # Step size maybe too big
            if loss4 < loss5:
                m1 = m2new2
                onesmaller = True
            if loss3 < loss4:
                m1 = m2new
                onesmaller = True
                if i % 8 == 0:
                    epsilon2 = epsilon2 * 2
            if not onesmaller:
                epsilon2 = epsilon2 * 0.5

            if loss3 < GRADIENT_ITERATION_BOUND:
            #    if debug: # TODO: Remove debugging code
            #        print("Kernel 2: {} iterations: {}".format(i, loss3))
                print("Kernel 2: xi:", xi, ", d:", d, ": Iterations:", i, ". Bounds:", loss3)
                break
        else: # no break
            # pass
        #    if debug:
            print("Kernel 2: xi:", xi, ", d:", d, ": max iterations reached:", i, ". Bounds:", loss3)
        #    print("Kernel 2: max iterations reached. bounds: {}".format(loss3))
        #        print("xi: {}, d: {}".format(xi, d))

        check = su.det(b3)

        su.store(u0[xi, d], b3)
        su.store(u1[xi, d], b3)


# Gradient descent on algebra element
# Calculate gradient analytically
@myjit
def init_kernel_2_TEST4(xi, u0, u1, ua, ub):
    # initialize transverse gauge links (longitudinal magnetic field)
    # (see PhD thesis eq.(2.135))  # TODO: add proper link or reference
    for d in range(2):
        b1 = su.load(ua[xi, d])
        b1 = su.add(b1, ub[xi, d])  # A

        m1 = zero_algebra # real values

        # Make solution consistently unitary
        epsilon2 = 0.0001 # 0.125
        for i in range(GRADIENT_ITERATION_MAX):
            # Calculate Loss:
            b3 = su.mexp(su.get_algebra_element(m1))
            loss1, check1, check2, check3 = loss(b1, b3)

            m2new = m1
            m2new2 = m1
            m2new3 = m1

            epsilon1 = epsilon2 # * 0.125 # smaller
            for a in range(8):
                mdelta = unit_algebra[a]
                m2 = add_algebra(m1, mul_algebra(mdelta, epsilon1))
                m3 = su.get_algebra_element(m2)
                b3test = su.mexp(m3)

                loss2 = loss(b1, b3test)[0]
                dloss_first_order = (loss2 - loss1) / epsilon1

                # Calculate derivative to second order accuracy:
                m2 = add_algebra(m1, mul_algebra(mdelta, -epsilon1))
                m3 = su.get_algebra_element(m2)
                b3test = su.mexp(m3)

                loss3 = loss(b1, b3test)[0]
                dloss_second_order = (loss2 - loss3) / (2 * epsilon1)

                # Calculate analytic derivative:
                dloss_analytic = gradient(b1, m1, a)

                # print("loss: a: ", a , ", loss1: ", dloss_first_order, ", loss2: ", dloss, " loss3: ", dloss_analytic)

                dloss = dloss_analytic

                m2new = add_algebra(m2new, mul_algebra(mdelta, -dloss * epsilon2))
                b3new = su.mexp(su.get_algebra_element(m2new))

                m2new2 = add_algebra(m2new2, mul_algebra(mdelta, -dloss * epsilon2 * 0.5))
                b3new2 = su.mexp(su.get_algebra_element(m2new2))

                m2new3 = add_algebra(m2new3, mul_algebra(mdelta, -dloss * epsilon2 * 0.25))
                b3new3 = su.mexp(su.get_algebra_element(m2new3))

            # Calculate gradient analytically



            loss3, check4, check5, check6 = loss(b1, b3new)
            loss4 = loss(b1, b3new2)[0]
            loss5 = loss(b1, b3new3)[0]

            onesmaller = False
            if loss5 < loss1:
                m1 = m2new3
                # onesmaller = True # Step size maybe too big
            if loss4 < loss5:
                m1 = m2new2
                onesmaller = True
            if loss3 < loss4:
                m1 = m2new
                onesmaller = True
                if i % 8 == 0:
                    epsilon2 = epsilon2 * 2
            if not onesmaller:
                epsilon2 = epsilon2 * 0.5

            if loss3 < GRADIENT_ITERATION_BOUND:
            #    if debug: # TODO: Remove debugging code
            #        print("Kernel 2: {} iterations: {}".format(i, loss3))
                print("Kernel 2: xi:", xi, ", d:", d, ": Iterations:", i, ". Bounds:", loss3)
                break
        else: # no break
            # pass
        #    if debug:
            print("Kernel 2: xi:", xi, ", d:", d, ": max iterations reached:", i, ". Bounds:", loss3)
        #    print("Kernel 2: max iterations reached. bounds: {}".format(loss3))
        #        print("xi: {}, d: {}".format(xi, d))

        check = su.det(b3)

        su.store(u0[xi, d], b3)
        su.store(u1[xi, d], b3)

@myjit
def gradient(b1, m1, a):

    # b1 # A
    unit = su.unit()
    b3 = su.mexp(su.get_algebra_element(m1)) # B = exp(m1)

    e1 = su.mul(b1, su.dagger(su.add(unit, b3))) # X = A (1 + B)^dagger
    e2 = su.add(e1, su.mul_s(su.dagger(e1), -1)) # X - X^dagger
    e3 = su.mul_s(unit, -su.tr(e2) / su.N_C) # - tr(e2) / N_C * 1
    e4 = su.add(e2, e3) # Y = [X]_ah

    mdelta = unit_algebra[a]
    m3 = su.get_algebra_element(mdelta)

    f1 = su.mul(b1, su.mul(m3, su.dagger(b3))) # A (-i t_a/2) B^dagger
    f2 = su.add(f1, su.mul_s(su.dagger(f1), -1)) # f1 - f1^dagger
    f3 = su.mul_s(unit, -su.tr(f2) / su.N_C) # - tr(f2) / N_C * 1
    f4 = su.add(f2, f3) # d/da Y = d/da [X]_ah

    # g1 = su.mul(f2, su.dagger(e2)) # d/da (X - X^dagger) * (X - X^dagger)^dagger
    # g2 = su.mul(e2, su.dagger(f2)) # (X - X^dagger) * d/da (X - X^dagger)^dagger
    # g3 = su.mul_s(su.add(g1, g2), 0.5)
    #
    # h1 = su.mul_s(unit, su.tr(g3) / su.N_C)
    # h2 = su.add(g3, su.mul_s(h1, -1))

    g1 = su.mul(f4, su.dagger(e4)) # (d/da Y) . Y^dagger
    g2 = su.mul(e4, su.dagger(f4)) # Y . d/da Y^dagger
    g3 = su.tr(su.add(g1, g2)) # d/da tr(Y . Y^dagger) = tr(g1 + g2)

    #i = su.tr(h2)

    #i1 = -2 * su.tr(g3)

    #i = su.tr(g3)

    # TEST
    #t1 = su.mul(m3, b3)
    #i = su.tr(t1)
    res = -g3.real * 0.25 # Result should be real
    return res

@myjit
def add_algebra(a, b):
    r0 = a[0] + b[0]
    r1 = a[1] + b[1]
    r2 = a[2] + b[2]
    r3 = a[3] + b[3]
    r4 = a[4] + b[4]
    r5 = a[5] + b[5]
    r6 = a[6] + b[6]
    r7 = a[7] + b[7]
    return r0, r1, r2, r3, r4, r5, r6, r7

@myjit
def mul_algebra(a, f):
    r0 = a[0] * f
    r1 = a[1] * f
    r2 = a[2] * f
    r3 = a[3] * f
    r4 = a[4] * f
    r5 = a[5] * f
    r6 = a[6] * f
    r7 = a[7] * f
    return r0, r1, r2, r3, r4, r5, r6, r7

unit_algebra = ((1,0,0,0,0,0,0,0),
                (0,1,0,0,0,0,0,0),
                (0,0,1,0,0,0,0,0),
                (0,0,0,1,0,0,0,0),
                (0,0,0,0,1,0,0,0),
                (0,0,0,0,0,1,0,0),
                (0,0,0,0,0,0,1,0),
                (0,0,0,0,0,0,0,1))

zero_algebra = (0,0,0,0,0,0,0,0)

@myjit
def loss(b1, b3):
    unit = su.unit()

    # Check result
    e1 = su.mul(b1, su.dagger(su.add(unit, b3)))
    e2 = su.ah(e1)
    check1 = su.sq(e2)

    # Check unitarity:
    check2 = su.check_unitary(b3)

    # Check determinant
    f1 = su.det(b3) - 1
    check3 = f1.real * f1.real + f1.imag * f1.imag

    #res = check1 + check2 + check3
    res = check1

    # TEST
    #t1 = su.add(e1, su.mul_s(su.dagger(e1), -1))
    #res1 = su.sq(t1)

    #res = su.tr(t1)
    return res, check1, check2, check3

@myjit
def init_kernel_3(xi, u0, peta1, n, ua, ub):
    # initialize pi field (longitudinal electric field)
    # (see PhD thesis eq.(2.136))  # TODO: add proper link or reference
    tmp_peta1 = su.zero()
    for d in range(2):
        xs = l.shift(xi, d, -1, n)

        b1 = su.load(ub[xi, d])
        b1 = l.add_mul(b1, ua[xi, d], -1)
        b1 = su.dagger(b1)

        b2 = su.mul(u0[xi, d], b1)
        b2 = l.add_mul(b2, b1, -1)

        b1 = su.load(ub[xs, d])
        b1 = l.add_mul(b1, ua[xs, d], -1)

        b3 = su.mul(su.dagger(u0[xs, d]), b1)
        b3 = l.add_mul(b3, b1, -1)

        b2 = su.add(b2, b3)
        b3 = su.ah(b2)

        tmp_peta1 = su.add(tmp_peta1, b3)
    tmp_peta1 = su.mul_s(tmp_peta1, 0.5)
    su.store(peta1[xi], tmp_peta1)


@myjit
def init_kernel_4(xi, u0, pt1, n, dt):
    # pt corrections at tau = dt / 2
    for d in range(2):
        # transverse electric field update
        b1 = l.plaquettes(xi, d, u0, n)
        b1 = l.add_mul(pt1[xi, d], b1, - dt ** 2 / 2.0)
        su.store(pt1[xi, d], b1)

@myjit
def init_kernel_5(xi, u0, u1, pt1, aeta0, aeta1, peta1, dt, dth):
    # coordinate update
    for d in range(2):
        # transverse link variables update
        b0 = su.mul_s(pt1[xi, d], dt / dth)
        b1 = su.mexp(b0)
        b2 = su.mul(b1, u0[xi, d])
        su.store(u1[xi, d], b2)

    # longitudinal gauge field update
    b1 = l.add_mul(aeta0[xi], peta1[xi], dth * dt)
    su.store(aeta1[xi], b1)


@myjit
def init_kernel_6(xi, u0, u1, peta1, n, en_EL, en_BL):
    # initial condition check (EL ~ BL?)
    b1 = l.plaq(u0, xi, 0, 1, 1, 1, n)
    b2 = su.ah(b1)
    en_BL[xi] += su.sq(b2) / 2

    b1 = l.plaq(u1, xi, 0, 1, 1, 1, n)
    b2 = su.ah(b1)
    en_BL[xi] += su.sq(b2) / 2

    # b1 = l.plaq(u0, xi, 0, 1, 1, 1, n)
    # en_BL[0] += 2*(1.0 - b1[0])
    # b1 = l.plaq(u1, xi, 0, 1, 1, 1, n)
    # en_BL[0] += 2*(1.0 - b1[0])

    en_EL[xi] += su.sq(peta1[xi])
