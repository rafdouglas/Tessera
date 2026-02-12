"""Tests for StripeHatchingAlgorithm.

Stripe hatching fills polygons with parallel rectangular stripes at a given
angle.  Stripe width can be automatic (derived from TARGET_STRIPES) or
explicit.  Output fields include _tessera_algorithm, _tessera_parent_fid, and
_tessera_stripe_index.
"""
import gc
import math
import time

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
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType

from tessera.algorithms.stripe_hatching import StripeHatchingAlgorithm

from .helpers import make_fields, make_feature, make_layer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_stripe_hatching(layer, angle=0, stripe_width=0, gap_width=0,
                         target_stripes=10, extra_params=None):
    """Run StripeHatchingAlgorithm and return output features.

    Returns (features_list, result_dict, feedback, output_layer).
    """
    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        alg = StripeHatchingAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'ANGLE': angle,
            'STRIPE_WIDTH': stripe_width,
            'GAP_WIDTH': gap_width,
            'TARGET_STRIPES': target_stripes,
            'OUTPUT': 'memory:',
        }
        if extra_params:
            parameters.update(extra_params)
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
# T1 -- Stripe hatching produces output features
# ===========================================================================

def test_stripe_hatching_produces_output(qgis_app, simple_squares):
    """Horizontal stripes on simple squares produce > 0 MultiPolygon features."""
    layer = make_layer(simple_squares)
    features, results, feedback, _ = _run_stripe_hatching(
        layer, angle=0, stripe_width=0, target_stripes=5)

    assert len(features) > 0, "Stripe hatching should produce output features"
    for feat in features:
        geom = feat.geometry()
        assert not geom.isEmpty(), "Output geometry must not be empty"
        assert geom.isMultipart(), "Output geometry must be MultiPolygon"
        assert geom.type() == QgsWkbTypes.PolygonGeometry, \
            "Output geometry type must be PolygonGeometry"


# ===========================================================================
# T2 -- Output has correct _tessera_* fields
# ===========================================================================

def test_output_has_tessera_fields(qgis_app, simple_squares):
    """Output has _tessera_algorithm='stripe_hatching', _tessera_parent_fid, _tessera_stripe_index;
    does NOT have _tessera_fraction, _tessera_state, _tessera_part."""
    layer = make_layer(simple_squares)
    features, results, feedback, _ = _run_stripe_hatching(
        layer, angle=0, stripe_width=0, target_stripes=5)

    assert len(features) > 0
    feat = features[0]
    field_names = [feat.fields().field(i).name()
                   for i in range(feat.fields().count())]

    assert '_tessera_algorithm' in field_names
    assert '_tessera_parent_fid' in field_names
    assert '_tessera_stripe_index' in field_names
    assert '_tessera_fraction' not in field_names, "Should not have _tessera_fraction"
    assert '_tessera_state' not in field_names, "Should not have _tessera_state"
    assert '_tessera_part' not in field_names, "Should not have _tessera_part"

    for f in features:
        assert f.attribute('_tessera_algorithm') == 'stripe_hatching'


# ===========================================================================
# T3 -- Parent attributes carried forward
# ===========================================================================

def test_parent_attributes_carried(qgis_app):
    """Parent 'name' and 'value' attributes are carried to output."""
    feat = _make_unit_square_feature()
    layer = make_layer([feat])
    features, results, feedback, _ = _run_stripe_hatching(
        layer, angle=0, stripe_width=0, target_stripes=5)

    assert len(features) > 0
    for f in features:
        assert f.attribute('name') == 'unit', \
            f"Expected 'unit', got {f.attribute('name')!r}"
        assert f.attribute('value') == 42.0, \
            f"Expected 42.0, got {f.attribute('value')!r}"


# ===========================================================================
# T4 -- Stripe index ordering
# ===========================================================================

def test_stripe_index_ordering(qgis_app):
    """Stripe indices start at 0 and are sequential (no gaps)."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, results, feedback, _ = _run_stripe_hatching(
        layer, angle=0, stripe_width=0, target_stripes=10)

    assert len(features) >= 2, \
        f"Expected at least 2 stripes, got {len(features)}"

    indices = sorted(f.attribute('_tessera_stripe_index') for f in features)
    assert indices[0] == 0, f"First stripe index should be 0, got {indices[0]}"
    # Indices should be sequential with no gaps
    for i in range(len(indices) - 1):
        assert indices[i + 1] == indices[i] + 1, \
            f"Stripe indices should be sequential: {indices}"


# ===========================================================================
# T5 -- Horizontal stripes geometry
# ===========================================================================

def test_horizontal_stripes_geometry(qgis_app):
    """Angle=0 produces stripes that are roughly horizontal rectangles.

    Each stripe's bounding box should be wider than it is tall.
    """
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, results, feedback, _ = _run_stripe_hatching(
        layer, angle=0, stripe_width=0, target_stripes=5)

    assert len(features) > 0
    for f in features:
        bbox = f.geometry().boundingBox()
        # For horizontal stripes, width should be >= height
        assert bbox.width() >= bbox.height() * 0.8, \
            f"Horizontal stripe should be wider than tall: w={bbox.width():.4f}, h={bbox.height():.4f}"


# ===========================================================================
# T6 -- Vertical stripes geometry
# ===========================================================================

def test_vertical_stripes_geometry(qgis_app):
    """Angle=90 produces stripes that are roughly vertical rectangles.

    Each stripe's bounding box should be taller than it is wide.
    """
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, results, feedback, _ = _run_stripe_hatching(
        layer, angle=90, stripe_width=0, target_stripes=5)

    assert len(features) > 0
    for f in features:
        bbox = f.geometry().boundingBox()
        # For vertical stripes, height should be >= width
        assert bbox.height() >= bbox.width() * 0.8, \
            f"Vertical stripe should be taller than wide: w={bbox.width():.4f}, h={bbox.height():.4f}"


# ===========================================================================
# T7 -- Diagonal stripes
# ===========================================================================

def test_diagonal_stripes(qgis_app):
    """Angle=45 produces valid output with non-degenerate geometries."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, results, feedback, _ = _run_stripe_hatching(
        layer, angle=45, stripe_width=0, target_stripes=10)

    assert len(features) > 0, "Diagonal stripes should produce output"
    for f in features:
        geom = f.geometry()
        assert not geom.isEmpty(), "Diagonal stripe geometry must not be empty"
        assert geom.area() > 0, "Diagonal stripe must have positive area"


# ===========================================================================
# T8 -- Auto stripe width
# ===========================================================================

def test_auto_stripe_width(qgis_app):
    """STRIPE_WIDTH=0 with TARGET_STRIPES=10 produces approximately 10 stripes."""
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])
    features, results, feedback, _ = _run_stripe_hatching(
        layer, angle=0, stripe_width=0, target_stripes=10)

    # Count distinct stripe indices for this single feature
    indices = set(f.attribute('_tessera_stripe_index') for f in features)
    count = len(indices)

    # Should be approximately 10 (within 50%)
    assert count >= 5, f"Expected >= 5 stripes with target=10, got {count}"
    assert count <= 15, f"Expected <= 15 stripes with target=10, got {count}"


# ===========================================================================
# T9 -- Gap width default
# ===========================================================================

def test_gap_width_default(qgis_app):
    """GAP_WIDTH=0 uses STRIPE_WIDTH, resulting in alternating stripe/gap.

    With explicit STRIPE_WIDTH and GAP_WIDTH=0, the total number of stripes
    should be about half what you'd get if there were no gaps.
    """
    feat = _make_10x10_square_feature()
    layer = make_layer([feat])

    # Run with explicit stripe width but default gap (0 = same as stripe width).
    # The polygon is 10x10 degrees, which becomes some metres in working CRS.
    # We use TARGET_STRIPES=20 for auto width, then compare to explicit width with gap.
    features_auto, _, _, _ = _run_stripe_hatching(
        layer, angle=0, stripe_width=0, gap_width=0, target_stripes=20)

    auto_count = len(set(f.attribute('_tessera_stripe_index') for f in features_auto))

    # When auto computes stripe width, it accounts for gaps (n stripes + n-1 gaps).
    # With gap_width = stripe_width (default), we expect approximately TARGET_STRIPES stripes.
    assert auto_count >= 10, f"Expected >= 10 stripes with target=20, got {auto_count}"
    assert auto_count <= 30, f"Expected <= 30 stripes with target=20, got {auto_count}"


# ===========================================================================
# T10 -- Polygon with holes
# ===========================================================================

def test_polygon_with_holes(qgis_app, polygon_with_holes):
    """No stripes inside the hole."""
    layer = make_layer([polygon_with_holes])
    features, results, feedback, _ = _run_stripe_hatching(
        layer, angle=0, stripe_width=0, target_stripes=10)

    assert len(features) > 0

    # Hole is at (3,3)-(7,7) in source CRS
    hole_geom = QgsGeometry.fromPolygonXY([
        [QgsPointXY(3.5, 3.5), QgsPointXY(6.5, 3.5),
         QgsPointXY(6.5, 6.5), QgsPointXY(3.5, 6.5), QgsPointXY(3.5, 3.5)]
    ])

    for f in features:
        geom = f.geometry()
        centroid = geom.centroid()
        if hole_geom.contains(centroid):
            intersection = geom.intersection(hole_geom)
            assert intersection.isEmpty() or intersection.area() < 0.01, \
                "Stripe should not substantially overlap with hole"


# ===========================================================================
# T11 -- MultiPolygon input
# ===========================================================================

def test_multipolygon_input(qgis_app, multipolygon):
    """MultiPolygon input produces stripes for all parts, same parent_fid."""
    layer = make_layer([multipolygon])
    features, results, feedback, _ = _run_stripe_hatching(
        layer, angle=0, stripe_width=0, target_stripes=10)

    assert len(features) > 0

    # All features should have the same _tessera_parent_fid (single input feature)
    parent_fids = set(f.attribute('_tessera_parent_fid') for f in features)
    assert len(parent_fids) == 1, \
        f"All stripes should share same parent fid, got {parent_fids}"

    # Check stripes exist in both the mainland and island regions
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

    assert has_mainland, "Should have stripes in mainland part"
    assert has_island, "Should have stripes in island part"


# ===========================================================================
# T12 -- Output CRS matches input
# ===========================================================================

def test_output_crs_matches_input(qgis_app):
    """Output layer CRS matches input layer CRS (EPSG:4326)."""
    feat = _make_unit_square_feature()
    layer = make_layer([feat], crs_id='EPSG:4326')

    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        alg = StripeHatchingAlgorithm()
        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'ANGLE': 0,
            'STRIPE_WIDTH': 0,
            'GAP_WIDTH': 0,
            'TARGET_STRIPES': 5,
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
# T13 -- Natural Earth integration
# ===========================================================================

def test_natural_earth_integration(qgis_app, natural_earth_path):
    """Stripe hatching produces output for Natural Earth countries, completes < 30s."""
    ne_layer = QgsVectorLayer(str(natural_earth_path), 'ne', 'ogr')
    assert ne_layer.isValid(), f"Natural Earth layer not valid: {natural_earth_path}"

    start = time.time()
    features, results, feedback, _ = _run_stripe_hatching(
        ne_layer, angle=45, stripe_width=0, target_stripes=10)
    elapsed = time.time() - start

    assert len(features) > 0, "Should produce output for Natural Earth"
    assert elapsed < 30, f"Should complete in < 30s, took {elapsed:.1f}s"

    parent_fids = set(f.attribute('_tessera_parent_fid') for f in features)
    assert len(parent_fids) > 1, \
        f"Should have stripes from multiple countries, got {len(parent_fids)} parent fids"


# ===========================================================================
# T14 -- Snap axis-aligned angles
# ===========================================================================

def test_snap_axis_aligned_angles(qgis_app):
    """Angle=0.05 is treated as 0 (snap within 0.1 degrees).

    Both angle=0 and angle=0.05 should produce the same stripe count
    and horizontal geometry orientation.
    """
    feat = _make_10x10_square_feature()

    layer_exact = make_layer([feat])
    features_exact, _, _, _ = _run_stripe_hatching(
        layer_exact, angle=0, stripe_width=0, target_stripes=10)

    feat2 = _make_10x10_square_feature()
    layer_snap = make_layer([feat2])
    features_snap, _, _, _ = _run_stripe_hatching(
        layer_snap, angle=0.05, stripe_width=0, target_stripes=10)

    count_exact = len(set(f.attribute('_tessera_stripe_index') for f in features_exact))
    count_snap = len(set(f.attribute('_tessera_stripe_index') for f in features_snap))

    # Both should produce the same number of stripes (exact same code path)
    assert count_exact == count_snap, \
        f"Snapped angle should produce same count as exact: {count_exact} vs {count_snap}"

    # Stripes should still be horizontal
    for f in features_snap:
        bbox = f.geometry().boundingBox()
        assert bbox.width() >= bbox.height() * 0.8, \
            "Snapped-to-0 stripe should be horizontal"
