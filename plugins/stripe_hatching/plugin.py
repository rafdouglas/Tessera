"""Stripe Hatching standalone QGIS plugin."""
from qgis.core import QgsApplication

from .processing_provider import StripeHatchingProvider


class StripeHatchingPlugin:
    """Standalone QGIS plugin for stripe-based hatching patterns."""

    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initGui(self):
        self.provider = StripeHatchingProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
