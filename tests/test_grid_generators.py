"""Tests for grid_generators module."""
import math

import pytest
from qgis.core import QgsGeometry, QgsPointXY, QgsRectangle, QgsWkbTypes

from tessera.infrastructure.grid_generators import (
    generate_point_grid,
    generate_cell_polygons,
    auto_cell_size,
    nearest_grid_point,
    nearest_grid_vertex,
)


# ---------------------------------------------------------------------------
# T4.1 - T4.2: generate_point_grid -- square
# ---------------------------------------------------------------------------

class TestGeneratePointGridSquare:
    """Tests for generate_point_grid() with square grid."""

    def test_square_grid_point_count(self, qgis_app):
        """T4.1: extent(0,0,100,100), spacing=10 yields 11*11=121 points."""
        extent = QgsRectangle(0, 0, 100, 100)
        points = generate_point_grid(extent, 10, 'square')
        assert len(points) == 121
        # Verify corners are present
        xs = [p.x() for p in points]
        ys = [p.y() for p in points]
        assert min(xs) == pytest.approx(0.0)
        assert max(xs) == pytest.approx(100.0)
        assert min(ys) == pytest.approx(0.0)
        assert max(ys) == pytest.approx(100.0)

    def test_square_grid_non_divisible_extent(self, qgis_app):
        """T4.2: extent(0,0,105,105), spacing=10 covers the extent."""
        extent = QgsRectangle(0, 0, 105, 105)
        points = generate_point_grid(extent, 10, 'square')
        # Should have 11*11=121 points (0,10,...,100) per axis
        # since 110 > 105, we expect the grid to include up to 110
        # or at minimum cover 0..100. Accept either 121 or 144.
        xs = [p.x() for p in points]
        ys = [p.y() for p in points]
        # Grid must reach or exceed extent boundaries
        assert max(xs) >= 100.0
        assert max(ys) >= 100.0
        assert min(xs) == pytest.approx(0.0)
        assert min(ys) == pytest.approx(0.0)
        # Reasonable count: at least 121 (11x11), at most 144 (12x12)
        assert 121 <= len(points) <= 144


# ---------------------------------------------------------------------------
# T4.3 - T4.4: generate_point_grid -- hexagonal
# ---------------------------------------------------------------------------

class TestGeneratePointGridHex:
    """Tests for generate_point_grid() with hexagonal grid."""

    def test_hex_grid_point_count_approx(self, qgis_app):
        """T4.3: hex grid on extent(0,0,100,100), spacing=10 gives reasonable count."""
        extent = QgsRectangle(0, 0, 100, 100)
        points = generate_point_grid(extent, 10, 'hexagonal')
        # Hex grids have col_spacing = 3*R/2 where R = 10/sqrt(3) ~ 5.774
        # col_spacing ~ 8.66, so about 12 columns over 100 units
        # row_spacing = 10, so about 11 rows
        # Expect roughly 110-150 points
        assert 80 <= len(points) <= 200
        # All points should be within or close to extent (one cell buffer)
        R = 10 / math.sqrt(3)
        for p in points:
            assert p.x() >= -R - 0.01
            assert p.y() >= -10 - 0.01
            assert p.x() <= 100 + R + 0.01
            assert p.y() <= 100 + 10 + 0.01

    def test_hex_grid_column_offset(self, qgis_app):
        """T4.4: odd columns are offset by spacing/2 vertically."""
        extent = QgsRectangle(0, 0, 100, 100)
        spacing = 10
        points = generate_point_grid(extent, spacing, 'hexagonal')
        R = spacing / math.sqrt(3)
        col_spacing = 1.5 * R

        # Group points by column (approximate x coordinate)
        columns = {}
        for p in points:
            col_idx = round(p.x() / col_spacing)
            columns.setdefault(col_idx, []).append(p.y())

        # Check that odd columns have different y-offsets than even columns
        even_ys = set()
        odd_ys = set()
        for col_idx, ys in columns.items():
            rounded_ys = {round(y, 4) for y in ys}
            if col_idx % 2 == 0:
                even_ys.update(rounded_ys)
            else:
                odd_ys.update(rounded_ys)

        if even_ys and odd_ys:
            # The min y of odd columns should differ from even by spacing/2
            even_min = min(even_ys)
            odd_min = min(odd_ys)
            offset = abs(odd_min - even_min)
            assert abs(offset - spacing / 2) < 1.0


# ---------------------------------------------------------------------------
# T4.5 - T4.6: generate_cell_polygons
# ---------------------------------------------------------------------------

class TestGenerateCellPolygons:
    """Tests for generate_cell_polygons()."""

    def test_square_cell_polygons(self, qgis_app):
        """T4.5: extent(0,0,20,20), spacing=10 yields square polygons with area=100."""
        extent = QgsRectangle(0, 0, 20, 20)
        cells = generate_cell_polygons(extent, 10, 'square')
        # Grid points at (0,0),(10,0),(20,0),(0,10),(10,10),(20,10),(0,20),(10,20),(20,20)
        # = 3*3 = 9 cells
        assert len(cells) == 9
        for center, geom in cells:
            assert isinstance(center, QgsPointXY)
            assert not geom.isEmpty()
            assert geom.type() == QgsWkbTypes.PolygonGeometry
            # Each square cell has area = spacing^2 = 100
            assert abs(geom.area() - 100.0) < 0.01

    def test_hex_cell_polygon_geometry(self, qgis_app):
        """T4.6: hex cell polygons have 6 vertices, correct R, expected area."""
        extent = QgsRectangle(0, 0, 100, 100)
        spacing = 10
        cells = generate_cell_polygons(extent, spacing, 'hexagonal')
        R = spacing / math.sqrt(3)
        expected_area = (3 * math.sqrt(3) / 2) * R ** 2

        assert len(cells) > 0
        for center, geom in cells:
            assert isinstance(center, QgsPointXY)
            assert not geom.isEmpty()
            assert geom.type() == QgsWkbTypes.PolygonGeometry
            # Hexagon exterior ring: 6 vertices + closing = 7 points
            exterior = geom.asPolygon()[0]
            assert len(exterior) == 7
            # Area should match hexagon formula
            assert abs(geom.area() - expected_area) < 1.0


# ---------------------------------------------------------------------------
# T4.7 - T4.9: auto_cell_size
# ---------------------------------------------------------------------------

class TestAutoCellSize:
    """Tests for auto_cell_size()."""

    def test_auto_cell_size_square(self, qgis_app):
        """T4.7: extent 1000x1000, target=100 -> cell_size=100 (factor=1.0)."""
        extent = QgsRectangle(0, 0, 1000, 1000)
        cell_size = auto_cell_size(extent, 100, 'square')
        expected = math.sqrt(1000 * 1000 / 100) * 1.0  # = 100
        assert abs(cell_size - expected) < 0.01

    def test_auto_cell_size_hex(self, qgis_app):
        """T4.8: extent 1000x1000, target=100 -> cell_size ~ 107."""
        extent = QgsRectangle(0, 0, 1000, 1000)
        cell_size = auto_cell_size(extent, 100, 'hexagonal')
        expected = math.sqrt(1000 * 1000 / 100) * 1.07  # = 107
        assert abs(cell_size - expected) < 0.01

    def test_packing_factors_correct(self, qgis_app):
        """T4.9: verify packing factors for all grid types."""
        extent = QgsRectangle(0, 0, 1000, 1000)
        base = math.sqrt(1000 * 1000 / 100)  # = 100

        # square: factor = 1.0
        assert abs(auto_cell_size(extent, 100, 'square') - base * 1.0) < 0.01
        # hexagonal: factor = 1.07
        assert abs(auto_cell_size(extent, 100, 'hexagonal') - base * 1.07) < 0.01
        # circle: factor = 1.07
        assert abs(auto_cell_size(extent, 100, 'circle') - base * 1.07) < 0.01
        # triangular: factor = 1.52
        assert abs(auto_cell_size(extent, 100, 'triangular') - base * 1.52) < 0.01


# ---------------------------------------------------------------------------
# T4.10 - T4.14: nearest_grid_point
# ---------------------------------------------------------------------------

class TestNearestGridPointSquare:
    """Tests for nearest_grid_point() with square grid."""

    def test_snaps_to_nearest(self, qgis_app):
        """T4.10: spacing=10, point(13,27) -> (10,30)."""
        result = nearest_grid_point(QgsPointXY(13, 27), 10, 'square')
        assert abs(result.x() - 10.0) < 1e-6
        assert abs(result.y() - 30.0) < 1e-6

    def test_at_grid_intersection(self, qgis_app):
        """T4.11: spacing=10, point(20,30) -> (20,30)."""
        result = nearest_grid_point(QgsPointXY(20, 30), 10, 'square')
        assert abs(result.x() - 20.0) < 1e-6
        assert abs(result.y() - 30.0) < 1e-6


class TestNearestGridPointHex:
    """Tests for nearest_grid_point() with hexagonal grid."""

    def test_at_known_center(self, qgis_app):
        """T4.12: point at hex grid center returns same center."""
        spacing = 10
        R = spacing / math.sqrt(3)
        col_sp = 1.5 * R
        # Column 0, row 0 -> center at (0, 0)
        center = QgsPointXY(0.0, 0.0)
        result = nearest_grid_point(center, spacing, 'hexagonal')
        assert abs(result.x() - 0.0) < 1e-3
        assert abs(result.y() - 0.0) < 1e-3

    def test_closest_center(self, qgis_app):
        """T4.13: point closer to one hex center returns the closer one."""
        spacing = 10
        R = spacing / math.sqrt(3)
        col_sp = 1.5 * R
        # Col 0 center at (0, 0); col 1 center at (col_sp, spacing/2)
        # A point very close to col 0 center
        test_point = QgsPointXY(1.0, 1.0)
        result = nearest_grid_point(test_point, spacing, 'hexagonal')
        # Should snap to (0, 0) -- the nearest center
        assert abs(result.x() - 0.0) < 1e-3
        assert abs(result.y() - 0.0) < 1e-3

    def test_midpoint_no_crash(self, qgis_app):
        """T4.14: point at exact midpoint between two hex centers returns one deterministically."""
        spacing = 10
        R = spacing / math.sqrt(3)
        col_sp = 1.5 * R
        # Midpoint between col 0 row 0 (0,0) and col 0 row 1 (0, 10)
        midpoint = QgsPointXY(0.0, 5.0)
        result = nearest_grid_point(midpoint, spacing, 'hexagonal')
        # Should return one of the two centers without crashing
        assert isinstance(result, QgsPointXY)
        # Must be a valid grid point -- either (0,0) or (0,10)
        valid = (
            (abs(result.x() - 0.0) < 1e-3 and abs(result.y() - 0.0) < 1e-3)
            or (abs(result.x() - 0.0) < 1e-3 and abs(result.y() - 10.0) < 1e-3)
        )
        assert valid


# ---------------------------------------------------------------------------
# T4.15: triangular grid
# ---------------------------------------------------------------------------

class TestTriangularGrid:
    """Tests for triangular grid generation and snapping."""

    def test_triangular_point_grid_count(self, qgis_app):
        """T4.15a: extent(0,0,100,100) spacing=10 yields reasonable point count.

        Row height h = 10*sqrt(3)/2 ~ 8.66.  Rows covering [0,100]: ~12 rows.
        Each row has ~20 columns (each s/2=5 wide).  With boundary padding
        to ensure full coverage, expect 200-400 points.
        """
        extent = QgsRectangle(0, 0, 100, 100)
        points = generate_point_grid(extent, 10, 'triangular')
        assert 200 <= len(points) <= 400

    def test_triangular_point_grid_covers_extent(self, qgis_app):
        """T4.15b: all triangle centroids lie within a padded extent."""
        extent = QgsRectangle(0, 0, 100, 100)
        spacing = 10
        h = spacing * math.sqrt(3) / 2
        pad = spacing  # one cell buffer
        points = generate_point_grid(extent, spacing, 'triangular')
        assert len(points) > 0
        for p in points:
            assert p.x() >= -pad
            assert p.y() >= -pad
            assert p.x() <= 100 + pad
            assert p.y() <= 100 + pad

    def test_triangular_cell_polygons_are_triangles(self, qgis_app):
        """T4.15c: each polygon has 4 vertices (3 + closing) and correct area.

        Each equilateral triangle has side = s, so area = (sqrt(3)/4) * s^2.
        """
        extent = QgsRectangle(0, 0, 50, 50)
        spacing = 10
        expected_area = (math.sqrt(3) / 4) * spacing ** 2
        cells = generate_cell_polygons(extent, spacing, 'triangular')
        assert len(cells) > 0
        for center, geom in cells:
            assert isinstance(center, QgsPointXY)
            assert not geom.isEmpty()
            assert geom.type() == QgsWkbTypes.PolygonGeometry
            exterior = geom.asPolygon()[0]
            assert len(exterior) == 4, (
                f"Expected 4 vertices (triangle + close), got {len(exterior)}"
            )
            assert geom.area() == pytest.approx(expected_area, rel=0.01)

    def test_triangular_cell_union_covers_extent(self, qgis_app):
        """T4.15d: union of all triangles covers the input extent."""
        extent = QgsRectangle(0, 0, 50, 50)
        cells = generate_cell_polygons(extent, 10, 'triangular')
        polygons = [geom for _, geom in cells]
        union = QgsGeometry.unaryUnion(polygons)
        extent_geom = QgsGeometry.fromRect(extent)
        assert union.contains(extent_geom)

    def test_nearest_triangular_at_centroid(self, qgis_app):
        """T4.15e: a known triangle centroid snaps to itself."""
        spacing = 10
        h = spacing * math.sqrt(3) / 2
        # Up triangle at col=0, row=0: centroid = ((0+1)*s/2, (0+1/3)*h)
        cx = (0 + 1) * spacing / 2.0
        cy = (0 + 1.0 / 3.0) * h
        result = nearest_grid_point(QgsPointXY(cx, cy), spacing, 'triangular')
        assert abs(result.x() - cx) < 1e-6
        assert abs(result.y() - cy) < 1e-6

    def test_nearest_triangular_consistency(self, qgis_app):
        """T4.15f: points within a triangle snap to that triangle's centroid.

        Pick several points inside a known up-triangle and verify they all
        snap to the same centroid.  Up triangle at col=0, row=0 has vertices:
            (0, 0), (s, 0), (s/2, h)
        Centroid: ((0+1)*s/2, (0+1/3)*h) = (s/2, h/3)
        """
        spacing = 10
        h = spacing * math.sqrt(3) / 2
        cx = (0 + 1) * spacing / 2.0
        cy = (0 + 1.0 / 3.0) * h
        # Test points near the centroid (well inside the triangle)
        offsets = [(0, 0), (0.3, 0.2), (-0.3, 0.1), (0.1, -0.2)]
        for dx, dy in offsets:
            test_pt = QgsPointXY(cx + dx, cy + dy)
            result = nearest_grid_point(test_pt, spacing, 'triangular')
            assert abs(result.x() - cx) < 1e-6, (
                f"offset ({dx},{dy}): expected cx={cx}, got {result.x()}"
            )
            assert abs(result.y() - cy) < 1e-6, (
                f"offset ({dx},{dy}): expected cy={cy}, got {result.y()}"
            )


# ---------------------------------------------------------------------------
# T4.16: generate_cell_polygons padding coverage
# ---------------------------------------------------------------------------

class TestCellPolygonsCoverage:
    """Tests for polygon coverage of extent."""

    def test_union_covers_extent(self, qgis_app):
        """T4.16: union of all square cells covers entire extent."""
        extent = QgsRectangle(0, 0, 100, 100)
        cells = generate_cell_polygons(extent, 10, 'square')
        polygons = [geom for _, geom in cells]
        union = QgsGeometry.unaryUnion(polygons)
        extent_geom = QgsGeometry.fromRect(extent)
        # The union must contain the entire extent
        assert union.contains(extent_geom)


# ---------------------------------------------------------------------------
# Grid origin consistency: Tile Fill grids align with Snap to Grid snapping
# ---------------------------------------------------------------------------

class TestGridOriginConsistency:
    """Verify that grid generators and grid snapping functions share the same origin."""

    def test_square_centers_match_nearest_grid_point(self, qgis_app):
        """Every centre from generate_point_grid round-trips through nearest_grid_point."""
        extent = QgsRectangle(50, 70, 250, 270)
        spacing = 20.0
        points = generate_point_grid(extent, spacing, 'square')
        assert len(points) > 0
        for pt in points:
            snapped = nearest_grid_point(pt, spacing, 'square')
            assert abs(snapped.x() - pt.x()) < 1e-6, (
                f"Square centre ({pt.x()},{pt.y()}) doesn't round-trip: "
                f"snapped to ({snapped.x()},{snapped.y()})"
            )
            assert abs(snapped.y() - pt.y()) < 1e-6, (
                f"Square centre ({pt.x()},{pt.y()}) doesn't round-trip: "
                f"snapped to ({snapped.x()},{snapped.y()})"
            )

    def test_hex_centers_match_nearest_grid_point(self, qgis_app):
        """Every centre from generate_point_grid(hex) round-trips through nearest_grid_point."""
        extent = QgsRectangle(50, 70, 250, 270)
        spacing = 20.0
        points = generate_point_grid(extent, spacing, 'hexagonal')
        assert len(points) > 0
        for pt in points:
            snapped = nearest_grid_point(pt, spacing, 'hexagonal')
            assert abs(snapped.x() - pt.x()) < 1e-3, (
                f"Hex centre ({pt.x():.4f},{pt.y():.4f}) doesn't round-trip: "
                f"snapped to ({snapped.x():.4f},{snapped.y():.4f})"
            )
            assert abs(snapped.y() - pt.y()) < 1e-3, (
                f"Hex centre ({pt.x():.4f},{pt.y():.4f}) doesn't round-trip: "
                f"snapped to ({snapped.x():.4f},{snapped.y():.4f})"
            )

    def test_square_corners_match_nearest_grid_vertex(self, qgis_app):
        """Vertices of square cells round-trip through nearest_grid_vertex."""
        extent = QgsRectangle(50, 70, 150, 170)
        spacing = 20.0
        cells = generate_cell_polygons(extent, spacing, 'square')
        assert len(cells) > 0
        for center, geom in cells:
            exterior = geom.asPolygon()[0]
            for vertex in exterior[:-1]:  # skip closing vertex
                snapped = nearest_grid_vertex(vertex, spacing, 'square')
                assert abs(snapped.x() - vertex.x()) < 1e-6, (
                    f"Square corner ({vertex.x()},{vertex.y()}) doesn't round-trip: "
                    f"snapped to ({snapped.x()},{snapped.y()})"
                )
                assert abs(snapped.y() - vertex.y()) < 1e-6, (
                    f"Square corner ({vertex.x()},{vertex.y()}) doesn't round-trip: "
                    f"snapped to ({snapped.x()},{snapped.y()})"
                )

    def test_hex_vertices_match_nearest_grid_vertex(self, qgis_app):
        """Vertices of hex cells round-trip through nearest_grid_vertex."""
        extent = QgsRectangle(50, 70, 150, 170)
        spacing = 20.0
        cells = generate_cell_polygons(extent, spacing, 'hexagonal')
        assert len(cells) > 0
        for center, geom in cells:
            exterior = geom.asPolygon()[0]
            for vertex in exterior[:-1]:
                snapped = nearest_grid_vertex(
                    QgsPointXY(vertex.x(), vertex.y()), spacing, 'hexagonal',
                )
                assert abs(snapped.x() - vertex.x()) < 0.01, (
                    f"Hex vertex ({vertex.x():.4f},{vertex.y():.4f}) doesn't round-trip: "
                    f"snapped to ({snapped.x():.4f},{snapped.y():.4f})"
                )
                assert abs(snapped.y() - vertex.y()) < 0.01, (
                    f"Hex vertex ({vertex.x():.4f},{vertex.y():.4f}) doesn't round-trip: "
                    f"snapped to ({snapped.x():.4f},{snapped.y():.4f})"
                )

    def test_negative_extent_square_consistent(self, qgis_app):
        """Square grid with negative coordinates still aligns with snapping."""
        extent = QgsRectangle(-100, -80, -20, -10)
        spacing = 15.0
        points = generate_point_grid(extent, spacing, 'square')
        assert len(points) > 0
        for pt in points:
            snapped = nearest_grid_point(pt, spacing, 'square')
            assert abs(snapped.x() - pt.x()) < 1e-6
            assert abs(snapped.y() - pt.y()) < 1e-6

    def test_negative_extent_hex_consistent(self, qgis_app):
        """Hex grid with negative coordinates still aligns with snapping."""
        extent = QgsRectangle(-100, -80, -20, -10)
        spacing = 15.0
        points = generate_point_grid(extent, spacing, 'hexagonal')
        assert len(points) > 0
        for pt in points:
            snapped = nearest_grid_point(pt, spacing, 'hexagonal')
            assert abs(snapped.x() - pt.x()) < 1e-3
            assert abs(snapped.y() - pt.y()) < 1e-3
