import React, { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";

function EquityCurve({ equity = [] }) {

const chartRef = useRef();
const containerRef = useRef();

useEffect(()=>{

if(!containerRef.current) return;

const chart = createChart(containerRef.current,{
height:250,
layout:{
background:{color:"#0b0b0b"},
textColor:"#DDD"
},
grid:{
vertLines:{color:"#1a1a1a"},
horzLines:{color:"#1a1a1a"}
},
rightPriceScale:{
borderColor:"#333"
},
timeScale:{
borderColor:"#333",
timeVisible:true
}
});

const lineSeries = chart.addLineSeries({
color:"#00ff9c",
lineWidth:2
});

if(equity.length>0){
lineSeries.setData(equity);
}

chartRef.current = chart;

return ()=>{
chart.remove();
}

},[equity]);

return(

<div style={{marginTop:20}}>

<h3>Equity Curve</h3>

<div
ref={containerRef}
style={{
width:"100%",
height:250
}}
/>

</div>

);

}

export default EquityCurve;