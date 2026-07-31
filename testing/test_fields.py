"""Tests for the field model in `cot.config._fields`.

The field model is the single place that knows what a ConfigPart's fields are,
what they are annotated with, and what they default to. Everything else reads
it, so it gets tested directly rather than only through the manager.
"""

from __future__ import annotations

from typing import Annotated

from cot.config import ConfigPart, SubConfig, addopts_field, from_parent, help, short
from cot.config._annotations import (
    AddoptsMarker,
    FromParentMarker,
    HelpMarker,
    ShortMarker,
)
from cot.config._fields import (
    MISSING,
    field_defaults,
    fields_of,
    has_marker,
    is_sub_config,
    leaf_fields,
    marker_of,
    unwrap_type,
)


class Inner(SubConfig):
    level: Annotated[str, from_parent] = "WARNING"
    enabled: bool = False


class Outer(ConfigPart, prefix="app"):
    level: str = "INFO"
    verbose: Annotated[bool, short("v"), help("be loud")] = False
    required_field: str
    inner: Inner


class TestUnwrapType:
    def test_plain_type(self) -> None:
        assert unwrap_type(str) is str

    def test_annotated(self) -> None:
        assert unwrap_type(Annotated[int, from_parent]) is int

    def test_optional(self) -> None:
        assert unwrap_type(str | None) is str

    def test_annotated_optional(self) -> None:
        assert unwrap_type(Annotated[str | None, from_parent]) is str


class TestFieldsOf:
    def test_flat_walk_excludes_nested(self) -> None:
        names = [f.name for f in fields_of(Outer, recurse=False)]
        assert names == ["level", "verbose", "required_field", "inner"]

    def test_recursive_walk_includes_nested_paths(self) -> None:
        paths = [f.dotted for f in fields_of(Outer)]
        assert paths == [
            "level",
            "verbose",
            "required_field",
            "inner",
            "inner.level",
            "inner.enabled",
        ]

    def test_leaf_fields_drops_subconfig_containers(self) -> None:
        assert [f.dotted for f in leaf_fields(Outer)] == [
            "level",
            "verbose",
            "required_field",
            "inner.level",
            "inner.enabled",
        ]

    def test_inherited_fields_come_first(self) -> None:
        class Base(SubConfig):
            a: int = 1

        class Derived(Base):
            b: int = 2

        assert [f.name for f in fields_of(Derived)] == ["a", "b"]

    def test_defaults_and_required(self) -> None:
        by_name = {f.name: f for f in fields_of(Outer, recurse=False)}
        assert by_name["level"].default == "INFO"
        assert by_name["required_field"].default is MISSING
        assert by_name["required_field"].required is True
        assert by_name["level"].required is False

    def test_subconfig_field_is_not_required(self) -> None:
        # The manager builds sub-configs; they are not caller-supplied.
        by_name = {f.name: f for f in fields_of(Outer, recurse=False)}
        assert by_name["inner"].is_sub_config is True
        assert by_name["inner"].required is False

    def test_owner_is_the_declaring_class(self) -> None:
        by_name = {f.name: f for f in fields_of(Outer, recurse=False)}
        assert by_name["level"].owner is Outer

    def test_results_are_cached(self) -> None:
        assert fields_of(Outer) is fields_of(Outer)

    def test_private_names_are_skipped(self) -> None:
        class WithPrivate(SubConfig):
            visible: int = 1
            _hidden: int = 2

        assert [f.name for f in fields_of(WithPrivate)] == ["visible"]


class TestMarkers:
    def test_marker_of_returns_the_instance(self) -> None:
        by_name = {f.name: f for f in fields_of(Outer, recurse=False)}
        marker = marker_of(by_name["verbose"], ShortMarker)
        assert marker is not None
        assert marker.char == "v"

    def test_multiple_markers_on_one_field(self) -> None:
        by_name = {f.name: f for f in fields_of(Outer, recurse=False)}
        verbose = by_name["verbose"]
        assert has_marker(verbose, ShortMarker)
        help_marker = marker_of(verbose, HelpMarker)
        assert help_marker is not None
        assert help_marker.help == "be loud"

    def test_marker_absent(self) -> None:
        by_name = {f.name: f for f in fields_of(Outer, recurse=False)}
        assert marker_of(by_name["level"], ShortMarker) is None
        assert has_marker(by_name["level"], FromParentMarker) is False

    def test_nested_field_keeps_its_markers(self) -> None:
        by_path = {f.dotted: f for f in fields_of(Outer)}
        assert has_marker(by_path["inner.level"], FromParentMarker)

    def test_marker_via_matmul_syntax(self) -> None:
        class WithMatmul(SubConfig):
            value: str @ from_parent = "x"  # type: ignore[valid-type]

        by_name = {f.name: f for f in fields_of(WithMatmul)}
        assert has_marker(by_name["value"], FromParentMarker)

    def test_addopts_marker_carries_precedence(self) -> None:
        class WithAddopts(ConfigPart):
            addopts: Annotated[str, addopts_field] = ""

        by_name = {f.name: f for f in fields_of(WithAddopts)}
        marker = marker_of(by_name["addopts"], AddoptsMarker)
        assert marker is not None
        assert marker.precedence == 18


class TestFieldDefaults:
    def test_only_fields_with_defaults(self) -> None:
        assert field_defaults(Outer) == {"level": "INFO", "verbose": False}

    def test_inherited_default_is_included(self) -> None:
        class Base(SubConfig):
            a: int = 1

        class Derived(Base):
            b: int = 2

        assert field_defaults(Derived) == {"a": 1, "b": 2}

    def test_override_in_subclass_wins(self) -> None:
        class Base(SubConfig):
            a: int = 1

        class Derived(Base):
            a: int = 99

        assert field_defaults(Derived) == {"a": 99}


class TestIsSubConfig:
    def test_true_for_subconfig(self) -> None:
        assert is_sub_config(Inner)

    def test_false_for_configpart_and_scalars(self) -> None:
        assert not is_sub_config(Outer)
        assert not is_sub_config(str)
        assert not is_sub_config("not a type")


class TestRecursionGuard:
    def test_self_referential_subconfig_terminates(self) -> None:
        class Node(SubConfig):
            name: str = ""

        # Attach the self-reference after class creation so the annotation
        # resolves; a direct forward reference would need the module globals.
        Node.__annotations__["child"] = Node

        # The repeated sub-config field is still reported, but not descended
        # into a second time -- otherwise this never terminates.
        paths = [f.dotted for f in fields_of(Node)]
        assert paths == ["name", "child", "child.name", "child.child"]
