export async function fetchNews(){

 try{

 const res = await fetch(
   "https://api.allorigins.win/raw?url=" +
   encodeURIComponent(
     "https://cryptopanic.com/api/developer/v2/posts/?auth_token=YOUR_TOKEN&currencies=BTC&public=true"
   )
 );

 const data = await res.json();

 return data.results.map(n => ({
   title:n.title,
   url:n.url
 }));

 }catch(e){

 console.error("News fetch error:",e);
 return [];

 }

}