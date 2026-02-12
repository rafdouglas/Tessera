"""Tests for ScaleByValueAlgorithm.

Scale by Value resizes each polygon proportionally to an attribute value.
Shape is preserved; only the scale changes.  Output fields include
_tessera_algorithm, _tessera_parent_fid, _tessera_value, and _tessera_scale_factor.
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
    QgsProcessingParameterDefinition,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType

from tessera.algorithms.scale_by_value import ScaleByValueAlgorithm

from .helpers import make_fields, make_feature, make_layer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_scale_by_value(layer, value_field='value', scale_method=0,
                        reference=0, fixed_reference=100.0, max_scale=3.0,
                        min_scale=0.1, center_method=1, extra_params=None):
    """Run ScaleByValueAlgorithm and return output features.

    Returns (features_list, result_dict, feedback, output_layer).
    """
    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        alg = ScaleByValueAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'VALUE_FIELD': value_field,
            'SCALE_METHOD': scale_method,
            'REFERENCE': reference,
            'FIXED_REFERENCE': fixed_reference,
            'MAX_SCALE': max_scale,
            'MIN_SCALE': min_scale,
            'CENTER_METHOD': center_method,
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


def _make_square_feature(x, y, size, value, name='sq'):
    """Create a square feature at (x, y) with given size and value.

    Coordinates are in projected CRS (metres) so area = size^2.
    """
    fields = make_fields()
    ring = [
        QgsPointXY(x, y),
        QgsPointXY(x + size, y),
        QgsPointXY(x + size, y + size),
        QgsPointXY(x, y + size),
        QgsPointXY(x, y),
    ]
    geom = QgsGeometry.fromPolygonXY([ring])
    return make_feature(geom, name, value, fields)


def _make_100m_square(value, name='sq'):
    """Create a 100m x 100m square at origin with given value."""
    return _make_square_feature(500000, 5000000, 100, value, name)


# ===========================================================================
# T1 -- Import and metadata
# ===========================================================================

def test_import_and_metadata(qgis_app):
    """ScaleByValueAlgorithm has correct name, displayName, group, groupId."""
    alg = ScaleByValueAlgorithm()
    assert alg.name() == 'scale_by_value'
    assert alg.displayName() == 'Scale by Value'
    assert alg.group() == 'Shape'
    assert alg.groupId() == 'shape'

    # createInstance returns a new object of the same type
    inst = alg.createInstance()
    assert isinstance(inst, ScaleByValueAlgorithm)
    assert inst is not alg


# ===========================================================================
# T2 -- Parameters defined correctly
# ===========================================================================

def test_parameters_defined(qgis_app):
    """Algorithm has all required parameters with correct types and defaults."""
    alg = ScaleByValueAlgorithm()
    alg.initAlgorithm()

    # VALUE_FIELD
    vf = alg.parameterDefinition('VALUE_FIELD')
    assert vf is not None, "VALUE_FIELD parameter must exist"

    # SCALE_METHOD
    sm = alg.parameterDefinition('SCALE_METHOD')
    assert sm is not None, "SCALE_METHOD parameter must exist"
    assert sm.options() == ['Proportional area', 'Square root', 'Logarithmic']
    assert sm.defaultValue() == 0

    # REFERENCE
    ref = alg.parameterDefinition('REFERENCE')
    assert ref is not None, "REFERENCE parameter must exist"
    assert ref.options() == ['Maximum value', 'Mean value', 'Fixed']
    assert ref.defaultValue() == 0

    # FIXED_REFERENCE (Advanced)
    fr = alg.parameterDefinition('FIXED_REFERENCE')
    assert fr is not None, "FIXED_REFERENCE parameter must exist"
    assert fr.defaultValue() == 100.0
    assert fr.flags() & QgsProcessingParameterDefinition.FlagAdvanced, \
        "FIXED_REFERENCE should be flagged as Advanced"

    # MAX_SCALE
    mx = alg.parameterDefinition('MAX_SCALE')
    assert mx is not None, "MAX_SCALE parameter must exist"
    assert mx.defaultValue() == 3.0

    # MIN_SCALE
    mn = alg.parameterDefinition('MIN_SCALE')
    assert mn is not None, "MIN_SCALE parameter must exist"
    assert mn.defaultValue() == 0.1

    # CENTER_METHOD
    cm = alg.parameterDefinition('CENTER_METHOD')
    assert cm is not None, "CENTER_METHOD parameter must exist"
    assert cm.options() == ['Centroid', 'Pole of inaccessibility']
    assert cm.defaultValue() == 1, "CENTER_METHOD default should be 1 (pole_of_inaccessibility)"


# ===========================================================================
# T3 -- Output fields correct
# ===========================================================================

def test_output_fields_correct(qgis_app):
    """Output has _tessera_algorithm, _tessera_parent_fid, _tessera_value, _tessera_scale_factor."""
    feat = _make_100m_square(40.0)
    layer = make_layer([feat], crs_id='EPSG:32633')
    features, _, _, _ = _run_scale_by_value(
        layer, reference=2, fixed_reference=40.0)

    assert len(features) > 0
    f = features[0]
    field_names = [f.fields().field(i).name()
                   for i in range(f.fields().count())]

    assert '_tessera_algorithm' in field_names
    assert '_tessera_parent_fid' in field_names
    assert '_tessera_value' in field_names
    assert '_tessera_scale_factor' in field_names

    # Should not have fields from other algorithms
    assert '_tessera_tile_index' not in field_names
    assert '_tessera_part' not in field_names
    assert '_tessera_fraction' not in field_names

    for feat in features:
        assert feat.attribute('_tessera_algorithm') == 'scale_by_value'


# ===========================================================================
# T4 -- Proportional area scaling
# ===========================================================================

def test_proportional_area_scaling(qgis_app):
    """SCALE_METHOD=0 (proportional_area): scale_factor = value / max_value.

    Two squares: value=20 and value=40. max=40.
    Feature with value=20: scale = 20/40 = 0.5
    Feature with value=40: scale = 40/40 = 1.0
    """
    feat1 = _make_square_feature(500000, 5000000, 100, 20.0, 'sq1')
    feat2 = _make_square_feature(500200, 5000000, 100, 40.0, 'sq2')
    layer = make_layer([feat1, feat2], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, scale_method=0, reference=0, min_scale=0.01, max_scale=10.0)

    scale_factors = {}
    for f in features:
        scale_factors[f.attribute('name')] = f.attribute('_tessera_scale_factor')

    assert abs(scale_factors['sq1'] - 0.5) < 0.001, \
        f"Expected scale 0.5 for sq1, got {scale_factors['sq1']}"
    assert abs(scale_factors['sq2'] - 1.0) < 0.001, \
        f"Expected scale 1.0 for sq2, got {scale_factors['sq2']}"


# ===========================================================================
# T5 -- Proportional sqrt scaling
# ===========================================================================

def test_proportional_sqrt_scaling(qgis_app):
    """SCALE_METHOD=1 (proportional_sqrt): scale_factor = sqrt(value / max_value).

    Two squares: value=16 and value=64. max=64.
    Feature with value=16: scale = sqrt(16/64) = sqrt(0.25) = 0.5
    Feature with value=64: scale = sqrt(64/64) = 1.0
    """
    feat1 = _make_square_feature(500000, 5000000, 100, 16.0, 'sq1')
    feat2 = _make_square_feature(500200, 5000000, 100, 64.0, 'sq2')
    layer = make_layer([feat1, feat2], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, scale_method=1, reference=0, min_scale=0.01, max_scale=10.0)

    scale_factors = {}
    for f in features:
        scale_factors[f.attribute('name')] = f.attribute('_tessera_scale_factor')

    assert abs(scale_factors['sq1'] - 0.5) < 0.001, \
        f"Expected scale 0.5 for sq1, got {scale_factors['sq1']}"
    assert abs(scale_factors['sq2'] - 1.0) < 0.001, \
        f"Expected scale 1.0 for sq2, got {scale_factors['sq2']}"


# ===========================================================================
# T6 -- Proportional log scaling
# ===========================================================================

def test_proportional_log_scaling(qgis_app):
    """SCALE_METHOD=2 (proportional_log): scale = log(value+1)/log(ref+1).

    With fixed reference=99:
    Feature value=99: scale = log(100)/log(100) = 1.0
    Feature value=9:  scale = log(10)/log(100) = 0.5
    """
    feat1 = _make_square_feature(500000, 5000000, 100, 9.0, 'sq1')
    feat2 = _make_square_feature(500200, 5000000, 100, 99.0, 'sq2')
    layer = make_layer([feat1, feat2], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, scale_method=2, reference=2, fixed_reference=99.0,
        min_scale=0.01, max_scale=10.0)

    scale_factors = {}
    for f in features:
        scale_factors[f.attribute('name')] = f.attribute('_tessera_scale_factor')

    expected_sq1 = math.log(10) / math.log(100)  # = 0.5
    expected_sq2 = math.log(100) / math.log(100)  # = 1.0

    assert abs(scale_factors['sq1'] - expected_sq1) < 0.001, \
        f"Expected scale {expected_sq1:.3f} for sq1, got {scale_factors['sq1']}"
    assert abs(scale_factors['sq2'] - expected_sq2) < 0.001, \
        f"Expected scale {expected_sq2:.3f} for sq2, got {scale_factors['sq2']}"


# ===========================================================================
# T7 -- Reference methods: max_value, mean_value, fixed
# ===========================================================================

def test_reference_max_value(qgis_app):
    """REFERENCE=0 (max_value): reference is the maximum value in the dataset."""
    feat1 = _make_square_feature(500000, 5000000, 100, 25.0, 'sq1')
    feat2 = _make_square_feature(500200, 5000000, 100, 100.0, 'sq2')
    layer = make_layer([feat1, feat2], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, scale_method=0, reference=0, min_scale=0.01, max_scale=10.0)

    scale_factors = {}
    for f in features:
        scale_factors[f.attribute('name')] = f.attribute('_tessera_scale_factor')

    # max is 100, so sq1 scale = 25/100 = 0.25
    assert abs(scale_factors['sq1'] - 0.25) < 0.001
    assert abs(scale_factors['sq2'] - 1.0) < 0.001


def test_reference_mean_value(qgis_app):
    """REFERENCE=1 (mean_value): reference is the mean of all values."""
    feat1 = _make_square_feature(500000, 5000000, 100, 20.0, 'sq1')
    feat2 = _make_square_feature(500200, 5000000, 100, 40.0, 'sq2')
    layer = make_layer([feat1, feat2], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, scale_method=0, reference=1, min_scale=0.01, max_scale=10.0)

    scale_factors = {}
    for f in features:
        scale_factors[f.attribute('name')] = f.attribute('_tessera_scale_factor')

    # mean = (20+40)/2 = 30
    # sq1: 20/30 = 0.6667
    # sq2: 40/30 = 1.3333
    assert abs(scale_factors['sq1'] - 20.0 / 30.0) < 0.001
    assert abs(scale_factors['sq2'] - 40.0 / 30.0) < 0.001


def test_reference_fixed(qgis_app):
    """REFERENCE=2 (fixed): reference is user-specified FIXED_REFERENCE."""
    feat = _make_square_feature(500000, 5000000, 100, 50.0, 'sq1')
    layer = make_layer([feat], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, scale_method=0, reference=2, fixed_reference=200.0,
        min_scale=0.01, max_scale=10.0)

    assert len(features) == 1
    # scale = 50/200 = 0.25
    assert abs(features[0].attribute('_tessera_scale_factor') - 0.25) < 0.001


# ===========================================================================
# T8 -- MIN_SCALE and MAX_SCALE clamping
# ===========================================================================

def test_min_scale_clamping(qgis_app):
    """Scale factors below MIN_SCALE are clamped upward."""
    # value=1 with max=100 gives raw ratio 0.01 => below min_scale=0.1
    feat1 = _make_square_feature(500000, 5000000, 100, 1.0, 'small')
    feat2 = _make_square_feature(500200, 5000000, 100, 100.0, 'big')
    layer = make_layer([feat1, feat2], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, scale_method=0, reference=0, min_scale=0.1, max_scale=3.0)

    scale_factors = {}
    for f in features:
        scale_factors[f.attribute('name')] = f.attribute('_tessera_scale_factor')

    # raw ratio for 'small' = 1/100 = 0.01, clamped to min_scale=0.1
    assert abs(scale_factors['small'] - 0.1) < 0.001, \
        f"Expected clamped scale 0.1, got {scale_factors['small']}"


def test_max_scale_clamping(qgis_app):
    """Scale factors above MAX_SCALE are clamped downward."""
    # Use mean_value reference: mean=10, value=50 gives ratio 5.0 => above max_scale=3.0
    feat1 = _make_square_feature(500000, 5000000, 100, 50.0, 'big')
    feat2 = _make_square_feature(500200, 5000000, 100, 10.0, 'small')
    # Add a third feature to keep mean low
    feat3 = _make_square_feature(500400, 5000000, 100, 10.0, 'small2')
    # But with fixed reference, it's cleaner:
    layer = make_layer([feat1], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, scale_method=0, reference=2, fixed_reference=10.0,
        min_scale=0.1, max_scale=3.0)

    assert len(features) == 1
    # raw ratio = 50/10 = 5.0, clamped to max_scale=3.0
    assert abs(features[0].attribute('_tessera_scale_factor') - 3.0) < 0.001, \
        f"Expected clamped scale 3.0, got {features[0].attribute('_tessera_scale_factor')}"


# ===========================================================================
# T9 -- Null/zero values skipped with warning
# ===========================================================================

def test_null_value_skipped_with_warning(qgis_app):
    """Feature with NULL value is skipped, warning issued."""
    fields = make_fields()
    ring = [QgsPointXY(500000, 5000000), QgsPointXY(500100, 5000000),
            QgsPointXY(500100, 5000100), QgsPointXY(500000, 5000100),
            QgsPointXY(500000, 5000000)]
    geom = QgsGeometry.fromPolygonXY([ring])
    feat_null = QgsFeature(fields)
    feat_null.setGeometry(geom)
    feat_null.setAttribute('name', 'null_val')
    # Leave 'value' as NULL

    feat_valid = _make_square_feature(500200, 5000000, 100, 50.0, 'valid')
    layer = make_layer([feat_null, feat_valid], crs_id='EPSG:32633')

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

        alg = ScaleByValueAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'VALUE_FIELD': 'value',
            'SCALE_METHOD': 0,
            'REFERENCE': 2,
            'FIXED_REFERENCE': 50.0,
            'MAX_SCALE': 3.0,
            'MIN_SCALE': 0.1,
            'CENTER_METHOD': 1,
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

        # Only the valid feature should produce output
        assert len(features) == 1, \
            f"Expected 1 feature (NULL skipped), got {len(features)}"
        assert features[0].attribute('name') == 'valid'

        # Warning should have been issued for NULL
        null_warnings = [w for w in warnings if 'NULL' in w]
        assert len(null_warnings) > 0, "Should issue a warning for NULL value"
    finally:
        project.removeMapLayer(layer.id())


def test_zero_value_skipped_with_warning(qgis_app):
    """Feature with zero value is skipped, warning issued."""
    feat_zero = _make_square_feature(500000, 5000000, 100, 0.0, 'zero')
    feat_valid = _make_square_feature(500200, 5000000, 100, 50.0, 'valid')
    layer = make_layer([feat_zero, feat_valid], crs_id='EPSG:32633')

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

        alg = ScaleByValueAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'VALUE_FIELD': 'value',
            'SCALE_METHOD': 0,
            'REFERENCE': 2,
            'FIXED_REFERENCE': 50.0,
            'MAX_SCALE': 3.0,
            'MIN_SCALE': 0.1,
            'CENTER_METHOD': 1,
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

        # Only the valid feature should produce output
        assert len(features) == 1, \
            f"Expected 1 feature (zero skipped), got {len(features)}"
        assert features[0].attribute('name') == 'valid'

        # Warning should have been issued for zero value
        zero_warnings = [w for w in warnings if 'zero' in w.lower()]
        assert len(zero_warnings) > 0, "Should issue a warning for zero value"
    finally:
        project.removeMapLayer(layer.id())


# ===========================================================================
# T10 -- Center preserved (centroid of scaled ~ centroid of original)
# ===========================================================================

def test_center_preserved(qgis_app):
    """Center of scaled polygon is approximately the same as the original.

    We use a square at a known location and verify the centroid doesn't move
    significantly after scaling. Using centroid center method for simplicity.
    """
    feat = _make_square_feature(500000, 5000000, 100, 50.0, 'sq')
    layer = make_layer([feat], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, scale_method=0, reference=2, fixed_reference=50.0,
        min_scale=0.01, max_scale=10.0, center_method=0)

    assert len(features) == 1

    orig_geom = feat.geometry()
    out_geom = features[0].geometry()

    orig_centroid = orig_geom.centroid().asPoint()
    out_centroid = out_geom.centroid().asPoint()

    # For scale_factor=1.0 (value==reference), centroid should be essentially identical
    dist = math.hypot(orig_centroid.x() - out_centroid.x(),
                      orig_centroid.y() - out_centroid.y())
    assert dist < 1.0, \
        f"Centroid should not move significantly, distance={dist:.4f}m"


# ===========================================================================
# T11 -- Area validation (scaled area ~ original_area * scale_factor)
# ===========================================================================

def test_area_scales_by_factor(qgis_app):
    """Scaled area should equal original_area * scale_factor.

    Using a projected CRS (EPSG:32633) to avoid distortion.
    Two features: value=25 and value=100 with max reference.
    Feature value=25: scale = 0.25, area should be 0.25 * original
    Feature value=100: scale = 1.0, area should be unchanged
    """
    size = 100  # 100m square => area = 10000 m^2
    feat1 = _make_square_feature(500000, 5000000, size, 25.0, 'quarter')
    feat2 = _make_square_feature(500200, 5000000, size, 100.0, 'full')
    layer = make_layer([feat1, feat2], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, scale_method=0, reference=0, min_scale=0.01, max_scale=10.0)

    original_area = size * size  # 10000 m^2

    for f in features:
        scale_factor = f.attribute('_tessera_scale_factor')
        expected_area = original_area * scale_factor
        actual_area = f.geometry().area()

        # Allow 5% tolerance due to CRS round-trip
        rel_error = abs(actual_area - expected_area) / expected_area
        assert rel_error < 0.05, \
            f"Feature '{f.attribute('name')}': expected area " \
            f"~{expected_area:.1f}, got {actual_area:.1f} " \
            f"(scale={scale_factor}, error={rel_error:.2%})"


# ===========================================================================
# T12 -- Parent attributes carried forward
# ===========================================================================

def test_parent_attributes_carried(qgis_app):
    """Parent 'name' and 'value' attributes are carried to output features."""
    feat = _make_100m_square(40.0, 'my_square')
    layer = make_layer([feat], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, reference=2, fixed_reference=40.0)

    assert len(features) == 1
    assert features[0].attribute('name') == 'my_square'
    assert features[0].attribute('value') == 40.0


# ===========================================================================
# T13 -- Output geometry is MultiPolygon
# ===========================================================================

def test_output_geometry_is_multipolygon(qgis_app):
    """Output geometry is always MultiPolygon (promoted from single-part)."""
    feat = _make_100m_square(40.0)
    layer = make_layer([feat], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, reference=2, fixed_reference=40.0)

    assert len(features) == 1
    geom = features[0].geometry()
    assert not geom.isEmpty(), "Output geometry must not be empty"
    assert geom.isMultipart(), "Output geometry must be MultiPolygon"
    assert geom.type() == QgsWkbTypes.PolygonGeometry


# ===========================================================================
# T14 -- _tessera_value stores raw value
# ===========================================================================

def test_tessera_value_stores_raw_value(qgis_app):
    """_tessera_value attribute stores the original feature value."""
    feat = _make_100m_square(42.5, 'sq')
    layer = make_layer([feat], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, reference=2, fixed_reference=42.5)

    assert len(features) == 1
    assert features[0].attribute('_tessera_value') == 42.5


# ===========================================================================
# T15 -- Multiple features with different values
# ===========================================================================

def test_multiple_features(qgis_app):
    """Four features with varying values produce four output features."""
    feats = [
        _make_square_feature(500000 + i * 200, 5000000, 100, (i + 1) * 10.0,
                             f'sq{i}')
        for i in range(4)
    ]
    layer = make_layer(feats, crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, scale_method=0, reference=0, min_scale=0.01, max_scale=10.0)

    assert len(features) == 4, f"Expected 4 output features, got {len(features)}"

    # All should have different scale factors (values are 10, 20, 30, 40)
    factors = sorted(f.attribute('_tessera_scale_factor') for f in features)
    for i in range(len(factors) - 1):
        assert factors[i] < factors[i + 1], \
            f"Scale factors should be strictly increasing, got {factors}"


# ===========================================================================
# T16 -- Negative value rejected with error
# ===========================================================================

def test_negative_value_rejected(qgis_app):
    """Feature with negative value is rejected (reportError called)."""
    feat_neg = _make_square_feature(500000, 5000000, 100, -5.0, 'neg')
    feat_pos = _make_square_feature(500200, 5000000, 100, 50.0, 'pos')
    layer = make_layer([feat_neg, feat_pos], crs_id='EPSG:32633')

    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        errors = []
        orig_error = feedback.reportError

        def capture_error(msg, fatalError=False):
            errors.append(msg)
            orig_error(msg, fatalError)

        feedback.reportError = capture_error

        alg = ScaleByValueAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'VALUE_FIELD': 'value',
            'SCALE_METHOD': 0,
            'REFERENCE': 2,
            'FIXED_REFERENCE': 50.0,
            'MAX_SCALE': 3.0,
            'MIN_SCALE': 0.1,
            'CENTER_METHOD': 1,
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

        # Only the positive feature should produce output
        assert len(features) == 1, \
            f"Expected 1 feature (negative rejected), got {len(features)}"
        assert features[0].attribute('name') == 'pos'

        # Error should have been reported for negative value
        neg_errors = [e for e in errors if 'negative' in e.lower()]
        assert len(neg_errors) > 0, "Should report error for negative value"
    finally:
        project.removeMapLayer(layer.id())


# ===========================================================================
# T17 -- Scale factor 1.0 produces unchanged geometry
# ===========================================================================

def test_scale_factor_one_preserves_geometry(qgis_app):
    """When value equals reference, scale_factor=1.0 and geometry is unchanged."""
    feat = _make_square_feature(500000, 5000000, 100, 50.0, 'sq')
    layer = make_layer([feat], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, scale_method=0, reference=2, fixed_reference=50.0,
        min_scale=0.01, max_scale=10.0)

    assert len(features) == 1
    assert abs(features[0].attribute('_tessera_scale_factor') - 1.0) < 0.001

    orig_area = feat.geometry().area()
    out_area = features[0].geometry().area()
    rel_error = abs(out_area - orig_area) / orig_area
    assert rel_error < 0.01, \
        f"Area should be unchanged, got rel_error={rel_error:.4f}"


# ===========================================================================
# T18 -- Centroid center method works
# ===========================================================================

def test_centroid_center_method(qgis_app):
    """CENTER_METHOD=0 (centroid) produces valid scaled output."""
    feat = _make_square_feature(500000, 5000000, 100, 25.0, 'sq')
    layer = make_layer([feat], crs_id='EPSG:32633')

    features, _, _, _ = _run_scale_by_value(
        layer, scale_method=0, reference=2, fixed_reference=100.0,
        min_scale=0.01, max_scale=10.0, center_method=0)

    assert len(features) == 1
    geom = features[0].geometry()
    assert not geom.isEmpty()
    assert geom.area() > 0


# ===========================================================================
# T19 -- Natural Earth integration
# ===========================================================================

def test_natural_earth_integration(qgis_app, natural_earth_path):
    """Scale by Value produces output for Natural Earth countries, completes < 30s."""
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
    features, results, feedback, _ = _run_scale_by_value(
        ne_layer, value_field=numeric_field, scale_method=0, reference=0,
        min_scale=0.1, max_scale=3.0)
    elapsed = time.time() - start

    assert len(features) > 0, "Should produce output for Natural Earth"
    assert elapsed < 30, f"Should complete in < 30s, took {elapsed:.1f}s"

    parent_fids = set(f.attribute('_tessera_parent_fid') for f in features)
    assert len(parent_fids) > 1, \
        f"Should have output from multiple countries, got {len(parent_fids)} parent fids"
