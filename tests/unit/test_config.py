# New unit tests for configuration loader

from pathlib import Path

from malla.config import AppConfig, _clear_config_cache, load_config


def test_yaml_loading(tmp_path: Path, monkeypatch):
    """Ensure that values from a YAML file are loaded into AppConfig."""

    # Clear any cached config from other imports
    _clear_config_cache()

    # Clear any environment variables that might override the YAML
    monkeypatch.delenv("MALLA_NAME", raising=False)
    monkeypatch.delenv("MALLA_PORT", raising=False)
    monkeypatch.delenv("MALLA_HOME_MARKDOWN", raising=False)

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

    # Clear any cached config from other imports
    _clear_config_cache()

    monkeypatch.setenv("MALLA_NAME", "EnvName")
    monkeypatch.setenv("MALLA_DEBUG", "true")
    cfg = load_config(config_path=None)

    assert cfg.name == "EnvName"
    assert cfg.debug is True


def test_chat_hide_empty_channels_config(tmp_path: Path, monkeypatch):
    """chat_hide_empty_channels defaults to False and can be configured via YAML and env."""
    _clear_config_cache()
    monkeypatch.delenv("MALLA_CHAT_HIDE_EMPTY_CHANNELS", raising=False)

    # Defaults to False
    default_cfg = load_config(config_path=None)
    assert default_cfg.chat_hide_empty_channels is False

    # Loaded from YAML
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("chat_hide_empty_channels: true\n")
    yaml_cfg = load_config(config_path=yaml_file)
    assert yaml_cfg.chat_hide_empty_channels is True

    # Overridden by environment variable
    _clear_config_cache()
    monkeypatch.setenv("MALLA_CHAT_HIDE_EMPTY_CHANNELS", "1")
    env_cfg = load_config(config_path=None)
    assert env_cfg.chat_hide_empty_channels is True


def test_chat_include_exclude_channels_config(tmp_path: Path, monkeypatch):
    """chat_include_channels and chat_exclude_channels support defaults, YAML lists, and env overrides."""
    _clear_config_cache()
    monkeypatch.delenv("MALLA_CHAT_INCLUDE_CHANNELS", raising=False)
    monkeypatch.delenv("MALLA_CHAT_EXCLUDE_CHANNELS", raising=False)

    # Defaults to empty strings (and empty list getters)
    default_cfg = load_config(config_path=None)
    assert default_cfg.chat_include_channels == ""
    assert default_cfg.chat_exclude_channels == ""
    assert default_cfg.get_chat_include_channels() == []
    assert default_cfg.get_chat_exclude_channels() == []

    # Loaded from YAML comma-separated strings
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("""
chat_include_channels: "LongFast, LocalChat"
chat_exclude_channels: "NoisyChannel"
""")
    yaml_cfg = load_config(config_path=yaml_file)
    assert yaml_cfg.chat_include_channels == "LongFast, LocalChat"
    assert yaml_cfg.get_chat_include_channels() == ["LongFast", "LocalChat"]
    assert yaml_cfg.get_chat_exclude_channels() == ["NoisyChannel"]

    # Loaded from YAML list fallback
    yaml_list_file = tmp_path / "config_list.yaml"
    yaml_list_file.write_text("""
chat_include_channels:
  - LongFast
  - LocalChat
""")
    yaml_list_cfg = load_config(config_path=yaml_list_file)
    assert yaml_list_cfg.get_chat_include_channels() == ["LongFast", "LocalChat"]

    # Overridden by environment variables (comma-separated strings)
    _clear_config_cache()
    monkeypatch.setenv("MALLA_CHAT_INCLUDE_CHANNELS", "LongFast, Emergency, TestChan")
    monkeypatch.setenv("MALLA_CHAT_EXCLUDE_CHANNELS", "TestChan")
    env_cfg = load_config(config_path=None)
    assert env_cfg.get_chat_include_channels() == ["LongFast", "Emergency", "TestChan"]
    assert env_cfg.get_chat_exclude_channels() == ["TestChan"]

    # Numeric channels (scalars and lists of ints) in YAML
    _clear_config_cache()
    monkeypatch.delenv("MALLA_CHAT_INCLUDE_CHANNELS", raising=False)
    monkeypatch.delenv("MALLA_CHAT_EXCLUDE_CHANNELS", raising=False)
    yaml_num_file = tmp_path / "config_num.yaml"
    yaml_num_file.write_text("""
chat_include_channels:
  - 0
  - 1
chat_exclude_channels: 2
""")
    num_cfg = load_config(config_path=yaml_num_file)
    assert num_cfg.get_chat_include_channels() == ["0", "1"]
    assert num_cfg.get_chat_exclude_channels() == ["2"]

    # Deduplication of duplicate entries
    _clear_config_cache()
    monkeypatch.setenv("MALLA_CHAT_INCLUDE_CHANNELS", "ChanA, ChanB, ChanA, ChanB")
    monkeypatch.setenv("MALLA_CHAT_EXCLUDE_CHANNELS", "ChanX, ChanX, ChanY")
    dedup_cfg = load_config(config_path=None)
    assert dedup_cfg.get_chat_include_channels() == ["ChanA", "ChanB"]
    assert dedup_cfg.get_chat_exclude_channels() == ["ChanX", "ChanY"]


def test_normalize_channel_list_deduplication():
    """_normalize_channel_list strips whitespace and deduplicates while preserving insertion order."""
    from malla.config import _normalize_channel_list

    assert _normalize_channel_list(["ChanA", " ChanA ", "ChanB", "ChanA"]) == ["ChanA", "ChanB"]
    assert _normalize_channel_list("ChanA, ChanB, ChanA") == ["ChanA", "ChanB"]
    assert _normalize_channel_list([1, 1, 2, "1"]) == ["1", "2"]
    assert _normalize_channel_list(None) == []
    assert _normalize_channel_list("") == []


