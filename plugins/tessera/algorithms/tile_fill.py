"""Tile Fill algorithm — fill polygons with regular tile grids."""
import math

from qgis.core import (
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsRectangle,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType

from ..infrastructure.grid_generators import (
    auto_cell_size,
    generate_cell_polygons,
    generate_point_grid,
)
from ..infrastructure.geometry_helpers import (
    extract_polygons,
    regular_polygon,
    split_polygon_by_fraction,
)
from ..infrastructure.feature_builder import create_output_fields, build_feature, BATCH_SIZE
from ..infrastructure.percent_helpers import (
    detect_divisor,
    read_fraction,
    value_to_fraction,
    VALUE_RANGE_OPTIONS,
)
from .base_algorithm import TesseraAlgorithm

# Tile shape enum indices
_SHAPE_HEXAGON = 0
_SHAPE_SQUARE = 1
_SHAPE_CIRCLE = 2
_SHAPE_TRIANGLE = 3
_SHAPE_DIAMOND = 4

_SHAPE_OPTIONS = ['Hexagon', 'Square', 'Circle', 'Triangle', 'Diamond']

# Circle CRS enum indices
_CIRCLE_CRS_PROJECT = 0
_CIRCLE_CRS_SOURCE = 1
_CIRCLE_CRS_EQUAL_AREA = 2

_CIRCLE_CRS_OPTIONS = ['Project CRS', 'Source CRS', 'Equal area']

# Grid type names for generate_cell_polygons / auto_cell_size
_GRID_TYPE_MAP = {
    _SHAPE_HEXAGON: 'hexagonal',
    _SHAPE_SQUARE: 'square',
    _SHAPE_CIRCLE: 'hexagonal',  # circles use hex grid layout
    _SHAPE_TRIANGLE: 'triangular',
    _SHAPE_DIAMOND: 'diamond',
}

_WARNING_THRESHOLD = 50_000

# Circle rendering constants
_CIRCLE_RADIUS_FACTOR = 0.45
_CIRCLE_SEGMENTS = 64


class TileFillAlgorithm(TesseraAlgorithm):
    """Fill input polygons with a regular grid of tiles."""

    def name(self):
        return 'tile_fill'

    def displayName(self):
        return 'Tile Fill'

    def group(self):
        return 'Fill'

    def groupId(self):
        return 'fill'

    def shortHelpString(self):
        return (
            '<p><b>Tile Fill</b> fills polygons with regular tile grids (hexagons, squares, circles, triangles, or diamonds). '
            'Use this to create waffle charts, tile maps, dot density approximations, or proportional '
            'symbol visualizations.</p>'

            '<h3>Common Use Cases</h3>'
            '<ul>'
            '<li><b>Waffle charts:</b> Visualize proportions with filled vs. remainder tiles</li>'
            '<li><b>Tile maps:</b> Replace administrative regions with regular grids for clarity</li>'
            '<li><b>Dot density:</b> Approximate population distribution with uniform tiles</li>'
            '<li><b>Proportional fill:</b> Show percentages by filling only part of the polygon with tiles</li>'
            '</ul>'

            '<h3>Parameters</h3>'
            '<ul>'
            '<li><b>Tile shape:</b> Choose Hexagon (default, best for organic patterns), Square (clean grid look), '
            'Circle (bubble-like appearance), Triangle (alternating up/down equilateral triangles), '
            'or Diamond (45° rotated squares, good for argyle patterns). Hexagons pack most efficiently.</li>'

            '<li><b>Cell size:</b> Tile size in map units (e.g., meters if using a projected CRS). '
            'Set to 0 for automatic sizing based on Target tiles. Manual sizing gives precise control; '
            'auto-sizing adapts to feature dimensions.</li>'

            '<li><b>Target tiles:</b> Used when Cell size is 0. Algorithm computes cell size to fit approximately '
            'this many tiles in each polygon. Default 100. Higher values create finer grids but more features.</li>'

            '<li><b>Clip boundary:</b> When checked (default), tiles are clipped to exact polygon boundaries. '
            'When unchecked, only tiles whose centroids fall within the polygon are kept. Clipping produces '
            'partial tiles at edges; centroid filtering keeps only whole tiles.</li>'

            '<li><b>Circle CRS:</b> For circles only. Specifies the coordinate system in which circles appear round. '
            'Choose "Project CRS" (uses canvas CRS), "Source CRS" (layer CRS), or "Equal area" (preserves roundness in all views). '
            'Matters for map projections that distort shapes.</li>'

            '<li><b>Percentage field (optional):</b> Numeric field with percentage values. When set, tiles are flagged '
            'as "filled" or "remainder" based on the percentage. The first N tiles (sorted bottom-to-top, left-to-right) '
            'are marked "filled", the rest "remainder". The boundary tile may be split into filled and remainder parts.</li>'

            '<li><b>Percentage range:</b> Interprets Percentage field values. Choose "0 - 100" (0-100%), "0 - 1" (0.0-1.0), '
            'or "Auto scale" (each value is divided by the maximum value across all features). Only used when Percentage field is set.</li>'
            '</ul>'

            '<h3>Output Fields</h3>'
            '<ul>'
            '<li><b>tile index (<code>_tessera_tile_index</code>):</b> Integer index starting at 0, assigned bottom-to-top then left-to-right.</li>'
            '<li><b>part (<code>_tessera_part</code>):</b> Present only when Percentage field is set. Values: "filled" or "remainder". '
            'Use this field with a categorized renderer to color filled vs. remainder tiles differently.</li>'
            '</ul>'

            '<h3>Tips and Workflow</h3>'
            '<ul>'
            '<li>Chain with <b>Percentage Split</b> to create proportional waffle charts.</li>'
            '<li>For pixel art cartography, use squares with Clip boundary unchecked.</li>'
            '<li>Set Cell size to 0 and Target tiles to 50-200 for quick auto-sizing.</li>'
            '<li>Hexagons work best for organic patterns; squares for technical/architectural styles.</li>'
            '<li>Large polygons with small cells generate many features. Use Target tiles to avoid performance issues.</li>'
            '<li>The algorithm warns if output exceeds 50,000 features. Increase cell size if this happens.</li>'
            '</ul>'
        )

    def output_layer_name(self):
        return 'Tile filled'

    def createInstance(self):
        return TileFillAlgorithm()

    def initAlgorithm(self, config=None):
        super().initAlgorithm(config)
        self.addParameter(
            QgsProcessingParameterEnum(
                'TILE_SHAPE',
                'Tile shape',
                options=_SHAPE_OPTIONS,
                defaultValue=_SHAPE_HEXAGON,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'CELL_SIZE',
                'Cell size (map units, 0 = auto)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0,
                minValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'TARGET_TILES',
                'Target number of tiles (when cell size is auto)',
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=100,
                minValue=1,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                'CLIP_BOUNDARY',
                'Clip tiles to polygon boundary',
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                'CIRCLE_CRS',
                'Circle construction CRS (circles appear round in this CRS)',
                options=_CIRCLE_CRS_OPTIONS,
                defaultValue=_CIRCLE_CRS_PROJECT,
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                'PERCENT_FIELD',
                'Percentage field (optional, numeric)',
                parentLayerParameterName='INPUT',
                type=QgsProcessingParameterField.Numeric,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                'PERCENT_RANGE',
                'Percentage value range',
                options=VALUE_RANGE_OPTIONS,
                defaultValue=0,
                optional=True,
            )
        )

    def get_output_fields(self, source, parameters=None, context=None):
        """Return output fields: source fields + _tessera_algorithm, _tessera_parent_fid, _tessera_tile_index.

        When PERCENT_FIELD is set, also adds _tessera_part.
        """
        has_percent = False
        if parameters and context:
            pf = self.parameterAsString(parameters, 'PERCENT_FIELD', context)
            has_percent = bool(pf and pf.strip())

        extra = [
            ('_tessera_algorithm', QMetaType.Type.QString),
            ('_tessera_parent_fid', QMetaType.Type.Int),
            ('_tessera_tile_index', QMetaType.Type.Int),
        ]
        if has_percent:
            extra.append(('_tessera_part', QMetaType.Type.QString))
        return create_output_fields(source.fields(), extra)

    def run_algorithm(self, source, parameters, context, working_crs,
                      topology, sink, feedback):
        """Execute the tessellation algorithm."""
        # --- Read parameters ---
        tile_shape = self.parameterAsEnum(parameters, 'TILE_SHAPE', context)
        cell_size = self.parameterAsDouble(parameters, 'CELL_SIZE', context)
        target_tiles = self.parameterAsInt(parameters, 'TARGET_TILES', context)
        clip_boundary = self.parameterAsBool(parameters, 'CLIP_BOUNDARY', context)
        circle_crs_choice = self.parameterAsEnum(parameters, 'CIRCLE_CRS', context)

        percent_field = self.parameterAsString(parameters, 'PERCENT_FIELD', context)
        has_percent = bool(percent_field and percent_field.strip())

        if has_percent:
            percent_range = self.parameterAsEnum(
                parameters, 'PERCENT_RANGE', context)
        else:
            percent_range = 0

        grid_type = _GRID_TYPE_MAP[tile_shape]
        output_fields = self.get_output_fields(source, parameters, context)

        # For auto-detect, scan all values to determine divisor
        auto_divisor = None
        if has_percent and percent_range == 2:
            auto_divisor = detect_divisor(source, percent_field, feedback)

        total_features = source.featureCount()
        feature_count = 0
        total_output = 0
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

            # Compute bounding box in working CRS
            bbox = work_geom.boundingBox()

            # Auto cell size if requested
            feat_cell_size = cell_size
            if feat_cell_size == 0:
                feat_cell_size = auto_cell_size(bbox, target_tiles, grid_type)
            if feat_cell_size <= 0:
                feature_count += 1
                continue

            # Expand bbox by 1 cell_size padding
            padded_bbox = QgsRectangle(
                bbox.xMinimum() - feat_cell_size,
                bbox.yMinimum() - feat_cell_size,
                bbox.xMaximum() + feat_cell_size,
                bbox.yMaximum() + feat_cell_size,
            )

            # Generate grid cells
            cells = self._generate_cells(
                tile_shape, padded_bbox, feat_cell_size, grid_type,
                circle_crs_choice, working_crs, source, context,
            )

            # Process each cell: clip or centroid-filter
            raw_tiles = []  # list of (center_point, tile_geometry)
            for center, cell_geom in cells:
                if feedback.isCanceled():
                    break

                if clip_boundary:
                    clipped = cell_geom.intersection(work_geom)
                    clipped = extract_polygons(clipped)
                    if clipped.isEmpty():
                        continue
                    raw_tiles.append((center, clipped))
                else:
                    centroid = cell_geom.centroid()
                    if not work_geom.contains(centroid):
                        continue
                    raw_tiles.append((center, cell_geom))

            # Sort tiles by (y ascending, x ascending) for bottom-to-top, left-to-right
            raw_tiles.sort(key=lambda t: (t[0].y(), t[0].x()))

            # Read percentage value for this feature if PERCENT_FIELD is set
            fraction = None
            if has_percent:
                fraction = read_fraction(
                    feature, percent_field, percent_range, auto_divisor,
                    feedback)

            # Build output features with tile indices and optional fill status
            n_tiles = len(raw_tiles)
            if has_percent and fraction is not None:
                filled_count = math.floor(fraction * n_tiles)
                leftover = fraction * n_tiles - filled_count
            else:
                filled_count = 0
                leftover = 0.0

            for tile_index, (center, tile_geom) in enumerate(raw_tiles):
                if feedback.isCanceled():
                    break

                new_feats = self._emit_tile(
                    tile_geom, tile_index, feature, working_crs,
                    output_fields, has_percent, fraction,
                    filled_count, leftover,
                )
                batch.extend(new_feats)
                total_output += len(new_feats)

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

        # Warn if large output
        if total_output > _WARNING_THRESHOLD:
            feedback.pushWarning(
                f'Tessellate produced {total_output} features, '
                f'exceeding the 50,000 warning threshold. '
                f'Consider using a larger cell size.'
            )

    @staticmethod
    def _generate_cells(tile_shape, padded_bbox, cell_size, grid_type,
                        circle_crs_choice, working_crs, source, context):
        """Generate grid cells for one feature's bounding box.

        Returns list of (center_point, polygon_geometry) tuples.
        """
        if tile_shape != _SHAPE_CIRCLE:
            return generate_cell_polygons(padded_bbox, cell_size, grid_type)

        # Circle tiles: hex grid point layout with circle geometries
        points = generate_point_grid(padded_bbox, cell_size, 'hexagonal')
        radius = cell_size * _CIRCLE_RADIUS_FACTOR

        if circle_crs_choice == _CIRCLE_CRS_EQUAL_AREA:
            return [
                (pt, regular_polygon(pt, radius, _CIRCLE_SEGMENTS, 0))
                for pt in points
            ]

        # Build circles in target CRS for visual roundness
        target_crs = (
            context.project().crs()
            if circle_crs_choice == _CIRCLE_CRS_PROJECT
            else source.sourceCrs()
        )
        to_target = QgsCoordinateTransform(
            working_crs.working_crs, target_crs, context.project()
        )
        from_target = QgsCoordinateTransform(
            target_crs, working_crs.working_crs, context.project()
        )
        cells = []
        for pt in points:
            tgt_center = to_target.transform(pt)
            east_pt = QgsPointXY(pt.x() + radius, pt.y())
            tgt_east = to_target.transform(east_pt)
            tgt_radius = abs(tgt_east.x() - tgt_center.x())
            circle = regular_polygon(
                QgsPointXY(tgt_center.x(), tgt_center.y()),
                tgt_radius, _CIRCLE_SEGMENTS, 0,
            )
            circle.transform(from_target)
            cells.append((pt, circle))
        return cells

    @staticmethod
    def _emit_tile(tile_geom, tile_index, feature, working_crs,
                   output_fields, has_percent, fraction,
                   filled_count, leftover):
        """Build output feature(s) for a single tile.

        Returns a list of QgsFeature (1 without percentage, up to 2 with).
        """
        if not has_percent or fraction is None:
            out_geom = working_crs.inverse(tile_geom)
            return [build_feature(
                out_geom, feature, 'tile_fill',
                {'_tessera_tile_index': tile_index},
                output_fields,
            )]

        results = []
        if tile_index < filled_count:
            out_geom = working_crs.inverse(tile_geom)
            results.append(build_feature(
                out_geom, feature, 'tile_fill',
                {'_tessera_tile_index': tile_index,
                 '_tessera_part': 'filled'},
                output_fields,
            ))
        elif tile_index == filled_count and leftover > 0.0:
            # Boundary tile: split into filled + remainder
            filled_geom, remainder_geom = split_polygon_by_fraction(
                tile_geom, leftover, 'horizontal')
            if not filled_geom.isEmpty():
                results.append(build_feature(
                    working_crs.inverse(filled_geom), feature, 'tile_fill',
                    {'_tessera_tile_index': tile_index,
                     '_tessera_part': 'filled'},
                    output_fields,
                ))
            if not remainder_geom.isEmpty():
                results.append(build_feature(
                    working_crs.inverse(remainder_geom), feature, 'tile_fill',
                    {'_tessera_tile_index': tile_index,
                     '_tessera_part': 'remainder'},
                    output_fields,
                ))
        else:
            out_geom = working_crs.inverse(tile_geom)
            results.append(build_feature(
                out_geom, feature, 'tile_fill',
                {'_tessera_tile_index': tile_index,
                 '_tessera_part': 'remainder'},
                output_fields,
            ))
        return results
