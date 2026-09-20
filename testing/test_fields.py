"""Tests for the field model in `cot.config._fields`.

The field model is the single place that knows what a ConfigPart's fields are,
what they are annotated with, and what they default to. Everything else reads
it, so it gets tested directly rather than only through the manager.
"""

from __future__ import annotations

from typing import Annotated

import pytest

from cot.config import (
    ConfigDeclarationError,
    ConfigPart,
    from_parent,
    help,
    injected_args,
    short,
)
from cot.config._annotations import (
    FromParentMarker,
    HelpMarker,
    InjectedArgsMarker,
    ShortMarker,
)
from cot.config._fields import (
    MISSING,
    check_declaration,
    declared_type,
    field_defaults,
    fields_of,
    has_marker,
    is_nested_type,
    leaf_fields,
    marker_of,
    misbound_markers,
    unwrap_type,
)


class Inner(ConfigPart):
    level: Annotated[str, from_parent] = "WARNING"
    enabled: bool = False


class Outer(ConfigPart, prefix="app"):
    level: str = "INFO"
    verbose: Annotated[bool, short("v"), help("be loud")] = False
    required_field: str
    inner: Inner


class PrefixedSection(ConfigPart, prefix="nope"):
    """A part carrying a root keyword, used below as someone else's section."""

    value: int = 1


class RootWithPrefixedSection(ConfigPart, prefix="app"):
    section: PrefixedSection


class PlainSection(ConfigPart):
    value: int = 1


class RootWithEveryKeyword(ConfigPart, prefix="app", name_prefix="db", from_env=True):
    inner: PlainSection


class InheritingSection(PrefixedSection):
    """Carries `prefix` only by inheritance, so it made no claim of its own."""

    other: int = 2


class RootWithInheritingSection(ConfigPart, prefix="app"):
    section: InheritingSection


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
        class Base(ConfigPart):
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
        assert by_name["inner"].is_nested is True
        assert by_name["inner"].required is False

    def test_owner_is_the_declaring_class(self) -> None:
        by_name = {f.name: f for f in fields_of(Outer, recurse=False)}
        assert by_name["level"].owner is Outer

    def test_results_are_cached(self) -> None:
        assert fields_of(Outer) is fields_of(Outer)

    def test_private_names_are_skipped(self) -> None:
        class WithPrivate(ConfigPart):
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
        class WithMatmul(ConfigPart):
            value: str @ from_parent = "x"  # type: ignore[valid-type]

        by_name = {f.name: f for f in fields_of(WithMatmul)}
        assert has_marker(by_name["value"], FromParentMarker)

    def test_addopts_marker_carries_precedence(self) -> None:
        class WithAddopts(ConfigPart):
            addopts: Annotated[str, injected_args] = ""

        by_name = {f.name: f for f in fields_of(WithAddopts)}
        marker = marker_of(by_name["addopts"], InjectedArgsMarker)
        assert marker is not None
        assert marker.precedence == 18


class TestFieldDefaults:
    def test_only_fields_with_defaults(self) -> None:
        assert field_defaults(Outer) == {"level": "INFO", "verbose": False}

    def test_inherited_default_is_included(self) -> None:
        class Base(ConfigPart):
            a: int = 1

        class Derived(Base):
            b: int = 2

        assert field_defaults(Derived) == {"a": 1, "b": 2}

    def test_override_in_subclass_wins(self) -> None:
        class Base(ConfigPart):
            a: int = 1

        class Derived(Base):
            a: int = 99

        assert field_defaults(Derived) == {"a": 99}


class TestIsNestedType:
    """Any ConfigPart can be nested; nothing else can (D30)."""

    def test_true_for_any_config_part(self) -> None:
        # Outer carries root keywords and is still nestable: a class has no
        # position of its own, only the declaration it appears in has one.
        assert is_nested_type(Inner)
        assert is_nested_type(Outer)

    def test_false_for_anything_else(self) -> None:
        assert not is_nested_type(str)
        assert not is_nested_type("not a type")


class TestRecursionGuard:
    def test_self_referential_subconfig_terminates(self) -> None:
        class Node(ConfigPart):
            name: str = ""

        # Attach the self-reference after class creation so the annotation
        # resolves; a direct forward reference would need the module globals.
        Node.__annotations__["child"] = Node

        # The repeated sub-config field is still reported, but not descended
        # into a second time -- otherwise this never terminates.
        paths = [f.dotted for f in fields_of(Node)]
        assert paths == ["name", "child", "child.name", "child.child"]


class TestDeclaredType:
    """`Optional` is absence, so it collapses; a real union is kept whole."""

    def test_optional_collapses_to_its_one_member(self) -> None:
        assert declared_type(str | None) is str
        assert declared_type(Annotated[str | None, from_parent]) is str

    def test_a_multi_member_union_survives(self) -> None:
        # bool | int | None is pytest's log_auto_indent. Collapsing it to bool
        # would make "4" into True; which member wins is conversion's question.
        assert declared_type(bool | int | None) == (bool | int)

    def test_a_plain_type_is_itself(self) -> None:
        assert declared_type(int) is int


class TestMisboundMarkers:
    """`@` binds tighter than `|`, so a marker can land on a union member (D31)."""

    def test_a_marker_on_the_field_is_fine(self) -> None:
        assert misbound_markers(Annotated[str | None, from_parent]) == ()

    def test_a_marker_on_a_member_is_found(self) -> None:
        misbound = misbound_markers(str | Annotated[None, from_parent])
        assert misbound == (from_parent,)

    def test_a_foreign_annotation_is_not_ours_to_judge(self) -> None:
        assert misbound_markers(str | Annotated[None, "some other library"]) == ()


class TestCheckDeclaration:
    def test_a_well_formed_root_passes(self) -> None:
        check_declaration(Outer)

    def test_a_marker_bound_to_a_union_member_is_refused(self) -> None:
        class Broken(ConfigPart):
            level: str | Annotated[None, from_parent] = None

        with pytest.raises(ConfigDeclarationError) as excinfo:
            check_declaration(Broken)

        message = str(excinfo.value)
        assert "Broken.level" in message
        assert "binds tighter" in message

    def test_a_nested_part_may_not_carry_a_root_keyword(self) -> None:
        with pytest.raises(ConfigDeclarationError) as excinfo:
            check_declaration(RootWithPrefixedSection)

        message = str(excinfo.value)
        assert "RootWithPrefixedSection.section" in message
        assert "prefix" in message

    def test_the_root_itself_may_carry_them(self) -> None:
        check_declaration(RootWithEveryKeyword)

    def test_an_inherited_keyword_is_not_the_nested_class_making_a_claim(self) -> None:
        check_declaration(RootWithInheritingSection)
