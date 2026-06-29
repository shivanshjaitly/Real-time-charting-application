"""Seeding pipeline tests."""

import unittest

from src.adapters.generator import MockDataGenerator
from src.domain.entities.symbol import Interval
from src.domain.services.aggregator import AggregationEngine
from src.domain.services.seed import required_1m_seed_bars


class SeedTests(unittest.TestCase):
    def test_replay_matches_incremental_aggregation(self) -> None:
        """Bulk replay must match step-by-step process_1m_candle results."""
        gen = MockDataGenerator()
        candles_1m = gen.generate_1m_history("BTCUSDT", 30)

        bulk = AggregationEngine()
        bulk_series, _ = bulk.replay_1m_history("BTCUSDT", candles_1m)

        step = AggregationEngine()
        last: dict[Interval, object] = {}
        for c1m in candles_1m:
            for topic, candle in step.process_1m_candle("BTCUSDT", c1m):
                iv = Interval(topic.rsplit(":", 1)[1])
                last[iv] = candle

        for interval in (Interval.FIVE_MINUTES, Interval.FIFTEEN_MINUTES):
            self.assertGreater(len(bulk_series[interval]), 0)
            self.assertEqual(bulk_series[interval][-1].open, last[interval].open)
            self.assertEqual(bulk_series[interval][-1].close, last[interval].close)
            self.assertEqual(bulk_series[interval][-1].high, last[interval].high)
            self.assertEqual(bulk_series[interval][-1].low, last[interval].low)

    def test_seed_1m_bars_is_reasonable_default(self) -> None:
        bars = required_1m_seed_bars()
        self.assertGreaterEqual(bars, 200)
        self.assertLessEqual(bars, 50_000)

    def test_seed_syncs_generator_last_close(self) -> None:
        from src.adapters.candle_store import CandleStore
        from src.domain.services.seed import seed_history

        store = CandleStore()
        agg = AggregationEngine()
        gen = MockDataGenerator()
        seed_history(gen, store, agg)

        history = store.get_history("BTCUSDT:1m")
        self.assertGreater(len(history), 0)
        self.assertAlmostEqual(gen._last_close["BTCUSDT"], history[-1].close, places=2)


if __name__ == "__main__":
    unittest.main()
