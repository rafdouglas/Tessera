"""Scale by Value algorithm -- resize polygons proportionally to an attribute value."""
import math

from qgis.core import (
    QgsPointXY,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
)
from PyQt5.QtCore import QMetaType, QVariant

from ..infrastructure.geometry_helpers import (
    clamp,
    safe_pole_of_inaccessibility,
    scale_geometry,
)
from ..infrastructure.feature_builder import create_output_fields, build_feature, BATCH_SIZE
from ..infrastructure.scale_helpers import (
    METHOD_PROPORTIONAL_AREA as _METHOD_PROPORTIONAL_AREA,
    METHOD_PROPORTIONAL_SQRT as _METHOD_PROPORTIONAL_SQRT,
    METHOD_PROPORTIONAL_LOG as _METHOD_PROPORTIONAL_LOG,
    REF_MAX_VALUE as _REF_MAX_VALUE,
    REF_MEAN_VALUE as _REF_MEAN_VALUE,
    REF_FIXED as _REF_FIXED,
    compute_reference,
    compute_scale_factor,
    validate_scale_value,
)
from .base_algorithm import TesseraAlgorithm

_SCALE_METHOD_OPTIONS = ['Proportional area', 'Square root', 'Logarithmic']
_REFERENCE_OPTIONS = ['Maximum value', 'Mean value', 'Fixed']

# Center method enum indices
_CENTER_CENTROID = 0
_CENTER_POLE = 1

_CENTER_METHOD_OPTIONS = ['Centroid', 'Pole of inaccessibility']



class ScaleByValueAlgorithm(TesseraAlgorithm):
    """Resize each polygon proportionally to an attribute value.

    Shape is preserved; only the scale changes.  The scale factor is derived
    from the ratio of each feature's value to a reference value, using one of
    three methods (proportional area, proportional sqrt, proportional log).
    """

    def name(self):
        return 'scale_by_value'

    def displayName(self):
        return 'Scale by Value'

    def group(self):
        return 'Shape'

    def groupId(self):
        return 'shape'

    def shortHelpString(self):
        return (
            '<p><b>Scale by Value</b> resizes each polygon proportionally to a numeric attribute value while preserving '
            'its original shape. Use this for cartograms, proportional symbol maps where shape recognition matters, '
            'or any visualization where area should represent data magnitude.</p>'

            '<h3>Common Use Cases</h3>'
            '<ul>'
            '<li><b>Cartograms:</b> Size countries/states by population, GDP, or other values while keeping shapes recognizable</li>'
            '<li><b>Proportional symbol maps:</b> Scale administrative regions by data (alternative to simple circles)</li>'
            '<li><b>Economic visualization:</b> Show market size, production volume, or trade value through polygon area</li>'
            '<li><b>Demographic mapping:</b> Represent population density or demographic variables spatially</li>'
            '<li><b>Pre-processing for layouts:</b> Scale features before using Arrange Features to create non-overlapping visualizations</li>'
            '</ul>'

            '<h3>Parameters</h3>'
            '<ul>'
            '<li><b>Value field:</b> Numeric field driving the scaling. Required. Each feature is scaled based on its value '
            'relative to a reference value. Example: population field where larger values produce larger polygons.</li>'

            '<li><b>Scale method:</b> How values map to scale factors:'
            '<ul>'
            '<li><i>Proportional area (default):</i> Area scales linearly with value. If value doubles, area doubles. '
            'Natural for counts and totals (population, production).</li>'
            '<li><i>Square root:</i> Linear dimension scales with value, area scales with square of value. '
            'More moderate scaling, better visual balance for wide value ranges.</li>'
            '<li><i>Logarithmic:</i> Logarithmic scaling. Compresses extreme values, good for highly skewed distributions '
            '(wealth, city sizes with few megacities).</li>'
            '</ul>'
            'Start with Proportional area; switch to Square root or Logarithmic if small features become invisible.</li>'

            '<li><b>Reference value:</b> Determines which feature gets scale factor 1.0 (unchanged size):'
            '<ul>'
            '<li><i>Maximum value (default):</i> Feature with highest value keeps original size, others scale down. '
            'Best for seeing relative sizes when you want the largest feature at full size.</li>'
            '<li><i>Mean value:</i> Average-valued feature keeps original size. Balanced approach, some features grow, others shrink.</li>'
            '<li><i>Fixed:</i> Specify a reference value manually (advanced parameter Fixed reference value). '
            'Useful for comparing multiple maps with consistent reference.</li>'
            '</ul></li>'

            '<li><b>Maximum scale / Minimum scale:</b> Clamp scale factors to prevent extreme sizes. Default: 0.1 to 3.0. '
            'Maximum scale = 3.0 means largest features can grow to 3x original area. '
            'Minimum scale = 0.1 means smallest features shrink to 10% of original area. Adjust if features become too large/small.</li>'

            '<li><b>Center method:</b> Point around which scaling occurs:'
            '<ul>'
            '<li><i>Centroid:</i> Geometric center (fast, but may be outside concave polygons)</li>'
            '<li><i>Pole of inaccessibility (default):</i> Most interior point (better for concave/irregular shapes, '
            'ensures center stays inside polygon)</li>'
            '</ul>'
            'Pole of inaccessibility produces better results for complex shapes but is slightly slower.</li>'
            '</ul>'

            '<h3>Output Fields</h3>'
            '<ul>'
            '<li><b>value (_tessera_value):</b> Original value from the value field. Preserved for labeling and reference.</li>'
            '<li><b>scale factor (_tessera_scale_factor):</b> Computed area scale factor (after applying method and clamping). '
            'For example, 0.5 means polygon was scaled to 50% of original area.</li>'
            '</ul>'

            '<h3>Tips and Workflow</h3>'
            '<ul>'
            '<li>After scaling, features often overlap. Chain with <b>Arrange Features</b> (Separate mode) to create '
            'a non-overlapping Dorling-style cartogram.</li>'

            '<li>Use <b>Proportional area</b> for intuitive area-value relationships (good for counts).</li>'

            '<li>Use <b>Logarithmic</b> when value range spans several orders of magnitude (e.g., city populations from '
            '10,000 to 10,000,000).</li>'

            '<li>Adjust Maximum scale and Minimum scale if small features disappear or large features dominate the view.</li>'

            '<li>For NULL or zero values, features are skipped with warnings. Negative values trigger errors.</li>'

            '<li>Use <i>Pole of inaccessibility</i> for irregular coastlines, islands, or concave administrative regions.</li>'

            '<li>Compare multiple datasets consistently by using Reference = Fixed with the same Fixed reference value.</li>'
            '</ul>'
        )

    def output_layer_name(self):
        return 'Scaled by value'

    def createInstance(self):
        return ScaleByValueAlgorithm()

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
                'SCALE_METHOD',
                'Scale method',
                options=_SCALE_METHOD_OPTIONS,
                defaultValue=_METHOD_PROPORTIONAL_AREA,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                'REFERENCE',
                'Reference value',
                options=_REFERENCE_OPTIONS,
                defaultValue=_REF_MAX_VALUE,
            )
        )

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
            QgsProcessingParameterNumber(
                'MAX_SCALE',
                'Maximum scale factor',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=3.0,
                minValue=0.1,
                maxValue=10.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'MIN_SCALE',
                'Minimum scale factor',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.1,
                minValue=0.01,
                maxValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                'CENTER_METHOD',
                'Center method',
                options=_CENTER_METHOD_OPTIONS,
                defaultValue=_CENTER_POLE,
            )
        )

    def get_output_fields(self, source, parameters=None, context=None):
        """Return output fields: source fields + _tessera_algorithm, _tessera_parent_fid, _tessera_value, _tessera_scale_factor."""
        return create_output_fields(source.fields(), [
            ('_tessera_algorithm', QMetaType.Type.QString),
            ('_tessera_parent_fid', QMetaType.Type.Int),
            ('_tessera_value', QMetaType.Type.Double),
            ('_tessera_scale_factor', QMetaType.Type.Double),
        ])

    def run_algorithm(self, source, parameters, context, working_crs,
                      topology, sink, feedback):
        """Execute the scale by value algorithm."""
        # --- Read parameters ---
        value_field = self.parameterAsString(parameters, 'VALUE_FIELD', context)
        scale_method = self.parameterAsEnum(parameters, 'SCALE_METHOD', context)
        reference_type = self.parameterAsEnum(parameters, 'REFERENCE', context)
        fixed_reference = self.parameterAsDouble(parameters, 'FIXED_REFERENCE', context)
        max_scale = self.parameterAsDouble(parameters, 'MAX_SCALE', context)
        min_scale = self.parameterAsDouble(parameters, 'MIN_SCALE', context)
        center_method = self.parameterAsEnum(parameters, 'CENTER_METHOD', context)

        output_fields = self.get_output_fields(source)

        # --- First pass: compute reference value R ---
        ref_value = compute_reference(
            source, value_field, reference_type, fixed_reference, feedback
        )
        if ref_value is None or ref_value == 0:
            feedback.pushWarning(
                'Reference value is zero or could not be computed. '
                'No features will be scaled.'
            )
            return

        # --- Second pass: scale each feature ---
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

            # Read and validate value
            value = validate_scale_value(feature, value_field, feedback)
            if value is None:
                feature_count += 1
                continue

            # Compute scale factor
            scale_factor = compute_scale_factor(
                value, ref_value, scale_method, min_scale, max_scale
            )

            # Transform to working CRS
            work_geom = working_crs.forward(geom)
            if work_geom.isEmpty():
                feature_count += 1
                continue

            # Compute center
            if center_method == _CENTER_POLE:
                center, _ = safe_pole_of_inaccessibility(work_geom, tolerance=1.0)
            else:
                centroid_geom = work_geom.centroid()
                center_pt = centroid_geom.asPoint()
                center = QgsPointXY(center_pt.x(), center_pt.y())

            # Scale geometry: pass sqrt(scale_factor) as linear factor
            # because area scales as square of linear dimensions
            linear_factor = math.sqrt(scale_factor)
            scaled_geom = scale_geometry(work_geom, center, linear_factor)

            # Transform back to source CRS
            out_geom = working_crs.inverse(scaled_geom)

            # Build output feature
            out_feat = build_feature(
                out_geom,
                feature,
                'scale_by_value',
                {'_tessera_value': value, '_tessera_scale_factor': scale_factor},
                output_fields,
            )
            batch.append(out_feat)

            # Batch write
            if len(batch) >= BATCH_SIZE:
                sink.addFeatures(batch)
                batch = []

            feature_count += 1
            if total_features > 0:
                feedback.setProgress(int(feature_count / total_features * 100))

        # Flush remaining batch
        if batch:
            sink.addFeatures(batch)

