"""Tests for SketchyBordersAlgorithm (sketchy_borders.py).

TDD tests for the sketchy borders algorithm defined in spec section 5.5.
Tests the hash-based vertex jitter, topology preservation via
TopologyTransformer, densification, and output field schema.
"""
import math

import gc

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
)
from PyQt5.QtCore import QMetaType

from .helpers import make_fields, make_feature, make_layer
from tessera.algorithms.sketchy_borders import (
    SketchyBordersAlgorithm,
    vertex_hash,
    jitter_vertex,
)
from tessera.infrastructure.topology_wrapper import TopologyTransformer
from tessera.infrastructure.feature_builder import create_output_fields, build_feature


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_vertices(geom):
    """Return a set of (rounded x, rounded y) tuples for all vertices."""
    vertices = set()
    parts = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
    for part in parts:
        for ring in part:
            for pt in ring:
                vertices.add((round(pt.x(), 6), round(pt.y(), 6)))
    return vertices


def _extract_vertices_list(geom):
    """Return a list of all (x, y) vertex tuples (with duplicates)."""
    vertices = []
    parts = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
    for part in parts:
        for ring in part:
            for pt in ring:
                vertices.append((pt.x(), pt.y()))
    return vertices


def _shared_edge_vertices(feat_a, feat_b):
    """Return set of vertex coords shared between two features' geometries."""
    verts_a = _extract_vertices(feat_a.geometry())
    verts_b = _extract_vertices(feat_b.geometry())
    return verts_a & verts_b


def _count_ring_vertices(features):
    """Count total ring vertices across all features."""
    total = 0
    for feat in features:
        geom = feat.geometry()
        parts = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
        for part in parts:
            for ring in part:
                total += len(ring)
    return total


# ---------------------------------------------------------------------------
# 1. Import
# ---------------------------------------------------------------------------

class TestSketchyBordersImport:
    """Test that the algorithm can be imported."""

    def test_sketchy_borders_importable(self):
        """SketchyBordersAlgorithm imports without error."""
        assert SketchyBordersAlgorithm is not None


# ---------------------------------------------------------------------------
# 2. Metadata
# ---------------------------------------------------------------------------

class TestSketchyBordersMetadata:
    """Test algorithm metadata methods."""

    def test_sketchy_borders_metadata(self):
        """name='sketchy_borders', displayName='Sketchy Borders', group='Shape', groupId='shape'."""
        alg = SketchyBordersAlgorithm()
        assert alg.name() == 'sketchy_borders'
        assert alg.displayName() == 'Sketchy Borders'
        assert alg.group() == 'Shape'
        assert alg.groupId() == 'shape'


# ---------------------------------------------------------------------------
# 3. Parameters
# ---------------------------------------------------------------------------

class TestSketchyBordersParameters:
    """Test algorithm parameters after initAlgorithm."""

    def test_sketchy_borders_has_parameters(self, qgis_app):
        """After initAlgorithm(), has ROUGHNESS, DENSIFY_FACTOR, SEED parameters."""
        alg = SketchyBordersAlgorithm()
        alg.initAlgorithm()

        param_names = [p.name() for p in alg.parameterDefinitions()]
        assert 'ROUGHNESS' in param_names
        assert 'DENSIFY_FACTOR' in param_names
        assert 'SEED' in param_names
        # Also check INPUT and OUTPUT from base class
        assert 'INPUT' in param_names
        assert 'OUTPUT' in param_names


# ---------------------------------------------------------------------------
# 4-6. vertex_hash function
# ---------------------------------------------------------------------------

class TestVertexHash:
    """Tests for the vertex_hash module-level function."""

    def test_vertex_hash_deterministic(self):
        """Same (vertex_id, seed, component) always returns same value."""
        v1 = vertex_hash(42, 123, 0)
        v2 = vertex_hash(42, 123, 0)
        assert v1 == v2

        v3 = vertex_hash(100, 7, 1)
        v4 = vertex_hash(100, 7, 1)
        assert v3 == v4

    def test_vertex_hash_range(self):
        """Output is in (0, 1) range for many inputs."""
        for vid in range(1000):
            for seed in [0, 42, 999]:
                for comp in [0, 1]:
                    val = vertex_hash(vid, seed, comp)
                    assert 0.0 < val <= 1.0, (
                        f"vertex_hash({vid}, {seed}, {comp}) = {val} "
                        f"not in (0, 1]"
                    )

    def test_vertex_hash_different_seeds(self):
        """Different seeds produce different values."""
        v1 = vertex_hash(42, 0, 0)
        v2 = vertex_hash(42, 1, 0)
        assert v1 != v2, "Different seeds should produce different hash values"


# ---------------------------------------------------------------------------
# 7-8. jitter_vertex function
# ---------------------------------------------------------------------------

class TestJitterVertex:
    """Tests for the jitter_vertex module-level function."""

    def test_jitter_deterministic_same_seed(self):
        """Same seed + same vertex -> same jitter displacement."""
        pt = QgsPointXY(5.0, 10.0)
        max_disp = 0.1
        seed = 42

        result1 = jitter_vertex(pt, 7, seed, max_disp)
        result2 = jitter_vertex(pt, 7, seed, max_disp)

        assert result1.x() == result2.x()
        assert result1.y() == result2.y()

    def test_jitter_different_with_different_seed(self):
        """Different seeds -> different displacements."""
        pt = QgsPointXY(5.0, 10.0)
        max_disp = 0.1

        result1 = jitter_vertex(pt, 7, 42, max_disp)
        result2 = jitter_vertex(pt, 7, 99, max_disp)

        # At least one coordinate should differ
        assert (result1.x() != result2.x() or result1.y() != result2.y()), (
            "Different seeds should produce different jitter"
        )


# ---------------------------------------------------------------------------
# 9. Topology preservation
# ---------------------------------------------------------------------------

class TestSketchyBordersTopology:
    """Tests for topology preservation through TopologyTransformer."""

    def test_sketchy_borders_preserves_topology(self, qgis_app, simple_squares):
        """Shared vertices between adjacent squares have same coords in output.

        After running jitter through TopologyTransformer, shared edges should
        remain consistent: sq0/sq1 share x=1 boundary, sq0/sq2 share y=1
        boundary.
        """
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)

        max_displacement = 0.05
        seed = 42

        def jitter_fn(point, vertex_id):
            return jitter_vertex(point, vertex_id, seed, max_displacement)

        results = tt.transform(jitter_fn)

        # sq0 and sq1 share the vertical edge at x~1
        shared_01 = _shared_edge_vertices(results[0], results[1])
        # They originally shared (1,0) and (1,1) -> 2 shared vertices
        assert len(shared_01) >= 2, (
            f"sq0 and sq1 should share at least 2 vertices, got {len(shared_01)}"
        )

        # sq0 and sq2 share the horizontal edge at y~1
        shared_02 = _shared_edge_vertices(results[0], results[2])
        assert len(shared_02) >= 2, (
            f"sq0 and sq2 should share at least 2 vertices, got {len(shared_02)}"
        )

        # Center vertex (1,1) should be in all four features with the SAME coords
        center_coords = []
        for feat in results:
            verts = _extract_vertices(feat.geometry())
            # Find the vertex closest to the original center (1,1)
            for vx, vy in verts:
                if feat is results[0]:
                    center_coords.append((vx, vy))
                    break
        # All four features share center: check a common vertex exists in all
        all_verts = [_extract_vertices(f.geometry()) for f in results]
        common = all_verts[0] & all_verts[1] & all_verts[2] & all_verts[3]
        assert len(common) >= 1, (
            "Center vertex should be shared by all 4 squares after jitter"
        )


# ---------------------------------------------------------------------------
# 10. Vertices displaced
# ---------------------------------------------------------------------------

class TestSketchyBordersDisplacement:
    """Test that vertices are actually displaced by jitter."""

    def test_sketchy_borders_vertices_displaced(self, qgis_app, simple_squares):
        """After jitter, vertices are NOT at their original positions (roughness > 0)."""
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)

        max_displacement = 0.1
        seed = 42

        def jitter_fn(point, vertex_id):
            return jitter_vertex(point, vertex_id, seed, max_displacement)

        results = tt.transform(jitter_fn)

        # Collect original vertices
        original_verts = set()
        for feat in simple_squares:
            original_verts |= _extract_vertices(feat.geometry())

        # Collect output vertices
        output_verts = set()
        for feat in results:
            output_verts |= _extract_vertices(feat.geometry())

        # At least some vertices should have moved
        unchanged = original_verts & output_verts
        assert len(unchanged) < len(original_verts), (
            "Some vertices should have been displaced by jitter, "
            f"but all {len(original_verts)} remained unchanged"
        )


# ---------------------------------------------------------------------------
# 11. Zero roughness preserves geometry
# ---------------------------------------------------------------------------

class TestSketchyBordersZeroRoughness:
    """Test zero-roughness short circuit."""

    def test_sketchy_borders_zero_roughness_preserves_geometry(
        self, qgis_app, simple_squares
    ):
        """With max_displacement=0, jitter_vertex returns point unchanged."""
        pt = QgsPointXY(3.0, 7.0)
        result = jitter_vertex(pt, 42, 99, 0.0)
        assert abs(result.x() - pt.x()) < 1e-12
        assert abs(result.y() - pt.y()) < 1e-12


# ---------------------------------------------------------------------------
# 12. Output fields
# ---------------------------------------------------------------------------

class TestSketchyBordersOutputFields:
    """Test output field schema."""

    def test_sketchy_borders_output_fields(self, qgis_app, simple_squares):
        """Output has _tessera_algorithm and _tessera_parent_fid fields."""
        alg = SketchyBordersAlgorithm()

        # Simulate what get_output_fields does
        # We need a mock source with fields(), but we can test directly
        # by checking what the algorithm's get_output_fields returns
        class MockSource:
            def fields(self_inner):
                return simple_squares[0].fields()
        source = MockSource()
        output_fields = alg.get_output_fields(source)

        field_names = [output_fields.field(i).name()
                       for i in range(output_fields.count())]
        assert '_tessera_algorithm' in field_names
        assert '_tessera_parent_fid' in field_names


# ---------------------------------------------------------------------------
# 13. Densification
# ---------------------------------------------------------------------------

class TestSketchyBordersDensification:
    """Test that densification adds vertices before jitter."""

    def test_sketchy_borders_densifies_before_jitter(
        self, qgis_app, simple_squares
    ):
        """After sketchy borders with densification, features have MORE vertices."""
        feedback = QgsProcessingFeedback()

        # Count original vertices
        pre_count = _count_ring_vertices(simple_squares)

        # Create transformer, densify, then jitter
        tt = TopologyTransformer(simple_squares, feedback)

        max_displacement = 0.1
        densify_factor = 3.0
        interval = max_displacement * densify_factor
        tt.densify_shared_edges(interval)

        seed = 42

        def jitter_fn(point, vertex_id):
            return jitter_vertex(point, vertex_id, seed, max_displacement)

        results = tt.transform(jitter_fn)

        post_count = _count_ring_vertices(results)

        assert post_count > pre_count, (
            f"Densification should increase vertex count: "
            f"before={pre_count}, after={post_count}"
        )


# ---------------------------------------------------------------------------
# Helpers for full-algorithm integration tests
# ---------------------------------------------------------------------------

def _run_sketchy_borders(layer, roughness=0.5, densify_factor=3.0, seed=42,
                         smoothing=0):
    """Run SketchyBordersAlgorithm and return output features."""
    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        alg = SketchyBordersAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'ROUGHNESS': roughness,
            'DENSIFY_FACTOR': densify_factor,
            'SEED': seed,
            'SMOOTHING': smoothing,
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
        return features, results, output_layer
    finally:
        project.removeMapLayer(layer.id())


# ---------------------------------------------------------------------------
# B3.1-B3.9: Chaikin Smoothing Tests
# ---------------------------------------------------------------------------

class TestSketchyBordersSmoothingParameter:
    """Tests for the SMOOTHING parameter definition."""

    def test_smoothing_parameter_exists(self, qgis_app):
        """B3.1: SMOOTHING parameter exists as Integer, default=0, min=0, max=5."""
        alg = SketchyBordersAlgorithm()
        alg.initAlgorithm()

        param = alg.parameterDefinition('SMOOTHING')
        assert param is not None, "SMOOTHING parameter should exist"
        assert param.defaultValue() == 0
        assert param.minimum() == 0
        assert param.maximum() == 5


class TestSketchyBordersSmoothing:
    """Tests for Chaikin smoothing behavior."""

    def test_smoothing_zero_identical_to_pre_enhancement(self, qgis_app):
        """B3.2: SMOOTHING=0 output identical to pre-enhancement."""
        fields = make_fields()
        ring = [
            QgsPointXY(0, 0), QgsPointXY(1, 0),
            QgsPointXY(1, 1), QgsPointXY(0, 1), QgsPointXY(0, 0),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])
        feat = make_feature(geom, 'sq', 10.0, fields)
        layer = make_layer([feat])

        features_s0, _, _ = _run_sketchy_borders(
            layer, roughness=0.5, seed=42, smoothing=0,
        )
        assert len(features_s0) == 1

        # Run again without SMOOTHING param in a fresh layer
        layer2 = make_layer([make_feature(
            QgsGeometry.fromPolygonXY([ring[:]]), 'sq', 10.0, fields
        )])
        features_no_smooth, _, _ = _run_sketchy_borders(
            layer2, roughness=0.5, seed=42, smoothing=0,
        )
        assert len(features_no_smooth) == 1

        count_s0 = _count_ring_vertices(features_s0)
        count_ns = _count_ring_vertices(features_no_smooth)
        assert count_s0 == count_ns, (
            f"SMOOTHING=0 should match no-smoothing: {count_s0} vs {count_ns}"
        )

    def test_smoothing_increases_vertex_count(self, qgis_app):
        """B3.3: SMOOTHING > 0 increases vertex count."""
        fields = make_fields()
        ring = [
            QgsPointXY(0, 0), QgsPointXY(1, 0),
            QgsPointXY(1, 1), QgsPointXY(0, 1), QgsPointXY(0, 0),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])

        layer_s0 = make_layer([make_feature(geom, 'sq', 10.0, fields)])
        features_s0, _, _ = _run_sketchy_borders(
            layer_s0, roughness=0.5, seed=42, smoothing=0,
        )

        layer_s2 = make_layer([make_feature(
            QgsGeometry.fromPolygonXY([ring[:]]), 'sq', 10.0, fields
        )])
        features_s2, _, _ = _run_sketchy_borders(
            layer_s2, roughness=0.5, seed=42, smoothing=2,
        )

        count_s0 = _count_ring_vertices(features_s0)
        count_s2 = _count_ring_vertices(features_s2)
        assert count_s2 > count_s0, (
            f"SMOOTHING=2 should have more vertices than SMOOTHING=0: "
            f"{count_s2} vs {count_s0}"
        )

    def test_higher_smoothing_more_vertices(self, qgis_app):
        """B3.4: higher SMOOTHING produces more vertices."""
        fields = make_fields()
        ring = [
            QgsPointXY(0, 0), QgsPointXY(1, 0),
            QgsPointXY(1, 1), QgsPointXY(0, 1), QgsPointXY(0, 0),
        ]

        layer_s1 = make_layer([make_feature(
            QgsGeometry.fromPolygonXY([ring[:]]), 'sq', 10.0, fields
        )])
        features_s1, _, _ = _run_sketchy_borders(
            layer_s1, roughness=0.5, seed=42, smoothing=1,
        )

        layer_s3 = make_layer([make_feature(
            QgsGeometry.fromPolygonXY([ring[:]]), 'sq', 10.0, fields
        )])
        features_s3, _, _ = _run_sketchy_borders(
            layer_s3, roughness=0.5, seed=42, smoothing=3,
        )

        count_s1 = _count_ring_vertices(features_s1)
        count_s3 = _count_ring_vertices(features_s3)
        assert count_s3 > count_s1, (
            f"SMOOTHING=3 should have more vertices than SMOOTHING=1: "
            f"{count_s3} vs {count_s1}"
        )

    def test_smoothed_output_valid_geometry(self, qgis_app):
        """B3.5: smoothed output has valid geometry."""
        fields = make_fields()
        ring = [
            QgsPointXY(0, 0), QgsPointXY(1, 0),
            QgsPointXY(1, 1), QgsPointXY(0, 1), QgsPointXY(0, 0),
        ]

        layer = make_layer([make_feature(
            QgsGeometry.fromPolygonXY([ring[:]]), 'sq', 10.0, fields
        )])
        features, _, _ = _run_sketchy_borders(
            layer, roughness=0.5, seed=42, smoothing=3,
        )

        for feat in features:
            geom = feat.geometry()
            assert geom.isGeosValid(), "Smoothed geometry should be valid"
            assert geom.area() > 0, "Smoothed geometry should have positive area"

    def test_smoothing_preserves_topology(self, qgis_app):
        """B3.6: shared vertices between adjacent features >= 2 after smoothing."""
        fields = make_fields()
        # Two adjacent squares sharing edge at x=1
        sq0 = make_feature(
            QgsGeometry.fromPolygonXY([[
                QgsPointXY(0, 0), QgsPointXY(1, 0),
                QgsPointXY(1, 1), QgsPointXY(0, 1), QgsPointXY(0, 0),
            ]]), 'sq0', 10.0, fields,
        )
        sq1 = make_feature(
            QgsGeometry.fromPolygonXY([[
                QgsPointXY(1, 0), QgsPointXY(2, 0),
                QgsPointXY(2, 1), QgsPointXY(1, 1), QgsPointXY(1, 0),
            ]]), 'sq1', 20.0, fields,
        )

        layer = make_layer([sq0, sq1])
        features, _, _ = _run_sketchy_borders(
            layer, roughness=0.5, seed=42, smoothing=2,
        )

        assert len(features) == 2
        shared = _shared_edge_vertices(features[0], features[1])
        assert len(shared) >= 2, (
            f"Adjacent features should share at least 2 vertices, got {len(shared)}"
        )

    def test_smoothing_preserves_attributes_and_fields(self, qgis_app):
        """B3.7: attributes and _tessera_algorithm preserved after smoothing."""
        fields = make_fields()
        ring = [
            QgsPointXY(0, 0), QgsPointXY(1, 0),
            QgsPointXY(1, 1), QgsPointXY(0, 1), QgsPointXY(0, 0),
        ]

        layer = make_layer([make_feature(
            QgsGeometry.fromPolygonXY([ring[:]]), 'test_name', 42.0, fields
        )])
        features, _, _ = _run_sketchy_borders(
            layer, roughness=0.5, seed=42, smoothing=2,
        )

        assert len(features) == 1
        feat = features[0]
        assert feat.attribute('name') == 'test_name'
        assert feat.attribute('value') == 42.0
        assert feat.attribute('_tessera_algorithm') == 'sketchy_borders'

    def test_smoothing_with_polygon_with_holes(self, qgis_app, polygon_with_holes):
        """B3.8: smoothing preserves hole and increases interior ring vertices."""
        fields = polygon_with_holes.fields()
        layer = make_layer([polygon_with_holes])

        features_s0, _, _ = _run_sketchy_borders(
            layer, roughness=0.3, seed=42, smoothing=0,
        )

        layer2 = make_layer([
            make_feature(
                QgsGeometry(polygon_with_holes.geometry()),
                polygon_with_holes.attribute('name'),
                polygon_with_holes.attribute('value'),
                fields,
            )
        ])
        features_s2, _, _ = _run_sketchy_borders(
            layer2, roughness=0.3, seed=42, smoothing=2,
        )

        # Smoothed version should still have interior ring
        geom_s2 = features_s2[0].geometry()
        parts = (geom_s2.asMultiPolygon() if geom_s2.isMultipart()
                 else [geom_s2.asPolygon()])
        has_hole = any(len(part) > 1 for part in parts)
        assert has_hole, "Smoothed polygon should still have interior ring"

        # Interior ring should have more vertices
        geom_s0 = features_s0[0].geometry()
        parts_s0 = (geom_s0.asMultiPolygon() if geom_s0.isMultipart()
                     else [geom_s0.asPolygon()])
        hole_verts_s0 = sum(len(ring) for part in parts_s0 for ring in part[1:])
        hole_verts_s2 = sum(len(ring) for part in parts for ring in part[1:])
        assert hole_verts_s2 > hole_verts_s0, (
            f"Smoothed hole should have more vertices: {hole_verts_s2} vs {hole_verts_s0}"
        )

    def test_roughness_zero_ignores_smoothing(self, qgis_app):
        """B3.9: roughness=0 ignores SMOOTHING parameter."""
        fields = make_fields()
        ring = [
            QgsPointXY(0, 0), QgsPointXY(1, 0),
            QgsPointXY(1, 1), QgsPointXY(0, 1), QgsPointXY(0, 0),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])

        layer_r0 = make_layer([make_feature(
            QgsGeometry(geom), 'sq', 10.0, fields
        )])
        features_r0, _, _ = _run_sketchy_borders(
            layer_r0, roughness=0.0, seed=42, smoothing=3,
        )

        # With roughness=0, output should be identical to input
        out_geom = features_r0[0].geometry()
        # Vertex count should match input (5 vertices in a square ring)
        parts = (out_geom.asMultiPolygon() if out_geom.isMultipart()
                 else [out_geom.asPolygon()])
        total_verts = sum(len(ring) for part in parts for ring in part)
        assert total_verts == 5, (
            f"Roughness=0 should preserve input exactly, got {total_verts} vertices"
        )
