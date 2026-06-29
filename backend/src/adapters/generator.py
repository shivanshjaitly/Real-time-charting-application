"""
Mock 1-Minute Candle Generator

Generates sub-minute price ticks via random walk. Ticks are rolled into 1m
candles by the AggregationEngine; higher intervals are derived from 1m only.

Uses real wall-clock time with calendar-aligned candle windows (local timezone).
"""

import asyncio
import random
import time
from collections.abc import Callable
from typing import Any

from src.domain.entities.candle import Candle
from src.domain.entities.symbol import (
    BASE_PRICES,
    INTERVAL_MS,
    Interval,
    Symbol,
)
from src.domain.services.time_utils import floor_to_interval
from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _generate_tick(prev_close: float) -> Candle:
    """Small OHLCV price movement for one live tick."""
    volatility = 0.0008 + random.gauss(0, 0.0002)
    volatility = max(0.0003, min(0.004, volatility))

    trend = random.gauss(0, 0.00005)
    shock = random.gauss(0, volatility)

    if random.random() < 0.02:
        shock += random.gauss(0, volatility * 2)

    open_ = prev_close
    close = max(0.01, open_ * (1 + trend + shock))

    body_high = max(open_, close)
    body_low = min(open_, close)

    wick = volatility * random.uniform(0.2, 1.5)
    high = body_high * (1 + wick * random.uniform(0.05, 0.8))
    low = max(0.01, body_low * (1 - wick * random.uniform(0.05, 0.8)))

    range_ratio = (high - low) / open_
    volume_base = 8 + open_ * 0.002
    volume_spike = random.uniform(2.0, 5.0) if random.random() < 0.03 else 1.0
    volume = max(1, round(volume_base * (1 + range_ratio * 40) * random.uniform(0.5, 1.5) * volume_spike))

    return Candle(
        timestamp=0,
        open=round(open_, 4),
        high=round(high, 4),
        low=round(low, 4),
        close=round(close, 4),
        volume=volume,
    )


def _generate_hourly_as_1m(prev_close: float, hour_start: int) -> Candle:
    """One synthetic 1m candle representing a full hour (fast deep-history seeding)."""
    volatility = 0.008 + random.gauss(0, 0.001)
    volatility = max(0.003, min(0.025, volatility))

    trend = random.gauss(0, 0.0005)
    shock = random.gauss(0, volatility)
    if random.random() < 0.04:
        shock += random.gauss(0, volatility * 2.5)

    open_ = prev_close
    close = max(0.01, open_ * (1 + trend + shock))

    body_high = max(open_, close)
    body_low = min(open_, close)
    wick = volatility * random.uniform(0.4, 2.0)
    high = body_high * (1 + wick * random.uniform(0.15, 0.9))
    low = max(0.01, body_low * (1 - wick * random.uniform(0.15, 0.9)))

    range_ratio = (high - low) / open_
    volume_base = 25_000 + open_ * 8
    volume_spike = random.uniform(1.5, 3.5) if random.random() < 0.06 else 1.0
    volume = max(
        1,
        round(volume_base * (1 + range_ratio * 40) * random.uniform(0.7, 1.3) * volume_spike),
    )

    return Candle(
        timestamp=hour_start,
        open=round(open_, 4),
        high=round(high, 4),
        low=round(low, 4),
        close=round(close, 4),
        volume=volume,
    )


def _generate_1m_candle(prev_close: float, window_start: int) -> Candle:
    """Generate one completed 1m historical candle."""
    volatility = 0.003 + random.gauss(0, 0.0005)
    volatility = max(0.001, min(0.012, volatility))

    trend = random.gauss(0, 0.0002)
    shock = random.gauss(0, volatility)

    if random.random() < 0.03:
        shock += random.gauss(0, volatility * 3)

    open_ = prev_close
    close = max(0.01, open_ * (1 + trend + shock))

    body_high = max(open_, close)
    body_low = min(open_, close)

    wick = volatility * random.uniform(0.3, 2.5)
    high = body_high * (1 + wick * random.uniform(0.1, 1.0))
    low = max(0.01, body_low * (1 - wick * random.uniform(0.1, 1.0)))

    range_ratio = (high - low) / open_
    volume_base = 500 + open_ * 0.15
    volume_spike = random.uniform(1.8, 4.5) if random.random() < 0.05 else 1.0
    volume = max(1, round(volume_base * (1 + range_ratio * 80) * random.uniform(0.6, 1.4) * volume_spike))

    return Candle(
        timestamp=window_start,
        open=round(open_, 4),
        high=round(high, 4),
        low=round(low, 4),
        close=round(close, 4),
        volume=volume,
    )


class MockDataGenerator:
    """
    Emits sub-minute price ticks for all symbols on a fixed real-time interval.

    Callback signature: async/sync fn(symbol: str, tick: Candle, now_ms: int)
    Only 1m data is produced (via tick accumulation). Higher timeframes are
    derived by AggregationEngine.process_1m_candle().
    """

    def __init__(self) -> None:
        self._last_close: dict[str, float] = {
            sym.value: BASE_PRICES[sym] for sym in Symbol
        }
        self._callbacks: list[Callable[..., Any]] = []
        self._task: asyncio.Task | None = None
        settings = get_settings()
        self._tick_interval = settings.tick_interval_seconds

    def add_callback(self, fn: Callable[..., Any]) -> None:
        self._callbacks.append(fn)

    def set_last_close(self, symbol: str, price: float) -> None:
        """Align live tick prices with the end of seeded history."""
        self._last_close[symbol] = price

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())
            logger.info(f"MockDataGenerator started (tick every {self._tick_interval}s)")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("MockDataGenerator stopped")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._tick_interval)
            now_ms = int(time.time() * 1000)

            for sym in Symbol:
                tick = _generate_tick(self._last_close[sym.value])
                self._last_close[sym.value] = tick.close

                for cb in self._callbacks:
                    try:
                        result = cb(sym.value, tick, now_ms)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        logger.error(f"Generator callback error: {e}")

    def generate_1m_history(self, symbol: str, count: int) -> list[Candle]:
        """Generate calendar-aligned 1m candles ending before the current minute."""
        settings = get_settings()
        fine_tail = min(settings.seed_fine_1m_bars, count)
        if count > fine_tail + 60:
            return self._generate_hybrid_1m_history(symbol, count, fine_tail)
        return self._generate_fine_1m_history(symbol, count)

    def _generate_fine_1m_history(self, symbol: str, count: int) -> list[Candle]:
        interval_ms = INTERVAL_MS[Interval.ONE_MINUTE]
        now_ms = int(time.time() * 1000)
        current_window = floor_to_interval(now_ms, Interval.ONE_MINUTE)
        start_ts = current_window - count * interval_ms

        price = BASE_PRICES.get(Symbol(symbol), 1000.0)
        candles: list[Candle] = []

        for i in range(count):
            ts = start_ts + i * interval_ms
            candle = _generate_1m_candle(price, ts)
            candles.append(candle)
            price = candle.close

        return candles

    def _generate_hybrid_1m_history(
        self, symbol: str, total_bars: int, fine_tail_bars: int
    ) -> list[Candle]:
        """
        Fast deep history: hourly synthetic 1m for the old tail, full 1m for recent data.

        Coarse section only feeds 1h/1d store slices; fine tail preserves 1m/5m/15m accuracy.
        """
        minute_ms = INTERVAL_MS[Interval.ONE_MINUTE]
        hour_ms = INTERVAL_MS[Interval.ONE_HOUR]
        now_ms = int(time.time() * 1000)
        current_window = floor_to_interval(now_ms, Interval.ONE_MINUTE)
        total_start = current_window - total_bars * minute_ms
        fine_start = current_window - fine_tail_bars * minute_ms

        price = BASE_PRICES.get(Symbol(symbol), 1000.0)
        coarse: list[Candle] = []

        hour_start = floor_to_interval(total_start, Interval.ONE_HOUR)
        while hour_start < fine_start:
            candle = _generate_hourly_as_1m(price, hour_start)
            coarse.append(candle)
            price = candle.close
            hour_start += hour_ms

        fine: list[Candle] = []
        ts = fine_start
        while ts < current_window:
            candle = _generate_1m_candle(price, ts)
            fine.append(candle)
            price = candle.close
            ts += minute_ms

        return coarse + fine
