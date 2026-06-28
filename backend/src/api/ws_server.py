"""
WebSocket Server

Handles client connections, subscriptions, and message routing.

Client → Server protocol:
  { "type": "subscribe",   "symbol": "BTCUSDT", "interval": "1m" }
  { "type": "unsubscribe", "symbol": "BTCUSDT", "interval": "1m" }
  { "type": "history",     "symbol": "BTCUSDT", "interval": "1m" }

Server → Client protocol:
  { "type": "history", "symbol": ..., "interval": ..., "data": [...candles] }
  { "type": "candle",  "symbol": ..., "interval": ..., "data": {...candle} }
  { "type": "error",   "message": "..." }
"""

import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect

from src.adapters.candle_store import CandleStore
from src.adapters.pubsub import PubSub
from src.domain.entities.symbol import ALL_INTERVALS, ALL_SYMBOLS, INTERVAL_MS, Interval, Symbol, topic_key
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

VALID_SYMBOLS = {s.value for s in Symbol}
VALID_INTERVALS = {i.value for i in Interval}


class ConnectionManager:
    """Tracks all active WebSocket connections and their subscriptions."""

    def __init__(self, pubsub: PubSub, store: CandleStore) -> None:
        self._pubsub = pubsub
        self._store = store
        # client_id -> { topic -> asyncio.Queue }
        self._client_subs: dict[str, dict[str, asyncio.Queue]] = {}
        # client_id -> { topic -> asyncio.Task (listener loop) }
        self._client_tasks: dict[str, dict[str, asyncio.Task]] = {}
        # client_id -> WebSocket
        self._connections: dict[str, WebSocket] = {}

    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, client_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[client_id] = ws
        self._client_subs[client_id] = {}
        self._client_tasks[client_id] = {}
        logger.info(f"Client connected: {client_id} | total={self.connection_count()}")

    async def disconnect(self, client_id: str) -> None:
        await self._unsubscribe_all(client_id)
        self._connections.pop(client_id, None)
        self._client_subs.pop(client_id, None)
        self._client_tasks.pop(client_id, None)
        logger.info(f"Client disconnected: {client_id} | total={self.connection_count()}")

    async def handle(self, client_id: str, ws: WebSocket) -> None:
        await self.connect(client_id, ws)
        try:
            while True:
                raw = await ws.receive_text()
                await self._dispatch(client_id, ws, raw)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning(f"Client {client_id} error: {e}")
        finally:
            await self.disconnect(client_id)

    async def _dispatch(self, client_id: str, ws: WebSocket, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await self._send_error(ws, "Invalid JSON")
            return

        msg_type = msg.get("type")
        symbol = msg.get("symbol", "")
        interval = msg.get("interval", "")

        if symbol not in VALID_SYMBOLS:
            await self._send_error(ws, f"Unknown symbol: {symbol}")
            return
        if interval not in VALID_INTERVALS:
            await self._send_error(ws, f"Unknown interval: {interval}")
            return

        topic = topic_key(symbol, interval)

        if msg_type == "history":
            await self._send_history(ws, symbol, interval, topic)

        elif msg_type == "subscribe":
            await self._send_history(ws, symbol, interval, topic)
            await self._subscribe(client_id, ws, topic, symbol, interval)

        elif msg_type == "unsubscribe":
            await self._unsubscribe(client_id, topic)

        else:
            await self._send_error(ws, f"Unknown message type: {msg_type}")

    async def _send_history(self, ws: WebSocket, symbol: str, interval: str, topic: str) -> None:
        history = self._store.get_history(topic)
        await ws.send_text(json.dumps({
            "type": "history",
            "symbol": symbol,
            "interval": interval,
            "data": [c.to_dict() for c in history],
        }))

    async def _subscribe(self, client_id: str, ws: WebSocket, topic: str, symbol: str, interval: str) -> None:
        if topic in self._client_subs.get(client_id, {}):
            return  # already subscribed

        queue = self._pubsub.subscribe(topic)
        self._client_subs[client_id][topic] = queue

        task = asyncio.create_task(
            self._listener_loop(client_id, ws, queue, topic, symbol, interval)
        )
        self._client_tasks[client_id][topic] = task

    async def _listener_loop(
        self,
        client_id: str,
        ws: WebSocket,
        queue: asyncio.Queue,
        topic: str,
        symbol: str,
        interval: str,
    ) -> None:
        try:
            while True:
                candle_msg = await queue.get()
                if client_id not in self._connections:
                    break
                await ws.send_text(json.dumps({
                    "type": "candle",
                    "symbol": symbol,
                    "interval": interval,
                    "data": candle_msg,
                }))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Listener loop error for {client_id}/{topic}: {e}")

    async def _unsubscribe(self, client_id: str, topic: str) -> None:
        tasks = self._client_tasks.get(client_id, {})
        if topic in tasks:
            tasks[topic].cancel()
            del tasks[topic]

        subs = self._client_subs.get(client_id, {})
        if topic in subs:
            self._pubsub.unsubscribe(topic, subs[topic])
            del subs[topic]

    async def _unsubscribe_all(self, client_id: str) -> None:
        for topic in list(self._client_tasks.get(client_id, {}).keys()):
            await self._unsubscribe(client_id, topic)

    @staticmethod
    async def _send_error(ws: WebSocket, message: str) -> None:
        try:
            await ws.send_text(json.dumps({"type": "error", "message": message}))
        except Exception:
            pass
