# IdeoGIS — Phase 1 Implementation

## What This Is

IdeoGIS is a QGIS plugin suite for cartographic ideograms — thematic maps where geographic shapes are modified to communicate data visually. The full spec is in `ideogis_final_spec.md` in this repository. Read it before writing any code.

## What To Build Now (Phase 1)

Build the foundation + one working algorithm (Tessellate), end-to-end from QGIS dialog to output layer. The spec has 9 algorithms across 5 phases — **only build Phase 1**.

### Deliverables, in order:

1. **Repository structure** — Create the full directory tree from §2 of the spec. All `__init__.py` files, `metadata.txt` for the main plugin, empty placeholder files for Phase 2+ algorithms and standalone plugins. The structure should be complete even though most files are stubs.

2. **Shared library** (`lib/ideogis_common/`):
   - `crs_manager.py` — Full implementation per §4.1. Equal-area detection via proj string parsing, Snyder's 1/6 rule for Albers parallels, Equal Earth for global/hemispheric data, antimeridian detection and splitting. Thread-safe (no shared QgsCoordinateTransform).
   - `feature_builder.py` — Full implementation per §4.4. `create_output_fields()`, `build_feature()` with MultiPolygon promotion. No `create_memory_layer()`.
   - `geometry_helpers.py` — Phase 1 subset: `extract_polygons()`, `safe_pole_of_inaccessibility()`, `clamp()`, `regular_polygon()`. Leave `split_polygon_by_fraction()` and `scale_geometry()` as stubs with `raise NotImplementedError`.

3. **Grid generators** (`plugins/ideogis/infrastructure/grid_generators.py`):
   - `generate_point_grid()` for square + hexagonal
   - `generate_cell_polygons()` for square + hexagonal
   - `auto_cell_size()` with correct packing factors (1.0 square, 1.07 hex, 1.07 circle, 1.52 triangle)
   - `nearest_grid_point()` for square + hex (use the cube-coordinate algorithm from §4.3)
   - Triangular grid: stub with `raise NotImplementedError`

4. **Base algorithm class** (`plugins/ideogis/algorithms/base_algorithm.py`) per §6:
   - Creates WorkingCRS inside processAlgorithm (thread-safe)
   - Creates output sink with MultiPolygon type
   - Input type filter: `QgsProcessing.TypeVectorPolygon`
   - Optionally creates TopologyTransformer (Phase 3, so just pass None for now)
   - Calls `run_algorithm()` passing sink directly
   - Progress reporting

5. **Processing provider** (`plugins/ideogis/processing_provider.py`) per §8:
   - Provider id `"ideogis"`, name `"IdeoGIS"`
   - Register Tessellate (only algorithm implemented now)
   - Other algorithms: don't register stubs, only register working algorithms

6. **Tessellate algorithm** (`plugins/ideogis/algorithms/tessellate.py`) per §5.2:
   - All parameters: TILE_SHAPE (hex/square/circle/triangle), CELL_SIZE, TARGET_TILES, CLIP_BOUNDARY
   - Per-feature grid generation with bbox padding
   - `extract_polygons()` after every intersection
   - Batch sink writes (1000-5000 features at a time)
   - `_ig_tile_index` bottom-to-top, left-to-right
   - Warning if >50K total output features

7. **Plugin entry point** (`plugins/ideogis/__init__.py`, `plugins/ideogis/plugin.py`):
   - `classFactory()` returning `IdeoGISPlugin`
   - Plugin registers the Processing provider on `initGui()`
   - Adds toolbar button that opens the dialog

8. **Plugin dialog** (`plugins/ideogis/ui/main_dialog.py`) per §7:
   - `QgsMapLayerComboBox` filtered to polygon layers
   - Algorithm dropdown (for now just Tessellate, but structure for grouped Fill/Shape/Layout)
   - Dynamic parameter panel built from algorithm's Processing parameter declarations
   - Run button using `QgsProcessingAlgRunnerTask` (NOT custom QgsTask)
   - "Apply default style" checkbox (can be non-functional stub for now)
   - Log area showing progress
   - "Open Processing Dialog" button

9. **Tests**:
   - `tests/conftest.py` — fixtures creating simple test geometries programmatically (simple_squares, concave_polygon, multipolygon, polygon_with_holes)
   - `tests/test_crs_manager.py` — equal-area detection, Albers construction, antimeridian detection
   - `tests/test_grid_generators.py` — point counts, nearest_grid_point correctness for square + hex
   - `tests/test_geometry_helpers.py` — extract_polygons, regular_polygon vertex count and area
   - `tests/test_tessellate.py` — output feature count, geometry type, metadata fields, tile indexing

## Critical Implementation Notes

Read these before coding — they come from two expert reviews and fix real bugs:

- **Tolerance is 1e-6 meters**, not 1e-8. Coordinate transform round-trips introduce 1e-6 to 1e-4m errors.
- **`extract_polygons()` after EVERY `intersection()`, `difference()`, `clipped()` call.** These can return GeometryCollection with degenerate point/line components. Without filtering, area calculations are wrong.
- **`createFromProj()` not `createFromProj4()`** — the latter was removed in QGIS 3.30.
- **Hex grid: cell_size = flat-to-flat height, circumradius R = cell_size / √3.** Column spacing = 3R/2, row spacing = R√3 = cell_size. See §4.3 for the exact formulas.
- **Packing factors:** square=1.0, hex=1.07, circle=1.07, triangle=1.52. The triangle factor is NOT 0.87.
- **Sink-based output:** Algorithms write to `QgsFeatureSink` directly, NOT return a list of features. This keeps memory O(1) for non-topology algorithms.
- **`QgsProcessingAlgRunnerTask` for dialog execution**, not a custom `QgsTask`. It handles threading and layer loading correctly.
- **Do NOT use `QgsProcessingAlgorithmDialogBase`** for the plugin dialog — it's tightly coupled to the Processing lifecycle. Build the dialog from scratch.

## What NOT To Build Yet

- Percentage Split, Stripe Hatching, or any other algorithm beyond Tessellate
- Standalone plugins (percentage_split/, stripe_hatching/)
- Topology wrapper
- `split_polygon_by_fraction()` or `scale_geometry()`
- `.qml` style presets (just create the `styles/` directory)
- `scripts/package.py` (just create a placeholder)

Create placeholder/stub files for all of these so the directory structure is complete, but don't implement them.

## Environment

- Python with QGIS libraries (PyQt5, qgis.core, qgis.gui)
- No pip install needed — everything uses QGIS-bundled libraries
- Test data: Natural Earth 110m countries in `tests/test_data/` (user will provide)
- Tests should work with `pytest` using QGIS's bundled Python

## When Done

The plugin should be installable in QGIS by symlinking `plugins/ideogis/` into `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`. After enabling it, the user should be able to:
1. See "IdeoGIS" in the Processing Toolbox under its own provider
2. Run Tessellate from the Processing Toolbox on any polygon layer
3. Open the IdeoGIS dialog from the toolbar and run Tessellate from there
4. Get a MultiPolygon output layer with hex/square/circle/triangle tiles, correct `_ig_*` metadata fields, and all parent attributes carried over
