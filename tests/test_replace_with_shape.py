"""Tests for Replace with Shape algorithm (spec section 5.8).

Replace with Shape replaces each polygon with a circle/square/hexagon of
proportional area based on a numeric attribute. Output fields include
_tessera_algorithm, _tessera_parent_fid, _tessera_value, and _tessera_scale_factor.
"""
import gc
import math

import pytest
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType

from tessera.algorithms.replace_with_shape import ReplaceWithShapeAlgorithm

from .helpers import make_layer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_fields():
    """Test-specific fields: name (String), pop (Double) instead of value."""
    from qgis.core import QgsField, QgsFields
    from PyQt5.QtCore import QMetaType
    fields = QgsFields()
    fields.append(QgsField('name', QMetaType.Type.QString))
    fields.append(QgsField('pop', QMetaType.Type.Double))
    return fields


def make_feature(geometry, name, pop, fields):
    """Test-specific feature builder that uses 'pop' field instead of 'value'."""
    from qgis.core import QgsFeature
    feat = QgsFeature(fields)
    feat.setGeometry(geometry)
    feat.setAttribute('name', name)
    feat.setAttribute('pop', pop)
    return feat


def _run_replace_with_shape(layer, value_field='pop', shape=0,
                             scale_method=0, reference=0,
                             extra_params=None):
    """Run ReplaceWithShapeAlgorithm and return output features.

    Returns (features_list, result_dict, feedback, output_layer).
    """
    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        alg = ReplaceWithShapeAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'VALUE_FIELD': value_field,
            'SHAPE': shape,
            'SCALE_METHOD': scale_method,
            'REFERENCE': reference,
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


def _make_square_feature(x, y, size, name, pop, fields):
    """Create a square feature at (x, y) with given side length."""
    ring = [
        QgsPointXY(x, y),
        QgsPointXY(x + size, y),
        QgsPointXY(x + size, y + size),
        QgsPointXY(x, y + size),
        QgsPointXY(x, y),
    ]
    geom = QgsGeometry.fromPolygonXY([ring])
    return make_feature(geom, name, pop, fields)


def _count_vertices(geom):
    """Count vertices in a geometry (excluding closing vertex of each ring)."""
    count = 0
    if geom.isMultipart():
        for part in geom.asMultiPolygon():
            for ring in part:
                # ring includes closing vertex (same as first)
                count += len(ring) - 1
    else:
        for ring in geom.asPolygon():
            count += len(ring) - 1
    return count


def _get_vertices(geom):
    """Get list of (x, y) tuples for all vertices, excluding closing vertex."""
    vertices = []
    if geom.isMultipart():
        for part in geom.asMultiPolygon():
            for ring in part:
                for pt in ring[:-1]:
                    vertices.append((pt.x(), pt.y()))
    else:
        for ring in geom.asPolygon():
            for pt in ring[:-1]:
                vertices.append((pt.x(), pt.y()))
    return vertices


# ---------------------------------------------------------------------------
# Test 1: Import and metadata
# ---------------------------------------------------------------------------

class TestReplaceWithShapeImport:
    """Test import and metadata."""

    def test_importable(self):
        """ReplaceWithShapeAlgorithm imports without error."""
        assert ReplaceWithShapeAlgorithm is not None

    def test_metadata(self):
        """name='replace_with_shape', displayName='Replace with Shape',
        group='Shape', groupId='shape'."""
        alg = ReplaceWithShapeAlgorithm()
        assert alg.name() == 'replace_with_shape'
        assert alg.displayName() == 'Replace with Shape'
        assert alg.group() == 'Shape'
        assert alg.groupId() == 'shape'

    def test_create_instance(self):
        """createInstance returns a new ReplaceWithShapeAlgorithm."""
        alg = ReplaceWithShapeAlgorithm()
        instance = alg.createInstance()
        assert isinstance(instance, ReplaceWithShapeAlgorithm)
        assert instance is not alg


# ---------------------------------------------------------------------------
# Test 2: Parameters defined correctly
# ---------------------------------------------------------------------------

class TestReplaceWithShapeParameters:
    """Test algorithm parameters after initAlgorithm."""

    def test_has_all_parameters(self, qgis_app):
        """After initAlgorithm(), has all required parameters."""
        alg = ReplaceWithShapeAlgorithm()
        alg.initAlgorithm()

        param_names = [p.name() for p in alg.parameterDefinitions()]
        assert 'INPUT' in param_names
        assert 'VALUE_FIELD' in param_names
        assert 'SHAPE' in param_names
        assert 'SCALE_METHOD' in param_names
        assert 'REFERENCE' in param_names
        assert 'FIXED_REFERENCE' in param_names
        assert 'SIZE_REFERENCE' in param_names
        assert 'FIXED_RADIUS' in param_names
        assert 'CENTER_METHOD' in param_names
        assert 'CIRCLE_SEGMENTS' in param_names
        assert 'OUTPUT' in param_names

    def test_shape_options(self, qgis_app):
        """SHAPE has options: circle, square, hexagon with default 0."""
        alg = ReplaceWithShapeAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('SHAPE')
        assert param.options() == ['Circle', 'Square', 'Hexagon']
        assert param.defaultValue() == 0

    def test_scale_method_options(self, qgis_app):
        """SCALE_METHOD has correct options with default 0."""
        alg = ReplaceWithShapeAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('SCALE_METHOD')
        assert param.options() == [
            'Proportional area', 'Square root', 'Logarithmic'
        ]
        assert param.defaultValue() == 0

    def test_reference_options(self, qgis_app):
        """REFERENCE has options: max_value, mean_value, fixed with default 0."""
        alg = ReplaceWithShapeAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('REFERENCE')
        assert param.options() == ['Maximum value', 'Mean value', 'Fixed']
        assert param.defaultValue() == 0

    def test_center_method_default(self, qgis_app):
        """CENTER_METHOD default is 1 (pole_of_inaccessibility)."""
        alg = ReplaceWithShapeAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('CENTER_METHOD')
        assert param.options() == ['Centroid', 'Pole of inaccessibility']
        assert param.defaultValue() == 1

    def test_circle_segments_range(self, qgis_app):
        """CIRCLE_SEGMENTS has default 64, min 16, max 256."""
        alg = ReplaceWithShapeAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('CIRCLE_SEGMENTS')
        assert param.defaultValue() == 64
        assert param.minimum() == 16
        assert param.maximum() == 256

    def test_fixed_reference_is_advanced(self, qgis_app):
        """FIXED_REFERENCE is flagged as Advanced."""
        from qgis.core import QgsProcessingParameterDefinition
        alg = ReplaceWithShapeAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('FIXED_REFERENCE')
        assert param.flags() & QgsProcessingParameterDefinition.FlagAdvanced

    def test_fixed_radius_is_advanced(self, qgis_app):
        """FIXED_RADIUS is flagged as Advanced."""
        from qgis.core import QgsProcessingParameterDefinition
        alg = ReplaceWithShapeAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('FIXED_RADIUS')
        assert param.flags() & QgsProcessingParameterDefinition.FlagAdvanced


# ---------------------------------------------------------------------------
# Test 3: Output fields correct
# ---------------------------------------------------------------------------

class TestReplaceWithShapeOutputFields:
    """Test output field schema."""

    def test_output_has_tessera_fields(self, qgis_app):
        """Output has _tessera_algorithm, _tessera_parent_fid, _tessera_value, _tessera_scale_factor."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'sq1', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')
        features, _, _, _ = _run_replace_with_shape(layer)

        assert len(features) > 0
        f = features[0]
        field_names = [f.fields().field(i).name()
                       for i in range(f.fields().count())]
        assert '_tessera_algorithm' in field_names
        assert '_tessera_parent_fid' in field_names
        assert '_tessera_value' in field_names
        assert '_tessera_scale_factor' in field_names

    def test_tessera_algorithm_is_replace_with_shape(self, qgis_app):
        """_tessera_algorithm is 'replace_with_shape'."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'sq1', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')
        features, _, _, _ = _run_replace_with_shape(layer)

        assert len(features) > 0
        for f in features:
            assert f.attribute('_tessera_algorithm') == 'replace_with_shape'

    def test_parent_attributes_carried(self, qgis_app):
        """Parent 'name' and 'pop' attributes are carried to output."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'city_a', 50000.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')
        features, _, _, _ = _run_replace_with_shape(layer)

        assert len(features) > 0
        for f in features:
            assert f.attribute('name') == 'city_a'
            assert f.attribute('pop') == 50000.0


# ---------------------------------------------------------------------------
# Test 4: Circle shape
# ---------------------------------------------------------------------------

class TestCircleShape:
    """Test circle output shape."""

    def test_circle_vertex_count(self, qgis_app):
        """Circle shape (SHAPE=0) produces approximately CIRCLE_SEGMENTS vertices."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'sq1', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')
        features, _, _, _ = _run_replace_with_shape(
            layer, shape=0, extra_params={'CIRCLE_SEGMENTS': 64})

        assert len(features) == 1
        geom = features[0].geometry()
        n_verts = _count_vertices(geom)
        assert n_verts == 64, f"Expected 64 vertices for circle, got {n_verts}"

    def test_circle_is_roughly_circular(self, qgis_app):
        """Circle vertices are roughly equidistant from center.

        Note: CRS round-trip (source -> working -> source) can introduce
        small distortions, so we use a generous 15% tolerance.
        """
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'sq1', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')
        features, _, _, _ = _run_replace_with_shape(
            layer, shape=0, extra_params={'CIRCLE_SEGMENTS': 32})

        assert len(features) == 1
        geom = features[0].geometry()
        vertices = _get_vertices(geom)

        # Compute center as average of all vertices
        cx = sum(v[0] for v in vertices) / len(vertices)
        cy = sum(v[1] for v in vertices) / len(vertices)

        # All vertices should be roughly equidistant from center
        distances = [math.hypot(v[0] - cx, v[1] - cy) for v in vertices]
        mean_dist = sum(distances) / len(distances)

        for d in distances:
            relative_diff = abs(d - mean_dist) / mean_dist
            assert relative_diff < 0.15, (
                f"Vertex distance {d:.1f} differs from mean {mean_dist:.1f} "
                f"by {relative_diff*100:.1f}%"
            )


# ---------------------------------------------------------------------------
# Test 5: Square shape
# ---------------------------------------------------------------------------

class TestSquareShape:
    """Test square output shape."""

    def test_square_vertex_count(self, qgis_app):
        """Square shape (SHAPE=1) has 4 vertices."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'sq1', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')
        features, _, _, _ = _run_replace_with_shape(layer, shape=1)

        assert len(features) == 1
        geom = features[0].geometry()
        n_verts = _count_vertices(geom)
        assert n_verts == 4, f"Expected 4 vertices for square, got {n_verts}"

    def test_square_has_roughly_equal_sides(self, qgis_app):
        """Square shape has 4 roughly equal-length edges.

        We check edge lengths rather than axis-alignment, since CRS
        round-trip can distort the exact orientation.
        """
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'sq1', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')
        features, _, _, _ = _run_replace_with_shape(
            layer, shape=1,
            extra_params={
                'SIZE_REFERENCE': 1,
                'FIXED_RADIUS': 5000.0,
                'CENTER_METHOD': 0,
            })

        assert len(features) == 1
        geom = features[0].geometry()
        vertices = _get_vertices(geom)
        assert len(vertices) == 4

        # Check that all 4 edges have roughly equal length
        edge_lengths = []
        for i in range(4):
            v1 = vertices[i]
            v2 = vertices[(i + 1) % 4]
            length = math.hypot(v1[0] - v2[0], v1[1] - v2[1])
            edge_lengths.append(length)

        mean_length = sum(edge_lengths) / len(edge_lengths)
        for length in edge_lengths:
            relative_diff = abs(length - mean_length) / mean_length
            assert relative_diff < 0.15, (
                f"Edge length {length:.1f} differs from mean {mean_length:.1f} "
                f"by {relative_diff*100:.1f}%"
            )


# ---------------------------------------------------------------------------
# Test 6: Hexagon shape
# ---------------------------------------------------------------------------

class TestHexagonShape:
    """Test hexagon output shape."""

    def test_hexagon_vertex_count(self, qgis_app):
        """Hexagon shape (SHAPE=2) has 6 vertices."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'sq1', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')
        features, _, _, _ = _run_replace_with_shape(layer, shape=2)

        assert len(features) == 1
        geom = features[0].geometry()
        n_verts = _count_vertices(geom)
        assert n_verts == 6, f"Expected 6 vertices for hexagon, got {n_verts}"


# ---------------------------------------------------------------------------
# Test 7: Radius proportional to scale factor
# ---------------------------------------------------------------------------

class TestRadiusProportionality:
    """Test that radius scales correctly with value."""

    def test_larger_value_gives_larger_shape(self, qgis_app):
        """Feature with larger value produces larger shape."""
        fields = make_fields()
        feat_small = _make_square_feature(500000, 5500000, 10000, 'small', 25.0, fields)
        feat_large = _make_square_feature(520000, 5500000, 10000, 'large', 100.0, fields)
        layer = make_layer([feat_small, feat_large], crs_id='EPSG:32633')

        features, _, _, _ = _run_replace_with_shape(
            layer, shape=0, reference=0,
            extra_params={'CIRCLE_SEGMENTS': 32})

        assert len(features) == 2

        areas = {}
        for f in features:
            areas[f.attribute('name')] = f.geometry().area()

        assert areas['large'] > areas['small'], (
            f"Larger value should produce larger shape: "
            f"large={areas['large']:.1f}, small={areas['small']:.1f}"
        )

    def test_scale_factor_stored_correctly(self, qgis_app):
        """_tessera_scale_factor is stored and max-value feature has scale=1.0."""
        fields = make_fields()
        feat1 = _make_square_feature(500000, 5500000, 10000, 'max', 100.0, fields)
        feat2 = _make_square_feature(520000, 5500000, 10000, 'half', 50.0, fields)
        layer = make_layer([feat1, feat2], crs_id='EPSG:32633')

        features, _, _, _ = _run_replace_with_shape(
            layer, reference=0)  # max_value

        scales = {}
        for f in features:
            scales[f.attribute('name')] = f.attribute('_tessera_scale_factor')

        # With proportional_area and max_value reference:
        # max: 100/100 = 1.0, half: 50/100 = 0.5
        assert abs(scales['max'] - 1.0) < 0.001, \
            f"Max value scale should be 1.0, got {scales['max']}"
        assert abs(scales['half'] - 0.5) < 0.001, \
            f"Half value scale should be 0.5, got {scales['half']}"

    def test_tessera_value_stored_correctly(self, qgis_app):
        """_tessera_value stores the raw attribute value."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'sq1', 42.5, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')
        features, _, _, _ = _run_replace_with_shape(layer)

        assert len(features) == 1
        assert features[0].attribute('_tessera_value') == 42.5


# ---------------------------------------------------------------------------
# Test 8: Auto reference radius based on median area
# ---------------------------------------------------------------------------

class TestAutoReferenceRadius:
    """Test auto reference radius computation."""

    def test_auto_reference_produces_reasonable_shape(self, qgis_app):
        """With SIZE_REFERENCE=auto, the output shape area is in a reasonable
        range relative to the input polygon area."""
        fields = make_fields()
        size = 10000  # 10km side = 100 km^2 area
        feat = _make_square_feature(500000, 5500000, size, 'sq1', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')

        features, _, _, _ = _run_replace_with_shape(
            layer, shape=0, reference=0,
            extra_params={'SIZE_REFERENCE': 0})

        assert len(features) == 1
        input_area = size * size  # 1e8 m^2
        output_area = features[0].geometry().area()

        # Auto radius = sqrt(median_area / pi), so the reference circle area
        # = pi * r^2 = pi * (median_area / pi) = median_area
        # With scale=1.0 (max_value, single feature), output area should be
        # close to input area (since radius = ref_radius * sqrt(1.0) = ref_radius)
        ratio = output_area / input_area
        assert 0.5 < ratio < 2.0, (
            f"Auto reference: output/input area ratio = {ratio:.3f}, "
            f"expected close to 1.0"
        )


# ---------------------------------------------------------------------------
# Test 9: Fixed radius option
# ---------------------------------------------------------------------------

class TestFixedRadius:
    """Test fixed radius option."""

    def test_fixed_radius_produces_expected_area(self, qgis_app):
        """With SIZE_REFERENCE=fixed_radius and known radius, output area matches."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'sq1', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')

        fixed_r = 5000.0  # 5 km radius
        features, _, _, _ = _run_replace_with_shape(
            layer, shape=0, reference=0,
            extra_params={
                'SIZE_REFERENCE': 1,
                'FIXED_RADIUS': fixed_r,
                'CIRCLE_SEGMENTS': 256,
            })

        assert len(features) == 1
        output_area = features[0].geometry().area()

        # With scale=1.0, radius = fixed_r * sqrt(1.0) = fixed_r
        # Circle area = pi * r^2
        expected_area = math.pi * fixed_r * fixed_r
        relative_err = abs(output_area - expected_area) / expected_area
        assert relative_err < 0.01, (
            f"Fixed radius circle area: got {output_area:.1f}, "
            f"expected {expected_area:.1f}, error {relative_err*100:.2f}%"
        )


# ---------------------------------------------------------------------------
# Test 10: Null/zero values skipped
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test edge cases: null, zero, negative values."""

    def test_null_value_skipped(self, qgis_app):
        """Feature with NULL pop is skipped with warning."""
        fields = make_fields()
        ring = [
            QgsPointXY(500000, 5500000),
            QgsPointXY(510000, 5500000),
            QgsPointXY(510000, 5510000),
            QgsPointXY(500000, 5510000),
            QgsPointXY(500000, 5500000),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])
        feat = QgsFeature(fields)
        feat.setGeometry(geom)
        feat.setAttribute('name', 'null_pop')
        # Leave 'pop' as NULL

        layer = make_layer([feat], crs_id='EPSG:32633')

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

            alg = ReplaceWithShapeAlgorithm()
            alg.initAlgorithm()

            parameters = {
                'INPUT': layer.id(),
                'VALUE_FIELD': 'pop',
                'SHAPE': 0,
                'SCALE_METHOD': 0,
                'REFERENCE': 0,
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

            assert len(features) == 0, \
                f"Expected 0 features for NULL value, got {len(features)}"
            assert len(warnings) > 0, "Should issue a warning for NULL value"
        finally:
            project.removeMapLayer(layer.id())

    def test_zero_value_skipped(self, qgis_app):
        """Feature with zero pop is skipped with warning."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'zero', 0.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')

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

            alg = ReplaceWithShapeAlgorithm()
            alg.initAlgorithm()

            parameters = {
                'INPUT': layer.id(),
                'VALUE_FIELD': 'pop',
                'SHAPE': 0,
                'SCALE_METHOD': 0,
                'REFERENCE': 0,
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

            assert len(features) == 0, \
                f"Expected 0 features for zero value, got {len(features)}"
            assert len(warnings) > 0, "Should issue a warning for zero value"
        finally:
            project.removeMapLayer(layer.id())

    def test_negative_value_rejected(self, qgis_app):
        """Feature with negative pop is skipped with error."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'neg', -10.0, fields)
        # Add a valid feature so the algorithm has something to work with
        feat_valid = _make_square_feature(520000, 5500000, 10000, 'valid', 50.0, fields)
        layer = make_layer([feat, feat_valid], crs_id='EPSG:32633')

        features, _, _, _ = _run_replace_with_shape(layer)

        # Only valid feature should produce output
        assert len(features) == 1, \
            f"Expected 1 feature (negative skipped), got {len(features)}"
        assert features[0].attribute('name') == 'valid'


# ---------------------------------------------------------------------------
# Test 11: Center at pole_of_inaccessibility
# ---------------------------------------------------------------------------

class TestCenterMethod:
    """Test center computation methods."""

    def test_pole_of_inaccessibility_center(self, qgis_app):
        """With CENTER_METHOD=1 (pole_of_inaccessibility), shape center is
        inside the original polygon."""
        fields = make_fields()
        # U-shaped polygon in projected CRS (EPSG:32633)
        ring = [
            QgsPointXY(500000, 5500000),
            QgsPointXY(540000, 5500000),
            QgsPointXY(540000, 5510000),
            QgsPointXY(510000, 5510000),
            QgsPointXY(510000, 5530000),
            QgsPointXY(540000, 5530000),
            QgsPointXY(540000, 5540000),
            QgsPointXY(500000, 5540000),
            QgsPointXY(500000, 5500000),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])
        feat = make_feature(geom, 'U-shape', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')

        features, _, _, _ = _run_replace_with_shape(
            layer, shape=0,
            extra_params={
                'CENTER_METHOD': 1,
                'SIZE_REFERENCE': 1,
                'FIXED_RADIUS': 3000.0,
                'CIRCLE_SEGMENTS': 32,
            })

        assert len(features) == 1
        out_geom = features[0].geometry()
        centroid = out_geom.centroid().asPoint()

        # The pole of inaccessibility for U-shape should be in the left arm,
        # not the centroid (which falls in the gap).
        # Verify the output shape center is inside the original polygon.
        center_geom = QgsGeometry.fromPointXY(
            QgsPointXY(centroid.x(), centroid.y()))
        assert geom.contains(center_geom), (
            f"Shape center ({centroid.x():.0f}, {centroid.y():.0f}) "
            f"should be inside the original U-shaped polygon"
        )

    def test_centroid_center(self, qgis_app):
        """With CENTER_METHOD=0 (centroid), shape center is at the polygon centroid."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'sq1', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')

        features, _, _, _ = _run_replace_with_shape(
            layer, shape=0,
            extra_params={
                'CENTER_METHOD': 0,
                'SIZE_REFERENCE': 1,
                'FIXED_RADIUS': 3000.0,
                'CIRCLE_SEGMENTS': 32,
            })

        assert len(features) == 1
        out_geom = features[0].geometry()
        out_centroid = out_geom.centroid().asPoint()

        # For a square, centroid = (505000, 5505000)
        expected_cx = 505000.0
        expected_cy = 5505000.0
        assert abs(out_centroid.x() - expected_cx) < 100, \
            f"Expected center x~{expected_cx}, got {out_centroid.x():.0f}"
        assert abs(out_centroid.y() - expected_cy) < 100, \
            f"Expected center y~{expected_cy}, got {out_centroid.y():.0f}"


# ---------------------------------------------------------------------------
# Test 12: Multiple features with different values
# ---------------------------------------------------------------------------

class TestMultipleFeatures:
    """Test processing multiple features."""

    def test_multiple_features_produce_correct_count(self, qgis_app):
        """Three input features produce three output features."""
        fields = make_fields()
        feat1 = _make_square_feature(500000, 5500000, 10000, 'a', 100.0, fields)
        feat2 = _make_square_feature(520000, 5500000, 10000, 'b', 50.0, fields)
        feat3 = _make_square_feature(540000, 5500000, 10000, 'c', 25.0, fields)
        layer = make_layer([feat1, feat2, feat3], crs_id='EPSG:32633')

        features, _, _, _ = _run_replace_with_shape(layer, reference=0)

        assert len(features) == 3, \
            f"Expected 3 features, got {len(features)}"

    def test_scale_methods(self, qgis_app):
        """Different scale methods produce different scale factors."""
        fields = make_fields()
        feat1 = _make_square_feature(500000, 5500000, 10000, 'a', 100.0, fields)
        feat2 = _make_square_feature(520000, 5500000, 10000, 'b', 25.0, fields)
        layer_area = make_layer([feat1, feat2], crs_id='EPSG:32633')
        layer_sqrt = make_layer([feat1, feat2], crs_id='EPSG:32633')
        layer_log = make_layer([feat1, feat2], crs_id='EPSG:32633')

        # proportional_area: scale = 25/100 = 0.25
        features_area, _, _, _ = _run_replace_with_shape(
            layer_area, scale_method=0, reference=0)

        # proportional_sqrt: scale = sqrt(25/100) = 0.5
        features_sqrt, _, _, _ = _run_replace_with_shape(
            layer_sqrt, scale_method=1, reference=0)

        # proportional_log: scale = log(26)/log(101)
        features_log, _, _, _ = _run_replace_with_shape(
            layer_log, scale_method=2, reference=0)

        def get_scale(features, name):
            for f in features:
                if f.attribute('name') == name:
                    return f.attribute('_tessera_scale_factor')
            return None

        scale_area = get_scale(features_area, 'b')
        scale_sqrt = get_scale(features_sqrt, 'b')
        scale_log = get_scale(features_log, 'b')

        assert abs(scale_area - 0.25) < 0.01, \
            f"proportional_area scale: expected 0.25, got {scale_area}"
        assert abs(scale_sqrt - 0.5) < 0.01, \
            f"proportional_sqrt scale: expected 0.5, got {scale_sqrt}"
        # log(26)/log(101) ~= 0.706
        expected_log = math.log(26) / math.log(101)
        assert abs(scale_log - expected_log) < 0.01, \
            f"proportional_log scale: expected {expected_log:.3f}, got {scale_log}"


# ---------------------------------------------------------------------------
# Test 13: Reference methods
# ---------------------------------------------------------------------------

class TestReferenceMethods:
    """Test different reference value methods."""

    def test_mean_value_reference(self, qgis_app):
        """With REFERENCE=mean_value, reference is the mean of all values."""
        fields = make_fields()
        feat1 = _make_square_feature(500000, 5500000, 10000, 'a', 100.0, fields)
        feat2 = _make_square_feature(520000, 5500000, 10000, 'b', 50.0, fields)
        layer = make_layer([feat1, feat2], crs_id='EPSG:32633')

        features, _, _, _ = _run_replace_with_shape(
            layer, reference=1, scale_method=0)

        scales = {}
        for f in features:
            scales[f.attribute('name')] = f.attribute('_tessera_scale_factor')

        # Mean = (100 + 50) / 2 = 75
        # a: 100/75 = 1.333, b: 50/75 = 0.667
        assert abs(scales['a'] - 100.0/75.0) < 0.01
        assert abs(scales['b'] - 50.0/75.0) < 0.01

    def test_fixed_reference(self, qgis_app):
        """With REFERENCE=fixed, FIXED_REFERENCE value is used."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'a', 200.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')

        features, _, _, _ = _run_replace_with_shape(
            layer, reference=2, scale_method=0,
            extra_params={'FIXED_REFERENCE': 400.0})

        assert len(features) == 1
        scale = features[0].attribute('_tessera_scale_factor')
        # 200/400 = 0.5
        assert abs(scale - 0.5) < 0.01, \
            f"Fixed reference scale: expected 0.5, got {scale}"


# ---------------------------------------------------------------------------
# Test 14: Output geometry is valid polygon
# ---------------------------------------------------------------------------

class TestOutputGeometry:
    """Test output geometry properties."""

    def test_output_is_multipolygon(self, qgis_app):
        """Output geometry is MultiPolygon type."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'sq1', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')
        features, _, _, _ = _run_replace_with_shape(layer)

        assert len(features) == 1
        geom = features[0].geometry()
        assert geom.isMultipart(), "Output should be MultiPolygon"
        assert geom.type() == QgsWkbTypes.PolygonGeometry

    def test_output_has_positive_area(self, qgis_app):
        """Output geometry has positive area."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'sq1', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')
        features, _, _, _ = _run_replace_with_shape(layer)

        assert len(features) == 1
        assert features[0].geometry().area() > 0

    def test_output_crs_matches_input(self, qgis_app):
        """Output layer CRS matches input layer CRS."""
        fields = make_fields()
        feat = _make_square_feature(500000, 5500000, 10000, 'sq1', 100.0, fields)
        layer = make_layer([feat], crs_id='EPSG:32633')

        project = QgsProject.instance()
        project.addMapLayer(layer)
        try:
            context = QgsProcessingContext()
            context.setProject(project)
            feedback = QgsProcessingFeedback()

            alg = ReplaceWithShapeAlgorithm()
            alg.initAlgorithm()

            parameters = {
                'INPUT': layer.id(),
                'VALUE_FIELD': 'pop',
                'SHAPE': 0,
                'SCALE_METHOD': 0,
                'REFERENCE': 0,
                'OUTPUT': 'memory:',
            }
            results = alg.processAlgorithm(parameters, context, feedback)
            output_layer = context.takeResultLayer(results['OUTPUT'])

            assert output_layer is not None
            assert output_layer.crs().authid() == 'EPSG:32633', \
                f"Expected EPSG:32633, got {output_layer.crs().authid()}"
        finally:
            project.removeMapLayer(layer.id())
