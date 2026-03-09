import React from "react";

function NewsFeed(){

  const news = [
    "Bitcoin ETF inflows increasing",
    "Ethereum gas fees drop to yearly lows",
    "AI trading bots gaining popularity",
    "Crypto market volatility rising"
  ];

  return (

    <div style={{
      background:"#121212",
      padding:16,
      borderRadius:10,
      border:"1px solid #262626"
    }}>

      <h3>Market News</h3>

      {news.map((n,i)=>(
        <p key={i} style={{fontSize:13}}>
          • {n}
        </p>
      ))}

    </div>

  );

}

export default NewsFeed;