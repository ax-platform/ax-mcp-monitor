"""Lightweight asynchronous message queue helper for the MCP monitor."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class MessageJob:
    """Container for queued monitor work."""

    id: str
    created_at: float
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


class MessageQueue:
    """Simple FIFO queue abstraction backed by ``asyncio.Queue``."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[MessageJob] = asyncio.Queue()

    async def enqueue(self, payload: Dict[str, Any], *, metadata: Optional[Dict[str, Any]] = None) -> MessageJob:
        """Create a job and place it on the queue."""

        job = MessageJob(
            id=str(uuid.uuid4()),
            created_at=time.time(),
            payload=payload,
            metadata=metadata or {},
        )
        await self._queue.put(job)
        return job

    async def get(self) -> MessageJob:
        """Retrieve the next job (awaits until one is available)."""

        return await self._queue.get()

    def task_done(self) -> None:
        """Mark the most recently retrieved job as processed."""

        self._queue.task_done()

    def size(self) -> int:
        """Return the number of pending jobs (best-effort)."""

        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    async def drain(self) -> None:
        """Wait until all queued jobs have been processed."""

        await self._queue.join()
