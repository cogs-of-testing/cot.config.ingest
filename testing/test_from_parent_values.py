"""Test from_parent field value propagation functionality."""

from cot.config import Config, field, from_parent, sub_config


def test_from_parent_value_propagation() -> None:
    """Test that from_parent fields get values from parent config instance."""

    class LogConfig(Config):
        # These fields should get their values from the parent config
        level: str = field(from_parent, default="INFO")
        format: str = field(from_parent, default="%(message)s")
        # This is a regular field
        enabled: bool = field(default=False)

    class AppConfig(Config):
        # Parent config has these fields
        level: str = field(default="DEBUG")
        format: str = field(default="%(levelname)s: %(message)s")
        # Sub-config should get level and format from parent
        logging: LogConfig = sub_config(LogConfig)

    # Create parent config instance
    app = AppConfig()

    # Sub-config fields marked with from_parent should get values from parent instance
    assert app.logging.level == "DEBUG"  # Got value from parent's level field
    assert (
        app.logging.format == "%(levelname)s: %(message)s"
    )  # Got value from parent's format field
    assert app.logging.enabled is False  # Used its own default


def test_from_parent_with_explicit_override() -> None:
    """Test that explicit values override from_parent."""

    class SubConfig(Config):
        value: str = field(from_parent, default="sub_default")

    class ParentConfig(Config):
        value: str = field(default="parent_value")
        sub: SubConfig = sub_config(SubConfig)

    # When sub-config is explicitly provided with a value
    config = ParentConfig(sub={"value": "explicit"})  # type: ignore[arg-type]
    assert config.sub.value == "explicit"  # Explicit value wins

    # When no explicit value, should get from parent
    config = ParentConfig()
    assert config.sub.value == "parent_value"  # Got from parent


def test_from_parent_missing_in_parent() -> None:
    """Test from_parent when parent doesn't have matching field."""

    class SubConfig(Config):
        # Parent won't have this field
        missing_field: str = field(from_parent, default="fallback")

    class ParentConfig(Config):
        other_field: str = field(default="other")
        sub: SubConfig = sub_config(SubConfig)

    config = ParentConfig()
    # Should use default when parent doesn't have the field
    assert config.sub.missing_field == "fallback"


def test_from_parent_with_multiple_sub_configs() -> None:
    """Test from_parent with multiple sub-configurations."""

    class LogConfig(Config):
        level: str = field(from_parent, default="INFO")
        format: str = field(from_parent, default="%(message)s")

    class AppConfig(Config):
        level: str = field(default="WARNING")
        format: str = field(default="[%(levelname)s] %(message)s")

        file_log: LogConfig = sub_config(LogConfig)
        console_log: LogConfig = sub_config(LogConfig)

    config = AppConfig()

    # Both sub-configs should get values from parent
    assert config.file_log.level == "WARNING"
    assert config.file_log.format == "[%(levelname)s] %(message)s"

    assert config.console_log.level == "WARNING"
    assert config.console_log.format == "[%(levelname)s] %(message)s"


def test_from_parent_with_custom_parent_values() -> None:
    """Test from_parent when parent values are customized."""

    class SubConfig(Config):
        level: str = field(from_parent, default="INFO")
        enabled: bool = field(default=True)

    class ParentConfig(Config):
        level: str = field(default="WARNING")
        sub: SubConfig = sub_config(SubConfig)

    # Create config with custom parent value
    config = ParentConfig(level="ERROR")

    # Sub-config should get the custom value
    assert config.sub.level == "ERROR"
    assert config.sub.enabled is True


def test_from_parent_with_none_values() -> None:
    """Test from_parent handles None values correctly."""

    class SubConfig(Config):
        value: str | None = field(from_parent, default="default")

    class ParentConfig(Config):
        value: str | None = field(default=None)
        sub: SubConfig = sub_config(SubConfig)

    config = ParentConfig()
    # When parent has None, sub should get None (not fall back to default)
    assert config.sub.value is None

    config = ParentConfig(value="explicit")
    # When parent has a value, sub gets it
    assert config.sub.value == "explicit"


def test_readme_logging_example_simplified() -> None:
    """Test simplified version of the logging configuration example from README."""

    DEFAULT_LOG_FORMAT = "%(levelname)-8s %(name)s:%(filename)s:%(lineno)d %(message)s"
    DEFAULT_LOG_DATE_FORMAT = "%H:%M:%S"

    class LogBaseConfig(Config):
        # These fields get values from parent
        level: str | None = field(from_parent, default=None)
        date_format: str = field(from_parent, default=DEFAULT_LOG_DATE_FORMAT)
        format: str = field(from_parent, default=DEFAULT_LOG_FORMAT)

    class LogCliConfig(LogBaseConfig):
        enable: bool = field(default=False)

    class LogFileConfig(LogBaseConfig):
        path: str | None = field(default=None)
        mode: str = field(default="w")

    class LoggingPluginConfig(Config, prefix="log"):
        # Parent values that sub-configs will get via from_parent
        level: str | None = field(default="WARNING")
        date_format: str = field(default=DEFAULT_LOG_DATE_FORMAT)
        format: str = field(default=DEFAULT_LOG_FORMAT)

        # Sub-configs that should get values from parent for from_parent fields
        cli: LogCliConfig = sub_config(LogCliConfig)
        file: LogFileConfig = sub_config(LogFileConfig)

        auto_indent: bool | int | None = field(default=None)
        disable: list[str] = field(default_factory=list)

    # Test default configuration
    config = LoggingPluginConfig()

    # Parent has these values
    assert config.level == "WARNING"
    assert config.format == DEFAULT_LOG_FORMAT
    assert config.date_format == DEFAULT_LOG_DATE_FORMAT

    # CLI sub-config should get from_parent field values from parent instance
    assert config.cli.level == "WARNING"  # from parent's level
    assert config.cli.format == DEFAULT_LOG_FORMAT  # from parent's format
    assert (
        config.cli.date_format == DEFAULT_LOG_DATE_FORMAT
    )  # from parent's date_format
    assert config.cli.enable is False  # own default

    # File sub-config should get from_parent field values from parent instance
    assert config.file.level == "WARNING"  # from parent's level
    assert config.file.format == DEFAULT_LOG_FORMAT  # from parent's format
    assert (
        config.file.date_format == DEFAULT_LOG_DATE_FORMAT
    )  # from parent's date_format
    assert config.file.path is None  # own default
    assert config.file.mode == "w"  # own default

    # Test with custom parent values
    config = LoggingPluginConfig(
        level="DEBUG",
        format="%(message)s",
        cli={"enable": True},  # type: ignore[arg-type]
    )

    # Sub-configs get new parent values
    assert config.cli.level == "DEBUG"  # from parent's custom level
    assert config.cli.format == "%(message)s"  # from parent's custom format
    assert config.cli.enable is True  # explicitly set

    assert config.file.level == "DEBUG"  # from parent's custom level
    assert config.file.format == "%(message)s"  # from parent's custom format


def test_from_parent_with_data_sources() -> None:
    """Test from_parent with from_data() method."""

    class SubConfig(Config):
        shared_value: str = field(from_parent, default="default")
        own_value: str = field(default="own")

    class ParentConfig(Config):
        shared_value: str = field(default="parent_default")
        parent_only: str = field(default="parent")
        sub: SubConfig = sub_config(SubConfig)

    # Load from multiple sources
    file_data = {"shared_value": "from_file", "parent_only": "file_parent"}
    env_data = {"sub": {"own_value": "from_env"}}

    config = ParentConfig.from_data(file_data, env_data)

    # Parent gets value from file
    assert config.shared_value == "from_file"
    # Sub-config gets shared_value from parent, own_value from env
    assert config.sub.shared_value == "from_file"  # from parent
    assert config.sub.own_value == "from_env"  # from env_data


def test_from_parent_initialization_order() -> None:
    """Test that from_parent values are resolved during initialization."""

    class SubConfig(Config):
        value: str = field(from_parent, default="sub_default")

    class ParentConfig(Config):
        value: str = field(default="parent_default")
        sub: SubConfig = sub_config(SubConfig)

    # Initialize with dict for sub-config (without explicit value)
    config = ParentConfig(value="custom", sub={})  # type: ignore[arg-type]
    assert config.sub.value == "custom"  # Should get from parent

    # Initialize with SubConfig instance
    sub_instance = SubConfig()  # At this point, no parent available
    config = ParentConfig(value="custom", sub=sub_instance)
    # This is a design question: should we re-resolve from_parent fields?
    # Current expectation: the instance is used as-is
    # (This test documents current behavior, may need adjustment)
