export function calculateEMA(data,period){

  const k=2/(period+1);

  let ema=data[0].close;

  const result=[ema];

  for(let i=1;i<data.length;i++){

    ema=data[i].close*k+ema*(1-k);

    result.push(ema);

  }

  return result;

}