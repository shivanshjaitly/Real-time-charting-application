"""
Mock 1-Minute Candle Generator

Generates realistic 1m candles via random walk for all symbols.
1 real second = 1 simulated minute (time compression for demo purposes).

Only 1m data is generated here. All higher timeframes are derived
by the AggregationEngine from these candles.
"""

import asyncio
import math
import random
import time
from collections.abc import Callable
from typing import Any

from src.domain.entities.candle import Candle
from src.domain.entities.symbol import BASE_PRICES, INTERVAL_MS, Interval, Symbol, topic_key
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 1 real second per simulated 1-minute candle
TICK_INTERVAL_SECONDS = 1.0


def _generate_next_candle(prev_close: float, timestamp: int) -> Candle:
    """Realistic OHLCV random walk from previous close."""
    volatility = 0.003 + random.gauss(0, 0.0005)
    volatility = max(0.001, min(0.012, volatility))

    trend = random.gauss(0, 0.0002)
    shock = random.gauss(0, volatility)

    # Occasional jump
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
        timestamp=timestamp,
        open=round(open_, 4),
        high=round(high, 4),
        low=round(low, 4),
        close=round(close, 4),
        volume=volume,
    )


class MockDataGenerator:
    """
    Emits 1m candles for all symbols every TICK_INTERVAL_SECONDS.

    On_candle callbacks are fired for each new candle. The aggregation
    engine and candle store register themselves as callbacks.
    """

    def __init__(self) -> None:
        self._last_close: dict[str, float] = {
            sym.value: BASE_PRICES[sym] for sym in Symbol
        }
        self._callbacks: list[Callable[[str, Candle], Any]] = []
        self._task: asyncio.Task | None = None
        # Simulated clock starts at a round 1m boundary in the past
        interval_ms = INTERVAL_MS[Interval.ONE_MINUTE]
        now_ms = int(time.time() * 1000)
        self._sim_timestamp = (now_ms // interval_ms) * interval_ms

    def add_callback(self, fn: Callable[[str, Candle], Any]) -> None:
        self._callbacks.append(fn)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())
            logger.info("MockDataGenerator started")

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
            await asyncio.sleep(TICK_INTERVAL_SECONDS)
            interval_ms = INTERVAL_MS[Interval.ONE_MINUTE]
            self._sim_timestamp += interval_ms

            for sym in Symbol:
                candle = _generate_next_candle(
                    self._last_close[sym.value],
                    self._sim_timestamp,
                )
                self._last_close[sym.value] = candle.close

                for cb in self._callbacks:
                    try:
                        result = cb(sym.value, candle)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        logger.error(f"Generator callback error: {e}")

    def generate_history(self, symbol: str, interval_ms: int, count: int = 200) -> list[Candle]:
        """Generate historical candles backwards from current simulated time."""
        candles: list[Candle] = []
        price = BASE_PRICES.get(Symbol(symbol), 1000.0)

        # Go back `count` candles from current simulated timestamp
        start_ts = self._sim_timestamp - count * interval_ms

        for i in range(count):
            ts = start_ts + i * interval_ms
            candle = _generate_next_candle(price, ts)
            candles.append(candle)
            price = candle.close

        return candles
