import React from "react";

function Portfolio({ portfolio }) {
  if (!portfolio) return <div className="text-dim" style={{ fontSize: "0.8rem" }}>No portfolio data</div>;

  return (
    <div>
      <div className="card-title">Portfolio</div>
      <div className="metric-grid">
        <div className="metric">
          <div className="metric-value text-green">
            ${(portfolio.cash || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </div>
          <div className="metric-label">Cash</div>
        </div>
        <div className="metric">
          <div className="metric-value text-cyan">
            {portfolio.open_trades || 0}
          </div>
          <div className="metric-label">Open Trades</div>
        </div>
      </div>

      {portfolio.positions && Object.keys(portfolio.positions).length > 0 && (
        <div style={{ marginTop: 12 }}>
          <table className="table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Size</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(portfolio.positions).map(([sym, pos]) => (
                <tr key={sym}>
                  <td>{sym}</td>
                  <td className={pos.side === "long" ? "text-green" : "text-red"}>
                    {pos.side?.toUpperCase()}
                  </td>
                  <td>${pos.entry_price?.toFixed(2)}</td>
                  <td>{pos.quantity?.toFixed(6)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default Portfolio;