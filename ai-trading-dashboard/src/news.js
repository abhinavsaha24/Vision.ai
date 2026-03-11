export async function fetchNews(){

 const res = await fetch(
   "https://cryptopanic.com/api/v1/posts/?auth_token=YOUR_TOKEN&currencies=BTC"
 );

 const data = await res.json();

 return data.results.map(n=>({
  title:n.title,
  url:n.url
 }));

}