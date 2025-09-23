"""Test environment variable adapter functionality."""

from cot.config import Config, field, sub_config
from cot.config.adapters import EnvironmentAdapter


class SimpleConfig(Config):
    """Simple configuration for testing."""

    name: str = field(default="test")
    debug: bool = field(default=False)
    count: int = field(default=0)
    items: list[str] = field(default_factory=list, action="append")


class AppConfig(Config, prefix="app"):
    """Configuration with prefix."""

    host: str = field(default="localhost")
    port: int = field(default=8080)
    ssl: bool = field(default=False)


def test_environment_adapter_basic():
    """Test basic environment adapter functionality."""
    adapter = EnvironmentAdapter(SimpleConfig)

    # Test with custom environment
    env = {
        "NAME": "envtest",
        "DEBUG": "true",
        "COUNT": "42",
        "ITEMS": "item1,item2,item3",
    }

    config_data = adapter.extract_config(env)

    assert config_data["name"] == "envtest"
    assert config_data["debug"] is True
    assert config_data["count"] == 42
    assert config_data["items"] == ["item1", "item2", "item3"]


def test_environment_adapter_with_prefix():
    """Test environment adapter with prefix."""
    adapter = EnvironmentAdapter(AppConfig)

    env = {
        "APP_HOST": "example.com",
        "APP_PORT": "3000",
        "APP_SSL": "yes",
    }

    config_data = adapter.extract_config(env)

    assert config_data["host"] == "example.com"
    assert config_data["port"] == 3000
    assert config_data["ssl"] is True


def test_environment_adapter_custom_prefix():
    """Test environment adapter with custom prefix."""
    adapter = EnvironmentAdapter(SimpleConfig, env_prefix="MYAPP")

    env = {
        "MYAPP_NAME": "custom",
        "MYAPP_DEBUG": "1",
    }

    config_data = adapter.extract_config(env)

    assert config_data["name"] == "custom"
    assert config_data["debug"] is True


def test_environment_adapter_json_parsing():
    """Test JSON parsing from environment variables."""
    adapter = EnvironmentAdapter(SimpleConfig, load_json=True)

    env = {
        "ITEMS": '["json1", "json2"]',
        "COUNT": "100",
    }

    config_data = adapter.extract_config(env)

    assert config_data["items"] == ["json1", "json2"]
    assert config_data["count"] == 100


def test_environment_adapter_boolean_parsing():
    """Test boolean value parsing."""
    adapter = EnvironmentAdapter(SimpleConfig)

    # Test various boolean representations
    for true_value in ["true", "True", "TRUE", "yes", "1", "on"]:
        env = {"DEBUG": true_value}
        config_data = adapter.extract_config(env)
        assert config_data["debug"] is True, f"Failed for {true_value}"

    for false_value in ["false", "False", "FALSE", "no", "0", "off"]:
        env = {"DEBUG": false_value}
        config_data = adapter.extract_config(env)
        assert config_data["debug"] is False, f"Failed for {false_value}"


def test_environment_adapter_with_subconfig():
    """Test environment adapter with sub-configuration."""

    class DatabaseConfig(Config):
        host: str = field(default="localhost")
        port: int = field(default=5432)

    class ServerConfig(Config, prefix="server"):
        db: DatabaseConfig = sub_config(DatabaseConfig, primary="host")
        name: str = field(default="server")

    adapter = EnvironmentAdapter(ServerConfig)

    env = {
        "SERVER_NAME": "myserver",
        "SERVER_DB": "dbserver",  # primary field
        "SERVER_DB_PORT": "5433",
    }

    config_data = adapter.extract_config(env)

    assert config_data["name"] == "myserver"
    assert "db" in config_data
    assert isinstance(config_data["db"], DatabaseConfig)
    assert config_data["db"].host == "dbserver"
    assert config_data["db"].port == 5433


def test_environment_adapter_get_var_names():
    """Test getting environment variable name mapping."""
    adapter = EnvironmentAdapter(AppConfig)

    mapping = adapter.get_env_var_names()

    assert mapping["host"] == "APP_HOST"
    assert mapping["port"] == "APP_PORT"
    assert mapping["ssl"] == "APP_SSL"


def test_environment_adapter_empty_values():
    """Test handling of empty environment values."""
    adapter = EnvironmentAdapter(SimpleConfig)

    env = {
        "NAME": "",  # Empty string
        "DEBUG": "false",
    }

    config_data = adapter.extract_config(env)

    assert "name" not in config_data  # Empty values are skipped
    assert config_data["debug"] is False