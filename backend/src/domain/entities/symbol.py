"""Symbol and Interval definitions."""

from enum import Enum


class Symbol(str, Enum):
    BTCUSDT = "BTCUSDT"
    ETHUSDT = "ETHUSDT"
    SOLUSDT = "SOLUSDT"
    BNBUSDT = "BNBUSDT"
    AAPL    = "AAPL"
    MSFT    = "MSFT"
    TSLA    = "TSLA"
    GOOGL   = "GOOGL"
    AMZN    = "AMZN"
    NVDA    = "NVDA"


class Interval(str, Enum):
    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR = "1h"
    ONE_DAY = "1d"


# Milliseconds per interval
INTERVAL_MS: dict[Interval, int] = {
    Interval.ONE_MINUTE:       60_000,
    Interval.FIVE_MINUTES:    300_000,
    Interval.FIFTEEN_MINUTES: 900_000,
    Interval.ONE_HOUR:      3_600_000,
    Interval.ONE_DAY:      86_400_000,
}

# Higher intervals derived from 1m (in order)
HIGHER_INTERVALS: list[Interval] = [
    Interval.FIVE_MINUTES,
    Interval.FIFTEEN_MINUTES,
    Interval.ONE_HOUR,
    Interval.ONE_DAY,
]

# Default history depth per interval (candles served to clients)
HISTORY_COUNTS: dict[Interval, int] = {
    Interval.ONE_MINUTE:       200,
    Interval.FIVE_MINUTES:     200,
    Interval.FIFTEEN_MINUTES:  200,
    Interval.ONE_HOUR:         240,   # 10 days at default seed depth
    Interval.ONE_DAY:           10,
}


def history_counts_for_seed(seed_1m_bars: int) -> dict[Interval, int]:
    """History slice sizes derived from how many 1m bars were seeded."""
    return {
        Interval.ONE_MINUTE: min(HISTORY_COUNTS[Interval.ONE_MINUTE], seed_1m_bars),
        Interval.FIVE_MINUTES: min(HISTORY_COUNTS[Interval.FIVE_MINUTES], seed_1m_bars // 5),
        Interval.FIFTEEN_MINUTES: min(
            HISTORY_COUNTS[Interval.FIFTEEN_MINUTES], seed_1m_bars // 15
        ),
        Interval.ONE_HOUR: min(HISTORY_COUNTS[Interval.ONE_HOUR], seed_1m_bars // 60),
        Interval.ONE_DAY: min(HISTORY_COUNTS[Interval.ONE_DAY], seed_1m_bars // 1440),
    }

# Base prices for mock data generation
BASE_PRICES: dict[Symbol, float] = {
    Symbol.BTCUSDT: 67_000.0,
    Symbol.ETHUSDT:  3_500.0,
    Symbol.SOLUSDT:    175.0,
    Symbol.BNBUSDT:    605.0,
    Symbol.AAPL:       195.0,
    Symbol.MSFT:       420.0,
    Symbol.TSLA:       175.0,
    Symbol.GOOGL:      178.0,
    Symbol.AMZN:       190.0,
    Symbol.NVDA:       875.0,
}

ALL_SYMBOLS = list(Symbol)
ALL_INTERVALS = list(Interval)


def topic_key(symbol: str, interval: str) -> str:
    """Canonical topic key for pub/sub."""
    return f"{symbol}:{interval}"
