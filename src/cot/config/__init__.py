from collections.abc import Sequence
from pathlib import Path
from typing import Any

import typing_extensions
from typing_extensions import Self, TypeAlias

Origin: TypeAlias = str | Path | None
InputData: TypeAlias = dict[str, Any]

Inputs: TypeAlias = Sequence[InputData | tuple[Origin, InputData]]
NormalizedInputs: TypeAlias = Sequence[tuple[Origin, InputData]]


@typing_extensions.dataclass_transform()
class Config:
    def __init__(self, **kwargs: Any):
        for name, value in kwargs.items():
            setattr(self, name, value)

    def __repr__(self) -> str:
        values = ", ".join(f"{k}={v!r}" for k, v in vars(self).items())
        return f"<{self.__class__.__name__} {values}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, self.__class__) and vars(self) == vars(other)

    @classmethod
    def from_data(cls, inputs: Inputs) -> Self:
        return cls(**inputs[0])  # type: ignore[arg-type]  # todo: normalize inputs


def field() -> Any:
    return None
