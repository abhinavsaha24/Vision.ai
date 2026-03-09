import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";

import Portfolio from "./Portfolio";
import Watchlist from "./Watchlist";
import MarketTimeline from "./MarketTimeline";
import RiskPanel from "./RiskPanel";
import MarketStatus from "./MarketStatus";
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

const API = "https://vision-ai-1aoe.onrender.com";

/* ---------------- STATES ---------------- */

const [symbol, setSymbol] = useState("BTC-USD");
const [predictions, setPredictions] = useState([]);
const [price, setPrice] = useState(null);
const [time, setTime] = useState(new Date());

const [loadingPred, setLoadingPred] = useState(false);
const [loadingPrice, setLoadingPrice] = useState(false);
const [error, setError] = useState(null);

const [portfolio, setPortfolio] = useState({
cash:10000,
btc:0,
history:[]
});

/* ---------------- SYMBOL MAP ---------------- */

const symbolMap = {
"BTC-USD":"BTCUSDT",
"ETH-USD":"ETHUSDT",
"SOL-USD":"SOLUSDT"
};

/* ---------------- LIVE CLOCK ---------------- */

useEffect(()=>{

const timer = setInterval(()=>{
setTime(new Date());
},1000);

return ()=>clearInterval(timer);

},[]);

/* ---------------- PRICE FETCH ---------------- */

const getPrice = useCallback(async()=>{

try{

setLoadingPrice(true);

const pair = symbolMap[symbol] || "BTCUSDT";

const res = await axios.get(
`https://api.binance.com/api/v3/ticker/price?symbol=${pair}`
);

setPrice(res.data.price);
setError(null);

}catch(err){

console.error(err);
setError("Price API error");

}finally{

setLoadingPrice(false);

}

},[symbol]);

/* ---------------- AUTO REFRESH PRICE ---------------- */

useEffect(()=>{

getPrice();

const interval = setInterval(getPrice,30000);

return ()=>clearInterval(interval);

},[getPrice]);

/* ---------------- AUTO AI TRADE ---------------- */

useEffect(()=>{

if(predictions.length>0 && price){

const updatedPortfolio = executeTrade(
predictions[0],
price,
portfolio
);

setPortfolio(updatedPortfolio);

}

},[predictions,price]);

/* ---------------- AI PREDICTION ---------------- */

const getPredictions = async()=>{

try{

setLoadingPred(true);

const response = await axios.post(`${API}/model/predict`,{
symbol,
horizon:5
});

setPredictions(response?.data?.predictions || []);

}catch(err){

console.error(err);
setError("Prediction API failed");

}finally{

setLoadingPred(false);

}

};

/* ---------------- STYLES ---------------- */

const styles={

container:{
padding:20,
display:"grid",
gridTemplateColumns:"260px minmax(600px,1fr) 320px",
alignItems:"start",
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

{/* LEFT SIDEBAR */}

<div>

<h2>Vision-AI</h2>

<p style={{color:"#aaa"}}>
{time.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'})}
</p>

{/* SYMBOL SWITCH */}

<div style={{marginBottom:15}}>

<button style={styles.button} onClick={()=>setSymbol("BTC-USD")}>BTC</button>
<button style={styles.button} onClick={()=>setSymbol("ETH-USD")}>ETH</button>
<button style={styles.button} onClick={()=>setSymbol("SOL-USD")}>SOL</button>

</div>

{/* ACTION BUTTONS */}

<div style={{marginBottom:15}}>

<button style={styles.button} onClick={getPredictions}>
{loadingPred ? "Loading..." : "AI Prediction"}
</button>

<button style={styles.button} onClick={getPrice}>
Refresh Price
</button>

</div>

{/* LIVE PRICE */}

<div style={styles.card}>

<h3>Live Price</h3>

<p style={{fontSize:22}}>
{loadingPrice ? "Loading..." : `$${price ? parseFloat(price).toFixed(2) : "--"}`}
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

<h2>{symbol.replace("-USD","")} AI Trading Chart</h2>

<Chart symbol={symbol} predictions={predictions}/>

</div>

{predictions.length>0 &&(

<div style={styles.card}>

<h3>AI Signal</h3>

<p>

<b>Signal:</b>

<span style={{
color: predictions[0].direction==="UP" ? "#00ff9c":"#ff4d4d",
fontWeight:"bold",
marginLeft:6
}}>

{predictions[0].direction==="UP"?"BUY":"SELL"}

</span>

</p>

<p>

Confidence {(predictions[0].probability*100).toFixed(2)}%

</p>

</div>

)}

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

Vision-AI <br/>

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