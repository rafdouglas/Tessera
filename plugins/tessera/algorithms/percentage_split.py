"""Percentage Split algorithm -- split polygons by attribute-driven area fraction."""
from qgis.core import (
    QgsProcessingParameterColor,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType, QVariant

from ..infrastructure.geometry_helpers import extract_polygons, split_polygon_by_fraction
from ..infrastructure.feature_builder import create_output_fields, build_feature, BATCH_SIZE
from ..infrastructure.percent_helpers import detect_divisor, value_to_fraction, VALUE_RANGE_OPTIONS
from .base_algorithm import TesseraAlgorithm
_ORIENTATION_OPTIONS = ['horizontal', 'vertical', 'diagonal_45', 'diagonal_135', 'radial']
_ORIENTATION_DISPLAY = ['Horizontal', 'Vertical', 'Diagonal 45\u00b0', 'Diagonal 135\u00b0', 'Radial']


class PercentageSplitAlgorithm(TesseraAlgorithm):
    """Split polygons into filled and remainder parts based on percentage values."""

    def name(self):
        return 'percentage_split'

    def displayName(self):
        return 'Percentage Split'

    def group(self):
        return 'Fill'

    def groupId(self):
        return 'fill'

    def shortHelpString(self):
        return (
            '<p><b>Percentage Split</b> divides each polygon into two parts\u2014filled and remainder\u2014based on '
            'a percentage value from a numeric attribute. The filled part represents the percentage, the '
            'remainder shows what\'s left. Ideal for visualizing proportions within geographic features.</p>'

            '<h3>Common Use Cases</h3>'
            '<ul>'
            '<li><b>Election results:</b> Show vote share vs. opposition within each district</li>'
            '<li><b>Budget allocation:</b> Visualize spent vs. remaining budget by department</li>'
            '<li><b>Completion rates:</b> Display project progress (complete vs. incomplete area)</li>'
            '<li><b>Market share:</b> Proportional representation of competing values within regions</li>'
            '<li><b>Demographic splits:</b> Urban vs. rural population, or other binary categories</li>'
            '</ul>'

            '<h3>Parameters</h3>'
            '<ul>'
            '<li><b>Value field:</b> Numeric field containing percentage values. Required. Each feature\'s value '
            'determines how much of the polygon becomes "filled". Example: a field with election percentages, '
            'where 65.3 means 65.3% of the polygon area will be filled.</li>'

            '<li><b>Value range:</b> Tells the algorithm how to interpret values. Choose "0 - 100" if your field contains '
            'percentages like 75 (meaning 75%), "0 - 1" if values are fractions like 0.75, or "Auto scale" to calculate '
            'each value as a ratio to the maximum value across all features.</li>'

            '<li><b>Orientation:</b> Direction of the split. Options:'
            '<ul>'
            '<li><i>Horizontal:</i> Split left-to-right (filled on left, remainder on right)</li>'
            '<li><i>Vertical:</i> Split bottom-to-top (filled on bottom, remainder on top)</li>'
            '<li><i>Diagonal 45\u00b0:</i> Split southwest-to-northeast at 45\u00b0</li>'
            '<li><i>Diagonal 135\u00b0:</i> Split southeast-to-northwest at 135\u00b0</li>'
            '<li><i>Radial:</i> Filled part grows from center outward (circular growth pattern)</li>'
            '</ul>'
            'Choose orientation based on visual flow: Horizontal for left-right reading, Vertical for growth metaphors, '
            'Radial for impact/influence visualizations.</li>'
            '</ul>'

            '<h3>Output Fields</h3>'
            '<ul>'
            '<li><b>part (<code>_tessera_part</code>):</b> Either "filled" or "remainder". Use this field with a categorized renderer to style '
            'the two parts differently (e.g., blue for filled, red for remainder).</li>'

            '<li><b>value (<code>_tessera_value</code>):</b> Original value from the Value field. Preserved for reference and labeling.</li>'

            '<li><b>fraction (<code>_tessera_fraction</code>):</b> Normalized fraction (0.0 to 1.0) after applying the Value range. Useful for data-driven '
            'styling or further calculations.</li>'
            '</ul>'

            '<h3>Special Cases</h3>'
            '<ul>'
            '<li>If value is 0%, only the remainder part is output (filled part is empty).</li>'
            '<li>If value is 100%, only the filled part is output (remainder is empty).</li>'
            '<li>For values between 0-100%, both filled and remainder parts are created.</li>'
            '</ul>'

            '<h3>Tips and Workflow</h3>'
            '<ul>'
            '<li>After running this algorithm, apply a <b>categorized renderer</b> on part (<code>_tessera_part</code>) to color filled and '
            'remainder parts distinctly.</li>'

            '<li>Chain with <b>Tile Fill</b> (using Percentage field) for waffle-chart-style proportional fills.</li>'

            '<li>Use <i>Horizontal</i> orientation for maps with left-to-right reading direction (Western cultures).</li>'

            '<li>Use <i>Radial</i> orientation for "heat" or "impact zone" visualizations where filled area represents '
            'influence spreading from the center.</li>'

            '<li>For NULL or non-numeric values, features are skipped and warnings are issued.</li>'
            '</ul>'
        )

    def output_layer_name(self):
        return 'Percentage split'

    def createInstance(self):
        return PercentageSplitAlgorithm()

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
                'VALUE_RANGE',
                'Value range',
                options=VALUE_RANGE_OPTIONS,
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                'ORIENTATION',
                'Split orientation',
                options=_ORIENTATION_DISPLAY,
                defaultValue=0,
            )
        )

        # Advanced color parameters
        filled_color_param = QgsProcessingParameterColor(
            'FILLED_COLOR',
            'Filled part color',
            defaultValue='#3b82f6',
            optional=True,
        )
        filled_color_param.setFlags(
            filled_color_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced
        )
        self.addParameter(filled_color_param)

        remainder_color_param = QgsProcessingParameterColor(
            'REMAINDER_COLOR',
            'Remainder part color',
            defaultValue='#ef4444',
            optional=True,
        )
        remainder_color_param.setFlags(
            remainder_color_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced
        )
        self.addParameter(remainder_color_param)

    def get_output_fields(self, source, parameters=None, context=None):
        """Return output fields: source fields + _tessera_algorithm, _tessera_parent_fid, _tessera_part, _tessera_value, _tessera_fraction."""
        return create_output_fields(source.fields(), [
            ('_tessera_algorithm', QMetaType.Type.QString),
            ('_tessera_parent_fid', QMetaType.Type.Int),
            ('_tessera_part', QMetaType.Type.QString),
            ('_tessera_value', QMetaType.Type.Double),
            ('_tessera_fraction', QMetaType.Type.Double),
        ])

    def run_algorithm(self, source, parameters, context, working_crs,
                      topology, sink, feedback):
        """Execute the percentage split algorithm."""
        # --- Read parameters ---
        value_field = self.parameterAsString(parameters, 'VALUE_FIELD', context)
        value_range = self.parameterAsEnum(parameters, 'VALUE_RANGE', context)
        orientation_idx = self.parameterAsEnum(parameters, 'ORIENTATION', context)
        orientation = _ORIENTATION_OPTIONS[orientation_idx]

        output_fields = self.get_output_fields(source)

        total_features = source.featureCount()
        feature_count = 0
        batch = []

        # For auto-detect, scan all values first to determine max
        divisor = None
        if value_range == 2:  # auto_detect
            divisor = detect_divisor(source, value_field, feedback)

        for feature in source.getFeatures():
            if feedback.isCanceled():
                break

            geom = feature.geometry()
            if geom.isEmpty() or geom.isNull():
                feature_count += 1
                continue

            # Read value
            raw_value = feature.attribute(value_field)
            if raw_value is None or raw_value == QVariant():
                feedback.pushWarning(
                    f'Feature {feature.id()}: NULL or missing value '
                    f'in field "{value_field}", skipping.'
                )
                feature_count += 1
                continue

            try:
                raw_value = float(raw_value)
            except (TypeError, ValueError):
                feedback.pushWarning(
                    f'Feature {feature.id()}: non-numeric value '
                    f'"{raw_value}" in field "{value_field}", skipping.'
                )
                feature_count += 1
                continue

            # Convert to fraction
            fraction = value_to_fraction(raw_value, value_range, divisor)

            # Transform to working CRS
            work_geom = working_crs.forward(geom)
            if work_geom.isEmpty():
                feature_count += 1
                continue

            # Split
            if fraction <= 0.0:
                # Only remainder
                out_geom = working_crs.inverse(work_geom)
                out_feat = build_feature(
                    out_geom, feature, 'percentage_split',
                    {'_tessera_part': 'remainder', '_tessera_value': raw_value,
                     '_tessera_fraction': fraction},
                    output_fields,
                )
                batch.append(out_feat)
            elif fraction >= 1.0:
                # Only filled
                out_geom = working_crs.inverse(work_geom)
                out_feat = build_feature(
                    out_geom, feature, 'percentage_split',
                    {'_tessera_part': 'filled', '_tessera_value': raw_value,
                     '_tessera_fraction': fraction},
                    output_fields,
                )
                batch.append(out_feat)
            else:
                # Split into filled and remainder
                filled_geom, remainder_geom = split_polygon_by_fraction(
                    work_geom, fraction, orientation
                )

                # Emit filled part
                if not filled_geom.isEmpty():
                    out_filled = working_crs.inverse(filled_geom)
                    out_feat = build_feature(
                        out_filled, feature, 'percentage_split',
                        {'_tessera_part': 'filled', '_tessera_value': raw_value,
                         '_tessera_fraction': fraction},
                        output_fields,
                    )
                    batch.append(out_feat)

                # Emit remainder part
                if not remainder_geom.isEmpty():
                    out_remainder = working_crs.inverse(remainder_geom)
                    out_feat = build_feature(
                        out_remainder, feature, 'percentage_split',
                        {'_tessera_part': 'remainder', '_tessera_value': raw_value,
                         '_tessera_fraction': fraction},
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
