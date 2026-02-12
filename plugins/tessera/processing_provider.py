"""Tessera Processing provider."""
from qgis.core import QgsProcessingProvider

from .algorithms.percentage_split import PercentageSplitAlgorithm
from .algorithms.replace_with_shape import ReplaceWithShapeAlgorithm
from .algorithms.arrange_features import ArrangeFeaturesAlgorithm
from .algorithms.grid_arrangement import GridArrangementAlgorithm
from .algorithms.scale_by_value import ScaleByValueAlgorithm
from .algorithms.sketchy_borders import SketchyBordersAlgorithm
from .algorithms.snap_to_grid import SnapToGridAlgorithm
from .algorithms.stripe_hatching import StripeHatchingAlgorithm
from .algorithms.tile_fill import TileFillAlgorithm


class TesseraProvider(QgsProcessingProvider):
    """QGIS Processing provider for Tessera algorithms."""

    def id(self):
        return 'tessera'

    def name(self):
        return 'Tessera'

    def loadAlgorithms(self):
        self.addAlgorithm(PercentageSplitAlgorithm())
        self.addAlgorithm(ReplaceWithShapeAlgorithm())
        self.addAlgorithm(ArrangeFeaturesAlgorithm())
        self.addAlgorithm(GridArrangementAlgorithm())
        self.addAlgorithm(ScaleByValueAlgorithm())
        self.addAlgorithm(SketchyBordersAlgorithm())
        self.addAlgorithm(SnapToGridAlgorithm())
        self.addAlgorithm(StripeHatchingAlgorithm())
        self.addAlgorithm(TileFillAlgorithm())
