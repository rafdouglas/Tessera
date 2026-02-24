"""Consistent output feature/layer construction for Tessera."""
from PyQt5.QtCore import QMetaType, QVariant
from qgis.core import QgsFeature, QgsField, QgsFields, QgsGeometry

# --- Shared constants ---
BATCH_SIZE = 1000

_METATYPE_TO_VARIANT = {
    QMetaType.Type.QString: QVariant.String,
    QMetaType.Type.Int: QVariant.Int,
    QMetaType.Type.Double: QVariant.Double,
    QMetaType.Type.Bool: QVariant.Bool,
}

_qgsfield_accepts_metatype = None


def _resolve_field_type(metatype):
    """Convert QMetaType.Type to QVariant.Type on QGIS versions that need it.

    QGIS < 3.38 does not accept QMetaType.Type in QgsField(); those versions
    require QVariant.Type instead. Detection is lazy and cached.
    """
    global _qgsfield_accepts_metatype
    if _qgsfield_accepts_metatype is None:
        try:
            QgsField(name='_compat_probe', type=QMetaType.Type.QString)
            _qgsfield_accepts_metatype = True
        except TypeError:
            _qgsfield_accepts_metatype = False
    if _qgsfield_accepts_metatype:
        return metatype
    return _METATYPE_TO_VARIANT[metatype]


def create_output_fields(input_fields, extra_fields):
    """Merge input layer fields with extra Tessera fields, deduplicating.

    Args:
        input_fields: QgsFields from the source layer.
        extra_fields: list of (name, QMetaType.Type) tuples for Tessera columns.

    Returns:
        QgsFields with input fields first (minus any that collide with
        extra_fields names), then extra_fields appended.
    """
    extra_names = {name for name, _ in extra_fields}
    result = QgsFields()

    # Input fields first, skipping collisions with extra fields and
    # GeoPackage primary key ('fid') which must be auto-generated
    for i in range(input_fields.count()):
        field = input_fields.field(i)
        if field.name() in extra_names:
            continue
        if field.name().lower() == 'fid':
            continue
        result.append(field)

    # Extra fields appended in order
    for name, metatype in extra_fields:
        result.append(QgsField(name=name, type=_resolve_field_type(metatype)))

    return result


def build_feature(geometry, parent_feature, algorithm_id, extra_attrs,
                  output_fields, carry_all_attributes=True):
    """Build an output QgsFeature with promoted geometry and merged attributes.

    Args:
        geometry: QgsGeometry (promoted to MultiPolygon if single-part).
        parent_feature: QgsFeature whose attributes may be carried forward.
        algorithm_id: string identifier for the algorithm (e.g. 'tessellate').
        extra_attrs: dict of additional attribute name->value pairs.
        output_fields: QgsFields defining the output schema.
        carry_all_attributes: if True, copy parent attributes to output.

    Returns:
        QgsFeature with MultiPolygon geometry and populated attributes.
    """
    feat = QgsFeature(output_fields)

    # --- Geometry: promote to multi if needed ---
    geom_copy = QgsGeometry(geometry)
    if not geom_copy.isEmpty() and not geom_copy.isNull():
        if not geom_copy.isMultipart():
            geom_copy.convertToMultiType()
    feat.setGeometry(geom_copy)

    # --- Carry parent attributes (by name match) ---
    if carry_all_attributes:
        parent_fields = parent_feature.fields()
        for i in range(parent_fields.count()):
            field_name = parent_fields.field(i).name()
            idx = output_fields.indexOf(field_name)
            if idx >= 0:
                feat.setAttribute(idx, parent_feature.attribute(i))

    # --- Standard Tessera attributes ---
    feat.setAttribute('_tessera_algorithm', algorithm_id)
    feat.setAttribute('_tessera_parent_fid', parent_feature.id())

    # --- Extra attributes ---
    for attr_name, attr_value in extra_attrs.items():
        feat.setAttribute(attr_name, attr_value)

    return feat
