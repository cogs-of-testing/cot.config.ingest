"""The exception hierarchy.

Only the two the field model needs exist so far. The rest of
``docs/design/diagnostics.md`` -- the warning set, the usage, value, lifecycle
and missing-field errors, aggregation and strict mode -- arrives with build
step 3, beneath the same ``ConfigError`` base.
"""

from __future__ import annotations


class ConfigError(Exception):
    """Base for everything this library raises about a configuration."""


class ConfigDeclarationError(ConfigError):
    """A class the library cannot honour as declared.

    Raised while a declaration is being read, never while values are being
    merged: the input is fine and the program is wrong.
    """
