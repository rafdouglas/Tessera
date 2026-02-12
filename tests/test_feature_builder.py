"""Tests for feature_builder module."""
import pytest
from qgis.core import QgsFeature, QgsField, QgsFields, QgsGeometry, QgsPointXY, QgsWkbTypes
from PyQt5.QtCore import QMetaType

from tessera.infrastructure.feature_builder import create_output_fields, build_feature


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input_fields(names_and_types):
    """Create a QgsFields from a list of (name, QMetaType.Type) tuples."""
    fields = QgsFields()
    for name, metatype in names_and_types:
        fields.append(QgsField(name=name, type=metatype))
    return fields


def _make_parent_feature(fields, attrs, geometry=None, fid=1):
    """Create a QgsFeature with given fields, attributes, geometry and id."""
    feat = QgsFeature(fields)
    feat.setId(fid)
    for name, value in attrs.items():
        feat.setAttribute(name, value)
    if geometry is not None:
        feat.setGeometry(geometry)
    return feat


def _unit_square_polygon():
    """Return a QgsGeometry Polygon for a unit square (0,0)-(1,0)-(1,1)-(0,1)."""
    ring = [
        QgsPointXY(0, 0), QgsPointXY(1, 0),
        QgsPointXY(1, 1), QgsPointXY(0, 1),
        QgsPointXY(0, 0),
    ]
    return QgsGeometry.fromPolygonXY([ring])


def _unit_square_multipolygon():
    """Return a QgsGeometry MultiPolygon for a unit square."""
    ring = [
        QgsPointXY(0, 0), QgsPointXY(1, 0),
        QgsPointXY(1, 1), QgsPointXY(0, 1),
        QgsPointXY(0, 0),
    ]
    return QgsGeometry.fromMultiPolygonXY([[ring]])


STANDARD_EXTRA = [
    ('_tessera_algorithm', QMetaType.Type.QString),
    ('_tessera_parent_fid', QMetaType.Type.Int),
]


# ===========================================================================
# T3.1 -- create_output_fields merges input and extra fields
# ===========================================================================

def test_create_output_fields_merges_input_and_extra(qgis_app):
    """T3.1: input [name, value] + extra [_tessera_algorithm, _tessera_parent_fid] -> 4 fields."""
    input_fields = _make_input_fields([
        ('name', QMetaType.Type.QString),
        ('value', QMetaType.Type.Double),
    ])
    result = create_output_fields(input_fields, STANDARD_EXTRA)

    assert isinstance(result, QgsFields)
    assert result.count() == 4
    assert result.field(0).name() == 'name'
    assert result.field(1).name() == 'value'
    assert result.field(2).name() == '_tessera_algorithm'
    assert result.field(3).name() == '_tessera_parent_fid'


# ===========================================================================
# T3.2 -- create_output_fields handles name collision
# ===========================================================================

def test_create_output_fields_collision_deduplicates(qgis_app):
    """T3.2: input has '_tessera_algorithm' + extra has '_tessera_algorithm' -> exactly one copy."""
    input_fields = _make_input_fields([
        ('name', QMetaType.Type.QString),
        ('_tessera_algorithm', QMetaType.Type.QString),
    ])
    extra = [('_tessera_algorithm', QMetaType.Type.QString), ('_tessera_parent_fid', QMetaType.Type.Int)]
    result = create_output_fields(input_fields, extra)

    # Should have 3 fields: name, _tessera_algorithm, _tessera_parent_fid
    assert result.count() == 3
    names = [result.field(i).name() for i in range(result.count())]
    assert names.count('_tessera_algorithm') == 1


# ===========================================================================
# T3.3 -- create_output_fields preserves field order
# ===========================================================================

def test_create_output_fields_preserves_order(qgis_app):
    """T3.3: input [name, pop, gdp] + extra [_tessera_algorithm] -> name, pop, gdp, _tessera_algorithm."""
    input_fields = _make_input_fields([
        ('name', QMetaType.Type.QString),
        ('pop', QMetaType.Type.Double),
        ('gdp', QMetaType.Type.Double),
    ])
    extra = [('_tessera_algorithm', QMetaType.Type.QString)]
    result = create_output_fields(input_fields, extra)

    names = [result.field(i).name() for i in range(result.count())]
    assert names == ['name', 'pop', 'gdp', '_tessera_algorithm']


# ===========================================================================
# T3.4 -- build_feature promotes Polygon to MultiPolygon
# ===========================================================================

def test_build_feature_promotes_polygon_to_multipolygon(qgis_app):
    """T3.4: simple polygon input -> result geometry is MultiPolygon, area unchanged."""
    input_fields = _make_input_fields([
        ('name', QMetaType.Type.QString),
        ('value', QMetaType.Type.Double),
    ])
    output_fields = create_output_fields(input_fields, STANDARD_EXTRA)

    polygon_geom = _unit_square_polygon()
    original_area = polygon_geom.area()

    parent = _make_parent_feature(
        input_fields, {'name': 'test', 'value': 1.0}, polygon_geom, fid=7,
    )

    result = build_feature(
        geometry=polygon_geom,
        parent_feature=parent,
        algorithm_id='tile_fill',
        extra_attrs={},
        output_fields=output_fields,
    )

    result_geom = result.geometry()
    assert result_geom.isMultipart(), 'Geometry should be promoted to MultiPolygon'
    assert result_geom.wkbType() == QgsWkbTypes.MultiPolygon
    assert abs(result_geom.area() - original_area) < 1e-9


# ===========================================================================
# T3.5 -- build_feature preserves MultiPolygon
# ===========================================================================

def test_build_feature_preserves_multipolygon(qgis_app):
    """T3.5: multi input -> result still MultiPolygon, unchanged."""
    input_fields = _make_input_fields([
        ('name', QMetaType.Type.QString),
        ('value', QMetaType.Type.Double),
    ])
    output_fields = create_output_fields(input_fields, STANDARD_EXTRA)

    multi_geom = _unit_square_multipolygon()
    original_area = multi_geom.area()

    parent = _make_parent_feature(
        input_fields, {'name': 'multi', 'value': 2.0}, multi_geom, fid=10,
    )

    result = build_feature(
        geometry=multi_geom,
        parent_feature=parent,
        algorithm_id='tile_fill',
        extra_attrs={},
        output_fields=output_fields,
    )

    result_geom = result.geometry()
    assert result_geom.isMultipart()
    assert abs(result_geom.area() - original_area) < 1e-9


# ===========================================================================
# T3.6 -- build_feature carries parent attributes
# ===========================================================================

def test_build_feature_carries_parent_attributes(qgis_app):
    """T3.6: parent name='France', value=65000000 -> result has those plus _ig fields."""
    input_fields = _make_input_fields([
        ('name', QMetaType.Type.QString),
        ('value', QMetaType.Type.Double),
    ])
    output_fields = create_output_fields(input_fields, STANDARD_EXTRA)

    geom = _unit_square_polygon()
    parent = _make_parent_feature(
        input_fields, {'name': 'France', 'value': 65000000.0}, geom, fid=42,
    )

    result = build_feature(
        geometry=geom,
        parent_feature=parent,
        algorithm_id='tile_fill',
        extra_attrs={},
        output_fields=output_fields,
    )

    assert result.attribute('name') == 'France'
    assert result.attribute('value') == 65000000.0
    assert result.attribute('_tessera_algorithm') == 'tile_fill'
    assert result.attribute('_tessera_parent_fid') == 42


# ===========================================================================
# T3.7 -- build_feature sets extra attributes
# ===========================================================================

def test_build_feature_sets_extra_attributes(qgis_app):
    """T3.7: extra_attrs={'_tessera_tile_index': 42} -> result['_tessera_tile_index'] == 42."""
    input_fields = _make_input_fields([
        ('name', QMetaType.Type.QString),
        ('value', QMetaType.Type.Double),
    ])
    extra_field_defs = STANDARD_EXTRA + [('_tessera_tile_index', QMetaType.Type.Int)]
    output_fields = create_output_fields(input_fields, extra_field_defs)

    geom = _unit_square_polygon()
    parent = _make_parent_feature(
        input_fields, {'name': 'tile', 'value': 1.0}, geom, fid=5,
    )

    result = build_feature(
        geometry=geom,
        parent_feature=parent,
        algorithm_id='grid',
        extra_attrs={'_tessera_tile_index': 42},
        output_fields=output_fields,
    )

    assert result.attribute('_tessera_tile_index') == 42
    assert result.attribute('_tessera_algorithm') == 'grid'
    assert result.attribute('_tessera_parent_fid') == 5


# ===========================================================================
# T3.8 -- build_feature without carry_all_attributes
# ===========================================================================

def test_build_feature_without_carry_all_attributes(qgis_app):
    """T3.8: carry_all_attributes=False -> _ig fields set, parent fields are NULL."""
    input_fields = _make_input_fields([
        ('name', QMetaType.Type.QString),
        ('value', QMetaType.Type.Double),
    ])
    output_fields = create_output_fields(input_fields, STANDARD_EXTRA)

    geom = _unit_square_polygon()
    parent = _make_parent_feature(
        input_fields, {'name': 'France', 'value': 65000000.0}, geom, fid=42,
    )

    result = build_feature(
        geometry=geom,
        parent_feature=parent,
        algorithm_id='tile_fill',
        extra_attrs={},
        output_fields=output_fields,
        carry_all_attributes=False,
    )

    # _ig fields should be set
    assert result.attribute('_tessera_algorithm') == 'tile_fill'
    assert result.attribute('_tessera_parent_fid') == 42

    # Parent fields should be NULL (None or QVariant null)
    name_val = result.attribute('name')
    value_val = result.attribute('value')
    assert name_val is None or (hasattr(name_val, 'isNull') and name_val.isNull())
    assert value_val is None or (hasattr(value_val, 'isNull') and value_val.isNull())


# ===========================================================================
# T3.9 -- build_feature handles empty geometry
# ===========================================================================

def test_build_feature_handles_empty_geometry(qgis_app):
    """T3.9: empty QgsGeometry -> result has empty geometry but attributes still set."""
    input_fields = _make_input_fields([
        ('name', QMetaType.Type.QString),
        ('value', QMetaType.Type.Double),
    ])
    output_fields = create_output_fields(input_fields, STANDARD_EXTRA)

    empty_geom = QgsGeometry()
    parent = _make_parent_feature(
        input_fields, {'name': 'empty', 'value': 0.0}, empty_geom, fid=99,
    )

    result = build_feature(
        geometry=empty_geom,
        parent_feature=parent,
        algorithm_id='tile_fill',
        extra_attrs={},
        output_fields=output_fields,
    )

    # Geometry should be empty
    result_geom = result.geometry()
    assert result_geom.isEmpty() or result_geom.isNull()

    # Attributes should still be set
    assert result.attribute('name') == 'empty'
    assert result.attribute('value') == 0.0
    assert result.attribute('_tessera_algorithm') == 'tile_fill'
    assert result.attribute('_tessera_parent_fid') == 99
