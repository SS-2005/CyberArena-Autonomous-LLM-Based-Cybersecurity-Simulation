import asyncio
import threading
from typing import Dict, List, Optional, AsyncIterator
from backend.schemas.agent import AgentEvent
from backend.utils.logger import logger


class AgentEventBroadcaster:
    """
    In-memory pub/sub event broadcaster for real-time agent telemetry.
    Thread-safe to support event emission from background worker threads to async SSE endpoints.
    Maintains per-agent event history for reconnecting clients.
    """

    def __init__(self, max_history_per_agent: int = 300):
        self.max_history_per_agent = max_history_per_agent
        self._history: Dict[str, List[AgentEvent]] = {}
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, event: AgentEvent) -> None:
        """Publish an event to all subscribers of the agent and record to history."""
        with self._lock:
            if event.agent_id not in self._history:
                self._history[event.agent_id] = []
            self._history[event.agent_id].append(event)
            if len(self._history[event.agent_id]) > self.max_history_per_agent:
                self._history[event.agent_id].pop(0)

            queues = list(self._subscribers.get(event.agent_id, []))

        for q in queues:
            try:
                if self._loop and self._loop.is_running():
                    self._loop.call_soon_threadsafe(q.put_nowait, event)
                else:
                    q.put_nowait(event)
            except Exception as e:
                logger.debug(f"Failed to dispatch event to subscriber queue: {e}")

    def get_history(self, agent_id: str) -> List[AgentEvent]:
        """Retrieve recent buffered events for an agent."""
        with self._lock:
            return list(self._history.get(agent_id, []))

    async def subscribe(self, agent_id: str) -> AsyncIterator[AgentEvent]:
        """
        Subscribe to live events for a specific agent.
        First replays historical events, then yields incoming real-time events.
        """
        q: asyncio.Queue = asyncio.Queue()
        self._loop = asyncio.get_running_loop()

        with self._lock:
            if agent_id not in self._subscribers:
                self._subscribers[agent_id] = []
            self._subscribers[agent_id].append(q)
            past_events = list(self._history.get(agent_id, []))

        # Replay past events
        for past_event in past_events:
            yield past_event
            await asyncio.sleep(0.001)

        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=10.0)
                    if event is None:
                        break
                    yield event
                except asyncio.TimeoutError:
                    # Keep-alive ping comment
                    yield AgentEvent(
                        agent_id=agent_id,
                        event_type="ping",
                        timestamp="",
                    )
        finally:

            with self._lock:
                if agent_id in self._subscribers and q in self._subscribers[agent_id]:
                    self._subscribers[agent_id].remove(q)
                    if not self._subscribers[agent_id]:
                        self._subscribers.pop(agent_id, None)

    def clear_agent(self, agent_id: str) -> None:
        """Purge all event history and subscribers for a deleted agent."""
        with self._lock:
            self._history.pop(agent_id, None)
            queues = self._subscribers.pop(agent_id, [])

        for q in queues:
            try:
                if self._loop and self._loop.is_running():
                    self._loop.call_soon_threadsafe(q.put_nowait, None)
                else:
                    q.put_nowait(None)
            except Exception:
                pass


# Global singleton broadcaster
event_broadcaster = AgentEventBroadcaster()
