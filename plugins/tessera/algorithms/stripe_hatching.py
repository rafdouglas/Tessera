"""Stripe Hatching algorithm -- fill polygons with parallel rectangular stripes."""
import math

from qgis.core import (
    QgsGeometry,
    QgsPointXY,
    QgsProcessingParameterNumber,
)
from PyQt5.QtCore import QMetaType

from ..infrastructure.geometry_helpers import extract_polygons
from ..infrastructure.feature_builder import create_output_fields, build_feature, BATCH_SIZE
from .base_algorithm import TesseraAlgorithm
_SNAP_TOLERANCE = 0.1  # degrees -- angles within this of 0/90/180 snap exactly


def _snap_angle(angle):
    """Snap angle to exact axis-aligned values if within tolerance.

    Returns the (possibly snapped) angle.
    """
    for target in (0.0, 90.0, 180.0):
        if abs(angle - target) < _SNAP_TOLERANCE:
            return target
    return angle


def _rotate_geometry(geom, angle_deg, center):
    """Rotate geometry by angle_deg around center.

    QgsGeometry.rotate() uses clockwise-positive convention.

    Args:
        geom: QgsGeometry to rotate.
        angle_deg: Rotation angle in degrees (positive = clockwise).
        center: QgsPointXY rotation center.

    Returns:
        New rotated QgsGeometry (original is not modified).
    """
    geom_copy = QgsGeometry(geom)
    geom_copy.rotate(angle_deg, center)
    return geom_copy


def _make_stripe_rect(x_min, y_bottom, x_max, y_top):
    """Create a rectangular polygon from axis-aligned bounds.

    Args:
        x_min, y_bottom: Lower-left corner.
        x_max, y_top: Upper-right corner.

    Returns:
        QgsGeometry polygon.
    """
    ring = [
        QgsPointXY(x_min, y_bottom),
        QgsPointXY(x_max, y_bottom),
        QgsPointXY(x_max, y_top),
        QgsPointXY(x_min, y_top),
        QgsPointXY(x_min, y_bottom),
    ]
    return QgsGeometry.fromPolygonXY([ring])


class StripeHatchingAlgorithm(TesseraAlgorithm):
    """Fill input polygons with parallel rectangular stripes at a given angle."""

    def name(self):
        return 'stripe_hatching'

    def displayName(self):
        return 'Stripe Hatching'

    def group(self):
        return 'Fill'

    def groupId(self):
        return 'fill'

    def shortHelpString(self):
        return (
            '<p><b>Stripe Hatching</b> fills polygons with parallel rectangular stripes at a specified angle. '
            'Classic hatching technique for differentiating land use, creating pattern fills, or adding visual '
            'texture to maps.</p>'

            '<h3>Common Use Cases</h3>'
            '<ul>'
            '<li><b>Land use differentiation:</b> Traditional hatching patterns for agriculture, forest, urban areas</li>'
            '<li><b>Overlapping regions:</b> Combine with transparency to show multiple overlapping datasets</li>'
            '<li><b>Prohibited/restricted zones:</b> Diagonal stripes for restricted airspace, exclusion zones</li>'
            '<li><b>Pattern fills:</b> Decorative hatching for illustration-style maps</li>'
            '<li><b>Texture layers:</b> Add visual interest to otherwise flat polygons</li>'
            '</ul>'

            '<h3>Parameters</h3>'
            '<ul>'
            '<li><b>Stripe angle:</b> Stripe angle in degrees, from 0 to 180. Key angles:'
            '<ul>'
            '<li><i>0\u00b0 or 180\u00b0:</i> Horizontal stripes (left-right)</li>'
            '<li><i>45\u00b0:</i> Classic diagonal hatching (bottom-left to top-right)</li>'
            '<li><i>90\u00b0:</i> Vertical stripes (top-bottom)</li>'
            '<li><i>135\u00b0:</i> Reverse diagonal (top-left to bottom-right)</li>'
            '</ul>'
            'Angles near 0, 90, or 180 are automatically snapped for precise axis alignment.</li>'

            '<li><b>Stripe width:</b> Width of each stripe in map units (e.g., meters for projected CRS). '
            'Set to 0 for automatic sizing based on Target stripes. Manual widths give precise control over density; '
            'auto-sizing adapts to feature dimensions.</li>'

            '<li><b>Gap width:</b> Space between adjacent stripes in map units. Set to 0 to make gaps equal to '
            'Stripe width (50% fill density). Set higher for sparse hatching, lower for dense patterns. '
            'Example: Stripe width=100, Gap width=200 creates widely-spaced stripes.</li>'

            '<li><b>Target stripes:</b> Used when Stripe width is 0. Algorithm computes stripe width to fit approximately '
            'this many stripes perpendicular to the stripe angle. Default 10. Higher values create denser hatching.</li>'
            '</ul>'

            '<h3>Output Fields</h3>'
            '<ul>'
            '<li><b>stripe index (<code>_tessera_stripe_index</code>):</b> Integer index starting at 0, assigned from "lowest" to "highest" '
            'perpendicular to the stripe angle (e.g., bottom-to-top for horizontal stripes, left-to-right for vertical).</li>'
            '</ul>'

            '<h3>Tips and Workflow</h3>'
            '<ul>'
            '<li>For classic hatching, use 45\u00b0 angle with equal stripe and gap widths.</li>'

            '<li>Combine with <b>50% transparency</b> for overlay effects (e.g., showing overlapping jurisdictions).</li>'

            '<li>Use <i>vertical</i> (90\u00b0) or <i>horizontal</i> (0\u00b0) stripes for technical drawings and engineering maps.</li>'

            '<li>Set Gap width larger than Stripe width for sparse patterns (better for complex backgrounds).</li>'

            '<li>Multiple hatching layers at different angles (e.g., 45\u00b0 and 135\u00b0) create crosshatch patterns.</li>'

            '<li>For performance, use Target stripes between 5-20. High stripe counts generate many features.</li>'

            '<li>Angles are snapped within 0.1\u00b0 of axis-aligned values (0, 90, 180) for cleaner output.</li>'
            '</ul>'
        )

    def output_layer_name(self):
        return 'Stripe hatched'

    def createInstance(self):
        return StripeHatchingAlgorithm()

    def initAlgorithm(self, config=None):
        super().initAlgorithm(config)
        self.addParameter(
            QgsProcessingParameterNumber(
                'ANGLE',
                'Stripe angle (degrees)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0,
                minValue=0,
                maxValue=180,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'STRIPE_WIDTH',
                'Stripe width (map units, 0 = auto)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0,
                minValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'GAP_WIDTH',
                'Gap width (map units, 0 = same as stripe width)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0,
                minValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'TARGET_STRIPES',
                'Target number of stripes (when stripe width is auto)',
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=10,
                minValue=2,
                maxValue=100,
            )
        )

    def get_output_fields(self, source, parameters=None, context=None):
        """Return output fields: source fields + _tessera_algorithm, _tessera_parent_fid, _tessera_stripe_index."""
        return create_output_fields(source.fields(), [
            ('_tessera_algorithm', QMetaType.Type.QString),
            ('_tessera_parent_fid', QMetaType.Type.Int),
            ('_tessera_stripe_index', QMetaType.Type.Int),
        ])

    def run_algorithm(self, source, parameters, context, working_crs,
                      topology, sink, feedback):
        """Execute the stripe hatching algorithm."""
        # --- Read parameters ---
        angle = self.parameterAsDouble(parameters, 'ANGLE', context)
        stripe_width = self.parameterAsDouble(parameters, 'STRIPE_WIDTH', context)
        gap_width = self.parameterAsDouble(parameters, 'GAP_WIDTH', context)
        target_stripes = self.parameterAsInt(parameters, 'TARGET_STRIPES', context)

        # Snap near-axis angles
        angle = _snap_angle(angle)

        output_fields = self.get_output_fields(source)
        total_features = source.featureCount()
        feature_count = 0
        batch = []

        for feature in source.getFeatures():
            if feedback.isCanceled():
                break

            geom = feature.geometry()
            if geom.isEmpty() or geom.isNull():
                feature_count += 1
                continue

            # Transform to working CRS
            work_geom = working_crs.forward(geom)
            if work_geom.isEmpty():
                feature_count += 1
                continue

            # Generate stripes for this feature
            stripes = self._generate_stripes(
                work_geom, angle, stripe_width, gap_width, target_stripes,
                feedback,
            )

            # Build output features
            for stripe_index, stripe_geom in enumerate(stripes):
                if feedback.isCanceled():
                    break

                # Transform back to source CRS
                out_geom = working_crs.inverse(stripe_geom)

                out_feat = build_feature(
                    out_geom,
                    feature,
                    'stripe_hatching',
                    {'_tessera_stripe_index': stripe_index},
                    output_fields,
                )
                batch.append(out_feat)

                if len(batch) >= BATCH_SIZE:
                    sink.addFeatures(batch)
                    batch = []

            feature_count += 1
            if total_features > 0:
                feedback.setProgress(int(feature_count / total_features * 100))

        # Flush remaining batch
        if batch:
            sink.addFeatures(batch)

    def _generate_stripes(self, work_geom, angle, stripe_width, gap_width,
                          target_stripes, feedback):
        """Generate stripe geometries for a single feature in working CRS.

        For axis-aligned angles (0, 90, 180), generates stripes directly.
        For other angles, rotates the polygon, generates horizontal stripes,
        then rotates each stripe back.

        Args:
            work_geom: QgsGeometry in working CRS.
            angle: Stripe angle in degrees (already snapped).
            stripe_width: Stripe width in working CRS units (0 = auto).
            gap_width: Gap width in working CRS units (0 = same as stripe_width).
            target_stripes: Target number of stripes when auto-sizing.
            feedback: QgsProcessingFeedback.

        Returns:
            List of QgsGeometry stripe polygons, ordered from "lowest" to
            "highest" perpendicular to the stripe angle.
        """
        is_axis_aligned = angle in (0.0, 180.0, 90.0)

        if is_axis_aligned:
            return self._generate_axis_aligned(
                work_geom, angle, stripe_width, gap_width, target_stripes,
                feedback,
            )
        else:
            return self._generate_rotated(
                work_geom, angle, stripe_width, gap_width, target_stripes,
                feedback,
            )

    def _compute_widths(self, extent_perpendicular, stripe_width, gap_width,
                        target_stripes):
        """Compute effective stripe and gap widths.

        Args:
            extent_perpendicular: Extent of the geometry perpendicular to
                the stripe direction (in working CRS units).
            stripe_width: User-specified stripe width (0 = auto).
            gap_width: User-specified gap width (0 = same as stripe_width).
            target_stripes: Target stripe count for auto mode.

        Returns:
            Tuple of (effective_stripe_width, effective_gap_width).
        """
        if stripe_width == 0:
            # Auto: divide extent by (2*n - 1) to get n stripes + (n-1) gaps
            sw = extent_perpendicular / (2 * target_stripes - 1)
        else:
            sw = stripe_width

        gw = sw if gap_width == 0 else gap_width
        return sw, gw

    def _generate_axis_aligned(self, work_geom, angle, stripe_width,
                               gap_width, target_stripes, feedback):
        """Generate stripes for axis-aligned angles (0, 90, 180).

        angle=0 or 180: horizontal stripes sweeping bottom-to-top.
        angle=90: vertical stripes sweeping left-to-right.

        Returns list of stripe geometries ordered by position.
        """
        bbox = work_geom.boundingBox()

        if angle == 90.0:
            # Vertical stripes: sweep left-to-right
            extent_perp = bbox.width()
            sw, gw = self._compute_widths(extent_perp, stripe_width,
                                          gap_width, target_stripes)
            if sw <= 0:
                return []

            stride = sw + gw
            x_start = bbox.xMinimum()
            y_min = bbox.yMinimum() - 1  # small padding
            y_max = bbox.yMaximum() + 1

            stripes = []
            x = x_start
            while x < bbox.xMaximum():
                if feedback.isCanceled():
                    break
                rect = _make_stripe_rect(x, y_min, x + sw, y_max)
                clipped = rect.intersection(work_geom)
                clipped = extract_polygons(clipped)
                if not clipped.isEmpty():
                    stripes.append(clipped)
                x += stride

        else:
            # angle == 0 or 180: horizontal stripes, bottom-to-top
            extent_perp = bbox.height()
            sw, gw = self._compute_widths(extent_perp, stripe_width,
                                          gap_width, target_stripes)
            if sw <= 0:
                return []

            stride = sw + gw
            y_start = bbox.yMinimum()
            x_min = bbox.xMinimum() - 1  # small padding
            x_max = bbox.xMaximum() + 1

            stripes = []
            y = y_start
            while y < bbox.yMaximum():
                if feedback.isCanceled():
                    break
                rect = _make_stripe_rect(x_min, y, x_max, y + sw)
                clipped = rect.intersection(work_geom)
                clipped = extract_polygons(clipped)
                if not clipped.isEmpty():
                    stripes.append(clipped)
                y += stride

        return stripes

    def _generate_rotated(self, work_geom, angle, stripe_width, gap_width,
                          target_stripes, feedback):
        """Generate stripes for non-axis-aligned angles via rotation.

        1. Compute centroid of the polygon as rotation center.
        2. Rotate polygon by -angle (so stripes become horizontal).
        3. Generate horizontal stripes on the rotated polygon.
        4. Rotate each stripe back by +angle.
        5. Intersect with the original polygon.

        Returns list of stripe geometries ordered bottom-to-top in the
        rotated frame (which corresponds to ordering perpendicular to the
        stripe angle).
        """
        # Centroid as rotation center
        centroid_pt = work_geom.centroid().asPoint()
        center = QgsPointXY(centroid_pt.x(), centroid_pt.y())

        # Rotate polygon by -angle so stripes become horizontal
        rotated_geom = _rotate_geometry(work_geom, -angle, center)
        bbox = rotated_geom.boundingBox()

        # Compute stripe/gap widths based on height of rotated bbox
        extent_perp = bbox.height()
        sw, gw = self._compute_widths(extent_perp, stripe_width,
                                      gap_width, target_stripes)
        if sw <= 0:
            return []

        stride = sw + gw

        # Pad horizontally by bbox diagonal to ensure full coverage
        diag = math.sqrt(bbox.width() ** 2 + bbox.height() ** 2)
        x_min = bbox.xMinimum() - diag
        x_max = bbox.xMaximum() + diag

        # Generate horizontal stripe rectangles in the rotated coordinate space
        y_start = bbox.yMinimum()
        rotated_stripes = []
        y = y_start
        while y < bbox.yMaximum():
            if feedback.isCanceled():
                break
            rect = _make_stripe_rect(x_min, y, x_max, y + sw)
            # Clip to rotated polygon first for efficiency
            clipped = rect.intersection(rotated_geom)
            clipped = extract_polygons(clipped)
            if not clipped.isEmpty():
                rotated_stripes.append(clipped)
            y += stride

        # Rotate each stripe back and intersect with original geometry
        result = []
        for stripe in rotated_stripes:
            if feedback.isCanceled():
                break
            # Rotate back by +angle
            back_rotated = _rotate_geometry(stripe, angle, center)
            # Intersect with original to clean up any rounding artifacts
            final = back_rotated.intersection(work_geom)
            final = extract_polygons(final)
            if not final.isEmpty():
                result.append(final)

        return result
