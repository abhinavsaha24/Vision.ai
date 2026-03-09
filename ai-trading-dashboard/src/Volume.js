import React,{useEffect,useRef} from "react";
import {createChart,HistogramSeries} from "lightweight-charts";

function Volume(){

const ref = useRef(null);

useEffect(()=>{

const chart = createChart(ref.current,{
height:150,

layout:{
background:{color:"#0f0f0f"},
textColor:"#DDD"
}
});

const volumeSeries = chart.addSeries(HistogramSeries,{
color:"#26a69a"
});

volumeSeries.setData([
{time:1700000000,value:100},
{time:1700000600,value:200},
{time:1700001200,value:150},
{time:1700001800,value:300}
]);

return ()=>chart.remove();

},[]);

return <div ref={ref}></div>;

}

export default Volume;