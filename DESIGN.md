# Design Write-Up — Real-Time Charting Application

## 1. System Architecture

The application is built inside the KlineCharts open-source library codebase. The frontend extends the existing `debug/` folder; the backend is a standalone Python service.

```
┌──────────────────────────────────────────────────────────────────┐
│                      Browser (KlineCharts debug/)                 │
│                                                                    │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐ │
│  │  ChartPanel│  │  ChartPanel│  │  ChartPanel│  │  ChartPanel│ │
│  │ BTCUSDT:1m │  │ ETHUSDT:5m │  │ BTCUSDT:1h │  │  AAPL:1d   │ │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘ │
│        │                │                │                │        │
│        └────────────────┴────────────────┴────────────────┘        │
│                              WSManager                              │
│                         (single WS connection)                      │
└──────────────────────────────┬───────────────────────────────────┘
                                │  WebSocket ws://localhost:8000/ws
                                │  Protocol:
                                │  → { type: "subscribe", symbol, interval }
                                │  ← { type: "history", data: Candle[] }
                                │  ← { type: "candle",  data: Candle }
┌──────────────────────────────┴───────────────────────────────────┐
│                     Backend (FastAPI + Python)                     │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  ConnectionManager (ws_server.py)                          │   │
│  │  client_id → { topic → asyncio.Queue }                     │   │
│  └──────────────────────┬─────────────────────────────────────┘   │
│                          │ publish()                               │
│  ┌───────────────────────┴────────────────────────────────────┐   │
│  │  PubSub                                                    │   │
│  │  topic ("BTCUSDT:1m") → set[asyncio.Queue]                 │   │
│  └───────────────────────┬────────────────────────────────────┘   │
│                          │                                         │
│  ┌───────────────────────┴────────────────────────────────────┐   │
│  │  AggregationEngine                                         │   │
│  │  1m candle → derives 5m / 15m / 1h / 1d                   │   │
│  └───────────────────────┬────────────────────────────────────┘   │
│                          │                                         │
│  ┌───────────────────────┴────────────────────────────────────┐   │
│  │  MockDataGenerator                                         │   │
│  │  Emits 1m candle every 1 real second (time compression)    │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  CandleStore                                               │   │
│  │  In-memory deque(maxlen=200) per topic                     │   │
│  │  Serves historical data on subscribe                       │   │
│  └────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

### Data Flow (per 1m tick)

```
Generator → 1m Candle (BTCUSDT, ts=T)
    │
    ├─→ CandleStore.append("BTCUSDT:1m", candle)
    ├─→ PubSub.publish("BTCUSDT:1m", candle)  →  all 1m subscribers
    │
    └─→ AggregationEngine.process_1m_candle("BTCUSDT", candle)
            │
            ├─→ 5m window: update high/low/close/volume → CandleStore + PubSub("BTCUSDT:5m")
            ├─→ 15m window: update high/low/close/volume → CandleStore + PubSub("BTCUSDT:15m")
            ├─→ 1h window:  update high/low/close/volume → CandleStore + PubSub("BTCUSDT:1h")
            └─→ 1d window:  update high/low/close/volume → CandleStore + PubSub("BTCUSDT:1d")
```

---

## 2. Technology Choice: Python / asyncio (and not Go or Node.js)

**The choice was deliberate, not default.**

Go and Node.js are both strong candidates for a high-concurrency WebSocket server. The reasoning for Python + asyncio + FastAPI:

| Factor | Python asyncio | Go | Node.js |
|---|---|---|---|
| Concurrency model | Single-threaded coroutines — no GIL contention on I/O | Goroutines — true parallelism | Single-threaded event loop |
| I/O-bound suitability | Excellent — WebSocket fan-out is pure I/O | Excellent | Excellent |
| CPU-bound (JSON serialisation) | GIL becomes a bottleneck above ~5K connections | No bottleneck | No bottleneck |
| Data/ML ecosystem | Pandas, NumPy available if aggregation grows complex | Weaker | Moderate |
| Assignment constraint | FastAPI + uvicorn is the fastest path to a provably correct, testable architecture within 3 days | — | — |

**Honest limitation:** Python's GIL means JSON serialisation of 1,000 simultaneous candle pushes is single-threaded. At ~5,000 connections the event loop saturates. The mitigation is `ujson` (5× faster serialisation) and `uvicorn --workers N` with Redis Pub/Sub to share state across workers. That path is documented in the scalability section below but not implemented — a conscious scope decision for a 3-day assignment.

---

## 3. Scalability Strategy

### How it handles 1,000 concurrent connections

The backend uses Python asyncio with FastAPI's native WebSocket support. Each WebSocket connection is a coroutine — not a thread — so memory overhead per connection is ~2KB (one asyncio.Queue + task per subscription). A single uvicorn worker process comfortably handles 1,000+ concurrent connections on the asyncio event loop.

**Verified:** k6 load test ran 1,000 simultaneous VUs:
- **Zero connection errors** (0 of 14,731 sessions)
- **100% subscribe success rate**
- **88,386 WebSocket messages delivered**
- **117 MB data at ~1 MB/s**

### Where it breaks next

| Limit | Cause | Solution |
|---|---|---|
| ~5,000 connections | asyncio event loop + GIL saturates on JSON serialization | Move to `ujson`, add `uvicorn --workers N` |
| ~20,000 connections | Single process memory ceiling | Redis Pub/Sub + multiple stateless WS workers behind nginx |
| Aggregation at scale | All 5 intervals processed per 1m tick per symbol — O(symbols × intervals) | Separate aggregation worker, message queue (Redis Streams) |

### Next-tier architecture (for production)

```
nginx (load balancer)
  ├── WS Worker 1 (uvicorn)
  ├── WS Worker 2 (uvicorn)
  └── WS Worker N (uvicorn)
        └── Redis Pub/Sub ←── Aggregation Worker ←── Generator
```

---

## 4. Real-Time Transport Choice: WebSocket

**Chosen:** Native WebSocket (`ws://`)

**Why not Server-Sent Events (SSE):**
SSE is server-push only (unidirectional). Clients cannot send subscription commands over SSE. Our design requires each client to send `{ type: "subscribe", symbol, interval }` messages, which mandates a bidirectional channel. WebSocket is the correct choice.

**Why not HTTP long-polling:**
Long-polling cannot sustain 1,000 concurrent real-time streams efficiently. Each candle update would require a new HTTP request, creating N × ticks_per_second requests per second — completely impractical.

**WebSocket advantages for this use case:**
- Single persistent TCP connection per client — minimal overhead
- Bidirectional: subscription management over the same channel
- Native browser support — no library needed on frontend
- Full-duplex: server can push candles exactly when generated

---

## 5. Trade-offs and Assumptions

| Decision | Assumption | Reasoning |
|---|---|---|
| **1 real second = 1 simulated minute** | Time compression for demo | A real trading platform generates 1 candle per minute. For a 3-day assignment demo, accelerated time is required to observe live updates. Documented here to be explicit. |
| **In-memory candle store** | No persistence across restarts | The assignment asks for real-time streaming, not historical persistence. Adding a database would add complexity without demonstrating the core system. |
| **Single WebSocket connection per browser tab** | All panels share one WS | Multiplexing all symbol:interval subscriptions over one connection is more efficient than one WS per panel. Standard practice in trading platforms. |
| **10 mock symbols (BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, AAPL, MSFT, TSLA, GOOGL, AMZN, NVDA)** | Symbols not specified in brief | The brief references "selected symbols" without specifying which. 10 symbols covering major crypto and equity demonstrates the multi-symbol workspace feature at a realistic scale. |
| **localStorage for workspace persistence** | No user auth required | The brief says "persist and be restorable" without specifying a persistence backend. localStorage is zero-dependency and correct for a single-user scenario. |
| **History: 200 candles per topic** | "Reasonable" not specified | 200 candles provides meaningful chart context without excessive memory usage (~60KB per topic as JSON). |
| **Higher-interval open candle published live** | "Restorable" partially open candle | When a 5m candle is in progress, subscribers receive rolling updates (close, high, low update on each 1m tick). This is correct trading terminal behavior — the candle is live until the window closes. |
| **Out-of-order candles not handled** | Mock generator guarantees monotonic timestamps | The aggregator uses `window_start = floor(ts / interval_ms) * interval_ms` and assumes candles arrive in increasing timestamp order. A late-arriving 1m candle would compute a stale `window_start`, causing it to overwrite the in-progress candle with incorrect data. This is a conscious deferral: the mock generator never produces out-of-order data, so the edge case cannot trigger. In production the fix is a reorder buffer with a configurable late-arrival tolerance (typically 1–2 seconds for exchange feeds), applied before the aggregation engine. |

---

## 6. Aggregation Correctness

All higher-interval candles are derived strictly from 1-minute data only. The rules implemented in `backend/src/domain/services/aggregator.py`:

```
For each 1m candle arriving for symbol S at timestamp T:
  window_start = floor(T / interval_ms) * interval_ms

  If no candle open for this window:
    open   = 1m.open              ← first sub-candle's open, NEVER changes
    high   = 1m.high
    low    = 1m.low
    close  = 1m.close
    volume = 1m.volume

  Else (window already open):
    open   = UNCHANGED            ← strictly preserved
    high   = max(existing.high, 1m.high)
    low    = min(existing.low,  1m.low)
    close  = 1m.close             ← always the last sub-candle
    volume = existing.volume + 1m.volume
```

This is applied identically for 5m, 15m, 1h, and 1d windows.
