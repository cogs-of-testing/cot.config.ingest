"""Test argparse adapter functionality."""

import argparse

from cot.config import Config, field, sub_config
from cot.config.adapters import ConfigToArgparseAdapter


class SimpleConfig(Config):
    """Simple configuration for testing."""

    name: str = field(default="test", help="Name for the test")
    debug: bool = field(default=False, action="store_true", help="Enable debug mode")
    verbose: int = field(default=0, help="Verbosity level")
    paths: list[str] = field(
        default_factory=list, action="append", help="Paths to include"
    )


class AppConfig(Config, prefix="app"):
    """Configuration with prefix."""

    host: str = field(default="localhost", help="Server host")
    port: int = field(default=8080, help="Server port")
    workers: int = field(default=4, help="Number of workers")


def test_argparse_adapter_basic():
    """Test basic argparse adapter functionality."""
    adapter = ConfigToArgparseAdapter(SimpleConfig)
    parser = argparse.ArgumentParser()

    adapter.add_to_parser(parser)

    # Parse some arguments
    args = parser.parse_args(
        ["--name", "mytest", "--debug", "--paths", "path1", "--paths", "path2"]
    )

    assert args.name == "mytest"
    assert args.debug is True
    assert args.verbose == 0
    assert args.paths == ["path1", "path2"]


def test_argparse_adapter_with_prefix():
    """Test argparse adapter with prefix."""
    adapter = ConfigToArgparseAdapter(AppConfig)
    parser = argparse.ArgumentParser()

    adapter.add_to_parser(parser)

    # Parse arguments with prefix
    args = parser.parse_args(["--app-host", "example.com", "--app-port", "3000"])

    assert args.app_host == "example.com"
    assert args.app_port == 3000
    assert args.app_workers == 4  # default


def test_argparse_extract_config():
    """Test extracting config from parsed arguments."""
    adapter = ConfigToArgparseAdapter(SimpleConfig)
    parser = argparse.ArgumentParser()
    adapter.add_to_parser(parser)

    args = parser.parse_args(["--name", "extracted", "--debug", "--verbose", "2"])
    config_data = adapter.extract_config(args)

    assert config_data["name"] == "extracted"
    assert config_data["debug"] is True
    assert config_data["verbose"] == 2
    # paths not in config_data because it's using default


def test_argparse_create_parser():
    """Test creating a parser directly."""
    adapter = ConfigToArgparseAdapter(AppConfig)
    parser = adapter.create_parser(
        prog="myapp",
        description="My application",
    )

    args = parser.parse_args(["--app-host", "0.0.0.0", "--app-port", "9999"])
    config_data = adapter.extract_config(args)

    assert config_data["host"] == "0.0.0.0"
    assert config_data["port"] == 9999


def test_argparse_with_subconfig():
    """Test argparse adapter with sub-configuration."""

    class DatabaseConfig(Config):
        host: str = field(default="localhost")
        port: int = field(default=5432)

    class ServerConfig(Config):
        db: DatabaseConfig = sub_config(DatabaseConfig)
        name: str = field(default="server")

    adapter = ConfigToArgparseAdapter(ServerConfig)
    parser = argparse.ArgumentParser()
    adapter.add_to_parser(parser)

    args = parser.parse_args(
        ["--name", "myserver", "--db-host", "dbserver", "--db-port", "5433"]
    )

    config_data = adapter.extract_config(args)

    assert config_data["name"] == "myserver"
    assert "db" in config_data
    # Sub-config should be a dict, not an instance (for from_parent support)
    assert isinstance(config_data["db"], dict)
    assert config_data["db"]["host"] == "dbserver"
    assert config_data["db"]["port"] == 5433


def test_argparse_field_dest():
    """Test field destination naming."""
    adapter = ConfigToArgparseAdapter(AppConfig)

    # With prefix
    assert adapter._field_to_dest("host") == "app_host"
    assert adapter._field_to_dest("port") == "app_port"

    # Without prefix
    adapter_no_prefix = ConfigToArgparseAdapter(SimpleConfig)
    assert adapter_no_prefix._field_to_dest("name") == "name"
