import React, { useState, useEffect } from "react";
import axios from "axios";

function Watchlist() {

  const assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT"];
  const [prices, setPrices] = useState({});

  const loadPrices = async () => {
    try {

      const updated = {};

      for (const asset of assets) {

        const res = await axios.get(
          `https://api.binance.com/api/v3/ticker/price?symbol=${asset}`
        );

        updated[asset] = res.data.price;

      }

      setPrices(updated);

    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {

    loadPrices();

    const interval = setInterval(loadPrices, 30000);

    return () => clearInterval(interval);

  }, []);

  return (

    <div style={{marginBottom:20}}>

      <h3>Watchlist</h3>

      {assets.map(a => (

        <div key={a} style={{marginBottom:6}}>

          <b>{a.replace("USDT","")}</b>

          {"  "}  

          ${prices[a] ? parseFloat(prices[a]).toFixed(2) : "--"}

        </div>

      ))}

    </div>

  );

}

export default Watchlist;