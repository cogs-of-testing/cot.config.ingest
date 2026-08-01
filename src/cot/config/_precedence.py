"""The precedence ladder, in one place.

Every source carries a ``precedence``; higher wins. The ladder below is the
*default* assignment, not a fixed enum: each source takes ``precedence=`` and
each marker that creates a source takes one too, so an application that wants
its config files to outrank the environment can say so::

    TomlSource(path, precedence=Precedence.ENV + 1)

The defaults exist so that the common case -- files below environment below
command line, with ``addopts`` sitting between file and environment -- needs no
arithmetic at the call site.

``DEFAULTS`` is deliberately negative: a value nobody configured must lose to
every real source, including one declared at precedence 0.
"""

from __future__ import annotations

from typing import Final


class Precedence:
    """Default precedence values, lowest first.

    ``defaults < file < addopts < env < cli``
    """

    DEFAULTS: Final = -1
    """Class-level defaults. Below every source."""

    FILE: Final = 15
    """TOML/INI files, and files named by a ``config_source`` field."""

    ADDOPTS: Final = 18
    """Arguments contributed by an ``addopts_field``, re-parsed as CLI args."""

    ENV: Final = 20
    """Environment variables."""

    CLI: Final = 25
    """Arguments the user actually typed."""


__all__ = ["Precedence"]
