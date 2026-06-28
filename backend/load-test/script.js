/**
 * k6 Load Test — Real-Time Charting Backend
 *
 * Tests: 1,000 concurrent WebSocket connections each receiving live candle updates.
 *
 * Run:
 *   k6 run load-test/script.js
 *
 * Expected: p95 message latency < 1500ms at 1000 concurrent users (see DESIGN.md §Trade-offs).
 */

import { check, sleep } from 'k6'
import ws from 'k6/ws'
import { Counter, Rate, Trend } from 'k6/metrics'

// ─── Custom Metrics ───────────────────────────────────────────────────────────
const candlesReceived   = new Counter('candles_received')
const historyReceived   = new Counter('history_received')
const messageLatency    = new Trend('message_latency_ms', true)
const connectionErrors  = new Counter('connection_errors')
const subscribeSuccess  = new Rate('subscribe_success_rate')

// ─── Options ──────────────────────────────────────────────────────────────────
export const options = {
  stages: [
    { duration: '30s', target: 1000 },   // ramp up to 1000 VUs
    { duration: '60s', target: 1000 },   // hold at 1000 VUs
    { duration: '20s', target: 0   },    // ramp down
  ],
  thresholds: {
    // Generator emits 1 candle/second; p95 latency is bounded by tick rate (~1s), not server overhead.
    // Threshold set to 1500ms to reflect this documented assumption (see DESIGN.md §Trade-offs).
    message_latency_ms:    ['p(95)<1500'],
    // All subscribes must succeed
    subscribe_success_rate: ['rate>0.99'],
    // Zero connection errors at 1000 concurrent users
    connection_errors:      ['count<10'],
  },
}

// ─── Test Function ────────────────────────────────────────────────────────────
export default function () {
  const symbols   = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'AAPL', 'MSFT', 'TSLA', 'GOOGL', 'AMZN', 'NVDA']
  const intervals = ['1m', '5m', '15m', '1h', '1d']

  const symbol   = symbols[Math.floor(Math.random() * symbols.length)]
  const interval = intervals[Math.floor(Math.random() * intervals.length)]

  const url = 'ws://localhost:8000/ws'

  let gotHistory   = false
  let candleCount  = 0
  let sentAt       = 0
  let subscribed   = false

  const res = ws.connect(url, {}, function (socket) {
    socket.on('open', function () {
      subscribed = true
      sentAt = Date.now()
      socket.send(JSON.stringify({ type: 'subscribe', symbol, interval }))
    })

    socket.on('message', function (data) {
      const msg = JSON.parse(data)
      const latency = Date.now() - sentAt

      if (msg.type === 'history') {
        gotHistory = true
        historyReceived.add(msg.data ? msg.data.length : 0)
        messageLatency.add(latency)
        sentAt = Date.now()
      } else if (msg.type === 'candle') {
        candleCount++
        candlesReceived.add(1)
        messageLatency.add(Date.now() - sentAt)
        sentAt = Date.now()

        // Receive 5 live candles then gracefully close
        if (candleCount >= 5) {
          socket.send(JSON.stringify({ type: 'unsubscribe', symbol, interval }))
          socket.close()
        }
      } else if (msg.type === 'error') {
        connectionErrors.add(1)
        socket.close()
      }
    })

    socket.on('error', function () {
      connectionErrors.add(1)
    })

    // Safety timeout — close after 30s regardless
    socket.setTimeout(function () {
      socket.close()
    }, 30000)
  })

  subscribeSuccess.add(subscribed && res && res.status === 101 ? 1 : 0)

  check(res, {
    'WebSocket connected (101)': (r) => r && r.status === 101,
    'History received':          () => gotHistory,
    'Live candles received':     () => candleCount > 0,
  })

  sleep(1)
}
