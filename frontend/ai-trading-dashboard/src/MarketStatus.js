import React, { useEffect, useState } from "react";

function MarketStatus(){

return(

<div style={{
background:"#161616",
padding:18,
borderRadius:10,
marginBottom:20,
border:"1px solid #2a2a2a"
}}>

<h3>Market Timeline</h3>

<p>🇮🇳 India Market</p>
<p>9:15 AM – 3:30 PM</p>

<br/>

<p>🇺🇸 US Market</p>
<p>9:30 AM – 4:00 PM</p>

<br/>

<p>₿ Crypto Market</p>
<p>Open 24 Hours</p>

</div>

)

}

export default MarketStatus