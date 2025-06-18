# New unit tests for configuration loader

from pathlib import Path

from malla.config import AppConfig, load_config


def test_yaml_loading(tmp_path: Path):
    """Ensure that values from a YAML file are loaded into AppConfig."""

    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("""
name: CustomName
home_markdown: "# Welcome\nThis is **markdown** content."
port: 9999
""")

    cfg = load_config(config_path=yaml_file)

    assert isinstance(cfg, AppConfig)
    assert cfg.name == "CustomName"
    assert "markdown" in cfg.home_markdown
    assert cfg.port == 9999


def test_env_override(monkeypatch):
    """Environment variables with the `MALLA_` prefix override YAML/defaults."""

    monkeypatch.setenv("MALLA_NAME", "EnvName")
    monkeypatch.setenv("MALLA_DEBUG", "true")
    cfg = load_config(config_path=None)

    assert cfg.name == "EnvName"
    assert cfg.debug is True
