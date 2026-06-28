"""
Candle Store

In-memory ring buffer (deque) storing last 200 candles per topic.
Updated on every published candle. Used to serve historical data.
"""

from collections import deque

from src.domain.entities.candle import Candle

MAX_CANDLES = 200


class CandleStore:
    def __init__(self) -> None:
        self._store: dict[str, deque[Candle]] = {}

    def append(self, topic: str, candle: Candle) -> None:
        if topic not in self._store:
            self._store[topic] = deque(maxlen=MAX_CANDLES)

        buf = self._store[topic]
        # Update last candle if same timestamp (live in-progress update)
        if buf and buf[-1].timestamp == candle.timestamp:
            buf[-1] = candle
        else:
            buf.append(candle)

    def get_history(self, topic: str) -> list[Candle]:
        return list(self._store.get(topic, []))

    def seed(self, topic: str, candles: list[Candle]) -> None:
        """Pre-populate store with historical candles."""
        if topic not in self._store:
            self._store[topic] = deque(maxlen=MAX_CANDLES)
        for c in candles[-MAX_CANDLES:]:
            self._store[topic].append(c)
