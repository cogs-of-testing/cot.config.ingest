"""The precedence ladder, in one place.

Every source carries a ``precedence``; higher wins. The ladder below is the
*default* assignment, not a fixed enum: each source takes ``precedence=`` and
each marker that creates a source takes one too, so an application that wants
its config files to outrank the environment can say so::

    TomlSource(path, precedence=Precedence.ENV + 1)

The gaps between the rungs let a caller slot in without renumbering, and tiers
such as system, user and local are ``FILE``, ``FILE + 1``, ``FILE + 2``,
assigned by whoever constructs the sources.

``DEFAULTS`` is deliberately negative: a value nobody configured must lose to
every real source, including one declared at precedence 0.

This ladder is the whole ordering rule. Nothing is special-cased above it:
injected arguments are a source at their own rung rather than a splice into
argv, ``-o`` is a source rather than a post-merge fixup, and a late write is a
source at the top rather than a mutation.
"""

from __future__ import annotations

from typing import Final


class Precedence:
    """Default precedence values, lowest first.

    ``defaults < file < injected < env < cli < override < runtime``
    """

    DEFAULTS: Final = -1
    """Class-level defaults. Below every source."""

    FILE: Final = 15
    """TOML/INI files, and files named by a ``config_source`` field."""

    INJECTED: Final = 18
    """Tokens an ``injected_args`` field contributed, re-parsed as arguments."""

    ADDOPTS: Final = INJECTED
    """Deprecated spelling of :attr:`INJECTED`, kept until the sources land."""

    ENV: Final = 20
    """Environment variables."""

    CLI: Final = 25
    """Arguments the user actually typed."""

    OVERRIDE: Final = 30
    """``-o key=value`` pairs, from whichever argv-parsing source carried them.

    Above the command line because ``-o`` names a field and supplies a value
    regardless of what else addressed it: ``--log-level=A -o log_level=B`` is B.
    """

    RUNTIME: Final = 40
    """A write made after resolution, with the whole configuration in view.

    The top of the ladder, and it stays the top: a source that wants to outrank
    a late write is describing input, and input belongs below the command line.
    """


__all__ = ["Precedence"]
