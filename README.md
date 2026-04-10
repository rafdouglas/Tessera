# Tessera

[![QGIS 3.28+](https://img.shields.io/badge/QGIS-3.28%2B-green)](https://qgis.org)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0.html)
[![Tests](https://img.shields.io/badge/tests-500%2B-brightgreen)](tests/)
[![Version 0.5.8](https://img.shields.io/badge/version-0.5.8-blue)](https://github.com/rafdouglas/tessera/releases)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)

Cartographic ideogram toolkit for QGIS — thematic maps where geographic shapes communicate data visually.

<!-- ![Tessera hero banner](docs/images/hero-banner.png) -->

Tessera provides 9 algorithms for creating compelling cartographic visualizations: tile grids for waffle charts, proportional fills, cartogram transforms, hand-drawn styling, force-directed layouts, and grid arrangements. All built into QGIS Processing with no external dependencies beyond what QGIS 3.28+ bundles.

---

## Gallery

| | | |
|---|---|---|
| ![Snap to Hex Grid](/images/screenshots/Europa_01_2.png)  | ![Fill with hexagons and flag by percentage](/images/screenshots/Europa_01_4.png)  | ![Retro fun!](/images/screenshots/Europa_01_6.png)  |
| ![Shapes + coalesce + Fill with Tiles](/images/screenshots/Africa_01_10.png)  |![Snap to Hex + Hex fill + Scale + Arrange on a grid](/images/screenshots/Africa_02_5.png) |![Snap to Hex + Hex fill + Scale + Arrange on a grid (particular)](/images/screenshots/Africa_02_6.png)  |

---

## Features

Tessera includes **9 cartographic algorithms** organized into 3 categories:

### Fill Algorithms — Tile and Pattern Fills

| Algorithm | Description |
|-----------|-------------|
| **Tile Fill** | Fill polygons with regular tile grids (square, hexagon, circle, triangle, diamond). Flag tiles based on percentage values for waffle-chart visualizations. |
| **Percentage Split** | Split each polygon into two parts (filled/remainder) based on a numeric attribute. Supports horizontal, vertical, diagonal, and radial orientations. |
| **Stripe Hatching** | Fill polygons with parallel rectangular stripes at configurable angle and spacing. Topology-aware for seamless multi-polygon fills. |

### Shape Algorithms — Cartogram Family

| Algorithm | Description |
|-----------|-------------|
| **Scale by Value** | Resize polygons proportionally to an attribute value. Methods: proportional area, square-root, logarithmic scaling. |
| **Replace with Shape** | Replace polygons with proportional geometric shapes (circle, square, hexagon) for Dorling/Demers cartogram visualizations. |
| **Arrange Features** | Force-directed layout. Three modes: resolve overlaps, attraction forces, separate with gap. Quality presets (Fast/Balanced/Precise/Custom). Multipart explosion, area-equivalent collision radius, geometry-based overlap refinement. Optional engineering CRS output. |
| **Grid Arrangement** | Place features in a regular grid layout for small-multiples posters. Configurable columns, cell size, padding, sort field, and fill order. Outputs in engineering CRS (meters). |

### Style Algorithms — Topology-Aware Vertex Transforms

| Algorithm | Description |
|-----------|-------------|
| **Snap to Grid** | Snap polygon edges to follow grid cell boundaries (square, hex, triangle). Densifies long edges, snaps to grid vertices, and traces cell edges for a pixelated/mosaic effect. Configurable attraction strength. Topology-aware for shared boundaries. |
| **Sketchy Borders** | Add hand-drawn style irregularity to polygon borders. Topology-aware, deterministic via hash-based displacement. |

---

## Installation

### From QGIS Plugin Manager (Recommended)

1. In QGIS, go to **Plugins → Manage and Install Plugins**
2. Search for **Tessera**
3. Click **Install Plugin**
4. Access algorithms via **Processing Toolbox → Tessera**

### Manual Installation from Release

1. Download the latest ZIP from [Releases](https://github.com/rafdouglas/tessera/releases)
2. Extract to `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/tessera`
3. Restart QGIS
4. Enable the plugin in **Plugins → Manage and Install Plugins**

### Development Installation

```bash
git clone https://github.com/rafdouglas/tessera.git
cd tessera
ln -sf $(pwd)/plugins/tessera ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/
```

---

## Quick Start

### Basic Workflow

1. **Load a polygon layer** in QGIS (e.g., countries, states, districts)
2. Open **Processing Toolbox** (typically under **Processing → Toolbox**)
3. Navigate to **Tessera** (or search by algorithm name)
4. Select an algorithm and configure parameters
5. Click **Run** — the result appears as a new layer
6. Style the output using QGIS symbology

### Example: Creating a Waffle Chart

Visualize a percentage attribute as a proportional tile fill:

1. Load a polygon layer with a numeric percentage field (e.g., `pct_urban`)
2. Run **Tile Fill** with:
   - **TILE_SHAPE**: Square
   - **CELL_SIZE**: 50000 (map units)
   - **PERCENT_FIELD**: pct_urban
3. Output tiles are flagged `_tessera_part = "filled"` or `"remainder"`
4. Style with a categorized renderer on `_tessera_part`
5. Result: a proportional waffle chart overlay on your geometry

---

## Standalone Plugins

For lightweight installations, **Percentage Split** and **Stripe Hatching** are also available as individual plugins:

- **Percentage Split Plugin** — Ideal for split-fill cartograms without the full toolkit
- **Stripe Hatching Plugin** — Hatching and pattern fills as a standalone tool

Both include the shared infrastructure and require no dependencies. Install either alongside or instead of the full Tessera suite.

---

## Building from Source

```bash
# Clone the repository
git clone https://github.com/rafdouglas/tessera.git
cd tessera

# Package plugins (creates ZIPs in dist/)
python scripts/package.py

# Outputs:
#   dist/tessera.zip            # Main plugin
#   dist/percentage_split.zip   # Standalone
#   dist/stripe_hatching.zip    # Standalone

# Prepare versioned release files (creates ZIPs in dist/)
./scripts/prepare_release.sh

# Outputs (in dist/):
#   tessera-0.5.4.zip            # Main plugin (versioned)
#   percentage_split-0.5.4.zip   # Standalone (versioned)
#   stripe_hatching-0.5.4.zip    # Standalone (versioned)
```

The packaging script automatically vendors the shared library into each plugin.

---

## Testing

Tessera includes **500+ tests** covering algorithms, geometry utilities, topology, and CRS handling.

### Run All Tests

```bash
flatpak run --command=python3 org.qgis.qgis -m pytest tests/ -v
```

### Run Tests for Specific Algorithm

```bash
flatpak run --command=python3 org.qgis.qgis -m pytest tests/test_tile_fill.py -v
```

### Run Without Flatpak

If QGIS is installed system-wide:

```bash
python -m pytest tests/ -v
```

Test data is not included in the repository. Fetch it with:

```bash
python scripts/download_test_data.py
```

---

## Architecture

### Directory Structure

```
tessera/
├── lib/
│   └── ideogis_common/          # Shared infrastructure
│       ├── crs_manager.py       # CRS detection and reprojection
│       ├── feature_builder.py   # Consistent output layer construction
│       ├── geometry_helpers.py  # Polygon utilities, grid operations
│       └── grid_generators.py   # Regular hex, square, triangle grids
│
├── plugins/
│   ├── tessera/                 # Main plugin (9 algorithms)
│   │   ├── algorithms/
│   │   ├── infrastructure/      # Vendored shared code
│   │   ├── ui/
│   │   ├── resources/
│   │   └── processing_provider.py
│   │
│   ├── percentage_split/        # Standalone plugin
│   └── stripe_hatching/         # Standalone plugin
│
├── tests/                       # 500+ tests
├── test_data/                   # Natural Earth 110m countries
└── scripts/
    ├── package.py              # Vendor and package plugins
    └── download_test_data.py    # Fetch test data
```

### Key Design Patterns

- **CRS-agnostic**: Automatically detects appropriate working CRS for area/distance calculations
- **Topology-aware**: Shared boundaries are transformed consistently to avoid gaps/overlaps
- **Deterministic**: Hash-based seeding ensures reproducible results
- **QGIS Processing**: Full integration with graphical modeler and command-line workflows
- **No dependencies**: Uses only Python stdlib, PyQt5, and QGIS bundled libraries

---

## Output Data Contract

All algorithms produce MultiPolygon output with:

- **Original fields** from input layer carried forward
- **Metadata fields** (prefixed `_tessera_`) for algorithm tracking:
  - `_tessera_algorithm` — Algorithm identifier
  - `_tessera_parent_fid` — Feature ID from input layer
  - `_tessera_fraction` — Computed fraction (for percentage-based algorithms)
  - `_tessera_part` — `"filled"` or `"remainder"` (for Tile Fill with PERCENT_FIELD, and Percentage Split)
  - Additional fields per algorithm (scale factor, iteration count, etc.)

**Output CRS matches input CRS** except Grid Arrangement (always engineering CRS) and Arrange Features with Force engineering CRS enabled.

---

## Requirements

- **QGIS**: 3.28 or later
- **Python**: 3.9+ (bundled with QGIS)
- **Dependencies**: None (uses QGIS-bundled PyQt5, qgis.core, qgis.gui, GEOS)

---

## Author

**RafDouglas C. Tommasi**
- Email: rafdouglas@exponential.engineering
- LinkedIn: https://www.linkedin.com/in/rafdouglas/

---

## License

Tessera is released under the **GNU General Public License v3 (GPLv3)**. See [LICENSE](LICENSE) for details.

---

## Changelog

**0.5.4** — Snap to Grid edge-following redesign, CRS distortion fix for projected input, auto-repair invalid geometries, multipart degenerate handling fix, unify `_tessera_part` field, Arrange Features UI improvements, contributor guide

**0.5.3** — Rename Tessellate → Tile Fill, standardize metadata prefix `_ts_` → `_tessera_`

**0.5.2** — Code quality: decompose god methods, extract shared helpers, consolidate test infrastructure

**0.5.1** — Triangle and diamond tile shapes for Tile Fill, quality presets for Arrange Features

**0.5.0** — Split Grid Arrangement into standalone algorithm (9 algorithms total)

**0.4.1** — Force-directed layout fixes: area-equivalent collision radius, multipart geometry explosion, geometry-based overlap refinement

**0.4.0** — Engineering CRS, comprehensive help text, arrange features enhancements

**0.3.0** — Cartogram algorithms: Scale by Value, Replace with Shape, Arrange Features

**0.2.0** — Tile Fill tile flagging, Snap to Grid, Sketchy Borders, topology support

**0.1.0** — Foundation: Tile Fill, Percentage Split, Stripe Hatching

---

## Releasing

See [RELEASE.md](RELEASE.md) for instructions on creating and publishing releases.

---

## Contributing

Issues, feature requests, and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and PR guidelines. Use the [issue tracker](https://github.com/rafdouglas/tessera/issues) for bug reports and feature discussions.

---

## See Also

- [QGIS Processing Framework](https://docs.qgis.org/stable/en/docs/user_manual/processing/)
- [QGIS Plugin Development](https://docs.qgis.org/stable/en/docs/pyqgis_developer_guide/)
- [Cartographic Design Principles](https://en.wikipedia.org/wiki/Cartogram)
