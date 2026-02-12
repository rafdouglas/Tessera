"""Tests for PercentageSplitAlgorithm.

Percentage split divides polygons into filled and remainder parts based on
a numeric attribute value. The split orientation can be horizontal, vertical,
diagonal (45/135 degrees), or radial. Output fields include _tessera_algorithm,
_tessera_parent_fid, _tessera_part, _tessera_value, and _tessera_fraction.
"""
import gc
import math
import time

import pytest
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType

from tessera.algorithms.percentage_split import PercentageSplitAlgorithm

from .helpers import make_fields, make_feature, make_layer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_percentage_split(layer, value_field='value', value_range=0,
                          orientation=0, extra_params=None):
    """Run PercentageSplitAlgorithm and return output features.

    Returns (features_list, result_dict, feedback, output_layer).
    """
    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        alg = PercentageSplitAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'VALUE_FIELD': value_field,
            'VALUE_RANGE': value_range,
            'ORIENTATION': orientation,
            'OUTPUT': 'memory:',
        }
        if extra_params:
            parameters.update(extra_params)
        results = alg.processAlgorithm(parameters, context, feedback)

        dest_id = results['OUTPUT']
        output_layer = context.takeResultLayer(dest_id)

        gc.collect()
        gc.disable()
        try:
            features = list(output_layer.getFeatures()) if output_layer else []
        finally:
            gc.enable()
        return features, results, feedback, output_layer
    finally:
        project.removeMapLayer(layer.id())


def _make_unit_square_feature(value=50.0):
    """Create a single unit-square feature at (0,0)-(1,1) in EPSG:4326."""
    fields = make_fields()
    ring = [QgsPointXY(0, 0), QgsPointXY(1, 0),
            QgsPointXY(1, 1), QgsPointXY(0, 1), QgsPointXY(0, 0)]
    geom = QgsGeometry.fromPolygonXY([ring])
    return make_feature(geom, 'unit', value, fields)


def _make_10x10_square_feature(value=70.0):
    """Create a 10x10 degree square at (0,0)-(10,10) in EPSG:4326."""
    fields = make_fields()
    ring = [QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)]
    geom = QgsGeometry.fromPolygonXY([ring])
    return make_feature(geom, 'big_square', value, fields)


# ===========================================================================
# T1 -- Percentage split produces output
# ===========================================================================

def test_percentage_split_produces_output(qgis_app):
    """Single square with value=50 produces 2 features (filled + remainder)."""
    feat = _make_unit_square_feature(50.0)
    layer = make_layer([feat])
    features, results, feedback, _ = _run_percentage_split(
        layer, value_field='value', value_range=0, orientation=0)

    assert len(features) == 2, \
        f"Expected 2 features (filled + remainder), got {len(features)}"
    for feat in features:
        geom = feat.geometry()
        assert not geom.isEmpty(), "Output geometry must not be empty"
        assert geom.isMultipart(), "Output geometry must be MultiPolygon"
        assert geom.type() == QgsWkbTypes.PolygonGeometry, \
            "Output geometry type must be PolygonGeometry"


# ===========================================================================
# T2 -- Output has correct _tessera_* fields
# ===========================================================================

def test_output_has_tessera_fields(qgis_app):
    """Output has _tessera_algorithm, _tessera_parent_fid, _tessera_part, _tessera_value, _tessera_fraction."""
    feat = _make_unit_square_feature(50.0)
    layer = make_layer([feat])
    features, results, feedback, _ = _run_percentage_split(
        layer, value_field='value', value_range=0, orientation=0)

    assert len(features) > 0
    feat = features[0]
    field_names = [feat.fields().field(i).name()
                   for i in range(feat.fields().count())]

    assert '_tessera_algorithm' in field_names
    assert '_tessera_parent_fid' in field_names
    assert '_tessera_part' in field_names
    assert '_tessera_value' in field_names
    assert '_tessera_fraction' in field_names
    assert '_tessera_tile_index' not in field_names, "Should not have _tessera_tile_index"
    assert '_tessera_stripe_index' not in field_names, "Should not have _tessera_stripe_index"

    for f in features:
        assert f.attribute('_tessera_algorithm') == 'percentage_split'


# ===========================================================================
# T3 -- Parent attributes carried forward
# ===========================================================================

def test_parent_attributes_carried(qgis_app):
    """Parent 'name' and 'value' attributes are carried to output."""
    feat = _make_unit_square_feature(50.0)
    layer = make_layer([feat])
    features, results, feedback, _ = _run_percentage_split(
        layer, value_field='value', value_range=0, orientation=0)

    assert len(features) > 0
    for f in features:
        assert f.attribute('name') == 'unit', \
            f"Expected 'unit', got {f.attribute('name')!r}"
        assert f.attribute('value') == 50.0, \
            f"Expected 50.0, got {f.attribute('value')!r}"


# ===========================================================================
# T4 -- Filled and remainder area ratio
# ===========================================================================

def test_filled_and_remainder_area_ratio(qgis_app):
    """For value=70 (0-100 range), filled area is approximately 70% of total."""
    feat = _make_10x10_square_feature(70.0)
    layer = make_layer([feat])
    features, results, feedback, _ = _run_percentage_split(
        layer, value_field='value', value_range=0, orientation=0)

    assert len(features) == 2, \
        f"Expected 2 features, got {len(features)}"

    parts = {}
    for f in features:
        parts[f.attribute('_tessera_part')] = f.geometry()

    assert 'filled' in parts, "Should have 'filled' part"
    assert 'remainder' in parts, "Should have 'remainder' part"

    filled_area = parts['filled'].area()
    remainder_area = parts['remainder'].area()
    total_area = filled_area + remainder_area

    actual_fraction = filled_area / total_area
    # Allow 5% tolerance (CRS round-trip + binary search tolerance)
    assert abs(actual_fraction - 0.7) < 0.05, \
        f"Filled fraction should be ~0.7, got {actual_fraction:.4f}"


# ===========================================================================
# T5 -- VALUE_RANGE 0-1
# ===========================================================================

def test_value_range_0_1(qgis_app):
    """Value=0.3 with VALUE_RANGE=1 (0-1) results in fraction=0.3."""
    feat = _make_10x10_square_feature(0.3)
    layer = make_layer([feat])
    features, results, feedback, _ = _run_percentage_split(
        layer, value_field='value', value_range=1, orientation=0)

    assert len(features) == 2, \
        f"Expected 2 features, got {len(features)}"

    # Check _tessera_fraction attribute
    for f in features:
        assert abs(f.attribute('_tessera_fraction') - 0.3) < 0.001, \
            f"Expected fraction ~0.3, got {f.attribute('_tessera_fraction')}"

    # Check area ratio
    parts = {}
    for f in features:
        parts[f.attribute('_tessera_part')] = f.geometry()

    filled_area = parts['filled'].area()
    remainder_area = parts['remainder'].area()
    total_area = filled_area + remainder_area

    actual_fraction = filled_area / total_area
    assert abs(actual_fraction - 0.3) < 0.05, \
        f"Filled fraction should be ~0.3, got {actual_fraction:.4f}"


# ===========================================================================
# T6 -- VALUE_RANGE auto-detect
# ===========================================================================

def test_value_range_auto_detect(qgis_app):
    """Values > 1 with VALUE_RANGE=2 (auto) are treated as percentages (divided by 100)."""
    # Create two features with values > 1 to trigger auto-detect
    fields = make_fields()
    ring1 = [QgsPointXY(0, 0), QgsPointXY(5, 0),
             QgsPointXY(5, 5), QgsPointXY(0, 5), QgsPointXY(0, 0)]
    ring2 = [QgsPointXY(10, 0), QgsPointXY(15, 0),
             QgsPointXY(15, 5), QgsPointXY(10, 5), QgsPointXY(10, 0)]
    geom1 = QgsGeometry.fromPolygonXY([ring1])
    geom2 = QgsGeometry.fromPolygonXY([ring2])
    feat1 = make_feature(geom1, 'sq1', 60.0, fields)
    feat2 = make_feature(geom2, 'sq2', 80.0, fields)
    layer = make_layer([feat1, feat2])

    features, results, feedback, _ = _run_percentage_split(
        layer, value_field='value', value_range=2, orientation=0)

    # Auto scale divides by max value (80.0): 60/80=0.75, 80/80=1.0
    # Feature with fraction=1.0 produces filled part only (no remainder)
    assert len(features) == 3, \
        f"Expected 3 features, got {len(features)}"

    # Check that fractions are 0.75 and 1.0 (auto-divided by max 80.0)
    fractions = set()
    for f in features:
        fractions.add(round(f.attribute('_tessera_fraction'), 2))

    assert 0.75 in fractions, f"Expected fraction 0.75, got {fractions}"
    assert 1.0 in fractions, f"Expected fraction 1.0, got {fractions}"


# ===========================================================================
# T7 -- Orientation vertical
# ===========================================================================

def test_orientation_vertical(qgis_app):
    """ORIENTATION=1 (vertical) produces a valid split."""
    feat = _make_10x10_square_feature(50.0)
    layer = make_layer([feat])
    features, results, feedback, _ = _run_percentage_split(
        layer, value_field='value', value_range=0, orientation=1)

    assert len(features) == 2, \
        f"Expected 2 features, got {len(features)}"

    parts = {}
    for f in features:
        parts[f.attribute('_tessera_part')] = f.geometry()

    assert 'filled' in parts
    assert 'remainder' in parts

    # For vertical split at 50%, both parts should have roughly equal area
    filled_area = parts['filled'].area()
    remainder_area = parts['remainder'].area()
    total_area = filled_area + remainder_area
    actual_fraction = filled_area / total_area
    assert abs(actual_fraction - 0.5) < 0.05, \
        f"Vertical split at 50% should give ~0.5 fraction, got {actual_fraction:.4f}"


# ===========================================================================
# T8 -- Orientation diagonal
# ===========================================================================

def test_orientation_diagonal(qgis_app):
    """ORIENTATION=2 (diagonal_45) produces valid output."""
    feat = _make_10x10_square_feature(50.0)
    layer = make_layer([feat])
    features, results, feedback, _ = _run_percentage_split(
        layer, value_field='value', value_range=0, orientation=2)

    assert len(features) == 2, \
        f"Expected 2 features, got {len(features)}"

    for f in features:
        geom = f.geometry()
        assert not geom.isEmpty(), "Diagonal split geometry must not be empty"
        assert geom.area() > 0, "Diagonal split part must have positive area"

    parts = {}
    for f in features:
        parts[f.attribute('_tessera_part')] = f.geometry()

    filled_area = parts['filled'].area()
    remainder_area = parts['remainder'].area()
    total_area = filled_area + remainder_area
    actual_fraction = filled_area / total_area
    assert abs(actual_fraction - 0.5) < 0.05, \
        f"Diagonal split at 50% should give ~0.5 fraction, got {actual_fraction:.4f}"


# ===========================================================================
# T9 -- Orientation radial
# ===========================================================================

def test_orientation_radial(qgis_app):
    """ORIENTATION=4 (radial) produces valid output."""
    feat = _make_10x10_square_feature(50.0)
    layer = make_layer([feat])
    features, results, feedback, _ = _run_percentage_split(
        layer, value_field='value', value_range=0, orientation=4)

    assert len(features) == 2, \
        f"Expected 2 features, got {len(features)}"

    for f in features:
        geom = f.geometry()
        assert not geom.isEmpty(), "Radial split geometry must not be empty"
        assert geom.area() > 0, "Radial split part must have positive area"

    parts = {}
    for f in features:
        parts[f.attribute('_tessera_part')] = f.geometry()

    filled_area = parts['filled'].area()
    remainder_area = parts['remainder'].area()
    total_area = filled_area + remainder_area
    actual_fraction = filled_area / total_area
    assert abs(actual_fraction - 0.5) < 0.05, \
        f"Radial split at 50% should give ~0.5 fraction, got {actual_fraction:.4f}"


# ===========================================================================
# T10 -- Fraction zero emits only remainder
# ===========================================================================

def test_fraction_zero_emits_only_remainder(qgis_app):
    """Value=0 produces only 1 feature with _tessera_part='remainder'."""
    feat = _make_10x10_square_feature(0.0)
    layer = make_layer([feat])
    features, results, feedback, _ = _run_percentage_split(
        layer, value_field='value', value_range=0, orientation=0)

    assert len(features) == 1, \
        f"Expected 1 feature for value=0, got {len(features)}"
    assert features[0].attribute('_tessera_part') == 'remainder', \
        f"Expected 'remainder' part, got {features[0].attribute('_tessera_part')!r}"


# ===========================================================================
# T11 -- Fraction full emits only filled
# ===========================================================================

def test_fraction_full_emits_only_filled(qgis_app):
    """Value=100 produces only 1 feature with _tessera_part='filled'."""
    feat = _make_10x10_square_feature(100.0)
    layer = make_layer([feat])
    features, results, feedback, _ = _run_percentage_split(
        layer, value_field='value', value_range=0, orientation=0)

    assert len(features) == 1, \
        f"Expected 1 feature for value=100, got {len(features)}"
    assert features[0].attribute('_tessera_part') == 'filled', \
        f"Expected 'filled' part, got {features[0].attribute('_tessera_part')!r}"


# ===========================================================================
# T12 -- MultiPolygon input
# ===========================================================================

def test_multipolygon_input(qgis_app, multipolygon):
    """MultiPolygon feature produces filled and remainder parts."""
    # Override the value attribute to 50
    multipolygon.setAttribute('value', 50.0)
    layer = make_layer([multipolygon])
    features, results, feedback, _ = _run_percentage_split(
        layer, value_field='value', value_range=0, orientation=0)

    assert len(features) == 2, \
        f"Expected 2 features (filled + remainder), got {len(features)}"

    # All features should have the same _tessera_parent_fid (single input feature)
    parent_fids = set(f.attribute('_tessera_parent_fid') for f in features)
    assert len(parent_fids) == 1, \
        f"All parts should share same parent fid, got {parent_fids}"

    parts = {}
    for f in features:
        parts[f.attribute('_tessera_part')] = f.geometry()

    assert 'filled' in parts
    assert 'remainder' in parts
    for p in parts.values():
        assert not p.isEmpty(), "Part geometry must not be empty"
        assert p.area() > 0, "Part must have positive area"


# ===========================================================================
# T13 -- Output CRS matches input
# ===========================================================================

def test_output_crs_matches_input(qgis_app):
    """Output layer CRS matches input layer CRS (EPSG:4326)."""
    feat = _make_unit_square_feature(50.0)
    layer = make_layer([feat], crs_id='EPSG:4326')

    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        alg = PercentageSplitAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'VALUE_FIELD': 'value',
            'VALUE_RANGE': 0,
            'ORIENTATION': 0,
            'OUTPUT': 'memory:',
        }
        results = alg.processAlgorithm(parameters, context, feedback)

        dest_id = results['OUTPUT']
        output_layer = context.takeResultLayer(dest_id)

        assert output_layer is not None
        assert output_layer.crs().authid() == 'EPSG:4326', \
            f"Expected EPSG:4326, got {output_layer.crs().authid()}"
    finally:
        project.removeMapLayer(layer.id())


# ===========================================================================
# T14 -- Parameters exist with correct types and defaults
# ===========================================================================

def test_parameters_exist(qgis_app):
    """Algorithm has VALUE_FIELD, VALUE_RANGE, ORIENTATION, FILLED_COLOR, REMAINDER_COLOR."""
    alg = PercentageSplitAlgorithm()
    alg.initAlgorithm()

    # VALUE_FIELD
    vf = alg.parameterDefinition('VALUE_FIELD')
    assert vf is not None, "VALUE_FIELD parameter should exist"

    # VALUE_RANGE
    vr = alg.parameterDefinition('VALUE_RANGE')
    assert vr is not None, "VALUE_RANGE parameter should exist"
    assert vr.options() == ['0 - 100', '0 - 1', 'Auto scale']
    assert vr.defaultValue() == 0

    # ORIENTATION
    orient = alg.parameterDefinition('ORIENTATION')
    assert orient is not None, "ORIENTATION parameter should exist"
    assert orient.options() == [
        'Horizontal', 'Vertical', 'Diagonal 45°', 'Diagonal 135°', 'Radial'
    ]
    assert orient.defaultValue() == 0

    # FILLED_COLOR (advanced, optional)
    fc = alg.parameterDefinition('FILLED_COLOR')
    assert fc is not None, "FILLED_COLOR parameter should exist"

    # REMAINDER_COLOR (advanced, optional)
    rc = alg.parameterDefinition('REMAINDER_COLOR')
    assert rc is not None, "REMAINDER_COLOR parameter should exist"


# ===========================================================================
# T15 -- _tessera_value and _tessera_fraction attributes correct
# ===========================================================================

def test_tessera_value_and_fraction_attributes(qgis_app):
    """Check _tessera_value stores raw value and _tessera_fraction stores computed fraction."""
    feat = _make_10x10_square_feature(70.0)
    layer = make_layer([feat])
    features, results, feedback, _ = _run_percentage_split(
        layer, value_field='value', value_range=0, orientation=0)

    for f in features:
        assert f.attribute('_tessera_value') == 70.0, \
            f"Expected _tessera_value=70.0, got {f.attribute('_tessera_value')}"
        assert abs(f.attribute('_tessera_fraction') - 0.7) < 0.001, \
            f"Expected _tessera_fraction~0.7, got {f.attribute('_tessera_fraction')}"


# ===========================================================================
# T16 -- Null/missing value skips feature with warning
# ===========================================================================

def test_null_value_skips_with_warning(qgis_app):
    """Feature with NULL value is skipped, warning issued."""
    fields = make_fields()
    ring = [QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)]
    geom = QgsGeometry.fromPolygonXY([ring])
    feat = QgsFeature(fields)
    feat.setGeometry(geom)
    feat.setAttribute('name', 'null_val')
    # Leave 'value' as NULL (don't set it)

    layer = make_layer([feat])

    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        warnings = []
        orig_warn = feedback.pushWarning

        def capture_warn(msg):
            warnings.append(msg)
            orig_warn(msg)

        feedback.pushWarning = capture_warn

        alg = PercentageSplitAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'VALUE_FIELD': 'value',
            'VALUE_RANGE': 0,
            'ORIENTATION': 0,
            'OUTPUT': 'memory:',
        }
        results = alg.processAlgorithm(parameters, context, feedback)

        dest_id = results['OUTPUT']
        output_layer = context.takeResultLayer(dest_id)

        gc.collect()
        gc.disable()
        try:
            features = list(output_layer.getFeatures()) if output_layer else []
        finally:
            gc.enable()

        # No output features for NULL value
        assert len(features) == 0, \
            f"Expected 0 features for NULL value, got {len(features)}"
        # Warning should have been issued
        assert len(warnings) > 0, "Should issue a warning for NULL value"
    finally:
        project.removeMapLayer(layer.id())


# ===========================================================================
# T17 -- Natural Earth integration
# ===========================================================================

def test_natural_earth_integration(qgis_app, natural_earth_path):
    """Percentage split produces output for Natural Earth countries with a
    numeric field, completes < 30s."""
    ne_layer = QgsVectorLayer(str(natural_earth_path), 'ne', 'ogr')
    assert ne_layer.isValid(), f"Natural Earth layer not valid: {natural_earth_path}"

    # Find a numeric field to use
    numeric_field = None
    for field in ne_layer.fields():
        if field.type() in (2, 6):  # Int, Double
            numeric_field = field.name()
            break

    if numeric_field is None:
        pytest.skip("No numeric field found in Natural Earth layer")

    start = time.time()
    features, results, feedback, _ = _run_percentage_split(
        ne_layer, value_field=numeric_field, value_range=2, orientation=0)
    elapsed = time.time() - start

    assert len(features) > 0, "Should produce output for Natural Earth"
    assert elapsed < 30, f"Should complete in < 30s, took {elapsed:.1f}s"

    parent_fids = set(f.attribute('_tessera_parent_fid') for f in features)
    assert len(parent_fids) > 1, \
        f"Should have parts from multiple countries, got {len(parent_fids)} parent fids"
