"""Shared percentage-value interpretation logic for Tessera algorithms."""
from PyQt5.QtCore import QVariant

VALUE_RANGE_OPTIONS = ['0 - 100', '0 - 1', 'Auto scale']


def value_to_fraction(raw_value, value_range, auto_divisor):
    """Convert a raw attribute value to a 0-1 fraction.

    Args:
        raw_value: Numeric value from the attribute.
        value_range: 0 = 0-100, 1 = 0-1, 2 = auto-detect.
        auto_divisor: Maximum value from auto scale scan.

    Returns:
        float clamped to [0, 1].
    """
    if value_range == 0:  # 0-100
        fraction = raw_value / 100.0
    elif value_range == 1:  # 0-1
        fraction = raw_value
    else:  # auto scale
        fraction = raw_value / auto_divisor if auto_divisor else 0.0
    return max(0.0, min(1.0, fraction))


def detect_divisor(source, value_field, feedback):
    """Scan all feature values to find the maximum value for auto scaling.

    Auto scale mode divides each value by the maximum value across all
    features, producing a 0-1 fraction where the largest value maps to 1.0.

    Args:
        source: QgsProcessingFeatureSource.
        value_field: Name of the value field.
        feedback: QgsProcessingFeedback.

    Returns:
        float: Maximum value found, or 1.0 if no valid values.
    """
    max_val = None
    for feature in source.getFeatures():
        if feedback.isCanceled():
            break
        raw = feature.attribute(value_field)
        if raw is None or raw == QVariant():
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if max_val is None or val > max_val:
            max_val = val
    if max_val is None or max_val <= 0:
        return 1.0
    return max_val


def read_fraction(feature, percent_field, percent_range, auto_divisor,
                  feedback):
    """Read the percentage value from a feature and convert to fraction.

    Args:
        feature: QgsFeature.
        percent_field: Name of the percentage field.
        percent_range: 0 = 0-100, 1 = 0-1, 2 = auto-detect.
        auto_divisor: Divisor from detect_divisor().
        feedback: QgsProcessingFeedback.

    Returns:
        float in [0, 1] or None if value is missing/invalid.
    """
    raw_value = feature.attribute(percent_field)
    if raw_value is None or raw_value == QVariant():
        return None
    try:
        raw_value = float(raw_value)
    except (TypeError, ValueError):
        feedback.pushWarning(
            f'Feature {feature.id()}: non-numeric percent value '
            f'"{raw_value}" in field "{percent_field}", skipping flagging.')
        return None
    return value_to_fraction(raw_value, percent_range, auto_divisor)
