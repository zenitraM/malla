# This module implements application-wide configuration handling.
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration data model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AppConfig:
    """Application configuration loaded from YAML and environment variables."""

    # Core UI settings
    name: str = "Malla"
    home_markdown: str = ""

    # Flask/server settings
    secret_key: str = "dev-secret-key-change-in-production"
    database_file: str = "meshtastic_history.db"
    host: str = "0.0.0.0"
    port: int = 5008
    debug: bool = False

    # MQTT capture settings
    mqtt_broker_address: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_topic_prefix: str = "msh"
    mqtt_topic_suffix: str = "/+/+/+/#"

    # Meshtastic channel default key (for optional packet decryption)
    default_channel_key: str = "1PG7OiApB1nwvP+rz05pAQ=="

    # Allowed domains for CORS
    cors_allowed_domains: list = [];

    # Logging
    log_level: str = "INFO"

    # Internal attribute to remember the source file used
    _config_path: Path | None = field(default=None, repr=False, compare=False)


# ---------------------------------------------------------------------------
# Loader helpers
# ---------------------------------------------------------------------------


_YAML_DEFAULT_PATH = "config.yaml"
_ENV_PREFIX = "MALLA_"  # Prefix for environment variable overrides


def _resolve_type(t: Any) -> Any:  # noqa: ANN001
    """Resolve **t** which may be a string forward-reference into a real type."""

    if isinstance(t, str):
        # Basic builtin types are fine to eval() in this restricted context.
        builtins_map = {"bool": bool, "int": int, "float": float, "str": str}
        return builtins_map.get(t, str)
    return t


def _coerce_value(value: str, target_type):  # noqa: ANN001
    """Coerce *value* (a string from env) to *target_type* (which may be a string)."""

    target_type = _resolve_type(target_type)

    try:
        if target_type is bool:
            return value.lower() in {"1", "true", "yes", "on"}
        if target_type is int:
            return int(value)
        if target_type is float:
            return float(value)
    except ValueError:
        logger.warning(
            "Could not coerce environment variable '%s' to %s – using raw string",
            value,
            target_type,
        )
    return value


def load_config(config_path: str | os.PathLike | None = None) -> AppConfig:  # noqa: C901
    """Load configuration in the following precedence order:

    1. Defaults defined in :class:`AppConfig`.
    2. YAML file (``config.yaml`` or path provided via *config_path* or the
       ``MALLA_CONFIG_FILE`` environment variable).
    3. Environment variables prefixed with ``MALLA_`` (e.g. ``MALLA_NAME``)
       – case-insensitive.  **This is the only supported override mechanism.**
    """

    # Step 1 – start with the defaults from the dataclass converted to dict
    data: dict[str, object] = {}

    # Determine the YAML path to use (step 2)
    yaml_path = (
        Path(config_path)  # explicit argument wins
        if config_path is not None
        else Path(os.getenv("MALLA_CONFIG_FILE", _YAML_DEFAULT_PATH))
    )

    if yaml_path.is_file():
        try:
            with yaml_path.open("r", encoding="utf-8") as fp:
                file_data = yaml.safe_load(fp) or {}
            if not isinstance(file_data, dict):
                logger.warning(
                    "YAML config file %s must contain a mapping at top-level – ignoring",
                    yaml_path,
                )
                file_data = {}
            data.update(file_data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read YAML config from %s: %s", yaml_path, exc)

    # Step 3 – look for env vars prefixed with MALLA_
    for field_name, field_obj in AppConfig.__dataclass_fields__.items():  # type: ignore[attr-defined]
        env_key = f"{_ENV_PREFIX}{field_name}".upper()
        if env_key in os.environ:
            data[field_name] = _coerce_value(os.environ[env_key], field_obj.type)

    # Construct the config instance
    config = AppConfig(**data)  # type: ignore[arg-type]
    config._config_path = yaml_path if yaml_path.is_file() else None

    logger.debug("Loaded application configuration: %s", config)
    return config


# Convenience singleton to avoid re-loading throughout the process
_config_singleton: AppConfig | None = None


def get_config() -> AppConfig:
    """Return a singleton :class:`AppConfig` instance loaded with *load_config()*.
    Subsequent calls return the cached object.
    """

    global _config_singleton  # noqa: PLW0603
    if _config_singleton is None:
        _config_singleton = load_config()
    return _config_singleton


# ---------------------------------------------------------------------------
# Helper for unit tests to override the cached singleton
# ---------------------------------------------------------------------------


def _override_config(new_cfg: AppConfig) -> None:  # noqa: D401, ANN001
    """Force the global singleton to *new_cfg* (used internally by tests)."""

    global _config_singleton  # noqa: PLW0603
    _config_singleton = new_cfg


def _clear_config_cache() -> None:
    """Clear the global config singleton cache (used internally by tests)."""

    global _config_singleton  # noqa: PLW0603
    _config_singleton = None
