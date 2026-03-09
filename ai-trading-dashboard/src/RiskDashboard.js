import React from "react";

function RiskDashboard(){

  const metrics = {

    volatility:"18%",
    sharpe:"1.8",
    sortino:"2.1",
    maxDrawdown:"-7%",
    var:"3.2%"

  };

  return(

    <div style={{marginBottom:20}}>

      <h3>Risk Dashboard</h3>

      <p>Volatility: {metrics.volatility}</p>
      <p>Sharpe Ratio: {metrics.sharpe}</p>
      <p>Sortino Ratio: {metrics.sortino}</p>
      <p>Max Drawdown: {metrics.maxDrawdown}</p>
      <p>Value at Risk: {metrics.var}</p>

    </div>

  );

}

export default RiskDashboard;