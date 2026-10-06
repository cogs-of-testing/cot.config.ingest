"""Help, rendered from specs and returned as text.

Rendering from specs rather than from a parser's registrations is what lets
help show what a host formatter cannot: the closed value set behind a
``Literal``, the ``--no-`` form of a boolean, every form of an option, and the
file key it corresponds to. Grouping follows the declared roots.

Nothing here prints or exits; the application owns the process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ._specs import CliForm, FieldSpec

_RESERVED: tuple[tuple[str, str], ...] = (
    ("-h, --help", "show this help"),
    ("-o KEY=VALUE", "set any option by its file key"),
)


def _render_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _metavar(spec: FieldSpec) -> str:
    if spec.values is not None:
        return "{" + ",".join(_render_value(value) for value in spec.values) + "}"
    return "VALUE"


def _takes_value(spec: FieldSpec, form: CliForm) -> bool:
    from ._fields import MISSING

    return not (form.flag or spec.counts or form.contributes is not MISSING)


def _invocation(spec: FieldSpec, form: CliForm) -> str:
    names = [name for name in (form.short, form.long) if name is not None]
    text = ", ".join(names)
    if _takes_value(spec, form):
        text += f" {_metavar(spec)}"
    if form.negative is not None:
        text += f", {form.negative}"
    return text


def _description(spec: FieldSpec, form: CliForm, first: bool) -> str:
    from ._fields import MISSING

    parts: list[str] = []
    if first and spec.help:
        parts.append(spec.help)
    if form.contributes is not MISSING:
        parts.append(f"same as {spec.flat}={_render_value(form.contributes)}")
    if first and spec.file_key is not None:
        parts.append(f"[file key: {spec.file_key}]")
    return "  ".join(parts)


def format_help(specs: Iterable[FieldSpec], *, prog: str | None = None) -> str:
    """Every command-line form of every spec, grouped by root."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for spec in specs:
        for position, form in enumerate(spec.cli):
            entry = (_invocation(spec, form), _description(spec, form, position == 0))
            rows = groups.setdefault(spec.group, [])
            if entry not in rows:
                rows.append(entry)

    every = [*_RESERVED, *(entry for rows in groups.values() for entry in rows)]
    width = max(len(invocation) for invocation, _ in every)

    def lines_for(rows: Iterable[tuple[str, str]]) -> list[str]:
        return [f"  {inv.ljust(width)}  {text}".rstrip() for inv, text in rows]

    lines: list[str] = []
    if prog:
        lines += [f"usage: {prog} [options]", ""]
    lines += ["options:", *lines_for(_RESERVED)]
    for group in sorted(groups):
        rows = sorted(groups[group], key=lambda row: row[0].lstrip("-"))
        lines += ["", f"{group}:", *lines_for(rows)]
    return "\n".join(lines) + "\n"


__all__ = ["format_help"]
