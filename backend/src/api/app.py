"""
Application Factory

Builds and returns the fully-wired FastAPI ASGI application.
Mirrors the create_app() pattern from the existing backend.
"""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from src.adapters.candle_store import CandleStore
from src.adapters.generator import MockDataGenerator
from src.adapters.pubsub import PubSub
from src.api.ws_server import ConnectionManager
from src.domain.entities.symbol import ALL_SYMBOLS, HISTORY_COUNTS, Interval, Symbol, topic_key
from src.domain.services.aggregator import AggregationEngine
from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger, setup_logging

logger = get_logger(__name__)


def _seed_history(generator: MockDataGenerator, store: CandleStore) -> None:
    """Pre-populate the store with calendar-aligned history for every symbol+interval."""
    for sym in ALL_SYMBOLS:
        for interval in Interval:
            count = HISTORY_COUNTS[interval]
            candles = generator.generate_history(sym.value, interval, count)
            store.seed(topic_key(sym.value, interval.value), candles)

    logger.info("Historical data seeded for all symbols and intervals")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    # Wire up core components
    pubsub = PubSub()
    store = CandleStore()
    aggregator = AggregationEngine()
    generator = MockDataGenerator()
    manager = ConnectionManager(pubsub=pubsub, store=store)

    def on_tick(symbol: str, tick, now_ms: int) -> None:
        """Called on every price tick. Updates store + aggregates + publishes all intervals."""
        import asyncio
        loop = asyncio.get_event_loop()

        updates = aggregator.process_tick(symbol, tick, now_ms)
        for topic, candle in updates:
            store.append(topic, candle)
            loop.create_task(pubsub.publish(topic, candle.to_dict()))

    generator.add_callback(on_tick)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting Real-Time Charting Backend")
        _seed_history(generator, store)
        # Reset aggregator state after seeding so live data starts fresh
        aggregator.reset()
        generator.start()
        logger.info(f"Backend ready — ws://localhost:{settings.port}/ws")
        yield
        await generator.stop()
        logger.info("Backend shutdown complete")

    app = FastAPI(
        title="Real-Time Charting Backend",
        description="WebSocket server for live candlestick data",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "connections": manager.connection_count(),
            "pubsub_subscribers": pubsub.total_subscribers(),
        }

    @app.get("/symbols")
    async def symbols():
        return {"symbols": [sym.value for sym in Symbol]}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        client_id = str(uuid.uuid4())
        await manager.handle(client_id, ws)

    return app
