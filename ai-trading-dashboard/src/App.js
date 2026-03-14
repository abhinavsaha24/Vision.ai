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

export default function App() {
  const { get, post, loading } = useApi();
  const [market, setMarket] = useState('BTC/USDT');

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
  }, [get, market]);

  const handleRefreshPaper = async () => {
    try {
      const data = await get(`/paper-trading/status`);
      setPaperStatus(data);
    } catch(e) {}
  };

  return (
    <div className="min-h-screen bg-[#0F172A] text-[#F8FAFC] flex flex-col pt-2 pb-6 selection:bg-trade-green/30">
      
      <Header apiHealth={health} market={market} setMarket={setMarket} />

      <main className="flex-1 p-[20px] grid gap-[20px] items-start xl:grid-cols-[1.1fr_2fr_1.1fr]" style={{ gridTemplateRows: 'auto auto auto' }}>
        
        {/* LEFT COLUMN */}
        <div className="flex flex-col gap-[20px]">
          <LivePricePanel symbol={market} />
          <PortfolioAnalytics portfolioData={portfolio} loading={loading['get-/portfolio/performance']} />
          <StrategyTable strategiesData={strategies} loading={loading['get-/strategies/list']} />
        </div>

        {/* CENTER COLUMN */}
        <div className="flex flex-col gap-[20px]">
          <AiSignalPanel signalData={prediction} loading={loading['post-/model/predict']} />
          <TradingChart symbol={market} signalData={prediction} />
        </div>

        {/* RIGHT COLUMN */}
        <div className="flex flex-col gap-[20px]">
          <RegimePanel regimeData={regime} loading={loading[`get-/regime/current?symbol=${encodeURIComponent(market)}`]} />
          <RiskDashboard riskData={risk} loading={loading[`get-/risk/status?symbol=${encodeURIComponent(market)}`]} />
          <NewsPanel newsData={news} loading={loading['get-/news']} />
        </div>

        {/* BOTTOM ROW (Full Width, split in two on desktop) */}
        <div className="col-span-1 xl:col-span-3 grid grid-cols-1 lg:grid-cols-2 gap-[20px]">
          <PaperTradingPanel statusData={paperStatus} loading={loading['get-/paper-trading/status']} onRefresh={handleRefreshPaper} />
          <OrderHistory historyData={orders} loading={loading['get-/orders/history']} />
        </div>

      </main>
      
      <Footer />
    </div>
  );
}