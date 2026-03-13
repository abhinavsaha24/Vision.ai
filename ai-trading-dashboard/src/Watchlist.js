import React from "react";

function Watchlist() {
  const pairs = [
    { sym: "BTC/USDT", type: "crypto" },
    { sym: "ETH/USDT", type: "crypto" },
    { sym: "SOL/USDT", type: "crypto" },
    { sym: "BNB/USDT", type: "crypto" },
    { sym: "XRP/USDT", type: "crypto" },
    { sym: "ADA/USDT", type: "crypto" },
    { sym: "AVAX/USDT", type: "crypto" },
    { sym: "DOGE/USDT", type: "crypto" },
  ];

  return (
    <div>
      <div className="card-title">Watchlist</div>
      <div className="space-y">
        {pairs.map((p, i) => (
          <div key={i} className="row-between" style={{ padding: "4px 0" }}>
            <span style={{ fontSize: "0.8rem", fontWeight: 500 }}>{p.sym}</span>
            <span className="tag tag-blue">{p.type}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default Watchlist;