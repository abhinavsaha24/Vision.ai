import React, { useState, useEffect,useCallback,useMemo } from "react";
import axios from "axios";

function Watchlist() {

  const assets = useMemo(() => [
  "BTCUSDT",
  "ETHUSDT",
  "SOLUSDT"
], []);
  const [prices, setPrices] = useState({});

 const loadPrices = useCallback(async () => {

  try {

    const res = await axios.get(
      "https://api.binance.com/api/v3/ticker/price"
    );

    const data = res.data;

    const newPrices = {};

    assets.forEach(a => {

      const match = data.find(d => d.symbol === a);

      if(match){
        newPrices[a] = match.price;
      }

    });

    setPrices(newPrices);

  } catch(err){
    console.error(err);
  }

}, [assets]);

 useEffect(() => {

  loadPrices();

  const interval = setInterval(loadPrices, 30000);

  return () => clearInterval(interval);

}, [loadPrices]);


return (

  <div style={{ marginBottom:20 }}>

    <h3>Watchlist</h3>

    {assets.map(a => (

      <div key={a} style={{ marginBottom:6 }}>

        <b>{a.replace("USDT","")}</b>

        {"  "}

        ${prices[a] ? parseFloat(prices[a]).toFixed(2) : "--"}

      </div>

    ))}

  </div>

);

}

export default Watchlist;