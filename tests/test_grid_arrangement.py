"""Tests for GridArrangementAlgorithm.

Grid arrangement places features in a regular grid layout for
small-multiples poster visualizations. Tests cover grid placement,
auto-columns, padding, sort field, geometry preservation, and CRS output.
"""
import gc
import math

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

from tessera.algorithms.grid_arrangement import (
    GridArrangementAlgorithm,
    _grid_position,
    _largest_part_bbox,
)

from .helpers import make_fields, make_feature, make_layer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_circle_feature(cx, cy, radius, name, value, fields, n_segments=64):
    """Create a circular polygon feature centered at (cx, cy) with given radius."""
    points = []
    for i in range(n_segments):
        angle = 2.0 * math.pi * i / n_segments
        px = cx + radius * math.cos(angle)
        py = cy + radius * math.sin(angle)
        points.append(QgsPointXY(px, py))
    points.append(points[0])
    geom = QgsGeometry.fromPolygonXY([points])
    return make_feature(geom, name, value, fields)


def _make_square_feature(cx, cy, half_side, name, value, fields):
    """Create a square polygon feature centered at (cx, cy)."""
    ring = [
        QgsPointXY(cx - half_side, cy - half_side),
        QgsPointXY(cx + half_side, cy - half_side),
        QgsPointXY(cx + half_side, cy + half_side),
        QgsPointXY(cx - half_side, cy + half_side),
        QgsPointXY(cx - half_side, cy - half_side),
    ]
    geom = QgsGeometry.fromPolygonXY([ring])
    return make_feature(geom, name, value, fields)


def _run_grid_arrangement(layer, grid_columns=0, grid_cell_width=0.0,
                          grid_cell_height=0.0, grid_internal_padding=0.0,
                          grid_padding=0.0,
                          grid_sort_field='', grid_fill_order=0):
    """Run GridArrangementAlgorithm and return output features."""
    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        alg = GridArrangementAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'GRID_COLUMNS': grid_columns,
            'GRID_CELL_WIDTH': grid_cell_width,
            'GRID_CELL_HEIGHT': grid_cell_height,
            'GRID_INTERNAL_PADDING': grid_internal_padding,
            'GRID_PADDING': grid_padding,
            'GRID_SORT_FIELD': grid_sort_field,
            'GRID_FILL_ORDER': grid_fill_order,
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
        return features, results, feedback, output_layer
    finally:
        project.removeMapLayer(layer.id())


# ===========================================================================
# C4: Grid arrangement
# ===========================================================================

class TestGridArrangement:
    """Tests for grid arrangement algorithm (C4)."""

    def test_grid_four_features_in_2x2(self, qgis_app):
        """C4.1: grid mode places 4 features in 2x2 grid."""
        fields = make_fields()
        feats = [
            _make_circle_feature(0.0, 0.0, 0.5, f'c{i}', float(i * 10), fields)
            for i in range(4)
        ]
        layer = make_layer(feats)

        features, _, _, _ = _run_grid_arrangement(layer, grid_columns=2)

        assert len(features) == 4

        centroids = sorted(
            [f.geometry().centroid().asPoint() for f in features],
            key=lambda p: (round(p.y(), 1), round(p.x(), 1)),
        )
        assert abs(centroids[0].y() - centroids[1].y()) < 0.5
        assert centroids[1].x() > centroids[0].x()
        assert centroids[2].y() > centroids[0].y()

    def test_grid_auto_columns_sqrt(self, qgis_app):
        """C4.2: auto-calculates columns from sqrt(n) when GRID_COLUMNS=0."""
        fields = make_fields()
        feats = [
            _make_circle_feature(float(i), 0.0, 0.3, f'c{i}', float(i), fields)
            for i in range(9)
        ]
        layer = make_layer(feats)

        features, _, _, _ = _run_grid_arrangement(layer, grid_columns=0)

        assert len(features) == 9

        centroids = [f.geometry().centroid().asPoint() for f in features]
        unique_x = sorted(set(round(c.x(), 0) for c in centroids))
        unique_y = sorted(set(round(c.y(), 0) for c in centroids))
        assert len(unique_x) == 3, f"Expected 3 columns, got {len(unique_x)} unique x values"
        assert len(unique_y) == 3, f"Expected 3 rows, got {len(unique_y)} unique y values"

    def test_grid_with_padding(self, qgis_app):
        """C4.3: padding increases cell separation."""
        fields = make_fields()
        feats = [
            _make_circle_feature(0.0, 0.0, 0.5, f'c{i}', float(i * 10), fields)
            for i in range(4)
        ]

        layer_no_pad = make_layer(feats[:])
        features_no_pad, _, _, _ = _run_grid_arrangement(
            layer_no_pad, grid_columns=2, grid_padding=0.0)

        feats2 = [
            _make_circle_feature(0.0, 0.0, 0.5, f'c{i}', float(i * 10), fields)
            for i in range(4)
        ]
        layer_pad = make_layer(feats2)
        features_pad, _, _, _ = _run_grid_arrangement(
            layer_pad, grid_columns=2, grid_padding=2.0)

        def max_centroid_dist(features):
            centroids = [f.geometry().centroid().asPoint() for f in features]
            max_d = 0.0
            for i in range(len(centroids)):
                for j in range(i + 1, len(centroids)):
                    d = math.hypot(centroids[j].x() - centroids[i].x(),
                                   centroids[j].y() - centroids[i].y())
                    if d > max_d:
                        max_d = d
            return max_d

        assert max_centroid_dist(features_pad) > max_centroid_dist(features_no_pad), (
            "Padded grid should have larger centroid spread"
        )

    def test_grid_with_sort_field(self, qgis_app):
        """C4.4: sort field orders features by value."""
        fields = make_fields()
        feats = [
            _make_circle_feature(0.0, 0.0, 0.3, 'c0', 40.0, fields),
            _make_circle_feature(1.0, 0.0, 0.3, 'c1', 10.0, fields),
            _make_circle_feature(2.0, 0.0, 0.3, 'c2', 30.0, fields),
            _make_circle_feature(3.0, 0.0, 0.3, 'c3', 20.0, fields),
        ]
        layer = make_layer(feats)

        features, _, _, _ = _run_grid_arrangement(
            layer, grid_columns=2, grid_sort_field='value')

        assert len(features) == 4
        centroids_vals = [
            (f.geometry().centroid().asPoint(), f.attribute('value'))
            for f in features
        ]
        centroids_vals.sort(key=lambda cv: (-round(cv[0].y(), 1), round(cv[0].x(), 1)))
        values_in_grid_order = [cv[1] for cv in centroids_vals]
        assert values_in_grid_order == [10.0, 20.0, 30.0, 40.0], (
            f"Expected sorted order [10,20,30,40], got {values_in_grid_order}"
        )

    def test_grid_preserves_geometry_shape(self, qgis_app):
        """C4.5: preserves geometry shape (only translates)."""
        fields = make_fields()
        feat = _make_square_feature(5.0, 5.0, 0.5, 'sq', 10.0, fields)
        original_vertex_count = feat.geometry().constGet().nCoordinates()
        layer = make_layer([feat])

        features, _, _, _ = _run_grid_arrangement(layer, grid_columns=1)

        assert len(features) == 1
        out_geom = features[0].geometry()
        assert out_geom.isGeosValid(), "Output geometry should be valid"
        assert not out_geom.isEmpty(), "Output geometry should not be empty"
        assert out_geom.area() > 0, "Output geometry should have positive area"
        assert out_geom.constGet().nCoordinates() == original_vertex_count, (
            "Grid mode should preserve vertex count (translation only)"
        )

    def test_grid_single_feature(self, qgis_app):
        """C4.6: single feature places it at grid cell (0,0)."""
        fields = make_fields()
        feat = _make_circle_feature(10.0, 10.0, 0.5, 'solo', 10.0, fields)
        layer = make_layer([feat])

        features, _, _, _ = _run_grid_arrangement(layer, grid_columns=1)

        assert len(features) == 1
        assert not features[0].geometry().isEmpty()

    def test_grid_outputs_engineering_crs(self, qgis_app):
        """Grid arrangement should output in engineering CRS, not source CRS."""
        fields = make_fields()
        feats = [
            _make_circle_feature(0.0, 0.0, 0.5, f'c{i}', float(i * 10), fields)
            for i in range(4)
        ]
        layer = make_layer(feats)

        features, _, _, output_layer = _run_grid_arrangement(layer, grid_columns=2)

        assert len(features) == 4
        output_crs = output_layer.crs()
        assert output_crs.isValid(), "Output CRS should be valid"
        assert not output_crs.isGeographic(), (
            f"Grid mode should output engineering CRS, not geographic. "
            f"Got CRS: {output_crs.authid()}"
        )

    def test_grid_geometries_not_distorted(self, qgis_app):
        """Grid arrangement should produce valid, non-empty geometries."""
        fields = make_fields()
        feats = [
            _make_circle_feature(float(i * 10), 0.0, 0.5, f'c{i}', float(i * 10), fields)
            for i in range(4)
        ]
        layer = make_layer(feats)

        features, _, _, _ = _run_grid_arrangement(layer, grid_columns=2)

        assert len(features) == 4
        for i, feat in enumerate(features):
            geom = feat.geometry()
            assert geom.isGeosValid(), f"Feature {i} geometry should be valid"
            assert not geom.isEmpty(), f"Feature {i} geometry should not be empty"
            assert geom.area() > 0, f"Feature {i} should have positive area"


# ===========================================================================
# Multipart auto sizing
# ===========================================================================

class TestMultipartAutoSizing:
    """Auto cell size uses full multipart bbox extent."""

    def test_largest_part_bbox_multipart(self, qgis_app):
        """_largest_part_bbox returns bbox of largest part, not whole geometry."""
        small_part = QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(1, 0),
            QgsPointXY(1, 1), QgsPointXY(0, 1),
            QgsPointXY(0, 0),
        ]])
        large_part = QgsGeometry.fromPolygonXY([[
            QgsPointXY(100, 100), QgsPointXY(103, 100),
            QgsPointXY(103, 103), QgsPointXY(100, 103),
            QgsPointXY(100, 100),
        ]])
        multi = QgsGeometry.collectGeometry([small_part, large_part])

        bbox = _largest_part_bbox(multi)
        assert bbox.width() == pytest.approx(3.0, abs=0.01)
        assert bbox.height() == pytest.approx(3.0, abs=0.01)

    def test_largest_part_bbox_singlepart(self, qgis_app):
        """_largest_part_bbox returns normal bbox for singlepart geometry."""
        geom = QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(5, 0),
            QgsPointXY(5, 3), QgsPointXY(0, 3),
            QgsPointXY(0, 0),
        ]])

        bbox = _largest_part_bbox(geom)
        assert bbox.width() == pytest.approx(5.0, abs=0.01)
        assert bbox.height() == pytest.approx(3.0, abs=0.01)

    def test_multipart_auto_cell_uses_full_extent(self, qgis_app):
        """Auto cell size considers full multipart extent, not just largest part.

        Uses EPSG:3857 so coordinates are already in meters.
        """
        fields = make_fields()

        part_a = QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(100, 0),
            QgsPointXY(100, 100), QgsPointXY(0, 100),
            QgsPointXY(0, 0),
        ]])
        part_b = QgsGeometry.fromPolygonXY([[
            QgsPointXY(1000, 0), QgsPointXY(1100, 0),
            QgsPointXY(1100, 100), QgsPointXY(1000, 100),
            QgsPointXY(1000, 0),
        ]])
        multi_geom = QgsGeometry.collectGeometry([part_a, part_b])
        feat_multi = make_feature(multi_geom, 'multi', 10.0, fields)

        feat_small = _make_square_feature(500.0, 50.0, 10.0, 'small', 20.0, fields)

        layer = make_layer([feat_multi, feat_small], crs_id='EPSG:3857')
        features, _, _, _ = _run_grid_arrangement(layer, grid_columns=2)

        assert len(features) == 2
        centroids = [f.geometry().centroid().asPoint() for f in features]
        dx = abs(centroids[0].x() - centroids[1].x())
        full_bbox_width = 1100.0
        assert dx >= full_bbox_width * 0.5, (
            f"Cell spacing {dx} should reflect full multipart extent "
            f"(~{full_bbox_width}), not just largest part (~100)"
        )


# ===========================================================================
# Fill order modes
# ===========================================================================

class TestFillOrderModes:
    """5 fill order modes place features in correct grid positions."""

    def test_grid_position_row_first_down(self):
        """fill_order 1: top-left → right → next row down."""
        positions = [_grid_position(i, 2, 2, 1) for i in range(4)]
        assert positions == [(1, 0), (1, 1), (0, 0), (0, 1)]

    def test_grid_position_row_first_up(self):
        """fill_order 2: bottom-left → right → next row up."""
        positions = [_grid_position(i, 2, 2, 2) for i in range(4)]
        assert positions == [(0, 0), (0, 1), (1, 0), (1, 1)]

    def test_grid_position_column_first_left(self):
        """fill_order 3: top-left → down → next column right."""
        positions = [_grid_position(i, 2, 2, 3) for i in range(4)]
        assert positions == [(1, 0), (0, 0), (1, 1), (0, 1)]

    def test_grid_position_column_first_right(self):
        """fill_order 4: top-right → down → next column left."""
        positions = [_grid_position(i, 2, 2, 4) for i in range(4)]
        assert positions == [(1, 1), (0, 1), (1, 0), (0, 0)]

    def test_grid_position_not_selected_same_as_row_down(self):
        """fill_order 0 (not selected) behaves same as fill_order 1."""
        for i in range(6):
            assert _grid_position(i, 3, 2, 0) == _grid_position(i, 3, 2, 1)

    def test_fill_order_row_down_placement(self, qgis_app):
        """Row first (down): feature 0 at top-left, feature 3 at bottom-right."""
        fields = make_fields()
        feats = [
            _make_square_feature(float(i), 0.0, 0.3, f'f{i}', float(i), fields)
            for i in range(4)
        ]
        layer = make_layer(feats)

        features, _, _, _ = _run_grid_arrangement(
            layer, grid_columns=2, grid_fill_order=1,
            grid_sort_field='value')

        vals_by_pos = {}
        for f in features:
            pt = f.geometry().centroid().asPoint()
            vals_by_pos[(round(pt.x(), 0), round(pt.y(), 0))] = f.attribute('value')

        positions_sorted = sorted(vals_by_pos.items(),
                                  key=lambda kv: (-kv[0][1], kv[0][0]))
        values_in_order = [v for _, v in positions_sorted]
        assert values_in_order == [0.0, 1.0, 2.0, 3.0]

    def test_fill_order_row_up_placement(self, qgis_app):
        """Row first (up): feature 0 at bottom-left, feature 3 at top-right."""
        fields = make_fields()
        feats = [
            _make_square_feature(float(i), 0.0, 0.3, f'f{i}', float(i), fields)
            for i in range(4)
        ]
        layer = make_layer(feats)

        features, _, _, _ = _run_grid_arrangement(
            layer, grid_columns=2, grid_fill_order=2,
            grid_sort_field='value')

        vals_by_pos = {}
        for f in features:
            pt = f.geometry().centroid().asPoint()
            vals_by_pos[(round(pt.x(), 0), round(pt.y(), 0))] = f.attribute('value')

        positions_sorted = sorted(vals_by_pos.items(),
                                  key=lambda kv: (kv[0][1], kv[0][0]))
        values_in_order = [v for _, v in positions_sorted]
        assert values_in_order == [0.0, 1.0, 2.0, 3.0]


# ===========================================================================
# Padding not double-counted
# ===========================================================================

class TestPaddingNotDoubleCount:
    """Cell stride = cell_w + padding, not cell_w + 2*padding."""

    def test_cell_stride_equals_cell_plus_padding(self, qgis_app):
        """With explicit cell size, centroid spacing = cell_size + padding."""
        fields = make_fields()
        feats = [
            _make_square_feature(0.0, 0.0, 0.3, f'f{i}', float(i), fields)
            for i in range(2)
        ]
        layer = make_layer(feats)

        cell_w = 10.0
        padding = 5.0
        features, _, _, _ = _run_grid_arrangement(
            layer, grid_columns=2, grid_cell_width=cell_w,
            grid_cell_height=10.0, grid_padding=padding)

        assert len(features) == 2
        centroids = [f.geometry().centroid().asPoint() for f in features]
        dx = abs(centroids[0].x() - centroids[1].x())
        expected_stride = cell_w + padding
        assert dx == pytest.approx(expected_stride, abs=0.5), (
            f"Centroid spacing {dx} should be cell_w + padding = {expected_stride}"
        )

    def test_auto_cell_size_no_grid_padding_baked_in(self, qgis_app):
        """Auto cell size should NOT include grid padding in cell dimensions."""
        fields = make_fields()
        feat = _make_square_feature(0.0, 0.0, 5.0, 'sq', 10.0, fields)
        layer = make_layer([feat])

        features_no_pad, _, _, _ = _run_grid_arrangement(
            layer, grid_columns=1, grid_padding=0.0)

        fields2 = make_fields()
        feat2 = _make_square_feature(0.0, 0.0, 5.0, 'sq', 10.0, fields2)
        layer2 = make_layer([feat2])

        features_pad, _, _, _ = _run_grid_arrangement(
            layer2, grid_columns=1, grid_padding=100.0)

        bbox_no_pad = features_no_pad[0].geometry().boundingBox()
        bbox_pad = features_pad[0].geometry().boundingBox()
        assert bbox_no_pad.width() == pytest.approx(bbox_pad.width(), abs=0.1), (
            "Feature bbox should be same size regardless of grid padding"
        )


# ===========================================================================
# Internal padding
# ===========================================================================

class TestInternalPadding:
    """Internal padding separates features from grid cell borders."""

    def test_internal_padding_increases_cell_spacing(self, qgis_app):
        """Internal padding increases auto cell size and centroid spacing."""
        fields = make_fields()
        feats = [
            _make_square_feature(0.0, 0.0, 0.3, f'f{i}', float(i), fields)
            for i in range(2)
        ]
        layer_no = make_layer(feats)
        features_no, _, _, _ = _run_grid_arrangement(
            layer_no, grid_columns=2, grid_internal_padding=0.0)

        feats2 = [
            _make_square_feature(0.0, 0.0, 0.3, f'f{i}', float(i), fields)
            for i in range(2)
        ]
        layer_yes = make_layer(feats2)
        features_yes, _, _, _ = _run_grid_arrangement(
            layer_yes, grid_columns=2, grid_internal_padding=5.0)

        def centroid_dx(features):
            pts = [f.geometry().centroid().asPoint() for f in features]
            return abs(pts[0].x() - pts[1].x())

        assert centroid_dx(features_yes) > centroid_dx(features_no), (
            "Internal padding should increase centroid spacing"
        )

    def test_internal_padding_adds_twice_to_auto_cell(self, qgis_app):
        """Auto cell = max_bbox + 2 * internal_padding (both sides)."""
        fields = make_fields()
        feats = [
            _make_square_feature(0.0, 0.0, 0.3, f'f{i}', float(i), fields)
            for i in range(2)
        ]
        layer = make_layer(feats)

        internal_pad = 10.0
        features, _, _, _ = _run_grid_arrangement(
            layer, grid_columns=2, grid_internal_padding=internal_pad,
            grid_padding=0.0)

        centroids = [f.geometry().centroid().asPoint() for f in features]
        dx = abs(centroids[0].x() - centroids[1].x())
        feat_w = features[0].geometry().boundingBox().width()
        expected_cell_w = feat_w + 2 * internal_pad
        assert dx == pytest.approx(expected_cell_w, abs=1.0), (
            f"Centroid spacing {dx} should equal bbox_w + 2*internal_pad = {expected_cell_w}"
        )
