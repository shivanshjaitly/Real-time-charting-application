# MASTER PLAN — Real-Time Charting Application
> Single source of truth. Read this before touching any file.
> Every decision here is final and locked to the Requirement.md.

---

## 0. The Non-Negotiable Rules (Requirement.md)

1. Clone `klinecharts/KLineChart` — this IS the project repo (not a separate app)
2. All frontend code goes inside `debug/` folder of that repo — nowhere else
3. Zero new entries in the root `package.json` — use only what KlineCharts ships
4. Backend is a completely separate service with its own `requirements.txt`
5. Generate mock data for **1-minute only** — derive everything else from 1m
6. Load test must be **real, run, with benchmark output + screenshot**
7. Design write-up (`DESIGN.md`) with architecture **diagram** is mandatory
8. Submit by **Monday 11:00 PM** via email reply with repo link + DESIGN.md

---

## 1. Repository Structure (Final)

```
klinecharts/KLineChart/               ← THE project repo (cloned from official)
  debug/                              ← ALL frontend lives here
    index.html                        ← extended (layout grid, symbol selector, workspace buttons)
    main.js                           ← extended (multi-panel, WebSocket service, workspace)
    style.css                         ← extended (TT dark theme, CSS grid layout)

  backend/                            ← separate service, own requirements.txt
    src/
      api/
        app.py                        ← create_app() factory
        ws_server.py                  ← WebSocket endpoint + subscription manager
        heartbeat.py                  ← connection keepalive
        health.py                     ← GET /health
      domain/
        entities/
          candle.py                   ← Candle dataclass {timestamp,open,high,low,close,volume}
          symbol.py                   ← Symbol enum, Interval enum + ms mapping
        ports/
          data_port.py                ← IDataGenerator, ICandleStore (abstract)
          pubsub_port.py              ← IPubSub (abstract)
        services/
          aggregator.py               ← derives 5m/15m/1h/1d from 1m only
          subscription_service.py     ← tracks client → {symbol, interval} subscriptions
      adapters/
        generator.py                  ← mock 1m candle generator (random walk)
        candle_store.py               ← in-memory ring buffer (200 candles per topic)
        pubsub.py                     ← in-memory asyncio pub/sub
      infrastructure/
        config.py                     ← pydantic-settings (host, port, tick_ms, symbols)
        logging.py                    ← structured logger
    server.py                         ← entry point: uvicorn src.api.app:create_app()
    requirements.txt
    load-test/
      script.js                       ← k6 script (1000 VUs, WS connect + subscribe + receive)
      results.txt                     ← k6 benchmark output (attached after run)
      screenshot.png                  ← terminal screenshot of k6 run

  DESIGN.md                           ← architecture write-up (required deliverable)
  README.md                           ← setup + run instructions for both frontend and backend
```

---

## 2. Frontend (inside `debug/`)

### What Already Exists in `debug/`
- `index.html` — has period switcher buttons (1m, 5m, 15m, 1h, 1d) + `#chart` div
- `main.js` — imports from `../src/index.ts`, uses `init()`, `setDataLoader()`, `setPeriod()`
- `style.css` — basic styles

### What We Add / Extend

#### `debug/index.html` changes
- Wrap `#chart` in a layout container
- Add layout switcher (1×1 | 2×2 buttons)
- Add symbol selector (BTCUSDT / ETHUSDT / AAPL) per panel
- Add workspace save/restore buttons
- Keep ALL existing period switcher buttons

#### `debug/main.js` changes

**Multi-panel system:**
```
panelCount: 1 (1×1) or 4 (2×2)
Each panel has: { chartInstance, symbol, interval, wsConnection }
```

**WebSocket integration via `setDataLoader`:**
```js
setDataLoader({
  getBars: ({ type, timestamp, period, callback }) => {
    // Send { type: "history", symbol, interval } to backend
    // Receive history array → callback(bars, { forward: false, backward: false })
  },
  subscribeBar: ({ period, callback }) => {
    // Send { type: "subscribe", symbol, interval } to backend
    // On each incoming candle: callback(candle, true)  ← true = partial/live update
  },
  unsubscribeBar: () => {
    // Send { type: "unsubscribe", symbol, interval } to backend
  }
})
```

**Workspace save/restore via localStorage:**
```js
// Save
localStorage.setItem('workspace', JSON.stringify({
  layout: '1x1' | '2x2',
  panels: [{ symbol: 'BTCUSDT', interval: '1m' }, ...]
}))

// Restore on load
const saved = JSON.parse(localStorage.getItem('workspace') ?? 'null')
if (saved) applyWorkspace(saved)
```

### Color Theme (Trading Technologies reference)
| Element | Value |
|---|---|
| Background | `#131722` |
| Grid lines | `#2a2e39` |
| Bullish candle | `#26a69a` |
| Bearish candle | `#ef5350` |
| Text | `#d1d4dc` |
| Border | `#363c4e` |

Applied via `chart.setStyles({ ... })` — no new library.

### Layouts
| Mode | CSS | Panels |
|---|---|---|
| 1×1 | `grid-template-columns: 1fr` | 1 chart, full width |
| 2×2 | `grid-template-columns: 1fr 1fr` | 4 charts, equal grid |

---

## 3. Backend (Python FastAPI)

### Stack
- Python 3.12
- FastAPI + uvicorn
- Native `fastapi.WebSocket` (NOT Socket.IO — raw WS is what KlineCharts frontend expects)
- Pydantic v2 for all models
- pydantic-settings for config
- asyncio throughout

### WebSocket Message Contract

**Client → Server:**
```json
{ "type": "subscribe",   "symbol": "BTCUSDT", "interval": "1m" }
{ "type": "unsubscribe", "symbol": "BTCUSDT", "interval": "1m" }
{ "type": "history",     "symbol": "BTCUSDT", "interval": "1m" }
```

**Server → Client:**
```json
{ "type": "history", "symbol": "BTCUSDT", "interval": "1m", "data": [ ...200 candles ] }
{ "type": "candle",  "symbol": "BTCUSDT", "interval": "1m", "data": { "timestamp": 1234567890000, "open": 50000.00, "high": 50200.00, "low": 49800.00, "close": 50100.00, "volume": 1230 } }
{ "type": "error",   "message": "unknown interval" }
```

### Data Model
```python
@dataclass
class Candle:
    timestamp: int    # Unix ms — start of candle window
    open: float
    high: float
    low: float
    close: float
    volume: float
```

### Interval Mapping
| Interval key | Milliseconds |
|---|---|
| `1m`  | 60_000 |
| `5m`  | 300_000 |
| `15m` | 900_000 |
| `1h`  | 3_600_000 |
| `1d`  | 86_400_000 |

### Mock Symbols
- `BTCUSDT` — base price ~50,000
- `ETHUSDT` — base price ~3,000
- `AAPL`    — base price ~195

### Data Generator (`adapters/generator.py`)
- Emits a new 1m candle **every 1 real second** (time compression for demo)
- Random walk: each candle's open = previous candle's close
- Realistic OHLCV with wicks and volume spikes
- Runs as an `asyncio` background task (started in lifespan)

### Aggregation Engine (`domain/services/aggregator.py`) — THE CRITICAL PIECE

```
For every incoming 1m candle (symbol, 1m_candle):
  For each higher interval in [5m, 15m, 1h, 1d]:
    window_start = floor(candle.timestamp / interval_ms) * interval_ms

    If no open candle for this window:
      Create: { open=candle.open, high=candle.high, low=candle.low,
                close=candle.close, volume=candle.volume, timestamp=window_start }
    Else:
      Update:
        high  = max(existing.high,   candle.high)   ← extremes
        low   = min(existing.low,    candle.low)    ← extremes
        close = candle.close                         ← always last
        volume += candle.volume                      ← cumulative sum
        open stays UNCHANGED                         ← always first

    Publish updated (live/in-progress) candle to all subscribers of symbol:interval
```

**Aggregation Rules (exact, from Requirement.md §03):**
- `open`   = first sub-candle's open — **never changes**
- `close`  = last sub-candle's close — **updates on every 1m tick**
- `high`   = max across all sub-candles — **updates on every 1m tick**
- `low`    = min across all sub-candles — **updates on every 1m tick**
- `volume` = sum of all sub-candle volumes — **updates on every 1m tick**

### Pub/Sub (`adapters/pubsub.py`)
- In-memory `dict[str, set[asyncio.Queue]]` — topic → set of subscriber queues
- Topic key: `"BTCUSDT:1m"`, `"BTCUSDT:5m"`, etc.
- `publish(topic, candle)` → puts candle into all subscriber queues
- `subscribe(topic)` → returns a new Queue
- `unsubscribe(topic, queue)` → removes queue from set

### Subscription Manager (`domain/services/subscription_service.py`)
- Tracks: `ws_client_id → set of (symbol, interval)` subscriptions
- On WS disconnect → auto-unsubscribe all topics for that client
- Prevents duplicate subscriptions per client

### Candle Store (`adapters/candle_store.py`)
- Ring buffer: `deque(maxlen=200)` per topic
- When history is requested → return last 200 candles for that topic
- Updated on every published candle

### Scalability (for DESIGN.md)
| Tier | Handles | Mechanism |
|---|---|---|
| Single process | ~5,000 WS connections | asyncio event loop, non-blocking |
| Next bottleneck | CPU-bound aggregation at very high concurrency | Move to Redis Pub/Sub + multiple workers |
| Load target (assignment) | 1,000 concurrent | Easily handled by single asyncio process |

---

## 4. Load Test (k6)

**Script logic:**
1. 1000 virtual users
2. Each VU: connect WS → send subscribe BTCUSDT:1m → receive 10 candle updates → disconnect
3. Ramp: 0 → 1000 VUs over 30s, hold 60s, ramp down 30s
4. Assertions: 95% of candle messages received within 500ms

**Run command:**
```bash
k6 run load-test/script.js
```

**Deliverables:**
- `load-test/results.txt` — k6 summary output (copy-paste)
- `load-test/screenshot.png` — terminal screenshot

---

## 5. Design Write-Up (DESIGN.md) — Required Sections

### 5.1 System Architecture (with Mermaid diagram)
```
Frontend (debug/) ←→ WebSocket ←→ Backend (FastAPI)
                                       ├── Generator (1m ticks)
                                       ├── Aggregator (→5m/15m/1h/1d)
                                       ├── PubSub (topic fan-out)
                                       └── CandleStore (history)
```

### 5.2 Scalability Strategy
- Single asyncio process → 1000+ concurrent WS
- Where it breaks: ~5000+ connections (GIL + serialization overhead)
- Next step: Redis Pub/Sub + N workers behind nginx

### 5.3 Real-Time Transport Choice
- **WebSocket** over SSE because: bidirectional subscribe/unsubscribe messages
- SSE is server-push only — cannot send subscription commands

### 5.4 Trade-offs and Assumptions
- 1 real second = 1 simulated minute (time compression for demo)
- In-memory storage — no persistence across restarts
- 3 mock symbols only (BTCUSDT, ETHUSDT, AAPL)
- localStorage for workspace — no user auth needed
- History: last 200 candles per topic

---

## 6. README.md — Required Sections

```markdown
## Frontend (KlineCharts debug app)
cd klinecharts/KLineChart
pnpm install
pnpm debug          # → http://localhost:5173

## Backend
cd backend
pip install -r requirements.txt
python server.py    # → ws://localhost:8000/ws

## Load Test
npm install -g k6
cd backend/load-test
k6 run script.js
```

---

## 7. Build Order (Do Not Deviate)

1. Clone `klinecharts/KLineChart`, run `pnpm install`, verify `pnpm debug` boots
2. Backend: `Candle` entity + `Interval` enum
3. Backend: `aggregator.py` — write + verify aggregation rules with unit test
4. Backend: `generator.py` + `pubsub.py` + `candle_store.py`
5. Backend: `ws_server.py` — connect everything, verify single client end-to-end
6. Frontend: wire `subscribeBar` + `getBars` to backend WS in `debug/main.js`
7. Frontend: verify single chart live-updates end-to-end
8. Frontend: multi-layout (1×1 / 2×2) + symbol selector
9. Frontend: workspace save/restore
10. Frontend: TT color theme via `chart.setStyles()`
11. Run load test → capture results + screenshot
12. Write `DESIGN.md` + `README.md`
13. Push to public GitHub repo

---

## 8. Symbols of Truth

- Official repo: `https://github.com/klinecharts/KLineChart`
- Debug script in `package.json`: `"debug": "vite --host 0.0.0.0 debug"`
- KlineCharts API entry points: `init()`, `dispose()`, `setDataLoader()`, `setPeriod()`, `setStyles()`, `setSymbol()`
- `subscribeBar.callback(candle, isPartial)` — `true` means live in-progress candle
- Assignment deadline: Monday 11:00 PM
- Submit: reply to email with GitHub repo link + DESIGN.md
