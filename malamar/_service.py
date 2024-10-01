from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import Protocol, runtime_checkable

__all__ = ("Service", "ServiceProto")


@runtime_checkable
class ServiceProto(Protocol):
    """Protocol for services.

    .. note::
        This protocol is used to allow for additional flexibility when defining services.
        In most cases, you should inherit from :class:`Service` instead.
    """

    async def _start(self) -> None: ...

    """Method called when the service is started."""

    def _register(self) -> None: ...

    """Method called when the service is registered."""

    async def _stop(self) -> None: ...

    """Method called when the service is stopped."""


class Service(metaclass=ABCMeta):
    """Base class for services."""

    __registered: bool = False
    __running: bool = False

    @abstractmethod
    async def start(self) -> None:
        """Called when the service is started, this method should be overridden to implement the service logic."""
        pass

    def _register(self) -> None:
        if self.__registered:
            raise RuntimeError("Service already registered")
        self.__registered = True

    async def _start(self) -> None:
        if not self.__registered:
            raise RuntimeError("Service not registered")
        if self.__running:
            raise RuntimeError("Service already running")

        self.__running = True
        await self.start()

    @abstractmethod
    async def stop(self) -> None:
        """Called when the service is stopped, this method should be overridden to implement the service cleanup logic."""
        pass

    async def _stop(self) -> None:
        if not self.__registered:
            raise RuntimeError("Service not registered")
        if not self.__running:
            raise RuntimeError("Service not running")

        await self.stop()
        self.__running = False
