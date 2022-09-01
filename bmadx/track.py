from collections import namedtuple
import sys
import math

#--------------------
# Named tuples for elements and particles
#--------------------

# Particles
# Phase space coordinates as def. in Bmad manual section 15.4.2
Particle = namedtuple('Particle', 'x px y py z pz s p0c mc2')

# Elements
Drift = namedtuple('Drift', 'L')
Quadrupole = namedtuple('Quadrupole', 
                        'L K1 NUM_STEPS X_OFFSET Y_OFFSET, TILT',
                        defaults=(None, None, 1, 0, 0, 0))

#--------------------
# TRACKING ROUTINES
#--------------------

def make_track_a_drift(lib):
    """Makes track_a_drift given the library lib."""
    sqrt = lib.sqrt
    
    def sqrt_one(x):
        """Routine to calculate Sqrt[1+x] - 1 to machine precision."""
        sq = sqrt(1 + x)
        rad = sq + 1
        return x/rad
    
    def track_a_drift(p_in, drift):
        """Tracks the incoming Particle p_in though drift element
        and returns the outgoing particle. 
        See Bmad manual section 24.9 
        """
        L = drift.L
        
        s = p_in.s
        p0c = p_in.p0c
        mc2 = p_in.mc2
        
        x = p_in.x
        px = p_in.px
        y = p_in.y
        py = p_in.py
        z = p_in.z
        pz = p_in.pz
        
        P = 1 + pz            # Particle's total momentum over p0
        Px = px / P           # Particle's 'x' momentum over p0
        Py = py / P           # Particle's 'y' momentum over p0
        Pxy2 = Px**2 + Py**2  # Particle's transverse mometum^2 over p0^2
        Pl = sqrt(1-Pxy2)     # Particle's longitudinal momentum over p0
        
        x = x + L * Px / Pl
        y = y + L * Py / Pl
        
        # z = z + L * ( beta/beta_ref - 1.0/Pl ) but numerically accurate:
        dz = L * (sqrt_one((mc2**2 * (2*pz+pz**2))/((p0c*P)**2 + mc2**2))
                  + sqrt_one(-Pxy2)/Pl)
        z = z + dz
        s = s + L
        
        return Particle(x, px, y, py, z, pz, s, p0c, mc2)
    
    return track_a_drift

def make_track_a_quadrupole(lib):
    """Makes track_a_quadrupole given the library lib."""
    sqrt = lib.sqrt
    sin = lib.sin
    cos = lib.cos
    sinh = lib.sinh
    cosh = lib.cosh
    sinc = lib.sinc
    pi = math.pi
    absolute = lib.abs
    
    def quad_mat2_calc(k1, length, rel_p):
        """Returns 2x2 transfer matrix elements aij and the coefficients
        to calculate the change in z position.
        Input: 
            k1_ref -- Quad strength: k1 > 0 ==> defocus
            length -- Quad length
            rel_p -- Relative momentum P/P0
        Output:
            a11, a12, a21, a22 -- transfer matrix elements
            c1, c2, c3 -- second order derivatives of z such that 
                           z = c1 * x_0^2 + c2 * x_0 * px_0 + c3* px_0^2
        **NOTE**: accumulated error due to machine epsilon. REVISIT
        """ 
        eps = 2.220446049250313e-16  # machine epsilon to double precission
        
        sqrt_k = sqrt(absolute(k1)+eps)
        sk_l = sqrt_k * length
        
        cx = cos(sk_l) * (k1<=0) + cosh(sk_l) * (k1>0) 
        sx = (sin(sk_l)/(sqrt_k))*(k1<=0) + (sinh(sk_l)/(sqrt_k))*(k1>0)
          
        a11 = cx
        a12 = sx / rel_p
        a21 = k1 * sx * rel_p
        a22 = cx
            
        c1 = k1 * (-cx * sx + length) / 4
        c2 = -k1 * sx**2 / (2 * rel_p)
        c3 = -(cx * sx + length) / (4 * rel_p**2)

        return a11, a12, a21, a22, c1, c2, c3
    
    def low_energy_z_correction(pz, p0c, mass, ds):
        """Corrects the change in z-coordinate due to speed < c_light.
        Input:
            p0c -- reference particle momentum in eV
            mass -- particle mass in eV
        Output: 
            dz -- dz = (ds - d_particle) + ds*(beta - beta_ref)/beta_ref
        """
        beta = (1+pz) * p0c / sqrt(((1+pz)*p0c)**2 + mass**2)
        beta0 = p0c / sqrt( p0c**2 + mass**2)
        e_tot = sqrt(p0c**2+mass**2)
        
        evaluation = mass * (beta0*pz)**2
        dz = ( (ds*pz*(1-3*(pz*beta0**2)/2+pz**2*beta0**2*(2*beta0**2-(mass/e_tot)**2/2))*(mass/e_tot)**2)
              * (evaluation<3e-7*e_tot)
              + (ds*(beta-beta0)/beta0)
              * (evaluation>=3e-7*e_tot) )
        
        return dz
    
    def offset_particle_entrance(length, x_offset, y_offset, tilt, 
                                 x_lab, y_lab, px_lab, py_lab):
        """transform from the laboratory coordinates to the
        entrance element coordinates.
        See Bmad sections 5.6.1, 15.3.1 and 24.2
        **NOTE**: transverse only.
        """
        s = sin(tilt)
        c = cos(tilt)
        x_ele_int = x_lab - x_offset
        y_ele_int = y_lab - y_offset
        x_ele = x_ele_int*c + y_ele_int*s
        y_ele = -x_ele_int*s + y_ele_int*c
        px_ele = px_lab*c + py_lab*s
        py_ele = -px_lab*s + py_lab*c
        return x_ele, y_ele, px_ele, py_ele
    
    def offset_particle_exit(length, x_offset, y_offset, tilt, 
                             x_ele, y_ele, px_ele, py_ele):
        """Transforms from the exit element reference frame to the
        laboratory reference frame.
        See Bmad sections 5.6.1, 15.3.1 and 24.2
        **NOTE**: transverse only as of now.
        """
        s = sin(tilt)
        c = cos(tilt)
        x_lab_int = x_ele*c - y_ele*s
        y_lab_int = x_ele*s + y_ele*c
        x_lab = x_lab_int + x_offset
        y_lab = y_lab_int + y_offset
        px_lab = px_ele*c - py_ele*s
        py_lab = px_ele*s + py_ele*c 
        return x_lab, y_lab, px_lab, py_lab
    
    def track_a_quadrupole(p_in, quad):
        """Tracks the incoming Particle p_in though quad element and 
        returns the outgoing particle.
        See Bmad manual section 24.15
        """
        l = quad.L
        k1 = quad.K1
        n_step = quad.NUM_STEPS  # number of divisions
        step_len = l/n_step  # length of division
        
        x_off = quad.X_OFFSET
        y_off = quad.Y_OFFSET
        tilt = quad.TILT
        
        b1 = k1*l
        
        s = p_in.s
        p0c = p_in.p0c
        mc2 = p_in.mc2
        
        x = p_in.x
        px = p_in.px
        y = p_in.y
        py = p_in.py
        z = p_in.z
        pz = p_in.pz
        
        # --- TRACKING --- :
        
        x, y, px, py = offset_particle_entrance(l, x_off, y_off, tilt, x, y, px, py)
        
        for i in range(n_step):
            rel_p = 1 + pz  # Particle's relative momentum (P/P0)
            k1 = b1/(l*rel_p)
            
            tx11, tx12, tx21, tx22, dz_x1, dz_x2, dz_x3 = quad_mat2_calc(-k1, step_len, rel_p)
            ty11, ty12, ty21, ty22, dz_y1, dz_y2, dz_y3 = quad_mat2_calc( k1, step_len, rel_p)
            
            z = ( z +
                dz_x1 * x**2 + dz_x2 * x * px + dz_x3 * px**2 +
                dz_y1 * y**2 + dz_y2 * y * py + dz_y3 * py**2 )
            x_next = tx11 * x + tx12 * px
            px_next = tx21 * x + tx22 * px
            y_next = ty11 * y + ty12 * py
            py_next = ty21 * y + ty22 * py
            x = x_next
            px = px_next
            y = y_next
            py = py_next
            
            z = z + low_energy_z_correction(pz, p0c, mc2, step_len)
        
        s = s + l
        
        x, y, px, py = offset_particle_exit(l, x_off, y_off, tilt, x, y, px, py)
        
        return Particle(x, px, y, py, z, pz, s, p0c, mc2)
      
    return track_a_quadrupole

def track_a_lattice(p_in,lattice):
    """Tracks an incomming Particle p_in through lattice and returns a 
    list of outgoing particles after each element.
    """
    lib = sys.modules[type(p_in.x).__module__]
    tracking_function_dict = {
        "Drift" : make_track_a_drift(lib),
        "Quadrupole" : make_track_a_quadrupole(lib)
    }
    n = len(lattice)
    all_p = [None] * (n+1)
    all_p[0] = p_in
    
    for i in range(n):
        ele = lattice[i]
        track_f = tracking_function_dict[type(ele).__name__]
        all_p[i+1] = track_f(all_p[i],ele)
        
    return all_p


def stub_element(ele, n):
    """Divides ele into 'n' equal length elements and returns
    a list of these short elements.
    """
    short_L = ele.L / n
    short_ele = ele._replace(L=short_L)
    lattice = [short_ele] * n
    
    return lattice

def stub_lattice(lattice, n):
    """Divides every element in the lattice into 'n' elements
    each and returns divided lattice. 
    """
    stubbed_lattice = []
    
    for ele in lattice:
        stubbed_lattice.extend(stub_element(ele, n))
        
    return stubbed_lattice