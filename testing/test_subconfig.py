"""
Tests for SubConfig inheritance and nested loading.

These tests verify that SubConfig classes support inheritance
and can be loaded from nested configuration structures.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from cot.config import (
    ConfigManager,
    ConfigPart,
    EnvSource,
    SubConfig,
    TomlSource,
)


class BaseOutput(SubConfig):
    """Base output settings for testing inheritance."""

    level: str = "WARNING"
    format: str = "%(message)s"


class CliOutput(BaseOutput):
    """CLI output - extends base with enabled flag."""

    enabled: bool = False


class FileOutput(BaseOutput):
    """File output - extends base with path."""

    path: str | None = None


class OutputConfig(ConfigPart, prefix="output"):
    """Config with nested SubConfigs for testing."""

    cli: CliOutput
    file: FileOutput
    capture: BaseOutput


class TestSubConfigInheritance:
    """Test SubConfig inheritance pattern."""

    def test_inherited_fields_have_defaults(self) -> None:
        """Child SubConfig inherits field defaults from parent."""
        cli = CliOutput()

        # Inherited defaults
        assert cli.level == "WARNING"
        assert cli.format == "%(message)s"
        # Own default
        assert cli.enabled is False

    def test_child_can_override_inherited_fields(self) -> None:
        """Child SubConfig can set inherited fields."""
        cli = CliOutput(enabled=True, level="DEBUG", format="custom")

        assert cli.enabled is True
        assert cli.level == "DEBUG"
        assert cli.format == "custom"

    def test_different_children_are_independent(self) -> None:
        """Different child SubConfigs don't share state."""
        cli = CliOutput(level="DEBUG")
        file = FileOutput(level="ERROR", path="/var/log/test.log")
        capture = BaseOutput(level="INFO")

        assert cli.level == "DEBUG"
        assert file.level == "ERROR"
        assert capture.level == "INFO"

        # Each has its own specific field
        assert cli.enabled is False
        assert file.path == "/var/log/test.log"
        assert not hasattr(capture, "enabled")
        assert not hasattr(capture, "path")


class TestNestedSubConfigLoading:
    """Test loading nested SubConfigs from sources."""

    def test_load_nested_from_toml(self, tmp_path: Path) -> None:
        """Load nested SubConfig from TOML with dotted sections."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            dedent("""
            [output.cli]
            enabled = true
            level = "DEBUG"
            format = "CLI: %(message)s"

            [output.file]
            path = "/var/log/app.log"
            level = "ERROR"

            [output.capture]
            level = "INFO"
        """)
        )

        manager = ConfigManager()
        manager.add_source(TomlSource(toml_file))

        manager.declare(OutputConfig)
        config = manager.get(OutputConfig)

        # CLI settings
        assert config.cli.enabled is True
        assert config.cli.level == "DEBUG"
        assert config.cli.format == "CLI: %(message)s"

        # File settings
        assert config.file.path == "/var/log/app.log"
        assert config.file.level == "ERROR"

        # Capture settings
        assert config.capture.level == "INFO"
        assert config.capture.format == "%(message)s"  # default

    def test_nested_env_vars(self) -> None:
        """Load nested SubConfig from environment variables."""
        env = {
            "OUTPUT_CLI_ENABLED": "true",
            "OUTPUT_CLI_LEVEL": "DEBUG",
            "OUTPUT_FILE_PATH": "/var/log/app.log",
            "OUTPUT_FILE_LEVEL": "ERROR",
            "OUTPUT_CAPTURE_LEVEL": "INFO",
        }

        manager = ConfigManager()
        manager.add_source(EnvSource(environ=env))

        manager.declare(OutputConfig)
        config = manager.get(OutputConfig)

        # CLI settings
        assert config.cli.enabled is True
        assert config.cli.level == "DEBUG"

        # File settings
        assert config.file.path == "/var/log/app.log"
        assert config.file.level == "ERROR"

        # Capture settings
        assert config.capture.level == "INFO"

    def test_nested_with_precedence(self, tmp_path: Path) -> None:
        """Environment variables override nested TOML config."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            dedent("""
            [output.cli]
            enabled = false
            level = "WARNING"

            [output.file]
            path = "/default/path.log"
            level = "INFO"
        """)
        )

        env = {
            "OUTPUT_CLI_ENABLED": "true",
            "OUTPUT_FILE_PATH": "/override/path.log",
        }

        manager = ConfigManager()
        manager.add_source(TomlSource(toml_file, precedence=10))
        manager.add_source(EnvSource(environ=env, precedence=20))

        manager.declare(OutputConfig)
        config = manager.get(OutputConfig)

        # Env overrides TOML
        assert config.cli.enabled is True
        assert config.file.path == "/override/path.log"

        # TOML values preserved where no env override
        assert config.cli.level == "WARNING"
        assert config.file.level == "INFO"
