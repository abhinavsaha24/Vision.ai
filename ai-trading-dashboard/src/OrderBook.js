import React, { useEffect, useState } from "react";

function OrderBook({ symbol }) {

  const [bids, setBids] = useState([]);
  const [asks, setAsks] = useState([]);

  const symbolMap = {
    "BTC-USD": "btcusdt",
    "ETH-USD": "ethusdt",
    "SOL-USD": "solusdt"
  };

  useEffect(() => {

    const pair = symbolMap[symbol] || "btcusdt";

    const ws = new WebSocket(
      `wss://stream.binance.com:9443/ws/${pair}@depth20@100ms`
    );

    ws.onmessage = (event) => {

      const data = JSON.parse(event.data);

      if (data.bids && data.asks) {

        setBids(data.bids.slice(0, 10));
        setAsks(data.asks.slice(0, 10));

      }

    };

    return () => ws.close();

  }, [symbol]);

  return (

    <div style={{
      background:"#121212",
      padding:15,
      borderRadius:10
    }}>

      <h3>Order Book</h3>

      <div style={{display:"flex", justifyContent:"space-between"}}>

        {/* BIDS */}

        <div>

          <h4 style={{color:"#00ff9c"}}>Bids</h4>

          {bids.map((b,i)=>(

            <div key={i} style={{fontSize:12}}>

              {parseFloat(b[0]).toFixed(2)}  
              {"  "}
              ({parseFloat(b[1]).toFixed(4)})

            </div>

          ))}

        </div>

        {/* ASKS */}

        <div>

          <h4 style={{color:"#ff4d4d"}}>Asks</h4>

          {asks.map((a,i)=>(

            <div key={i} style={{fontSize:12}}>

              {parseFloat(a[0]).toFixed(2)}  
              {"  "}
              ({parseFloat(a[1]).toFixed(4)})

            </div>

          ))}

        </div>

      </div>

    </div>

  );

}

export default OrderBook;