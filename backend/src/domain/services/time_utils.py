"""Calendar-aligned candle window utilities."""

from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from src.domain.entities.symbol import Interval
from src.infrastructure.config import get_settings


"""Calendar-aligned candle window utilities."""

import os
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from src.domain.entities.symbol import Interval
from src.infrastructure.config import get_settings


def _system_zoneinfo() -> ZoneInfo:
    """Resolve the machine's IANA zone (macOS/Linux via /etc/localtime)."""
    try:
        link = os.path.realpath("/etc/localtime")
    except OSError:
        link = ""
    marker = "/zoneinfo/"
    if marker in link:
        return ZoneInfo(link.split(marker, 1)[1])

    local = datetime.now().astimezone().tzinfo
    if isinstance(local, ZoneInfo):
        return local
    return ZoneInfo("UTC")


@lru_cache
def get_candle_timezone() -> ZoneInfo:
    """Resolved IANA zone used for candle window floors."""
    name = get_settings().candle_timezone.strip()
    if name and name.lower() not in ("local", "system"):
        return ZoneInfo(name)
    return _system_zoneinfo()


def get_candle_timezone_name() -> str:
    return get_candle_timezone().key


def floor_to_interval(ts_ms: int, interval: Interval, tz: ZoneInfo | None = None) -> int:
    """
    Floor a millisecond timestamp to the start of its candle window.

    Aligns to wall-clock boundaries in the configured candle timezone so 1h
    candles are 9:00–10:00 local, 5m candles are :00/:05/:10, and 1d candles
    start at local midnight.
    """
    zone = tz or get_candle_timezone()
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=zone)

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
