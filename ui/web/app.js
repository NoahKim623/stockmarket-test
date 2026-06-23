'use strict';

// ---------------------------------------------------------------------------
// Frontend controller. Talks to the Python backend over pywebview's bridge
// (window.pywebview.api.*) and renders into three synced TradingView charts
// (price + volume + overlays, RSI, MACD) plus a summary + backtest sidebar.
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);
const LWC = () => window.LightweightCharts;

const state = {
  ticker: 'AAPL',
  timeframe: '6M',
  overlays: { sma: false, ema: false, bb: false, volume: true },
  cfg: null,
  loading: false,
  lastCandles: null,
};

// Chart handles
let priceChart, rsiChart, macdChart;
let candleSeries, volumeSeries, smaSeries, emaSeries, bbUpper, bbMiddle, bbLower;
let rsiSeries, macdSeries, signalSeries, histSeries;
let booted = false;

// ---- formatting helpers ---------------------------------------------------
const fmtMoney = (v) => (v == null ? '—' : '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const fmtPct = (v, sign) => (v == null ? '—' : (sign && v > 0 ? '+' : '') + Number(v).toFixed(2) + '%');
const fmtNum2 = (v) => (v == null ? '—' : Number(v).toFixed(2));
function fmtVol(v) {
  if (v == null || isNaN(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (a >= 1e6) return (v / 1e6).toFixed(2) + 'M';
  if (a >= 1e3) return (v / 1e3).toFixed(1) + 'K';
  return String(Math.round(v));
}

// ---- charts ---------------------------------------------------------------
function baseOptions(extra) {
  return Object.assign({
    autoSize: true,
    layout: { background: { color: '#0e1116' }, textColor: '#c7d0dc', fontSize: 11 },
    grid: { vertLines: { color: '#161c27' }, horzLines: { color: '#161c27' } },
    rightPriceScale: { borderColor: '#2a3242', minimumWidth: 64 },
    crosshair: { mode: LWC().CrosshairMode.Normal },
  }, extra || {});
}

function initCharts() {
  // Price (with the visible time axis hidden — the MACD panel at the bottom owns it)
  priceChart = LWC().createChart($('chart-price'), baseOptions({
    timeScale: { visible: false, borderColor: '#2a3242', rightOffset: 4 },
  }));
  candleSeries = priceChart.addCandlestickSeries({
    upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
    wickUpColor: '#26a69a', wickDownColor: '#ef5350',
  });
  volumeSeries = priceChart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: '' });
  volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  smaSeries = priceChart.addLineSeries({ color: '#f5a524', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, visible: false });
  emaSeries = priceChart.addLineSeries({ color: '#22d3ee', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, visible: false });
  bbUpper = priceChart.addLineSeries({ color: 'rgba(139,148,255,.7)', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, visible: false });
  bbMiddle = priceChart.addLineSeries({ color: 'rgba(139,148,255,.45)', lineWidth: 1, lineStyle: LWC().LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, visible: false });
  bbLower = priceChart.addLineSeries({ color: 'rgba(139,148,255,.7)', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, visible: false });

  // RSI
  rsiChart = LWC().createChart($('chart-rsi'), baseOptions({
    timeScale: { visible: false, borderColor: '#2a3242' },
  }));
  rsiSeries = rsiChart.addLineSeries({ color: '#c084fc', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true });
  rsiSeries.createPriceLine({ price: 70, color: 'rgba(239,83,80,.5)', lineWidth: 1, lineStyle: LWC().LineStyle.Dashed, axisLabelVisible: true, title: '70' });
  rsiSeries.createPriceLine({ price: 30, color: 'rgba(38,166,154,.5)', lineWidth: 1, lineStyle: LWC().LineStyle.Dashed, axisLabelVisible: true, title: '30' });

  // MACD (bottom panel — shows the shared time axis)
  macdChart = LWC().createChart($('chart-macd'), baseOptions({
    timeScale: { visible: true, borderColor: '#2a3242', timeVisible: true, secondsVisible: false, rightOffset: 4 },
  }));
  histSeries = macdChart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
  macdSeries = macdChart.addLineSeries({ color: '#3b82f6', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });
  signalSeries = macdChart.addLineSeries({ color: '#f5a524', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });
  macdSeries.createPriceLine({ price: 0, color: 'rgba(133,147,166,.4)', lineWidth: 1, lineStyle: LWC().LineStyle.Dotted });

  linkTimeScales([priceChart, rsiChart, macdChart]);
  wirePriceLegend();
}

// Keep the three panels horizontally aligned by mirroring the visible range.
function linkTimeScales(charts) {
  let syncing = false;
  charts.forEach((src) => {
    src.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (syncing || !range) return;
      syncing = true;
      charts.forEach((tgt) => { if (tgt !== src) tgt.timeScale().setVisibleLogicalRange(range); });
      syncing = false;
    });
  });
}

function wirePriceLegend() {
  priceChart.subscribeCrosshairMove((param) => {
    const c = param && param.seriesData ? param.seriesData.get(candleSeries) : null;
    updateLegend(c || (state.lastCandles ? state.lastCandles[state.lastCandles.length - 1] : null));
  });
}

function updateLegend(c) {
  const el = $('price-legend');
  if (!c) { el.textContent = state.ticker; return; }
  const cls = c.close >= c.open ? 'up' : 'down';
  el.innerHTML = `<b>${state.ticker}</b> &nbsp;`
    + `<span class="k">O</span> ${c.open.toFixed(2)} `
    + `<span class="k">H</span> ${c.high.toFixed(2)} `
    + `<span class="k">L</span> ${c.low.toFixed(2)} `
    + `<span class="k">C</span> <span class="${cls}">${c.close.toFixed(2)}</span>`;
}

// ---- generic UI helpers ---------------------------------------------------
function showToast(msg, isError = true) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.toggle('error', isError);
  t.classList.remove('hidden');
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => t.classList.add('hidden'), 6000);
}

function setLoading(on, text) {
  state.loading = on;
  if (text) $('overlay-text').textContent = text;
  $('chart-overlay').classList.toggle('hidden', !on);
  $('load-btn').disabled = on;
  $('refresh-btn').disabled = on;
}

function renderTimeframes() {
  const wrap = $('timeframes');
  wrap.innerHTML = '';
  state.cfg.timeframes.forEach((tf) => {
    const b = document.createElement('button');
    b.className = 'seg' + (tf.key === state.timeframe ? ' active' : '');
    b.textContent = tf.key;
    b.title = tf.label;
    b.onclick = () => {
      if (state.loading || tf.key === state.timeframe) return;
      state.timeframe = tf.key;
      renderTimeframes();
      loadDashboard(false);
    };
    wrap.appendChild(b);
  });
}

function renderStatus(meta) {
  $('status-symbol').textContent = meta.ticker + ' · ' + meta.timeframe;
  $('status-asof').textContent = 'as of ' + meta.fetched_at_human + ' · ' + meta.bars + ' bars';
  $('status-source').textContent = meta.source === 'network' ? '· live' : '· cached';
  $('status-stale').classList.toggle('hidden', !meta.is_stale);
}

// ---- summary --------------------------------------------------------------
function renderSummary(s) {
  const grid = $('summary-grid');
  if (!s) { grid.innerHTML = '<div class="summary-empty">Summary unavailable for this symbol.</div>'; return; }
  const chgCls = s.daily_change_abs >= 0 ? 'pos' : 'neg';
  const chg = `${s.daily_change_abs >= 0 ? '+' : ''}${fmtNum2(s.daily_change_abs)} (${fmtPct(s.daily_change_pct, true)})`;
  const cells = [
    ['Price', fmtMoney(s.current_price), ''],
    ['Day change', chg, chgCls],
    ['52-wk high', fmtMoney(s.high_52w), ''],
    ['52-wk low', fmtMoney(s.low_52w), ''],
    ['Hist. vol (ann.)', fmtPct(s.hist_vol_annual_pct), ''],
    ['Avg vol (30d)', fmtVol(s.avg_volume_30d), ''],
  ];
  grid.innerHTML = cells.map(([label, value, cls]) =>
    `<div class="stat"><div class="label">${label}</div><div class="value ${cls}">${value}</div></div>`).join('');
}

// ---- main data load -------------------------------------------------------
async function loadDashboard(force) {
  if (!window.pywebview || !window.pywebview.api) { showToast('Bridge not ready yet.'); return; }
  setLoading(true, force ? 'Refreshing ' + state.ticker + '…' : 'Loading ' + state.ticker + '…');
  try {
    const res = await window.pywebview.api.get_dashboard(state.ticker, state.timeframe, !!force);
    if (!res || !res.ok) { showToast((res && res.error) || 'Failed to load data.'); return; }

    state.lastCandles = res.candles;
    candleSeries.setData(res.candles);
    volumeSeries.setData(res.volume);
    const ix = res.indicators;
    smaSeries.setData(ix.sma);
    emaSeries.setData(ix.ema);
    bbUpper.setData(ix.bb_upper);
    bbMiddle.setData(ix.bb_middle);
    bbLower.setData(ix.bb_lower);
    rsiSeries.setData(ix.rsi);
    macdSeries.setData(ix.macd);
    signalSeries.setData(ix.macd_signal);
    histSeries.setData(ix.macd_hist);

    applyOverlayVisibility();
    priceChart.timeScale().fitContent();
    updateLegend(res.candles[res.candles.length - 1]);
    renderStatus(res.meta);
    renderSummary(res.summary);
  } catch (e) {
    showToast('Error: ' + (e && e.message ? e.message : e));
  } finally {
    setLoading(false);
  }
}

function applyOverlayVisibility() {
  smaSeries.applyOptions({ visible: state.overlays.sma });
  emaSeries.applyOptions({ visible: state.overlays.ema });
  const bbOn = state.overlays.bb;
  bbUpper.applyOptions({ visible: bbOn });
  bbMiddle.applyOptions({ visible: bbOn });
  bbLower.applyOptions({ visible: bbOn });
  volumeSeries.applyOptions({ visible: state.overlays.volume });
}

async function onLoadClicked() {
  const t = $('ticker').value.trim().toUpperCase();
  if (!t) { showToast('Enter a ticker symbol.'); return; }
  state.ticker = t;
  setLoading(true, 'Checking ' + t + '…');
  try {
    const v = await window.pywebview.api.validate_ticker(t);
    if (!v.ok || !v.valid) {
      setLoading(false);
      showToast(v.error || ("'" + t + "' doesn't look like a valid symbol."));
      return;
    }
  } catch (e) { /* if validation itself errors, still try to load */ }
  await loadDashboard(false);
}

// ---- backtest -------------------------------------------------------------
function currentStrategy() {
  return state.cfg.strategies.find((s) => s.key === $('bt-strategy').value) || state.cfg.strategies[0];
}

function renderStrategyForm() {
  const sel = $('bt-strategy');
  sel.innerHTML = '';
  state.cfg.strategies.forEach((s) => {
    const o = document.createElement('option');
    o.value = s.key; o.textContent = s.label;
    sel.appendChild(o);
  });
  sel.onchange = renderParams;
  const d = state.cfg.backtest_defaults;
  $('bt-cash').value = d.cash;
  $('bt-commission').value = d.commission_pct;
  $('bt-slippage').value = d.slippage_pct;
  renderParams();
}

function renderParams() {
  const s = currentStrategy();
  $('bt-desc').textContent = s.description;
  const box = $('bt-params');
  box.innerHTML = '';
  s.params.forEach((p) => {
    const wrap = document.createElement('label');
    wrap.className = 'bt-field';
    const span = document.createElement('span');
    span.textContent = p.label;
    wrap.appendChild(span);
    let input;
    if (p.type === 'choice') {
      input = document.createElement('select');
      p.choices.forEach((c) => { const o = document.createElement('option'); o.value = c; o.textContent = c; input.appendChild(o); });
      input.value = p.default;
    } else {
      input = document.createElement('input');
      input.type = 'number';
      input.value = p.default;
      if (p.min != null) input.min = p.min;
      if (p.max != null) input.max = p.max;
    }
    input.className = 'bt-input';
    input.dataset.key = p.key;
    input.dataset.type = p.type;
    wrap.appendChild(input);
    box.appendChild(wrap);
  });
}

function collectParams() {
  const out = {};
  $('bt-params').querySelectorAll('[data-key]').forEach((i) => {
    out[i.dataset.key] = i.dataset.type === 'int' ? Number(i.value) : i.value;
  });
  return out;
}

function setBtBusy(on) {
  const b = $('bt-run');
  b.disabled = on;
  b.textContent = on ? 'Running…' : 'Run backtest';
}

async function runBacktest() {
  if (!window.pywebview || !window.pywebview.api) { showToast('Bridge not ready yet.'); return; }
  setBtBusy(true);
  $('bt-results').innerHTML = '';
  try {
    const res = await window.pywebview.api.run_backtest(
      state.ticker, state.timeframe, $('bt-strategy').value, collectParams(),
      Number($('bt-cash').value), Number($('bt-commission').value), Number($('bt-slippage').value));
    if (!res || !res.ok) { $('bt-results').innerHTML = `<div class="bt-error">${(res && res.error) || 'Backtest failed.'}</div>`; return; }
    renderBtResults(res);
  } catch (e) {
    $('bt-results').innerHTML = `<div class="bt-error">Error: ${e}</div>`;
  } finally {
    setBtBusy(false);
  }
}

function renderBtResults(r) {
  const S = r.strategy, B = r.baseline;
  const pctCell = (v) => `<td class="${v == null ? '' : (v >= 0 ? 'pos' : 'neg')}">${fmtPct(v, true)}</td>`;
  const rows = [
    ['Total return', pctCell(S.return_pct), pctCell(B.return_pct)],
    ['Max drawdown', pctCell(S.max_drawdown_pct), pctCell(B.max_drawdown_pct)],
    ['Sharpe ratio', `<td>${fmtNum2(S.sharpe)}</td>`, `<td>${fmtNum2(B.sharpe)}</td>`],
    ['Win rate', `<td>${fmtPct(S.win_rate_pct)}</td>`, `<td>${fmtPct(B.win_rate_pct)}</td>`],
    ['# Trades', `<td>${S.num_trades}</td>`, `<td>${B.num_trades}</td>`],
    ['Final equity', `<td>${fmtMoney(S.equity_final)}</td>`, `<td>${fmtMoney(B.equity_final)}</td>`],
  ];
  const meta = `${r.strategy_label} · ${r.ticker} ${r.timeframe} · ${r.bars} bars`
    + ` · costs: ${r.commission_pct}% commission, ${r.slippage_pct}% slippage`;
  const note = r.note ? `<div class="bt-note">⚠ ${r.note}</div>` : '';
  $('bt-results').innerHTML = `
    <div class="bt-meta">${meta}</div>
    <table class="bt-table">
      <thead><tr><th>Metric</th><th>Strategy</th><th>Buy &amp; Hold</th></tr></thead>
      <tbody>${rows.map((row) => `<tr><td>${row[0]}</td>${row[1]}${row[2]}</tr>`).join('')}</tbody>
    </table>${note}`;
}

// ---- wiring / boot --------------------------------------------------------
function wireControls() {
  $('load-btn').onclick = onLoadClicked;
  $('ticker').addEventListener('keydown', (e) => { if (e.key === 'Enter') onLoadClicked(); });
  $('refresh-btn').onclick = () => loadDashboard(true);
  const tg = (id, key) => $(id).addEventListener('change', (e) => { state.overlays[key] = e.target.checked; applyOverlayVisibility(); });
  tg('toggle-sma', 'sma'); tg('toggle-ema', 'ema'); tg('toggle-bb', 'bb'); tg('toggle-volume', 'volume');
  $('bt-run').onclick = runBacktest;
}

async function boot() {
  if (booted) return;
  booted = true;
  try {
    const cfg = await window.pywebview.api.get_config();
    state.cfg = cfg;
    state.ticker = cfg.default_ticker;
    state.timeframe = cfg.default_timeframe;
    $('ticker').value = cfg.default_ticker;
    $('disclaimer-short').textContent = cfg.disclaimer_short;
    $('disclaimer-long').textContent = cfg.disclaimer_long;
    $('bt-disclaimer').textContent = cfg.backtest_disclaimer;
    // Indicator toggle labels + panel titles reflect the configured lengths.
    $('tl-sma').textContent = cfg.indicators.sma_label;
    $('tl-ema').textContent = cfg.indicators.ema_label;
    $('tl-bb').textContent = cfg.indicators.bb_label;
    $('label-rsi').textContent = cfg.indicators.rsi_label;
    $('label-macd').textContent = cfg.indicators.macd_label;
    renderTimeframes();
    renderStrategyForm();
    await loadDashboard(false);
  } catch (e) {
    showToast('Failed to initialize: ' + e);
  }
}

window.addEventListener('DOMContentLoaded', () => {
  initCharts();
  wireControls();
  if (window.pywebview && window.pywebview.api) boot();
});
window.addEventListener('pywebviewready', boot);
