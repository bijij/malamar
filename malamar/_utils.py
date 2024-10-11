from __future__ import annotations

import operator
import types
import typing
from collections.abc import Callable
from functools import reduce
from typing import TYPE_CHECKING, Any, Literal, TypeVar, get_args, get_origin

if TYPE_CHECKING:
    from typing_extensions import Concatenate, ParamSpec

    P = ParamSpec("P")

__all__ = (
    "MISSING",
    "_bind_function",
    "_get_optional_type",
)


T = TypeVar("T")
R = TypeVar("R")


_NoneType = type(None)


class _MissingSentinel:
    def __repr__(self) -> str:
        return "..."

    def __bool__(self) -> bool:
        return False


MISSING: Any = _MissingSentinel()


def _bind_function(instance: T, func: Callable[Concatenate[T, P], R], *, name: str | None = None) -> Callable[P, R]:
    if name is None:
        name = func.__name__

    bound = func.__get__(instance, instance.__class__)
    setattr(instance, name, bound)
    return bound


def _get_optional_type(type: type[T | None]) -> tuple[Literal[True], T] | tuple[Literal[False], type[T | None]]:
    if hasattr(typing, "Optional"):
        if get_origin(type) is typing.Optional:
            args = get_args(type)
            if len(args) == 1:
                return True, args[0]

            return True, typing.Union.__getitem__(args)  # type: ignore

    if hasattr(typing, "Union"):
        args = get_args(type)
        if get_origin(type) is typing.Union and _NoneType in args:
            if len(args) == 2:
                other = args[0] if args[1] is _NoneType else args[1]
                return True, other

            return True, typing.Union.__getitem__(t for t in args if t is not _NoneType)  # type: ignore

    if hasattr(types, "UnionType"):
        if getattr(type, "__class__", None) is types.UnionType:  # type: ignore
            args = get_args(type)
            if _NoneType in args:
                if len(args) == 2:
                    other = args[0] if args[1] is _NoneType else args[1]
                    return True, other

                return True, reduce(operator.or_, (t for t in args if t is not _NoneType))

    return False, type
