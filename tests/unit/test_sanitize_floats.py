import math

from malla.utils.serialization_utils import sanitize_floats


def test_sanitize_floats_basic():
    input_data = {
        "valid": 123.45,
        "nan_value": float("nan"),
        "inf_value": float("inf"),
        "nested": {
            "neg_inf": float("-inf"),
            "list": [1, 2, math.nan, math.inf, -math.inf],
        },
    }

    sanitized = sanitize_floats(input_data)

    # Valid number should remain unchanged
    assert sanitized["valid"] == 123.45
    # Special floats should become None
    assert sanitized["nan_value"] is None
    assert sanitized["inf_value"] is None
    assert sanitized["nested"]["neg_inf"] is None
    # All problematic values in list should be converted
    assert sanitized["nested"]["list"] == [1, 2, None, None, None]
