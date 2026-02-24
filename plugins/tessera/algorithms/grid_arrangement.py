"""Grid Arrangement algorithm — place features in a regular grid layout.

Creates small-multiples poster layouts by arranging features in rows and
columns. Outputs in engineering CRS (flat Cartesian meters). Designed to
chain after Replace with Shape or Scale by Value.
"""
import math

from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType

from ..infrastructure.feature_builder import create_output_fields, build_feature
from ..infrastructure.crs_manager import WorkingCRS, create_engineering_crs
from .base_algorithm import TesseraAlgorithm


_FILL_ORDER_OPTIONS = [
    'Not selected',
    'Row first (down)',
    'Row first (up)',
    'Column first (left)',
    'Column first (right)',
]


def _largest_part_bbox(geom):
    """Return bounding box of the largest part (by area) for multipart geometries."""
    if geom.isMultipart():
        parts = geom.asGeometryCollection()
        if parts:
            return max(parts, key=lambda p: p.area()).boundingBox()
    return geom.boundingBox()


def _grid_position(idx, cols, rows, fill_order):
    """Convert linear index to (row, col) grid position.

    Row 0 is bottom, row (rows-1) is top in map coordinates.
    fill_order: 0=Not selected (same as 1), 1=Row first (down),
    2=Row first (up), 3=Column first (left), 4=Column first (right).
    """
    if fill_order <= 1:
        row = (rows - 1) - idx // cols
        col = idx % cols
    elif fill_order == 2:
        row = idx // cols
        col = idx % cols
    elif fill_order == 3:
        col = idx // rows
        row = (rows - 1) - idx % rows
    else:
        col = (cols - 1) - idx // rows
        row = (rows - 1) - idx % rows
    return row, col


def _cell_to_feature_index(row, col, cols, rows, fill_order):
    """Convert (row, col) grid position back to linear feature index.

    Returns None if no feature maps to this cell position.
    """
    if fill_order <= 1:
        idx = (rows - 1 - row) * cols + col
    elif fill_order == 2:
        idx = row * cols + col
    elif fill_order == 3:
        idx = col * rows + (rows - 1 - row)
    else:
        idx = (cols - 1 - col) * rows + (rows - 1 - row)
    return idx


class GridArrangementAlgorithm(TesseraAlgorithm):
    """Place features in a regular grid layout for small-multiples posters."""

    def name(self):
        return 'grid_arrangement'

    def displayName(self):
        return 'Grid Arrangement'

    def group(self):
        return 'Layout'

    def groupId(self):
        return 'layout'

    def shortHelpString(self):
        return (
            '<p><b>Grid Arrangement</b> places features in a regular grid layout for '
            'small-multiples poster visualizations. '
            'Designed to follow <b>Scale by Value</b> or <b>Replace with Shape</b>.</p>'

            '<h3>How It Works</h3>'
            '<p>Each feature is translated to a grid cell position. The grid cell size '
            'is determined automatically from the largest feature bounding box, or can '
            'be set manually. Features are optionally sorted by a field before placement.</p>'

            '<h3>Parameters</h3>'
            '<ul>'
            '<li><b>Grid columns:</b> Number of columns (0 = auto, uses sqrt(n)).</li>'
            '<li><b>Grid cell width / height:</b> Cell dimensions in map units (0 = auto).</li>'
            '<li><b>Internal padding:</b> Space between features and cell borders.</li>'
            '<li><b>Grid padding:</b> Space between cells in map units.</li>'
            '<li><b>Grid sort field:</b> Sort features before grid placement.</li>'
            '<li><b>Grid fill order:</b> Row first or Column first.</li>'
            '</ul>'

            '<h3>CRS Behavior</h3>'
            '<p>Output is always in a flat Cartesian engineering CRS (meters). '
            'This ensures grid cells are rectangular and undistorted.</p>'

            '<h3>Tips</h3>'
            '<ul>'
            '<li><b>Small multiples:</b> Sort by a category field for logical ordering.</li>'
            '<li><b>Equal cells:</b> Set explicit cell width/height for uniform grid.</li>'
            '<li><b>Grid cells output:</b> Enable to get rectangular cell boundaries as a separate layer.</li>'
            '</ul>'
        )

    def output_layer_name(self):
        return 'Grid arranged'

    def createInstance(self):
        return GridArrangementAlgorithm()

    def initAlgorithm(self, config=None):
        """Define parameters: INPUT, OUTPUT (from base) + grid options."""
        super().initAlgorithm(config)

        self.addParameter(
            QgsProcessingParameterNumber(
                'GRID_COLUMNS',
                'Grid columns (0 = auto)',
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=0,
                minValue=0,
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                'GRID_CELL_WIDTH',
                'Grid cell width (map units, 0 = auto)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                minValue=0.0,
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                'GRID_CELL_HEIGHT',
                'Grid cell height (map units, 0 = auto)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                minValue=0.0,
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                'GRID_INTERNAL_PADDING',
                'Internal padding (map units)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                minValue=0.0,
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                'GRID_PADDING',
                'Grid padding (map units)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                minValue=0.0,
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                'GRID_SORT_FIELD',
                'Grid sort field',
                parentLayerParameterName='INPUT',
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                'GRID_FILL_ORDER',
                'Grid fill order',
                options=_FILL_ORDER_OPTIONS,
                defaultValue=0,
                optional=True,
            )
        )

        grid_cells_param = QgsProcessingParameterFeatureSink(
            'GRID_CELLS',
            'Grid cells',
            optional=True,
        )
        grid_cells_param.setCreateByDefault(False)
        self.addParameter(grid_cells_param)

    def get_output_fields(self, source, parameters=None, context=None):
        """Return source fields + _tessera_algorithm, _tessera_parent_fid, _tessera_iteration."""
        return create_output_fields(source.fields(), [
            ('_tessera_algorithm', QMetaType.Type.QString),
            ('_tessera_parent_fid', QMetaType.Type.Int),
            ('_tessera_iteration', QMetaType.Type.Int),
        ])

    def processAlgorithm(self, parameters, context, feedback):
        """Override base to output in engineering CRS."""
        source = self.parameterAsSource(parameters, 'INPUT', context)
        output_fields = self.get_output_fields(source, parameters, context)
        output_crs = create_engineering_crs()

        working_crs = WorkingCRS(
            source.sourceCrs(), source.sourceExtent(), self.crs_strategy
        )

        (sink, dest_id) = self.parameterAsSink(
            parameters, 'OUTPUT', context,
            output_fields, QgsWkbTypes.MultiPolygon, output_crs,
        )

        grid_cells_sink = None
        grid_cells_dest_id = None
        if parameters.get('GRID_CELLS') is not None:
            grid_cell_fields = create_output_fields(source.fields(), [
                ('_tessera_algorithm', QMetaType.Type.QString),
                ('_tessera_grid_row', QMetaType.Type.Int),
                ('_tessera_grid_col', QMetaType.Type.Int),
                ('_tessera_grid_cell_index', QMetaType.Type.Int),
            ])
            (grid_cells_sink, grid_cells_dest_id) = self.parameterAsSink(
                parameters, 'GRID_CELLS', context,
                grid_cell_fields, QgsWkbTypes.MultiPolygon, output_crs,
            )

        topology = None
        self.run_algorithm(
            source, parameters, context, working_crs, topology, sink,
            feedback, grid_cells_sink=grid_cells_sink,
        )

        result = {'OUTPUT': dest_id}
        if grid_cells_dest_id is not None:
            result['GRID_CELLS'] = grid_cells_dest_id
        return result

    def run_algorithm(self, source, parameters, context, working_crs,
                      topology, sink, feedback, grid_cells_sink=None):
        """Place features in a regular grid layout."""
        output_fields = self.get_output_fields(source)

        grid_columns = self.parameterAsInt(parameters, 'GRID_COLUMNS', context)
        grid_cell_width = self.parameterAsDouble(
            parameters, 'GRID_CELL_WIDTH', context)
        grid_cell_height = self.parameterAsDouble(
            parameters, 'GRID_CELL_HEIGHT', context)
        grid_internal_padding = self.parameterAsDouble(
            parameters, 'GRID_INTERNAL_PADDING', context)
        grid_padding = self.parameterAsDouble(
            parameters, 'GRID_PADDING', context)
        grid_sort_field = self.parameterAsString(
            parameters, 'GRID_SORT_FIELD', context)
        grid_fill_order = self.parameterAsEnum(
            parameters, 'GRID_FILL_ORDER', context)

        feat_list = []
        work_geom_list = []
        for feature in source.getFeatures():
            if feedback.isCanceled():
                return
            geom = feature.geometry()
            if geom.isEmpty() or geom.isNull():
                out_feat = build_feature(
                    geom, feature, 'grid_arrangement',
                    {'_tessera_iteration': 0}, output_fields)
                sink.addFeatures([out_feat])
                continue
            work_geom = working_crs.forward(geom)
            if work_geom.isEmpty():
                out_feat = build_feature(
                    geom, feature, 'grid_arrangement',
                    {'_tessera_iteration': 0}, output_fields)
                sink.addFeatures([out_feat])
                continue
            feat_list.append(feature)
            work_geom_list.append(work_geom)

        n = len(feat_list)
        if n == 0:
            return

        if grid_sort_field and grid_sort_field.strip():
            indices = list(range(n))
            indices.sort(key=lambda idx: feat_list[idx].attribute(grid_sort_field))
            feat_list = [feat_list[i] for i in indices]
            work_geom_list = [work_geom_list[i] for i in indices]

        cols = grid_columns if grid_columns > 0 else math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)

        max_w = 0.0
        max_h = 0.0
        for wg in work_geom_list:
            bbox = wg.boundingBox()
            max_w = max(max_w, bbox.width())
            max_h = max(max_h, bbox.height())

        cell_w = grid_cell_width if grid_cell_width > 0 else max_w + 2 * grid_internal_padding
        cell_h = grid_cell_height if grid_cell_height > 0 else max_h + 2 * grid_internal_padding

        if grid_cells_sink is not None:
            grid_cell_fields = create_output_fields(source.fields(), [
                ('_tessera_algorithm', QMetaType.Type.QString),
                ('_tessera_grid_row', QMetaType.Type.Int),
                ('_tessera_grid_col', QMetaType.Type.Int),
                ('_tessera_grid_cell_index', QMetaType.Type.Int),
            ])
            cell_index = 0
            for r in range(rows):
                for c in range(cols):
                    x_min = c * (cell_w + grid_padding)
                    y_min = r * (cell_h + grid_padding)
                    x_max = x_min + cell_w
                    y_max = y_min + cell_h
                    ring = [
                        QgsPointXY(x_min, y_min),
                        QgsPointXY(x_max, y_min),
                        QgsPointXY(x_max, y_max),
                        QgsPointXY(x_min, y_max),
                        QgsPointXY(x_min, y_min),
                    ]
                    cell_geom = QgsGeometry.fromPolygonXY([ring])
                    cell_geom.convertToMultiType()
                    cell_feat = QgsFeature(grid_cell_fields)
                    cell_feat.setGeometry(cell_geom)

                    feat_idx = _cell_to_feature_index(
                        r, c, cols, rows, grid_fill_order)
                    if feat_idx is not None and feat_idx < n:
                        parent = feat_list[feat_idx]
                        parent_fields = parent.fields()
                        for fi in range(parent_fields.count()):
                            field_name = parent_fields.field(fi).name()
                            idx = grid_cell_fields.indexOf(field_name)
                            if idx >= 0:
                                cell_feat.setAttribute(idx, parent.attribute(fi))

                    cell_feat.setAttribute('_tessera_algorithm', 'grid_arrangement')
                    cell_feat.setAttribute('_tessera_grid_row', r)
                    cell_feat.setAttribute('_tessera_grid_col', c)
                    cell_feat.setAttribute('_tessera_grid_cell_index', cell_index)
                    grid_cells_sink.addFeatures([cell_feat])
                    cell_index += 1

        for idx in range(n):
            if feedback.isCanceled():
                return

            row, col = _grid_position(idx, cols, rows, grid_fill_order)

            cell_center_x = col * (cell_w + grid_padding) + cell_w / 2.0
            cell_center_y = row * (cell_h + grid_padding) + cell_h / 2.0

            work_geom = QgsGeometry(work_geom_list[idx])
            centroid = work_geom.centroid().asPoint()
            dx = cell_center_x - centroid.x()
            dy = cell_center_y - centroid.y()
            work_geom.translate(dx, dy)

            out_feat = build_feature(
                work_geom, feat_list[idx], 'grid_arrangement',
                {'_tessera_iteration': 0}, output_fields)
            sink.addFeatures([out_feat])

            feedback.setProgress(int((idx + 1) / n * 100))
