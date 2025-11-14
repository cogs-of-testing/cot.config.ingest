"""Configuration management core classes."""

from __future__ import annotations
from typing import Any, dataclass_transform




class FromParentMarker:
    """Marker class to indicate that a sub-configuration should be initialized from its parent configuration."""
    pass

from_parent = FromParentMarker()



class _FrozenFromKwargsMixin:
    """
    Mixin to allow initialization of classes from keyword arguments.
    """
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
