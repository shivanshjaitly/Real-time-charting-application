"""Calendar-aligned candle window utilities."""

from datetime import datetime, timezone

from src.domain.entities.symbol import Interval


def floor_to_interval(ts_ms: int, interval: Interval) -> int:
    """
    Floor a millisecond timestamp to the start of its candle window.

    Aligns to UTC wall-clock boundaries so 1h candles are 9:00–10:00 UTC,
    5m candles are :00/:05/:10, and 1d candles start at midnight UTC.
    """
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

    if interval == Interval.ONE_MINUTE:
        floored = dt.replace(second=0, microsecond=0)
    elif interval == Interval.FIVE_MINUTES:
        floored = dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)
    elif interval == Interval.FIFTEEN_MINUTES:
        floored = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
    elif interval == Interval.ONE_HOUR:
        floored = dt.replace(minute=0, second=0, microsecond=0)
    elif interval == Interval.ONE_DAY:
        floored = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"Unsupported interval: {interval}")

    return int(floored.timestamp() * 1000)
