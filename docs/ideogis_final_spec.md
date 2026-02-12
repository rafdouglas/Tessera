# IdeoGIS — Final Implementation Specification

**Version:** 2.0 (post-review)
**Date:** 2026-02-07
**Status:** Ready for implementation

This is the sole authoritative reference for implementing IdeoGIS. It supersedes all previous spec versions, review documents, and handoff notes.

---

## 1. What IdeoGIS Is

IdeoGIS is a suite of QGIS plugins for creating cartographic ideograms — thematic maps where geographic shapes are modified, filled, replaced, or rearranged to communicate quantitative data visually.

**Target users:** Cartographers, GIS analysts, data journalists, designers.

**Distribution:** Three QGIS plugins sharing a common library:

| Plugin | Algorithms | Standalone? |
|--------|-----------|-------------|
| **IdeoGIS** (main) | All 9 algorithms | No — full toolkit |
| **Percentage Split** | 1 algorithm | Yes — self-contained |
| **Stripe Hatching** | 1 algorithm | Yes — self-contained |

The two standalone plugins vendor the shared library so they have zero dependencies on the main plugin. Users who only need one tool don't install the full suite. Each standalone's metadata says: *"Part of the IdeoGIS cartographic toolkit. For the full suite of 9 algorithms, install IdeoGIS."*

**Dependencies:** None beyond what QGIS 3.28+ bundles (PyQt5, qgis.core, qgis.gui, GEOS via QgsGeometry). No pip install required.

---

## 2. Repository Structure

```
ideogis/
├── lib/
│   └── ideogis_common/
│       ├── __init__.py
│       ├── crs_manager.py           # CRS detection, reprojection context manager
│       ├── feature_builder.py       # Consistent output feature/layer construction
│       └── geometry_helpers.py      # split_polygon_by_fraction, extract_polygons, etc.
│
├── plugins/
│   ├── ideogis/                     # Main plugin — all 9 algorithms
│   │   ├── __init__.py              # classFactory entry point
│   │   ├── plugin.py                # IdeoGISPlugin: toolbar, menu, dialog launcher
│   │   ├── metadata.txt
│   │   ├── resources/
│   │   │   ├── icon.png
│   │   │   └── styles/              # Shipped .qml style presets
│   │   ├── infrastructure/
│   │   │   ├── __init__.py
│   │   │   ├── crs_manager.py       # → symlink or copy from lib/
│   │   │   ├── feature_builder.py   # → symlink or copy from lib/
│   │   │   ├── geometry_helpers.py  # → symlink or copy from lib/
│   │   │   ├── topology_wrapper.py  # Main-only: shared-edge topology
│   │   │   └── grid_generators.py   # Main-only: hex, square, triangle grids
│   │   ├── algorithms/
│   │   │   ├── __init__.py
│   │   │   ├── base_algorithm.py
│   │   │   ├── percentage_split.py
│   │   │   ├── tessellate.py
│   │   │   ├── stripe_hatching.py
│   │   │   ├── snap_to_grid.py
│   │   │   ├── sketchy_borders.py
│   │   │   ├── simplify_to_grid_cells.py
│   │   │   ├── scale_by_value.py
│   │   │   ├── replace_with_shape.py
│   │   │   └── resolve_overlaps.py
│   │   ├── ui/
│   │   │   ├── __init__.py
│   │   │   └── main_dialog.py
│   │   └── processing_provider.py
│   │
│   ├── percentage_split/            # Standalone plugin
│   │   ├── __init__.py
│   │   ├── plugin.py
│   │   ├── metadata.txt
│   │   ├── infrastructure/          # Vendored from lib/ideogis_common
│   │   │   ├── __init__.py
│   │   │   ├── crs_manager.py
│   │   │   ├── feature_builder.py
│   │   │   └── geometry_helpers.py
│   │   ├── algorithm.py             # The algorithm itself
│   │   └── processing_provider.py
│   │
│   └── stripe_hatching/             # Standalone plugin
│       ├── __init__.py
│       ├── plugin.py
│       ├── metadata.txt
│       ├── infrastructure/          # Vendored from lib/ideogis_common
│       │   ├── __init__.py
│       │   ├── crs_manager.py
│       │   ├── feature_builder.py
│       │   └── geometry_helpers.py
│       ├── algorithm.py
│       └── processing_provider.py
│
├── scripts/
│   ├── package.py                   # Vendors lib/ into standalone plugins, creates ZIPs
│   └── download_test_data.py        # Downloads Natural Earth 110m if not present
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                  # Shared fixtures: sample layers, geometries
│   ├── test_data/                   # Natural Earth 110m countries (user-provided)
│   ├── test_crs_manager.py
│   ├── test_topology_wrapper.py
│   ├── test_grid_generators.py
│   ├── test_geometry_helpers.py
│   └── test_<algorithm>.py          # One test file per algorithm
│
└── README.md
```

**Build process** (`scripts/package.py`):
1. Copy `lib/ideogis_common/*.py` into each standalone plugin's `infrastructure/` folder
2. Copy `lib/ideogis_common/*.py` into the main plugin's `infrastructure/` folder
3. ZIP each plugin directory for QGIS plugin manager upload

During development, the main plugin's `infrastructure/` can import from `lib/` directly. The vendoring only happens at package time.

---

## 3. Output Data Contract

Every algorithm produces a polygon (or multi-polygon) output with:

- All original attribute fields from the input layer carried forward.
- Metadata fields prefixed with `_ig_` to avoid collisions:

| Field | Type | Present in | Description |
|---|---|---|---|
| `_ig_algorithm` | String | all outputs | Algorithm id, e.g. `"percentage_split"` |
| `_ig_parent_fid` | Integer | all outputs | Feature id from input layer |
| `_ig_part` | String | percentage_split | `"filled"` or `"remainder"` |
| `_ig_value` | Double | percentage_split, scale_by_value, replace_with_shape | Raw attribute value |
| `_ig_fraction` | Double | percentage_split, tessellate | Computed fraction (0–1) |
| `_ig_state` | String | tessellate | `"on"` or `"off"` |
| `_ig_tile_index` | Integer | tessellate, simplify_to_grid_cells | Sequential tile index |
| `_ig_stripe_index` | Integer | stripe_hatching | Sequential stripe index |
| `_ig_scale_factor` | Double | scale_by_value, replace_with_shape | Computed scale factor |
| `_ig_iteration` | Integer | resolve_overlaps | Final iteration count |

Algorithms only add the fields they use. `_ig_algorithm` and `_ig_parent_fid` are always present.

Output geometry type is always **MultiPolygon** (promote single polygons). Output CRS always matches input layer CRS.

### Parameter Naming Conventions

All parameters use UPPER_SNAKE_CASE for Processing compatibility. Common names shared across algorithms use identical names for graphical modeler auto-wiring:

- `INPUT` — input polygon layer
- `OUTPUT` — output polygon layer
- `VALUE_FIELD` — numeric attribute field driving the visualization
- `ORIENTATION` — direction enum where applicable
- `GRID_TYPE` — square / hexagonal / triangular
- `CELL_SIZE` — grid cell size in map units (0 = auto)

---

## 4. Shared Infrastructure

### 4.1 CRS Manager (`crs_manager.py`)

**Purpose:** Transparently reproject input geometries into an appropriate working CRS for area/distance calculations, and reproject results back.

**Interface:**

```python
class WorkingCRS:
    """Context manager for CRS operations.

    Must be instantiated inside processAlgorithm() — QgsCoordinateTransform
    is NOT thread-safe and must not be shared across threads.
    """

    def __init__(self, source_crs, layer_extent, strategy="equal_area"):
        # strategy: "equal_area" | "equidistant" | "preserve"

    def forward(self, geometry):
        # Transform from source CRS to working CRS

    def inverse(self, geometry):
        # Transform from working CRS back to source CRS

    @property
    def working_crs(self):
        # The chosen working CRS (read-only)
```

**CRS Selection Logic:**

1. If strategy is `"preserve"`: working CRS = source CRS. No transforms.
2. If source CRS is already projected and equal-area: use it directly.
   **Equal-area detection** — parse the proj string:
   ```python
   EQUAL_AREA_PROJS = {'aea', 'laea', 'cea', 'eqearth', 'moll', 'sinu', 'eck4', 'eck6'}

   def is_equal_area(crs):
       if crs.isGeographic():
           return False
       for part in crs.toProj().split():
           if part.startswith('+proj='):
               return part.split('=')[1] in EQUAL_AREA_PROJS
       return False
   ```
   Do NOT rely on `isGeographic()` alone — it only distinguishes projected vs geographic, says nothing about area preservation.
3. If layer extent is global (width > 90° or height > 60°): use Equal Earth (EPSG:8857).
4. If latitude extent exceeds 30°: use Equal Earth (EPSG:8857). Local Albers has 5-10% area distortion at the edges of hemispheric data.
5. Otherwise: construct a local Albers Equal Area using **Snyder's 1/6 rule**:
   ```python
   lat_range = extent.yMaximum() - extent.yMinimum()
   lat_1 = extent.yMinimum() + lat_range / 6
   lat_2 = extent.yMaximum() - lat_range / 6
   lat_0 = (extent.yMinimum() + extent.yMaximum()) / 2
   lon_0 = (extent.xMinimum() + extent.xMaximum()) / 2

   proj_string = (
       f"+proj=aea +lat_1={lat_1} +lat_2={lat_2} "
       f"+lat_0={lat_0} +lon_0={lon_0} "
       f"+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
   )
   ```
   Create with `QgsCoordinateReferenceSystem.createFromProj()` (instance method returning bool). Do NOT use `createFromProj4()` — removed in QGIS 3.30. Always check `crs.isValid()` after creation.

**Antimeridian Handling:**

Before projecting, detect and split geometries that cross the antimeridian. Do this while geometry is still in EPSG:4326, before any CRS transformation.

Detection — check consecutive-vertex longitude jumps:
```python
def needs_antimeridian_split(geometry):
    for ring in all_rings(geometry):
        for i in range(len(ring) - 1):
            if abs(ring[i+1].x() - ring[i].x()) > 180:
                return True
    return False
```

Splitting — use intersection with half-plane rectangles:
```
1. Normalize all longitudes to [0, 360] range
2. Western part: intersection with rect(0, -90, 180, 90)
3. Eastern part: intersection with rect(180, -90, 360, 90), then shift x by -360
```

Do NOT use `splitGeometry()` — it modifies geometry in-place, handles MultiPolygons poorly, and can fail when vertices lie exactly on the meridian.

**Edge Cases:**
- Empty geometry: return empty geometry (no transform needed).
- Null geometry: return null.
- Point/line geometry: reject with a clear error — IdeoGIS requires polygon input.

**Thread Safety:** `QgsCoordinateTransform` is NOT thread-safe. `WorkingCRS` must be instantiated inside each `processAlgorithm()` call. Pass `QgsCoordinateReferenceSystem` objects (thread-safe value types) and `QgsCoordinateTransformContext` (thread-safe since 3.8).


### 4.2 Topology Wrapper (`topology_wrapper.py`) — Main Plugin Only

**Purpose:** For algorithms that modify polygon vertices (snap to grid, sketchy borders), ensure that shared boundaries are transformed consistently so no gaps or overlaps are introduced.

**When Active:** Only when an algorithm declares `topology_aware = True`. Other algorithms bypass this entirely.

**Interface:**

```python
class TopologyTransformer:
    """Handles topology-preserving vertex transformations."""

    SNAP_TOLERANCE = 1e-6  # 1 micrometer, projected CRS units (meters)

    def __init__(self, features, feedback):
        # Builds the shared vertex index AND shared edge index.
        # Assert that working CRS is projected.

    def densify_shared_edges(self, interval):
        # For sketchy borders: densify shared edges identically using
        # canonical direction (smaller-x vertex first, then smaller-y).
        # Private edges: use densifyByDistance() directly.
        # Must be called BEFORE transform().

    def transform(self, vertex_fn):
        # Applies vertex_fn to every unique vertex exactly once.
        # vertex_fn signature: (QgsPointXY, int) -> QgsPointXY
        #   where int is the unique vertex_id (for deterministic seeding).
        # Returns new features with same attributes, modified geometry.
```

**Internal Algorithm:**

**Phase 0 — T-Junction Detection:**

Before building the vertex index, detect and repair T-junctions (where a vertex of polygon A lies on an edge of polygon B, but B has no vertex there).

Build a **grid-based spatial hash** on edges (NOT `QgsSpatialIndex`, which indexes features, not edges):
- Cell size: `max(extent_width, extent_height) / 1000`
- For each vertex V of each feature, query the grid for nearby edges from other features
- If V lies within SNAP_TOLERANCE of an edge E (and is not near E's endpoints — guard with `t ∈ (tolerance, 1-tolerance)` on the edge parameter), insert V into E

Performance: ~3-5 seconds for GADM admin-1 (~500K vertices, ~500K edges).

**Phase 1 — Unique Vertex Extraction:**

1. Iterate all features, all rings (exterior + holes), all vertices.
2. Round each vertex coordinate to SNAP_TOLERANCE (1e-6 meters) to handle floating-point near-duplicates.
3. Build a dict: `{rounded_vertex: unique_id}`.
4. Build a reverse index: `{unique_id: [list of (feature_index, ring_index, vertex_index)]}`.
5. Vertices referenced by 2+ features are "shared." Single-feature vertices are "private."

Use `asMultiPolygon()` pattern to extract all vertices in one C++ call (~2-5μs per vertex processing in Python).

**Phase 2 — Transform:**

For each unique vertex, call `vertex_fn(original_point, unique_id)` exactly once. Store the result. Shared vertices get identical transformations.

**Phase 3 — Rebuild:**

1. For each feature, reconstruct all rings using transformed vertex positions.
2. Ensure rings are properly closed (last point = first point).
3. Validate each rebuilt geometry using the repair chain:
   a. Check `area() > 0` AND `area > 0.01 * original_area`
   b. If invalid: try `buffer(0)` (faster, preserves area, never produces non-polygon types)
   c. If still invalid: try `makeValid()` (handles bowties, but can split into MultiPolygon)
   d. If still invalid: keep original geometry, log warning
4. Collect `makeValid()` multi-part results into a single MultiPolygon per feature.

**Shared Edge Tracking (for densification):**

The `densify_shared_edges()` method requires edge-level, not just vertex-level, coordination:

1. Pre-densification: identify shared edges by matching vertex pairs across features (same grid-based spatial hash as T-junction detection).
2. For each shared edge pair (E_i in polygon A, E_j in polygon B):
   - Compute length L (same for both since endpoints match)
   - Use canonical direction: always from the vertex with smaller x (then smaller y for ties)
   - Compute n_new = floor(L / interval), insert n_new equally-spaced intermediate vertices
   - Insert identical vertices into both polygons
3. Private edges: densify with `QgsGeometry.densifyByDistance(interval)`.
4. After densification, build the Phase 1 vertex index on the densified geometries.

**Limitations:**
- Designed for layers with **< 1,000 features**. For larger layers (GADM admin-1), processing takes minutes.
- Assumes input layer has no pre-existing gaps or overlaps. If it does, they are preserved.


### 4.3 Grid Generators (`grid_generators.py`) — Main Plugin Only

**Purpose:** Generate regular point grids and cell grids for tessellation, snapping, and simplification.

**Functions:**

```python
def generate_point_grid(extent, spacing, grid_type):
    # grid_type: "square" | "hexagonal" | "triangular"
    # Returns grid intersection points covering the extent.

def generate_cell_polygons(extent, spacing, grid_type):
    # Returns the actual cell polygons covering the extent.

def nearest_grid_point(point, spacing, grid_type):
    # Returns the nearest grid intersection to the given point.

def auto_cell_size(extent, target_count):
    # Compute a cell size yielding approximately target_count cells.
```

**Definitions:**

For all grid types, `cell_size` (the `spacing` parameter) is defined as follows:
- **Square:** Side length of each cell. Center-to-center distance = cell_size.
- **Hexagonal (flat-top):** Flat-to-flat height of each hexagon (vertical distance between hex centers in the same column). Circumradius R = cell_size / √3.
- **Triangular:** Side length of each equilateral triangle.

**Square Grid:**

Points at `(x0 + i*s, y0 + j*s)` for integer `i, j`.
Cells are axis-aligned squares of side `s`.
`nearest_grid_point`: round to nearest `(n*s, m*s)`.

**Hexagonal Grid (flat-top):**

Using circumradius R = cell_size / √3, the standard axial-to-pixel formulas:

```python
# Hex center at axial coordinates (q, r):
x = R * 3/2 * q
y = R * sqrt(3) * (r + q/2)

# Column spacing = 3R/2 = cell_size * sqrt(3) / 2
# Row spacing = R * sqrt(3) = cell_size
# Odd columns offset vertically by cell_size / 2
```

Hex vertices (flat-top, circumradius R) at angles 0°, 60°, 120°, 180°, 240°, 300°:
```
(R, 0), (R/2, R√3/2), (-R/2, R√3/2), (-R, 0), (-R/2, -R√3/2), (R/2, -R√3/2)
```

`nearest_grid_point` for hex grid — complete algorithm:

```python
def nearest_hex_point(px, py, cell_size):
    R = cell_size / sqrt(3)
    # Pixel to fractional axial coordinates
    q_frac = (2/3 * px) / R
    r_frac = (-1/3 * px + sqrt(3)/3 * py) / R
    # Axial to cube coordinates
    x, z = q_frac, r_frac
    y = -x - z
    # Round to nearest integer cube coordinates
    rx, ry, rz = round(x), round(y), round(z)
    # Fix rounding to maintain x + y + z = 0
    dx, dy, dz = abs(rx - x), abs(ry - y), abs(rz - z)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy > dz:
        ry = -rx - rz
    else:
        rz = -rx - ry
    # Convert back to pixel coordinates
    return QgsPointXY(R * 3/2 * rx, R * sqrt(3) * (rz + rx / 2))
```

**Triangular Grid:**

Row height = cell_size * √3 / 2. Triangles alternate up-pointing (▲) and down-pointing (▽).

`nearest_grid_point` for triangular grid — uses barycentric approach:

```python
def nearest_tri_point(px, py, cell_size):
    s = cell_size
    h = s * sqrt(3) / 2
    # Determine which row
    row = floor(py / h)
    # Fractional position within row
    ty = (py - row * h) / h
    # Determine column (accounting for row offset)
    tx = px / (s / 2)
    col = floor(tx)
    # Determine if up or down triangle
    # In each parallelogram (col, row), the diagonal divides up from down
    frac_x = tx - col
    if (col + row) % 2 == 0:
        is_up = (ty < 1 - frac_x)
    else:
        is_up = (ty < frac_x)
    # Compute centroid of the identified triangle
    if is_up:
        cx = (col + 2/3) * s / 2
        cy = (row + 1/3) * h
    else:
        cx = (col + 1/3) * s / 2
        cy = (row + 2/3) * h
    return QgsPointXY(cx, cy)
```

**Auto Cell Size:**

```python
def auto_cell_size(extent, target_count):
    area = extent.width() * extent.height()
    raw = sqrt(area / target_count)
    # Packing factor adjusts for how efficiently shapes tile the plane
    # Derived from: cell_area * count ≈ total_area
    PACKING = {
        'square': 1.0,        # cell_area = s²
        'hexagonal': 1.07,    # cell_area = (√3/2)·s², factor = 1/√(√3/2)
        'circle': 1.07,       # hex-packed circles, same as hex
        'triangular': 1.52,   # cell_area = (√3/4)·s², factor = 2/3^(1/4)
    }
    return raw * PACKING.get(grid_type, 1.0)
```


### 4.4 Feature Builder (`feature_builder.py`)

**Purpose:** Consistently construct output features so all algorithms produce compatible outputs.

**Functions:**

```python
def create_output_fields(input_fields, extra_fields):
    # Merges input fields with _ig_* metadata fields.
    # extra_fields: List[Tuple[str, QVariant.Type]]
    # Handles name collisions (if input already has _ig_* fields, overwrite).

def build_feature(geometry, parent_feature, algorithm_id, extra_attrs, output_fields,
                  carry_all_attributes=True):
    # Creates a QgsFeature with:
    #   - geometry promoted to MultiPolygon
    #   - parent attributes copied (if carry_all_attributes)
    #   - _ig_algorithm set
    #   - _ig_parent_fid set to parent's id
    #   - extra_attrs written to appropriate fields
```

**No `create_memory_layer()` in public API.** The Processing framework creates the output destination (memory layer or file) via `QgsProcessingParameterFeatureSink`. If an intermediate memory layer is needed internally, create it locally within the algorithm — but output always goes through the sink.

**Geometry Promotion Rule:** All output geometries are promoted to MultiPolygon. If Polygon, wrap in Multi. If already Multi, keep. If empty, emit empty MultiPolygon.


### 4.5 Geometry Helpers (`geometry_helpers.py`)

**Purpose:** Small reusable geometric functions shared across all plugins (main + standalones).

**Functions:**

```python
def extract_polygons(geom):
    """Extract only polygon components, discarding points and lines.

    CRITICAL: Use after EVERY intersection(), difference(), and clipped() call.
    These operations can return GeometryCollection with degenerate components
    when the operation boundary passes through vertices.
    """
    if geom.isEmpty():
        return geom
    if geom.type() == QgsWkbTypes.PolygonGeometry:
        return geom
    collection = geom.asGeometryCollection()
    polys = [g for g in collection if g.type() == QgsWkbTypes.PolygonGeometry]
    return QgsGeometry.unaryUnion(polys) if polys else QgsGeometry()


def split_polygon_by_fraction(geom, fraction, orientation):
    # Returns (filled_geom, remainder_geom). See §5.1 for details.

def safe_pole_of_inaccessibility(geom, tolerance=1.0):
    """poleOfInaccessibility() with MultiPolygon bug workaround.

    QGIS 3.28-3.30 only considers the first part of a MultiPolygon.
    This function decomposes and returns the best pole.
    """
    if geom.isMultipart():
        parts = geom.asGeometryCollection()
        best_pole, best_dist = None, -1
        for part in parts:
            pole, dist = part.poleOfInaccessibility(tolerance)
            if dist > best_dist:
                best_pole, best_dist = pole, dist
        return best_pole, best_dist
    return geom.poleOfInaccessibility(tolerance)

def scale_geometry(geom, factor, center):
    # Scale geom by factor around center. Iterate all vertices:
    #   new_vertex = center + (old_vertex - center) * factor

def regular_polygon(center, size, n_sides, rotation):
    # Create a regular polygon centered at center with circumradius = size.
    # rotation in degrees (0 = first vertex points east).

def clamp(value, lo, hi):
    # min(max(value, lo), hi)
```

---

## 5. Algorithm Specifications

Each algorithm documents: purpose, parameters, geometric logic, infrastructure used, topology awareness, output schema, and edge cases.


### 5.1 Percentage Split

**Id:** `percentage_split`
**Group:** Fill
**Topology-aware:** No
**Plugin:** Main + Standalone

**Purpose:** Split each input polygon into two sub-polygons whose area ratio corresponds to a numeric attribute value.

**Parameters:**

| Name | Type | Default | Constraints | Description |
|---|---|---|---|---|
| INPUT | VectorLayer (Polygon) | — | required | Input polygon layer |
| VALUE_FIELD | Field (numeric) | — | required, parent=INPUT | Attribute field with values |
| VALUE_RANGE | Enum | 0 | 0="0–100", 1="0–1", 2="auto-detect" | How to interpret field values |
| ORIENTATION | Enum | 0 | 0=horizontal, 1=vertical, 2=diagonal_45, 3=diagonal_135, 4=radial | Direction of the split line |
| FILLED_COLOR | Color | #3b82f6 | optional, **FlagAdvanced** | Hint for default styling |
| REMAINDER_COLOR | Color | #ef4444 | optional, **FlagAdvanced** | Hint for default styling |
| OUTPUT | FeatureSink | — | required | Output layer |

**Geometric Logic:**

For each input feature:
1. Read the attribute value. Convert to fraction (0–1) based on VALUE_RANGE.
   - For "auto-detect": if max(field) > 1, assume percentage, divide by 100.
2. If fraction ≤ 0: emit only remainder. If ≥ 1: emit only filled.
3. Transform geometry to working CRS (equal area).
4. Call `split_polygon_by_fraction(geom, fraction, orientation)`.
5. Transform both parts back to source CRS.
6. Write two features to sink: `_ig_part = "filled"` / `"remainder"`.

**`split_polygon_by_fraction` — detailed algorithm:**

**Horizontal (bottom-to-top):**
1. Get bounding box. Sweep parameter `t ∈ [0, 1]` where `t = 0` is `ymin`, `t = 1` is `ymax`.
2. Binary search for `t` such that `area(geom ∩ rect_below) / area(geom) ≈ fraction`.
3. For horizontal/vertical: use `QgsGeometry.clipped(QgsRectangle)` — **5-10x faster** than general `intersection()`. Falls back to `intersection()` if `clipped()` result is suspicious (area validation).
4. The clipping rectangle extends beyond the polygon by `pad = bbox_diagonal` (cap at 1× diagonal to avoid float precision loss).
5. **Early termination:** Stop when `|computed_fraction - target| < 1e-4` (0.01% tolerance). Typically converges in 15-25 iterations, not 50.
6. **Remainder computation:** `remainder = extract_polygons(geom.difference(halfplane))` — NOT `geom.difference(filled)`. Both operations must node against the same clipping geometry to avoid micro-gaps.
7. After every `intersection()`, `clipped()`, and `difference()` call: apply `extract_polygons()` to discard degenerate components (points, lines).
8. After every `intersection()` / `clipped()`: check `geom.lastError()`. A GEOS noding failure returns empty geometry with no exception — the binary search would silently converge to the wrong position.

**Vertical (left-to-right):** Same but sweep `x_cut` from `xmin` to `xmax`.

**Diagonal (arbitrary angle θ):**
The half-plane is `{x : n · x ≤ d}` where `n = (cos θ, sin θ)`.
Construct a clipping polygon: four corners forming a rectangle extending `pad = bbox_diagonal` behind the sweep line and perpendicular to it.
Binary search on `d` from `d_min = min(n · v)` to `d_max = max(n · v)` over all vertices.
Snap angles within 0.1° of 0/90/180 to exact values; skip rotation for axis-aligned cases to avoid floating-point slivers.

**Radial (center-out):**
1. Compute center using `safe_pole_of_inaccessibility(geom)` — NOT centroid. For concave polygons, centroid can lie outside the polygon, causing the fill circle to not intersect the polygon at small fractions.
2. Binary search for radius `r` such that `area(geom ∩ circle(center, r)) / area(geom) ≈ fraction`.
3. Circle approximated with 64 segments.
4. **Known limitation for multi-polygons:** Radial fill starts from the mainland and only reaches islands at larger radii. Document this and recommend horizontal/vertical for archipelago features.

**Repair:** Do NOT apply `makeValid()` to Percentage Split output — it can corrupt the intended area ratio. Use `buffer(0)` → original only.

**Edge Cases:**
- Multi-polygons: GEOS intersection/difference handle natively.
- Polygons with holes: GEOS handles correctly.
- Fraction exactly 0 or 1: skip binary search, emit only one part.
- Null/missing values: skip feature, log warning.

**Output Fields:** All input fields + `_ig_algorithm`, `_ig_parent_fid`, `_ig_part`, `_ig_value`, `_ig_fraction`.


### 5.2 Tessellate

**Id:** `tessellate`
**Group:** Fill
**Topology-aware:** No
**Plugin:** Main only

**Purpose:** Fill each input polygon with a regular grid of small tile shapes. Each tile becomes a separate output feature linked to its parent. Tiles inherit all parent attributes. No coloring logic — the user styles tiles using QGIS's native renderers.

**Parameters:**

| Name | Type | Default | Constraints | Description |
|---|---|---|---|---|
| INPUT | VectorLayer (Polygon) | — | required | |
| TILE_SHAPE | Enum | 0 | 0=hexagon, 1=square, 2=circle, 3=triangle | Shape of each tile |
| CELL_SIZE | Number (float) | 0 | min=0 | Tile spacing in working CRS units. 0 = auto |
| TARGET_TILES | Number (int) | 200 | min=10, max=10000 | Approx tiles per feature when CELL_SIZE=0 |
| CLIP_BOUNDARY | Boolean | True | | If True, clip tiles at polygon boundary. If False, keep only centroid-inside tiles (unclipped). |
| OUTPUT | FeatureSink | — | required | |

**Geometric Logic:**

For each input feature:
1. Transform geometry to working CRS.
2. Compute cell size:
   - If CELL_SIZE > 0: use directly.
   - If CELL_SIZE = 0: `auto_cell_size(feature_bbox, TARGET_TILES)`.
3. Generate grid points over the feature's bounding box (plus one cell of padding for boundary coverage).
4. For each grid point:
   a. Generate tile geometry at that point.
      - Hexagon: circumradius = `cell_size / √3`.
      - Square: side = `cell_size`.
      - Circle: radius = `cell_size * 0.45`.
      - Triangle: side = `cell_size`.
   b. If CLIP_BOUNDARY is True:
      - `tile_result = extract_polygons(tile_geom.intersection(polygon_geom))`
      - If empty or zero area: skip.
   c. If CLIP_BOUNDARY is False:
      - Check if grid point is inside polygon. Skip if not.
5. Transform each tile back to source CRS.
6. Write features to sink in batches (1,000-5,000 for progress reporting). Do NOT add one at a time.

**Tile Indexing:** `_ig_tile_index` starting from 0, bottom-to-top, left-to-right within each parent polygon.

**Performance:** For 200 countries × 200 tiles = 40,000 features: ~2-5 seconds with batched `addFeatures()`. Memory ~44 MB. If total output exceeds 50,000 features, emit a feedback warning (QGIS rendering can become unresponsive).

**Edge Cases:**
- Very small polygons: may produce 0 tiles. Log warning.
- Multi-polygons: generate grid over full bbox, test containment per part.

**Output Fields:** All input fields + `_ig_algorithm`, `_ig_parent_fid`, `_ig_tile_index`.


### 5.3 Stripe Hatching

**Id:** `stripe_hatching`
**Group:** Fill
**Topology-aware:** No
**Plugin:** Main + Standalone

**Purpose:** Fill each polygon with parallel stripes at a configurable angle.

**Parameters:**

| Name | Type | Default | Constraints | Description |
|---|---|---|---|---|
| INPUT | VectorLayer (Polygon) | — | required | |
| ANGLE | Number (float) | 0 | min=0, max=180 | 0=horizontal, 90=vertical |
| STRIPE_WIDTH | Number (float) | 0 | min=0 | 0 = auto |
| GAP_WIDTH | Number (float) | 0 | min=0 | 0 = same as STRIPE_WIDTH |
| TARGET_STRIPES | Number (int) | 10 | min=2, max=100 | Target stripes when STRIPE_WIDTH=0 |
| OUTPUT | FeatureSink | — | required | |

**Geometric Logic:**

For each input feature:
1. Transform to working CRS.
2. Compute stripe width: if 0, measure extent perpendicular to stripe angle, divide by `(TARGET_STRIPES * 2 - 1)`.
3. Gap width: if 0, use STRIPE_WIDTH.
4. Snap angles within 0.1° of 0/90/180 to exact values. For axis-aligned cases, skip rotation entirely.
5. For non-axis-aligned: rotate polygon by `-ANGLE`, generate parallel rectangles in rotated coords, rotate back.
6. Intersect each stripe rectangle with polygon. Apply `extract_polygons()` to each result.
7. Transform back to source CRS.

**Stripe Ordering:** `_ig_stripe_index` from 0, starting from the "lowest" side perpendicular to the stripe angle.

**Output Fields:** All input fields + `_ig_algorithm`, `_ig_parent_fid`, `_ig_stripe_index`.


### 5.4 Snap to Grid

**Id:** `snap_to_grid`
**Group:** Shape
**Topology-aware:** Yes
**Plugin:** Main only

**Purpose:** Move every vertex toward the nearest regular grid intersection. Shared boundaries are snapped consistently via the topology wrapper.

**Parameters:**

| Name | Type | Default | Constraints | Description |
|---|---|---|---|---|
| INPUT | VectorLayer (Polygon) | — | required | |
| GRID_TYPE | Enum | 1 | 0=square, 1=hexagonal, 2=triangular | |
| CELL_SIZE | Number (float) | 0 | min=0 | 0 = auto |
| AUTO_CELLS_ACROSS | Number (int) | 30 | min=5, max=200 | Target cells across extent when CELL_SIZE=0 |
| ATTRACTION | Number (float) | 1.0 | min=0.0, max=1.0 | 0=no snap, 1=full snap |
| OUTPUT | FeatureSink | — | required | |

**Geometric Logic:**

1. Transform all features to working CRS.
2. Cell size: if 0, `min(extent_width, extent_height) / AUTO_CELLS_ACROSS`.
3. ATTRACTION = 0: short-circuit, copy features as-is.
4. Construct vertex transform:
   ```python
   def snap_vertex(point, vertex_id):
       target = nearest_grid_point(point, cell_size, grid_type)
       new_x = point.x() + (target.x() - point.x()) * attraction
       new_y = point.y() + (target.y() - point.y()) * attraction
       return QgsPointXY(new_x, new_y)
   ```
5. Pass to `TopologyTransformer.transform()`.
6. Post-validation: check `area() > 0` AND `area > 0.01 * original_area`. If either fails, keep original geometry. (The simple "ring < 4 points" check misses collinear-vertex degeneracy.)
7. Transform back to source CRS.

**Fast path:** When GRID_TYPE=square and ATTRACTION=1.0, `QgsGeometry.snappedToGrid()` (C++ implementation) can be used instead of Python vertex iteration. Still wrap with topology transformer for shared vertices.

**Output Fields:** All input fields + `_ig_algorithm`, `_ig_parent_fid`.


### 5.5 Sketchy Borders

**Id:** `sketchy_borders`
**Group:** Shape
**Topology-aware:** Yes
**Plugin:** Main only

**Purpose:** Give polygon boundaries a hand-drawn appearance via densify + jitter.

**Parameters:**

| Name | Type | Default | Constraints | Description |
|---|---|---|---|---|
| INPUT | VectorLayer (Polygon) | — | required | |
| ROUGHNESS | Number (float) | 0.5 | min=0.0, max=1.0 | Displacement magnitude. 0=none, 1=max |
| DENSIFY_FACTOR | Number (float) | 3.0 | min=1.0, max=20.0 | Intermediate vertices per edge |
| SEED | Number (int) | 42 | min=0 | Random seed for reproducibility |
| OUTPUT | FeatureSink | — | required | |

**Geometric Logic:**

1. Transform all features to working CRS.
2. ROUGHNESS = 0: short-circuit.
3. `max_displacement = ROUGHNESS * 0.01 * min(extent_width, extent_height)`.
4. Densify topology-aware: call `TopologyTransformer.densify_shared_edges(interval)` where `interval = max_displacement * DENSIFY_FACTOR`.
5. Construct jitter function using **hash-based displacement** (not `Random()` per vertex — 10x faster):
   ```python
   def jitter_vertex(point, vertex_id):
       u1 = vertex_hash(vertex_id, SEED, 0)
       u2 = vertex_hash(vertex_id, SEED, 1)
       # Box-Muller transform for Gaussian distribution
       sigma = max_displacement / 3  # 3-sigma ≈ max_displacement
       dx = sqrt(-2 * log(u1)) * cos(2 * pi * u2) * sigma
       dy = sqrt(-2 * log(u1)) * sin(2 * pi * u2) * sigma
       return QgsPointXY(point.x() + dx, point.y() + dy)

   def vertex_hash(vertex_id, seed, component):
       h = vertex_id * 2654435761 + seed * 2246822519 + component * 3266489917
       h = ((h >> 16) ^ h) * 0x45d9f3b
       h = ((h >> 16) ^ h) * 0x45d9f3b
       h = (h >> 16) ^ h
       return (h & 0x7FFFFFFF) / 0x7FFFFFFF
   ```
6. Pass to `TopologyTransformer.transform()`.
7. Post-validation (same as snap-to-grid).
8. Transform back to source CRS.

**Why Gaussian:** Most vertices move a little, a few move more — natural hand-drawn look. The 3-sigma clamping prevents extreme outliers.

**Self-intersection risk:** Low (~0.03% per polygon for typical parameters). Handled by the topology wrapper's repair chain. For v1, accept and repair; for v2, consider constrained jitter.

**Output Fields:** All input fields + `_ig_algorithm`, `_ig_parent_fid`.


### 5.6 Simplify to Grid Cells

**Id:** `simplify_to_grid_cells`
**Group:** Shape
**Topology-aware:** Yes (different mechanism — cell assignment, not vertex transform)
**Plugin:** Main only

**Purpose:** Replace each polygon with the union of grid cells it covers. "Pixel art" maps.

**Parameters:**

| Name | Type | Default | Constraints | Description |
|---|---|---|---|---|
| INPUT | VectorLayer (Polygon) | — | required | |
| GRID_TYPE | Enum | 1 | 0=square, 1=hexagonal, 2=triangular | |
| CELL_SIZE | Number (float) | 0 | min=0 | 0 = auto |
| AUTO_CELLS_ACROSS | Number (int) | 30 | min=5, max=200 | |
| ASSIGNMENT | Enum | 0 | 0=largest_overlap, 1=centroid_inside | Cell assignment method |
| OUTPUT | FeatureSink | — | required | |

**Geometric Logic:**

1. Transform all features to working CRS.
2. Compute cell size (same as snap-to-grid).
3. Generate full grid of cell polygons over layer extent.
4. **Cell assignment** — spatial index is MANDATORY:
   a. Build `QgsSpatialIndex` on input polygons.
   b. For each cell, query index for candidate polygons (bbox intersection).
   c. For interior cells (centroid fully inside one polygon): assign via point-in-polygon (skip expensive intersection computation).
   d. For boundary cells (touching multiple polygons):
      - `largest_overlap`: compute `extract_polygons(cell.intersection(polygon)).area()` for each candidate. Assign to largest.
      - `centroid_inside`: check which polygon contains centroid. Fallback to largest_overlap if centroid is in a gap.
   e. Tie-breaking: when two polygons have equal overlap, assign to the one whose centroid is nearest the cell's centroid.
5. Discard unassigned cells.
6. Group cells by assigned polygon. `QgsGeometry.unaryUnion(cells)` per group.
   - GEOS 3.11 (QGIS 3.28) caveat: known issue with union of cells sharing exact edges. Catch topology exceptions, fallback to sequential `union()` with intermediate `buffer(0)`.
7. Transfer original polygon's attributes to merged geometry.
8. Transform back to source CRS.

**Why topology is guaranteed:** Each cell assigned to at most one polygon. Adjacent cells assigned to different polygons share an edge exactly. Result is gap-free and overlap-free by construction.

**Edge Cases:**
- Holes: `polygon.intersection()` respects holes. Cells inside holes are correctly unassigned.
- Small polygons that disappear: `largest_overlap` is safer than `centroid_inside` — guarantees representation for any polygon overlapping at least one cell. Log warning for polygons that vanish.

**Output Fields:** All input fields + `_ig_algorithm`, `_ig_parent_fid`, `_ig_tile_index`.


### 5.7 Scale by Value

**Id:** `scale_by_value`
**Group:** Shape
**Topology-aware:** No
**Plugin:** Main only

**Purpose:** Resize each polygon proportionally to an attribute value. Shape is preserved.

**Parameters:**

| Name | Type | Default | Constraints | Description |
|---|---|---|---|---|
| INPUT | VectorLayer (Polygon) | — | required | |
| VALUE_FIELD | Field (numeric) | — | required, parent=INPUT | |
| SCALE_METHOD | Enum | 0 | 0=proportional_area, 1=proportional_sqrt, 2=proportional_log | |
| REFERENCE | Enum | 0 | 0=max_value, 1=mean_value, 2=fixed | What value gets scale factor 1.0 |
| FIXED_REFERENCE | Number (float) | 100.0 | min=0.001 | Only when REFERENCE=fixed |
| MAX_SCALE | Number (float) | 3.0 | min=0.1, max=10.0 | |
| MIN_SCALE | Number (float) | 0.1 | min=0.01, max=1.0 | |
| CENTER_METHOD | Enum | **1** | 0=centroid, **1=pole_of_inaccessibility** | Default is pole_of_inaccessibility — centroid can lie outside concave polygons, causing shift instead of resize |
| OUTPUT | FeatureSink | — | required | |

**Geometric Logic:**

1. First pass: read all values, compute max_value, mean_value. (Source supports multiple iterators.)
2. Determine reference value R.
3. Second pass — for each feature:
   a. `raw_ratio = feature_value / R` (R=0 → skip).
   b. Scale factor:
      - proportional_area: `scale = clamp(raw_ratio, MIN_SCALE, MAX_SCALE)`
      - proportional_sqrt: `scale = clamp(sqrt(raw_ratio), MIN_SCALE, MAX_SCALE)`
      - proportional_log: `scale = clamp(log(value+1) / log(R+1), MIN_SCALE, MAX_SCALE)`
   c. Center: `safe_pole_of_inaccessibility(geom)` or centroid.
   d. Transform to working CRS.
   e. Scale geometry: `new_vertex = center + (vertex - center) * sqrt(scale)`. Note: `sqrt(scale)` because area scales as square of linear dimensions.
   f. Transform back.
   g. Write to sink.

**Edge Cases:**
- Null or zero values: skip, log warning.
- Negative values: reject with error.

**Output Fields:** All input fields + `_ig_algorithm`, `_ig_parent_fid`, `_ig_value`, `_ig_scale_factor`.


### 5.8 Replace with Shape

**Id:** `replace_with_shape`
**Group:** Shape
**Topology-aware:** No
**Plugin:** Main only

**Purpose:** Replace each polygon with a circle/square/hexagon of proportional area.

**Parameters:**

| Name | Type | Default | Constraints | Description |
|---|---|---|---|---|
| INPUT | VectorLayer (Polygon) | — | required | |
| VALUE_FIELD | Field (numeric) | — | required, parent=INPUT | |
| SHAPE | Enum | 0 | 0=circle, 1=square, 2=hexagon | |
| SCALE_METHOD | Enum | 0 | same as Scale by Value | |
| REFERENCE | Enum | 0 | same as Scale by Value | |
| FIXED_REFERENCE | Number (float) | 100.0 | min=0.001 | |
| SIZE_REFERENCE | Enum | 0 | 0=auto, 1=fixed_radius | |
| FIXED_RADIUS | Number (float) | 100000 | min=0 | Only when SIZE_REFERENCE=fixed_radius |
| CENTER_METHOD | Enum | **1** | 0=centroid, **1=pole_of_inaccessibility** | |
| CIRCLE_SEGMENTS | Number (int) | 64 | min=16, max=256 | |
| OUTPUT | FeatureSink | — | required | |

**Geometric Logic:**

1. Read all values, compute reference R (same as Scale by Value).
2. Reference shape size:
   - auto: `reference_radius = sqrt(median_polygon_area / π)`
   - fixed_radius: use FIXED_RADIUS.
3. For each feature:
   a. `scale = scale_method(value / R)` (same logic as Scale by Value).
   b. `radius = reference_radius * sqrt(scale)`.
   c. Center: `safe_pole_of_inaccessibility(geom)`.
   d. Generate shape: `regular_polygon(center, radius, n_sides, rotation)`.
      - Circle: n_sides = CIRCLE_SEGMENTS, rotation = 0.
      - Square: n_sides = 4, rotation = 45° (axis-aligned sides).
      - Hexagon: n_sides = 6, rotation = 0.
   e. Transform back, write to sink.

**Output Fields:** All input fields + `_ig_algorithm`, `_ig_parent_fid`, `_ig_value`, `_ig_scale_factor`.


### 5.9 Resolve Overlaps

**Id:** `resolve_overlaps`
**Group:** Layout
**Topology-aware:** No
**Plugin:** Main only

**Purpose:** Force-directed push to eliminate overlapping polygons. Designed to chain after Replace with Shape or Scale by Value.

**Parameters:**

| Name | Type | Default | Constraints | Description |
|---|---|---|---|---|
| INPUT | VectorLayer (Polygon) | — | required | |
| ITERATIONS | Number (int) | 100 | min=1, max=1000 | |
| DAMPING | Number (float) | 0.1 | min=0.01, max=1.0 | |
| ANCHOR_STRENGTH | Number (float) | **0.01** | min=0.0, max=1.0 | Default 0.01, not 0.05. Higher values mathematically prevent full overlap resolution. At 0.01 with DAMPING=0.1, equilibrium retains ~9% of original overlap. |
| CONVERGENCE_THRESHOLD | Number (float) | 0.01 | min=0.0, max=1.0 | |
| ADAPTIVE_DAMPING | Boolean | True | | If True, damping decreases over iterations: η(t) = η₀ / (1 + t/τ) where τ = ITERATIONS/3 |
| OUTPUT | FeatureSink | — | required | |

**Geometric Logic:**

1. Transform all features to working CRS.
2. For each feature compute centroid, collision radius, original_centroid.
   - **Collision radius:** For shapes from Replace with Shape (circles/squares/hexagons), use average of circumradius and inradius. For arbitrary polygons, use minimum enclosing circle radius. This reduces the area overestimate from 57% (squares) to near-exact.
3. **Spatial grid** (mandatory for n > 500): cell size = `2 × max_radius`. Only compare features in same or adjacent cells. Rebuild grid each iteration.
4. Iterative force-directed layout:
   ```
   for iteration in range(ITERATIONS):
       η = DAMPING / (1 + iteration / (ITERATIONS/3)) if ADAPTIVE_DAMPING else DAMPING
       max_displacement = 0
       displacements = [(0, 0)] * n

       for each pair (i, j) in spatial neighborhood:
           distance = dist(centroid_i, centroid_j)
           overlap = (radius_i + radius_j) - distance
           if overlap > 0:
               direction = normalize(centroid_j - centroid_i)
               push = overlap * η / 2
               displacements[i] -= direction * push
               displacements[j] += direction * push

       for each feature i:
           anchor_pull = (original_centroid_i - centroid_i) * ANCHOR_STRENGTH
           displacements[i] += anchor_pull
           centroid_i += displacements[i]
           max_displacement = max(max_displacement, magnitude(displacements[i]))

       if max_displacement < CONVERGENCE_THRESHOLD * mean(all radii):
           break
   ```
5. Translate each feature's geometry by total displacement.
6. Transform back.

**Edge Cases:**
- Features that can't be fully resolved: log warning with count of remaining overlapping pairs.
- ANCHOR_STRENGTH = 0: shapes drift freely. Preserves relative topology but not absolute position.

**Output Fields:** All input fields + `_ig_algorithm`, `_ig_parent_fid`, `_ig_iteration`.

---

## 6. Base Algorithm Class

### `algorithms/base_algorithm.py`

`IdeoGISAlgorithm(QgsProcessingAlgorithm)` provides:

- Standard `INPUT` and `OUTPUT` parameter setup.
- A `processAlgorithm` implementation that:
  1. Resolves INPUT as `QgsProcessingFeatureSource`.
  2. Creates `WorkingCRS` (inside processAlgorithm — thread-safe).
  3. Creates output sink with `QgsWkbTypes.MultiPolygon` geometry type. Declare input type filter as `QgsProcessing.TypeVectorPolygon` for modeler compatibility (accepts both Polygon and MultiPolygon).
  4. If `topology_aware = True`, creates `TopologyTransformer`.
  5. Calls `run_algorithm()` passing the **sink** — algorithms write directly to it.
  6. Handles progress reporting.

**Signature:**

```python
class IdeoGISAlgorithm(QgsProcessingAlgorithm):
    topology_aware = False           # Override in subclass
    crs_strategy = "equal_area"      # Override in subclass

    def run_algorithm(self, source, parameters, context, working_crs, topology, sink, feedback):
        """
        Subclasses implement this. Write features directly to sink.
        No return value needed.

        - source: QgsProcessingFeatureSource (supports multiple iterators)
        - topology: TopologyTransformer or None
        - sink: QgsFeatureSink (write features here)
        """
        raise NotImplementedError
```

Non-topology algorithms can process one feature at a time with O(1) memory. Topology-aware algorithms materialize all input features (the vertex index needs random access). Algorithms needing a pre-scan (Scale by Value, Replace with Shape) call `source.getFeatures()` twice.

---

## 7. Plugin Dialog

### Layout

Single dialog with:
- Input layer dropdown (`QgsMapLayerComboBox`: polygon layers only)
- Algorithm dropdown (`QComboBox`: grouped by Fill / Shape / Layout)
- Dynamic parameter panel
- Output: temporary layer or save to file
- "Apply default style" checkbox
- Run button
- "Open Processing Dialog" button
- Log area

### Dynamic Parameter Panel

When the user selects an algorithm, rebuild the parameter panel from the algorithm's Processing parameter declarations. Widget mapping:

| Parameter Type | Widget |
|---------------|--------|
| `QgsProcessingParameterField` | `QgsFieldComboBox` (wire to `layerChanged`) |
| `QgsProcessingParameterEnum` | `QComboBox` |
| `QgsProcessingParameterNumber` | `QgsDoubleSpinBox` / `QgsSpinBox` |
| `QgsProcessingParameterColor` | `QgsColorButton` |
| `QgsProcessingParameterBoolean` | `QCheckBox` |

Build from scratch (~200 lines) — do NOT reuse `QgsProcessingAlgorithmDialogBase` (tightly coupled to Processing lifecycle).

**Conditional visibility** (plugin dialog only, not Processing Toolbox):
- `FIXED_REFERENCE` visible only when `REFERENCE=fixed`
- `FIXED_RADIUS` visible only when `SIZE_REFERENCE=fixed_radius`
- `TARGET_TILES` visible only when `CELL_SIZE=0`

Wire via Qt signals on the controlling widget.

### Execution

Use `QgsProcessingAlgRunnerTask` — do NOT build a custom `QgsTask`. It handles threading, context management, and layer loading automatically:

```python
task = QgsProcessingAlgRunnerTask(algorithm, parameters, context, feedback)
task.executed.connect(lambda ok, results: handle_completion(ok, results, context))
QgsApplication.taskManager().addTask(task)
```

`QgsProject.addMapLayer()` is NOT thread-safe — `QgsProcessingAlgRunnerTask` handles this correctly via `context.layersToLoadOnCompletion()`.

### "Open Processing Dialog" Button

```python
processing.execAlgorithmDialog('ideogis:percentage_split', {})
```

---

## 8. Processing Provider

Single `QgsProcessingProvider` with id `"ideogis"`, name `"IdeoGIS"`. Registers all 9 algorithms grouped as Fill / Shape / Layout.

Each standalone plugin has its own provider:
- `percentage_split` provider with id `"percentage_split"`, registering one algorithm
- `stripe_hatching` provider with id `"stripe_hatching"`, registering one algorithm

---

## 9. Shipped Style Presets

| File | Algorithm | Description |
|---|---|---|
| `percentage_split_blue_red.qml` | percentage_split | Categorized by `_ig_part`: filled=#3b82f6, remainder=#ef4444 |
| `percentage_split_green_grey.qml` | percentage_split | filled=#22c55e, remainder=#d1d5db |
| `tessellate_on_off.qml` | tessellate | Categorized by `_ig_state` |
| `graduated_value.qml` | scale_by_value, replace_with_shape | Graduated by `_ig_value`, YlOrRd |
| `grid_mosaic.qml` | simplify_to_grid_cells | Simple fill, thin outlines |

Set scale-based rendering limits in QMLs that can produce high feature counts (tessellate, simplify).

---

## 10. Testing Strategy

### Test Data

**Primary:** Natural Earth 110m countries (`ne_110m_admin_0_countries.shp`) — 177 features with `POP_EST`, `GDP_MD`, `ECONOMY` attributes.
**Location:** `tests/test_data/`

### Test Fixtures (`conftest.py`)

Create programmatically:
- `simple_squares`: 4 adjacent squares (2×2 grid) with known areas and numeric attribute.
- `concave_polygon`: single L-shaped polygon.
- `multipolygon`: single feature with mainland + island.
- `polygon_with_holes`: single polygon with interior ring.

### Unit Tests (pure geometry, no QGIS required if using QgsGeometry directly)

- `split_polygon_by_fraction` produces correct area ratio (within 0.1%)
- `extract_polygons` filters out non-polygon components
- Grid generators produce expected point counts for given extent/spacing
- `nearest_grid_point` for each grid type returns correct point
- `scale_geometry` preserves shape and correct area ratio
- `regular_polygon` produces correct vertex count and area
- `safe_pole_of_inaccessibility` returns point inside polygon for concave/multi cases

### Integration Tests (require qgis.core)

- Output feature count is correct
- Output geometry type is MultiPolygon
- Metadata fields present and correct
- Area ratios within tolerance
- Topology-aware algorithms: union of outputs ≈ union of inputs (area difference < 0.01%)
- CRS round-trip: output CRS matches input CRS

---

## 11. Implementation Phases

### Phase 1: Foundation + Tessellate

**Goal:** Working plugin with one algorithm, end-to-end from QGIS dialog to styled output.

1. **Shared library** (`lib/ideogis_common/`):
   - `crs_manager.py` — full implementation
   - `feature_builder.py` — full implementation
   - `geometry_helpers.py` — `extract_polygons`, `safe_pole_of_inaccessibility`, `clamp`, `regular_polygon`
2. **Grid generators** (`infrastructure/grid_generators.py`):
   - `generate_point_grid` and `generate_cell_polygons` for hexagonal + square
   - `auto_cell_size`
   - `nearest_grid_point` for square + hex (triangular can wait)
3. **Base algorithm class** + Processing provider
4. **Tessellate algorithm** — exercises grid generation, high-volume output, batch sink writing, parent-child linking
5. **Plugin dialog** — basic version: dropdown + dynamic parameters + run
6. **Tests** for CRS manager, grid generators, Tessellate

**Why Tessellate first:** It exercises more infrastructure (grid generators, batch output, cell geometry construction) than Percentage Split, and its geometry is simpler (no binary search, no sweep line). It validates that the full pipeline works: dialog → algorithm → sink → styled layer.

### Phase 2: Percentage Split + Standalone Plugins

7. **`split_polygon_by_fraction`** in geometry_helpers (binary search, `clipped()` optimization, `extract_polygons` integration)
8. **Percentage Split algorithm** in main plugin
9. **Standalone `percentage_split` plugin** — vendor shared library, create plugin.py/processing_provider.py
10. **Stripe Hatching algorithm** in main plugin
11. **Standalone `stripe_hatching` plugin**
12. **`scripts/package.py`** — vendoring + ZIP packaging

### Phase 3: Topology + Grid Algorithms

13. **Topology wrapper** — hardest infrastructure piece
14. **Snap to Grid** — primary topology consumer
15. **Sketchy Borders** — second topology consumer, validates densification + jitter
16. Triangular grid support in grid generators

### Phase 4: Cartogram Family

17. **Scale by Value**
18. **Replace with Shape**
19. **Resolve Overlaps** (force-directed layout)

### Phase 5: Polish

20. **Simplify to Grid Cells** (needs grid generators + cell assignment)
21. Shipped .qml style presets
22. Full test suite
23. README + documentation

---

## 12. Compatibility Notes

### QGIS Version Support

Minimum: QGIS 3.28 LTS. Key version-specific concerns:

| Issue | Versions | Workaround |
|---|---|---|
| `createFromProj4()` removed | ≥ 3.30 | Use `createFromProj()` |
| `poleOfInaccessibility()` MultiPolygon bug | 3.28-3.30 | `safe_pole_of_inaccessibility()` |
| `GEOSClipByRect` hole-vertex bug | 3.28 (GEOS 3.11) | Validate `clipped()` result |
| `unaryUnion` topology exception on exact-edge cells | 3.28 (GEOS 3.11) | Fallback to sequential union |
| Enum named values in CLI | < 3.36 | Use integer indices |

### GEOS Version Map

| QGIS | GEOS | Key Change |
|------|------|-----------|
| 3.28 LTS | 3.11 | OverlayNG default |
| 3.34 LTS | 3.12 | Fixes `GEOSClipByRect` hole bug |
| 3.38+ | 3.13 | 2x faster unaryUnion for shared-edge grids |

### CLI Notes

- Color parameters: shell-quote the `#`: `--FILLED_COLOR='#3b82f6'`
- Enum parameters: use integer indices on QGIS 3.28-3.34

---

## 13. Performance Targets

### Natural Earth 110m (177 features) — All under 10s

| Algorithm | Target | Notes |
|-----------|--------|-------|
| Percentage Split | 0.5-2s | `clipped()` + early termination |
| Tessellate | 2-5s | Batch sink writes |
| Stripe Hatching | 1-3s | |
| Snap to Grid | 2-5s | |
| Sketchy Borders | 3-8s | Hash-based jitter |
| Simplify to Grid Cells | 5-15s | Spatial index mandatory |
| Scale by Value | 0.5-1s | |
| Replace with Shape | 0.5-1s | |
| Resolve Overlaps | 1-5s | |

### GADM admin-1 (~3,500 features) — Topology algorithms may exceed 30s

Topology-aware algorithms (Snap to Grid, Sketchy Borders) are designed for **< 1,000 features**. For larger layers, simplify input first or expect multi-minute processing. Non-topology algorithms (Scale by Value, Replace with Shape, Stripe Hatching) remain fast.

---

## 14. Design Principles

1. **If QGIS already does it, don't rebuild it.** Processing handles parameter→UI, CLI, batch, modeler. Use it.
2. **If the result can be achieved by QGIS's native styling, don't build it into an algorithm.** The plugin's job is geometry transformation.
3. **Topology is opt-in and contained.** Only 3 algorithms use it. Others pay zero cost.
4. **Every algorithm's output is valid input to every other algorithm.**
5. **No external dependencies.** Must work with stock QGIS 3.28+.
6. **Ship fast, harden later.** Phase 1 should produce a working plugin with 1 algorithm in days, not months.
