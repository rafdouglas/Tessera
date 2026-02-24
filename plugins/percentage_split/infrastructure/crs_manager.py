"""CRS detection and reprojection for Tessera."""
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
    QgsRectangle,
)

# Projection identifiers recognized as equal-area
EQUAL_AREA_PROJS = {'aea', 'laea', 'cea', 'eqearth', 'moll', 'sinu', 'eck4', 'eck6'}


# Engineering CRS projection string (flat Cartesian output)
ENGINEERING_CRS_PROJ = (
    '+proj=tmerc +lat_0=0 +lon_0=0 +k=1 '
    '+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs'
)

def _parse_proj_id(crs):
    """Extract the +proj= value from a CRS proj string.

    Returns the projection identifier (e.g. 'aea', 'longlat') or empty string
    if parsing fails.
    """
    proj_str = crs.toProj()
    for token in proj_str.split():
        if token.startswith('+proj='):
            return token.split('=', 1)[1]
    return ''


def is_equal_area(crs):
    """Return True if *crs* uses an equal-area projection.

    Detection is based on parsing the proj string for the +proj= parameter
    and checking against the EQUAL_AREA_PROJS set.
    """
    return _parse_proj_id(crs) in EQUAL_AREA_PROJS


def needs_antimeridian_split(geometry):
    """Return True if *geometry* crosses the antimeridian (+-180 longitude).

    Heuristic: the bounding-box x-range exceeds 180 degrees, or any vertex
    has longitude > 180 (common convention for wrapping past the antimeridian).

    .. note::
        Reserved for future use. No algorithm currently calls this function,
        but it is retained for planned antimeridian-aware processing in a
        future release.
    """
    if geometry.isEmpty():
        return False
    bbox = geometry.boundingBox()
    # Vertices beyond +180 indicate wrapping past the antimeridian
    if bbox.xMaximum() > 180:
        return True
    # A bounding box wider than 180 degrees also signals a crossing
    if bbox.width() > 180:
        return True
    return False



def create_engineering_crs():
    """Create a flat Cartesian engineering CRS (Transverse Mercator at origin).

    Used by layout algorithms (Arrange Features, Grid Arrangement) for
    distortion-free Cartesian output.
    """
    crs = QgsCoordinateReferenceSystem()
    crs.createFromProj(ENGINEERING_CRS_PROJ)
    return crs

class WorkingCRS:
    """Choose and manage a working CRS appropriate for the data extent.

    Parameters
    ----------
    source_crs : QgsCoordinateReferenceSystem
        CRS of the input data.
    extent : QgsRectangle
        Geographic bounding box of the data (in *source_crs* units).
    strategy : str, optional
        ``"equal_area"`` (default) -- automatically select an equal-area CRS.
        ``"preserve"`` -- keep the source CRS unchanged.
    """

    def __init__(self, source_crs, extent, strategy='equal_area'):
        self._source_crs = source_crs
        self._working_crs = self._choose_crs(source_crs, extent, strategy)

        # Build transforms (both will be identity if CRS match)
        self._fwd = QgsCoordinateTransform(
            source_crs, self._working_crs, QgsProject.instance()
        )
        self._inv = QgsCoordinateTransform(
            self._working_crs, source_crs, QgsProject.instance()
        )

    # ------------------------------------------------------------------
    # CRS selection
    # ------------------------------------------------------------------

    @staticmethod
    def _choose_crs(source_crs, extent, strategy):
        """Return the working CRS based on strategy and extent."""
        if strategy == 'preserve':
            return source_crs

        # If source is already equal-area, nothing to do
        if is_equal_area(source_crs):
            return source_crs

        # If source is already projected (not geographic), preserve it.
        # Projected CRS coordinates are in a flat system (meters/feet).
        # Re-projecting to equal-area and back distorts grid cell shapes.
        # The degree-based extent thresholds below are meaningless for
        # meter-based coordinates.
        if not source_crs.isGeographic():
            return source_crs

        width = extent.width()
        height = extent.height()

        # Global extent
        if width > 90 or height > 60:
            return QgsCoordinateReferenceSystem.fromEpsgId(8857)

        # Hemispheric (large latitude span)
        if height > 30:
            return QgsCoordinateReferenceSystem.fromEpsgId(8857)

        # Local -- construct Albers Equal Area with Snyder 1/6 rule
        y_min = extent.yMinimum()
        y_max = extent.yMaximum()
        y_range = y_max - y_min

        lat_1 = y_min + y_range / 6
        lat_2 = y_max - y_range / 6
        lat_0 = (y_min + y_max) / 2
        lon_0 = (extent.xMinimum() + extent.xMaximum()) / 2

        proj_string = (
            f'+proj=aea +lat_1={lat_1} +lat_2={lat_2} '
            f'+lat_0={lat_0} +lon_0={lon_0} '
            f'+datum=WGS84 +units=m +no_defs'
        )
        crs = QgsCoordinateReferenceSystem()
        crs.createFromProj(proj_string)
        return crs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def working_crs(self):
        """Return the working CRS."""
        return self._working_crs

    def forward(self, geometry):
        """Transform *geometry* from source CRS to working CRS.

        Returns a new QgsGeometry; the original is not modified.
        Empty geometries are returned as-is.
        """
        if geometry.isEmpty():
            return QgsGeometry()
        geom_copy = QgsGeometry(geometry)
        geom_copy.transform(self._fwd)
        return geom_copy

    def inverse(self, geometry):
        """Transform *geometry* from working CRS back to source CRS.

        Returns a new QgsGeometry; the original is not modified.
        Empty geometries are returned as-is.
        """
        if geometry.isEmpty():
            return QgsGeometry()
        geom_copy = QgsGeometry(geometry)
        geom_copy.transform(self._inv)
        return geom_copy
