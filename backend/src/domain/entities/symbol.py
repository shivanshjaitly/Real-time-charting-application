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
