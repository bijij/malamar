from __future__ import annotations

import asyncio
import builtins
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextvars import ContextVar
from enum import Enum, auto
from os import urandom
from typing import TYPE_CHECKING, Any, Literal, TypeVar, get_type_hints, overload

from ._service import ServiceProto
from ._utils import MISSING, _get_optional_type

if TYPE_CHECKING:
    from typing_extensions import Self

__all__ = (
    "Application",
    "ApplicationState",
)

T = TypeVar("T")
T_SVC = TypeVar("T_SVC", bound=ServiceProto)


def _get_dependencies(cls: type) -> Sequence[tuple[str | None, type, bool]]:
    """Get the dependencies of a class.

    Parameters
    ----------
    cls: :class:`type`
        The class to get the dependencies of.
    """
    if cls.__init__ is object.__init__:
        return []

    annotations = get_type_hints(cls.__init__)
    signature = inspect.signature(cls.__init__)

    dependencies = []

    parameters = iter(signature.parameters.values())
    next(parameters)  # Skip self

    for parameter in parameters:
        if parameter.name not in annotations:
            raise ValueError(f"Missing type hint for parameter: {parameter}")

        required, type = _get_optional_type(annotations[parameter.name])

        name = None
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            name = parameter.name

        dependencies.append((name, type, required))

    return dependencies


class ApplicationState(Enum):
    """The state of the application."""

    UNKNOWN = auto()
    """The application is in an unknown state."""

    STARTING = auto()
    """The application is starting."""

    STARTED = auto()
    """The application has started."""

    STOPPING = auto()
    """The application is stopping."""

    STOPPED = auto()
    """The application has stopped."""


class Application:
    """The class responsible for managing the application and its services."""

    def __init__(self):
        """Creates a new Application instance."""
        self._singletons: dict[type[Any], Any] = {Application: self, type(self): self}
        self._transients: dict[type[Any], type[Any]] = {}
        self._scoped: dict[type[Any], type[Any]] = {}
        self._contexts: ContextVar[dict[type[Any], Any]] = ContextVar(
            f"malamar.{self.__class__.__name__}.{urandom(16).hex()}.context", default={}
        )
        self._services: dict[type[ServiceProto], ServiceProto] = {}

        self._lock: asyncio.Lock = asyncio.Lock()
        self._starting: asyncio.Event = asyncio.Event()
        self._started: asyncio.Event = asyncio.Event()
        self._stopping: asyncio.Event = asyncio.Event()
        self._stopped: asyncio.Event = asyncio.Event()

        self._stopped.set()

    def _resolve_dependencies(
        self, types: Sequence[tuple[str | None, type, bool]]
    ) -> tuple[Sequence[Any], Mapping[str, Any]]:
        dependencies = ([], {})
        for name, type, required in types:
            resolved = None
            if type in self._singletons:
                resolved = self.get_singleton(type, required=required)
            elif type in self._transients:
                resolved = self.get_transient(self._transients[type], required=required)
            elif type in self._scoped:
                resolved = self.get_scoped(type, required=required)
            elif type in self._services:
                resolved = self.get_service(type, required=required)
            elif required:
                raise ValueError(f"Unknown dependency: {type}")

            if name is None:
                dependencies[0].append(resolved)
            else:
                dependencies[1][name] = resolved

        return dependencies

    def _create_instance(
        self, cls: type[T] | T, *, type: type[T] | None = None, base: type[Any] | None = None
    ) -> tuple[T, type[T]]:
        if type is None:
            if not isinstance(cls, builtins.type):
                raise ValueError("type must be provided for singleton instances")
            type = cls

        if base is not None:
            if not issubclass(type, base):
                raise ValueError(f"Type {type} must be a subclass of {base}")

        if isinstance(cls, builtins.type):
            dependancies = _get_dependencies(cls)
            args, kwargs = self._resolve_dependencies(dependancies)
            instance = cls(*args, **kwargs)
        else:
            instance = cls

        if not isinstance(instance, type):
            raise ValueError(f"Type {cls} is not a subclass of {type}")

        return instance, type  # type: ignore  # I've got no idea what the type-checker is thinking

    @overload
    def add_singleton(self, cls: type[T], /, *, type: type[T] | None = ...) -> Self: ...

    @overload
    def add_singleton(self, cls: T, /, *, type: type[T] = ...) -> Self: ...

    def add_singleton(self, cls: type[T] | T, *, type: type[T] | None = None) -> Self:
        """Adds a singleton to the application.

        Parameters
        ----------
        cls: :class:`type`
            The singleton class or instance to add.
        type: Optional[:class:`type`]
            The type of the singleton. If not provided, the type of the class is used.
        """
        instance, type = self._create_instance(cls, type=type)
        self._singletons[type] = instance
        return self

    def add_transient(self, cls: type, *, type: type | None = None) -> Self:
        """Adds a transient service to the application.

        Parameters
        ----------
        cls: :class:`type`
            The transient service class to add.
        type: Optional[:class:`type`]
            The type of the transient. If not provided, the type of the class is used.
        """
        if type is None:
            type = cls

        if type in self._transients:
            raise ValueError(f"Transient already exists: {type}")

        self._resolve_dependencies(_get_dependencies(cls))
        self._transients[type] = cls
        return self

    def add_scoped(self, cls: type, *, type: type | None = None) -> Self:
        """Adds a scoped service to the application.

        Parameters
        ----------
        cls: :class:`type`
            The scoped service class to add.
        type: Optional[:class:`type`]
            The type of the scoped. If not provided, the type of the class is used.
        """
        if type is None:
            type = cls

        if type in self._scoped:
            raise ValueError(f"Scoped already exists: {type}")

        self._resolve_dependencies(_get_dependencies(cls))
        self._scoped[type] = cls
        return self

    def add_service(self, cls: type[T_SVC] | T_SVC, *, type: type[T_SVC] | None = None) -> Self:
        """Adds a service to the application.

        Parameters
        ----------
        cls: :class:`type`
            The service class to add.
        type: Optional[:class:`type`]
            The type of the service. If not provided, the type of the class is used.
        """
        instance, type = self._create_instance(cls, type=type, base=ServiceProto)
        self._services[type] = instance
        instance._register()
        return self

    @overload
    def get_transient(self, type: type[T], /, *, required: Literal[True]) -> T: ...

    @overload
    def get_transient(self, type: type[T], /, *, required: bool = ...) -> T | None: ...

    def get_singleton(self, type: type[T], /, *, required: bool = True) -> T | None:
        """Retrieves a singleton from the application.

        Parameters
        ----------
        type: :class:`type`
            The type of the singleton to retrieve.
        """
        if type not in self._singletons:
            if required:
                raise ValueError(f"Singleton not found: {type}")
            return None

        return self._singletons[type]

    @overload
    def get_transient(self, type: type[T], /, *, required: Literal[True]) -> T: ...

    @overload
    def get_transient(self, type: type[T], /, *, required: bool = ...) -> T | None: ...

    def get_transient(self, type: type[T], /, *, required: bool = True) -> T | None:
        """Retrieves a transient from the application.

        Parameters
        ----------
        type: :class:`type`
            The type of the transient to retrieve.
        """
        if type not in self._transients:
            if required:
                raise ValueError(f"Transient not found: {type}")
            return None

        instance, _ = self._create_instance(self._transients[type], type=type)
        return instance

    @overload
    def get_scoped(self, type: type[T], /, *, required: Literal[True]) -> T: ...

    @overload
    def get_scoped(self, type: type[T], /, *, required: bool = ...) -> T | None: ...

    def get_scoped(self, type: type[T], /, *, required: bool = True) -> T | None:
        """Retrieves a scoped from the application.

        Parameters
        ----------
        type: :class:`type`
            The type of the scoped to retrieve.
        """
        if type not in self._scoped:
            if required:
                raise ValueError(f"Scoped not found: {type}")
            return None

        context = self._contexts.get()

        if type not in context:
            instance, _ = self._create_instance(self._scoped[type], type=type)
            context[type] = instance

        return context[type]

    @overload
    def get_service(self, type: type[T_SVC], /, *, required: Literal[True]) -> T_SVC: ...

    @overload
    def get_service(self, type: type[T_SVC], /, *, required: bool = ...) -> T_SVC | None: ...

    def get_service(self, type: type[T_SVC], /, *, required: bool = True) -> T_SVC | None:
        """Retrieves a service from the application.

        Parameters
        ----------
        type: :class:`type`
            The type of the required service to retrieve.
        required: :class:`bool`
            Whether the service is required. If ``True``, an exception will be raised if the service is not found.
        """
        if type not in self._services:
            if required:
                raise ValueError(f"Service not found: {type}")
            return None

        return self._services[type]

    @overload
    def singleton(self, cls: type[T], /, type: type[T] = ...) -> type[T]: ...

    @overload
    def singleton(self, cls: Any = ..., /, type: type[T] = ...) -> Callable[[type[T]], type[T]]: ...

    def singleton(self, cls: type[T] = MISSING, /, type: type[T] = MISSING) -> type[T] | Callable[[type[T]], type[T]]:
        """|deco|

        Adds a singleton to the application.

        Parameters
        ----------
        cls: Optional[:class:`type`]
            The singleton class to add.
        type: Optional[:class:`type`]
            The type of the singleton. If not provided, the type of the class is used.
        """
        if cls is MISSING:
            if type is MISSING:
                raise ValueError("Either cls or type must be provided")
            return lambda cls: self.singleton(cls, type=type)

        if type is MISSING:
            type = cls

        self.add_singleton(cls, type=type)
        return cls

    @overload
    def service(self, cls: type[T_SVC], /, type: type[T_SVC] = ...) -> type[T_SVC]: ...

    @overload
    def service(self, cls: Any = ..., /, type: type[T_SVC] = ...) -> Callable[[type[T_SVC]], type[T_SVC]]: ...

    def service(
        self, cls: type[T_SVC] = MISSING, /, type: type[T_SVC] = MISSING
    ) -> type[T_SVC] | Callable[[type[T_SVC]], type[T_SVC]]:
        """|deco|

        Adds a service to the application.

        Parameters
        ----------
        cls: :class:`type`
            The service class to add.
        """

        if cls is MISSING:
            if type is MISSING:
                raise ValueError("Either cls or type must be provided")
            return lambda cls: self.service(cls, type=type)

        if type is MISSING:
            type = cls

        self.add_service(cls, type=type)
        return cls

    async def start(self, *, timeout: float | None = None) -> None:
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
        async with self._lock:

            if self._starting.is_set() or self._started.is_set():
                raise RuntimeError("Application is already running")
            elif self._stopping.is_set():  # Note: this shouldn't be possible
                raise RuntimeError("Application is stopping")

            self._starting.set()

            coros = []
            for service in self._services.values():
                coros.append(service._start())

            try:
                await asyncio.wait_for(
                    asyncio.gather(*coros), timeout=timeout
                )  # TODO: Maybe timeout per service, allows for better debugging
            finally:
                self._starting.clear()

            self._stopped.clear()
            self._started.set()

    async def run(self, *, timeout: float | None = None) -> None:
        """|coro|

        Starts the application and all services, then waits for the application to stop.

        .. Note::

            This method will not return until the application is stopped.

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
        await self.start(timeout=timeout)

        try:
            await self.stopped
        except asyncio.CancelledError as e:
            await self.stop()

    async def stop(self) -> None:
        """|coro|

        Stops the application and all services.

        .. Warning::

            Exceptions raised by stopping services are discarded.
        """
        async with self._lock:

            if not self._started.is_set():
                raise RuntimeError("Application is not running")
            elif self._stopping.is_set():
                raise RuntimeError("Application is already stopping")
            elif self._stopped.is_set():  # Note: this shouldn't be possible
                raise RuntimeError("Application is already stopped")

            self._stopping.set()

            coros = []
            for service in self._services.values():
                coros.append(service._stop())

            try:
                await asyncio.gather(*coros)
            finally:
                self._stopping.clear()

            self._started.clear()
            self._stopped.set()

    @property
    def state(self) -> ApplicationState:
        """The state of the application."""
        if self._starting.is_set():
            return ApplicationState.STARTING
        elif self._stopping.is_set():
            return ApplicationState.STOPPING
        elif self._started.is_set():
            return ApplicationState.STARTED
        elif self._stopped.is_set():
            return ApplicationState.STOPPED

        return ApplicationState.UNKNOWN

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
