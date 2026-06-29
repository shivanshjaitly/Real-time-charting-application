"""Aggregation engine correctness tests."""

import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.domain.entities.candle import Candle
from src.domain.entities.symbol import Interval
from src.domain.services.aggregator import AggregationEngine
from src.domain.services.time_utils import floor_to_interval

UTC = ZoneInfo("UTC")


def _c(ts: int, o: float, h: float, l: float, c: float, v: float) -> Candle:
    return Candle(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


class AggregationEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agg = AggregationEngine()
        self.base_ms = 1_700_000_000_000  # fixed UTC anchor
        self._tz_patch = patch(
            "src.domain.services.time_utils.get_candle_timezone",
            return_value=UTC,
        )
        self._tz_patch.start()

    def tearDown(self) -> None:
        self._tz_patch.stop()

    def test_five_1m_candles_roll_into_one_5m(self) -> None:
        """5 × 1m → 1 × 5m with correct OHLCV."""
        window_5m = floor_to_interval(self.base_ms, Interval.FIVE_MINUTES, tz=UTC)
        candles_1m = [
            _c(window_5m + 0 * 60_000, 100, 101, 99, 100.5, 10),
            _c(window_5m + 1 * 60_000, 100.5, 103, 100, 102, 20),
            _c(window_5m + 2 * 60_000, 102, 104, 101, 103, 15),
            _c(window_5m + 3 * 60_000, 103, 105, 102, 104, 25),
            _c(window_5m + 4 * 60_000, 104, 106, 103, 105, 30),
        ]

        last_5m = None
        for c1m in candles_1m:
            updates = self.agg.process_1m_candle("BTCUSDT", c1m)
            for topic, candle in updates:
                if topic.endswith(":5m"):
                    last_5m = candle

        assert last_5m is not None
        self.assertEqual(last_5m.timestamp, window_5m)
        self.assertEqual(last_5m.open, 100)
        self.assertEqual(last_5m.close, 105)
        self.assertEqual(last_5m.high, 106)
        self.assertEqual(last_5m.low, 99)
        self.assertEqual(last_5m.volume, 100)

    def test_open_never_changes_within_window(self) -> None:
        window_5m = floor_to_interval(self.base_ms, Interval.FIVE_MINUTES, tz=UTC)
        c1 = _c(window_5m, 50, 51, 49, 50.5, 5)
        c2 = _c(window_5m + 60_000, 200, 210, 190, 205, 5)

        self.agg.process_1m_candle("ETHUSDT", c1)
        updates = self.agg.process_1m_candle("ETHUSDT", c2)
        candle_5m = next(c for t, c in updates if t.endswith(":5m"))

        self.assertEqual(candle_5m.open, 50)
        self.assertEqual(candle_5m.close, 205)

    def test_process_tick_updates_1m_in_place(self) -> None:
        now_ms = self.base_ms
        tick1 = _c(0, 100, 100.5, 99.5, 100.2, 3)
        tick2 = _c(0, 100.2, 101, 99, 100.8, 2)

        u1 = self.agg.process_tick("BTCUSDT", tick1, now_ms)
        u2 = self.agg.process_tick("BTCUSDT", tick2, now_ms + 500)

        ts_1m = floor_to_interval(now_ms, Interval.ONE_MINUTE, tz=UTC)
        c1m_1 = next(c for t, c in u1 if t.endswith(":1m"))
        c1m_2 = next(c for t, c in u2 if t.endswith(":1m"))

        self.assertEqual(c1m_1.timestamp, ts_1m)
        self.assertEqual(c1m_2.timestamp, ts_1m)
        self.assertEqual(c1m_2.close, 100.8)
        self.assertEqual(c1m_2.volume, 5)

    def test_tick_derives_higher_intervals_from_1m(self) -> None:
        """Live tick builds 1m first, then rolls up to all higher intervals."""
        now_ms = self.base_ms
        tick = _c(0, 10, 11, 9, 10.5, 1)
        updates = self.agg.process_tick("SOLUSDT", tick, now_ms)

        topics = {t for t, _ in updates}
        self.assertIn("SOLUSDT:1m", topics)
        for suffix in ("5m", "15m", "1h", "1d"):
            self.assertIn(f"SOLUSDT:{suffix}", topics)

    def test_floor_to_interval_respects_timezone(self) -> None:
        ist = ZoneInfo("Asia/Kolkata")
        # 2023-11-14 22:13:20 UTC = 2023-11-15 03:43:20 IST
        ts_ms = 1_700_000_000_000
        utc_1h = floor_to_interval(ts_ms, Interval.ONE_HOUR, tz=UTC)
        ist_1h = floor_to_interval(ts_ms, Interval.ONE_HOUR, tz=ist)
        self.assertNotEqual(utc_1h, ist_1h)


if __name__ == "__main__":
    unittest.main()
