"""Shared test fixtures for Tessera test suite."""
import gc
import sys
from pathlib import Path

# sys.path setup — must happen before qgis imports
sys.path.insert(0, '/app/share/qgis/python')
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'plugins'))

import pytest
from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType


def _make_fields():
    """Create standard test fields: name (String), value (Double)."""
    fields = QgsFields()
    fields.append(QgsField('name', QMetaType.Type.QString))
    fields.append(QgsField('value', QMetaType.Type.Double))
    return fields


def _make_feature(geometry, name, value, fields):
    """Create a QgsFeature with geometry and attributes."""
    feat = QgsFeature(fields)
    feat.setGeometry(geometry)
    feat.setAttribute('name', name)
    feat.setAttribute('value', value)
    return feat


@pytest.fixture(scope='session')
def qgis_app():
    """Initialize QgsApplication for the test session."""
    app = QgsApplication([], False)
    app.setPrefixPath('/app', True)
    app.initQgis()
    yield app
    app.exitQgis()


@pytest.fixture(autouse=True)
def _flush_qgis_garbage():
    """Flush dead SIP wrappers between tests to prevent segfaults.

    Python 3.13's incremental GC can collect SIP/PyQt5 wrappers for QGIS
    C++ objects during heavy allocation, triggering use-after-free in the
    C++ destructor chain.  Forcing a full GC cycle between tests keeps the
    accumulated wrapper count low enough that mid-test collections don't
    cascade into C++ memory still in use.
    """
    yield
    gc.collect()


@pytest.fixture
def simple_squares(qgis_app):
    """Four adjacent unit squares in a 2x2 grid with numeric values.

    Layout (origin at bottom-left):
        (0,1)---(1,1)---(2,1)
          |  sq2  |  sq3  |
        (0,0)---(1,0)---(2,0)
          |  sq0  |  sq1  |
        (0,-1)--(1,-1)--(2,-1)

    Wait, let me use simpler coords:
        sq0: (0,0)-(1,0)-(1,1)-(0,1)  value=10
        sq1: (1,0)-(2,0)-(2,1)-(1,1)  value=20
        sq2: (0,1)-(1,1)-(1,2)-(0,2)  value=30
        sq3: (1,1)-(2,1)-(2,2)-(1,2)  value=40
    """
    fields = _make_fields()
    squares = []
    coords = [
        ((0, 0), (1, 0), (1, 1), (0, 1)),   # sq0 bottom-left
        ((1, 0), (2, 0), (2, 1), (1, 1)),   # sq1 bottom-right
        ((0, 1), (1, 1), (1, 2), (0, 2)),   # sq2 top-left
        ((1, 1), (2, 1), (2, 2), (1, 2)),   # sq3 top-right
    ]
    values = [10.0, 20.0, 30.0, 40.0]
    names = ['sq0', 'sq1', 'sq2', 'sq3']

    for (verts, val, name) in zip(coords, values, names):
        ring = [QgsPointXY(x, y) for x, y in verts]
        ring.append(ring[0])  # close the ring
        geom = QgsGeometry.fromPolygonXY([ring])
        feat = _make_feature(geom, name, val, fields)
        squares.append(feat)

    return squares


@pytest.fixture
def concave_polygon(qgis_app):
    """A U-shaped concave polygon whose centroid lies outside the polygon.

    Vertices: (0,0),(4,0),(4,1),(1,1),(1,3),(4,3),(4,4),(0,4)
    Three arms of width 1 forming a U. Centroid ~(1.7, 2.0) falls in the gap.
    """
    fields = _make_fields()
    ring = [
        QgsPointXY(0, 0),
        QgsPointXY(4, 0),
        QgsPointXY(4, 1),
        QgsPointXY(1, 1),
        QgsPointXY(1, 3),
        QgsPointXY(4, 3),
        QgsPointXY(4, 4),
        QgsPointXY(0, 4),
        QgsPointXY(0, 0),  # close
    ]
    geom = QgsGeometry.fromPolygonXY([ring])
    return _make_feature(geom, 'U-shape', 100.0, fields)


@pytest.fixture
def multipolygon(qgis_app):
    """A MultiPolygon feature with mainland (large) and island (small).

    Mainland: (0,0)-(10,0)-(10,10)-(0,10) — area 100
    Island:   (15,15)-(17,15)-(17,17)-(15,17) — area 4
    """
    fields = _make_fields()
    mainland = [
        QgsPointXY(0, 0), QgsPointXY(10, 0),
        QgsPointXY(10, 10), QgsPointXY(0, 10),
        QgsPointXY(0, 0),
    ]
    island = [
        QgsPointXY(15, 15), QgsPointXY(17, 15),
        QgsPointXY(17, 17), QgsPointXY(15, 17),
        QgsPointXY(15, 15),
    ]
    geom = QgsGeometry.fromMultiPolygonXY([[mainland], [island]])
    return _make_feature(geom, 'archipelago', 200.0, fields)


@pytest.fixture
def polygon_with_holes(qgis_app):
    """A polygon with one interior hole.

    Outer ring: (0,0)-(10,0)-(10,10)-(0,10) — area 100
    Inner hole: (3,3)-(7,3)-(7,7)-(3,7) — area 16
    Net area: 84
    """
    fields = _make_fields()
    outer = [
        QgsPointXY(0, 0), QgsPointXY(10, 0),
        QgsPointXY(10, 10), QgsPointXY(0, 10),
        QgsPointXY(0, 0),
    ]
    hole = [
        QgsPointXY(3, 3), QgsPointXY(7, 3),
        QgsPointXY(7, 7), QgsPointXY(3, 7),
        QgsPointXY(3, 3),
    ]
    geom = QgsGeometry.fromPolygonXY([outer, hole])
    return _make_feature(geom, 'with-hole', 84.0, fields)


@pytest.fixture(scope='session')
def natural_earth_path():
    """Return path to the Natural Earth 110m countries shapefile.

    Path is resolved relative to the project root (parent of tests/).
    Run scripts/download_test_data.py to fetch the data if missing.
    """
    project_root = Path(__file__).parent.parent
    path = project_root / 'test_data' / 'ne_110m_admin_0_countries' / 'ne_110m_admin_0_countries.shp'
    assert path.exists(), (
        f'Natural Earth shapefile not found at {path}. '
        f'Run: python scripts/download_test_data.py'
    )
    return path
