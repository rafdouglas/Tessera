"""Tessera QGIS plugin entry point."""
from qgis.core import QgsApplication

from .processing_provider import TesseraProvider


class TesseraPlugin:
    """Main plugin class for Tessera."""

    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initGui(self):
        self.provider = TesseraProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
