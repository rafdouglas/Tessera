"""Stripe Hatching Processing provider."""
from qgis.core import QgsProcessingProvider

from .algorithm import StripeHatchingAlgorithm


class StripeHatchingProvider(QgsProcessingProvider):
    """Processing provider for standalone Stripe Hatching plugin."""

    def id(self):
        return 'stripe_hatching'

    def name(self):
        return 'Stripe Hatching'

    def loadAlgorithms(self):
        self.addAlgorithm(StripeHatchingAlgorithm())
