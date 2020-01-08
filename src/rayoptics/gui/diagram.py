#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright © 2019 Michael J. Hayford
"""
.. Created on Wed Oct 16 14:20:49 2019

.. codeauthor: Michael J. Hayford
"""

import math
import numpy as np
from copy import deepcopy

from rayoptics.gui.util import GUIHandle, bbox_from_poly, fit_data_range

from rayoptics.optical.model_constants import ht, slp
from rayoptics.optical.model_constants import pwr, tau, indx, rmd
from rayoptics.util.rgb2mpl import rgb2mpl
from rayoptics.util.misc_math import projected_point_on_radial_line
from rayoptics.util import misc_math


class Diagram():
    """ class for paraxial ray rendering/editing """
    def __init__(self, opt_model, dgm_type, seq_start=1,
                 do_barrel_constraint=False, barrel_constraint=1.0,
                 label='paraxial'):
        self.label = label
        self.opt_model = opt_model

        self.dgm_type = dgm_type
        self.setup_dgm_type(dgm_type)

        self.do_barrel_constraint = do_barrel_constraint
        self.barrel_constraint_radius = barrel_constraint

    def setup_dgm_type(self, dgm_type):
        parax_model = self.opt_model.parax_model
        if dgm_type == 'ht':
            self.type_sel = ht
            self._apply_data = parax_model.apply_ht_dgm_data
        elif dgm_type == 'slp':
            self.type_sel = slp
            self._apply_data = parax_model.apply_slope_dgm_data

    def get_label(self):
        return self.label

    def update_data(self, fig):
        parax_model = self.opt_model.parax_model

        self.shape = self.render_shape()
        self.shape_bbox = bbox_from_poly(self.shape)
        if fig.build == 'update':
            # just a change in node positions - handled above
            # self.shape = self.render_shape()
            pass
        else:
            # number of nodes have changed, rebuild everything
            if fig.build == 'full_rebuild':
                # change from another non-parax_model source,
                #  rebuild parax_model
                parax_model.build_lens()

            self.node_list = []
            for i in range(len(parax_model.sys)):
                self.node_list.append(DiagramNode(self, i))

            self.edge_list = []
            for i in range(len(parax_model.sys)-1):
                self.edge_list.append(DiagramEdge(self, i))

            self.object_shift = ConjugateLine(self, 'object_image')
            if self.opt_model.seq_model.stop_surface is None:
                # stop shift conjugate line is only editable for floating stop
                self.stop_shift = ConjugateLine(self, 'stop')

            if self.do_barrel_constraint:
                self.barrel_constraint = BarrelConstraint(self)

        self.node_bbox = fig.update_patches(self.node_list)
        self.edge_bbox = fig.update_patches(self.edge_list)

        self.object_shift_bbox = fig.update_patches([self.object_shift])
        if self.opt_model.seq_model.stop_surface is None:
            self.stop_shift_bbox = fig.update_patches([self.stop_shift])

        if self.do_barrel_constraint:
            self.barrel_bbox = fig.update_patches([self.barrel_constraint])

        return self.shape_bbox

    def apply_data(self, node, vertex):
        self._apply_data(node, vertex)
        self.opt_model.parax_model.paraxial_lens_to_seq_model()

    def assign_object_to_node(self, node, factory, **kwargs):
        parax_model = self.opt_model.parax_model
        inputs = parax_model.assign_object_to_node(node, factory, **kwargs)
        parax_model.paraxial_lens_to_seq_model()
        return inputs

    def register_commands(self, *args, **inputs):
        fig = inputs.pop('figure')
        self.command_inputs = dict(inputs)

        def do_command_action(event, target, event_key):
            nonlocal fig
            if target is not None:
                shape, handle = target.artist.shape
                try:
#                    print(type(shape).__name__, shape.node, handle, event_key)
                    handle_action_obj = shape.actions[handle]
                    if isinstance(handle_action_obj, dict):
                        handle_action_obj[event_key](fig, event)
                    else:
                        handle_action_obj.actions[event_key](fig, event)
                except KeyError:
                    pass
        fig.do_action = do_command_action

    def register_add_replace_element(self, *args, **inputs):
        fig = inputs.pop('figure')
        self.command_inputs = dict(inputs)
        action_obj = AddReplaceElementAction(self, **inputs)

        def do_command_action(event, target, event_key):
            nonlocal fig
            shape, handle = target.artist.shape
            if isinstance(shape, DiagramNode) or \
               isinstance(shape, DiagramEdge):
                try:
                    action_obj.actions[event_key](fig, event, shape)
                except KeyError:
                    pass
        fig.do_action = do_command_action

    def render_shape(self):
        """ render the diagram into a shape list """
        parax_model = self.opt_model.parax_model
        shape = []
        for x, y in zip(parax_model.pr, parax_model.ax):
            shape.append([x[self.type_sel], y[self.type_sel]])
        shape = np.array(shape)
        return shape

    def update_diagram_from_shape(self, shape):
        ''' use the shape list to update the paraxial model '''
        parax_model = self.opt_model.parax_model
        for x, y, shp in zip(parax_model.pr, parax_model.ax, shape):
            x[self.type_sel] = shp[0]
            y[self.type_sel] = shp[1]

    def fit_axis_limits(self):
        ''' define diagram axis limits as the extent of the shape polygon '''
        x_min, x_max = fit_data_range([x[0] for x in self.shape])
        y_min, y_max = fit_data_range([x[1] for x in self.shape])
        return np.array([[x_min, y_min], [x_max, y_max]])


def compute_slide_line(shape, node, imode):
    """ compute a constraint line to keep the overall length of the airspaces
        surrounding `node` constant
    """
    def distance_sqr(pt):
        return pt[0]**2 + pt[1]**2
    num_nodes = len(shape)
    if node > 0 and node < num_nodes-1:
        pt0 = shape[node-1]
        pt1 = shape[node]
        pt2 = shape[node+1]
        if imode == 'transmit':
            # if transmitting, constrain movement of node to a line parallel
            #  to the line between the previous and next nodes.
            origin2line = misc_math.perpendicular_from_origin(pt0, pt2)
            pt2line = misc_math.perpendicular_to_line(pt1, pt0, pt2)
            scale_factor = (origin2line - pt2line)/origin2line
            new_pt0 = scale_factor*pt0
            new_pt2 = scale_factor*pt2
            return new_pt0, new_pt2
        elif imode == 'reflect':
            # if reflecting, constrain movement to a radial line from the
            #  origin through the selected node
            origin = np.array([0., 0.])
            dist_pt0 = distance_sqr(pt0)
            dist_pt1 = distance_sqr(pt1)
            dist_pt2 = distance_sqr(pt2)
            # figure out how long a line to draw
            dist = dist_pt0 if dist_pt0 > dist_pt1 else dist_pt1
            dist = dist_pt2 if dist_pt2 > dist else dist
            scale_factor = math.sqrt(dist/dist_pt1)
            new_pt1 = scale_factor*pt1
            return origin, new_pt1
    return None


class DiagramNode():
    def __init__(self, diagram, idx):
        self.diagram = diagram
        self.node = idx
        self.select_pt = None
        self.move_direction = None
        self.handles = {}
        self.actions = self.handle_actions()

    def update_shape(self, view):
        n_color = rgb2mpl([138, 43, 226])  # blueviolet
        sys = self.diagram.opt_model.parax_model.sys
        shape = self.diagram.shape
        self.handles['shape'] = shape[self.node], 'vertex', {'linestyle': '',
                                                             'marker': 's',
                                                             'picker': 6,
                                                             'color': n_color,
                                                             'hilite': 'red',
                                                             'zorder': 3.}
        # define the "constant spacing" or "slide" constraint
        if view.enable_slide:
            slide_pts = compute_slide_line(shape, self.node,
                                           sys[self.node][rmd])
            if slide_pts is not None:
                seg = [*slide_pts]
                f_color = rgb2mpl([138, 43, 226, 127])  # blueviolet
                h_color = rgb2mpl([138, 43, 226, 255])  # blueviolet

                self.handles['slide'] = seg, 'polyline', {'linestyle': ':',
                                                          'picker': 6,
                                                          'color': f_color,
                                                          'hilite': h_color,
                                                          'zorder': 2.5}
        gui_handles = {}
        for key, graphics_handle in self.handles.items():
            poly_data, poly_type, kwargs = graphics_handle
            poly = np.array(poly_data)
            if poly_type == 'vertex':
                p = view.create_vertex(poly, **kwargs)
            elif poly_type == 'polyline':
                p = view.create_polyline(poly, **kwargs)
            elif poly_type == 'polygon':
                p = view.create_polygon(poly, self.render_color(),
                                        **kwargs)
            else:
                break
            if len(poly.shape) > 1:
                bbox = bbox_from_poly(poly)
            else:
                x = poly[0]
                y = poly[1]
                bbox = np.array([[x, y], [x, y]])
            gui_handles[key] = GUIHandle(p, bbox)
        return gui_handles

    def render_color(self):
        e = self.diagram.opt_model.ele_model.elements[self.node]
        return e.render_color

    def get_label(self):
        return 'node' + str(self.node)

    def constrain_to_line_action(pt0, pt2):

        def constrain_to_line(input_pt):
            """ constrain the input point to the line pt0 to pt2 """
            output_pt = misc_math.projected_point_on_line(input_pt, pt0, pt2)
            return output_pt

        return constrain_to_line

    def handle_actions(self):
        actions = {}
        actions['shape'] = EditNodeAction(self)
        slide_filter = None
        sys = self.diagram.opt_model.parax_model.sys
        slide_pts = compute_slide_line(self.diagram.shape, self.node,
                                       sys[self.node][rmd])
        if slide_pts is not None:
            slide_filter = DiagramNode.constrain_to_line_action(*slide_pts)
        actions['slide'] = EditNodeAction(self, filter=slide_filter)
        return actions


class DiagramEdge():
    def __init__(self, diagram, idx):
        self.diagram = diagram
        self.node = idx
        self.select_pt = None
        self.move_direction = None
        self.handles = {}
        self.actions = self.handle_actions()

    def update_shape(self, view):
        shape = self.diagram.shape
        edge_poly = shape[self.node:self.node+2]
        self.handles['shape'] = edge_poly, 'polyline', {'picker': 6,
                                                        'hilite': 'red',
                                                        'zorder': 2.}
        area_poly = [[0, 0]]
        area_poly.extend(edge_poly)
        fill_color = self.render_color()
        self.handles['area'] = area_poly, 'polygon', {'fill_color': fill_color,
                                                      'zorder': 1.}

        gui_handles = {}
        for key, graphics_handle in self.handles.items():
            poly_data, poly_type, kwargs = graphics_handle
            poly = np.array(poly_data)
            if poly_type == 'polygon':
                p = view.create_polygon(poly, self.render_color(), **kwargs)
            elif poly_type == 'polyline':
                p = view.create_polyline(poly, **kwargs)
            else:
                break
            gui_handles[key] = GUIHandle(p, bbox_from_poly(poly))
        return gui_handles

    def render_color(self):
        gap = self.diagram.opt_model.seq_model.gaps[self.node]
        e = self.diagram.opt_model.ele_model.gap_dict.get(gap)
        if hasattr(e, 'gap'):
            return e.render_color
        else:
            # single surface element, like mirror or thinlens, use airgap
            return (237, 243, 254, 64)  # light blue

    def get_label(self):
        return 'edge' + str(self.node)

    def handle_actions(self):
        actions = {}
        actions['shape'] = AddElementAction(self)
        return actions


class BarrelConstraint():
    def __init__(self, diagram):
        self.diagram = diagram
        self.handles = {}
        self.actions = self.handle_actions()

    def update_shape(self, view):
        barrel_radius = self.diagram.barrel_constraint_radius
        diamond = []
        diamond.append([0., barrel_radius])
        diamond.append([barrel_radius, 0.])
        diamond.append([0., -barrel_radius])
        diamond.append([-barrel_radius, 0.])
        diamond.append([0., barrel_radius])
        diamond = np.array(diamond)
        self.handles['shape'] = diamond, 'polyline', {'color': 'black',
                                                      'zorder': 1.}
        square = []
        square.append([ barrel_radius,  barrel_radius])
        square.append([-barrel_radius,  barrel_radius])
        square.append([-barrel_radius, -barrel_radius])
        square.append([ barrel_radius, -barrel_radius])
        square.append([ barrel_radius,  barrel_radius])
        square = np.array(square)
        self.handles['square'] = square, 'polyline', {'color': 'black',
                                                      'zorder': 1.}

        gui_handles = {}
        for key, graphics_handle in self.handles.items():
            poly_data, poly_type, kwargs = graphics_handle
            poly = np.array(poly_data)
            if poly_type == 'polygon':
                p = view.create_polygon(poly, self.render_color(), **kwargs)
            elif poly_type == 'polyline':
                p = view.create_polyline(poly, **kwargs)
            else:
                break
            gui_handles[key] = GUIHandle(p, bbox_from_poly(poly))
        return gui_handles

    def render_color(self):
        return 'black'

    def get_label(self):
        return 'barrel constraint'

    def handle_actions(self):
        actions = {}
        return actions


class ConjugateLine():
    def __init__(self, diagram, line_type):
        self.diagram = diagram
        self.line_type = line_type
        self.sys_orig = []
        self.shape_orig = []
        self.handles = {}
        self.actions = self.handle_actions()

    def update_shape(self, view):
        shape_bbox = self.diagram.shape_bbox
        line = []
        if self.line_type == 'stop':
            ht = shape_bbox[1][1] - shape_bbox[0][1]
            line.append([0., -2*ht])
            line.append([0., 2*ht])
        elif self.line_type == 'object_image':
            wid = shape_bbox[1][0] - shape_bbox[0][0]
            line.append([-2*wid, 0.])
            line.append([2*wid, 0.])
        self.handles['shape'] = line, 'polyline', {'color': 'black',
                                                   'zorder': 1.}

        if len(self.shape_orig) > 0:
            conj_line = []
            if self.line_type == 'stop':
                lwr, upr = view.ax.get_ybound()
                ht = upr - lwr
                conj_line.append([self.k*ht, -ht])
                conj_line.append([-self.k*ht, ht])
            elif self.line_type == 'object_image':
                lwr, upr = view.ax.get_xbound()
                wid = upr - lwr
                conj_line.append([-wid, self.k*wid])
                conj_line.append([wid, -self.k*wid])
            self.handles['conj_line'] = conj_line, 'polyline', \
                                                  {'color': 'orange',
                                                   'zorder': 1.}
            self.handles['shift'] = self.shape_orig, 'polyline', \
                                                    {'color': 'blue',
                                                     'zorder': 1.}

        gui_handles = {}
        for key, graphics_handle in self.handles.items():
            poly_data, poly_type, kwargs = graphics_handle
            poly = np.array(poly_data)
            if poly_type == 'polygon':
                p = view.create_polygon(poly, self.render_color(), **kwargs)
            elif poly_type == 'polyline':
                p = view.create_polyline(poly, **kwargs)
            else:
                break
            gui_handles[key] = GUIHandle(p, bbox_from_poly(poly))
        return gui_handles

    def render_color(self):
        return 'black'

    def get_label(self):
        if self.line_type == 'stop':
            return 'stop shift line'
        elif self.line_type == 'object_image':
            return 'object shift line'
        else:
            return ''

    def edit_conjugate_line_actions(self):
        dgm = self.diagram
        pm = dgm.opt_model.parax_model

        def calculate_slope(x, y):
            ''' x=ybar, y=y  '''
            if self.line_type == 'stop':
                k = -x/y
                return k, np.array([[1, 0], [k, 1]])
            elif self.line_type == 'object_image':
                k = -y/x
                return k, np.array([[1, k], [0, 1]])
            else:
                return 0, np.array([[1, 0], [0, 1]])

        def apply_data(event_data):
            self.k, mat = calculate_slope(event_data[0], event_data[1])
            # apply the shear transformation to the original shape
            dgm.shape = self.shape_orig.dot(mat)

            dgm.update_diagram_from_shape(dgm.shape)

            # update slope values
            for i in range(1, len(dgm.shape)):
                pm.pr[i-1][slp] = ((pm.pr[i][ht] - pm.pr[i-1][ht]) /
                                   self.sys_orig[i-1][tau])
                pm.ax[i-1][slp] = ((pm.ax[i][ht] - pm.ax[i-1][ht]) /
                                   self.sys_orig[i-1][tau])
            pm.pr[-1][slp] = pm.pr[-2][slp]
            pm.ax[-1][slp] = pm.ax[-2][slp]

            if self.line_type == 'object_image':
                # update object distance and object y and ybar
                pm.sys[0][tau] = pm.ax[1][ht]/pm.ax[0][slp]
                pm.ax[0][ht] = 0
                pm.pr[0][ht] = pm.pr[1][ht] - pm.sys[0][tau]*pm.pr[0][slp]

                # update image distance and image y and ybar
                pm.sys[-2][tau] = -pm.ax[-2][ht]/pm.ax[-2][slp]
                pm.ax[-1][ht] = 0
                pm.pr[-1][ht] = pm.pr[-2][ht] + pm.sys[-2][tau]*pm.pr[-2][slp]

            pm.paraxial_lens_to_seq_model()

        def on_select(fig, event):
            self.sys_orig = deepcopy(pm.sys)
            self.shape_orig = deepcopy(dgm.shape)

        def on_edit(fig, event):
            if event.xdata is not None and event.ydata is not None:
                event_data = np.array([event.xdata, event.ydata])
                apply_data(event_data)
                fig.build = 'update'
                fig.refresh_gui()

        def on_release(fig, event):
            event_data = np.array([event.xdata, event.ydata])
            apply_data(event_data)
            self.sys_orig = []
            self.shape_orig = []
            fig.refresh_gui()

        actions = {}
        actions['press'] = on_select
        actions['drag'] = on_edit
        actions['release'] = on_release
        return actions

    def handle_actions(self):
        actions = {}
        actions['shape'] = self.edit_conjugate_line_actions()
        return actions


class EditNodeAction():
    """ Action to move a diagram node, using an input pt """
    def __init__(self, dgm_node, filter=None):
        diagram = dgm_node.diagram
        self.cur_node = None
        self.pt0 = None
        self.pt2 = None
        self.filter = filter

        def point_on_line(pt1, pt2, t):
            d = pt2 - pt1
            return pt1 + t*d

        def constrain_to_wedge(input_pt):
            """ keep the input point inside the wedge of adjacent points """

            if self.pt0 is not None:
                x_prod0 = input_pt[0]*self.pt0[1] - self.pt0[0]*input_pt[1]
                if x_prod0 < 0:
                    # pin to boundary
                    output_pt = projected_point_on_radial_line(input_pt,
                                                               self.pt0)
                    return output_pt

            if self.pt2 is not None:
                x_prod2 = input_pt[0]*self.pt2[1] - self.pt2[0]*input_pt[1]
                if x_prod2 > 0:
                    # pin to boundary
                    output_pt = projected_point_on_radial_line(input_pt,
                                                               self.pt2)
                    return output_pt

            return input_pt

        def on_select(fig, event):
            nonlocal diagram
            # we don't allow points to move onto their adjacent neighbors. Use
            #  a buffer amount when constraining to the wedge
            buffer_fraction = 0.0025
            self.cur_node = dgm_node.node
            pt1 = diagram.shape[self.cur_node]
            if self.cur_node == 0:
                pt2 = diagram.shape[self.cur_node+1]
                self.pt2 = point_on_line(pt1, pt2, 1-buffer_fraction)
                self.pt0 = None
            elif self.cur_node == len(diagram.shape)-1:
                pt0 = diagram.shape[self.cur_node-1]
                self.pt0 = point_on_line(pt0, pt1, buffer_fraction)
                self.pt2 = None
            else:
                pt0 = diagram.shape[self.cur_node-1]
                self.pt0 = point_on_line(pt0, pt1, buffer_fraction)
                pt2 = diagram.shape[self.cur_node+1]
                self.pt2 = point_on_line(pt1, pt2, 1-buffer_fraction)

        def on_edit(fig, event):
            if event.xdata is not None and event.ydata is not None:
                event_data = np.array([event.xdata, event.ydata])
                if self.filter:
                    event_data = self.filter(event_data)
                event_data = constrain_to_wedge(event_data)
                diagram.apply_data(self.cur_node, event_data)
                fig.build = 'update'
                fig.refresh_gui()

        def on_release(fig, event):
            if event.xdata is not None and event.ydata is not None:
                event_data = np.array([event.xdata, event.ydata])
                if self.filter:
                    event_data = self.filter(event_data)
                event_data = constrain_to_wedge(event_data)
                diagram.apply_data(self.cur_node, event_data)
                fig.build = 'update'
                fig.refresh_gui()
                self.cur_node = None

        self.actions = {}
        self.actions['drag'] = on_edit
        self.actions['press'] = on_select
        self.actions['release'] = on_release


class AddReplaceElementAction():
    ''' insert or replace a node with a chunk from a factory fct 
    The do_command_action fct registered for this operation passes the shape
    being operated upon; these can be:
        DiagramEdge -> insert/add the chunk returned by the factory fct
        DiagramNode -> replace the selected node with the factory fct return
    Inserting is done by splitting the corresponding gap in two. A new gap
    and an AirGap element are tacked on to the chunk returned from the factory
    fct.
    Replacing is done when a DiagramNode is selected. The gaps surrounding the
    node are retained, and modified as needed to accomodate the chunk.
    '''
    def __init__(self, diagram, **kwargs):
        seq_model = diagram.opt_model.seq_model
        parax_model = diagram.opt_model.parax_model
        self.cur_node = None

        def on_press_add_point(fig, event, shape):
            # if we don't have factory functions, skip the command
            if isinstance(shape, DiagramEdge):
                if 'node_init' in diagram.command_inputs and \
                   'factory' in diagram.command_inputs:
    
                    self.cur_node = shape.node
                    event_data = np.array([event.xdata, event.ydata])
                    interact = diagram.command_inputs['interact_mode']
                    parax_model.add_node(self.cur_node, event_data,
                                         diagram.type_sel, interact)
                    self.cur_node += 1
                    # create a node for editing during the drag action
                    #  'node_init' will currently be a thinlens or a mirror
                    node_init = diagram.command_inputs['node_init']
                    self.init_inputs = diagram.assign_object_to_node(self.cur_node,
                                                                     node_init,
                                                                     insert=True)
                    fig.build = 'rebuild'
                    fig.refresh_gui()
            elif isinstance(shape, DiagramNode):
                if 'factory' in diagram.command_inputs:
                    # replacing a node with a chunk only requires recording
                    # what chunk corresponds to the current node. There is 
                    # no drag action
                    self.cur_node = node = shape.node
                    self.init_inputs = parax_model.get_object_for_node(node)

        def on_drag_add_point(fig, event, shape):
            if self.cur_node is not None and isinstance(shape, DiagramEdge):
                event_data = np.array([event.xdata, event.ydata])
                diagram.apply_data(self.cur_node, event_data)
                fig.build = 'update'
                fig.refresh_gui()

        def on_release_add_point(fig, event, shape):
            if self.cur_node is not None:
                factory = diagram.command_inputs['factory']
                # if factory and node_init fcts are the same, we're done;
                # always call factory fct for a node
                if factory != diagram.command_inputs['node_init'] or \
                              isinstance(shape, DiagramNode):
                    prev_ifc = seq_model.ifcs[self.cur_node]
                    inputs = diagram.assign_object_to_node(self.cur_node,
                                                           factory)
                    idx = seq_model.ifcs.index(prev_ifc)
                    n_after = parax_model.sys[idx-1][indx]
                    thi = n_after*parax_model.sys[idx-1][tau]
                    seq_model.gaps[idx-1].thi = thi
                    # remove the edit scaffolding or previous node from model
                    args, kwargs = self.init_inputs
                    diagram.opt_model.remove_ifc_gp_ele(*args, **kwargs)
                fig.build = 'rebuild'
                fig.refresh_gui()
            self.cur_node = None

        self.actions = {}
        self.actions['press'] = on_press_add_point
        self.actions['drag'] = on_drag_add_point
        self.actions['release'] = on_release_add_point


class AddElementAction():
    ''' Deprecated '''
    def __init__(self, dgm_edge, **kwargs):
        diagram = dgm_edge.diagram
        seq_model = diagram.opt_model.seq_model
        parax_model = diagram.opt_model.parax_model
        self.cur_node = None

        def on_press_add_point(fig, event):
            # if we don't have factory functions, skip the command
            if 'node_init' in diagram.command_inputs and \
               'factory' in diagram.command_inputs:

                self.cur_node = dgm_edge.node
                event_data = np.array([event.xdata, event.ydata])
                interact = diagram.command_inputs['interact_mode']
                parax_model.add_node(self.cur_node, event_data,
                                     diagram.type_sel, interact)
                self.cur_node += 1
                node_init = diagram.command_inputs['node_init']
                self.init_inputs = diagram.assign_object_to_node(self.cur_node,
                                                                 node_init)
                fig.build = 'rebuild'
                fig.refresh_gui()

        def on_drag_add_point(fig, event):
            if self.cur_node is not None:
                event_data = np.array([event.xdata, event.ydata])
                diagram.apply_data(self.cur_node, event_data)
                fig.build = 'update'
                fig.refresh_gui()

        def on_release_add_point(fig, event):
            if self.cur_node is not None:
                factory = diagram.command_inputs['factory']
                if factory != diagram.command_inputs['node_init']:
                    prev_ifc = seq_model.ifcs[self.cur_node]
                    inputs = diagram.assign_object_to_node(self.cur_node,
                                                           factory)
                    idx = seq_model.ifcs.index(prev_ifc)
                    n_after = parax_model.sys[idx-1][indx]
                    thi = n_after*parax_model.sys[idx-1][tau]
                    seq_model.gaps[idx-1].thi = thi
                    args, kwargs = self.init_inputs
                    diagram.opt_model.remove_ifc_gp_ele(*args, **kwargs)
                fig.build = 'rebuild'
                fig.refresh_gui()
            self.cur_node = None

        self.actions = {}
        self.actions['press'] = on_press_add_point
        self.actions['drag'] = on_drag_add_point
        self.actions['release'] = on_release_add_point
