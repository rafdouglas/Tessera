# Architectural Decisions

This file logs architectural decisions (ADRs) with context and trade-offs. Use bullet lists for clarity.

## Format

Each decision should include:
- Date and ADR number
- Context (why the decision was needed)
- Decision (what was chosen)
- Alternatives considered
- Consequences (trade-offs, implications)

---

### ADR-001: Import Strategy — Symlinks + Relative Imports (2026-02-07)

**Context:**
- Shared library lives at `lib/ideogis_common/`, plugin code at `plugins/ideogis/`
- Plugin must work both during dev (symlinked into QGIS) and when packaged (vendored copies)
- QGIS adds `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/` to sys.path automatically; `lib/` is NOT on that path

**Decision:**
- `infrastructure/crs_manager.py`, `feature_builder.py`, `geometry_helpers.py` are filesystem symlinks to `lib/ideogis_common/` counterparts
- `grid_generators.py` and `topology_wrapper.py` are NOT symlinked (main-plugin-only)
- All plugin code uses relative imports: `from ..infrastructure.geometry_helpers import extract_polygons`
- pytest sys.path: add both repo root and `plugins/` directory in conftest.py
- `scripts/package.py` resolves symlinks to actual copies at package time

**Alternatives considered:**
- Thin re-export wrappers (`from lib.ideogis_common.x import *`) → fails at QGIS runtime since lib/ not on path
- Algorithms import from `lib.` directly → same path problem
- Develop directly in infrastructure/, sync to lib/ manually → divergence risk

**Consequences:**
- Windows requires `git config core.symlinks true`
- Some editors show symlink targets confusingly
- Single source of truth for shared code

---

### ADR-002: Tessellate Output Fields — Section 5.2 Over Section 3 (2026-02-07)

**Context:**
- Spec Section 3 (output data contract) lists `_ig_fraction` and `_ig_state` for Tessellate
- Spec Section 5.2 (Tessellate-specific) lists only `_ig_algorithm`, `_ig_parent_fid`, `_ig_tile_index`
- Tessellate has no VALUE_FIELD parameter — no fraction to compute, no on/off logic defined

**Decision:**
- Phase 1 Tessellate outputs ONLY: `_ig_algorithm`, `_ig_parent_fid`, `_ig_tile_index`
- `_ig_fraction` and `_ig_state` deferred — Section 5.2 (detailed spec) takes precedence over Section 3 (summary table)
- `tessellate_on_off.qml` style preset deferred to Phase 5

**Alternatives considered:**
- Include `_ig_state="on"` for all tiles, `_ig_fraction=1.0` → misleading, implies logic that doesn't exist
- Add VALUE_FIELD to Tessellate → scope creep, changes algorithm semantics

**Consequences:**
- Section 3 table is technically inaccurate for Phase 1
- Future phase can add these fields as backward-compatible enhancement

---

### ADR-003: WorkingCRS as Plain Class, Not Context Manager (2026-02-07)

**Context:**
- Spec calls WorkingCRS a "Context manager for CRS operations"
- The forward/inverse API doesn't benefit from `__enter__`/`__exit__` semantics
- No resources to acquire/release

**Decision:**
- Implement as plain class with `forward()`, `inverse()`, and `working_crs` property
- No `__enter__`/`__exit__`

**Consequences:**
- Simpler API, no `with` statement needed
- Minor spec deviation documented

---

### ADR-004: QMetaType.Type for QgsField Construction (2026-02-07, amended 2026-02-16)

**Context:**
- QGIS 3.44.6 deprecates `QgsField('name', QVariant.String)` constructor
- New style: `QgsField(name='name', type=QMetaType.Type.QString)`
- QGIS < 3.38 does not accept `QMetaType.Type` in `QgsField()` (TypeError)
- User report confirmed breakage on QGIS 3.34.0

**Decision:**
- Algorithms define field types using `QMetaType.Type` (forward-compatible)
- `feature_builder._resolve_field_type()` detects at first use whether `QgsField` accepts `QMetaType.Type`; falls back to `QVariant.Type` mapping on older QGIS
- Compatibility shim lives in one place: `feature_builder.py`

**Consequences:**
- Works on QGIS 3.28+ (our declared minimum) through current
- No deprecation warnings on 3.44+
- Single conversion point — algorithms don't need version-specific code

---

### ADR-005: auto_cell_size Takes 3 Parameters (2026-02-07)

**Context:**
- Spec shows `auto_cell_size(extent, target_count)` with 2 parameters
- Implementation requires `grid_type` to select packing factor

**Decision:**
- Add `grid_type` as third parameter: `auto_cell_size(extent, target_count, grid_type)`
- Spec's code example references `grid_type` in the function body but omits it from signature — likely an oversight

**Consequences:**
- Minor spec deviation, functionally necessary

---

### ADR-006: Triangular Grid Tessellation — Equilateral with Row-Shift (2026-02-07)

**Context:**
- Spec §4.3 provides pseudocode for `nearest_tri_point` using a simple parallelogram-based approach (col = floor(px / (s/2)), no row offset)
- Following the spec's column width of s/2 literally produces non-equilateral right triangles (base s/2, not side s)
- Proper equilateral triangles require each triangle base to span s (2 column steps)

**Decision:**
- Implemented equilateral triangle tessellation with base = s (side length)
- Up triangles: vertices at `(col*s/2, row*h), ((col+2)*s/2, row*h), ((col+1)*s/2, (row+1)*h)`
- Centroids use `(col+1)*s/2` rather than spec's `(col+2/3)*s/2` and `(col+1/3)*s/2`
- `_nearest_triangular` uses odd-row x-shift for correct tessellation alignment
- All three functions (point_grid, cell_polygons, nearest_grid_point) are internally consistent

**Alternatives considered:**
- Follow spec pseudocode literally → produces non-equilateral triangles that don't tile without gaps
- Use spec centroids with corrected vertices → centroids would not be true centroids

**Consequences:**
- Triangular grid tessellates correctly without gaps (verified by union-covers-extent test)
- `nearest_grid_point` for triangular matches the same tessellation as `generate_cell_polygons`
- Spec pseudocode was guidance, not exact API contract — implementation prioritizes correctness

---

### ADR-007: Area-Equivalent Radius for Force-Directed Collision (2026-02-08)

**Context:**
- Arrange Features force-directed layout used Minimum Enclosing Circle (MEC) as collision radius
- MEC vastly overestimates for elongated shapes (Chile: MEC ≈ 10x area-equiv) and catastrophically overestimates for multipart geometries (Russia: MEC spans both European and Far East landmasses)
- User observed Russia displaced 1.5M meters from all other features with Natural Earth 110m data

**Decision:**
- Replace MEC with area-equivalent circle radius: `r = sqrt(area / pi)`
- Explode multipart geometries into single parts before force simulation; each part gets its own centroid and radius
- Add geometry-based refinement pass (`_refine_overlaps`) for separate mode using `QgsGeometry.intersects()` to catch remaining actual boundary overlaps

**Alternatives considered:**
- Bounding box diagonal / 2 — still overestimates for elongated shapes, just less than MEC
- Convex hull equivalent radius — more expensive to compute, marginal improvement over area-equiv
- Per-part MEC — fixes multipart but still overestimates for elongated single-part features
- Actual geometry distance throughout force loop — O(n²) per iteration with expensive GEOS operations, too slow

**Consequences:**
- Area-equiv radius underestimates for very concave shapes (donut, U-shape) — the refinement pass compensates
- Multipart explosion increases output feature count (each part becomes a separate output feature with same attributes)
- Refinement pass is O(n²) per iteration (max 20 iterations) — acceptable for typical cartographic feature counts (< 1000)
- `_count_remaining_overlaps` warning still uses area-equiv approximation (fast heuristic), not actual geometry

---

### ADR-008: Split Grid Arrangement Into Separate Algorithm Class (2026-02-09)

**Context:**
- `ArrangeFeaturesAlgorithm` grew to 1,341 lines with 4 modes: Separate, Attract, Separate with gap, Grid arrangement
- Grid mode shares zero domain logic with the force-directed/geometric modes — no common parameters, no shared helper methods
- Grid has 7 unique parameters (GRID_COLUMNS, GRID_CELL_WIDTH, GRID_CELL_HEIGHT, GRID_PADDING, GRID_SORT_FIELD, GRID_FILL_ORDER, GRID_CELLS) with zero overlap against force-directed parameters
- Grid mode overrides `processAlgorithm()` to change output CRS to engineering CRS, breaking the Template Method contract of `TesseraAlgorithm` (other modes follow the base class pipeline)
- Coupling analysis: grid mode calls `_run_grid_arrangement()` only, force/geometric modes call `_run_geometric_separation()`, `_run_force_directed()`, `_compute_pair_force()`, `_refine_gap()`, `_refine_overlaps()`, `_count_remaining_overlaps()` — disjoint call graphs

**Decision:**
- Extract grid arrangement into `GridArrangementAlgorithm` in `plugins/tessera/algorithms/grid_arrangement.py`
- Grid algorithm overrides `processAlgorithm()` legitimately (engineering CRS output) — the override makes sense as its own class
- `ArrangeFeaturesAlgorithm` retains 3 modes: Separate, Attract, Separate with gap — keeps `FORCE_ENGINEERING_CRS` param
- Engineering CRS constant (`_ENGINEERING_CRS_PROJ`) and `_create_engineering_crs()` are duplicated (both classes need it) — acceptable for two ~20-line constants
- Grid algorithm registered as 9th algorithm in provider and dialog
- Grid tests moved to `tests/test_grid_arrangement.py`

**Alternatives considered:**
- Split all 4 modes into separate classes (one per mode) — over-engineering, the 3 force/geometric modes share significant infrastructure (feature collection, multipart explosion, displacement tracking)
- Keep as-is — violates SRP, the file is the largest in the codebase at 1,341 lines, and grid mode makes the class harder to understand
- Extract shared code into a base "arrangement" class — unnecessary, the only shared code is boilerplate that `TesseraAlgorithm` already provides

**Consequences:**
- `ArrangeFeaturesAlgorithm` shrinks from 1,341 to ~850 lines
- `GridArrangementAlgorithm` is ~200 lines — clean, single-responsibility
- Algorithm count increases from 8 to 9 (provider, dialog, tests, docs all updated)
- `resolve_overlaps.py` backward compat alias unchanged (still points to ArrangeFeaturesAlgorithm)
- MODE enum changes from 4 to 3 options — existing workflows using `MODE: 3` for grid will break (must use the new algorithm instead)

---

### ADR-009: Centralized Engineering CRS in crs_manager.py (2026-02-09)

**Context:**
- `arrange_features.py` and `grid_arrangement.py` both defined identical `_ENGINEERING_CRS_PROJ` constant and `_create_engineering_crs()` static method
- Both algorithms need a flat Cartesian CRS for layout output
- `crs_manager.py` is the shared infrastructure module for CRS operations

**Decision:**
- Moved `ENGINEERING_CRS_PROJ` constant and `create_engineering_crs()` function to `lib/ideogis_common/crs_manager.py`
- Both algorithms import from `..infrastructure.crs_manager`
- Function is module-level (not a static method) since it has no instance dependency

**Consequences:**
- Single source of truth for engineering CRS definition
- Any future layout algorithms can reuse without duplication

---

### ADR-010: Shared Scale Helpers Module (2026-02-09)

**Context:**
- `scale_by_value.py` and `replace_with_shape.py` had near-identical scale factor computation logic
- `_compute_scale()` (static method) and `_compute_scale_factor()` (module function) differed only in configurable vs hardcoded clamp ranges
- Scale method constants (`METHOD_PROPORTIONAL_AREA/SQRT/LOG`) and reference constants (`REF_MAX_VALUE/MEAN_VALUE/FIXED`) defined separately in each file

**Decision:**
- Created `lib/ideogis_common/scale_helpers.py` with shared `compute_scale_factor()` and `compute_reference()`
- `compute_scale_factor()` takes `min_scale`/`max_scale` params (default 0.0/10.0) — unifies both use cases
- Constants use module-level names without underscore prefix (public API): `METHOD_PROPORTIONAL_AREA`, `REF_MAX_VALUE`, etc.
- `scale_by_value.py` re-aliases imports to preserve internal `_METHOD_*` / `_REF_*` naming convention

**Alternatives considered:**
- Extract only `compute_scale_factor`, leave reference computation separate — viable but incomplete, `compute_reference` is also duplicable
- Move all scaling logic to a base class — over-engineering, these algorithms don't share enough to warrant inheritance

**Consequences:**
- ~80 lines of duplicated logic removed
- New shared module added to vendoring pipeline (symlink created)
- `replace_with_shape.py` reference computation remains inline (structurally different from scale_by_value's pattern)

---

### ADR-011: Quality Meta-Parameter for Arrange Features (2026-02-09)

_Note: Originally numbered ADR-009, renumbered after inserting ADR-009 and ADR-010._

**Context:**
- Arrange Features has 5 advanced force-simulation parameters (iterations, damping, anchor_strength, convergence_threshold, adaptive_damping)
- Most users don't understand these parameters and want simple controls
- Power users still need fine-grained control

**Decision:**
- Added QUALITY enum parameter with 4 options: Fast, Balanced, Precise, Custom
- Fast/Balanced/Precise map to preset values via `_QUALITY_PRESETS` dict
- Custom mode reads the advanced parameters directly (backward compatible)
- Default is Balanced (100 iterations, damping=0.1, anchor=0.01)
- QUALITY is NOT flagged as Advanced — always visible in dialog
- Advanced params remain available but only take effect when QUALITY=Custom

**Alternatives considered:**
- Single "quality" slider (0-100) — harder to map to meaningful parameter combinations
- Remove advanced params entirely — breaks power users
- Auto-detect quality from feature count — unpredictable, hard to explain

**Consequences:**
- Existing workflows that set ITERATIONS etc. without QUALITY will get Balanced defaults (behavioral change)
- Test helpers updated to pass QUALITY=3 (Custom) to preserve explicit param behavior
- 4 preset levels provide good coverage for common use cases

---

### ADR-012: Rename Tessellate → Tile Fill and _ts_ → _tessera_ Prefix (2026-02-09)

**Context:**
- "Tessellate" as an algorithm name was technically accurate but not user-friendly for cartographers
- The `_ts_` metadata field prefix was cryptic — stood for "Tessera" but this wasn't obvious
- Remaining `_ig_` references (old "IdeoGIS" prefix) still existed in test files and some function names
- Three different prefixes (`_ig_`, `_ts_`, and the project name "Tessera") created confusion

**Decision:**
- Rename algorithm: Tessellate → Tile Fill (`tile_fill.py`, `TileFillAlgorithm`, `name()='tile_fill'`, `displayName()='Tile Fill'`)
- Standardize ALL metadata field prefixes to `_tessera_` (full, unambiguous project name)
- Replace `_ts_` → `_tessera_` across all 9 algorithms, feature_builder.py, base_algorithm.py
- Replace `_ig_` → `_tessera_` in all test files
- Update imports and registry in processing_provider.py, main_dialog.py

**Alternatives considered:**
- Keep `_ts_` prefix — shorter but cryptic, doesn't self-document
- Use `_tf_` for Tile Fill — inconsistent, per-algorithm prefixes would fragment the schema
- Rename only the algorithm without changing prefix — half-measure, misses the opportunity

**Consequences:**
- Breaking change: existing workflows using `tessellate` algorithm name or `_ts_*`/`_ig_*` field names must update
- Field names are longer (`_tessera_algorithm` vs `_ts_algorithm`) but self-documenting
- Zero ambiguity about which project generated the metadata fields
- All three historical prefixes (`_ig_`, `_ts_`, `_tessera_`) now unified into one
