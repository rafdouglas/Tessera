"""Percentage Split algorithm implementation."""
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterColor,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType
from PyQt5.QtGui import QColor

from .infrastructure.geometry_helpers import split_polygon_by_fraction
from .infrastructure.feature_builder import create_output_fields, build_feature
from .infrastructure.crs_manager import WorkingCRS

_BATCH_SIZE = 1000


class PercentageSplitAlgorithm(QgsProcessingAlgorithm):
    """Split polygons into filled and remainder parts based on percentage values."""

    def name(self):
        return 'percentage_split'

    def displayName(self):
        return 'Percentage Split'

    def group(self):
        return 'Fill'

    def groupId(self):
        return 'fill'

    def createInstance(self):
        return PercentageSplitAlgorithm()

    def initAlgorithm(self, config=None):
        """Define INPUT (polygon source) and OUTPUT (feature sink) parameters."""
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                'INPUT',
                'Input layer',
                [QgsProcessing.TypeVectorPolygon],
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                'OUTPUT',
                'Output layer',
            )
        )
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
                'How to interpret field values',
                options=['0 - 100', '0 - 1', 'Auto scale'],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                'ORIENTATION',
                'Direction of the split line',
                options=['Horizontal', 'Vertical', 'Diagonal 45°', 'Diagonal 135°', 'Radial'],
                defaultValue=0,
            )
        )

        # Advanced parameters
        filled_color = QgsProcessingParameterColor(
            'FILLED_COLOR',
            'Hint for default styling (filled part)',
            defaultValue=QColor('#3b82f6'),
            optional=True,
        )
        filled_color.setFlags(filled_color.flags() | QgsProcessingParameterColor.FlagAdvanced)
        self.addParameter(filled_color)

        remainder_color = QgsProcessingParameterColor(
            'REMAINDER_COLOR',
            'Hint for default styling (remainder part)',
            defaultValue=QColor('#ef4444'),
            optional=True,
        )
        remainder_color.setFlags(remainder_color.flags() | QgsProcessingParameterColor.FlagAdvanced)
        self.addParameter(remainder_color)

    def get_output_fields(self, source):
        """Return output fields: source fields + _tessera_algorithm, _tessera_parent_fid, _tessera_part, _tessera_value, _tessera_fraction."""
        return create_output_fields(source.fields(), [
            ('_tessera_algorithm', QMetaType.Type.QString),
            ('_tessera_parent_fid', QMetaType.Type.Int),
            ('_tessera_part', QMetaType.Type.QString),
            ('_tessera_value', QMetaType.Type.Double),
            ('_tessera_fraction', QMetaType.Type.Double),
        ])

    def processAlgorithm(self, parameters, context, feedback):
        """Orchestrate the algorithm: resolve input, create CRS, sink, delegate."""
        # 1. Resolve INPUT source
        source = self.parameterAsSource(parameters, 'INPUT', context)

        # 2. Get output field schema
        output_fields = self.get_output_fields(source)

        # 3. Create WorkingCRS (thread-safe, created per invocation)
        working_crs = WorkingCRS(
            source.sourceCrs(), source.sourceExtent(), 'equal_area'
        )

        # 4. Create output sink
        (sink, dest_id) = self.parameterAsSink(
            parameters, 'OUTPUT', context,
            output_fields, QgsWkbTypes.MultiPolygon, source.sourceCrs(),
        )

        # 5. Execute the algorithm logic
        self.run_algorithm(
            source, parameters, context, working_crs, None, sink, feedback
        )

        # 6. Return output reference
        return {'OUTPUT': dest_id}

    def run_algorithm(self, source, parameters, context, working_crs,
                      topology, sink, feedback):
        """Execute the percentage split algorithm."""
        # --- Read parameters ---
        value_field = self.parameterAsString(parameters, 'VALUE_FIELD', context)
        value_range = self.parameterAsEnum(parameters, 'VALUE_RANGE', context)
        orientation_idx = self.parameterAsEnum(parameters, 'ORIENTATION', context)

        orientation_map = ['horizontal', 'vertical', 'diagonal_45', 'diagonal_135', 'radial']
        orientation = orientation_map[orientation_idx]

        output_fields = self.get_output_fields(source)
        total_features = source.featureCount()
        feature_count = 0
        batch = []

        # For auto scale, find the maximum value across all features
        max_value = None
        if value_range == 2:  # auto scale
            for f in source.getFeatures():
                v = f[value_field]
                if v is not None and not isinstance(v, type(None)):
                    try:
                        v = float(v)
                        if max_value is None or v > max_value:
                            max_value = v
                    except (TypeError, ValueError):
                        pass
            if max_value is None or max_value <= 0:
                max_value = 1.0

        for feature in source.getFeatures():
            if feedback.isCanceled():
                break

            geom = feature.geometry()
            if geom.isEmpty() or geom.isNull():
                feature_count += 1
                continue

            # Read and convert value to fraction
            raw_value = feature[value_field]
            if raw_value is None or isinstance(raw_value, type(None)):
                feedback.reportError(f'Feature {feature.id()} has null value in field {value_field}, skipping')
                feature_count += 1
                continue

            try:
                value = float(raw_value)
            except (ValueError, TypeError):
                feedback.reportError(f'Feature {feature.id()} has non-numeric value in field {value_field}, skipping')
                feature_count += 1
                continue

            # Convert to fraction based on value_range
            if value_range == 0:  # 0-100
                fraction = value / 100.0
            elif value_range == 1:  # 0-1
                fraction = value
            else:  # auto scale
                fraction = value / max_value

            # Clamp fraction to [0, 1]
            fraction = max(0.0, min(1.0, fraction))

            # Transform to working CRS
            work_geom = working_crs.forward(geom)
            if work_geom.isEmpty():
                feature_count += 1
                continue

            # Split the polygon
            filled_geom, remainder_geom = split_polygon_by_fraction(
                work_geom, fraction, orientation
            )

            # Emit filled part if not empty
            if not filled_geom.isEmpty():
                out_geom = working_crs.inverse(filled_geom)
                out_feat = build_feature(
                    out_geom,
                    feature,
                    'percentage_split',
                    {
                        '_tessera_part': 'filled',
                        '_tessera_value': value,
                        '_tessera_fraction': fraction,
                    },
                    output_fields,
                )
                batch.append(out_feat)

            # Emit remainder part if not empty
            if not remainder_geom.isEmpty():
                out_geom = working_crs.inverse(remainder_geom)
                out_feat = build_feature(
                    out_geom,
                    feature,
                    'percentage_split',
                    {
                        '_tessera_part': 'remainder',
                        '_tessera_value': value,
                        '_tessera_fraction': fraction,
                    },
                    output_fields,
                )
                batch.append(out_feat)

            # Flush batch if needed
            if len(batch) >= _BATCH_SIZE:
                sink.addFeatures(batch)
                batch = []

            feature_count += 1
            if total_features > 0:
                feedback.setProgress(int(feature_count / total_features * 100))

        # Flush remaining batch
        if batch:
            sink.addFeatures(batch)
