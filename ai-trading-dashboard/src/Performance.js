import React from "react";

function Performance() {

  const stats = {
    winRate: "63%",
    sharpe: "1.8",
    drawdown: "-7%",
    totalReturn: "+24%"
  };

  const cardStyle = {
    background: "#161616",
    borderRadius: 10,
    padding: 18,
    marginBottom: 20,
    border: "1px solid #2a2a2a",
    boxShadow: "0 6px 15px rgba(0,0,0,0.4)",
    color: "white",
    width: "100%"
  };

  return (

    <div style={cardStyle}>

      <h3 style={{ marginBottom: 15 }}>
        Strategy Performance
      </h3>

      <p><b>Win Rate:</b> {stats.winRate}</p>
      <p><b>Sharpe Ratio:</b> {stats.sharpe}</p>
      <p><b>Max Drawdown:</b> {stats.drawdown}</p>
      <p><b>Total Return:</b> {stats.totalReturn}</p>

      {/* Equity Curve Chart */}

    </div>

  );

}

export default Performance;