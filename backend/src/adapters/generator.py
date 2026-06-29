"""
Mock Candle Generator

Generates realistic price ticks via random walk for all symbols.
Uses real wall-clock time so candle windows align to clock boundaries
(9:00–10:00, :00/:05/:10, etc.) and each interval updates in place
until its window completes.

All intervals (1m, 5m, 15m, 1h, 1d) are derived by the AggregationEngine
from these ticks.
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
        timestamp=0,  # window timestamp is assigned by the aggregator
        open=round(open_, 4),
        high=round(high, 4),
        low=round(low, 4),
        close=round(close, 4),
        volume=volume,
    )


def _generate_candle(prev_close: float, window_start: int, interval: Interval) -> Candle:
    """Generate one completed historical candle for a given window."""
    # Scale volatility by interval length
    scale = {
        Interval.ONE_MINUTE: 1.0,
        Interval.FIVE_MINUTES: 2.0,
        Interval.FIFTEEN_MINUTES: 3.0,
        Interval.ONE_HOUR: 6.0,
        Interval.ONE_DAY: 15.0,
    }[interval]

    volatility = (0.003 + random.gauss(0, 0.0005)) * scale
    volatility = max(0.001, min(0.012 * scale, volatility))

    trend = random.gauss(0, 0.0002 * scale)
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
    Emits price ticks for all symbols on a fixed real-time interval.

    Callback signature: fn(symbol: str, tick: Candle, now_ms: int)
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

    def generate_history(self, symbol: str, interval: Interval, count: int) -> list[Candle]:
        """Generate calendar-aligned historical candles ending before the current window."""
        interval_ms = INTERVAL_MS[interval]
        now_ms = int(time.time() * 1000)
        current_window = floor_to_interval(now_ms, interval)
        start_ts = current_window - count * interval_ms

        candles: list[Candle] = []
        price = BASE_PRICES.get(Symbol(symbol), 1000.0)

        for i in range(count):
            ts = start_ts + i * interval_ms
            candle = _generate_candle(price, ts, interval)
            candles.append(candle)
            price = candle.close

        return candles
