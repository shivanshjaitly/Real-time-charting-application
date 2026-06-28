"""
Aggregation Engine

Derives 5m, 15m, 1h, 1d candles from 1-minute data ONLY.

Aggregation rules (from Requirement.md §03):
  open   = first sub-candle's open  — never changes once set
  close  = last sub-candle's close  — updates on every 1m tick
  high   = max across all sub-candles in window
  low    = min across all sub-candles in window
  volume = cumulative sum of all sub-candle volumes
"""

from src.domain.entities.candle import Candle
from src.domain.entities.symbol import HIGHER_INTERVALS, INTERVAL_MS, Interval, topic_key


class AggregationEngine:
    """
    Maintains open (in-progress) candles for every higher interval.

    Structure:
        _open_candles[symbol][interval] = Candle (current in-progress window)
    """

    def __init__(self) -> None:
        # symbol -> interval -> in-progress Candle
        self._open_candles: dict[str, dict[Interval, Candle]] = {}

    def process_1m_candle(self, symbol: str, candle_1m: Candle) -> list[tuple[str, Candle]]:
        """
        Process a new 1m candle and return updated higher-interval candles.

        Returns:
            List of (topic_key, updated_candle) for every interval that was updated.
        """
        updates: list[tuple[str, Candle]] = []

        if symbol not in self._open_candles:
            self._open_candles[symbol] = {}

        for interval in HIGHER_INTERVALS:
            interval_ms = INTERVAL_MS[interval]
            window_start = (candle_1m.timestamp // interval_ms) * interval_ms

            existing = self._open_candles[symbol].get(interval)

            if existing is None or existing.timestamp != window_start:
                # New window — open is always the first sub-candle's open
                new_candle = Candle(
                    timestamp=window_start,
                    open=candle_1m.open,
                    high=candle_1m.high,
                    low=candle_1m.low,
                    close=candle_1m.close,
                    volume=candle_1m.volume,
                )
                self._open_candles[symbol][interval] = new_candle
            else:
                # Existing window — update in place
                existing.high = max(existing.high, candle_1m.high)
                existing.low = min(existing.low, candle_1m.low)
                existing.close = candle_1m.close        # always last
                existing.volume += candle_1m.volume     # cumulative sum
                # open is deliberately NOT touched

            updated = self._open_candles[symbol][interval]
            updates.append((topic_key(symbol, interval.value), updated))

        return updates

    def get_open_candle(self, symbol: str, interval: Interval) -> Candle | None:
        return self._open_candles.get(symbol, {}).get(interval)

    def reset(self) -> None:
        self._open_candles.clear()
