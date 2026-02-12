"""Tests for crs_manager module."""
import pytest
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
)

from tessera.infrastructure.crs_manager import (
    EQUAL_AREA_PROJS,
    WorkingCRS,
    is_equal_area,
    needs_antimeridian_split,
)


# ---------------------------------------------------------------------------
# T2.1 - T2.6: is_equal_area
# ---------------------------------------------------------------------------

def test_is_equal_area_detects_equal_earth(qgis_app):
    """T2.1: is_equal_area detects EPSG:8857 (Equal Earth) as equal-area."""
    crs = QgsCoordinateReferenceSystem.fromEpsgId(8857)
    assert crs.isValid()
    assert is_equal_area(crs) is True


def test_is_equal_area_detects_albers(qgis_app):
    """T2.2: is_equal_area detects Albers (+proj=aea) as equal-area."""
    crs = QgsCoordinateReferenceSystem()
    ok = crs.createFromProj(
        '+proj=aea +lat_1=29.5 +lat_2=45.5 +lat_0=37.5 +lon_0=-96 '
        '+datum=WGS84 +units=m +no_defs'
    )
    assert ok
    assert is_equal_area(crs) is True


def test_is_equal_area_rejects_wgs84(qgis_app):
    """T2.3: is_equal_area rejects EPSG:4326 (WGS 84 geographic)."""
    crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
    assert crs.isValid()
    assert is_equal_area(crs) is False


def test_is_equal_area_rejects_mercator(qgis_app):
    """T2.4: is_equal_area rejects EPSG:3857 (Web Mercator)."""
    crs = QgsCoordinateReferenceSystem.fromEpsgId(3857)
    assert crs.isValid()
    assert is_equal_area(crs) is False


def test_is_equal_area_detects_laea(qgis_app):
    """T2.5: is_equal_area detects Lambert Azimuthal Equal Area (+proj=laea)."""
    crs = QgsCoordinateReferenceSystem()
    ok = crs.createFromProj(
        '+proj=laea +lat_0=52 +lon_0=10 +datum=WGS84 +units=m +no_defs'
    )
    assert ok
    assert is_equal_area(crs) is True


def test_is_equal_area_detects_mollweide(qgis_app):
    """T2.6: is_equal_area detects Mollweide (+proj=moll)."""
    crs = QgsCoordinateReferenceSystem()
    ok = crs.createFromProj(
        '+proj=moll +lon_0=0 +datum=WGS84 +units=m +no_defs'
    )
    assert ok
    assert is_equal_area(crs) is True


# ---------------------------------------------------------------------------
# T2.7 - T2.15: WorkingCRS
# ---------------------------------------------------------------------------

def test_working_crs_uses_source_when_already_equal_area(qgis_app):
    """T2.7: WorkingCRS uses source CRS when it is already equal-area."""
    source_crs = QgsCoordinateReferenceSystem.fromEpsgId(8857)
    extent = QgsRectangle(-180, -90, 180, 90)
    wcrs = WorkingCRS(source_crs, extent)
    assert wcrs.working_crs == source_crs


def test_working_crs_constructs_albers_for_local_wgs84(qgis_app):
    """T2.8: WorkingCRS constructs Albers for local WGS84 data (France extent)."""
    source_crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
    extent = QgsRectangle(2, 42, 8, 51)  # France approx
    wcrs = WorkingCRS(source_crs, extent)

    proj_str = wcrs.working_crs.toProj()
    assert '+proj=aea' in proj_str

    # Snyder 1/6 parallels for yMin=42, yMax=51
    # lat_1 = 42 + 9/6 = 43.5
    # lat_2 = 51 - 9/6 = 49.5
    assert '+lat_1=43.5' in proj_str
    assert '+lat_2=49.5' in proj_str


def test_working_crs_uses_equal_earth_for_global_extent(qgis_app):
    """T2.9: WorkingCRS uses Equal Earth (EPSG:8857) for global extent."""
    source_crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
    extent = QgsRectangle(-180, -90, 180, 90)
    wcrs = WorkingCRS(source_crs, extent)

    equal_earth = QgsCoordinateReferenceSystem.fromEpsgId(8857)
    assert wcrs.working_crs == equal_earth


def test_working_crs_uses_equal_earth_for_hemispheric_extent(qgis_app):
    """T2.10: WorkingCRS uses Equal Earth for hemispheric extent (lat span > 30)."""
    source_crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
    # Lat span: -35 to 70 = 105 degrees > 30
    extent = QgsRectangle(-20, -35, 60, 70)
    wcrs = WorkingCRS(source_crs, extent)

    equal_earth = QgsCoordinateReferenceSystem.fromEpsgId(8857)
    assert wcrs.working_crs == equal_earth


def test_working_crs_forward_inverse_round_trip(qgis_app):
    """T2.11: WorkingCRS forward/inverse round-trip preserves geometry within tolerance."""
    source_crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
    extent = QgsRectangle(2, 42, 8, 51)  # France
    wcrs = WorkingCRS(source_crs, extent)

    # Build a polygon in France
    ring = [
        QgsPointXY(3, 43), QgsPointXY(7, 43),
        QgsPointXY(7, 50), QgsPointXY(3, 50),
        QgsPointXY(3, 43),
    ]
    original = QgsGeometry.fromPolygonXY([ring])

    projected = wcrs.forward(original)
    round_tripped = wcrs.inverse(projected)

    # Compare vertices
    orig_poly = original.asPolygon()[0]
    rt_poly = round_tripped.asPolygon()[0]
    assert len(orig_poly) == len(rt_poly)
    for p_orig, p_rt in zip(orig_poly, rt_poly):
        assert abs(p_orig.x() - p_rt.x()) < 1e-6
        assert abs(p_orig.y() - p_rt.y()) < 1e-6


def test_working_crs_forward_transforms_to_meters(qgis_app):
    """T2.12: WorkingCRS forward transforms geographic coords to projected meters."""
    source_crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
    extent = QgsRectangle(2, 42, 8, 51)
    wcrs = WorkingCRS(source_crs, extent)

    point_geom = QgsGeometry.fromPointXY(QgsPointXY(5, 47))
    projected = wcrs.forward(point_geom)
    proj_point = projected.asPoint()

    # Projected coords should be in meters -- much larger than degree values
    assert abs(proj_point.x()) > 100 or abs(proj_point.y()) > 100


def test_working_crs_preserve_strategy_returns_source_crs(qgis_app):
    """T2.13: WorkingCRS preserve strategy returns source CRS unchanged."""
    source_crs = QgsCoordinateReferenceSystem.fromEpsgId(3857)
    extent = QgsRectangle(-20037508, -20037508, 20037508, 20037508)
    wcrs = WorkingCRS(source_crs, extent, strategy='preserve')
    assert wcrs.working_crs == source_crs


def test_working_crs_handles_empty_geometry(qgis_app):
    """T2.14: WorkingCRS forward/inverse handle empty geometry without crashing."""
    source_crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
    extent = QgsRectangle(2, 42, 8, 51)
    wcrs = WorkingCRS(source_crs, extent)

    empty = QgsGeometry()
    result_fwd = wcrs.forward(empty)
    assert result_fwd.isEmpty()

    result_inv = wcrs.inverse(empty)
    assert result_inv.isEmpty()


def test_snyder_one_sixth_parallels_are_correct(qgis_app):
    """T2.15: Snyder 1/6 parallels computed correctly for given extent."""
    source_crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
    extent = QgsRectangle(2, 42, 8, 51)  # yMin=42, yMax=51, range=9
    wcrs = WorkingCRS(source_crs, extent)

    proj_str = wcrs.working_crs.toProj()
    # lat_1 = 42 + 9/6 = 43.5
    assert '+lat_1=43.5' in proj_str
    # lat_2 = 51 - 9/6 = 49.5
    assert '+lat_2=49.5' in proj_str
    # lat_0 = (42 + 51) / 2 = 46.5
    assert '+lat_0=46.5' in proj_str
    # lon_0 = (2 + 8) / 2 = 5.0
    assert '+lon_0=5.0' in proj_str


# ---------------------------------------------------------------------------
# T2.16 - T2.17: needs_antimeridian_split
# ---------------------------------------------------------------------------

def test_needs_antimeridian_split_detects_crossing(qgis_app):
    """T2.16: needs_antimeridian_split detects polygon crossing the antimeridian."""
    ring = [
        QgsPointXY(170, 0), QgsPointXY(190, 0),
        QgsPointXY(190, 10), QgsPointXY(170, 10),
        QgsPointXY(170, 0),
    ]
    geom = QgsGeometry.fromPolygonXY([ring])
    assert needs_antimeridian_split(geom) is True


def test_needs_antimeridian_split_rejects_non_crossing(qgis_app):
    """T2.17: needs_antimeridian_split rejects polygon in Europe (no crossing)."""
    ring = [
        QgsPointXY(2, 42), QgsPointXY(8, 42),
        QgsPointXY(8, 51), QgsPointXY(2, 51),
        QgsPointXY(2, 42),
    ]
    geom = QgsGeometry.fromPolygonXY([ring])
    assert needs_antimeridian_split(geom) is False


# ---------------------------------------------------------------------------
# T2.18 - T2.19: CRS validity and antimeridian transform
# ---------------------------------------------------------------------------

def test_create_from_proj_produces_valid_crs(qgis_app):
    """T2.18: createFromProj produces a valid CRS from Albers proj string."""
    crs = QgsCoordinateReferenceSystem()
    ok = crs.createFromProj(
        '+proj=aea +lat_1=43.5 +lat_2=49.5 +lat_0=46.5 +lon_0=5.0 '
        '+datum=WGS84 +units=m +no_defs'
    )
    assert ok is True
    assert crs.isValid()


def test_working_crs_preserves_projected_crs(qgis_app):
    """WorkingCRS preserves projected (non-geographic) CRS instead of re-projecting.

    When source CRS is already projected (e.g. UTM, engineering CRS),
    re-projecting to equal-area and back distorts grid cell shapes.
    The degree-based extent thresholds are meaningless for meter coordinates.
    """
    # UTM zone 33N (EPSG:32633) — conformal, not equal-area, but projected
    utm_crs = QgsCoordinateReferenceSystem.fromEpsgId(32633)
    assert utm_crs.isValid()
    assert not utm_crs.isGeographic()

    # Extent in meters — would trigger width>90 if misinterpreted as degrees
    extent = QgsRectangle(166000, 0, 834000, 9400000)
    wcrs = WorkingCRS(utm_crs, extent)
    assert wcrs.working_crs == utm_crs


def test_working_crs_preserves_engineering_crs(qgis_app):
    """WorkingCRS preserves engineering CRS (Transverse Mercator at origin).

    Grid Arrangement outputs in engineering CRS. Downstream algorithms
    (Snap to Grid, Tile Fill) must work in that same CRS to avoid
    distorting grid shapes via round-trip reprojection.
    """
    from tessera.infrastructure.crs_manager import create_engineering_crs

    eng_crs = create_engineering_crs()
    assert eng_crs.isValid()
    assert not eng_crs.isGeographic()

    # Large extent in meters (typical Grid Arrangement output)
    extent = QgsRectangle(0, 0, 12_000_000, 10_000_000)
    wcrs = WorkingCRS(eng_crs, extent)
    assert wcrs.working_crs == eng_crs


def test_working_crs_still_reprojects_geographic_to_equal_area(qgis_app):
    """WorkingCRS still selects equal-area for geographic (lat/lon) input.

    The projected-CRS preservation must not break the geographic case.
    """
    wgs84 = QgsCoordinateReferenceSystem.fromEpsgId(4326)
    assert wgs84.isGeographic()

    # Local extent in degrees — should get Albers
    extent = QgsRectangle(2, 42, 8, 51)
    wcrs = WorkingCRS(wgs84, extent)
    assert '+proj=aea' in wcrs.working_crs.toProj()


def test_antimeridian_polygon_transforms_to_valid_geometry(qgis_app):
    """T2.19: Polygon crossing antimeridian transforms to valid geometry."""
    source_crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
    # Use global extent since polygon crosses antimeridian
    extent = QgsRectangle(-180, -90, 180, 90)
    wcrs = WorkingCRS(source_crs, extent)

    ring = [
        QgsPointXY(170, 0), QgsPointXY(190, 0),
        QgsPointXY(190, 10), QgsPointXY(170, 10),
        QgsPointXY(170, 0),
    ]
    geom = QgsGeometry.fromPolygonXY([ring])
    result = wcrs.forward(geom)
    assert result.isGeosValid()
