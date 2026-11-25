"""Persistent configuration management for CircuitGen with atomic writes and schema versioning."""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import platformdirs
from circuitgen.export import OUTPUT_FORMATS, SchematicStyle

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1
CONFIG_DIR_ENV_VAR = "CIRCUITGEN_CONFIG_DIR"


@dataclass
class AppConfig:
    """CircuitGen user configuration."""

    schema_version: int = CURRENT_SCHEMA_VERSION
    onboarding_status: str = "not_started"  # "not_started", "skipped", "completed"
    default_provider: str = "gemini"
    model_mode: str = "automatic"
    explicit_model: str | None = None
    default_output_dir: str = "./output/"
    overwrite_confirmation: bool = True
    fallback_policy: str = "off"
    interface_theme: str = "pcb-green"
    reduced_motion: bool = False
    terminal_colors: str = "auto"
    output_format: str = "svg"
    auto_open: bool = False
    save_netlist: bool = False
    background: str = "transparent"
    component_color: str | None = None
    wire_color: str | None = None
    text_color: str | None = None
    show_component_ids: bool = True
    show_component_values: bool = True
    retry_transient: bool = True
    essential_clarifications: bool = True
    request_timeout: int = 120
    # Runtime diagnostic attributes (not written to disk)
    load_warning: str | None = field(default=None, repr=False, compare=False)

    def schematic_style(self) -> SchematicStyle:
        return SchematicStyle(**{name: getattr(self, name) for name in SchematicStyle.__dataclass_fields__})

    def generate(self, description: str, **kwargs):
        """Generate using the saved provider, request policy, and appearance."""
        from circuitgen import generate

        return generate(
            description,
            provider=self.default_provider,
            model=self.explicit_model if self.model_mode == "manual" else None,
            timeout=self.request_timeout,
            retry_transient=self.retry_transient,
            allow_model_fallback=self.fallback_policy == "auto",
            clarify=self.essential_clarifications,
            style=self.schematic_style(),
            output_format=self.output_format,
            **kwargs,
        )

    def should_show_onboarding(self) -> bool:
        """Return True if first-run setup wizard should be presented."""
        return self.onboarding_status == "not_started"

    def mark_onboarding_skipped(self) -> None:
        """Mark onboarding as intentionally skipped by the user."""
        self.onboarding_status = "skipped"

    def mark_onboarding_completed(self) -> None:
        """Mark onboarding as completed."""
        self.onboarding_status = "completed"

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary excluding runtime-only fields."""
        data = asdict(self)
        data.pop("load_warning", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], warning: str | None = None) -> AppConfig:
        """Create AppConfig from dictionary with safe defaults for missing or invalid values."""
        valid_onboarding = {"not_started", "skipped", "completed"}
        onboarding = data.get("onboarding_status", "not_started")
        if onboarding not in valid_onboarding:
            onboarding = "not_started"

        from circuitgen.ai import list_providers

        valid_providers = set(list_providers())
        provider = data.get("default_provider", "gemini")
        if provider not in valid_providers:
            provider = "gemini"

        config = cls(
            schema_version=int(data.get("schema_version", CURRENT_SCHEMA_VERSION)),
            onboarding_status=str(onboarding),
            default_provider=str(provider),
            model_mode=str(data.get("model_mode", "automatic")),
            explicit_model=data.get("explicit_model"),
            default_output_dir=str(data.get("default_output_dir", "./output/")),
            overwrite_confirmation=bool(data.get("overwrite_confirmation", True)),
            fallback_policy="auto" if data.get("fallback_policy") == "auto" else "off",
            load_warning=warning,
        )
        choices = {
            "interface_theme": ("pcb-green", "midnight-blue", "light", "monochrome", "terminal"),
            "terminal_colors": ("auto", "none"),
            "output_format": OUTPUT_FORMATS,
        }
        for name, options in choices.items():
            if data.get(name) in options:
                setattr(config, name, data[name])
        for name in (
            "reduced_motion", "auto_open", "save_netlist", "show_component_ids",
            "show_component_values", "retry_transient", "essential_clarifications",
        ):
            if isinstance(data.get(name), bool):
                setattr(config, name, data[name])
        timeout = data.get("request_timeout")
        if type(timeout) is int and 1 <= timeout <= 600:
            config.request_timeout = timeout
        for name in ("background", "component_color", "wire_color", "text_color"):
            if name in data:
                try:
                    SchematicStyle(**{name: data[name]})
                except ValueError:
                    continue
                setattr(config, name, data[name])
        return config


class ConfigService:
    """Service for loading and persisting user configuration safely."""

    _cached_config: AppConfig | None = None

    @classmethod
    def get_config_dir(cls, override_dir: Path | str | None = None) -> Path:
        """Return the configuration directory, respecting overrides and environment variables."""
        if override_dir:
            return Path(override_dir).resolve()
        env_override = os.environ.get(CONFIG_DIR_ENV_VAR)
        if env_override:
            return Path(env_override).resolve()
        return Path(platformdirs.user_config_dir("CircuitGen", "CircuitGen")).resolve()

    @classmethod
    def get_config_path(cls, override_dir: Path | str | None = None) -> Path:
        """Return path to config.json."""
        return cls.get_config_dir(override_dir) / "config.json"

    @classmethod
    def load(cls, override_dir: Path | str | None = None, force_reload: bool = False) -> AppConfig:
        """Load configuration from disk. Recovers gracefully from corrupt files."""
        if cls._cached_config is not None and not force_reload and override_dir is None:
            return cls._cached_config

        config_path = cls.get_config_path(override_dir)
        if not config_path.is_file():
            config = AppConfig()
            if override_dir is None:
                cls._cached_config = config
            return config

        try:
            content = config_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("Configuration root must be a JSON object")
            config = AppConfig.from_dict(data)
        except Exception as exc:
            # Corrupted or unreadable config file: backup safely and restore defaults
            warning = f"Corrupt configuration detected at {config_path}: {exc}. Restored default settings."
            logger.warning(warning)
            try:
                backup_path = config_path.with_suffix(".json.bak")
                shutil.copy2(config_path, backup_path)
            except Exception:
                pass
            config = AppConfig.from_dict({}, warning=warning)

        if override_dir is None:
            cls._cached_config = config
        return config

    @classmethod
    def save(cls, config: AppConfig, override_dir: Path | str | None = None) -> None:
        """Persist configuration atomically to disk."""
        target_dir = cls.get_config_dir(override_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "config.json"

        # Explicit safety assertion: never allow secret credentials in config.json
        data = config.to_dict()
        for forbidden in ("api_key", "key", "token", "password", "secret"):
            if forbidden in data:
                del data[forbidden]

        payload = json.dumps(data, indent=2, ensure_ascii=False)

        # Atomic save: write to temporary file in the same directory, then atomic rename
        temp_file = target_dir / f".config.json.{uuid4().hex}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, target_file)
        except Exception:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            raise

        if override_dir is None:
            cls._cached_config = config

    @classmethod
    def reset_cache(cls) -> None:
        """Reset the cached in-memory configuration."""
        cls._cached_config = None
