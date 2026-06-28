"""
In-memory async Pub/Sub

Topic-based fan-out using asyncio.Queue per subscriber.
Designed for 1000+ concurrent WebSocket connections.

Topic format: "BTCUSDT:1m", "ETHUSDT:5m", etc.
"""

import asyncio

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class PubSub:
    def __init__(self) -> None:
        # topic -> set of subscriber queues
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, topic: str) -> asyncio.Queue:
        """Return a new queue subscribed to this topic."""
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        if topic not in self._subscribers:
            self._subscribers[topic] = set()
        self._subscribers[topic].add(q)
        return q

    def unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        if topic in self._subscribers:
            self._subscribers[topic].discard(queue)
            if not self._subscribers[topic]:
                del self._subscribers[topic]

    async def publish(self, topic: str, message: dict) -> None:
        """Fan-out message to all subscribers of this topic."""
        subs = self._subscribers.get(topic)
        if not subs:
            return
        dead: list[asyncio.Queue] = []
        for q in list(subs):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                # Slow consumer — drop this message for them
                dead.append(q)
            except Exception as e:
                logger.warning(f"PubSub publish error on topic {topic}: {e}")
                dead.append(q)
        for q in dead:
            self.unsubscribe(topic, q)

    def subscriber_count(self, topic: str) -> int:
        return len(self._subscribers.get(topic, set()))

    def total_subscribers(self) -> int:
        return sum(len(s) for s in self._subscribers.values())
