"""
Acceptance test for bootstrap workflow.

This test demonstrates the complete bootstrap flow where:
1. ConfigManager is created with sources (CLI, env, config files)
2. ConfigFileDiscoverySource discovers config files from CLI/env/filesystem
3. Configuration is loaded with proper precedence (CLI > env > file > defaults)

This mirrors how pytest discovers pytest.ini/pyproject.toml based on
invocation directory and CLI args, and how addopts from different sources combine.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Annotated

from cot.config import (
    CLISource,
    ConfigFileDiscoverySource,
    ConfigManager,
    ConfigPart,
    EnvSource,
    addopts_field,
    bootstrap_only,
    config_source,
    short,
)

# --- Pytest-like ConfigPart with config file discovery ---


class PytestConfig(ConfigPart, prefix="pytest"):
    """
    Pytest-like configuration with addopts.

    The config_file field is marked with config_source, so when provided
    via CLI (--config-file), it will automatically be added as a TOML source.

    Similar to pytest's configuration where addopts can come from:
    - Config file (pytest.ini, pyproject.toml)
    - Environment variable (PYTEST_ADDOPTS)
    - CLI args
    """

    config_file: Annotated[str | None, config_source] = None
    addopts: str = ""
    testpaths: str = "tests"


class TestBootstrapConfigFileDiscovery:
    """
    Test that config file path from CLI args is discovered and loaded.
    """

    def test_config_file_from_cli_arg(self, tmp_path: Path) -> None:
        """
        Config file specified via CLI arg is discovered and loaded.

        Simulates: pytest --config-file custom.toml
        """
        # Create config file with addopts
        config_file = tmp_path / "custom.toml"
        config_file.write_text(
            dedent("""
            [pytest]
            addopts = "-v --tb=short"
            testpaths = "testing"
        """)
        )

        # Create sources
        cli = CLISource(
            args=["--config-file", "custom.toml"],
            invocation_dir=tmp_path,
        )
        files = ConfigFileDiscoverySource(
            invocation_dir=tmp_path,
            cli_source=cli,
        )
        manager = ConfigManager(sources=[cli, files])
        config = manager.register_fragment_type(PytestConfig)

        assert config.config_file == "custom.toml"
        assert config.addopts == "-v --tb=short"
        assert config.testpaths == "testing"

    def test_env_overrides_config_file(self, tmp_path: Path) -> None:
        """
        Environment variables override config file values.

        Precedence: CLI (25) > env (20) > config file (15) > defaults
        """
        config_file = tmp_path / "pytest.toml"
        config_file.write_text(
            dedent("""
            [pytest]
            addopts = "-v"
            testpaths = "tests"
        """)
        )

        env = {
            "PYTEST_ADDOPTS": "-x --pdb",
        }

        cli = CLISource(
            args=["--config-file", "pytest.toml"],
            invocation_dir=tmp_path,
        )
        files = ConfigFileDiscoverySource(
            invocation_dir=tmp_path,
            cli_source=cli,
        )
        manager = ConfigManager(sources=[cli, files])
        manager.add_source(EnvSource(environ=env, precedence=20))

        config = manager.register_fragment_type(PytestConfig)

        # Env overrides file
        assert config.addopts == "-x --pdb"
        # File value preserved where no env override
        assert config.testpaths == "tests"

    def test_no_config_file_uses_defaults(self, tmp_path: Path) -> None:
        """
        Without config file, defaults are used.
        """
        cli = CLISource(args=[], invocation_dir=tmp_path)
        manager = ConfigManager(sources=[cli])
        config = manager.register_fragment_type(PytestConfig)

        assert config.config_file is None
        assert config.addopts == ""
        assert config.testpaths == "tests"

    def test_nonexistent_config_file_raises_error(self, tmp_path: Path) -> None:
        """
        If specified config file doesn't exist, FileNotFoundError is raised.
        """
        import pytest

        cli = CLISource(
            args=["--config-file", "nonexistent.toml"],
            invocation_dir=tmp_path,
        )
        files = ConfigFileDiscoverySource(
            invocation_dir=tmp_path,
            cli_source=cli,
        )
        manager = ConfigManager(sources=[cli, files])

        with pytest.raises(FileNotFoundError, match="nonexistent.toml"):
            manager.register_fragment_type(PytestConfig)


class TestAddoptsCombination:
    """
    Test that addopts from different sources can be combined.

    In pytest, PYTEST_ADDOPTS is prepended to addopts from config file.
    This tests shows how different sources can provide values that
    need to be merged (not just overridden).
    """

    def test_env_and_file_addopts_both_available(self, tmp_path: Path) -> None:
        """
        Both env and file provide addopts - higher precedence wins.

        Note: This test shows override behavior. For actual combination
        (like pytest's prepending), a custom merge strategy would be needed.
        """
        config_file = tmp_path / "pytest.toml"
        config_file.write_text(
            dedent("""
            [pytest]
            addopts = "-v --tb=short"
        """)
        )

        env = {
            "PYTEST_ADDOPTS": "-x --pdb",
        }

        cli = CLISource(
            args=["--config-file", "pytest.toml"],
            invocation_dir=tmp_path,
        )
        files = ConfigFileDiscoverySource(
            invocation_dir=tmp_path,
            cli_source=cli,
        )
        manager = ConfigManager(sources=[cli, files])
        manager.add_source(EnvSource(environ=env, precedence=20))

        config = manager.register_fragment_type(PytestConfig)

        # With current override semantics, env wins completely
        assert config.addopts == "-x --pdb"

    def test_only_file_addopts(self, tmp_path: Path) -> None:
        """
        Only file provides addopts - file value is used.
        """
        config_file = tmp_path / "pytest.toml"
        config_file.write_text(
            dedent("""
            [pytest]
            addopts = "-v --tb=short"
        """)
        )

        cli = CLISource(
            args=["--config-file", "pytest.toml"],
            invocation_dir=tmp_path,
        )
        files = ConfigFileDiscoverySource(
            invocation_dir=tmp_path,
            cli_source=cli,
        )
        manager = ConfigManager(sources=[cli, files])

        config = manager.register_fragment_type(PytestConfig)

        assert config.addopts == "-v --tb=short"

    def test_only_env_addopts(self, tmp_path: Path) -> None:
        """
        Only env provides addopts - env value is used.
        """
        env = {
            "PYTEST_ADDOPTS": "-x --pdb",
        }

        cli = CLISource(args=[], invocation_dir=tmp_path)
        manager = ConfigManager(sources=[cli])
        manager.add_source(EnvSource(environ=env, precedence=20))

        config = manager.register_fragment_type(PytestConfig)

        assert config.addopts == "-x --pdb"

    def test_cli_overrides_all(self, tmp_path: Path) -> None:
        """
        CLI args override both env and file.
        """
        config_file = tmp_path / "pytest.toml"
        config_file.write_text(
            dedent("""
            [pytest]
            addopts = "-v"
        """)
        )

        env = {
            "PYTEST_ADDOPTS": "-x",
        }

        cli = CLISource(
            args=["--config-file", "pytest.toml", "--addopts=--pdb"],
            invocation_dir=tmp_path,
        )
        files = ConfigFileDiscoverySource(
            invocation_dir=tmp_path,
            cli_source=cli,
        )
        manager = ConfigManager(sources=[cli, files])
        manager.add_source(EnvSource(environ=env, precedence=20))

        config = manager.register_fragment_type(PytestConfig)

        # CLI wins
        assert config.addopts == "--pdb"


class TestAddoptsPropagation:
    """
    Test that addopts from config file/env are re-parsed as CLI args.

    When addopts contains options like "-v --tb=short", these should be
    parsed and applied to the config (with appropriate precedence).

    Bootstrap-only fields (like config_file) should NOT be settable via
    addopts - they're already processed by the time addopts is loaded.
    """

    def test_addopts_from_file_sets_verbose(self, tmp_path: Path) -> None:
        """
        addopts from config file propagates to config fields.

        Config file has addopts="--verbose", which should set verbose=True.
        """
        config_file = tmp_path / "pytest.toml"
        config_file.write_text(
            dedent("""
            [pytest]
            addopts = "--verbose"
        """)
        )

        cli = CLISource(
            args=["--config-file", "pytest.toml"],
            invocation_dir=tmp_path,
        )
        files = ConfigFileDiscoverySource(
            invocation_dir=tmp_path,
            cli_source=cli,
        )
        manager = ConfigManager(sources=[cli, files])
        config = manager.register_fragment_type(PytestConfigWithVerbose)

        assert config.verbose is True
        assert config.addopts == "--verbose"

    def test_addopts_from_env_sets_verbose(self, tmp_path: Path) -> None:
        """
        addopts from environment propagates to config fields.
        """
        env = {
            "PYTEST_ADDOPTS": "--verbose",
        }

        cli = CLISource(args=[], invocation_dir=tmp_path)
        manager = ConfigManager(sources=[cli])
        manager.add_source(EnvSource(environ=env, precedence=20))
        config = manager.register_fragment_type(PytestConfigWithVerbose)

        assert config.verbose is True

    def test_cli_verbose_overrides_addopts(self, tmp_path: Path) -> None:
        """
        Explicit CLI arg overrides addopts value.

        Even if addopts has --verbose, explicit --no-verbose (if supported) or
        absence of --verbose on CLI should win based on precedence.
        """
        config_file = tmp_path / "pytest.toml"
        config_file.write_text(
            dedent("""
            [pytest]
            addopts = "--verbose"
        """)
        )

        # CLI explicitly sets verbose=False (no -v flag)
        cli = CLISource(
            args=["--config-file", "pytest.toml"],  # no --verbose
            invocation_dir=tmp_path,
        )
        files = ConfigFileDiscoverySource(
            invocation_dir=tmp_path,
            cli_source=cli,
        )
        manager = ConfigManager(sources=[cli, files])
        config = manager.register_fragment_type(PytestConfigWithVerbose)

        # addopts -v sets it to True (since CLI didn't explicitly set it)
        assert config.verbose is True

    def test_config_file_in_addopts_raises_error(self, tmp_path: Path) -> None:
        """
        Specifying --config-file in addopts should raise an error.

        The config file has already been processed by the time addopts is
        loaded, so it's too late to specify a different config file.
        """
        import pytest

        config_file = tmp_path / "pytest.toml"
        config_file.write_text(
            dedent("""
            [pytest]
            addopts = "--config-file other.toml"
        """)
        )

        cli = CLISource(
            args=["--config-file", "pytest.toml"],
            invocation_dir=tmp_path,
        )
        files = ConfigFileDiscoverySource(
            invocation_dir=tmp_path,
            cli_source=cli,
        )
        manager = ConfigManager(sources=[cli, files])

        with pytest.raises(ValueError, match="config.file.*addopts|bootstrap"):
            manager.register_fragment_type(PytestConfigWithVerbose)

    def test_multiple_addopts_options_propagate(self, tmp_path: Path) -> None:
        """
        Multiple options in addopts all propagate.
        """
        config_file = tmp_path / "pytest.toml"
        config_file.write_text(
            dedent("""
            [pytest]
            addopts = "--verbose --tb=short"
        """)
        )

        cli = CLISource(
            args=["--config-file", "pytest.toml"],
            invocation_dir=tmp_path,
        )
        files = ConfigFileDiscoverySource(
            invocation_dir=tmp_path,
            cli_source=cli,
        )
        manager = ConfigManager(sources=[cli, files])
        config = manager.register_fragment_type(PytestConfigWithVerbose)

        assert config.verbose is True
        assert config.tb == "short"


# Extended PytestConfig with verbose flag for addopts propagation tests
class PytestConfigWithVerbose(ConfigPart, prefix="pytest"):
    """PytestConfig extended with verbose and tb fields for addopts tests."""

    # bootstrap_only: can only be set via CLI, not via addopts
    config_file: Annotated[str | None, config_source, bootstrap_only] = None
    # addopts_field: value is re-parsed as CLI args
    addopts: Annotated[str, addopts_field] = ""
    testpaths: str = "tests"
    verbose: bool = False
    tb: str = "auto"


class TestShortOptions:
    """Test short CLI options via annotations."""

    def test_short_option_boolean_flag(self, tmp_path: Path) -> None:
        """Short option -v sets verbose=True."""

        class VerboseConfig(ConfigPart, prefix="test"):
            verbose: Annotated[bool, short("v")] = False
            quiet: Annotated[bool, short("q")] = False

        cli = CLISource(args=["-v"], invocation_dir=tmp_path)
        manager = ConfigManager(sources=[cli])
        config = manager.register_fragment_type(VerboseConfig)

        assert config.verbose is True
        assert config.quiet is False

    def test_short_option_with_value(self, tmp_path: Path) -> None:
        """Short option -c sets config_file."""

        class FileConfig(ConfigPart, prefix="test"):
            config_file: Annotated[str | None, short("c")] = None

        cli = CLISource(args=["-c", "custom.toml"], invocation_dir=tmp_path)
        manager = ConfigManager(sources=[cli])
        config = manager.register_fragment_type(FileConfig)

        assert config.config_file == "custom.toml"

    def test_combined_short_options(self, tmp_path: Path) -> None:
        """Combined short options -vq sets both flags."""

        class FlagsConfig(ConfigPart, prefix="test"):
            verbose: Annotated[bool, short("v")] = False
            quiet: Annotated[bool, short("q")] = False
            debug: Annotated[bool, short("d")] = False

        cli = CLISource(args=["-vq"], invocation_dir=tmp_path)
        manager = ConfigManager(sources=[cli])
        config = manager.register_fragment_type(FlagsConfig)

        assert config.verbose is True
        assert config.quiet is True
        assert config.debug is False

    def test_short_and_long_options_together(self, tmp_path: Path) -> None:
        """Both short and long options work for same field."""

        class MixedConfig(ConfigPart, prefix="test"):
            verbose: Annotated[bool, short("v")] = False

        # Test short option
        cli1 = CLISource(args=["-v"], invocation_dir=tmp_path)
        manager1 = ConfigManager(sources=[cli1])
        config1 = manager1.register_fragment_type(MixedConfig)
        assert config1.verbose is True

        # Test long option
        cli2 = CLISource(args=["--verbose"], invocation_dir=tmp_path)
        manager2 = ConfigManager(sources=[cli2])
        config2 = manager2.register_fragment_type(MixedConfig)
        assert config2.verbose is True
