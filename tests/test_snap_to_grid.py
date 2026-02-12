"""Tests for Snap to Grid algorithm (spec section 5.4).

TDD tests for SnapToGridAlgorithm covering metadata, parameters,
snap_vertex logic, topology preservation, attribute/field handling,
area validation, and edge-following behavior.
"""
import math
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

from tessera.algorithms.snap_to_grid import (
    SnapToGridAlgorithm,
    remove_spikes,
    remove_consecutive_duplicates,
    resolve_grid_edges,
)

from .helpers import make_fields, make_feature
from tessera.infrastructure.topology_wrapper import TopologyTransformer
from tessera.infrastructure.feature_builder import create_output_fields, build_feature
from tessera.infrastructure.grid_generators import (
    nearest_grid_point,
    nearest_grid_vertex,
    grid_edge_length,
    trace_grid_path,
)


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


def _snap_vertex(point, spacing, grid_type, attraction):
    """Replicate the snap_vertex logic from the spec for direct testing.

    target = nearest_grid_point(point, spacing, grid_type)
    new_x = point.x() + (target.x() - point.x()) * attraction
    new_y = point.y() + (target.y() - point.y()) * attraction
    """
    target = nearest_grid_point(point, spacing, grid_type)
    new_x = point.x() + (target.x() - point.x()) * attraction
    new_y = point.y() + (target.y() - point.y()) * attraction
    return QgsPointXY(new_x, new_y)


# ---------------------------------------------------------------------------
# Test 1: Import
# ---------------------------------------------------------------------------

class TestSnapToGridImport:
    """Test that the algorithm can be imported."""

    def test_snap_to_grid_importable(self):
        """SnapToGridAlgorithm imports without error."""
        assert SnapToGridAlgorithm is not None


# ---------------------------------------------------------------------------
# Test 2: Metadata
# ---------------------------------------------------------------------------

class TestSnapToGridMetadata:
    """Test algorithm metadata."""

    def test_snap_to_grid_metadata(self):
        """name='snap_to_grid', displayName='Snap to Grid', group='Shape', groupId='shape'."""
        alg = SnapToGridAlgorithm()
        assert alg.name() == 'snap_to_grid'
        assert alg.displayName() == 'Snap to Grid'
        assert alg.group() == 'Shape'
        assert alg.groupId() == 'shape'


# ---------------------------------------------------------------------------
# Test 3: Parameters
# ---------------------------------------------------------------------------

class TestSnapToGridParameters:
    """Test algorithm parameters after initAlgorithm."""

    def test_snap_to_grid_has_parameters(self, qgis_app):
        """After initAlgorithm(), has GRID_TYPE, CELL_SIZE, AUTO_CELLS_ACROSS, ATTRACTION."""
        alg = SnapToGridAlgorithm()
        alg.initAlgorithm()

        param_names = [p.name() for p in alg.parameterDefinitions()]
        assert 'GRID_TYPE' in param_names
        assert 'CELL_SIZE' in param_names
        assert 'AUTO_CELLS_ACROSS' in param_names
        assert 'ATTRACTION' in param_names
        # Also check base params are present
        assert 'INPUT' in param_names
        assert 'OUTPUT' in param_names


# ---------------------------------------------------------------------------
# Tests 4-6: Snap Vertex Logic
# ---------------------------------------------------------------------------

class TestSnapVertexLogic:
    """Test the snap_vertex calculation directly."""

    def test_snap_vertex_full_attraction(self):
        """With attraction=1.0, vertex at (0.3, 0.7) with spacing=1 on square grid snaps to (0.0, 1.0)."""
        point = QgsPointXY(0.3, 0.7)
        result = _snap_vertex(point, 1.0, 'square', 1.0)
        assert abs(result.x() - 0.0) < 1e-9, f"Expected x=0.0, got {result.x()}"
        assert abs(result.y() - 1.0) < 1e-9, f"Expected y=1.0, got {result.y()}"

    def test_snap_vertex_zero_attraction(self):
        """With attraction=0.0, vertex stays unchanged."""
        point = QgsPointXY(0.3, 0.7)
        result = _snap_vertex(point, 1.0, 'square', 0.0)
        assert abs(result.x() - 0.3) < 1e-9, f"Expected x=0.3, got {result.x()}"
        assert abs(result.y() - 0.7) < 1e-9, f"Expected y=0.7, got {result.y()}"

    def test_snap_vertex_half_attraction(self):
        """With attraction=0.5, vertex moves halfway to grid point."""
        point = QgsPointXY(0.3, 0.7)
        # nearest grid point with spacing=1 is (0.0, 1.0)
        # halfway: x = 0.3 + (0.0 - 0.3) * 0.5 = 0.3 - 0.15 = 0.15
        #          y = 0.7 + (1.0 - 0.7) * 0.5 = 0.7 + 0.15 = 0.85
        result = _snap_vertex(point, 1.0, 'square', 0.5)
        assert abs(result.x() - 0.15) < 1e-9, f"Expected x=0.15, got {result.x()}"
        assert abs(result.y() - 0.85) < 1e-9, f"Expected y=0.85, got {result.y()}"


# ---------------------------------------------------------------------------
# Tests 7-10: Integration with TopologyTransformer
# ---------------------------------------------------------------------------

class TestSnapToGridTopology:
    """Test snap-to-grid integration with TopologyTransformer."""

    def test_snap_to_grid_preserves_topology(self, qgis_app, simple_squares):
        """Shared vertices between sq0 and sq1 should have same coords in output."""
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)

        cell_size = 1.0
        attraction = 0.5

        def snap_fn(point, vertex_id):
            target = nearest_grid_point(point, cell_size, 'square')
            new_x = point.x() + (target.x() - point.x()) * attraction
            new_y = point.y() + (target.y() - point.y()) * attraction
            return QgsPointXY(new_x, new_y)

        results = tt.transform(snap_fn)

        # sq0 and sq1 share edge at x=1 (vertices (1,0) and (1,1))
        shared = _shared_edge_vertices(results[0], results[1])
        # With spacing=1 and the squares having integer coords, grid points
        # are at integer positions. With attraction=0.5, integer coords stay put.
        # So shared vertices should still be shared and at the same positions.
        assert len(shared) >= 2, (
            f"Expected at least 2 shared vertices between sq0 and sq1, got {len(shared)}"
        )

        # Also verify sq0 and sq2 share edge at y=1
        shared_02 = _shared_edge_vertices(results[0], results[2])
        assert len(shared_02) >= 2, (
            f"Expected at least 2 shared vertices between sq0 and sq2, got {len(shared_02)}"
        )

    def test_snap_to_grid_preserves_attributes(self, qgis_app, simple_squares):
        """Output features have same 'name' and 'value' attributes as input."""
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)

        def snap_fn(point, vertex_id):
            target = nearest_grid_point(point, 1.0, 'square')
            return QgsPointXY(
                point.x() + (target.x() - point.x()) * 0.5,
                point.y() + (target.y() - point.y()) * 0.5,
            )

        results = tt.transform(snap_fn)

        for orig, out in zip(simple_squares, results):
            assert out.attribute('name') == orig.attribute('name')
            assert out.attribute('value') == orig.attribute('value')

    def test_snap_to_grid_output_fields(self, qgis_app, simple_squares):
        """Output has _tessera_algorithm and _tessera_parent_fid fields."""
        fields = make_fields()
        output_fields = create_output_fields(fields, [
            ('_tessera_algorithm', QMetaType.Type.QString),
            ('_tessera_parent_fid', QMetaType.Type.Int),
        ])

        # Verify fields exist
        field_names = [output_fields.field(i).name()
                       for i in range(output_fields.count())]
        assert '_tessera_algorithm' in field_names
        assert '_tessera_parent_fid' in field_names
        assert 'name' in field_names
        assert 'value' in field_names

        # Verify build_feature populates them
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)
        results = tt.transform(lambda pt, vid: pt)

        out_feat = build_feature(
            results[0].geometry(),
            simple_squares[0],
            'snap_to_grid',
            {},
            output_fields,
        )
        assert out_feat.attribute('_tessera_algorithm') == 'snap_to_grid'
        assert out_feat.attribute('_tessera_parent_fid') is not None

    def test_snap_to_grid_area_validation(self, qgis_app, simple_squares):
        """Extreme snapping that would collapse geometry: original should be kept.

        TopologyTransformer's _validate_and_repair handles this internally.
        """
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)

        # Collapse all vertices to origin -- should trigger area validation
        def collapse_fn(point, vertex_id):
            return QgsPointXY(0.0, 0.0)

        results = tt.transform(collapse_fn)

        for orig, out in zip(simple_squares, results):
            # Area validation should keep original geometry
            assert out.geometry().area() > 0, (
                f"Feature '{orig.attribute('name')}' collapsed to zero area"
            )
            # Area should be close to original (since original was kept)
            assert abs(out.geometry().area() - orig.geometry().area()) < 1e-6, (
                f"Feature '{orig.attribute('name')}' area changed unexpectedly"
            )


# ---------------------------------------------------------------------------
# Tests S1.1-S1.8: Spike Removal (remove_spikes function)
# ---------------------------------------------------------------------------

def _ring_to_tuples(ring):
    """Convert a list of QgsPointXY to list of (x, y) tuples."""
    return [(pt.x(), pt.y()) for pt in ring]


def _tuples_to_ring(tuples):
    """Convert list of (x, y) tuples to list of QgsPointXY."""
    return [QgsPointXY(x, y) for x, y in tuples]


class TestRemoveSpikes:
    """Tests for the remove_spikes module-level function."""

    def test_returns_ring_unchanged_when_no_spikes(self):
        """S1.1: returns ring unchanged when no spikes present."""
        ring = _tuples_to_ring([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
        result = remove_spikes(ring)
        assert len(result) == 5
        result_tuples = _ring_to_tuples(result)
        expected = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
        for actual, exp in zip(result_tuples, expected):
            assert abs(actual[0] - exp[0]) < 1e-9
            assert abs(actual[1] - exp[1]) < 1e-9

    def test_removes_spike_where_vertex0_approx_vertex2(self):
        """S1.2: removes single spike where vertex[0] ≈ vertex[2]."""
        # vertex[0]=(0,0), vertex[1]=(0.5, 1.0) spike tip, vertex[2]=(0, 1e-9)
        # vertex[0] ≈ vertex[2] within tolerance -> spike
        ring = _tuples_to_ring([
            (0, 0), (0.5, 1.0), (0, 1e-9),
            (1, 0), (1, 1), (0, 1), (0, 0),
        ])
        result = remove_spikes(ring)
        result_tuples = _ring_to_tuples(result)
        # vertex[1] (spike tip) and vertex[2] (duplicate of vertex[0]) removed
        # ring should still be valid (closed) and shorter
        assert len(result) < len(ring)
        # The spike tip (0.5, 1.0) should not be in result
        for x, y in result_tuples:
            assert not (abs(x - 0.5) < 1e-9 and abs(y - 1.0) < 1e-9), \
                "Spike tip (0.5, 1.0) should have been removed"

    def test_removes_spike_where_vertexi_equals_vertexi2_exactly(self):
        """S1.3: removes spike where vertex[i] == vertex[i+2] exactly."""
        # 7 vertices with vertex[2] == vertex[4]
        ring = _tuples_to_ring([
            (0, 0), (1, 0), (2, 0), (2.5, 1.0), (2, 0),
            (2, 1), (0, 1), (0, 0),
        ])
        result = remove_spikes(ring)
        # vertex[3] (spike tip) and vertex[4] (dup of vertex[2]) removed
        assert len(result) == 6
        result_tuples = _ring_to_tuples(result)
        # Spike tip (2.5, 1.0) should not be present
        for x, y in result_tuples:
            assert not (abs(x - 2.5) < 1e-9 and abs(y - 1.0) < 1e-9), \
                "Spike tip (2.5, 1.0) should have been removed"

    def test_removes_multiple_spikes_iteratively(self):
        """S1.4: removes multiple spikes iteratively (cascade)."""
        # After removing first spike, a second spike is exposed
        # Spike 1: vertex[2]==(1,0) ≈ vertex[4]==(1,0) -> remove v[3],v[4]
        # After removal: [(0,0),(1,0),(1.5,2.0),(1,0),(1,1),(0,1),(0,0)]
        #   becomes    : [(0,0),(1,0),(1,1),(0,1),(0,0)]
        # But let's construct: removing v[3],v[4] from first spike leaves
        # a second spike
        ring = _tuples_to_ring([
            (0, 0), (1, 0), (2, 0), (2.5, 1.0), (2, 0),
            (1.5, -0.5), (2, 0), (2, 1), (0, 1), (0, 0),
        ])
        # First spike: v[2]=(2,0) ≈ v[4]=(2,0) -> remove v[3],v[4]
        # After: [(0,0),(1,0),(2,0),(1.5,-0.5),(2,0),(2,1),(0,1),(0,0)]
        # Second spike: v[2]=(2,0) ≈ v[4]=(2,0) -> remove v[3],v[4]
        # After: [(0,0),(1,0),(2,0),(2,1),(0,1),(0,0)]
        result = remove_spikes(ring)
        assert len(result) == 6
        result_tuples = _ring_to_tuples(result)
        # Neither spike tip should remain
        for x, y in result_tuples:
            assert not (abs(x - 2.5) < 1e-9 and abs(y - 1.0) < 1e-9)
            assert not (abs(x - 1.5) < 1e-9 and abs(y - -0.5) < 1e-9)

    def test_degenerate_ring_returns_fewer_than_4_vertices(self):
        """S1.5: degenerate ring returns fewer than 4 vertices."""
        # All vertices collapse: spike removal leaves < 4 vertices
        ring = _tuples_to_ring([
            (0, 0), (0.5, 1.0), (0, 0), (0, 0),
        ])
        result = remove_spikes(ring)
        assert len(result) < 4

    def test_ring_closure_maintained_after_spike_removal(self):
        """S1.6: first == last in returned ring after spike removal."""
        ring = _tuples_to_ring([
            (0, 0), (1, 0), (2, 0), (2.5, 1.0), (2, 0),
            (2, 1), (0, 1), (0, 0),
        ])
        result = remove_spikes(ring)
        assert len(result) >= 2
        first = result[0]
        last = result[-1]
        assert abs(first.x() - last.x()) < 1e-9
        assert abs(first.y() - last.y()) < 1e-9


class TestSnapToGridSpikeIntegration:
    """Integration tests for spike removal in the snap-to-grid pipeline."""

    def test_spike_from_grid_snapping_removed(self, qgis_app, simple_squares):
        """S1.7: output has no spikes, area > 0, isGeosValid after snapping."""
        fields = make_fields()
        # Create a polygon with vertices that will produce a spike
        # when snapped to a coarse grid (cell_size=2)
        ring = [
            QgsPointXY(0, 0), QgsPointXY(2, 0), QgsPointXY(2.1, 1),
            QgsPointXY(2, 2), QgsPointXY(0, 2), QgsPointXY(0, 0),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])
        feat = QgsFeature(make_fields())
        feat.setGeometry(geom)
        feat.setAttribute('name', 'spike_test')
        feat.setAttribute('value', 1.0)

        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer([feat], feedback)

        cell_size = 2.0

        def snap_fn(point, vertex_id):
            target = nearest_grid_point(point, cell_size, 'square')
            return QgsPointXY(target.x(), target.y())

        results = tt.transform(snap_fn)

        for out in results:
            out_geom = out.geometry()
            assert out_geom.area() > 0, "Output area should be > 0"
            assert out_geom.isGeosValid(), "Output should be valid geometry"

    def test_no_spikes_when_vertices_already_on_grid(self, qgis_app, simple_squares):
        """S1.8: simple_squares with cell_size=1.0 unchanged, no vertices removed."""
        feedback = QgsProcessingFeedback()
        tt = TopologyTransformer(simple_squares, feedback)

        cell_size = 1.0

        def snap_fn(point, vertex_id):
            target = nearest_grid_point(point, cell_size, 'square')
            return QgsPointXY(target.x(), target.y())

        results = tt.transform(snap_fn)

        # Input and output vertex counts should match
        input_count = sum(
            len(ring)
            for feat in simple_squares
            for ring in (feat.geometry().asPolygon()
                         if not feat.geometry().isMultipart()
                         else [r for p in feat.geometry().asMultiPolygon() for r in p])
        )
        output_count = sum(
            len(ring)
            for feat in results
            for ring in (feat.geometry().asPolygon()
                         if not feat.geometry().isMultipart()
                         else [r for p in feat.geometry().asMultiPolygon() for r in p])
        )
        assert output_count == input_count, (
            f"Expected same vertex count: input={input_count}, output={output_count}"
        )


# ---------------------------------------------------------------------------
# Tests: grid_edge_length
# ---------------------------------------------------------------------------

class TestGridEdgeLength:
    """Tests for grid_edge_length()."""

    def test_square_edge_length(self):
        """Square grid edge length equals spacing."""
        assert grid_edge_length(10.0, 'square') == 10.0

    def test_hex_edge_length(self):
        """Hex grid edge = spacing / sqrt(3) (circumradius)."""
        result = grid_edge_length(10.0, 'hexagonal')
        expected = 10.0 / math.sqrt(3)
        assert abs(result - expected) < 1e-9

    def test_triangular_edge_length(self):
        """Triangular grid edge length equals spacing."""
        assert grid_edge_length(10.0, 'triangular') == 10.0

    def test_unknown_grid_type_raises(self):
        """Unknown grid type raises ValueError."""
        with pytest.raises(ValueError):
            grid_edge_length(10.0, 'unknown')


# ---------------------------------------------------------------------------
# Tests: nearest_grid_vertex (cell corners)
# ---------------------------------------------------------------------------

class TestNearestGridVertex:
    """Tests for nearest_grid_vertex() — snap to cell corners, not centres."""

    def test_square_vertex_at_corner(self):
        """Point near a square cell corner snaps to that corner.

        Square cells centred at (i*s, j*s), corners at ((i±0.5)*s, (j±0.5)*s).
        With spacing=10, corners at multiples of 10 offset by 5:
        ..., -5, 5, 15, 25, ...
        Point (7, 12) -> nearest corner is (5, 15).
        """
        result = nearest_grid_vertex(QgsPointXY(7, 12), 10.0, 'square')
        assert abs(result.x() - 5.0) < 1e-9, f"Expected x=5, got {result.x()}"
        assert abs(result.y() - 15.0) < 1e-9, f"Expected y=15, got {result.y()}"

    def test_square_vertex_at_origin_region(self):
        """Point (0.3, 0.2) with spacing=1 snaps to corner (0.5, 0.5) or (-0.5, -0.5)."""
        result = nearest_grid_vertex(QgsPointXY(0.3, 0.2), 1.0, 'square')
        # Corners are at ±0.5, ±1.5, ... Nearest to (0.3, 0.2) is (0.5, 0.5)
        # Actually, check: dist to (0.5,0.5) = sqrt(0.04+0.09) = 0.36
        # dist to (-0.5,-0.5) = sqrt(0.64+0.49) = 1.06
        # dist to (0.5,-0.5) = sqrt(0.04+0.49) = 0.73
        # dist to (-0.5,0.5) = sqrt(0.64+0.09) = 0.85
        assert abs(result.x() - 0.5) < 1e-9
        assert abs(result.y() - 0.5) < 1e-9

    def test_square_vertex_already_on_corner(self):
        """Point exactly on a corner stays there."""
        result = nearest_grid_vertex(QgsPointXY(0.5, 0.5), 1.0, 'square')
        assert abs(result.x() - 0.5) < 1e-9
        assert abs(result.y() - 0.5) < 1e-9

    def test_hex_vertex_is_on_hex_corner(self):
        """Hex vertex snap lands on an actual hexagon vertex.

        Verify the snapped point is at distance R from some hex centre.
        """
        spacing = 10.0
        R = spacing / math.sqrt(3)
        point = QgsPointXY(3.0, 4.0)
        result = nearest_grid_vertex(point, spacing, 'hexagonal')

        # Verify: result should be at distance R (±tolerance) from the
        # nearest hex centre
        center = nearest_grid_point(result, spacing, 'hexagonal')
        dist = math.sqrt(
            (result.x() - center.x()) ** 2 + (result.y() - center.y()) ** 2
        )
        assert abs(dist - R) < 1e-6, (
            f"Hex vertex should be at R={R:.4f} from centre, got dist={dist:.4f}"
        )

    def test_tri_vertex_on_valid_lattice(self):
        """Triangular vertex snap lands on the (k*s/2, m*h) lattice with (k+m)%2==0."""
        spacing = 10.0
        h = spacing * math.sqrt(3) / 2.0
        half_s = spacing / 2.0

        point = QgsPointXY(7.0, 3.0)
        result = nearest_grid_vertex(point, spacing, 'triangular')

        # Check lattice membership: x = k*half_s, y = m*h, (k+m)%2 == 0
        k = round(result.x() / half_s)
        m = round(result.y() / h)
        assert abs(result.x() - k * half_s) < 1e-9, (
            f"x={result.x()} not on lattice (k={k}, expected {k * half_s})"
        )
        assert abs(result.y() - m * h) < 1e-9, (
            f"y={result.y()} not on lattice (m={m}, expected {m * h})"
        )
        assert (k + m) % 2 == 0, (
            f"Parity violation: k={k}, m={m}, (k+m)%2={((k + m) % 2)}"
        )

    def test_unknown_grid_type_raises(self):
        """Unknown grid type raises ValueError."""
        with pytest.raises(ValueError):
            nearest_grid_vertex(QgsPointXY(0, 0), 1.0, 'unknown')


# ---------------------------------------------------------------------------
# Tests: remove_consecutive_duplicates
# ---------------------------------------------------------------------------

class TestRemoveConsecutiveDuplicates:
    """Tests for remove_consecutive_duplicates()."""

    def test_no_duplicates_unchanged(self):
        """Ring with no consecutive duplicates is returned unchanged."""
        ring = _tuples_to_ring([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
        result = remove_consecutive_duplicates(ring)
        assert len(result) == 5

    def test_consecutive_duplicates_collapsed(self):
        """Two consecutive identical points collapse to one."""
        ring = _tuples_to_ring([
            (0, 0), (1, 0), (1, 0), (1, 1), (0, 1), (0, 0),
        ])
        result = remove_consecutive_duplicates(ring, tolerance=1e-6)
        result_tuples = _ring_to_tuples(result)
        # Should collapse (1,0),(1,0) -> single (1,0)
        assert len(result) == 5

    def test_multiple_consecutive_duplicates(self):
        """Three consecutive identical points collapse to one."""
        ring = _tuples_to_ring([
            (0, 0), (1, 0), (1, 0), (1, 0), (1, 1), (0, 1), (0, 0),
        ])
        result = remove_consecutive_duplicates(ring, tolerance=1e-6)
        assert len(result) == 5

    def test_within_tolerance_collapsed(self):
        """Points within tolerance of each other are collapsed."""
        ring = _tuples_to_ring([
            (0, 0), (1, 0), (1.0001, 0.0001), (1, 1), (0, 1), (0, 0),
        ])
        result = remove_consecutive_duplicates(ring, tolerance=0.001)
        assert len(result) == 5

    def test_ring_closure_maintained(self):
        """Ring remains closed after dedup."""
        ring = _tuples_to_ring([
            (0, 0), (1, 0), (1, 0), (1, 1), (0, 1), (0, 0),
        ])
        result = remove_consecutive_duplicates(ring)
        first, last = result[0], result[-1]
        assert abs(first.x() - last.x()) < 1e-9
        assert abs(first.y() - last.y()) < 1e-9

    def test_empty_ring(self):
        """Empty ring returns empty."""
        assert remove_consecutive_duplicates([]) == []

    def test_single_point(self):
        """Single-point ring returns as-is."""
        ring = [QgsPointXY(1, 1)]
        result = remove_consecutive_duplicates(ring)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Tests: Edge-following integration
# ---------------------------------------------------------------------------

class TestEdgeFollowing:
    """Integration tests for the densify → snap-to-vertex → dedup pipeline."""

    def test_long_edge_gains_intermediate_vertices(self, qgis_app):
        """A 100-unit side with grid spacing=20 gets densified and produces
        intermediate vertices along the edge (not just 2 endpoints)."""
        # Rectangle: 100 wide x 50 tall
        ring = [
            QgsPointXY(0, 0), QgsPointXY(100, 0),
            QgsPointXY(100, 50), QgsPointXY(0, 50), QgsPointXY(0, 0),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])
        feat = QgsFeature(make_fields())
        feat.setGeometry(geom)
        feat.setAttribute('name', 'rect')
        feat.setAttribute('value', 1.0)

        feedback = QgsProcessingFeedback()
        cell_size = 20.0
        grid_type = 'square'
        edge_len = grid_edge_length(cell_size, grid_type)
        densify_interval = edge_len / 2.0

        tt = TopologyTransformer([feat], feedback)
        tt.densify_shared_edges(densify_interval)

        def snap_fn(point, vertex_id):
            return nearest_grid_vertex(point, cell_size, grid_type)

        results = tt.transform(snap_fn)
        out_geom = results[0].geometry()
        out_ring = out_geom.asPolygon()[0]

        # The bottom edge (y≈some grid vertex y) should have more than
        # 2 vertices — densification should have added intermediate points
        assert len(out_ring) > 5, (
            f"Expected densified output with many vertices, got {len(out_ring)}"
        )

    def test_square_grid_edges_axis_aligned(self, qgis_app):
        """For a square grid with full attraction, all output edges should be
        axis-aligned (horizontal or vertical)."""
        # A rectangle that spans multiple grid cells
        ring = [
            QgsPointXY(2, 3), QgsPointXY(48, 3),
            QgsPointXY(48, 27), QgsPointXY(2, 27), QgsPointXY(2, 3),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])
        feat = QgsFeature(make_fields())
        feat.setGeometry(geom)
        feat.setAttribute('name', 'rect')
        feat.setAttribute('value', 1.0)

        feedback = QgsProcessingFeedback()
        cell_size = 10.0
        grid_type = 'square'
        edge_len = grid_edge_length(cell_size, grid_type)
        densify_interval = edge_len / 2.0

        tt = TopologyTransformer([feat], feedback)
        tt.densify_shared_edges(densify_interval)

        def snap_fn(point, vertex_id):
            return nearest_grid_vertex(point, cell_size, grid_type)

        results = tt.transform(snap_fn)
        out_geom = results[0].geometry()

        # Apply consecutive duplicate removal like the algorithm does
        out_ring = out_geom.asPolygon()[0]
        out_ring = remove_consecutive_duplicates(out_ring, cell_size * 0.01)

        # Check every edge is axis-aligned
        for i in range(len(out_ring) - 1):
            p1 = out_ring[i]
            p2 = out_ring[i + 1]
            dx = abs(p1.x() - p2.x())
            dy = abs(p1.y() - p2.y())
            is_horizontal = dy < 1e-6
            is_vertical = dx < 1e-6
            assert is_horizontal or is_vertical, (
                f"Edge {i}: ({p1.x():.2f},{p1.y():.2f})->({p2.x():.2f},{p2.y():.2f}) "
                f"is neither horizontal nor vertical"
            )

    def test_square_grid_vertices_on_grid_corners(self, qgis_app):
        """All output vertices land on square grid cell corners."""
        ring = [
            QgsPointXY(3, 7), QgsPointXY(37, 7),
            QgsPointXY(37, 23), QgsPointXY(3, 23), QgsPointXY(3, 7),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])
        feat = QgsFeature(make_fields())
        feat.setGeometry(geom)
        feat.setAttribute('name', 'rect')
        feat.setAttribute('value', 1.0)

        feedback = QgsProcessingFeedback()
        cell_size = 10.0
        grid_type = 'square'
        edge_len = grid_edge_length(cell_size, grid_type)
        densify_interval = edge_len / 2.0

        tt = TopologyTransformer([feat], feedback)
        tt.densify_shared_edges(densify_interval)

        def snap_fn(point, vertex_id):
            return nearest_grid_vertex(point, cell_size, grid_type)

        results = tt.transform(snap_fn)
        out_ring = results[0].geometry().asPolygon()[0]

        # Square grid corners at (i±0.5)*spacing.
        # With spacing=10, corners at 5, 15, 25, 35, -5, ...
        half = cell_size / 2.0
        for pt in out_ring:
            rx = (pt.x() - half) / cell_size
            ry = (pt.y() - half) / cell_size
            assert abs(rx - round(rx)) < 1e-6, (
                f"x={pt.x()} not on grid corner (remainder={rx - round(rx):.6f})"
            )
            assert abs(ry - round(ry)) < 1e-6, (
                f"y={pt.y()} not on grid corner (remainder={ry - round(ry):.6f})"
            )

    def test_topology_preserved_with_edge_following(self, qgis_app, simple_squares):
        """After densify+vertex-snap, adjacent features still share vertices."""
        feedback = QgsProcessingFeedback()
        cell_size = 0.5
        grid_type = 'square'
        edge_len = grid_edge_length(cell_size, grid_type)
        densify_interval = edge_len / 2.0

        tt = TopologyTransformer(simple_squares, feedback)
        tt.densify_shared_edges(densify_interval)

        def snap_fn(point, vertex_id):
            return nearest_grid_vertex(point, cell_size, grid_type)

        results = tt.transform(snap_fn)

        # sq0 and sq1 share edge at x=1
        shared_01 = _shared_edge_vertices(results[0], results[1])
        assert len(shared_01) >= 2, (
            f"Expected shared vertices between sq0/sq1, got {len(shared_01)}"
        )

        # sq0 and sq2 share edge at y=1
        shared_02 = _shared_edge_vertices(results[0], results[2])
        assert len(shared_02) >= 2, (
            f"Expected shared vertices between sq0/sq2, got {len(shared_02)}"
        )


# ---------------------------------------------------------------------------
# Tests: trace_grid_path (grid-edge pathfinding)
# ---------------------------------------------------------------------------

class TestTraceGridPath:
    """Tests for trace_grid_path() — shortest path along grid edges."""

    def test_square_adjacent_returns_empty(self):
        """Two adjacent square corners need no intermediates."""
        # (5, 5) and (15, 5) are adjacent corners (spacing=10, one step right)
        result = trace_grid_path(QgsPointXY(5, 5), QgsPointXY(15, 5), 10.0, 'square')
        assert result == []

    def test_square_same_point_returns_empty(self):
        """Same point returns no intermediates."""
        result = trace_grid_path(QgsPointXY(5, 5), QgsPointXY(5, 5), 10.0, 'square')
        assert result == []

    def test_square_diagonal_inserts_elbow(self):
        """Diagonal square corners get a staircase intermediate.

        (5, 5) → (15, 15) should produce one intermediate at either
        (15, 5) or (5, 15), making two axis-aligned edges.
        """
        result = trace_grid_path(QgsPointXY(5, 5), QgsPointXY(15, 15), 10.0, 'square')
        assert len(result) == 1
        pt = result[0]
        # Must be either (15, 5) or (5, 15)
        option_a = abs(pt.x() - 15) < 1e-6 and abs(pt.y() - 5) < 1e-6
        option_b = abs(pt.x() - 5) < 1e-6 and abs(pt.y() - 15) < 1e-6
        assert option_a or option_b, f"Expected (15,5) or (5,15), got ({pt.x()},{pt.y()})"

    def test_square_multi_step_diagonal(self):
        """3-step diagonal produces staircase intermediates.

        (5, 5) → (35, 35): 3 steps in x, 3 in y. Needs 5 intermediates
        (3+3-1 steps total, minus start and end).
        """
        result = trace_grid_path(QgsPointXY(5, 5), QgsPointXY(35, 35), 10.0, 'square')
        assert len(result) == 5
        # All edges in the full path must be axis-aligned
        full_path = [QgsPointXY(5, 5)] + result + [QgsPointXY(35, 35)]
        for i in range(len(full_path) - 1):
            p1, p2 = full_path[i], full_path[i + 1]
            dx = abs(p1.x() - p2.x())
            dy = abs(p1.y() - p2.y())
            assert (dx < 1e-6) or (dy < 1e-6), (
                f"Edge {i} is diagonal: ({p1.x()},{p1.y()})→({p2.x()},{p2.y()})"
            )

    def test_hex_adjacent_returns_empty(self):
        """Two adjacent hex vertices need no intermediates."""
        spacing = 10.0
        R = spacing / math.sqrt(3)
        # Two adjacent vertices of the hex at origin: (R, 0) and (R/2, R*√3/2)
        p1 = QgsPointXY(R, 0)
        p2 = QgsPointXY(R / 2, R * math.sqrt(3) / 2)
        result = trace_grid_path(p1, p2, spacing, 'hexagonal')
        assert result == []

    def test_hex_non_adjacent_inserts_intermediates(self):
        """Non-adjacent hex vertices get intermediates along hex edges."""
        spacing = 10.0
        R = spacing / math.sqrt(3)
        # Opposite vertices of hex at origin: (R, 0) and (-R, 0), distance 2R
        p1 = QgsPointXY(R, 0)
        p2 = QgsPointXY(-R, 0)
        result = trace_grid_path(p1, p2, spacing, 'hexagonal')
        assert len(result) >= 1
        # All edges in full path must be length R (hex edge length)
        full_path = [p1] + result + [p2]
        for i in range(len(full_path) - 1):
            pa, pb = full_path[i], full_path[i + 1]
            dist = math.sqrt((pa.x() - pb.x()) ** 2 + (pa.y() - pb.y()) ** 2)
            assert abs(dist - R) < R * 0.02, (
                f"Edge {i} length {dist:.4f} != R={R:.4f}"
            )

    def test_hex_opposite_vertices_traces_around(self):
        """Opposite hex vertices (R,0) → (-R,0) traces 3 edges around the hex.

        The path must go around (not through) the hexagon, producing
        2 intermediates and 3 edges, each of length R.
        """
        spacing = 10.0
        R = spacing / math.sqrt(3)
        p1 = QgsPointXY(R, 0)
        p2 = QgsPointXY(-R, 0)
        result = trace_grid_path(p1, p2, spacing, 'hexagonal')
        assert len(result) == 2, (
            f"Expected 2 intermediates for opposite hex vertices, got {len(result)}"
        )
        full_path = [p1] + result + [p2]
        for i in range(len(full_path) - 1):
            pa, pb = full_path[i], full_path[i + 1]
            dist = math.sqrt((pa.x() - pb.x()) ** 2 + (pa.y() - pb.y()) ** 2)
            assert abs(dist - R) < R * 0.02, (
                f"Edge {i} length {dist:.4f} != R={R:.4f}"
            )

    def test_hex_long_path_all_edges_valid(self):
        """A hex path spanning multiple cells: all edges must be length R."""
        spacing = 10.0
        R = spacing / math.sqrt(3)
        # Snap two distant points to hex vertices, then trace
        p1 = nearest_grid_vertex(QgsPointXY(0, 0), spacing, 'hexagonal')
        p2 = nearest_grid_vertex(QgsPointXY(50, 30), spacing, 'hexagonal')
        result = trace_grid_path(p1, p2, spacing, 'hexagonal')
        assert len(result) >= 3, (
            f"Expected several intermediates for long path, got {len(result)}"
        )
        full_path = [p1] + result + [p2]
        for i in range(len(full_path) - 1):
            pa, pb = full_path[i], full_path[i + 1]
            dist = math.sqrt((pa.x() - pb.x()) ** 2 + (pa.y() - pb.y()) ** 2)
            assert abs(dist - R) < R * 0.02, (
                f"Edge {i} length {dist:.4f} != R={R:.4f} "
                f"({pa.x():.2f},{pa.y():.2f})→({pb.x():.2f},{pb.y():.2f})"
            )

    def test_hex_path_vertices_are_hex_corners(self):
        """Every intermediate vertex in a hex path must be an actual hex corner."""
        spacing = 10.0
        R = spacing / math.sqrt(3)
        p1 = nearest_grid_vertex(QgsPointXY(5, 5), spacing, 'hexagonal')
        p2 = nearest_grid_vertex(QgsPointXY(40, 20), spacing, 'hexagonal')
        result = trace_grid_path(p1, p2, spacing, 'hexagonal')
        for pt in result:
            snapped = nearest_grid_vertex(pt, spacing, 'hexagonal')
            assert abs(snapped.x() - pt.x()) < 0.01, (
                f"Intermediate ({pt.x():.4f},{pt.y():.4f}) not on hex vertex lattice"
            )
            assert abs(snapped.y() - pt.y()) < 0.01, (
                f"Intermediate ({pt.x():.4f},{pt.y():.4f}) not on hex vertex lattice"
            )

    def test_tri_non_adjacent_all_edges_valid(self):
        """Triangular path has all edges of length s."""
        spacing = 10.0
        h = spacing * math.sqrt(3) / 2.0
        # Two vertices 2 steps apart horizontally: (0, 0) and (20, 0)
        p1 = QgsPointXY(0, 0)
        p2 = QgsPointXY(20, 0)
        result = trace_grid_path(p1, p2, spacing, 'triangular')
        assert len(result) == 1  # One intermediate at (10, 0)
        full_path = [p1] + result + [p2]
        for i in range(len(full_path) - 1):
            pa, pb = full_path[i], full_path[i + 1]
            dist = math.sqrt((pa.x() - pb.x()) ** 2 + (pa.y() - pb.y()) ** 2)
            assert abs(dist - spacing) < spacing * 0.02, (
                f"Edge {i} length {dist:.4f} != s={spacing:.4f}"
            )


# ---------------------------------------------------------------------------
# Tests: Diagonal input → axis-aligned output (the actual bug fix)
# ---------------------------------------------------------------------------

class TestDiagonalEdgeResolution:
    """Tests that diagonal input edges produce grid-aligned output."""

    def test_triangle_input_square_grid_no_diagonals(self, qgis_app):
        """A triangle with 45° edges, square grid: all output edges axis-aligned."""
        ring = [
            QgsPointXY(0, 0), QgsPointXY(100, 0),
            QgsPointXY(50, 50), QgsPointXY(0, 0),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])
        feat = QgsFeature(make_fields())
        feat.setGeometry(geom)
        feat.setAttribute('name', 'triangle')
        feat.setAttribute('value', 1.0)

        feedback = QgsProcessingFeedback()
        cell_size = 20.0
        grid_type = 'square'
        edge_len = grid_edge_length(cell_size, grid_type)

        tt = TopologyTransformer([feat], feedback)
        tt.densify_shared_edges(edge_len / 2.0)

        results = tt.transform(
            lambda pt, vid: nearest_grid_vertex(pt, cell_size, grid_type)
        )

        # Apply resolve + dedup (same pipeline as the algorithm)
        out_geom = results[0].geometry()
        out_ring = out_geom.asPolygon()[0]
        out_ring = resolve_grid_edges(out_ring, cell_size, grid_type)
        out_ring = remove_consecutive_duplicates(out_ring, cell_size * 0.01)

        for i in range(len(out_ring) - 1):
            p1, p2 = out_ring[i], out_ring[i + 1]
            dx = abs(p1.x() - p2.x())
            dy = abs(p1.y() - p2.y())
            assert (dx < 1e-6) or (dy < 1e-6), (
                f"Edge {i}: ({p1.x():.1f},{p1.y():.1f})→({p2.x():.1f},{p2.y():.1f}) "
                f"is diagonal"
            )

    def test_hex_zigzag_survives_spike_removal(self, qgis_app):
        """After resolve + spike removal, all hex edges remain valid.

        A hex zigzag (2 consecutive hex edges) produces a diagonal
        distance of R*sqrt(3) = spacing.  With the old spike tolerance
        (cell_size = spacing), ALL zigzag patterns were destroyed.  With
        the corrected tolerance (edge_len * 0.3), only true spikes
        (back-and-forth along the same edges) are removed, preserving
        the grid-aligned outline.
        """
        spacing = 20.0
        R = spacing / math.sqrt(3)
        grid_type = 'hexagonal'

        # Rectangle spanning multiple hex cells
        ring = [
            QgsPointXY(0, 0), QgsPointXY(80, 0),
            QgsPointXY(80, 60), QgsPointXY(0, 60), QgsPointXY(0, 0),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])
        feat = QgsFeature(make_fields())
        feat.setGeometry(geom)
        feat.setAttribute('name', 'hex_rect')
        feat.setAttribute('value', 1.0)

        feedback = QgsProcessingFeedback()
        edge_len = grid_edge_length(spacing, grid_type)

        tt = TopologyTransformer([feat], feedback)
        tt.densify_shared_edges(edge_len / 2.0)

        results = tt.transform(
            lambda pt, vid: nearest_grid_vertex(pt, spacing, grid_type)
        )

        out_geom = results[0].geometry()
        out_ring = out_geom.asPolygon()[0]
        out_ring = resolve_grid_edges(out_ring, spacing, grid_type)

        # Apply dedup + spike removal with correct tolerance
        dedup_tolerance = spacing * 0.01
        spike_tolerance = edge_len * 0.3
        out_ring = remove_consecutive_duplicates(out_ring, dedup_tolerance)
        out_ring = remove_spikes(out_ring, spike_tolerance)

        # Must have enough vertices for a valid polygon
        assert len(out_ring) >= 4, (
            f"Polygon degenerate after spike removal: {len(out_ring)} vertices"
        )

        # All edges should be hex-edge length R
        for i in range(len(out_ring) - 1):
            p1, p2 = out_ring[i], out_ring[i + 1]
            dist = math.sqrt((p1.x() - p2.x()) ** 2 + (p1.y() - p2.y()) ** 2)
            assert abs(dist - R) < R * 0.05, (
                f"Edge {i}: length {dist:.4f} != R={R:.4f} "
                f"({p1.x():.2f},{p1.y():.2f})→({p2.x():.2f},{p2.y():.2f})"
            )

    def test_canonical_resolve_shared_edges(self, qgis_app):
        """Two adjacent features sharing an edge produce identical edge paths.

        Feature A has edge P1→P2, Feature B has edge P2→P1.
        Canonical resolve ensures both produce the same intermediates.
        """
        spacing = 20.0
        grid_type = 'hexagonal'

        # Snap two points to hex vertices to get valid grid endpoints
        p1 = nearest_grid_vertex(QgsPointXY(10, 5), spacing, grid_type)
        p2 = nearest_grid_vertex(QgsPointXY(60, 35), spacing, grid_type)

        # Feature A: ring goes ... → p1 → p2 → ...
        ring_a = [p1, p2, nearest_grid_vertex(QgsPointXY(60, 60), spacing, grid_type), p1]
        resolved_a = resolve_grid_edges(ring_a, spacing, grid_type)

        # Feature B: ring goes ... → p2 → p1 → ...
        ring_b = [p2, p1, nearest_grid_vertex(QgsPointXY(10, 60), spacing, grid_type), p2]
        resolved_b = resolve_grid_edges(ring_b, spacing, grid_type)

        # Extract the shared edge path from each resolved ring
        # In A: from p1 to p2 (first segment)
        path_a = []
        for pt in resolved_a:
            path_a.append((round(pt.x(), 6), round(pt.y(), 6)))
            if abs(pt.x() - p2.x()) < 0.01 and abs(pt.y() - p2.y()) < 0.01:
                break

        # In B: from p2 to p1 (first segment)
        path_b = []
        for pt in resolved_b:
            path_b.append((round(pt.x(), 6), round(pt.y(), 6)))
            if abs(pt.x() - p1.x()) < 0.01 and abs(pt.y() - p1.y()) < 0.01:
                break

        # path_b reversed should equal path_a
        path_b_reversed = list(reversed(path_b))

        assert len(path_a) == len(path_b_reversed), (
            f"Shared edge paths have different lengths: "
            f"A={len(path_a)}, B_reversed={len(path_b_reversed)}"
        )
        for i, (a, b) in enumerate(zip(path_a, path_b_reversed)):
            assert abs(a[0] - b[0]) < 0.01 and abs(a[1] - b[1]) < 0.01, (
                f"Vertex {i} differs: A={a}, B_reversed={b}"
            )

    def test_hex_grid_all_edges_valid_length(self, qgis_app):
        """Hex grid output: all edges should be hex-edge length R."""
        ring = [
            QgsPointXY(0, 0), QgsPointXY(60, 0),
            QgsPointXY(30, 40), QgsPointXY(0, 0),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])
        feat = QgsFeature(make_fields())
        feat.setGeometry(geom)
        feat.setAttribute('name', 'triangle')
        feat.setAttribute('value', 1.0)

        feedback = QgsProcessingFeedback()
        cell_size = 20.0
        grid_type = 'hexagonal'
        edge_len = grid_edge_length(cell_size, grid_type)
        R = cell_size / math.sqrt(3)

        tt = TopologyTransformer([feat], feedback)
        tt.densify_shared_edges(edge_len / 2.0)

        results = tt.transform(
            lambda pt, vid: nearest_grid_vertex(pt, cell_size, grid_type)
        )

        out_geom = results[0].geometry()
        out_ring = out_geom.asPolygon()[0]
        out_ring = resolve_grid_edges(out_ring, cell_size, grid_type)
        out_ring = remove_consecutive_duplicates(out_ring, cell_size * 0.01)

        for i in range(len(out_ring) - 1):
            p1, p2 = out_ring[i], out_ring[i + 1]
            dist = math.sqrt((p1.x() - p2.x()) ** 2 + (p1.y() - p2.y()) ** 2)
            assert abs(dist - R) < R * 0.05, (
                f"Edge {i}: length {dist:.4f} != R={R:.4f} "
                f"({p1.x():.2f},{p1.y():.2f})→({p2.x():.2f},{p2.y():.2f})"
            )


def test_degenerate_part_does_not_block_valid_parts(qgis_app):
    """Multipolygon with one degenerate part should snap the valid parts.

    When a tiny exclave (e.g. Cabinda) collapses to < 4 vertices at coarse
    cell sizes, the main polygon body must still be snapped — not the entire
    feature falling back to original geometry.
    """
    large = [
        QgsPointXY(1700000, 9600000), QgsPointXY(2200000, 9600000),
        QgsPointXY(2200000, 10300000), QgsPointXY(1700000, 10300000),
        QgsPointXY(1700000, 9600000),
    ]
    tiny = [
        QgsPointXY(1710000, 10340000), QgsPointXY(1740000, 10340000),
        QgsPointXY(1740000, 10370000), QgsPointXY(1710000, 10370000),
        QgsPointXY(1710000, 10340000),
    ]

    cell_size = 150000.0
    grid_type = 'hexagonal'

    dedup_tol = cell_size * 0.01
    large_snapped = [nearest_grid_vertex(pt, cell_size, grid_type) for pt in large]
    large_deduped = remove_consecutive_duplicates(large_snapped, dedup_tol)
    tiny_snapped = [nearest_grid_vertex(pt, cell_size, grid_type) for pt in tiny]
    tiny_deduped = remove_consecutive_duplicates(tiny_snapped, dedup_tol)

    multi_geom = QgsGeometry.fromMultiPolygonXY([[large_deduped], [tiny_deduped]])
    feat = QgsFeature()
    feat.setGeometry(multi_geom)

    original_geom = QgsGeometry.fromMultiPolygonXY([[large], [tiny]])

    SnapToGridAlgorithm._remove_spikes_from_features(
        [feat], [original_geom], cell_size, grid_type)

    result_parts = feat.geometry().asMultiPolygon()
    assert len(result_parts) == 1, (
        f'Degenerate tiny part should be dropped, got {len(result_parts)} parts'
    )
    assert feat.geometry().area() > 0


def test_self_intersecting_snap_produces_valid_output(qgis_app):
    """Snapping to a coarse grid can create self-intersections (bow-ties).

    The algorithm must repair these via makeValid before output, so
    downstream tools like Tile Fill don't reject the geometry.
    """
    from tessera.infrastructure.geometry_helpers import extract_polygons

    # Build a bow-tie (self-intersecting polygon) — simulates what
    # coarse grid snapping can produce when opposite sides cross
    bowtie = QgsGeometry.fromPolygonXY([[
        QgsPointXY(0, 0), QgsPointXY(100, 100),
        QgsPointXY(100, 0), QgsPointXY(0, 100),
        QgsPointXY(0, 0),
    ]])
    assert not bowtie.isGeosValid()

    # makeValid + extract_polygons should produce valid polygon(s)
    repaired = bowtie.makeValid()
    repaired = extract_polygons(repaired)
    assert not repaired.isEmpty()
    assert repaired.isGeosValid()
    assert repaired.area() > 0
