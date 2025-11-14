"""Test loading configuration from multiple sources."""

import argparse
import json
from pathlib import Path

from cot.config import Config, field
from cot.config.adapters import ConfigToArgparseAdapter, EnvironmentAdapter


class AppConfig(Config, prefix="app"):
    """Application configuration."""

    name: str = field(default="myapp", help="Application name")
    host: str = field(default="localhost", help="Server host")
    port: int = field(default=8080, help="Server port")
    debug: bool = field(default=False, help="Enable debug mode")
    log_level: str = field(default="INFO", help="Logging level")
    workers: int = field(default=4, help="Number of workers")


def test_from_data_single_source() -> None:
    """Test from_data with a single source."""
    config = AppConfig.from_data({"name": "test", "port": 3000})

    assert config.name == "test"
    assert config.host == "localhost"  # default
    assert config.port == 3000
    assert config.debug is False


def test_from_data_multiple_sources() -> None:
    """Test from_data with multiple sources that override each other."""
    # First source: base config
    base = {
        "name": "base_app",
        "host": "0.0.0.0",
        "port": 8000,
        "debug": False,
    }

    # Second source: environment overrides
    env = {
        "port": 9000,
        "debug": True,
        "log_level": "DEBUG",
    }

    # Third source: CLI overrides
    cli = {
        "workers": 8,
    }

    config = AppConfig.from_data(base, env, cli)

    assert config.name == "base_app"  # from base
    assert config.host == "0.0.0.0"  # from base
    assert config.port == 9000  # overridden by env
    assert config.debug is True  # overridden by env
    assert config.log_level == "DEBUG"  # from env
    assert config.workers == 8  # from cli


def test_from_data_with_origins() -> None:
    """Test from_data with origin tracking."""
    config = AppConfig.from_data(
        ("config.json", {"name": "from_file", "port": 5000}),
        ("environment", {"debug": True}),
        ("cli", {"workers": 16}),
    )

    assert config.name == "from_file"
    assert config.port == 5000
    assert config.debug is True
    assert config.workers == 16


def test_from_files(tmp_path: Path) -> None:
    """Test loading from multiple files."""
    # Create test files
    base_config = tmp_path / "base.json"
    with base_config.open("w") as f:
        json.dump({"name": "file_app", "port": 7000}, f)

    override_config = tmp_path / "override.json"
    with override_config.open("w") as f:
        json.dump({"port": 7777, "debug": True}, f)

    config = AppConfig.from_files(base_config, override_config)

    assert config.name == "file_app"
    assert config.port == 7777  # overridden
    assert config.debug is True


def test_from_env() -> None:
    """Test loading from environment variables."""
    env = {
        "APP_NAME": "env_app",
        "APP_HOST": "env.example.com",
        "APP_PORT": "4000",
        "APP_DEBUG": "true",
    }

    config = AppConfig.from_env(environ=env)

    assert config.name == "env_app"
    assert config.host == "env.example.com"
    assert config.port == 4000
    assert config.debug is True


def test_combined_sources_integration(tmp_path: Path) -> None:
    """Test realistic integration with file, env, and CLI sources."""
    # 1. Create a config file
    config_file = tmp_path / "app.json"
    with config_file.open("w") as f:
        json.dump(
            {
                "name": "production_app",
                "host": "0.0.0.0",
                "port": 80,
                "workers": 10,
            },
            f,
        )

    # 2. Simulate environment variables
    env_adapter = EnvironmentAdapter(AppConfig)
    env_data = env_adapter.extract_config(
        {
            "APP_DEBUG": "true",
            "APP_LOG_LEVEL": "WARNING",
        }
    )

    # 3. Simulate CLI arguments
    parser = argparse.ArgumentParser()
    cli_adapter = ConfigToArgparseAdapter(AppConfig)
    cli_adapter.add_to_parser(parser)

    args = parser.parse_args(["--app-port", "8888"])
    cli_data = cli_adapter.extract_config(args)

    # 4. Load and merge from all sources
    file_data = json.loads(config_file.read_text())
    config = AppConfig.from_data(
        ("file", file_data),
        ("env", env_data),
        ("cli", cli_data),
    )

    # Verify final configuration
    assert config.name == "production_app"  # from file
    assert config.host == "0.0.0.0"  # from file
    assert config.port == 8888  # overridden by CLI
    assert config.debug is True  # from env
    assert config.log_level == "WARNING"  # from env
    assert config.workers == 10  # from file


def test_deep_merge() -> None:
    """Test deep merging of nested configurations."""
    from typing import Any

    class NestedConfig(Config):
        database: dict[str, Any] = field(default_factory=dict)
        features: dict[str, Any] = field(default_factory=dict)

    source1 = {
        "database": {
            "host": "localhost",
            "port": 5432,
            "name": "mydb",
        },
        "features": {
            "auth": True,
            "cache": False,
        },
    }

    source2 = {
        "database": {
            "port": 5433,  # override
            "user": "admin",  # new field
        },
        "features": {
            "cache": True,  # override
            "logging": True,  # new field
        },
    }

    config = NestedConfig.from_data(source1, source2)

    # Check merged database config
    assert config.database["host"] == "localhost"  # from source1
    assert config.database["port"] == 5433  # overridden
    assert config.database["name"] == "mydb"  # from source1
    assert config.database["user"] == "admin"  # from source2

    # Check merged features
    assert config.features["auth"] is True  # from source1
    assert config.features["cache"] is True  # overridden
    assert config.features["logging"] is True  # from source2
