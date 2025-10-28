"""Test field features and descriptors."""
from cot.config import get_fields_config

import pytest

from cot.config import Config, field, from_parent, sub_config


def test_field_default_value():
    """Test field with default value."""

    class TestConfig(Config):
        name: str = field(default="default_name")
        count: int = field(default=42)

    config = TestConfig()
    assert config.name == "default_name"
    assert config.count == 42

    # Override defaults
    config = TestConfig(name="custom", count=100)
    assert config.name == "custom"
    assert config.count == 100


def test_field_default_factory():
    """Test field with default factory."""

    class TestConfig(Config):
        items: list[str] = field(default_factory=list)
        data: dict[str, int] = field(default_factory=dict)

    # Each instance should get a new list/dict
    config1 = TestConfig()
    config2 = TestConfig()

    config1.items.append("item1")
    config1.data["key"] = 1

    assert config2.items == []  # Not shared
    assert config2.data == {}  # Not shared


def test_field_with_help():
    """Test field help text is stored."""

    class TestConfig(Config):
        option: str = field(default="test", help="This is help text")

    fields = get_fields_config(TestConfig)
    assert fields["option"].help == "This is help text"


def test_field_with_choices():
    """Test field with restricted choices."""

    class TestConfig(Config):
        level: str = field(
            default="info", choices=["debug", "info", "warning", "error"]
        )

    # Valid choice
    config = TestConfig(level="debug")
    assert config.level == "debug"

    # Invalid choice should raise
    with pytest.raises(ValueError, match="Invalid value.*Must be one of"):
        TestConfig(level="invalid")


def test_field_from_parent():
    """Test from_parent marker."""

    class BaseConfig(Config):
        format: str = field(from_parent, default="%(message)s")
        level: str = field(from_parent, default="INFO")

    class ChildConfig(BaseConfig):
        enabled: bool = field(default=True)

    config = ChildConfig()
    assert config.format == "%(message)s"
    assert config.level == "INFO"
    assert config.enabled is True

    # Check that from_parent is marked
    assert get_fields_config(BaseConfig)["format"].from_parent is True
    assert get_fields_config(BaseConfig)["level"].from_parent is True
    assert get_fields_config(ChildConfig)["enabled"].from_parent is False


def test_field_action():
    """Test field action for CLI."""

    class TestConfig(Config):
        verbose: bool = field(default=False, action="store_true")
        paths: list[str] = field(default_factory=list, action="append")

    fields = get_fields_config(TestConfig)
    assert fields["verbose"].action == "store_true"
    assert fields["paths"].action == "append"


def test_field_required():
    """Test required field marker."""

    class TestConfig(Config):
        required_field: str = field(required=True)
        optional_field: str = field(default="optional")

    fields = get_fields_config(TestConfig)
    assert fields["required_field"].required is True
    assert fields["optional_field"].required is False


def test_field_metavar():
    """Test field metavar for CLI help."""

    class TestConfig(Config):
        file: str = field(default=None, metavar="FILE")
        count: int = field(default=1, metavar="N")

    fields = get_fields_config(TestConfig)
    assert fields["file"].metavar == "FILE"
    assert fields["count"].metavar == "N"


def test_sub_config_basic():
    """Test basic sub-configuration."""

    class SubConfig(Config):
        enabled: bool = field(default=False)
        value: str = field(default="test")

    class MainConfig(Config):
        sub: SubConfig = sub_config(SubConfig)

    config = MainConfig()
    assert isinstance(config.sub, SubConfig)
    assert config.sub.enabled is False
    assert config.sub.value == "test"

    # With values
    config = MainConfig(sub=SubConfig(enabled=True, value="custom"))
    assert config.sub.enabled is True
    assert config.sub.value == "custom"


def test_sub_config_primary():
    """Test sub-config with primary field."""

    class FeatureConfig(Config):
        enabled: bool = field(default=False)
        level: str = field(default="normal")

    class AppConfig(Config):
        feature: FeatureConfig = sub_config(FeatureConfig, primary="enabled")

    fields = get_fields_config(AppConfig)
    assert fields["feature"].primary == "enabled"


def test_config_inheritance():
    """Test configuration class inheritance."""

    class BaseConfig(Config):
        base_field: str = field(default="base")

    class DerivedConfig(BaseConfig):
        derived_field: str = field(default="derived")

    config = DerivedConfig()
    assert config.base_field == "base"
    assert config.derived_field == "derived"

    # Both fields should be in the derived config's fields
    fields = get_fields_config(DerivedConfig)
    assert "base_field" in fields
    assert "derived_field" in fields


def test_config_prefix():
    """Test configuration prefix."""

    class PrefixedConfig(Config, prefix="myprefix"):
        option: str = field(default="test")

    assert get_fields_config(PrefixedConfig).prefix == "myprefix"

    class NoPrefixConfig(Config):
        option: str = field(default="test")

    assert get_fields_config(NoPrefixConfig).prefix is None


def test_field_cannot_have_both_default_and_factory():
    """Test that field cannot have both default and default_factory."""
    err_msg = "Cannot specify both default and default_factory"
    with pytest.raises(ValueError, match=err_msg):
        field(default="test", default_factory=list)


def test_field_descriptor_get_default():
    """Test FieldDescriptor.get_default method."""
    from cot.config.descriptors import FieldDescriptor

    # With default value
    desc = FieldDescriptor(default="test")
    assert desc.get_default() == "test"

    # With default factory
    desc = FieldDescriptor(default_factory=list)
    result = desc.get_default()
    assert isinstance(result, list)
    assert result == []

    # With neither
    desc = FieldDescriptor()
    assert desc.get_default() is None
