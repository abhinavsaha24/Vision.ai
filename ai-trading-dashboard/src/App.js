import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";

import Portfolio from "./Portfolio";
import Watchlist from "./Watchlist";
import MarketTimeline from "./MarketTimeline";
import RiskPanel from "./RiskPanel";
import Performance from "./Performance";
import TradeHistory from "./TradeHistory";

import Chart from "./Chart";
import Volume from "./Volume";
import RSI from "./RSI";
import EquityCurve from "./EquityCurve";

import OrderBook from "./OrderBook";
import NewsFeed from "./NewsFeed";
import RiskDashboard from "./RiskDashboard";
import { executeTrade } from "./TradeEngine";
import PnLDashboard from "./PnLDashboard";

function App() {

const API = process.env.REACT_APP_API || "https://vision-ai-5qm1.onrender.com";

/* ---------------- STATES ---------------- */

const [symbol,setSymbol] = useState("BTCUSDT");
const [predictions,setPredictions] = useState([]);
const [price,setPrice] = useState(null);
const [time,setTime] = useState(new Date());

const [loadingPred,setLoadingPred] = useState(false);
const [loadingPrice,setLoadingPrice] = useState(false);
const [setError] = useState(null);

const [signal,setSignal] = useState(null);
const [confidence,setConfidence] = useState(null);
const [risk,setRisk] = useState(null);
const [score,setScore] = useState(null);
const [components,setComponents] = useState({});

const [regime,setRegime] = useState({});
const [strategy,setStrategy] = useState(null);

const [portfolio,setPortfolio] = useState({
cash:10000,
btc:0,
history:[]
});


/* ---------------- CLOCK ---------------- */

useEffect(()=>{

const timer=setInterval(()=>{
setTime(new Date());
},1000);

return()=>clearInterval(timer);

},[]);


/* ---------------- PRICE FETCH ---------------- */

const getPrice = useCallback(async () => {

  try {

    setLoadingPrice(true);

    const res = await axios.get(
      "https://api.binance.com/api/v3/ticker/price",
      { params: { symbol } }
    );

    setPrice(parseFloat(res.data.price));
    setError(null);

  } catch (err) {

    console.error(err);
    setError("Price API error");

  } finally {

    setLoadingPrice(false);

  }

}, [symbol, setError]);

/* ---------------- PRICE LOOP ---------------- */

useEffect(()=>{

getPrice();

const interval=setInterval(getPrice,30000);

return()=>clearInterval(interval);

},[getPrice]);


/* ---------------- AUTO TRADE SIMULATION ---------------- */

useEffect(()=>{

if(!predictions.length || !price) return;

setPortfolio(prev =>
executeTrade(predictions[0],price,prev)
);

},[predictions,price]);


/* ---------------- AI PREDICTIONS ---------------- */

const getPredictions = useCallback(async () => {

  try {

    setLoadingPred(true);
    setError(null);

    const res = await axios.post(
      `${API}/model/predict`,
      {
        symbol,
        horizon:5
      },
      {timeout:15000}
    );

    const data=res.data;

    if(!data || !data.predictions){
      throw new Error("Invalid prediction response");
    }

    setPredictions(data.predictions);

    setSignal(data.signal);
    setConfidence(data.confidence);
    setRisk(data.risk);
    setScore(data.signal_score);
    setComponents(data.components || {});
    setRegime(data.regime || {});
    setStrategy(data.strategy || null);

  } catch(err){

    console.error(err);

    if(err.response){
      setError(err.response.data.detail);
    }
    else if(err.request){
      setError("Backend sleeping (Render cold start)");
    }
    else{
      setError("Prediction request failed");
    }

    setPredictions([]);

  } finally {

    setLoadingPred(false);

  }

}, [API, symbol,setError]);

/* ---------------- AUTO PREDICTION LOOP ---------------- */

useEffect(()=>{

getPredictions();

const interval=setInterval(()=>{
getPredictions();
},10000);

return()=>clearInterval(interval);

},[symbol, getPredictions]);

/* ---------------- SIGNAL TEXT ---------------- */

const signalText = (val)=>{

if(val===1) return "Bullish";
if(val===-1) return "Bearish";

return "Neutral";

};


/* ---------------- STYLES ---------------- */

const styles={

container:{
padding:20,
display:"grid",
gridTemplateColumns:"260px minmax(600px,1fr) 320px",
gap:20,
background:"#0a0a0a",
minHeight:"100vh",
color:"#e4e4e4",
fontFamily:"Inter"
},

card:{
background:"#121212",
borderRadius:10,
padding:16,
border:"1px solid #262626",
marginBottom:15
},

button:{
padding:"8px 14px",
background:"#1a1a1a",
border:"1px solid #333",
borderRadius:6,
color:"#ddd",
cursor:"pointer",
marginRight:6
}

};


return(

<div>

<div style={styles.container}>

{/* LEFT PANEL */}

<div>

<h2>Vision-AI</h2>

<p style={{color:"#aaa"}}>
{time.toLocaleTimeString()}
</p>

<div style={{marginBottom:15}}>

<button style={styles.button} onClick={()=>setSymbol("BTCUSDT")}>BTC</button>
<button style={styles.button} onClick={()=>setSymbol("ETHUSDT")}>ETH</button>
<button style={styles.button} onClick={()=>setSymbol("SOLUSDT")}>SOL</button>

</div>

<div style={{marginBottom:15}}>

<button style={styles.button} onClick={getPredictions}>
{loadingPred ? "Loading..." : "AI Prediction"}
</button>

<button style={styles.button} onClick={getPrice}>
Refresh Price
</button>

</div>

<div style={styles.card}>

<h3>Live Price</h3>

<p style={{fontSize:22}}>
{loadingPrice ? "Loading..." : `$${price?.toFixed(2) || "--"}`}
</p>

</div>

<div style={styles.card}><Portfolio portfolio={portfolio}/></div>
<div style={styles.card}><Watchlist/></div>
<div style={styles.card}><MarketTimeline/></div>
<div style={styles.card}><RiskPanel/></div>

</div>


{/* CENTER PANEL */}

<div>

<div style={styles.card}>

<h2>{symbol.replace("USDT","")} AI Trading Chart</h2>

<Chart symbol={symbol} predictions={predictions}/>

</div>


{/* AI SIGNAL */}

<div style={styles.card}>

<h3>AI Trading Intelligence</h3>

<p>

<b>Signal:</b>

<span style={{
color:
signal==="BUY"
? "#00ff9c"
: signal==="SELL"
? "#ff4d4d"
: "#aaa",
fontWeight:"bold",
marginLeft:6
}}>

{signal || "--"}

</span>

</p>

<p>Confidence: {confidence || "--"}</p>
<p>Risk Level: {risk || "--"}</p>
<p>Signal Score: {score || "--"}</p>

</div>


{/* MARKET REGIME */}

<div style={styles.card}>

<h3>Market Regime</h3>

<p>Trend: {regime?.trend || "--"}</p>

<p>Volatility: {regime?.volatility || "--"}</p>

<p>Momentum: {regime?.momentum || "--"}</p>

<p>Active Strategy: {strategy || "--"}</p>

</div>


{/* SIGNAL BREAKDOWN */}

<div style={styles.card}>

<h3>Signal Breakdown</h3>

<p>AI Model: {signalText(components.ai)}</p>
<p>Momentum: {signalText(components.momentum)}</p>
<p>Mean Reversion: {signalText(components.mean_reversion)}</p>
<p>Sentiment: {signalText(components.sentiment)}</p>

</div>


<div style={styles.card}><Volume/></div>
<div style={styles.card}><RSI/></div>

<div style={styles.card}>
<h3>Strategy Performance</h3>
<Performance/>
</div>

<div style={styles.card}>
<EquityCurve portfolio={portfolio} price={price}/>
</div>

</div>


{/* RIGHT PANEL */}

<div>

<div style={styles.card}>
<PnLDashboard portfolio={portfolio} price={price}/>
</div>

<div style={styles.card}>
<OrderBook symbol={symbol}/>
</div>

<div style={styles.card}>
<NewsFeed/>
</div>

<div style={styles.card}>
<RiskDashboard/>
</div>

<div style={styles.card}>
<TradeHistory portfolio={portfolio}/>
</div>

</div>

</div>


{/* FOOTER */}

<div style={{
textAlign:"center",
padding:20,
background:"#080808",
color:"#aaa",
borderTop:"1px solid #222"
}}>

Vision-AI<br/>

Built by <b>Abhinav Saha</b><br/>

<a href="https://github.com/abhinavsaha24" style={{color:"#00ff9c"}}>
GitHub
</a>

{" | "}

<a href="https://linkedin.com/in/abhinavsaha24" style={{color:"#00ff9c"}}>
LinkedIn
</a>

</div>

</div>

);

}

export default App;