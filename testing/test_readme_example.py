"""Test the README logging configuration example."""

from pathlib import Path
from typing import Literal

from cot.config import Config, field, from_parent, sub_config
from cot.config.adapters.argparse import ConfigToArgparseAdapter

DEFAULT_LOG_FORMAT = "%(levelname)-8s %(name)s:%(filename)s:%(lineno)d %(message)s"
DEFAULT_LOG_DATE_FORMAT = "%H:%M:%S"


class LogBaseConfig(Config):
    """Base configuration for logging with inheritable fields."""

    level: int | str | None = field(
        from_parent,
        default=None,
        help=(
            "Level of messages to catch/display. "
            "Not set by default, so it depends on the root/parent log handler's "
            'effective level, where it is "WARNING" by default.'
        ),
    )
    date_format: str = field(from_parent, default=DEFAULT_LOG_DATE_FORMAT)
    format: str = field(
        from_parent,
        default=DEFAULT_LOG_FORMAT,
        help="Log format used by the logging module",
    )


class LogCliConfig(LogBaseConfig):
    """Configuration for CLI/live logging."""

    enable: bool = field(
        default=False,
        action="store_true",
        help='Enable log display during test run (also known as "live logging")',
    )


class LogFileConfig(LogBaseConfig):
    """Configuration for file logging."""

    path: Path | None = field(
        default=None, help="Path to a file when logging will be written to"
    )
    mode: Literal["w", "a"] = field(
        default="w", choices=["w", "a"], help="Log file open mode"
    )


class LoggingPluginConfig(Config, prefix="log"):
    """Main logging plugin configuration."""

    # Parent fields that sub-configs inherit via from_parent
    level: int | str | None = field(default=None)
    date_format: str = field(default=DEFAULT_LOG_DATE_FORMAT)
    format: str = field(default=DEFAULT_LOG_FORMAT)

    # Sub-configurations
    cli: LogCliConfig = sub_config(LogCliConfig)
    file: LogFileConfig = sub_config(LogFileConfig)

    # Additional fields
    auto_indent: bool | int | None = field(
        default=None,
        help="Auto-indent multiline messages passed to the logging module. "
        "Accepts true|on, false|off or an integer.",
    )
    disable: list[str] = field(
        default_factory=list,
        action="append",
        help="Disable a logger by name. Can be passed multiple times.",
    )


def test_logging_config_defaults() -> None:
    """Test default configuration values."""
    config = LoggingPluginConfig()

    # Parent config defaults
    assert config.level is None
    assert config.format == DEFAULT_LOG_FORMAT
    assert config.date_format == DEFAULT_LOG_DATE_FORMAT

    # CLI sub-config inherits from parent
    assert config.cli.level is None  # Inherited from parent
    assert config.cli.format == DEFAULT_LOG_FORMAT  # Inherited
    assert config.cli.date_format == DEFAULT_LOG_DATE_FORMAT  # Inherited
    assert config.cli.enable is False  # Own default

    # File sub-config inherits from parent
    assert config.file.level is None  # Inherited from parent
    assert config.file.format == DEFAULT_LOG_FORMAT  # Inherited
    assert config.file.date_format == DEFAULT_LOG_DATE_FORMAT  # Inherited
    assert config.file.path is None  # Own default
    assert config.file.mode == "w"  # Own default

    # Other fields
    assert config.auto_indent is None
    assert config.disable == []


def test_logging_config_with_custom_parent_values() -> None:
    """Test that sub-configs inherit custom parent values."""
    config = LoggingPluginConfig(
        level="DEBUG",
        format="[%(levelname)s] %(message)s",
        date_format="%Y-%m-%d %H:%M:%S",
    )

    # Parent has custom values
    assert config.level == "DEBUG"
    assert config.format == "[%(levelname)s] %(message)s"
    assert config.date_format == "%Y-%m-%d %H:%M:%S"

    # CLI inherits custom values
    assert config.cli.level == "DEBUG"
    assert config.cli.format == "[%(levelname)s] %(message)s"
    assert config.cli.date_format == "%Y-%m-%d %H:%M:%S"

    # File inherits custom values
    assert config.file.level == "DEBUG"
    assert config.file.format == "[%(levelname)s] %(message)s"
    assert config.file.date_format == "%Y-%m-%d %H:%M:%S"


def test_logging_config_with_sub_config_overrides() -> None:
    """Test that explicit sub-config values override inheritance."""
    config = LoggingPluginConfig(
        level="WARNING",
        format="parent format",
        cli={"level": "DEBUG", "enable": True},  # type: ignore[arg-type]
        file={"level": "ERROR", "path": "/tmp/test.log"},  # type: ignore[arg-type]
    )

    # Parent values
    assert config.level == "WARNING"
    assert config.format == "parent format"

    # CLI has explicit override for level
    assert config.cli.level == "DEBUG"  # Explicit override
    assert config.cli.format == "parent format"  # Inherited
    assert config.cli.enable is True  # Explicitly set

    # File has explicit override for level
    assert config.file.level == "ERROR"  # Explicit override
    assert config.file.format == "parent format"  # Inherited
    assert str(config.file.path) == "/tmp/test.log"  # Explicitly set


def test_logging_config_from_data() -> None:
    """Test loading configuration from multiple data sources."""
    # Simulate data from different sources
    file_data = {"level": "INFO", "format": "file format"}

    env_data = {"cli": {"enable": True}, "auto_indent": True}

    cli_data = {
        "file": {"path": "/var/log/app.log", "mode": "a"},
        "disable": ["module1", "module2"],
    }

    config = LoggingPluginConfig.from_data(file_data, env_data, cli_data)

    # Values from file_data
    assert config.level == "INFO"
    assert config.format == "file format"

    # CLI inherits from parent and gets enable from env_data
    assert config.cli.level == "INFO"  # Inherited from parent
    assert config.cli.format == "file format"  # Inherited from parent
    assert config.cli.enable is True  # From env_data

    # File inherits from parent and gets path/mode from cli_data
    assert config.file.level == "INFO"  # Inherited from parent
    assert config.file.format == "file format"  # Inherited from parent
    assert str(config.file.path) == "/var/log/app.log"  # From cli_data
    assert config.file.mode == "a"  # From cli_data

    # Other values
    assert config.auto_indent is True  # From env_data
    assert config.disable == ["module1", "module2"]  # From cli_data


def test_logging_config_with_argparse() -> None:
    """Test that the configuration works with argparse adapter."""

    # Create adapter and parser
    adapter = ConfigToArgparseAdapter(LoggingPluginConfig)
    parser = adapter.create_parser(description="Test logging configuration")

    # Parse some arguments
    args = parser.parse_args(
        [
            "--log-level",
            "DEBUG",
            "--log-cli-enable",
            "--log-file-path",
            "/tmp/test.log",
            "--log-disable",
            "module1",
            "--log-disable",
            "module2",
        ]
    )

    # Extract config from parsed args
    config_data = adapter.extract_config(args)

    # Debug: print what was extracted
    print(f"Extracted config_data: {config_data}")

    config = LoggingPluginConfig(**config_data)

    # Check values
    assert config.level == "DEBUG"
    assert config.cli.enable is True
    assert (
        str(config.file.path) == "/tmp/test.log"
    )  # Convert Path to str for comparison
    assert config.disable == ["module1", "module2"]

    # Check inheritance works
    assert config.cli.level == "DEBUG"  # Inherited from parent
    assert config.file.level == "DEBUG"  # Inherited from parent


def test_logging_config_complex_inheritance() -> None:
    """Test complex inheritance scenarios."""

    class ExtendedLogConfig(LogBaseConfig):
        """Extended config with additional fields."""

        buffer_size: int = field(default=1000)

    class AdvancedLoggingConfig(LoggingPluginConfig):
        """Advanced config with extended sub-configs."""

        network: ExtendedLogConfig = sub_config(ExtendedLogConfig)

    config = AdvancedLoggingConfig(level="ERROR", format="[%(name)s] %(message)s")

    # Network sub-config inherits from parent
    assert config.network.level == "ERROR"  # Inherited
    assert config.network.format == "[%(name)s] %(message)s"  # Inherited
    assert config.network.date_format == DEFAULT_LOG_DATE_FORMAT  # Inherited
    assert config.network.buffer_size == 1000  # Own default

    # Original sub-configs still work
    assert config.cli.level == "ERROR"
    assert config.file.level == "ERROR"
