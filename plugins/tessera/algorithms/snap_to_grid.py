"""Snap to Grid algorithm — spec section 5.4.

Densifies polygon edges and snaps vertices to the nearest grid cell
**corner** (vertex, not centre), producing output edges that follow grid
cell boundaries.  Uses TopologyTransformer to ensure shared boundaries
remain consistent.
"""
from qgis.core import (
    QgsGeometry,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsPointXY,
    QgsFeature,
)
from PyQt5.QtCore import QMetaType

from ..infrastructure.grid_generators import (
    nearest_grid_point,
    nearest_grid_vertex,
    grid_edge_length,
    trace_grid_path,
)
from ..infrastructure.feature_builder import create_output_fields, build_feature
from ..infrastructure.geometry_helpers import extract_polygons
from ..infrastructure.topology_wrapper import TopologyTransformer
from .base_algorithm import TesseraAlgorithm

_GRID_TYPE_MAP = {0: 'square', 1: 'hexagonal', 2: 'triangular'}


def remove_spikes(ring, snap_tolerance=1e-6):
    """Remove spike vertices from a polygon ring.

    A spike occurs when vertex[i] ≈ vertex[i+2] (within tolerance),
    making vertex[i+1] a zero-width spike tip.  Removes vertex[i+1]
    and vertex[i+2], keeps vertex[i].  Loops until stable.

    Parameters
    ----------
    ring : list[QgsPointXY]
        Polygon ring (first == last for closure).
    snap_tolerance : float
        Distance threshold for considering two vertices coincident.

    Returns
    -------
    list[QgsPointXY]
        Ring with spikes removed.  May have < 4 vertices if degenerate.
    """
    result = list(ring)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(result) - 2:
            vi = result[i]
            vi2 = result[i + 2]
            dx = vi.x() - vi2.x()
            dy = vi.y() - vi2.y()
            if (dx * dx + dy * dy) <= snap_tolerance * snap_tolerance:
                del result[i + 1:i + 3]
                changed = True
            else:
                i += 1
        # Re-close ring if needed
        if len(result) >= 2:
            first, last = result[0], result[-1]
            dx = first.x() - last.x()
            dy = first.y() - last.y()
            if (dx * dx + dy * dy) > snap_tolerance * snap_tolerance:
                result.append(QgsPointXY(first.x(), first.y()))
    return result


def remove_consecutive_duplicates(ring, tolerance=1e-6):
    """Collapse consecutive vertices that snap to the same position.

    Parameters
    ----------
    ring : list[QgsPointXY]
        Polygon ring (first == last for closure).
    tolerance : float
        Distance threshold for considering two vertices coincident.

    Returns
    -------
    list[QgsPointXY]
        Ring with consecutive duplicates collapsed.
    """
    if len(ring) < 2:
        return ring
    tol_sq = tolerance * tolerance
    result = [ring[0]]
    for pt in ring[1:]:
        prev = result[-1]
        dx = pt.x() - prev.x()
        dy = pt.y() - prev.y()
        if (dx * dx + dy * dy) > tol_sq:
            result.append(pt)
    # Re-close ring
    if len(result) >= 2:
        first, last = result[0], result[-1]
        dx = first.x() - last.x()
        dy = first.y() - last.y()
        if (dx * dx + dy * dy) > tol_sq:
            result.append(QgsPointXY(first.x(), first.y()))
    return result


def resolve_grid_edges(ring, spacing, grid_type):
    """Insert intermediate vertices so all edges follow grid boundaries.

    For each pair of consecutive vertices not connected by a single grid
    edge, inserts the shortest path along grid edges (staircase for
    square, hex-edge path for hexagonal, etc.).

    Uses canonical endpoint ordering (lexicographic by x then y) so that
    shared edges between adjacent features produce identical intermediate
    vertices regardless of traversal direction.

    Parameters
    ----------
    ring : list[QgsPointXY]
        Polygon ring with vertices on the grid vertex lattice.
    spacing : float
        Grid spacing.
    grid_type : str
        One of ``'square'``, ``'hexagonal'``, ``'triangular'``.

    Returns
    -------
    list[QgsPointXY]
        Ring with intermediate grid-edge vertices inserted.
    """
    if len(ring) < 2:
        return ring
    result = [ring[0]]
    for i in range(1, len(ring)):
        p1 = result[-1]
        p2 = ring[i]
        if (p1.x(), p1.y()) > (p2.x(), p2.y()):
            intermediates = trace_grid_path(p2, p1, spacing, grid_type)
            intermediates.reverse()
        else:
            intermediates = trace_grid_path(p1, p2, spacing, grid_type)
        result.extend(intermediates)
        result.append(ring[i])
    return result


class SnapToGridAlgorithm(TesseraAlgorithm):
    """Snap feature vertices towards grid points with topology preservation."""

    topology_aware = True

    def name(self):
        return 'snap_to_grid'

    def displayName(self):
        return 'Snap to Grid'

    def group(self):
        return 'Shape'

    def groupId(self):
        return 'shape'

    def shortHelpString(self):
        return (
            '<p><b>Snap to Grid</b> makes polygon edges follow grid cell boundaries, producing a blocky, '
            'pixelated appearance. Edges are densified and snapped to grid cell <i>corners</i> (not centres), '
            'so output edges zigzag along cell boundaries. Topology-aware: shared boundaries between adjacent '
            'features remain consistent, preventing gaps or overlaps.</p>'

            '<h3>How It Works</h3>'
            '<ol>'
            '<li><b>Densify:</b> Long edges are subdivided so no segment is longer than half a grid cell edge.</li>'
            '<li><b>Snap:</b> Every vertex is pulled toward the nearest grid cell corner with configurable attraction.</li>'
            '<li><b>Clean up:</b> Consecutive duplicate vertices are collapsed and spike artifacts are removed.</li>'
            '</ol>'

            '<h3>Common Use Cases</h3>'
            '<ul>'
            '<li><b>Stylized/blocky map aesthetics:</b> Create geometric, pixelated map styles</li>'
            '<li><b>Pixel art cartography:</b> Convert smooth polygons into grid-aligned shapes with edges following cell boundaries</li>'
            '<li><b>Simplified geometries:</b> Reduce vertex density while maintaining recognizable shapes</li>'
            '<li><b>Retro/8-bit map style:</b> Evoke vintage video game aesthetics</li>'
            '</ul>'

            '<h3>Parameters</h3>'
            '<ul>'
            '<li><b>Grid type:</b> Grid pattern to snap toward. Options:'
            '<ul>'
            '<li><i>Square:</i> Rectangular grid (most common, creates blocky orthogonal shapes)</li>'
            '<li><i>Hexagonal (default):</i> Honeycomb grid (organic look, six-way symmetry)</li>'
            '<li><i>Triangular:</i> Triangular grid (angular aesthetic, three-way symmetry)</li>'
            '</ul>'
            'Square grids produce the cleanest pixel-art effect. Hexagonal grids approximate circles better.</li>'

            '<li><b>Cell size:</b> Grid spacing in map units. Set to 0 for automatic sizing based on Auto cells across. '
            'Larger cells = stronger blocky effect. Smaller cells preserve more detail.</li>'

            '<li><b>Auto cells across:</b> Used when Cell size is 0. Divides the extent into this many cells '
            'across the smaller dimension. Default 30.</li>'

            '<li><b>Attraction:</b> Snap strength from 0.0 to 1.0:'
            '<ul>'
            '<li><i>0.0:</i> No snapping (features unchanged)</li>'
            '<li><i>0.3-0.5:</i> Subtle grid influence</li>'
            '<li><i>0.7-0.9:</i> Strong snapping</li>'
            '<li><i>1.0 (default):</i> Full snap — edges follow cell boundaries precisely</li>'
            '</ul></li>'
            '</ul>'

            '<h3>Topology Preservation</h3>'
            '<p>Shared edges between adjacent polygons are densified and snapped identically, '
            'maintaining seamless boundaries. No gaps or overlaps are introduced.</p>'

            '<h3>Tips</h3>'
            '<ul>'
            '<li>For pixel art maps, use <b>Square grid</b> with <b>Attraction = 1.0</b> and low Auto cells across (10-20).</li>'
            '<li>Chain with <b>Sketchy Borders</b> for a hand-drawn grid effect.</li>'
            '<li>Hexagonal grids work well for organic/natural features; square grids for built environments.</li>'
            '<li>Set Cell size manually for consistency across multiple layers.</li>'
            '</ul>'
        )

    def output_layer_name(self):
        return 'Snapped to grid'

    def createInstance(self):
        return SnapToGridAlgorithm()

    def initAlgorithm(self, config=None):
        """Define parameters: INPUT, OUTPUT (from base) + grid options."""
        super().initAlgorithm(config)
        self.addParameter(
            QgsProcessingParameterEnum(
                'GRID_TYPE',
                'Grid type',
                options=['Square', 'Hexagonal', 'Triangular'],
                defaultValue=1,
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
                'AUTO_CELLS_ACROSS',
                'Auto cells across (when cell size is 0)',
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=30,
                minValue=5,
                maxValue=200,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'ATTRACTION',
                'Attraction (0 = none, 1 = full snap)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.0,
                minValue=0.0,
                maxValue=1.0,
            )
        )

    def get_output_fields(self, source, parameters=None, context=None):
        """Return source fields + _tessera_algorithm, _tessera_parent_fid."""
        return create_output_fields(source.fields(), [
            ('_tessera_algorithm', QMetaType.Type.QString),
            ('_tessera_parent_fid', QMetaType.Type.Int),
        ])

    def run_algorithm(self, source, parameters, context, working_crs,
                      topology, sink, feedback):
        """Execute the snap-to-grid algorithm."""
        # --- Read parameters ---
        grid_type_enum = self.parameterAsEnum(parameters, 'GRID_TYPE', context)
        cell_size = self.parameterAsDouble(parameters, 'CELL_SIZE', context)
        auto_cells_across = self.parameterAsInt(
            parameters, 'AUTO_CELLS_ACROSS', context
        )
        attraction = self.parameterAsDouble(parameters, 'ATTRACTION', context)

        grid_type = _GRID_TYPE_MAP[grid_type_enum]
        output_fields = self.get_output_fields(source)

        # --- Collect all features and transform to working CRS ---
        features = []
        original_geoms = []
        for feature in source.getFeatures():
            if feedback.isCanceled():
                return

            geom = feature.geometry()
            if geom.isEmpty() or geom.isNull():
                # Pass through empty features directly
                out_feat = build_feature(
                    geom, feature, 'snap_to_grid', {}, output_fields,
                )
                sink.addFeatures([out_feat])
                continue

            # Transform to working CRS
            work_geom = working_crs.forward(geom)
            if work_geom.isEmpty():
                out_feat = build_feature(
                    geom, feature, 'snap_to_grid', {}, output_fields,
                )
                sink.addFeatures([out_feat])
                continue

            # Build a working feature with transformed geometry
            work_feat = QgsFeature(feature.fields())
            work_feat.setAttributes(feature.attributes())
            work_feat.setGeometry(work_geom)
            work_feat.setId(feature.id())
            features.append(work_feat)
            original_geoms.append(geom)

        if not features:
            return

        # --- Compute cell size if auto ---
        if cell_size == 0:
            # Compute combined extent of all working-CRS features
            combined_extent = features[0].geometry().boundingBox()
            for feat in features[1:]:
                combined_extent.combineExtentWith(feat.geometry().boundingBox())
            cell_size = min(
                combined_extent.width(), combined_extent.height()
            ) / auto_cells_across

        if cell_size <= 0:
            # Degenerate extent -- copy features as-is
            for feat, orig_geom in zip(features, original_geoms):
                out_feat = build_feature(
                    orig_geom, feat, 'snap_to_grid', {}, output_fields,
                )
                sink.addFeatures([out_feat])
            return

        # --- Short-circuit if attraction == 0 ---
        if attraction == 0.0:
            for feat, orig_geom in zip(features, original_geoms):
                out_feat = build_feature(
                    orig_geom, feat, 'snap_to_grid', {}, output_fields,
                )
                sink.addFeatures([out_feat])
            return

        # --- Build TopologyTransformer, densify, and transform ---
        edge_len = grid_edge_length(cell_size, grid_type)
        densify_interval = edge_len / 2.0

        tt = TopologyTransformer(features, feedback)
        tt.densify_shared_edges(densify_interval)

        def snap_vertex(point, vertex_id):
            """Snap a vertex towards the nearest grid cell corner."""
            target = nearest_grid_vertex(point, cell_size, grid_type)
            new_x = point.x() + (target.x() - point.x()) * attraction
            new_y = point.y() + (target.y() - point.y()) * attraction
            return QgsPointXY(new_x, new_y)

        transformed_features = tt.transform(snap_vertex)

        if feedback.isCanceled():
            return

        # --- Resolve diagonal edges into grid-aligned paths ---
        if attraction == 1.0:
            self._resolve_grid_edges_in_features(
                transformed_features, cell_size, grid_type,
            )

        if feedback.isCanceled():
            return

        # --- Remove spikes caused by grid snapping ---
        self._remove_spikes_from_features(
            transformed_features, original_geoms, cell_size, grid_type,
        )

        if feedback.isCanceled():
            return

        # --- Build output features, transform back to source CRS ---
        for i, (trans_feat, orig_feat) in enumerate(
            zip(transformed_features, features)
        ):
            if feedback.isCanceled():
                return

            # Transform geometry back to source CRS
            out_geom = working_crs.inverse(trans_feat.geometry())

            # Repair invalid geometries from grid snapping (self-intersections,
            # bow-ties from vertices crossing after coarse snap)
            if not out_geom.isEmpty() and not out_geom.isGeosValid():
                out_geom = out_geom.makeValid()
                out_geom = extract_polygons(out_geom)

            out_feat = build_feature(
                out_geom, orig_feat, 'snap_to_grid', {}, output_fields,
            )
            sink.addFeatures([out_feat])

            if source.featureCount() > 0:
                feedback.setProgress(int((i + 1) / source.featureCount() * 100))

    @staticmethod
    def _remove_spikes_from_features(features, original_geoms, cell_size,
                                     grid_type):
        """Remove spikes from all features, falling back to originals for degenerate rings.

        Parameters
        ----------
        features : list[QgsFeature]
            Transformed features (modified in-place).
        original_geoms : list[QgsGeometry]
            Original geometries to fall back to if exterior ring becomes degenerate.
        cell_size : float
            Grid spacing.
        grid_type : str
            One of ``'square'``, ``'hexagonal'``, ``'triangular'``.
        """
        edge_len = grid_edge_length(cell_size, grid_type)
        spike_tolerance = edge_len * 0.3

        for idx, feat in enumerate(features):
            geom = feat.geometry()
            if geom.isNull() or geom.isEmpty():
                continue

            parts = (geom.asMultiPolygon() if geom.isMultipart()
                     else [geom.asPolygon()])
            new_parts = []

            dedup_tolerance = cell_size * 0.01

            for part in parts:
                if not part:
                    continue
                exterior = part[0]
                exterior = remove_consecutive_duplicates(exterior, dedup_tolerance)
                cleaned_exterior = remove_spikes(exterior, spike_tolerance)
                if len(cleaned_exterior) < 4:
                    continue
                new_rings = [cleaned_exterior]
                for hole in part[1:]:
                    hole = remove_consecutive_duplicates(hole, dedup_tolerance)
                    cleaned_hole = remove_spikes(hole, spike_tolerance)
                    if len(cleaned_hole) >= 4:
                        new_rings.append(cleaned_hole)
                new_parts.append(new_rings)

            if not new_parts:
                feat.setGeometry(QgsGeometry(original_geoms[idx]))
                continue

            if geom.isMultipart():
                new_geom = QgsGeometry.fromMultiPolygonXY(new_parts)
            else:
                new_geom = QgsGeometry.fromPolygonXY(new_parts[0])
            feat.setGeometry(new_geom)

    @staticmethod
    def _resolve_grid_edges_in_features(features, cell_size, grid_type):
        """Replace diagonal edges with grid-aligned paths in all features.

        Modifies features in-place.  For each ring, inserts intermediate
        grid vertices so that every edge follows a grid cell boundary.

        Parameters
        ----------
        features : list[QgsFeature]
            Transformed features (modified in-place).
        cell_size : float
            Grid spacing.
        grid_type : str
            One of ``'square'``, ``'hexagonal'``, ``'triangular'``.
        """
        for feat in features:
            geom = feat.geometry()
            if geom.isNull() or geom.isEmpty():
                continue

            parts = (geom.asMultiPolygon() if geom.isMultipart()
                     else [geom.asPolygon()])
            new_parts = []

            for part in parts:
                if not part:
                    continue
                new_rings = []
                for ring in part:
                    new_rings.append(
                        resolve_grid_edges(ring, cell_size, grid_type)
                    )
                new_parts.append(new_rings)

            if geom.isMultipart():
                new_geom = QgsGeometry.fromMultiPolygonXY(new_parts)
            else:
                new_geom = QgsGeometry.fromPolygonXY(new_parts[0])
            feat.setGeometry(new_geom)
