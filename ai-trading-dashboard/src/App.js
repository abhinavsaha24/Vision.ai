import React, { useState, useEffect } from 'react';
import { useApi } from './hooks/useApi';

// Components
import Header from './components/Header';
import LivePricePanel from './components/LivePricePanel';
import AiSignalPanel from './components/AiSignalPanel';
import RegimePanel from './components/RegimePanel';
import RiskDashboard from './components/RiskDashboard';
import PortfolioAnalytics from './components/PortfolioAnalytics';
import StrategyTable from './components/StrategyTable';
import PaperTradingPanel from './components/PaperTradingPanel';
import NewsPanel from './components/NewsPanel';
import OrderHistory from './components/OrderHistory';
import TradingChart from './components/TradingChart';
import Footer from './components/Footer';
import AdvancedAnalyticsModal from './components/AdvancedAnalyticsModal';

export default function App() {
  const { get, post, loading } = useApi();
  const [market, setMarket] = useState('BTC/USDT');
  const [isAnalyticsOpen, setIsAnalyticsOpen] = useState(false);

  // Application State
  const [health, setHealth] = useState(null);
  const [prediction, setPrediction] = useState(null);
  const [risk, setRisk] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [strategies, setStrategies] = useState(null);
  const [paperStatus, setPaperStatus] = useState(null);
  const [news, setNews] = useState(null);
  const [orders, setOrders] = useState(null);
  const [regime, setRegime] = useState(null);

  // Initial Load & Polling
  useEffect(() => {
    let mounted = true;

    const fetchAllData = async () => {
      try {
        const start = Date.now();
        const healthRes = await get('/health');
        if (mounted) setHealth({ status: healthRes?.status || 'error', latency: Date.now() - start });

        // Ensure we handle URL encoding for the symbol parameter in GET requests
        const symQuery = `?symbol=${encodeURIComponent(market)}`;

        // Parallel fetching
        const [
          predData,
          riskData,
          portData,
          stratData,
          paperData,
          newsData,
          orderData,
          regimeData
        ] = await Promise.all([
          post(`/model/predict`, { symbol: market.replace('/', ''), horizon: 5 }), // The predictive API uses POST
          get(`/risk/status${symQuery}`),
          get(`/portfolio/performance`),
          get(`/strategies/list`),
          get(`/paper-trading/status`),
          get(`/news`),
          get(`/orders/history`),
          get(`/regime/current${symQuery}`),
        ]);

        if (mounted) {
          setPrediction(predData);
          setRisk(riskData);
          setPortfolio(portData);
          setStrategies(stratData);
          setPaperStatus(paperData);
          setNews(newsData);
          setOrders(orderData);
          setRegime(regimeData);
        }
      } catch (err) {
        if (mounted) setHealth(prev => ({ ...prev, status: 'error' }));
      }
    };

    fetchAllData();
    const interval = setInterval(fetchAllData, 15000); // Poll every 15s

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [get, post, market]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRefreshPaper = async () => {
    try {
      const data = await get(`/paper-trading/status`);
      setPaperStatus(data);
    } catch(e) {}
  };

  return (
    <div className="min-h-screen bg-[#0b1220] text-[#F8FAFC] flex flex-col pt-2 pb-6 selection:bg-trade-green/30">
      
      <Header 
        apiHealth={health} 
        market={market} 
        setMarket={setMarket} 
        onOpenAnalytics={() => setIsAnalyticsOpen(true)} 
      />

      <AdvancedAnalyticsModal 
        isOpen={isAnalyticsOpen} 
        onClose={() => setIsAnalyticsOpen(false)} 
      />

      <main className="flex-1 w-full max-w-[1920px] mx-auto p-4 grid grid-cols-1 lg:grid-cols-12 gap-4">
        
        {/* SIDEBAR (Left - 3 columns on large screens) */}
        <div className="lg:col-span-3 flex flex-col gap-4">
          <LivePricePanel symbol={market} />
          <StrategyTable strategiesData={strategies} loading={loading['get-/strategies/list']} />
          <PortfolioAnalytics portfolioData={portfolio} loading={loading['get-/portfolio/performance']} />
        </div>

        {/* MAIN CHART CENTER (6 columns on large screens) */}
        <div className="lg:col-span-6 flex flex-col gap-4 h-full">
          <AiSignalPanel signalData={prediction} loading={loading['post-/model/predict']} />
          <TradingChart symbol={market} signalData={prediction} />
        </div>

        {/* INFO PANELS RIGHT (3 columns on large screens) */}
        <div className="lg:col-span-3 flex flex-col gap-4">
          <RegimePanel regimeData={regime} loading={loading[`get-/regime/current?symbol=${encodeURIComponent(market)}`]} />
          <RiskDashboard riskData={risk} loading={loading[`get-/risk/status?symbol=${encodeURIComponent(market)}`]} />
          <NewsPanel newsData={news} loading={loading['get-/news']} />
        </div>

        {/* BOTTOM ROW: PAPER TRADING & EXECUTION FEED */}
        <div className="lg:col-span-12 grid grid-cols-1 lg:grid-cols-12 gap-4 mt-2 mb-4">
           {/* Paper trading takes up 2/3 of space at bottom */}
           <div className="lg:col-span-8">
             <PaperTradingPanel statusData={paperStatus} loading={loading['get-/paper-trading/status']} onRefresh={handleRefreshPaper} />
           </div>
           
           {/* Execution feed takes up 1/3 of space at bottom right */}
           <div className="lg:col-span-4 max-h-[400px]">
             <OrderHistory historyData={orders} loading={loading['get-/orders/history']} />
           </div>
        </div>
      </main>
      
      <Footer />
    </div>
  );
}