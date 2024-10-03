from __future__ import annotations

import operator
import types
import typing
from functools import reduce
from typing import Any, Literal, TypeVar, get_args, get_origin

__all__ = (
    "MISSING",
    "_get_optional_type",
)


T = TypeVar("T")


class _MissingSentinel:
    def __repr__(self) -> str:
        return "..."

    def __bool__(self) -> bool:
        return False


MISSING: Any = _MissingSentinel()


def _get_optional_type(type: T | None) -> tuple[Literal[True], T] | tuple[Literal[False], T | None]:
    if hasattr(typing, "Optional"):
        if get_origin(type) is typing.Optional:
            args = get_args(type)
            if len(args) == 1:
                return True, args[0]

            return True, typing.Union.__getitem__(args)  # type: ignore

    if hasattr(typing, "Union"):
        args = get_args(type)
        if get_origin(type) is typing.Union and None in args:
            if len(args) == 2:
                other = args[0] if args[1] is None else args[1]
                return True, other

            return True, typing.Union.__getitem__(t for t in args if t is not None)  # type: ignore

    if hasattr(types, "UnionType"):
        if getattr(type, "__class__", None) is types.UnionType:  # type: ignore
            args = get_args(type)
            if None in args:
                if len(args) == 2:
                    other = args[0] if args[1] is None else args[1]
                    return True, other

                return True, reduce(operator.or_, (t for t in args if t is not None))  # type: ignore

    return False, type
