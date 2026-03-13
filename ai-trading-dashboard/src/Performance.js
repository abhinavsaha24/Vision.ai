import React from "react";

function Performance({ portfolio, performance }) {
  const perf = performance || {};

  return (
    <div>
      <div className="card-title">Performance Metrics</div>
      <div className="metric-grid">
        <div className="metric">
          <div className={`metric-value ${(perf.total_return || 0) >= 0 ? "text-green" : "text-red"}`}>
            {perf.total_return != null ? `${(perf.total_return * 100).toFixed(2)}%` : "--"}
          </div>
          <div className="metric-label">Total Return</div>
        </div>
        <div className="metric">
          <div className="metric-value text-blue">
            {perf.win_rate != null ? `${(perf.win_rate * 100).toFixed(1)}%` : "--"}
          </div>
          <div className="metric-label">Win Rate</div>
        </div>
        <div className="metric">
          <div className="metric-value text-red">
            {perf.max_drawdown != null ? `${(perf.max_drawdown * 100).toFixed(2)}%` : "--"}
          </div>
          <div className="metric-label">Max DD</div>
        </div>
        <div className="metric">
          <div className="metric-value text-purple">
            {perf.total_trades || 0}
          </div>
          <div className="metric-label">Total Trades</div>
        </div>
      </div>
    </div>
  );
}

export default Performance;