"""Shared scale computation helpers for Scale by Value and Replace with Shape."""
import math

from PyQt5.QtCore import QVariant

from .geometry_helpers import clamp

# Scale method enum indices (shared across algorithms)
METHOD_PROPORTIONAL_AREA = 0
METHOD_PROPORTIONAL_SQRT = 1
METHOD_PROPORTIONAL_LOG = 2

# Reference type enum indices (shared across algorithms)
REF_MAX_VALUE = 0
REF_MEAN_VALUE = 1
REF_FIXED = 2


def compute_scale_factor(value, ref_value, scale_method,
                         min_scale=0.0, max_scale=10.0):
    """Compute area scale factor for a feature value.

    Args:
        value: Feature attribute value (positive, non-zero).
        ref_value: Reference value R (positive, non-zero).
        scale_method: METHOD_PROPORTIONAL_AREA, METHOD_PROPORTIONAL_SQRT,
            or METHOD_PROPORTIONAL_LOG.
        min_scale: Minimum allowed scale factor.
        max_scale: Maximum allowed scale factor.

    Returns:
        float scale factor clamped to [min_scale, max_scale].
    """
    raw_ratio = value / ref_value
    if scale_method == METHOD_PROPORTIONAL_AREA:
        scale = clamp(raw_ratio, min_scale, max_scale)
    elif scale_method == METHOD_PROPORTIONAL_SQRT:
        scale = clamp(math.sqrt(raw_ratio), min_scale, max_scale)
    else:  # METHOD_PROPORTIONAL_LOG
        scale = clamp(
            math.log(value + 1) / math.log(ref_value + 1),
            min_scale, max_scale,
        )
    return scale


def compute_reference(source, value_field, reference_type, fixed_reference,
                      feedback):
    """First-pass scan to compute the reference value R.

    Args:
        source: QgsProcessingFeatureSource.
        value_field: Name of the numeric field.
        reference_type: REF_MAX_VALUE, REF_MEAN_VALUE, or REF_FIXED.
        fixed_reference: User-specified fixed reference value.
        feedback: QgsProcessingFeedback.

    Returns:
        float reference value, or None if no valid values found.
    """
    if reference_type == REF_FIXED:
        return fixed_reference

    total = 0.0
    count = 0
    max_val = None

    for feature in source.getFeatures():
        if feedback.isCanceled():
            return None

        raw = feature.attribute(value_field)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue

        if val <= 0:
            continue

        total += val
        count += 1
        if max_val is None or val > max_val:
            max_val = val

    if count == 0:
        return None

    if reference_type == REF_MAX_VALUE:
        return max_val
    return total / count


def validate_scale_value(feature, value_field, feedback):
    """Validate a feature's scale value, emitting warnings for invalid data.

    Args:
        feature: QgsFeature to read the value from.
        value_field: Name of the numeric attribute field.
        feedback: QgsProcessingFeedback for warnings/errors.

    Returns:
        float value if valid, or None if the value should be skipped.
    """
    raw_value = feature.attribute(value_field)
    if raw_value is None or raw_value == QVariant():
        feedback.pushWarning(
            f'Feature {feature.id()}: NULL value in field '
            f'"{value_field}", skipping.'
        )
        return None

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        feedback.pushWarning(
            f'Feature {feature.id()}: non-numeric value '
            f'"{raw_value}" in field "{value_field}", skipping.'
        )
        return None

    if value < 0:
        feedback.reportError(
            f'Feature {feature.id()}: negative value {value} '
            f'in field "{value_field}". Negative values are not supported.'
        )
        return None

    if value == 0:
        feedback.pushWarning(
            f'Feature {feature.id()}: zero value in field '
            f'"{value_field}", skipping.'
        )
        return None

    return value
