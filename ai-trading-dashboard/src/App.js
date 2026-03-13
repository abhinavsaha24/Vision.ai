import React, { useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";
import "./App.css";

import Chart from "./Chart";
import RSI from "./RSI";
import OrderBook from "./OrderBook";
import Footer from "./Footer";
import { fetchNews } from "./news";

/* ============================================ */
/*  API BASE                                     */
/* ============================================ */

const API = (process.env.REACT_APP_API || "https://vision-ai-5qm1.onrender.com").replace(/\/$/, "");

/* ============================================ */
/*  HELPER: API calls                            */
/* ============================================ */

const apiPost = async (path, data = {}, timeout = 12000) => {
  try {
    const res = await axios.post(`${API}${path}`, data, { timeout });
    return res.data;
  } catch (err) {
    console.error(`API POST ${path} error:`, err.response?.data || err.message);
    return null;
  }
};

const apiGet = async (path, timeout = 12000) => {
  try {
    const res = await axios.get(`${API}${path}`, { timeout });
    return res.data;
  } catch (err) {
    console.error(`API GET ${path} error:`, err.response?.data || err.message);
    return null;
  }
};

/* ============================================ */
/*  Mini Components                              */
/* ============================================ */

function SignalBadge({ signal }) {
  const cls = signal === "BUY" ? "signal-buy" : signal === "SELL" ? "signal-sell" : "signal-hold";
  const icon = signal === "BUY" ? "▲" : signal === "SELL" ? "▼" : "●";
  return <span className={`signal-badge ${cls}`}>{icon} {signal}</span>;
}

function MetricBox({ label, value, color = "" }) {
  return (
    <div className="metric">
      <div className={`metric-value ${color}`}>{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  );
}

function Tag({ text, color = "blue" }) {
  return <span className={`tag tag-${color}`}>{text}</span>;
}

function ProgressBar({ value, max = 1, color = "blue" }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div className="progress-bar">
      <div className={`progress-fill progress-${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function PriceChange({ current, previous }) {
  if (!current || !previous || previous === 0) return null;
  const change = current - previous;
  const pct = (change / previous) * 100;
  const isUp = change >= 0;
  return (
    <span className={isUp ? "text-green" : "text-red"} style={{ fontSize: "0.85rem", fontWeight: 600 }}>
      {isUp ? "▲" : "▼"} {Math.abs(change).toFixed(2)} ({isUp ? "+" : ""}{pct.toFixed(2)}%)
    </span>
  );
}

/* ============================================ */
/*  MAIN APP                                     */
/* ============================================ */

function App() {

  /* ---- States ---- */
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [time, setTime] = useState(new Date());
  const [price, setPrice] = useState(null);
  const [prevPrice, setPrevPrice] = useState(null);
  const [priceFlash, setPriceFlash] = useState("");
  const [news, setNews] = useState([]);
  const [orderHistory, setOrderHistory] = useState([]);
  const [orderStats, setOrderStats] = useState(null);

  // AI Prediction data
  const [predictions, setPredictions] = useState([]);
  const [signal, setSignal] = useState("HOLD");
  const [confidence, setConfidence] = useState(null);
  const [risk, setRisk] = useState(null);
  const [signalScore, setSignalScore] = useState(null);
  const [components, setComponents] = useState({});
  const [positionSize, setPositionSize] = useState(null);
  const [regime, setRegime] = useState({});
  const [strategy, setStrategy] = useState(null);
  const [sentiment, setSentiment] = useState({});

  // Risk dashboard
  const [riskDashboard, setRiskDashboard] = useState(null);

  // Portfolio
  const [performance, setPerformance] = useState(null);

  // Paper trading
  const [paperStatus, setPaperStatus] = useState(null);

  // Strategies
  const [strategies, setStrategies] = useState([]);

  // Loading
  const [loading, setLoading] = useState(false);
  const [apiStatus, setApiStatus] = useState(false);

  /* ---- Clock ---- */
  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  /* ---- Price from Binance ---- */
  const getPrice = useCallback(async () => {
    try {
      const res = await axios.get("https://api.binance.com/api/v3/ticker/price", {
        params: { symbol }
      });
      const newPrice = parseFloat(res.data.price);
      setPrice(prev => {
        if (prev !== null) {
          setPrevPrice(prev);
          if (newPrice > prev) {
            setPriceFlash("flash-green");
            setTimeout(() => setPriceFlash(""), 800);
          } else if (newPrice < prev) {
            setPriceFlash("flash-red");
            setTimeout(() => setPriceFlash(""), 800);
          }
        }
        return newPrice;
      });
    } catch (err) {
      console.error("Price error:", err.message);
    }
  }, [symbol]);

  useEffect(() => {
    getPrice();
    const iv = setInterval(getPrice, 10000);
    return () => clearInterval(iv);
  }, [getPrice]);

  /* ---- Health Check (retries for Render cold-start) ---- */
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      const res = await apiGet("/health", 15000);
      if (cancelled) return;
      if (res?.status === "healthy" || res?.status === "ok") {
        setApiStatus(true);
      } else {
        setApiStatus(false);
        setTimeout(check, 5000); // retry in 5s (Render wake-up)
      }
    };
    check();
    return () => { cancelled = true; };
  }, []);

  /* ---- AI Predictions ---- */
  const getPredictions = useCallback(async () => {
    setLoading(true);
    const data = await apiPost("/model/predict", { symbol, horizon: 5 });
    setLoading(false);
    
    if (!data) return;

    setPredictions(data.predictions || []);
    setSignal(data.signal || "HOLD");
    setConfidence(data.confidence ?? null);
    setRisk(data.risk || null);
    setSignalScore(data.signal_score ?? null);
    setComponents(data.components || {});
    setRegime(data.regime || {});
    setStrategy(data.strategy || null);
    setPositionSize(data.position_size ?? null);
    setSentiment(data.sentiment || {});
  }, [symbol]);

  useEffect(() => {
    getPredictions();
    const iv = setInterval(getPredictions, 30000);
    return () => clearInterval(iv);
  }, [getPredictions]);

  /* ---- Side Data (parallel, non-blocking) ---- */
  useEffect(() => {
    const load = async () => {
      const sym = symbol.replace("USDT", "/USDT");

      // Fire all requests in parallel — don't let one slow call block others
      const [rdRes, perfRes, psRes, stRes, newsRes, ordersRes] = await Promise.allSettled([
        apiGet(`/risk/status?symbol=${sym}`),
        apiGet("/portfolio/performance"),
        apiGet("/paper-trading/status"),
        apiGet("/strategies/list"),
        fetchNews().catch(() => []),
        apiGet("/orders/history?limit=20"),
      ]);

      const val = (r) => r.status === "fulfilled" ? r.value : null;

      const rd = val(rdRes);
      if (rd) setRiskDashboard(rd);

      const perf = val(perfRes);
      if (perf) setPerformance(perf);

      const ps = val(psRes);
      if (ps) setPaperStatus(ps);

      const st = val(stRes);
      if (st) setStrategies(st.strategies || []);

      const items = val(newsRes);
      setNews(items || []);

      const orders = val(ordersRes);
      if (orders) {
        setOrderHistory(orders.orders || []);
        setOrderStats(orders.statistics || null);
      }
    };

    load();
    const iv = setInterval(load, 60000);
    return () => clearInterval(iv);
  }, [symbol]);

  /* ---- Helpers ---- */
  const signalText = (v) => {
    if (v === 1) return "Bullish";
    if (v === -1) return "Bearish";
    return "Neutral";
  };
  const signalColor = (v) => {
    if (v === 1) return "text-green";
    if (v === -1) return "text-red";
    return "text-dim";
  };

  const fmtPct = (v) => v != null ? `${(v * 100).toFixed(1)}%` : "--";
  const fmtNum = (v, d = 2) => v != null ? v.toFixed(d) : "--";

  /* ============================================ */
  /*  RENDER                                       */
  /* ============================================ */

  return (
    <div className="app-container">

      {/* ======== HEADER ======== */}
      <div className="header">
        <div className="row">
          <span className="logo"><span className="logo-bold">VISION</span> <span className="logo-light">AI</span></span>
          <span className="logo-sub">Quant Trading Platform</span>
        </div>
        <div className="header-right">
          <div className="btn-group">
            {["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"].map(s => (
              <button
                key={s}
                className={`btn ${symbol === s ? "btn-active" : ""}`}
                onClick={() => setSymbol(s)}
              >
                {s.replace("USDT", "")}
              </button>
            ))}
          </div>
          <div className="clock">{time.toLocaleTimeString()}</div>
          <div className={`status-dot`} style={{ background: apiStatus ? "var(--accent-green)" : "var(--accent-red)" }} />
        </div>
      </div>

      {/* ======== LEFT PANEL ======== */}
      <div className="left-panel">

        {/* Price */}
        <div className={`card card-glow-blue ${priceFlash}`}>
          <div className="card-title">Live Price</div>
          <div className="metric-value text-cyan" style={{ fontSize: "2rem", transition: "color 0.3s ease" }}>
            ${price ? price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "--"}
          </div>
          <div style={{ marginTop: 4 }}>
            <PriceChange current={price} previous={prevPrice} />
          </div>
          <div className="metric-label">{symbol.replace("USDT", " / USDT")}</div>
        </div>

        {/* Signal */}
        <div className={`card ${signal === "BUY" ? "card-glow-green" : signal === "SELL" ? "card-glow-red" : ""}`}>
          <div className="card-title">AI Signal</div>
          <div style={{ textAlign: "center", padding: "8px 0" }}>
            <SignalBadge signal={signal} />
          </div>
          <div className="metric-grid" style={{ marginTop: 12 }}>
            <MetricBox label="Confidence" value={fmtPct(confidence)} color="text-blue" />
            <MetricBox label="Score" value={fmtNum(signalScore, 3)} color="text-purple" />
          </div>
          <div style={{ marginTop: 8, textAlign: "center" }}>
            <span className="metric-label">Position Size: </span>
            <span className="text-cyan" style={{ fontFamily: "'JetBrains Mono'" }}>{fmtNum(positionSize, 3)}</span>
          </div>
        </div>

        {/* Active Strategy */}
        <div className="card card-glow-purple">
          <div className="card-title">Active Strategy</div>
          <div className="space-y">
            <div style={{ fontSize: "1.05rem", fontWeight: 700, color: "var(--accent-purple)" }}>
              {(() => {
                if (!strategy) return "Momentum Strategy";
                if (typeof strategy === "string") return strategy;
                return strategy.strategy || strategy.name || "Momentum Strategy";
              })()}
            </div>
            <div className="row-between" style={{ marginTop: 8 }}>
              <span className="metric-label">Type</span>
              <Tag text={typeof strategy === "object" && strategy?.type ? strategy.type : "Trend Following"} color="blue" />
            </div>
            <div className="row-between">
              <span className="metric-label">Bias</span>
              <Tag
                text={signal === "BUY" ? "Bullish" : signal === "SELL" ? "Bearish" : "Neutral"}
                color={signal === "BUY" ? "green" : signal === "SELL" ? "red" : "orange"}
              />
            </div>
            <div className="row-between">
              <span className="metric-label">Confidence</span>
              <span className="text-cyan" style={{ fontFamily: "'JetBrains Mono'" }}>{fmtPct(confidence)}</span>
            </div>
            <div className="row-between">
              <span className="metric-label">Volume Signal</span>
              <Tag
                text={confidence && confidence > 0.6 ? "High" : confidence && confidence > 0.4 ? "Medium" : "Low"}
                color={confidence && confidence > 0.6 ? "green" : confidence && confidence > 0.4 ? "yellow" : "red"}
              />
            </div>
          </div>
        </div>

        {/* Regime */}
        <div className="card">
          <div className="card-title">Market Regime</div>
          <div className="space-y">
            <div className="row-between">
              <span className="metric-label">Trend</span>
              <Tag text={regime?.trend || "--"} color={regime?.trend === "uptrend" ? "green" : regime?.trend === "downtrend" ? "red" : "orange"} />
            </div>
            <div className="row-between">
              <span className="metric-label">Volatility</span>
              <Tag text={regime?.volatility || "--"} color={regime?.volatility === "high_volatility" ? "red" : "green"} />
            </div>
            <div className="row-between">
              <span className="metric-label">Risk</span>
              <Tag text={regime?.risk || "--"} color={regime?.risk === "risk_off" ? "red" : "green"} />
            </div>
            <div className="row-between">
              <span className="metric-label">Label</span>
              <Tag text={regime?.label || "--"} color="purple" />
            </div>
          </div>
        </div>

        {/* Sentiment */}
        <div className="card">
          <div className="card-title">Sentiment</div>
          <div className="row-between">
            <span className={sentiment?.label === "bullish" ? "text-green" : sentiment?.label === "bearish" ? "text-red" : "text-dim"} style={{ fontSize: "1.2rem", fontWeight: 700 }}>
              {sentiment?.label ? sentiment.label.charAt(0).toUpperCase() + sentiment.label.slice(1) : "Neutral"}
            </span>
            <span className="metric-value text-blue" style={{ fontSize: "1rem" }}>
              {fmtNum(sentiment?.score, 4)}
            </span>
          </div>
        </div>

        {/* Risk */}
        <div className="card">
          <div className="card-title">Risk Status</div>
          {risk ? (
            <div className="space-y">
              <div className="row-between">
                <span className="metric-label">Risk Level</span>
                <Tag
                  text={risk.risk_level || "--"}
                  color={risk.risk_level === "high" ? "red" : risk.risk_level === "medium" ? "orange" : "green"}
                />
              </div>
              <div className="row-between">
                <span className="metric-label">Score</span>
                <span className="text-orange" style={{ fontFamily: "'JetBrains Mono'" }}>{fmtNum(risk.risk_score, 4)}</span>
              </div>
              {riskDashboard?.kill_switch && (
                <div style={{ textAlign: "center", marginTop: 8 }}>
                  <Tag text="⚠ KILL SWITCH ACTIVE" color="red" />
                </div>
              )}
            </div>
          ) : (
            <div className="text-dim" style={{ fontSize: "0.8rem" }}>Loading...</div>
          )}
        </div>

        {/* Actions */}
        <div className="card">
          <div className="card-title">Actions</div>
          <div className="btn-group" style={{ flexDirection: "column" }}>
            <button className="btn btn-primary" onClick={getPredictions} disabled={loading}>
              {loading ? "⏳ Loading..." : "🧠 AI Prediction"}
            </button>
            <button className="btn" onClick={getPrice}>📊 Refresh Price</button>
          </div>
        </div>
      </div>

      {/* ======== CENTER PANEL ======== */}
      <div className="center-panel">

        {/* Chart */}
        <div className="card">
          <div className="card-title">{symbol.replace("USDT", "")} Trading Chart</div>
          <Chart symbol={symbol} predictions={predictions} />
        </div>

        {/* Signal Breakdown */}
        <div className="card">
          <div className="card-title">Signal Breakdown</div>
          <table className="table">
            <thead>
              <tr>
                <th>Component</th>
                <th>Signal</th>
                <th>Strength</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(components).map(([key, val]) => (
                <tr key={key}>
                  <td style={{ textTransform: "capitalize" }}>{key.replace(/_/g, " ")}</td>
                  <td className={signalColor(val)}>{signalText(val)}</td>
                  <td>
                    <ProgressBar value={Math.abs(val || 0)} color={val > 0 ? "green" : val < 0 ? "red" : "blue"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Predictions Table */}
        {predictions.length > 0 && (
          <div className="card">
            <div className="card-title">Multi-Step Predictions</div>
            <table className="table">
              <thead>
                <tr>
                  <th>Step</th>
                  <th>Direction</th>
                  <th>Probability</th>
                  <th>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {predictions.map((p, i) => (
                  <tr key={i}>
                    <td>{p.step}</td>
                    <td className={p.direction === "UP" ? "text-green" : "text-red"}>
                      {p.direction === "UP" ? "▲" : "▼"} {p.direction}
                    </td>
                    <td>{fmtPct(p.probability)}</td>
                    <td>{fmtPct(p.confidence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}



        {/* RSI Indicator */}
        <div className="card"><RSI /></div>

        {/* Strategies List */}
        {strategies.length > 0 && (
          <div className="card">
            <div className="card-title">Strategy Library</div>
            <table className="table">
              <thead>
                <tr><th>Strategy</th><th>Type</th><th>Weight</th></tr>
              </thead>
              <tbody>
                {strategies.map((s, i) => (
                  <tr key={i}>
                    <td>{s.name}</td>
                    <td><Tag text={s.type} color="purple" /></td>
                    <td className="text-cyan">{fmtPct(s.weight)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ======== RIGHT PANEL ======== */}
      <div className="right-panel">

        {/* Portfolio */}
        <div className="card card-glow-purple">
          <div className="card-title">Portfolio</div>
          {performance ? (
            <div className="metric-grid">
              <MetricBox label="Total Return" value={fmtPct(performance.total_return)} color={performance.total_return >= 0 ? "text-green" : "text-red"} />
              <MetricBox label="Win Rate" value={fmtPct(performance.win_rate)} color="text-blue" />
              <MetricBox label="Max DD" value={fmtPct(performance.max_drawdown)} color="text-red" />
              <MetricBox label="Trades" value={performance.total_trades || 0} color="text-purple" />
            </div>
          ) : (
            <div className="text-dim" style={{ fontSize: "0.8rem", padding: 12 }}>No portfolio data</div>
          )}
        </div>

        {/* Paper Trading */}
        <div className="card">
          <div className="card-title">Paper Trading</div>
          {paperStatus && paperStatus.running ? (
            <div className="space-y">
              <div className="row-between">
                <span className="metric-label">Status</span>
                <Tag text="RUNNING" color="green" />
              </div>
              <div className="row-between">
                <span className="metric-label">Cycles</span>
                <span className="text-cyan">{paperStatus.cycle_count}</span>
              </div>
              {paperStatus.performance && (
                <>
                  <div className="row-between">
                    <span className="metric-label">Return</span>
                    <span className={paperStatus.performance.total_return >= 0 ? "text-green" : "text-red"}>
                      {fmtPct(paperStatus.performance.total_return)}
                    </span>
                  </div>
                  <div className="row-between">
                    <span className="metric-label">Win Rate</span>
                    <span className="text-blue">{fmtPct(paperStatus.performance.win_rate)}</span>
                  </div>
                </>
              )}
            </div>
          ) : (
            <div className="text-dim" style={{ fontSize: "0.8rem", padding: 8 }}>
              Paper trading not started
            </div>
          )}
        </div>

        {/* Order Book */}
        <div className="card">
          <OrderBook symbol={symbol} />
        </div>

        {/* News */}
        <div className="card">
          <div className="card-title">News Feed</div>
          {news.length > 0 ? (
            <div className="space-y">
              {news.slice(0, 8).map((item, i) => (
                <div key={i} style={{ borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
                  <a
                    href={item.url || "#"}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: "var(--text-primary)", textDecoration: "none", fontSize: "0.78rem", lineHeight: 1.4 }}
                  >
                    {item.title || item}
                  </a>
                  {item.source && (
                    <div className="metric-label" style={{ marginTop: 2 }}>{item.source}</div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-dim" style={{ fontSize: "0.8rem" }}>No news loaded</div>
          )}
        </div>

        {/* Order History */}
        {orderHistory.length > 0 && (
          <div className="card">
            <div className="card-title">Recent Orders</div>
            {orderStats && (
              <div className="metric-grid" style={{ marginBottom: 12 }}>
                <MetricBox label="Filled" value={orderStats.total_filled || 0} color="text-green" />
                <MetricBox label="Fill Rate" value={orderStats.fill_rate ? `${(orderStats.fill_rate * 100).toFixed(0)}%` : "--"} color="text-blue" />
              </div>
            )}
            <div className="space-y">
              {orderHistory.slice(0, 8).map((o, i) => (
                <div key={i} style={{ fontSize: "0.75rem", borderBottom: "1px solid var(--border)", paddingBottom: 6, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <Tag text={o.side?.toUpperCase() || ""} color={o.side === "buy" ? "green" : "red"} />
                    <span style={{ marginLeft: 6 }}>{o.symbol}</span>
                  </div>
                  <div className="text-cyan" style={{ fontFamily: "'JetBrains Mono'" }}>
                    {o.filled_price ? `$${Number(o.filled_price).toFixed(2)}` : "--"}
                  </div>
                  <Tag text={o.status || ""} color={o.status === "filled" ? "green" : o.status === "rejected" ? "red" : "orange"} />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Risk Events */}
        {riskDashboard?.events?.length > 0 && (
          <div className="card">
            <div className="card-title">Risk Events</div>
            <div className="space-y">
              {riskDashboard.events.slice(0, 5).map((evt, i) => (
                <div key={i} style={{ fontSize: "0.75rem", borderBottom: "1px solid var(--border)", paddingBottom: 6 }}>
                  <Tag text={evt.type || "event"} color="red" />
                  <span style={{ marginLeft: 6, color: "var(--text-secondary)" }}>{evt.message || JSON.stringify(evt)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ======== FOOTER ======== */}
      <Footer />
    </div>
  );
}

export default App;