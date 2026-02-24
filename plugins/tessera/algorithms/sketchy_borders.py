"""Sketchy Borders algorithm -- spec section 5.5.

Adds hand-drawn style irregularity to polygon borders using hash-based
vertex displacement through a TopologyTransformer, ensuring that shared
edges between adjacent features remain topologically consistent.
"""
import math

from qgis.core import (
    QgsFeature,
    QgsPointXY,
    QgsProcessingParameterNumber,
)
from PyQt5.QtCore import QMetaType

from ..infrastructure.feature_builder import create_output_fields, build_feature
from ..infrastructure.topology_wrapper import TopologyTransformer
from .base_algorithm import TesseraAlgorithm


# ---------------------------------------------------------------------------
# Module-level helper functions (importable for testing)
# ---------------------------------------------------------------------------

def vertex_hash(vertex_id, seed, component):
    """Deterministic hash producing a float in (0, 1] for a vertex.

    Uses integer mixing with large primes.  The result is clamped to
    a minimum of 1e-10 / 0x7FFFFFFF so that log(u1) never encounters
    log(0).

    Parameters
    ----------
    vertex_id : int
        Unique vertex identifier from TopologyTransformer.
    seed : int
        User-supplied random seed.
    component : int
        0 for the first uniform variate, 1 for the second.

    Returns
    -------
    float
        Value in (0, 1].
    """
    # Knuth multiplicative hash constants (golden-ratio-derived primes)
    # 2654435761 = floor(2^32 / phi), 2246822519 and 3266489917 are large
    # primes chosen for good bit mixing across the three input components.
    h = vertex_id * 2654435761 + seed * 2246822519 + component * 3266489917
    # Finalizer: two rounds of xorshift-multiply (Murmur3-style) to
    # distribute entropy from the upper bits into the lower bits.
    h = ((h >> 16) ^ h) * 0x45d9f3b
    h = ((h >> 16) ^ h) * 0x45d9f3b
    h = (h >> 16) ^ h
    raw = (h & 0x7FFFFFFF) / 0x7FFFFFFF
    # Clamp to avoid log(0) in Box-Muller
    if raw < 1e-10:
        raw = 1e-10
    return raw


def jitter_vertex(point, vertex_id, seed, max_displacement):
    """Apply hash-based Gaussian jitter to a single vertex.

    When *max_displacement* is zero the point is returned unchanged
    (short-circuit for ROUGHNESS=0).

    Parameters
    ----------
    point : QgsPointXY
        Original vertex position.
    vertex_id : int
        Unique vertex identifier.
    seed : int
        User-supplied random seed.
    max_displacement : float
        Maximum displacement distance (3-sigma value).

    Returns
    -------
    QgsPointXY
        Displaced vertex.
    """
    if max_displacement == 0.0:
        return QgsPointXY(point.x(), point.y())

    u1 = vertex_hash(vertex_id, seed, 0)
    u2 = vertex_hash(vertex_id, seed, 1)

    sigma = max_displacement / 3.0  # 3-sigma ~ max_displacement
    dx = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2) * sigma
    dy = math.sqrt(-2.0 * math.log(u1)) * math.sin(2.0 * math.pi * u2) * sigma

    return QgsPointXY(point.x() + dx, point.y() + dy)


# ---------------------------------------------------------------------------
# Algorithm class
# ---------------------------------------------------------------------------

class SketchyBordersAlgorithm(TesseraAlgorithm):
    """Add hand-drawn style irregularity to polygon borders.

    Topology-aware: shared boundaries receive identical jitter so that
    adjacent polygons remain seamlessly connected.
    """

    def name(self):
        return 'sketchy_borders'

    def displayName(self):
        return 'Sketchy Borders'

    def group(self):
        return 'Shape'

    def groupId(self):
        return 'shape'

    def shortHelpString(self):
        return (
            '<p><b>Sketchy Borders</b> adds hand-drawn style irregularity to polygon borders by displacing vertices '
            'with deterministic noise. Creates illustration-style, editorial, or artistic map aesthetics. '
            'Topology-aware: shared boundaries between adjacent features receive identical jitter, maintaining seamless connections.</p>'

            '<h3>Common Use Cases</h3>'
            '<ul>'
            '<li><b>Illustration-style maps:</b> Hand-drawn aesthetic for editorial or infographic maps</li>'
            '<li><b>Sketch aesthetics:</b> Rough, casual look for conceptual or planning maps</li>'
            '<li><b>Editorial cartography:</b> Friendly, approachable style for magazines or blogs</li>'
            '<li><b>Artistic visualization:</b> Non-photorealistic rendering for exhibitions</li>'
            '<li><b>Emphasis through informality:</b> Downplay precision to focus on concepts rather than exact boundaries</li>'
            '</ul>'

            '<h3>Parameters</h3>'
            '<ul>'
            '<li><b>Roughness:</b> Displacement strength from 0.0 to 1.0:'
            '<ul>'
            '<li><i>0.0:</i> No effect (features unchanged)</li>'
            '<li><i>0.2-0.4:</i> Subtle hand-drawn feel (gentle waviness)</li>'
            '<li><i>0.5 (default):</i> Noticeable sketch effect (clear irregularity)</li>'
            '<li><i>0.7-1.0:</i> Strong sketch (highly irregular, exaggerated hand-drawn look)</li>'
            '</ul>'
            'Roughness scales with map extent (1% of smaller extent dimension). Start with 0.3-0.5 for most maps.</li>'

            '<li><b>Densify factor:</b> Controls vertex density before jittering. Higher values add more vertices, '
            'creating finer irregularity. Default 3.0. Range 1.0-20.0:'
            '<ul>'
            '<li><i>1.0-2.0:</i> Sparse (fewer vertices, smoother curves between jitters)</li>'
            '<li><i>3.0-5.0:</i> Balanced (good default for most use cases)</li>'
            '<li><i>10.0+:</i> Dense (very detailed, high-frequency jitter)</li>'
            '</ul>'
            'Higher densify factors increase processing time but produce more detailed sketch effects.</li>'

            '<li><b>Seed:</b> Random seed for deterministic results. Same seed on same data always produces identical output. '
            'Change seed to get a different sketch pattern. Default 42. Use specific seeds for reproducible publication graphics.</li>'

            '<li><b>Smoothing:</b> Chaikin smoothing iterations (0-5) applied after jittering. Softens sharp corners and '
            'produces flowing, organic curves. Default 0 (no smoothing):'
            '<ul>'
            '<li><i>0:</i> Sharp, angular jitter (more "pen-and-ink" feel)</li>'
            '<li><i>1-2:</i> Gentle smoothing (balanced between angular and flowing)</li>'
            '<li><i>3-5:</i> Heavy smoothing (soft, watercolor-like borders)</li>'
            '</ul>'
            'Smoothing works well with lower Densify factor values.</li>'
            '</ul>'

            '<h3>Output Fields</h3>'
            '<ul>'
            '<li>No extra fields beyond standard algorithm (<code>_tessera_algorithm</code>) and parent feature ID (<code>_tessera_parent_fid</code>).</li>'
            '<li>Geometries are jittered; attributes are preserved.</li>'
            '</ul>'

            '<h3>Topology Preservation</h3>'
            '<p>Shared edges between adjacent polygons receive identical displacement, maintaining seamless boundaries. '
            'No gaps or slivers are created. Critical for administrative regions, parcels, or any topology-dependent data.</p>'

            '<h3>Tips and Workflow</h3>'
            '<ul>'
            '<li>For illustration maps, use <b>Roughness = 0.4-0.6</b> with <b>Smoothing = 1-2</b> and soft pastel colors.</li>'

            '<li>Combine with <b>Snap to Grid</b> (low attraction) for a geometric hand-drawn effect.</li>'

            '<li>Use Seed for reproducibility: same seed always gives same result, critical for versioned maps or publications.</li>'

            '<li>Higher Densify factor creates finer detail but increases feature count and processing time.</li>'

            '<li>For subtle effect on large-scale maps, use Roughness = 0.2-0.3.</li>'

            '<li>Apply different Roughness to different layers (e.g., rough borders for water, smoother for land) for visual hierarchy.</li>'

            '<li>Chain with semi-transparent fills and textured backgrounds for watercolor map aesthetics.</li>'

            '<li>If Roughness = 0, the algorithm short-circuits and returns features unchanged (performance optimization).</li>'
            '</ul>'
        )

    def output_layer_name(self):
        return 'Sketchy borders'

    def createInstance(self):
        return SketchyBordersAlgorithm()

    def initAlgorithm(self, config=None):
        """Add INPUT, OUTPUT (from base) plus ROUGHNESS, DENSIFY_FACTOR, SEED."""
        super().initAlgorithm(config)

        self.addParameter(
            QgsProcessingParameterNumber(
                'ROUGHNESS',
                'Roughness',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.5,
                minValue=0.0,
                maxValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'DENSIFY_FACTOR',
                'Densify factor',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=3.0,
                minValue=1.0,
                maxValue=20.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'SEED',
                'Random seed',
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=42,
                minValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'SMOOTHING',
                'Chaikin smoothing iterations (0 = none)',
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=0,
                minValue=0,
                maxValue=5,
            )
        )

    def get_output_fields(self, source, parameters=None, context=None):
        """Return source fields plus _tessera_algorithm and _tessera_parent_fid."""
        return create_output_fields(
            source.fields(),
            [
                ('_tessera_algorithm', QMetaType.Type.QString),
                ('_tessera_parent_fid', QMetaType.Type.Int),
            ],
        )

    def run_algorithm(self, source, parameters, context, working_crs,
                      topology, sink, feedback):
        """Execute Sketchy Borders: densify shared edges then jitter vertices.

        Parameters
        ----------
        source : QgsProcessingFeatureSource
        parameters : dict
        context : QgsProcessingContext
        working_crs : WorkingCRS
        topology : None (created internally)
        sink : QgsFeatureSink
        feedback : QgsProcessingFeedback
        """
        roughness = self.parameterAsDouble(parameters, 'ROUGHNESS', context)
        densify_factor = self.parameterAsDouble(parameters, 'DENSIFY_FACTOR', context)
        seed = self.parameterAsInt(parameters, 'SEED', context)
        smoothing = self.parameterAsInt(parameters, 'SMOOTHING', context)

        output_fields = self.get_output_fields(source)

        # Collect features and transform to working CRS
        raw_features = list(source.getFeatures())
        total = len(raw_features)
        if total == 0:
            return

        # Transform geometries to working CRS
        working_features = []
        for feat in raw_features:
            wf = QgsFeature(feat.fields())
            wf.setAttributes(feat.attributes())
            wf.setId(feat.id())
            geom = feat.geometry()
            if not geom.isNull() and not geom.isEmpty():
                geom = working_crs.forward(geom)
            wf.setGeometry(geom)
            working_features.append(wf)

        # Short-circuit: roughness == 0 -> copy features unchanged
        if roughness == 0.0:
            for i, feat in enumerate(raw_features):
                if feedback and feedback.isCanceled():
                    break
                out_feat = build_feature(
                    feat.geometry(), feat, 'sketchy_borders', {},
                    output_fields,
                )
                sink.addFeature(out_feat)
                if feedback:
                    feedback.setProgress(int((i + 1) / total * 100))
            return

        # Compute max_displacement from extent
        extent = source.sourceExtent()
        # Transform extent corners to working CRS to get working-CRS extent
        from qgis.core import QgsGeometry, QgsRectangle
        extent_geom = QgsGeometry.fromRect(extent)
        extent_geom_working = working_crs.forward(extent_geom)
        working_extent = extent_geom_working.boundingBox()
        extent_width = working_extent.width()
        extent_height = working_extent.height()
        min_dim = min(extent_width, extent_height)
        max_displacement = roughness * 0.01 * min_dim

        # Build TopologyTransformer on working-CRS features
        tt = TopologyTransformer(working_features, feedback)

        # Densify shared edges
        interval = max_displacement * densify_factor
        if interval > 0:
            tt.densify_shared_edges(interval)

        # Build jitter function capturing seed and max_displacement
        def jitter_fn(point, vertex_id):
            return jitter_vertex(point, vertex_id, seed, max_displacement)

        # Transform
        transformed_features = tt.transform(jitter_fn)

        # Apply Chaikin smoothing if requested
        if smoothing > 0:
            for feat in transformed_features:
                geom = feat.geometry()
                if not geom.isNull() and not geom.isEmpty():
                    feat.setGeometry(geom.smooth(smoothing, 0.25))

        # Write output features: transform back to source CRS, build output
        for i, (orig_feat, xformed_feat) in enumerate(
            zip(raw_features, transformed_features)
        ):
            if feedback and feedback.isCanceled():
                break

            geom = xformed_feat.geometry()
            if not geom.isNull() and not geom.isEmpty():
                geom = working_crs.inverse(geom)

            out_feat = build_feature(
                geom, orig_feat, 'sketchy_borders', {},
                output_fields,
            )
            sink.addFeature(out_feat)

            if feedback:
                feedback.setProgress(int((i + 1) / total * 100))
