"""Base class for all Tessera Processing algorithms."""
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsWkbTypes,
)
from ..infrastructure.crs_manager import WorkingCRS
from ..infrastructure.feature_builder import create_output_fields


class TesseraAlgorithm(QgsProcessingAlgorithm):
    """Abstract base for all Tessera algorithms.

    Subclasses must override:
        - name()
        - displayName()
        - createInstance()
        - run_algorithm(source, parameters, context, working_crs, topology, sink, feedback)

    Optionally override:
        - get_output_fields(source) to add _tessera_* columns beyond source fields.

    Class attributes:
        crs_strategy (str): CRS selection strategy passed to WorkingCRS.
    """

    crs_strategy = 'equal_area'

    def output_layer_name(self):
        """Return the description for the OUTPUT parameter.

        Subclasses override to provide algorithm-specific names like
        'Tessellated', 'Scaled by value', etc.
        """
        return 'Output layer'

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
                self.output_layer_name(),
            )
        )

    def get_output_fields(self, source, parameters=None, context=None):
        """Return output fields for the sink.

        Default implementation returns source fields unchanged.
        Subclasses override this to add _tessera_* fields via create_output_fields.
        Parameters and context are passed for algorithms that need them
        to determine conditional fields.
        """
        return source.fields()

    def processAlgorithm(self, parameters, context, feedback):
        """Orchestrate the algorithm: resolve input, create CRS, sink, delegate."""
        # 1. Resolve INPUT source
        source = self.parameterAsSource(parameters, 'INPUT', context)

        # 2. Get output field schema
        output_fields = self.get_output_fields(source, parameters, context)

        # 3. Create WorkingCRS (thread-safe, created per invocation)
        working_crs = WorkingCRS(
            source.sourceCrs(), source.sourceExtent(), self.crs_strategy
        )

        # 4. Create output sink
        (sink, dest_id) = self.parameterAsSink(
            parameters, 'OUTPUT', context,
            output_fields, QgsWkbTypes.MultiPolygon, source.sourceCrs(),
        )

        # 5. Topology placeholder (Phase 3 will populate this)
        topology = None

        # 6. Delegate to subclass implementation
        self.run_algorithm(
            source, parameters, context, working_crs, topology, sink, feedback
        )

        # 7. Return output reference
        return {'OUTPUT': dest_id}

    def run_algorithm(self, source, parameters, context, working_crs,
                      topology, sink, feedback):
        """Execute the algorithm logic -- subclasses must override."""
        raise NotImplementedError(
            'Subclasses must implement run_algorithm()'
        )

    def name(self):
        """Unique algorithm identifier -- subclasses must override."""
        raise NotImplementedError

    def displayName(self):
        """Human-readable algorithm name -- subclasses must override."""
        raise NotImplementedError

    def group(self):
        """Return the algorithm group name."""
        return 'Tessera'

    def groupId(self):
        """Return the algorithm group identifier."""
        return 'tessera'

    def createInstance(self):
        """Return a new instance of this algorithm -- subclasses must override."""
        raise NotImplementedError
