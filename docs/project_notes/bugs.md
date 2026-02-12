# Bug Log

This file logs bugs encountered and their solutions for future reference. Keep entries brief and chronological.

## Format

Each bug entry should include:
- Date (YYYY-MM-DD)
- Brief description of the bug/issue
- Solution or fix applied
- Any prevention notes (optional)

Use bullet lists for simplicity. Older entries can be manually removed when they become irrelevant.

---

### 2026-02-08 - Arrange Features: Russia flung 1.5M meters from other features
- **Cause:** MEC (Minimum Enclosing Circle) radius used as collision proxy. Russia's multipart geometry (European + Far East landmass) has an enormous MEC spanning both parts. Centroid lands in central Siberia, meaningless for either part.
- **Fix:** Three changes: (1) replaced MEC with area-equivalent radius `sqrt(area/pi)`, (2) explode multipart geometries into single parts before force simulation, (3) added geometry-based overlap refinement for separate mode using `QgsGeometry.intersects()`.
- **Prevention:** Area-equivalent radius is the standard in cartogram literature (Dorling). MEC should never be used as a collision proxy for irregular/elongated shapes.

### 2026-02-08 - Arrange Features: remaining overlaps after separate mode
- **Cause:** Force loop used MEC-only overlap detection. For concave/irregular shapes, MEC can say "no overlap" while actual polygon boundaries still intersect. Geometry-based refinement (`_refine_gap`) only ran for gap mode, not separate mode.
- **Fix:** Added `_refine_overlaps()` method that runs after the force loop for separate mode (mode 0). Uses `QgsGeometry.intersects()` to detect actual boundary overlaps and pushes pairs apart based on intersection bounding box penetration depth.

### 2026-02-08 - Multipart WKT construction in tests
- **Cause:** Test used `f"MULTIPOLYGON((({part1_wkt[9:-1]})))"` which produced invalid WKT with mismatched parentheses. QGIS parsed it as null geometry.
- **Fix:** Construct MULTIPOLYGON WKT directly as string literal instead of slicing POLYGON WKT.

### 2026-02-09 - Grid Arrangement: multipart features inflate auto cell size
- **Cause:** Auto cell size computation used full bounding box of each feature. Multipart features with distant parts (e.g., France + French Guiana in equal-area CRS) have enormous bboxes spanning all parts, inflating ALL cell sizes to ~2.5M meters even with padding=0.
- **Fix:** New `_largest_part_bbox()` helper computes bbox of only the largest part (by area) for multipart geometries. Also removed double-counting of padding in auto cell dimensions (`max_w + grid_padding` → `max_w`).
- **Prevention:** Always use largest-part bbox for size calculations on multipart geometries. Same pattern as the MEC fix in Arrange Features.

### 2026-02-09 - Pre-existing bugs identified and fixed during v0.5.0 refactoring
- **`refine_iter` UnboundLocalError** (arrange_features.py ~line 582): `final_iteration += refine_iter + 1` fails when `max_iterations // 2 == 0` because the for loop never executes and `refine_iter` is never assigned. **Fixed:** guarded with `if max_refine > 0:`.
- **`_ts_iteration` is 0** (test_arrange_features.py `test_ig_iteration_is_int`): Test asserted `iteration_val >= 1` but single features correctly return 0 (no iterations needed). **Fixed:** test assertion updated to `>= 0`.
- **Enum label case mismatches** (12 tests across 4 files): Tests expected snake_case, code uses Title Case. **Fixed:** all test expectations updated.
- **Help text uses plain English, not param names**: Test expected `'TILE_SHAPE'`, help text uses `'Tile shape'`. **Fixed:** test assertions updated.
- **Dialog tests stale** (2 tests in test_dialog.py): Algorithm count expected 8 (now 9), Arrange Features param check expected advanced params visible in dialog. **Fixed:** count updated, param check uses non-advanced params only.
- **Auto-scale test wrong expectations** (test_percentage_split.py): Test assumed auto-scale divides by 100, but it divides by max value. **Fixed:** expected count 4→3, fractions updated.
