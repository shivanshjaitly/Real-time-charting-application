/**
 * Real-Time Charting Platform
 *
 * Built inside the KlineCharts codebase (debug/ folder).
 * No new external libraries — uses only what KlineCharts ships.
 *
 * KlineCharts v10 API used:
 *  - init(dom, options)           → create chart instance
 *  - chart.setSymbol(...)         → set ticker metadata
 *  - chart.setPeriod(...)         → set active interval
 *  - chart.setStyles(...)         → apply color theme
 *  - chart.setDataLoader(loader)  → hook for history + live data
 *  - dispose(dom)                 → destroy chart instance
 */

import { dispose, init } from '../src/index.ts'

// ─── Constants ────────────────────────────────────────────────────────────────

function resolveWsUrl () {
  const backend = import.meta.env.VITE_WS_URL
  if (backend) {
    return backend.replace(/^http/i, 'ws').replace(/\/$/, '') + '/ws'
  }
  return 'ws://localhost:8000/ws'
}

function resolveApiBase () {
  return WS_URL.replace(/^wss:\/\//i, 'https://').replace(/^ws:\/\//i, 'http://').replace(/\/ws$/, '')
}

const WS_URL = resolveWsUrl()
const WORKSPACE_KEY = 'chartpro:workspace'

const FALLBACK_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'AAPL', 'MSFT', 'TSLA', 'GOOGL', 'AMZN', 'NVDA']

async function fetchSymbols () {
  const res = await fetch(`${resolveApiBase()}/symbols`)
  if (!res.ok) throw new Error(`symbols fetch failed: ${res.status}`)
  const { symbols } = await res.json()
  if (!Array.isArray(symbols) || symbols.length === 0) throw new Error('empty symbols list')
  return symbols
}

const PERIODS = [
  { key: '1m',  label: '1m',  period: { span: 1,  type: 'minute' } },
  { key: '5m',  label: '5m',  period: { span: 5,  type: 'minute' } },
  { key: '15m', label: '15m', period: { span: 15, type: 'minute' } },
  { key: '1h',  label: '1h',  period: { span: 1,  type: 'hour'   } },
  { key: '1d',  label: '1d',  period: { span: 1,  type: 'day'    } },
]

/** Convert KlineCharts period object → backend interval key */
function periodToKey (period) {
  for (const p of PERIODS) {
    if (p.period.span === period.span && p.period.type === period.type) return p.key
  }
  return '1m'
}

const INDICATORS = [
  { key: 'MA',   label: 'MA'   },
  { key: 'EMA',  label: 'EMA'  },
  { key: 'BOLL', label: 'BOLL' },
  { key: 'MACD', label: 'MACD' },
  { key: 'RSI',  label: 'RSI'  },
  { key: 'KDJ',  label: 'KDJ'  },
  { key: 'CCI',  label: 'CCI'  },
]

const OVERLAY_INDICATORS = new Set(['MA', 'EMA', 'BOLL'])

const OVERLAYS = [
  { key: 'straightLine',           label: 'Trend Line'  },
  { key: 'horizontalStraightLine', label: 'Horizontal'  },
  { key: 'rayLine',                label: 'Ray Line'    },
  { key: 'priceLine',              label: 'Price Line'  },
  { key: 'fibonacciLine',          label: 'Fibonacci'   },
  { key: 'segment',                label: 'Segment'     },
]

const KLINE_STYLES = {
  grid: {
    horizontal: { color: '#2a2e39', size: 1, style: 'solid', show: true },
    vertical:   { color: '#2a2e39', size: 1, style: 'solid', show: true },
  },
  candle: {
    bar: {
      upColor:       '#26a69a',
      downColor:     '#ef5350',
      noChangeColor: '#888888',
    },
    priceMark: {
      last: {
        upColor:   '#26a69a',
        downColor: '#ef5350',
        show:      true,
        line: { show: true },
        text: { show: true },
      },
    },
  },
  xAxis: {
    axisLine: { color: '#2a2e39' },
    tickLine: { color: '#2a2e39' },
    tickText: { color: '#787b86' },
  },
  yAxis: {
    axisLine: { color: '#2a2e39' },
    tickLine: { color: '#2a2e39' },
    tickText: { color: '#787b86' },
  },
  crosshair: {
    show: true,
    horizontal: { line: { color: '#434651', style: 'dashed', size: 1 } },
    vertical:   { line: { color: '#434651', style: 'dashed', size: 1 } },
  },
  background: { color: '#131722' },
}

// ─── WebSocket Manager ────────────────────────────────────────────────────────
// Single shared WS connection. All panel subscriptions route through here.

class WSManager {
  constructor () {
    this._ws              = null
    this._ready           = false
    this._queue           = []           // messages queued before connection opens
    this._candleHandlers  = {}           // topic → fn(candle)
    this._historyHandlers = {}           // topic → fn(candles[])
    this._reconnectTimer  = null
    this._intentionalClose = false
    this._connect()
  }

  _setStatus (s) {
    const el = document.getElementById('ws-status')
    if (el) { el.className = `ws-dot ${s}`; el.title = `WebSocket: ${s}` }
  }

  _connect () {
    this._setStatus('connecting')
    this._ws = new WebSocket(WS_URL)

    this._ws.onopen = () => {
      this._ready = true
      this._setStatus('connected')
      // Flush queued messages
      while (this._queue.length) this._ws.send(this._queue.shift())
    }

    this._ws.onmessage = ({ data }) => {
      let msg; try { msg = JSON.parse(data) } catch { return }
      const topic = `${msg.symbol}:${msg.interval}`
      if (msg.type === 'history') {
        const h = this._historyHandlers[topic]
        if (h) { h(msg.data || []); delete this._historyHandlers[topic] }
      } else if (msg.type === 'candle') {
        const fn = this._candleHandlers[topic]
        if (fn) fn(msg.data)
      }
    }

    this._ws.onclose = () => {
      this._ready = false
      this._setStatus('disconnected')
      if (!this._intentionalClose) {
        this._reconnectTimer = setTimeout(() => this._connect(), 2000)
      }
    }

    this._ws.onerror = () => this._setStatus('disconnected')
  }

  _send (payload) {
    const str = JSON.stringify(payload)
    if (this._ready && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(str)
    } else {
      this._queue.push(str)
    }
  }

  /** Register a one-shot history callback for symbol:interval */
  onHistory (symbol, interval, fn) {
    this._historyHandlers[`${symbol}:${interval}`] = fn
  }

  /** Register live candle callback. Returns unsubscribe fn. */
  onCandle (symbol, interval, fn) {
    const topic = `${symbol}:${interval}`
    this._candleHandlers[topic] = fn
    return () => { delete this._candleHandlers[topic] }
  }

  subscribe   (symbol, interval) { this._send({ type: 'subscribe',   symbol, interval }) }
  unsubscribe (symbol, interval) { this._send({ type: 'unsubscribe', symbol, interval }) }

  destroy () {
    this._intentionalClose = true
    clearTimeout(this._reconnectTimer)
    if (this._ws) this._ws.close()
  }
}

// ─── Chart Panel ──────────────────────────────────────────────────────────────

class ChartPanel {
  constructor (panelEl, wsManager, symbols, symbol = 'BTCUSDT', interval = '1m', indicators = []) {
    this._el               = panelEl
    this._ws               = wsManager
    this._symbols          = symbols
    this._symbol           = symbols.includes(symbol) ? symbol : symbols[0]
    this._interval         = interval
    this._chart            = null
    this._unsubFn          = null
    this._activeIndicators = new Set(Array.isArray(indicators) ? indicators : [])
    this._closeDropdowns   = null

    this._render()
    this._mountChart()
  }

  // ── DOM ──────────────────────────────────────────────────────────────────────

  _render () {
    if (this._closeDropdowns) document.removeEventListener('click', this._closeDropdowns)

    if (this._chart) {
      this._teardownChartSubscription()
      dispose(this._chart)
      this._chart = null
    }

    this._el.innerHTML = `
      <div class="panel-toolbar">
        <select class="symbol-select" aria-label="Symbol">
          ${this._symbols.map(s => `<option value="${s}"${s === this._symbol ? ' selected' : ''}>${s}</option>`).join('')}
        </select>
        <span class="live-badge">LIVE</span>
        <div class="period-switcher">
          ${PERIODS.map(p => `<button data-period="${p.key}" type="button" class="${p.key === this._interval ? 'active' : ''}">${p.label}</button>`).join('')}
        </div>
        <div class="panel-tools">
          <div class="tool-dropdown">
            <button class="tool-btn" type="button" title="Indicators">Ind ▾</button>
            <div class="dropdown-menu">
              ${INDICATORS.map(i => `<button class="drop-item" data-ind="${i.key}" type="button">${i.label}</button>`).join('')}
            </div>
          </div>
          <div class="tool-dropdown">
            <button class="tool-btn" type="button" title="Drawing Tools">Draw ▾</button>
            <div class="dropdown-menu">
              ${OVERLAYS.map(o => `<button class="drop-item" data-overlay="${o.key}" type="button">${o.label}</button>`).join('')}
            </div>
          </div>
          <button class="tool-btn snap-btn" type="button" title="Download chart snapshot">📷</button>
        </div>
      </div>
      <div class="chart-canvas"></div>
    `

    this._el.querySelector('.symbol-select').addEventListener('change', e => this._changeSymbol(e.target.value))

    this._el.querySelectorAll('.period-switcher button').forEach(btn =>
      btn.addEventListener('click', () => this._changeInterval(btn.dataset.period))
    )

    // Dropdown open/close toggle
    this._el.querySelectorAll('.tool-dropdown').forEach(drop => {
      drop.querySelector('.tool-btn').addEventListener('click', e => {
        e.stopPropagation()
        this._el.querySelectorAll('.tool-dropdown.open').forEach(d => { if (d !== drop) d.classList.remove('open') })
        drop.classList.toggle('open')
      })
    })

    // Indicator toggle
    this._el.querySelectorAll('[data-ind]').forEach(btn =>
      btn.addEventListener('click', e => { e.stopPropagation(); this._toggleIndicator(btn.dataset.ind) })
    )

    // Drawing tool selection
    this._el.querySelectorAll('[data-overlay]').forEach(btn =>
      btn.addEventListener('click', e => {
        e.stopPropagation()
        this._startDrawing(btn.dataset.overlay)
        btn.closest('.tool-dropdown').classList.remove('open')
      })
    )

    // Snapshot
    this._el.querySelector('.snap-btn').addEventListener('click', () => this._snapshot())

    // Close any open dropdown on outside click
    this._closeDropdowns = () => this._el.querySelectorAll('.tool-dropdown.open').forEach(d => d.classList.remove('open'))
    document.addEventListener('click', this._closeDropdowns)

    this._syncIndicatorButtons()
  }

  _updatePeriodButtons () {
    this._el.querySelectorAll('.period-switcher button').forEach(btn =>
      btn.classList.toggle('active', btn.dataset.period === this._interval)
    )
  }

  _createIndicatorOnChart (name) {
    if (OVERLAY_INDICATORS.has(name)) {
      this._chart.createIndicator(name, { isStack: true, pane: { id: 'candle_pane' } })
    } else {
      this._chart.createIndicator(name)
    }
  }

  _teardownChartSubscription () {
    this._ws.unsubscribe(this._symbol, this._interval)
    if (this._unsubFn) { this._unsubFn(); this._unsubFn = null }
  }

  _rebuildActiveIndicators () {
    if (!this._chart || this._activeIndicators.size === 0) return
    for (const name of [...this._activeIndicators]) {
      this._chart.removeIndicator({ name })
    }
    const ordered = [...this._activeIndicators].sort((a, b) => {
      const ao = OVERLAY_INDICATORS.has(a)
      const bo = OVERLAY_INDICATORS.has(b)
      if (ao === bo) return 0
      return ao ? -1 : 1
    })
    for (const name of ordered) this._createIndicatorOnChart(name)
    this._syncIndicatorButtons()
  }

  _syncIndicatorButtons () {
    this._el.querySelectorAll('[data-ind]').forEach(btn =>
      btn.classList.toggle('active', this._activeIndicators.has(btn.dataset.ind))
    )
  }

  _applyActiveIndicators () {
    queueMicrotask(() => this._rebuildActiveIndicators())
  }

  _toggleIndicator (name) {
    if (!this._chart) return
    if (this._activeIndicators.has(name)) {
      this._chart.removeIndicator({ name })
      this._activeIndicators.delete(name)
    } else {
      this._createIndicatorOnChart(name)
      this._activeIndicators.add(name)
    }
    this._syncIndicatorButtons()
  }

  _startDrawing (overlayKey) {
    if (this._chart) this._chart.createOverlay(overlayKey)
  }

  _snapshot () {
    if (!this._chart) return
    const url = this._chart.getConvertPictureUrl(true, 'png', '#131722')
    const a = document.createElement('a')
    a.href = url
    a.download = `${this._symbol}-${this._interval}-${Date.now()}.png`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  // ── KlineCharts v10 — setDataLoader integration ───────────────────────────

  _mountChart () {
    const canvas = this._el.querySelector('.chart-canvas')

    if (this._chart) {
      this._teardownChartSubscription()
      dispose(this._chart)
      this._chart = null
    }

    this._chart = init(canvas, {
      layout: {
        panes: [
          { type: 'candle' },
          { type: 'indicator', content: ['VOL'] },
        ],
      },
      timezone: 'UTC',
    })

    this._chart.setStyles(KLINE_STYLES)

    const periodCfg = PERIODS.find(p => p.key === this._interval) || PERIODS[0]
    const self     = this

    this._chart.setSymbol({
      ticker:          this._symbol,
      pricePrecision:  2,
      volumePrecision: 0,
    })
    this._chart.setPeriod(periodCfg.period)

    this._chart.setDataLoader({
      getBars: ({ type, period, symbol, callback }) => {
        if (type !== 'init') {
          // forward/backward paging — we don't support infinite scroll yet
          callback([], { forward: true, backward: true })
          return
        }
        const intervalKey = periodToKey(period)
        const ticker = symbol.ticker
        self._ws.onHistory(ticker, intervalKey, (candles) => {
          callback(candles, { forward: true, backward: false })
          self._applyActiveIndicators()
        })
        self._ws.subscribe(ticker, intervalKey)
      },

      subscribeBar: ({ period, symbol, callback }) => {
        const intervalKey = periodToKey(period)
        const ticker = symbol.ticker
        self._interval = intervalKey
        self._unsubFn = self._ws.onCandle(ticker, intervalKey, (candle) => {
          callback(candle)
        })
      },

      unsubscribeBar: ({ period, symbol }) => {
        const intervalKey = periodToKey(period)
        self._ws.unsubscribe(symbol.ticker, intervalKey)
        if (self._unsubFn) { self._unsubFn(); self._unsubFn = null }
      },
    })

    this._syncIndicatorButtons()
  }

  // ── Controls ─────────────────────────────────────────────────────────────────

  _changeSymbol (symbol) {
    if (symbol === this._symbol) return
    const savedIndicators = [...this._activeIndicators]

    if (this._chart) {
      this._ws.unsubscribe(this._symbol, this._interval)
      if (this._unsubFn) { this._unsubFn(); this._unsubFn = null }
      dispose(this._chart)
      this._chart = null
    }

    this._symbol = symbol

    const select = this._el.querySelector('.symbol-select')
    if (select) select.value = symbol

    this._activeIndicators = new Set(savedIndicators)
    this._syncIndicatorButtons()
    this._mountChart()
  }

  _changeInterval (intervalKey) {
    if (intervalKey === this._interval) return
    this._interval = intervalKey
    this._updatePeriodButtons()

    const periodCfg = PERIODS.find(p => p.key === intervalKey)
    if (periodCfg && this._chart) {
      // setPeriod triggers unsubscribeBar → getBars(init) → subscribeBar automatically
      this._chart.setPeriod(periodCfg.period)
    }
  }

  // ── Workspace ────────────────────────────────────────────────────────────────

  getState () {
    return {
      symbol:     this._symbol,
      interval:   this._interval,
      indicators: [...this._activeIndicators],
    }
  }

  destroy () {
    this._teardownChartSubscription()
    if (this._chart) { dispose(this._chart); this._chart = null }
    if (this._closeDropdowns) { document.removeEventListener('click', this._closeDropdowns); this._closeDropdowns = null }
  }
}

// ─── App ──────────────────────────────────────────────────────────────────────

class App {
  constructor (symbols) {
    this._symbols = symbols
    this._layout = '1x1'
    this._panels = []
    this._ws     = new WSManager()
    this._grid   = document.getElementById('chart-grid')

    this._bindControls()
    this._applyLayout('1x1')
  }

  _bindControls () {
    document.querySelectorAll('#layout-switcher button').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.layout === this._layout) return
        document.querySelectorAll('#layout-switcher button').forEach(b => b.classList.remove('active'))
        btn.classList.add('active')
        this._applyLayout(btn.dataset.layout)
      })
    })

    document.getElementById('btn-save').addEventListener('click',    () => this._saveWorkspace())
    document.getElementById('btn-restore').addEventListener('click', () => this._restoreWorkspace())
  }

  _applyLayout (layout, states = null) {
    this._panels.forEach(p => p.destroy())
    this._panels = []

    this._layout = layout
    this._grid.className = `layout-${layout}`
    this._grid.innerHTML = ''

    const LAYOUT_COUNT = { '1x1': 1, '1x2': 2, '2x1': 2, '2x2': 4, '2x3': 6, '3x1': 3, '3x3': 9, '4x4': 16 }
    const count = LAYOUT_COUNT[layout] ?? 1

    const defaults = [
      { symbol: 'BTCUSDT', interval: '1m'  },
      { symbol: 'ETHUSDT', interval: '5m'  },
      { symbol: 'BTCUSDT', interval: '1h'  },
      { symbol: 'AAPL',    interval: '1d'  },
      { symbol: 'SOLUSDT', interval: '15m' },
      { symbol: 'MSFT',    interval: '1d'  },
      { symbol: 'BNBUSDT', interval: '1m'  },
      { symbol: 'TSLA',    interval: '5m'  },
      { symbol: 'GOOGL',   interval: '1h'  },
      { symbol: 'AMZN',    interval: '15m' },
      { symbol: 'NVDA',    interval: '1d'  },
      { symbol: 'ETHUSDT', interval: '1h'  },
      { symbol: 'SOLUSDT', interval: '1d'  },
      { symbol: 'BTCUSDT', interval: '5m'  },
      { symbol: 'MSFT',    interval: '15m' },
      { symbol: 'TSLA',    interval: '1h'  },
      { symbol: 'GOOGL',   interval: '1d'  },
      { symbol: 'AMZN',    interval: '1h'  },
    ]

    for (let i = 0; i < count; i++) {
      const panelEl = document.createElement('div')
      panelEl.className = 'chart-panel'
      this._grid.appendChild(panelEl)

      const st = (states && states[i]) ? states[i] : defaults[i]
      const symbol = this._symbols.includes(st.symbol) ? st.symbol : this._symbols[0]
      this._panels.push(new ChartPanel(panelEl, this._ws, this._symbols, symbol, st.interval, st.indicators))
    }
  }

  _saveWorkspace () {
    localStorage.setItem(WORKSPACE_KEY, JSON.stringify({
      layout:  this._layout,
      panels:  this._panels.map(p => p.getState()),
      savedAt: new Date().toISOString(),
    }))
    const btn = document.getElementById('btn-save')
    const orig = btn.textContent
    btn.textContent = '✅ Saved!'
    setTimeout(() => { btn.textContent = orig }, 1500)
  }

  _restoreWorkspace () {
    const raw = localStorage.getItem(WORKSPACE_KEY)
    if (!raw) { alert('No saved workspace found.'); return }
    let ws
    try { ws = JSON.parse(raw) } catch { alert('Workspace data is corrupt.'); return }

    document.querySelectorAll('#layout-switcher button').forEach(btn =>
      btn.classList.toggle('active', btn.dataset.layout === ws.layout)
    )
    this._applyLayout(ws.layout || '1x1', ws.panels || [])

    const btn = document.getElementById('btn-restore')
    const orig = btn.textContent
    btn.textContent = '✅ Restored!'
    setTimeout(() => { btn.textContent = orig }, 1500)
  }
}

// ─── Bootstrap ────────────────────────────────────────────────────────────────

let app

fetchSymbols()
  .catch(() => FALLBACK_SYMBOLS)
  .then((symbols) => {
    app = new App(symbols)
    window.addEventListener('beforeunload', () => {
      app._panels.forEach(p => p.destroy())
      app._ws.destroy()
    })
  })
