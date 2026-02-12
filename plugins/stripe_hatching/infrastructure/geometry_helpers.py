"""Reusable geometric functions shared across all Tessera plugins."""
import math

from qgis.core import QgsGeometry, QgsPointXY, QgsRectangle, QgsWkbTypes


def extract_polygons(geom):
    """Filter non-polygon components from a geometry, returning only polygons.

    Fast path: if the geometry is already a polygon type (Polygon or
    MultiPolygon), return it as-is.  Otherwise, decompose the geometry
    collection, keep only polygon parts, and merge them with unaryUnion.

    Args:
        geom: A QgsGeometry instance (may be empty, polygon, multi, or collection).

    Returns:
        QgsGeometry containing only polygon components, or empty geometry.
    """
    if geom.isEmpty():
        return QgsGeometry()

    # Fast path: already a polygon type (includes MultiPolygon)
    if geom.type() == QgsWkbTypes.PolygonGeometry:
        return geom

    # Slow path: geometry collection -- filter to polygon parts only
    parts = geom.asGeometryCollection()
    polygon_parts = [
        p for p in parts
        if not p.isEmpty() and p.type() == QgsWkbTypes.PolygonGeometry
    ]

    if not polygon_parts:
        return QgsGeometry()

    if len(polygon_parts) == 1:
        return polygon_parts[0]

    return QgsGeometry.unaryUnion(polygon_parts)


def clamp(value, lo, hi):
    """Clamp a numeric value to the range [lo, hi].

    Args:
        value: The number to clamp.
        lo: Lower bound.
        hi: Upper bound.

    Returns:
        value if lo <= value <= hi, else the nearest bound.
    """
    return max(lo, min(value, hi))


def regular_polygon(center, size, n_sides, rotation=0):
    """Create a regular polygon geometry.

    Vertices are placed at ``center + size * (cos(angle), sin(angle))``
    for angles ``rotation + i * 360 / n_sides``, where *rotation* is in
    degrees.

    Args:
        center: QgsPointXY for the polygon centre.
        size: Circumradius (distance from centre to each vertex).
        n_sides: Number of sides (>=3).
        rotation: Starting angle in degrees (default 0).

    Returns:
        QgsGeometry polygon with *n_sides* vertices.
    """
    angle_step = 360.0 / n_sides
    vertices = []
    for i in range(n_sides):
        angle_deg = rotation + i * angle_step
        angle_rad = math.radians(angle_deg)
        x = center.x() + size * math.cos(angle_rad)
        y = center.y() + size * math.sin(angle_rad)
        vertices.append(QgsPointXY(x, y))
    # Close the ring
    vertices.append(vertices[0])
    return QgsGeometry.fromPolygonXY([vertices])


def safe_pole_of_inaccessibility(geom, tolerance=1.0):
    """Multipolygon-safe wrapper for pole of inaccessibility.

    For a MultiPolygon, computes the pole for each part independently
    and returns the one with the largest inscribed-circle distance.

    Args:
        geom: QgsGeometry (Polygon or MultiPolygon).
        tolerance: Precision tolerance passed to poleOfInaccessibility.

    Returns:
        Tuple of (QgsPointXY, float) -- the pole point and its distance
        from the nearest boundary.
    """
    # Check if it's a MultiPolygon by WKB type
    wkb = geom.wkbType()
    is_multi = wkb in (
        QgsWkbTypes.MultiPolygon,
        QgsWkbTypes.MultiPolygon25D,
        QgsWkbTypes.MultiPolygonZ,
        QgsWkbTypes.MultiPolygonM,
        QgsWkbTypes.MultiPolygonZM,
    )

    if not is_multi:
        # Simple polygon -- poleOfInaccessibility returns (QgsGeometry, float)
        pole_geom, distance = geom.poleOfInaccessibility(tolerance)
        point = pole_geom.asPoint()
        return (QgsPointXY(point.x(), point.y()), distance)

    # MultiPolygon: evaluate each part, pick the one with largest distance
    best_point = None
    best_distance = -1.0

    parts = geom.asGeometryCollection()
    for part in parts:
        if part.isEmpty():
            continue
        pole_geom, distance = part.poleOfInaccessibility(tolerance)
        if distance > best_distance:
            best_distance = distance
            pt = pole_geom.asPoint()
            best_point = QgsPointXY(pt.x(), pt.y())

    return (best_point, best_distance)


def split_polygon_by_fraction(geom, fraction, orientation):
    """Split a polygon into filled and remainder parts by area fraction.

    Uses binary search to find a clipping boundary that divides the polygon
    so that the filled part contains approximately ``fraction`` of the total
    area.  Supports horizontal (bottom-to-top), vertical (left-to-right),
    diagonal (45 and 135 degrees), and radial (center-out) orientations.

    Args:
        geom: QgsGeometry (Polygon or MultiPolygon) in projected CRS.
        fraction: float 0-1, target area ratio for the filled part.
        orientation: str, one of ``'horizontal'``, ``'vertical'``,
            ``'diagonal_45'``, ``'diagonal_135'``, ``'radial'``.

    Returns:
        Tuple of (filled_geom, remainder_geom) as QgsGeometry objects.
        Both are polygon-type geometries (may be empty if fraction is 0 or 1).
    """
    # Edge cases: fraction at boundaries
    if fraction <= 0.0:
        return (QgsGeometry(), QgsGeometry(geom))
    if fraction >= 1.0:
        return (QgsGeometry(geom), QgsGeometry())

    total_area = geom.area()
    if total_area <= 0:
        return (QgsGeometry(), QgsGeometry())

    if orientation == 'radial':
        return _split_radial(geom, fraction, total_area)

    if orientation in ('diagonal_45', 'diagonal_135'):
        theta = 45.0 if orientation == 'diagonal_45' else 135.0
        return _split_diagonal(geom, fraction, total_area, theta)

    # horizontal or vertical
    return _split_axis_aligned(geom, fraction, total_area, orientation)


def _split_axis_aligned(geom, fraction, total_area, orientation):
    """Binary search split along horizontal or vertical axis.

    Horizontal sweeps bottom-to-top (y), vertical sweeps left-to-right (x).
    Uses QgsGeometry.clipped(QgsRectangle) for speed.
    """
    bbox = geom.boundingBox()
    pad = math.sqrt(bbox.width() ** 2 + bbox.height() ** 2)

    tolerance = 1e-4
    max_iterations = 50
    lo, hi = 0.0, 1.0

    for _ in range(max_iterations):
        t = (lo + hi) / 2.0
        clip_rect = _make_axis_clip_rect(bbox, pad, orientation, t)

        clipped = geom.clipped(clip_rect)
        clipped = extract_polygons(clipped)

        # Check for GEOS noding failure (returns empty silently)
        if clipped.isEmpty() and t > 0.01:
            # Fallback: use intersection instead of clipped
            clip_poly = QgsGeometry.fromRect(clip_rect)
            clipped = extract_polygons(geom.intersection(clip_poly))

        clipped_area = clipped.area() if not clipped.isEmpty() else 0.0
        current_fraction = clipped_area / total_area

        if abs(current_fraction - fraction) < tolerance:
            break

        if current_fraction < fraction:
            lo = t
        else:
            hi = t

    # Build the half-plane for remainder computation
    clip_rect = _make_axis_clip_rect(bbox, pad, orientation, t)

    filled = extract_polygons(geom.clipped(clip_rect))
    if filled.isEmpty() and t > 0.01:
        clip_poly = QgsGeometry.fromRect(clip_rect)
        filled = extract_polygons(geom.intersection(clip_poly))

    # Remainder: difference against the same clipping geometry (not filled)
    clip_poly = QgsGeometry.fromRect(clip_rect)
    remainder = extract_polygons(geom.difference(clip_poly))

    # Repair with buffer(0) if needed
    filled = _repair_if_needed(filled)
    remainder = _repair_if_needed(remainder)

    return (filled, remainder)


def _make_axis_clip_rect(bbox, pad, orientation, t):
    """Create clipping rectangle for axis-aligned split at parameter t.

    For horizontal: clips from ymin to ymin + t*(ymax-ymin), extending
    pad beyond the polygon in x and below in y.
    For vertical: clips from xmin to xmin + t*(xmax-xmin), extending
    pad beyond the polygon in y and left in x.
    """
    if orientation == 'horizontal':
        y_cut = bbox.yMinimum() + t * (bbox.yMaximum() - bbox.yMinimum())
        return QgsRectangle(
            bbox.xMinimum() - pad,
            bbox.yMinimum() - pad,
            bbox.xMaximum() + pad,
            y_cut,
        )
    else:  # vertical
        x_cut = bbox.xMinimum() + t * (bbox.xMaximum() - bbox.xMinimum())
        return QgsRectangle(
            bbox.xMinimum() - pad,
            bbox.yMinimum() - pad,
            x_cut,
            bbox.yMaximum() + pad,
        )


def _split_diagonal(geom, fraction, total_area, theta_deg):
    """Binary search split along a diagonal angle.

    The half-plane is {x : n . x <= d} where n = (cos(theta), sin(theta)).
    The clipping polygon is a rectangle extending pad behind the sweep line.
    """
    # Snap near-axis angles
    if abs(theta_deg % 180.0) < 0.1 or abs(theta_deg % 180.0 - 180.0) < 0.1:
        return _split_axis_aligned(geom, fraction, total_area, 'horizontal')
    if abs((theta_deg - 90.0) % 180.0) < 0.1:
        return _split_axis_aligned(geom, fraction, total_area, 'vertical')

    theta_rad = math.radians(theta_deg)
    nx = math.cos(theta_rad)
    ny = math.sin(theta_rad)

    bbox = geom.boundingBox()
    pad = math.sqrt(bbox.width() ** 2 + bbox.height() ** 2)

    # Compute d_min and d_max over all vertices of the geometry
    # Get all vertices via the abstract geometry
    vertices = _get_all_vertices(geom)
    dots = [nx * v.x() + ny * v.y() for v in vertices]
    d_min = min(dots)
    d_max = max(dots)

    tolerance = 1e-4
    max_iterations = 50
    lo, hi = 0.0, 1.0

    t = 0.5
    for _ in range(max_iterations):
        t = (lo + hi) / 2.0
        d = d_min + t * (d_max - d_min)
        clip_poly = _make_diagonal_clip_polygon(nx, ny, d, pad, bbox)

        clipped = extract_polygons(geom.intersection(clip_poly))
        clipped_area = clipped.area() if not clipped.isEmpty() else 0.0
        current_fraction = clipped_area / total_area

        if abs(current_fraction - fraction) < tolerance:
            break

        if current_fraction < fraction:
            lo = t
        else:
            hi = t

    # Final clipping
    d = d_min + t * (d_max - d_min)
    clip_poly = _make_diagonal_clip_polygon(nx, ny, d, pad, bbox)

    filled = extract_polygons(geom.intersection(clip_poly))
    remainder = extract_polygons(geom.difference(clip_poly))

    filled = _repair_if_needed(filled)
    remainder = _repair_if_needed(remainder)

    return (filled, remainder)


def _make_diagonal_clip_polygon(nx, ny, d, pad, bbox):
    """Build a clipping polygon for the half-plane {p : n.p <= d}.

    Constructs a large rectangle behind the sweep line perpendicular to
    the normal direction, extending pad in all directions.
    """
    # The sweep line is n.p = d.  Points on the line satisfy:
    #   nx*x + ny*y = d
    # Direction along the line: tangent = (-ny, nx)
    tx, ty = -ny, nx

    # A point on the line: p0 = d * n (closest point to origin on the line)
    p0x = d * nx
    p0y = d * ny

    # Four corners: extend along tangent by pad, and behind normal by pad
    # "Behind" means in the direction of -n (the filled side)
    c1 = QgsPointXY(p0x + pad * tx - pad * nx,
                     p0y + pad * ty - pad * ny)
    c2 = QgsPointXY(p0x - pad * tx - pad * nx,
                     p0y - pad * ty - pad * ny)
    c3 = QgsPointXY(p0x - pad * tx,
                     p0y - pad * ty)
    c4 = QgsPointXY(p0x + pad * tx,
                     p0y + pad * ty)

    return QgsGeometry.fromPolygonXY([[c1, c2, c3, c4, c1]])


def _get_all_vertices(geom):
    """Extract all vertex coordinates from a geometry as QgsPointXY list."""
    vertices = []
    # Use QgsGeometry.vertices() iterator which yields QgsPoint objects
    it = geom.vertices()
    while it.hasNext():
        v = it.next()
        vertices.append(QgsPointXY(v.x(), v.y()))
    return vertices


def _split_radial(geom, fraction, total_area):
    """Binary search split using expanding circle from center.

    Center is computed via safe_pole_of_inaccessibility (not centroid).
    Circle is approximated with 64 segments.
    """
    center, _ = safe_pole_of_inaccessibility(geom, tolerance=1.0)

    # Determine max radius: must be large enough to cover entire polygon
    bbox = geom.boundingBox()
    corners = [
        QgsPointXY(bbox.xMinimum(), bbox.yMinimum()),
        QgsPointXY(bbox.xMaximum(), bbox.yMinimum()),
        QgsPointXY(bbox.xMaximum(), bbox.yMaximum()),
        QgsPointXY(bbox.xMinimum(), bbox.yMaximum()),
    ]
    max_radius = max(
        math.hypot(c.x() - center.x(), c.y() - center.y())
        for c in corners
    )

    tolerance = 1e-4
    max_iterations = 50
    lo, hi = 0.0, max_radius

    r = max_radius / 2.0
    for _ in range(max_iterations):
        r = (lo + hi) / 2.0
        circle = regular_polygon(center, r, 64)

        clipped = extract_polygons(geom.intersection(circle))
        clipped_area = clipped.area() if not clipped.isEmpty() else 0.0
        current_fraction = clipped_area / total_area

        if abs(current_fraction - fraction) < tolerance:
            break

        if current_fraction < fraction:
            lo = r
        else:
            hi = r

    # Final split
    circle = regular_polygon(center, r, 64)
    filled = extract_polygons(geom.intersection(circle))
    remainder = extract_polygons(geom.difference(circle))

    filled = _repair_if_needed(filled)
    remainder = _repair_if_needed(remainder)

    return (filled, remainder)


def _repair_if_needed(geom):
    """Apply buffer(0) repair if geometry is invalid, otherwise return as-is.

    Per spec: do NOT use makeValid(). Use buffer(0) -> original only.
    """
    if geom.isEmpty():
        return geom
    if not geom.isGeosValid():
        repaired = geom.buffer(0, 5)
        if not repaired.isEmpty():
            return extract_polygons(repaired)
    return geom


def scale_geometry(geom, center, scale_factor):
    """Scale a geometry around a center point by a linear scale factor.

    Each vertex is moved: new_vertex = center + (vertex - center) * scale_factor.

    Args:
        geom: QgsGeometry (Polygon or MultiPolygon).
        center: QgsPointXY, the point to scale around.
        scale_factor: float, linear scale factor (1.0 = no change).

    Returns:
        QgsGeometry with all vertices scaled around center.
    """
    if geom.isEmpty() or scale_factor == 1.0:
        return QgsGeometry(geom)

    cx, cy = center.x(), center.y()

    new_geom = QgsGeometry(geom)
    vid = 0
    it = new_geom.vertices()
    moves = []
    while it.hasNext():
        v = it.next()
        nx = cx + (v.x() - cx) * scale_factor
        ny = cy + (v.y() - cy) * scale_factor
        moves.append((vid, nx, ny))
        vid += 1

    for vertex_index, nx, ny in moves:
        new_geom.moveVertex(nx, ny, vertex_index)

    return new_geom
