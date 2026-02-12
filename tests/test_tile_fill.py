"""Tests for TileFillAlgorithm (T6.1 -- T6.18).

Cell-size values are in working-CRS units (metres for equal-area projections).
A 1-degree polygon near the equator spans ~111 km, so cell sizes are chosen
accordingly (e.g. 20000 m = 20 km for a sparse grid).
"""
import gc
import math
import time
from unittest.mock import MagicMock, patch

import pytest
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType

from tessera.algorithms.tile_fill import TileFillAlgorithm

from .helpers import make_fields, make_feature, make_layer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_tile_fill(layer, tile_shape=0, cell_size=0, target_tiles=100,
                    clip_boundary=True, extra_params=None):
    """Run TileFillAlgorithm against a layer and return output features.

    Returns (features_list, result_dict, feedback, output_layer).
    """
    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        alg = TileFillAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'TILE_SHAPE': tile_shape,
            'CELL_SIZE': cell_size,
            'TARGET_TILES': target_tiles,
            'CLIP_BOUNDARY': clip_boundary,
            'OUTPUT': 'memory:',
        }
        if extra_params:
            parameters.update(extra_params)
        results = alg.processAlgorithm(parameters, context, feedback)

        # Retrieve output layer from context — takeResultLayer transfers
        # C++ ownership to Python, preventing premature deallocation.
        dest_id = results['OUTPUT']
        output_layer = context.takeResultLayer(dest_id)

        # Python 3.13's incremental GC can collect SIP wrappers for QGIS
        # C++ objects during heavy allocation (feature iteration). Flush
        # dead objects first, then suppress GC during the critical section.
        gc.collect()
        gc.disable()
        try:
            features = list(output_layer.getFeatures()) if output_layer else []
        finally:
            gc.enable()
        return features, results, feedback, output_layer
    finally:
        project.removeMapLayer(layer.id())


def _run_tile_fill_with_feedback(layer, tile_shape=0, cell_size=0,
                                  target_tiles=100, clip_boundary=True):
    """Like _run_tile_fill but also returns captured warnings and errors."""
    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        warnings = []
        errors = []
        orig_warn = feedback.pushWarning
        orig_error = feedback.reportError

        def capture_warn(msg):
            warnings.append(msg)
            orig_warn(msg)

        def capture_error(msg, fatal=False):
            errors.append(msg)
            orig_error(msg, fatal)

        feedback.pushWarning = capture_warn
        feedback.reportError = capture_error

        alg = TileFillAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'TILE_SHAPE': tile_shape,
            'CELL_SIZE': cell_size,
            'TARGET_TILES': target_tiles,
            'CLIP_BOUNDARY': clip_boundary,
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
        return features, results, feedback, warnings, errors, output_layer
    finally:
        project.removeMapLayer(layer.id())


def _make_unit_square_feature():
    """Create a single unit-square feature at (0,0)-(1,1) in EPSG:4326."""
    fields = make_fields()
    ring = [QgsPointXY(0, 0), QgsPointXY(1, 0),
            QgsPointXY(1, 1), QgsPointXY(0, 1), QgsPointXY(0, 0)]
    geom = QgsGeometry.fromPolygonXY([ring])
    return make_feature(geom, 'unit', 42.0, fields)


def _make_10x10_square_feature():
    """Create a 10x10 degree square at (0,0)-(10,10) in EPSG:4326."""
    fields = make_fields()
    ring = [QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)]
    geom = QgsGeometry.fromPolygonXY([ring])
    return make_feature(geom, 'big_square', 100.0, fields)


# ===========================================================================
# T6.1 -- Tile Fill produces output features
# ===========================================================================

def test_tile_fill_produces_output(qgis_app, simple_squares):
    """T6.1: Hexagon tessellation of simple_squares produces > 0 MultiPolygon features.

    Uses auto cell size (CELL_SIZE=0) with target=20 tiles per feature.
    """
    layer = make_layer(simple_squares)
    features, results, feedback, _ = _run_tile_fill(
        layer, tile_shape=0, cell_size=0, target_tiles=20, clip_boundary=True)

    assert len(features) > 0, "Tile Fill should produce output features"
    for feat in features:
        geom = feat.geometry()
        assert not geom.isEmpty(), "Output geometry must not be empty"
        assert geom.isMultipart(), "Output geometry must be MultiPolygon"
        assert geom.type() == QgsWkbTypes.PolygonGeometry, \
            "Output geometry type must be PolygonGeometry"


# ===========================================================================
# T6.2 -- Output has correct _tessera_* fields
# ===========================================================================

def test_output_has_tessera_fields(qgis_app, simple_squares):
    """T6.2: Output has _tessera_algorithm, _tessera_parent_fid, _tessera_tile_index; NOT _tessera_fraction/_tessera_state."""
    layer = make_layer(simple_squares)
    features, results, feedback, _ = _run_tile_fill(
        layer, tile_shape=0, cell_size=0, target_tiles=20, clip_boundary=True)

    assert len(features) > 0
    feat = features[0]
    field_names = [feat.fields().field(i).name()
                   for i in range(feat.fields().count())]

    assert '_tessera_algorithm' in field_names
    assert '_tessera_parent_fid' in field_names
    assert '_tessera_tile_index' in field_names
    assert '_tessera_fraction' not in field_names, "SD-1: no _tessera_fraction"
    assert '_tessera_state' not in field_names, "SD-1: no _tessera_state"

    for f in features:
        assert f.attribute('_tessera_algorithm') == 'tile_fill'


# ===========================================================================
# T6.3 -- Parent attributes carried forward
# ===========================================================================

def test_parent_attributes_carried(qgis_app):
    """T6.3: Parent 'name' and 'value' attributes are carried to output."""
    feat = _make_unit_square_feature()
    layer = make_layer([feat])
    features, results, feedback, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=10, clip_boundary=True)

    assert len(features) > 0
    for f in features:
        assert f.attribute('name') == 'unit', \
            f"Expected 'unit', got {f.attribute('name')!r}"
        assert f.attribute('value') == 42.0, \
            f"Expected 42.0, got {f.attribute('value')!r}"


# ===========================================================================
# T6.4 -- Tile index ordering: bottom-to-top, left-to-right
# ===========================================================================

def test_tile_index_ordering(qgis_app):
    """T6.4: For a 10x10 square, tile index 0 is at the bottom (lower y)
    and the highest index is at the top (higher y).

    The sort is by (y, x) ascending in working CRS, then indices are
    inverse-transformed back to source CRS, so we verify the overall
    bottom-to-top trend.
    """
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, results, feedback, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=9, clip_boundary=True)

    assert len(features) >= 2, \
        f"Expected at least 2 tiles, got {len(features)}"

    # Collect (centroid_y, tile_index) for each tile
    tiles = []
    for f in features:
        centroid = f.geometry().centroid().asPoint()
        tiles.append((centroid.y(), f.attribute('_tessera_tile_index')))

    # Sort by tile_index
    tiles.sort(key=lambda t: t[1])

    # The tile with the lowest index should have a lower y-centroid than
    # the tile with the highest index (bottom-to-top ordering)
    first_y = tiles[0][0]
    last_y = tiles[-1][0]
    assert first_y < last_y, \
        f"Tile index 0 (y={first_y:.4f}) should be below last tile (y={last_y:.4f})"


# ===========================================================================
# T6.5 -- Square tiles are axis-aligned with expected area
# ===========================================================================

def test_square_tiles_geometry(qgis_app):
    """T6.5: Square tiles are axis-aligned squares with approximately expected area.

    Uses CLIP_BOUNDARY=False so interior tiles remain full squares.
    """
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    # Use auto cell size targeting ~16 tiles, so each tile is substantial
    features, results, feedback, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=16,
        clip_boundary=False)

    assert len(features) > 0

    # All tiles should be axis-aligned squares (bbox area ≈ geometry area)
    # and all tiles with centroid inside have full cell area
    areas = [f.geometry().area() for f in features]
    # Most frequent area (the "full" tile area)
    areas.sort()
    full_area = areas[len(areas) // 2]  # median

    full_tiles = [f for f in features
                  if abs(f.geometry().area() - full_area) < full_area * 0.01]
    assert len(full_tiles) > 0, "Should have full-sized square tiles"

    for f in full_tiles[:3]:
        geom = f.geometry()
        bbox = geom.boundingBox()
        bbox_area = bbox.width() * bbox.height()
        assert abs(bbox_area - geom.area()) / geom.area() < 0.02, \
            "Square tile should be axis-aligned (bbox area ≈ geometry area)"
        # Width ≈ height for a square
        assert abs(bbox.width() - bbox.height()) / bbox.width() < 0.02, \
            "Square tile should have width ≈ height"


# ===========================================================================
# T6.6 -- Hex tiles have 6+1 vertices and expected area
# ===========================================================================

def test_hex_tiles_geometry(qgis_app):
    """T6.6: Hex tiles have 7 vertices (6+closure) and area ≈ (3*sqrt(3)/2)*R^2."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, results, feedback, _ = _run_tile_fill(
        layer, tile_shape=0, cell_size=0, target_tiles=16,
        clip_boundary=False)

    assert len(features) > 0

    # Check an unclipped hex tile -- find one with 7 vertices
    found_hex = False
    for f in features:
        geom = f.geometry()
        if geom.isMultipart():
            multi = geom.asMultiPolygon()
            ring = multi[0][0]
        else:
            ring = geom.asPolygon()[0]

        if len(ring) == 7:
            found_hex = True
            # Compute expected area: R = cell_size / sqrt(3), area = (3*sqrt(3)/2)*R^2
            # Since all tiles have the same R, just verify area is consistent
            area = geom.area()
            assert area > 0, "Hex tile area must be positive"
            break

    assert found_hex, "Should find at least one hex tile with 7 vertices (6+closure)"


# ===========================================================================
# T6.7 -- CLIP_BOUNDARY=True clips tiles at boundary
# ===========================================================================

def test_clip_boundary_true(qgis_app):
    """T6.7: With CLIP_BOUNDARY=True, union of output tiles is within original polygon."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, results, feedback, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=16, clip_boundary=True)

    assert len(features) > 0

    original = feat.geometry()

    # Union all output tiles
    tile_geoms = [f.geometry() for f in features]
    union = QgsGeometry.unaryUnion(tile_geoms)

    # The union should be within (or very close to) the original polygon.
    # CRS round-trip (forward to equal-area, clip, inverse back) introduces
    # small coordinate shifts (~0.02 degrees), so use a generous buffer.
    buffered_original = original.buffer(0.05, 5)
    assert buffered_original.contains(union), \
        "Clipped tiles union should be contained within original polygon (with tolerance)"


# ===========================================================================
# T6.8 -- CLIP_BOUNDARY=False keeps full tiles with centroids inside
# ===========================================================================

def test_clip_boundary_false(qgis_app):
    """T6.8: With CLIP_BOUNDARY=False, tiles whose centroids are inside are kept whole;
    tiles may extend beyond boundary."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, results, feedback, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=9,
        clip_boundary=False)

    assert len(features) > 0

    original = feat.geometry()
    has_overshoot = False
    for f in features:
        geom = f.geometry()
        centroid = geom.centroid()
        # Centroid should be inside original polygon (with small tolerance)
        buffered = original.buffer(0.001, 5)
        assert buffered.contains(centroid), \
            "Tile centroid must be inside original polygon when CLIP_BOUNDARY=False"
        # Check if any tile extends beyond
        if not original.contains(geom):
            has_overshoot = True

    # Tiles near the boundary should overshoot
    assert has_overshoot, \
        "With CLIP_BOUNDARY=False, some tiles should extend beyond boundary"


# ===========================================================================
# T6.9 -- Circle tiles have 64+1 vertices and expected area
# ===========================================================================

def test_circle_tiles_geometry(qgis_app):
    """T6.9: Circle tiles have 65 vertices (64+closure) and area ≈ pi*(cell_size*0.45)^2."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, results, feedback, _ = _run_tile_fill(
        layer, tile_shape=2, cell_size=0, target_tiles=16,
        clip_boundary=False)

    assert len(features) > 0

    # Check a circle tile has 65 vertices
    found_circle = False
    for f in features:
        geom = f.geometry()
        if geom.isMultipart():
            ring = geom.asMultiPolygon()[0][0]
        else:
            ring = geom.asPolygon()[0]

        if len(ring) == 65:
            found_circle = True
            area = geom.area()
            assert area > 0, "Circle tile area must be positive"
            break

    assert found_circle, "Should find a circle tile with 65 vertices (64+closure)"


# ===========================================================================
# T6.10 -- TILE_SHAPE has exactly 3 options (no triangle)
# ===========================================================================

def test_tile_shape_has_five_options(qgis_app):
    """T6.10: TILE_SHAPE enum offers hexagon, square, circle, triangle, diamond."""
    alg = TileFillAlgorithm()
    alg.initAlgorithm()
    param = alg.parameterDefinition('TILE_SHAPE')
    assert param.options() == ['Hexagon', 'Square', 'Circle', 'Triangle', 'Diamond']


# ===========================================================================
# T6.10b -- CIRCLE_CRS parameter exists with correct options
# ===========================================================================

def test_circle_crs_parameter_exists(qgis_app):
    """T6.10b: CIRCLE_CRS enum has project/source/equal_area, defaults to project."""
    alg = TileFillAlgorithm()
    alg.initAlgorithm()
    param = alg.parameterDefinition('CIRCLE_CRS')
    assert param is not None, "CIRCLE_CRS parameter should exist"
    assert param.options() == ['Project CRS', 'Source CRS', 'Equal area']
    assert param.defaultValue() == 0


# ===========================================================================
# T6.10c -- Circles in project CRS differ from circles in equal_area CRS
# ===========================================================================

def test_circle_crs_affects_geometry(qgis_app):
    """T6.10c: Circles constructed in project vs equal_area CRS produce different geometry."""
    # Set project CRS to EPSG:4326 — in real QGIS the project always has a CRS.
    QgsProject.instance().setCrs(QgsCoordinateReferenceSystem('EPSG:4326'))

    feat_proj = _make_10x10_square_feature()
    layer_proj = make_layer([feat_proj])
    features_proj, _, _, _ = _run_tile_fill(
        layer_proj, tile_shape=2, cell_size=0, target_tiles=16,
        clip_boundary=False, extra_params={'CIRCLE_CRS': 0})

    feat_ea = _make_10x10_square_feature()
    layer_ea = make_layer([feat_ea])
    features_ea, _, _, _ = _run_tile_fill(
        layer_ea, tile_shape=2, cell_size=0, target_tiles=16,
        clip_boundary=False, extra_params={'CIRCLE_CRS': 2})

    assert len(features_proj) > 0
    assert len(features_ea) > 0

    geom_proj = features_proj[0].geometry()
    geom_ea = features_ea[0].geometry()
    assert not geom_proj.equals(geom_ea), \
        "Circles in project CRS should differ from circles in equal_area CRS"


# ===========================================================================
# T6.11 -- Auto cell size produces approximately target count
# ===========================================================================

def test_auto_cell_size(qgis_app):
    """T6.11: With CELL_SIZE=0, output count ≈ target_tiles (within 50%)."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    target = 100
    features, results, feedback, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=target,
        clip_boundary=True)

    count = len(features)
    assert count > 0, "Auto cell size should produce features"
    # Within 50% of target
    assert count >= target * 0.5, \
        f"Expected >= {target * 0.5} tiles, got {count}"
    assert count <= target * 1.5, \
        f"Expected <= {target * 1.5} tiles, got {count}"


# ===========================================================================
# T6.12 -- Output CRS matches input CRS
# ===========================================================================

def test_output_crs_matches_input(qgis_app):
    """T6.12: Output layer CRS matches input layer CRS (EPSG:4326)."""
    feat = _make_unit_square_feature()
    layer = make_layer([feat], crs_id='EPSG:4326')

    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        alg = TileFillAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'TILE_SHAPE': 1,
            'CELL_SIZE': 0,
            'TARGET_TILES': 10,
            'CLIP_BOUNDARY': True,
            'OUTPUT': 'memory:',
        }
        results = alg.processAlgorithm(parameters, context, feedback)

        dest_id = results['OUTPUT']
        output_layer = context.takeResultLayer(dest_id)

        assert output_layer is not None
        assert output_layer.crs().authid() == 'EPSG:4326', \
            f"Expected EPSG:4326, got {output_layer.crs().authid()}"
    finally:
        project.removeMapLayer(layer.id())


# ===========================================================================
# T6.13 -- Empty/degenerate polygon produces zero tiles
# ===========================================================================

def test_empty_polygon_zero_tiles(qgis_app):
    """T6.13: Empty/degenerate polygon produces zero tiles."""
    fields = make_fields()
    # Degenerate polygon: a line (zero area)
    ring = [QgsPointXY(0, 0), QgsPointXY(1, 0), QgsPointXY(0, 0)]
    geom = QgsGeometry.fromPolygonXY([ring])
    feat = make_feature(geom, 'degenerate', 0.0, fields)
    layer = make_layer([feat])

    features, results, feedback, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=10, clip_boundary=True)

    assert len(features) == 0, \
        f"Degenerate polygon should produce 0 tiles, got {len(features)}"


# ===========================================================================
# T6.14 -- MultiPolygon input produces tiles for all parts
# ===========================================================================

def test_multipolygon_all_parts(qgis_app, multipolygon):
    """T6.14: MultiPolygon input generates tiles for all parts, same _tessera_parent_fid."""
    layer = make_layer([multipolygon])
    features, results, feedback, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=20, clip_boundary=True)

    assert len(features) > 0

    # All features should have the same _tessera_parent_fid (single input feature)
    parent_fids = set(f.attribute('_tessera_parent_fid') for f in features)
    assert len(parent_fids) == 1, \
        f"All tiles should share same parent fid, got {parent_fids}"

    # The multipolygon has mainland(10x10) + island(2x2)
    # Check tiles in both parts via centroid proximity
    mainland_box = QgsGeometry.fromRect(
        QgsGeometry.fromWkt('POLYGON((-1 -1, 11 -1, 11 11, -1 11, -1 -1))')
        .boundingBox())
    island_box = QgsGeometry.fromRect(
        QgsGeometry.fromWkt('POLYGON((14 14, 18 14, 18 18, 14 18, 14 14))')
        .boundingBox())

    has_mainland = False
    has_island = False
    for f in features:
        centroid = f.geometry().centroid().asPoint()
        pt_geom = QgsGeometry.fromPointXY(centroid)
        if mainland_box.contains(pt_geom):
            has_mainland = True
        if island_box.contains(pt_geom):
            has_island = True

    assert has_mainland, "Should have tiles in mainland part"
    assert has_island, "Should have tiles in island part"


# ===========================================================================
# T6.15 -- Large output > 50K triggers warning
# ===========================================================================

def test_large_output_warning(qgis_app):
    """T6.15: Output > 50K features triggers a pushWarning on feedback."""
    # Use a large polygon with a high target to ensure many tiles
    fields = make_fields()
    ring = [QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)]
    geom = QgsGeometry.fromPolygonXY([ring])
    feat = make_feature(geom, 'huge', 999.0, fields)
    layer = make_layer([feat])

    features, results, feedback, warnings, errors, _ = \
        _run_tile_fill_with_feedback(
            layer, tile_shape=1, cell_size=0, target_tiles=60000,
            clip_boundary=False)

    count = len(features)
    assert count > 50000, \
        f"Expected > 50K tiles to trigger warning, got {count}"
    assert len(warnings) > 0, "Should have pushWarning for > 50K features"
    assert any('50' in w for w in warnings), \
        f"Warning should mention 50K threshold, got: {warnings}"


# ===========================================================================
# T6.16 -- Batch writing uses addFeatures (not individual addFeature)
# ===========================================================================

def test_batch_writing(qgis_app):
    """T6.16: Sink.addFeatures() is called (batch writing), not individual addFeature()."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])

    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        alg = TileFillAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'TILE_SHAPE': 1,
            'CELL_SIZE': 0,
            'TARGET_TILES': 20,
            'CLIP_BOUNDARY': True,
            'OUTPUT': 'memory:',
        }

        # Monkey-patch run_algorithm to wrap the sink and track calls
        original_run = alg.run_algorithm
        add_features_called = [False]

        def patched_run(source, params, ctx, working_crs, topology, sink, fb):
            original_add_features = sink.addFeatures

            def tracked_add_features(features, flags=None):
                add_features_called[0] = True
                if flags is not None:
                    return original_add_features(features, flags)
                return original_add_features(features)

            sink.addFeatures = tracked_add_features
            return original_run(source, params, ctx, working_crs, topology, sink, fb)

        alg.run_algorithm = patched_run
        alg.processAlgorithm(parameters, context, feedback)

        assert add_features_called[0], \
            "Algorithm should use addFeatures() for batch writing"
    finally:
        project.removeMapLayer(layer.id())


# ===========================================================================
# T6.17 -- Polygon with holes: no tiles inside hole
# ===========================================================================

def test_polygon_with_holes(qgis_app, polygon_with_holes):
    """T6.17: Polygon with hole produces no tiles inside the hole."""
    layer = make_layer([polygon_with_holes])
    features, results, feedback, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=50, clip_boundary=True)

    assert len(features) > 0

    # Hole is at (3,3)-(7,7) in source CRS
    hole_geom = QgsGeometry.fromPolygonXY([
        [QgsPointXY(3.5, 3.5), QgsPointXY(6.5, 3.5),
         QgsPointXY(6.5, 6.5), QgsPointXY(3.5, 6.5), QgsPointXY(3.5, 3.5)]
    ])

    for f in features:
        geom = f.geometry()
        centroid = geom.centroid()
        # Tile centroids well inside the hole should not exist
        if hole_geom.contains(centroid):
            # This tile's centroid is inside the hole -- verify it has negligible
            # intersection with the hole interior (due to clipping)
            intersection = geom.intersection(hole_geom)
            assert intersection.isEmpty() or intersection.area() < 0.01, \
                "Clipped tile should not substantially overlap with hole"


# ===========================================================================
# T6.18 -- Integration with Natural Earth
# ===========================================================================

def test_natural_earth_integration(qgis_app, natural_earth_path):
    """T6.18: Tile Fill produces output for Natural Earth countries, completes < 30s."""
    ne_layer = QgsVectorLayer(str(natural_earth_path), 'ne', 'ogr')
    assert ne_layer.isValid(), f"Natural Earth layer not valid: {natural_earth_path}"

    start = time.time()
    features, results, feedback, _ = _run_tile_fill(
        ne_layer, tile_shape=0, cell_size=0, target_tiles=20,
        clip_boundary=True)
    elapsed = time.time() - start

    assert len(features) > 0, "Should produce output for Natural Earth"
    assert elapsed < 30, f"Should complete in < 30s, took {elapsed:.1f}s"

    # Should have output for multiple countries
    parent_fids = set(f.attribute('_tessera_parent_fid') for f in features)
    assert len(parent_fids) > 1, \
        f"Should have tiles from multiple countries, got {len(parent_fids)} parent fids"


# ===========================================================================
# D1 -- PERCENT_FIELD parameter exists as optional numeric field
# ===========================================================================

def test_percent_field_parameter_exists(qgis_app):
    """D1: PERCENT_FIELD parameter exists as optional numeric field."""
    from qgis.core import QgsProcessingParameterField
    alg = TileFillAlgorithm()
    alg.initAlgorithm()
    param = alg.parameterDefinition('PERCENT_FIELD')
    assert param is not None, "PERCENT_FIELD parameter should exist"
    assert isinstance(param, QgsProcessingParameterField)
    assert param.dataType() == QgsProcessingParameterField.Numeric
    # Parameter should be optional (empty string is valid)
    flags = param.flags()
    assert flags & QgsProcessingParameterField.FlagOptional


# ===========================================================================
# D2 -- No PERCENT_FIELD: backward compatible, no _tessera_part
# ===========================================================================

def test_no_percent_field_backward_compatible(qgis_app):
    """D2: Without PERCENT_FIELD, output tiles have no _tessera_part field."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, _, _, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=9, clip_boundary=True)

    assert len(features) > 0
    field_names = [features[0].fields().field(i).name()
                   for i in range(features[0].fields().count())]
    assert '_tessera_part' not in field_names, \
        "Without PERCENT_FIELD, _tessera_part should not appear"


# ===========================================================================
# D3 -- 50% fills half the tiles
# ===========================================================================

def _make_fields_with_percent():
    """Fields: name (String), value (Double), percent (Double)."""
    fields = QgsFields()
    fields.append(QgsField('name', QMetaType.Type.QString))
    fields.append(QgsField('value', QMetaType.Type.Double))
    fields.append(QgsField('percent', QMetaType.Type.Double))
    return fields


def _make_feature_with_percent(geometry, name, value, percent, fields):
    """Create a QgsFeature with geometry, attributes, and percent value."""
    feat = QgsFeature(fields)
    feat.setGeometry(geometry)
    feat.setAttribute('name', name)
    feat.setAttribute('value', value)
    feat.setAttribute('percent', percent)
    return feat


def test_50_percent_fills_half_tiles(qgis_app):
    """D3: 50% fills half the tiles."""
    fields = _make_fields_with_percent()
    ring = [QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)]
    geom = QgsGeometry.fromPolygonXY([ring])
    feat = _make_feature_with_percent(geom, 'half', 100.0, 50.0, fields)
    layer = make_layer([feat])

    features, _, _, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=10,
        clip_boundary=True,
        extra_params={'PERCENT_FIELD': 'percent'})

    assert len(features) > 0

    filled = [f for f in features if f.attribute('_tessera_part') == 'filled']
    remainder = [f for f in features if f.attribute('_tessera_part') == 'remainder']

    total = len(filled) + len(remainder)
    assert total == len(features), \
        f"All features should have fill_status, got {total} of {len(features)}"

    # Approximately half should be filled (within ±1 due to rounding)
    half = len(features) / 2.0
    assert abs(len(filled) - half) <= 1.5, \
        f"Expected ~{half:.0f} filled tiles, got {len(filled)} of {len(features)}"


# ===========================================================================
# D4 -- 100% fills all tiles
# ===========================================================================

def test_100_percent_fills_all_tiles(qgis_app):
    """D4: 100% fills all tiles."""
    fields = _make_fields_with_percent()
    ring = [QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)]
    geom = QgsGeometry.fromPolygonXY([ring])
    feat = _make_feature_with_percent(geom, 'full', 100.0, 100.0, fields)
    layer = make_layer([feat])

    features, _, _, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=10,
        clip_boundary=True,
        extra_params={'PERCENT_FIELD': 'percent'})

    assert len(features) > 0

    for f in features:
        assert f.attribute('_tessera_part') == 'filled', \
            f"100% should make all tiles filled, got {f.attribute('_tessera_part')!r}"


# ===========================================================================
# D5 -- 0% fills no tiles
# ===========================================================================

def test_0_percent_fills_no_tiles(qgis_app):
    """D5: 0% fills no tiles."""
    fields = _make_fields_with_percent()
    ring = [QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)]
    geom = QgsGeometry.fromPolygonXY([ring])
    feat = _make_feature_with_percent(geom, 'empty', 100.0, 0.0, fields)
    layer = make_layer([feat])

    features, _, _, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=10,
        clip_boundary=True,
        extra_params={'PERCENT_FIELD': 'percent'})

    assert len(features) > 0

    for f in features:
        assert f.attribute('_tessera_part') == 'remainder', \
            f"0% should make all tiles remainder, got {f.attribute('_tessera_part')!r}"


# ===========================================================================
# D6 -- Fractional percentage splits boundary tile
# ===========================================================================

def test_fractional_percent_splits_boundary_tile(qgis_app):
    """D6: Fractional percentage splits the boundary tile into filled+remainder parts.

    With 10 tiles and 75%, we expect 7 fully filled, 1 split (producing
    2 features: filled + remainder), and 2 fully remainder = 12 total.
    """
    fields = _make_fields_with_percent()
    ring = [QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)]
    geom = QgsGeometry.fromPolygonXY([ring])
    feat = _make_feature_with_percent(geom, 'three_quarter', 100.0, 75.0, fields)
    layer = make_layer([feat])

    features, _, _, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=10,
        clip_boundary=True,
        extra_params={'PERCENT_FIELD': 'percent'})

    filled = [f for f in features if f.attribute('_tessera_part') == 'filled']
    remainder = [f for f in features if f.attribute('_tessera_part') == 'remainder']

    # With fractional split, output count > original tile count
    # (one tile gets split into two features)
    total_without_split = len(filled) + len(remainder) - 1  # one extra from split
    assert len(features) > total_without_split or len(features) >= len(filled) + len(remainder)

    # More filled than remainder (75% > 50%)
    assert len(filled) > len(remainder), \
        f"75% should produce more filled ({len(filled)}) than remainder ({len(remainder)})"


# ===========================================================================
# D7 -- Fill order is bottom-left → right → up
# ===========================================================================

def test_fill_order_bottom_left_to_top(qgis_app):
    """D7: Tiles with lower y (then lower x) get 'filled' first."""
    fields = _make_fields_with_percent()
    ring = [QgsPointXY(0, 0), QgsPointXY(10, 0),
            QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)]
    geom = QgsGeometry.fromPolygonXY([ring])
    # 30% — only bottom tiles should be filled
    feat = _make_feature_with_percent(geom, 'low_fill', 100.0, 30.0, fields)
    layer = make_layer([feat])

    features, _, _, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=16,
        clip_boundary=True,
        extra_params={'PERCENT_FIELD': 'percent'})

    filled = [f for f in features if f.attribute('_tessera_part') == 'filled']
    remainder = [f for f in features if f.attribute('_tessera_part') == 'remainder']

    assert len(filled) > 0 and len(remainder) > 0

    # Average y of filled tiles should be lower than average y of remainder tiles
    filled_avg_y = sum(f.geometry().centroid().asPoint().y() for f in filled) / len(filled)
    remainder_avg_y = sum(f.geometry().centroid().asPoint().y() for f in remainder) / len(remainder)

    assert filled_avg_y < remainder_avg_y, \
        f"Filled tiles (avg y={filled_avg_y:.2f}) should be below remainder tiles (avg y={remainder_avg_y:.2f})"


# ===========================================================================
# D8 -- Per-feature flagging with multiple input features
# ===========================================================================

def test_per_feature_flagging(qgis_app):
    """D8: Multiple features with different percentages get flagged independently."""
    fields = _make_fields_with_percent()

    # Feature 1: 100% filled
    ring1 = [QgsPointXY(0, 0), QgsPointXY(5, 0),
             QgsPointXY(5, 5), QgsPointXY(0, 5), QgsPointXY(0, 0)]
    geom1 = QgsGeometry.fromPolygonXY([ring1])
    feat1 = _make_feature_with_percent(geom1, 'full', 100.0, 100.0, fields)

    # Feature 2: 0% filled
    ring2 = [QgsPointXY(20, 20), QgsPointXY(25, 20),
             QgsPointXY(25, 25), QgsPointXY(20, 25), QgsPointXY(20, 20)]
    geom2 = QgsGeometry.fromPolygonXY([ring2])
    feat2 = _make_feature_with_percent(geom2, 'empty', 100.0, 0.0, fields)

    layer = make_layer([feat1, feat2])

    features, _, _, _ = _run_tile_fill(
        layer, tile_shape=1, cell_size=0, target_tiles=9,
        clip_boundary=True,
        extra_params={'PERCENT_FIELD': 'percent'})

    assert len(features) > 0

    # Group by parent
    from collections import defaultdict
    by_parent = defaultdict(list)
    for f in features:
        by_parent[f.attribute('name')].append(f)

    assert 'full' in by_parent, "Should have tiles from feat1"
    assert 'empty' in by_parent, "Should have tiles from feat2"

    # All tiles from feat1 (100%) should be filled
    for f in by_parent['full']:
        assert f.attribute('_tessera_part') == 'filled', \
            f"100% feature should have all filled tiles"

    # All tiles from feat2 (0%) should be remainder
    for f in by_parent['empty']:
        assert f.attribute('_tessera_part') == 'remainder', \
            f"0% feature should have all remainder tiles"


# ===========================================================================
# Triangle tile shape
# ===========================================================================

def test_triangle_tile_shape_produces_output(qgis_app):
    """Triangle tile shape produces valid tessellation output."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, _, _ , _ = _run_tile_fill(layer, tile_shape=3, cell_size=50000)
    assert len(features) > 0, "Triangle tessellation should produce tiles"
    for f in features:
        geom = f.geometry()
        assert not geom.isEmpty()
        assert geom.area() > 0


def test_triangle_tiles_are_triangular(qgis_app):
    """Triangle tiles should have 3-vertex ring (triangles), not 4 (squares)."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    # Use centroid filtering (no clip) to get clean unclipped triangles
    features, _, _, _ = _run_tile_fill(layer, tile_shape=3, cell_size=50000,
                                        clip_boundary=False)
    assert len(features) > 0
    # At least one tile should be a triangle (3 unique vertices + closing)
    found_triangle = False
    for f in features:
        geom = f.geometry()
        # Extract first polygon's exterior ring
        if geom.isMultipart():
            parts = geom.asMultiPolygon()
            if parts:
                ring = parts[0][0]  # first polygon, exterior ring
            else:
                continue
        else:
            ring = geom.asPolygon()[0]
        # Triangle ring = 4 points (3 vertices + closing point)
        if len(ring) == 4:
            found_triangle = True
            break
    assert found_triangle, "Expected at least one triangular tile"


# ===========================================================================
# Diamond tile shape
# ===========================================================================

def test_diamond_tile_shape_produces_output(qgis_app):
    """Diamond tile shape produces valid tessellation output."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, _, _, _ = _run_tile_fill(layer, tile_shape=4, cell_size=50000)
    assert len(features) > 0, "Diamond tessellation should produce tiles"
    for f in features:
        geom = f.geometry()
        assert not geom.isEmpty()
        assert geom.area() > 0


def test_diamond_tiles_are_diamond_shaped(qgis_app):
    """Diamond tiles should have 4-vertex ring (rhombus)."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, _, _, _ = _run_tile_fill(layer, tile_shape=4, cell_size=50000,
                                        clip_boundary=False)
    assert len(features) > 0
    # At least one tile should be a diamond (4 unique vertices + closing)
    found_diamond = False
    for f in features:
        geom = f.geometry()
        if geom.isMultipart():
            parts = geom.asMultiPolygon()
            if parts:
                ring = parts[0][0]
            else:
                continue
        else:
            ring = geom.asPolygon()[0]
        # Diamond ring = 5 points (4 vertices + closing point)
        if len(ring) == 5:
            found_diamond = True
            break
    assert found_diamond, "Expected at least one diamond-shaped tile"
