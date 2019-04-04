#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright © 2017 Michael J. Hayford
""" Module for optical surface related classes

    Surface
        Container of profile, extent, position and orientation information of
        the surface

    DecenterData
        Maintains data and actions to support 4 types of position and
        orientation changes.

        - DEC: pos and orientation applied prior to surface
        - REV: pos and orientation applied following surface in reverse
        - DAR: pos and orientation applied prior to surface and then returned to initial frame
        - BEN: used for fold mirrors, orientation applied before and after surface

    Aperture
        - Circular
        - Rectangular
        - Elliptical

.. Created on Sat Sep 16 09:22:05 2017

.. codeauthor: Michael J. Hayford
"""


from . import profiles
from math import sqrt
import numpy as np
import transforms3d as t3d
from .model_enums import DecenterType as dec


class Interface:
    def __init__(self, refract_mode='', delta_n=0.0,
                 max_ap=1.0, decenter=None):
        self.refract_mode = refract_mode
        self.delta_n = delta_n
        self.decenter = decenter
        self.max_aperture = max_ap

    def update(self):
        if self.decenter is not None:
            self.decenter.update()

    def interface_type(self):
        return type(self).__name__

    def sync_to_restore(self, opt_model):
        if not hasattr(self, 'max_aperture'):
            self.max_aperture = 1.0

    def profile_cv(self):
        return 0.0

    def set_optical_power(self, pwr, n_before, n_after):
        pass

    def surface_od(self):
        pass

    def set_max_aperture(self, max_ap):
        """ max_ap is the max aperture radius """
        self.max_aperture = max_ap

    def intersect(self, p0, d, eps=1.0e-12):
        pass

    def normal(self, p):
        pass

    def phase(self, pt, d_in, normal, wl):
        pass


class Surface(Interface):
    """ Container of profile, extent, position and orientation. """

    def __init__(self, lbl='', profile=None, **kwargs):
        super().__init__(**kwargs)
        self.label = lbl
        if profile:
            self.profile = profile
        else:
            self.profile = profiles.Spherical()
        self.clear_apertures = []
        self.edge_apertures = []

    def __repr__(self):
        if len(self.label) > 0:
            return "{!s}(lbl={!r}, profile={!r})".format(type(self).__name__,
                                                         self.label,
                                                         self.profile)
        else:
            return "{!s}(profile={!r})".format(type(self).__name__,
                                               self.profile)

    def interface_type(self):
        return type(self.profile).__name__

    def update(self):
        super().update()
        self.profile.update()

    def profile_cv(self):
        return self.profile.cv

    @property
    def optical_power(self):
        return self.delta_n * self.profile.cv

    @optical_power.setter
    def optical_power(self, pwr):
        self.profile.cv = pwr/self.delta_n if self.delta_n != 0.0 else 0.0

    def set_optical_power(self, pwr, n_before, n_after):
        self.delta_n = n_after - n_before
        self.optical_power = pwr

    def from_first_order(self, nu_before, nu_after, y):
        pass

    def surface_od(self):
        od = 0
        if len(self.edge_apertures) > 0:
            for e in self.edge_apertures:
                edg = e.max_dimension()
                if edg > od:
                    od = edg
        elif len(self.clear_apertures) > 0:
            for ca in self.clear_apertures:
                ap = ca.max_dimension()
                if ap > od:
                    od = ap
        else:
            od = self.max_aperture

        return od

    def get_y_aperture_extent(self):
        """ returns [y_min, y_max] for the union of apertures """
        od = [1.0e10, -1.0e10]
        if len(self.edge_apertures) > 0:
            for e in self.edge_apertures:
                edg = e.bounding_box()
                if edg[0][1] < od[0]:
                    od[0] = edg[0][1]
                if edg[1][1] > od[1]:
                    od[1] = edg[1][1]
        elif len(self.clear_apertures) > 0:
            for ca in self.clear_apertures:
                ap = ca.bounding_box()
                if ap[0][1] < od[0]:
                    od[0] = ap[0][1]
                if ap[1][1] > od[1]:
                    od[1] = ap[1][1]
        else:
            od = [-self.max_aperture, self.max_aperture]

        return od

    def full_profile(self, edge_extent, flat_id=None, dir=1, steps=6):
        if flat_id is None:
            return self.profile.profile(edge_extent, dir, steps)
        else:
            if len(edge_extent) == 1:
                sd_upr = edge_extent[0]
                sd_lwr = -edge_extent[0]
            else:
                sd_upr = edge_extent[1]
                sd_lwr = edge_extent[0]
            if dir<0:
                sd_lwr, sd_upr = sd_upr, sd_lwr
            sag = self.profile.sag(0, flat_id)
            prf = []
            prf.append([sag, sd_lwr])
            prf += self.profile.profile((flat_id,), dir, steps)
            prf.append([sag, sd_upr])
            return prf

    def intersect(self, p0, d, eps=1.0e-12, z_dir=1.0):
        return self.profile.intersect(p0, d, eps, z_dir)

    def normal(self, p):
        return self.profile.normal(p)

    def phase(self, pt, d_in, normal, wl):
        pass


class DecenterData():
    """ Maintains data and actions for position and orientation changes.

        - LOCAL: pos and orientation applied prior to surface
        - REV:   pos and orientation applied following surface in reverse
        - DAR:   pos and orientation applied prior to surface and then returned to initial frame
        - BEND:  used for fold mirrors, orientation applied before and after surface

    """
    def __init__(self, dtype, x=0., y=0., alpha=0., beta=0., gamma=0.):
        self.dtype = dtype
        # x, y, z vertex decenter
        self.dec = np.array([x, y, 0.])
        # alpha, beta, gamma euler angles
        self.euler = np.array([alpha, beta, gamma])
        # x, y, z rotation point offset
        self.rot_pt = np.array([0., 0., 0.])
        self.rot_mat = None

    def __repr__(self):
        return "%r: Decenter: %r, Tilt: %r" % (self.dtype.name, self.dec,
                                               self.euler)

    def update(self):
        def convertl2r(self):
            return np.array([-self.euler[0], -self.euler[1], self.euler[2]])
        if self.euler.any():
            self.rot_mat = t3d.euler.euler2mat(*np.deg2rad(convertl2r(self)))
        else:
            self.rot_mat = None

    def tform_before_surf(self):
        if self.dtype is not dec.REV:
            return self.rot_mat, self.dec
        else:
            return None, np.array([0., 0., 0.])

    def tform_after_surf(self):
        if self.dtype is dec.REV or self.dtype is dec.DAR:
            return self.rot_mat.transpose(), -self.dec
        elif self.dtype is dec.BEND:
            return self.rot_mat, np.array([0., 0., 0.])
        else:
            return None, np.array([0., 0., 0.])


class Aperture():
    def __init__(self, x_offset=0.0, y_offset=0.0, rotation=0.0):
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.rotation = rotation

    def dimension(self):
        pass

    def set_dimension(self, x, y):
        pass

    def max_dimension(self):
        x, y = self.dimension()
        return sqrt(x*x + y*y)

    def bounding_box(self):
        center = np.array([self.x_offset, self.y_offset])
        extent = np.array(self.dimension())
        return center-extent, center+extent


class Circular(Aperture):
    def __init__(self, radius=1.0, **kwargs):
        super().__init__(**kwargs)
        self.radius = radius

    def dimension(self):
        return (self.radius, self.radius)

    def set_dimension(self, x, y):
        self.radius = sqrt(x*x + y*y)

    def max_dimension(self):
        return self.radius


class Rectangular(Aperture):
    def __init__(self, x_half_width=1.0, y_half_width=1.0, **kwargs):
        super().__init__(**kwargs)
        self.x_half_width = x_half_width
        self.y_half_width = y_half_width

    def dimension(self):
        return (self.x_half_width, self.y_half_width)

    def set_dimension(self, x, y):
        self.x_half_width = abs(x)
        self.y_half_width = abs(y)


class Elliptical(Aperture):
    def __init__(self, x_half_width=1.0, y_half_width=1.0, **kwargs):
        super().__init__(**kwargs)
        self.x_half_width = x_half_width
        self.y_half_width = y_half_width

    def dimension(self):
        return (self.x_half_width, self.y_half_width)

    def set_dimension(self, x, y):
        self.x_half_width = abs(x)
        self.y_half_width = abs(y)