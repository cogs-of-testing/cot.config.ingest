"""The documentation home page's code has to be code.

`docs/index.md` is the usage walkthrough. It shows a declaration, a config
file, a provenance table and help output, and every one of them is checked
here against what the library produces, so the page cannot describe a library
that does not exist. `test_readme.py` does the same for the README.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from cot.config import CLISource, ConfigManager, EnvSource, TomlSource

DOCS_INDEX = Path(__file__).parent.parent / "docs" / "index.md"

FENCED_BLOCK = re.compile(r"```(\w*)\s*\n(.*?)```", re.S)


def blocks(language: str) -> list[str]:
    text = DOCS_INDEX.read_text(encoding="utf-8")
    return [body for lang, body in FENCED_BLOCK.findall(text) if lang == language]


@pytest.mark.parametrize("index", range(len(blocks("python"))))
def test_every_python_block_parses(index: int) -> None:
    ast.parse(blocks("python")[index])


@pytest.fixture
def walkthrough(tmp_path: Path) -> tuple[ConfigManager, type[Any], Path]:
    """The page's declaration, config file, environment and argv, for real."""
    declaration = next(b for b in blocks("python") if "class DatabaseConfig" in b)
    module = ModuleType("docs_index_example")
    sys.modules[module.__name__] = module
    try:
        exec(compile(declaration, "<docs/index.md>", "exec"), module.__dict__)  # noqa: S102
        part = module.__dict__["DatabaseConfig"]

        config_file = tmp_path / "app.toml"
        config_file.write_text(blocks("toml")[0])
        manager = ConfigManager(
            sources=[
                TomlSource(config_file),
                EnvSource(environ={"APP_DB_TIMEOUT": "2.5"}),
                CLISource(["--db-pool-size", "8"]),
            ]
        )
        manager.declare(part)
        manager.resolve()
    finally:
        del sys.modules[module.__name__]
    return manager, part, config_file


def test_the_values_the_page_claims(
    walkthrough: tuple[ConfigManager, type[Any], Path],
) -> None:
    manager, part, _ = walkthrough
    config = manager.get(part)

    assert config.host == "db.internal"
    assert config.pool.size == 8
    assert config.pool.timeout == 2.5  # the from_parent cascade

    origin = manager.origin_of(part, "pool.timeout")
    assert origin.kind == "env"
    assert origin.location == "inherited from timeout (APP_DB_TIMEOUT)"
    assert origin.precedence == 20


def test_the_explain_table_is_the_real_one(
    walkthrough: tuple[ConfigManager, type[Any], Path],
) -> None:
    manager, part, config_file = walkthrough
    shown = next(b for b in blocks("") if b.startswith("DatabaseConfig:"))

    actual = manager.explain(part).replace(str(config_file), "app.toml")
    assert actual.strip() == shown.strip()


def test_the_help_output_is_the_real_one(
    walkthrough: tuple[ConfigManager, type[Any], Path],
) -> None:
    manager, _, _ = walkthrough
    shown = next(b for b in blocks("") if b.startswith("usage: app"))

    assert manager.format_help(prog="app").strip() == shown.strip()


def test_the_page_documents_the_pytest_patching() -> None:
    text = DOCS_INDEX.read_text(encoding="utf-8").lower()

    assert "monkeypatches pytest" in text
    assert "-p no:cot_config" in text
    assert "installing this package" in text
