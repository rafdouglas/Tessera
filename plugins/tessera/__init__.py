"""Tessera QGIS plugin."""


def classFactory(iface):
    from .plugin import TesseraPlugin
    return TesseraPlugin(iface)
