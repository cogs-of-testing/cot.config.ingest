"""Tests for the forward name derivation in `cot.config._names`.

One declaration, four spellings. This is the table `docs/design/names.md`
states, executed: a field's qualified path rendered flat, as a CLI option, as
an environment variable and as a table-and-key, for a root with both class
keywords, a root with neither, and the overrides that redirect a leaf.
"""

from __future__ import annotations

from typing import Annotated

import pytest

from cot.config import ConfigPart, named
from cot.config._fields import fields_of
from cot.config._names import FieldNames, names_of, qualified_path


class Pool(ConfigPart):
    size: int = 5


class Database(ConfigPart, prefix="app", name_prefix="db"):
    host: str = "localhost"
    pool: Pool


class LogFile(ConfigPart):
    # Structurally `file.path`; pytest calls it `log_file`.
    path: Annotated[str | None, named("log_file")] = None


class Logging(ConfigPart, prefix="pytest", name_prefix="log"):
    level: str = "WARNING"
    file: LogFile


class Bare(ConfigPart):
    """A root with no class keywords: no section, no leading segment."""

    host: str = "localhost"
    pool: Pool


def names_for(part: type[ConfigPart], dotted: str) -> FieldNames:
    field = next(f for f in fields_of(part) if f.dotted == dotted)
    return names_of(part, field)


class TestQualifiedPath:
    def test_name_prefix_is_a_segment(self) -> None:
        field = next(f for f in fields_of(Database) if f.dotted == "pool.size")
        assert qualified_path(Database, field) == ("db", "pool", "size")

    def test_no_name_prefix_leaves_the_path_alone(self) -> None:
        field = next(f for f in fields_of(Bare) if f.dotted == "pool.size")
        assert qualified_path(Bare, field) == ("pool", "size")


class TestTheFourSpellings:
    @pytest.mark.parametrize(
        ("dotted", "flat", "cli", "env", "section", "table", "key"),
        [
            ("host", "db_host", "db-host", "APP_DB_HOST", "app", ("db",), "host"),
            (
                "pool.size",
                "db_pool_size",
                "db-pool-size",
                "APP_DB_POOL_SIZE",
                "app",
                ("db", "pool"),
                "size",
            ),
        ],
    )
    def test_a_root_with_both_keywords(
        self,
        dotted: str,
        flat: str,
        cli: str,
        env: str,
        section: str,
        table: tuple[str, ...],
        key: str,
    ) -> None:
        names = names_for(Database, dotted)
        assert names.flat == flat
        assert names.cli == cli
        assert names.env == env
        assert names.nested.section == section
        assert names.nested.table == table
        assert names.nested.key == key

    def test_a_root_with_neither_keyword(self) -> None:
        names = names_for(Bare, "pool.size")
        assert names.flat == "pool_size"
        assert names.cli == "pool-size"
        assert names.env == "POOL_SIZE"
        assert names.nested.section is None
        assert names.nested.dotted == "pool.size"


class TestTheStressCase:
    """pytest's logging options, which is what the yardstick declares."""

    @pytest.mark.parametrize(
        ("dotted", "flat", "cli", "env", "nested"),
        [
            ("level", "log_level", "log-level", "PYTEST_LOG_LEVEL", "pytest.log.level"),
            (
                "file.path",
                "log_file",
                "log-file",
                "PYTEST_LOG_FILE",
                "pytest.log.file.path",
            ),
        ],
    )
    def test_each_spelling_is_pytests_own(
        self, dotted: str, flat: str, cli: str, env: str, nested: str
    ) -> None:
        names = names_for(Logging, dotted)
        assert names.flat == flat
        assert names.cli == cli
        assert names.env == env
        assert names.nested.dotted == nested


class TestNamedOverride:
    def test_it_replaces_the_flat_name_and_redrives_the_rest(self) -> None:
        names = names_for(Logging, "file.path")
        # log_file_path would be the derived name; named() replaces it, and the
        # CLI and environment spellings follow it rather than the path.
        assert (names.flat, names.cli, names.env) == (
            "log_file",
            "log-file",
            "PYTEST_LOG_FILE",
        )

    def test_it_does_not_move_the_nested_spelling(self) -> None:
        names = names_for(Logging, "file.path")
        assert names.nested.table == ("log", "file")
        assert names.nested.key == "path"


class TestNestedFieldsGetNamesToo:
    """A nested part is itself addressable: TomlEnvSource reads a whole table."""

    def test_the_section_field_has_its_own_spellings(self) -> None:
        names = names_for(Database, "pool")
        assert names.flat == "db_pool"
        assert names.env == "APP_DB_POOL"
