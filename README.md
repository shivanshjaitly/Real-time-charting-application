# Real-Time Charting Application

Live candlestick charting built on top of the [KlineCharts](https://github.com/klinecharts/KLineChart) library.

---

## Live Demo

**App:** https://charting-frontend.onrender.com/

**Backend health:** https://charting-backend-c4f3.onrender.com/health

The app is deployed on [Render](https://render.com) — a static frontend and a paid Python backend (always on). Open the frontend link in your browser; charts update live over WebSocket once connected.

> **Load time:** The backend stays warm (paid tier). The frontend static site may take **10–15 seconds** on the first load; refresh if the page looks blank initially.

**Design write-up:** [DESIGN.md](./DESIGN.md)

---

## Quick Start (Clone Fresh)

```bash
# 1. Clone the repo
git clone https://github.com/shivanshjaitly/Real-time-charting-application.git
cd Real-time-charting-application

# 2. Install frontend dependencies
pnpm install

# 3. Install backend dependencies
cd backend && python3 -m pip install --user --break-system-packages -r requirements.txt && cd ..

# 4. Terminal 1 — start backend
cd backend && python3 server.py

# 5. Terminal 2 — start frontend (open a new terminal tab)
pnpm debug
```

Open **http://localhost:5173** in your browser. The backend must be running first.

---

**Features:**
- Live candlestick charts with real-time WebSocket updates
- Interval switching: 1m, 5m, 15m, 1h, 1d (clock-aligned to local timezone; higher intervals derived from 1m only)
- Multi-layout views: 1×1, 1×2, 2×1, 2×2, 2×3, 3×1, 3×3, 4×4 grid
- 10 symbols: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, AAPL, MSFT, TSLA, GOOGL, AMZN, NVDA
- Technical indicators: MA, EMA, BOLL, MACD, RSI, KDJ, CCI (toggle per panel)
- Drawing tools: Trend Line, Horizontal, Ray Line, Price Line, Fibonacci, Segment
- Chart snapshot download (PNG, per panel, includes overlays)
- Workspace save/restore (persists layout + symbols + intervals)
- Trading Technologies inspired dark theme

---

## Prerequisites

- **Node.js** ≥ 18 + **pnpm** (`npm install -g pnpm`)
- **Python** ≥ 3.12
- **k6** (for load testing): `brew install k6`

> **Python 3.14 (Homebrew):** Homebrew marks the system Python as externally managed. Use:
> `python3 -m pip install --user --break-system-packages -r requirements.txt`
> instead of plain `pip3 install`. On Python 3.11/3.12, `pip3 install -r requirements.txt` also works.

---

## Frontend Setup

The frontend is built inside the KlineCharts codebase (`debug/` folder). No separate project is scaffolded.

```bash
# From the repo root
pnpm install
pnpm debug
```

Opens at **http://localhost:5173**

> The frontend requires the backend to be running for live data.

---

## Backend Setup

```bash
cd backend
python3 -m pip install --user --break-system-packages -r requirements.txt
python3 server.py
```

Backend runs at **http://localhost:8000**

Startup seeds **4,320 1m bars per symbol** (~3 days) in parallel — typically **under 2 seconds**. Set `CHART_SEED_1M_BARS=10080` in env for ~7 days of 1d history (slower).

- Health check: `GET http://localhost:8000/health`
- WebSocket: `ws://localhost:8000/ws`

---

## Running Both Together

**Terminal 1 — Backend:**
```bash
cd backend && python3 server.py
```

**Terminal 2 — Frontend:**
```bash
pnpm debug
```

Open **http://localhost:5173** in your browser.

---

## Load Test

Requires k6. Run with the backend already started:

```bash
cd backend
python3 server.py &          # start backend in background

k6 run load-test/script.js   # run 1000-user load test
```

Results: `backend/load-test/results.txt` | Screenshot: `backend/load-test/screenshot.png`

**Benchmark summary (1,000 concurrent users — all thresholds ✓):**

| Metric | Result |
|---|---|
| WS sessions | **14,566** |
| Connection errors | **0** (threshold: count < 10) ✓ |
| Subscribe success rate | **100%** (14,566 / 14,566) ✓ |
| Message latency p(95) | **1.06 s** (threshold: p(95) < 1.5 s) ✓ |
| WS messages delivered | **87,396** |
| Data throughput | **253 MB at ~2.2 MB/s** |
| k6 checks passed | **100%** (43,698 / 43,698) |

> **Latency threshold note:** The p(95) threshold is set to 1,500 ms. The mock generator emits price ticks every ~1 second; server-side processing is <50 ms. See [DESIGN.md](./DESIGN.md) §Trade-offs.

---

## Backend Tests

```bash
cd backend
python3 -m unittest discover -s tests -v
```

Tests cover 5×1m → 1×5m OHLCV rollup, in-place 1m tick updates, and bulk replay vs incremental aggregation.

---

## Project Structure

```
/                           ← KlineCharts repo (project root)
  debug/
    index.html              ← App HTML (layout, toolbar, grid)
    main.js                 ← Full frontend app (panels, WS, workspace)
    style.css               ← TT dark theme + grid layout

  backend/
    src/
      api/
        app.py              ← FastAPI app factory
        ws_server.py        ← WebSocket server + subscription manager
      domain/
        entities/           ← Candle, Symbol, Interval
        services/
          aggregator.py     ← 1m ticks → 1m candle → derives 5m/15m/1h/1d
          seed.py             ← History seeding from 1m source only
          time_utils.py       ← local calendar-aligned window floors
      adapters/
        generator.py        ← Sub-minute tick generator (1m source data)
        candle_store.py     ← In-memory ring buffer (max 1000/topic)
        pubsub.py           ← Async pub/sub broker
      infrastructure/
        config.py           ← pydantic-settings
        logging.py          ← structured logging
    server.py               ← Entry point
    requirements.txt
    load-test/
      script.js             ← k6 load test (1000 VUs)
      results.txt           ← Benchmark output
    tests/
      test_aggregator.py    ← OHLCV rollup correctness
      test_seed.py          ← 1m-only seed pipeline

  DESIGN.md                 ← Architecture write-up
  README.md                 ← This file
```

---

## Design Write-Up

See [DESIGN.md](./DESIGN.md) for:
- System architecture diagram + data flow (per 1m tick)
- Technology choice: Python/asyncio vs Go vs Node.js
- Scalability strategy (1,000 concurrent + where it breaks next and why)
- WebSocket vs SSE vs long-polling reasoning
- Trade-offs and assumptions (8 documented decisions)
- Aggregation correctness pseudocode
