"use client";

import { NewsFeed } from "@/components/dashboard/NewsFeed";

export default function NewsPage() {
  return (
    <div className="flex flex-col gap-6 max-w-5xl mx-auto h-full">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight text-white">Market News</h1>
        <p className="text-slate-400">Real-time financial news and AI-driven sentiment analysis.</p>
      </div>

      <div className="flex-1 min-h-[600px]">
        <NewsFeed />
      </div>
    </div>
  );
}
