"""Base classes for configuration."""

from __future__ import annotations

from typing import ClassVar

from typing_extensions import Self, dataclass_transform

from ._annotations import PrefixMarker


class _FrozenFromKwargsMixin:
    """
    Mixin to allow initialization of classes from keyword arguments.
    """

    _config_markers: ClassVar[
        tuple[object, ...]
    ] = ()  # configuration for the classes themselfes

    def __init_subclass__(cls: type[Self], prefix: str | None = None) -> None:
        if prefix is not None:
            cls._config_markers += (PrefixMarker(prefix),)

    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, name):
            raise AttributeError(f"Cannot modify frozen attribute '{name}'")
        super().__setattr__(name, value)

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self.__dict__ == other.__dict__


@dataclass_transform(eq_default=True, kw_only_default=True, frozen_default=True)
class ConfigPart(_FrozenFromKwargsMixin):
    """
    Base class for configuration parts that can be composed together.

    Example:
        class LoggingConfig(ConfigPart):
            level: str = "INFO"
            file: str | None = None
    """


@dataclass_transform(eq_default=True, kw_only_default=True, frozen_default=True)
class SubConfig(_FrozenFromKwargsMixin):
    """
    Base class for sub-configuration sections.

    class DatabaseConfig(SubConfig):
        host: str
        port: int

    class AppConfig(ConfigPart):
        debug: bool = False
        database: DatabaseConfig

    """


__all__ = [
    "ConfigPart",
    "SubConfig",
]
