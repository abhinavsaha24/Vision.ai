import React, { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";

function Chart({ symbol }) {

const containerRef = useRef(null);

useEffect(() => {

if(!containerRef.current) return;

const chart = createChart(containerRef.current,{
height:420,
layout:{
background:{color:"#0f0f0f"},
textColor:"#DDD"
}
});

const candleSeries = chart.addCandlestickSeries();

let ws;

const connect = () => {

ws = new WebSocket(
`wss://stream.binance.com:9443/ws/${symbol.toLowerCase()}@kline_5m`
);

ws.onmessage = (event)=>{

const msg = JSON.parse(event.data);

if(!msg.k) return;

const k = msg.k;

candleSeries.update({
time: k.t / 1000,
open: parseFloat(k.o),
high: parseFloat(k.h),
low: parseFloat(k.l),
close: parseFloat(k.c)
});

};

ws.onerror = (err)=>{
console.log("Chart websocket error:",err);
};

ws.onclose = ()=>{
console.log("Chart websocket closed — reconnecting...");
setTimeout(connect,2000);
};

};

connect();

return ()=>{
if(ws){
ws.close();
}
chart.remove();
};

},[symbol]);

return <div ref={containerRef} style={{width:"100%"}}></div>;

}

export default Chart;