import React from "react";

function NewsFeed({ items = [] }) {

  return (

    <div style={{
      background:"#0f0f0f",
      padding:16,
      borderRadius:10,
      border:"1px solid #262626"
    }}>

      <h3 style={{marginTop:0}}>Market News</h3>

      {items.length === 0 ? (

        <p style={{color:"#aaa"}}>Loading news...</p>

      ) : (

        <ul style={{paddingLeft:18, margin:0}}>

          {items.map((n,i)=>(
            <li key={i} style={{marginBottom:8}}>
              <a
                href={n.url}
                target="_blank"
                rel="noreferrer"
                style={{color:"#8fd8b6"}}
              >
                {n.title}
              </a>
            </li>
          ))}

        </ul>

      )}

    </div>

  );

}

export default NewsFeed;