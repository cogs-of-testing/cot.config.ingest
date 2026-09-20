"""The re-parsing argument parser.

It exists because options must be registrable after parsing has already
happened. A config file read during resolution can contribute injected
arguments that must be parsed against options a later plugin declared, and
argparse cannot re-open a parsed namespace. This parser re-parses from scratch
on every read, which makes registration order irrelevant.

Two rules carry the whole design. Every boolean gets a ``--no-`` form, and an
option that takes a value consumes the next token unconditionally. Without the
first, a file's ``verbose = true`` cannot be turned off from the command line;
without the second, ``--offset -5`` is unreachable. Both failures would be
silent, and the ladder puts files below the command line precisely so that an
argument can override a file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ._diagnostics import ConfigUsageError
from ._fields import MISSING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ._specs import CliForm, FieldSpec

#: Reserved by the parser: ``-o`` for generic overrides, ``-h`` for help.
RESERVED_SHORTS = frozenset({"-o", "-h"})


@dataclass(frozen=True)
class Occurrence:
    """One appearance of one option on the command line."""

    spec: FieldSpec
    form: CliForm
    raw: Any
    """The text that followed, or the constant a flag or a form supplied."""

    token: str
    """The option as the user spelled it, for the origin."""


@dataclass
class ParseResult:
    """Everything one pass over the tokens produced."""

    occurrences: list[Occurrence] = field(default_factory=list)
    overrides: list[tuple[str, str]] = field(default_factory=list)
    """``-o key=value`` pairs, for the override source to place."""

    unknown: list[str] = field(default_factory=list)
    """Tokens this parser does not claim, left for the host to deal with."""

    help_requested: bool = False


@dataclass
class ArgumentParser:
    """Registered forms, and a pass over tokens that uses them."""

    _long: dict[str, tuple[FieldSpec, CliForm, bool]] = field(default_factory=dict)
    _short: dict[str, tuple[FieldSpec, CliForm]] = field(default_factory=dict)

    def register(self, specs: Iterable[FieldSpec]) -> None:
        """Register every form of every spec. Registering twice is harmless."""
        for spec in specs:
            for form in spec.cli:
                self._register_form(spec, form)

    def _register_form(self, spec: FieldSpec, form: CliForm) -> None:
        if form.long is not None:
            self._long[form.long] = (spec, form, False)
        if form.negative is not None:
            self._long[form.negative] = (spec, form, True)
        if form.short is not None:
            if form.short in RESERVED_SHORTS:
                raise ConfigUsageError(
                    f"{form.short} is reserved by the parser "
                    f"({'-o' if form.short == '-o' else '-h'}), so "
                    f"{spec.flat} cannot claim it"
                )
            self._short[form.short] = (spec, form)

    def parse(self, tokens: Sequence[str]) -> ParseResult:
        """Read ``tokens`` from scratch, claiming what has been registered."""
        result = ParseResult()
        remaining = list(tokens)

        while remaining:
            token = remaining.pop(0)
            if token in ("-h", "--help"):
                result.help_requested = True
            elif token == "-o":
                self._take_override(token, remaining, result)
            elif token.startswith("--"):
                self._take_long(token, remaining, result)
            elif token.startswith("-") and token != "-":
                self._take_short(token, remaining, result)
            else:
                result.unknown.append(token)

        return result

    def _take_override(
        self, token: str, remaining: list[str], result: ParseResult
    ) -> None:
        if not remaining:
            raise ConfigUsageError("-o needs a key=value pair, and none followed")
        pair = remaining.pop(0)
        key, sep, value = pair.partition("=")
        if not sep:
            raise ConfigUsageError(f"-o expects key=value, got {pair!r}")
        result.overrides.append((key, value))

    def _take_long(self, token: str, remaining: list[str], result: ParseResult) -> None:
        name, sep, inline = token.partition("=")
        registered = self._long.get(name)
        if registered is None:
            result.unknown.append(token)
            return

        spec, form, negated = registered
        if negated:
            result.occurrences.append(
                Occurrence(spec=spec, form=form, raw=False, token=name)
            )
            return
        if form.contributes is not MISSING:
            result.occurrences.append(
                Occurrence(spec=spec, form=form, raw=form.contributes, token=name)
            )
            return
        if form.flag:
            result.occurrences.append(
                Occurrence(spec=spec, form=form, raw=True, token=name)
            )
            return

        value = inline if sep else self._next_value(name, remaining)
        result.occurrences.append(
            Occurrence(spec=spec, form=form, raw=value, token=name)
        )

    def _take_short(
        self, token: str, remaining: list[str], result: ParseResult
    ) -> None:
        body = token[1:]
        # -vx is two boolean shorts; -j4 is a short with its value attached.
        for position, letter in enumerate(body):
            option = f"-{letter}"
            registered = self._short.get(option)
            if registered is None:
                result.unknown.append(token)
                return

            spec, form = registered
            if form.contributes is not MISSING:
                result.occurrences.append(
                    Occurrence(spec=spec, form=form, raw=form.contributes, token=option)
                )
                continue
            if form.flag:
                result.occurrences.append(
                    Occurrence(spec=spec, form=form, raw=True, token=option)
                )
                continue

            rest = body[position + 1 :]
            value = rest if rest else self._next_value(option, remaining)
            result.occurrences.append(
                Occurrence(spec=spec, form=form, raw=value, token=option)
            )
            return

    def _next_value(self, option: str, remaining: list[str]) -> str:
        """Take the next token as this option's value, whatever it looks like.

        Unconditionally, so that ``--offset -5`` works. The companion of that
        rule is this error: an option whose value is missing has to say so
        rather than be dropped as unknown.
        """
        if not remaining:
            raise ConfigUsageError(f"{option} needs a value, and none followed")
        return remaining.pop(0)


__all__ = [
    "RESERVED_SHORTS",
    "ArgumentParser",
    "Occurrence",
    "ParseResult",
]
