"""Replace with Shape algorithm -- replace polygons with proportional shapes."""
import math
import statistics

from qgis.core import (
    QgsPointXY,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
)
from PyQt5.QtCore import QMetaType, QVariant

from ..infrastructure.geometry_helpers import (
    regular_polygon,
    safe_pole_of_inaccessibility,
)
from ..infrastructure.feature_builder import create_output_fields, build_feature, BATCH_SIZE
from ..infrastructure.scale_helpers import compute_scale_factor, validate_scale_value
from .base_algorithm import TesseraAlgorithm

_SHAPE_OPTIONS = ['Circle', 'Square', 'Hexagon']
_SCALE_METHOD_OPTIONS = ['Proportional area', 'Square root', 'Logarithmic']
_REFERENCE_OPTIONS = ['Maximum value', 'Mean value', 'Fixed']
_SIZE_REFERENCE_OPTIONS = ['Auto', 'Fixed radius']
_CENTER_METHOD_OPTIONS = ['Centroid', 'Pole of inaccessibility']


class ReplaceWithShapeAlgorithm(TesseraAlgorithm):
    """Replace each polygon with a circle/square/hexagon of proportional area."""

    def name(self):
        return 'replace_with_shape'

    def displayName(self):
        return 'Replace with Shape'

    def group(self):
        return 'Shape'

    def groupId(self):
        return 'shape'

    def shortHelpString(self):
        return (
            '<p><b>Replace with Shape</b> replaces each polygon with a proportionally-sized geometric shape '
            '(circle, square, or hexagon) centered on the original location. Ideal for Dorling cartograms, proportional '
            'symbol maps, bubble maps, and abstract spatial visualizations where shape uniformity clarifies data comparisons.</p>'

            '<h3>Common Use Cases</h3>'
            '<ul>'
            '<li><b>Dorling cartograms:</b> Replace countries/states with proportional circles for clear size comparison</li>'
            '<li><b>Proportional symbol maps:</b> Uniform shapes make magnitude comparisons easier than irregular polygons</li>'
            '<li><b>Bubble maps:</b> Classic bubble chart over geographic space</li>'
            '<li><b>Abstract representations:</b> Remove geographic detail to focus purely on data relationships</li>'
            '<li><b>Small multiples preparation:</b> Regular shapes work better in grid layouts (use with Arrange Features)</li>'
            '</ul>'

            '<h3>Parameters</h3>'
            '<ul>'
            '<li><b>Value field:</b> Numeric field determining shape size. Required. Each feature\'s value controls the '
            'area (or radius, depending on scale method) of the replacement shape. Example: GDP field where larger values '
            'produce larger circles.</li>'

            '<li><b>Shape:</b> Replacement geometry:'
            '<ul>'
            '<li><i>Circle (default):</i> Best for Dorling cartograms and bubble maps. Visually clean, easy to compare sizes.</li>'
            '<li><i>Square:</i> Good for grid-like layouts, architectural aesthetics, or when you need clear boundaries.</li>'
            '<li><i>Hexagon:</i> Compromise between circles and squares. Packs efficiently, distinctive look.</li>'
            '</ul>'
            'Circles are most common; hexagons offer a stylistic alternative with better space efficiency.</li>'

            '<li><b>Scale method:</b> How values map to shape sizes:'
            '<ul>'
            '<li><i>Proportional area (default):</i> Area scales linearly with value. Doubling value doubles area. '
            'Natural for counts (population, votes, production).</li>'
            '<li><i>Square root:</i> Radius scales linearly with value. More moderate scaling for wide ranges.</li>'
            '<li><i>Logarithmic:</i> Logarithmic scaling. Compresses extreme outliers, useful for highly skewed data '
            '(wealth, city sizes).</li>'
            '</ul></li>'

            '<li><b>Reference value:</b> Which value gets "base size". Options:'
            '<ul>'
            '<li><i>Maximum value (default):</i> Highest-valued feature uses reference radius, others scale proportionally down.</li>'
            '<li><i>Mean value:</i> Average-valued feature uses reference radius.</li>'
            '<li><i>Fixed:</i> Use Fixed reference value parameter (advanced) for manual reference value.</li>'
            '</ul></li>'

            '<li><b>Size reference:</b> Determines base shape size:'
            '<ul>'
            '<li><i>Auto (default):</i> Reference radius computed from median polygon area. '
            'Shapes roughly match original feature sizes.</li>'
            '<li><i>Fixed radius:</i> Use Fixed radius (map units) parameter (advanced) for manual control. Useful for multi-map consistency.</li>'
            '</ul></li>'

            '<li><b>Center method:</b> Where to place replacement shapes:'
            '<ul>'
            '<li><i>Centroid:</i> Geometric center (fast, but may fall outside concave polygons)</li>'
            '<li><i>Pole of inaccessibility (default):</i> Most interior point. Better for irregular shapes, ensures '
            'shape stays within original polygon bounds.</li>'
            '</ul>'
            'Pole of inaccessibility is recommended for coastlines, islands, or complex administrative boundaries.</li>'

            '<li><b>Circle segments:</b> Vertex count for circles (16-256). Default 64. Higher values create smoother circles '
            'but more vertices. 32-64 is usually sufficient; use 128+ for large-scale print maps.</li>'
            '</ul>'

            '<h3>Output Fields</h3>'
            '<ul>'
            '<li><b>value (_tessera_value):</b> Original value from the value field.</li>'
            '<li><b>scale factor (_tessera_scale_factor):</b> Computed area scale factor (before radius conversion). For reference and debugging.</li>'
            '</ul>'

            '<h3>Tips and Workflow</h3>'
            '<ul>'
            '<li>For <b>Dorling cartograms</b>, use circles with Proportional area, then chain with <b>Arrange Features</b> '
            '(Separate mode) to resolve overlaps and create a non-overlapping layout.</li>'

            '<li>For <b>static bubble maps</b> where overlap is acceptable, use circles without further arrangement.</li>'

            '<li>Use <b>hexagons</b> for a distinctive, modern look (hexagons pack more efficiently than squares).</li>'

            '<li>Chain with <b>Arrange Features</b> in Grid arrangement mode to create small-multiples poster layouts.</li>'

            '<li>Use <i>Proportional area</i> for intuitive size comparisons (area directly represents magnitude).</li>'

            '<li>Use <i>Logarithmic</i> when value range spans orders of magnitude (prevents tiny shapes from disappearing).</li>'

            '<li>For NULL, zero, or negative values, features are skipped with warnings/errors.</li>'

            '<li>Set Circle segments = 32 for draft work, 64 for final maps, 128+ for high-resolution printing.</li>'

            '<li>For multi-map consistency, use Size reference = Fixed radius with the same Fixed radius (map units) across datasets.</li>'
            '</ul>'
        )

    def output_layer_name(self):
        return 'Replaced with shape'

    def createInstance(self):
        return ReplaceWithShapeAlgorithm()

    def initAlgorithm(self, config=None):
        super().initAlgorithm(config)

        self.addParameter(
            QgsProcessingParameterField(
                'VALUE_FIELD',
                'Value field (numeric)',
                parentLayerParameterName='INPUT',
                type=QgsProcessingParameterField.Numeric,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                'SHAPE',
                'Shape',
                options=_SHAPE_OPTIONS,
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                'SCALE_METHOD',
                'Scale method',
                options=_SCALE_METHOD_OPTIONS,
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                'REFERENCE',
                'Reference value',
                options=_REFERENCE_OPTIONS,
                defaultValue=0,
            )
        )

        # Advanced: FIXED_REFERENCE
        fixed_ref_param = QgsProcessingParameterNumber(
            'FIXED_REFERENCE',
            'Fixed reference value',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=100.0,
            minValue=0.001,
        )
        fixed_ref_param.setFlags(
            fixed_ref_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced
        )
        self.addParameter(fixed_ref_param)

        self.addParameter(
            QgsProcessingParameterEnum(
                'SIZE_REFERENCE',
                'Size reference',
                options=_SIZE_REFERENCE_OPTIONS,
                defaultValue=0,
            )
        )

        # Advanced: FIXED_RADIUS
        fixed_radius_param = QgsProcessingParameterNumber(
            'FIXED_RADIUS',
            'Fixed radius (map units)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=100000.0,
            minValue=0.0,
        )
        fixed_radius_param.setFlags(
            fixed_radius_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced
        )
        self.addParameter(fixed_radius_param)

        self.addParameter(
            QgsProcessingParameterEnum(
                'CENTER_METHOD',
                'Center method',
                options=_CENTER_METHOD_OPTIONS,
                defaultValue=1,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'CIRCLE_SEGMENTS',
                'Circle segments',
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=64,
                minValue=16,
                maxValue=256,
            )
        )

    def get_output_fields(self, source, parameters=None, context=None):
        """Return output fields: source + _tessera_algorithm, _tessera_parent_fid, _tessera_value, _tessera_scale_factor."""
        return create_output_fields(source.fields(), [
            ('_tessera_algorithm', QMetaType.Type.QString),
            ('_tessera_parent_fid', QMetaType.Type.Int),
            ('_tessera_value', QMetaType.Type.Double),
            ('_tessera_scale_factor', QMetaType.Type.Double),
        ])

    def run_algorithm(self, source, parameters, context, working_crs,
                      topology, sink, feedback):
        """Execute the replace with shape algorithm."""
        # --- Read parameters ---
        value_field = self.parameterAsString(parameters, 'VALUE_FIELD', context)
        shape_idx = self.parameterAsEnum(parameters, 'SHAPE', context)
        scale_method = self.parameterAsEnum(parameters, 'SCALE_METHOD', context)
        reference_type = self.parameterAsEnum(parameters, 'REFERENCE', context)
        fixed_reference = self.parameterAsDouble(parameters, 'FIXED_REFERENCE', context)
        size_reference = self.parameterAsEnum(parameters, 'SIZE_REFERENCE', context)
        fixed_radius = self.parameterAsDouble(parameters, 'FIXED_RADIUS', context)
        center_method = self.parameterAsEnum(parameters, 'CENTER_METHOD', context)
        circle_segments = self.parameterAsInt(parameters, 'CIRCLE_SEGMENTS', context)

        output_fields = self.get_output_fields(source)

        # --- Pass 1: Collect all values and polygon areas ---
        features_data = []  # list of (feature, value)
        all_values = []
        all_areas = []

        for feature in source.getFeatures():
            if feedback.isCanceled():
                return

            geom = feature.geometry()
            if geom.isEmpty() or geom.isNull():
                continue

            value = validate_scale_value(feature, value_field, feedback)
            if value is None:
                continue

            # Transform to working CRS and get area
            work_geom = working_crs.forward(geom)
            if work_geom.isEmpty():
                continue

            area = work_geom.area()
            if area <= 0:
                continue

            all_values.append(value)
            all_areas.append(area)
            features_data.append((feature, value))

        if not features_data:
            return

        # --- Compute reference value R ---
        if reference_type == 0:  # max_value
            reference_value = max(all_values)
        elif reference_type == 1:  # mean_value
            reference_value = sum(all_values) / len(all_values)
        else:  # fixed
            reference_value = fixed_reference

        if reference_value <= 0:
            feedback.reportError('Reference value is zero or negative, cannot proceed.')
            return

        # --- Compute reference radius ---
        if size_reference == 0:  # auto
            median_area = statistics.median(all_areas)
            reference_radius = math.sqrt(median_area / math.pi)
        else:  # fixed_radius
            reference_radius = fixed_radius

        if reference_radius <= 0:
            feedback.reportError('Reference radius is zero or negative, cannot proceed.')
            return

        # --- Shape parameters ---
        if shape_idx == 0:  # circle
            n_sides = circle_segments
            rotation = 0.0
        elif shape_idx == 1:  # square
            n_sides = 4
            rotation = 45.0
        else:  # hexagon
            n_sides = 6
            rotation = 0.0

        # --- Pass 2: Generate shapes ---
        total_features = len(features_data)
        batch = []

        for i, (feature, value) in enumerate(features_data):
            if feedback.isCanceled():
                break

            # Compute scale factor
            scale = compute_scale_factor(value, reference_value, scale_method)

            # Compute radius from scale
            radius = reference_radius * math.sqrt(scale)

            # Transform geometry to working CRS for center computation
            geom = feature.geometry()
            work_geom = working_crs.forward(geom)

            # Compute center
            if center_method == 0:  # centroid
                center_geom = work_geom.centroid()
                center_pt = center_geom.asPoint()
                center = QgsPointXY(center_pt.x(), center_pt.y())
            else:  # pole_of_inaccessibility
                center, _ = safe_pole_of_inaccessibility(work_geom)

            if center is None:
                feedback.pushWarning(
                    f'Feature {feature.id()}: could not compute center, skipping.'
                )
                continue

            # Generate shape in working CRS
            shape_geom = regular_polygon(center, radius, n_sides, rotation)

            # Transform back to source CRS
            out_geom = working_crs.inverse(shape_geom)

            # Build output feature
            out_feat = build_feature(
                out_geom, feature, 'replace_with_shape',
                {'_tessera_value': value, '_tessera_scale_factor': scale},
                output_fields,
            )
            batch.append(out_feat)

            # Batch write
            if len(batch) >= BATCH_SIZE:
                sink.addFeatures(batch)
                batch = []

            if total_features > 0:
                feedback.setProgress(int((i + 1) / total_features * 100))

        # Flush remaining batch
        if batch:
            sink.addFeatures(batch)
