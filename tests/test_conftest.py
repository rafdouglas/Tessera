"""Tests validating conftest.py fixtures."""
from pathlib import Path

import pytest
from qgis.core import QgsApplication, QgsGeometry, QgsVectorLayer, QgsWkbTypes


def test_qgis_initialization_provides_valid_application(qgis_app):
    """T0.1: QGIS initialization works - qgis_app fixture provides a valid QgsApplication."""
    assert qgis_app is not None
    assert isinstance(qgis_app, QgsApplication)


def test_qgis_geometry_can_be_created(qgis_app):
    """T0.1: QGIS initialization works - QgsGeometry can be created."""
    geom = QgsGeometry.fromWkt('POINT(0 0)')
    assert geom is not None
    assert not geom.isNull()


def test_simple_squares_returns_exactly_four_features(simple_squares):
    """T0.2: simple_squares produces 4 QgsFeature objects."""
    assert len(simple_squares) == 4


def test_simple_squares_have_valid_polygon_geometry(simple_squares):
    """T0.2: simple_squares features have valid polygon geometry (not null, not empty)."""
    for feat in simple_squares:
        geom = feat.geometry()
        assert not geom.isNull()
        assert not geom.isEmpty()
        assert geom.type() == QgsWkbTypes.PolygonGeometry


def test_simple_squares_have_numeric_value_attributes(simple_squares):
    """T0.2: simple_squares features have numeric 'value' attributes (10, 20, 30, 40)."""
    values = [feat.attribute('value') for feat in simple_squares]
    assert values == [10.0, 20.0, 30.0, 40.0]


def test_simple_squares_each_have_unit_area(simple_squares):
    """T0.2: simple_squares features each have area == 1.0 (unit squares)."""
    for feat in simple_squares:
        area = feat.geometry().area()
        assert abs(area - 1.0) < 0.0001


def test_simple_squares_bounding_box_covers_2x2_area(simple_squares):
    """T0.2: simple_squares geometries are adjacent (bounding box covers 2x2 area)."""
    # Collect all geometries into one geometry collection
    geoms = [feat.geometry() for feat in simple_squares]

    # Get bounding box of all geometries
    bbox = geoms[0].boundingBox()
    for geom in geoms[1:]:
        bbox.combineExtentWith(geom.boundingBox())

    # Check bounding box dimensions
    assert abs(bbox.width() - 2.0) < 0.0001
    assert abs(bbox.height() - 2.0) < 0.0001
    assert abs(bbox.xMinimum() - 0.0) < 0.0001
    assert abs(bbox.yMinimum() - 0.0) < 0.0001
    assert abs(bbox.xMaximum() - 2.0) < 0.0001
    assert abs(bbox.yMaximum() - 2.0) < 0.0001


def test_concave_polygon_has_valid_geometry(concave_polygon):
    """T0.3: concave_polygon has valid geometry with area > 0."""
    geom = concave_polygon.geometry()
    assert not geom.isNull()
    assert not geom.isEmpty()
    assert geom.area() > 0


def test_concave_polygon_centroid_outside_polygon(concave_polygon):
    """T0.3: concave_polygon centroid lies outside polygon (proving concavity of U-shape)."""
    geom = concave_polygon.geometry()
    centroid = geom.centroid()

    # Centroid should NOT be contained within the polygon (this proves concavity)
    assert not geom.contains(centroid)


def test_multipolygon_is_multipart(multipolygon):
    """T0.4: multipolygon has MultiPolygon geometry type (isMultipart())."""
    geom = multipolygon.geometry()
    assert geom.isMultipart()


def test_multipolygon_has_exactly_two_parts(multipolygon):
    """T0.4: multipolygon has exactly 2 parts via asMultiPolygon()."""
    geom = multipolygon.geometry()
    multi = geom.asMultiPolygon()
    assert len(multi) == 2


def test_multipolygon_both_parts_have_positive_area(multipolygon):
    """T0.4: multipolygon both parts have area > 0."""
    geom = multipolygon.geometry()
    multi = geom.asMultiPolygon()

    # Convert each part back to QgsGeometry to calculate area
    for part in multi:
        part_geom = QgsGeometry.fromPolygonXY(part)
        assert part_geom.area() > 0


def test_polygon_with_holes_has_valid_geometry(polygon_with_holes):
    """T0.5: polygon_with_holes has valid geometry."""
    geom = polygon_with_holes.geometry()
    assert not geom.isNull()
    assert not geom.isEmpty()


def test_polygon_with_holes_has_exterior_and_interior_ring(polygon_with_holes):
    """T0.5: polygon_with_holes has 1 exterior ring and 1 interior ring (hole)."""
    geom = polygon_with_holes.geometry()
    polygon = geom.asPolygon()

    # First list is exterior ring, subsequent lists are holes
    assert len(polygon) == 2  # 1 exterior + 1 interior

    # Verify rings are not empty
    assert len(polygon[0]) > 0  # exterior ring
    assert len(polygon[1]) > 0  # interior ring (hole)


def test_polygon_with_holes_area_is_approximately_84(polygon_with_holes):
    """T0.5: polygon_with_holes total area is approximately 84 (100 outer - 16 hole)."""
    geom = polygon_with_holes.geometry()
    area = geom.area()
    assert abs(area - 84.0) < 0.0001


def test_natural_earth_path_returns_path_object(natural_earth_path):
    """T0.6: natural_earth_path returns a Path object."""
    assert isinstance(natural_earth_path, Path)


def test_natural_earth_path_file_exists(natural_earth_path):
    """T0.6: natural_earth_path file exists on disk."""
    assert natural_earth_path.exists()


def test_natural_earth_path_creates_valid_vector_layer(natural_earth_path):
    """T0.6: QgsVectorLayer created from natural_earth_path is valid and has features."""
    layer = QgsVectorLayer(str(natural_earth_path), 'ne_countries', 'ogr')
    assert layer.isValid()
    assert layer.featureCount() > 0
