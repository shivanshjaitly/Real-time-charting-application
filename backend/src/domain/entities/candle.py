"""Candle entity — core domain model."""

from dataclasses import dataclass


@dataclass
class Candle:
    timestamp: int    # Unix milliseconds — start of candle window
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Candle":
        return cls(
            timestamp=data["timestamp"],
            open=data["open"],
            high=data["high"],
            low=data["low"],
            close=data["close"],
            volume=data["volume"],
        )
