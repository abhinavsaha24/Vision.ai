import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Newspaper, Flame, TrendingDown, Clock } from "lucide-react";
import { apiService } from "@/services/api";
import { NewsArticle } from "@/types";

export function NewsFeed() {
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    async function fetchNews() {
      try {
        const data = await apiService.getNews(10);
        if (mounted) {
          setArticles(data?.articles || []);
          setLoading(false);
        }
      } catch (err) {
        if (mounted) setLoading(false);
      }
    }
    fetchNews();
    const interval = setInterval(fetchNews, 60000); // 1 minute
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return (
    <Card className="flex flex-col h-full bg-slate-900 border-slate-800">
      <CardHeader className="pb-3 border-b border-slate-800/50">
        <CardTitle className="text-sm font-medium text-slate-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Newspaper className="h-4 w-4 text-indigo-400" />
            Market News
          </div>
          <span className="text-[10px] bg-slate-800 px-2 py-0.5 rounded text-slate-400 font-mono tracking-widest uppercase">
            Live Feed
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 p-0 overflow-hidden">
        <div className="h-full overflow-y-auto custom-scrollbar p-4 flex flex-col gap-4">
          {loading && articles.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-2">
              <Clock className="h-5 w-5 animate-pulse opacity-50" />
              <span className="text-xs font-mono uppercase tracking-widest">Fetching news...</span>
            </div>
          ) : articles.length === 0 ? (
            <div className="text-center text-slate-500 text-xs font-mono py-6">
              No recent news items.
            </div>
          ) : (
            articles.map((article, i) => {
              const text = article.title || 'Untitled Update';
              const textLower = text.toLowerCase();
              let isBullish = textLower.includes('surge') || textLower.includes('up') || textLower.includes('bull') || textLower.includes('high') || textLower.includes('breakout');
              let isBearish = textLower.includes('drop') || textLower.includes('down') || textLower.includes('bear') || textLower.includes('crash') || textLower.includes('low');
              
              return (
                <div key={i} className="group flex flex-col gap-1.5 pb-4 border-b border-dark-border/30 last:border-0 last:pb-0">
                  <a 
                    href={article.url || '#'} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="text-xs font-medium text-slate-200 leading-snug group-hover:text-indigo-400 transition-colors"
                  >
                    {isBullish && <Flame className="h-3 w-3 inline text-orange-500 mr-1.5 mb-0.5" />}
                    {isBearish && <TrendingDown className="h-3 w-3 inline text-rose-500 mr-1.5 mb-0.5" />}
                    {!isBullish && !isBearish && <span className="text-indigo-500 mr-1.5">•</span>}
                    {text}
                  </a>
                  <div className="flex justify-between items-center mt-1">
                    <span className="text-[9px] uppercase tracking-wider text-slate-500 font-mono">
                      {article.source || 'Market Update'}
                    </span>
                    {article.published_at && (
                      <span className="text-[9px] text-slate-500">
                        {new Date(article.published_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </CardContent>
    </Card>
  );
}
