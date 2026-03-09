import React from "react";

function PnLDashboard({ portfolio, price }) {

const equity = price
? portfolio.cash + portfolio.btc * price
: portfolio.cash;

const pnl = equity - 10000;

const totalTrades = portfolio.history.length;

const wins = portfolio.history.filter(
t => t.type === "SELL"
).length;

const winRate = totalTrades
? ((wins / totalTrades) * 100).toFixed(1)
: 0;

return (

<div>

<h3>PnL Analytics</h3>

<p>
<b>Total Equity:</b> ${equity.toFixed(2)}
</p>

<p>
<b>Total PnL:</b>
<span style={{
color: pnl >= 0 ? "#00ff9c" : "#ff4d4d"
}}>
${pnl.toFixed(2)}
</span>
</p>

<p>
<b>Total Trades:</b> {totalTrades}
</p>

<p>
<b>Win Rate:</b> {winRate}%
</p>

</div>

);

}

export default PnLDashboard;