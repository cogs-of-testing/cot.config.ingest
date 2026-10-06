"""What an option is, as data, in the library's own vocabulary.

A :class:`FieldSpec` is a pure function of a root: no parser, no host, no I/O.
It is what a binding binds, what the spelling index is built from, what help
renders, and what a conformance suite compares. Every spelling in it is
answerable from the class alone, which is why environment exposure is a marker
on the field rather than a policy on a source, and why the environment spelling
stops short of the source's own prefix.

Almost everything is derived from the annotation. A marker is added only where
nothing can be inferred: a second option spelling, a legacy name, a constant,
and whether occurrences are counted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, get_args, get_origin

from ._annotations import (
    CountedMarker,
    EnvNamedMarker,
    FormerlyMarker,
    FormMarker,
    FromEnvMarker,
    HelpMarker,
    NoCLIMarker,
    NoIniMarker,
    ShortMarker,
)
from ._bases import part_from_env, part_name_prefix, part_prefix
from ._fields import (
    MISSING,
    FieldInfo,
    fields_of,
    has_marker,
    marker_of,
    strip_annotated,
    union_members,
)
from ._names import names_of

if TYPE_CHECKING:
    from ._bases import ConfigPart


@dataclass(frozen=True)
class CliForm:
    """One command-line spelling of a field."""

    long: str | None
    """``--log-cli-level``, or None for a short-only form."""

    short: str | None
    """``-v``, or None."""

    negative: str | None
    """``--no-verbose``; every boolean form has one."""

    flag: bool
    """Presence alone carries the value."""

    contributes: Any = MISSING
    """The constant this form supplies, or MISSING if it takes a value."""


@dataclass(frozen=True)
class EnvSpelling:
    """A field's environment variable, before any source prefix."""

    name: str
    """``PYTEST_LOG_CLI_LEVEL``, or ``SOURCE_DATE_EPOCH``."""

    absolute: bool
    """From ``env_named()``: the source adds no prefix of its own."""


@dataclass(frozen=True)
class FieldSpec:
    """Everything a source or a host needs to know about one field."""

    path: tuple[str, ...]
    flat: str
    file_key: str | None
    env: EnvSpelling | None
    cli: tuple[CliForm, ...]
    annotation: Any
    default: Any

    repeatable: bool
    """Each occurrence accumulates: the field is a list."""

    optional: bool
    """Absence is meaningful: None is one of the declared members."""

    counts: bool
    """Occurrences of any form are summed."""

    values: tuple[Any, ...] | None
    """A closed set, from Literal or Enum."""

    aliases: tuple[str, ...]
    help: str
    group: str

    def comparable(self) -> FieldSpec:
        """This spec reduced to what two roots must agree on to share a spelling.

        Path is cleared because adoption is precisely about two paths behind
        one name. Group is cleared because it is derived from the root's own
        naming, so two roots can never agree on it, and adoption between two
        roots is the only case this comparison exists for.
        """
        return replace(self, path=(), group="")


def _closed_values(declared: Any) -> tuple[Any, ...] | None:
    """The permitted values of a Literal or an Enum, if the type is closed."""
    if get_origin(declared) is Literal:
        return get_args(declared)
    if isinstance(declared, type) and issubclass(declared, Enum):
        return tuple(member.value for member in declared)
    return None


def _is_optional(annotation: Any) -> bool:
    members = union_members(strip_annotated(annotation))
    return members is not None and type(None) in members


def _is_repeatable(declared: Any) -> bool:
    return get_origin(declared) is list


def _group_of(root: type[ConfigPart]) -> str:
    """The group a root's options are rendered under.

    Derived from the root's own naming. Whether a host's hand-written group
    descriptions come from here instead is that host's question.
    """
    return part_name_prefix(root) or part_prefix(root) or root.__name__


def _env_spelling(
    root: type[ConfigPart],
    field: FieldInfo,
    flat: str,
    *,
    exposed: bool,
) -> EnvSpelling | None:
    """The field's variable, or None when nobody opted it in."""
    absolute = marker_of(field, EnvNamedMarker)
    if absolute is not None:
        return EnvSpelling(name=absolute.name, absolute=True) if exposed else None
    if not exposed:
        return None
    prefix = part_prefix(root)
    return EnvSpelling(
        name="_".join([prefix, flat] if prefix else [flat]).upper(),
        absolute=False,
    )


def _cli_forms(
    field: FieldInfo, cli_name: str, *, flag: bool, counts: bool
) -> tuple[CliForm, ...]:
    """The derived form, then one per ``form()`` marker, in declaration order.

    A counted field's forms take no value: occurrences are what carry the
    meaning, so ``-v -v -v`` is three rather than a demand for an argument.
    """
    if has_marker(field, NoCLIMarker):
        return ()

    flag = flag or counts
    short = marker_of(field, ShortMarker)
    long = f"--{cli_name}"
    forms = [
        CliForm(
            long=long,
            short=f"-{short.char}" if short is not None else None,
            negative=f"--no-{cli_name}" if flag else None,
            flag=flag,
            contributes=MISSING,
        )
    ]

    for marker in field.markers:
        if not isinstance(marker, FormMarker):
            continue
        supplies = marker.contributes is not MISSING
        forms.append(
            CliForm(
                long=marker.long,
                short=f"-{marker.short}" if marker.short is not None else None,
                # A form supplying a constant needs no value, so it behaves as
                # a flag whatever the field's own type is.
                negative=(f"--no-{marker.long[2:]}" if flag and marker.long else None),
                flag=flag or supplies,
                contributes=marker.contributes,
            )
        )
    return tuple(forms)


def _exposed_to_env(root: type[ConfigPart], field: FieldInfo, subtree: bool) -> bool:
    """Whether this field has opted in, itself or through an ancestor.

    A root declaring ``from_env=True`` is the same marker on the one field that
    has no parent, and a marker on a nested field opts in everything beneath
    it, because a variable holding a whole table exposes every key inside it.
    """
    return subtree or part_from_env(root) or has_marker(field, FromEnvMarker)


def field_specs(root: type[ConfigPart]) -> tuple[FieldSpec, ...]:
    """Derive the spec of every leaf field of ``root``.

    The single derivation: nothing else may work out what an option looks like.
    """
    specs: list[FieldSpec] = []
    exposed_subtrees: set[tuple[str, ...]] = set()

    for field in fields_of(root):
        subtree = any(field.path[: len(opted)] == opted for opted in exposed_subtrees)
        exposed = _exposed_to_env(root, field, subtree)

        if field.is_nested:
            if exposed:
                exposed_subtrees.add(field.path)
            continue

        names = names_of(root, field)
        declared = field.type
        flag = declared is bool
        counts = has_marker(field, CountedMarker)
        help_marker = marker_of(field, HelpMarker)

        specs.append(
            FieldSpec(
                path=field.path,
                flat=names.flat,
                file_key=None if has_marker(field, NoIniMarker) else names.flat,
                env=_env_spelling(root, field, names.flat, exposed=exposed),
                cli=_cli_forms(field, names.cli, flag=flag, counts=counts),
                annotation=field.annotation,
                default=field.default,
                repeatable=_is_repeatable(declared),
                optional=_is_optional(field.annotation),
                counts=counts,
                values=_closed_values(declared),
                aliases=tuple(
                    marker.name
                    for marker in field.markers
                    if isinstance(marker, FormerlyMarker)
                ),
                help=help_marker.help if help_marker is not None else "",
                group=_group_of(root),
            )
        )

    return tuple(specs)


__all__ = [
    "CliForm",
    "EnvSpelling",
    "FieldSpec",
    "field_specs",
]
