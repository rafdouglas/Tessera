"""Grid generation for tessellation, snapping, and simplification."""
import math

from qgis.core import QgsGeometry, QgsPointXY, QgsRectangle

from .geometry_helpers import regular_polygon


def generate_point_grid(extent, spacing, grid_type):
    """Generate grid center points within an extent.

    Args:
        extent: QgsRectangle defining the area to fill.
        spacing: Distance between adjacent row centres (flat-to-flat for hex).
        grid_type: One of ``'square'``, ``'hexagonal'``, ``'triangular'``,
            ``'diamond'``.

    Returns:
        List of QgsPointXY grid centre points.
    """
    if grid_type == 'square':
        return _point_grid_square(extent, spacing)
    elif grid_type == 'hexagonal':
        return _point_grid_hex(extent, spacing)
    elif grid_type == 'triangular':
        return _point_grid_triangular(extent, spacing)
    elif grid_type == 'diamond':
        return _point_grid_square(extent, spacing)
    else:
        raise ValueError(f"Unknown grid_type: {grid_type!r}")


def generate_cell_polygons(extent, spacing, grid_type):
    """Generate grid cell polygons within an extent.

    Args:
        extent: QgsRectangle defining the area to fill.
        spacing: Distance between adjacent row centres (flat-to-flat for hex).
        grid_type: One of ``'square'``, ``'hexagonal'``, ``'triangular'``,
            ``'diamond'``.

    Returns:
        List of ``(centre_point, polygon_geometry)`` tuples.
    """
    if grid_type == 'square':
        return _cell_polygons_square(extent, spacing)
    elif grid_type == 'hexagonal':
        return _cell_polygons_hex(extent, spacing)
    elif grid_type == 'triangular':
        return _cell_polygons_triangular(extent, spacing)
    elif grid_type == 'diamond':
        return _cell_polygons_diamond(extent, spacing)
    else:
        raise ValueError(f"Unknown grid_type: {grid_type!r}")


def auto_cell_size(extent, target_count, grid_type):
    """Calculate cell spacing to achieve approximately *target_count* cells.

    Formula: ``sqrt(width * height / target_count) * packing_factor``

    Args:
        extent: QgsRectangle defining the area.
        target_count: Desired number of cells.
        grid_type: One of ``'square'``, ``'hexagonal'``, ``'circle'``,
            ``'triangular'``, ``'diamond'``.

    Returns:
        float -- recommended cell spacing.
    """
    # Packing factors compensate for the difference between a grid cell's
    # area and the bounding rectangle area used by sqrt(W*H/N).
    # - square/diamond: cells tile perfectly, factor = 1.0
    # - hexagonal/circle: hex cells cover ~93% of their bounding rect
    #   (area = sqrt(3)/2 * s^2 vs s^2), so factor = 1/0.93 ≈ 1.07
    # - triangular: each triangle covers ~43% of its bounding rect
    #   (area = sqrt(3)/4 * s^2 vs s * h/2), so factor = 1/0.43 ≈ 1.52
    #   (empirically tuned to match target count)
    packing_factors = {
        'square': 1.0,
        'hexagonal': 1.07,
        'circle': 1.07,
        'triangular': 1.52,
        'diamond': 1.0,
    }
    factor = packing_factors.get(grid_type, 1.0)
    return math.sqrt(extent.width() * extent.height() / target_count) * factor


def nearest_grid_point(point, spacing, grid_type):
    """Snap a point to the nearest grid centre.

    Args:
        point: QgsPointXY to snap.
        spacing: Grid spacing (flat-to-flat for hex).
        grid_type: One of ``'square'``, ``'hexagonal'``, ``'triangular'``,
            ``'diamond'``.

    Returns:
        QgsPointXY of the nearest grid centre.
    """
    if grid_type == 'square':
        return _nearest_square(point, spacing)
    elif grid_type == 'hexagonal':
        return _nearest_hex(point, spacing)
    elif grid_type == 'triangular':
        return _nearest_triangular(point, spacing)
    elif grid_type == 'diamond':
        return _nearest_square(point, spacing)
    else:
        raise ValueError(f"Unknown grid_type: {grid_type!r}")


def grid_edge_length(spacing, grid_type):
    """Return the edge length of a single grid cell.

    Args:
        spacing: Grid spacing (flat-to-flat for hex, side length for others).
        grid_type: One of ``'square'``, ``'hexagonal'``, ``'triangular'``.

    Returns:
        float -- edge length of one cell.
    """
    if grid_type == 'square':
        return spacing
    elif grid_type == 'hexagonal':
        return spacing / math.sqrt(3)
    elif grid_type == 'triangular':
        return spacing
    else:
        raise ValueError(f"Unknown grid_type: {grid_type!r}")


def nearest_grid_vertex(point, spacing, grid_type):
    """Snap a point to the nearest grid cell vertex (corner, not centre).

    Args:
        point: QgsPointXY to snap.
        spacing: Grid spacing (flat-to-flat for hex, side length for others).
        grid_type: One of ``'square'``, ``'hexagonal'``, ``'triangular'``.

    Returns:
        QgsPointXY of the nearest grid cell corner.
    """
    if grid_type == 'square':
        return _nearest_square_vertex(point, spacing)
    elif grid_type == 'hexagonal':
        return _nearest_hex_vertex(point, spacing)
    elif grid_type == 'triangular':
        return _nearest_tri_vertex(point, spacing)
    else:
        raise ValueError(f"Unknown grid_type: {grid_type!r}")


# ---------------------------------------------------------------------------
# Internal: square grid
# ---------------------------------------------------------------------------

def _point_grid_square(extent, spacing):
    """Square grid: centres at (col*spacing, row*spacing), anchored at origin."""
    col_start = math.floor(extent.xMinimum() / spacing)
    col_end = math.ceil(extent.xMaximum() / spacing)
    row_start = math.floor(extent.yMinimum() / spacing)
    row_end = math.ceil(extent.yMaximum() / spacing)

    points = []
    for col in range(col_start, col_end + 1):
        x = col * spacing
        for row in range(row_start, row_end + 1):
            y = row * spacing
            points.append(QgsPointXY(x, y))
    return points


def _cell_polygons_square(extent, spacing):
    """Square cells centred on grid points, each side = spacing."""
    points = _point_grid_square(extent, spacing)
    half = spacing / 2.0
    cells = []
    for pt in points:
        rect = QgsRectangle(
            pt.x() - half, pt.y() - half,
            pt.x() + half, pt.y() + half,
        )
        cells.append((pt, QgsGeometry.fromRect(rect)))
    return cells


def _nearest_square(point, spacing):
    """Snap to nearest square grid intersection."""
    x = round(point.x() / spacing) * spacing
    y = round(point.y() / spacing) * spacing
    return QgsPointXY(x, y)


def _cell_polygons_diamond(extent, spacing):
    """Diamond cells (45-degree rotated squares) centred on square grid points."""
    points = _point_grid_square(extent, spacing)
    half = spacing / 2.0
    cells = []
    for pt in points:
        ring = [
            QgsPointXY(pt.x(), pt.y() + half),   # top
            QgsPointXY(pt.x() + half, pt.y()),    # right
            QgsPointXY(pt.x(), pt.y() - half),    # bottom
            QgsPointXY(pt.x() - half, pt.y()),    # left
            QgsPointXY(pt.x(), pt.y() + half),    # close ring
        ]
        geom = QgsGeometry.fromPolygonXY([ring])
        cells.append((pt, geom))
    return cells


# ---------------------------------------------------------------------------
# Internal: hexagonal grid
# ---------------------------------------------------------------------------

def _point_grid_hex(extent, spacing):
    """Hex grid with offset odd columns, anchored at global origin.

    R (circumradius) = spacing / sqrt(3).
    col_spacing = 3 * R / 2.
    row_spacing = spacing.
    Odd columns offset by spacing / 2.
    """
    R = spacing / math.sqrt(3)
    col_spacing = 1.5 * R
    row_spacing = spacing

    col_start = math.floor(extent.xMinimum() / col_spacing)
    col_end = math.ceil(extent.xMaximum() / col_spacing)

    points = []
    for col in range(col_start, col_end + 1):
        x = col * col_spacing
        y_offset = (spacing / 2.0) if (col % 2 != 0) else 0.0
        row_start = math.floor((extent.yMinimum() - y_offset) / row_spacing)
        row_end = math.ceil((extent.yMaximum() - y_offset) / row_spacing)
        for row in range(row_start, row_end + 1):
            y = row * row_spacing + y_offset
            points.append(QgsPointXY(x, y))
    return points


def _cell_polygons_hex(extent, spacing):
    """Hex cell polygons using regular_polygon(center, R, 6, 0)."""
    R = spacing / math.sqrt(3)
    points = _point_grid_hex(extent, spacing)
    cells = []
    for pt in points:
        geom = regular_polygon(pt, R, 6, 0)
        cells.append((pt, geom))
    return cells


def _nearest_hex(point, spacing):
    """Snap to nearest hex grid centre using axial rounding.

    Steps:
        1. Compute fractional column from x.
        2. Round to nearest column.
        3. Compute fractional row accounting for odd-column offset.
        4. Round to nearest row.
        5. Convert back to pixel coordinates.
    """
    R = spacing / math.sqrt(3)
    col_sp = 1.5 * R

    # Fractional column
    fc = point.x() / col_sp
    rc = round(fc)

    # Fractional row (account for odd-column y-offset)
    y_offset = (spacing / 2.0) if (rc % 2 != 0) else 0.0
    fr = (point.y() - y_offset) / spacing
    rr = round(fr)

    # Convert back to pixel
    return QgsPointXY(rc * col_sp, rr * spacing + y_offset)


# ---------------------------------------------------------------------------
# Internal: triangular grid
# ---------------------------------------------------------------------------

def _point_grid_triangular(extent, spacing):
    """Triangular grid centroids for both up and down equilateral triangles.

    spacing = side length s of each equilateral triangle.
    Row height h = s * sqrt(3) / 2.
    Column step = s / 2 (each triangle advances half a side length).
    Each triangle spans 2 column steps (= s) in the x direction.

    Up triangle centroid at (col, row): ((col + 1) * s/2, (row + 1/3) * h)
    Down triangle centroid at (col, row): ((col + 1) * s/2, (row + 2/3) * h)
    Triangle orientation: (col + row) % 2 == 0 -> up, else down.

    Start row/col are computed from the extent minimum to handle negative
    coordinates (southern/western hemispheres), with padding for full coverage.
    """
    s = spacing
    h = s * math.sqrt(3) / 2.0
    half_s = s / 2.0

    row_start = math.floor(extent.yMinimum() / h) - 1
    col_start = math.floor(extent.xMinimum() / half_s) - 2

    points = []
    row = row_start
    while row * h <= extent.yMaximum() + h:
        col = col_start
        while col * half_s <= extent.xMaximum() + half_s:
            if (col + row) % 2 == 0:
                cx = (col + 1) * half_s
                cy = (row + 1.0 / 3.0) * h
            else:
                cx = (col + 1) * half_s
                cy = (row + 2.0 / 3.0) * h
            points.append(QgsPointXY(cx, cy))
            col += 1
        row += 1
    return points


def _cell_polygons_triangular(extent, spacing):
    """Triangular cell polygons (equilateral triangles with side = spacing).

    Each triangle spans 2 column steps in x (base = s).

    Up triangle (col+row even):
        V0: (col * s/2, row * h)
        V1: ((col+2) * s/2, row * h)
        V2: ((col+1) * s/2, (row+1) * h)
    Down triangle (col+row odd):
        V0: (col * s/2, (row+1) * h)
        V1: ((col+2) * s/2, (row+1) * h)
        V2: ((col+1) * s/2, row * h)

    Start row/col are computed from the extent minimum to handle negative
    coordinates (southern/western hemispheres), with padding for full coverage.
    """
    s = spacing
    h = s * math.sqrt(3) / 2.0
    half_s = s / 2.0

    row_start = math.floor(extent.yMinimum() / h) - 1
    col_start = math.floor(extent.xMinimum() / half_s) - 2

    cells = []
    row = row_start
    while row * h <= extent.yMaximum() + h:
        col = col_start
        while col * half_s <= extent.xMaximum() + half_s:
            if (col + row) % 2 == 0:
                v0 = QgsPointXY(col * half_s, row * h)
                v1 = QgsPointXY((col + 2) * half_s, row * h)
                v2 = QgsPointXY((col + 1) * half_s, (row + 1) * h)
                cx = (col + 1) * half_s
                cy = (row + 1.0 / 3.0) * h
            else:
                v0 = QgsPointXY(col * half_s, (row + 1) * h)
                v1 = QgsPointXY((col + 2) * half_s, (row + 1) * h)
                v2 = QgsPointXY((col + 1) * half_s, row * h)
                cx = (col + 1) * half_s
                cy = (row + 2.0 / 3.0) * h

            ring = [v0, v1, v2, v0]
            geom = QgsGeometry.fromPolygonXY([ring])
            cells.append((QgsPointXY(cx, cy), geom))
            col += 1
        row += 1
    return cells


def _nearest_triangular(point, spacing):
    """Snap a point to the nearest equilateral-triangle grid centroid.

    The tessellation alternates up and down equilateral triangles with
    side length *spacing*.  Odd rows are offset by s/2 so that vertices
    interlock.  A half-plane (zigzag) test within the row strip
    determines whether the point falls in an up or down triangle.
    """
    s = spacing
    h = s * math.sqrt(3) / 2.0
    half_s = s / 2.0

    row = math.floor(point.y() / h)
    local_y = (point.y() - row * h) / h          # 0..1 within row strip

    # Odd rows shift the zigzag by s/2
    x_shift = half_s if (row % 2 != 0) else 0.0
    px_shifted = point.x() - x_shift

    seg = math.floor(px_shifted / half_s)
    frac_x = px_shifted / half_s - seg            # 0..1 within segment

    # Half-plane test: even segments have /-edge, odd segments have \-edge
    if seg % 2 == 0:
        is_up = (local_y < frac_x)
    else:
        is_up = (local_y < 1.0 - frac_x)

    if is_up:
        cx = (2 * (seg // 2) + 1) * half_s + x_shift
        cy = (row + 1.0 / 3.0) * h
    else:
        cx = (2 * ((seg + 1) // 2)) * half_s + x_shift
        cy = (row + 2.0 / 3.0) * h

    return QgsPointXY(cx, cy)


# ---------------------------------------------------------------------------
# Grid vertex snapping (corners, not centres)
# ---------------------------------------------------------------------------

def _nearest_square_vertex(point, spacing):
    """Snap to nearest square grid cell corner.

    Square cells are centred on grid points at ``(i*s, j*s)``.
    Cell corners sit at ``((i ± 0.5)*s, (j ± 0.5)*s)``.
    """
    half = spacing / 2.0
    x = round((point.x() - half) / spacing) * spacing + half
    y = round((point.y() - half) / spacing) * spacing + half
    return QgsPointXY(x, y)


def _nearest_hex_vertex(point, spacing):
    """Snap to nearest hexagonal grid cell corner.

    Finds the nearest hex centre and its 6 neighbours, computes all
    their vertices (6 per centre), and returns the closest vertex.
    """
    R = spacing / math.sqrt(3)
    col_sp = 1.5 * R

    # Find nearest hex centre
    center = _nearest_hex(point, spacing)

    # Determine column/row index of this center
    rc = round(center.x() / col_sp)
    y_offset = (spacing / 2.0) if (rc % 2 != 0) else 0.0
    rr = round((center.y() - y_offset) / spacing)

    # Check this center + 6 neighbours
    best_pt = None
    best_dist_sq = float('inf')

    for dc, dr in [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1)]:
        nc = rc + dc
        nr = rr + dr
        ny_offset = (spacing / 2.0) if (nc % 2 != 0) else 0.0
        cx = nc * col_sp
        cy = nr * spacing + ny_offset

        # 6 vertices of hex centred at (cx, cy)
        for k in range(6):
            angle = math.radians(k * 60.0)
            vx = cx + R * math.cos(angle)
            vy = cy + R * math.sin(angle)
            dx = vx - point.x()
            dy = vy - point.y()
            dist_sq = dx * dx + dy * dy
            if dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_pt = QgsPointXY(vx, vy)

    return best_pt


def _nearest_tri_vertex(point, spacing):
    """Snap to nearest triangular grid cell corner.

    Triangular grid vertices form a regular lattice at
    ``(k * s/2, m * h)`` where ``h = s * sqrt(3) / 2`` and
    ``(k + m) % 2 == 0``.
    """
    s = spacing
    h = s * math.sqrt(3) / 2.0
    half_s = s / 2.0

    k = round(point.x() / half_s)
    m = round(point.y() / h)

    if (k + m) % 2 != 0:
        candidates = [(k - 1, m), (k + 1, m), (k, m - 1), (k, m + 1)]
        best = min(
            candidates,
            key=lambda km: (km[0] * half_s - point.x()) ** 2
                         + (km[1] * h - point.y()) ** 2,
        )
        k, m = best

    return QgsPointXY(k * half_s, m * h)


# ---------------------------------------------------------------------------
# Grid-edge path tracing
# ---------------------------------------------------------------------------

def trace_grid_path(p1, p2, spacing, grid_type):
    """Return intermediate grid vertices along grid edges from p1 to p2.

    Both p1 and p2 must be on the grid vertex lattice (as returned by
    ``nearest_grid_vertex``).  If they are already connected by a single
    grid edge (or are the same point), returns an empty list.

    Uses a greedy walk: at each step, move to the lattice neighbour
    closest to p2.  This always converges on regular lattices.

    Args:
        p1: QgsPointXY start vertex (on grid lattice).
        p2: QgsPointXY end vertex (on grid lattice).
        spacing: Grid spacing.
        grid_type: One of ``'square'``, ``'hexagonal'``, ``'triangular'``.

    Returns:
        List of intermediate QgsPointXY points (excluding p1 and p2).
    """
    edge_len = grid_edge_length(spacing, grid_type)

    if grid_type == 'square':
        s = spacing
        steps = [(s, 0), (0, s), (-s, 0), (0, -s)]
    elif grid_type == 'hexagonal':
        return _trace_hex_lattice_path(p1, p2, spacing)
    elif grid_type == 'triangular':
        s = spacing
        h = s * math.sqrt(3) / 2.0
        steps = [
            (s, 0), (s / 2, h), (-s / 2, h),
            (-s, 0), (-s / 2, -h), (s / 2, -h),
        ]
    else:
        raise ValueError(f"Unknown grid_type: {grid_type!r}")

    return _trace_lattice_path(p1, p2, steps, edge_len)


def _trace_hex_lattice_path(p1, p2, spacing):
    """Greedy lattice walk along hex edges from p1 to p2.

    Hex vertices form a honeycomb lattice where each vertex has exactly
    3 edge-connected neighbours (not 6).  Two vertex types alternate:

    - Type A (``n % 3 == 2``): valid steps at 0°, 120°, 240°
    - Type B (``n % 3 == 1``): valid steps at 60°, 180°, 300°

    where ``n = round(x / (R / 2))``.
    """
    R = spacing / math.sqrt(3)
    half_R = R / 2.0
    half_spacing = spacing / 2.0
    threshold_sq = (R * 1.01) ** 2

    type_a_steps = [
        (R, 0),
        (-half_R, half_spacing),
        (-half_R, -half_spacing),
    ]
    type_b_steps = [
        (half_R, half_spacing),
        (-R, 0),
        (half_R, -half_spacing),
    ]

    dx = p2.x() - p1.x()
    dy = p2.y() - p1.y()
    if dx * dx + dy * dy <= threshold_sq:
        return []

    intermediates = []
    cx, cy = p1.x(), p1.y()

    for _ in range(500):
        dx = p2.x() - cx
        dy = p2.y() - cy
        remaining_sq = dx * dx + dy * dy

        if remaining_sq <= threshold_sq:
            break

        n = round(cx / half_R)
        vtype = n % 3
        steps = type_a_steps if vtype == 2 else type_b_steps

        best_dist_sq = float('inf')
        best_nx, best_ny = cx, cy

        for sx, sy in steps:
            nx = cx + sx
            ny = cy + sy
            d_sq = (nx - p2.x()) ** 2 + (ny - p2.y()) ** 2
            if d_sq < best_dist_sq:
                best_dist_sq = d_sq
                best_nx, best_ny = nx, ny

        if best_dist_sq >= remaining_sq:
            break

        cx, cy = best_nx, best_ny
        intermediates.append(QgsPointXY(cx, cy))

    return intermediates


def _trace_lattice_path(p1, p2, steps, edge_len):
    """Greedy lattice walk from p1 towards p2 using step vectors.

    Returns intermediate vertices (excluding p1 and p2).
    """
    threshold_sq = (edge_len * 1.01) ** 2

    dx = p2.x() - p1.x()
    dy = p2.y() - p1.y()
    if dx * dx + dy * dy <= threshold_sq:
        return []

    intermediates = []
    cx, cy = p1.x(), p1.y()

    for _ in range(500):
        dx = p2.x() - cx
        dy = p2.y() - cy
        remaining_sq = dx * dx + dy * dy

        if remaining_sq <= threshold_sq:
            break

        best_dist_sq = float('inf')
        best_nx, best_ny = cx, cy

        for sx, sy in steps:
            nx = cx + sx
            ny = cy + sy
            d_sq = (nx - p2.x()) ** 2 + (ny - p2.y()) ** 2
            if d_sq < best_dist_sq:
                best_dist_sq = d_sq
                best_nx, best_ny = nx, ny

        if best_dist_sq >= remaining_sq:
            break

        cx, cy = best_nx, best_ny
        intermediates.append(QgsPointXY(cx, cy))

    return intermediates
