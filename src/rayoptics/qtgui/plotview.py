#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright © 2018 Michael J. Hayford
""" Support for fully featured QT windows for plotting/matplotlib

.. Created on Wed Nov  7 15:04:19 2018

.. codeauthor: Michael J. Hayford
"""
from pathlib import Path

from PyQt5.QtCore import Qt as qt
from PyQt5.QtCore import QSize
from PyQt5 import QtGui
from PyQt5.QtWidgets import (QHBoxLayout, QVBoxLayout, QWidget, QLineEdit,
                             QRadioButton, QGroupBox, QSizePolicy, QCheckBox,
                             QListWidget, QListWidgetItem, QPushButton,
                             QToolBar)

from matplotlib.backends.backend_qt5agg \
     import (NavigationToolbar2QT as NavigationToolbar)

from rayoptics.gui.appmanager import ModelInfo
from rayoptics.qtgui.plotcanvas import PlotCanvas
from rayoptics.mpl.axisarrayfigure import Fit


def update_figure_view(plotFigure):
    plotFigure.refresh()


class CommandItem(QListWidgetItem):
    def __init__(self, parent, txt, cntxt):
        super().__init__(parent)
        self.setData(qt.DisplayRole, txt)
        self.setData(qt.EditRole, cntxt)

    def data(self, role):
        if role == qt.DisplayRole:
            return self.txt
        elif role == qt.EditRole:
            return self.cntxt
        else:
            return None

    def setData(self, role, value):
        if role == qt.DisplayRole:
            self.txt = value
            return True
        elif role == qt.EditRole:
            self.cntxt = value
            return True
        else:
            return False


def create_command_panel(fig, commands):
    command_panel = QListWidget()

    for c in commands:
        cmd_txt, cntxt = c
        cntxt[2]['figure'] = fig
        btn = CommandItem(command_panel, cmd_txt, cntxt)

    command_panel.itemClicked.connect(on_command_clicked)
    width = command_panel.size()
    hint = command_panel.sizeHint()
    frame_width = command_panel.frameWidth() + 2
    column_width = command_panel.sizeHintForColumn(0) + 2*frame_width
    command_panel.setMinimumWidth(column_width)
    command_panel.setMaximumWidth(column_width)
    command_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)

    return command_panel


def on_command_clicked(item):
    cntxt = item.data(qt.EditRole)
    fct, args, kwargs = cntxt
    fct(*args, **kwargs)


def create_plot_view(app, fig, title, view_width, view_ht, commands=None,
                     add_panel_fcts=None, add_nav_toolbar=False):
    # construct the top level widget
    widget = QWidget()

    top_layout = QHBoxLayout(widget)
    # set the layout on the widget
    widget.setLayout(top_layout)

    if commands:
        command_panel = create_command_panel(fig, commands)
        top_layout.addWidget(command_panel)

    # construct the top level layout
    plot_layout = QVBoxLayout()
    top_layout.addLayout(plot_layout)

    pc = PlotCanvas(app, fig)
    if add_panel_fcts is not None:
        panel_layout = QHBoxLayout()
        plot_layout.addLayout(panel_layout)
        for p in add_panel_fcts:
            panel = p(app, pc)
            panel_layout.addWidget(panel)
        panel_layout.addStretch(50)

    mi = ModelInfo(app.app_manager.model, update_figure_view, (fig,))
    sub_window = app.add_subwindow(widget, mi)
    sub_window.setWindowTitle(title)
    orig_x, orig_y = app.initial_window_offset()
    sub_window.setGeometry(orig_x, orig_y, view_width, view_ht)

    plot_layout.addWidget(pc)

    if add_nav_toolbar:
        plot_layout.addWidget(NavigationToolbar(pc, sub_window))

    sub_window.show()


def create_plot_scale_panel(app, pc):
    groupBox = QGroupBox("Plot Scale", app)

    user_scale_wdgt = QLineEdit()
    user_scale_wdgt.setReadOnly(True)
    pf = pc.figure
    cntxt = pf, user_scale_wdgt
    user_scale_wdgt.editingFinished.connect(lambda:
                                            on_plot_scale_changed(cntxt))
    fit_all_btn = QRadioButton("Fit All")
    fit_all_btn.setChecked(pf.scale_type == Fit.All)
    fit_all_btn.toggled.connect(lambda:
                                on_plot_scale_toggled(cntxt, Fit.All))
    fit_all_same_btn = QRadioButton("Fit All Same")
    fit_all_same_btn.setChecked(pf.scale_type == Fit.All_Same)
    fit_all_same_btn.toggled.connect(lambda: on_plot_scale_toggled(
                                             cntxt, Fit.All_Same))
    user_scale_btn = QRadioButton("User Scale")
    user_scale_btn.setChecked(pf.scale_type == Fit.User_Scale)
    user_scale_btn.toggled.connect(lambda: on_plot_scale_toggled(
                                           cntxt, Fit.User_Scale))
    box = QHBoxLayout()
    box.addWidget(fit_all_btn)
    box.addWidget(fit_all_same_btn)
    box.addWidget(user_scale_btn)
    box.addWidget(user_scale_wdgt)

    groupBox.setLayout(box)

    return groupBox


def on_plot_scale_toggled(cntxt, scale_type):
    plotFigure, scale_wdgt = cntxt
    plotFigure.scale_type = scale_type
    if scale_type == Fit.User_Scale:
        scale_wdgt.setReadOnly(False)
        scale_wdgt.setText('{:7.4f}'.format(plotFigure.user_scale_value))
    else:
        scale_wdgt.setReadOnly(True)

    plotFigure.plot()


def on_plot_scale_changed(cntxt):
    plotFigure, scale_wdgt = cntxt
    eval_str = scale_wdgt.text()
    try:
        val = eval(eval_str)
        plotFigure.user_scale_value = val
        scale_wdgt.setText('{:7.4f}'.format(val))
    except IndexError:
        return ''

    plotFigure.plot()


def get_icon(fig, icon_filepath, icon_size=48):
    pm = QtGui.QPixmap(str(icon_filepath)).scaled(icon_size, icon_size)
    # pm = QtGui.QPixmap(str(icon_filepath))
    if hasattr(pm, 'setDevicePixelRatio'):
        pm.setDevicePixelRatio(fig.canvas._dpi_ratio)
    return QtGui.QIcon(pm)


def create_2d_figure_toolbar(app, pc):
    """ zoom, fit and pan commands for figures
    Pan
    Zoom Box
    Fit
    Zoom In, Out
    1:1
    """
    icon_size=24
    tb = QToolBar()
    tb.setIconSize(QSize(icon_size, icon_size))
    tb.setStyleSheet("QToolBar{spacing:0px;}");

    toolitems = (
        ('Pan', 'Pan axes with mouse', 'pan', 'register_pan'),
        ('Zoom', 'Zoom to rectangle', 'zoom', 'register_zoom_box'),
        ('Fit', 'Fit to view', 'fit', 'fit'),
        ('Zoom In', 'Zoom in', 'zoom_in', 'zoom_in'),
        ('Zoom Out', 'Zoom out', 'zoom_out', 'zoom_out'),
      )

    pth = Path(__file__).resolve().parent
    image_dir = Path(pth / 'images')

    fig = pc.figure
    actions = {}
    for text, tooltip_text, image_file, callback in toolitems:
        if text is None:
            tb.addSeparator()
        else:
            def create_action_and_on_finished(fig, callback):
                def make_cb_fct():
                    def on_finished():
                        # unpress button when action is finished
                        actions[callback].setChecked(False)
                    getattr(fig, callback)(on_finished)
                return make_cb_fct

            image_path = image_dir / (image_file + '.png')
            icon = get_icon(fig, image_path, icon_size=icon_size)

            if callback in ['register_zoom_box', 'register_pan']:
                # action requires mouse input handling, unpress when finished
                a = tb.addAction(icon, text,
                                 create_action_and_on_finished(fig, callback))
                actions[callback] = a
                a.setCheckable(True)
            else:
                # immediate action button
                a = tb.addAction(icon, text, getattr(fig, callback))
                actions[callback] = a

            if tooltip_text is not None:
                a.setToolTip(tooltip_text)

    def attr_check(fig, attr, state):
        checked = state == qt.Checked
        setattr(fig, attr, checked)
        fig.refresh()

    # add checkbox for unit aspect ration display
    aratio_checkBox = QCheckBox("1:1")
    aratio_checkBox.setChecked(fig.is_unit_aspect_ratio)
    aratio_checkBox.stateChanged.connect(lambda checked: attr_check(fig,
                                         'is_unit_aspect_ratio', checked))
    tb.addWidget(aratio_checkBox)

    return tb


def create_draw_rays_groupbox(app, pc):
    groupBox = QGroupBox("", app)
    fig = pc.figure

    def attr_check(fig, attr, state):
        checked = state == qt.Checked
#        cur_value = getattr(fig, attr, None)
        setattr(fig, attr, checked)
        fig.refresh()

    parax_checkBox = QCheckBox("&paraxial rays")
    parax_checkBox.setChecked(fig.do_paraxial_layout)
    parax_checkBox.stateChanged.connect(lambda checked: attr_check(fig,
                                        'do_paraxial_layout', checked))
    edge_checkBox = QCheckBox("&edge rays")
    edge_checkBox.setChecked(fig.do_draw_rays)
    edge_checkBox.stateChanged.connect(lambda checked: attr_check(fig,
                                       'do_draw_rays', checked))

    hbox = QHBoxLayout()
    hbox.addWidget(parax_checkBox)
    hbox.addWidget(edge_checkBox)

    groupBox.setLayout(hbox)

    return groupBox


def create_diagram_controls_groupbox(app, pc):
    groupBox = QGroupBox("", app)

    def attr_check(fig, attr, state):
        checked = state == qt.Checked
#        cur_value = getattr(fig, attr, None)
        setattr(fig, attr, checked)
        print('attr_check: {}={}'.format(attr, checked))
        fig.refresh()

    barrel_value_wdgt = QLineEdit()
    barrel_value_wdgt.setReadOnly(True)
    fig = pc.figure
    cntxt = fig, barrel_value_wdgt
    barrel_value_wdgt.editingFinished.connect(lambda:
                                              on_barrel_constraint_changed(
                                                      cntxt))

    slide_checkBox = QCheckBox("&slide")
    slide_checkBox.setChecked(fig.enable_slide)
    slide_checkBox.stateChanged.connect(lambda checked: attr_check(fig,
                                        'enable_slide', checked))
    barrel_checkBox = QCheckBox("&barrel constraint")
    barrel_checkBox.setChecked(fig.diagram.do_barrel_constraint)
    barrel_checkBox.stateChanged.connect(lambda checked:
                                         on_barrel_constraint_toggled(
                                                 cntxt, checked))

    hbox = QHBoxLayout()
    hbox.addWidget(slide_checkBox)
    hbox.addWidget(barrel_checkBox)
    hbox.addWidget(barrel_value_wdgt)

    groupBox.setLayout(hbox)

    return groupBox


def on_barrel_constraint_toggled(cntxt, state):
    fig, barrel_wdgt = cntxt
    diagram = fig.diagram
    checked = state == qt.Checked
    if checked:
        diagram.do_barrel_constraint = True
        barrel_wdgt.setReadOnly(False)
        barrel_wdgt.setText('{:7.4f}'.format(diagram.barrel_constraint_radius))
    else:
        diagram.do_barrel_constraint = False
        barrel_wdgt.setReadOnly(True)

    fig.refresh()


def on_barrel_constraint_changed(cntxt):
    fig, barrel_wdgt = cntxt
    eval_str = barrel_wdgt.text()
    try:
        val = eval(eval_str)
        fig.diagram.barrel_constraint_radius = val
        barrel_wdgt.setText('{:7.4f}'.format(val))
    except IndexError:
        return ''

    fig.refresh()
