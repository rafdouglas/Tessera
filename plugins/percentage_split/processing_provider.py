"""Percentage Split Processing provider."""
from qgis.core import QgsProcessingProvider

from .algorithm import PercentageSplitAlgorithm


class PercentageSplitProvider(QgsProcessingProvider):
    """Processing provider for standalone Percentage Split plugin."""

    def id(self):
        return 'percentage_split'

    def name(self):
        return 'Percentage Split'

    def loadAlgorithms(self):
        self.addAlgorithm(PercentageSplitAlgorithm())
