from __future__ import annotations

import asyncio
import builtins
import inspect
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextvars import ContextVar
from os import urandom
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, TypeVar, get_args, get_origin, get_type_hints, overload

from ._service import Service
from ._utils import MISSING, _get_optional_type

if TYPE_CHECKING:
    from typing_extensions import Self

__all__ = ("Application",)

T = TypeVar("T")
T_SVC = TypeVar("T_SVC", bound=Service)


class _Dependency(NamedTuple):
    name: str | None
    type: type | Sequence[type]
    required: bool
    multiple: bool


def _get_dependencies(cls: type) -> Sequence[_Dependency]:
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

        optional, dependency = _get_optional_type(annotations[parameter.name])
        multiple = False

        origin = get_origin(dependency)
        if origin is not None:

            if issubclass(origin, Iterable):
                multiple = True

            dependency = get_args(dependency)

        name = None
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            name = parameter.name

        dependencies.append(_Dependency(name, dependency, not optional, multiple))

    return dependencies


class Application(Service):
    """The class responsible for managing the application and its services."""

    def __init__(self):
        """Creates a new Application instance."""
        super().__init__()

        self._singletons: dict[type[Any], Any | list[Any]] = {Application: self, type(self): self}
        self._transients: dict[type[Any], type[Any]] = {}
        self._scoped: dict[type[Any], type[Any]] = {}
        self._contexts: ContextVar[dict[type[Any], Any]] = ContextVar(
            f"malamar.{self.__class__.__name__}.{urandom(16).hex()}.context", default={}
        )
        self._services: dict[type[Service], Service] = {}

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
        coros = []
        for service in self._services.values():
            coros.append(service.start())

        await asyncio.gather(*coros)

    async def stop(self, *, timeout: float | None = None) -> None:
        """|coro|

        Stops the application and all services.

        .. Warning::

            Exceptions raised by stopping services are discarded.
        """
        coros = []
        for service in self._services.values():
            coros.append(service.stop())

        await asyncio.gather(*coros)

    def _resolve_dependency(self, type: type, multiple: bool) -> Any | None:
        dependency = None
        if type in self._singletons:
            if multiple:
                dependency = self.get_singletons(type)
            else:
                dependency = self.get_singleton(type)
        elif type in self._transients:
            dependency = self.get_transient(self._transients[type])
        elif type in self._scoped:
            dependency = self.get_scoped(type)
        elif type in self._services:
            dependency = self.get_service(type)

        return dependency

    def _resolve_dependencies(self, types: Sequence[_Dependency]) -> tuple[Sequence[Any], Mapping[str, Any]]:
        dependencies = ([], {})
        for dependency in types:
            name, idk, required, multiple = dependency

            resolved = None
            if not isinstance(idk, Sequence):
                idk = [idk]

            for type in idk:
                resolved = self._resolve_dependency(type, multiple=multiple)
                if resolved is not None:
                    break
            else:
                if required:
                    raise ValueError(f"Required dependency not found: {dependency.type}")

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
        if type in self._singletons:
            if isinstance(self._singletons[type], list):
                self._singletons[type].append(instance)
            else:
                self._singletons[type] = [self._singletons[type], instance]
        else:
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
        instance, type = self._create_instance(cls, type=type, base=Service)
        self._services[type] = instance
        # instance._register()
        return self

    @overload
    def get_singleton(self, type: type[T], /, *, required: Literal[True]) -> T: ...

    @overload
    def get_singleton(self, type: type[T], /, *, required: bool = ...) -> T | None: ...

    def get_singleton(self, type: type[T], /, *, required: bool = True) -> T | None:
        """Retrieves a singleton from the application.

        Parameters
        ----------
        type: :class:`type`
            The type of the singleton to retrieve.
        """
        if type not in self._singletons:
            if required:
                raise ValueError(f"Singleton of type {type} not found")
            return None

        singleton = self._singletons[type]

        if isinstance(singleton, list):
            raise ValueError(f"Multiple singletons of type {type} found")

        return singleton

    @overload
    def get_singletons(self, type: type[T], /, *, required: Literal[True]) -> list[T]: ...

    @overload
    def get_singletons(self, type: type[T], /, *, required: bool = ...) -> list[T] | None: ...

    def get_singletons(self, type: type[T], /, *, required: bool = True) -> list[T] | None:
        """Retrieves all singletons of a type from the application.

        Parameters
        ----------
        type: :class:`type`
            The type of the singletons to retrieve.
        """
        if type not in self._singletons:
            if required:
                raise ValueError(f"Singletons of type {type} not found")
            return None

        singletons = self._singletons[type]

        if not isinstance(singletons, list):
            singletons = [singletons]

        return singletons

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
