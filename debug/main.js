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

function browserTimezone () {
  return Intl.DateTimeFormat().resolvedOptions().timeZone
}

async function fetchConfig () {
  try {
    const res = await fetch(`${resolveApiBase()}/config`)
    if (!res.ok) throw new Error(`config fetch failed: ${res.status}`)
    const { candle_timezone: candleTimezone } = await res.json()
    if (typeof candleTimezone === 'string' && candleTimezone.length > 0) {
      return { candleTimezone }
    }
  } catch (_) { /* backend may be offline during dev */ }
  return { candleTimezone: browserTimezone() }
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

/** Default params and settings schema per indicator (matches KlineCharts built-ins). */
const INDICATOR_CONFIGS = {
  MA: {
    type: 'periods',
    defaultParams: [5, 10, 30, 60],
    presetPeriods: [5, 10, 20, 30, 60, 120, 200],
  },
  EMA: {
    type: 'periods',
    defaultParams: [6, 12, 20],
    presetPeriods: [6, 9, 12, 20, 26, 50, 100, 200],
  },
  BOLL: {
    type: 'fields',
    defaultParams: [20, 2],
    fields: [
      { label: 'Period', min: 1, max: 500, step: 1 },
      { label: 'Std Dev', min: 0.1, max: 10, step: 0.1 },
    ],
  },
  MACD: {
    type: 'fields',
    defaultParams: [12, 26, 9],
    fields: [
      { label: 'Fast EMA', min: 1, max: 500, step: 1 },
      { label: 'Slow EMA', min: 1, max: 500, step: 1 },
      { label: 'Signal', min: 1, max: 500, step: 1 },
    ],
  },
  RSI: {
    type: 'periods',
    defaultParams: [6, 12, 24],
    presetPeriods: [6, 9, 12, 14, 24, 28],
  },
  KDJ: {
    type: 'fields',
    defaultParams: [9, 3, 3],
    fields: [
      { label: 'K Period', min: 1, max: 500, step: 1 },
      { label: 'D Period', min: 1, max: 500, step: 1 },
      { label: 'J Period', min: 1, max: 500, step: 1 },
    ],
  },
  CCI: {
    type: 'fields',
    defaultParams: [20],
    fields: [
      { label: 'Period', min: 1, max: 500, step: 1 },
    ],
  },
}

function normalizeIndicatorState (indicators) {
  if (!Array.isArray(indicators)) return []
  return indicators.map(item => {
    if (typeof item === 'string') {
      const cfg = INDICATOR_CONFIGS[item]
      return { name: item, calcParams: cfg ? [...cfg.defaultParams] : [] }
    }
    const cfg = INDICATOR_CONFIGS[item.name]
    return {
      name: item.name,
      calcParams: Array.isArray(item.calcParams)
        ? [...item.calcParams]
        : (cfg ? [...cfg.defaultParams] : []),
    }
  }).filter(item => INDICATOR_CONFIGS[item.name])
}

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
    this._ws               = null
    this._ready            = false
    this._queue            = []
    this._candleHandlers   = {}           // topic → Set<fn>
    this._historyHandlers  = {}           // topic → Set<fn> (one-shot per reconnect batch)
    this._historyCache     = {}           // topic → last history payload (shared across panels)
    this._subRefCount      = {}           // topic → refcount for shared subscriptions
    this._reconnectCbs     = []
    this._reconnectTimer   = null
    this._intentionalClose = false
    this._hadConnection    = false
    this._connect()
  }

  _topic (symbol, interval) {
    return `${symbol}:${interval}`
  }

  _parseTopic (topic) {
    const i = topic.indexOf(':')
    return { symbol: topic.slice(0, i), interval: topic.slice(i + 1) }
  }

  _setStatus (s) {
    const el = document.getElementById('ws-status')
    if (el) { el.className = `ws-dot ${s}`; el.title = `WebSocket: ${s}` }
  }

  _resubscribeAll () {
    for (const topic of Object.keys(this._subRefCount)) {
      if (this._subRefCount[topic] > 0) {
        const { symbol, interval } = this._parseTopic(topic)
        this._send({ type: 'subscribe', symbol, interval })
      }
    }
  }

  _connect () {
    this._setStatus('connecting')
    this._ws = new WebSocket(WS_URL)

    this._ws.onopen = () => {
      this._ready = true
      this._setStatus('connected')
      while (this._queue.length) this._ws.send(this._queue.shift())
      if (this._hadConnection) {
        this._historyCache = {}
        this._reconnectCbs.forEach(fn => fn())
        this._resubscribeAll()
      }
      this._hadConnection = true
    }

    this._ws.onmessage = ({ data }) => {
      let msg; try { msg = JSON.parse(data) } catch { return }
      const topic = this._topic(msg.symbol, msg.interval)
      if (msg.type === 'history') {
        this._deliverHistory(topic, msg.data || [])
      } else if (msg.type === 'candle') {
        const handlers = this._candleHandlers[topic]
        if (handlers) handlers.forEach(fn => fn(msg.data))
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

  /** Register callback fired after WS reconnects (not initial connect). */
  onReconnect (fn) {
    this._reconnectCbs.push(fn)
    return () => {
      this._reconnectCbs = this._reconnectCbs.filter(f => f !== fn)
    }
  }

  _deliverHistory (topic, data) {
    this._historyCache[topic] = data
    const handlers = this._historyHandlers[topic]
    if (!handlers) return
    handlers.forEach(fn => fn(data))
    delete this._historyHandlers[topic]
  }

  /** Register a one-shot history callback for symbol:interval */
  onHistory (symbol, interval, fn) {
    const topic = this._topic(symbol, interval)
    if (!this._historyHandlers[topic]) this._historyHandlers[topic] = new Set()
    this._historyHandlers[topic].add(fn)
    if (Object.prototype.hasOwnProperty.call(this._historyCache, topic)) {
      const cached = this._historyCache[topic]
      queueMicrotask(() => {
        if (!this._historyHandlers[topic]?.has(fn)) return
        fn(cached)
        this._historyHandlers[topic].delete(fn)
        if (this._historyHandlers[topic].size === 0) delete this._historyHandlers[topic]
      })
    }
    return () => { this._historyHandlers[topic]?.delete(fn) }
  }

  /** Cancel pending history callback(s) */
  cancelHistory (symbol, interval = null) {
    if (interval) {
      delete this._historyHandlers[this._topic(symbol, interval)]
      return
    }
    const prefix = `${symbol}:`
    for (const key of Object.keys(this._historyHandlers)) {
      if (key.startsWith(prefix)) delete this._historyHandlers[key]
    }
  }

  /** Register live candle callback. Returns unsubscribe fn. Multicast-safe. */
  onCandle (symbol, interval, fn) {
    const topic = this._topic(symbol, interval)
    if (!this._candleHandlers[topic]) this._candleHandlers[topic] = new Set()
    this._candleHandlers[topic].add(fn)
    return () => {
      this._candleHandlers[topic]?.delete(fn)
      if (this._candleHandlers[topic]?.size === 0) delete this._candleHandlers[topic]
    }
  }

  subscribe (symbol, interval) {
    const topic = this._topic(symbol, interval)
    const prev = this._subRefCount[topic] || 0
    this._subRefCount[topic] = prev + 1
    if (prev === 0) {
      this._send({ type: 'subscribe', symbol, interval })
    } else if (this._historyHandlers[topic]?.size > 0) {
      // Topic already active — fetch history for additional panel(s)
      this._send({ type: 'history', symbol, interval })
    }
  }

  unsubscribe (symbol, interval) {
    const topic = this._topic(symbol, interval)
    if (!this._subRefCount[topic]) return
    this._subRefCount[topic] -= 1
    if (this._subRefCount[topic] <= 0) {
      delete this._subRefCount[topic]
      this._send({ type: 'unsubscribe', symbol, interval })
    }
  }

  destroy () {
    this._intentionalClose = true
    clearTimeout(this._reconnectTimer)
    if (this._ws) this._ws.close()
  }
}

// ─── Indicator Settings Modal ─────────────────────────────────────────────────

class IndicatorSettingsModal {
  constructor () {
    this._onApply = null
    this._el = document.createElement('div')
    this._el.className = 'ind-settings-modal'
    this._el.hidden = true
    this._el.innerHTML = `
      <div class="ind-settings-backdrop" data-action="cancel"></div>
      <div class="ind-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="ind-settings-title">
        <div class="ind-settings-header">
          <h3 id="ind-settings-title"></h3>
          <button type="button" class="ind-settings-close" data-action="cancel" aria-label="Close">×</button>
        </div>
        <div class="ind-settings-body"></div>
        <p class="ind-settings-error" hidden></p>
        <div class="ind-settings-footer">
          <button type="button" class="ind-settings-btn" data-action="cancel">Cancel</button>
          <button type="button" class="ind-settings-btn ind-settings-btn-primary" data-action="apply">Apply</button>
        </div>
      </div>
    `
    document.body.appendChild(this._el)

    this._titleEl = this._el.querySelector('#ind-settings-title')
    this._bodyEl = this._el.querySelector('.ind-settings-body')
    this._errorEl = this._el.querySelector('.ind-settings-error')

    this._el.addEventListener('click', e => {
      const action = e.target.closest('[data-action]')?.dataset.action
      if (action === 'cancel') this.close()
      if (action === 'apply') this._apply()
    })

    document.addEventListener('keydown', e => {
      if (!this._el.hidden && e.key === 'Escape') this.close()
    })
  }

  open ({ name, calcParams, onApply }) {
    const cfg = INDICATOR_CONFIGS[name]
    if (!cfg) return

    const label = INDICATORS.find(i => i.key === name)?.label ?? name
    this._name = name
    this._cfg = cfg
    this._onApply = onApply
    this._titleEl.textContent = `${label} Settings`
    this._errorEl.hidden = true
    this._errorEl.textContent = ''
    this._renderBody(calcParams)
    this._el.hidden = false
  }

  close () {
    this._el.hidden = true
    this._onApply = null
  }

  _renderBody (calcParams) {
    const cfg = this._cfg
    const active = new Set(Array.isArray(calcParams) ? calcParams : [])

    if (cfg.type === 'periods') {
      const presets = cfg.presetPeriods || cfg.defaultParams
      this._bodyEl.innerHTML = `
        <p class="ind-settings-hint">Select the periods you want — only checked values will be drawn.</p>
        <div class="ind-settings-presets">
          ${presets.map(p => `
            <label class="ind-settings-check">
              <input type="checkbox" value="${p}"${active.has(p) ? ' checked' : ''} />
              <span>${p}</span>
            </label>
          `).join('')}
        </div>
        <label class="ind-settings-field">
          <span>Custom periods (comma-separated)</span>
          <input type="text" class="ind-settings-custom" placeholder="e.g. 9, 21, 55" />
        </label>
      `
      return
    }

    this._bodyEl.innerHTML = `
      <p class="ind-settings-hint">Adjust the parameters, then click Apply.</p>
      <div class="ind-settings-fields">
        ${cfg.fields.map((field, i) => `
          <label class="ind-settings-field">
            <span>${field.label}</span>
            <input
              type="number"
              data-field="${i}"
              min="${field.min}"
              max="${field.max}"
              step="${field.step}"
              value="${(calcParams ?? cfg.defaultParams)[i] ?? cfg.defaultParams[i]}"
            />
          </label>
        `).join('')}
      </div>
    `
  }

  _parsePeriods () {
    const cfg = this._cfg
    const periods = new Set()

    this._bodyEl.querySelectorAll('.ind-settings-presets input:checked').forEach(input => {
      periods.add(Number(input.value))
    })

    const custom = this._bodyEl.querySelector('.ind-settings-custom')?.value ?? ''
    custom.split(/[,;\s]+/).forEach(part => {
      const n = Number(part.trim())
      if (Number.isFinite(n) && n > 0) periods.add(Math.round(n))
    })

    return [...periods].sort((a, b) => a - b)
  }

  _parseFields () {
    const cfg = this._cfg
    const values = []
    for (let i = 0; i < cfg.fields.length; i++) {
      const input = this._bodyEl.querySelector(`input[data-field="${i}"]`)
      const field = cfg.fields[i]
      const n = Number(input?.value)
      if (!Number.isFinite(n) || n < field.min || n > field.max) {
        return { error: `${field.label} must be between ${field.min} and ${field.max}.` }
      }
      values.push(field.step >= 1 ? Math.round(n) : n)
    }
    return { values }
  }

  _apply () {
    const cfg = this._cfg
    let calcParams

    if (cfg.type === 'periods') {
      calcParams = this._parsePeriods()
      if (calcParams.length === 0) {
        this._errorEl.textContent = 'Select at least one period.'
        this._errorEl.hidden = false
        return
      }
    } else {
      const parsed = this._parseFields()
      if (parsed.error) {
        this._errorEl.textContent = parsed.error
        this._errorEl.hidden = false
        return
      }
      calcParams = parsed.values
    }

    this._onApply?.(calcParams)
    this.close()
  }
}

let _indicatorModal = null
function getIndicatorModal () {
  if (!_indicatorModal) _indicatorModal = new IndicatorSettingsModal()
  return _indicatorModal
}

// ─── Chart Panel ──────────────────────────────────────────────────────────────

class ChartPanel {
  constructor (panelEl, wsManager, symbols, timezone, symbol = 'BTCUSDT', interval = '1m', indicators = []) {
    this._el               = panelEl
    this._ws               = wsManager
    this._symbols          = symbols
    this._timezone         = timezone
    this._symbol           = symbols.includes(symbol) ? symbol : symbols[0]
    this._interval         = interval
    this._chart            = null
    this._unsubFn          = null
    this._activeIndicators = normalizeIndicatorState(indicators)
    this._closeDropdowns   = null
    this._loadGen          = 0

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
      <div class="chart-viewport">
        <div class="chart-canvas"></div>
        <div class="chart-loading" hidden aria-live="polite">
          <div class="chart-loading-inner">
            <span class="chart-loading-spinner"></span>
            <span class="chart-loading-text">Loading…</span>
          </div>
        </div>
      </div>
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

    // Indicator — open settings when adding, click again to remove
    this._el.querySelectorAll('[data-ind]').forEach(btn =>
      btn.addEventListener('click', e => { e.stopPropagation(); this._onIndicatorClick(btn.dataset.ind) })
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

  _setLoading (show) {
    const el = this._el.querySelector('.chart-loading')
    if (el) el.hidden = !show
  }

  _clearDrawings () {
    if (this._chart) this._chart.removeOverlay()
  }

  /** Bump generation, cancel stale history, show loading overlay */
  _prepareDataTransition () {
    this._loadGen += 1
    this._ws.cancelHistory(this._symbol, this._interval)
    this._setLoading(true)
    this._clearDrawings()
    return this._loadGen
  }

  _createIndicatorOnChart ({ name, calcParams }) {
    const payload = { name, calcParams }
    if (OVERLAY_INDICATORS.has(name)) {
      return this._chart.createIndicator(payload, { isStack: true, pane: { id: 'candle_pane' } })
    }
    return this._chart.createIndicator(payload)
  }

  _isIndicatorActive (name) {
    return this._activeIndicators.some(ind => ind.name === name)
  }

  _findIndicator (name) {
    return this._activeIndicators.find(ind => ind.name === name)
  }

  _teardownChartSubscription () {
    this._ws.unsubscribe(this._symbol, this._interval)
    if (this._unsubFn) { this._unsubFn(); this._unsubFn = null }
  }

  _rebuildActiveIndicators () {
    if (!this._chart || this._activeIndicators.length === 0) return
    for (const ind of [...this._activeIndicators]) {
      this._chart.removeIndicator({ name: ind.name, id: ind.id })
    }
    const ordered = [...this._activeIndicators].sort((a, b) => {
      const ao = OVERLAY_INDICATORS.has(a.name)
      const bo = OVERLAY_INDICATORS.has(b.name)
      if (ao === bo) return 0
      return ao ? -1 : 1
    })
    this._activeIndicators = ordered.map(ind => {
      const id = this._createIndicatorOnChart(ind)
      return { ...ind, id }
    })
    this._syncIndicatorButtons()
  }

  _syncIndicatorButtons () {
    this._el.querySelectorAll('[data-ind]').forEach(btn =>
      btn.classList.toggle('active', this._isIndicatorActive(btn.dataset.ind))
    )
  }

  _applyActiveIndicators () {
    queueMicrotask(() => this._rebuildActiveIndicators())
  }

  _onIndicatorClick (name) {
    if (!this._chart) return
    this._el.querySelectorAll('.tool-dropdown.open').forEach(d => d.classList.remove('open'))

    if (this._isIndicatorActive(name)) {
      this._removeIndicator(name)
      return
    }

    const existing = this._findIndicator(name)
    getIndicatorModal().open({
      name,
      calcParams: existing?.calcParams ?? null,
      onApply: calcParams => this._applyIndicator(name, calcParams),
    })
  }

  _applyIndicator (name, calcParams) {
    const existing = this._findIndicator(name)
    if (existing) {
      this._chart.removeIndicator({ name: existing.name, id: existing.id })
      this._activeIndicators = this._activeIndicators.filter(ind => ind.name !== name)
    }

    const id = this._createIndicatorOnChart({ name, calcParams })
    this._activeIndicators.push({ name, calcParams, id })
    this._syncIndicatorButtons()
  }

  _removeIndicator (name) {
    const ind = this._findIndicator(name)
    if (!ind) return
    this._chart.removeIndicator({ name: ind.name, id: ind.id })
    this._activeIndicators = this._activeIndicators.filter(i => i.name !== name)
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
      timezone: this._timezone,
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

    this._prepareDataTransition()
    this._chart.setDataLoader({
      getBars: ({ type, period, symbol, callback }) => {
        if (type !== 'init') {
          // forward/backward paging — we don't support infinite scroll yet
          callback([], { forward: true, backward: true })
          return
        }
        const intervalKey = periodToKey(period)
        const ticker = symbol.ticker
        const loadGen = self._loadGen
        self._setLoading(true)

        self._ws.onHistory(ticker, intervalKey, (candles) => {
          if (loadGen !== self._loadGen) {
            self._setLoading(false)
            return
          }
          self._setLoading(false)
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
    const savedIndicators = this._activeIndicators.map(({ name, calcParams }) => ({ name, calcParams: [...calcParams] }))

    if (this._chart) {
      this._ws.unsubscribe(this._symbol, this._interval)
      if (this._unsubFn) { this._unsubFn(); this._unsubFn = null }
      this._ws.cancelHistory(this._symbol, this._interval)
      dispose(this._chart)
      this._chart = null
    }

    this._symbol = symbol

    const select = this._el.querySelector('.symbol-select')
    if (select) select.value = symbol

    this._activeIndicators = normalizeIndicatorState(savedIndicators)
    this._syncIndicatorButtons()
    this._mountChart()
  }

  _changeInterval (intervalKey) {
    if (intervalKey === this._interval) return
    this._interval = intervalKey
    this._updatePeriodButtons()
    this._prepareDataTransition()

    const periodCfg = PERIODS.find(p => p.key === intervalKey)
    if (periodCfg && this._chart) {
      // setPeriod triggers unsubscribeBar → getBars(init) → subscribeBar automatically
      this._chart.setPeriod(periodCfg.period)
    }
  }

  /** Reload history + live subscription after WebSocket reconnect */
  reconnect () {
    if (!this._chart) return
    this._prepareDataTransition()
    this._chart.resetData()
  }

  // ── Workspace ────────────────────────────────────────────────────────────────

  getState () {
    return {
      symbol:     this._symbol,
      interval:   this._interval,
      indicators: this._activeIndicators.map(({ name, calcParams }) => ({ name, calcParams: [...calcParams] })),
    }
  }

  destroy () {
    this._teardownChartSubscription()
    this._ws.cancelHistory(this._symbol, this._interval)
    this._setLoading(false)
    if (this._chart) { dispose(this._chart); this._chart = null }
    if (this._closeDropdowns) { document.removeEventListener('click', this._closeDropdowns); this._closeDropdowns = null }
  }
}

// ─── App ──────────────────────────────────────────────────────────────────────

class App {
  constructor (symbols, timezone) {
    this._symbols   = symbols
    this._timezone  = timezone
    this._layout = '1x1'
    this._panels = []
    this._ws     = new WSManager()
    this._grid   = document.getElementById('chart-grid')

    this._ws.onReconnect(() => {
      this._panels.forEach(p => p.reconnect())
    })

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
      this._panels.push(new ChartPanel(panelEl, this._ws, this._symbols, this._timezone, symbol, st.interval, st.indicators))
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

Promise.all([
  fetchSymbols().catch(() => FALLBACK_SYMBOLS),
  fetchConfig(),
]).then(([symbols, config]) => {
  const timezone = config.candleTimezone || browserTimezone()
  app = new App(symbols, timezone)
  window.addEventListener('beforeunload', () => {
    app._panels.forEach(p => p.destroy())
    app._ws.destroy()
  })
})
