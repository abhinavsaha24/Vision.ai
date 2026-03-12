export async function fetchNews(){

 try{

 const res = await fetch(
   "https://api.allorigins.win/raw?url=" +
   encodeURIComponent(
     "https://cryptopanic.com/api/developer/v2/posts/?auth_token=49641981207a1c63d81ea39a957c89ced5e5b805&currencies=BTC&public=true"
   )
 );

 const data = await res.json();

 return data.results.slice(0,5).map(n => ({
   title:n.title,
   url:n.url
 }));

 }catch(e){

 console.error("News fetch error:",e);
 return [];

 }

}