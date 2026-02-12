# Contributing to Tessera

Tessera is a cartographic ideogram toolkit for QGIS -- 9 algorithms for thematic maps. Python + PyQt5 + qgis.core. No external dependencies beyond what QGIS 3.28+ bundles. Licensed GPLv3.

Author: RafDouglas C. Tommasi.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Development Environment](#development-environment)
3. [Project Architecture](#project-architecture)
4. [Coding Standards](#coding-standards)
5. [Adding a New Algorithm](#adding-a-new-algorithm)
6. [Writing Tests](#writing-tests)
7. [Output Data Contract](#output-data-contract)
8. [Shared Infrastructure](#shared-infrastructure)
9. [Packaging](#packaging)
10. [Pull Request Guidelines](#pull-request-guidelines)
11. [Architecture Decisions](#architecture-decisions)

---

## Getting Started

```bash
# 1. Fork and clone
git clone <your-fork-url>
cd tessera

# 2. Enable symlinks (required on Windows)
git config core.symlinks true

# 3. Verify symlinks resolved correctly
ls -la plugins/tessera/infrastructure/crs_manager.py
# Should show: crs_manager.py -> ../../../lib/ideogis_common/crs_manager.py

# 4. Get test data
python scripts/download_test_data.py
# Or manually place Natural Earth 110m countries shapefile in:
#   test_data/ne_110m_admin_0_countries/ne_110m_admin_0_countries.shp

# 5. Run tests
flatpak run --command=python3 org.qgis.qgis -m pytest tests/ -v
```

If symlinks show as plain text files instead of links (common on Windows without the git config), delete them and re-checkout:

```bash
git config core.symlinks true
git checkout -- plugins/tessera/infrastructure/
```

---

## Development Environment

**Required:**
- QGIS 3.28+ (3.44+ recommended)
- Python 3.9+ (bundled with QGIS)
- pytest (bundled with QGIS flatpak; `pip install pytest` otherwise)

**QGIS installation options:**

| Method | Test command |
|--------|-------------|
| Flatpak (recommended) | `flatpak run --command=python3 org.qgis.qgis -m pytest tests/ -v` |
| System-wide install | `python -m pytest tests/ -v` |

**No pip installs.** All dependencies (qgis.core, qgis.gui, PyQt5) are provided by QGIS. Do not add external packages.

**Symlink setup (development only):**

The shared library at `lib/ideogis_common/` is symlinked into each plugin's `infrastructure/` directory. This lets you edit once in `lib/` and have changes reflected everywhere during development.

```
plugins/tessera/infrastructure/crs_manager.py      -> lib/ideogis_common/crs_manager.py
plugins/tessera/infrastructure/feature_builder.py   -> lib/ideogis_common/feature_builder.py
plugins/tessera/infrastructure/geometry_helpers.py   -> lib/ideogis_common/geometry_helpers.py
plugins/tessera/infrastructure/scale_helpers.py      -> lib/ideogis_common/scale_helpers.py
```

If you need to recreate a symlink:

```bash
cd plugins/tessera/infrastructure
ln -sf ../../../lib/ideogis_common/crs_manager.py crs_manager.py
```

---

## Project Architecture

### Directory Structure

```
lib/ideogis_common/              # Shared library (source of truth for shared code)
    crs_manager.py               #   WorkingCRS, create_engineering_crs()
    feature_builder.py           #   create_output_fields(), build_feature()
    geometry_helpers.py          #   extract_polygons(), regular_polygon(), split_polygon_by_fraction()
    scale_helpers.py             #   compute_scale_factor(), compute_reference()

plugins/
    tessera/                     # Main plugin (9 algorithms)
        algorithms/              # All algorithm implementations
            base_algorithm.py    #   TesseraAlgorithm (Template Method base class)
            tile_fill.py         #   Tile Fill
            percentage_split.py  #   Percentage Split
            stripe_hatching.py   #   Stripe Hatching
            scale_by_value.py    #   Scale by Value
            replace_with_shape.py#   Replace with Shape
            arrange_features.py  #   Arrange Features (3 modes)
            grid_arrangement.py  #   Grid Arrangement
            snap_to_grid.py      #   Snap to Grid
            sketchy_borders.py   #   Sketchy Borders
        infrastructure/          # Shared code (symlinks) + plugin-only modules
            crs_manager.py       #   SYMLINK -> lib/ideogis_common/
            feature_builder.py   #   SYMLINK -> lib/ideogis_common/
            geometry_helpers.py  #   SYMLINK -> lib/ideogis_common/
            scale_helpers.py     #   SYMLINK -> lib/ideogis_common/
            grid_generators.py   #   NOT symlinked (main-plugin-only)
            topology_wrapper.py  #   NOT symlinked (main-plugin-only)
            percent_helpers.py   #   NOT symlinked (main-plugin-only)
        ui/
            main_dialog.py       #   TesseraDialog with _ALGORITHM_REGISTRY
        processing_provider.py   #   TesseraProvider.loadAlgorithms()
    percentage_split/            # Standalone plugin
    stripe_hatching/             # Standalone plugin

tests/                           # 500+ tests
    conftest.py                  #   qgis_app fixture, geometry fixtures
    helpers.py                   #   make_fields(), make_feature(), make_layer()
    test_*.py                    #   One test file per algorithm + infrastructure module

test_data/                       # Natural Earth 110m countries (not committed)
scripts/
    package.py                   #   Vendor symlinks -> copies, create ZIPs
    download_test_data.py        #   Fetch test data
docs/project_notes/              #   ADRs, bugs, key facts, work log
```

### Base Algorithm Pattern (Template Method)

All algorithms inherit from `TesseraAlgorithm` in `base_algorithm.py`. The base class orchestrates the processing pipeline:

```
processAlgorithm()
    1. Resolve INPUT source
    2. Get output fields (via get_output_fields())
    3. Create WorkingCRS
    4. Create output sink (MultiPolygon, source CRS)
    5. Create topology placeholder
    6. Delegate to run_algorithm()    <-- subclass implements this
    7. Return output reference
```

**Subclasses must override:**

| Method | Purpose |
|--------|---------|
| `name()` | Unique algorithm identifier (e.g., `'tile_fill'`) |
| `displayName()` | Human-readable name (e.g., `'Tile Fill'`) |
| `createInstance()` | Return `self.__class__()` |
| `run_algorithm()` | Core logic -- receives source, parameters, context, working_crs, topology, sink, feedback |

**Optionally override:**

| Method | Purpose |
|--------|---------|
| `get_output_fields(source, parameters, context)` | Add `_tessera_*` columns beyond source fields |
| `group()` / `groupId()` | Algorithm category (default: `'Tessera'` / `'tessera'`) |
| `output_layer_name()` | OUTPUT parameter description |

**Two algorithms override `processAlgorithm()` directly:**
- `GridArrangementAlgorithm` -- outputs in engineering CRS instead of source CRS
- `SnapToGridAlgorithm` -- injects topology handling around the base pipeline

### CRS Handling

- **WorkingCRS**: auto-detects equal-area CRS for geographic input, preserves projected CRS as-is. All area/distance calculations should happen in the working CRS.
- **Engineering CRS**: flat Cartesian output for Grid Arrangement (always) and Arrange Features (optional via `FORCE_ENGINEERING_CRS`). Created via `create_engineering_crs()` in `crs_manager.py`.
- Transform geometries with `working_crs.forward(geom)` and `working_crs.inverse(geom)` before writing output.

### Topology

`TopologyTransformer` in `topology_wrapper.py` tracks shared vertices across features for topology-preserving vertex transforms. Used by Snap to Grid and Sketchy Borders. If your algorithm modifies vertex positions and needs to preserve shared boundaries, use it.

---

## Coding Standards

### Naming

| Element | Convention | Example |
|---------|-----------|---------|
| Functions, variables | `snake_case` | `auto_cell_size()`, `working_crs` |
| Classes | `PascalCase` | `TileFillAlgorithm`, `WorkingCRS` |
| Processing parameters | `UPPER_SNAKE_CASE` | `CELL_SIZE`, `VALUE_FIELD`, `GRID_COLUMNS` |
| Metadata fields | `_tessera_` prefix | `_tessera_algorithm`, `_tessera_parent_fid` |
| Constants | `_UPPER_SNAKE_CASE` | `_SHAPE_HEXAGON`, `_BATCH_SIZE` |

### QgsField Construction

Use `QMetaType.Type` -- never the deprecated `QVariant` constructor:

```python
# Correct
from PyQt5.QtCore import QMetaType
QgsField(name='field_name', type=QMetaType.Type.QString)
QgsField(name='field_name', type=QMetaType.Type.Double)
QgsField(name='field_name', type=QMetaType.Type.Int)
QgsField(name='field_name', type=QMetaType.Type.Bool)

# Wrong -- deprecated, produces warnings
from PyQt5.QtCore import QVariant
QgsField('field_name', QVariant.String)
```

### Geometry Safety

After **every** geometry operation that may change geometry type (`intersection()`, `difference()`, `clipped()`), call `extract_polygons()`:

```python
from ..infrastructure.geometry_helpers import extract_polygons

clipped = polygon.intersection(clip_region)
clipped = extract_polygons(clipped)  # Always -- may return GeometryCollection
```

Before writing output for algorithms that may produce invalid geometries:

```python
geom = geom.makeValid()
geom = extract_polygons(geom)
```

### Imports

- Use relative imports within the plugin: `from ..infrastructure.geometry_helpers import extract_polygons`
- Use absolute imports only in tests: `from plugins.tessera.algorithms.tile_fill import TileFillAlgorithm`
- No external packages. Only `qgis.core`, `qgis.gui`, `PyQt5`, Python stdlib.

### Docstrings

Public functions and classes require docstrings. Follow the existing pattern:

```python
def compute_scale_factor(value, reference, method, min_scale=0.0, max_scale=10.0):
    """Compute a scale factor for a value relative to a reference.

    Args:
        value: Numeric value to scale.
        reference: Reference value (typically max or mean).
        method: Scaling method constant (METHOD_PROPORTIONAL_AREA, etc.).
        min_scale: Minimum output scale factor.
        max_scale: Maximum output scale factor.

    Returns:
        Float scale factor, clamped to [min_scale, max_scale].
    """
```

---

## Adding a New Algorithm

### Checklist

1. **Create the algorithm file** in `plugins/tessera/algorithms/your_algorithm.py`
2. **Register in the Processing provider** (`plugins/tessera/processing_provider.py`)
3. **Register in the dialog** (`plugins/tessera/ui/main_dialog.py`)
4. **Add tests** (`tests/test_your_algorithm.py`)
5. **Run the full test suite** to verify no regressions

### Step 1: Create the Algorithm

```python
"""Your Algorithm -- one-line description."""
from qgis.core import QgsProcessingParameterNumber
from ..infrastructure.feature_builder import create_output_fields, build_feature
from ..infrastructure.geometry_helpers import extract_polygons
from .base_algorithm import TesseraAlgorithm


class YourAlgorithm(TesseraAlgorithm):
    """Fill description of what this algorithm does."""

    def name(self):
        return 'your_algorithm'

    def displayName(self):
        return 'Your Algorithm'

    def group(self):
        return 'Fill'  # or 'Shape', 'Style'

    def groupId(self):
        return 'fill'  # or 'shape', 'style'

    def createInstance(self):
        return YourAlgorithm()

    def output_layer_name(self):
        return 'Your output'

    def initAlgorithm(self, config=None):
        super().initAlgorithm(config)
        # Add algorithm-specific parameters after INPUT/OUTPUT
        self.addParameter(
            QgsProcessingParameterNumber(
                'MY_PARAM', 'My parameter',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.0, minValue=0.0,
            )
        )

    def get_output_fields(self, source, parameters=None, context=None):
        """Add _tessera_ metadata fields."""
        extra_fields = [
            ('_tessera_algorithm', 'String'),
            ('_tessera_parent_fid', 'Int'),
        ]
        return create_output_fields(source.fields(), extra_fields)

    def run_algorithm(self, source, parameters, context, working_crs,
                      topology, sink, feedback):
        my_param = self.parameterAsDouble(parameters, 'MY_PARAM', context)
        features = list(source.getFeatures())
        total = len(features)

        for i, feature in enumerate(features):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(i / total * 100))

            geom = feature.geometry()
            geom = working_crs.forward(geom)

            # ... your algorithm logic ...

            geom = working_crs.inverse(geom)
            output_feature = build_feature(
                geom, feature, sink.fields(),
                _tessera_algorithm='your_algorithm',
                _tessera_parent_fid=feature.id(),
            )
            sink.addFeature(output_feature)
```

### Step 2: Register in the Provider

In `plugins/tessera/processing_provider.py`:

```python
from .algorithms.your_algorithm import YourAlgorithm

# In loadAlgorithms():
self.addAlgorithm(YourAlgorithm())
```

### Step 3: Register in the Dialog

In `plugins/tessera/ui/main_dialog.py`:

```python
from ..algorithms.your_algorithm import YourAlgorithm

# In _ALGORITHM_REGISTRY dict:
_ALGORITHM_REGISTRY = {
    # ... existing entries ...
    'Your Algorithm': YourAlgorithm,
}
```

### Step 4: Add Tests

Create `tests/test_your_algorithm.py`. See [Writing Tests](#writing-tests).

### Step 5: Run Tests

```bash
flatpak run --command=python3 org.qgis.qgis -m pytest tests/ -v
```

All existing tests must still pass. No regressions.

---

## Writing Tests

### Running Tests

```bash
# Full suite
flatpak run --command=python3 org.qgis.qgis -m pytest tests/ -v

# Single file
flatpak run --command=python3 org.qgis.qgis -m pytest tests/test_tile_fill.py -v

# Single test
flatpak run --command=python3 org.qgis.qgis -m pytest tests/test_tile_fill.py::test_basic_hex -v

# Without flatpak (if QGIS installed system-wide)
python -m pytest tests/ -v
```

### Shared Fixtures (conftest.py)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `qgis_app` | session | Initialized `QgsApplication` -- required for all QGIS operations |
| `simple_squares` | function | Four adjacent 1x1 squares with values 10, 20, 30, 40 |
| `concave_polygon` | function | U-shaped polygon whose centroid lies outside the polygon |
| `multipolygon` | function | MultiPolygon: mainland (100 area) + island (4 area) |
| `polygon_with_holes` | function | Polygon with one interior hole (net area 84) |
| `natural_earth_path` | session | Path to Natural Earth 110m shapefile |

### Shared Helpers (helpers.py)

```python
from tests.helpers import make_fields, make_feature, make_layer

fields = make_fields()                              # name (String), value (Double)
feat = make_feature(geometry, 'name', 42.0, fields) # QgsFeature with geom + attrs
layer = make_layer(features, crs_id='EPSG:4326')    # Memory vector layer
```

### Test Conventions

- **Create geometries programmatically.** Don't depend on test data files unless testing real-world edge cases.
- **One test file per algorithm** (`test_tile_fill.py`, `test_snap_to_grid.py`, etc.) plus files for infrastructure modules.
- **Test the Processing interface.** Run algorithms through QGIS Processing to catch parameter handling bugs:

```python
from qgis.core import QgsProcessingContext, QgsProcessingFeedback

def test_basic_run(qgis_app, simple_squares):
    layer = make_layer(simple_squares, crs_id='EPSG:32632')
    context = QgsProcessingContext()
    feedback = QgsProcessingFeedback()

    alg = YourAlgorithm()
    alg.initAlgorithm()
    result = alg.processAlgorithm(
        {'INPUT': layer, 'OUTPUT': 'memory:', 'MY_PARAM': 1.0},
        context, feedback,
    )
    output_layer = context.getMapLayer(result['OUTPUT'])
    assert output_layer.featureCount() > 0
```

- **Test output field schema.** Verify `_tessera_*` fields exist with correct types.
- **Test geometry validity.** Check output geometries are valid MultiPolygons.
- **Test edge cases.** Empty layers, single features, multipart geometries, polygons with holes.

---

## Output Data Contract

All algorithms produce **MultiPolygon** output in the **source CRS** (except Grid Arrangement, which outputs in engineering CRS).

### Standard Metadata Fields

| Field | Type | Present In | Description |
|-------|------|-----------|-------------|
| `_tessera_algorithm` | String | All algorithms | Algorithm identifier (e.g., `'tile_fill'`) |
| `_tessera_parent_fid` | Int | All algorithms | Feature ID of the input feature |

### Per-Algorithm Fields

| Field | Type | Algorithms | Description |
|-------|------|-----------|-------------|
| `_tessera_fraction` | Double | Tile Fill, Percentage Split | Value fraction (0.0--1.0) |
| `_tessera_part` | String | Tile Fill (with PERCENT_FIELD), Percentage Split | `'filled'` or `'remainder'` |
| `_tessera_tile_index` | Int | Tile Fill | Index of the tile within the parent feature |
| `_tessera_scale_factor` | Double | Scale by Value, Replace with Shape | Applied scale factor |

Use `create_output_fields()` and `build_feature()` from `feature_builder.py` to construct output features. Never create `_tessera_*` fields manually -- always go through the shared builder.

### Field Prefix

All metadata fields use the `_tessera_` prefix. Historical prefixes `_ig_` and `_ts_` are deprecated and must not be used in new code.

---

## Shared Infrastructure

### What Lives in lib/ideogis_common/ (Source of Truth)

| Module | Key Exports | Used By |
|--------|-------------|---------|
| `crs_manager.py` | `WorkingCRS`, `create_engineering_crs()` | All algorithms |
| `feature_builder.py` | `create_output_fields()`, `build_feature()` | All algorithms |
| `geometry_helpers.py` | `extract_polygons()`, `regular_polygon()`, `split_polygon_by_fraction()` | Most algorithms |
| `scale_helpers.py` | `compute_scale_factor()`, `compute_reference()` | Scale by Value, Replace with Shape |

**Always edit files in `lib/ideogis_common/`.** Never edit the symlink targets in `plugins/*/infrastructure/` directly. Changes in `lib/` are reflected everywhere via symlinks.

### Plugin-Only Modules (Not Symlinked)

These live directly in `plugins/tessera/infrastructure/` and are not shared:

| Module | Purpose |
|--------|---------|
| `grid_generators.py` | Point grids and cell polygon generation for Tile Fill |
| `topology_wrapper.py` | `TopologyTransformer` for shared-vertex tracking |
| `percent_helpers.py` | Fraction parsing and divisor detection for Tile Fill / Percentage Split |

### Adding a New Shared Module

1. Create the module in `lib/ideogis_common/your_module.py`
2. Create symlinks in each plugin that needs it:
   ```bash
   cd plugins/tessera/infrastructure
   ln -s ../../../lib/ideogis_common/your_module.py your_module.py
   ```
3. Add the filename to the `shared_files` list in `scripts/package.py` (`vendor_shared_lib()`)
4. Add tests in `tests/test_your_module.py`

---

## Packaging

`scripts/package.py` builds distribution ZIPs for the QGIS Plugin Manager:

```bash
python scripts/package.py --output-dir dist/
```

What it does:
1. **Standalone plugins** (`percentage_split`, `stripe_hatching`): copies `lib/ideogis_common/` files into each plugin's `infrastructure/` directory, then ZIPs
2. **Main plugin** (`tessera`): resolves all symlinks to real file copies in a temp directory, then ZIPs
3. Skips `__pycache__` and `.pyc` files

Output: `dist/tessera.zip`, `dist/percentage_split.zip`, `dist/stripe_hatching.zip`

Do not commit the `dist/` directory.

---

## Pull Request Guidelines

### Branch Naming

```
feature/short-description     # New features
fix/short-description         # Bug fixes
refactor/short-description    # Refactoring
```

### Requirements

- [ ] All existing tests pass
- [ ] New code has corresponding tests
- [ ] No external dependencies added
- [ ] `_tessera_` prefix used for any new metadata fields
- [ ] Shared code edited in `lib/ideogis_common/`, not in symlink targets
- [ ] `extract_polygons()` called after every geometry set operation
- [ ] Docstrings on public functions and classes

### Commit Messages

Use imperative mood. Prefix with the area of change:

```
Grid Arrangement: add sort-by-area option
Fix extract_polygons handling of empty GeometryCollection
Refactor: move engineering CRS to crs_manager.py
Tests: add multipolygon edge case for Percentage Split
```

### What Makes a Good PR

- Focused: one logical change per PR
- Tested: new behavior has tests, existing tests untouched or deliberately updated
- Documented: if you add a parameter, add a docstring. If you make an architectural decision, add an ADR.

---

## Architecture Decisions

Architectural decisions are logged as ADRs in `docs/project_notes/decisions.md`. There are currently 12 ADRs covering:

- ADR-001: Symlink + vendoring strategy
- ADR-002: Output field schema for Tile Fill
- ADR-003: WorkingCRS as plain class
- ADR-004: QMetaType.Type for QgsField construction
- ADR-005: auto_cell_size parameter signature
- ADR-006: Triangular grid tessellation geometry
- ADR-007: Area-equivalent radius for force-directed collision
- ADR-008: Split Grid Arrangement into separate algorithm
- ADR-009: Centralized engineering CRS in crs_manager.py
- ADR-010: Shared scale helpers module
- ADR-011: Quality meta-parameter for Arrange Features
- ADR-012: Rename Tessellate to Tile Fill, standardize `_tessera_` prefix

**Before proposing architectural changes**, check `docs/project_notes/decisions.md` for existing decisions that may conflict.

**When making a significant design choice**, add a new ADR following the format:

```markdown
### ADR-NNN: Title (YYYY-MM-DD)

**Context:** Why the decision was needed.
**Decision:** What was chosen.
**Alternatives considered:** What else was evaluated.
**Consequences:** Trade-offs and implications.
```

Other project memory files in `docs/project_notes/`:

| File | Purpose |
|------|---------|
| `bugs.md` | Bug log with dates, solutions, prevention notes |
| `decisions.md` | ADRs (see above) |
| `key_facts.md` | Environment details, critical constants |
| `issues.md` | Work log with dates |
