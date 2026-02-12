"""Topology-aware coordinate transformer.

Implements shared-vertex and shared-edge tracking so that algorithms which
modify polygon vertices (e.g. snap-to-grid, sketchy borders) preserve
topological consistency between adjacent features.  See spec section 4.2.
"""

import math
from collections import defaultdict

from qgis.core import QgsFeature, QgsGeometry, QgsPointXY


class TopologyTransformer:
    """Manages shared edges between adjacent features.

    Builds a unique vertex index on construction so that every coordinate
    position appearing in two or more features is identified.  The
    ``transform`` method applies a caller-supplied function to each unique
    vertex exactly once, guaranteeing that shared boundaries remain
    consistent after modification.
    """

    SNAP_TOLERANCE = 1e-6  # 1 micrometer, projected CRS units

    def __init__(self, features, feedback):
        """Build the shared vertex and shared edge indices.

        Parameters
        ----------
        features : list of QgsFeature
            Input features with polygon or multipolygon geometry.
        feedback : QgsProcessingFeedback or None
            Optional feedback object for progress/warning messages.
        """
        self._features = list(features)
        self._feedback = feedback

        # Store original areas for validation during rebuild
        self._original_areas = []
        for feat in self._features:
            geom = feat.geometry()
            self._original_areas.append(geom.area() if not geom.isNull() else 0.0)

        # Track whether each feature's original geometry was multipart
        self._is_multipart = []

        # Extract geometry data as nested lists:
        # _geometries[feat_idx][part_idx][ring_idx] = list of QgsPointXY
        self._geometries = []
        for feat in self._features:
            geom = feat.geometry()
            if geom.isNull() or geom.isEmpty():
                self._geometries.append([])
                self._is_multipart.append(False)
                continue
            if geom.isMultipart():
                parts = geom.asMultiPolygon()
                self._is_multipart.append(True)
            else:
                parts = [geom.asPolygon()]
                self._is_multipart.append(False)
            self._geometries.append(parts)

        # Phase 0: T-junction detection and repair
        self._repair_t_junctions()

        # Phase 1: Unique vertex extraction
        self._build_vertex_index()

    # ------------------------------------------------------------------
    # Phase 0 — T-Junction Detection
    # ------------------------------------------------------------------

    def _repair_t_junctions(self):
        """Detect and repair T-junctions across features.

        A T-junction exists when a vertex of feature A lies on an edge of
        feature B but B has no vertex at that position.  This method inserts
        the missing vertex into B's geometry representation.
        """
        if len(self._features) < 2:
            return

        # Collect all edges and all vertices with their owning feature index
        all_edges = []  # (feat_idx, part_idx, ring_idx, vert_idx, p1, p2)
        all_vertices = []  # (feat_idx, QgsPointXY)

        for feat_idx, parts in enumerate(self._geometries):
            for part_idx, rings in enumerate(parts):
                for ring_idx, ring in enumerate(rings):
                    for vert_idx in range(len(ring)):
                        all_vertices.append((feat_idx, ring[vert_idx]))
                        # Edge from this vertex to next (skip closing edge
                        # implicitly handled by ring[-1] == ring[0])
                        if vert_idx < len(ring) - 1:
                            p1 = ring[vert_idx]
                            p2 = ring[vert_idx + 1]
                            all_edges.append(
                                (feat_idx, part_idx, ring_idx, vert_idx, p1, p2)
                            )

        if not all_edges:
            return

        # Compute extent for grid cell size
        all_x = []
        all_y = []
        for _, pt in all_vertices:
            all_x.append(pt.x())
            all_y.append(pt.y())

        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        extent_w = max_x - min_x
        extent_h = max_y - min_y
        cell_size = max(extent_w, extent_h) / 1000.0
        if cell_size < self.SNAP_TOLERANCE:
            cell_size = self.SNAP_TOLERANCE * 1000

        # Build spatial hash on edges
        edge_grid = defaultdict(list)
        for edge_info in all_edges:
            _, _, _, _, p1, p2 = edge_info
            # Determine which grid cells this edge touches
            cells = self._edge_grid_cells(p1, p2, min_x, min_y, cell_size)
            for cell in cells:
                edge_grid[cell].append(edge_info)

        # For each vertex of each feature, check edges from OTHER features
        # Collect insertions: {(feat_idx, part_idx, ring_idx, vert_idx_after): [QgsPointXY, ...]}
        insertions = defaultdict(list)

        for v_feat_idx, v_pt in all_vertices:
            cell = self._point_grid_cell(v_pt, min_x, min_y, cell_size)
            # Check this cell and neighbors
            cx, cy = cell
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbor = (cx + dx, cy + dy)
                    if neighbor not in edge_grid:
                        continue
                    for edge_info in edge_grid[neighbor]:
                        e_feat_idx, e_part_idx, e_ring_idx, e_vert_idx, p1, p2 = edge_info
                        # Only check edges from OTHER features
                        if e_feat_idx == v_feat_idx:
                            continue
                        # Check if vertex is on this edge
                        t = self._point_on_edge_parameter(v_pt, p1, p2)
                        if t is None:
                            continue
                        # Guard: not near endpoints
                        tol_t = self.SNAP_TOLERANCE
                        edge_len = math.sqrt(
                            (p2.x() - p1.x()) ** 2 + (p2.y() - p1.y()) ** 2
                        )
                        if edge_len > 0:
                            tol_t = self.SNAP_TOLERANCE / edge_len
                        if t <= tol_t or t >= 1.0 - tol_t:
                            continue
                        # Insert this vertex into the edge's feature
                        key = (e_feat_idx, e_part_idx, e_ring_idx, e_vert_idx)
                        insertions[key].append((t, v_pt))

        # Apply insertions in reverse order (by vert_idx) to preserve indices
        for (feat_idx, part_idx, ring_idx, vert_idx_after), t_pts in insertions.items():
            # Sort by parameter t to insert in order
            t_pts.sort(key=lambda x: x[0])
            ring = self._geometries[feat_idx][part_idx][ring_idx]
            # Insert after vert_idx_after, before vert_idx_after+1
            insert_pos = vert_idx_after + 1
            for i, (t, pt) in enumerate(t_pts):
                # Check if this point already exists in the ring (near-duplicate)
                already_exists = False
                for existing_pt in ring:
                    if (abs(existing_pt.x() - pt.x()) < self.SNAP_TOLERANCE and
                            abs(existing_pt.y() - pt.y()) < self.SNAP_TOLERANCE):
                        already_exists = True
                        break
                if not already_exists:
                    ring.insert(insert_pos + i, QgsPointXY(pt.x(), pt.y()))

    def _point_grid_cell(self, pt, min_x, min_y, cell_size):
        """Return the grid cell (col, row) for a point."""
        col = int((pt.x() - min_x) / cell_size)
        row = int((pt.y() - min_y) / cell_size)
        return (col, row)

    def _edge_grid_cells(self, p1, p2, min_x, min_y, cell_size):
        """Return all grid cells that an edge passes through."""
        c1 = self._point_grid_cell(p1, min_x, min_y, cell_size)
        c2 = self._point_grid_cell(p2, min_x, min_y, cell_size)
        min_col = min(c1[0], c2[0])
        max_col = max(c1[0], c2[0])
        min_row = min(c1[1], c2[1])
        max_row = max(c1[1], c2[1])
        cells = set()
        for col in range(min_col, max_col + 1):
            for row in range(min_row, max_row + 1):
                cells.add((col, row))
        return cells

    def _point_on_edge_parameter(self, pt, p1, p2):
        """Return parameter t if pt is within SNAP_TOLERANCE of segment p1-p2.

        Returns None if pt is not close to the edge.  Otherwise returns
        t in [0, 1] representing the projection parameter along the edge.
        """
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        len_sq = dx * dx + dy * dy
        if len_sq < self.SNAP_TOLERANCE * self.SNAP_TOLERANCE:
            return None  # degenerate edge

        # Project pt onto the line through p1-p2
        t = ((pt.x() - p1.x()) * dx + (pt.y() - p1.y()) * dy) / len_sq
        if t < 0.0 or t > 1.0:
            return None

        # Compute closest point on segment
        closest_x = p1.x() + t * dx
        closest_y = p1.y() + t * dy
        dist_sq = (pt.x() - closest_x) ** 2 + (pt.y() - closest_y) ** 2

        if dist_sq <= self.SNAP_TOLERANCE * self.SNAP_TOLERANCE:
            return t
        return None

    # ------------------------------------------------------------------
    # Phase 1 — Unique Vertex Extraction
    # ------------------------------------------------------------------

    def _build_vertex_index(self):
        """Build the unique vertex index from current geometry data."""
        self._vertex_to_id = {}   # (rounded_x, rounded_y) -> unique_id
        self._id_to_point = {}    # unique_id -> QgsPointXY (original coords)
        self._id_to_locations = defaultdict(list)  # unique_id -> [(feat, part, ring, vert)]
        next_id = 0

        inv_tol = 1.0 / self.SNAP_TOLERANCE  # for rounding

        for feat_idx, parts in enumerate(self._geometries):
            for part_idx, rings in enumerate(parts):
                for ring_idx, ring in enumerate(rings):
                    for vert_idx, pt in enumerate(ring):
                        key = (round(pt.x() * inv_tol) / inv_tol,
                               round(pt.y() * inv_tol) / inv_tol)
                        if key not in self._vertex_to_id:
                            self._vertex_to_id[key] = next_id
                            self._id_to_point[next_id] = QgsPointXY(pt.x(), pt.y())
                            next_id += 1
                        vid = self._vertex_to_id[key]
                        self._id_to_locations[vid].append(
                            (feat_idx, part_idx, ring_idx, vert_idx)
                        )

    # ------------------------------------------------------------------
    # Densify Shared Edges
    # ------------------------------------------------------------------

    def densify_shared_edges(self, interval):
        """Densify shared edges identically and private edges independently.

        Must be called BEFORE ``transform()``.  After densification the
        internal vertex index is rebuilt.

        Parameters
        ----------
        interval : float
            Maximum distance between consecutive vertices after densification.
        """
        if not self._geometries:
            return

        inv_tol = 1.0 / self.SNAP_TOLERANCE

        # Step 1: Identify shared edges (pairs of adjacent vertices whose
        # rounded coordinates match across two features).
        # Build an edge index: (rounded_p1, rounded_p2) canonical -> list of
        # (feat_idx, part_idx, ring_idx, vert_idx)
        edge_to_locations = defaultdict(list)

        for feat_idx, parts in enumerate(self._geometries):
            for part_idx, rings in enumerate(parts):
                for ring_idx, ring in enumerate(rings):
                    for vert_idx in range(len(ring) - 1):
                        pa = ring[vert_idx]
                        pb = ring[vert_idx + 1]
                        ka = (round(pa.x() * inv_tol) / inv_tol,
                              round(pa.y() * inv_tol) / inv_tol)
                        kb = (round(pb.x() * inv_tol) / inv_tol,
                              round(pb.y() * inv_tol) / inv_tol)
                        # Canonical direction: smaller x first, then smaller y
                        canonical = (min(ka, kb), max(ka, kb))
                        edge_to_locations[canonical].append(
                            (feat_idx, part_idx, ring_idx, vert_idx)
                        )

        # Shared edges: appear in 2+ locations from different features
        shared_edges = set()  # set of canonical edge keys
        for canonical, locs in edge_to_locations.items():
            feat_indices = set(loc[0] for loc in locs)
            if len(feat_indices) >= 2:
                shared_edges.add(canonical)

        # Step 2: Densify shared edges identically
        # Process shared edges and record which (feat, part, ring, vert) segments
        # need new intermediate vertices inserted
        # insertions: {(feat_idx, part_idx, ring_idx, vert_idx): [list of QgsPointXY]}
        shared_insertions = defaultdict(list)

        processed_canonicals = set()
        for canonical, locs in edge_to_locations.items():
            if canonical not in shared_edges:
                continue
            if canonical in processed_canonicals:
                continue
            processed_canonicals.add(canonical)

            # Compute new vertices using canonical direction
            ca, cb = canonical
            # Canonical direction: ca < cb (by x, then y)
            length = math.sqrt((cb[0] - ca[0]) ** 2 + (cb[1] - ca[1]) ** 2)
            if length < interval:
                continue

            n_new = int(length / interval)
            if n_new < 1:
                continue

            # Generate intermediate points in canonical direction
            new_pts_canonical = []
            for i in range(1, n_new + 1):
                frac = i / (n_new + 1)
                nx = ca[0] + frac * (cb[0] - ca[0])
                ny = ca[1] + frac * (cb[1] - ca[1])
                new_pts_canonical.append(QgsPointXY(nx, ny))

            # Insert into all locations that have this edge
            for loc in locs:
                feat_idx, part_idx, ring_idx, vert_idx = loc
                ring = self._geometries[feat_idx][part_idx][ring_idx]
                pa = ring[vert_idx]
                pb = ring[vert_idx + 1]
                ka = (round(pa.x() * inv_tol) / inv_tol,
                      round(pa.y() * inv_tol) / inv_tol)
                # Determine if this edge's direction matches canonical
                if ka == ca:
                    # Same direction as canonical
                    pts = list(new_pts_canonical)
                else:
                    # Reverse direction
                    pts = list(reversed(new_pts_canonical))
                shared_insertions[(feat_idx, part_idx, ring_idx, vert_idx)] = pts

        # Step 3: Densify private edges
        private_insertions = defaultdict(list)
        for canonical, locs in edge_to_locations.items():
            if canonical in shared_edges:
                continue
            ca, cb = canonical
            length = math.sqrt((cb[0] - ca[0]) ** 2 + (cb[1] - ca[1]) ** 2)
            if length < interval:
                continue

            n_new = int(length / interval)
            if n_new < 1:
                continue

            for loc in locs:
                feat_idx, part_idx, ring_idx, vert_idx = loc
                ring = self._geometries[feat_idx][part_idx][ring_idx]
                pa = ring[vert_idx]
                pb = ring[vert_idx + 1]
                pts = []
                for i in range(1, n_new + 1):
                    frac = i / (n_new + 1)
                    nx = pa.x() + frac * (pb.x() - pa.x())
                    ny = pa.y() + frac * (pb.y() - pa.y())
                    pts.append(QgsPointXY(nx, ny))
                private_insertions[(feat_idx, part_idx, ring_idx, vert_idx)] = pts

        # Step 4: Apply all insertions (process rings in reverse vert_idx order)
        all_insertions = {}
        all_insertions.update(private_insertions)
        all_insertions.update(shared_insertions)

        # Group by (feat_idx, part_idx, ring_idx) and sort by vert_idx descending
        ring_insertions = defaultdict(list)
        for (feat_idx, part_idx, ring_idx, vert_idx), pts in all_insertions.items():
            if pts:
                ring_insertions[(feat_idx, part_idx, ring_idx)].append(
                    (vert_idx, pts)
                )

        for ring_key, insertion_list in ring_insertions.items():
            feat_idx, part_idx, ring_idx = ring_key
            ring = self._geometries[feat_idx][part_idx][ring_idx]
            # Sort by vert_idx descending to preserve indices during insertion
            insertion_list.sort(key=lambda x: x[0], reverse=True)
            for vert_idx, pts in insertion_list:
                for i, pt in enumerate(pts):
                    ring.insert(vert_idx + 1 + i, pt)

        # Ensure rings are still properly closed after insertions
        for feat_idx, parts in enumerate(self._geometries):
            for part_idx, rings in enumerate(parts):
                for ring_idx, ring in enumerate(rings):
                    if len(ring) >= 2:
                        first = ring[0]
                        last = ring[-1]
                        if (abs(first.x() - last.x()) > self.SNAP_TOLERANCE or
                                abs(first.y() - last.y()) > self.SNAP_TOLERANCE):
                            ring.append(QgsPointXY(first.x(), first.y()))

        # Step 5: Rebuild vertex index on densified geometries
        self._build_vertex_index()

    # ------------------------------------------------------------------
    # Transform
    # ------------------------------------------------------------------

    def transform(self, vertex_fn):
        """Apply a transformation function to every unique vertex.

        Parameters
        ----------
        vertex_fn : callable
            Signature ``(QgsPointXY, int) -> QgsPointXY``.  Called exactly
            once per unique vertex.  The int argument is the vertex's
            unique identifier (useful for deterministic seeding).

        Returns
        -------
        list of QgsFeature
            New features with the same attributes as the originals but
            with transformed geometry.
        """
        if not self._features:
            return []

        # Phase 2: Call vertex_fn once per unique vertex
        transformed = {}  # unique_id -> new QgsPointXY
        for vid, original_pt in self._id_to_point.items():
            transformed[vid] = vertex_fn(QgsPointXY(original_pt), vid)

        inv_tol = 1.0 / self.SNAP_TOLERANCE

        # Phase 3: Rebuild geometries
        results = []
        for feat_idx, feat in enumerate(self._features):
            parts = self._geometries[feat_idx]
            if not parts:
                # Empty geometry — copy feature as-is
                new_feat = QgsFeature(feat.fields())
                new_feat.setAttributes(feat.attributes())
                new_feat.setGeometry(feat.geometry())
                results.append(new_feat)
                continue

            new_parts = []
            for part_idx, rings in enumerate(parts):
                new_rings = []
                for ring_idx, ring in enumerate(rings):
                    new_ring = []
                    for vert_idx, pt in enumerate(ring):
                        key = (round(pt.x() * inv_tol) / inv_tol,
                               round(pt.y() * inv_tol) / inv_tol)
                        vid = self._vertex_to_id.get(key)
                        if vid is not None and vid in transformed:
                            new_ring.append(transformed[vid])
                        else:
                            # Fallback: use original point
                            new_ring.append(QgsPointXY(pt.x(), pt.y()))

                    # Ensure ring is closed
                    if len(new_ring) >= 2:
                        first = new_ring[0]
                        last = new_ring[-1]
                        if (abs(first.x() - last.x()) > 1e-12 or
                                abs(first.y() - last.y()) > 1e-12):
                            new_ring[-1] = QgsPointXY(first.x(), first.y())

                    new_rings.append(new_ring)
                new_parts.append(new_rings)

            # Build geometry — preserve original geometry type
            if self._is_multipart[feat_idx]:
                new_geom = QgsGeometry.fromMultiPolygonXY(new_parts)
            elif len(new_parts) == 1:
                new_geom = QgsGeometry.fromPolygonXY(new_parts[0])
            else:
                new_geom = QgsGeometry.fromMultiPolygonXY(new_parts)

            # Validation / repair chain
            original_area = self._original_areas[feat_idx]
            new_geom = self._validate_and_repair(
                new_geom, feat.geometry(), original_area
            )

            new_feat = QgsFeature(feat.fields())
            new_feat.setAttributes(feat.attributes())
            new_feat.setGeometry(new_geom)
            results.append(new_feat)

        return results

    # ------------------------------------------------------------------
    # Geometry Validation / Repair
    # ------------------------------------------------------------------

    def _validate_and_repair(self, new_geom, original_geom, original_area):
        """Validate rebuilt geometry and attempt repair if needed.

        Returns a valid geometry, falling back to the original if all
        repair attempts fail.
        """
        # Check basic validity
        if self._geometry_acceptable(new_geom, original_area):
            return new_geom

        # Try buffer(0)
        try:
            repaired = new_geom.buffer(0, 5)
            if not repaired.isNull() and self._geometry_acceptable(repaired, original_area):
                return repaired
        except Exception:
            pass

        # Try makeValid()
        try:
            repaired = new_geom.makeValid()
            if not repaired.isNull() and self._geometry_acceptable(repaired, original_area):
                return repaired
        except Exception:
            pass

        # All repair attempts failed — keep original geometry
        if self._feedback is not None:
            try:
                self._feedback.pushWarning(
                    'TopologyTransformer: geometry repair failed, '
                    'keeping original geometry'
                )
            except Exception:
                pass
        return QgsGeometry(original_geom)

    def _geometry_acceptable(self, geom, original_area):
        """Check if a geometry meets minimum validity requirements."""
        if geom.isNull() or geom.isEmpty():
            return False
        area = geom.area()
        if area <= 0:
            return False
        if original_area > 0 and area < 0.01 * original_area:
            return False
        return True
