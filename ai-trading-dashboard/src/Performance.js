import React, { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";

function Performance({ data=[] }){

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

const series = chart.addHistogramSeries({
color:"#4CAF50"
});

if(data.length>0){
series.setData(data);
}

chartRef.current = chart;

return ()=> chart.remove();

},[data]);

return(

<div style={{marginTop:20}}>

<h3>Strategy Performance</h3>

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

export default Performance;