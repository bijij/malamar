"""
Malamar: Dependency Injection Framework for Python

"""

from __future__ import annotations

from typing import NamedTuple

from .core import *
from .core import __all__ as _core_all
from .service import *
from .service import __all__ as _service_all


class _VersionInfo(NamedTuple):
    major: int
    minor: int
    micro: int
    release: str
    serial: int


version: str = "0.1.0a"
version_info: _VersionInfo = _VersionInfo(0, 1, 0, "alpha", 0)

__all__ = [
    *_core_all,
    *_service_all,
    "version",
    "version_info",
]
