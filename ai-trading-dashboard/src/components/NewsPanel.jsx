import React from 'react';
import { Newspaper } from 'lucide-react';

export default function NewsPanel({ newsData, loading }) {
  if (loading && !newsData) {
    return (
      <div className="panel flex flex-col items-center justify-center text-dark-muted h-full min-h-[300px]">
        <Newspaper className="w-8 h-8 mb-2 opacity-50" />
        <span className="text-xs font-mono">FETCHING NEWS...</span>
      </div>
    );
  }

  const articles = newsData?.articles || [];

  return (
    <div className="panel h-[420px] flex flex-col">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h2 className="text-sm font-bold text-dark-muted uppercase tracking-wider flex items-center space-x-2">
          <Newspaper className="w-4 h-4" />
          <span>Macro & Sentiment</span>
        </h2>
        <span className="text-xs bg-dark-bg px-2 py-1 rounded border border-dark-border text-dark-muted font-mono whitespace-nowrap">
          {articles.length} RECENT
        </span>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar pr-2 space-y-3">
        {articles.length === 0 ? (
          <div className="text-xs font-mono text-dark-muted italic p-4 text-center">No recent news found</div>
        ) : (
          articles.map((article, index) => {
            const timeAgo = Math.floor((new Date() - new Date(article.published_at)) / 1000 / 60);
            
            return (
              <a 
                key={index} 
                href={article.url} 
                target="_blank" 
                rel="noreferrer"
                className="block bg-dark-bg border border-dark-border p-3 rounded-lg hover:border-dark-muted transition-colors group"
              >
                <div className="flex justify-between items-start mb-1">
                  <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-trade-green bg-trade-green/10 px-1.5 py-0.5 rounded">
                    {article.domain || 'CRYPTO'}
                  </span>
                  <span className="text-[10px] font-mono text-dark-muted">
                    {timeAgo < 60 ? `${timeAgo}m ago` : `${Math.floor(timeAgo/60)}h ago`}
                  </span>
                </div>
                <h3 className="text-sm font-medium text-dark-text group-hover:text-white leading-snug line-clamp-2 mt-2">
                  {article.title}
                </h3>
              </a>
            );
          })
        )}
      </div>
    </div>
  );
}
