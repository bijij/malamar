from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .._core import Application

from .._service import Service

__all__ = ("ApplicationLifetime",)


class ApplicationLifetime(Service):
    """Provides application lifetime event handling and control.

    .. Note::

        This class is automatically registered with the application as a required service.
    """

    def __init__(self, app: Application) -> None:
        """Initializes the application lifetime service."""
        self._app: Application = app
        self._started: asyncio.Event = asyncio.Event()
        self._stopping: asyncio.Event = asyncio.Event()

    async def start(self) -> None:
        self._started.set()

    async def stop(self) -> None:
        self._stopping.set()
        await self._app.wait()
        self._started.clear()
        self._stopping.clear()

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
    def stopped(self) -> Awaitable[None]:
        """|coroprop|

        An awaitable that resolves when the application has stopped.
        """
        return self._app.wait()

    async def stop_application(self) -> None:
        """|coro|

        Signals for the application to stop.
        """
        await self._app.stop()
