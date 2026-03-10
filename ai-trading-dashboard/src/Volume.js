import React, { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";

function Volume(){

const ref = useRef(null);

useEffect(()=>{

if(!ref.current) return;

const chart = createChart(ref.current,{
height:150,

layout:{
background:{color:"#0f0f0f"},
textColor:"#DDD"
},

grid:{
vertLines:{color:"#1a1a1a"},
horzLines:{color:"#1a1a1a"}
}

});

const volumeSeries = chart.addHistogramSeries({
color:"#26a69a"
});

volumeSeries.setData([]);

return ()=>chart.remove();

},[]);

return <div ref={ref} style={{width:"100%"}}></div>;

}

export default Volume;