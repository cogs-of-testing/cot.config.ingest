"""
Tests for configuration sources (TOML, INI, Environment).

These tests verify the basic functionality of loading configuration
from various sources with type conversion and precedence handling.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from cot.config import (
    ConfigManager,
    ConfigPart,
    EnvSource,
    IniSource,
    TomlSource,
)


class TestTomlSource:
    """Test loading config from TOML files."""

    def test_load_flat_config(self, tmp_path: Path) -> None:
        """Load a simple flat configuration."""

        class SimpleConfig(ConfigPart, prefix="app"):
            debug: bool = False
            log_level: str = "INFO"
            name: str = "myapp"

        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            dedent("""
            [app]
            debug = true
            log_level = "DEBUG"
            name = "testapp"
        """)
        )

        manager = ConfigManager()
        manager.add_source(TomlSource(toml_file))

        manager.declare(SimpleConfig)
        config = manager.get(SimpleConfig)

        assert config.debug is True
        assert config.log_level == "DEBUG"
        assert config.name == "testapp"

    def test_defaults_when_missing(self, tmp_path: Path) -> None:
        """Defaults are used when values are not in config."""

        class SimpleConfig(ConfigPart, prefix="app"):
            debug: bool = False
            log_level: str = "INFO"

        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            dedent("""
            [app]
            debug = true
        """)
        )

        manager = ConfigManager()
        manager.add_source(TomlSource(toml_file))

        manager.declare(SimpleConfig)
        config = manager.get(SimpleConfig)

        assert config.debug is True
        assert config.log_level == "INFO"  # default

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Missing config file returns empty dict, uses defaults."""

        class AppConfig(ConfigPart, prefix="app"):
            debug: bool = False
            log_level: str = "WARNING"

        manager = ConfigManager()
        manager.add_source(TomlSource(tmp_path / "nonexistent.toml"))

        manager.declare(AppConfig)
        config = manager.get(AppConfig)

        # All defaults
        assert config.debug is False
        assert config.log_level == "WARNING"


class TestIniSource:
    """Test loading config from INI files (pytest.ini style)."""

    def test_load_from_ini(self, tmp_path: Path) -> None:
        """Load config from INI file."""

        class PytestConfig(ConfigPart, prefix="pytest"):
            addopts: str = ""
            testpaths: str = "tests"
            python_files: str = "test_*.py"

        ini_file = tmp_path / "pytest.ini"
        ini_file.write_text(
            dedent("""
            [pytest]
            addopts = -v --tb=short
            testpaths = testing
        """)
        )

        manager = ConfigManager()
        manager.add_source(IniSource(ini_file))

        manager.declare(PytestConfig)
        config = manager.get(PytestConfig)

        assert config.addopts == "-v --tb=short"
        assert config.testpaths == "testing"
        assert config.python_files == "test_*.py"  # default

    def test_ini_boolean_values(self, tmp_path: Path) -> None:
        """INI source handles various boolean formats."""

        class FlagsConfig(ConfigPart, prefix="flags"):
            enabled: bool = False
            verbose: bool = False

        ini_file = tmp_path / "config.ini"
        ini_file.write_text(
            dedent("""
            [flags]
            enabled = yes
            verbose = true
        """)
        )

        manager = ConfigManager()
        manager.add_source(IniSource(ini_file))

        manager.declare(FlagsConfig)
        config = manager.get(FlagsConfig)

        assert config.enabled is True
        assert config.verbose is True


class TestEnvSource:
    """Test loading config from environment variables."""

    def test_load_from_env(self) -> None:
        """Load config from environment variables."""

        class AppConfig(ConfigPart, prefix="APP"):
            debug: bool = False
            log_level: str = "INFO"
            name: str = "default"

        env = {
            "APP_DEBUG": "true",
            "APP_LOG_LEVEL": "ERROR",
            "APP_NAME": "testapp",
        }

        manager = ConfigManager()
        manager.add_source(EnvSource(environ=env))

        manager.declare(AppConfig)
        config = manager.get(AppConfig)

        assert config.debug is True
        assert config.log_level == "ERROR"
        assert config.name == "testapp"

    def test_env_prefix_from_class(self) -> None:
        """Environment variables use ConfigPart prefix."""

        class DbConfig(ConfigPart, prefix="DB"):
            host: str = "localhost"
            port: int = 5432

        env = {
            "DB_HOST": "production.db",
            "DB_PORT": "3306",
        }

        manager = ConfigManager()
        manager.add_source(EnvSource(environ=env))

        manager.declare(DbConfig)
        config = manager.get(DbConfig)

        assert config.host == "production.db"
        assert config.port == 3306

    def test_source_and_part_prefixes_compose(self) -> None:
        """An application prefix survives a ConfigPart declaring its own.

        The part's ``prefix`` names a config-file section; the source's names
        the application's slice of the environment. They are different
        concerns, so they compose -- the part used to shadow the source, which
        made ``EnvSource("APP")`` silently read nothing.
        """

        class DbConfig(ConfigPart, prefix="db"):
            host: str = "localhost"

        manager = ConfigManager(
            sources=[EnvSource("APP", environ={"APP_DB_HOST": "production.db"})]
        )
        manager.declare(DbConfig)

        assert manager.get(DbConfig).host == "production.db"
        assert manager.origin_of(DbConfig, "host").location == "APP_DB_HOST"

    def test_unprefixed_source_leaves_the_part_prefix_alone(self) -> None:
        """With no source prefix the part's prefix is the whole name."""

        class DbConfig(ConfigPart, prefix="db"):
            host: str = "localhost"

        manager = ConfigManager(sources=[EnvSource(environ={"DB_HOST": "prod"})])
        manager.declare(DbConfig)

        assert manager.get(DbConfig).host == "prod"


class TestSourcePrecedence:
    """Test that sources are merged with correct precedence."""

    def test_env_overrides_file(self, tmp_path: Path) -> None:
        """Environment variables override file config."""

        class AppConfig(ConfigPart, prefix="app"):
            debug: bool = False
            log_level: str = "INFO"
            name: str = "default"

        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            dedent("""
            [app]
            debug = false
            log_level = "DEBUG"
            name = "from-file"
        """)
        )

        env = {
            "APP_DEBUG": "true",
            "APP_LOG_LEVEL": "ERROR",
        }

        manager = ConfigManager()
        manager.add_source(TomlSource(toml_file, precedence=10))
        manager.add_source(EnvSource(environ=env, precedence=20))

        manager.declare(AppConfig)
        config = manager.get(AppConfig)

        # Env overrides
        assert config.debug is True
        assert config.log_level == "ERROR"
        # File value preserved where no env override
        assert config.name == "from-file"

    def test_multiple_files_merge(self, tmp_path: Path) -> None:
        """Multiple config files merge with precedence."""

        class AppConfig(ConfigPart, prefix="app"):
            debug: bool = False
            log_level: str = "WARNING"
            format: str = "default"

        base_config = tmp_path / "base.toml"
        base_config.write_text(
            dedent("""
            [app]
            debug = false
            log_level = "DEBUG"
            format = "base format"
        """)
        )

        local_config = tmp_path / "local.toml"
        local_config.write_text(
            dedent("""
            [app]
            debug = true
            log_level = "INFO"
        """)
        )

        manager = ConfigManager()
        manager.add_source(TomlSource(base_config, precedence=5))
        manager.add_source(TomlSource(local_config, precedence=10))

        manager.declare(AppConfig)
        config = manager.get(AppConfig)

        # Local overrides base
        assert config.debug is True
        assert config.log_level == "INFO"
        # Base value preserved where no local override
        assert config.format == "base format"


class TestSourcesOnly:
    """Test the sources-only architecture."""

    def test_sources_provide_context(self, tmp_path: Path) -> None:
        """Sources provide all context directly."""
        from cot.config import CLISource, ConfigFileDiscoverySource

        class AppConfig(ConfigPart, prefix="app"):
            debug: bool = False
            config_file: str | None = None

        # Create config file
        ini_file = tmp_path / "config.ini"
        ini_file.write_text(
            dedent("""
            [app]
            debug = true
        """)
        )

        # Sources hold all context
        cli = CLISource(
            args=["--config-file", "config.ini"],
            invocation_dir=tmp_path,
        )
        files = ConfigFileDiscoverySource(
            invocation_dir=tmp_path,
            cli_source=cli,
            filenames=["config.ini"],
        )

        manager = ConfigManager(sources=[cli, files])

        manager.declare(AppConfig)
        config = manager.get(AppConfig)
        assert config.debug is True
        assert config.config_file == "config.ini"
