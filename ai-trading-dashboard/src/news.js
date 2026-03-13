/**
 * news.js — Fetch news from backend (CORS-safe)
 *
 * FIX ERROR 4: All external API calls go through FastAPI backend.
 * Frontend never calls CryptoPanic/Finnhub/NewsAPI directly.
 * No API tokens exposed in frontend code.
 */

const API = process.env.REACT_APP_API || "http://localhost:10000";

export async function fetchNews() {
  try {
    const res = await fetch(`${API}/news`, { timeout: 10000 });

    if (!res.ok) {
      console.warn("News API returned", res.status);
      return [];
    }

    const data = await res.json();

    return (data.articles || data.results || data || []).slice(0, 20).map((n) => ({
      title: n.title || n.headline || "",
      url: n.url || n.link || "#",
      source: n.source || "Unknown",
      sentiment: n.sentiment || null,
      timestamp: n.timestamp || n.published_at || null,
    }));
  } catch (e) {
    console.error("News fetch error:", e);
    return [];
  }
}