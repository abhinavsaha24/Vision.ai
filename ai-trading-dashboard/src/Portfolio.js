import React from "react";

function Portfolio({ portfolio }) {

  return (

    <div>

      <h3>Portfolio</h3>

      <p>Cash: ${portfolio.cash.toFixed(2)}</p>

      <p>BTC: {portfolio.btc}</p>

    </div>

  );

}

export default Portfolio;