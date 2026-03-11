// src/NewsFeed.js
import React from "react";

function NewsFeed({ items = [] }) {
  // items: [{title, url, source, timestamp}]
  const news = items.length ? items : [
    { title: "Bitcoin ETF inflows increasing", url: "https://example.com/bitcoin-etf" },
    { title: "Ethereum gas fees drop", url: "https://example.com/eth-gas" },
  ];

  return (
    <div style={{
      background:"#0f0f0f", padding:16, borderRadius:10, border:"1px solid #262626"
    }}>
      <h3 style={{marginTop:0}}>Market News</h3>
      <ul style={{paddingLeft:18, margin:0}}>
        {news.map((n, i) => (
          <li key={i} style={{marginBottom:8}}>
            <a href={n.url} target="_blank" rel="noreferrer" style={{color:"#8fd8b6"}}>
              {n.title}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default NewsFeed;