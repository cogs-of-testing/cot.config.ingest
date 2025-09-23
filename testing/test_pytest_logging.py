"""Test the pytest logging configuration example."""

from pathlib import Path
from typing import Literal

import pytest

from cot.config import Config, field, from_parent, sub_config

DEFAULT_LOG_FORMAT = "%(levelname)-8s %(name)s:%(filename)s:%(lineno)d %(message)s"
DEFAULT_LOG_DATE_FORMAT = "%H:%M:%S"


class LogBaseConfig(Config):
    """Base configuration for logging with common fields."""

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
    """Configuration for CLI logging output."""

    enable: bool = field(
        default=False,
        help='Enable log display during test run (also known as "live logging")',
    )


class LogFileConfig(LogBaseConfig):
    """Configuration for file logging output."""

    path: Path | None = field(
        default=None, help="Path to a file when logging will be written to"
    )
    mode: Literal["w", "a"] = field(
        default="w", choices=["w", "a"], help="Log file open mode"
    )


class LoggingPluginConfig(Config, prefix="log"):
    """Main logging plugin configuration."""

    # Base logging config fields are directly on this class
    level: int | str | None = field(
        default=None,
        help=(
            "Level of messages to catch/display. "
            "Not set by default, so it depends on the root/parent log handler's "
            'effective level, where it is "WARNING" by default.'
        ),
    )
    date_format: str = field(
        default=DEFAULT_LOG_DATE_FORMAT,
        help="Log date format used by the logging module",
    )
    format: str = field(
        default=DEFAULT_LOG_FORMAT, help="Log format used by the logging module"
    )

    # Sub-configs
    cli: LogCliConfig = sub_config(LogCliConfig, primary="enable")
    file: LogFileConfig = sub_config(LogFileConfig, primary="path")

    # Additional fields
    auto_indent: bool | int | None = field(
        default=None,
        help="Auto-indent multiline messages passed to the logging module",
    )
    disable: list[str] = field(
        default_factory=list,
        action="append",
        help="Disable a logger by name. Can be passed multiple times.",
    )


def test_logging_config_basic():
    """Test basic logging configuration creation."""
    config = LoggingPluginConfig()

    # Check defaults
    assert config.level is None
    assert config.date_format == DEFAULT_LOG_DATE_FORMAT
    assert config.format == DEFAULT_LOG_FORMAT
    assert config.auto_indent is None
    assert config.disable == []

    # Check sub-configs exist
    assert isinstance(config.cli, LogCliConfig)
    assert isinstance(config.file, LogFileConfig)

    # Check sub-config defaults
    assert config.cli.enable is False
    assert config.file.path is None
    assert config.file.mode == "w"


def test_logging_config_with_values():
    """Test logging configuration with custom values."""
    config = LoggingPluginConfig(
        level="DEBUG",
        format="%(message)s",
        cli=LogCliConfig(enable=True, level="INFO"),
        file=LogFileConfig(path=Path("/tmp/test.log"), mode="a"),
        disable=["requests", "urllib3"],
    )

    assert config.level == "DEBUG"
    assert config.format == "%(message)s"
    assert config.cli.enable is True
    assert config.cli.level == "INFO"
    assert config.file.path == Path("/tmp/test.log")
    assert config.file.mode == "a"
    assert config.disable == ["requests", "urllib3"]


def test_field_metadata():
    """Test that field metadata is preserved."""
    # Access field metadata through the class
    fields = LoggingPluginConfig.__config_fields__

    assert "level" in fields
    level_field = fields["level"]
    assert level_field.help is not None
    assert "WARNING" in level_field.help

    assert "disable" in fields
    disable_field = fields["disable"]
    assert disable_field.action == "append"
    assert disable_field.default_factory is not None


def test_config_prefix():
    """Test that config prefix is stored."""
    assert LoggingPluginConfig.__config_prefix__ == "log"
    assert LogBaseConfig.__config_prefix__ is None


def test_field_choices_validation():
    """Test that field choices are validated."""
    # This should work
    config = LogFileConfig(mode="w")
    assert config.mode == "w"

    config = LogFileConfig(mode="a")
    assert config.mode == "a"

    # This should raise an error
    with pytest.raises(ValueError, match="Invalid value.*Must be one of"):
        LogFileConfig(mode="x")
