import typing_extensions
from collections.abc import Sequence
from pathlib import Path
from typing import TypeAlias, Any, Sequence
from typing_extensions import Self

Origin: TypeAlias = str | Path | None
InputData = dict[str | Any]

Inputs = Sequence[InputData | tuple[Origin, InputData]]
NormalizedInputs = Sequence[tuple[Origin, InputData]]


@typing_extensions.dataclass_transform()
class Config:
    def __init__(self, **kwargs: Any):
        for name, value in kwargs.items():
            setattr(self, name, value)

    def __repr__(self):
        values = ", ".join(f"{k}={v!r}" for k, v in vars(self).items())
        return f"<{self.__class__.__name__} {values}>"

    def __eq__(self, other: object):
        return isinstance(other, self.__class__) and vars(self) == vars(other)

    @classmethod
    def from_data(self, inputs: Sequence[Inputs]) -> Self:
        return self(**inputs[0])  # todo: normalize inputs


def field() -> None:
    return None
