"""Source tracking and debugging information for configuration values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class SourceType(Enum):
    """Type of configuration source."""

    DEFAULT = "default"
    DEFAULT_FACTORY = "default_factory"
    FILE = "file"
    ENV = "environment"
    CLI = "cli"
    CODE = "code"
    MERGED = "merged"


@dataclass
class SourceInfo:
    """Information about where a configuration value came from."""

    source_type: SourceType
    location: str | None = None  # file path, env var name, cli flag, etc.
    raw_value: Any = None  # original value before conversion
    is_default: bool = False
    line_number: int | None = None  # for file sources
    override_count: int = 0  # how many times this value was overridden
    previous_source: SourceInfo | None = None  # chain of overrides

    def __str__(self) -> str:
        """Human-readable description of the source."""
        if self.is_default:
            return f"{self.source_type.value} (default)"

        if self.location:
            if self.source_type == SourceType.FILE and self.line_number:
                return f"{self.source_type.value}: {self.location}:{self.line_number}"
            return f"{self.source_type.value}: {self.location}"

        return self.source_type.value

    def get_override_chain(self) -> list[SourceInfo]:
        """Get the full chain of overrides for this value."""
        chain = [self]
        current = self.previous_source
        while current:
            chain.append(current)
            current = current.previous_source
        return chain


@dataclass
class ConfigValue:
    """Wrapper for a configuration value with its metadata."""

    value: Any
    source: SourceInfo
    field_name: str | None = None

    def __repr__(self) -> str:
        return f"ConfigValue({self.value!r}, source={self.source})"

    def is_default(self) -> bool:
        """Check if this value is using the default."""
        return self.source.is_default

    def was_overridden(self) -> bool:
        """Check if this value was overridden from a previous source."""
        return self.source.override_count > 0


class ConfigDebugInfo:
    """Debug information for a configuration instance."""

    def __init__(self) -> None:
        self._values: dict[str, ConfigValue] = {}
        self._load_order: list[tuple[SourceType, str | None]] = []

    def set_value(
        self,
        field_name: str,
        value: Any,
        source_type: SourceType,
        location: str | None = None,
        raw_value: Any = None,
        is_default: bool = False,
    ) -> None:
        """Set a configuration value with source tracking."""
        # Check if we're overriding an existing value
        previous = None
        override_count = 0

        if field_name in self._values:
            previous = self._values[field_name].source
            override_count = previous.override_count + 1

        source = SourceInfo(
            source_type=source_type,
            location=location,
            raw_value=raw_value if raw_value is not None else value,
            is_default=is_default,
            override_count=override_count,
            previous_source=previous,
        )

        self._values[field_name] = ConfigValue(
            value=value,
            source=source,
            field_name=field_name,
        )

    def get_value(self, field_name: str) -> ConfigValue | None:
        """Get a configuration value with its metadata."""
        return self._values.get(field_name)

    def add_source(self, source_type: SourceType, location: str | None = None) -> None:
        """Record that a source was loaded."""
        self._load_order.append((source_type, location))

    def get_load_order(self) -> list[tuple[SourceType, str | None]]:
        """Get the order in which sources were loaded."""
        return self._load_order.copy()

    def get_non_default_values(self) -> dict[str, ConfigValue]:
        """Get all values that are not using defaults."""
        return {k: v for k, v in self._values.items() if not v.is_default()}

    def get_overridden_values(self) -> dict[str, ConfigValue]:
        """Get all values that were overridden from previous sources."""
        return {k: v for k, v in self._values.items() if v.was_overridden()}

    def generate_report(self) -> str:
        """Generate a human-readable debug report."""
        lines = ["Configuration Debug Report", "=" * 50]

        # Load order
        lines.append("\nLoad Order:")
        for i, (source_type, location) in enumerate(self._load_order, 1):
            loc_str = f" ({location})" if location else ""
            lines.append(f"  {i}. {source_type.value}{loc_str}")

        # Current values
        lines.append("\nCurrent Values:")
        for field_name, config_value in sorted(self._values.items()):
            lines.append(f"  {field_name}:")
            lines.append(f"    value: {config_value.value!r}")
            lines.append(f"    source: {config_value.source}")
            if config_value.was_overridden():
                lines.append(f"    overrides: {config_value.source.override_count}")

        # Override chains
        overridden = self.get_overridden_values()
        if overridden:
            lines.append("\nOverride Chains:")
            for field_name, config_value in sorted(overridden.items()):
                lines.append(f"  {field_name}:")
                chain = config_value.source.get_override_chain()
                for i, source in enumerate(chain):
                    arrow = "    <- " if i > 0 else "    "
                    lines.append(f"{arrow}{source}")

        return "\n".join(lines)
