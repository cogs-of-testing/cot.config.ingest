"""
Test replicating pytest logging plugin configuration.

This test demonstrates a real-world use case: how the configuration
system can handle pytest-style logging configuration from multiple
sources using nested SubConfig structures with inheritance.

The pytest logging plugin has two log output handlers with specific settings:
- CLI (live logging to terminal) - log_cli, log_cli_level, log_cli_format, etc.
- File (logging to a file) - log_file, log_file_level, log_file_format, etc.

The top-level settings (log_level, log_format, log_date_format) serve as:
1. Settings for captured logs (shown on test failure)
2. Defaults that cascade to cli/file when their specific settings aren't set

Key pytest behaviors demonstrated:
1. Child configs inherit from parent (e.g., log_cli_level defaults to log_level)
2. INI flat keys map to nested structure (log_cli_level -> cli.level)
3. Environment variables override file config
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Annotated

from cot.config import (
    ConfigManager,
    ConfigPart,
    EnvSource,
    IniSource,
    SubConfig,
    TomlSource,
    from_parent,
)

# --- Logging SubConfig hierarchy ---
# Mirrors pytest's logging plugin structure


class LogOutputConfig(SubConfig):
    """
    Base log output settings - reused via inheritance.

    Contains the common fields shared by all log outputs:
    - level: minimum log level to display
    - format: log message format string
    - date_format: timestamp format string

    Fields marked with `from_parent` will cascade from parent config
    (e.g., log.level -> log.cli.level) when not explicitly set.
    """

    level: Annotated[str, from_parent] = "WARNING"
    format: Annotated[str, from_parent] = "%(levelname)s %(message)s"
    date_format: Annotated[str, from_parent] = "%H:%M:%S"


class LogCliConfig(LogOutputConfig):
    """
    CLI (live) logging configuration.

    Extends base with:
    - enabled: whether to show live logs during test execution
    """

    enabled: bool = False


class LogFileConfig(LogOutputConfig):
    """
    File logging configuration.

    Extends base with:
    - path: file path for log output (None = disabled)
    """

    path: str | None = None


class LoggingConfig(LogOutputConfig, ConfigPart, prefix="log"):
    """
    Pytest-style logging configuration using nested SubConfigs.

    Inherits from LogOutputConfig to get the shared fields (level, format,
    date_format) which serve as settings for captured logs AND as defaults
    that cascade to the nested SubConfigs when their fields aren't set.

    Maps to pytest's log_* options:
        log.level          -> log_level (capture level + default for outputs)
        log.format         -> log_format (capture format + default for outputs)
        log.date_format    -> log_date_format (capture date format + default)
        log.cli.enabled    -> log_cli
        log.cli.level      -> log_cli_level (defaults to log.level)
        log.cli.format     -> log_cli_format (defaults to log.format)
        log.file.path      -> log_file
        log.file.level     -> log_file_level (defaults to log.level)
        log.file.format    -> log_file_format (defaults to log.format)
    """

    # Nested configs - will inherit from top-level if not explicitly set
    cli: LogCliConfig
    file: LogFileConfig


class TestParentValueCascade:
    """
    Test that parent config values cascade to children.

    In pytest, setting log_level sets the default for log_cli_level,
    log_file_level, etc. This is different from class inheritance -
    it's about config values flowing from parent to children at runtime.
    """

    def test_top_level_cascades_to_children(self, tmp_path: Path) -> None:
        """Setting log.level should set default for cli.level, file.level, etc."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            dedent("""
            [log]
            level = "DEBUG"
            format = "%(asctime)s %(message)s"
        """)
        )

        manager = ConfigManager()
        manager.add_source(TomlSource(toml_file))
        config = manager.register_fragment_type(LoggingConfig)

        # Top-level values should cascade to cli and file
        assert config.level == "DEBUG"
        assert config.cli.level == "DEBUG"
        assert config.file.level == "DEBUG"

        assert config.format == "%(asctime)s %(message)s"
        assert config.cli.format == "%(asctime)s %(message)s"
        assert config.file.format == "%(asctime)s %(message)s"

    def test_child_override_takes_precedence(self, tmp_path: Path) -> None:
        """Child-specific value overrides parent cascade."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            dedent("""
            [log]
            level = "DEBUG"

            [log.cli]
            level = "INFO"

            [log.file]
            level = "ERROR"
        """)
        )

        manager = ConfigManager()
        manager.add_source(TomlSource(toml_file))
        config = manager.register_fragment_type(LoggingConfig)

        # Top-level
        assert config.level == "DEBUG"

        # Children with explicit values override cascade
        assert config.cli.level == "INFO"
        assert config.file.level == "ERROR"

    def test_env_can_set_parent_level(self) -> None:
        """Environment variable sets parent level, cascades to children."""
        env = {
            "LOG_LEVEL": "DEBUG",
        }

        manager = ConfigManager()
        manager.add_source(EnvSource(environ=env))
        config = manager.register_fragment_type(LoggingConfig)

        # All should get DEBUG from parent
        assert config.level == "DEBUG"
        assert config.cli.level == "DEBUG"
        assert config.file.level == "DEBUG"


class TestFromParentBehavior:
    """
    Test that child SubConfigs inherit defaults from parent class.

    This tests CLASS inheritance (LogCliConfig extends LogOutputConfig),
    not config value cascade (log.level -> log.cli.level).
    """

    def test_child_inherits_parent_defaults(self) -> None:
        """Child SubConfig classes inherit field defaults from parent."""
        # LogCliConfig inherits from LogOutputConfig
        cli = LogCliConfig()

        # Inherited from LogOutputConfig
        assert cli.level == "WARNING"
        assert cli.format == "%(levelname)s %(message)s"
        assert cli.date_format == "%H:%M:%S"

        # Own field
        assert cli.enabled is False

    def test_child_can_override_inherited_at_instance(self) -> None:
        """Child can override inherited fields when instantiated."""
        cli = LogCliConfig(level="DEBUG", enabled=True)

        assert cli.level == "DEBUG"  # overridden
        assert cli.format == "%(levelname)s %(message)s"  # inherited default
        assert cli.enabled is True  # own field

    def test_sibling_children_are_independent(self) -> None:
        """Different child SubConfigs don't share instance state."""
        cli = LogCliConfig(level="DEBUG")
        file = LogFileConfig(level="ERROR")

        # Each has its own level
        assert cli.level == "DEBUG"
        assert file.level == "ERROR"

    def test_nested_subconfigs_get_defaults_from_parent_class(self) -> None:
        """When loading config, nested SubConfigs use their class defaults."""
        manager = ConfigManager()
        config = manager.register_fragment_type(LoggingConfig)

        # Both outputs inherit from LogOutputConfig defaults
        assert config.cli.level == "WARNING"
        assert config.file.level == "WARNING"

        # Each has the same inherited format
        assert config.cli.format == "%(levelname)s %(message)s"
        assert config.file.format == "%(levelname)s %(message)s"

    def test_partial_override_preserves_inherited_defaults(
        self, tmp_path: Path
    ) -> None:
        """Setting one field preserves other inherited defaults."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            dedent("""
            [log.cli]
            level = "DEBUG"
            # format and date_format not set - should use inherited defaults

            [log.file]
            path = "test.log"
            # level, format, date_format not set - should use inherited defaults
        """)
        )

        manager = ConfigManager()
        manager.add_source(TomlSource(toml_file))
        config = manager.register_fragment_type(LoggingConfig)

        # CLI: level overridden, others inherited
        assert config.cli.level == "DEBUG"
        assert config.cli.format == "%(levelname)s %(message)s"
        assert config.cli.date_format == "%H:%M:%S"

        # File: path set, level/format/date_format inherited
        assert config.file.path == "test.log"
        assert config.file.level == "WARNING"
        assert config.file.format == "%(levelname)s %(message)s"


class TestIniMapping:
    """
    Test INI flat key mapping to nested structure.

    pytest.ini uses flat keys like:
        log_cli = true
        log_cli_level = DEBUG
        log_file = pytest.log

    These need to map to our nested structure.
    """

    def test_flat_ini_keys_basic(self, tmp_path: Path) -> None:
        """
        Demonstrate that INI requires a flat ConfigPart.

        INI files don't support nested sections, so for pytest.ini
        compatibility we'd need a flat config class.
        """

        class FlatLoggingConfig(ConfigPart, prefix="pytest"):
            """Flat config matching pytest.ini structure."""

            log_cli: bool = False
            log_cli_level: str = "WARNING"
            log_cli_format: str = "%(levelname)s %(message)s"
            log_file: str | None = None
            log_file_level: str = "WARNING"
            log_level: str = "WARNING"  # capture level

        ini_file = tmp_path / "pytest.ini"
        ini_file.write_text(
            dedent("""
            [pytest]
            log_cli = true
            log_cli_level = DEBUG
            log_file = pytest.log
            log_file_level = INFO
            log_level = WARNING
        """)
        )

        manager = ConfigManager()
        manager.add_source(IniSource(ini_file))
        config = manager.register_fragment_type(FlatLoggingConfig)

        assert config.log_cli is True
        assert config.log_cli_level == "DEBUG"
        assert config.log_file == "pytest.log"
        assert config.log_file_level == "INFO"
        assert config.log_level == "WARNING"

    def test_toml_nested_is_cleaner(self, tmp_path: Path) -> None:
        """
        TOML nested structure is cleaner than INI flat keys.

        pyproject.toml can use proper nesting which maps directly
        to our SubConfig hierarchy.
        """
        toml_file = tmp_path / "pyproject.toml"
        toml_file.write_text(
            dedent("""
            [log]
            level = "WARNING"

            [log.cli]
            enabled = true
            level = "DEBUG"

            [log.file]
            path = "pytest.log"
            level = "INFO"
        """)
        )

        manager = ConfigManager()
        manager.add_source(TomlSource(toml_file))
        config = manager.register_fragment_type(LoggingConfig)

        # Same data, but structured
        assert config.level == "WARNING"  # capture level
        assert config.cli.enabled is True
        assert config.cli.level == "DEBUG"
        assert config.file.path == "pytest.log"
        assert config.file.level == "INFO"


class TestPrecedenceOverride:
    """Test that higher precedence sources override lower ones."""

    def test_env_overrides_toml(self, tmp_path: Path) -> None:
        """Environment variables override TOML config (CI scenario)."""
        toml_file = tmp_path / "pyproject.toml"
        toml_file.write_text(
            dedent("""
            [log.cli]
            enabled = false
            level = "WARNING"

            [log.file]
            path = "local.log"
            level = "INFO"
        """)
        )

        # CI environment overrides
        env = {
            "LOG_CLI_ENABLED": "true",
            "LOG_CLI_LEVEL": "DEBUG",
            "LOG_FILE_PATH": "/ci/logs/pytest.log",
        }

        manager = ConfigManager()
        manager.add_source(TomlSource(toml_file, precedence=10))
        manager.add_source(EnvSource(environ=env, precedence=20))

        config = manager.register_fragment_type(LoggingConfig)

        # Env overrides TOML
        assert config.cli.enabled is True
        assert config.cli.level == "DEBUG"
        assert config.file.path == "/ci/logs/pytest.log"

        # TOML preserved where no env override
        assert config.file.level == "INFO"

    def test_local_toml_overrides_base(self, tmp_path: Path) -> None:
        """Local config file overrides shared base config."""
        base_config = tmp_path / "base.toml"
        base_config.write_text(
            dedent("""
            [log.cli]
            format = "%(levelname)s %(name)s: %(message)s"

            [log.file]
            format = "%(asctime)s %(levelname)s: %(message)s"
            date_format = "%Y-%m-%d %H:%M:%S"
        """)
        )

        local_config = tmp_path / "local.toml"
        local_config.write_text(
            dedent("""
            [log.cli]
            enabled = true
            level = "DEBUG"

            [log.file]
            path = "dev.log"
        """)
        )

        manager = ConfigManager()
        manager.add_source(TomlSource(base_config, precedence=5))
        manager.add_source(TomlSource(local_config, precedence=10))

        config = manager.register_fragment_type(LoggingConfig)

        # From local (higher precedence)
        assert config.cli.enabled is True
        assert config.cli.level == "DEBUG"
        assert config.file.path == "dev.log"

        # From base (not overridden by local)
        assert config.cli.format == "%(levelname)s %(name)s: %(message)s"
        assert config.file.date_format == "%Y-%m-%d %H:%M:%S"
