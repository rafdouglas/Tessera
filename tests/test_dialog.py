"""Tests for TesseraDialog (T8.5 -- T8.8)."""
import pytest
from PyQt5.QtWidgets import QCheckBox, QComboBox, QPushButton, QTextEdit
from qgis.core import QgsApplication
from qgis.gui import QgsMapLayerComboBox

from tessera.ui.main_dialog import TesseraDialog


# ---------------------------------------------------------------------------
# T8.5 -- Dialog creates with correct widgets
# ---------------------------------------------------------------------------

def test_dialog_has_layer_combo(qgis_app):
    """T8.5a: Dialog has a QgsMapLayerComboBox."""
    dialog = TesseraDialog()
    combos = dialog.findChildren(QgsMapLayerComboBox)
    assert len(combos) == 1


def test_dialog_has_algorithm_combo(qgis_app):
    """T8.5b: Dialog has an algorithm QComboBox."""
    dialog = TesseraDialog()
    assert isinstance(dialog.algorithm_combo, QComboBox)


def test_dialog_has_run_button(qgis_app):
    """T8.5c: Dialog has a Run button."""
    dialog = TesseraDialog()
    run_buttons = [b for b in dialog.findChildren(QPushButton)
                   if 'run' in b.text().lower()]
    assert len(run_buttons) == 1


def test_dialog_has_open_processing_button(qgis_app):
    """T8.5d: Dialog has an 'Open Processing Dialog' button."""
    dialog = TesseraDialog()
    proc_buttons = [b for b in dialog.findChildren(QPushButton)
                    if 'processing' in b.text().lower()]
    assert len(proc_buttons) == 1


def test_dialog_has_log_area(qgis_app):
    """T8.5e: Dialog has a log area (QTextEdit)."""
    dialog = TesseraDialog()
    logs = dialog.findChildren(QTextEdit)
    assert len(logs) >= 1


# ---------------------------------------------------------------------------
# T8.6 -- Dialog algorithm dropdown contains Tile Fill
# ---------------------------------------------------------------------------

def test_algorithm_dropdown_contains_tile_fill(qgis_app):
    """T8.6: Algorithm dropdown contains 'Tile Fill'."""
    dialog = TesseraDialog()
    items = [dialog.algorithm_combo.itemText(i)
             for i in range(dialog.algorithm_combo.count())]
    assert 'Tile Fill' in items


# ---------------------------------------------------------------------------
# T8.7 -- Dialog rebuilds parameter panel on algorithm change
# ---------------------------------------------------------------------------

def test_parameter_panel_shows_tile_fill_params(qgis_app):
    """T8.7: Parameter panel shows TILE_SHAPE, CELL_SIZE, TARGET_TILES, CLIP_BOUNDARY."""
    dialog = TesseraDialog()
    param_names = set(dialog.parameter_widgets.keys())
    assert param_names == {
        'TILE_SHAPE', 'CELL_SIZE', 'TARGET_TILES', 'CLIP_BOUNDARY',
        'CIRCLE_CRS', 'PERCENT_FIELD', 'PERCENT_RANGE',
    }


def test_tile_shape_widget_is_combobox(qgis_app):
    """T8.7b: TILE_SHAPE uses a QComboBox."""
    dialog = TesseraDialog()
    assert isinstance(dialog.parameter_widgets['TILE_SHAPE'], QComboBox)


def test_clip_boundary_widget_is_checkbox(qgis_app):
    """T8.7c: CLIP_BOUNDARY uses a QCheckBox."""
    dialog = TesseraDialog()
    assert isinstance(dialog.parameter_widgets['CLIP_BOUNDARY'], QCheckBox)


# ---------------------------------------------------------------------------
# T8.8 -- Dialog "Apply default style" checkbox exists
# ---------------------------------------------------------------------------

def test_apply_style_checkbox_exists(qgis_app):
    """T8.8: 'Apply default style' checkbox is present."""
    dialog = TesseraDialog()
    style_checkboxes = [cb for cb in dialog.findChildren(QCheckBox)
                        if 'style' in cb.text().lower()]
    assert len(style_checkboxes) == 1


# ---------------------------------------------------------------------------
# Phase 2: Dialog includes new algorithms
# ---------------------------------------------------------------------------

def test_algorithm_dropdown_contains_percentage_split(qgis_app):
    """Dialog algorithm dropdown contains 'Percentage Split'."""
    dialog = TesseraDialog()
    items = [dialog.algorithm_combo.itemText(i)
             for i in range(dialog.algorithm_combo.count())]
    assert 'Percentage Split' in items


def test_algorithm_dropdown_contains_stripe_hatching(qgis_app):
    """Dialog algorithm dropdown contains 'Stripe Hatching'."""
    dialog = TesseraDialog()
    items = [dialog.algorithm_combo.itemText(i)
             for i in range(dialog.algorithm_combo.count())]
    assert 'Stripe Hatching' in items


def test_algorithm_dropdown_has_eight_algorithms(qgis_app):
    """Dialog algorithm dropdown has exactly 8 algorithms."""
    dialog = TesseraDialog()
    assert dialog.algorithm_combo.count() == 9


def test_algorithm_dropdown_contains_snap_to_grid(qgis_app):
    """Dialog algorithm dropdown contains 'Snap to Grid'."""
    dialog = TesseraDialog()
    items = [dialog.algorithm_combo.itemText(i)
             for i in range(dialog.algorithm_combo.count())]
    assert 'Snap to Grid' in items


def test_algorithm_dropdown_contains_sketchy_borders(qgis_app):
    """Dialog algorithm dropdown contains 'Sketchy Borders'."""
    dialog = TesseraDialog()
    items = [dialog.algorithm_combo.itemText(i)
             for i in range(dialog.algorithm_combo.count())]
    assert 'Sketchy Borders' in items


def test_switching_to_snap_to_grid_rebuilds_params(qgis_app):
    """Selecting Snap to Grid rebuilds parameter panel with snap params."""
    dialog = TesseraDialog()
    dialog.algorithm_combo.setCurrentText('Snap to Grid')
    param_names = set(dialog.parameter_widgets.keys())
    assert 'GRID_TYPE' in param_names
    assert 'CELL_SIZE' in param_names
    assert 'AUTO_CELLS_ACROSS' in param_names
    assert 'ATTRACTION' in param_names


def test_switching_to_sketchy_borders_rebuilds_params(qgis_app):
    """Selecting Sketchy Borders rebuilds parameter panel with sketchy params."""
    dialog = TesseraDialog()
    dialog.algorithm_combo.setCurrentText('Sketchy Borders')
    param_names = set(dialog.parameter_widgets.keys())
    assert 'ROUGHNESS' in param_names
    assert 'DENSIFY_FACTOR' in param_names
    assert 'SEED' in param_names


def test_switching_to_stripe_hatching_rebuilds_params(qgis_app):
    """Selecting Stripe Hatching rebuilds parameter panel with stripe params."""
    dialog = TesseraDialog()
    dialog.algorithm_combo.setCurrentText('Stripe Hatching')
    param_names = set(dialog.parameter_widgets.keys())
    assert 'ANGLE' in param_names
    assert 'STRIPE_WIDTH' in param_names
    assert 'TARGET_STRIPES' in param_names


def test_switching_back_to_tile_fill_restores_params(qgis_app):
    """Switching back to Tile Fill restores tile_fill params."""
    dialog = TesseraDialog()
    dialog.algorithm_combo.setCurrentText('Stripe Hatching')
    dialog.algorithm_combo.setCurrentText('Tile Fill')
    param_names = set(dialog.parameter_widgets.keys())
    assert 'TILE_SHAPE' in param_names
    assert 'CELL_SIZE' in param_names


# ---------------------------------------------------------------------------
# Phase 4: Dialog includes cartogram family algorithms
# ---------------------------------------------------------------------------

def test_algorithm_dropdown_contains_scale_by_value(qgis_app):
    """Dialog algorithm dropdown contains 'Scale by Value'."""
    dialog = TesseraDialog()
    items = [dialog.algorithm_combo.itemText(i)
             for i in range(dialog.algorithm_combo.count())]
    assert 'Scale by Value' in items


def test_algorithm_dropdown_contains_replace_with_shape(qgis_app):
    """Dialog algorithm dropdown contains 'Replace with Shape'."""
    dialog = TesseraDialog()
    items = [dialog.algorithm_combo.itemText(i)
             for i in range(dialog.algorithm_combo.count())]
    assert 'Replace with Shape' in items


def test_algorithm_dropdown_contains_arrange_features(qgis_app):
    """Dialog algorithm dropdown contains 'Arrange Features'."""
    dialog = TesseraDialog()
    items = [dialog.algorithm_combo.itemText(i)
             for i in range(dialog.algorithm_combo.count())]
    assert 'Arrange Features' in items


def test_switching_to_scale_by_value_rebuilds_params(qgis_app):
    """Selecting Scale by Value rebuilds parameter panel with scale params."""
    dialog = TesseraDialog()
    dialog.algorithm_combo.setCurrentText('Scale by Value')
    param_names = set(dialog.parameter_widgets.keys())
    assert 'VALUE_FIELD' in param_names
    assert 'SCALE_METHOD' in param_names
    assert 'REFERENCE' in param_names
    assert 'MAX_SCALE' in param_names
    assert 'MIN_SCALE' in param_names
    assert 'CENTER_METHOD' in param_names


def test_switching_to_replace_with_shape_rebuilds_params(qgis_app):
    """Selecting Replace with Shape rebuilds parameter panel with shape params."""
    dialog = TesseraDialog()
    dialog.algorithm_combo.setCurrentText('Replace with Shape')
    param_names = set(dialog.parameter_widgets.keys())
    assert 'VALUE_FIELD' in param_names
    assert 'SHAPE' in param_names
    assert 'SCALE_METHOD' in param_names
    assert 'CIRCLE_SEGMENTS' in param_names


def test_switching_to_arrange_features_rebuilds_params(qgis_app):
    """Selecting Arrange Features rebuilds parameter panel with overlap params."""
    dialog = TesseraDialog()
    dialog.algorithm_combo.setCurrentText('Arrange Features')
    param_names = set(dialog.parameter_widgets.keys())
    assert 'MODE' in param_names
    assert 'SEPARATION_DISTANCE' in param_names
    assert 'QUALITY' in param_names
