import React from "react";

function TradeHistory({ portfolio }) {

  const trades = portfolio?.history || [];

  return (

    <div style={{
      background:"#121212",
      padding:18,
      borderRadius:12,
      marginBottom:20,
      border:"1px solid #262626"
    }}>

      <h3>Trade History</h3>

      {trades.length === 0 && <p>No trades yet</p>}

      {trades.map((t,i)=>(
        <div key={i}>
          {t.type} BTC @ ${t.price.toFixed(2)}
        </div>
      ))}

    </div>

  );

}

export default TradeHistory;