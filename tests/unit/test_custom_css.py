"""Tests for operator page customization (custom_css / custom_html_head)."""

import os
import tempfile

from malla.config import AppConfig, _clear_config_cache, load_config
from malla.web_ui import create_app
from tests.fixtures.database_fixtures import DatabaseFixtures


def test_customization_defaults(monkeypatch):
    """Both customization fields default to empty (no behaviour change)."""

    _clear_config_cache()
    monkeypatch.delenv("MALLA_CUSTOM_CSS", raising=False)
    monkeypatch.delenv("MALLA_CUSTOM_HTML_HEAD", raising=False)

    cfg = load_config(config_path=None)

    assert cfg.custom_css == ""
    assert cfg.custom_html_head == ""


def test_customization_from_yaml(tmp_path, monkeypatch):
    """custom_css / custom_html_head can be set via the YAML config file."""

    _clear_config_cache()
    monkeypatch.delenv("MALLA_CUSTOM_CSS", raising=False)
    monkeypatch.delenv("MALLA_CUSTOM_HTML_HEAD", raising=False)

    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(
        'custom_css: ".navbar { background: #123456; }"\n'
        "custom_html_head: '<meta name=\"x\" content=\"y\">'\n"
    )

    cfg = load_config(config_path=yaml_file)

    assert cfg.custom_css == ".navbar { background: #123456; }"
    assert cfg.custom_html_head == '<meta name="x" content="y">'


def test_customization_env_override(monkeypatch):
    """MALLA_CUSTOM_CSS / MALLA_CUSTOM_HTML_HEAD override YAML/defaults."""

    _clear_config_cache()
    monkeypatch.setenv("MALLA_CUSTOM_CSS", ":root{--bs-primary:#14532d}")
    monkeypatch.setenv("MALLA_CUSTOM_HTML_HEAD", "<link rel='icon' href='/f.ico'>")

    cfg = load_config(config_path=None)

    assert cfg.custom_css == ":root{--bs-primary:#14532d}"
    assert cfg.custom_html_head == "<link rel='icon' href='/f.ico'>"


def _client_for(cfg: AppConfig):
    """Build a Flask test client backed by a temporary fixture database."""

    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    temp_db.close()
    cfg.database_file = temp_db.name
    DatabaseFixtures().create_test_database(temp_db.name)
    app = create_app(cfg)
    app.config["TESTING"] = True
    return app.test_client(), temp_db.name


def test_customization_rendered_into_head():
    """When set, both fields appear in the rendered <head> of a page."""

    marker_css = ".navbar{background:#abcdef}"
    marker_head = '<meta name="malla-test" content="custom-head">'
    client, db_path = _client_for(
        AppConfig(custom_css=marker_css, custom_html_head=marker_head)
    )
    try:
        html = client.get("/nodes").get_data(as_text=True)
        assert f"<style>{marker_css}</style>" in html
        assert marker_head in html
    finally:
        _clear_config_cache()
        try:
            os.unlink(db_path)
        except FileNotFoundError:
            pass


def test_no_customization_markup_when_unset():
    """With the defaults, no empty <style> tag or injection is emitted."""

    client, db_path = _client_for(AppConfig())
    try:
        html = client.get("/nodes").get_data(as_text=True)
        assert "<style></style>" not in html
        assert 'name="malla-test"' not in html
    finally:
        _clear_config_cache()
        try:
            os.unlink(db_path)
        except FileNotFoundError:
            pass
