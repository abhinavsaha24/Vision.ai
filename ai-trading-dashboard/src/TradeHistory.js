import React from "react";

function TradeHistory({ portfolio }) {
  const history = portfolio?.history || [];

  if (history.length === 0) {
    return (
      <div>
        <div className="card-title">Trade History</div>
        <div className="text-dim" style={{ fontSize: "0.8rem" }}>No trades yet</div>
      </div>
    );
  }

  return (
    <div>
      <div className="card-title">Trade History</div>
      <table className="table">
        <thead>
          <tr>
            <th>Side</th>
            <th>Price</th>
            <th>P&L</th>
          </tr>
        </thead>
        <tbody>
          {history.slice(-10).reverse().map((trade, i) => (
            <tr key={i}>
              <td className={trade.side === "BUY" || trade.side === "long" ? "text-green" : "text-red"}>
                {(trade.side || "").toUpperCase()}
              </td>
              <td>${(trade.price || 0).toFixed(2)}</td>
              <td className={(trade.pnl || 0) >= 0 ? "text-green" : "text-red"}>
                {trade.pnl != null ? `$${trade.pnl.toFixed(2)}` : "--"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default TradeHistory;