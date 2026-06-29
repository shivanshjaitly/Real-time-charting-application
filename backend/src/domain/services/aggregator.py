"""
Aggregation Engine

Maintains open (in-progress) candles for every interval (1m, 5m, 15m, 1h, 1d).

Each price tick updates the current window in place. When the wall-clock
window changes, a new candle opens automatically on the next tick.

Aggregation rules (from Requirement.md §03):
  open   = first tick's open  — never changes once set
  close  = last tick's close    — updates on every tick
  high   = max across all ticks in window
  low    = min across all ticks in window
  volume = cumulative sum of tick volumes
"""

from src.domain.entities.candle import Candle
from src.domain.entities.symbol import ALL_INTERVALS, Interval, topic_key
from src.domain.services.time_utils import floor_to_interval


class AggregationEngine:
    """
    Maintains open (in-progress) candles for every interval.

    Structure:
        _open_candles[symbol][interval] = Candle (current in-progress window)
    """

    def __init__(self) -> None:
        self._open_candles: dict[str, dict[Interval, Candle]] = {}

    def process_tick(self, symbol: str, tick: Candle, now_ms: int) -> list[tuple[str, Candle]]:
        """
        Process a price tick and return updated candles for every interval.

        All returned candles use the window-start timestamp so the chart
        updates the current bar in place until the interval completes.
        """
        updates: list[tuple[str, Candle]] = []

        if symbol not in self._open_candles:
            self._open_candles[symbol] = {}

        for interval in ALL_INTERVALS:
            window_start = floor_to_interval(now_ms, interval)
            existing = self._open_candles[symbol].get(interval)

            if existing is None or existing.timestamp != window_start:
                new_candle = Candle(
                    timestamp=window_start,
                    open=tick.open,
                    high=tick.high,
                    low=tick.low,
                    close=tick.close,
                    volume=tick.volume,
                )
                self._open_candles[symbol][interval] = new_candle
            else:
                existing.high = max(existing.high, tick.high)
                existing.low = min(existing.low, tick.low)
                existing.close = tick.close
                existing.volume += tick.volume

            updated = self._open_candles[symbol][interval]
            updates.append((topic_key(symbol, interval.value), updated))

        return updates

    def process_1m_candle(self, symbol: str, candle_1m: Candle) -> list[tuple[str, Candle]]:
        """Backward-compatible wrapper used when replaying 1m history."""
        return self.process_tick(symbol, candle_1m, candle_1m.timestamp)

    def get_open_candle(self, symbol: str, interval: Interval) -> Candle | None:
        return self._open_candles.get(symbol, {}).get(interval)

    def reset(self) -> None:
        self._open_candles.clear()
