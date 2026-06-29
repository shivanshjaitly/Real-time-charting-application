"""
Aggregation Engine

1m candles are the only source data. Higher intervals (5m, 15m, 1h, 1d) are
derived exclusively via process_1m_candle().

Live path:
  sub-minute tick → in-progress 1m candle → roll up to higher intervals

Aggregation rules (Requirement.md §03):
  open   = first sub-candle's open  — never changes once set
  close  = last sub-candle's close  — updates on every 1m tick
  high   = max across all sub-candles in window
  low    = min across all sub-candles in window
  volume = cumulative sum of sub-candle volumes
"""

from dataclasses import replace

from src.domain.entities.candle import Candle
from src.domain.entities.symbol import HIGHER_INTERVALS, Interval, topic_key
from src.domain.services.time_utils import floor_to_interval


class AggregationEngine:
    """
    Maintains open (in-progress) candles for 1m and all higher intervals.

    Structure:
        _open_1m[symbol] = Candle
        _open_higher[symbol][interval] = Candle
    """

    def __init__(self) -> None:
        self._open_1m: dict[str, Candle] = {}
        self._open_higher: dict[str, dict[Interval, Candle]] = {}

    def process_tick(self, symbol: str, tick: Candle, now_ms: int) -> list[tuple[str, Candle]]:
        """
        Accumulate a sub-minute tick into the 1m candle, then derive higher intervals.

        Returns updates for 1m plus every higher interval (window-start timestamps).
        """
        window_start = floor_to_interval(now_ms, Interval.ONE_MINUTE)
        existing_1m = self._open_1m.get(symbol)

        if existing_1m is None or existing_1m.timestamp != window_start:
            candle_1m = Candle(
                timestamp=window_start,
                open=tick.open,
                high=tick.high,
                low=tick.low,
                close=tick.close,
                volume=tick.volume,
            )
            self._open_1m[symbol] = candle_1m
        else:
            existing_1m.high = max(existing_1m.high, tick.high)
            existing_1m.low = min(existing_1m.low, tick.low)
            existing_1m.close = tick.close
            existing_1m.volume += tick.volume
            candle_1m = existing_1m

        updates: list[tuple[str, Candle]] = [
            (topic_key(symbol, Interval.ONE_MINUTE.value), candle_1m)
        ]
        updates.extend(self.process_1m_candle(symbol, candle_1m))
        return updates

    def process_1m_candle(self, symbol: str, candle_1m: Candle) -> list[tuple[str, Candle]]:
        """
        Derive higher-interval candles from one 1m candle (complete or in-progress).

        Does not modify the 1m series — only rolls up into 5m / 15m / 1h / 1d.
        """
        updates: list[tuple[str, Candle]] = []

        if symbol not in self._open_higher:
            self._open_higher[symbol] = {}

        for interval in HIGHER_INTERVALS:
            window_start = floor_to_interval(candle_1m.timestamp, interval)
            existing = self._open_higher[symbol].get(interval)

            if existing is None or existing.timestamp != window_start:
                new_candle = Candle(
                    timestamp=window_start,
                    open=candle_1m.open,
                    high=candle_1m.high,
                    low=candle_1m.low,
                    close=candle_1m.close,
                    volume=candle_1m.volume,
                )
                self._open_higher[symbol][interval] = new_candle
            else:
                existing.high = max(existing.high, candle_1m.high)
                existing.low = min(existing.low, candle_1m.low)
                existing.close = candle_1m.close
                existing.volume += candle_1m.volume

            updated = self._open_higher[symbol][interval]
            updates.append((topic_key(symbol, interval.value), updated))

        return updates

    def get_open_candle(self, symbol: str, interval: Interval) -> Candle | None:
        if interval == Interval.ONE_MINUTE:
            return self._open_1m.get(symbol)
        return self._open_higher.get(symbol, {}).get(interval)

    def load_open_higher_candles(self, symbol: str, candles: dict[Interval, Candle]) -> None:
        """Restore in-progress higher-interval candles (used after history replay)."""
        if not candles:
            return
        if symbol not in self._open_higher:
            self._open_higher[symbol] = {}
        for interval, candle in candles.items():
            self._open_higher[symbol][interval] = replace(candle)

    def replay_1m_history(
        self,
        symbol: str,
        candles_1m: list[Candle],
    ) -> tuple[dict[Interval, list[Candle]], dict[Interval, Candle]]:
        """
        Replay completed 1m history and return higher-interval series plus open candles.

        Used for seeding — same rules as process_1m_candle(), optimized for bulk replay.
        """
        completed: dict[Interval, list[Candle]] = {iv: [] for iv in HIGHER_INTERVALS}
        prev: dict[Interval, Candle | None] = {iv: None for iv in HIGHER_INTERVALS}

        if symbol not in self._open_higher:
            self._open_higher[symbol] = {}

        for candle_1m in candles_1m:
            for interval in HIGHER_INTERVALS:
                window_start = floor_to_interval(candle_1m.timestamp, interval)
                existing = self._open_higher[symbol].get(interval)

                if existing is None or existing.timestamp != window_start:
                    if existing is not None:
                        completed[interval].append(replace(existing))
                    existing = Candle(
                        timestamp=window_start,
                        open=candle_1m.open,
                        high=candle_1m.high,
                        low=candle_1m.low,
                        close=candle_1m.close,
                        volume=candle_1m.volume,
                    )
                    self._open_higher[symbol][interval] = existing
                else:
                    existing.high = max(existing.high, candle_1m.high)
                    existing.low = min(existing.low, candle_1m.low)
                    existing.close = candle_1m.close
                    existing.volume += candle_1m.volume

                prev[interval] = existing

        open_candles: dict[Interval, Candle] = {}
        for interval in HIGHER_INTERVALS:
            if prev[interval] is not None:
                snap = replace(prev[interval])
                if not completed[interval] or completed[interval][-1].timestamp != snap.timestamp:
                    completed[interval].append(snap)
                open_candles[interval] = replace(prev[interval])

        return completed, open_candles

    def reset(self) -> None:
        self._open_1m.clear()
        self._open_higher.clear()
