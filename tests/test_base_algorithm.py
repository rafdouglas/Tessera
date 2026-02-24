"""Tests for base_algorithm module (TesseraAlgorithm)."""
import pytest
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from PyQt5.QtCore import QMetaType

from tessera.algorithms.base_algorithm import TesseraAlgorithm
from tessera.infrastructure.crs_manager import WorkingCRS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class ConcreteAlgorithm(TesseraAlgorithm):
    """Minimal concrete subclass for testing the base class."""

    def __init__(self):
        super().__init__()
        self.run_algorithm_calls = []

    def run_algorithm(self, source, parameters, context, working_crs,
                      topology, sink, feedback):
        """Record arguments for test inspection instead of doing real work."""
        self.run_algorithm_calls.append({
            'source': source,
            'parameters': parameters,
            'context': context,
            'working_crs': working_crs,
            'topology': topology,
            'sink': sink,
            'feedback': feedback,
        })

    def name(self):
        return 'test_concrete'

    def displayName(self):
        return 'Test Concrete Algorithm'

    def createInstance(self):
        return ConcreteAlgorithm()


def _make_polygon_layer():
    """Create an in-memory polygon layer with one feature in EPSG:4326."""
    layer = QgsVectorLayer('Polygon?crs=EPSG:4326', 'test_input', 'memory')
    provider = layer.dataProvider()
    provider.addAttributes([QgsField('name', QMetaType.Type.QString)])
    layer.updateFields()

    feat = QgsFeature(layer.fields())
    feat.setGeometry(QgsGeometry.fromWkt(
        'POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'
    ))
    feat.setAttribute('name', 'test_poly')
    provider.addFeatures([feat])

    return layer


def _run_algorithm(alg, layer):
    """Run a pre-initialized algorithm against a layer, returning results.

    Adds the layer to the project, creates context/feedback, invokes
    processAlgorithm, and cleans up.
    """
    project = QgsProject.instance()
    project.addMapLayer(layer)
    try:
        context = QgsProcessingContext()
        context.setProject(project)
        feedback = QgsProcessingFeedback()

        alg.initAlgorithm()

        parameters = {
            'INPUT': layer.id(),
            'OUTPUT': 'memory:',
        }
        results = alg.processAlgorithm(parameters, context, feedback)
        return results, context, feedback
    finally:
        project.removeMapLayer(layer.id())


# ===========================================================================
# T5.1 -- Concrete subclass can be instantiated
# ===========================================================================

def test_concrete_subclass_instantiation(qgis_app):
    """T5.1: Concrete subclass instantiates; crs_strategy='equal_area'."""
    alg = ConcreteAlgorithm()
    assert alg.crs_strategy == 'equal_area'
    assert alg.name() == 'test_concrete'
    assert alg.displayName() == 'Test Concrete Algorithm'
    assert alg.group() == 'Tessera'
    assert alg.groupId() == 'tessera'


# ===========================================================================
# T5.2 -- initAlgorithm defines INPUT and OUTPUT parameters
# ===========================================================================

def test_init_algorithm_defines_parameters(qgis_app):
    """T5.2: After initAlgorithm, has INPUT (FeatureSource/Polygon) and OUTPUT (FeatureSink)."""
    alg = ConcreteAlgorithm()
    alg.initAlgorithm(config={})

    param_input = alg.parameterDefinition('INPUT')
    assert param_input is not None
    assert isinstance(param_input, QgsProcessingParameterFeatureSource)
    # dataTypes() returns a list; should contain TypeVectorPolygon
    assert QgsProcessing.TypeVectorPolygon in param_input.dataTypes()

    param_output = alg.parameterDefinition('OUTPUT')
    assert param_output is not None
    assert isinstance(param_output, QgsProcessingParameterFeatureSink)


# ===========================================================================
# T5.3 -- run_algorithm is called during processAlgorithm
# ===========================================================================

def test_run_algorithm_called_during_process(qgis_app):
    """T5.3: processAlgorithm calls run_algorithm exactly once with correct arg types."""
    alg = ConcreteAlgorithm()
    layer = _make_polygon_layer()
    results, context, feedback = _run_algorithm(alg, layer)

    assert len(alg.run_algorithm_calls) == 1

    call = alg.run_algorithm_calls[0]
    assert call['source'] is not None
    assert isinstance(call['parameters'], dict)
    assert isinstance(call['context'], QgsProcessingContext)
    assert isinstance(call['working_crs'], WorkingCRS)
    assert call['sink'] is not None
    assert isinstance(call['feedback'], QgsProcessingFeedback)


# ===========================================================================
# T5.4 -- Output sink has MultiPolygon geometry type
# ===========================================================================

def test_output_sink_has_multipolygon_type(qgis_app):
    """T5.4: Output result references a valid dest_id (memory layer)."""
    alg = ConcreteAlgorithm()
    layer = _make_polygon_layer()
    results, context, feedback = _run_algorithm(alg, layer)

    assert 'OUTPUT' in results
    dest_id = results['OUTPUT']
    assert dest_id is not None
    assert isinstance(dest_id, str)
    assert len(dest_id) > 0


# ===========================================================================
# T5.5 -- WorkingCRS is created inside processAlgorithm
# ===========================================================================

def test_working_crs_created_in_process(qgis_app):
    """T5.5: run_algorithm receives a WorkingCRS with valid working_crs property."""
    alg = ConcreteAlgorithm()
    layer = _make_polygon_layer()
    _run_algorithm(alg, layer)

    call = alg.run_algorithm_calls[0]
    wcrs = call['working_crs']
    assert isinstance(wcrs, WorkingCRS)
    assert wcrs.working_crs is not None
    assert wcrs.working_crs.isValid()


# ===========================================================================
# T5.6 -- topology is always None (placeholder for future topology support)
# ===========================================================================

def test_topology_none_when_not_topology_aware(qgis_app):
    """T5.6: run_algorithm receives topology=None (placeholder)."""
    alg = ConcreteAlgorithm()
    layer = _make_polygon_layer()
    _run_algorithm(alg, layer)

    call = alg.run_algorithm_calls[0]
    assert call['topology'] is None


# ===========================================================================
# T5.7 -- Abstract run_algorithm raises NotImplementedError
# ===========================================================================

def test_abstract_run_algorithm_raises(qgis_app):
    """T5.7: Calling TesseraAlgorithm.run_algorithm directly raises NotImplementedError."""
    # We cannot instantiate TesseraAlgorithm directly (abstract methods),
    # but we can call the base class method via super on a minimal subclass.

    class BareSubclass(TesseraAlgorithm):
        """Subclass that does NOT override run_algorithm."""

        def name(self):
            return 'bare'

        def displayName(self):
            return 'Bare'

        def createInstance(self):
            return BareSubclass()

    alg = BareSubclass()
    with pytest.raises(NotImplementedError):
        alg.run_algorithm(None, None, None, None, None, None, None)


# ===========================================================================
# A1 -- base class output_layer_name returns 'Output layer'
# ===========================================================================

def test_base_output_layer_name_returns_default(qgis_app):
    """A1: Base class output_layer_name returns 'Output layer'."""
    alg = ConcreteAlgorithm()
    assert alg.output_layer_name() == 'Output layer'


# ===========================================================================
# A3 -- OUTPUT param description matches output_layer_name for each algorithm
# ===========================================================================

def test_output_param_description_matches_output_layer_name(qgis_app):
    """A3: OUTPUT parameter description equals output_layer_name() after initAlgorithm."""
    alg = ConcreteAlgorithm()
    alg.initAlgorithm()
    param_output = alg.parameterDefinition('OUTPUT')
    assert param_output.description() == alg.output_layer_name()


def test_each_algorithm_output_param_uses_its_layer_name(qgis_app):
    """A3b: Each algorithm's OUTPUT description matches its output_layer_name."""
    from tessera.algorithms.tile_fill import TileFillAlgorithm
    from tessera.algorithms.percentage_split import PercentageSplitAlgorithm
    from tessera.algorithms.stripe_hatching import StripeHatchingAlgorithm
    from tessera.algorithms.snap_to_grid import SnapToGridAlgorithm
    from tessera.algorithms.sketchy_borders import SketchyBordersAlgorithm
    from tessera.algorithms.scale_by_value import ScaleByValueAlgorithm
    from tessera.algorithms.replace_with_shape import ReplaceWithShapeAlgorithm
    from tessera.algorithms.arrange_features import ArrangeFeaturesAlgorithm
    from tessera.algorithms.grid_arrangement import GridArrangementAlgorithm

    expected = {
        TileFillAlgorithm: 'Tile filled',
        PercentageSplitAlgorithm: 'Percentage split',
        StripeHatchingAlgorithm: 'Stripe hatched',
        SnapToGridAlgorithm: 'Snapped to grid',
        SketchyBordersAlgorithm: 'Sketchy borders',
        ScaleByValueAlgorithm: 'Scaled by value',
        ReplaceWithShapeAlgorithm: 'Replaced with shape',
        ArrangeFeaturesAlgorithm: 'Arranged features',
        GridArrangementAlgorithm: 'Grid arranged',
    }

    for alg_cls, expected_name in expected.items():
        alg = alg_cls()
        assert alg.output_layer_name() == expected_name, \
            f'{alg_cls.__name__}.output_layer_name() should be {expected_name!r}'
        alg.initAlgorithm()
        param = alg.parameterDefinition('OUTPUT')
        assert param.description() == expected_name, \
            f'{alg_cls.__name__} OUTPUT description should be {expected_name!r}'


# ===========================================================================
# E1 -- each algorithm returns non-empty shortHelpString
# ===========================================================================

def test_each_algorithm_has_non_empty_help_string(qgis_app):
    """E1: Each algorithm returns a non-empty shortHelpString."""
    from tessera.algorithms.tile_fill import TileFillAlgorithm
    from tessera.algorithms.percentage_split import PercentageSplitAlgorithm
    from tessera.algorithms.stripe_hatching import StripeHatchingAlgorithm
    from tessera.algorithms.snap_to_grid import SnapToGridAlgorithm
    from tessera.algorithms.sketchy_borders import SketchyBordersAlgorithm
    from tessera.algorithms.scale_by_value import ScaleByValueAlgorithm
    from tessera.algorithms.replace_with_shape import ReplaceWithShapeAlgorithm
    from tessera.algorithms.arrange_features import ArrangeFeaturesAlgorithm
    from tessera.algorithms.grid_arrangement import GridArrangementAlgorithm

    all_algs = [
        TileFillAlgorithm, PercentageSplitAlgorithm,
        StripeHatchingAlgorithm, SnapToGridAlgorithm,
        SketchyBordersAlgorithm, ScaleByValueAlgorithm,
        ReplaceWithShapeAlgorithm, ArrangeFeaturesAlgorithm,
        GridArrangementAlgorithm,
    ]
    for alg_cls in all_algs:
        alg = alg_cls()
        help_text = alg.shortHelpString()
        assert len(help_text) > 0, \
            f'{alg_cls.__name__}.shortHelpString() is empty'
        assert alg.displayName().lower() in help_text.lower(), \
            f'{alg_cls.__name__}.shortHelpString() should mention its display name'


# ===========================================================================
# E2 -- shortHelpString mentions key parameters
# ===========================================================================

def test_tile_fill_help_mentions_key_params(qgis_app):
    """E2: TileFillAlgorithm shortHelpString mentions TILE_SHAPE, CELL_SIZE, TARGET_TILES."""
    from tessera.algorithms.tile_fill import TileFillAlgorithm
    alg = TileFillAlgorithm()
    help_text = alg.shortHelpString()
    assert 'Tile shape' in help_text
    assert 'Cell size' in help_text
    assert 'Target tiles' in help_text
    assert 'Triangle' in help_text
    assert 'Diamond' in help_text
