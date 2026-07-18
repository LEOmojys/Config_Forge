"""Event Bus: thread-safe event store for SSE streaming.

Orchestrator pushes events during generation in a background thread.
SSE endpoint polls events and streams to the client.
"""
import asyncio
import json
import time
from threading import Lock
from typing import Optional


class EventBus:
    """In-memory event store with async-compatible polling."""

    def __init__(self):
        self._events: dict[str, list[dict]] = {}  # job_id -> [events]
        self._lock = Lock()
        self._dones: set[str] = set()  # job_ids that have finished

    def push(self, job_id: str, event_type: str, data: dict):
        """Push an event from the orchestrator (thread-safe)."""
        with self._lock:
            if job_id not in self._events:
                self._events[job_id] = []
            self._events[job_id].append({
                "type": event_type,
                "timestamp": time.time(),
                "data": data,
            })

    def mark_done(self, job_id: str, final_data: dict):
        """Mark a job as complete with the final result."""
        self.push(job_id, "done", final_data)
        with self._lock:
            self._dones.add(job_id)

    def mark_error(self, job_id: str, error: str):
        """Mark a job as failed."""
        self.push(job_id, "error", {"message": str(error)})
        with self._lock:
            self._dones.add(job_id)

    def get_new_events(self, job_id: str, since_idx: int) -> tuple[list[dict], bool]:
        """Get events since given index. Returns (events, is_done)."""
        with self._lock:
            all_events = self._events.get(job_id, [])
            new = all_events[since_idx:]
            is_done = job_id in self._dones
            return new, is_done

    async def stream(self, job_id: str):
        """Async generator: yields SSE-formatted strings."""
        seen = 0
        while True:
            events, done = self.get_new_events(job_id, seen)
            for evt in events:
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                seen += 1
            if done:
                yield f"data: {json.dumps({'type': 'close', 'data': {}}, ensure_ascii=False)}\n\n"
                return
            await asyncio.sleep(0.3)  # poll every 300ms


# Global singleton
event_bus = EventBus()
