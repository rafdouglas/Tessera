"""Percentage Split standalone QGIS plugin."""
from qgis.core import QgsApplication

from .processing_provider import PercentageSplitProvider


class PercentageSplitPlugin:
    """Standalone QGIS plugin for percentage-based polygon splitting."""

    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initGui(self):
        self.provider = PercentageSplitProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
