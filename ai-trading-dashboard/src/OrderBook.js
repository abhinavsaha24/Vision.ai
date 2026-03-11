import React, { useEffect, useState, useRef } from "react";

function OrderBook({ symbol }) {

  const [bids, setBids] = useState([]);
  const [asks, setAsks] = useState([]);

  const wsRef = useRef(null);

  useEffect(() => {

    const connect = () => {

      if (wsRef.current) {
        wsRef.current.close();
      }

      const ws = new WebSocket(
        `wss://stream.binance.com:9443/ws/${symbol.toLowerCase()}@depth20@100ms`
      );

      wsRef.current = ws;

      ws.onmessage = (event) => {

        try {

          const data = JSON.parse(event.data);

          setBids(data.bids.slice(0, 10));
          setAsks(data.asks.slice(0, 10));

        } catch (err) {
          console.warn("OrderBook parse error", err);
        }

      };

      ws.onerror = (err) => {
        console.warn("OrderBook websocket error:", err);
      };

      ws.onclose = () => {

        console.log("OrderBook websocket closed — reconnecting...");

        setTimeout(() => {
          connect();
        }, 3000);

      };

    };

    connect();

    return () => {

      if (wsRef.current) {
        wsRef.current.close();
      }

    };

  }, [symbol]);

  return (

    <div>

      <h3>Order Book</h3>

      <div style={{ display: "flex", gap: 20 }}>

        <div>

          <h4>Bids</h4>

          {bids.map((b, i) => (
            <p key={i} style={{ color: "#00ff9c" }}>
              {parseFloat(b[0]).toFixed(2)} ({parseFloat(b[1]).toFixed(4)})
            </p>
          ))}

        </div>

        <div>

          <h4>Asks</h4>

          {asks.map((a, i) => (
            <p key={i} style={{ color: "#ff4d4d" }}>
              {parseFloat(a[0]).toFixed(2)} ({parseFloat(a[1]).toFixed(4)})
            </p>
          ))}

        </div>

      </div>

    </div>

  );

}

export default OrderBook;