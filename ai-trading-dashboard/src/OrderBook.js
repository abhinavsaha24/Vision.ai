import React, { useEffect, useState, useRef, useCallback } from "react";

/**
 * OrderBook.js — Live order book depth
 *
 * Fixes:
 *  1. WebSocket URL: removed :9443 port
 *  2. Exponential backoff reconnect
 *  3. Stale connection detection
 *  4. Proper cleanup on unmount
 *  5. Premium visual design with depth bars
 */

const WS_BASE = "wss://stream.binance.com/ws";
const MAX_RECONNECT_DELAY = 30000;
const STALE_TIMEOUT = 30000;

function OrderBook({ symbol }) {

  const [bids, setBids] = useState([]);
  const [asks, setAsks] = useState([]);

  const wsRef = useRef(null);
  const reconnectRef = useRef(null);
  const attemptRef = useRef(0);
  const lastMsgRef = useRef(Date.now());
  const staleRef = useRef(null);
  const mounted = useRef(true);

  const connect = useCallback(() => {
    if (!mounted.current) return;

    // Close existing
    if (wsRef.current) {
      try { wsRef.current.close(); } catch {}
    }

    const pair = symbol.toLowerCase();

    // FIX: no port number
    const ws = new WebSocket(`${WS_BASE}/${pair}@depth20@100ms`);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("OrderBook WS connected");
      attemptRef.current = 0;
      lastMsgRef.current = Date.now();
    };

    ws.onmessage = (event) => {
      if (!mounted.current) return;
      lastMsgRef.current = Date.now();

      try {
        const data = JSON.parse(event.data);
        if (data.bids) setBids(data.bids.slice(0, 10));
        if (data.asks) setAsks(data.asks.slice(0, 10));
      } catch (err) {
        console.warn("OrderBook parse error", err);
      }
    };

    ws.onerror = (err) => {
      console.warn("OrderBook WS error:", err);
    };

    ws.onclose = () => {
      if (!mounted.current) return;

      const delay = Math.min(1000 * Math.pow(2, attemptRef.current), MAX_RECONNECT_DELAY);
      attemptRef.current += 1;

      console.warn(`OrderBook WS closed — reconnecting in ${delay}ms`);

      reconnectRef.current = setTimeout(() => {
        if (mounted.current) connect();
      }, delay);
    };
  }, [symbol]);

  // Stale detector
  useEffect(() => {
    staleRef.current = setInterval(() => {
      if (!mounted.current) return;
      if (Date.now() - lastMsgRef.current > STALE_TIMEOUT && wsRef.current) {
        console.warn("OrderBook WS stale — forcing reconnect");
        wsRef.current.close();
      }
    }, STALE_TIMEOUT / 2);

    return () => clearInterval(staleRef.current);
  }, []);

  // Connect on mount / symbol change
  useEffect(() => {
    mounted.current = true;
    connect();

    return () => {
      mounted.current = false;
      if (wsRef.current) { try { wsRef.current.close(); } catch {} }
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
    };
  }, [connect]);

  // Find max quantity for bar sizing
  const maxQty = Math.max(
    ...bids.map(b => parseFloat(b[1]) || 0),
    ...asks.map(a => parseFloat(a[1]) || 0),
    0.001
  );

  return (
    <div>
      <div className="card-title">Order Book</div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>

        {/* Bids */}
        <div>
          <div style={{ fontSize: "0.65rem", color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>
            Bids
          </div>
          {bids.map((b, i) => {
            const price = parseFloat(b[0]);
            const qty = parseFloat(b[1]);
            const pct = (qty / maxQty) * 100;

            return (
              <div
                key={i}
                style={{
                  position: "relative",
                  padding: "3px 6px",
                  marginBottom: 2,
                  borderRadius: 3,
                  overflow: "hidden",
                  fontSize: "0.75rem",
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                {/* Depth bar */}
                <div style={{
                  position: "absolute",
                  left: 0, top: 0, bottom: 0,
                  width: `${pct}%`,
                  background: "rgba(0,230,118,0.1)",
                  borderRadius: 3,
                }} />
                <div style={{ position: "relative", display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "var(--accent-green)" }}>{price.toFixed(2)}</span>
                  <span style={{ color: "var(--text-dim)" }}>{qty.toFixed(4)}</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Asks */}
        <div>
          <div style={{ fontSize: "0.65rem", color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>
            Asks
          </div>
          {asks.map((a, i) => {
            const price = parseFloat(a[0]);
            const qty = parseFloat(a[1]);
            const pct = (qty / maxQty) * 100;

            return (
              <div
                key={i}
                style={{
                  position: "relative",
                  padding: "3px 6px",
                  marginBottom: 2,
                  borderRadius: 3,
                  overflow: "hidden",
                  fontSize: "0.75rem",
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                <div style={{
                  position: "absolute",
                  right: 0, top: 0, bottom: 0,
                  width: `${pct}%`,
                  background: "rgba(255,71,87,0.1)",
                  borderRadius: 3,
                }} />
                <div style={{ position: "relative", display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "var(--accent-red)" }}>{price.toFixed(2)}</span>
                  <span style={{ color: "var(--text-dim)" }}>{qty.toFixed(4)}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default OrderBook;