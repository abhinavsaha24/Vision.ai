export async function fetchNews(){

  try{

    const res = await fetch(
      "https://cryptopanic.com/api/developer/v2/posts/?auth_token=49641981207a1c63d81ea39a957c89ced5e5b805&currencies=BTC&public=true"
    );

    const data = await res.json();

    return data.results.slice(0,6).map(n => ({
      title: n.title,
      url: n.url
    }));

  }catch(err){

    console.error("News fetch error:",err);

    return [];

  }

}