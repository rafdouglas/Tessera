"""Tests for TopologyTransformer (topology_wrapper.py).

TDD tests for the topology-preserving vertex transformer defined in spec
section 4.2.  The implementation is currently a stub; all tests should fail
with NotImplementedError until the real code lands.

Test fixture ``simple_squares`` provides four adjacent unit squares in a 2x2
grid -- perfect for shared-vertex / shared-edge assertions.
"""
import pytest
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingFeedback,
)
from PyQt5.QtCore import QMetaType

from tessera.infrastructure.topology_wrapper import TopologyTransformer

from .helpers import make_fields, make_feature


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_vertices(geom):
    """Return a set of (rounded x, rounded y) tuples for all vertices."""
    vertices = set()
    for part in geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]:
        for ring in part:
            for pt in ring:
                vertices.add((round(pt.x(), 6), round(pt.y(), 6)))
    return vertices


def _shared_edge_vertices(feat_a, feat_b):
    """Return set of vertex coords shared between two features' geometries."""
    verts_a = _extract_vertices(feat_a.geometry())
    verts_b = _extract_vertices(feat_b.geometry())
    return verts_a & verts_b


def _identity_fn(point, vertex_id):
    """Identity transform -- returns point unchanged."""
    return point


def _offset_fn(point, vertex_id):
    """Shift every vertex by (+0.5, +0.5)."""
    return QgsPointXY(point.x() + 0.5, point.y() + 0.5)


def _collapse_fn(point, vertex_id):
    """Collapse all vertices to the origin -- produces degenerate geometry."""
    return QgsPointXY(0.0, 0.0)


# ---------------------------------------------------------------------------
# Constructor / Vertex Index
# ---------------------------------------------------------------------------

class TestConstructorAndVertexIndex:
    """Tests for TopologyTransformer construction and vertex indexing."""

    def test_constructor_builds_vertex_index(self, qgis_app, simple_squares):
        """T4.1: Constructor accepts features + feedback without raising."""
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        assert tt is not None

    def test_shared_vertices_detected(self, qgis_app, simple_squares):
        """T4.2: The four squares share internal vertices; shared count > 0.

        In a 2x2 grid the internal vertex (1,1) is shared by all four squares,
        and edge midpoints like (1,0), (1,1), (0,1), (2,1), (1,2) are shared
        by two squares each.
        """
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        # The transformer must expose something about shared vertices.
        # We test indirectly: transform with a counting function that records
        # which vertex_ids are called.  Shared vertices appear once in the
        # transform call but in multiple features.
        #
        # Total unique coords across 4 squares = 9 (3x3 grid).
        # Each square has 4 unique corners.  A non-topology-aware approach
        # would call 4*4 = 16.  If shared detection works, exactly 9 calls.
        call_log = {}

        def counting_fn(point, vertex_id):
            call_log[vertex_id] = (point.x(), point.y())
            return point

        tt.transform(counting_fn)
        # 9 unique grid points in the 2x2 arrangement
        assert len(call_log) == 9

    def test_private_vertices_remain_private(self, qgis_app, simple_squares):
        """T4.3: Corner vertices (0,0), (2,0), (0,2), (2,2) belong to one square only.

        After transform, these should still appear in only one output feature.
        """
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        results = tt.transform(_identity_fn)

        # The four purely-private corners
        private_corners = {(0, 0), (2, 0), (0, 2), (2, 2)}
        for corner in private_corners:
            count = 0
            for feat in results:
                verts = _extract_vertices(feat.geometry())
                if corner in verts:
                    count += 1
            assert count == 1, (
                f"Private corner {corner} found in {count} features, expected 1"
            )


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

class TestTransform:
    """Tests for the transform() method."""

    def test_transform_returns_same_number_of_features(
        self, qgis_app, simple_squares
    ):
        """T4.4: 4 features in -> 4 features out."""
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        results = tt.transform(_identity_fn)
        assert len(results) == len(simple_squares)

    def test_transform_preserves_attributes(self, qgis_app, simple_squares):
        """T4.5: name and value attributes are unchanged after transform."""
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        results = tt.transform(_offset_fn)

        for orig, out in zip(simple_squares, results):
            assert out.attribute('name') == orig.attribute('name')
            assert out.attribute('value') == orig.attribute('value')

    def test_transform_identity_preserves_geometry(
        self, qgis_app, simple_squares
    ):
        """T4.6: Identity transform produces geometries equal to originals."""
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        results = tt.transform(_identity_fn)

        for orig, out in zip(simple_squares, results):
            assert out.geometry().equals(orig.geometry()), (
                f"Feature '{orig.attribute('name')}' geometry changed "
                f"under identity transform"
            )

    def test_transform_shared_vertices_identical(
        self, qgis_app, simple_squares
    ):
        """T4.7: After offset transform, adjacent polygons still share exact boundary.

        sq0 and sq1 share the edge from (1,0) to (1,1).  After offsetting
        by (+0.5, +0.5), the shared edge should become (1.5, 0.5)-(1.5, 1.5)
        in BOTH output features.
        """
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        results = tt.transform(_offset_fn)

        # sq0 and sq1 share a vertical edge
        shared_01 = _shared_edge_vertices(results[0], results[1])
        # After offset, the shared vertices (1,0) and (1,1) become
        # (1.5, 0.5) and (1.5, 1.5)
        assert (1.5, 0.5) in shared_01, (
            "Shared vertex (1,0) -> (1.5, 0.5) not found in both sq0/sq1"
        )
        assert (1.5, 1.5) in shared_01, (
            "Shared vertex (1,1) -> (1.5, 1.5) not found in both sq0/sq1"
        )

        # sq0 and sq2 share a horizontal edge
        shared_02 = _shared_edge_vertices(results[0], results[2])
        assert (0.5, 1.5) in shared_02
        assert (1.5, 1.5) in shared_02

        # Center vertex (1,1) -> (1.5, 1.5) should be in all four
        for feat in results:
            verts = _extract_vertices(feat.geometry())
            assert (1.5, 1.5) in verts, (
                f"Center vertex (1.5, 1.5) missing from {feat.attribute('name')}"
            )

    def test_transform_calls_vertex_fn_once_per_unique_vertex(
        self, qgis_app, simple_squares
    ):
        """T4.8: vertex_fn called exactly once per unique vertex.

        The 2x2 grid has 9 unique vertex positions (3x3 grid of points).
        """
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        call_count = [0]

        def counting_fn(point, vertex_id):
            call_count[0] += 1
            return point

        tt.transform(counting_fn)
        assert call_count[0] == 9, (
            f"Expected 9 unique vertex calls, got {call_count[0]}"
        )

    def test_transform_vertex_fn_receives_point_and_id(
        self, qgis_app, simple_squares
    ):
        """T4.9: vertex_fn receives (QgsPointXY, int) arguments."""
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        arg_types = []

        def inspecting_fn(point, vertex_id):
            arg_types.append((type(point), type(vertex_id)))
            return point

        tt.transform(inspecting_fn)
        assert len(arg_types) > 0, "vertex_fn was never called"
        for pt_type, id_type in arg_types:
            assert pt_type is QgsPointXY, (
                f"First arg should be QgsPointXY, got {pt_type}"
            )
            assert id_type is int, (
                f"Second arg should be int, got {id_type}"
            )


# ---------------------------------------------------------------------------
# Repair Chain
# ---------------------------------------------------------------------------

class TestRepairChain:
    """Tests for geometry repair during rebuild (Phase 3 of spec)."""

    def test_transform_repair_degenerate_keeps_original(
        self, qgis_app, simple_squares
    ):
        """T4.10: A vertex_fn that collapses geometry -> original kept.

        When all vertices collapse to a single point the area drops to zero,
        which triggers the repair chain.  The final fallback keeps the
        original geometry.
        """
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        results = tt.transform(_collapse_fn)

        for orig, out in zip(simple_squares, results):
            # The repair chain should have kept the original geometry
            # rather than returning a degenerate one.
            assert out.geometry().area() > 0, (
                f"Feature '{orig.attribute('name')}' has zero area after "
                f"degenerate collapse -- repair chain should keep original"
            )

    def test_transform_rings_properly_closed(self, qgis_app, simple_squares):
        """T4.11: After transform, all rings have first point == last point."""
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        results = tt.transform(_offset_fn)

        for feat in results:
            geom = feat.geometry()
            parts = (
                geom.asMultiPolygon()
                if geom.isMultipart()
                else [geom.asPolygon()]
            )
            for part in parts:
                for ring in part:
                    assert len(ring) >= 4, "Ring has fewer than 4 vertices"
                    first, last = ring[0], ring[-1]
                    assert (
                        abs(first.x() - last.x()) < 1e-9
                        and abs(first.y() - last.y()) < 1e-9
                    ), (
                        f"Ring not closed: first={first}, last={last}"
                    )

    def test_transform_result_geometries_valid(
        self, qgis_app, simple_squares
    ):
        """T4.12: All output geometries pass isGeosValid()."""
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        results = tt.transform(_offset_fn)

        for feat in results:
            geom = feat.geometry()
            assert geom.isGeosValid(), (
                f"Feature '{feat.attribute('name')}' geometry is not valid"
            )


# ---------------------------------------------------------------------------
# Densify Shared Edges
# ---------------------------------------------------------------------------

class TestDensifySharedEdges:
    """Tests for densify_shared_edges() method."""

    def test_densify_shared_edges_adds_vertices(
        self, qgis_app, simple_squares
    ):
        """T4.13: After densifying, shared edges have more vertices.

        The shared edge between sq0 and sq1 is from (1,0) to (1,1), length=1.
        With interval=0.3 we expect floor(1/0.3) = 3 new intermediate vertices
        inserted, so total vertices on that edge goes from 2 to 5.
        """
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)

        # Count vertices before densification
        pre_count = sum(
            len(ring)
            for feat in simple_squares
            for ring in feat.geometry().asPolygon()
        )

        tt.densify_shared_edges(0.3)

        # After densification, transform with identity to get features back
        results = tt.transform(_identity_fn)
        post_count = sum(
            len(ring)
            for feat in results
            for ring in feat.geometry().asPolygon()
        )

        assert post_count > pre_count, (
            f"Vertex count did not increase after densification: "
            f"before={pre_count}, after={post_count}"
        )

    def test_densify_shared_edges_identical_on_both_sides(
        self, qgis_app, simple_squares
    ):
        """T4.14: New vertices on a shared edge are identical in both polygons.

        sq0 and sq1 share edge (1,0)-(1,1).  After densification with
        interval=0.25, both features must have the exact same set of vertices
        along that edge.
        """
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        tt.densify_shared_edges(0.25)
        results = tt.transform(_identity_fn)

        # Extract vertices along x=1 for sq0 (results[0]) and sq1 (results[1])
        def edge_verts_at_x(feat, x_val):
            """Return sorted list of y-coords for vertices at the given x."""
            verts = _extract_vertices(feat.geometry())
            return sorted(y for (vx, vy) in verts if abs(vx - x_val) < 1e-9
                          for y in [vy])

        sq0_edge = edge_verts_at_x(results[0], 1.0)
        sq1_edge = edge_verts_at_x(results[1], 1.0)

        assert len(sq0_edge) > 2, (
            "Shared edge in sq0 was not densified (only 2 vertices)"
        )
        assert sq0_edge == sq1_edge, (
            f"Shared edge vertices differ:\n  sq0: {sq0_edge}\n  sq1: {sq1_edge}"
        )

    def test_densify_private_edges_independently(
        self, qgis_app, simple_squares
    ):
        """T4.15: Private (exterior boundary) edges are also densified.

        The bottom edge of sq0, from (0,0) to (1,0), is private (no other
        square shares it).  With interval=0.3, floor(1/0.3)=3 new vertices
        should be added, giving 5 points along that edge.
        """
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        tt.densify_shared_edges(0.3)
        results = tt.transform(_identity_fn)

        # Bottom edge of sq0: y=0, x in [0, 1]
        sq0_verts = _extract_vertices(results[0].geometry())
        bottom_edge = sorted(
            (vx, vy) for (vx, vy) in sq0_verts
            if abs(vy) < 1e-9 and -1e-9 <= vx <= 1.0 + 1e-9
        )
        # Original: 2 endpoints.  After densification: should be more.
        assert len(bottom_edge) > 2, (
            f"Private bottom edge not densified: {bottom_edge}"
        )


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge-case inputs."""

    def test_single_feature_no_shared_vertices(self, qgis_app):
        """T4.16: A single polygon has no shared vertices; transform still works."""
        fields = make_fields()
        ring = [
            QgsPointXY(0, 0), QgsPointXY(5, 0),
            QgsPointXY(5, 5), QgsPointXY(0, 5),
            QgsPointXY(0, 0),
        ]
        feat = make_feature(
            QgsGeometry.fromPolygonXY([ring]), 'solo', 42.0, fields
        )
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer([feat], feedback)
        results = tt.transform(_offset_fn)

        assert len(results) == 1
        geom = results[0].geometry()
        assert geom.isGeosValid()
        # Verify offset was applied
        verts = _extract_vertices(geom)
        assert (0.5, 0.5) in verts  # (0,0) shifted by (0.5, 0.5)
        assert (5.5, 5.5) in verts  # (5,5) shifted by (0.5, 0.5)

    def test_multipolygon_feature(self, qgis_app, multipolygon):
        """T4.17: MultiPolygon with 2 parts handled correctly."""
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer([multipolygon], feedback)
        results = tt.transform(_identity_fn)

        assert len(results) == 1
        geom = results[0].geometry()
        # Should still be a MultiPolygon (or Polygon) with same area
        assert abs(geom.area() - multipolygon.geometry().area()) < 1e-6

    def test_empty_feature_list(self, qgis_app):
        """T4.18: Empty feature list -> returns empty list."""
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer([], feedback)
        results = tt.transform(_identity_fn)
        assert results == [] or len(results) == 0


# ---------------------------------------------------------------------------
# T-Junction Detection
# ---------------------------------------------------------------------------

class TestTJunctionDetection:
    """Tests for T-junction repair during construction (Phase 0)."""

    def test_t_junction_repair(self, qgis_app):
        """T4.19: Vertex of poly A on edge of poly B -> B gets the vertex inserted.

        Setup:
          poly_a: (0,0)-(2,0)-(2,1)-(0,1)  (has vertex at (1,0) implicitly
                                              if we add it)
          Actually, poly_a: (0,0)-(1,0)-(2,0)-(2,1)-(0,1)
          poly_b: (0,-1)-(2,-1)-(2,0)-(0,0)   -- bottom edge (0,0)-(2,0)
                  with NO vertex at (1,0)

        After T-junction detection, poly_b should have vertex (1,0) inserted
        into its top edge.
        """
        fields = make_fields()

        # poly_a has an explicit vertex at (1,0) along its bottom edge
        ring_a = [
            QgsPointXY(0, 0), QgsPointXY(1, 0), QgsPointXY(2, 0),
            QgsPointXY(2, 1), QgsPointXY(0, 1),
            QgsPointXY(0, 0),
        ]
        feat_a = make_feature(
            QgsGeometry.fromPolygonXY([ring_a]), 'poly_a', 1.0, fields
        )

        # poly_b does NOT have a vertex at (1,0) -- its top edge goes
        # directly from (0,0) to (2,0)
        ring_b = [
            QgsPointXY(0, -1), QgsPointXY(2, -1), QgsPointXY(2, 0),
            QgsPointXY(0, 0),
            QgsPointXY(0, -1),
        ]
        feat_b = make_feature(
            QgsGeometry.fromPolygonXY([ring_b]), 'poly_b', 2.0, fields
        )

        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer([feat_a, feat_b], feedback)

        # After construction, the internal representation of poly_b should
        # include (1,0).  We verify by transforming with identity and
        # checking that both features share (1,0).
        results = tt.transform(_identity_fn)

        verts_a = _extract_vertices(results[0].geometry())
        verts_b = _extract_vertices(results[1].geometry())

        assert (1.0, 0.0) in verts_a, "poly_a should still have vertex (1,0)"
        assert (1.0, 0.0) in verts_b, (
            "poly_b should have vertex (1,0) inserted by T-junction repair"
        )
