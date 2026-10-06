"""Every warning and every error, and the rule that decides which one an input gets.

The rule that chooses between them:

- the run can continue, and everything the user got right still holds: **warn**,
  naming what was ignored
- the input cannot be honoured, or honouring it would put a forbidden value in
  a field: **raise**
- the declaration is wrong rather than the input: **raise**
  ``ConfigDeclarationError``, at ``declare()``

Two corollaries. A warning must never fire on correct configuration, because a
warning the user learns to ignore is worth less than no warning at all. And
programmer error never waits for ``resolve()``: a collision is known the moment
``declare()`` sees the class, and reporting it then puts the traceback at the
call site that caused it.

Nothing here prints and nothing exits. Warnings go through ``warnings.warn``
with a filterable category; errors are raised.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


class ConfigWarning(UserWarning):
    """Base of every warning this library emits.

    Shared so that a host can filter the whole set with one ``filterwarnings``
    entry, and an application can promote them wholesale.
    """


class UnknownConfigKeyWarning(ConfigWarning):
    """A source supplied a spelling no declared root claims."""


class UnknownOverrideKeyWarning(ConfigWarning):
    """An ``-o`` key addressed no field."""


class DeprecatedNameWarning(ConfigWarning):
    """A field was reached by one of its legacy names.

    A ``ConfigWarning`` rather than a ``DeprecationWarning``, so that it
    reaches a user by default: Python hides ``DeprecationWarning`` outside
    ``__main__``, and the person who needs to rename a key in a config file is
    not the person running the interpreter.
    """


class ShadowedValueWarning(ConfigWarning):
    """A value that failed conversion, and lost its path to a higher layer.

    Still a broken file: the day the override goes away it becomes the winner.
    """


class RuntimeMutationWarning(ConfigWarning):
    """A fragment was rebuilt after resolve()."""


class ConfigError(Exception):
    """Base every error shares.

    An application can tell "this library rejected the configuration" from any
    other exception with one ``except``.
    """


class ConfigLifecycleError(ConfigError):
    """An operation happened in the wrong phase, or resolution never settled."""


class ConfigDeclarationError(ConfigError):
    """A class or a source set the library cannot honour.

    Raised while a declaration is being read, never while values are being
    merged: the input is fine and the program is wrong.
    """


class ConfigCollisionError(ConfigDeclarationError):
    """Two roots claim one spelling, and mean different things by it."""


class ConfigUsageError(ConfigError):
    """Input that cannot be honoured as written."""


class ConfigValueError(ConfigError):
    """A value cannot be the declared type of the field it addresses."""


class MissingConfigError(ConfigError):
    """Required fields nobody supplied."""


#: What strict mode raises in place of each warning that reports *input*.
#: `RuntimeMutationWarning` is absent on purpose: it reports what the host did,
#: not what the user wrote, and promoting it would make `manager.set()`
#: unusable.
STRICT_PROMOTIONS: dict[type[ConfigWarning], type[ConfigError]] = {
    UnknownConfigKeyWarning: ConfigUsageError,
    UnknownOverrideKeyWarning: ConfigUsageError,
    DeprecatedNameWarning: ConfigUsageError,
    ShadowedValueWarning: ConfigValueError,
}


@dataclass(frozen=True)
class Diagnostic:
    """One thing that went wrong, named once."""

    category: type[ConfigWarning] | type[ConfigError]
    message: str
    """What, where, and the way out when there is one."""


@dataclass
class Diagnostics:
    """Everything one ``resolve()`` found, reported in one go.

    Collected rather than emitted as they are discovered, because the order
    declared roots are visited is not something the user controls: a per-root
    stream would come out in an order nobody can predict or diff. A config file
    with six typos produces one warning listing six keys.
    """

    strict: bool = False
    entries: list[Diagnostic] = field(default_factory=list)

    def add(
        self, category: type[ConfigWarning] | type[ConfigError], message: str
    ) -> None:
        """Record one diagnostic. Nothing is emitted until :meth:`emit`."""
        self.entries.append(Diagnostic(category=category, message=message))

    def extend(
        self, category: type[ConfigWarning] | type[ConfigError], messages: Iterable[str]
    ) -> None:
        """Record several of one category."""
        for message in messages:
            self.add(category, message)

    def clear(self) -> None:
        """Forget everything collected so far.

        Each iteration of resolution starts clean: an earlier one parsed argv
        against fewer options, and what it complained about may no longer be
        true.
        """
        self.entries.clear()

    def emit(self) -> None:
        """Warn once per category, then raise once if anything was fatal.

        Under ``strict``, the warnings that report input are promoted first, so
        an application that treats one kind of user error as fatal is not left
        tolerating the rest.
        """
        promoted = [
            Diagnostic(self._effective(entry.category), entry.message)
            for entry in self.entries
        ]

        fatal = [d for d in promoted if _is_error(d.category)]
        warned = [d for d in promoted if not _is_error(d.category)]

        for category, messages in _by_category(warned):
            warnings.warn(_render(messages), category, stacklevel=3)  # type: ignore[arg-type]

        if fatal:
            # The first category found decides the type; every message is
            # carried, so nothing discovered in this pass is lost.
            category = fatal[0].category
            raise category(_render([d.message for d in fatal]))

    def _effective(
        self, category: type[ConfigWarning] | type[ConfigError]
    ) -> type[ConfigWarning] | type[ConfigError]:
        if not self.strict or _is_error(category):
            return category
        return STRICT_PROMOTIONS.get(category, category)  # type: ignore[arg-type]


def _is_error(category: type[ConfigWarning] | type[ConfigError]) -> bool:
    return issubclass(category, ConfigError)


def _by_category(
    diagnostics: Sequence[Diagnostic],
) -> list[tuple[type[ConfigWarning] | type[ConfigError], list[str]]]:
    """Group messages by category, keeping the order each first appeared."""
    grouped: dict[type[ConfigWarning] | type[ConfigError], list[str]] = {}
    for diagnostic in diagnostics:
        grouped.setdefault(diagnostic.category, []).append(diagnostic.message)
    return list(grouped.items())


def _render(messages: Sequence[str]) -> str:
    if len(messages) == 1:
        return messages[0]
    return "\n".join(["several problems were found:", *(f"  {m}" for m in messages)])


__all__ = [
    "STRICT_PROMOTIONS",
    "ConfigCollisionError",
    "ConfigDeclarationError",
    "ConfigError",
    "ConfigLifecycleError",
    "ConfigUsageError",
    "ConfigValueError",
    "ConfigWarning",
    "DeprecatedNameWarning",
    "Diagnostic",
    "Diagnostics",
    "MissingConfigError",
    "RuntimeMutationWarning",
    "ShadowedValueWarning",
    "UnknownConfigKeyWarning",
    "UnknownOverrideKeyWarning",
]
