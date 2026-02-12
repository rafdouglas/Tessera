"""Shared test helper functions for Tessera test suite.

Provides reusable factory functions for creating test geometries,
features, fields, and layers. Import these instead of duplicating
in each test file.
"""
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType


def make_fields():
    """Create standard test fields: name (String), value (Double)."""
    fields = QgsFields()
    fields.append(QgsField('name', QMetaType.Type.QString))
    fields.append(QgsField('value', QMetaType.Type.Double))
    return fields


def make_feature(geometry, name, value, fields):
    """Create a QgsFeature with geometry and attributes."""
    feat = QgsFeature(fields)
    feat.setGeometry(geometry)
    feat.setAttribute('name', name)
    feat.setAttribute('value', value)
    return feat


def make_layer(features, crs_id='EPSG:4326'):
    """Create a memory vector layer from features.

    Args:
        features: list of QgsFeature with geometry and attributes.
        crs_id: CRS identifier string. Default 'EPSG:4326'.

    Returns:
        QgsVectorLayer with all features added.
    """
    layer = QgsVectorLayer(f'Polygon?crs={crs_id}', 'test', 'memory')
    pr = layer.dataProvider()
    if features:
        fields = features[0].fields()
        pr.addAttributes([fields.field(i) for i in range(fields.count())])
        layer.updateFields()
        pr.addFeatures(features)
    layer.updateExtents()
    return layer
