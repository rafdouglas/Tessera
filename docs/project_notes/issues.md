# Issues / Work Log

This file logs work completed on tickets. Keep it simple - just enough to remember what was done. Full details live in your ticket system.

## Format

Each entry should include:
- Date (YYYY-MM-DD)
- Ticket ID
- Brief description (1-2 lines)
- URL to ticket (if available)
- Status (optional: completed, in-progress, blocked)

---

### 2026-02-07 - Phase 1 planning complete
- **Status:** Completed
- **Description:** Ralplan consensus planning for IdeoGIS Phase 1 (Foundation + Tessellate). Plan v2.0 approved after 1 iteration (initial REJECT, revised, approved). 10 implementation steps, ~80+ test cases, 5 ADRs documented.
- **Artifacts:** `.omc/plans/ideogis-phase1.md`
- **Next:** Step 0 — Project scaffolding + test infrastructure

### 2026-02-08 - v0.4.1: Force-directed layout fixes
- **Status:** Completed
- **Description:** Fixed three issues in Arrange Features force-directed layout: (1) replaced MEC with area-equivalent radius sqrt(area/pi) to prevent elongated shapes being pushed unreasonably far, (2) explode multipart geometries into single parts before simulation to fix Russia/antimeridian problem, (3) added geometry-based overlap refinement for separate mode using QgsGeometry.intersects().
- **Tests:** 432 passing (6 new: TestAreaEquivalentRadius, TestMultipartExplosion, TestGeometryRefinement)
- **Files:** arrange_features.py, test_arrange_features.py

### 2026-02-09 - v0.5.0: Extract Grid Arrangement into standalone algorithm
- **Status:** Completed
- **Branch:** `refactor/split-grid-arrangement`
- **Description:** Split `ArrangeFeaturesAlgorithm` (1,341 lines, 4 modes) into two classes. Grid mode shared zero domain logic, had 7 unique params with zero overlap, and overrode `processAlgorithm()` breaking the Template Method contract. New `GridArrangementAlgorithm` (~200 lines) in `grid_arrangement.py`. Arrange Features retains 3 force/geometric modes (~850 lines). Algorithm count 8→9.
- **Tests:** 440 passing, 0 failures.
- **Files:** grid_arrangement.py (new), test_grid_arrangement.py (new), arrange_features.py, test_arrange_features.py, processing_provider.py, main_dialog.py, test_stubs.py, test_base_algorithm.py, test_processing_provider.py, README.md, metadata.txt, decisions.md (ADR-008)
- **Breaking:** Workflows using `MODE: 3` (grid) must switch to the new Grid Arrangement algorithm

### 2026-02-09 - Fix 16 pre-existing test failures
- **Status:** Completed
- **Description:** Fixed `refine_iter` UnboundLocalError in arrange_features.py (code bug) and 15 stale test expectations across 7 test files: enum labels (snake_case→Title Case), dialog algorithm count (8→9), dialog param visibility (advanced params hidden), help text (param names→plain English), auto-scale fractions, single-feature iteration count.
- **Tests:** 440 passing, 0 failures (previously 424 passed, 16 failed)
- **Files:** arrange_features.py, test_arrange_features.py, test_base_algorithm.py, test_dialog.py, test_percentage_split.py, test_replace_with_shape.py, test_scale_by_value.py, test_tessellate.py

### 2026-02-09 - v0.5.2: Code quality refactoring
- **Status:** Completed
- **Description:** Systematic code quality improvements identified via codebase assessment. 9 issues addressed: (1) Decomposed arrange_features.py god methods — `_run_geometric_separation` (335 lines) and `_run_force_directed` (260 lines) split into 12 focused private methods. (2) Extracted shared `scale_helpers.py` with `compute_scale_factor()` and `compute_reference()` — removes duplication between scale_by_value.py and replace_with_shape.py. (3) Centralized `create_engineering_crs()` in crs_manager.py — single source of truth. (4) Created `tests/helpers.py` consolidating `make_fields()`, `make_feature()`, `make_layer()` from 10 test files (-239 lines). (5) Fixed 8 stale `_ig_` docstrings → `_ts_`. (6) Deleted dead code `simplify_to_grid_cells.py`. (7) Extracted 5 named constants from 7 magic numbers across tessellate.py and arrange_features.py. (8) Fixed test_stubs.py references to deleted file.
- **Tests:** 447 passing, 0 failures.
- **Files changed:** 27 files (13 algorithm files, 11 test files, 2 infrastructure files, 1 new shared module)

### 2026-02-09 - v0.5.3: Rename Tessellate → Tile Fill, standardize _tessera_ prefix
- **Status:** Completed
- **Description:** Large-scale rename: (1) Renamed Tessellate algorithm to Tile Fill — module file `tessellate.py` → `tile_fill.py`, class `TessellateAlgorithm` → `TileFillAlgorithm`, algorithm name/displayName/output layer name updated, all internal references. (2) Renamed metadata field prefix `_ts_` → `_tessera_` across all 9 algorithms, feature_builder.py (lib + 2 vendored copies), 2 standalone plugin algorithm files, base_algorithm.py docstrings. (3) Renamed remaining `_ig_` → `_tessera_` in all test files. (4) Updated processing_provider.py, main_dialog.py imports and registry. (5) Updated all 12+ test files for new class names, field prefixes, import paths.
- **Tests:** 447 passing, 0 failures.
- **Files changed:** ~30 files (14 production files, 12 test files, 4 documentation files)
- **Breaking:** Existing workflows referencing `tessellate` algorithm name, `TessellateAlgorithm` class, or `_ts_*`/`_ig_*` field names must update.

### 2026-02-09 - v0.5.1: Triangle tiles, Diamond tiles, Quality presets
- **Status:** Completed
- **Description:** Three feature enhancements: (1) Triangle tile shape for Tessellate (routes through existing triangular grid generator), (2) Diamond tile shape for Tessellate (45°-rotated squares, new `_cell_polygons_diamond()`), (3) Quality preset meta-parameter for Arrange Features (Fast/Balanced/Precise/Custom) controlling force simulation params via `_effective_params()`.
- **Tests:** 449 passing, 0 failures (9 new tests)
- **Files:** tessellate.py, grid_generators.py, arrange_features.py, test_tessellate.py, test_arrange_features.py, test_dialog.py, test_base_algorithm.py

### 2026-02-12 - Release workflow and automation
- **Status:** Completed
- **Description:** Created release infrastructure for v0.5.4: (1) GitHub Actions workflow `.github/workflows/release.yml` that auto-creates releases when version tags are pushed, (2) `scripts/prepare_release.sh` script to package and prepare versioned ZIPs in `releases/` folder, (3) Packaged v0.5.4 release files (tessera-0.5.4.zip, percentage_split-0.5.4.zip, stripe_hatching-0.5.4.zip).
- **Files:** .github/workflows/release.yml (new), scripts/prepare_release.sh (new), releases/ (populated), README.md (building section updated)

### 2026-02-24 - Codebase audit remediation (Phases 1-3)
- **Status:** Completed
- **Description:** Implemented the consensus-approved remediation plan from the 2026-02-24 codebase audit. Three phases:
  - **Phase 1 (Quick Wins):** Removed unused imports from 7 files, fixed `scale_helpers.py` missing from vendoring list in `package.py`, fixed 3 stale `lib/tessera_common` → `lib/ideogis_common` docstring references, added deprecation note to `resolve_overlaps.py`.
  - **Phase 2 (DRY Extraction):** Centralized `BATCH_SIZE` constant in `feature_builder.py` (was duplicated in 7 files), centralized `VALUE_RANGE_OPTIONS` in `percent_helpers.py` (was in 2 files), extracted `validate_scale_value()` helper to `scale_helpers.py` (was ~30-line duplicate in `scale_by_value.py` and `replace_with_shape.py`).
  - **Phase 3 (Performance & Quality):** Added `_build_spatial_grid`, `_iter_nearby_pairs`, `_max_geom_extent` helpers to `arrange_features.py`. Applied spatial indexing to 5 O(n^2) refinement/counting methods (two geometry-access patterns: Pattern A direct geoms, Pattern B displaced geoms with offsets). Consolidated `_iterate_force_directed_loop` from 13 to 9 parameters by moving 4 params into the config dict.
- **Tests:** 507 passing after each phase, 0 failures.
- **Files changed:** ~15 files (7 algorithm files, 3 library/infrastructure files, 1 packaging script, 1 standalone plugin, 1 shim, 1 docs file, 1 test data script)
