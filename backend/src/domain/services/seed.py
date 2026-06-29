"""Historical data seeding — 1m source only, higher intervals derived."""

from concurrent.futures import ProcessPoolExecutor, as_completed

from src.adapters.candle_store import CandleStore
from src.adapters.generator import MockDataGenerator
from src.domain.entities.candle import Candle
from src.domain.entities.symbol import (
    ALL_SYMBOLS,
    HIGHER_INTERVALS,
    HISTORY_COUNTS,
    Interval,
    topic_key,
)
from src.domain.services.aggregator import AggregationEngine
from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


def required_1m_seed_bars() -> int:
    """1m bars to generate at startup (configurable for speed vs depth)."""
    return get_settings().seed_1m_bars


def _seed_one_symbol(symbol: str, bars_1m: int) -> tuple[
    str,
    list[Candle],
    dict[Interval, list[Candle]],
    dict[Interval, Candle],
    float,
]:
    """Worker: generate 1m history and derive higher intervals for one symbol."""
    gen = MockDataGenerator()
    candles_1m = gen.generate_1m_history(symbol, bars_1m)
    sym_agg = AggregationEngine()
    higher_series, open_higher = sym_agg.replay_1m_history(symbol, candles_1m)
    last_close = candles_1m[-1].close if candles_1m else gen._last_close.get(symbol, 0.0)
    return symbol, candles_1m, higher_series, open_higher, last_close


def seed_history(
    generator: MockDataGenerator,
    store: CandleStore,
    aggregator: AggregationEngine,
) -> None:
    """
    Seed all intervals from 1m data only.

    Uses parallel workers per symbol for fast startup on mock data.
    Aggregator state is preserved after seeding so live ticks continue
    in-progress higher-interval windows without a discontinuity.
    """
    bars_1m = required_1m_seed_bars()
    logger.info(f"Seeding history — {bars_1m:,} 1m bars/symbol (parallel)")

    symbol_values = [sym.value for sym in ALL_SYMBOLS]
    results: list[tuple[str, list[Candle], dict, dict, float]] = []

    # Parallel seed across symbols (each worker is independent)
    with ProcessPoolExecutor(max_workers=min(len(symbol_values), 4)) as pool:
        futures = {
            pool.submit(_seed_one_symbol, sym, bars_1m): sym for sym in symbol_values
        }
        for future in as_completed(futures):
            sym = futures[future]
            try:
                results.append(future.result())
                logger.info(f"  seeded {sym}")
            except Exception as e:
                logger.error(f"  seed failed for {sym}: {e}")
                raise

    for sym_value, candles_1m, higher_series, open_higher, last_close in results:
        store.seed(
            topic_key(sym_value, Interval.ONE_MINUTE.value),
            candles_1m[-HISTORY_COUNTS[Interval.ONE_MINUTE]:],
        )

        for interval in HIGHER_INTERVALS:
            count = HISTORY_COUNTS[interval]
            store.seed(topic_key(sym_value, interval.value), higher_series[interval][-count:])

        aggregator.load_open_higher_candles(sym_value, open_higher)
        generator.set_last_close(sym_value, last_close)

    logger.info("Historical data seeded from 1m source for all symbols and intervals")
