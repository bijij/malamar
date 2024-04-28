from __future__ import annotations

from abc import ABCMeta, abstractmethod

__all__ = ("Service",)


class Service(metaclass=ABCMeta):
    """Base class for services."""

    __registered: bool = False
    __running: bool = False

    @abstractmethod
    async def start(self) -> None:
        """Called when the service is started."""
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
        """Called when the service is stopped."""
        pass

    async def _stop(self) -> None:
        if not self.__registered:
            raise RuntimeError("Service not registered")
        if not self.__running:
            raise RuntimeError("Service not running")

        await self.stop()
        self.__running = False
