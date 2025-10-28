"""Test the pytest adapter functionality."""

from unittest.mock import Mock

from cot.config import Config, field, sub_config, get_fields_config
from cot.config.adapters import ConfigToPytestAdapter


class SampleConfig(Config, prefix="sample"):
    """Sample configuration for testing."""

    name: str = field(default="test", help="Name for the test")
    debug: bool = field(default=False, help="Enable debug mode")
    verbose: int = field(default=0, help="Verbosity level")
    paths: list[str] = field(
        default_factory=list, action="append", help="Paths to include"
    )


class NestedConfig(Config):
    """Nested configuration for testing."""

    enabled: bool = field(default=False, help="Enable the feature")
    level: str = field(default="info", choices=["debug", "info", "warning"])


class ParentConfig(Config, prefix="parent"):
    """Parent configuration with nested config."""

    option: str = field(default="default", help="A simple option")
    nested: NestedConfig = sub_config(NestedConfig, primary="enabled")


def test_adapter_basic():
    """Test basic adapter functionality."""
    adapter = ConfigToPytestAdapter(SampleConfig)

    assert adapter.config_class is SampleConfig
    assert adapter.prefix == "sample"


def test_adapter_field_name_conversion():
    """Test field name to CLI/ini name conversion."""
    adapter = ConfigToPytestAdapter(SampleConfig)

    # Test CLI name conversion
    assert adapter._field_to_cli_name("name") == "--sample-name"
    assert adapter._field_to_cli_name("debug") == "--sample-debug"
    assert adapter._field_to_cli_name("verbose_level") == "--sample-verbose-level"

    # Test ini name conversion
    assert adapter._field_to_ini_name("name") == "sample_name"
    assert adapter._field_to_ini_name("debug") == "sample_debug"


def test_adapter_no_prefix():
    """Test adapter without prefix."""

    class NoPrefix(Config):
        option: str = field(default="test")

    adapter = ConfigToPytestAdapter(NoPrefix)

    assert adapter._field_to_cli_name("option") == "--option"
    assert adapter._field_to_ini_name("option") == "option"


def test_add_to_parser():
    """Test adding configuration to a mock parser."""
    # Create mock parser
    parser = Mock()
    group = Mock()
    parser.getgroup.return_value = group

    # Create adapter and add to parser
    adapter = ConfigToPytestAdapter(SampleConfig)
    adapter.add_to_parser(parser, "test_group")

    # Verify parser calls
    parser.getgroup.assert_called_once_with("test_group")

    # Check ini options were added
    assert parser.addini.call_count == 3  # name, debug, verbose (paths is append-only)

    # Check that paths was added as CLI-only with append
    group.addoption.assert_any_call(
        "--sample-paths",
        dest="sample_paths",
        default=[],
        action="append",
        help="Paths to include",
        metavar=None,
    )


def test_add_nested_config_to_parser():
    """Test adding nested configuration to parser."""
    parser = Mock()
    group = Mock()
    parser.getgroup.return_value = group

    adapter = ConfigToPytestAdapter(ParentConfig)
    adapter.add_to_parser(parser, "parent_group")

    # Should add parent option
    parser.addini.assert_any_call(
        "parent_option",
        default="default",
        type=None,
        help="A simple option",
    )

    # Should add nested primary field
    parser.addini.assert_any_call(
        "parent_nested",
        default=False,
        type="bool",
        help="Enable the feature",
    )

    # Should add nested non-primary field with prefix
    parser.addini.assert_any_call(
        "parent_nested_level",
        default="info",
        type=None,
        help="Default value for --parent-nested-level",
    )


def test_extract_config():
    """Test extracting configuration from parsed arguments."""
    adapter = ConfigToPytestAdapter(SampleConfig)

    # Mock parsed args
    parsed_args = Mock()
    parsed_args.sample_name = "test_name"
    parsed_args.sample_debug = True
    parsed_args.sample_verbose = 2
    parsed_args.sample_paths = ["path1", "path2"]

    config_data = adapter.extract_config(parsed_args)

    assert config_data == {
        "name": "test_name",
        "debug": True,
        "verbose": 2,
        "paths": ["path1", "path2"],
    }


def test_extract_nested_config():
    """Test extracting nested configuration."""
    adapter = ConfigToPytestAdapter(ParentConfig)

    parsed_args = Mock()
    parsed_args.parent_option = "custom"
    parsed_args.parent_nested = True  # primary field
    parsed_args.parent_nested_level = "warning"

    config_data = adapter.extract_config(parsed_args)

    assert "option" in config_data
    assert config_data["option"] == "custom"
    assert "nested" in config_data
    assert isinstance(config_data["nested"], NestedConfig)
    assert config_data["nested"].enabled is True
    assert config_data["nested"].level == "warning"


def test_ini_type_detection():
    """Test ini type detection for fields."""
    adapter = ConfigToPytestAdapter(SampleConfig)

    bool_field = get_fields_config(SampleConfig)["debug"]
    assert adapter._get_ini_type(bool_field) == "bool"

    str_field = get_fields_config(SampleConfig)["name"]
    assert adapter._get_ini_type(str_field) is None  # Default to None for non-bool
