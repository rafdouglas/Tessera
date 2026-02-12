"""Tests for TesseraProvider (T7.1 -- T7.4)."""
import pytest
from qgis.core import QgsApplication
from PyQt5.QtGui import QIcon

from tessera.processing_provider import TesseraProvider


# ---------------------------------------------------------------------------
# T7.1 -- Provider has correct id and name
# ---------------------------------------------------------------------------

def test_provider_id_is_tessera(qgis_app):
    """T7.1a: Provider id is 'tessera'."""
    provider = TesseraProvider()
    assert provider.id() == 'tessera'


def test_provider_name_is_tessera(qgis_app):
    """T7.1b: Provider name is 'Tessera'."""
    provider = TesseraProvider()
    assert provider.name() == 'Tessera'


# ---------------------------------------------------------------------------
# T7.2 -- Provider loads Tile Fill algorithm
# ---------------------------------------------------------------------------

def test_provider_loads_algorithms(qgis_app):
    """T7.2: loadAlgorithms() registers all implemented algorithms."""
    provider = TesseraProvider()
    provider.loadAlgorithms()
    alg_names = sorted(a.name() for a in provider.algorithms())
    assert 'tile_fill' in alg_names
    assert 'stripe_hatching' in alg_names
    assert 'percentage_split' in alg_names
    assert 'snap_to_grid' in alg_names
    assert 'sketchy_borders' in alg_names
    assert 'scale_by_value' in alg_names
    assert 'replace_with_shape' in alg_names
    assert 'arrange_features' in alg_names
    assert 'grid_arrangement' in alg_names
    assert len(alg_names) == 9


# ---------------------------------------------------------------------------
# T7.3 -- Provider icon returns valid QIcon
# ---------------------------------------------------------------------------

def test_provider_icon_returns_qicon(qgis_app):
    """T7.3: icon() returns a QIcon instance."""
    provider = TesseraProvider()
    icon = provider.icon()
    assert isinstance(icon, QIcon)


# ---------------------------------------------------------------------------
# T7.4 -- Tile Fill algorithm id is correct
# ---------------------------------------------------------------------------

def test_tile_fill_algorithm_id(qgis_app):
    """T7.4: Provider includes a 'tile_fill' algorithm."""
    provider = TesseraProvider()
    provider.loadAlgorithms()
    alg_names = [a.name() for a in provider.algorithms()]
    assert 'tile_fill' in alg_names
