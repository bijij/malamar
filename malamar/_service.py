from __future__ import annotations

import asyncio
from abc import ABCMeta, abstractmethod
from collections.abc import Awaitable, Callable
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Literal

from ._utils import _bind_function

__all__ = ("Service", "ServiceState")


class ServiceState(Enum):
    """The state of the service."""

    UNKNOWN = auto()
    """The application is in an unknown state.
    
    .. note::
        This state should never be returned by the application.
    """

    STARTING = auto()
    """The application is starting."""

    STARTED = auto()
    """The application has started."""

    STOPPING = auto()
    """The application is stopping."""

    STOPPED = auto()
    """The application has stopped."""


async def _start_service(self: Service, *, timeout: float | None = None) -> None:
    """|coro|

    Starts the application and all services.

    Parameters
    ----------
    timeout: Optional[:class:`float`]
        The maximum number of seconds to allow for all services to start.
        If ``None``, no timeout is applied.

    Raises
    ------
    asyncio.TimeoutError
        A service did not start within the specified timeout.
    """
    if self._starting.is_set() or self._started.is_set():
        raise RuntimeError("Application is already running")
    elif self._stopping.is_set():  # Note: this shouldn't be possible
        raise RuntimeError("Application is stopping")

    self._starting.set()

    try:
        await self.__service_start__(timeout=timeout)
    finally:
        self._starting.clear()

    self._stopped.clear()
    self._started.set()


async def _stop_service(self: Service, *, timeout: float | None = None) -> None:
    if not self._started.is_set():
        raise RuntimeError("Application is not running")
    elif self._stopping.is_set():
        raise RuntimeError("Application is already stopping")
    elif self._stopped.is_set():  # Note: this shouldn't be possible
        raise RuntimeError("Application is already stopped")

    self._stopping.set()

    try:
        await self.__service_stop__(timeout=timeout)
    finally:
        self._stopping.clear()

    self._started.clear()
    self._stopped.set()


class _ServiceMeta(ABCMeta):

    __service_start__: Callable[..., Awaitable[None]]
    __service_stop__: Callable[..., Awaitable[None]]

    if TYPE_CHECKING:

        async def start(self, *, timeout: float | None = ...) -> None: ...

        async def stop(self, *, timeout: float | None = ...) -> None: ...

    def __new__(
        cls: type[_ServiceMeta],
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs,
    ) -> _ServiceMeta:
        service = super().__new__(cls, name, bases, namespace, **kwargs)

        service.__service_start__ = service.start
        service.__service_stop__ = service.stop

        return service


class Service(metaclass=_ServiceMeta):
    """Base class for services."""

    # __registered: bool = False
    # __running: bool = False

    def __init__(self):
        """Creates a new Service instance."""
        print("Hello from Service", self)
        self._starting: asyncio.Event = asyncio.Event()
        self._started: asyncio.Event = asyncio.Event()
        self._stopping: asyncio.Event = asyncio.Event()
        self._stopped: asyncio.Event = asyncio.Event()

        self.start = _bind_function(self, _start_service, name="start")
        self.stop = _bind_function(self, _stop_service, name="stop")

        self._stopped.set()

    @abstractmethod
    async def start(self, *, timeout: float | None = None) -> None:
        """Called when the service is started, this method should be overridden to implement the service logic."""
        pass

    @abstractmethod
    async def stop(self, *, timeout: float | None = None) -> None:
        """Called when the service is stopped, this method should be overridden to implement the service cleanup logic."""
        pass

    @property
    def state(self) -> ServiceState:
        """The state of the application."""
        if self._starting.is_set():
            return ServiceState.STARTING
        elif self._stopping.is_set():
            return ServiceState.STOPPING
        elif self._started.is_set():
            return ServiceState.STARTED
        elif self._stopped.is_set():
            return ServiceState.STOPPED

        return ServiceState.UNKNOWN

    @property
    def starting(self) -> Awaitable[Literal[True]]:
        """|coroprop|

        An awaitable that resolves when the application is starting.
        """
        return self._starting.wait()

    @property
    def started(self) -> Awaitable[Literal[True]]:
        """|coroprop|

        An awaitable that resolves when the application has started.
        """
        return self._started.wait()

    @property
    def stopping(self) -> Awaitable[Literal[True]]:
        """|coroprop|

        An awaitable that resolves when the application is stopping.
        """
        return self._stopping.wait()

    @property
    def stopped(self) -> Awaitable[Literal[True]]:
        """|coroprop|

        An awaitable that resolves when the application has stopped.
        """
        return self._stopped.wait()
