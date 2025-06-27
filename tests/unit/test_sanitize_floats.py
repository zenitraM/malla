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


def test_safe_jsonify(app):
    """Test that safe_jsonify properly sanitizes data and returns valid Flask response."""
    from malla.routes.api_routes import safe_jsonify

    test_data = {
        "normal": 42.0,
        "nan": float("nan"),
        "inf": float("inf"),
        "nested": {"neg_inf": float("-inf")},
    }

    with app.app_context():
        # This should not raise an exception
        response = safe_jsonify(test_data)

        # Should be a Flask response
        assert hasattr(response, "get_json")
        assert response.status_code == 200

        # The response data should be sanitized
        response_data = response.get_json()
        assert response_data["normal"] == 42.0
        assert response_data["nan"] is None
        assert response_data["inf"] is None
        assert response_data["nested"]["neg_inf"] is None
