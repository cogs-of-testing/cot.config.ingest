"""
Acceptance test for bootstrap workflow.

This test demonstrates the complete bootstrap flow where:
1. ConfigManager is created with invocation_dir and CLI args
2. ConfigPart fields marked with config_source are auto-discovered as sources
3. Configuration is loaded with proper precedence (CLI > env > file > defaults)

This mirrors how pytest discovers pytest.ini/pyproject.toml based on
invocation directory and CLI args, and how addopts from different sources combine.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Annotated

from cot.config import (
    ConfigManager,
    ConfigPart,
    EnvSource,
    config_source,
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

        # ConfigManager with CLI args - config_source marker auto-adds the file
        manager = ConfigManager(
            invocation_dir=tmp_path,
            args=["--config-file", "custom.toml"],
        )
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

        manager = ConfigManager(
            invocation_dir=tmp_path,
            args=["--config-file", "pytest.toml"],
        )
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
        manager = ConfigManager(
            invocation_dir=tmp_path,
            args=[],
        )
        config = manager.register_fragment_type(PytestConfig)

        assert config.config_file is None
        assert config.addopts == ""
        assert config.testpaths == "tests"

    def test_nonexistent_config_file_raises_error(self, tmp_path: Path) -> None:
        """
        If specified config file doesn't exist, FileNotFoundError is raised.
        """
        import pytest

        manager = ConfigManager(
            invocation_dir=tmp_path,
            args=["--config-file", "nonexistent.toml"],
        )

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

        manager = ConfigManager(
            invocation_dir=tmp_path,
            args=["--config-file", "pytest.toml"],
        )
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

        manager = ConfigManager(
            invocation_dir=tmp_path,
            args=["--config-file", "pytest.toml"],
        )

        config = manager.register_fragment_type(PytestConfig)

        assert config.addopts == "-v --tb=short"

    def test_only_env_addopts(self, tmp_path: Path) -> None:
        """
        Only env provides addopts - env value is used.
        """
        env = {
            "PYTEST_ADDOPTS": "-x --pdb",
        }

        manager = ConfigManager(
            invocation_dir=tmp_path,
            args=[],
        )
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

        manager = ConfigManager(
            invocation_dir=tmp_path,
            args=["--config-file", "pytest.toml", "--addopts=--pdb"],
        )
        manager.add_source(EnvSource(environ=env, precedence=20))

        config = manager.register_fragment_type(PytestConfig)

        # CLI wins
        assert config.addopts == "--pdb"
