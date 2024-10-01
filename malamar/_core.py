from __future__ import annotations

import asyncio
import builtins
import inspect
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, TypeVar, get_type_hints, overload

from ._service import ServiceProto
from ._utils import MISSING
from .services import ApplicationLifetime

if TYPE_CHECKING:
    from typing_extensions import Self

__all__ = (
    "Application",
    "ApplicationLifetime",
)

T = TypeVar("T")
T_SVC = TypeVar("T_SVC", bound=ServiceProto)


def _get_dependencies(cls: type) -> list[type]:
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

    parameters = iter(signature.parameters)
    next(parameters)  # Skip self

    for parameter in parameters:
        if parameter not in annotations:
            raise ValueError(f"Missing type hint for parameter: {parameter}")

        dependencies.append(annotations[parameter])

    return dependencies


class Application:
    """The class responsible for managing the application and its services."""

    def __init__(self):
        """Creates a new Application instance."""
        self._singletons: dict[type[Any], Any] = {}
        self._transients: dict[type[Any], type[Any]] = {}
        # scoped? ContextVar?
        self._required_services: dict[type[ServiceProto], ServiceProto] = {}
        self._services: dict[type[ServiceProto], list[ServiceProto]] = defaultdict(list)
        self._stopped: asyncio.Event = asyncio.Event()
        self._stopped.set()

        self.add_required_service(ApplicationLifetime(self), type=ApplicationLifetime)

    def _resolve_dependencies(self, types: list[type]) -> list[Any]:
        dependencies = []
        for dependency in types:
            if dependency in self._singletons:
                dependencies.append(self._singletons[dependency])
            elif dependency in self._transients:
                dependencies.append(self.get_transient(self._transients[dependency]))
            elif dependency in self._required_services:
                dependencies.append(self._required_services[dependency])
            else:
                raise ValueError(f"Unknown dependency: {dependency}")
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
            instance = cls(*self._resolve_dependencies(dependancies))
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
            The singleton class to add.
        type: Optional[:class:`type`]
            The type of the singleton. If not provided, the type of the class is used.
        """
        instance, type = self._create_instance(cls, type=type)
        self._singletons[type] = instance
        return self

    def add_transient(self, cls: type, *, type: type | None = None) -> Self:
        """Adds a transient to the application.

        Parameters
        ----------
        cls: :class:`type`
            The transient class to add.
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

    def add_required_service(self, cls: type[T_SVC] | T_SVC, *, type: type[T_SVC] | None = None) -> Self:
        """Adds a required service to the application.

        Parameters
        ----------
        cls: :class:`type`
            The required service class to add.
        type: Optional[:class:`type`]
            The type of the required service. If not provided, the type of the class is used.
        """
        instance, type = self._create_instance(cls, type=type, base=ServiceProto)
        self._required_services[type] = instance
        instance._register()
        return self

    def _add_service(self, cls: type[T_SVC] | T_SVC, *, type: type[T_SVC] | None) -> Self:
        instance, type = self._create_instance(cls, type=type, base=ServiceProto)
        self._services[type].append(instance)
        instance._register()
        return self

    def add_service(self, cls: type[T_SVC] | T_SVC, *, type: type[T_SVC] | None = None, required: bool = False) -> Self:
        """Adds a service to the application.

        Parameters
        ----------
        cls: :class:`type`
            The service class to add.
        type: Optional[:class:`type`]
            The type of the service. If not provided, the type of the class is used.
        required: :class:`bool`
            Whether the service is required. If ``True``, the service will be added as a required service.
        """
        if required:
            return self.add_required_service(cls, type=type)
        else:
            return self._add_service(cls, type=type)

    def get_singleton(self, type: type[T]) -> T:
        """Retrieves a singleton from the application.

        Parameters
        ----------
        type: :class:`type`
            The type of the singleton to retrieve.
        """
        return self._singletons[type]

    def get_transient(self, type: type[T]) -> T:
        """Retrieves a transient from the application.

        Parameters
        ----------
        type: :class:`type`
            The type of the transient to retrieve.
        """
        if type not in self._transients:
            raise ValueError(f"Unknown transient type: {type}")
        instance, _ = self._create_instance(self._transients[type], type=type)
        return instance

    def get_required_service(self, type: type[T_SVC]) -> T_SVC:
        """Retrieves a required service from the application.

        Parameters
        ----------
        type: :class:`type`
            The type of the required service to retrieve.
        """
        return self._required_services[type]  # type: ignore

    def get_services(self, type: type[T_SVC]) -> Iterable[T_SVC]:
        """Retrieves all services of a given type from the application.

        Parameters
        ----------
        type: :class:`type`
            The type of the services to retrieve.
        """
        services: list[T_SVC] = self._services.get(type, [])  # type: ignore
        return iter(services)

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
        if not self._stopped.is_set():
            raise RuntimeError("Application is already running")

        self._stopped.clear()

        coros = []
        for service_type in self._services:
            for service in self._services[service_type]:
                coros.append(service._start())

        await asyncio.wait_for(
            asyncio.gather(*coros), timeout=timeout
        )  # TODO: Maybe timeout per service, allows for better debugging

    def run(self, *, startup_timeout: float | None = None) -> None:
        """
        Starts the application and all services, then waits for the application to stop.

        .. Note::

            This method will not return until the application is stopped.

        Parameters
        ----------
        startup_timeout: Optional[:class:`float`]
            The maximum number of seconds to allow for all services to start.
            If ``None``, no timeout is applied.

        Raises
        ------
        asyncio.TimeoutError
            A service did not start within the specified timeout.
        """

        async def runner():
            await self.start(timeout=startup_timeout)

            try:
                await self.wait()
            except asyncio.CancelledError:
                await self.stop()

        asyncio.run(runner())

    async def stop(self) -> None:
        """|coro|

        Stops the application and all services.

        .. Warning::

            Exceptions raised by stopping services are discarded.
        """
        coros = []
        for service_type in self._services:
            for service in self._services[service_type]:
                coros.append(service._stop())

        await asyncio.gather(*coros)

        self._stopped.set()

    async def wait(self) -> None:
        """|coro|

        Waits for the application to stop.

        .. Note::

            This method will not return until the application is stopped.
        """
        await self._stopped.wait()

    @property
    def lifetime(self) -> ApplicationLifetime:
        """:class:`ApplicationLifetime`: The application lifetime service."""
        return self.get_required_service(ApplicationLifetime)
