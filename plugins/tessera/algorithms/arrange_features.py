"""Arrange Features algorithm — geometric overlap resolution and force-directed
attraction.

Separate and gap modes use geometric intersection detection (spatial grid +
bounding box filter + precise intersects() check). Attract mode uses
force-directed simulation.

Designed to chain after Replace with Shape or Scale by Value.
"""
import math
from collections import defaultdict

from qgis.core import (
    QgsGeometry,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType

from ..infrastructure.feature_builder import create_output_fields, build_feature
from ..infrastructure.crs_manager import WorkingCRS, create_engineering_crs
from .base_algorithm import TesseraAlgorithm


_QUALITY_OPTIONS = ['Fast', 'Balanced', 'Precise', 'Custom advanced parameters']
_QUALITY_FAST = 0
_QUALITY_BALANCED = 1
_QUALITY_PRECISE = 2
_QUALITY_CUSTOM = 3

_QUALITY_PRESETS = {
    _QUALITY_FAST: {
        'iterations': 30, 'damping': 0.3, 'anchor_strength': 0.05,
        'convergence_threshold': 0.05, 'adaptive_damping': True,
    },
    _QUALITY_BALANCED: {
        'iterations': 100, 'damping': 0.1, 'anchor_strength': 0.01,
        'convergence_threshold': 0.01, 'adaptive_damping': True,
    },
    _QUALITY_PRECISE: {
        'iterations': 500, 'damping': 0.05, 'anchor_strength': 0.005,
        'convergence_threshold': 0.001, 'adaptive_damping': True,
    },
}

# Force-directed / refinement constants
# 0.3 = fraction of penetration depth applied per iteration; conservative
# to avoid overshooting and oscillation in the refinement pass.
_GENTLE_PUSH_FACTOR = 0.3
# Cap on geometry-based refinement iterations (gap and overlap modes).
# 200 is generous — convergence typically occurs in 10-50 iterations.
_MAX_REFINEMENT_ITERATIONS = 200
# Below this feature count, skip spatial grid and use brute-force O(n^2)
# pair iteration (grid overhead exceeds savings for small n).
_BRUTE_FORCE_THRESHOLD = 200


def _build_spatial_grid(geometries, cell_size, offsets=None):
    """Build spatial hash grid from geometry bounding box centroids.

    Args:
        geometries: List of QgsGeometry objects.
        cell_size: Grid cell size.
        offsets: Optional list of [dx, dy] displacement offsets per geometry.
                 Required for methods that use work_geoms + total_displacements.
    """
    grid = defaultdict(list)
    for i, geom in enumerate(geometries):
        bbox = geom.boundingBox()
        cx = (bbox.xMinimum() + bbox.xMaximum()) / 2.0
        cy = (bbox.yMinimum() + bbox.yMaximum()) / 2.0
        if offsets is not None:
            cx += offsets[i][0]
            cy += offsets[i][1]
        grid[(int(cx // cell_size), int(cy // cell_size))].append(i)
    return grid


def _iter_nearby_pairs(grid):
    """Yield unique (i, j) pairs from neighboring grid cells."""
    visited = set()
    for (gx, gy), indices in grid.items():
        neighbors = []
        for dx_off in (-1, 0, 1):
            for dy_off in (-1, 0, 1):
                key = (gx + dx_off, gy + dy_off)
                if key in grid:
                    neighbors.extend(grid[key])
        for i in indices:
            for j in neighbors:
                if i < j and (i, j) not in visited:
                    visited.add((i, j))
                    yield i, j


def _max_geom_extent(geometries):
    """Return max bounding box dimension across all geometries."""
    max_extent = 0.0
    for geom in geometries:
        bbox = geom.boundingBox()
        extent = max(bbox.width(), bbox.height())
        if extent > max_extent:
            max_extent = extent
    return max_extent


class ArrangeFeaturesAlgorithm(TesseraAlgorithm):
    """Arrange features via geometric overlap resolution or force-directed
    attraction."""

    def name(self):
        return 'arrange_features'

    def displayName(self):
        return 'Arrange Features'

    def group(self):
        return 'Layout'

    def groupId(self):
        return 'layout'

    def shortHelpString(self):
        return (
            '<p><b>Arrange Features</b> repositions features to resolve overlaps or compact clusters. '
            'Designed to follow <b>Scale by Value</b> or <b>Replace with Shape</b>.</p>'

            '<h3>Modes</h3>'
            '<ul>'
            '<li><b>Separate:</b> Detect and resolve actual polygon overlaps using geometric intersection checks. '
            'Features are pushed away from the overlap zone until no intersections remain.</li>'
            '<li><b>Attract:</b> Pull features together while preventing overlaps (force-directed, compact clustering)</li>'
            '<li><b>Separate with gap:</b> Like Separate, plus enforces a minimum gap between feature boundaries</li>'
            '</ul>'

            '<h3>How Separate / Gap Modes Work</h3>'
            '<p>These modes use <b>geometric overlap detection</b>: a spatial grid filters candidate pairs by bounding box, '
            'then <code>intersects()</code> checks confirm actual polygon overlap. Each overlapping feature is pushed away '
            'from the centroid of the intersection geometry. This handles concave and irregular shapes accurately. '
            'The algorithm iterates until no overlaps remain or the maximum iteration count is reached.</p>'

            '<h3>How Attract Mode Works</h3>'
            '<p>Uses force-directed simulation with area-equivalent collision radii. Features attract each other when separated '
            'and repel when overlapping. Parameters like damping, anchor strength, and convergence threshold '
            'control the simulation behavior.</p>'

            '<h3>Parameters</h3>'
            '<ul>'
            '<li><b>Mode:</b> Choose layout strategy.</li>'
            '<li><b>Quality:</b> Controls the balance between speed and precision. '
            'Fast (30 iterations, quick results), Balanced (default, 100 iterations), '
            'Precise (500 iterations, best results for dense layouts), '
            'or Custom advanced parameters (uses the values from the collapsed section below).</li>'
            '<li><b>Separation distance:</b> (Separate with gap only) Minimum boundary gap in map units.</li>'
            '<li><b>Force engineering CRS:</b> Output in flat Cartesian meters instead of source CRS.</li>'
            '</ul>'

            '<h3>Custom Advanced Parameters</h3>'
            '<ul>'
            '<li><b>Damping factor:</b> Force damping (0.01-1.0). Default 0.1.</li>'
            '<li><b>Anchor strength:</b> Pull toward original position (0.0-1.0). Default 0.01.</li>'
            '<li><b>Convergence threshold:</b> Stop when displacement drops below this fraction of mean radius.</li>'
            '<li><b>Adaptive damping:</b> Reduce force over time to prevent oscillation.</li>'
            '</ul>'

            '<h3>CRS Behavior</h3>'
            '<p>Output preserves source CRS by default. Enable <b>Force engineering CRS</b> '
            'for flat Cartesian output (meters).</p>'

            '<h3>Tips</h3>'
            '<ul>'
            '<li><b>Dorling cartograms:</b> Replace with Shape (circles) → Arrange Features (Separate).</li>'
            '<li><b>Compact clusters:</b> Attract mode with low anchor strength.</li>'
            '<li><b>Spaced layouts:</b> Separate with gap, distance = 5-10% of feature size.</li>'
            '<li>If overlaps remain, increase Maximum iterations.</li>'
            '<li>For grid layouts, use the <b>Grid Arrangement</b> algorithm instead.</li>'
            '</ul>'
        )

    def output_layer_name(self):
        return 'Arranged features'

    def createInstance(self):
        return ArrangeFeaturesAlgorithm()

    def initAlgorithm(self, config=None):
        """Define parameters: INPUT, OUTPUT (from base) + mode + force options."""
        super().initAlgorithm(config)

        # --- Mode (first, so user picks strategy before seeing options) ---
        self.addParameter(
            QgsProcessingParameterEnum(
                'MODE',
                'Mode',
                options=['Separate', 'Attract', 'Separate with gap'],
                defaultValue=0,
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                'QUALITY',
                'Quality (advanced parameters presets)',
                options=_QUALITY_OPTIONS,
                defaultValue=_QUALITY_BALANCED,
            )
        )

        separation_param = QgsProcessingParameterNumber(
            'SEPARATION_DISTANCE',
            'Separation distance (Separate with gap mode, map units)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.0,
            minValue=0.0,
        )
        self.addParameter(separation_param)

        self.addParameter(
            QgsProcessingParameterBoolean(
                'FORCE_ENGINEERING_CRS',
                'Force engineering CRS (flat Cartesian output)',
                defaultValue=False,
            )
        )

        # --- Custom advanced parameters (Quality = "Custom advanced parameters") ---
        iterations_param = QgsProcessingParameterNumber(
            'ITERATIONS',
            'Maximum iterations',
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=100,
            minValue=1,
            maxValue=1000,
        )
        iterations_param.setFlags(
            iterations_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced
        )
        self.addParameter(iterations_param)

        damping_param = QgsProcessingParameterNumber(
            'DAMPING',
            'Damping factor',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.1,
            minValue=0.01,
            maxValue=1.0,
        )
        damping_param.setFlags(
            damping_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced
        )
        self.addParameter(damping_param)

        anchor_param = QgsProcessingParameterNumber(
            'ANCHOR_STRENGTH',
            'Anchor strength',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.01,
            minValue=0.0,
            maxValue=1.0,
        )
        anchor_param.setFlags(
            anchor_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced
        )
        self.addParameter(anchor_param)

        convergence_param = QgsProcessingParameterNumber(
            'CONVERGENCE_THRESHOLD',
            'Convergence threshold',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.01,
            minValue=0.0,
            maxValue=1.0,
        )
        convergence_param.setFlags(
            convergence_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced
        )
        self.addParameter(convergence_param)

        adaptive_param = QgsProcessingParameterBoolean(
            'ADAPTIVE_DAMPING',
            'Adaptive damping',
            defaultValue=True,
        )
        adaptive_param.setFlags(
            adaptive_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced
        )
        self.addParameter(adaptive_param)

    def get_output_fields(self, source, parameters=None, context=None):
        """Return source fields + _tessera_algorithm, _tessera_parent_fid, _tessera_iteration."""
        return create_output_fields(source.fields(), [
            ('_tessera_algorithm', QMetaType.Type.QString),
            ('_tessera_parent_fid', QMetaType.Type.Int),
            ('_tessera_iteration', QMetaType.Type.Int),
        ])

    def _use_engineering_crs(self, parameters, context):
        """Return True if output should use engineering CRS."""
        return self.parameterAsBool(parameters, 'FORCE_ENGINEERING_CRS', context)

    def _effective_params(self, parameters, context):
        """Read force parameters, applying quality preset if not Custom."""
        quality = self.parameterAsEnum(parameters, 'QUALITY', context)
        if quality in _QUALITY_PRESETS:
            preset = _QUALITY_PRESETS[quality]
            return (
                preset['iterations'],
                preset['damping'],
                preset['anchor_strength'],
                preset['convergence_threshold'],
                preset['adaptive_damping'],
            )
        return (
            self.parameterAsInt(parameters, 'ITERATIONS', context),
            self.parameterAsDouble(parameters, 'DAMPING', context),
            self.parameterAsDouble(parameters, 'ANCHOR_STRENGTH', context),
            self.parameterAsDouble(parameters, 'CONVERGENCE_THRESHOLD', context),
            self.parameterAsBool(parameters, 'ADAPTIVE_DAMPING', context),
        )

    def processAlgorithm(self, parameters, context, feedback):
        """Override base to support engineering CRS output."""
        source = self.parameterAsSource(parameters, 'INPUT', context)
        output_fields = self.get_output_fields(source, parameters, context)
        force_eng = self.parameterAsBool(parameters, 'FORCE_ENGINEERING_CRS', context)

        if force_eng:
            output_crs = create_engineering_crs()
        else:
            output_crs = source.sourceCrs()

        working_crs = WorkingCRS(
            source.sourceCrs(), source.sourceExtent(), self.crs_strategy
        )

        (sink, dest_id) = self.parameterAsSink(
            parameters, 'OUTPUT', context,
            output_fields, QgsWkbTypes.MultiPolygon, output_crs,
        )

        topology = None
        self.run_algorithm(
            source, parameters, context, working_crs, topology, sink, feedback,
        )

        return {'OUTPUT': dest_id}

    def run_algorithm(self, source, parameters, context, working_crs,
                      topology, sink, feedback):
        """Execute overlap resolution or force-directed attract."""
        mode = self.parameterAsEnum(parameters, 'MODE', context)
        use_eng = self._use_engineering_crs(parameters, context)

        if mode == 1:  # attract — force-directed
            self._run_force_directed(
                source, parameters, context, working_crs, sink, feedback,
                mode, skip_inverse=use_eng)
            return

        # modes 0 (separate), 2 (separate_with_gap) — geometric resolution
        self._run_geometric_separation(
            source, parameters, context, working_crs, sink, feedback,
            mode, skip_inverse=use_eng)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _collect_working_geometries(self, source, working_crs,
                                    output_fields, sink, feedback):
        """Transform source features to working CRS and explode multiparts.

        Empty/null geometries and features that produce empty working-CRS
        geometries are written directly to *sink* with iteration 0.

        Returns
        -------
        features : list[QgsFeature]
            Original features (for attribute passthrough).
        work_geoms : list[QgsGeometry]
            Single-part working-CRS geometries.
        canceled : bool
            True if feedback was canceled during iteration.
        """
        features = []
        work_geoms = []
        for feature in source.getFeatures():
            if feedback.isCanceled():
                return features, work_geoms, True

            geom = feature.geometry()
            if geom.isEmpty() or geom.isNull():
                out_feat = build_feature(
                    geom, feature, 'arrange_features',
                    {'_tessera_iteration': 0}, output_fields,
                )
                sink.addFeatures([out_feat])
                continue

            work_geom = working_crs.forward(geom)
            if work_geom.isEmpty():
                out_feat = build_feature(
                    geom, feature, 'arrange_features',
                    {'_tessera_iteration': 0}, output_fields,
                )
                sink.addFeatures([out_feat])
                continue

            parts = work_geom.asGeometryCollection()
            if len(parts) <= 1:
                features.append(feature)
                work_geoms.append(work_geom)
            else:
                for part in parts:
                    if part.isEmpty() or part.area() <= 0:
                        continue
                    multi_part = QgsGeometry.collectGeometry([part])
                    features.append(feature)
                    work_geoms.append(multi_part)

        return features, work_geoms, False

    @staticmethod
    def _write_single_or_empty(features, work_geoms, working_crs,
                               skip_inverse, output_fields, sink):
        """Write features when n <= 1 (nothing to separate)."""
        for i in range(len(features)):
            work_geom = QgsGeometry(work_geoms[i])
            if skip_inverse:
                out_geom = work_geom
            else:
                out_geom = working_crs.inverse(work_geom)
            out_feat = build_feature(
                out_geom, features[i], 'arrange_features',
                {'_tessera_iteration': 0}, output_fields)
            sink.addFeatures([out_feat])

    @staticmethod
    def _build_output_geometries(work_geoms, total_displacements,
                                 working_crs, skip_inverse):
        """Translate work geometries by total displacement and inverse-transform.

        Returns
        -------
        list[QgsGeometry]
            Output geometries in source CRS (or working CRS if skip_inverse).
        """
        out_geoms = []
        for i in range(len(work_geoms)):
            work_geom = QgsGeometry(work_geoms[i])
            work_geom.translate(total_displacements[i][0],
                                total_displacements[i][1])
            if skip_inverse:
                out_geoms.append(work_geom)
            else:
                out_geoms.append(working_crs.inverse(work_geom))
        return out_geoms

    @staticmethod
    def _write_output_features(out_geoms, features, final_iteration,
                               output_fields, sink, feedback):
        """Write final output features to the sink."""
        for i in range(len(out_geoms)):
            if feedback.isCanceled():
                return
            out_feat = build_feature(
                out_geoms[i],
                features[i],
                'arrange_features',
                {'_tessera_iteration': final_iteration},
                output_fields,
            )
            sink.addFeatures([out_feat])

    # ------------------------------------------------------------------
    # Geometric separation
    # ------------------------------------------------------------------

    def _run_geometric_separation(self, source, parameters, context,
                                   working_crs, sink, feedback, mode,
                                   skip_inverse=False):
        """Resolve overlaps using actual geometry intersection detection.

        Two-phase approach:
        1. Main loop in working CRS (equal-area): spatial grid + bbox
           pre-filter + precise intersects() check. Pushes overlapping
           pairs apart along centroid-to-centroid axis with magnitude
           sqrt(intersection_area). Overlap-count averaging prevents
           cascade in dense areas.
        2. Refinement pass in source CRS: the equal-area projection
           round-trip can reintroduce overlaps. A brute-force O(n^2)
           refinement pass on the output geometries resolves residuals
           directly in the source coordinate system.

        For gap mode (mode 2), also enforces minimum separation distance
        between boundaries using QgsGeometry.distance().
        """
        max_iterations, _, _, _, _ = self._effective_params(parameters, context)
        separation_distance = self.parameterAsDouble(
            parameters, 'SEPARATION_DISTANCE', context
        )
        gap = separation_distance if mode == 2 else 0.0
        output_fields = self.get_output_fields(source)

        features, work_geoms, canceled = self._collect_working_geometries(
            source, working_crs, output_fields, sink, feedback)
        if canceled:
            return

        n = len(features)
        if n == 0:
            return

        centroids = [[pt.x(), pt.y()] for wg in work_geoms
                     for pt in [wg.centroid().asPoint()]]
        total_displacements = [[0.0, 0.0] for _ in range(n)]

        if n <= 1:
            self._write_single_or_empty(
                features, work_geoms, working_crs, skip_inverse,
                output_fields, sink)
            return

        final_iteration = self._iterate_geometric_resolution(
            features, work_geoms, centroids, total_displacements,
            max_iterations, gap, feedback)
        if final_iteration is None:
            return  # canceled

        out_geoms = self._build_output_geometries(
            work_geoms, total_displacements, working_crs, skip_inverse)

        if not skip_inverse:
            refinement_iters = self._refine_in_source_crs(
                out_geoms, max_iterations, feedback)
            if refinement_iters is None:
                return  # canceled
            final_iteration += refinement_iters

        remaining = self._count_source_crs_overlaps(out_geoms)
        if remaining > 0:
            feedback.pushWarning(
                f'Arrange Features: {remaining} overlapping pair(s) '
                f'remain after {final_iteration} iteration(s).'
            )

        self._write_output_features(
            out_geoms, features, final_iteration, output_fields,
            sink, feedback)

    def _iterate_geometric_resolution(self, features, work_geoms, centroids,
                                      total_displacements, max_iterations,
                                      gap, feedback):
        """Run the iterative spatial-grid overlap resolution loop.

        Detects overlaps (and gap violations) via spatial grid + bbox
        pre-filter + precise intersects() check, then pushes pairs apart
        along the centroid-to-centroid axis.

        Returns
        -------
        int or None
            Final iteration count, or None if canceled.
        """
        n = len(features)
        final_iteration = 0

        for iteration in range(max_iterations):
            if feedback.isCanceled():
                return None

            # Build translated geometries for this iteration
            translated = []
            for i in range(n):
                gi = QgsGeometry(work_geoms[i])
                gi.translate(total_displacements[i][0],
                             total_displacements[i][1])
                translated.append(gi)

            # Build spatial grid from bounding boxes
            max_extent = 0.0
            for gi in translated:
                bbox = gi.boundingBox()
                extent = max(bbox.width(), bbox.height())
                if extent > max_extent:
                    max_extent = extent
            cell_size = max_extent + gap if max_extent > 0 else 1.0

            grid = defaultdict(list)
            for i in range(n):
                bbox = translated[i].boundingBox()
                cx = (bbox.xMinimum() + bbox.xMaximum()) / 2.0
                cy = (bbox.yMinimum() + bbox.yMaximum()) / 2.0
                gx = int(cx // cell_size)
                gy = int(cy // cell_size)
                grid[(gx, gy)].append(i)

            # Find overlapping/too-close pairs and compute displacements
            displacements = [[0.0, 0.0] for _ in range(n)]
            overlap_counts = [0] * n
            any_violation = False
            visited = set()

            for (gx, gy), indices in grid.items():
                neighbors = []
                for dx_off in (-1, 0, 1):
                    for dy_off in (-1, 0, 1):
                        key = (gx + dx_off, gy + dy_off)
                        if key in grid:
                            neighbors.extend(grid[key])

                for i in indices:
                    for j in neighbors:
                        if i >= j:
                            continue
                        pair = (i, j)
                        if pair in visited:
                            continue
                        visited.add(pair)

                        gi = translated[i]
                        gj = translated[j]

                        # Bounding box pre-filter
                        bi = gi.boundingBox()
                        bj = gj.boundingBox()
                        if gap > 0:
                            bi.grow(gap)
                        if not bi.intersects(bj):
                            continue

                        # --- Overlap check: actual geometry intersection ---
                        if gi.intersects(gj):
                            intersection = gi.intersection(gj)
                            if intersection.isEmpty():
                                continue
                            inter_area = intersection.area()
                            if inter_area <= 0:
                                continue

                            # Push direction: centroid-to-centroid axis.
                            # Robust for all polygon shapes including
                            # those with holes (e.g. South Africa/Lesotho).
                            ci = gi.centroid().asPoint()
                            cj = gj.centroid().asPoint()
                            dx_ij = cj.x() - ci.x()
                            dy_ij = cj.y() - ci.y()
                            dist_ij = math.hypot(dx_ij, dy_ij)

                            if dist_ij > 0:
                                dir_x = dx_ij / dist_ij
                                dir_y = dy_ij / dist_ij
                            else:
                                dir_x = 1.0
                                dir_y = 0.0

                            # Push magnitude from intersection area.
                            penetration = math.sqrt(inter_area)
                            displacements[i][0] -= dir_x * penetration
                            displacements[i][1] -= dir_y * penetration
                            displacements[j][0] += dir_x * penetration
                            displacements[j][1] += dir_y * penetration

                            overlap_counts[i] += 1
                            overlap_counts[j] += 1
                            any_violation = True

                        # --- Gap check: boundary distance < separation ---
                        elif gap > 0:
                            actual_dist = gi.distance(gj)
                            if actual_dist < gap:
                                deficit = gap - actual_dist
                                ci = gi.centroid().asPoint()
                                cj = gj.centroid().asPoint()
                                dx_ij = cj.x() - ci.x()
                                dy_ij = cj.y() - ci.y()
                                dist_ij = math.hypot(dx_ij, dy_ij)
                                if dist_ij > 0:
                                    push_dir_x = dx_ij / dist_ij
                                    push_dir_y = dy_ij / dist_ij
                                else:
                                    push_dir_x = 1.0
                                    push_dir_y = 0.0

                                push = deficit * 0.5
                                displacements[i][0] -= push_dir_x * push
                                displacements[i][1] -= push_dir_y * push
                                displacements[j][0] += push_dir_x * push
                                displacements[j][1] += push_dir_y * push
                                overlap_counts[i] += 1
                                overlap_counts[j] += 1
                                any_violation = True

            if not any_violation:
                final_iteration = iteration + 1
                break

            # Divide by overlap count so a feature pushed by N
            # neighbors moves the average, not the sum. This prevents
            # compounding without killing late-game convergence.
            for i in range(n):
                divisor = max(1, overlap_counts[i])
                displacements[i][0] /= divisor
                displacements[i][1] /= divisor

                total_displacements[i][0] += displacements[i][0]
                total_displacements[i][1] += displacements[i][1]
                centroids[i][0] += displacements[i][0]
                centroids[i][1] += displacements[i][1]

            final_iteration = iteration + 1
            feedback.setProgress(int((iteration + 1) / max_iterations * 100))

        return final_iteration

    @staticmethod
    def _refine_in_source_crs(out_geoms, max_iterations, feedback):
        """Spatial-indexed refinement pass in source CRS.

        The equal-area CRS round-trip can reintroduce overlaps. This pass
        resolves residuals directly on the output geometries.

        Returns
        -------
        int or None
            Number of refinement iterations performed, or None if canceled.
        """
        n = len(out_geoms)
        max_refine = max_iterations // 2
        refine_iter = 0
        cell_size = _max_geom_extent(out_geoms)
        if cell_size <= 0:
            cell_size = 1.0

        for refine_iter in range(max_refine):
            if feedback.isCanceled():
                return None
            any_refine = False
            displacements = [[0.0, 0.0] for _ in range(n)]
            overlap_counts = [0] * n

            grid = _build_spatial_grid(out_geoms, cell_size)
            for i, j in _iter_nearby_pairs(grid):
                gi = out_geoms[i]
                gj = out_geoms[j]
                if not gi.boundingBox().intersects(gj.boundingBox()):
                    continue
                if not gi.intersects(gj):
                    continue
                inter = gi.intersection(gj)
                if inter.isEmpty():
                    continue
                ia = inter.area()
                if ia <= 0:
                    continue

                ci = gi.centroid().asPoint()
                cj = gj.centroid().asPoint()
                dx = cj.x() - ci.x()
                dy = cj.y() - ci.y()
                dist = math.hypot(dx, dy)
                if dist > 0:
                    dir_x = dx / dist
                    dir_y = dy / dist
                else:
                    dir_x = 1.0
                    dir_y = 0.0

                push = math.sqrt(ia)
                displacements[i][0] -= dir_x * push
                displacements[i][1] -= dir_y * push
                displacements[j][0] += dir_x * push
                displacements[j][1] += dir_y * push
                overlap_counts[i] += 1
                overlap_counts[j] += 1
                any_refine = True

            if not any_refine:
                break

            for i in range(n):
                divisor = max(1, overlap_counts[i])
                dx = displacements[i][0] / divisor
                dy = displacements[i][1] / divisor
                out_geoms[i].translate(dx, dy)

        if max_refine > 0:
            return refine_iter + 1
        return 0

    @staticmethod
    def _count_source_crs_overlaps(out_geoms):
        """Count remaining overlaps among output geometries in source CRS."""
        n = len(out_geoms)
        if n == 0:
            return 0
        cell_size = _max_geom_extent(out_geoms)
        if cell_size <= 0:
            cell_size = 1.0

        remaining = 0
        grid = _build_spatial_grid(out_geoms, cell_size)
        for i, j in _iter_nearby_pairs(grid):
            if out_geoms[i].intersects(out_geoms[j]):
                inter = out_geoms[i].intersection(out_geoms[j])
                if not inter.isEmpty() and inter.area() > 0:
                    remaining += 1
        return remaining

    # ------------------------------------------------------------------
    # Force-directed layout
    # ------------------------------------------------------------------

    def _run_force_directed(self, source, parameters, context,
                            working_crs, sink, feedback, mode,
                            skip_inverse=False):
        """Execute force-directed overlap resolution."""
        (max_iterations, damping, anchor_strength,
         convergence_threshold, adaptive_damping) = self._effective_params(
            parameters, context)
        separation_distance = self.parameterAsDouble(
            parameters, 'SEPARATION_DISTANCE', context
        )
        output_fields = self.get_output_fields(source)

        features, work_geoms, canceled = self._collect_working_geometries(
            source, working_crs, output_fields, sink, feedback)
        if canceled:
            return

        n = len(features)
        if n == 0:
            return

        centroids, original_centroids, radii = self._compute_force_parameters(
            work_geoms)

        if feedback.isCanceled():
            return

        total_displacements = [[0.0, 0.0] for _ in range(n)]
        force_config = self._configure_force_layout(
            radii, work_geoms, mode, separation_distance,
            convergence_threshold)
        force_config['max_iterations'] = max_iterations
        force_config['damping'] = damping
        force_config['anchor_strength'] = anchor_strength
        force_config['adaptive_damping'] = adaptive_damping

        final_iteration = self._iterate_force_directed_loop(
            n, centroids, original_centroids, radii, work_geoms,
            total_displacements, force_config, feedback)
        if final_iteration is None:
            return  # canceled

        # Geometry-based refinement
        if mode == 2 and separation_distance > 0:
            self._refine_gap(
                work_geoms, total_displacements, centroids,
                separation_distance, n, feedback,
            )
            self._refine_overlaps(
                work_geoms, total_displacements, centroids, n, feedback,
            )
        elif mode in (0, 1):
            self._refine_overlaps(
                work_geoms, total_displacements, centroids, n, feedback,
            )

        # Check for remaining overlaps and warn
        gap_for_check = separation_distance if mode == 2 else 0.0
        remaining_overlaps = self._count_remaining_overlaps(
            work_geoms, total_displacements, n, gap_for_check,
        )
        if remaining_overlaps > 0:
            feedback.pushWarning(
                f'Arrange Features: {remaining_overlaps} overlapping pair(s) '
                f'remain after {final_iteration} iteration(s).'
            )

        # Translate geometries and build output
        for i in range(n):
            if feedback.isCanceled():
                return

            work_geom = QgsGeometry(work_geoms[i])
            tdx = total_displacements[i][0]
            tdy = total_displacements[i][1]
            work_geom.translate(tdx, tdy)

            if skip_inverse:
                out_geom = work_geom
            else:
                out_geom = working_crs.inverse(work_geom)

            out_feat = build_feature(
                out_geom,
                features[i],
                'arrange_features',
                {'_tessera_iteration': final_iteration},
                output_fields,
            )
            sink.addFeatures([out_feat])

    @staticmethod
    def _compute_force_parameters(work_geoms):
        """Compute centroids and area-equivalent collision radii.

        Returns
        -------
        centroids : list[list[float, float]]
            Mutable current centroid positions.
        original_centroids : list[tuple[float, float]]
            Immutable original centroid positions (for anchor force).
        radii : list[float]
            Area-equivalent circle radii.
        """
        centroids = []
        original_centroids = []
        radii = []

        for work_geom in work_geoms:
            centroid_geom = work_geom.centroid()
            centroid_pt = centroid_geom.asPoint()
            cx, cy = centroid_pt.x(), centroid_pt.y()
            centroids.append([cx, cy])
            original_centroids.append((cx, cy))

            # Collision radius: area-equivalent circle radius.
            # sqrt(area / pi) gives the radius of a circle with the
            # same area as the polygon -- much tighter than MEC for
            # elongated or irregular shapes.
            area = work_geom.area()
            radius = math.sqrt(area / math.pi) if area > 0 else 0.0
            radii.append(radius)

        return centroids, original_centroids, radii

    @staticmethod
    def _configure_force_layout(radii, work_geoms, mode,
                                separation_distance,
                                convergence_threshold):
        """Compute force-directed layout configuration from geometry stats.

        Returns
        -------
        dict
            Configuration with keys: convergence_limit, max_radius,
            max_half_diag, gap, displacement_clamp, use_brute_force,
            attract_cell_size, use_attract.
        """
        n = len(radii)
        max_radius = max(radii) if radii else 1.0
        mean_radius = sum(radii) / n if n > 0 else 1.0
        convergence_limit = convergence_threshold * mean_radius

        # Maximum half-diagonal across all features. For elongated shapes
        # this can be much larger than the area-equivalent radius, and is
        # needed so the spatial grid cells are wide enough to find all
        # potentially overlapping neighbours.
        max_half_diag = 0.0
        for wg in work_geoms:
            bbox = wg.boundingBox()
            half_diag = math.hypot(bbox.width(), bbox.height()) / 2.0
            if half_diag > max_half_diag:
                max_half_diag = half_diag

        # mode 0 = separate, 1 = attract, 2 = separate_with_gap
        use_attract = (mode == 1)
        gap = separation_distance if mode == 2 else 0.0
        displacement_clamp = 2.0 * max_radius if use_attract else float('inf')

        # Attract mode: brute-force for small N, spatial grid for large N
        use_brute_force = use_attract and n <= _BRUTE_FORCE_THRESHOLD
        attract_cell_size = 4.0 * max(max_radius, max_half_diag) if use_attract else 2.0 * max(max_radius, max_half_diag)

        return {
            'convergence_limit': convergence_limit,
            'max_radius': max_radius,
            'max_half_diag': max_half_diag,
            'gap': gap,
            'displacement_clamp': displacement_clamp,
            'use_brute_force': use_brute_force,
            'attract_cell_size': attract_cell_size,
            'use_attract': use_attract,
        }

    def _iterate_force_directed_loop(self, n, centroids, original_centroids,
                                     radii, work_geoms, total_displacements,
                                     config, feedback):
        """Run the iterative force-directed simulation loop.

        Returns
        -------
        int or None
            Final iteration count, or None if canceled.
        """
        max_iterations = config['max_iterations']
        damping = config['damping']
        anchor_strength = config['anchor_strength']
        adaptive_damping = config['adaptive_damping']
        convergence_limit = config['convergence_limit']
        max_radius = config['max_radius']
        max_half_diag = config['max_half_diag']
        gap = config['gap']
        displacement_clamp = config['displacement_clamp']
        use_brute_force = config['use_brute_force']
        attract_cell_size = config['attract_cell_size']
        use_attract = config['use_attract']

        final_iteration = 0
        for iteration in range(max_iterations):
            if feedback.isCanceled():
                return None

            # Compute effective damping
            if adaptive_damping:
                eta = damping / (1.0 + iteration / (max_iterations / 3.0))
            else:
                eta = damping

            # Compute displacements
            displacements = [[0.0, 0.0] for _ in range(n)]

            if use_brute_force:
                # Brute-force all pairs (attract mode, small N)
                for i in range(n):
                    for j in range(i + 1, n):
                        self._compute_pair_force(
                            i, j, centroids, radii, eta, gap,
                            use_attract, displacements,
                        )
            else:
                # Spatial grid acceleration
                cell_size = attract_cell_size if use_attract else 2.0 * max(max_radius, max_half_diag)
                if cell_size <= 0:
                    cell_size = 1.0

                grid = defaultdict(list)
                for i in range(n):
                    gx = int(centroids[i][0] // cell_size)
                    gy = int(centroids[i][1] // cell_size)
                    grid[(gx, gy)].append(i)

                visited_pairs = set()
                for (gx, gy), indices in grid.items():
                    neighbors = []
                    for dx_off in (-1, 0, 1):
                        for dy_off in (-1, 0, 1):
                            key = (gx + dx_off, gy + dy_off)
                            if key in grid:
                                neighbors.extend(grid[key])
                    neighbor_set = set(neighbors)

                    for i in indices:
                        for j in neighbor_set:
                            if i >= j:
                                continue
                            pair_key = (i, j)
                            if pair_key in visited_pairs:
                                continue
                            visited_pairs.add(pair_key)

                            self._compute_pair_force(
                                i, j, centroids, radii, eta, gap,
                                use_attract, displacements,
                            )

            # Apply anchor pull, clamp, and update centroids
            max_disp_mag = 0.0
            for i in range(n):
                anchor_dx = (
                    (original_centroids[i][0] - centroids[i][0]) * anchor_strength
                )
                anchor_dy = (
                    (original_centroids[i][1] - centroids[i][1]) * anchor_strength
                )
                displacements[i][0] += anchor_dx
                displacements[i][1] += anchor_dy

                # Clamp displacement magnitude (prevent oscillation in attract mode)
                disp_mag = math.hypot(displacements[i][0], displacements[i][1])
                if disp_mag > displacement_clamp:
                    scale = displacement_clamp / disp_mag
                    displacements[i][0] *= scale
                    displacements[i][1] *= scale
                    disp_mag = displacement_clamp

                centroids[i][0] += displacements[i][0]
                centroids[i][1] += displacements[i][1]

                total_displacements[i][0] += displacements[i][0]
                total_displacements[i][1] += displacements[i][1]

                if disp_mag > max_disp_mag:
                    max_disp_mag = disp_mag

            final_iteration = iteration + 1

            if max_disp_mag < convergence_limit:
                break

            feedback.setProgress(int((iteration + 1) / max_iterations * 100))

        return final_iteration

    @staticmethod
    def _compute_pair_force(i, j, centroids, radii, eta, gap,
                            use_attract, displacements):
        """Compute and accumulate force between feature pair (i, j).

        Parameters
        ----------
        i, j : int
            Feature indices.
        centroids : list[list[float, float]]
            Current centroid positions.
        radii : list[float]
            Collision radii.
        eta : float
            Effective damping for this iteration.
        gap : float
            Separation distance (only for gap mode, 0 otherwise).
        use_attract : bool
            Whether to apply attractive force when separated.
        displacements : list[list[float, float]]
            Accumulated displacements (modified in-place).
        """
        dx = centroids[j][0] - centroids[i][0]
        dy = centroids[j][1] - centroids[i][1]
        distance = math.hypot(dx, dy)
        target_dist = radii[i] + radii[j] + gap

        if distance > 0:
            dir_x = dx / distance
            dir_y = dy / distance
        else:
            dir_x = 1.0
            dir_y = 0.0

        if distance < target_dist:
            # Repulsive: push apart
            overlap = target_dist - distance
            push = overlap * eta / 2.0
            displacements[i][0] -= dir_x * push
            displacements[i][1] -= dir_y * push
            displacements[j][0] += dir_x * push
            displacements[j][1] += dir_y * push
        elif use_attract and distance > target_dist:
            # Attractive: pull together (attract mode only)
            pull_magnitude = (distance - target_dist) * eta / 2.0
            displacements[i][0] += dir_x * pull_magnitude
            displacements[i][1] += dir_y * pull_magnitude
            displacements[j][0] -= dir_x * pull_magnitude
            displacements[j][1] -= dir_y * pull_magnitude

    @staticmethod
    def _count_remaining_overlaps(work_geoms, total_displacements, n, gap):
        """Count remaining overlaps using actual geometry intersection.

        For gap mode (gap > 0), counts pairs closer than gap distance.
        For other modes, counts pairs that actually intersect with
        non-zero area (shared edges/points are not counted).
        """
        if n == 0:
            return 0
        cell_size = _max_geom_extent(work_geoms) + gap
        if cell_size <= 0:
            cell_size = 1.0

        remaining = 0
        grid = _build_spatial_grid(work_geoms, cell_size,
                                   offsets=total_displacements)
        for i, j in _iter_nearby_pairs(grid):
            gi = QgsGeometry(work_geoms[i])
            gi.translate(total_displacements[i][0],
                         total_displacements[i][1])
            gj = QgsGeometry(work_geoms[j])
            gj.translate(total_displacements[j][0],
                         total_displacements[j][1])

            if gap > 0:
                if gi.distance(gj) < gap:
                    remaining += 1
            else:
                if gi.intersects(gj):
                    inter = gi.intersection(gj)
                    if not inter.isEmpty() and inter.area() > 0:
                        remaining += 1
        return remaining

    @staticmethod
    def _refine_pairwise(work_geoms, total_displacements, centroids,
                         cell_size, evaluate_pair, converged_fn, feedback):
        """Common pairwise refinement loop using spatial grid.

        Args:
            work_geoms: List of QgsGeometry (untranslated base geometries).
            total_displacements: List of [dx, dy] accumulated offsets.
            centroids: List of [cx, cy] current centroid positions.
            cell_size: Spatial grid cell size.
            evaluate_pair: Callable(gi, gj) -> push_amount or None.
                Returns the push magnitude for the pair, or None to skip.
            converged_fn: Callable(max_correction, had_any) -> bool.
                Returns True when the iteration should stop.
            feedback: QgsProcessingFeedback.
        """
        if cell_size <= 0:
            cell_size = 1.0

        for _refine_iter in range(_MAX_REFINEMENT_ITERATIONS):
            if feedback.isCanceled():
                return

            max_correction = 0.0
            had_any = False
            grid = _build_spatial_grid(work_geoms, cell_size,
                                       offsets=total_displacements)
            for i, j in _iter_nearby_pairs(grid):
                gi = QgsGeometry(work_geoms[i])
                gi.translate(total_displacements[i][0],
                             total_displacements[i][1])
                gj = QgsGeometry(work_geoms[j])
                gj.translate(total_displacements[j][0],
                             total_displacements[j][1])

                push = evaluate_pair(gi, gj)
                if push is None or push <= 0:
                    continue

                had_any = True

                # Push apart along centroid-to-centroid direction
                dx = centroids[j][0] - centroids[i][0]
                dy = centroids[j][1] - centroids[i][1]
                dist = math.hypot(dx, dy)
                if dist > 0:
                    dir_x = dx / dist
                    dir_y = dy / dist
                else:
                    dir_x = 1.0
                    dir_y = 0.0

                total_displacements[i][0] -= dir_x * push
                total_displacements[i][1] -= dir_y * push
                total_displacements[j][0] += dir_x * push
                total_displacements[j][1] += dir_y * push

                centroids[i][0] -= dir_x * push
                centroids[i][1] -= dir_y * push
                centroids[j][0] += dir_x * push
                centroids[j][1] += dir_y * push

                if push > max_correction:
                    max_correction = push

            if converged_fn(max_correction, had_any):
                break

    @staticmethod
    def _refine_gap(work_geoms, total_displacements, centroids,
                    separation_distance, n, feedback):
        """Spatial-indexed gap refinement pass.

        After force-directed convergence, measure actual boundary
        distances and push pairs apart until they achieve the
        requested separation_distance.
        """
        cell_size = _max_geom_extent(work_geoms) + separation_distance

        def evaluate_pair(gi, gj):
            deficit = separation_distance - gi.distance(gj)
            return deficit / 2.0 if deficit > 0 else None

        def converged(max_correction, _had_any):
            return max_correction < separation_distance * 0.05

        ArrangeFeaturesAlgorithm._refine_pairwise(
            work_geoms, total_displacements, centroids,
            cell_size, evaluate_pair, converged, feedback,
        )

    @staticmethod
    def _refine_overlaps(work_geoms, total_displacements, centroids,
                         n, feedback):
        """Spatial-indexed overlap refinement for separate mode.

        After the force loop converges using area-equivalent radii,
        check actual polygon boundaries for remaining overlaps and
        push apart any pairs that still intersect.
        """
        cell_size = _max_geom_extent(work_geoms)

        def evaluate_pair(gi, gj):
            if not gi.intersects(gj):
                return None
            intersection = gi.intersection(gj)
            if intersection.isEmpty():
                return None
            # sqrt(area) gives a characteristic length proportional to
            # overlap severity, robust to long-thin sliver intersections.
            inter_area = intersection.area()
            if inter_area <= 0:
                return None
            return math.sqrt(inter_area) * _GENTLE_PUSH_FACTOR

        def converged(_max_correction, had_any):
            return not had_any

        ArrangeFeaturesAlgorithm._refine_pairwise(
            work_geoms, total_displacements, centroids,
            cell_size, evaluate_pair, converged, feedback,
        )
