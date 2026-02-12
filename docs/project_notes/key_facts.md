# Key Facts

This file stores project configuration, constants, and frequently-needed **non-sensitive** information. Organize by category using bullet lists.

## Security Warning

**NEVER store passwords, API keys, or sensitive credentials in this file.** Store secrets in `.env` files, password managers, or secrets managers.

---

## Environment

- **QGIS version:** 3.44.6-Solothurn (flatpak)
- **QGIS launch command:** `/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=qgis --file-forwarding org.qgis.qgis`
- **Python version:** 3.13.11 (inside flatpak)
- **pytest version:** 9.0.2 (inside flatpak)
- **QGIS Python path:** `/app/share/qgis/python` (inside flatpak, must be added to sys.path)
- **QGIS prefix path:** `/app` (used in `QgsApplication.setPrefixPath('/app', True)`)

## Running Tests

```bash
flatpak run --command=python3 org.qgis.qgis -m pytest tests/ -v
```

Or use the `run_tests.sh` wrapper script (to be created in Step 0).

## Running Python Inside Flatpak

```bash
flatpak run --command=python3 org.qgis.qgis -c "import sys; sys.path.insert(0, '/app/share/qgis/python'); ..."
```

## Project Structure

- **Shared library:** `lib/ideogis_common/`
- **Main plugin:** `plugins/tessera/` (9 algorithms)
- **Test data:** `test_data/ne_110m_admin_0_countries/ne_110m_admin_0_countries.shp` (run `python scripts/download_test_data.py`)
- **Version:** 0.5.4
- **Shared infrastructure modules:** `crs_manager.py`, `feature_builder.py`, `geometry_helpers.py`, `scale_helpers.py` (symlinked from `lib/ideogis_common/`)
- **Test helpers:** `tests/helpers.py` — `make_fields()`, `make_feature()`, `make_layer()`

## Plugin Installation (Dev)

```bash
ln -sf $(pwd)/plugins/tessera \
  ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/tessera
```

## Critical Implementation Constants

- **Tolerance:** 1e-6 meters (not 1e-8)
- **Hex grid:** cell_size = flat-to-flat height, circumradius R = cell_size / sqrt(3)
- **Packing factors:** square=1.0, hex=1.07, circle=1.07, triangle=1.52, diamond=1.0
- **Circle tile radius:** cell_size * 0.45
- **Batch sink write size:** 1000-5000 features
- **50K feature warning threshold**
- **EQUAL_AREA_PROJS:** aea, laea, cea, eqearth, moll, sinu, eck4, eck6

## QgsField Construction (QGIS 3.44.6)

```python
from PyQt5.QtCore import QMetaType
QgsField(name='field_name', type=QMetaType.Type.QString)   # String
QgsField(name='field_name', type=QMetaType.Type.Double)    # Float/Double
QgsField(name='field_name', type=QMetaType.Type.Int)       # Integer
QgsField(name='field_name', type=QMetaType.Type.Bool)      # Boolean
```

Do NOT use `QVariant.String` etc. — deprecated in 3.44.

## CRS Operations

- Use `createFromProj()` (instance method returning bool), NOT `createFromProj4()` (removed in 3.30)
- `extract_polygons()` after EVERY `intersection()`, `difference()`, `clipped()` call
- `QgsProcessingAlgRunnerTask` for dialog execution, NOT custom QgsTask
- Do NOT use `QgsProcessingAlgorithmDialogBase`
