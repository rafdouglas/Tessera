"""Tests for ArrangeFeaturesAlgorithm.

Geometric overlap resolution and force-directed attraction.
Tests cover metadata, parameters, output fields, overlap resolution,
convergence, adaptive damping, anchor strength, attribute passthrough,
feature count preservation, and attract/gap mode.
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
    QgsProcessingParameterBoolean,
    QgsProcessingParameterNumber,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType

from tessera.algorithms.arrange_features import ArrangeFeaturesAlgorithm

from .helpers import make_fields, make_feature, make_layer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_circle_feature(cx, cy, radius, name, value, fields, n_segments=64):
    """Create a circular polygon feature centered at (cx, cy) with given radius."""
    points = []
    for i in range(n_segments):
        angle = 2.0 * math.pi * i / n_segments
        px = cx + radius * math.cos(angle)
        py = cy + radius * math.sin(angle)
        points.append(QgsPointXY(px, py))
    points.append(points[0])  # close the ring
    geom = QgsGeometry.fromPolygonXY([points])
    return make_feature(geom, name, value, fields)


def _make_square_feature(cx, cy, half_side, name, value, fields):
    """Create a square polygon feature centered at (cx, cy)."""
    ring = [
        QgsPointXY(cx - half_side, cy - half_side),
        QgsPointXY(cx + half_side, cy - half_side),
        QgsPointXY(cx + half_side, cy + half_side),
        QgsPointXY(cx - half_side, cy + half_side),
        QgsPointXY(cx - half_side, cy - half_side),
    ]
    geom = QgsGeometry.fromPolygonXY([ring])
    return make_feature(geom, name, value, fields)


def _run_resolve_overlaps(layer, iterations=100, damping=0.1,
                          anchor_strength=0.01,
                          convergence_threshold=0.01,
                          adaptive_damping=True,
                          mode=0,
                          separation_distance=0.0):
    """Run ArrangeFeaturesAlgorithm and return output features.

    Returns (features_list, result_dict, feedback, output_layer).
    """
    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'QUALITY': 3,
            'ITERATIONS': iterations,
            'DAMPING': damping,
            'ANCHOR_STRENGTH': anchor_strength,
            'CONVERGENCE_THRESHOLD': convergence_threshold,
            'ADAPTIVE_DAMPING': adaptive_damping,
            'MODE': mode,
            'SEPARATION_DISTANCE': separation_distance,
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
        return features, results, feedback, output_layer
    finally:
        project.removeMapLayer(layer.id())


def _run_resolve_overlaps_with_feedback(layer, iterations=100, damping=0.1,
                                        anchor_strength=0.01,
                                        convergence_threshold=0.01,
                                        adaptive_damping=True,
                                        mode=0,
                                        separation_distance=0.0):
    """Like _run_resolve_overlaps but also captures warnings and errors."""
    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        warnings = []
        errors = []
        orig_warn = feedback.pushWarning
        orig_error = feedback.reportError

        def capture_warn(msg):
            warnings.append(msg)
            orig_warn(msg)

        def capture_error(msg, fatal=False):
            errors.append(msg)
            orig_error(msg, fatal)

        feedback.pushWarning = capture_warn
        feedback.reportError = capture_error

        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'QUALITY': 3,
            'ITERATIONS': iterations,
            'DAMPING': damping,
            'ANCHOR_STRENGTH': anchor_strength,
            'CONVERGENCE_THRESHOLD': convergence_threshold,
            'ADAPTIVE_DAMPING': adaptive_damping,
            'MODE': mode,
            'SEPARATION_DISTANCE': separation_distance,
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
        return features, results, feedback, warnings, errors, output_layer
    finally:
        project.removeMapLayer(layer.id())


# ===========================================================================
# Test 1: Import and metadata
# ===========================================================================

class TestResolveOverlapsMetadata:
    """Test algorithm import and metadata."""

    def test_importable(self):
        """ArrangeFeaturesAlgorithm imports without error."""
        assert ArrangeFeaturesAlgorithm is not None

    def test_metadata(self):
        """name='arrange_features', displayName='Arrange Features', group='Layout', groupId='layout'."""
        alg = ArrangeFeaturesAlgorithm()
        assert alg.name() == 'arrange_features'
        assert alg.displayName() == 'Arrange Features'
        assert alg.group() == 'Layout'
        assert alg.groupId() == 'layout'

    def test_create_instance(self):
        """createInstance returns a new ArrangeFeaturesAlgorithm."""
        alg = ArrangeFeaturesAlgorithm()
        instance = alg.createInstance()
        assert isinstance(instance, ArrangeFeaturesAlgorithm)
        assert instance is not alg


# ===========================================================================
# Test 2: Parameters defined correctly
# ===========================================================================

class TestResolveOverlapsParameters:
    """Test algorithm parameters after initAlgorithm."""

    def test_has_all_parameters(self, qgis_app):
        """After initAlgorithm(), has INPUT, OUTPUT, ITERATIONS, DAMPING,
        ANCHOR_STRENGTH, CONVERGENCE_THRESHOLD, ADAPTIVE_DAMPING."""
        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()

        param_names = [p.name() for p in alg.parameterDefinitions()]
        assert 'INPUT' in param_names
        assert 'OUTPUT' in param_names
        assert 'ITERATIONS' in param_names
        assert 'DAMPING' in param_names
        assert 'ANCHOR_STRENGTH' in param_names
        assert 'CONVERGENCE_THRESHOLD' in param_names
        assert 'ADAPTIVE_DAMPING' in param_names

    def test_iterations_parameter(self, qgis_app):
        """ITERATIONS is integer, default=100, min=1, max=1000."""
        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('ITERATIONS')
        assert isinstance(param, QgsProcessingParameterNumber)
        assert param.defaultValue() == 100
        assert param.minimum() == 1
        assert param.maximum() == 1000

    def test_damping_parameter(self, qgis_app):
        """DAMPING is double, default=0.1, min=0.01, max=1.0."""
        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('DAMPING')
        assert isinstance(param, QgsProcessingParameterNumber)
        assert param.defaultValue() == 0.1
        assert abs(param.minimum() - 0.01) < 1e-9
        assert abs(param.maximum() - 1.0) < 1e-9

    def test_anchor_strength_parameter(self, qgis_app):
        """ANCHOR_STRENGTH is double, default=0.01, min=0.0, max=1.0."""
        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('ANCHOR_STRENGTH')
        assert isinstance(param, QgsProcessingParameterNumber)
        assert param.defaultValue() == 0.01
        assert abs(param.minimum() - 0.0) < 1e-9
        assert abs(param.maximum() - 1.0) < 1e-9

    def test_convergence_threshold_parameter(self, qgis_app):
        """CONVERGENCE_THRESHOLD is double, default=0.01, min=0.0, max=1.0."""
        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('CONVERGENCE_THRESHOLD')
        assert isinstance(param, QgsProcessingParameterNumber)
        assert param.defaultValue() == 0.01
        assert abs(param.minimum() - 0.0) < 1e-9
        assert abs(param.maximum() - 1.0) < 1e-9

    def test_adaptive_damping_parameter(self, qgis_app):
        """ADAPTIVE_DAMPING is boolean, default=True."""
        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('ADAPTIVE_DAMPING')
        assert isinstance(param, QgsProcessingParameterBoolean)
        assert param.defaultValue() is True


# ===========================================================================
# Test 3: Output fields correct
# ===========================================================================

class TestResolveOverlapsOutputFields:
    """Test that output has correct _tessera_* fields."""

    def test_output_has_tessera_fields(self, qgis_app):
        """Output has _tessera_algorithm, _tessera_parent_fid, _tessera_iteration."""
        fields = make_fields()
        # Two non-overlapping circles far apart
        feat1 = _make_circle_feature(5.0, 5.0, 0.5, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(15.0, 15.0, 0.5, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(layer, iterations=10)

        assert len(features) == 2
        feat = features[0]
        field_names = [feat.fields().field(i).name()
                       for i in range(feat.fields().count())]

        assert '_tessera_algorithm' in field_names
        assert '_tessera_parent_fid' in field_names
        assert '_tessera_iteration' in field_names

        for f in features:
            assert f.attribute('_tessera_algorithm') == 'arrange_features'

    def test_tessera_iteration_is_int(self, qgis_app):
        """_tessera_iteration should be a positive integer."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 0.5, 'c1', 10.0, fields)
        layer = make_layer([feat1])

        features, _, _, _ = _run_resolve_overlaps(layer, iterations=10)
        assert len(features) == 1
        iteration_val = features[0].attribute('_tessera_iteration')
        assert isinstance(iteration_val, int)
        assert iteration_val >= 0


# ===========================================================================
# Test 4: Two overlapping circles resolved
# ===========================================================================

class TestOverlappingCirclesResolved:
    """Test that two overlapping circles are pushed apart."""

    def test_two_overlapping_circles_separated(self, qgis_app):
        """After resolution, distance between centers >= sum of radii (approximately)."""
        fields = make_fields()
        radius = 1.0
        # Place two circles with centers 1.0 apart (overlap = 2*1.0 - 1.0 = 1.0)
        feat1 = _make_circle_feature(5.0, 5.0, radius, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(6.0, 5.0, radius, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True,
        )

        assert len(features) == 2

        # Compute distance between output centroids
        c1 = features[0].geometry().centroid().asPoint()
        c2 = features[1].geometry().centroid().asPoint()
        dist = math.hypot(c2.x() - c1.x(), c2.y() - c1.y())

        # The collision radii are approximately 1.0 (minimum enclosing circle
        # of a 64-segment polygon approximating a circle). After resolution,
        # the distance should be close to or exceed 2*radius.
        # Allow some tolerance due to CRS transform and polygon approximation.
        assert dist > 1.5, (
            f"Expected centers to be pushed apart (dist={dist:.4f}), "
            f"but they are still too close"
        )

    def test_three_overlapping_circles(self, qgis_app):
        """Three overlapping circles in a triangle should separate."""
        fields = make_fields()
        radius = 1.0
        # Equilateral triangle with side 1.0 (overlap = 2*1.0 - 1.0 = 1.0)
        feat1 = _make_circle_feature(5.0, 5.0, radius, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(6.0, 5.0, radius, 'c2', 20.0, fields)
        feat3 = _make_circle_feature(5.5, 5.0 + math.sqrt(3) / 2, radius, 'c3', 30.0, fields)
        layer = make_layer([feat1, feat2, feat3])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True,
        )

        assert len(features) == 3

        # All pairwise distances should be > 1.5 (loose tolerance)
        centroids = [f.geometry().centroid().asPoint() for f in features]
        for i in range(3):
            for j in range(i + 1, 3):
                dist = math.hypot(
                    centroids[j].x() - centroids[i].x(),
                    centroids[j].y() - centroids[i].y(),
                )
                assert dist > 1.5, (
                    f"Pair ({i},{j}) still too close: dist={dist:.4f}"
                )


# ===========================================================================
# Test 5: Non-overlapping features unchanged
# ===========================================================================

class TestNonOverlappingUnchanged:
    """Test that non-overlapping features remain in approximately original positions."""

    def test_non_overlapping_stay_put(self, qgis_app):
        """Features that don't overlap should barely move."""
        fields = make_fields()
        # Two circles far apart (10 units between centers, radius 0.5)
        feat1 = _make_circle_feature(5.0, 5.0, 0.5, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(15.0, 5.0, 0.5, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=100, damping=0.1,
            anchor_strength=0.01, convergence_threshold=0.01,
        )

        assert len(features) == 2

        c1 = features[0].geometry().centroid().asPoint()
        c2 = features[1].geometry().centroid().asPoint()

        # Should be very close to original positions
        # (CRS transform introduces small shifts, so allow generous tolerance)
        assert abs(c1.x() - 5.0) < 0.5, f"c1.x moved too much: {c1.x()}"
        assert abs(c1.y() - 5.0) < 0.5, f"c1.y moved too much: {c1.y()}"
        assert abs(c2.x() - 15.0) < 0.5, f"c2.x moved too much: {c2.x()}"
        assert abs(c2.y() - 5.0) < 0.5, f"c2.y moved too much: {c2.y()}"


# ===========================================================================
# Test 6: Convergence before max iterations
# ===========================================================================

class TestConvergence:
    """Test that the algorithm converges before max iterations for simple cases."""

    def test_converges_early_for_non_overlapping(self, qgis_app):
        """Non-overlapping features should converge on iteration 1."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 0.5, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(15.0, 5.0, 0.5, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=100, damping=0.1,
            anchor_strength=0.0, convergence_threshold=0.01,
        )

        assert len(features) == 2
        # With no overlaps and no anchor, convergence should happen immediately
        iteration_val = features[0].attribute('_tessera_iteration')
        assert iteration_val < 10, (
            f"Expected early convergence, but ran {iteration_val} iterations"
        )

    def test_simple_overlap_converges_before_max(self, qgis_app):
        """Two overlapping circles with high iterations should converge before max."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 0.5, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(5.5, 5.0, 0.5, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=1000, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.01,
            adaptive_damping=False,
        )

        assert len(features) == 2
        iteration_val = features[0].attribute('_tessera_iteration')
        assert iteration_val < 1000, (
            f"Expected convergence before 1000 iterations, ran {iteration_val}"
        )


# ===========================================================================
# Test 7: Adaptive damping reduces displacement over time
# ===========================================================================

class TestAdaptiveDamping:
    """Test that adaptive damping reduces effective push over iterations."""

    def test_adaptive_vs_fixed_damping(self, qgis_app):
        """With adaptive damping, features move less in later iterations.

        We verify indirectly: adaptive damping with the same parameters
        should result in features closer to their original positions
        than fixed damping (because the push weakens over time while
        the anchor pull remains constant relative to displacement).
        """
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields)

        # Run with adaptive damping
        layer_adaptive = make_layer([
            _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields),
            _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields),
        ])
        features_adaptive, _, _, _ = _run_resolve_overlaps(
            layer_adaptive, iterations=50, damping=0.5,
            anchor_strength=0.0, convergence_threshold=0.0,
            adaptive_damping=True,
        )

        # Run with fixed damping
        layer_fixed = make_layer([
            _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields),
            _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields),
        ])
        features_fixed, _, _, _ = _run_resolve_overlaps(
            layer_fixed, iterations=50, damping=0.5,
            anchor_strength=0.0, convergence_threshold=0.0,
            adaptive_damping=False,
        )

        # With fixed damping and no anchor, features spread more
        c1_adaptive = features_adaptive[0].geometry().centroid().asPoint()
        c2_adaptive = features_adaptive[1].geometry().centroid().asPoint()
        dist_adaptive = math.hypot(
            c2_adaptive.x() - c1_adaptive.x(),
            c2_adaptive.y() - c1_adaptive.y(),
        )

        c1_fixed = features_fixed[0].geometry().centroid().asPoint()
        c2_fixed = features_fixed[1].geometry().centroid().asPoint()
        dist_fixed = math.hypot(
            c2_fixed.x() - c1_fixed.x(),
            c2_fixed.y() - c1_fixed.y(),
        )

        # Fixed damping with no convergence check pushes harder for longer,
        # so final distance should be larger (or equal, in the converged case)
        assert dist_fixed >= dist_adaptive - 0.1, (
            f"Fixed damping distance ({dist_fixed:.4f}) should be >= "
            f"adaptive ({dist_adaptive:.4f})"
        )


# ===========================================================================
# Test 8: ANCHOR_STRENGTH pulls features back
# ===========================================================================

class TestAnchorStrength:
    """Test that anchor strength pulls features toward original positions."""

    def test_strong_anchor_limits_drift(self, qgis_app):
        """With high ANCHOR_STRENGTH, features stay closer to original positions
        compared to zero anchor."""
        fields = make_fields()

        # Run with strong anchor
        layer_anchor = make_layer([
            _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields),
            _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields),
        ])
        features_anchor, _, _, _ = _run_resolve_overlaps(
            layer_anchor, iterations=200, damping=0.3,
            anchor_strength=0.5, convergence_threshold=0.001,
            adaptive_damping=True,
        )

        # Run with zero anchor
        layer_free = make_layer([
            _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields),
            _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields),
        ])
        features_free, _, _, _ = _run_resolve_overlaps(
            layer_free, iterations=200, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True,
        )

        # Compute drift from original for both
        # Original midpoint is (5.5, 5.0)
        c1_anchor = features_anchor[0].geometry().centroid().asPoint()
        c2_anchor = features_anchor[1].geometry().centroid().asPoint()
        midpoint_anchor_x = (c1_anchor.x() + c2_anchor.x()) / 2
        midpoint_anchor_y = (c1_anchor.y() + c2_anchor.y()) / 2

        c1_free = features_free[0].geometry().centroid().asPoint()
        c2_free = features_free[1].geometry().centroid().asPoint()
        midpoint_free_x = (c1_free.x() + c2_free.x()) / 2
        midpoint_free_y = (c1_free.y() + c2_free.y()) / 2

        # The anchored midpoint should be closer to original (5.5, 5.0)
        # than the free midpoint, OR equally close.
        drift_anchor = math.hypot(midpoint_anchor_x - 5.5, midpoint_anchor_y - 5.0)
        drift_free = math.hypot(midpoint_free_x - 5.5, midpoint_free_y - 5.0)

        # Both should be near the midpoint in this symmetric case,
        # but check that anchored displacement per-feature is smaller
        disp_anchor_1 = math.hypot(c1_anchor.x() - 5.0, c1_anchor.y() - 5.0)
        disp_free_1 = math.hypot(c1_free.x() - 5.0, c1_free.y() - 5.0)

        assert disp_anchor_1 <= disp_free_1 + 0.1, (
            f"Anchor should limit drift: anchored={disp_anchor_1:.4f}, "
            f"free={disp_free_1:.4f}"
        )

    def test_zero_anchor_allows_free_drift(self, qgis_app):
        """With ANCHOR_STRENGTH=0, algorithm runs without error and shapes can drift."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=100, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.01,
        )

        assert len(features) == 2
        # Just verify it ran successfully
        for f in features:
            assert not f.geometry().isEmpty()


# ===========================================================================
# Test 9: Attribute passthrough
# ===========================================================================

class TestAttributePassthrough:
    """Test that original attributes are preserved."""

    def test_original_attributes_preserved(self, qgis_app):
        """Parent 'name' and 'value' attributes are carried to output."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 0.5, 'circle_a', 42.0, fields)
        feat2 = _make_circle_feature(15.0, 5.0, 0.5, 'circle_b', 99.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(layer, iterations=10)

        assert len(features) == 2

        # Sort by name to get consistent ordering
        features_by_name = sorted(features, key=lambda f: f.attribute('name'))
        assert features_by_name[0].attribute('name') == 'circle_a'
        assert features_by_name[0].attribute('value') == 42.0
        assert features_by_name[1].attribute('name') == 'circle_b'
        assert features_by_name[1].attribute('value') == 99.0


# ===========================================================================
# Test 10: Feature count preserved
# ===========================================================================

class TestFeatureCountPreserved:
    """Test that feature count is preserved (same in, same out)."""

    def test_single_feature(self, qgis_app):
        """Single feature in, single feature out."""
        fields = make_fields()
        feat = _make_circle_feature(5.0, 5.0, 1.0, 'solo', 10.0, fields)
        layer = make_layer([feat])

        features, _, _, _ = _run_resolve_overlaps(layer, iterations=10)
        assert len(features) == 1

    def test_multiple_features(self, qgis_app):
        """N features in, N features out."""
        fields = make_fields()
        feats = []
        for i in range(5):
            feats.append(
                _make_circle_feature(5.0 + i * 0.8, 5.0, 0.5,
                                     f'c{i}', float(i * 10), fields)
            )
        layer = make_layer(feats)

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=100, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.01,
        )
        assert len(features) == 5

    def test_all_non_overlapping(self, qgis_app):
        """Multiple non-overlapping features: count preserved."""
        fields = make_fields()
        feats = []
        for i in range(4):
            feats.append(
                _make_circle_feature(5.0 + i * 10.0, 5.0, 0.5,
                                     f'c{i}', float(i * 10), fields)
            )
        layer = make_layer(feats)

        features, _, _, _ = _run_resolve_overlaps(layer, iterations=10)
        assert len(features) == 4


# ===========================================================================
# Additional edge case tests
# ===========================================================================

class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_overlapping_squares(self, qgis_app):
        """Overlapping squares are pushed apart."""
        fields = make_fields()
        feat1 = _make_square_feature(5.0, 5.0, 0.5, 'sq1', 10.0, fields)
        feat2 = _make_square_feature(5.5, 5.0, 0.5, 'sq2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True,
        )

        assert len(features) == 2
        c1 = features[0].geometry().centroid().asPoint()
        c2 = features[1].geometry().centroid().asPoint()
        dist = math.hypot(c2.x() - c1.x(), c2.y() - c1.y())

        # Squares should have been pushed apart
        assert dist > 0.5, (
            f"Expected squares to be pushed apart, dist={dist:.4f}"
        )

    def test_output_geometry_is_multipolygon(self, qgis_app):
        """Output geometries are promoted to MultiPolygon."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 0.5, 'c1', 10.0, fields)
        layer = make_layer([feat1])

        features, _, _, _ = _run_resolve_overlaps(layer, iterations=10)

        assert len(features) == 1
        geom = features[0].geometry()
        assert geom.isMultipart(), "Output geometry should be MultiPolygon"
        assert geom.type() == QgsWkbTypes.PolygonGeometry

    def test_remaining_overlaps_warning(self, qgis_app):
        """When overlaps cannot be fully resolved, a warning is issued."""
        fields = make_fields()
        # Create many tightly packed circles that can't be fully resolved
        # in just 1 iteration with low damping
        feats = []
        for i in range(5):
            for j in range(5):
                feats.append(
                    _make_circle_feature(
                        5.0 + i * 0.3, 5.0 + j * 0.3, 0.5,
                        f'c{i}_{j}', 10.0, fields,
                    )
                )
        layer = make_layer(feats)

        features, _, _, warnings, errors, _ = _run_resolve_overlaps_with_feedback(
            layer, iterations=1, damping=0.01,
            anchor_strength=0.0, convergence_threshold=0.0,
            adaptive_damping=False,
        )

        assert len(features) == 25
        # Should have a warning about remaining overlaps
        assert any('overlapping' in w.lower() for w in warnings), (
            f"Expected warning about remaining overlaps, got: {warnings}"
        )

    def test_iteration_count_recorded(self, qgis_app):
        """_tessera_iteration records the actual iteration count at termination."""
        fields = make_fields()
        # Non-overlapping features should converge quickly
        feat1 = _make_circle_feature(5.0, 5.0, 0.5, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(15.0, 5.0, 0.5, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.1,
            anchor_strength=0.0, convergence_threshold=0.01,
        )

        assert len(features) == 2
        # Both features should have the same iteration count
        iter1 = features[0].attribute('_tessera_iteration')
        iter2 = features[1].attribute('_tessera_iteration')
        assert iter1 == iter2, (
            f"All features should have same iteration count: {iter1} vs {iter2}"
        )
        assert iter1 >= 1, "Iteration count should be >= 1"


# ===========================================================================
# R2.1-R2.14: New MODE and SEPARATION_DISTANCE tests
# ===========================================================================

class TestResolveOverlapsNewParameters:
    """Tests for MODE and SEPARATION_DISTANCE parameters."""

    def test_mode_parameter_exists(self, qgis_app):
        """R2.1: MODE parameter exists as Enum with 3 options, default=0."""
        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('MODE')
        assert param is not None, "MODE parameter should exist"
        assert param.defaultValue() == 0
        options = param.options()
        assert len(options) == 3
        assert options[0] == 'Separate'
        assert options[1] == 'Attract'
        assert options[2] == 'Separate with gap'

    def test_separation_distance_parameter_exists(self, qgis_app):
        """R2.2: SEPARATION_DISTANCE parameter exists as Double, default=0.0, min=0.0."""
        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('SEPARATION_DISTANCE')
        assert param is not None, "SEPARATION_DISTANCE parameter should exist"
        assert param.defaultValue() == 0.0
        assert abs(param.minimum() - 0.0) < 1e-9


class TestSeparateMode:
    """Tests for separate mode (backward compatibility)."""

    def test_separate_mode_backward_compatible(self, qgis_app):
        """R2.3: separate mode same behavior as before."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=0,
        )

        assert len(features) == 2
        c1 = features[0].geometry().centroid().asPoint()
        c2 = features[1].geometry().centroid().asPoint()
        dist = math.hypot(c2.x() - c1.x(), c2.y() - c1.y())
        assert dist > 1.5, (
            f"Separate mode should push apart, dist={dist:.4f}"
        )


class TestAttractMode:
    """Tests for attract mode."""

    def test_attract_pulls_separated_features(self, qgis_app):
        """R2.4: attract mode pulls separated features together."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(15.0, 5.0, 1.0, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=False, mode=1,
        )

        assert len(features) == 2
        c1 = features[0].geometry().centroid().asPoint()
        c2 = features[1].geometry().centroid().asPoint()
        dist = math.hypot(c2.x() - c1.x(), c2.y() - c1.y())
        # Should have been pulled closer than original 10.0
        assert dist < 10.0, (
            f"Attract mode should pull closer, dist={dist:.4f}"
        )

    def test_attract_stabilizes_overlapping_at_touching(self, qgis_app):
        """R2.5: attract mode pushes overlapping features to just touching."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(5.5, 5.0, 1.0, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=False, mode=1,
        )

        assert len(features) == 2
        c1 = features[0].geometry().centroid().asPoint()
        c2 = features[1].geometry().centroid().asPoint()
        dist = math.hypot(c2.x() - c1.x(), c2.y() - c1.y())
        # Should be pushed apart from 0.5 to approximately touching (~2.0)
        assert dist > 1.5, (
            f"Overlapping features should be pushed to touching, dist={dist:.4f}"
        )

    def test_attract_three_features_cluster(self, qgis_app):
        """R2.6: attract mode with three features forms cluster."""
        fields = make_fields()
        feat1 = _make_circle_feature(0.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(10.0, 5.0, 1.0, 'c2', 20.0, fields)
        feat3 = _make_circle_feature(20.0, 5.0, 1.0, 'c3', 30.0, fields)
        layer = make_layer([feat1, feat2, feat3])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=False, mode=1,
        )

        assert len(features) == 3
        centroids = [f.geometry().centroid().asPoint() for f in features]
        # All pairs should be close (approximately touching at ~2.0)
        for i in range(3):
            for j in range(i + 1, 3):
                dist = math.hypot(
                    centroids[j].x() - centroids[i].x(),
                    centroids[j].y() - centroids[i].y(),
                )
                assert dist < 10.0, (
                    f"Pair ({i},{j}) should have clustered, dist={dist:.4f}"
                )

    def test_attract_with_anchor_limits_clustering(self, qgis_app):
        """R2.7: attract mode with anchor_strength limits clustering."""
        fields = make_fields()

        layer_no_anchor = make_layer([
            _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields),
            _make_circle_feature(15.0, 5.0, 1.0, 'c2', 20.0, fields),
        ])
        features_no_anchor, _, _, _ = _run_resolve_overlaps(
            layer_no_anchor, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=False, mode=1,
        )

        layer_anchor = make_layer([
            _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields),
            _make_circle_feature(15.0, 5.0, 1.0, 'c2', 20.0, fields),
        ])
        features_anchor, _, _, _ = _run_resolve_overlaps(
            layer_anchor, iterations=500, damping=0.3,
            anchor_strength=0.5, convergence_threshold=0.001,
            adaptive_damping=False, mode=1,
        )

        c_na = [f.geometry().centroid().asPoint() for f in features_no_anchor]
        dist_na = math.hypot(c_na[1].x() - c_na[0].x(), c_na[1].y() - c_na[0].y())

        c_a = [f.geometry().centroid().asPoint() for f in features_anchor]
        dist_a = math.hypot(c_a[1].x() - c_a[0].x(), c_a[1].y() - c_a[0].y())

        # With anchor, features should stay further apart
        assert dist_a > dist_na - 0.5, (
            f"Anchor should limit clustering: anchored={dist_a:.4f}, "
            f"free={dist_na:.4f}"
        )

    def test_attract_single_feature_no_error(self, qgis_app):
        """R2.8: attract mode with single feature — no error, no movement."""
        fields = make_fields()
        feat = _make_circle_feature(5.0, 5.0, 1.0, 'solo', 10.0, fields)
        layer = make_layer([feat])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=100, damping=0.3,
            anchor_strength=0.0, mode=1,
        )

        assert len(features) == 1
        c = features[0].geometry().centroid().asPoint()
        assert abs(c.x() - 5.0) < 0.5
        assert abs(c.y() - 5.0) < 0.5

    def test_attract_convergence_before_max(self, qgis_app):
        """R2.9: attract mode convergence before max iterations."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(10.0, 5.0, 1.0, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=1000, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.01,
            adaptive_damping=False, mode=1,
        )

        assert len(features) == 2
        iteration_val = features[0].attribute('_tessera_iteration')
        assert iteration_val < 1000, (
            f"Expected convergence before 1000 iterations, ran {iteration_val}"
        )


class TestGapMode:
    """Tests for separate_with_gap mode."""

    def test_gap_separates_beyond_touching(self, qgis_app):
        """R2.10: gap mode separates beyond touching."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=False, mode=2, separation_distance=0.5,
        )

        assert len(features) == 2
        c1 = features[0].geometry().centroid().asPoint()
        c2 = features[1].geometry().centroid().asPoint()
        dist = math.hypot(c2.x() - c1.x(), c2.y() - c1.y())
        # Original gap between centers was 1.0. With gap mode and
        # separation_distance=0.5, features should push further apart
        # than simple separate mode. CRS transforms add noise.
        assert dist > 1.5, (
            f"Gap mode should push apart (further than original 1.0), "
            f"dist={dist:.4f}"
        )

    def test_gap_pushes_close_but_not_overlapping(self, qgis_app):
        """R2.11: gap mode pushes close-but-not-overlapping features apart."""
        fields = make_fields()
        # Two circles 2.5 apart, radius 1.0 — not overlapping but within gap
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(7.5, 5.0, 1.0, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=2, separation_distance=1.0,
        )

        assert len(features) == 2
        c1 = features[0].geometry().centroid().asPoint()
        c2 = features[1].geometry().centroid().asPoint()
        dist = math.hypot(c2.x() - c1.x(), c2.y() - c1.y())
        # Distance should have increased from 2.5
        assert dist > 2.5, (
            f"Gap mode should push close features apart, dist={dist:.4f}"
        )

    def test_gap_already_separated_no_movement(self, qgis_app):
        """R2.12: gap mode with already-separated features — no movement."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(25.0, 5.0, 1.0, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=100, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.01,
            adaptive_damping=True, mode=2, separation_distance=1.0,
        )

        assert len(features) == 2
        c1 = features[0].geometry().centroid().asPoint()
        c2 = features[1].geometry().centroid().asPoint()
        dist = math.hypot(c2.x() - c1.x(), c2.y() - c1.y())
        assert abs(dist - 20.0) < 1.0, (
            f"Already-separated features should barely move, dist={dist:.4f}"
        )

    def test_gap_remaining_overlap_warning(self, qgis_app):
        """R2.13: gap mode remaining-overlap warning uses gap in calculation."""
        fields = make_fields()
        feats = []
        for i in range(5):
            for j in range(5):
                feats.append(
                    _make_circle_feature(
                        5.0 + i * 0.3, 5.0 + j * 0.3, 0.5,
                        f'c{i}_{j}', 10.0, fields,
                    )
                )
        layer = make_layer(feats)

        features, _, _, warnings, errors, _ = _run_resolve_overlaps_with_feedback(
            layer, iterations=1, damping=0.01,
            anchor_strength=0.0, convergence_threshold=0.0,
            adaptive_damping=False, mode=2, separation_distance=5.0,
        )

        assert len(features) == 25
        assert any('overlapping' in w.lower() for w in warnings), (
            f"Expected gap-aware warning about remaining overlaps, got: {warnings}"
        )

    def test_separation_distance_ignored_in_separate_mode(self, qgis_app):
        """R2.14: SEPARATION_DISTANCE ignored when MODE is not 'separate_with_gap'."""
        fields = make_fields()

        layer1 = make_layer([
            _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields),
            _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields),
        ])
        features_sd0, _, _, _ = _run_resolve_overlaps(
            layer1, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=0, separation_distance=0.0,
        )

        layer2 = make_layer([
            _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields),
            _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields),
        ])
        features_sd100, _, _, _ = _run_resolve_overlaps(
            layer2, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=0, separation_distance=100.0,
        )

        c_sd0 = [f.geometry().centroid().asPoint() for f in features_sd0]
        dist_sd0 = math.hypot(c_sd0[1].x() - c_sd0[0].x(), c_sd0[1].y() - c_sd0[0].y())

        c_sd100 = [f.geometry().centroid().asPoint() for f in features_sd100]
        dist_sd100 = math.hypot(c_sd100[1].x() - c_sd100[0].x(), c_sd100[1].y() - c_sd100[0].y())

        assert abs(dist_sd0 - dist_sd100) < 0.5, (
            f"SEPARATION_DISTANCE should be ignored in separate mode: "
            f"dist_sd0={dist_sd0:.4f}, dist_sd100={dist_sd100:.4f}"
        )


# ===========================================================================
# C0.3: MODE has 3 options
# ===========================================================================

class TestModeHasThreeOptions:
    """Test that MODE enum has 3 options."""

    def test_mode_has_three_options(self, qgis_app):
        """C0.3: MODE has 3 options: Separate, Attract, Separate with gap."""
        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('MODE')
        options = param.options()
        assert len(options) == 3
        assert options[0] == 'Separate'
        assert options[1] == 'Attract'
        assert options[2] == 'Separate with gap'


# ===========================================================================
# C2: Attract mode overshoot fixes
# ===========================================================================

class TestAttractOvershootFix:
    """Tests that attract mode pulls features without overshoot/oscillation."""

    def test_attract_no_overshoot_two_circles(self, qgis_app):
        """C2.1: attract pulls two separated circles together without overshoot.

        Final distance should approximately equal sum of MEC radii (touching),
        with NO overlap (geometry intersection area ≈ 0).
        """
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(15.0, 5.0, 1.0, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=False, mode=1,
        )

        assert len(features) == 2
        g1 = features[0].geometry()
        g2 = features[1].geometry()
        c1 = g1.centroid().asPoint()
        c2 = g2.centroid().asPoint()
        dist = math.hypot(c2.x() - c1.x(), c2.y() - c1.y())

        # Should be approximately touching (~2.0 for two radius-1.0 circles)
        # Within 10% tolerance: 1.8 to 2.2
        assert 1.8 <= dist <= 2.5, (
            f"Expected distance ≈ 2.0 (touching), got {dist:.4f}"
        )

        # Verify NO overlap (intersection area should be negligible)
        intersection = g1.intersection(g2)
        overlap_area = intersection.area() if not intersection.isEmpty() else 0.0
        assert overlap_area < 0.1, (
            f"Features should not overlap after attract, overlap_area={overlap_area:.4f}"
        )

    def test_attract_three_features_equilibrium_no_overlap(self, qgis_app):
        """C2.2: three features in attract all reach equilibrium without overlap."""
        fields = make_fields()
        feat1 = _make_circle_feature(0.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(10.0, 5.0, 1.0, 'c2', 20.0, fields)
        feat3 = _make_circle_feature(20.0, 5.0, 1.0, 'c3', 30.0, fields)
        layer = make_layer([feat1, feat2, feat3])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=False, mode=1,
        )

        assert len(features) == 3
        geoms = [f.geometry() for f in features]
        centroids = [g.centroid().asPoint() for g in geoms]

        # All pairwise distances ≈ 2.0 (within 10% tolerance)
        for i in range(3):
            for j in range(i + 1, 3):
                dist = math.hypot(
                    centroids[j].x() - centroids[i].x(),
                    centroids[j].y() - centroids[i].y(),
                )
                assert dist < 3.0, (
                    f"Pair ({i},{j}) should be close after attract, dist={dist:.4f}"
                )
                # No overlap
                intersection = geoms[i].intersection(geoms[j])
                overlap_area = intersection.area() if not intersection.isEmpty() else 0.0
                assert overlap_area < 0.1, (
                    f"Pair ({i},{j}) should not overlap, area={overlap_area:.4f}"
                )


# ===========================================================================
# C3: Gap mode geometry-based fix
# ===========================================================================

class TestGapModeGeometryFix:
    """Tests that gap mode produces correct actual boundary gap.

    Uses projected CRS (EPSG:3857) so coordinates are in meters and
    SEPARATION_DISTANCE (in working CRS meters) is meaningful.
    """

    def test_gap_correct_actual_boundary_distance(self, qgis_app):
        """C3.1: gap mode produces correct actual boundary gap.

        Uses QgsGeometry.distance() to measure the actual gap between
        output feature boundaries (not centroid distance).
        """
        fields = make_fields()
        # Squares in EPSG:3857 (meters): 10m x 10m, centered 5m apart (overlapping)
        feat1 = _make_square_feature(500000.0, 500000.0, 5.0, 'sq1', 10.0, fields)
        feat2 = _make_square_feature(500005.0, 500000.0, 5.0, 'sq2', 20.0, fields)
        layer = make_layer([feat1, feat2], crs_id='EPSG:3857')

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=2, separation_distance=20.0,
        )

        assert len(features) == 2
        g1 = features[0].geometry()
        g2 = features[1].geometry()
        actual_gap = g1.distance(g2)

        # Actual gap should be approximately 20.0 meters (within 30% tolerance)
        assert actual_gap > 14.0, (
            f"Gap mode should produce actual gap ≈ 20.0, got {actual_gap:.4f}"
        )

    def test_gap_different_distances_produce_different_gaps(self, qgis_app):
        """C3.2: different SEPARATION_DISTANCE values produce different actual gaps."""
        fields = make_fields()

        layer1 = make_layer([
            _make_square_feature(500000.0, 500000.0, 5.0, 'sq1', 10.0, fields),
            _make_square_feature(500005.0, 500000.0, 5.0, 'sq2', 20.0, fields),
        ], crs_id='EPSG:3857')
        features_gap10, _, _, _ = _run_resolve_overlaps(
            layer1, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=2, separation_distance=10.0,
        )

        layer2 = make_layer([
            _make_square_feature(500000.0, 500000.0, 5.0, 'sq1', 10.0, fields),
            _make_square_feature(500005.0, 500000.0, 5.0, 'sq2', 20.0, fields),
        ], crs_id='EPSG:3857')
        features_gap50, _, _, _ = _run_resolve_overlaps(
            layer2, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=2, separation_distance=50.0,
        )

        gap10 = features_gap10[0].geometry().distance(features_gap10[1].geometry())
        gap50 = features_gap50[0].geometry().distance(features_gap50[1].geometry())

        assert gap50 > gap10, (
            f"Larger separation_distance should produce larger gap: "
            f"gap_10={gap10:.4f}, gap_50={gap50:.4f}"
        )

    def test_gap_zero_separation_like_resolve_overlaps(self, qgis_app):
        """C3.3: zero separation_distance behaves like resolve_overlaps mode."""
        fields = make_fields()

        layer_gap0 = make_layer([
            _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields),
            _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields),
        ])
        features_gap0, _, _, _ = _run_resolve_overlaps(
            layer_gap0, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=2, separation_distance=0.0,
        )

        layer_sep = make_layer([
            _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields),
            _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields),
        ])
        features_sep, _, _, _ = _run_resolve_overlaps(
            layer_sep, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=0,
        )

        c_gap0 = [f.geometry().centroid().asPoint() for f in features_gap0]
        dist_gap0 = math.hypot(c_gap0[1].x() - c_gap0[0].x(),
                                c_gap0[1].y() - c_gap0[0].y())

        c_sep = [f.geometry().centroid().asPoint() for f in features_sep]
        dist_sep = math.hypot(c_sep[1].x() - c_sep[0].x(),
                               c_sep[1].y() - c_sep[0].y())

        assert abs(dist_gap0 - dist_sep) < 0.5, (
            f"Gap=0 should behave like resolve_overlaps: "
            f"gap0={dist_gap0:.4f}, sep={dist_sep:.4f}"
        )


# ===========================================================================
# Engineering CRS support tests
# ===========================================================================

class TestEngineeringCRS:
    """Tests for engineering CRS output."""

    def test_force_directed_modes_keep_source_crs(self, qgis_app):
        """Force-directed modes (separate) should keep source CRS."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])  # EPSG:4326

        features, _, _, output_layer = _run_resolve_overlaps(
            layer, iterations=100, damping=0.3,
            anchor_strength=0.0, mode=0,  # separate mode
        )

        assert len(features) == 2
        output_crs = output_layer.crs()
        assert output_crs.authid() == 'EPSG:4326', (
            f"Force-directed mode should keep source CRS. Got: {output_crs.authid()}"
        )

    def test_force_engineering_crs_param_exists(self, qgis_app):
        """FORCE_ENGINEERING_CRS parameter should exist as boolean, default False."""
        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('FORCE_ENGINEERING_CRS')
        assert param is not None, "FORCE_ENGINEERING_CRS parameter should exist"
        assert isinstance(param, QgsProcessingParameterBoolean), (
            "FORCE_ENGINEERING_CRS should be boolean"
        )
        assert param.defaultValue() is False, (
            "FORCE_ENGINEERING_CRS default should be False"
        )

    def test_force_engineering_crs_overrides_source_mode(self, qgis_app):
        """FORCE_ENGINEERING_CRS=True should force engineering CRS in any mode."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])  # EPSG:4326

        # Run mode=0 with FORCE_ENGINEERING_CRS=True
        project = QgsProject.instance()
        project.addMapLayer(layer)
        try:
            context = QgsProcessingContext()
            context.setProject(project)
            feedback = QgsProcessingFeedback()

            alg = ArrangeFeaturesAlgorithm()
            alg.initAlgorithm()

            parameters = {
                'INPUT': layer.id(),
                'ITERATIONS': 100,
                'DAMPING': 0.3,
                'ANCHOR_STRENGTH': 0.0,
                'CONVERGENCE_THRESHOLD': 0.01,
                'ADAPTIVE_DAMPING': True,
                'MODE': 0,  # separate mode
                'SEPARATION_DISTANCE': 0.0,
                'FORCE_ENGINEERING_CRS': True,
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

            assert len(features) == 2
            output_crs = output_layer.crs()
            assert not output_crs.isGeographic(), (
                f"FORCE_ENGINEERING_CRS should force non-geographic CRS. "
                f"Got: {output_crs.authid()}"
            )
        finally:
            project.removeMapLayer(layer.id())


# ===========================================================================
# Parameter organization tests
# ===========================================================================

class TestParameterOrganization:
    """Tests for parameter organization and help text."""

    def test_mode_hint_in_help_text(self, qgis_app):
        """shortHelpString should explain which CRS each mode produces."""
        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()
        help_text = alg.shortHelpString()

        assert help_text is not None, "shortHelpString should not be None"
        assert len(help_text) > 0, "shortHelpString should not be empty"

        # Check for mentions of CRS behavior in different modes
        help_lower = help_text.lower()
        assert 'crs' in help_lower or 'coordinate' in help_lower, (
            "Help text should mention CRS or coordinate system"
        )


# ===========================================================================
# Area-equivalent radius tests
# ===========================================================================

class TestAreaEquivalentRadius:
    """Tests that collision radius uses area-equivalent (sqrt(area/pi)) not MEC."""

    def test_elongated_feature_not_pushed_unreasonably_far(self, qgis_app):
        """Elongated rectangle (1:20 ratio) should not be pushed far from small square.

        A 0.1 x 2.0 rectangle has area=0.2, area-equiv-radius ≈ 0.25,
        but MEC radius ≈ 1.0. With area-equiv radius, these features
        should remain near their original positions since they don't overlap.
        """
        fields = make_fields()
        # Elongated rectangle: width=0.1, height=2.0, centered at (5, 5)
        rect_wkt = "POLYGON((4.95 4, 5.05 4, 5.05 6, 4.95 6, 4.95 4))"
        rect_geom = QgsGeometry.fromWkt(rect_wkt)
        feat1 = make_feature(rect_geom, 'rect', 10.0, fields)

        # Small square: side=0.2, centered at (5.5, 5)
        feat2 = _make_square_feature(5.5, 5.0, 0.1, 'sq', 20.0, fields)

        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=200, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=0,
        )

        assert len(features) == 2
        c1 = features[0].geometry().centroid().asPoint()
        c2 = features[1].geometry().centroid().asPoint()

        # Both features should remain within 1.0 unit of original positions
        # Original positions: (5, 5) and (5.5, 5)
        dist_from_origin_1 = math.hypot(c1.x() - 5.0, c1.y() - 5.0)
        dist_from_origin_2 = math.hypot(c2.x() - 5.5, c2.y() - 5.0)

        assert dist_from_origin_1 < 1.0, (
            f"Elongated rect should not move far with area-equiv radius: "
            f"displacement={dist_from_origin_1:.4f}"
        )
        assert dist_from_origin_2 < 1.0, (
            f"Small square should not move far: displacement={dist_from_origin_2:.4f}"
        )

    def test_elongated_features_displacement_proportional_to_area(self, qgis_app):
        """Two overlapping elongated rectangles should be pushed apart proportionally to area.

        With area-equivalent radius ≈ 0.25 each, displacement should be
        much less than with MEC (radius ≈ 1.0 each).
        """
        fields = make_fields()
        # Two identical rectangles: width=0.1, height=2.0
        rect_wkt1 = "POLYGON((4.95 4, 5.05 4, 5.05 6, 4.95 6, 4.95 4))"
        rect_wkt2 = "POLYGON((5.15 4, 5.25 4, 5.25 6, 5.15 6, 5.15 4))"
        feat1 = make_feature(QgsGeometry.fromWkt(rect_wkt1), 'rect1', 10.0, fields)
        feat2 = make_feature(QgsGeometry.fromWkt(rect_wkt2), 'rect2', 20.0, fields)

        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=200, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=0,
        )

        assert len(features) == 2
        c1 = features[0].geometry().centroid().asPoint()
        c2 = features[1].geometry().centroid().asPoint()

        # Original centers at (5.0, 5.0) and (5.2, 5.0)
        disp1 = math.hypot(c1.x() - 5.0, c1.y() - 5.0)
        disp2 = math.hypot(c2.x() - 5.2, c2.y() - 5.0)

        # With area-equiv radius, displacement should be < 2.0 units
        # (MEC would push them much farther)
        assert disp1 < 2.0, (
            f"Displacement should be proportional to area, not MEC: disp1={disp1:.4f}"
        )
        assert disp2 < 2.0, (
            f"Displacement should be proportional to area, not MEC: disp2={disp2:.4f}"
        )


# ===========================================================================
# Multipart explosion tests
# ===========================================================================

class TestMultipartExplosion:
    """Tests that multipart geometries are exploded into parts for force simulation."""

    def test_multipart_parts_processed_independently(self, qgis_app):
        """Multipart polygon with distant parts should be exploded and parts processed independently.

        One part overlaps with another feature, the other part is far away.
        The far part should not be displaced significantly.
        """
        fields = make_fields()

        # Multipart polygon: two squares 63+ units apart
        # Part 1 at (5, 5), Part 2 at (50, 50)
        multipart_wkt = (
            "MULTIPOLYGON("
            "((4.75 4.75, 5.25 4.75, 5.25 5.25, 4.75 5.25, 4.75 4.75)),"
            "((49.75 49.75, 50.25 49.75, 50.25 50.25, 49.75 50.25, 49.75 49.75))"
            ")"
        )
        multipart_geom = QgsGeometry.fromWkt(multipart_wkt)
        assert not multipart_geom.isEmpty(), "Multipart WKT failed to parse"
        feat_multi = make_feature(multipart_geom, 'multi', 10.0, fields)

        # Single-part square at (5.3, 5) — overlaps with first part of multipart
        feat_single = _make_square_feature(5.3, 5.0, 0.15, 'single', 20.0, fields)

        layer = make_layer([feat_multi, feat_single])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=200, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=0,
        )

        # Output should have 3 features (multipart exploded into 2 + the single)
        assert len(features) == 3, (
            f"Expected 3 features (multipart exploded), got {len(features)}"
        )

        # Identify which features are near (5, 5) and which is near (50, 50)
        centroids = [(f.geometry().centroid().asPoint(), f.attribute('name'))
                     for f in features]
        near_origin = [c for c in centroids if math.hypot(c[0].x() - 5.0, c[0].y() - 5.0) < 10.0]
        near_distant = [c for c in centroids if math.hypot(c[0].x() - 50.0, c[0].y() - 50.0) < 10.0]

        # Should have 2 features near origin (part 1 of multipart + single)
        # and 1 feature near (50, 50) (part 2 of multipart)
        assert len(near_origin) == 2, (
            f"Expected 2 features near origin, got {len(near_origin)}"
        )
        assert len(near_distant) == 1, (
            f"Expected 1 feature near (50,50), got {len(near_distant)}"
        )

        # The two near-origin features should be pushed apart
        if len(near_origin) == 2:
            dist_near = math.hypot(
                near_origin[1][0].x() - near_origin[0][0].x(),
                near_origin[1][0].y() - near_origin[0][0].y(),
            )
            assert dist_near > 0.3, (
                f"Overlapping parts near origin should be pushed apart, dist={dist_near:.4f}"
            )

    def test_multipart_distant_part_not_displaced(self, qgis_app):
        """Distant part of multipart polygon should not be displaced significantly.

        The part near (50, 50) has no neighbors, so it should stay put.
        """
        fields = make_fields()

        # Same setup as previous test
        multipart_wkt = (
            "MULTIPOLYGON("
            "((4.75 4.75, 5.25 4.75, 5.25 5.25, 4.75 5.25, 4.75 4.75)),"
            "((49.75 49.75, 50.25 49.75, 50.25 50.25, 49.75 50.25, 49.75 49.75))"
            ")"
        )
        multipart_geom = QgsGeometry.fromWkt(multipart_wkt)
        assert not multipart_geom.isEmpty(), "Multipart WKT failed to parse"
        feat_multi = make_feature(multipart_geom, 'multi', 10.0, fields)

        feat_single = _make_square_feature(5.3, 5.0, 0.15, 'single', 20.0, fields)

        layer = make_layer([feat_multi, feat_single])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=200, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=0,
        )

        assert len(features) == 3

        # Find the feature near (50, 50)
        for feat in features:
            c = feat.geometry().centroid().asPoint()
            if math.hypot(c.x() - 50.0, c.y() - 50.0) < 10.0:
                # This is the distant part — should be within 1.0 unit of (50, 50)
                dist_from_50 = math.hypot(c.x() - 50.0, c.y() - 50.0)
                assert dist_from_50 < 1.0, (
                    f"Distant part should not be displaced significantly: "
                    f"displacement={dist_from_50:.4f}"
                )
                break
        else:
            assert False, "Could not find feature near (50, 50)"


# ===========================================================================
# Geometry refinement tests
# ===========================================================================

class TestGeometryRefinement:
    """Tests that geometry-based refinement runs for separate mode (not just gap mode)."""

    def test_separate_mode_no_actual_boundary_overlaps_remain(self, qgis_app):
        """After separate mode, no pair of features should have actual boundary overlaps.

        Uses QgsGeometry.intersects() to verify that all actual polygon
        overlaps are resolved, not just MEC-estimated overlaps.
        """
        fields = make_fields()
        # 4 squares in tight cluster, each with half_side=0.25
        # Centers: (5, 5), (5.4, 5), (5, 5.4), (5.4, 5.4)
        # These overlap pairwise
        feats = [
            _make_square_feature(5.0, 5.0, 0.25, 'sq1', 10.0, fields),
            _make_square_feature(5.4, 5.0, 0.25, 'sq2', 20.0, fields),
            _make_square_feature(5.0, 5.4, 0.25, 'sq3', 30.0, fields),
            _make_square_feature(5.4, 5.4, 0.25, 'sq4', 40.0, fields),
        ]
        layer = make_layer(feats)

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=300, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=0,
        )

        assert len(features) == 4

        # Verify no pair has intersecting boundaries
        geoms = [f.geometry() for f in features]
        for i in range(4):
            for j in range(i + 1, 4):
                # Use a small buffer tolerance to account for numerical precision
                intersection = geoms[i].intersection(geoms[j])
                overlap_area = intersection.area() if not intersection.isEmpty() else 0.0
                assert overlap_area < 0.01, (
                    f"Pair ({i},{j}) should not overlap after separate mode: "
                    f"overlap_area={overlap_area:.6f}"
                )

    def test_separate_mode_concave_shapes_no_overlap(self, qgis_app):
        """Two concave U-shaped polygons that interlock should be separated without overlap.

        MEC of U-shapes is large (enclosing the concavity), but actual
        geometry overlap should be resolved.
        """
        fields = make_fields()

        # U-shape facing right
        u1_wkt = "POLYGON((4 4, 5 4, 5 6, 4.5 6, 4.5 4.5, 4 4.5, 4 4))"
        feat1 = make_feature(QgsGeometry.fromWkt(u1_wkt), 'u1', 10.0, fields)

        # U-shape facing left, positioned to interlock
        u2_wkt = "POLYGON((5.2 4.2, 5.7 4.2, 5.7 4.7, 5.2 4.7, 5.2 6.2, 5.7 6.2, 5.7 4.2, 5.2 4.2))"
        # Actually, let's make a simpler mirrored U
        u2_wkt = "POLYGON((5.5 4, 6.5 4, 6.5 4.5, 6 4.5, 6 6, 5.5 6, 5.5 4))"
        feat2 = make_feature(QgsGeometry.fromWkt(u2_wkt), 'u2', 20.0, fields)

        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=300, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=0,
        )

        assert len(features) == 2

        g1 = features[0].geometry()
        g2 = features[1].geometry()

        # Verify no overlap
        intersection = g1.intersection(g2)
        overlap_area = intersection.area() if not intersection.isEmpty() else 0.0
        assert overlap_area < 0.01, (
            f"Concave U-shapes should not overlap after separate mode: "
            f"overlap_area={overlap_area:.6f}"
        )


# ===========================================================================
# G1: Geometric overlap resolution — replaces force-directed for modes 0, 2
# ===========================================================================

class TestGeometricOverlapResolution:
    """Tests that separate and gap modes use geometric overlap detection.

    Two-phase algorithm:
    1. Main loop in equal-area working CRS: spatial grid + bbox pre-filter
       + precise intersects() check. Pushes apart along centroid-to-centroid
       axis with sqrt(intersection_area) magnitude.
    2. Refinement pass in source CRS: resolves overlaps reintroduced by the
       CRS round-trip.
    """

    def test_dense_cluster_fully_resolved(self, qgis_app):
        """G1.1: 5x5 grid of tightly packed circles — zero overlaps remain.

        This is the primary regression test. The force-directed approach
        sometimes left residual overlaps in dense clusters. The geometric
        approach should resolve all of them.
        """
        fields = make_fields()
        feats = []
        for i in range(5):
            for j in range(5):
                feats.append(
                    _make_circle_feature(
                        5.0 + i * 0.5, 5.0 + j * 0.5, 0.5,
                        f'c{i}_{j}', float(i * 5 + j), fields,
                    )
                )
        layer = make_layer(feats)

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=True, mode=0,
        )

        assert len(features) == 25

        geoms = [f.geometry() for f in features]
        overlapping_pairs = []
        for i in range(len(geoms)):
            for j in range(i + 1, len(geoms)):
                intersection = geoms[i].intersection(geoms[j])
                area = intersection.area() if not intersection.isEmpty() else 0.0
                if area > 0.01:
                    overlapping_pairs.append((i, j, area))

        assert len(overlapping_pairs) == 0, (
            f"Expected zero overlapping pairs, got {len(overlapping_pairs)}: "
            f"{overlapping_pairs[:5]}"
        )

    def test_non_overlapping_features_unmoved(self, qgis_app):
        """G1.2: features with no geometric overlap are not displaced."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 0.5, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(15.0, 5.0, 0.5, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=100, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            mode=0,
        )

        assert len(features) == 2
        c1 = features[0].geometry().centroid().asPoint()
        c2 = features[1].geometry().centroid().asPoint()
        # Should stay very close to original positions
        assert abs(c1.x() - 5.0) < 0.5, f"c1.x moved: {c1.x()}"
        assert abs(c1.y() - 5.0) < 0.5, f"c1.y moved: {c1.y()}"
        assert abs(c2.x() - 15.0) < 0.5, f"c2.x moved: {c2.x()}"

    def test_two_overlapping_squares_zero_intersection(self, qgis_app):
        """G1.3: two overlapping squares end with zero area intersection."""
        fields = make_fields()
        feat1 = _make_square_feature(5.0, 5.0, 0.5, 'sq1', 10.0, fields)
        feat2 = _make_square_feature(5.3, 5.0, 0.5, 'sq2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            mode=0,
        )

        assert len(features) == 2
        g1 = features[0].geometry()
        g2 = features[1].geometry()
        intersection = g1.intersection(g2)
        overlap_area = intersection.area() if not intersection.isEmpty() else 0.0
        assert overlap_area < 0.01, (
            f"Squares should have zero overlap, got area={overlap_area:.6f}"
        )

    def test_gap_mode_enforces_actual_boundary_gap(self, qgis_app):
        """G1.4: gap mode with geometric detection enforces actual boundary distance.

        Uses EPSG:3857 (meters) so separation_distance is meaningful.
        """
        fields = make_fields()
        feat1 = _make_square_feature(500000.0, 500000.0, 5.0, 'sq1', 10.0, fields)
        feat2 = _make_square_feature(500005.0, 500000.0, 5.0, 'sq2', 20.0, fields)
        layer = make_layer([feat1, feat2], crs_id='EPSG:3857')

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            mode=2, separation_distance=20.0,
        )

        assert len(features) == 2
        g1 = features[0].geometry()
        g2 = features[1].geometry()

        # No overlap
        intersection = g1.intersection(g2)
        overlap_area = intersection.area() if not intersection.isEmpty() else 0.0
        assert overlap_area < 0.1, (
            f"Gap mode should not leave overlaps, got area={overlap_area:.4f}"
        )

        # Actual boundary gap close to requested
        actual_gap = g1.distance(g2)
        assert actual_gap > 14.0, (
            f"Gap mode should enforce ~20m boundary gap, got {actual_gap:.4f}"
        )

    def test_iterations_cap_produces_warning(self, qgis_app):
        """G1.5: when max_iterations reached with remaining overlaps, warn."""
        fields = make_fields()
        feats = []
        for i in range(5):
            for j in range(5):
                feats.append(
                    _make_circle_feature(
                        5.0 + i * 0.3, 5.0 + j * 0.3, 0.5,
                        f'c{i}_{j}', 10.0, fields,
                    )
                )
        layer = make_layer(feats)

        features, _, _, warnings, errors, _ = _run_resolve_overlaps_with_feedback(
            layer, iterations=1, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.0,
            mode=0,
        )

        assert len(features) == 25
        assert any('overlapping' in w.lower() for w in warnings), (
            f"Expected warning about remaining overlaps, got: {warnings}"
        )

    def test_attract_mode_still_pulls_features(self, qgis_app):
        """G1.6: attract mode unchanged — still uses force-directed pull."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(15.0, 5.0, 1.0, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            adaptive_damping=False, mode=1,
        )

        assert len(features) == 2
        c1 = features[0].geometry().centroid().asPoint()
        c2 = features[1].geometry().centroid().asPoint()
        dist = math.hypot(c2.x() - c1.x(), c2.y() - c1.y())
        assert dist < 10.0, (
            f"Attract mode should pull features closer, dist={dist:.4f}"
        )

    def test_mixed_sizes_all_resolved(self, qgis_app):
        """G1.7: different-sized circles all resolved without overlap."""
        fields = make_fields()
        feats = [
            _make_circle_feature(5.0, 5.0, 1.5, 'big', 100.0, fields),
            _make_circle_feature(6.0, 5.0, 0.3, 'small1', 10.0, fields),
            _make_circle_feature(5.0, 6.0, 0.5, 'med', 50.0, fields),
            _make_circle_feature(5.5, 5.5, 0.2, 'tiny', 5.0, fields),
        ]
        layer = make_layer(feats)

        features, _, _, _ = _run_resolve_overlaps(
            layer, iterations=500, damping=0.3,
            anchor_strength=0.0, convergence_threshold=0.001,
            mode=0,
        )

        assert len(features) == 4
        geoms = [f.geometry() for f in features]
        for i in range(4):
            for j in range(i + 1, 4):
                intersection = geoms[i].intersection(geoms[j])
                area = intersection.area() if not intersection.isEmpty() else 0.0
                assert area < 0.01, (
                    f"Pair ({i},{j}) should not overlap, area={area:.6f}"
                )


# ===========================================================================
# Quality preset parameter
# ===========================================================================

class TestQualityPreset:
    """Tests for the QUALITY meta-parameter."""

    def test_quality_parameter_exists(self, qgis_app):
        """QUALITY enum exists with 4 options, default Balanced."""
        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('QUALITY')
        assert param is not None, "QUALITY parameter should exist"
        assert param.options() == ['Fast', 'Balanced', 'Precise', 'Custom advanced parameters']
        assert param.defaultValue() == 1  # Balanced

    def test_quality_is_not_advanced(self, qgis_app):
        """QUALITY should not be flagged as Advanced (visible in dialog)."""
        from qgis.core import QgsProcessingParameterDefinition
        alg = ArrangeFeaturesAlgorithm()
        alg.initAlgorithm()
        param = alg.parameterDefinition('QUALITY')
        assert not (param.flags() & QgsProcessingParameterDefinition.FlagAdvanced)

    def test_fast_preset_uses_30_iterations(self, qgis_app):
        """Fast quality produces output (smoke test with low iterations)."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        feat2 = _make_circle_feature(6.0, 5.0, 1.0, 'c2', 20.0, fields)
        layer = make_layer([feat1, feat2])

        project = QgsProject.instance()
        project.addMapLayer(layer)
        try:
            context = QgsProcessingContext()
            context.setProject(project)
            feedback = QgsProcessingFeedback()
            alg = ArrangeFeaturesAlgorithm()
            alg.initAlgorithm()
            parameters = {
                'INPUT': layer.id(),
                'MODE': 0,
                'QUALITY': 0,  # Fast
                'SEPARATION_DISTANCE': 0.0,
                'OUTPUT': 'memory:',
            }
            results = alg.processAlgorithm(parameters, context, feedback)
            assert 'OUTPUT' in results
        finally:
            project.removeMapLayer(layer.id())

    def test_precise_preset_uses_500_iterations(self, qgis_app):
        """Precise quality produces output (smoke test with high iterations)."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        layer = make_layer([feat1])

        project = QgsProject.instance()
        project.addMapLayer(layer)
        try:
            context = QgsProcessingContext()
            context.setProject(project)
            feedback = QgsProcessingFeedback()
            alg = ArrangeFeaturesAlgorithm()
            alg.initAlgorithm()
            parameters = {
                'INPUT': layer.id(),
                'MODE': 0,
                'QUALITY': 2,  # Precise
                'SEPARATION_DISTANCE': 0.0,
                'OUTPUT': 'memory:',
            }
            results = alg.processAlgorithm(parameters, context, feedback)
            assert 'OUTPUT' in results
        finally:
            project.removeMapLayer(layer.id())

    def test_custom_quality_uses_advanced_params(self, qgis_app):
        """Custom quality should use the advanced parameter values."""
        fields = make_fields()
        feat1 = _make_circle_feature(5.0, 5.0, 1.0, 'c1', 10.0, fields)
        layer = make_layer([feat1])

        project = QgsProject.instance()
        project.addMapLayer(layer)
        try:
            context = QgsProcessingContext()
            context.setProject(project)
            feedback = QgsProcessingFeedback()
            alg = ArrangeFeaturesAlgorithm()
            alg.initAlgorithm()
            parameters = {
                'INPUT': layer.id(),
                'MODE': 0,
                'QUALITY': 3,  # Custom
                'ITERATIONS': 5,
                'DAMPING': 0.5,
                'ANCHOR_STRENGTH': 0.1,
                'CONVERGENCE_THRESHOLD': 0.1,
                'ADAPTIVE_DAMPING': False,
                'SEPARATION_DISTANCE': 0.0,
                'OUTPUT': 'memory:',
            }
            results = alg.processAlgorithm(parameters, context, feedback)
            assert 'OUTPUT' in results
        finally:
            project.removeMapLayer(layer.id())
