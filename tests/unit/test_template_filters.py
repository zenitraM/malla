"""
Unit tests for template filters.
"""

import pytest

from malla.web_ui import create_app


@pytest.fixture(scope="module")
def app():
    import tempfile

    from tests.fixtures.database_fixtures import DatabaseFixtures

    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tf.close()
    DatabaseFixtures().create_test_database(tf.name)
    application = create_app(_cfg_for(tf.name))
    yield application


def _cfg_for(db_path):
    from malla.config import AppConfig

    return AppConfig(database_file=db_path)


class TestTemplateFilters:
    """Test template filter registration and functionality."""

    def test_format_rssi_filter_exists(self, app):
        """Test that format_rssi filter is properly registered."""
        # app fixture: isolated temp DB, no cwd artefacts

        with app.app_context():
            # Check if filter is registered
            assert "format_rssi" in app.jinja_env.filters

            # Test the filter function
            filter_func = app.jinja_env.filters["format_rssi"]

            # Test with valid values
            assert filter_func(None) == "N/A"
            assert filter_func(-50.0) == "-50.0"
            assert filter_func(-50.123) == "-50.1"
            assert filter_func("-50.123") == "-50.1"

            # Test with invalid values
            assert filter_func("invalid") == "invalid"

    def test_format_snr_filter_exists(self, app):
        """Test that format_snr filter is properly registered."""
        # app fixture: isolated temp DB, no cwd artefacts

        with app.app_context():
            # Check if filter is registered
            assert "format_snr" in app.jinja_env.filters

            # Test the filter function
            filter_func = app.jinja_env.filters["format_snr"]

            # Test with valid values
            assert filter_func(None) == "N/A"
            assert filter_func(5.0) == "5.00"
            assert filter_func(5.123) == "5.12"
            assert filter_func("5.123") == "5.12"

            # Test with invalid values
            assert filter_func("invalid") == "invalid"

    def test_all_filters_registered(self, app):
        """Test that all expected filters are registered."""
        # app fixture: isolated temp DB, no cwd artefacts

        with app.app_context():
            expected_filters = [
                "format_node_id",
                "format_node_short_name",
                "format_time_ago",
                "safe_json",
                "format_rssi",
                "format_snr",
                "format_signal",
                "markdown",
            ]

            for filter_name in expected_filters:
                assert filter_name in app.jinja_env.filters, (
                    f"Filter {filter_name} not registered"
                )

    def test_template_rendering_with_filters(self, app):
        """Test that templates can be rendered with the filters."""
        with app.app_context():
            from flask import render_template_string

            # Test format_rssi filter in template
            template = "{{ value|format_rssi }}"
            result = render_template_string(template, value=-50.123)
            assert result == "-50.1"

            # Test format_snr filter in template
            template = "{{ value|format_snr }}"
            result = render_template_string(template, value=5.123)
            assert result == "5.12"

            # Test with None values
            template = "{{ value|format_rssi }}"
            result = render_template_string(template, value=None)
            assert result == "N/A"

    def test_format_snr_rendered(self, app):
        """Pin the template usage: node_detail must render two decimals."""
        with app.test_request_context():
            rendered = app.jinja_env.from_string("{{ v|format_snr }} dB").render(
                v=-0.6768815127497501
            )
            assert rendered == "-0.68 dB", rendered
