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
│                          │ read from subscriber queues            │
│  ┌───────────────────────┴────────────────────────────────────┐   │
│  │  PubSub — topic ("BTCUSDT:1m") → set[asyncio.Queue]        │   │
│  └───────────────────────┬─────────────────────────────────────┘   │
│                          │ publish on every candle update         │
│  ┌───────────────────────┴────────────────────────────────────┐   │
│  │  MockDataGenerator (sub-minute ticks → 1m only)              │   │
│  └───────────────────────┬─────────────────────────────────────┘   │
│                          │ tick per symbol (~1/s)                   │
│  ┌───────────────────────┴────────────────────────────────────┐   │
│  │  AggregationEngine                                           │   │
│  │    process_tick → in-progress 1m candle                      │   │
│  │    process_1m_candle → derives 5m / 15m / 1h / 1d ONLY     │   │
│  └───────────────────────┬─────────────────────────────────────┘   │
│                          │ append                                  │
│  ┌───────────────────────┴────────────────────────────────────┐   │
│  │  CandleStore (deque maxlen=1000 per topic)                   │   │
│  └────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

### Frontend (debug/)

Each **ChartPanel** owns a KlineCharts instance wired via `setDataLoader()` — `getBars` for history, `subscribeBar` for live candles. A single **WSManager** multiplexes all panel subscriptions over one WebSocket. Layout modes (1×1, 1×2, 2×1, 2×2, 2×3, 3×1, 3×3, 4×4), symbol/interval selectors, loading overlay on interval switch, and workspace save/restore (localStorage) are handled in `debug/main.js` without adding external frontend dependencies.

### Data Flow (live tick → 1m → higher intervals)

```
Generator → sub-minute tick (BTCUSDT)
    │
    └─→ AggregationEngine.process_tick()
            │
            ├─→ accumulate into in-progress 1m candle (clock-aligned local)
            │       → CandleStore + PubSub("BTCUSDT:1m")
            │
            └─→ process_1m_candle(current 1m bar)
                    ├─→ 5m  → CandleStore + PubSub("BTCUSDT:5m")
                    ├─→ 15m → CandleStore + PubSub("BTCUSDT:15m")
                    ├─→ 1h  → CandleStore + PubSub("BTCUSDT:1h")
                    └─→ 1d  → CandleStore + PubSub("BTCUSDT:1d")
```

**History seeding** (`seed.py`): generates 4,320 1m candles per symbol by default (~3 days), replays through `replay_1m_history()` in parallel across symbols (~1–2s startup). Increase `CHART_SEED_1M_BARS` for deeper 1d/1h history.

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

The backend uses Python asyncio with FastAPI's native WebSocket support. Each WebSocket connection is a coroutine — not a thread — so memory overhead per connection is ~2KB (one asyncio.Queue + listener task per subscription). A single uvicorn worker process comfortably handles 1,000+ concurrent connections on the asyncio event loop.

**Load test:** k6 script at `backend/load-test/script.js` ramps to 1,000 VUs over 30s, holds 60s, ramps down. Each VU connects, subscribes to a random symbol (10 available) and interval (1m–1d), receives history + 5 live candles, then disconnects. Evidence: `backend/load-test/results.txt` and `backend/load-test/screenshot.png`.

**Verified results (1,000 max VUs):**

| Metric | Result | Threshold |
|---|---|---|
| WebSocket sessions | **14,566** | — |
| Connection errors | **0** | count < 10 ✓ |
| Subscribe success rate | **100%** (14,566 / 14,566) | rate > 99% ✓ |
| Message latency p(95) | **1.06 s** | p(95) < 1.5 s ✓ |
| WS messages delivered | **87,396** | — |
| k6 checks passed | **100%** (43,698 / 43,698) | — |
| Data throughput | **253 MB at ~2.2 MB/s** | — |

**Latency threshold note:** The mock generator emits price ticks every ~1 real second (`CHART_TICK_INTERVAL_SECONDS`). Each tick updates the in-progress 1m candle and rolls up to higher intervals. The k6 threshold is set to 1,500 ms — server-side processing is <50 ms; observed latency is dominated by the tick interval.

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
| **Real wall-clock ticks (~1/s)** | Demo uses actual minute/hour/day boundaries | Candles align to local clock (:00, :05, top-of-hour, midnight). 1m bars update in place until the minute completes; higher intervals roll up from 1m only. |
| **In-memory candle store** | No persistence across restarts | The assignment asks for real-time streaming, not historical persistence. Adding a database would add complexity without demonstrating the core system. |
| **Single WebSocket connection per browser tab** | All panels share one WS | Multiplexing all symbol:interval subscriptions over one connection is more efficient than one WS per panel. Standard practice in trading platforms. |
| **10 mock symbols** | Symbols not specified in brief | 10 symbols covering major crypto and equity demonstrates the multi-symbol workspace feature at a realistic scale. |
| **localStorage for workspace persistence** | No user auth required | Zero-dependency and correct for a single-user scenario. |
| **Variable history depth** | Mock startup speed vs depth | Default: 4,320 1m bars (~3 days) → 200 1m/5m/15m, 72 1h, 3 1d candles. Set `CHART_SEED_1M_BARS` for more. All derived from 1m. |
| **Local candle alignment** | Boundaries match chart labels | `floor_to_interval()` uses `CHART_CANDLE_TIMEZONE` (default: server local). Frontend reads `/config` and sets the chart to the same IANA zone. |
| **Higher-interval open candle published live** | Correct trading-terminal behaviour | When a 5m candle is in progress, subscribers receive rolling updates as each 1m sub-candle arrives. |
| **Out-of-order candles not handled** | Mock generator guarantees monotonic timestamps | In production, apply a reorder buffer before the aggregation engine. |

---

## 6. Aggregation Correctness

All higher-interval candles are derived **strictly from 1-minute data only** — both live and at seed time. Implemented in `backend/src/domain/services/aggregator.py`:

```
Live: sub-minute tick
  → process_tick: accumulate into in-progress 1m candle (local window start)
  → process_1m_candle(1m bar): roll up into 5m / 15m / 1h / 1d

For each 1m candle at timestamp T:
  window_start = floor_to_interval(T, interval)   # local calendar alignment

  If no candle open for this window:
    open   = 1m.open              ← first sub-candle's open, NEVER changes
    high   = 1m.high
    low    = 1m.low
    close  = 1m.close
    volume = 1m.volume

  Else (window already open):
    open   = UNCHANGED
    high   = max(existing.high, 1m.high)
    low    = min(existing.low,  1m.low)
    close  = 1m.close             ← always the last sub-candle
    volume = existing.volume + 1m.volume
```

Unit tests in `backend/tests/` verify 5×1m → 1×5m OHLCV correctness and that bulk replay matches incremental aggregation.

### Sub-minute ticks vs 1-minute source (Requirement.md §03)

The brief requires mock data at the **1-minute** timeframe only. The generator emits **sub-minute price ticks** (~1 per second) for smooth live updates, but these are **not** separate data products — they are accumulated into a single in-progress **1m candle** by `process_tick()`. Only that 1m bar (complete or in-progress) is passed to `process_1m_candle()` to derive 5m, 15m, 1h, and 1d. No higher interval reads tick data directly.

---

## 7. Known Limitations

| Limitation | Impact | Mitigation |
|---|---|---|
| History pagination not implemented | Cannot scroll left for older bars | Documented; store holds fixed depth per interval |
| Per-client timezone | All clients share one backend zone | Set `CHART_CANDLE_TIMEZONE` on the server; frontend syncs via `GET /config`. For multi-region, pass timezone per session (not implemented). |
| No WebSocket heartbeat | Idle connections may drop behind proxies | Client auto-reconnects and resubscribes all panels |
| ~3 days default 1d history | 1d chart shows 3 candles at default seed depth | Set `CHART_SEED_1M_BARS=10080` for ~7 days |
| Mock data only | No real exchange feed | Appropriate for assignment scope |
| Out-of-order ticks not handled | Late ticks could corrupt open candle | Mock generator is monotonic; production needs reorder buffer |
