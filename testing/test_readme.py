"""The README's code has to be code.

The README shipped a "proposed API" example for a long time after that API was
built differently -- it referenced names that never existed and did not even
parse. It is also the PyPI long description, so it is the first thing anyone
sees. These tests make it break the build instead of quietly rotting.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

README = Path(__file__).parent.parent / "README.md"

PYTHON_BLOCK = re.compile(r"```python\s*\n(.*?)```", re.S)


def python_blocks() -> list[str]:
    return PYTHON_BLOCK.findall(README.read_text(encoding="utf-8"))


def test_readme_exists() -> None:
    assert README.is_file(), "README.md is the PyPI long description"


@pytest.mark.parametrize("index", range(len(python_blocks())))
def test_every_python_block_parses(index: int) -> None:
    """Every ```python block is syntactically valid Python."""
    ast.parse(python_blocks()[index])


def test_the_declaration_example_actually_works() -> None:
    """The headline example declares, resolves and cascades for real.

    Parsing is not enough: the old README parsed in places while importing
    names that had never existed.
    """
    from cot.config import CLISource, ConfigManager, EnvSource

    declaration = next(b for b in python_blocks() if "class LoggingConfig" in b)

    # Executed as a real module: `get_type_hints` resolves a class's annotations
    # against `sys.modules[cls.__module__]`, so a bare dict namespace would
    # leave `cli: LogCliConfig` unresolvable.
    module = ModuleType("readme_example")
    module.DEFAULT_LOG_FORMAT = "%(levelname)s %(message)s"  # type: ignore[attr-defined]
    module.DEFAULT_LOG_DATE_FORMAT = "%H:%M:%S"  # type: ignore[attr-defined]

    # The module has to stay registered for the whole test: annotations are
    # resolved lazily, when the manager first walks the fields.
    sys.modules[module.__name__] = module
    try:
        exec(compile(declaration, "<README.md>", "exec"), module.__dict__)  # noqa: S102
        logging_config = module.__dict__["LoggingConfig"]

        manager = ConfigManager(
            sources=[
                EnvSource(environ={"PYTEST_LOG_LEVEL": "DEBUG"}),
                CLISource(["--log-file", "out.log"]),
            ]
        )
        manager.declare(logging_config)
        config = manager.get(logging_config)
    finally:
        del sys.modules[module.__name__]

    assert config.level == "DEBUG"
    assert config.cli.level == "DEBUG"  # the from_parent cascade the README claims
    assert config.file.path == "out.log"  # named("log_file") reaching file.path


def test_readme_shows_the_binding_and_the_old_patch() -> None:
    """The README shows the functions, and warns 0.1.0 users about the patch.

    0.1.0 patched pytest on install, which affected environments its users
    never meant to change; that is the one thing they cannot discover from the
    new API surface (P1).
    """
    text = README.read_text(encoding="utf-8")

    assert "from cot.config.pytest_binding import add_config" in text
    assert "0.1.0 patched pytest" in text
    assert "parser.add_config" not in text
