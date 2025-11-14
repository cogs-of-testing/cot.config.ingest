"""Test ConfigLoader and debug functionality."""

import json
from pathlib import Path

import pytest

from cot.config import Config, field
from cot.config.debug import (
    get_config_report,
    get_load_order,
    get_non_default_values,
    get_overridden_values,
    get_override_chain,
    get_value_source,
    is_default,
    was_overridden,
)
from cot.config.loader import ConfigLoader, LazyConfigLoader
from cot.config.source_info import SourceType


class SampleConfig(Config, prefix="sample"):
    """Sample configuration for testing."""

    name: str = field(default="default_name", help="Application name")
    host: str = field(default="localhost", help="Server host")
    port: int = field(default=8080, help="Server port")
    debug: bool = field(default=False, help="Debug mode")
    workers: int = field(default=4, help="Number of workers")
    paths: list[str] = field(default_factory=list, action="append")


def test_loader_basic() -> None:
    """Test basic loader functionality."""
    loader = ConfigLoader(SampleConfig)
    config = loader.build()

    assert config.name == "default_name"
    assert config.host == "localhost"
    assert config.port == 8080
    assert config.debug is False


def test_loader_with_values() -> None:
    """Test loader with programmatically set values."""
    loader = ConfigLoader(SampleConfig)
    loader.set_values(name="test_app", port=9000)
    config = loader.build()

    assert config.name == "test_app"
    assert config.port == 9000
    assert config.host == "localhost"  # still default


def test_loader_from_file(tmp_path: Path) -> None:
    """Test loading from a configuration file."""
    config_file = tmp_path / "config.json"
    with config_file.open("w") as f:
        json.dump(
            {
                "name": "file_app",
                "host": "0.0.0.0",
                "port": 3000,
            },
            f,
        )

    loader = ConfigLoader(SampleConfig)
    loader.load_file(config_file)
    config = loader.build()

    assert config.name == "file_app"
    assert config.host == "0.0.0.0"
    assert config.port == 3000


def test_loader_from_env() -> None:
    """Test loading from environment variables."""
    env = {
        "SAMPLE_NAME": "env_app",
        "SAMPLE_PORT": "5000",
        "SAMPLE_DEBUG": "true",
    }

    loader = ConfigLoader(SampleConfig)
    loader.load_env(env)
    config = loader.build()

    assert config.name == "env_app"
    assert config.port == 5000
    assert config.debug is True


def test_loader_from_cli() -> None:
    """Test loading from CLI arguments."""
    loader = ConfigLoader(SampleConfig)
    loader.load_cli(["--sample-name", "cli_app", "--sample-workers", "8"])
    config = loader.build()

    assert config.name == "cli_app"
    assert config.workers == 8


def test_loader_precedence(tmp_path: Path) -> None:
    """Test that sources are merged with correct precedence."""
    # Create a config file
    config_file = tmp_path / "config.json"
    with config_file.open("w") as f:
        json.dump(
            {
                "name": "file_app",
                "host": "file_host",
                "port": 1000,
                "workers": 2,
            },
            f,
        )

    # Environment variables
    env = {
        "SAMPLE_HOST": "env_host",
        "SAMPLE_PORT": "2000",
        "SAMPLE_DEBUG": "true",
    }

    # Load in order: file -> env -> cli
    loader = ConfigLoader(SampleConfig)
    loader.load_file(config_file)
    loader.load_env(env)
    loader.load_cli(["--sample-port", "3000"])
    config = loader.build()

    # Verify precedence
    assert config.name == "file_app"  # from file
    assert config.host == "env_host"  # overridden by env
    assert config.port == 3000  # overridden by cli
    assert config.debug is True  # from env
    assert config.workers == 2  # from file


def test_debug_info_basic() -> None:
    """Test basic debug information tracking."""
    loader = ConfigLoader(SampleConfig, debug=True)
    loader.set_values(name="test_app")
    config = loader.build()

    # Check if value is marked as non-default
    assert not is_default(config, "name")
    assert is_default(config, "host")

    # Check source location
    source = get_value_source(config, "name")
    assert source is not None
    assert source.value == "test_app"
    assert source.source.source_type == SourceType.CODE


def test_debug_info_overrides(tmp_path: Path) -> None:
    """Test tracking of value overrides."""
    config_file = tmp_path / "config.json"
    with config_file.open("w") as f:
        json.dump({"port": 1000}, f)

    loader = ConfigLoader(SampleConfig, debug=True)
    loader.load_file(config_file)
    loader.load_env({"SAMPLE_PORT": "2000"})
    loader.load_cli(["--sample-port", "3000"])
    config = loader.build()

    # Check that port was overridden
    assert was_overridden(config, "port")
    assert not was_overridden(config, "name")

    # Check override chain
    chain = get_override_chain(config, "port")
    assert len(chain) == 3  # cli -> env -> file

    # Check final value
    assert config.port == 3000


def test_debug_report(tmp_path: Path) -> None:
    """Test generation of debug report."""
    config_file = tmp_path / "config.json"
    with config_file.open("w") as f:
        json.dump({"name": "test_app", "port": 1000}, f)

    loader = ConfigLoader(SampleConfig, debug=True)
    loader.load_file(config_file)
    loader.load_env({"SAMPLE_DEBUG": "true"})
    config = loader.build()

    report = get_config_report(config)

    # Check that report contains expected sections
    assert "Load Order:" in report
    assert "Current Values:" in report
    assert "file" in report
    assert "environment" in report


def test_load_order() -> None:
    """Test tracking of load order."""
    loader = ConfigLoader(SampleConfig, debug=True)
    loader.load_env({})
    loader.load_cli([])
    config = loader.build()

    order = get_load_order(config)
    assert len(order) == 2
    assert order[0][0] == "environment"
    assert order[1][0] == "cli"


def test_non_default_values() -> None:
    """Test getting non-default values."""
    loader = ConfigLoader(SampleConfig, debug=True)
    loader.set_values(name="custom", port=9999)
    config = loader.build()

    non_defaults = get_non_default_values(config)
    assert "name" in non_defaults
    assert "port" in non_defaults
    assert "host" not in non_defaults  # using default


def test_overridden_values() -> None:
    """Test getting overridden values."""
    loader = ConfigLoader(SampleConfig, debug=True)
    loader.load_env({"SAMPLE_PORT": "2222"})
    loader.set_values(port=3333)  # set_values after env, so it overrides
    config = loader.build()

    overridden = get_overridden_values(config)
    assert "port" in overridden
    assert config.port == 3333  # The actual value (CODE overrides ENV)


def test_no_debug_info() -> None:
    """Test that debug functions handle missing debug info gracefully."""
    loader = ConfigLoader(SampleConfig, debug=False)  # debug disabled
    config = loader.build()

    # Should not raise, but return sensible defaults
    assert not is_default(config, "name")
    assert not was_overridden(config, "name")
    assert get_value_source(config, "name") is None
    assert get_load_order(config) == []
    assert get_non_default_values(config) == {}

    # Should raise for report
    with pytest.raises(ValueError, match="No debug information"):
        get_config_report(config)


def test_lazy_loader() -> None:
    """Test LazyConfigLoader functionality."""
    lazy = LazyConfigLoader(SampleConfig, debug=True)

    # Set up loading
    loader = lazy.get_loader()
    loader.set_values(name="lazy_app")

    # Config is built on first access
    config = lazy.get_config()
    assert config.name == "lazy_app"

    # Same instance returned on subsequent calls
    assert lazy.get_config() is config

    # Reset clears everything
    lazy.reset()
    new_config = lazy.get_config()
    assert new_config is not config
    assert new_config.name == "default_name"  # back to default


def test_loader_chaining() -> None:
    """Test that loader methods can be chained."""
    loader = ConfigLoader(SampleConfig)
    config = loader.set_values(name="chained").load_env({"SAMPLE_PORT": "7777"}).build()

    assert config.name == "chained"
    assert config.port == 7777


def test_optional_file_loading(tmp_path: Path) -> None:
    """Test loading optional files that may not exist."""
    missing_file = tmp_path / "missing.json"
    existing_file = tmp_path / "existing.json"

    with existing_file.open("w") as f:
        json.dump({"name": "exists"}, f)

    loader = ConfigLoader(SampleConfig)
    loader.load_file(missing_file, required=False)  # Should not raise
    loader.load_file(existing_file, required=False)
    config = loader.build()

    assert config.name == "exists"

    # Required file should raise
    with pytest.raises(FileNotFoundError):
        loader.load_file(missing_file, required=True)
