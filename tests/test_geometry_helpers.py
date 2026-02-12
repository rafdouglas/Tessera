"""Tests for geometry_helpers module."""
import math

import pytest
from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes

from tessera.infrastructure.geometry_helpers import (
    extract_polygons,
    clamp,
    regular_polygon,
    safe_pole_of_inaccessibility,
    split_polygon_by_fraction,
    scale_geometry,
)


# ---------------------------------------------------------------------------
# T1.1 - T1.5: extract_polygons
# ---------------------------------------------------------------------------

class TestExtractPolygons:
    """Tests for extract_polygons()."""

    def test_returns_polygon_unchanged(self, qgis_app):
        """T1.1: Given a valid polygon, returns same polygon with same area."""
        ring = [
            QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10),
            QgsPointXY(0, 0),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])
        result = extract_polygons(geom)
        assert not result.isEmpty()
        assert result.type() == QgsWkbTypes.PolygonGeometry
        assert abs(result.area() - geom.area()) < 1e-6

    def test_filters_degenerate_components(self, qgis_app):
        """T1.2: Collection of polygon+point+line returns only polygon."""
        ring = [
            QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10),
            QgsPointXY(0, 0),
        ]
        polygon = QgsGeometry.fromPolygonXY([ring])
        point = QgsGeometry.fromPointXY(QgsPointXY(50, 50))
        line = QgsGeometry.fromPolylineXY([QgsPointXY(0, 0), QgsPointXY(5, 5)])

        collection = QgsGeometry.collectGeometry([polygon, point, line])
        result = extract_polygons(collection)
        assert not result.isEmpty()
        assert result.type() == QgsWkbTypes.PolygonGeometry
        assert abs(result.area() - 100.0) < 1e-6

    def test_returns_empty_for_all_degenerate(self, qgis_app):
        """T1.3: Collection of only point+line returns empty geometry."""
        point = QgsGeometry.fromPointXY(QgsPointXY(50, 50))
        line = QgsGeometry.fromPolylineXY([QgsPointXY(0, 0), QgsPointXY(5, 5)])

        collection = QgsGeometry.collectGeometry([point, line])
        result = extract_polygons(collection)
        assert result.isEmpty()

    def test_handles_empty_geometry(self, qgis_app):
        """T1.4: Empty QgsGeometry returns empty."""
        geom = QgsGeometry()
        result = extract_polygons(geom)
        assert result.isEmpty()

    def test_handles_multipolygon(self, qgis_app):
        """T1.5: MultiPolygon returned unchanged with type() == PolygonGeometry."""
        ring1 = [
            QgsPointXY(0, 0), QgsPointXY(5, 0),
            QgsPointXY(5, 5), QgsPointXY(0, 5),
            QgsPointXY(0, 0),
        ]
        ring2 = [
            QgsPointXY(10, 10), QgsPointXY(15, 10),
            QgsPointXY(15, 15), QgsPointXY(10, 15),
            QgsPointXY(10, 10),
        ]
        geom = QgsGeometry.fromMultiPolygonXY([[ring1], [ring2]])
        result = extract_polygons(geom)
        assert not result.isEmpty()
        assert result.type() == QgsWkbTypes.PolygonGeometry
        assert abs(result.area() - geom.area()) < 1e-6


# ---------------------------------------------------------------------------
# T1.6 - T1.8: clamp
# ---------------------------------------------------------------------------

class TestClamp:
    """Tests for clamp()."""

    def test_within_range(self):
        """T1.6: clamp(5, 0, 10) returns 5."""
        assert clamp(5, 0, 10) == 5

    def test_below_range(self):
        """T1.7: clamp(-5, 0, 10) returns 0."""
        assert clamp(-5, 0, 10) == 0

    def test_above_range(self):
        """T1.8: clamp(15, 0, 10) returns 10."""
        assert clamp(15, 0, 10) == 10


# ---------------------------------------------------------------------------
# T1.9 - T1.13: regular_polygon
# ---------------------------------------------------------------------------

class TestRegularPolygon:
    """Tests for regular_polygon()."""

    def test_hexagon_has_6_vertices(self, qgis_app):
        """T1.9: Hexagon has 6 vertices, all at distance 100 from center."""
        center = QgsPointXY(0, 0)
        geom = regular_polygon(center, 100, 6)
        # Exterior ring of a polygon: vertices + closing vertex
        exterior = geom.asPolygon()[0]
        # Last vertex duplicates the first (closed ring), so unique = len - 1
        assert len(exterior) - 1 == 6
        for pt in exterior[:-1]:
            dist = math.hypot(pt.x() - center.x(), pt.y() - center.y())
            assert abs(dist - 100) < 1e-6

    def test_square_area(self, qgis_app):
        """T1.10: Square (n=4, rotation=45) has area = 2 * 100^2 = 20000."""
        center = QgsPointXY(0, 0)
        geom = regular_polygon(center, 100, 4, rotation=45)
        expected_area = 2 * 100 ** 2  # 20000
        assert abs(geom.area() - expected_area) < 1.0

    def test_circle_approximation(self, qgis_app):
        """T1.11: 64-sided polygon approximates circle area pi*r^2."""
        center = QgsPointXY(0, 0)
        geom = regular_polygon(center, 50, 64)
        expected_area = math.pi * 50 ** 2
        assert abs(geom.area() - expected_area) < 15.0  # 64-gon ~0.16% error

    def test_triangle_area(self, qgis_app):
        """T1.12: Equilateral triangle area = (3*sqrt(3)/4) * r^2."""
        center = QgsPointXY(0, 0)
        geom = regular_polygon(center, 100, 3)
        expected_area = (3 * math.sqrt(3) / 4) * 100 ** 2
        assert abs(geom.area() - expected_area) < 1.0

    def test_rotation_changes_vertices_not_area(self, qgis_app):
        """T1.13: Two hexagons with different rotation have equal area but different vertices."""
        center = QgsPointXY(0, 0)
        geom_a = regular_polygon(center, 100, 6, rotation=0)
        geom_b = regular_polygon(center, 100, 6, rotation=30)
        # Same area
        assert abs(geom_a.area() - geom_b.area()) < 1e-6
        # Different vertex positions
        verts_a = geom_a.asPolygon()[0][:-1]
        verts_b = geom_b.asPolygon()[0][:-1]
        any_different = any(
            abs(a.x() - b.x()) > 1e-6 or abs(a.y() - b.y()) > 1e-6
            for a, b in zip(verts_a, verts_b)
        )
        assert any_different


# ---------------------------------------------------------------------------
# T1.14 - T1.16: safe_pole_of_inaccessibility
# ---------------------------------------------------------------------------

class TestSafePoleOfInaccessibility:
    """Tests for safe_pole_of_inaccessibility()."""

    def test_simple_square(self, qgis_app):
        """T1.14: Square (0,0)-(100,100) pole near (50,50), distance ~50."""
        ring = [
            QgsPointXY(0, 0), QgsPointXY(100, 0),
            QgsPointXY(100, 100), QgsPointXY(0, 100),
            QgsPointXY(0, 0),
        ]
        geom = QgsGeometry.fromPolygonXY([ring])
        point, distance = safe_pole_of_inaccessibility(geom, tolerance=0.1)
        assert abs(point.x() - 50) < 1.0
        assert abs(point.y() - 50) < 1.0
        assert abs(distance - 50) < 1.0

    def test_multipolygon_picks_best(self, qgis_app):
        """T1.15: MultiPolygon with small(10x10) + large(100x100) returns pole inside large."""
        small = [
            QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10),
            QgsPointXY(0, 0),
        ]
        large = [
            QgsPointXY(200, 200), QgsPointXY(300, 200),
            QgsPointXY(300, 300), QgsPointXY(200, 300),
            QgsPointXY(200, 200),
        ]
        geom = QgsGeometry.fromMultiPolygonXY([[small], [large]])
        point, distance = safe_pole_of_inaccessibility(geom, tolerance=0.1)
        # Point should be inside the large polygon (near 250, 250)
        assert 200 < point.x() < 300
        assert 200 < point.y() < 300
        # Distance should be ~50 (half of 100)
        assert distance > 4.0  # definitely larger than small polygon's ~5

    def test_concave_polygon_inside(self, concave_polygon, qgis_app):
        """T1.16: Concave polygon pole is inside the polygon (not at centroid)."""
        geom = concave_polygon.geometry()
        point, distance = safe_pole_of_inaccessibility(geom, tolerance=0.1)
        # The pole must actually be inside the polygon
        pole_geom = QgsGeometry.fromPointXY(point)
        assert geom.contains(pole_geom)
        assert distance > 0


# ---------------------------------------------------------------------------
# T1.17 - T1.18: stubs
# ---------------------------------------------------------------------------

class TestScaleGeometry:
    """Tests for scale_geometry()."""

    def test_scale_factor_2_quadruples_area(self, qgis_app):
        """Scaling by 2.0 quadruples polygon area (area scales as square of linear)."""
        ring = [
            QgsPointXY(4, 4), QgsPointXY(6, 4),
            QgsPointXY(6, 6), QgsPointXY(4, 6),
            QgsPointXY(4, 4),
        ]
        square = QgsGeometry.fromPolygonXY([ring])
        center = QgsPointXY(5, 5)
        scaled = scale_geometry(square, center, 2.0)
        assert abs(scaled.area() - square.area() * 4) < 1e-6

    def test_scale_factor_half_quarters_area(self, qgis_app):
        """Scaling by 0.5 quarters polygon area."""
        ring = [
            QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10),
            QgsPointXY(0, 0),
        ]
        square = QgsGeometry.fromPolygonXY([ring])
        center = QgsPointXY(5, 5)
        scaled = scale_geometry(square, center, 0.5)
        assert abs(scaled.area() - square.area() * 0.25) < 1e-6

    def test_scale_factor_one_no_change(self, qgis_app):
        """Scaling by 1.0 returns geometry with identical area."""
        ring = [
            QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10),
            QgsPointXY(0, 0),
        ]
        square = QgsGeometry.fromPolygonXY([ring])
        center = QgsPointXY(5, 5)
        scaled = scale_geometry(square, center, 1.0)
        assert abs(scaled.area() - square.area()) < 1e-6

    def test_center_preserved_after_scaling(self, qgis_app):
        """The center point remains fixed after scaling."""
        ring = [
            QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10),
            QgsPointXY(0, 0),
        ]
        square = QgsGeometry.fromPolygonXY([ring])
        center = QgsPointXY(5, 5)
        scaled = scale_geometry(square, center, 3.0)
        centroid = scaled.centroid().asPoint()
        assert abs(centroid.x() - 5.0) < 1e-4
        assert abs(centroid.y() - 5.0) < 1e-4

    def test_empty_geometry_returns_empty(self, qgis_app):
        """Empty geometry input returns empty geometry."""
        empty = QgsGeometry()
        center = QgsPointXY(0, 0)
        result = scale_geometry(empty, center, 2.0)
        assert result.isEmpty()

    def test_multipolygon_scaling(self, qgis_app):
        """MultiPolygon scales all parts around the same center."""
        ring1 = [
            QgsPointXY(0, 0), QgsPointXY(2, 0),
            QgsPointXY(2, 2), QgsPointXY(0, 2),
            QgsPointXY(0, 0),
        ]
        ring2 = [
            QgsPointXY(5, 5), QgsPointXY(7, 5),
            QgsPointXY(7, 7), QgsPointXY(5, 7),
            QgsPointXY(5, 5),
        ]
        mp = QgsGeometry.fromMultiPolygonXY([[ring1], [ring2]])
        center = QgsPointXY(3.5, 3.5)
        scaled = scale_geometry(mp, center, 2.0)
        assert abs(scaled.area() - mp.area() * 4) < 1e-4


# ---------------------------------------------------------------------------
# T2.1 - T2.15: split_polygon_by_fraction
# ---------------------------------------------------------------------------

def _make_unit_square():
    """Create a 100x100 unit square at origin (projected CRS units)."""
    ring = [
        QgsPointXY(0, 0), QgsPointXY(100, 0),
        QgsPointXY(100, 100), QgsPointXY(0, 100),
        QgsPointXY(0, 0),
    ]
    return QgsGeometry.fromPolygonXY([ring])


def _make_l_shape():
    """Create an L-shaped concave polygon.

    Vertices form an L:
        (0,0)-(60,0)-(60,40)-(40,40)-(40,100)-(0,100)
    Area = 60*40 + 40*60 = 2400 + 2400 = 4800
    Actually: bottom bar 60x40=2400, left column 40x60=2400, total=4800
    """
    ring = [
        QgsPointXY(0, 0), QgsPointXY(60, 0),
        QgsPointXY(60, 40), QgsPointXY(40, 40),
        QgsPointXY(40, 100), QgsPointXY(0, 100),
        QgsPointXY(0, 0),
    ]
    return QgsGeometry.fromPolygonXY([ring])


class TestSplitPolygonByFraction:
    """Tests for split_polygon_by_fraction()."""

    def test_split_horizontal_simple_square(self, qgis_app):
        """T2.1: 50% horizontal split of square, filled area ~ 0.5 * total."""
        geom = _make_unit_square()
        total_area = geom.area()
        filled, remainder = split_polygon_by_fraction(geom, 0.5, 'horizontal')

        assert not filled.isEmpty()
        assert not remainder.isEmpty()
        ratio = filled.area() / total_area
        assert abs(ratio - 0.5) < 0.001, \
            f"Expected ratio ~0.5, got {ratio:.6f}"

    def test_split_vertical_simple_square(self, qgis_app):
        """T2.2: 50% vertical split of square, filled area ~ 0.5 * total."""
        geom = _make_unit_square()
        total_area = geom.area()
        filled, remainder = split_polygon_by_fraction(geom, 0.5, 'vertical')

        assert not filled.isEmpty()
        assert not remainder.isEmpty()
        ratio = filled.area() / total_area
        assert abs(ratio - 0.5) < 0.001, \
            f"Expected ratio ~0.5, got {ratio:.6f}"

    def test_split_horizontal_25_percent(self, qgis_app):
        """T2.3: 25% horizontal split, area ratio within 0.1%."""
        geom = _make_unit_square()
        total_area = geom.area()
        filled, remainder = split_polygon_by_fraction(geom, 0.25, 'horizontal')

        assert not filled.isEmpty()
        assert not remainder.isEmpty()
        ratio = filled.area() / total_area
        assert abs(ratio - 0.25) < 0.001, \
            f"Expected ratio ~0.25, got {ratio:.6f}"

    def test_split_horizontal_75_percent(self, qgis_app):
        """T2.4: 75% horizontal split, area ratio within 0.1%."""
        geom = _make_unit_square()
        total_area = geom.area()
        filled, remainder = split_polygon_by_fraction(geom, 0.75, 'horizontal')

        assert not filled.isEmpty()
        assert not remainder.isEmpty()
        ratio = filled.area() / total_area
        assert abs(ratio - 0.75) < 0.001, \
            f"Expected ratio ~0.75, got {ratio:.6f}"

    def test_split_fraction_zero_returns_empty_filled(self, qgis_app):
        """T2.5: fraction=0 returns empty filled, remainder = full geom."""
        geom = _make_unit_square()
        total_area = geom.area()
        filled, remainder = split_polygon_by_fraction(geom, 0.0, 'horizontal')

        assert filled.isEmpty()
        assert not remainder.isEmpty()
        assert abs(remainder.area() - total_area) < 1e-6

    def test_split_fraction_one_returns_empty_remainder(self, qgis_app):
        """T2.6: fraction=1 returns filled = full geom, remainder empty."""
        geom = _make_unit_square()
        total_area = geom.area()
        filled, remainder = split_polygon_by_fraction(geom, 1.0, 'horizontal')

        assert not filled.isEmpty()
        assert remainder.isEmpty()
        assert abs(filled.area() - total_area) < 1e-6

    def test_split_diagonal_45_area_ratio(self, qgis_app):
        """T2.7: 50% diagonal 45 split, area check."""
        geom = _make_unit_square()
        total_area = geom.area()
        filled, remainder = split_polygon_by_fraction(geom, 0.5, 'diagonal_45')

        assert not filled.isEmpty()
        assert not remainder.isEmpty()
        ratio = filled.area() / total_area
        assert abs(ratio - 0.5) < 0.001, \
            f"Expected ratio ~0.5, got {ratio:.6f}"

    def test_split_diagonal_135_area_ratio(self, qgis_app):
        """T2.8: 50% diagonal 135 split, area check."""
        geom = _make_unit_square()
        total_area = geom.area()
        filled, remainder = split_polygon_by_fraction(
            geom, 0.5, 'diagonal_135')

        assert not filled.isEmpty()
        assert not remainder.isEmpty()
        ratio = filled.area() / total_area
        assert abs(ratio - 0.5) < 0.001, \
            f"Expected ratio ~0.5, got {ratio:.6f}"

    def test_split_radial_area_ratio(self, qgis_app):
        """T2.9: 50% radial split, area check."""
        geom = _make_unit_square()
        total_area = geom.area()
        filled, remainder = split_polygon_by_fraction(geom, 0.5, 'radial')

        assert not filled.isEmpty()
        assert not remainder.isEmpty()
        ratio = filled.area() / total_area
        assert abs(ratio - 0.5) < 0.001, \
            f"Expected ratio ~0.5, got {ratio:.6f}"

    def test_split_radial_small_fraction(self, qgis_app):
        """T2.10: 10% radial split, area check."""
        geom = _make_unit_square()
        total_area = geom.area()
        filled, remainder = split_polygon_by_fraction(geom, 0.1, 'radial')

        assert not filled.isEmpty()
        assert not remainder.isEmpty()
        ratio = filled.area() / total_area
        assert abs(ratio - 0.1) < 0.001, \
            f"Expected ratio ~0.1, got {ratio:.6f}"

    def test_split_polygon_with_holes(self, polygon_with_holes, qgis_app):
        """T2.11: Split polygon with interior hole, filled+remainder ~ original."""
        geom = polygon_with_holes.geometry()
        total_area = geom.area()  # 84.0 (100 - 16)
        filled, remainder = split_polygon_by_fraction(
            geom, 0.5, 'horizontal')

        assert not filled.isEmpty()
        assert not remainder.isEmpty()
        combined = filled.area() + remainder.area()
        assert abs(combined - total_area) / total_area < 0.005, \
            f"Combined area {combined:.4f} != total {total_area:.4f}"

    def test_split_multipolygon(self, qgis_app):
        """T2.12: Split multipolygon, area validation."""
        mainland = [
            QgsPointXY(0, 0), QgsPointXY(100, 0),
            QgsPointXY(100, 100), QgsPointXY(0, 100),
            QgsPointXY(0, 0),
        ]
        island = [
            QgsPointXY(150, 150), QgsPointXY(170, 150),
            QgsPointXY(170, 170), QgsPointXY(150, 170),
            QgsPointXY(150, 150),
        ]
        geom = QgsGeometry.fromMultiPolygonXY([[mainland], [island]])
        total_area = geom.area()  # 10000 + 400 = 10400
        filled, remainder = split_polygon_by_fraction(
            geom, 0.5, 'horizontal')

        assert not filled.isEmpty()
        assert not remainder.isEmpty()
        ratio = filled.area() / total_area
        assert abs(ratio - 0.5) < 0.001, \
            f"Expected ratio ~0.5, got {ratio:.6f}"

    def test_split_concave_polygon(self, qgis_app):
        """T2.13: L-shape concave polygon, area check."""
        geom = _make_l_shape()
        total_area = geom.area()
        filled, remainder = split_polygon_by_fraction(
            geom, 0.5, 'horizontal')

        assert not filled.isEmpty()
        assert not remainder.isEmpty()
        ratio = filled.area() / total_area
        assert abs(ratio - 0.5) < 0.001, \
            f"Expected ratio ~0.5, got {ratio:.6f}"

    def test_split_result_geometries_are_valid(self, qgis_app):
        """T2.14: Both results pass isGeosValid()."""
        geom = _make_unit_square()
        for orientation in ('horizontal', 'vertical', 'diagonal_45',
                            'diagonal_135', 'radial'):
            filled, remainder = split_polygon_by_fraction(
                geom, 0.5, orientation)
            if not filled.isEmpty():
                assert filled.isGeosValid(), \
                    f"Filled not valid for {orientation}"
            if not remainder.isEmpty():
                assert remainder.isGeosValid(), \
                    f"Remainder not valid for {orientation}"

    def test_split_filled_plus_remainder_equals_original(self, qgis_app):
        """T2.15: area(filled) + area(remainder) ~ area(original) within 0.5%."""
        geom = _make_unit_square()
        total_area = geom.area()
        for orientation in ('horizontal', 'vertical', 'diagonal_45',
                            'diagonal_135', 'radial'):
            for frac in (0.1, 0.3, 0.5, 0.7, 0.9):
                filled, remainder = split_polygon_by_fraction(
                    geom, frac, orientation)
                combined = filled.area() + remainder.area()
                assert abs(combined - total_area) / total_area < 0.005, \
                    (f"Combined {combined:.4f} != total {total_area:.4f} "
                     f"for {orientation} frac={frac}")
