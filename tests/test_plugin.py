"""Tests for plugin entry point and TesseraPlugin (T8.1 -- T8.4)."""
import configparser
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from qgis.core import QgsApplication

from tessera import classFactory
from tessera.plugin import TesseraPlugin
from tessera.processing_provider import TesseraProvider


# ---------------------------------------------------------------------------
# T8.1 -- classFactory returns plugin instance
# ---------------------------------------------------------------------------

def test_class_factory_returns_plugin_instance(qgis_app):
    """T8.1: classFactory(iface) returns an TesseraPlugin instance."""
    iface = MagicMock()
    plugin = classFactory(iface)
    assert isinstance(plugin, TesseraPlugin)


# ---------------------------------------------------------------------------
# T8.2 -- Plugin registers provider on initGui
# ---------------------------------------------------------------------------

def test_init_gui_registers_processing_provider(qgis_app):
    """T8.2: initGui() registers TesseraProvider with Processing registry."""
    iface = MagicMock()
    plugin = TesseraPlugin(iface)

    registry = QgsApplication.processingRegistry()
    provider_before = registry.providerById('tessera')

    plugin.initGui()
    try:
        provider = registry.providerById('tessera')
        assert provider is not None
        assert provider.id() == 'tessera'
        assert provider.name() == 'Tessera'
    finally:
        plugin.unload()


# ---------------------------------------------------------------------------
# T8.3 -- Plugin unload removes provider
# ---------------------------------------------------------------------------

def test_unload_removes_processing_provider(qgis_app):
    """T8.3: unload() removes the Tessera Processing provider."""
    iface = MagicMock()
    plugin = TesseraPlugin(iface)
    plugin.initGui()

    registry = QgsApplication.processingRegistry()
    assert registry.providerById('tessera') is not None

    plugin.unload()
    assert registry.providerById('tessera') is None


# ---------------------------------------------------------------------------
# T8.4 -- metadata.txt has required fields
# ---------------------------------------------------------------------------

def test_metadata_has_required_fields():
    """T8.4: metadata.txt contains all required QGIS plugin fields."""
    metadata_path = Path(__file__).parent.parent / 'plugins' / 'tessera' / 'metadata.txt'
    assert metadata_path.exists(), f"metadata.txt not found at {metadata_path}"

    config = configparser.ConfigParser()
    config.read(str(metadata_path))

    assert config.has_section('general')

    required_fields = ['name', 'description', 'version', 'qgisminimumversion',
                       'author', 'email']
    for field in required_fields:
        assert config.has_option('general', field), \
            f"Missing required field: {field}"

    min_version = config.get('general', 'qgisminimumversion')
    major, minor = min_version.split('.')[:2]
    assert int(major) >= 3 and int(minor) >= 28, \
        f"qgisMinimumVersion should be >= 3.28, got {min_version}"
